"""Click CLI entry point for sites-report."""

from __future__ import annotations

import datetime
import logging
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from sites_report.collectors.base import CollectorError
from sites_report.config import (
    Config,
    ConfigError,
    ProjectConfig,
    Schedule,
    default_config_path,
    load_config,
)
from sites_report.db import (
    DatabaseError,
    get_db_status,
    get_ga_daily,
    get_gsc_daily,
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
    default=None,
    type=click.Path(exists=False),
    help="Path to TOML configuration file (default: ~/.sites-report/config.toml).",
)
@click.option("--verbose", is_flag=True, help="Enable DEBUG logging.")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, *, verbose: bool) -> None:
    """Sites Report — site analytics reports from GA4, GSC, and Vercel."""
    ctx.ensure_object(dict)
    if config_path is not None:
        ctx.obj["config_path"] = Path(config_path)
    else:
        try:
            ctx.obj["config_path"] = default_config_path()
        except ConfigError as exc:
            click.echo(f"Configuration error: {exc}", err=True)
            raise SystemExit(1) from exc
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

    ga4_collector, gsc_collector = _init_collectors(cfg)

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


def _init_collectors(cfg: Config) -> tuple[Any | None, Any | None]:
    """Instantiate GA4 and GSC collectors from config. Returns (ga4, gsc)."""
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
    return ga4_collector, gsc_collector


def _ensure_data_fetched(
    cfg: Config,
    report_date: datetime.date,
    schedule: Schedule,
) -> None:
    """Fetch missing data for the report date range if a prior fetch was skipped.

    This handles the common case where the scheduled fetch cron did not run
    (e.g. the machine was asleep) but the report cron fires later.
    Best-effort: failures are logged and reported but do not abort the report.

    Caller must have called ``init_db`` before invoking this function.
    """
    from sites_report.reports.builder import compute_date_ranges

    if not cfg.projects:
        return

    try:
        ranges = compute_date_ranges(schedule, report_date)
    except ValueError:
        logger.warning("Cannot compute date ranges for auto-backfill", exc_info=True)
        click.echo("Warning: could not determine date range for auto-backfill.", err=True)
        return

    days = (ranges.current_end - ranges.current_start).days + 1
    needed_dates = [ranges.current_start + datetime.timedelta(days=i) for i in range(days)]

    # Check which (date, project) pairs are missing data.
    # Only check sources the project is actually configured to collect.
    missing_pairs: list[tuple[datetime.date, ProjectConfig]] = []
    db_check_failed = False
    for d in needed_dates:
        d_iso = d.isoformat()
        for project in cfg.projects:
            needs_ga = bool(project.ga4_property_id)
            needs_gsc = bool(project.gsc_site_url)
            if not needs_ga and not needs_gsc:
                continue
            try:
                has_ga = not needs_ga or bool(
                    get_ga_daily(cfg.db_path, project.slug, d_iso, d_iso)
                )
                has_gsc = not needs_gsc or bool(
                    get_gsc_daily(cfg.db_path, project.slug, d_iso, d_iso)
                )
            except DatabaseError:
                logger.error(
                    "DB error checking data for '%s' on %s",
                    project.slug,
                    d_iso,
                    exc_info=True,
                )
                db_check_failed = True
                break
            if not has_ga or not has_gsc:
                missing_pairs.append((d, project))
        if db_check_failed:
            break

    if db_check_failed:
        click.echo(
            "Warning: could not verify data completeness (database error).",
            err=True,
        )
        return

    if not missing_pairs:
        return

    missing_dates = sorted({d for d, _ in missing_pairs})
    logger.info(
        "Auto-backfill: fetching %d missing date(s): %s", len(missing_dates), missing_dates
    )

    ga4_collector, gsc_collector = _init_collectors(cfg)

    failures: list[str] = []
    for date, project in missing_pairs:
        _fetch_project(project, date, cfg.db_path, ga4_collector, gsc_collector, failures)

    if failures:
        logger.warning("Auto-backfill had %d failure(s): %s", len(failures), failures)
        click.echo(
            f"Warning: auto-backfill had {len(failures)} failure(s); "
            "report may contain incomplete data.",
            err=True,
        )
        for f in failures:
            click.echo(f"  - {f}", err=True)
    else:
        logger.info("Auto-backfill complete")


def _default_report_date(schedule: Schedule, today: datetime.date | None = None) -> datetime.date:
    """Compute a sensible default report date for the given schedule.

    For daily: yesterday.
    For weekly: last Sunday (last day of the previous full week).
        ``compute_date_ranges`` uses this to derive the Mon-Sun current period.
    For monthly: last day of the previous month.
    """
    if today is None:
        today = datetime.date.today()
    if schedule == Schedule.DAILY:
        return today - datetime.timedelta(days=1)
    if schedule == Schedule.WEEKLY:
        # Last Sunday (end of previous full week)
        days_since_sunday = (today.weekday() + 1) % 7
        if days_since_sunday == 0:
            days_since_sunday = 7
        return today - datetime.timedelta(days=days_since_sunday)
    if schedule == Schedule.MONTHLY:
        first_of_month = today.replace(day=1)
        return first_of_month - datetime.timedelta(days=1)
    msg = f"Unhandled schedule: {schedule!r}"
    raise ValueError(msg)


