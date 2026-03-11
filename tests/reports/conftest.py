import pytest


@pytest.fixture
def trend_data_7d():
    """7-day sample trend data for GA4."""
    return [
        {"date": f"2025-03-0{i}", "sessions": 100 + i * 10, "users": 80 + i * 8}
        for i in range(1, 8)
    ]


@pytest.fixture
def gsc_trend_data_7d():
    """7-day sample GSC trend data."""
    return [
        {"date": f"2025-03-0{i}", "clicks": 50 + i * 5, "impressions": 1000 + i * 100}
        for i in range(1, 8)
    ]


@pytest.fixture
def top_queries_data():
    """12 sample search queries."""
    return [{"query": f"query {i}", "clicks": 100 - i * 5} for i in range(12)]


@pytest.fixture
def top_pages_data():
    """8 sample pages."""
    return [{"page_path": f"/page-{i}", "pageviews": 500 - i * 50} for i in range(8)]
