# Sites Report — System Plan

## Architecture Overview

**Tech stack**: Python 3.14+ (via `uv`), Click CLI, SQLite, matplotlib, Jinja2, SMTP

**CLI commands**:
- `sites-report init` — create database, verify config and API access
- `sites-report fetch` — fetch data for all projects (supports `--date`, `--project`, `--range` for backfill)
- `sites-report report` — generate charts + send email (supports `--no-send --output` for local preview)
- `sites-report db-status` — show data health

---

## Project Structure

```
sites-report/
├── pyproject.toml
├── config.toml                    # TOML configuration (gitignored)
├── config.example.toml            # Example configuration (committed)
├── credentials/                   # Google service account key (gitignored)
│   └── .gitkeep
├── src/sites_report/
│   ├── __init__.py
│   ├── cli.py                     # Click commands
│   ├── config.py                  # Config loading and validation
│   ├── db.py                      # SQLite schema + queries
│   ├── email.py                   # SMTP sending
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract collector
│   │   ├── analytics.py           # GA4 Data API
│   │   ├── search_console.py      # GSC API
│   │   └── vercel.py              # Vercel Analytics API
│   └── reports/
│       ├── __init__.py
│       ├── builder.py             # Report orchestration
│       ├── charts.py              # matplotlib charts
│       └── templates/
│           └── report.html        # Jinja2 email template
├── tests/
│   ├── conftest.py
│   ├── test_db.py
│   ├── test_collectors.py
│   ├── test_charts.py
│   └── test_reports.py
├── data/                          # SQLite database (gitignored)
│   └── .gitkeep
└── docs/
    └── PLAN.md
```

---

## Configuration (`config.toml`)

```toml
[general]
db_path = "data/sites-report.db"
log_level = "INFO"

[email]
smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_user = "user@gmail.com"
smtp_password_env = "SITES_REPORT_SMTP_PASSWORD"   # Read from environment variable
from_address = "user@gmail.com"

[google]
service_account_key = "credentials/service-account.json"

[vercel]
api_token_env = "SITES_REPORT_VERCEL_TOKEN"    # Read from environment variable

# --- Projects: define data sources ---
# All fields are optional — only configure the sources available for each project.

[[projects]]
name = "Project Alpha"
slug = "project-alpha"
ga4_property_id = "properties/123456789"
gsc_site_url = "https://alpha.example.com"
vercel_project_id = "prj_abc123"

[[projects]]
name = "Project Beta"
slug = "project-beta"
ga4_property_id = "properties/987654321"
gsc_site_url = "https://beta.example.com"
vercel_project_id = "prj_def456"

[[projects]]
name = "Project Gamma"
slug = "project-gamma"
ga4_property_id = "properties/111222333"
gsc_site_url = "https://gamma.example.com"
# No Vercel — not hosted there

[[projects]]
name = "Project Delta"
slug = "project-delta"
ga4_property_id = "properties/444555666"
gsc_site_url = "https://delta.example.com"
vercel_project_id = "prj_ghi789"

# --- Subscriptions: who gets what, and how often ---

[[subscriptions]]
recipient = "alice@example.com"
projects = ["project-alpha", "project-beta"]
schedule = "daily"                               # High-priority projects

[[subscriptions]]
recipient = "alice@example.com"
projects = ["project-gamma", "project-delta"]
schedule = "weekly"                              # Lower-priority — weekly digest

[[subscriptions]]
recipient = "bob@example.com"
projects = ["project-alpha", "project-gamma"]
schedule = "weekly"

[[subscriptions]]
recipient = "carol@example.com"
projects = ["project-gamma", "project-delta"]
schedule = "monthly"                             # Least involved — monthly digest
```

Notes:
- SMTP password read from an environment variable (never stored in the file).
- Each project has a `slug` used as a key in the database and file naming.
- **Projects** only define data sources (what to fetch). No schedule or recipients here. Data source fields are optional — only configure what's available per project.
- **Subscriptions** define who receives reports for which projects, and how often.
- **`schedule`**: `"daily"`, `"weekly"` (every Monday), or `"monthly"` (1st of each month).
- A recipient can have multiple subscriptions at different frequencies (e.g., Alice gets Alpha daily but Gamma weekly).
- The same project can appear in multiple subscriptions with different schedules.
- Data is **always fetched daily** for all projects (via cron). Only the _reporting_ frequency differs per subscription.
- Each subscription generates one email containing all its projects.

---

## SQLite Schema

