"""Report builder — orchestrates data queries, comparisons, charts, and HTML rendering."""

from __future__ import annotations

import base64
import calendar
import datetime
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import jinja2

from sites_report.config import ProjectConfig, Schedule, SubscriptionConfig
from sites_report.db import get_ga_daily, get_gsc_daily, get_top_pages, get_top_queries
from sites_report.reports import charts

logger = logging.getLogger(__name__)


# ── Public dataclasses ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Report:
    subject: str
    html: str

    def __post_init__(self) -> None:
        if not self.subject:
            msg = "subject must not be empty"
            raise ValueError(msg)
        if not self.html:
            msg = "html must not be empty"
            raise ValueError(msg)


# ── Internal dataclasses ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _DateRanges:
    current_start: datetime.date
    current_end: datetime.date
    previous_start: datetime.date
    previous_end: datetime.date
    trend_start: datetime.date
    trend_end: datetime.date

    def __post_init__(self) -> None:
        if self.current_start > self.current_end:
            msg = "current_start must be <= current_end"
            raise ValueError(msg)
        if self.previous_start > self.previous_end:
            msg = "previous_start must be <= previous_end"
            raise ValueError(msg)
        if self.trend_start > self.trend_end:
            msg = "trend_start must be <= trend_end"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _MetricDef:
    key: str
    label: str
    aggregate: Literal["sum", "avg"]
    fmt: Literal["integer", "percentage", "position"]
    higher_is_better: bool


# ── Metric definitions ────────────────────────────────────────────

_GA4_METRICS = (
    _MetricDef("sessions", "Sessions", "sum", "integer", higher_is_better=True),
    _MetricDef("users", "Users", "sum", "integer", higher_is_better=True),
    _MetricDef("new_users", "New Users", "sum", "integer", higher_is_better=True),
    _MetricDef("pageviews", "Pageviews", "sum", "integer", higher_is_better=True),
    _MetricDef("bounce_rate", "Bounce Rate", "avg", "percentage", higher_is_better=False),
)

_GSC_METRICS = (
    _MetricDef("clicks", "Clicks", "sum", "integer", higher_is_better=True),
    _MetricDef("impressions", "Impressions", "sum", "integer", higher_is_better=True),
    _MetricDef("ctr", "CTR", "avg", "percentage", higher_is_better=True),
    _MetricDef("avg_position", "Avg Position", "avg", "position", higher_is_better=False),
)

# ── Template environment (cached) ────────────────────────────────

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)


# ── Private helpers ───────────────────────────────────────────────


def _compute_date_ranges(schedule: Schedule, report_date: datetime.date) -> _DateRanges:
    """Compute current, previous, and trend date ranges for the given schedule."""
    if schedule == Schedule.DAILY:
        current_start = current_end = report_date
        previous_start = previous_end = report_date - datetime.timedelta(days=7)
        trend_start = report_date - datetime.timedelta(days=29)
        trend_end = report_date
    elif schedule == Schedule.WEEKLY:
        # Monday of report_date's week
        current_start = report_date - datetime.timedelta(days=report_date.weekday())
        current_end = current_start + datetime.timedelta(days=6)
        previous_start = current_start - datetime.timedelta(days=7)
        previous_end = current_start - datetime.timedelta(days=1)
        trend_start = current_end - datetime.timedelta(days=27)
        trend_end = current_end
    elif schedule == Schedule.MONTHLY:
        current_start = report_date.replace(day=1)
        last_day = calendar.monthrange(report_date.year, report_date.month)[1]
        current_end = report_date.replace(day=last_day)
        prev_month_end = current_start - datetime.timedelta(days=1)
        previous_start = prev_month_end.replace(day=1)
        previous_end = prev_month_end
        trend_start = current_end - datetime.timedelta(days=179)
        trend_end = current_end
    else:
        msg = f"Unknown schedule: {schedule!r}"
        raise ValueError(msg)
    return _DateRanges(
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        trend_start=trend_start,
        trend_end=trend_end,
    )


def _aggregate(
    data: list[dict], key: str, method: Literal["sum", "avg"]
) -> float:
    """Aggregate a metric across rows. Filters None values. Returns 0.0 for empty."""
    values = [v for row in data if (v := row.get(key)) is not None]
    if not values and data:
        logger.warning(
            "No rows contained key '%s' out of %d rows — returning 0.0",
            key,
            len(data),
        )
    if not values:
        return 0.0
    try:
        if method == "sum":
            return float(sum(values))
        if method == "avg":
            return sum(values) / len(values)
    except TypeError as exc:
        msg = f"Non-numeric values for metric '{key}': {values[:3]!r}"
        raise TypeError(msg) from exc
    msg = f"Unknown aggregation method: {method!r}"
    raise ValueError(msg)