@cli.command()
@click.option(
    "--schedule",
    required=True,
    type=click.Choice(["daily", "weekly", "monthly"], case_sensitive=False),
    help="Which schedule frequency to generate.",
)
@click.option(
    "--date",
    "date_str",
    default=None,
    help="Report date YYYY-MM-DD (default: auto based on schedule)",
)
@click.option("--no-send", is_flag=True, help="Generate report but don't send email.")
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="Write HTML to file (implies --no-send).",
)
@click.option("--preview", is_flag=True, help="Open report in browser after generating.")
@click.pass_context
def report(
    ctx: click.Context,
    schedule: str,
    date_str: str | None,
    *,
    no_send: bool,
    output_path: str | None,
    preview: bool,
) -> None:
    """Generate and send analytics reports."""
    try:
        from sites_report.reports.builder import build_report
    except ImportError as exc:
        logger.error("Report builder dependencies not available: %s", exc)
        click.echo(f"Report builder unavailable (missing dependency): {exc}", err=True)
        raise SystemExit(1) from exc

    try:
        from sites_report.email import EmailError, send_email
    except ImportError as exc:
        logger.error("Email sending dependencies not available: %s", exc)
        click.echo(f"Email sender unavailable (missing dependency): {exc}", err=True)
        raise SystemExit(1) from exc

    cfg = _load_config(ctx)
    sched = Schedule(schedule.lower())

    if output_path is not None:
        no_send = True

    if preview and output_path is None:
        click.echo("--preview requires --output to specify a file path.", err=True)
        raise SystemExit(1)

    if date_str is not None:
        try:
            report_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            click.echo(f"Invalid date format: {date_str!r} (expected YYYY-MM-DD)", err=True)
            raise SystemExit(1) from None
    else:
        report_date = _default_report_date(sched)

    try:
        init_db(cfg.db_path)
    except DatabaseError as exc:
        click.echo(f"Database error: {exc}", err=True)
        raise SystemExit(1) from exc

    _ensure_data_fetched(cfg, report_date, sched)

    matching = [s for s in cfg.subscriptions if s.schedule == sched]
    if not matching:
        click.echo(f"No subscriptions matching schedule '{schedule}'.")
        return

    last_output_file: Path | None = None
    generated = 0
    sent_failures = 0

    for idx, sub in enumerate(matching):
        sub_projects = tuple(p for p in cfg.projects if p.slug in sub.projects)
        try:
            result = build_report(cfg.db_path, sub, sub_projects, sched, report_date)
        except ValueError as exc:
            logger.warning("Skipping subscription for %s: %s", sub.recipient, exc)
            click.echo(f"Warning: skipping {sub.recipient}: {exc}", err=True)
            continue
        except Exception as exc:
            logger.exception("Unexpected error building report for %s", sub.recipient)
            click.echo(f"Error: failed to build report for {sub.recipient}: {exc}", err=True)
            continue

        generated += 1
        click.echo(f"Generated: {result.subject} ({sub.recipient})")

        if output_path is not None:
            out = Path(output_path)
            if len(matching) > 1:
                out = out.with_stem(f"{out.stem}_{idx}")
            try:
                out.write_text(result.html)
            except OSError as exc:
                logger.error("Cannot write report to %s: %s", out, exc)
                click.echo(f"Cannot write report to {out}: {exc}", err=True)
                raise SystemExit(1) from exc
            click.echo(f"Written to: {out}")
            last_output_file = out

        if not no_send:
            try:
                send_email(cfg.email, sub.recipient, result.subject, result.html)
            except EmailError as exc:
                logger.error("Failed to send email to %s: %s", sub.recipient, exc)
                click.echo(f"Error: failed to send to {sub.recipient}: {exc}", err=True)
                sent_failures += 1
                continue
            click.echo(f"Sent to: {sub.recipient}")

    failed = len(matching) - generated
    if generated == 0 and failed > 0:
        click.echo("All subscriptions failed to generate.", err=True)
        raise SystemExit(1)

    if failed > 0 or sent_failures > 0:
        total_failures = failed + sent_failures
        click.echo(
            f"{total_failures} of {len(matching)} subscription(s) failed.", err=True
        )
        raise SystemExit(1)

    if preview and last_output_file is not None:
        try:
            webbrowser.open(last_output_file.as_uri())
        except (webbrowser.Error, OSError) as exc:
            click.echo(f"Could not open browser: {exc}. View: {last_output_file}", err=True)
