from sites_report.reports.charts import (
    gsc_clicks_impressions_trend,
    sessions_users_trend,
    top_pages,
    top_search_queries,
)

_PNG_MAGIC = b"\x89PNG"


def test_sessions_users_trend_returns_png(trend_data_7d):
    result = sessions_users_trend(trend_data_7d)

    assert result is not None
    assert result[:4] == _PNG_MAGIC
    assert len(result) > 1000


def test_sessions_users_trend_returns_none_for_empty():
    assert sessions_users_trend([]) is None


def test_gsc_clicks_impressions_trend_returns_png(gsc_trend_data_7d):
    result = gsc_clicks_impressions_trend(gsc_trend_data_7d)

    assert result is not None
    assert result[:4] == _PNG_MAGIC
    assert len(result) > 1000


def test_gsc_clicks_impressions_trend_returns_none_for_empty():
    assert gsc_clicks_impressions_trend([]) is None


def test_top_search_queries_returns_png(top_queries_data):
    result = top_search_queries(top_queries_data)

    assert result is not None
    assert result[:4] == _PNG_MAGIC
    assert len(result) > 1000


def test_top_search_queries_returns_none_for_empty():
    assert top_search_queries([]) is None


def test_top_search_queries_respects_limit(top_queries_data):
    result = top_search_queries(top_queries_data, limit=5)

    assert result is not None
    assert result[:4] == _PNG_MAGIC


def test_top_pages_returns_png(top_pages_data):
    result = top_pages(top_pages_data)

    assert result is not None
    assert result[:4] == _PNG_MAGIC
    assert len(result) > 1000


def test_top_pages_returns_none_for_empty():
    assert top_pages([]) is None


def test_top_pages_respects_limit(top_pages_data):
    result = top_pages(top_pages_data, limit=3)

    assert result is not None
    assert result[:4] == _PNG_MAGIC


def test_single_data_point_does_not_crash():
    data = [{"date": "2025-03-01", "sessions": 100, "users": 80}]
    result = sessions_users_trend(data)

    assert result is not None
    assert result[:4] == _PNG_MAGIC
