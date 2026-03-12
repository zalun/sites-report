"""Tests for GA4 analytics collector."""

import datetime
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError

from sites_report.collectors.analytics import (
    GA4Collector,
    _parse_metric_value,
)
from sites_report.collectors.base import CollectorError
from sites_report.config import GoogleConfig, ProjectConfig

_DATE = datetime.date(2026, 3, 10)
_PATCH_CREDS = "sites_report.collectors.analytics.build_google_credentials"
_PATCH_CLIENT = "sites_report.collectors.analytics.BetaAnalyticsDataClient"


def _grpc_unavailable() -> object:
    """Return grpc UNAVAILABLE status code, importing lazily."""
    from grpc import StatusCode

    return StatusCode.UNAVAILABLE


def _make_project(ga4_property_id: str | None = "properties/123456") -> ProjectConfig:
    return ProjectConfig(
        name="Test Site",
        slug="test-site",
        ga4_property_id=ga4_property_id,
        gsc_site_url="https://example.com",
    )


def _make_metric_value(value: str) -> MagicMock:
    mv = MagicMock()
    mv.value = value
    return mv


def _make_dimension_value(value: str) -> MagicMock:
    dv = MagicMock()
    dv.value = value
    return dv


def _make_row(
    dimension_values: list[str] | None = None,
    metric_values: list[str] | None = None,
) -> MagicMock:
    row = MagicMock()
    row.dimension_values = [_make_dimension_value(v) for v in (dimension_values or [])]
    row.metric_values = [_make_metric_value(v) for v in (metric_values or [])]
    return row


