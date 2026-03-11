import pytest

from sites_report.config import ProjectConfig, Schedule, SubscriptionConfig


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


@pytest.fixture
def sample_project_both():
    """ProjectConfig with GA4 + GSC."""
    return ProjectConfig(
        name="My Site",
        slug="my-site",
        ga4_property_id="properties/123",
        gsc_site_url="https://example.com",
    )


@pytest.fixture
def sample_project_ga4_only():
    """ProjectConfig with only GA4."""
    return ProjectConfig(
        name="GA4 Only Site",
        slug="ga4-only",
        ga4_property_id="properties/456",
    )


@pytest.fixture
def sample_subscription():
    """SubscriptionConfig for testing."""
    return SubscriptionConfig(
        recipient="test@example.com",
        projects=("my-site",),
        schedule=Schedule.DAILY,
    )


@pytest.fixture
def ga4_daily_rows():
    """Realistic GA4 daily query results."""
    return [
        {
            "date": "2025-03-10",
            "sessions": 150,
            "users": 120,
            "new_users": 80,
            "pageviews": 450,
            "avg_session_duration": 125.5,
            "bounce_rate": 0.42,
            "conversions": 5,
        },
    ]


@pytest.fixture
def gsc_daily_rows():
    """Realistic GSC daily query results."""
    return [
        {
            "date": "2025-03-10",
            "clicks": 85,
            "impressions": 2400,
            "ctr": 0.035,
            "avg_position": 14.2,
        },
    ]
