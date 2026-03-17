"""AI-powered highlights for analytics reports using Claude CLI."""

from __future__ import annotations

import logging
import subprocess

from sites_report.config import Schedule

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30

_SCHEDULE_GUIDANCE = {
    Schedule.DAILY: "Compare against the same day last week.",
    Schedule.WEEKLY: "Look for week-over-week trends.",
    Schedule.MONTHLY: "Focus on month-over-month shifts and long-term trends.",
}
assert set(_SCHEDULE_GUIDANCE) == set(Schedule), (
    f"_SCHEDULE_GUIDANCE missing variants: {set(Schedule) - set(_SCHEDULE_GUIDANCE)}"
)


def generate_highlights(
    project_name: str,
    schedule: Schedule,
    ga4_metrics: list[dict] | None,
    gsc_metrics: list[dict] | None,
    pages: list[dict] | None,
    queries: list[dict] | None,
    *,
    ai_model: str | None = None,
) -> str | None:
    """Generate AI-powered highlights from analytics data.

    Calls ``claude -p`` via subprocess. Returns the generated text,
    or ``None`` when data is insufficient or the CLI is unavailable.
    """
    if not _has_meaningful_data(ga4_metrics, gsc_metrics, pages, queries):
        logger.debug("Skipping AI highlights for '%s': no meaningful data", project_name)
        return None

    try:
        prompt = _build_prompt(project_name, schedule, ga4_metrics, gsc_metrics, pages, queries)
    except (KeyError, TypeError) as exc:
        logger.warning("Failed to build AI highlights prompt for '%s': %s", project_name, exc)
        return None

    cmd = ["claude", "-p"]
    if ai_model:
        cmd.extend(["--model", ai_model])

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError:
        logger.warning(
            "claude CLI OS error for '%s' — skipping AI highlights",
            project_name,
            exc_info=True,
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning(
            "claude CLI timed out after %ds for '%s' — skipping AI highlights",
            _TIMEOUT_SECONDS,
            project_name,
        )
        return None
    except subprocess.SubprocessError as exc:
        logger.warning(
            "claude CLI subprocess error (%s) for '%s' — skipping AI highlights",
            type(exc).__name__,
            project_name,
            exc_info=True,
        )
        return None
    except UnicodeDecodeError:
        logger.warning(
            "claude CLI produced undecodable output for '%s' — skipping AI highlights",
            project_name,
            exc_info=True,
        )
        return None

    if result.returncode != 0:
        logger.warning(
            "claude CLI exited with code %d for '%s' — skipping AI highlights\nstderr: %s",
            result.returncode,
            project_name,
            _truncate_stderr(result.stderr),
        )
        return None

    output = result.stdout.strip()
    if not output:
        logger.warning(
            "claude CLI returned empty output for '%s' — skipping AI highlights",
            project_name,
        )
        return None
    return output


_STDERR_LIMIT = 500


def _truncate_stderr(stderr: str) -> str:
    """Truncate stderr for logging, indicating when content was cut."""
    text = stderr.strip()
    if not text:
        return "(empty)"
    if len(text) <= _STDERR_LIMIT:
        return text
    return f"{text[:_STDERR_LIMIT]} ... ({len(text) - _STDERR_LIMIT} more chars)"


def _has_meaningful_data(
    ga4_metrics: list[dict] | None,
    gsc_metrics: list[dict] | None,
    pages: list[dict] | None,
    queries: list[dict] | None,
) -> bool:
    """Return True if there is any non-empty data to analyze."""
    return bool(ga4_metrics or gsc_metrics or pages or queries)


def _build_prompt(
    project_name: str,
    schedule: Schedule,
    ga4_metrics: list[dict] | None,
    gsc_metrics: list[dict] | None,
    pages: list[dict] | None,
    queries: list[dict] | None,
) -> str:
    """Format analytics data into a structured prompt for Claude."""
    lines = [
        f"You are an analytics assistant. Analyze the following data for {project_name} "
        f"({schedule} report) and provide 2-4 concise highlights. "
        "Focus on: significant changes, unusual patterns, notable trends. "
        "Be specific with numbers. "
        f"{_SCHEDULE_GUIDANCE[schedule]}",
        "",
    ]

    if ga4_metrics:
        lines.append("## GA4 Metrics")
        lines.append(_format_metrics_table(ga4_metrics))
        lines.append("")

    if gsc_metrics:
        lines.append("## GSC Metrics")
        lines.append(_format_metrics_table(gsc_metrics))
        lines.append("")

    if pages:
        lines.append("## Top Pages")
        for p in pages:
            lines.append(
                f"- {p['page_path']}: {p['pageviews']} pageviews, "
                f"{p['sessions']} sessions, {p['avg_time_on_page']}s avg time"
            )
        lines.append("")

    if queries:
        lines.append("## Top Search Queries")
        for q in queries:
            ctr = f"{q['ctr']:.1%}" if q.get("ctr") is not None else "N/A"
            pos = f"{q['position']:.1f}" if q.get("position") is not None else "N/A"
            lines.append(
                f'- "{q["query"]}": {q["clicks"]} clicks, '
                f"{q['impressions']} impressions, "
                f"{ctr} CTR, position {pos}"
            )
        lines.append("")

    lines.append(
        'Respond with 2-4 bullet points starting with "- ". No headers, no preamble, no sign-off.'
    )
    return "\n".join(lines)


def _format_metrics_table(metrics: list[dict]) -> str:
    """Format a list of metric dicts into readable lines."""
    lines = []
    for m in metrics:
        lines.append(
            f"- {m['label']}: {m['current']} (previous: {m['previous']}, change: {m['change']})"
        )
    return "\n".join(lines)
