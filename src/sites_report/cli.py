"""Click CLI entry point for sites-report."""

from __future__ import annotations

import datetime
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from sites_report.collectors.base import CollectorError
from sites_report.config import Config, ConfigError, ProjectConfig, load_config
from sites_report.db import (
    DatabaseError,
    get_db_status,
    init_db,
    insert_ga_daily,
    insert_ga_top_pages,
    insert_gsc_daily,
    insert_gsc_top_queries,
)

logger = logging.getLogger(__name__)


def _setup_logging(log_level: str, *, verbose: bool) -> None:
    """Configure logging to stderr. Safe to call multiple times."""
    level = "DEBUG" if verbose else log_level
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _load_config(ctx: click.Context) -> Config:
    """Load config from path stored in Click context, exit on error."""
    config_path = ctx.obj["config_path"]
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        raise SystemExit(1) from exc
    _setup_logging(cfg.log_level, verbose=ctx.obj["verbose"])
    return cfg


@click.group()
@click.option(
    "--config",
    "config_path",
    default="config.toml",
    type=click.Path(exists=False),
    help="Path to TOML configuration file.",
)
@click.option("--verbose", is_flag=True, help="Enable DEBUG logging.")
@click.pass_context
def cli(ctx: click.Context, config_path: str, *, verbose: bool) -> None:
    """Sites Report — site analytics reports from GA4, GSC, and Vercel."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config_path)
    ctx.obj["verbose"] = verbose
    # Initial logging so errors during config loading are captured;
    # _load_config reconfigures with the config-file level via force=True.
    _setup_logging("INFO", verbose=verbose)


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create database and verify configuration."""
    cfg = _load_config(ctx)
    try:
        init_db(cfg.db_path)
    except DatabaseError as exc:
        click.echo(f"Database error: {exc}", err=True)
        raise SystemExit(1) from exc
    click.echo(f"Database initialized: {cfg.db_path}")


