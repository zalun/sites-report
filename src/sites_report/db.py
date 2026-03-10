"""SQLite schema creation and query helpers."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION: int = 1

DATA_TABLES: tuple[str, ...] = (
    "ga_daily",
    "gsc_daily",
    "gsc_top_queries",
    "ga_top_pages",
    "vercel_daily",
)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ga_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,
    sessions INTEGER,
    users INTEGER,
    new_users INTEGER,
    pageviews INTEGER,
    avg_session_duration REAL,
    bounce_rate REAL,
    conversions INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

CREATE TABLE IF NOT EXISTS gsc_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    avg_position REAL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

CREATE TABLE IF NOT EXISTS gsc_top_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,
    query TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    position REAL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date, query)
);

CREATE TABLE IF NOT EXISTS ga_top_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,
    page_path TEXT NOT NULL,
    pageviews INTEGER,
    sessions INTEGER,
    avg_time_on_page REAL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date, page_path)
);

CREATE TABLE IF NOT EXISTS vercel_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,
    requests INTEGER,
    unique_visitors INTEGER,
    pageviews INTEGER,
    avg_duration_ms REAL,
    p75_duration_ms REAL,
    p95_duration_ms REAL,
    errors INTEGER,
    bandwidth_bytes INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

CREATE INDEX IF NOT EXISTS idx_ga_daily_lookup ON ga_daily(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_lookup ON gsc_daily(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_gsc_queries_lookup ON gsc_top_queries(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_ga_pages_lookup ON ga_top_pages(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_vercel_daily_lookup ON vercel_daily(project_slug, date);
"""


class DatabaseError(Exception):
    """Raised when a database operation fails."""


@dataclass(frozen=True, slots=True)
class TableStatus:
    name: str
    row_count: int
    min_date: str | None
    max_date: str | None
    last_fetched_at: str | None

    def __post_init__(self) -> None:
        if not self.name:
            msg = "name must not be empty"
            raise ValueError(msg)
        if self.row_count < 0:
            msg = "row_count must be non-negative"
            raise ValueError(msg)
        has_dates = (
            self.min_date is not None
            or self.max_date is not None
            or self.last_fetched_at is not None
        )
        if self.row_count == 0 and has_dates:
            msg = "date fields and last_fetched_at must be None when row_count is 0"
            raise ValueError(msg)
        if self.row_count > 0 and (
            self.min_date is None or self.max_date is None or self.last_fetched_at is None
        ):
            msg = "min_date, max_date, and last_fetched_at must not be None when row_count > 0"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DbStatus:
    schema_version: int
    tables: tuple[TableStatus, ...]

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            msg = "schema_version must be >= 1"
            raise ValueError(msg)
        actual_names = tuple(t.name for t in self.tables)
        if actual_names != DATA_TABLES:
            msg = f"expected tables {DATA_TABLES}, got {actual_names}"
            raise ValueError(msg)


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with WAL mode and foreign keys enabled."""
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        msg = f"Cannot open database '{db_path}': {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    try:
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        if result is None or result[0].lower() != "wal":
            actual = result[0] if result else "unknown"
            msg = f"Failed to enable WAL journal mode for '{db_path}', got: {actual}"
            logger.error(msg)
            raise DatabaseError(msg)
        conn.execute("PRAGMA foreign_keys=ON")
        fk_result = conn.execute("PRAGMA foreign_keys").fetchone()
        if fk_result is None or fk_result[0] != 1:
            msg = f"Failed to enable foreign keys for '{db_path}'"
            logger.error(msg)
            raise DatabaseError(msg)
    except DatabaseError:
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        msg = f"Failed to configure database pragmas for '{db_path}': {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    return conn


def init_db(db_path: Path) -> None:
    """Create database file, parent dirs, and all tables. Idempotent."""
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"Cannot create database directory '{db_path.parent}': {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc

    conn = _connect(db_path)

    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()

        current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        if current is None or current[0] is None:
            msg = "Database schema version table is empty — may be corrupt"
            logger.error(msg)
            raise DatabaseError(msg)
        if current[0] != SCHEMA_VERSION:
            msg = (
                f"Database schema version mismatch: expected {SCHEMA_VERSION}, "
                f"found {current[0]}. Migration may be required."
            )
            logger.error(msg)
            raise DatabaseError(msg)
    except sqlite3.Error as exc:
        msg = f"Failed to initialize database schema: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


def get_db_status(db_path: Path) -> DbStatus:
    """Return row counts, date ranges, last fetch times for all data tables."""
    if not db_path.exists():
        msg = f"Database file not found: {db_path}"
        logger.error(msg)
        raise DatabaseError(msg)

    conn = _connect(db_path)

    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        if row is None or row[0] is None:
            msg = f"Database '{db_path}' has no schema version — may be uninitialized or corrupt"
            logger.error(msg)
            raise DatabaseError(msg)
        version = row[0]
        if version != SCHEMA_VERSION:
            msg = (
                f"Database schema version mismatch: expected {SCHEMA_VERSION}, "
                f"found {version}. Migration may be required."
            )
            logger.error(msg)
            raise DatabaseError(msg)

        statuses: list[TableStatus] = []
        for table in DATA_TABLES:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*), MIN(date), MAX(date), MAX(fetched_at) FROM {table}"
                ).fetchone()
            except sqlite3.Error as exc:
                msg = f"Failed to query status for table '{table}': {exc}"
                logger.error(msg)
                raise DatabaseError(msg) from exc
            try:
                statuses.append(
                    TableStatus(
                        name=table,
                        row_count=row[0],
                        min_date=row[1],
                        max_date=row[2],
                        last_fetched_at=row[3],
                    )
                )
            except ValueError as exc:
                msg = f"Invalid data in table '{table}': {exc}"
                logger.error(msg)
                raise DatabaseError(msg) from exc
    except DatabaseError:
        raise
    except sqlite3.Error as exc:
        msg = f"Failed to query database status: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()

    return DbStatus(schema_version=version, tables=tuple(statuses))
