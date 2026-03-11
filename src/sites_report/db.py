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
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
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
            if row is None:
                msg = f"No result from status query for table '{table}'"
                logger.error(msg)
                raise DatabaseError(msg)
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

    try:
        return DbStatus(schema_version=version, tables=tuple(statuses))
    except ValueError as exc:
        msg = f"Inconsistent database status: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc


# ── Insert helpers ────────────────────────────────────────────────

_GA_DAILY_KEYS = frozenset(
    {
        "sessions",
        "users",
        "new_users",
        "pageviews",
        "avg_session_duration",
        "bounce_rate",
        "conversions",
    }
)
_GSC_DAILY_KEYS = frozenset(
    {
        "clicks",
        "impressions",
        "ctr",
        "avg_position",
    }
)
_GA_TOP_PAGES_KEYS = frozenset(
    {
        "page_path",
        "pageviews",
        "sessions",
        "avg_time_on_page",
    }
)
_GSC_TOP_QUERIES_KEYS = frozenset(
    {
        "query",
        "clicks",
        "impressions",
        "ctr",
        "position",
    }
)


def _check_keys(
    data_keys: set[str],
    expected: frozenset[str],
    table: str,
    project_slug: str,
    date: str,
) -> None:
    unknown = data_keys - expected
    if unknown:
        logger.warning(
            "Unknown keys in %s data for '%s' on %s: %s",
            table,
            project_slug,
            date,
            unknown,
        )
    missing = expected - data_keys
    if missing:
        logger.warning(
            "Missing keys in %s data for '%s' on %s: %s",
            table,
            project_slug,
            date,
            missing,
        )


def insert_ga_daily(
    db_path: Path, project_slug: str, date: str, data: dict[str, int | float | str | None]
) -> None:
    """Insert or replace a GA4 daily metrics row."""
    _check_keys(set(data.keys()), _GA_DAILY_KEYS, "ga_daily", project_slug, date)
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO ga_daily
               (project_slug, date, sessions, users, new_users, pageviews,
                avg_session_duration, bounce_rate, conversions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_slug,
                date,
                data.get("sessions"),
                data.get("users"),
                data.get("new_users"),
                data.get("pageviews"),
                data.get("avg_session_duration"),
                data.get("bounce_rate"),
                data.get("conversions"),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        msg = f"Failed to insert ga_daily for '{project_slug}' on {date}: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


def insert_gsc_daily(
    db_path: Path, project_slug: str, date: str, data: dict[str, int | float | str | None]
) -> None:
    """Insert or replace a GSC daily metrics row."""
    _check_keys(set(data.keys()), _GSC_DAILY_KEYS, "gsc_daily", project_slug, date)
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO gsc_daily
               (project_slug, date, clicks, impressions, ctr, avg_position)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                project_slug,
                date,
                data.get("clicks"),
                data.get("impressions"),
                data.get("ctr"),
                data.get("avg_position"),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        msg = f"Failed to insert gsc_daily for '{project_slug}' on {date}: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


def insert_ga_top_pages(
    db_path: Path,
    project_slug: str,
    date: str,
    pages: list[dict[str, int | float | str | None]],
) -> None:
    """Insert or replace GA4 top pages rows. Deletes existing rows for the slug+date first."""
    for p in pages:
        _check_keys(set(p.keys()), _GA_TOP_PAGES_KEYS, "ga_top_pages", project_slug, date)
    conn = _connect(db_path)
    try:
        # DELETE + INSERT run in a single implicit transaction;
        # conn.commit() applies both atomically.
        conn.execute(
            "DELETE FROM ga_top_pages WHERE project_slug = ? AND date = ?",
            (project_slug, date),
        )
        conn.executemany(
            """INSERT INTO ga_top_pages
               (project_slug, date, page_path, pageviews, sessions, avg_time_on_page)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    project_slug,
                    date,
                    p.get("page_path"),
                    p.get("pageviews"),
                    p.get("sessions"),
                    p.get("avg_time_on_page"),
                )
                for p in pages
            ],
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        msg = f"Failed to insert ga_top_pages for '{project_slug}' on {date}: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


def insert_gsc_top_queries(
    db_path: Path,
    project_slug: str,
    date: str,
    queries: list[dict[str, int | float | str | None]],
) -> None:
    """Insert or replace GSC top queries rows. Deletes existing rows for the slug+date first."""
    for q in queries:
        _check_keys(set(q.keys()), _GSC_TOP_QUERIES_KEYS, "gsc_top_queries", project_slug, date)
    conn = _connect(db_path)
    try:
        # DELETE + INSERT run in a single implicit transaction;
        # conn.commit() applies both atomically.
        conn.execute(
            "DELETE FROM gsc_top_queries WHERE project_slug = ? AND date = ?",
            (project_slug, date),
        )
        conn.executemany(
            """INSERT INTO gsc_top_queries
               (project_slug, date, query, clicks, impressions, ctr, position)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    project_slug,
                    date,
                    q.get("query"),
                    q.get("clicks"),
                    q.get("impressions"),
                    q.get("ctr"),
                    q.get("position"),
                )
                for q in queries
            ],
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        msg = f"Failed to insert gsc_top_queries for '{project_slug}' on {date}: {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


