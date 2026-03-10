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

# Generate report without sending
preview *ARGS:
    uv run sites-report report --no-send --output report.html {{ARGS}}
