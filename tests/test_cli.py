"""Tests for the CLI commands."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from sites_report.cli import _default_report_date, cli
from sites_report.config import Schedule
from sites_report.email import EmailError
from sites_report.reports.builder import Report

MINIMAL_CONFIG = """\
[email]
smtp_host = "smtp.test.com"
smtp_port = 587
smtp_user = "test@test.com"
smtp_password_env = "TEST_SMTP_PASS"
from_address = "test@test.com"

[google]
service_account_key = "credentials/sa.json"

[[projects]]
name = "Test Project"
slug = "test-project"
ga4_property_id = "properties/123"

[[subscriptions]]
recipient = "admin@test.com"
projects = ["test-project"]
schedule = "daily"
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a minimal valid config pointing db_path into tmp_path."""
    db_path = tmp_path / "data" / "sites-report.db"
    cfg_text = MINIMAL_CONFIG.replace(
        "[email]",
        f'[general]\ndb_path = "{db_path}"\n\n[email]',
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(cfg_text)
    monkeypatch.setenv("TEST_SMTP_PASS", "secret")
    return cfg


# --- init command ---


def test_init_creates_database(runner: CliRunner, config_path: Path, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["--config", str(config_path), "init"])
    assert result.exit_code == 0, result.output
    assert "initialized" in result.output.lower()
    assert (tmp_path / "data" / "sites-report.db").exists()


def test_init_is_idempotent(runner: CliRunner, config_path: Path) -> None:
    result1 = runner.invoke(cli, ["--config", str(config_path), "init"])
    result2 = runner.invoke(cli, ["--config", str(config_path), "init"])
    assert result1.exit_code == 0, result1.output
    assert result2.exit_code == 0, result2.output


def test_init_fails_on_missing_config(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--config", "/nonexistent/config.toml", "init"])
    assert result.exit_code == 1
    assert "configuration error" in result.output.lower()


def test_init_fails_on_invalid_config(runner: CliRunner, tmp_path: Path) -> None:
    bad_cfg = tmp_path / "bad.toml"
    bad_cfg.write_text("this is not valid toml [[[")
    result = runner.invoke(cli, ["--config", str(bad_cfg), "init"])
    assert result.exit_code == 1
    assert "configuration error" in result.output.lower()


# --- db-status command ---


def test_db_status_shows_empty_tables(runner: CliRunner, config_path: Path) -> None:
    setup = runner.invoke(cli, ["--config", str(config_path), "init"])
    assert setup.exit_code == 0, setup.output

    result = runner.invoke(cli, ["--config", str(config_path), "db-status"])
    assert result.exit_code == 0, result.output
    for table in ("ga_daily", "gsc_daily", "gsc_top_queries", "ga_top_pages", "vercel_daily"):
        assert table in result.output


def test_db_status_shows_schema_version(runner: CliRunner, config_path: Path) -> None:
    setup = runner.invoke(cli, ["--config", str(config_path), "init"])
    assert setup.exit_code == 0, setup.output

    result = runner.invoke(cli, ["--config", str(config_path), "db-status"])
    assert result.exit_code == 0, result.output
    assert "Schema version: 2" in result.output


def test_db_status_fails_on_uninitialized_db(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "nonexistent" / "db.sqlite"
    cfg_text = MINIMAL_CONFIG.replace(
        "[email]",
        f'[general]\ndb_path = "{db_path}"\n\n[email]',
    )
    cfg = tmp_path / "uninitialized.toml"
    cfg.write_text(cfg_text)
    monkeypatch.setenv("TEST_SMTP_PASS", "secret")

    result = runner.invoke(cli, ["--config", str(cfg), "db-status"])
    assert result.exit_code == 1
    assert "database error" in result.output.lower()


# --- verbose flag ---


def test_verbose_flag_accepted(runner: CliRunner, config_path: Path) -> None:
    result = runner.invoke(cli, ["--verbose", "--config", str(config_path), "init"])
    assert result.exit_code == 0, result.output


# --- shared config templates ---

MULTI_PROJECT_CONFIG = """\
[general]
db_path = "{db_path}"

[email]
smtp_host = "smtp.test.com"
smtp_port = 587
smtp_user = "test@test.com"
smtp_password_env = "TEST_SMTP_PASS"
from_address = "test@test.com"

[google]
service_account_key = "credentials/sa.json"

[[projects]]
name = "Site A"
slug = "site-a"
ga4_property_id = "properties/111"
gsc_site_url = "https://site-a.com"

[[projects]]
name = "Site B"
slug = "site-b"
ga4_property_id = "properties/222"

