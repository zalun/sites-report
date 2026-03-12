"""Tests for the AI-powered insights module."""

from __future__ import annotations

import logging
import subprocess
from unittest import mock

from sites_report.config import Schedule
from sites_report.reports.insights import (
    _build_prompt,
    _has_meaningful_data,
    generate_highlights,
)

_P = "sites_report.reports.insights"

# ── Sample data ──────────────────────────────────────────────────


def _ga4_metrics():
    return [
        {
            "label": "Sessions",
            "current": "100",
            "previous": "80",
            "change": "+25.0%",
            "direction": "positive",
        },
        {
            "label": "Users",
            "current": "90",
            "previous": "70",
            "change": "+28.6%",
            "direction": "positive",
        },
    ]


def _gsc_metrics():
    return [
        {
            "label": "Clicks",
            "current": "50",
            "previous": "40",
            "change": "+25.0%",
            "direction": "positive",
        },
    ]


def _pages():
    return [
        {"page_path": "/home", "pageviews": 500, "sessions": 300, "avg_time_on_page": 45.2},
        {"page_path": "/about", "pageviews": 200, "sessions": 150, "avg_time_on_page": 30.1},
    ]


def _queries():
    return [
        {
            "query": "example search",
            "clicks": 20,
            "impressions": 500,
            "ctr": 0.04,
            "position": 3.2,
        },
    ]


# ── generate_highlights ─────────────────────────────────────────


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_returns_text(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["claude", "-p"],
        returncode=0,
        stdout="- Sessions up 25%\n- Users up 28.6%\n",
        stderr="",
    )
    result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result == "- Sessions up 25%\n- Users up 28.6%"
    assert mock_run.call_count == 1
    assert mock_run.call_args == mock.call(
        ["claude", "-p"],
        input=mock.ANY,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "My Site" in mock_run.call_args.kwargs["input"]


def test_generate_highlights_no_data():
    result = generate_highlights("My Site", Schedule.DAILY, None, None, [], [])
    assert result is None


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_timeout(mock_run, caplog):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "timed out" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_claude_not_found(mock_run, caplog):
    mock_run.side_effect = FileNotFoundError
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "OS error" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_permission_error(mock_run, caplog):
    mock_run.side_effect = PermissionError("not executable")
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "OS error" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_subprocess_error(mock_run, caplog):
    mock_run.side_effect = subprocess.SubprocessError("something broke")
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "subprocess error" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_unicode_decode_error(mock_run, caplog):
    mock_run.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "undecodable output" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_empty_output(mock_run, caplog):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["claude", "-p"],
        returncode=0,
        stdout="   \n  ",
        stderr="",
    )
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "empty output" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_nonzero_returncode(mock_run, caplog):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["claude", "-p"],
        returncode=1,
        stdout="",
        stderr="model not found",
    )
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert result is None
    assert "exited with code 1" in caplog.text
    assert "model not found" in caplog.text
    assert "My Site" in caplog.text


@mock.patch(f"{_P}.subprocess.run")
def test_generate_highlights_malformed_data(mock_run, caplog):
    bad_pages = [{"page_path": "/home"}]  # missing pageviews, sessions, avg_time_on_page
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, None, None, bad_pages, [])
    assert result is None
    assert mock_run.call_count == 0
    assert "Failed to build" in caplog.text


def test_generate_highlights_malformed_metrics(caplog):
    bad_metrics = [{"label": "Sessions"}]  # missing current, previous, change, direction
    with caplog.at_level(logging.WARNING):
        result = generate_highlights("My Site", Schedule.DAILY, bad_metrics, None, [], [])
    assert result is None
    assert "Failed to build" in caplog.text


# ── _build_prompt ────────────────────────────────────────────────


def test_build_prompt_includes_project_name():
    prompt = _build_prompt("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert "My Site" in prompt
    assert "daily report" in prompt


def test_build_prompt_omits_empty_sections():
    prompt = _build_prompt("My Site", Schedule.WEEKLY, None, _gsc_metrics(), [], [])
    assert "## GA4 Metrics" not in prompt
    assert "## GSC Metrics" in prompt
    assert "## Top Pages" not in prompt
    assert "## Top Search Queries" not in prompt


def test_build_prompt_formats_metrics():
    prompt = _build_prompt("My Site", Schedule.DAILY, _ga4_metrics(), None, _pages(), _queries())
    assert "Sessions: 100" in prompt
    assert "previous: 80" in prompt
    assert "+25.0%" in prompt
    assert "direction" not in prompt
    assert "/home" in prompt
    assert "500 pageviews" in prompt
    assert '"example search"' in prompt
    assert "20 clicks" in prompt
    assert "4.0% CTR" in prompt


def test_build_prompt_all_data_types():
    prompt = _build_prompt(
        "My Site", Schedule.DAILY, _ga4_metrics(), _gsc_metrics(), _pages(), _queries()
    )
    assert "## GA4 Metrics" in prompt
    assert "## GSC Metrics" in prompt
    assert "## Top Pages" in prompt
    assert "## Top Search Queries" in prompt


def test_build_prompt_daily_schedule():
    prompt = _build_prompt("My Site", Schedule.DAILY, _ga4_metrics(), None, [], [])
    assert "Compare against the same day last week" in prompt


def test_build_prompt_weekly_schedule():
    prompt = _build_prompt("My Site", Schedule.WEEKLY, _ga4_metrics(), None, [], [])
    assert "week-over-week trends" in prompt


def test_build_prompt_monthly_schedule():
    prompt = _build_prompt("My Site", Schedule.MONTHLY, _ga4_metrics(), None, [], [])
    assert "month-over-month shifts" in prompt


def test_build_prompt_queries_ctr_as_percentage():
    queries = [{"query": "test", "clicks": 10, "impressions": 200, "ctr": 0.035, "position": 5.7}]
    prompt = _build_prompt("My Site", Schedule.DAILY, None, None, [], queries)
    assert "3.5% CTR" in prompt
    assert "position 5.7" in prompt


def test_build_prompt_no_direction_in_output():
    prompt = _build_prompt("My Site", Schedule.DAILY, _ga4_metrics(), _gsc_metrics(), [], [])
    assert "direction" not in prompt


def test_build_prompt_pages_only():
    prompt = _build_prompt("My Site", Schedule.DAILY, None, None, _pages(), [])
    assert "## Top Pages" in prompt
    assert "## GA4 Metrics" not in prompt
    assert "## GSC Metrics" not in prompt
    assert "## Top Search Queries" not in prompt


def test_build_prompt_queries_only():
    prompt = _build_prompt("My Site", Schedule.DAILY, None, None, [], _queries())
    assert "## Top Search Queries" in prompt
    assert "## GA4 Metrics" not in prompt
    assert "## GSC Metrics" not in prompt
    assert "## Top Pages" not in prompt


def test_build_prompt_queries_none_ctr_position():
    queries = [{"query": "test", "clicks": 5, "impressions": 0, "ctr": None, "position": None}]
    prompt = _build_prompt("My Site", Schedule.DAILY, None, None, [], queries)
    assert "N/A CTR" in prompt
    assert "position N/A" in prompt


# ── _has_meaningful_data ─────────────────────────────────────────


def test_has_meaningful_data_all_empty():
    assert _has_meaningful_data(None, None, [], []) is False


def test_has_meaningful_data_with_none_lists():
    assert _has_meaningful_data(None, None, None, None) is False


def test_has_meaningful_data_with_pages():
    assert _has_meaningful_data(None, None, _pages(), []) is True


def test_has_meaningful_data_with_metrics():
    assert _has_meaningful_data(_ga4_metrics(), None, [], []) is True
