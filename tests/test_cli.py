"""Tests for the CLI commands."""

from __future__ import annotations

from pathlib import Path

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


def test_init_creates_database(
    runner: CliRunner, config_path: Path, tmp_path: Path
) -> None:
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


# --- placeholder commands ---


def test_fetch_prints_not_implemented(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["fetch"])
    assert result.exit_code == 1
    assert "not implemented" in result.output.lower()


def test_report_prints_not_implemented(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 1
    assert "not implemented" in result.output.lower()
