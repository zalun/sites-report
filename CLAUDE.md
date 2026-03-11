# Sites Report

Daily/weekly/monthly site analytics reports from GA4, GSC, and Vercel — delivered via email.

## Tech Stack

- Python 3.14+ (managed via `uv`)
- Click CLI
- SQLite (`sqlite3` stdlib)
- matplotlib (charts)
- Jinja2 (email templates)
- SMTP (email delivery)
- httpx (Vercel API)
- google-api-python-client / google-auth / google-analytics-data (Google APIs)

## Project Structure

- `src/sites_report/` — main package
- `src/sites_report/cli.py` — Click commands entry point
- `src/sites_report/collectors/` — data source collectors (GA4, GSC, Vercel)
- `src/sites_report/reports/` — report builder, charts, templates
- `~/.sites-report/` — runtime data directory (config, DB, credentials)
  - `config.toml` — TOML configuration
  - `data/sites-report.db` — SQLite database
  - `credentials/` — Google service account keys
- `docs/PLAN.md` — full system plan
- `docs/IDEAS.md` — future ideas

## CLI Entry Point

```
sites-report init
sites-report fetch [--date, --project, --range]
sites-report report --schedule daily|weekly|monthly [--no-send, --output, --preview]
sites-report db-status
```

## Dev Commands

```
just check    # lint + typecheck + test
just fmt      # format code
just lint     # ruff lint with auto-fix
just typecheck # ty check
just test     # pytest
just test-cov # pytest with coverage
```

## Conventions

- All docs and code in English
- Config in TOML (`~/.sites-report/config.toml`), override with `--config`
- Secrets via environment variables, never in files
- Data always fetched daily; reporting frequency per subscription
- Charts as CID-embedded PNG in emails, base64 in `--output` HTML
- Full style guide: `docs/STYLE.md`
