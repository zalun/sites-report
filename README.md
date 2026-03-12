# Sites Report

Daily, weekly, and monthly site analytics reports from Google Analytics 4, Google Search Console, and Vercel — delivered via email.

## Features

- **Multi-source analytics** — GA4 (traffic), GSC (search performance), Vercel (infrastructure)
- **Flexible scheduling** — daily, weekly, or monthly reports per recipient
- **AI-powered highlights** — automated insights via Claude CLI
- **Embedded charts** — trend lines, top pages, top queries
- **SQLite storage** — local database, no external services
- **Subscription model** — different recipients can get different projects at different frequencies

## Installation

Requires **Python 3.14+** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/zalun/sites-report.git
cd sites-report
uv sync
```

The `sites-report` CLI is now available:

```bash
sites-report --help
```

## Configuration

Copy the example config and edit it:

```bash
mkdir -p ~/.sites-report
cp config.example.toml ~/.sites-report/config.toml
```

The config file uses TOML format with these sections:

### `[email]` — SMTP settings (required)

```toml
[email]
smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_user = "user@gmail.com"
smtp_password_env = "SITES_REPORT_SMTP_PASSWORD"
from_address = "user@gmail.com"
```

Use `smtp_password_env` to read the password from an environment variable (recommended). Alternatively, use `smtp_password` for inline plaintext (not recommended).

### `[google]` — Google API credentials

```toml
[google]
service_account_key = "credentials/service-account.json"
```

Relative paths are resolved against the config file's parent directory (`~/.sites-report/`).

### `[vercel]` — Vercel API token (optional)

```toml
[vercel]
api_token_env = "SITES_REPORT_VERCEL_TOKEN"
```

### `[[projects]]` — Data sources

Define one or more projects. Each must have at least one data source:

```toml
[[projects]]
name = "My Website"
slug = "my-website"
ga4_property_id = "properties/123456789"    # optional
gsc_site_url = "https://example.com"        # optional
vercel_project_id = "prj_abc123"            # optional
```

### `[[subscriptions]]` — Report delivery

Define who receives reports and at what frequency:

```toml
[[subscriptions]]
recipient = "you@example.com"
projects = ["my-website"]
schedule = "daily"    # daily | weekly | monthly
```

A recipient can have multiple subscriptions at different frequencies.

See `config.example.toml` for a complete example.

## Google API Setup

1. Create a [Google Cloud project](https://console.cloud.google.com/) (or use an existing one)
2. Enable the **Google Analytics Data API** and **Search Console API**
3. Create a **service account** and download the JSON key
4. Save the key to `~/.sites-report/credentials/service-account.json`
5. Grant the service account access:
   - **GA4**: Add as **Viewer** in Admin > Property access management
   - **GSC**: Add as **User** in Settings > Users and permissions

## Quick Start

```bash
# Set SMTP password
export SITES_REPORT_SMTP_PASSWORD="your-app-password"

# Initialize database
sites-report init

# Fetch yesterday's data
sites-report fetch

# Generate and send daily reports
sites-report report --schedule daily

# Preview a report locally
sites-report report --schedule daily --output report.html --preview
```

## CLI Reference

### `sites-report init`

Initialize the database and verify configuration.

### `sites-report fetch`

Fetch analytics data from configured sources.

```
--date TEXT        Date to fetch (YYYY-MM-DD, default: yesterday)
--project TEXT     Fetch only this project slug
--range INTEGER    Number of days to fetch ending at --date (default: 1)
```

Examples:

```bash
sites-report fetch                              # yesterday
sites-report fetch --date 2026-03-01            # specific date
sites-report fetch --range 30                   # last 30 days
sites-report fetch --project my-website         # single project
```

### `sites-report report`

Generate and optionally send analytics reports.

```
--schedule TEXT     daily | weekly | monthly (required)
--date TEXT         Report date (YYYY-MM-DD, default: auto per schedule)
--no-send           Generate without sending email
--output PATH       Write HTML to file (implies --no-send)
--preview           Open in browser after generating (requires --output)
```

Examples:

```bash
sites-report report --schedule daily                          # send daily reports
sites-report report --schedule weekly --no-send               # generate only
sites-report report --schedule daily --output report.html --preview  # local preview
```

### `sites-report db-status`

Show database health: schema version, table row counts, and date ranges.

### Global options

```
--config PATH      Path to config file (default: ~/.sites-report/config.toml)
--verbose          Enable debug logging
```

## Cron Scheduling

Data is always fetched daily. Reports run on their own schedule:

```cron
# Fetch data every day at 6:00 AM
0 6 * * * cd /path/to/sites-report && .venv/bin/sites-report fetch 2>&1 | logger -t sites-report

# Daily reports
0 6 * * * cd /path/to/sites-report && .venv/bin/sites-report report --schedule daily 2>&1 | logger -t sites-report

# Weekly reports (Monday)
0 6 * * 1 cd /path/to/sites-report && .venv/bin/sites-report report --schedule weekly 2>&1 | logger -t sites-report

# Monthly reports (1st of month)
0 6 1 * * cd /path/to/sites-report && .venv/bin/sites-report report --schedule monthly 2>&1 | logger -t sites-report
```

## Development

Requires [just](https://just.systems/) for task running.

```bash
just check      # lint + typecheck + test
just fmt        # format code
just lint       # ruff lint with auto-fix
just typecheck  # ty check
just test       # pytest
just test-cov   # pytest with coverage
```

### Tech stack

Python 3.14+ | Click | SQLite | matplotlib | Jinja2 | SMTP | httpx | google-api-python-client
