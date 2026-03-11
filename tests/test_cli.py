"""Tests for the CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from sites_report.cli import cli

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
    assert "Schema version: 1" in result.output


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


# --- report placeholder ---


def test_report_prints_not_implemented(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 1
    assert "not implemented" in result.output.lower()


# --- fetch command ---


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