def _format_value(
    value: float, fmt: Literal["integer", "percentage", "position"]
) -> str:
    """Format a numeric value for display."""
    if math.isnan(value) or math.isinf(value):
        logger.warning("Cannot format non-finite value %r as '%s'", value, fmt)
        return "N/A"
    if fmt == "integer":
        return f"{round(value):,}"
    if fmt == "percentage":
        return f"{value * 100:.1f}%"
    if fmt == "position":
        return f"{value:.1f}"
    msg = f"Unknown format type: {fmt!r}"
    raise ValueError(msg)


def _format_change(pct_change: float | None) -> str:
    """Format percentage change for display."""
    if pct_change is None:
        return "N/A"
    if pct_change > 0:
        return f"+{pct_change:.1f}%"
    return f"{pct_change:.1f}%"


def _compare_metric(
    current_data: list[dict],
    previous_data: list[dict],
    metric: _MetricDef,
) -> dict:
    """Build a comparison dict for a single metric."""
    cur = _aggregate(current_data, metric.key, metric.aggregate)
    prev = _aggregate(previous_data, metric.key, metric.aggregate)

    pct_change = None if prev == 0.0 else ((cur - prev) / prev) * 100

    if pct_change is None or pct_change == 0.0:
        direction = "neutral"
    elif pct_change > 0:
        direction = "positive" if metric.higher_is_better else "negative"
    else:
        direction = "negative" if metric.higher_is_better else "positive"

    return {
        "label": metric.label,
        "current": _format_value(cur, metric.fmt),
        "previous": _format_value(prev, metric.fmt),
        "change": _format_change(pct_change),
        "direction": direction,
    }


def _encode_chart(png_bytes: bytes | None) -> str | None:
    """Base64-encode PNG bytes for embedding in HTML."""
    if png_bytes is None:
        return None
    return base64.b64encode(png_bytes).decode("ascii")


def _build_charts(
    db_path: Path,
    slug: str,
    ranges: _DateRanges,
    *,
    has_ga4: bool,
    has_gsc: bool,
) -> dict:
    """Generate all charts and return base64-encoded PNGs."""
    trend_start = ranges.trend_start.isoformat()
    trend_end = ranges.trend_end.isoformat()
    current_start = ranges.current_start.isoformat()
    current_end = ranges.current_end.isoformat()

    result: dict[str, str | None] = {
        "sessions_users": None,
        "gsc_trend": None,
        "top_queries": None,
        "top_pages": None,
    }

    if has_ga4:
        ga_trend = get_ga_daily(db_path, slug, trend_start, trend_end)
        chart_bytes = charts.sessions_users_trend(ga_trend)
        if chart_bytes is None and ga_trend:
            logger.warning(
                "Chart 'sessions_users' returned None despite %d data rows for '%s'",
                len(ga_trend),
                slug,
            )
        result["sessions_users"] = _encode_chart(chart_bytes)

        pages = get_top_pages(db_path, slug, current_start, current_end)
        chart_bytes = charts.top_pages(pages)
        if chart_bytes is None and pages:
            logger.warning(
                "Chart 'top_pages' returned None despite %d data rows for '%s'",
                len(pages),
                slug,
            )
        result["top_pages"] = _encode_chart(chart_bytes)

    if has_gsc:
        gsc_trend = get_gsc_daily(db_path, slug, trend_start, trend_end)
        chart_bytes = charts.gsc_clicks_impressions_trend(gsc_trend)
        if chart_bytes is None and gsc_trend:
            logger.warning(
                "Chart 'gsc_trend' returned None despite %d data rows for '%s'",
                len(gsc_trend),
                slug,
            )
        result["gsc_trend"] = _encode_chart(chart_bytes)

        queries = get_top_queries(db_path, slug, current_start, current_end)
        chart_bytes = charts.top_search_queries(queries)
        if chart_bytes is None and queries:
            logger.warning(
                "Chart 'top_queries' returned None despite %d data rows for '%s'",
                len(queries),
                slug,
            )
        result["top_queries"] = _encode_chart(chart_bytes)

    return result


def _build_subject(schedule: Schedule, report_date: datetime.date) -> str:
    """Build the email subject line."""
    label = schedule.value.capitalize()
    if schedule == Schedule.DAILY:
        date_str = report_date.isoformat()
    elif schedule == Schedule.WEEKLY:
        monday = report_date - datetime.timedelta(days=report_date.weekday())
        sunday = monday + datetime.timedelta(days=6)
        date_str = f"{monday.isoformat()} - {sunday.isoformat()}"
    elif schedule == Schedule.MONTHLY:
        date_str = report_date.strftime("%Y-%m")
    else:
        msg = f"Unknown schedule: {schedule!r}"
        raise ValueError(msg)
    return f"Sites Report ({label}): {date_str}"


