"""Click CLI entry point for sites-report."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from sites_report.config import Config, ConfigError, load_config
from sites_report.db import DatabaseError, get_db_status, init_db

logger = logging.getLogger(__name__)


def _setup_logging(log_level: str, *, verbose: bool) -> None:
    """Configure logging to stderr."""
    level = "DEBUG" if verbose else log_level
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_config(ctx: click.Context) -> Config:
    """Load config from path stored in Click context, exit on error."""
    config_path = ctx.obj["config_path"]
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
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
    # Set up basic logging before config is loaded so errors are captured
    _setup_logging("INFO", verbose=verbose)


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create database and verify configuration."""
    cfg = _load_config(ctx)
    try:
        init_db(cfg.db_path)
    except DatabaseError as exc:
        logger.error("Database error: %s", exc)
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
        logger.error("Database error: %s", exc)
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
def fetch() -> None:
    """Fetch analytics data for all projects."""
    click.echo("Not implemented yet.")
    raise SystemExit(1)


@cli.command()
def report() -> None:
    """Generate and send analytics reports."""
    click.echo("Not implemented yet.")
    raise SystemExit(1)
