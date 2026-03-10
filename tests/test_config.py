from pathlib import Path

import pytest

from sites_report.config import (
    Config,
    ConfigError,
    EmailConfig,
    GoogleConfig,
    ProjectConfig,
    Schedule,
    SubscriptionConfig,
    VercelConfig,
    load_config,
)


def _write_toml_str(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content)
    return path


def _minimal_toml(overrides: str = "") -> str:
    """Return minimal valid TOML config string with optional overrides appended."""
    return f"""\
[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[[projects]]
name = "My Site"
slug = "my-site"

[[subscriptions]]
recipient = "admin@example.com"
projects = ["my-site"]
schedule = "daily"

{overrides}
"""


# ── Happy path ──────────────────────────────────────────────────────


def test_load_config_returns_config_with_all_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("VERCEL_TOKEN", "tok_123")

    toml = """\
[general]
db_path = "data/test.db"
log_level = "DEBUG"

[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[google]
service_account_key = "credentials/sa.json"

[vercel]
api_token_env = "VERCEL_TOKEN"

[[projects]]
name = "My Site"
slug = "my-site"
ga4_property_id = "properties/123"
gsc_site_url = "https://example.com"
vercel_project_id = "prj_abc"

[[subscriptions]]
recipient = "admin@example.com"
projects = ["my-site"]
schedule = "daily"
"""
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path)

    assert isinstance(cfg, Config)
    assert cfg.db_path == Path("data/test.db")
    assert cfg.log_level == "DEBUG"
    assert isinstance(cfg.email, EmailConfig)
    assert cfg.email.smtp_password == "secret"
    assert isinstance(cfg.google, GoogleConfig)
    assert cfg.google.service_account_key == Path("credentials/sa.json")
    assert isinstance(cfg.vercel, VercelConfig)
    assert cfg.vercel.api_token == "tok_123"
    assert len(cfg.projects) == 1
    assert isinstance(cfg.projects[0], ProjectConfig)
    assert cfg.projects[0].slug == "my-site"
    assert len(cfg.subscriptions) == 1
    assert isinstance(cfg.subscriptions[0], SubscriptionConfig)
    assert cfg.subscriptions[0].schedule == Schedule.DAILY


def test_load_config_without_vercel_section(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path)

    assert cfg.vercel is None
    assert cfg.google is None


def test_load_config_without_google_section(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("VERCEL_TOKEN", "tok_123")
    toml = _minimal_toml("""\
[vercel]
api_token_env = "VERCEL_TOKEN"

[[projects]]
name = "Vercel Only"
slug = "vercel-only"
vercel_project_id = "prj_xyz"
""")
    # Need to also add the vercel-only slug to subscription or use separate subscription
    # The minimal_toml already has a subscription for "my-site", so this is fine
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path)

    assert cfg.google is None
    assert cfg.vercel is not None


def test_load_config_defaults_general_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path)

    assert cfg.db_path == Path("data/sites-report.db")
    assert cfg.log_level == "INFO"


def test_load_config_resolves_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "my_smtp_pass")
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path)

    assert cfg.email.smtp_password == "my_smtp_pass"


def test_load_config_with_resolve_env_false(tmp_path):
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    cfg = load_config(path, resolve_env=False)

    assert cfg.email.smtp_password == "<SMTP_PASSWORD>"


# ── Validation errors ───────────────────────────────────────────────


def test_load_config_raises_on_missing_file(tmp_path):
    path = tmp_path / "nonexistent.toml"
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config(path)


def test_load_config_raises_on_malformed_toml(tmp_path):
    path = _write_toml_str(tmp_path, "not valid [[ toml")
    with pytest.raises(ConfigError, match="Malformed TOML"):
        load_config(path)


def test_load_config_raises_on_missing_email_section(tmp_path):
    toml = """\
[[projects]]
name = "X"
slug = "x"

[[subscriptions]]
recipient = "a@b.com"
projects = ["x"]
schedule = "daily"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="Missing required \\[email\\] section"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_invalid_log_level(tmp_path):
    toml = _minimal_toml().replace(
        "[email]",
        '[general]\nlog_level = "VERBOSE"\n\n[email]',
    )
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="Invalid log_level"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_invalid_schedule(tmp_path):
    toml = _minimal_toml().replace('schedule = "daily"', 'schedule = "hourly"')
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="Invalid schedule 'hourly'"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_duplicate_project_slugs(tmp_path):
    toml = _minimal_toml() + """\
[[projects]]
name = "Duplicate"
slug = "my-site"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="Duplicate project slug"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_empty_projects(tmp_path):
    toml = """\
[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[[subscriptions]]
recipient = "admin@example.com"
projects = ["x"]
schedule = "daily"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="At least one \\[\\[projects\\]\\]"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_empty_subscriptions(tmp_path):
    toml = """\
[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[[projects]]
name = "X"
slug = "x"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="At least one \\[\\[subscriptions\\]\\]"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_unknown_slug_in_subscription(tmp_path):
    toml = _minimal_toml().replace('projects = ["my-site"]', 'projects = ["unknown"]')
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="Unknown project slug 'unknown'"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_missing_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match=r"Environment variable 'SMTP_PASSWORD'.*not set"):
        load_config(path)


def test_load_config_raises_on_vercel_project_without_vercel_section(tmp_path):
    toml = """\
[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[[projects]]
name = "My Site"
slug = "my-site"
vercel_project_id = "prj_abc"

[[subscriptions]]
recipient = "admin@example.com"
projects = ["my-site"]
schedule = "daily"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="no \\[vercel\\] section"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_google_project_without_google_section(tmp_path):
    toml = """\
[email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_password_env = "SMTP_PASSWORD"
from_address = "reports@example.com"

[[projects]]
name = "My Site"
slug = "my-site"
ga4_property_id = "properties/123"

[[subscriptions]]
recipient = "admin@example.com"
projects = ["my-site"]
schedule = "daily"
"""
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="no \\[google\\] section"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_empty_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "")
    toml = _minimal_toml()
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match=r"'SMTP_PASSWORD'.*is empty"):
        load_config(path)


def test_load_config_raises_on_invalid_smtp_port(tmp_path):
    toml = _minimal_toml().replace("smtp_port = 587", "smtp_port = 99999")
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="smtp_port must be an integer"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_subscription_projects_not_array(tmp_path):
    toml = _minimal_toml().replace('projects = ["my-site"]', 'projects = "my-site"')
    path = _write_toml_str(tmp_path, toml)
    with pytest.raises(ConfigError, match="must be an array"):
        load_config(path, resolve_env=False)


def test_load_config_raises_on_unreadable_file(tmp_path):
    path = tmp_path / "config.toml"
    path.mkdir()  # directory, not a file
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(path)
