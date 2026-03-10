# Code Style Guide

## Tooling

- **Type checker**: `ty`
- **Linter/formatter**: `ruff` (linting + formatting in one)
- **Task runner**: `justfile` (via `just`)
- **Package manager**: `uv`

## Python Style

- Python 3.14+
- Use modern type hints (`str | None` not `Optional[str]`, `list[str]` not `List[str]`)
- Use `pathlib.Path` over `os.path`
- Use `tomllib` (stdlib) for config parsing
- Use `logging` (stdlib) — no print statements for operational output
- Use `dataclasses` or `NamedTuple` for structured data; avoid plain dicts for internal data passing
- Prefer early returns over deep nesting
- No wildcard imports
- Imports ordered by: stdlib, third-party, local (ruff handles this)
- Docstrings only on public API and non-obvious functions
- Keep functions short and focused — if it needs a comment block explaining a section, extract it

## Project Layout

```
src/sites_report/
├── __init__.py
├── cli.py
├── config.py
├── db.py
├── email.py
├── collectors/
│   ├── __init__.py
│   ├── base.py
│   ├── analytics.py
│   ├── search_console.py
│   └── vercel.py
└── reports/
    ├── __init__.py
    ├── builder.py
    ├── charts.py
    └── templates/
        └── report.html
```

## Error Handling

- Let exceptions propagate unless there's a specific recovery action
- Use custom exception classes for domain errors (e.g., `CollectorError`, `ConfigError`)
- Never silently swallow exceptions
- Log errors with context (project slug, date, source) before re-raising

## Testing

### Directory Structure

Mirror `src/sites_report/` subdirectories:

```
tests/
├── conftest.py
├── test_config.py
├── test_db.py
├── test_email.py
├── collectors/
│   ├── conftest.py
│   ├── test_collectors_analytics.py
│   ├── test_collectors_search_console.py
│   └── test_collectors_vercel.py
└── reports/
    ├── conftest.py
    ├── test_reports_builder.py
    └── test_reports_charts.py
```

### Conventions

- **pytest style only** — no test classes, plain functions
- **File naming**: `test_{subpackage}_{module}.py` (e.g., `test_collectors_analytics.py`)
- **Test naming**: `test_{method}_{scenario}` — describe what and why
  ```python
  def test_fetch_returns_empty_dict_for_missing_date():
  def test_fetch_raises_on_invalid_credentials():
  def test_parse_config_ignores_unknown_keys():
  ```

### Mocking

- Use `@mock.patch` decorator, not `with mock.patch()` context managers
- **Never use magic assert methods** (`assert_called_once_with`, `assert_called_with`, etc.)
- Instead, assert explicitly on `call_count` and `call_args`:
  ```python
  @mock.patch("sites_report.collectors.analytics.build")
  def test_fetch_calls_api_with_property_id(mock_build):
      fetch(project)
      assert mock_build.call_count == 1
      assert mock_build.call_args == mock.call("analyticsdata", "v1beta", credentials=mock.ANY)
  ```
- Use `mock.ANY` for arguments you don't care about
- Prefer dependency injection over patching when practical

### Fixtures

- Shared fixtures in `conftest.py` at the appropriate directory level
- Use `tmp_path` for database and file tests
- Create a `sample_config` fixture with realistic test data

## Justfile

Dev commands via `just`:

```just
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
```

## Ruff Configuration

In `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py314"
line-length = 99

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "BLE", "SIM", "RUF", "S110"]

[tool.ruff.lint.isort]
known-first-party = ["sites_report"]
```
