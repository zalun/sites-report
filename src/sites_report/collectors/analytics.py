"""GA4 analytics data collector."""

import datetime
import logging

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
    RunReportResponse,
)
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from sites_report.collectors.base import Collector, CollectorError, build_google_credentials
from sites_report.config import GoogleConfig, ProjectConfig

logger = logging.getLogger(__name__)

_DAILY_METRICS: dict[str, str] = {
    "sessions": "sessions",
    "totalUsers": "users",
    "newUsers": "new_users",
    "screenPageViews": "pageviews",
    "averageSessionDuration": "avg_session_duration",
    "bounceRate": "bounce_rate",
    "conversions": "conversions",
}

_TOP_PAGES_METRICS: dict[str, str] = {
    "screenPageViews": "pageviews",
    "sessions": "sessions",
    "averageSessionDuration": "avg_time_on_page",
}

_GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_TOP_PAGES_LIMIT = 10


class GA4Collector(Collector):
    """Fetches daily analytics from Google Analytics 4 Data API."""

    def __init__(self, google_config: GoogleConfig) -> None:
        credentials = build_google_credentials(google_config, [_GA4_SCOPE])
        self._client = BetaAnalyticsDataClient(credentials=credentials)

    def fetch(
        self, project: ProjectConfig, date: datetime.date
    ) -> dict[str, int | float | str | None]:
        property_id = self._require_property_id(project)
        date_str = date.isoformat()
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            metrics=[Metric(name=name) for name in _DAILY_METRICS],
        )
        response = self._run_report(request, project.slug, date)
        return self._parse_daily(response)

    def fetch_top_pages(
        self, project: ProjectConfig, date: datetime.date
    ) -> list[dict[str, int | float | str | None]]:
        property_id = self._require_property_id(project)
        date_str = date.isoformat()
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name=name) for name in _TOP_PAGES_METRICS],
            order_bys=[
                OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"),
                    desc=True,
                )
            ],
            limit=_TOP_PAGES_LIMIT,
        )
        response = self._run_report(request, project.slug, date)
        return self._parse_top_pages(response)

    def _require_property_id(self, project: ProjectConfig) -> str:
        if not project.ga4_property_id:
            logger.error("No ga4_property_id for project '%s'", project.slug)
            raise CollectorError(f"No ga4_property_id configured for project '{project.slug}'")
        return project.ga4_property_id

    def _run_report(
        self, request: RunReportRequest, slug: str, date: datetime.date
    ) -> RunReportResponse:
        try:
            return self._client.run_report(request)
        except (GoogleAPIError, GoogleAuthError) as exc:
            logger.error("GA4 API error for '%s' on %s: %s", slug, date, exc)
            raise CollectorError(f"GA4 API error for '{slug}' on {date}: {exc}") from exc

    def _parse_daily(
        self, response: RunReportResponse
    ) -> dict[str, int | float | str | None]:
        if not response.rows:
            return {db_col: None for db_col in _DAILY_METRICS.values()}
        row = response.rows[0]
        result: dict[str, int | float | str | None] = {}
        for i, (_api_name, db_col) in enumerate(_DAILY_METRICS.items()):
            result[db_col] = _parse_metric_value(row.metric_values[i].value, db_col)
        return result

    def _parse_top_pages(
        self, response: RunReportResponse
    ) -> list[dict[str, int | float | str | None]]:
        if not response.rows:
            return []
        pages: list[dict[str, int | float | str | None]] = []
        for row in response.rows:
            page: dict[str, int | float | str | None] = {
                "page_path": row.dimension_values[0].value,
            }
            for i, (_api_name, db_col) in enumerate(_TOP_PAGES_METRICS.items()):
                page[db_col] = _parse_metric_value(row.metric_values[i].value, db_col)
            pages.append(page)
        return pages


def _parse_metric_value(raw: str, db_col: str) -> int | float | None:
    """Convert GA4 metric string to appropriate Python type."""
    if not raw or raw == "(not set)":
        return None
    try:
        if db_col in ("avg_session_duration", "bounce_rate", "avg_time_on_page"):
            return float(raw)
        return int(raw)
    except ValueError as exc:
        logger.error("Cannot parse GA4 metric '%s'=%r: %s", db_col, raw, exc)
        raise CollectorError(f"Cannot parse GA4 metric '{db_col}' value {raw!r}: {exc}") from exc