def _build_period_label(schedule: Schedule, ranges: _DateRanges) -> str:
    """Human-readable period label."""
    if schedule == Schedule.DAILY:
        return ranges.current_start.strftime("%b %d, %Y")
    cur_start = ranges.current_start.strftime("%b %d")
    cur_end = ranges.current_end.strftime("%b %d, %Y")
    return f"{cur_start} - {cur_end}"


def _build_comparison_labels(schedule: Schedule, ranges: _DateRanges) -> dict:
    """Labels for current and previous period columns."""
    if schedule == Schedule.DAILY:
        return {
            "current": ranges.current_start.strftime("%b %d"),
            "previous": ranges.previous_start.strftime("%b %d"),
        }
    cur_s = ranges.current_start.strftime("%b %d")
    cur_e = ranges.current_end.strftime("%b %d")
    prev_s = ranges.previous_start.strftime("%b %d")
    prev_e = ranges.previous_end.strftime("%b %d")
    return {
        "current": f"{cur_s} - {cur_e}",
        "previous": f"{prev_s} - {prev_e}",
    }


def _build_project_context(
    db_path: Path,
    project: ProjectConfig,
    schedule: Schedule,
    ranges: _DateRanges,
) -> dict:
    """Build the full template context for a single project."""
    current_start = ranges.current_start.isoformat()
    current_end = ranges.current_end.isoformat()
    previous_start = ranges.previous_start.isoformat()
    previous_end = ranges.previous_end.isoformat()

    # GA4
    ga4_ctx = None
    has_ga4 = project.ga4_property_id is not None
    if has_ga4:
        cur_ga = get_ga_daily(db_path, project.slug, current_start, current_end)
        prev_ga = get_ga_daily(db_path, project.slug, previous_start, previous_end)
        if cur_ga or prev_ga:
            ga4_ctx = {
                "metrics": [_compare_metric(cur_ga, prev_ga, m) for m in _GA4_METRICS],
            }
        else:
            logger.info(
                "No GA4 data for project '%s' in range %s to %s",
                project.slug,
                current_start,
                current_end,
            )

    # GSC
    gsc_ctx = None
    has_gsc = project.gsc_site_url is not None
    if has_gsc:
        cur_gsc = get_gsc_daily(db_path, project.slug, current_start, current_end)
        prev_gsc = get_gsc_daily(db_path, project.slug, previous_start, previous_end)
        if cur_gsc or prev_gsc:
            gsc_ctx = {
                "metrics": [_compare_metric(cur_gsc, prev_gsc, m) for m in _GSC_METRICS],
            }
        else:
            logger.info(
                "No GSC data for project '%s' in range %s to %s",
                project.slug,
                current_start,
                current_end,
            )

    chart_data = _build_charts(
        db_path, project.slug, ranges, has_ga4=has_ga4, has_gsc=has_gsc
    )

    return {
        "name": project.name,
        "period": _build_period_label(schedule, ranges),
        "comparison_label": _build_comparison_labels(schedule, ranges),
        "ga4": ga4_ctx,
        "gsc": gsc_ctx,
        "ai_highlights": None,
        "charts": chart_data,
    }


def _render_template(context: dict) -> str:
    """Render the report HTML template."""
    try:
        template = _JINJA_ENV.get_template("report.html")
        return template.render(**context)
    except jinja2.TemplateNotFound as exc:
        logger.error(
            "Report template not found: %s (searched in %s)",
            exc.name,
            _TEMPLATE_DIR,
        )
        raise
    except jinja2.TemplateError as exc:
        logger.error("Failed to render report template: %s", exc)
        raise


# ── Public API ────────────────────────────────────────────────────


def build_report(
    db_path: Path,
    subscription: SubscriptionConfig,
    projects: tuple[ProjectConfig, ...],
    schedule: Schedule,
    report_date: datetime.date,
) -> Report:
    """Build a complete HTML report for a subscription.

    Queries data from SQLite, computes period-over-period comparisons,
    generates charts, and renders the final HTML email.
    """
    ranges = _compute_date_ranges(schedule, report_date)
    subject = _build_subject(schedule, report_date)

    project_contexts = []
    for project in projects:
        if project.slug in subscription.projects:
            logger.debug("Building context for project '%s'", project.slug)
            ctx = _build_project_context(db_path, project, schedule, ranges)
            project_contexts.append(ctx)

    if not project_contexts:
        msg = (
            f"No matching projects for subscription '{subscription.recipient}': "
            f"requested {subscription.projects}, "
            f"available {[p.slug for p in projects]}"
        )
        raise ValueError(msg)

    template_context = {
        "subject": subject,
        "schedule": schedule.value.capitalize(),
        "generated_at": datetime.datetime.now(tz=datetime.UTC).strftime(
            "%Y-%m-%d %H:%M UTC"
        ),
        "projects": project_contexts,
    }

    html = _render_template(template_context)
    return Report(subject=subject, html=html)