```sql
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Daily Google Analytics metrics
CREATE TABLE IF NOT EXISTS ga_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,           -- 'YYYY-MM-DD'
    sessions INTEGER,
    users INTEGER,
    new_users INTEGER,
    pageviews INTEGER,
    avg_session_duration REAL,    -- seconds
    bounce_rate REAL,             -- 0.0-1.0
    conversions INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

-- Daily Google Search Console metrics
CREATE TABLE IF NOT EXISTS gsc_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,           -- 'YYYY-MM-DD'
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,                     -- 0.0-1.0
    avg_position REAL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

-- Top search queries from GSC (daily snapshot)
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

-- Top landing pages from GA (daily snapshot)
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

-- Daily Vercel Analytics metrics
CREATE TABLE IF NOT EXISTS vercel_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    date TEXT NOT NULL,           -- 'YYYY-MM-DD'
    requests INTEGER,
    unique_visitors INTEGER,
    pageviews INTEGER,
    avg_duration_ms REAL,        -- milliseconds
    p75_duration_ms REAL,        -- 75th percentile
    p95_duration_ms REAL,        -- 95th percentile
    errors INTEGER,              -- 4xx + 5xx responses
    bandwidth_bytes INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_slug, date)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ga_daily_lookup ON ga_daily(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_lookup ON gsc_daily(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_gsc_queries_lookup ON gsc_top_queries(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_ga_pages_lookup ON ga_top_pages(project_slug, date);
CREATE INDEX IF NOT EXISTS idx_vercel_daily_lookup ON vercel_daily(project_slug, date);
```

Notes:
- `UNIQUE` constraints with `INSERT OR REPLACE` make re-fetching idempotent (safe to re-run).
- `fetched_at` tracks data freshness for debugging.
- Dates stored as ISO-8601 text (sorts correctly in SQLite).
- Flat schema instead of generic key-value — easier to query and chart.
- Schema is the same for daily and weekly projects — data is always stored daily. The schedule only affects reporting.

---

## Google API Authentication

**Recommendation: Service Account** (not OAuth).

- Server-side/CLI tool, no browser consent flow needed.
- Single JSON key file, no token refresh dance.
- Works with both GA4 Data API and Search Console API.

Setup steps:
1. Create a Google Cloud project (or use an existing one).
2. Enable "Google Analytics Data API" and "Search Console API".
3. Create a service account, download JSON key to `credentials/`.
4. In GA4: add the service account email as a Viewer on each property.
5. In Search Console: add the service account email as a user for each site.

---

## Charts and Email Report

### Generated charts (per project):
1. **Sessions/Users trend** — line chart, last 30 days, yesterday highlighted.
2. **GSC Clicks/Impressions trend** — dual-axis line chart, 30 days.
3. **Top 10 Search Queries** — horizontal bar chart (clicks).
4. **Top 10 Pages** — horizontal bar chart (pageviews).

Charts rendered by `matplotlib` to PNG, base64-encoded and embedded in HTML email as `<img src="data:image/png;base64,...">`.

### Daily report email:
```
Subject: Sites Report (Daily): {date}

For each subscribed project:

  [Project Name header]
  [Date]

  --- Summary Table ---
  | Metric          | Yesterday | Same Day Last Week | Change |
  | Sessions        | 1,234     | 1,100              | +12%   |
  | Users           | 987       | 900                | +10%   |
  | Pageviews       | 3,456     | 3,200              | +8%    |
  | GSC Clicks      | 567       | 500                | +13%   |
  | GSC Impressions | 12,345    | 11,000             | +12%   |
  | Avg Position    | 15.2      | 16.1               | +0.9   |

  [Sessions/Users trend chart — last 30 days]
  [GSC Clicks/Impressions trend chart — last 30 days]
  [Top Queries bar chart]
  [Top Pages bar chart]
```

### Weekly report email:
```
Subject: Sites Report (Weekly): {week_start} to {week_end}

For each subscribed project:

  [Project Name header]
  [Week range]

  --- Summary Table ---
  | Metric          | This Week | Last Week | Change |
  | Sessions        | 8,500     | 7,800     | +9%    |
  | Users           | 6,200     | 5,900     | +5%    |
  | Pageviews       | 24,000    | 22,100    | +9%    |
  | GSC Clicks      | 3,900     | 3,500     | +11%   |
  | GSC Impressions | 85,000    | 78,000    | +9%    |
  | Avg Position    | 15.2      | 16.1      | +0.9   |

  [Sessions/Users trend chart — last 4 weeks]
  [GSC Clicks/Impressions trend chart — last 4 weeks]
  [Top Queries bar chart]
  [Top Pages bar chart]
```

