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
    get_ga_daily,
    get_gsc_daily,
    get_top_pages,
    get_top_queries,
    init_db,
    insert_ga_daily,
    insert_ga_top_pages,
    insert_gsc_daily,
    insert_gsc_top_queries,
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
        "idx_ga_events_lookup",
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

    with pytest.raises(DatabaseError, match="newer than supported"):
        init_db(db_path)


def test_get_db_status_raises_on_schema_version_mismatch(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (999,))
    conn.commit()
    conn.close()

    with pytest.raises(DatabaseError, match="schema version mismatch"):
        get_db_status(db_path)


def test_init_db_enables_wal_mode(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()

    assert mode[0] == "wal"


# ── Dataclass validation ──────────────────────────────────────────


def test_table_status_rejects_negative_row_count():
    with pytest.raises(ValueError, match="row_count must be non-negative"):
        TableStatus(
            name="ga_daily",
            row_count=-1,
            min_date=None,
            max_date=None,
            last_fetched_at=None,
        )


def test_table_status_rejects_empty_name():
    with pytest.raises(ValueError, match="name must not be empty"):
        TableStatus(
            name="",
            row_count=0,
            min_date=None,
            max_date=None,
            last_fetched_at=None,
        )


def test_db_status_rejects_invalid_schema_version():
    tables = tuple(
        TableStatus(name=t, row_count=0, min_date=None, max_date=None, last_fetched_at=None)
        for t in DATA_TABLES
    )
    with pytest.raises(ValueError, match="schema_version must be >= 1"):
        DbStatus(schema_version=0, tables=tables)


def test_db_status_rejects_wrong_table_names():
    tables = tuple(
        TableStatus(
            name="wrong",
            row_count=0,
            min_date=None,
            max_date=None,
            last_fetched_at=None,
        )
        for _ in DATA_TABLES
    )
    with pytest.raises(ValueError, match="expected tables"):
        DbStatus(schema_version=1, tables=tables)


# ── Insert helpers ────────────────────────────────────────────────


def test_insert_ga_daily_stores_row(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    data = {"sessions": 100, "users": 80, "pageviews": 200}
    insert_ga_daily(db_path, "my-site", "2025-03-01", data)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT project_slug, date, sessions, users, pageviews FROM ga_daily"
    ).fetchone()
    conn.close()

    assert row == ("my-site", "2025-03-01", 100, 80, 200)


def test_insert_ga_daily_replaces_existing(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    insert_ga_daily(db_path, "my-site", "2025-03-01", {"sessions": 100})
    insert_ga_daily(db_path, "my-site", "2025-03-01", {"sessions": 200})

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT sessions FROM ga_daily").fetchone()
    count = conn.execute("SELECT COUNT(*) FROM ga_daily").fetchone()
    conn.close()

    assert row[0] == 200
    assert count[0] == 1


def test_insert_gsc_daily_stores_row(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    data = {"clicks": 50, "impressions": 1000, "ctr": 0.05, "avg_position": 3.2}
    insert_gsc_daily(db_path, "my-site", "2025-03-01", data)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT project_slug, date, clicks, impressions, ctr, avg_position FROM gsc_daily"
    ).fetchone()
    conn.close()

    assert row == ("my-site", "2025-03-01", 50, 1000, 0.05, 3.2)


def test_insert_ga_top_pages_stores_rows(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    pages = [
        {"page_path": "/home", "pageviews": 100, "sessions": 80, "avg_time_on_page": 30.5},
        {"page_path": "/about", "pageviews": 50, "sessions": 40, "avg_time_on_page": 20.0},
    ]
    insert_ga_top_pages(db_path, "my-site", "2025-03-01", pages)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT page_path, pageviews FROM ga_top_pages ORDER BY pageviews DESC"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0] == ("/home", 100)
    assert rows[1] == ("/about", 50)


def test_insert_ga_top_pages_replaces_stale_data(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    old_pages = [
        {"page_path": "/old", "pageviews": 10, "sessions": 5, "avg_time_on_page": 1.0},
    ]
    insert_ga_top_pages(db_path, "my-site", "2025-03-01", old_pages)

    new_pages = [
        {"page_path": "/new1", "pageviews": 100, "sessions": 80, "avg_time_on_page": 30.5},
        {"page_path": "/new2", "pageviews": 50, "sessions": 40, "avg_time_on_page": 20.0},
    ]
    insert_ga_top_pages(db_path, "my-site", "2025-03-01", new_pages)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT page_path FROM ga_top_pages WHERE project_slug='my-site' AND date='2025-03-01'"
    ).fetchall()
    conn.close()

    paths = {r[0] for r in rows}
    assert paths == {"/new1", "/new2"}


def test_insert_gsc_top_queries_stores_rows(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    queries = [
        {
            "query": "python tutorial",
            "clicks": 20,
            "impressions": 500,
            "ctr": 0.04,
            "position": 5.1,
        },
        {
            "query": "flask guide",
            "clicks": 10,
            "impressions": 300,
            "ctr": 0.03,
            "position": 8.2,
        },
    ]
    insert_gsc_top_queries(db_path, "my-site", "2025-03-01", queries)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT query, clicks FROM gsc_top_queries ORDER BY clicks DESC"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0] == ("python tutorial", 20)
    assert rows[1] == ("flask guide", 10)


def test_insert_gsc_top_queries_replaces_stale_data(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    old = [{"query": "old query", "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 3.0}]
    insert_gsc_top_queries(db_path, "my-site", "2025-03-01", old)

    new = [
        {"query": "new query 1", "clicks": 20, "impressions": 500, "ctr": 0.04, "position": 5.1},
        {"query": "new query 2", "clicks": 10, "impressions": 300, "ctr": 0.03, "position": 8.2},
    ]
    insert_gsc_top_queries(db_path, "my-site", "2025-03-01", new)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT query FROM gsc_top_queries WHERE project_slug='my-site' AND date='2025-03-01'"
    ).fetchall()
    conn.close()

    queries = {r[0] for r in rows}
    assert queries == {"new query 1", "new query 2"}


# ── Query helpers ──────────────────────────────────────────────────


def test_get_ga_daily_returns_rows_in_date_order(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_ga_daily(db_path, "site-a", "2025-03-03", {"sessions": 30})
    insert_ga_daily(db_path, "site-a", "2025-03-01", {"sessions": 10})
    insert_ga_daily(db_path, "site-a", "2025-03-02", {"sessions": 20})

    rows = get_ga_daily(db_path, "site-a", "2025-03-01", "2025-03-03")

    assert len(rows) == 3
    assert [r["date"] for r in rows] == ["2025-03-01", "2025-03-02", "2025-03-03"]
    assert [r["sessions"] for r in rows] == [10, 20, 30]


def test_get_ga_daily_filters_by_slug(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_ga_daily(db_path, "site-a", "2025-03-01", {"sessions": 10})
    insert_ga_daily(db_path, "site-b", "2025-03-01", {"sessions": 99})

    rows = get_ga_daily(db_path, "site-a", "2025-03-01", "2025-03-01")

    assert len(rows) == 1
    assert rows[0]["sessions"] == 10


def test_get_ga_daily_returns_empty_for_no_data(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    rows = get_ga_daily(db_path, "site-a", "2025-03-01", "2025-03-07")

    assert rows == []


def test_get_gsc_daily_returns_rows_in_date_order(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_gsc_daily(db_path, "site-a", "2025-03-02", {"clicks": 20})
    insert_gsc_daily(db_path, "site-a", "2025-03-01", {"clicks": 10})

    rows = get_gsc_daily(db_path, "site-a", "2025-03-01", "2025-03-02")

    assert len(rows) == 2
    assert [r["date"] for r in rows] == ["2025-03-01", "2025-03-02"]
    assert [r["clicks"] for r in rows] == [10, 20]


def test_get_gsc_daily_filters_by_slug(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_gsc_daily(db_path, "site-a", "2025-03-01", {"clicks": 10})
    insert_gsc_daily(db_path, "site-b", "2025-03-01", {"clicks": 99})

    rows = get_gsc_daily(db_path, "site-a", "2025-03-01", "2025-03-01")

    assert len(rows) == 1
    assert rows[0]["clicks"] == 10


def test_get_top_pages_aggregates_across_days(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_ga_top_pages(
        db_path,
        "site-a",
        "2025-03-01",
        [
            {"page_path": "/home", "pageviews": 100, "sessions": 80, "avg_time_on_page": 30.0},
            {"page_path": "/about", "pageviews": 50, "sessions": 40, "avg_time_on_page": 20.0},
        ],
    )
    insert_ga_top_pages(
        db_path,
        "site-a",
        "2025-03-02",
        [
            {"page_path": "/home", "pageviews": 120, "sessions": 90, "avg_time_on_page": 35.0},
        ],
    )

    rows = get_top_pages(db_path, "site-a", "2025-03-01", "2025-03-02")

    assert rows[0]["page_path"] == "/home"
    assert rows[0]["pageviews"] == 220  # 100 + 120
    assert rows[0]["sessions"] == 170  # 80 + 90
    # avg_time_on_page is weighted: (30.0*80 + 35.0*90) / 170 ≈ 32.647
    assert abs(rows[0]["avg_time_on_page"] - (30.0 * 80 + 35.0 * 90) / 170) < 1e-6


def test_get_top_pages_respects_limit(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    pages = [
        {"page_path": f"/page-{i}", "pageviews": 100 - i, "sessions": 50, "avg_time_on_page": 10.0}
        for i in range(15)
    ]
    insert_ga_top_pages(db_path, "site-a", "2025-03-01", pages)

    rows = get_top_pages(db_path, "site-a", "2025-03-01", "2025-03-01", limit=5)

    assert len(rows) == 5


def test_get_top_queries_aggregates_across_days(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    insert_gsc_top_queries(
        db_path,
        "site-a",
        "2025-03-01",
        [
            {
                "query": "python tutorial",
                "clicks": 20,
                "impressions": 500,
                "ctr": 0.04,
                "position": 5.0,
            },
        ],
    )
    insert_gsc_top_queries(
        db_path,
        "site-a",
        "2025-03-02",
        [
            {
                "query": "python tutorial",
                "clicks": 30,
                "impressions": 600,
                "ctr": 0.05,
                "position": 4.0,
            },
        ],
    )

    rows = get_top_queries(db_path, "site-a", "2025-03-01", "2025-03-02")

    assert rows[0]["query"] == "python tutorial"
    assert rows[0]["clicks"] == 50  # 20 + 30
    assert rows[0]["impressions"] == 1100  # 500 + 600
    # CTR is weighted: 50 / 1100 ≈ 0.04545
    assert abs(rows[0]["ctr"] - 50 / 1100) < 1e-6
    # Position is weighted: (5.0*500 + 4.0*600) / 1100 ≈ 4.4545
    assert abs(rows[0]["position"] - (5.0 * 500 + 4.0 * 600) / 1100) < 1e-6


def test_get_top_queries_respects_limit(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    queries = [
        {
            "query": f"query-{i}",
            "clicks": 100 - i,
            "impressions": 1000,
            "ctr": 0.05,
            "position": 3.0,
        }
        for i in range(25)
    ]
    insert_gsc_top_queries(db_path, "site-a", "2025-03-01", queries)

    rows = get_top_queries(db_path, "site-a", "2025-03-01", "2025-03-01", limit=10)

    assert len(rows) == 10


def test_get_top_queries_returns_empty_for_no_data(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    rows = get_top_queries(db_path, "site-a", "2025-03-01", "2025-03-07")

    assert rows == []


def test_query_helpers_raise_on_missing_db(tmp_path):
    db_path = tmp_path / "nonexistent.db"
    with pytest.raises(DatabaseError, match="Database file not found"):
        get_ga_daily(db_path, "site-a", "2025-03-01", "2025-03-07")
