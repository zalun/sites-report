"""GA4 analytics data collector."""

import datetime
import logging

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    OrderBy,
    RunReportRequest,
    RunReportResponse,
)
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError

from sites_report.collectors.base import (
    Collector,
    CollectorError,
    build_google_credentials,
    retry_on_transient,
)
from sites_report.config import GoogleConfig, ProjectConfig

logger = logging.getLogger(__name__)

_DAILY_METRICS: dict[str, tuple[str, type]] = {
    "sessions": ("sessions", int),
    "totalUsers": ("users", int),
    "newUsers": ("new_users", int),
    "screenPageViews": ("pageviews", int),
    "averageSessionDuration": ("avg_session_duration", float),
    "bounceRate": ("bounce_rate", float),
    "conversions": ("conversions", int),
}

_TOP_PAGES_METRICS: dict[str, tuple[str, type]] = {
    "screenPageViews": ("pageviews", int),
    "sessions": ("sessions", int),
    "averageSessionDuration": ("avg_time_on_page", float),
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

    def fetch_events(
        self,
        project: ProjectConfig,
        date: datetime.date,
        event_names: list[str],
    ) -> list[dict[str, int | str | None]]:
        """Fetch event counts for specific event names on a given date."""
        property_id = self._require_property_id(project)
        date_str = date.isoformat()
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    in_list_filter=Filter.InListFilter(values=event_names),
                )
            ),
        )
        response = self._run_report(request, project.slug, date)
        return self._parse_events(response)

    @staticmethod
    def _parse_events(
        response: RunReportResponse,
    ) -> list[dict[str, int | str | None]]:
        if not response.rows:
            return []
        events: list[dict[str, int | str | None]] = []
        for row in response.rows:
            event_name = row.dimension_values[0].value
            raw_count = row.metric_values[0].value
            event_count = int(raw_count) if raw_count else 0
            events.append({"event_name": event_name, "event_count": event_count})
        return events

    def _require_property_id(self, project: ProjectConfig) -> str:
        if not project.ga4_property_id:
            logger.error("No ga4_property_id for project '%s'", project.slug)
            raise CollectorError(f"No ga4_property_id configured for project '{project.slug}'")
        pid = project.ga4_property_id
        if not pid.startswith("properties/"):
            if not pid.isdigit():
                raise CollectorError(
                    f"ga4_property_id '{pid}' for project '{project.slug}' is invalid:"
                    f" expected a numeric ID like '123456' or 'properties/123456'"
                )
            logger.debug(
                "Prepending 'properties/' prefix to ga4_property_id '%s' for project '%s'",
                pid,
                project.slug,
            )
            pid = f"properties/{pid}"
        return pid

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, GoogleAuthError):
            return False
        if isinstance(exc, GoogleAPIError):
            code = getattr(exc, "grpc_status_code", None)
            if code is not None:
                from grpc import StatusCode

                return code in {
                    StatusCode.UNAVAILABLE,  # HTTP 503
                    StatusCode.DEADLINE_EXCEEDED,  # HTTP 504
                    StatusCode.RESOURCE_EXHAUSTED,  # HTTP 429
                    StatusCode.INTERNAL,  # HTTP 500
                }
            # Fallback: check HTTP status code for non-gRPC transports.
            http_code = getattr(exc, "code", None)
            if http_code is not None:
                return http_code in {429, 500, 502, 503, 504}
        return False

    def _run_report(
        self, request: RunReportRequest, slug: str, date: datetime.date
    ) -> RunReportResponse:
        try:
            return retry_on_transient(
                lambda: self._client.run_report(request),
                is_retryable=self._is_retryable,
                context=f"GA4 '{slug}' on {date}",
            )
        except (GoogleAPIError, GoogleAuthError) as exc:
            logger.error("GA4 API error for '%s' on %s: %s", slug, date, exc)
            raise CollectorError(f"GA4 API error for '{slug}' on {date}: {exc}") from exc

    def _parse_daily(self, response: RunReportResponse) -> dict[str, int | float | str | None]:
        if not response.rows:
            return {db_col: None for db_col, _typ in _DAILY_METRICS.values()}
        row = response.rows[0]
        result: dict[str, int | float | str | None] = {}
        for i, (_api_name, (db_col, typ)) in enumerate(_DAILY_METRICS.items()):
            try:
                raw = row.metric_values[i].value
            except (IndexError, AttributeError) as exc:
                logger.error("GA4 response missing metric at index %d (%s): %s", i, db_col, exc)
                raise CollectorError(
                    f"GA4 response missing metric '{db_col}' at index {i}"
                ) from exc
            result[db_col] = _parse_metric_value(raw, db_col, typ)
        return result

    def _parse_top_pages(
        self, response: RunReportResponse
    ) -> list[dict[str, int | float | str | None]]:
        if not response.rows:
            return []
        pages: list[dict[str, int | float | str | None]] = []
        for row in response.rows:
            try:
                page_path = row.dimension_values[0].value
            except (IndexError, AttributeError) as exc:
                logger.error("GA4 response missing pagePath dimension: %s", exc)
                raise CollectorError("GA4 response missing pagePath dimension") from exc
            page: dict[str, int | float | str | None] = {"page_path": page_path}
            for i, (_api_name, (db_col, typ)) in enumerate(_TOP_PAGES_METRICS.items()):
                try:
                    raw = row.metric_values[i].value
                except (IndexError, AttributeError) as exc:
                    logger.error(
                        "GA4 response missing metric at index %d (%s): %s", i, db_col, exc
                    )
                    raise CollectorError(
                        f"GA4 response missing metric '{db_col}' at index {i}"
                    ) from exc
                page[db_col] = _parse_metric_value(raw, db_col, typ)
            pages.append(page)
        return pages


def _parse_metric_value(raw: str, db_col: str, target_type: type) -> int | float | None:
    """Convert GA4 metric string to appropriate Python type."""
    if not raw or raw == "(not set)":
        return None
    try:
        return target_type(raw)
    except (ValueError, TypeError) as exc:
        logger.error("Cannot parse GA4 metric '%s'=%r: %s", db_col, raw, exc)
        raise CollectorError(f"Cannot parse GA4 metric '{db_col}' value {raw!r}: {exc}") from exc
