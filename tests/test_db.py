import sqlite3
from pathlib import Path

import pytest

from sites_report.db import (
    DATA_TABLES,
    SCHEMA_VERSION,
    DatabaseError,
    DbStatus,
    TableStatus,
    get_db_status,
    init_db,
)

# ── Happy path ─────────────────────────────────────────────────────


def test_init_db_creates_database_file(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    assert db_path.exists()


def test_init_db_creates_parent_directories(tmp_path):
    db_path = tmp_path / "nested" / "dirs" / "test.db"
    init_db(db_path)

    assert db_path.exists()


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    table_names = {row[0] for row in rows}
    expected = {"schema_version", *DATA_TABLES}
    assert expected.issubset(table_names)


def test_init_db_creates_indexes(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()

    index_names = {row[0] for row in rows}
    expected = {
        "idx_ga_daily_lookup",
        "idx_gsc_daily_lookup",
        "idx_gsc_queries_lookup",
        "idx_ga_pages_lookup",
        "idx_vercel_daily_lookup",
    }
    assert expected == index_names


def test_init_db_sets_schema_version(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    conn.close()

    assert row[0] == SCHEMA_VERSION


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
    conn.close()

    assert rows[0] == 1


def test_get_db_status_returns_empty_database(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    status = get_db_status(db_path)

    assert isinstance(status, DbStatus)
    assert status.schema_version == SCHEMA_VERSION
    assert len(status.tables) == len(DATA_TABLES)
    for ts in status.tables:
        assert isinstance(ts, TableStatus)
        assert ts.row_count == 0
        assert ts.min_date is None
        assert ts.max_date is None
        assert ts.last_fetched_at is None


def test_get_db_status_reflects_inserted_data(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO ga_daily (project_slug, date, sessions) VALUES (?, ?, ?)",
        ("my-site", "2025-01-15", 100),
    )
    conn.commit()
    conn.close()

    status = get_db_status(db_path)
    ga = next(t for t in status.tables if t.name == "ga_daily")
    assert ga.row_count == 1
    assert ga.min_date == "2025-01-15"
    assert ga.max_date == "2025-01-15"
    assert ga.last_fetched_at is not None


def test_get_db_status_returns_correct_date_range(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO gsc_daily (project_slug, date, clicks) VALUES (?, ?, ?)",
        ("site-a", "2025-01-10", 50),
    )
    conn.execute(
        "INSERT INTO gsc_daily (project_slug, date, clicks) VALUES (?, ?, ?)",
        ("site-a", "2025-01-20", 75),
    )
    conn.execute(
        "INSERT INTO gsc_daily (project_slug, date, clicks) VALUES (?, ?, ?)",
        ("site-b", "2025-01-15", 60),
    )
    conn.commit()
    conn.close()

    status = get_db_status(db_path)
    gsc = next(t for t in status.tables if t.name == "gsc_daily")
    assert gsc.row_count == 3
    assert gsc.min_date == "2025-01-10"
    assert gsc.max_date == "2025-01-20"


def test_get_db_status_returns_all_five_data_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    status = get_db_status(db_path)
    table_names = tuple(t.name for t in status.tables)
    assert table_names == DATA_TABLES


def test_insert_or_replace_updates_existing_row(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO ga_daily (project_slug, date, sessions) VALUES (?, ?, ?)",
        ("my-site", "2025-01-15", 100),
    )
    conn.commit()

    conn.execute(
        "INSERT OR REPLACE INTO ga_daily (project_slug, date, sessions) VALUES (?, ?, ?)",
        ("my-site", "2025-01-15", 200),
    )
    conn.commit()

    row = conn.execute(
        "SELECT sessions FROM ga_daily WHERE project_slug=? AND date=?",
        ("my-site", "2025-01-15"),
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM ga_daily").fetchone()
    conn.close()

    assert row[0] == 200
    assert count[0] == 1


# ── Error cases ────────────────────────────────────────────────────


def test_get_db_status_raises_on_missing_database(tmp_path):
    db_path = tmp_path / "nonexistent.db"
    with pytest.raises(DatabaseError, match="Database file not found"):
        get_db_status(db_path)


def test_init_db_raises_on_invalid_path():
    db_path = Path("/dev/null/impossible/test.db")
    with pytest.raises(DatabaseError):
        init_db(db_path)


def test_get_db_status_raises_on_corrupt_database(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_text("this is not a sqlite database")
    with pytest.raises(DatabaseError):
        get_db_status(db_path)


def test_get_db_status_raises_on_uninitialized_database(tmp_path):
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    with pytest.raises(DatabaseError):
        get_db_status(db_path)


def test_init_db_raises_on_schema_version_mismatch(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (999,))
    conn.commit()
    conn.close()

    with pytest.raises(DatabaseError, match="schema version mismatch"):
        init_db(db_path)


# ── Dataclass validation ──────────────────────────────────────────


def test_table_status_rejects_negative_row_count():
    with pytest.raises(ValueError, match="row_count must be non-negative"):
        TableStatus(
            name="ga_daily", row_count=-1,
            min_date=None, max_date=None, last_fetched_at=None,
        )


def test_db_status_rejects_invalid_schema_version():
    tables = tuple(
        TableStatus(name=t, row_count=0, min_date=None, max_date=None, last_fetched_at=None)
        for t in DATA_TABLES
    )
    with pytest.raises(ValueError, match="schema_version must be >= 1"):
        DbStatus(schema_version=0, tables=tables)


def test_db_status_rejects_wrong_table_count():
    with pytest.raises(ValueError, match="expected 5 tables"):
        DbStatus(schema_version=1, tables=())
