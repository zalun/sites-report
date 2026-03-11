"""TOML configuration loading and validation."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Schedule(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


def default_config_path() -> Path:
    """Return ``~/.sites-report/config.toml``."""
    try:
        home = Path.home()
    except (RuntimeError, KeyError):
        msg = (
            "Cannot determine home directory. "
            "Set HOME or use --config to specify a config path."
        )
        raise ConfigError(msg) from None
    return home / ".sites-report" / "config.toml"


@dataclass(frozen=True, slots=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str = field(repr=False)
    from_address: str


@dataclass(frozen=True, slots=True)
class GoogleConfig:
    service_account_key: Path


@dataclass(frozen=True, slots=True)
class VercelConfig:
    api_token: str


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    name: str
    slug: str
    ga4_property_id: str | None = None
    gsc_site_url: str | None = None
    vercel_project_id: str | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionConfig:
    recipient: str
    projects: tuple[str, ...]
    schedule: Schedule


@dataclass(frozen=True, slots=True)
class Config:
    db_path: Path
    log_level: LogLevel
    email: EmailConfig
    google: GoogleConfig | None
    vercel: VercelConfig | None
    projects: tuple[ProjectConfig, ...]
    subscriptions: tuple[SubscriptionConfig, ...]


def _resolve_path(base_dir: Path, raw: object, label: str) -> Path:
    """Resolve a path relative to *base_dir* unless it is already absolute."""
    if not isinstance(raw, str):
        msg = f"Expected a string for {label}, got {type(raw).__name__}: {raw!r}"
        raise ConfigError(msg)
    cleaned = raw.strip()
    if not cleaned:
        msg = f"{label} must not be empty"
        raise ConfigError(msg)
    p = Path(cleaned)
    if p.is_absolute():
        return p
    return base_dir / p


def load_config(path: Path, *, resolve_env: bool = True) -> Config:
    """Load and validate configuration from a TOML file.

    Relative paths in the config (``db_path``, ``service_account_key``)
    are resolved against the config file's parent directory.
    """
    try:
        raw = path.read_bytes()
        base_dir = path.resolve().parent
    except FileNotFoundError:
        msg = f"Config file not found: {path}"
        raise ConfigError(msg) from None
    except OSError as exc:
        msg = f"Cannot read config file '{path}': {exc}"
        raise ConfigError(msg) from exc

    try:
        data = tomllib.loads(raw.decode())
    except tomllib.TOMLDecodeError as exc:
        msg = f"Malformed TOML: {exc}"
        raise ConfigError(msg) from None

    general = data.get("general", {})
    raw_db_path = general.get("db_path", "data/sites-report.db")
    db_path = _resolve_path(base_dir, raw_db_path, "general.db_path")
    raw_log_level = general.get("log_level", "INFO")
    if not isinstance(raw_log_level, str):
        valid = ", ".join(lv.value for lv in LogLevel)
        got = type(raw_log_level).__name__
        msg = f"general.log_level must be a string, got {got}. Valid values: {valid}"
        raise ConfigError(msg)
    try:
        log_level = LogLevel(raw_log_level.upper())
    except ValueError:
        valid = ", ".join(lv.value for lv in LogLevel)
        msg = f"Invalid log_level '{raw_log_level}', must be one of: {valid}"
        raise ConfigError(msg) from None

    if "email" not in data:
        msg = "Missing required [email] section"
        raise ConfigError(msg)
    email = _parse_email(data["email"], resolve_env=resolve_env)

    google = _parse_google(data["google"], base_dir) if "google" in data else None
    vercel = _parse_vercel(data["vercel"], resolve_env=resolve_env) if "vercel" in data else None

    if "projects" not in data or len(data["projects"]) == 0:
        msg = "At least one [[projects]] entry is required"
        raise ConfigError(msg)
    projects = tuple(_parse_project(p, i) for i, p in enumerate(data["projects"]))

    slugs = [p.slug for p in projects]
    seen: set[str] = set()
    for s in slugs:
        if s in seen:
            msg = f"Duplicate project slug: '{s}'"
            raise ConfigError(msg)
        seen.add(s)
    valid_slugs = frozenset(slugs)

    if "subscriptions" not in data or len(data["subscriptions"]) == 0:
        msg = "At least one [[subscriptions]] entry is required"
        raise ConfigError(msg)
    subscriptions = tuple(
        _parse_subscription(s, i, valid_slugs) for i, s in enumerate(data["subscriptions"])
    )

    _cross_validate(projects, google=google, vercel=vercel)

    return Config(
        db_path=db_path,
        log_level=log_level,
        email=email,
        google=google,
        vercel=vercel,
        projects=projects,
        subscriptions=subscriptions,
    )


def _resolve_env_var(env_var_name: str, field_label: str, *, resolve: bool) -> str:
    if not resolve:
        return f"<{env_var_name}>"
    value = os.environ.get(env_var_name)
    if value is None:
        msg = f"Environment variable '{env_var_name}' required for {field_label} is not set"
        raise ConfigError(msg)
    if not value:
        msg = f"Environment variable '{env_var_name}' required for {field_label} is empty"
        raise ConfigError(msg)
    return value


def _parse_email(data: dict, *, resolve_env: bool) -> EmailConfig:
    for key in ("smtp_host", "smtp_port", "smtp_user", "smtp_password_env", "from_address"):
        if key not in data:
            msg = f"Missing required email field: '{key}'"
            raise ConfigError(msg)
    port = data["smtp_port"]
    if not isinstance(port, int) or not (1 <= port <= 65535):
        msg = f"email.smtp_port must be an integer between 1 and 65535, got: {port!r}"
        raise ConfigError(msg)
    return EmailConfig(
        smtp_host=data["smtp_host"],
        smtp_port=port,
        smtp_user=data["smtp_user"],
        smtp_password=_resolve_env_var(
            data["smtp_password_env"], "email.smtp_password", resolve=resolve_env
        ),
        from_address=data["from_address"],
    )


def _parse_google(data: dict, base_dir: Path) -> GoogleConfig:
    try:
        raw_key = data["service_account_key"]
    except KeyError as exc:
        msg = f"Missing required google field: {exc}"
        raise ConfigError(msg) from None
    return GoogleConfig(
        service_account_key=_resolve_path(base_dir, raw_key, "google.service_account_key"),
    )


def _parse_vercel(data: dict, *, resolve_env: bool) -> VercelConfig:
    if "api_token_env" not in data:
        msg = "Missing required vercel field: 'api_token_env'"
        raise ConfigError(msg)
    return VercelConfig(
        api_token=_resolve_env_var(data["api_token_env"], "vercel.api_token", resolve=resolve_env),
    )


def _parse_project(data: dict, index: int) -> ProjectConfig:
    for key in ("name", "slug"):
        if key not in data:
            msg = f"Missing required field '{key}' in projects[{index}]"
            raise ConfigError(msg)
        if not data[key] or not data[key].strip():
            msg = f"Field '{key}' in projects[{index}] must not be empty"
            raise ConfigError(msg)
    name = data["name"].strip()
    slug = data["slug"].strip()
    ga4 = data.get("ga4_property_id")
    gsc = data.get("gsc_site_url")
    vercel = data.get("vercel_project_id")
    if ga4 is None and gsc is None and vercel is None:
        msg = f"Project '{slug}' has no data sources configured"
        raise ConfigError(msg)
    return ProjectConfig(
        name=name,
        slug=slug,
        ga4_property_id=ga4,
        gsc_site_url=gsc,
        vercel_project_id=vercel,
    )


def _parse_subscription(data: dict, index: int, valid_slugs: frozenset[str]) -> SubscriptionConfig:
    try:
        recipient = data["recipient"]
        raw_projects = data["projects"]
        raw_schedule = data["schedule"]
    except KeyError as exc:
        msg = f"Missing required field {exc} in subscriptions[{index}]"
        raise ConfigError(msg) from None

    try:
        schedule = Schedule(raw_schedule)
    except ValueError:
        valid = ", ".join(s.value for s in Schedule)
        msg = (
            f"Invalid schedule '{raw_schedule}' in subscriptions[{index}], must be one of: {valid}"
        )
        raise ConfigError(msg) from None

    if not isinstance(raw_projects, list):
        msg = (
            f"'projects' in subscriptions[{index}] must be an array, "
            f"got: {type(raw_projects).__name__}"
        )
        raise ConfigError(msg)
    if len(raw_projects) == 0:
        msg = f"'projects' in subscriptions[{index}] must not be empty"
        raise ConfigError(msg)
    for slug in raw_projects:
        if slug not in valid_slugs:
            msg = f"Unknown project slug '{slug}' in subscriptions[{index}]"
            raise ConfigError(msg)

    return SubscriptionConfig(
        recipient=recipient,
        projects=tuple(raw_projects),
        schedule=schedule,
    )


def _cross_validate(
    projects: tuple[ProjectConfig, ...],
    *,
    google: GoogleConfig | None,
    vercel: VercelConfig | None,
) -> None:
    for p in projects:
        if (p.ga4_property_id or p.gsc_site_url) and google is None:
            msg = (
                f"Project '{p.slug}' uses Google data sources "
                "but no [google] section is configured"
            )
            raise ConfigError(msg)
        if p.vercel_project_id and vercel is None:
            msg = (
                f"Project '{p.slug}' uses vercel_project_id but no [vercel] section is configured"
            )
            raise ConfigError(msg)
