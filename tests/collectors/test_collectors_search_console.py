"""Tests for GSC search analytics collector."""

import datetime
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from sites_report.collectors.base import CollectorError
from sites_report.collectors.search_console import GSCCollector
from sites_report.config import GoogleConfig, ProjectConfig

_DATE = datetime.date(2026, 3, 10)
_PATCH_CREDS = "sites_report.collectors.search_console.build_google_credentials"
_PATCH_BUILD = "sites_report.collectors.search_console.build"


def _make_project(gsc_site_url: str | None = "https://example.com") -> ProjectConfig:
    return ProjectConfig(
        name="Test Site",
        slug="test-site",
        ga4_property_id="properties/123456",
        gsc_site_url=gsc_site_url,
    )


def _make_collector(mock_creds: MagicMock, mock_build: MagicMock) -> GSCCollector:
    mock_creds.return_value = MagicMock()
    return GSCCollector(GoogleConfig(service_account_key=Path("key.json")))


def _make_daily_row(
    clicks: int = 150,
    impressions: int = 3000,
    ctr: float = 0.05,
    position: float = 12.3,
) -> dict:
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


def _make_query_row(
    query: str,
    clicks: int = 50,
    impressions: int = 1000,
    ctr: float = 0.05,
    position: float = 5.2,
) -> dict:
    return {
        "keys": [query],
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


# -- init --


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_init_builds_credentials_and_service(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    google_config = GoogleConfig(service_account_key=Path("key.json"))
    fake_creds = MagicMock()
    mock_creds.return_value = fake_creds

    collector = GSCCollector(google_config)

    assert mock_creds.call_count == 1
    assert mock_creds.call_args == mock.call(
        google_config,
        ["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    assert mock_build.call_count == 1
    assert mock_build.call_args == mock.call(
        "searchconsole", "v1", credentials=fake_creds
    )
    assert collector._service is mock_build.return_value


# -- fetch --


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_returns_daily_metrics(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [_make_daily_row()],
    }

    result = collector.fetch(_make_project(), _DATE)

    assert result == {
        "clicks": 150,
        "impressions": 3000,
        "ctr": 0.05,
        "avg_position": 12.3,
    }
    assert service.searchanalytics.return_value.query.call_count == 1


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_returns_none_values_when_no_rows(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [],
    }

    result = collector.fetch(_make_project(), _DATE)

    assert result == {
        "clicks": None,
        "impressions": None,
        "ctr": None,
        "avg_position": None,
    }


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_returns_none_values_when_rows_key_missing(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {}

    result = collector.fetch(_make_project(), _DATE)

    assert result == {
        "clicks": None,
        "impressions": None,
        "ctr": None,
        "avg_position": None,
    }


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_raises_when_no_site_url(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    project = _make_project(gsc_site_url=None)

    with pytest.raises(CollectorError, match="No gsc_site_url configured"):
        collector.fetch(project, _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_wraps_http_error(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    resp = MagicMock()
    resp.status = 403
    resp.reason = "Forbidden"
    service.searchanalytics.return_value.query.return_value.execute.side_effect = (
        HttpError(resp=resp, content=b"quota exceeded")
    )

    with pytest.raises(CollectorError, match="GSC API error"):
        collector.fetch(_make_project(), _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_wraps_google_auth_error(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.side_effect = (
        GoogleAuthError("token expired")
    )

    with pytest.raises(CollectorError, match="GSC API error"):
        collector.fetch(_make_project(), _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_raises_on_missing_metric_key(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    # Row missing 'position' key
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [{"clicks": 10, "impressions": 200, "ctr": 0.05}],
    }

    with pytest.raises(CollectorError, match="missing metric"):
        collector.fetch(_make_project(), _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_raises_on_uncastable_metric_value(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [
            {
                "clicks": "not_a_number",
                "impressions": 200,
                "ctr": 0.05,
                "position": 3.0,
            }
        ],
    }

    with pytest.raises(CollectorError, match="Cannot cast GSC metric"):
        collector.fetch(_make_project(), _DATE)


# -- fetch_top_queries --


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_queries_returns_query_list(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [
            _make_query_row(
                "python tutorial",
                clicks=80,
                impressions=2000,
                ctr=0.04,
                position=3.1,
            ),
            _make_query_row(
                "django guide",
                clicks=40,
                impressions=800,
                ctr=0.05,
                position=7.5,
            ),
        ],
    }

    result = collector.fetch_top_queries(_make_project(), _DATE)

    assert result == [
        {
            "query": "python tutorial",
            "clicks": 80,
            "impressions": 2000,
            "ctr": 0.04,
            "position": 3.1,
        },
        {
            "query": "django guide",
            "clicks": 40,
            "impressions": 800,
            "ctr": 0.05,
            "position": 7.5,
        },
    ]
    assert service.searchanalytics.return_value.query.call_count == 1


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_queries_returns_empty_list_when_no_rows(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [],
    }

    result = collector.fetch_top_queries(_make_project(), _DATE)

    assert result == []


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_queries_raises_when_no_site_url(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    project = _make_project(gsc_site_url=None)

    with pytest.raises(CollectorError, match="No gsc_site_url configured"):
        collector.fetch_top_queries(project, _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_queries_raises_on_missing_query_dimension(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [
            {"clicks": 10, "impressions": 200, "ctr": 0.05, "position": 3.0}
        ],
    }

    with pytest.raises(CollectorError, match="missing query dimension"):
        collector.fetch_top_queries(_make_project(), _DATE)


@mock.patch(_PATCH_BUILD)
@mock.patch(_PATCH_CREDS)
def test_fetch_top_queries_raises_on_uncastable_metric_value(
    mock_creds: MagicMock, mock_build: MagicMock
) -> None:
    collector = _make_collector(mock_creds, mock_build)
    service = mock_build.return_value
    service.searchanalytics.return_value.query.return_value.execute.return_value = {
        "rows": [
            {
                "keys": ["some query"],
                "clicks": "bad",
                "impressions": 200,
                "ctr": 0.05,
                "position": 3.0,
            }
        ],
    }

    with pytest.raises(CollectorError, match="Cannot cast GSC metric"):
        collector.fetch_top_queries(_make_project(), _DATE)