def _make_response(rows: list[MagicMock] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.rows = rows or []
    return resp


def _make_collector(mock_creds: MagicMock, mock_client_cls: MagicMock) -> GA4Collector:
    mock_creds.return_value = MagicMock()
    return GA4Collector(GoogleConfig(service_account_key=Path("key.json")))


# -- init --


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_init_builds_credentials_and_client(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    google_config = GoogleConfig(service_account_key=Path("key.json"))
    fake_creds = MagicMock()
    mock_creds.return_value = fake_creds

    collector = GA4Collector(google_config)

    assert mock_creds.call_count == 1
    assert mock_creds.call_args == mock.call(
        google_config,
        ["https://www.googleapis.com/auth/analytics.readonly"],
    )
    assert mock_client_cls.call_count == 1
    assert mock_client_cls.call_args == mock.call(credentials=fake_creds)
    assert collector._client is mock_client_cls.return_value


# -- fetch --


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_returns_daily_metrics(mock_creds: MagicMock, mock_client_cls: MagicMock) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    row = _make_row(
        metric_values=["100", "80", "40", "500", "120.5", "0.35", "10"],
    )
    collector._client.run_report.return_value = _make_response([row])

    result = collector.fetch(_make_project(), _DATE)

    assert result == {
        "sessions": 100,
        "users": 80,
        "new_users": 40,
        "pageviews": 500,
        "avg_session_duration": 120.5,
        "bounce_rate": 0.35,
        "conversions": 10,
    }
    assert collector._client.run_report.call_count == 1


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_returns_none_values_when_no_rows(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    collector._client.run_report.return_value = _make_response([])

    result = collector.fetch(_make_project(), _DATE)

    assert result == {
        "sessions": None,
        "users": None,
        "new_users": None,
        "pageviews": None,
        "avg_session_duration": None,
        "bounce_rate": None,
        "conversions": None,
    }


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_require_property_id_prepends_prefix_when_missing(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    project = _make_project(ga4_property_id="491072921")
    assert collector._require_property_id(project) == "properties/491072921"


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_require_property_id_raises_on_non_numeric_bare_id(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    project = _make_project(ga4_property_id="property/123456")
    with pytest.raises(CollectorError, match="is invalid"):
        collector._require_property_id(project)


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_require_property_id_keeps_existing_prefix(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    project = _make_project(ga4_property_id="properties/123456")
    assert collector._require_property_id(project) == "properties/123456"


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_raises_when_no_property_id(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    project = _make_project(ga4_property_id=None)

    with pytest.raises(CollectorError, match="No ga4_property_id configured"):
        collector.fetch(project, _DATE)


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_wraps_google_api_error(mock_creds: MagicMock, mock_client_cls: MagicMock) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    collector._client.run_report.side_effect = GoogleAPICallError("quota exceeded")

    with pytest.raises(CollectorError, match="GA4 API error"):
        collector.fetch(_make_project(), _DATE)


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_wraps_google_auth_error(mock_creds: MagicMock, mock_client_cls: MagicMock) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    collector._client.run_report.side_effect = GoogleAuthError("token expired")

    with pytest.raises(CollectorError, match="GA4 API error"):
        collector.fetch(_make_project(), _DATE)


# -- retry behaviour --


@mock.patch("sites_report.collectors.base.time.sleep")
@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_retries_on_transient_api_error(
    mock_creds: MagicMock, mock_client_cls: MagicMock, mock_sleep: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    transient = GoogleAPICallError("unavailable")
    transient.grpc_status_code = _grpc_unavailable()
    row = _make_row(metric_values=["10", "8", "4", "50", "12.0", "0.3", "1"])
    collector._client.run_report.side_effect = [transient, _make_response([row])]

    result = collector.fetch(_make_project(), _DATE)

    assert result["sessions"] == 10
    assert collector._client.run_report.call_count == 2
    assert mock_sleep.call_count == 1


@mock.patch("sites_report.collectors.base.time.sleep")
@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_does_not_retry_on_auth_error(
    mock_creds: MagicMock, mock_client_cls: MagicMock, mock_sleep: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    collector._client.run_report.side_effect = GoogleAuthError("bad creds")

    with pytest.raises(CollectorError, match="GA4 API error"):
        collector.fetch(_make_project(), _DATE)

    assert collector._client.run_report.call_count == 1
    assert mock_sleep.call_count == 0


# -- fetch_top_pages --


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_pages_returns_page_list(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    rows = [
        _make_row(dimension_values=["/home"], metric_values=["200", "150", "45.2"]),
        _make_row(dimension_values=["/about"], metric_values=["80", "60", "30.0"]),
    ]
    collector._client.run_report.return_value = _make_response(rows)

    result = collector.fetch_top_pages(_make_project(), _DATE)

    assert result == [
        {"page_path": "/home", "pageviews": 200, "sessions": 150, "avg_time_on_page": 45.2},
        {"page_path": "/about", "pageviews": 80, "sessions": 60, "avg_time_on_page": 30.0},
    ]
    assert collector._client.run_report.call_count == 1


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_pages_returns_empty_list_when_no_rows(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    collector._client.run_report.return_value = _make_response([])

    result = collector.fetch_top_pages(_make_project(), _DATE)

    assert result == []


# -- response shape errors --


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_raises_on_missing_metric_column(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    row = _make_row(metric_values=["100", "80", "40"])
    collector._client.run_report.return_value = _make_response([row])

    with pytest.raises(CollectorError, match="missing metric"):
        collector.fetch(_make_project(), _DATE)


@mock.patch(_PATCH_CLIENT)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_pages_raises_on_missing_dimension(
    mock_creds: MagicMock, mock_client_cls: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_client_cls)
    row = _make_row(dimension_values=[], metric_values=["200", "150", "45.2"])
    collector._client.run_report.return_value = _make_response([row])

    with pytest.raises(CollectorError, match="missing pagePath dimension"):
        collector.fetch_top_pages(_make_project(), _DATE)


# -- _parse_metric_value --


def test_parse_metric_value_integer_column() -> None:
    assert _parse_metric_value("42", "sessions", int) == 42


def test_parse_metric_value_float_column() -> None:
    assert _parse_metric_value("3.14", "avg_session_duration", float) == 3.14


def test_parse_metric_value_zero_string() -> None:
    assert _parse_metric_value("0", "sessions", int) == 0


def test_parse_metric_value_empty_string() -> None:
    assert _parse_metric_value("", "sessions", int) is None


def test_parse_metric_value_not_set() -> None:
    assert _parse_metric_value("(not set)", "sessions", int) is None


def test_parse_metric_value_raises_on_malformed_int() -> None:
    with pytest.raises(CollectorError, match="Cannot parse GA4 metric"):
        _parse_metric_value("N/A", "sessions", int)


def test_parse_metric_value_raises_on_malformed_float() -> None:
    with pytest.raises(CollectorError, match="Cannot parse GA4 metric"):
        _parse_metric_value("not-a-number", "avg_session_duration", float)
