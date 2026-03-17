# Run all checks
check: lint typecheck test

# Format code
fmt:
    uv run ruff format src/ tests/

# Lint and auto-fix
lint:
    uv run ruff check --fix src/ tests/

# Type check
typecheck:
    uv run ty check src/

# Run tests
test:
    uv run pytest tests/ -v

# Run tests with coverage
test-cov:
    uv run pytest tests/ -v --cov=sites_report --cov-report=term-missing

# Fetch data (dev shortcut)
fetch *ARGS:
    uv run sites-report fetch {{ARGS}}

# Generate daily report and open in browser (DATE: YYYY-MM-DD, default: yesterday)
daily DATE="" *ARGS:
    uv run sites-report report --schedule daily --no-send --output report.html --preview {{ if DATE != "" { "--date " + DATE } else { "" } }} {{ARGS}}

# Generate weekly report and open in browser (DATE: YYYY-MM-DD, any day in desired week)
weekly DATE="" *ARGS:
    uv run sites-report report --schedule weekly --no-send --output report.html --preview {{ if DATE != "" { "--date " + DATE } else { "" } }} {{ARGS}}

# Generate monthly report and open in browser (DATE: YYYY-MM-DD, any day in desired month)
monthly DATE="" *ARGS:
    uv run sites-report report --schedule monthly --no-send --output report.html --preview {{ if DATE != "" { "--date " + DATE } else { "" } }} {{ARGS}}
