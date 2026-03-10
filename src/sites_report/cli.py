"""Click CLI entry point for sites-report."""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

import click

from sites_report.collectors.base import CollectorError
from sites_report.config import Config, ConfigError, load_config
from sites_report.db import (
    DatabaseError,
    get_db_status,
    init_db,
    insert_ga_daily,
    insert_ga_top_pages,
    insert_gsc_daily,
    insert_gsc_top_queries,
)


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
    logger = logging.getLogger(__name__)
    cfg = _load_config(ctx)

    # Parse target date
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

    # Filter projects
    projects = cfg.projects
    if project_slug:
        projects = tuple(p for p in projects if p.slug == project_slug)
        if not projects:
            click.echo(f"Unknown project slug: {project_slug!r}", err=True)
            raise SystemExit(1)

    # Ensure DB exists
    try:
        init_db(cfg.db_path)
    except DatabaseError as exc:
        click.echo(f"Database error: {exc}", err=True)
        raise SystemExit(1) from exc

    # Instantiate collectors
    ga4_collector = None
    gsc_collector = None
    if cfg.google:
        try:
            from sites_report.collectors.analytics import GA4Collector

            ga4_collector = GA4Collector(cfg.google)
        except ImportError as exc:
            logger.error("GA4 dependencies not installed: %s", exc)
            click.echo(f"GA4 collector unavailable (missing dependency): {exc}", err=True)
        except CollectorError as exc:
            logger.error("Cannot initialize GA4 collector: %s", exc)
            click.echo(f"GA4 collector unavailable: {exc}", err=True)
        try:
            from sites_report.collectors.search_console import GSCCollector

            gsc_collector = GSCCollector(cfg.google)
        except ImportError as exc:
            logger.error("GSC dependencies not installed: %s", exc)
            click.echo(f"GSC collector unavailable (missing dependency): {exc}", err=True)
        except CollectorError as exc:
            logger.error("Cannot initialize GSC collector: %s", exc)
            click.echo(f"GSC collector unavailable: {exc}", err=True)

    succeeded = 0
    failed = 0
    failures: list[str] = []

    for date in dates:
        date_iso = date.isoformat()
        for project in projects:
            # GA4 daily
            if project.ga4_property_id and ga4_collector:
                try:
                    daily = ga4_collector.fetch(project, date)
                    insert_ga_daily(cfg.db_path, project.slug, date_iso, daily)
                    logger.info("GA4 daily %s %s OK", project.slug, date_iso)
                    succeeded += 1
                except (CollectorError, DatabaseError) as exc:
                    msg = f"GA4 daily {project.slug} {date_iso}: {exc}"
                    logger.error(msg)
                    failures.append(msg)
                    failed += 1

            # GA4 top pages
            if project.ga4_property_id and ga4_collector:
                try:
                    top_pages = ga4_collector.fetch_top_pages(project, date)
                    insert_ga_top_pages(cfg.db_path, project.slug, date_iso, top_pages)
                    logger.info("GA4 top_pages %s %s OK", project.slug, date_iso)
                    succeeded += 1
                except (CollectorError, DatabaseError) as exc:
                    msg = f"GA4 top_pages {project.slug} {date_iso}: {exc}"
                    logger.error(msg)
                    failures.append(msg)
                    failed += 1

            # GSC daily
            if project.gsc_site_url and gsc_collector:
                try:
                    daily = gsc_collector.fetch(project, date)
                    insert_gsc_daily(cfg.db_path, project.slug, date_iso, daily)
                    logger.info("GSC daily %s %s OK", project.slug, date_iso)
                    succeeded += 1
                except (CollectorError, DatabaseError) as exc:
                    msg = f"GSC daily {project.slug} {date_iso}: {exc}"
                    logger.error(msg)
                    failures.append(msg)
                    failed += 1

            # GSC top queries
            if project.gsc_site_url and gsc_collector:
                try:
                    top_queries = gsc_collector.fetch_top_queries(project, date)
                    insert_gsc_top_queries(cfg.db_path, project.slug, date_iso, top_queries)
                    logger.info("GSC top_queries %s %s OK", project.slug, date_iso)
                    succeeded += 1
                except (CollectorError, DatabaseError) as exc:
                    msg = f"GSC top_queries {project.slug} {date_iso}: {exc}"
                    logger.error(msg)
                    failures.append(msg)
                    failed += 1

            # Vercel -- not yet implemented
            if project.vercel_project_id:
                logger.debug(
                    "Vercel collector not implemented, skipping %s", project.slug
                )

    # Summary
    total = succeeded + failed
    if total == 0:
        click.echo("No fetch operations were attempted.")
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