@cli.command("db-status")
@click.pass_context
def db_status(ctx: click.Context) -> None:
    """Show database health: row counts, date ranges, last fetch times."""
    cfg = _load_config(ctx)
    try:
        status = get_db_status(cfg.db_path)
    except DatabaseError as exc:
        click.echo(f"Database error: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo(f"Schema version: {status.schema_version}")
    click.echo(f"Database: {cfg.db_path}")
    click.echo()

    header = f"{'Table':<20} {'Rows':>6}    {'Date range':<27} {'Last fetched'}"
    click.echo(header)
    click.echo("\u2500" * len(header))
    for t in status.tables:
        if t.row_count == 0:
            date_range = "\u2014"
            last_fetched = "\u2014"
        else:
            date_range = f"{t.min_date} .. {t.max_date}"
            last_fetched = t.last_fetched_at or "\u2014"
        click.echo(f"{t.name:<20} {t.row_count:>6}    {date_range:<27} {last_fetched}")


def _init_collector(
    name: str,
    factory: Callable[[], Any],
) -> Any | None:
    """Try to instantiate a collector; return None on failure."""
    try:
        return factory()
    except ImportError as exc:
        logger.error("%s dependencies not installed: %s", name, exc)
        click.echo(f"{name} collector unavailable (missing dependency): {exc}", err=True)
    except CollectorError as exc:
        logger.error("Cannot initialize %s collector: %s", name, exc)
        click.echo(f"{name} collector unavailable: {exc}", err=True)
    return None


def _run_fetch_op(
    label: str,
    fetch_fn: Callable[[], Any],
    insert_fn: Callable[[Any], None],
    slug: str,
    date_iso: str,
    failures: list[str],
) -> bool:
    """Run a single fetch + insert operation. Returns True on success."""
    try:
        data = fetch_fn()
        insert_fn(data)
        logger.info("%s %s %s OK", label, slug, date_iso)
    except (CollectorError, DatabaseError) as exc:
        msg = f"{label} {slug} {date_iso}: {exc}"
        logger.error(msg)
        failures.append(msg)
        return False
    except Exception as exc:
        msg = f"{label} {slug} {date_iso}: unexpected: {exc}"
        logger.exception(msg)
        failures.append(msg)
        return False
    return True


def _fetch_project(
    project: ProjectConfig,
    date: datetime.date,
    db_path: Path,
    ga4_collector: Any | None,
    gsc_collector: Any | None,
    failures: list[str],
) -> tuple[int, int]:
    """Fetch all sources for one project+date. Returns (succeeded, failed)."""
    ok = 0
    bad = 0
    date_iso = date.isoformat()

    if project.ga4_property_id and ga4_collector:
        if _run_fetch_op(
            "GA4 daily",
            lambda: ga4_collector.fetch(project, date),
            lambda d: insert_ga_daily(db_path, project.slug, date_iso, d),
            project.slug,
            date_iso,
            failures,
        ):
            ok += 1
        else:
            bad += 1

        if _run_fetch_op(
            "GA4 top_pages",
            lambda: ga4_collector.fetch_top_pages(project, date),
            lambda d: insert_ga_top_pages(db_path, project.slug, date_iso, d),
            project.slug,
            date_iso,
            failures,
        ):
            ok += 1
        else:
            bad += 1

    if project.gsc_site_url and gsc_collector:
        if _run_fetch_op(
            "GSC daily",
            lambda: gsc_collector.fetch(project, date),
            lambda d: insert_gsc_daily(db_path, project.slug, date_iso, d),
            project.slug,
            date_iso,
            failures,
        ):
            ok += 1
        else:
            bad += 1

        if _run_fetch_op(
            "GSC top_queries",
            lambda: gsc_collector.fetch_top_queries(project, date),
            lambda d: insert_gsc_top_queries(db_path, project.slug, date_iso, d),
            project.slug,
            date_iso,
            failures,
        ):
            ok += 1
        else:
            bad += 1

    if project.vercel_project_id:
        logger.debug("Vercel collector not implemented, skipping %s", project.slug)

    return ok, bad


@cli.command()
@click.option("--date", "date_str", default=None, help="Date YYYY-MM-DD (default: yesterday)")
@click.option("--project", "project_slug", default=None, help="Fetch only this project slug")
@click.option(
    "--range", "range_days", default=1, type=int, help="Number of days to fetch ending at --date"
)
@click.pass_context
def fetch(
    ctx: click.Context, date_str: str | None, project_slug: str | None, range_days: int
) -> None:
    """Fetch analytics data for configured projects."""
    cfg = _load_config(ctx)

    if date_str is None:
        end_date = datetime.date.today() - datetime.timedelta(days=1)
    else:
        try:
            end_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            click.echo(f"Invalid date format: {date_str!r} (expected YYYY-MM-DD)", err=True)
            raise SystemExit(1) from None

    if range_days < 1:
        click.echo("--range must be >= 1", err=True)
        raise SystemExit(1)

    dates = [end_date - datetime.timedelta(days=i) for i in range(range_days - 1, -1, -1)]

    projects = cfg.projects
    if project_slug:
        projects = tuple(p for p in projects if p.slug == project_slug)
        if not projects:
            click.echo(f"Unknown project slug: {project_slug!r}", err=True)
            raise SystemExit(1)

    try:
        init_db(cfg.db_path)
    except DatabaseError as exc:
        click.echo(f"Database error: {exc}", err=True)
        raise SystemExit(1) from exc

    # Instantiate collectors
    ga4_collector = None
    gsc_collector = None
    if cfg.google:
        google_cfg = cfg.google

        def _make_ga4():
            from sites_report.collectors.analytics import GA4Collector

            return GA4Collector(google_cfg)

        def _make_gsc():
            from sites_report.collectors.search_console import GSCCollector

            return GSCCollector(google_cfg)

        ga4_collector = _init_collector("GA4", _make_ga4)
        gsc_collector = _init_collector("GSC", _make_gsc)

    # Warn if configured sources have no working collector
    needs_ga4 = any(p.ga4_property_id for p in projects)
    needs_gsc = any(p.gsc_site_url for p in projects)
    if needs_ga4 and not ga4_collector:
        click.echo("Warning: projects require GA4 but collector is unavailable.", err=True)
    if needs_gsc and not gsc_collector:
        click.echo("Warning: projects require GSC but collector is unavailable.", err=True)

    succeeded = 0
    failed = 0
    failures: list[str] = []

    for date in dates:
        for project in projects:
            ok, bad = _fetch_project(
                project,
                date,
                cfg.db_path,
                ga4_collector,
                gsc_collector,
                failures,
            )
            succeeded += ok
            failed += bad

    # Summary
    total = succeeded + failed
    if total == 0:
        msg = "No fetch operations were attempted."
        if needs_ga4 or needs_gsc:
            click.echo(msg, err=True)
            raise SystemExit(1)
        click.echo(msg)
    else:
        click.echo(f"Fetched {succeeded}/{total} operations successfully.")
    if failures:
        click.echo(f"\n{len(failures)} failure(s):", err=True)
        for f in failures:
            click.echo(f"  - {f}", err=True)
        raise SystemExit(1)


@cli.command()
def report() -> None:
    """Generate and send analytics reports."""
    click.echo("Not implemented yet.", err=True)
    raise SystemExit(1)