[[subscriptions]]
recipient = "admin@test.com"
projects = ["site-a", "site-b"]
schedule = "daily"
"""


# --- report command ---

_MOCK_REPORT = Report(subject="Test Report", html="<html>test</html>")


@pytest.fixture
def report_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Config with a daily subscription for report tests."""
    db_path = tmp_path / "data" / "sites-report.db"
    cfg_text = MULTI_PROJECT_CONFIG.format(db_path=db_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text(cfg_text)
    monkeypatch.setenv("TEST_SMTP_PASS", "secret")
    return cfg


TWO_SUBSCRIPTION_CONFIG = """\
[general]
db_path = "{db_path}"

[email]
smtp_host = "smtp.test.com"
smtp_port = 587
smtp_user = "test@test.com"
smtp_password_env = "TEST_SMTP_PASS"
from_address = "test@test.com"

[google]
service_account_key = "credentials/sa.json"

[[projects]]
name = "Site A"
slug = "site-a"
ga4_property_id = "properties/111"

[[projects]]
name = "Site B"
slug = "site-b"
ga4_property_id = "properties/222"

[[subscriptions]]
recipient = "admin@test.com"
projects = ["site-a"]
schedule = "daily"

[[subscriptions]]
recipient = "boss@test.com"
projects = ["site-b"]
schedule = "daily"
"""


@pytest.fixture
def two_sub_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "data" / "sites-report.db"
    cfg_text = TWO_SUBSCRIPTION_CONFIG.format(db_path=db_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text(cfg_text)
    monkeypatch.setenv("TEST_SMTP_PASS", "secret")
    return cfg


def test_report_requires_schedule(runner: CliRunner, report_config_path: Path) -> None:
    result = runner.invoke(cli, ["--config", str(report_config_path), "report"])
    assert result.exit_code == 2


def test_report_rejects_invalid_schedule(runner: CliRunner, report_config_path: Path) -> None:
    result = runner.invoke(
        cli, ["--config", str(report_config_path), "report", "--schedule", "foo"]
    )
    assert result.exit_code == 2


# Note: build_report is patched at its definition site (sites_report.reports.builder)
# because the report command uses a deferred local import that re-reads the module
# attribute on every call. This is equivalent to patching at the consumer site.

@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_generates_daily(mock_build, runner: CliRunner, report_config_path: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Test Report" in result.output


@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_calls_build_report_with_correct_args(
    mock_build, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_build.call_count == 1
    args = mock_build.call_args[0]
    assert args[3] == Schedule.DAILY
    assert args[4] == datetime.date(2025, 3, 1)


@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_default_date_daily(
    mock_build, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(report_config_path), "report", "--schedule", "daily", "--no-send"],
    )
    assert result.exit_code == 0, result.output
    expected = datetime.date.today() - datetime.timedelta(days=1)
    args = mock_build.call_args[0]
    assert args[4] == expected


@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_output_writes_file(
    mock_build, runner: CliRunner, report_config_path: Path, tmp_path: Path
) -> None:
    out_file = tmp_path / "report.html"
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_file.exists()
    assert out_file.read_text() == "<html>test</html>"


@mock.patch("sites_report.email.send_email")
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_output_implies_no_send(
    mock_build, mock_send, runner: CliRunner, report_config_path: Path, tmp_path: Path
) -> None:
    out_file = tmp_path / "report.html"
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_send.call_count == 0


# Note: send_email is patched at its definition site (sites_report.email) because
# the report command uses a deferred conditional import inside the function body.

@mock.patch("sites_report.email.send_email")
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_sends_email(
    mock_build, mock_send, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_send.call_count == 1
    call_args = mock_send.call_args[0]
    assert call_args[1] == "admin@test.com"
    assert call_args[2] == _MOCK_REPORT.subject
    assert call_args[3] == _MOCK_REPORT.html
    assert "Sent to" in result.output


@mock.patch("sites_report.email.send_email")
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_no_send_skips_email(
    mock_build, mock_send, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_send.call_count == 0


@mock.patch(
    "sites_report.email.send_email",
    side_effect=EmailError("SMTP down"),
)
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_send_email_error_logged(
    mock_build, mock_send, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 1
    assert "failed to send" in result.output.lower()


@mock.patch("sites_report.email.send_email")
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_multiple_subscriptions_sends_all(
    mock_build, mock_send, runner: CliRunner, two_sub_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(two_sub_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_send.call_count == 2
    recipients = {call[0][1] for call in mock_send.call_args_list}
    assert recipients == {"admin@test.com", "boss@test.com"}


@mock.patch(
    "sites_report.email.send_email",
    side_effect=[None, EmailError("SMTP down")],
)
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_partial_send_failure(
    mock_build, mock_send, runner: CliRunner, two_sub_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(two_sub_config_path),
            "report",
            "--schedule",
            "daily",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 1
    assert mock_send.call_count == 2
    assert "Sent to" in result.output
    assert "failed to send" in result.output.lower()
    assert "1 of 2 subscription(s) failed" in result.output.lower()


def test_report_no_matching_subscriptions(runner: CliRunner, report_config_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(report_config_path), "report", "--schedule", "weekly", "--no-send"],
    )
    assert result.exit_code == 0, result.output
    assert "no subscriptions" in result.output.lower()


def test_report_invalid_date_rejected(runner: CliRunner, report_config_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(report_config_path), "report", "--schedule", "daily", "--date", "bad"],
    )
    assert result.exit_code == 1
    assert "invalid date" in result.output.lower()


@mock.patch(
    "sites_report.reports.builder.build_report", side_effect=ValueError("No matching projects")
)
def test_report_build_error_logged(
    mock_build, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 1
    assert "skipping" in result.output.lower()
    assert "all subscriptions failed" in result.output.lower()


@mock.patch(
    "sites_report.reports.builder.build_report",
    side_effect=RuntimeError("template rendering crashed"),
)
def test_report_unexpected_error_logged(
    mock_build, runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 1
    assert "failed to build report" in result.output.lower()


@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_multiple_subscriptions(
    mock_build, runner: CliRunner, two_sub_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(two_sub_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_build.call_count == 2
    assert "admin@test.com" in result.output
    assert "boss@test.com" in result.output


def test_report_preview_without_output_rejected(
    runner: CliRunner, report_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--no-send",
            "--preview",
            "--date",
            "2025-03-01",
        ],
    )
    assert result.exit_code == 1
    assert "--preview requires --output" in result.output


@mock.patch("sites_report.cli.webbrowser.open", return_value=True)
@mock.patch("sites_report.reports.builder.build_report", return_value=_MOCK_REPORT)
def test_report_preview_with_output_opens_browser(
    mock_build,
    mock_browser,
    runner: CliRunner,
    report_config_path: Path,
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "report.html"
    result = runner.invoke(
        cli,
        [
            "--config",
            str(report_config_path),
            "report",
            "--schedule",
            "daily",
            "--preview",
            "--date",
            "2025-03-01",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert mock_browser.call_count == 1


# --- _default_report_date tests ---


def test_default_report_date_daily() -> None:
    today = datetime.date(2025, 3, 12)
    assert _default_report_date(Schedule.DAILY, today) == datetime.date(2025, 3, 11)


def test_default_report_date_weekly_midweek() -> None:
    # Wednesday 2025-03-12 -> last Sunday = 2025-03-09
    today = datetime.date(2025, 3, 12)
    result = _default_report_date(Schedule.WEEKLY, today)
    assert result == datetime.date(2025, 3, 9)
    assert result.weekday() == 6  # Sunday


def test_default_report_date_weekly_on_sunday() -> None:
    # Sunday 2025-03-09 -> previous Sunday = 2025-03-02
    today = datetime.date(2025, 3, 9)
    result = _default_report_date(Schedule.WEEKLY, today)
    assert result == datetime.date(2025, 3, 2)
    assert result.weekday() == 6


def test_default_report_date_monthly() -> None:
    today = datetime.date(2025, 3, 15)
    assert _default_report_date(Schedule.MONTHLY, today) == datetime.date(2025, 2, 28)


def test_default_report_date_monthly_jan_first() -> None:
    today = datetime.date(2025, 1, 1)
    assert _default_report_date(Schedule.MONTHLY, today) == datetime.date(2024, 12, 31)


# --- fetch command ---


@pytest.fixture
def fetch_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "data" / "sites-report.db"
    cfg_text = MULTI_PROJECT_CONFIG.format(db_path=db_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text(cfg_text)
    monkeypatch.setenv("TEST_SMTP_PASS", "secret")
    return cfg


_GA4_DAILY = {"sessions": 100, "users": 80, "pageviews": 200}
_GA4_PAGES = [{"page_path": "/home", "pageviews": 100, "sessions": 80, "avg_time_on_page": 30.0}]
_GSC_DAILY = {"clicks": 50, "impressions": 1000, "ctr": 0.05, "avg_position": 3.2}
_GSC_QUERIES = [{"query": "test", "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 5.0}]


_GA4_CLS = "sites_report.collectors.analytics.GA4Collector"
_GSC_CLS = "sites_report.collectors.search_console.GSCCollector"


def _mock_ga4():
    collector = mock.MagicMock()
    collector.fetch.return_value = _GA4_DAILY
    collector.fetch_top_pages.return_value = _GA4_PAGES
    return collector


def _mock_gsc():
    collector = mock.MagicMock()
    collector.fetch.return_value = _GSC_DAILY
    collector.fetch_top_queries.return_value = _GSC_QUERIES
    return collector


def _ga4_factory(_cfg):
    return _mock_ga4()


def _gsc_factory(_cfg):
    return _mock_gsc()


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_calls_ga4_collector_for_configured_project(
    mock_ga4_cls, _mock_gsc_cls, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli, ["--config", str(fetch_config_path), "fetch", "--date", "2025-03-01"]
    )
    assert result.exit_code == 0, result.output
    assert mock_ga4_cls.call_count == 1
    assert "successfully" in result.output.lower()


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_calls_gsc_collector_for_configured_project(
    _mock_ga4_cls, mock_gsc_cls, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli, ["--config", str(fetch_config_path), "fetch", "--date", "2025-03-01"]
    )
    assert result.exit_code == 0, result.output
    assert mock_gsc_cls.call_count == 1


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_defaults_to_yesterday(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(cli, ["--config", str(fetch_config_path), "fetch"])
    assert result.exit_code == 0, result.output


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_date_option_uses_specified_date(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(fetch_config_path), "fetch", "--date", "2025-01-15"],
    )
    assert result.exit_code == 0, result.output


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_range_option_fetches_multiple_days(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(fetch_config_path),
            "fetch",
            "--date",
            "2025-03-03",
            "--range",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output
    # 3 days x (site-a: 4 ops + site-b: 2 ops) = 18 operations
    assert "18/18" in result.output


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_project_option_filters_projects(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        [
            "--config",
            str(fetch_config_path),
            "fetch",
            "--date",
            "2025-03-01",
            "--project",
            "site-a",
        ],
    )
    assert result.exit_code == 0, result.output
    # 1 day x site-a (GA4 daily + GA4 pages + GSC daily + GSC queries) = 4 ops
    assert "4/4" in result.output


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_ga4_factory)
def test_fetch_exits_zero_on_full_success(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(fetch_config_path), "fetch", "--date", "2025-03-01"],
    )
    assert result.exit_code == 0


def _failing_ga4_factory(_cfg):
    from sites_report.collectors.base import CollectorError

    collector = mock.MagicMock()
    collector.fetch.side_effect = CollectorError("API down")
    return collector


@mock.patch(_GSC_CLS, side_effect=_gsc_factory)
@mock.patch(_GA4_CLS, side_effect=_failing_ga4_factory)
def test_fetch_continues_on_collector_error(
    _ga4, _gsc, runner: CliRunner, fetch_config_path: Path
) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(fetch_config_path), "fetch", "--date", "2025-03-01"],
    )
    # Should exit 1 because of GA4 failures but still run GSC
    assert result.exit_code == 1
    assert "failure" in result.output.lower()


def test_fetch_skips_unconfigured_sources(runner: CliRunner, fetch_config_path: Path) -> None:
    """Site B has only GA4 (no gsc_site_url)."""
    ga4 = _mock_ga4()
    gsc = _mock_gsc()

    @mock.patch(_GSC_CLS, side_effect=lambda _: gsc)
    @mock.patch(_GA4_CLS, side_effect=lambda _: ga4)
    def _run(_ga4_cls, _gsc_cls):
        return runner.invoke(
            cli,
            [
                "--config",
                str(fetch_config_path),
                "fetch",
                "--date",
                "2025-03-01",
                "--project",
                "site-b",
            ],
        )

    result = _run()
    assert result.exit_code == 0, result.output
    # GSC should not be called for site-b (no gsc_site_url)
    assert gsc.fetch.call_count == 0


def test_fetch_rejects_invalid_date(runner: CliRunner, fetch_config_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(fetch_config_path), "fetch", "--date", "not-a-date"],
    )
    assert result.exit_code == 1
    assert "invalid date" in result.output.lower()


def test_fetch_rejects_range_zero(runner: CliRunner, fetch_config_path: Path) -> None:
    result = runner.invoke(
        cli,
        ["--config", str(fetch_config_path), "fetch", "--range", "0"],
    )
    assert result.exit_code == 1
    assert "--range must be >= 1" in result.output
