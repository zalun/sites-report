"""Tests for the report builder module."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from unittest import mock

import pytest

from sites_report.config import ProjectConfig, Schedule, SubscriptionConfig
from sites_report.reports.builder import (
    _GA4_METRICS,
    Report,
    _aggregate,
    _all_zeros,
    _build_comparison_labels,
    _build_period_label,
    _build_subject,
    _compare_metric,
    _compute_date_ranges,
    _encode_chart,
    _format_change,
    _format_value,
    _markdown_to_html,
    _MetricDef,
    build_report,
)

_P = "sites_report.reports.builder"


# ── Date ranges ───────────────────────────────────────────────────


def test_date_ranges_daily_current():
    r = _compute_date_ranges(Schedule.DAILY, datetime.date(2025, 3, 10))
    assert r.current_start == datetime.date(2025, 3, 10)
    assert r.current_end == datetime.date(2025, 3, 10)


def test_date_ranges_daily_previous():
    r = _compute_date_ranges(Schedule.DAILY, datetime.date(2025, 3, 10))
    assert r.previous_start == datetime.date(2025, 3, 3)
    assert r.previous_end == datetime.date(2025, 3, 3)


def test_date_ranges_daily_trend():
    r = _compute_date_ranges(Schedule.DAILY, datetime.date(2025, 3, 10))
    assert r.trend_start == datetime.date(2025, 2, 9)
    assert r.trend_end == datetime.date(2025, 3, 10)


def test_date_ranges_weekly_current():
    # 2025-03-12 is a Wednesday → week starts Mon 03-10
    r = _compute_date_ranges(Schedule.WEEKLY, datetime.date(2025, 3, 12))
    assert r.current_start == datetime.date(2025, 3, 10)
    assert r.current_end == datetime.date(2025, 3, 16)


def test_date_ranges_weekly_previous():
    r = _compute_date_ranges(Schedule.WEEKLY, datetime.date(2025, 3, 12))
    assert r.previous_start == datetime.date(2025, 3, 3)
    assert r.previous_end == datetime.date(2025, 3, 9)


def test_date_ranges_monthly_current():
    r = _compute_date_ranges(Schedule.MONTHLY, datetime.date(2025, 3, 15))
    assert r.current_start == datetime.date(2025, 3, 1)
    assert r.current_end == datetime.date(2025, 3, 31)


def test_date_ranges_monthly_previous():
    r = _compute_date_ranges(Schedule.MONTHLY, datetime.date(2025, 3, 15))
    assert r.previous_start == datetime.date(2025, 2, 1)
    assert r.previous_end == datetime.date(2025, 2, 28)


# ── Aggregation ───────────────────────────────────────────────────


def test_aggregate_sum():
    data = [{"sessions": 100}, {"sessions": 200}]
    assert _aggregate(data, "sessions", "sum") == 300.0


def test_aggregate_avg():
    data = [{"bounce_rate": 0.4}, {"bounce_rate": 0.6}]
    assert _aggregate(data, "bounce_rate", "avg") == pytest.approx(0.5)


def test_aggregate_skip_none():
    data = [{"sessions": 100}, {"sessions": None}, {"sessions": 200}]
    assert _aggregate(data, "sessions", "sum") == 300.0


def test_aggregate_empty_returns_zero():
    assert _aggregate([], "sessions", "sum") == 0.0


def test_aggregate_unknown_method_raises():
    data = [{"x": 1}]
    with pytest.raises(ValueError, match="Unknown aggregation method"):
        _aggregate(data, "x", "median")  # type: ignore[arg-type]


def test_aggregate_non_numeric_raises():
    data = [{"x": "not_a_number"}]
    with pytest.raises(TypeError, match="Non-numeric values"):
        _aggregate(data, "x", "sum")


# ── Formatting ────────────────────────────────────────────────────


def test_format_value_integer_with_commas():
    assert _format_value(1234.0, "integer") == "1,234"


def test_format_value_percentage():
    assert _format_value(0.452, "percentage") == "45.2%"


def test_format_value_position():
    assert _format_value(15.23, "position") == "15.2"


def test_format_value_unknown_raises():
    with pytest.raises(ValueError, match="Unknown format type"):
        _format_value(1.0, "duration")  # type: ignore[arg-type]


def test_format_value_nan_returns_na():
    assert _format_value(float("nan"), "integer") == "N/A"


def test_format_value_inf_returns_na():
    assert _format_value(float("inf"), "percentage") == "N/A"


def test_format_change_positive():
    assert _format_change(12.2) == "+12.2%"


def test_format_change_negative():
    assert _format_change(-5.0) == "-5.0%"


def test_format_change_zero():
    assert _format_change(0.0) == "0.0%"


def test_format_change_na():
    assert _format_change(None) == "N/A"


def test_format_change_nan():
    assert _format_change(float("nan")) == "N/A"


def test_format_change_inf():
    assert _format_change(float("inf")) == "N/A"


# ── Comparison ────────────────────────────────────────────────────


def test_compare_metric_increase_higher_is_better():
    metric = _MetricDef("sessions", "Sessions", "sum", "integer", higher_is_better=True)
    cur = [{"sessions": 200}]
    prev = [{"sessions": 100}]
    result = _compare_metric(cur, prev, metric)
    assert result["direction"] == "positive"
    assert result["change"] == "+100.0%"


def test_compare_metric_increase_higher_is_bad():
    metric = _MetricDef(
        "bounce_rate",
        "Bounce Rate",
        "avg",
        "percentage",
        higher_is_better=False,
    )
    cur = [{"bounce_rate": 0.6}]
    prev = [{"bounce_rate": 0.4}]
    result = _compare_metric(cur, prev, metric)
    assert result["direction"] == "negative"


def test_compare_metric_both_zero():
    metric = _MetricDef("sessions", "Sessions", "sum", "integer", higher_is_better=True)
    result = _compare_metric([], [], metric)
    assert result["direction"] == "neutral"
    assert result["change"] == "N/A"


def test_compare_metric_previous_zero():
    metric = _MetricDef("sessions", "Sessions", "sum", "integer", higher_is_better=True)
    cur = [{"sessions": 100}]
    result = _compare_metric(cur, [], metric)
    assert result["change"] == "N/A"
    assert result["direction"] == "neutral"


# ── Subject ───────────────────────────────────────────────────────


def test_build_subject_daily():
    s = _build_subject(Schedule.DAILY, datetime.date(2025, 3, 10))
    assert s == "Sites Report (Daily): 2025-03-10"


def test_build_subject_weekly():
    s = _build_subject(Schedule.WEEKLY, datetime.date(2025, 3, 12))
    assert "Weekly" in s
    assert "2025-03-10" in s  # Monday
    assert "2025-03-16" in s  # Sunday


def test_build_subject_monthly():
    s = _build_subject(Schedule.MONTHLY, datetime.date(2025, 3, 15))
    assert s == "Sites Report (Monthly): 2025-03"


# ── Encode chart ──────────────────────────────────────────────────


def test_encode_chart_encodes_bytes():
    result = _encode_chart(b"\x89PNG\r\n")
    assert isinstance(result, str)
    assert result


def test_encode_chart_none_input():
    assert _encode_chart(None) is None


# ── Period and comparison labels ──────────────────────────────────


def test_build_period_label_daily():
    ranges = _compute_date_ranges(Schedule.DAILY, datetime.date(2025, 3, 10))
    label = _build_period_label(Schedule.DAILY, ranges)
    assert "Mar 10, 2025" in label


def test_build_period_label_weekly():
    ranges = _compute_date_ranges(Schedule.WEEKLY, datetime.date(2025, 3, 12))
    label = _build_period_label(Schedule.WEEKLY, ranges)
    assert " - " in label


def test_build_comparison_labels_daily():
    ranges = _compute_date_ranges(Schedule.DAILY, datetime.date(2025, 3, 10))
    labels = _build_comparison_labels(Schedule.DAILY, ranges)
    assert labels["current"] == "Mar 10"
    assert labels["previous"] == "Mar 03"


def test_build_comparison_labels_weekly():
    ranges = _compute_date_ranges(Schedule.WEEKLY, datetime.date(2025, 3, 12))
    labels = _build_comparison_labels(Schedule.WEEKLY, ranges)
    assert " - " in labels["current"]
    assert " - " in labels["previous"]


# ── Report dataclass validation ───────────────────────────────────


def test_report_rejects_empty_subject():
    with pytest.raises(ValueError, match="subject"):
        Report(subject="", html="<html></html>")


def test_report_rejects_empty_html():
    with pytest.raises(ValueError, match="html"):
        Report(subject="Test", html="")


# ── Integration tests (mocked DB + charts) ────────────────────────


def _make_ga4_rows(date: str = "2025-03-10") -> list[dict]:
    return [
        {
            "date": date,
            "sessions": 150,
            "users": 120,
            "new_users": 80,
            "pageviews": 450,
            "avg_session_duration": 125.5,
            "bounce_rate": 0.42,
            "conversions": 5,
        },
    ]


def _make_gsc_rows(date: str = "2025-03-10") -> list[dict]:
    return [
        {
            "date": date,
            "clicks": 85,
            "impressions": 2400,
            "ctr": 0.035,
            "avg_position": 14.2,
        },
    ]


def _png_stub() -> bytes:
    return b"\x89PNG\r\nfake"


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_returns_report_dataclass(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert isinstance(report, Report)
    assert report.subject
    assert report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_html_contains_project_name(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "My Site" in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
def test_build_report_ga4_none_when_no_property_id(
    _m_gsc,
    _m_queries,
    _m_gt,
    _m_tq,
    _m_hi,
    sample_subscription,
):
    project = ProjectConfig(name="GSC Only", slug="my-site", gsc_site_url="https://example.com")
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (project,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "Google Analytics" not in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_gsc_none_when_no_site_url(
    _m_ga,
    _m_pages,
    _m_su,
    _m_tp,
    _m_hi,
    sample_subscription,
):
    project = ProjectConfig(name="GA4 Only", slug="my-site", ga4_property_id="properties/123")
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (project,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "Search Console" not in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=None)
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=None)
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_ga_daily", return_value=[])
def test_build_report_ga4_none_when_no_data(
    _m_ga,
    _m_pages,
    _m_su,
    _m_tp,
    _m_hi,
    sample_subscription,
):
    project = ProjectConfig(name="Empty GA4", slug="my-site", ga4_property_id="properties/123")
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (project,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "Google Analytics" not in report.html


# ── All-zeros / no-movement ──────────────────────────────────────


def _make_zero_ga4_rows(date: str = "2025-03-10") -> list[dict]:
    return [
        {
            "date": date,
            "sessions": 0,
            "users": 0,
            "new_users": 0,
            "pageviews": 0,
            "bounce_rate": 0,
        },
    ]


def _make_zero_gsc_rows(date: str = "2025-03-10") -> list[dict]:
    return [{"date": date, "clicks": 0, "impressions": 0, "ctr": 0, "avg_position": 0}]


def test_all_zeros_true_for_zero_data():
    assert _all_zeros(_make_zero_ga4_rows(), _GA4_METRICS) is True


def test_all_zeros_false_for_nonzero_data():
    assert _all_zeros(_make_ga4_rows(), _GA4_METRICS) is False


def test_all_zeros_true_for_empty_data():
    assert _all_zeros([], _GA4_METRICS) is True


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_zero_ga4_rows())
def test_build_report_ga4_no_movement_when_all_zeros(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "No movement" in report.html
    assert "Google Analytics" in report.html
    # Should not contain the metrics table headers
    assert "Sessions" not in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_zero_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_gsc_no_movement_when_all_zeros(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "Search Console" in report.html
    assert "No movement" in report.html
    # GSC table headers should not appear
    assert "Clicks" not in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_zero_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_skips_charts_for_zero_source(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    m_tp,
    m_su,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    # GA4 has data, so its charts should be generated
    assert m_su.call_count == 1
    assert m_tp.call_count == 1
    # GSC is all zeros, so gsc_trend and top_queries charts should NOT appear
    assert "Clicks and Impressions" not in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_calls_chart_functions(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    m_su,
    m_gt,
    m_tq,
    m_tp,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert m_su.call_count == 1
    assert m_gt.call_count == 1
    assert m_tq.call_count == 1
    assert m_tp.call_count == 1


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_encodes_charts_as_base64(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_hi,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "data:image/png;base64," in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_multiple_projects(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_hi,
):
    p1 = ProjectConfig(name="Site A", slug="site-a", ga4_property_id="p/1")
    p2 = ProjectConfig(name="Site B", slug="site-b", gsc_site_url="https://b.com")
    sub = SubscriptionConfig(
        recipient="test@example.com",
        projects=("site-a", "site-b"),
        schedule=Schedule.DAILY,
    )
    report = build_report(
        Path("/fake/db"),
        sub,
        (p1, p2),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "Site A" in report.html
    assert "Site B" in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=None)
@mock.patch(f"{_P}.charts.top_search_queries", return_value=None)
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=None)
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=None)
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=[])
@mock.patch(f"{_P}.get_ga_daily", return_value=[])
def test_build_report_empty_db_still_renders(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_hi,
    sample_subscription,
):
    project = ProjectConfig(
        name="Empty",
        slug="my-site",
        ga4_property_id="p/1",
        gsc_site_url="https://e.com",
    )
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (project,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert isinstance(report, Report)
    assert "Empty" in report.html


def test_build_report_raises_when_no_projects_match():
    sub = SubscriptionConfig(
        recipient="test@example.com",
        projects=("nonexistent",),
        schedule=Schedule.DAILY,
    )
    project = ProjectConfig(name="Real", slug="real-site", ga4_property_id="p/1")
    with pytest.raises(ValueError, match="No matching projects"):
        build_report(
            Path("/fake/db"),
            sub,
            (project,),
            Schedule.DAILY,
            datetime.date(2025, 3, 10),
        )


# ── AI highlights integration ────────────────────────────────────


@mock.patch(
    f"{_P}.generate_highlights",
    return_value="- **Sessions up 25%**\n- Bounce rate stable",
)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_includes_ai_highlights(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_highlights,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "<strong>Sessions up 25%</strong>" in report.html
    assert "Bounce rate stable" in report.html
    assert "<li>" in report.html
    assert "AI Highlights" in report.html


@mock.patch(f"{_P}.generate_highlights", return_value=None)
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_ai_highlights_none(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_highlights,
    sample_project_both,
    sample_subscription,
):
    report = build_report(
        Path("/fake/db"),
        sample_subscription,
        (sample_project_both,),
        Schedule.DAILY,
        datetime.date(2025, 3, 10),
    )
    assert "AI Highlights" not in report.html


# ── Markdown to HTML conversion ──────────────────────────────────


def test_markdown_to_html_bullet_list():
    md = "- First item\n- Second item"
    html = _markdown_to_html(md)
    assert "<ul" in html
    assert "<li>First item</li>" in html
    assert "<li>Second item</li>" in html
    assert "</ul>" in html


def test_markdown_to_html_bold():
    md = "- **Traffic doubled** this week"
    html = _markdown_to_html(md)
    assert "<strong>Traffic doubled</strong>" in html


def test_markdown_to_html_plain_paragraph():
    md = "No bullets here, just text."
    html = _markdown_to_html(md)
    assert "<p" in html
    assert "No bullets here, just text." in html
    assert "<ul" not in html


def test_markdown_to_html_empty_string():
    assert _markdown_to_html("") == ""


def test_markdown_to_html_escapes_html_tags():
    md = '- <script>alert(1)</script>'
    result = _markdown_to_html(md)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_markdown_to_html_escapes_html_in_bold():
    md = '- **<img src=x>bold**'
    result = _markdown_to_html(md)
    assert "<img" not in result
    assert "&lt;img src=x&gt;" in result
    assert "<strong>" in result


# ── generate_highlights unexpected exception ─────────────────────


@mock.patch(f"{_P}.generate_highlights", side_effect=RuntimeError("boom"))
@mock.patch(f"{_P}.charts.top_pages", return_value=_png_stub())
@mock.patch(f"{_P}.charts.top_search_queries", return_value=_png_stub())
@mock.patch(f"{_P}.charts.gsc_clicks_impressions_trend", return_value=_png_stub())
@mock.patch(f"{_P}.charts.sessions_users_trend", return_value=_png_stub())
@mock.patch(f"{_P}.get_top_queries", return_value=[])
@mock.patch(f"{_P}.get_top_pages", return_value=[])
@mock.patch(f"{_P}.get_gsc_daily", return_value=_make_gsc_rows())
@mock.patch(f"{_P}.get_ga_daily", return_value=_make_ga4_rows())
def test_build_report_survives_highlights_exception(
    _m_ga,
    _m_gsc,
    _m_pages,
    _m_queries,
    _m_su,
    _m_gt,
    _m_tq,
    _m_tp,
    _m_highlights,
    sample_project_both,
    sample_subscription,
    caplog,
):
    with caplog.at_level(logging.WARNING):
        report = build_report(
            Path("/fake/db"),
            sample_subscription,
            (sample_project_both,),
            Schedule.DAILY,
            datetime.date(2025, 3, 10),
        )
    assert report.html
    assert "AI Highlights" not in report.html
    assert "Unexpected error" in caplog.text
