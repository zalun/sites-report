"""GSC search analytics data collector."""

import datetime
import logging

from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from sites_report.collectors.base import Collector, CollectorError, build_google_credentials
from sites_report.config import GoogleConfig, ProjectConfig

logger = logging.getLogger(__name__)

_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_TOP_QUERIES_LIMIT = 20

# Daily metrics map API field → (DB column, type).
# "position" maps to "avg_position" because the daily row is an aggregate
# across all queries, so the value represents the average position.
_DAILY_METRICS: dict[str, tuple[str, type[int] | type[float]]] = {
    "clicks": ("clicks", int),
    "impressions": ("impressions", int),
    "ctr": ("ctr", float),
    "position": ("avg_position", float),
}

# Top-queries metrics map API field → (DB column, type).
# "position" keeps its name because each row is a single query.
_TOP_QUERIES_METRICS: dict[str, tuple[str, type[int] | type[float]]] = {
    "clicks": ("clicks", int),
    "impressions": ("impressions", int),
    "ctr": ("ctr", float),
    "position": ("position", float),
}


class GSCCollector(Collector):
    """Fetches daily search analytics from Google Search Console API."""

    def __init__(self, google_config: GoogleConfig) -> None:
        credentials = build_google_credentials(google_config, [_GSC_SCOPE])
        self._service = build("searchconsole", "v1", credentials=credentials)

    def fetch(
        self, project: ProjectConfig, date: datetime.date
    ) -> dict[str, int | float | str | None]:
        site_url = self._require_site_url(project)
        date_str = date.isoformat()
        body = {"startDate": date_str, "endDate": date_str}
        response = self._query(site_url, body, project.slug, date)
        return self._parse_daily(response)

    def fetch_top_queries(
        self, project: ProjectConfig, date: datetime.date
    ) -> list[dict[str, int | float | str | None]]:
        site_url = self._require_site_url(project)
        date_str = date.isoformat()
        body = {
            "startDate": date_str,
            "endDate": date_str,
            "dimensions": ["query"],
            "rowLimit": _TOP_QUERIES_LIMIT,
        }
        response = self._query(site_url, body, project.slug, date)
        return self._parse_top_queries(response)

    def _require_site_url(self, project: ProjectConfig) -> str:
        if not project.gsc_site_url:
            logger.error("No gsc_site_url for project '%s'", project.slug)
            raise CollectorError(
                f"No gsc_site_url configured for project '{project.slug}'"
            )
        return project.gsc_site_url

    def _query(
        self, site_url: str, body: dict, slug: str, date: datetime.date
    ) -> dict:
        try:
            return (
                self._service.searchanalytics()
                .query(siteUrl=site_url, body=body)
                .execute()
            )
        except (HttpError, GoogleAuthError) as exc:
            logger.error("GSC API error for '%s' on %s: %s", slug, date, exc)
            raise CollectorError(
                f"GSC API error for '{slug}' on {date}: {exc}"
            ) from exc

    def _parse_daily(
        self, response: dict
    ) -> dict[str, int | float | str | None]:
        rows = response.get("rows", [])
        if not rows:
            logger.debug("GSC returned no rows for daily query")
            return {db_col: None for db_col, _typ in _DAILY_METRICS.values()}
        row = rows[0]
        result: dict[str, int | float | str | None] = {}
        for api_name, (db_col, typ) in _DAILY_METRICS.items():
            result[db_col] = _cast_metric(row.get(api_name), db_col, typ)
        return result

    def _parse_top_queries(
        self, response: dict
    ) -> list[dict[str, int | float | str | None]]:
        rows = response.get("rows", [])
        if not rows:
            logger.debug("GSC returned no rows for top-queries query")
            return []
        queries: list[dict[str, int | float | str | None]] = []
        for row in rows:
            try:
                query_text = row["keys"][0]
            except (KeyError, IndexError) as exc:
                logger.error("GSC response missing query dimension: %s", exc)
                raise CollectorError(
                    "GSC response missing query dimension"
                ) from exc
            entry: dict[str, int | float | str | None] = {"query": query_text}
            for api_name, (db_col, typ) in _TOP_QUERIES_METRICS.items():
                entry[db_col] = _cast_metric(row.get(api_name), db_col, typ)
            queries.append(entry)
        return queries


def _cast_metric(
    raw: int | float | None, db_col: str, typ: type[int] | type[float]
) -> int | float:
    """Cast a GSC metric value to the expected Python type."""
    if raw is None:
        logger.error("GSC response missing metric '%s'", db_col)
        raise CollectorError(f"GSC response missing metric '{db_col}'")
    try:
        return typ(raw)
    except (ValueError, TypeError) as exc:
        logger.error("Cannot cast GSC metric '%s'=%r: %s", db_col, raw, exc)
        raise CollectorError(
            f"Cannot cast GSC metric '{db_col}' value {raw!r}: {exc}"
        ) from exc