### Monthly report email:
```
Subject: Sites Report (Monthly): {month_name} {year}

For each subscribed project:

  [Project Name header]
  [Month]

  --- Summary Table ---
  | Metric          | This Month | Last Month | Change |
  | Sessions        | 35,000     | 32,000     | +9%    |
  | Users           | 25,000     | 23,500     | +6%    |
  | Pageviews       | 95,000     | 88,000     | +8%    |
  | GSC Clicks      | 16,000     | 14,500     | +10%   |
  | GSC Impressions | 350,000    | 320,000    | +9%    |
  | Avg Position    | 14.8       | 15.5       | +0.7   |

  [Sessions/Users trend chart — last 6 months]
  [GSC Clicks/Impressions trend chart — last 6 months]
  [Top Queries bar chart]
  [Top Pages bar chart]
```

---

## Error Handling and Logging

- All API calls wrapped with retry (exponential backoff, max 3 attempts).
- Each collector logs success/failure per project per date.
- If one project fails, others still proceed. Failures collected and reported at the end.
- `fetch` exits with code 1 if any project failed (detectable in cron).
- Logs to stderr by default; `--verbose` flag increases to DEBUG level.
- Optional `--log-file` for cron usage.

---

## Scheduling (Cron)

Three cron entries, all at 6:00 AM CET. Data is fetched daily; the `report` command filters subscriptions by schedule type.

```
# Daily reports — every day at 6:00 AM CET
0 6 * * * cd /path/to/sites-report && .venv/bin/sites-report fetch && .venv/bin/sites-report report --schedule daily 2>&1 | logger -t sites-report

# Weekly reports — every Monday at 6:00 AM CET
0 6 * * 1 cd /path/to/sites-report && .venv/bin/sites-report report --schedule weekly 2>&1 | logger -t sites-report

# Monthly reports — 1st of each month at 6:00 AM CET
0 6 1 * * cd /path/to/sites-report && .venv/bin/sites-report report --schedule monthly 2>&1 | logger -t sites-report
```

Note: The daily cron handles `fetch` for all projects. Weekly and monthly only need `report` since data is already fetched. When multiple entries fire on the same day (e.g., 1st of month is a Monday), all applicable reports are sent.

---

## Implementation Phases

### Phase 1: Foundation
1. `uv init` with `pyproject.toml`, set up project structure.
2. `config.py` — TOML config loading and validation.
3. `db.py` — schema creation, insert/query helpers.
4. `cli.py` — skeleton with `init` and `db-status` commands.
5. Tests for config loading and database operations.

**Deliverable**: `sites-report init` works, creates the database.

### Phase 2: Data Collection
1. Google API authentication helper in `collectors/base.py`.
2. `collectors/analytics.py` — GA4 data fetcher.
3. `collectors/search_console.py` — GSC data fetcher.
4. Wire into `cli.py` `fetch` command.
5. Test with one real project, backfill a week of data.

**Deliverable**: `sites-report fetch` populates the database.

### Phase 3: Reports
1. `reports/charts.py` — chart generation functions.
2. `reports/templates/report.html` — Jinja2 template (handles both daily and weekly).
3. `reports/builder.py` — query data, generate charts, render HTML. Respects project schedule.
4. `cli.py` `report --no-send --output` for local testing.

**Deliverable**: `sites-report report --no-send --output test.html` produces a viewable report.

### Phase 4: Email Delivery
1. `email.py` — SMTP sending with inline images.
2. Wire into `report` command.
3. Test with real SMTP credentials.

**Deliverable**: `sites-report report` sends email.

### Phase 5: Polish and Scheduling
1. Error handling, retries, graceful degradation.
2. `--preview` flag (opens in browser).
3. Cron setup.
4. README with setup instructions.

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "sites-report"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "click>=8.1",
    "google-api-python-client>=2.100",
    "google-auth>=2.23",
    "google-analytics-data>=0.18",
    "httpx>=0.27",
    "matplotlib>=3.8",
    "jinja2>=3.1",
]

[project.scripts]
sites-report = "sites_report.cli:cli"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
]
```

Stdlib modules (no extra dependencies): `sqlite3`, `smtplib`, `email`, `tomllib`, `logging`.

---

## Decisions to Make

1. **One email per project or one combined digest?** (plan defaults to per-project)
2. **SMTP provider** — Gmail App Password, Fastmail, Mailgun, other?
3. **Additional data sources** beyond GA4/GSC? (collector pattern makes adding more easy)
4. **Backfill depth** — how many days back on first run? (recommended: 90 days)
