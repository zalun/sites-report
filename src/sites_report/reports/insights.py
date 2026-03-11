"""AI-powered highlights for analytics reports using Claude CLI."""

from __future__ import annotations

import logging
import subprocess

from sites_report.config import Schedule

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30


def generate_highlights(
    project_name: str,
    schedule: Schedule,
    ga4_metrics: list[dict] | None,
    gsc_metrics: list[dict] | None,
    pages: list[dict] | None,
    queries: list[dict] | None,
) -> str | None:
    """Generate AI-powered highlights from analytics data.

    Calls ``claude -p`` via subprocess. Returns the generated text,
    or ``None`` when data is insufficient or the CLI is unavailable.
    """
    if not _has_meaningful_data(ga4_metrics, gsc_metrics, pages, queries):
        return None

    try:
        prompt = _build_prompt(
            project_name, schedule, ga4_metrics, gsc_metrics, pages, queries
        )
    except (KeyError, TypeError) as exc:
        logger.warning("Failed to build AI highlights prompt: %s", exc)
        return None

    try:
        result = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError:
        logger.warning("claude CLI OS error — skipping AI highlights", exc_info=True)
        return None
    except subprocess.TimeoutExpired:
        logger.warning(
            "claude CLI timed out after %ds — skipping AI highlights", _TIMEOUT_SECONDS
        )
        return None
    except subprocess.SubprocessError as exc:
        logger.warning(
            "claude CLI subprocess error (%s) — skipping AI highlights",
            type(exc).__name__,
            exc_info=True,
        )
        return None

    if result.returncode != 0:
        logger.warning(
            "claude CLI exited with code %d — skipping AI highlights\nstderr: %s",
            result.returncode,
            result.stderr.strip()[:500] or "(empty)",
        )
        return None

    output = result.stdout.strip()
    if not output:
        logger.warning("claude CLI returned empty output — skipping AI highlights")
        return None
    return output


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
        "Be specific with numbers.",
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
            lines.append(
                f"- \"{q['query']}\": {q['clicks']} clicks, "
                f"{q['impressions']} impressions, "
                f"{q['ctr']} CTR, position {q['position']}"
            )
        lines.append("")

    lines.append("Respond with bullet points only, no headers or preamble.")
    return "\n".join(lines)


def _format_metrics_table(metrics: list[dict]) -> str:
    """Format a list of metric dicts into readable lines."""
    lines = []
    for m in metrics:
        lines.append(
            f"- {m['label']}: {m['current']} (previous: {m['previous']}, "
            f"change: {m['change']}, direction: {m['direction']})"
        )
    return "\n".join(lines)