# ── Query helpers ──────────────────────────────────────────────────


def _query_rows(
    db_path: Path,
    sql: str,
    params: tuple,
    *,
    label: str = "query",
) -> list[dict]:
    """Execute a query and return results as list of dicts."""
    if not db_path.exists():
        msg = f"Database file not found: {db_path}"
        logger.error(msg)
        raise DatabaseError(msg)
    conn = _connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        msg = f"Query failed ({label}): {exc}"
        logger.error(msg)
        raise DatabaseError(msg) from exc
    finally:
        conn.close()


def get_ga_daily(db_path: Path, slug: str, start_date: str, end_date: str) -> list[dict]:
    """Return GA4 daily metrics for a project in date range."""
    return _query_rows(
        db_path,
        """SELECT date, sessions, users, new_users, pageviews,
                  avg_session_duration, bounce_rate, conversions
           FROM ga_daily
           WHERE project_slug = ? AND date >= ? AND date <= ?
           ORDER BY date""",
        (slug, start_date, end_date),
        label=f"ga_daily for '{slug}'",
    )


def get_gsc_daily(db_path: Path, slug: str, start_date: str, end_date: str) -> list[dict]:
    """Return GSC daily metrics for a project in date range."""
    return _query_rows(
        db_path,
        """SELECT date, clicks, impressions, ctr, avg_position
           FROM gsc_daily
           WHERE project_slug = ? AND date >= ? AND date <= ?
           ORDER BY date""",
        (slug, start_date, end_date),
        label=f"gsc_daily for '{slug}'",
    )


def get_top_pages(
    db_path: Path, slug: str, start_date: str, end_date: str, *, limit: int = 10
) -> list[dict]:
    """Return top pages by pageviews, aggregated across date range."""
    return _query_rows(
        db_path,
        """SELECT page_path, SUM(pageviews) AS pageviews, SUM(sessions) AS sessions,
                  SUM(avg_time_on_page * sessions) * 1.0 / NULLIF(SUM(sessions), 0)
                      AS avg_time_on_page
           FROM ga_top_pages
           WHERE project_slug = ? AND date >= ? AND date <= ?
           GROUP BY page_path
           ORDER BY pageviews DESC
           LIMIT ?""",
        (slug, start_date, end_date, limit),
        label=f"ga_top_pages for '{slug}'",
    )


def get_top_queries(
    db_path: Path, slug: str, start_date: str, end_date: str, *, limit: int = 20
) -> list[dict]:
    """Return top search queries by clicks, aggregated across date range."""
    return _query_rows(
        db_path,
        """SELECT query, SUM(clicks) AS clicks, SUM(impressions) AS impressions,
                  SUM(clicks) * 1.0 / NULLIF(SUM(impressions), 0) AS ctr,
                  SUM(position * impressions) * 1.0 / NULLIF(SUM(impressions), 0)
                      AS position
           FROM gsc_top_queries
           WHERE project_slug = ? AND date >= ? AND date <= ?
           GROUP BY query
           ORDER BY clicks DESC
           LIMIT ?""",
        (slug, start_date, end_date, limit),
        label=f"gsc_top_queries for '{slug}'",
    )
