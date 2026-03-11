from pathlib import Path

import jinja2
import pytest


@pytest.fixture
def template_env():
    """Jinja2 environment loading from the reports templates directory."""
    templates_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "sites_report"
        / "reports"
        / "templates"
    )
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )


@pytest.fixture
def full_context():
    """Complete template context with all sections populated."""
    return {
        "subject": "Daily Analytics Report",
        "schedule": "Daily",
        "generated_at": "2025-03-10 08:00 UTC",
        "projects": [
            {
                "name": "My Website",
                "period": "March 10, 2025",
                "comparison_label": {"current": "Mar 10", "previous": "Mar 3"},
                "ga4": {
                    "metrics": [
                        {
                            "label": "Sessions",
                            "current": "1,234",
                            "previous": "1,100",
                            "change": "+12.2%",
                            "direction": "positive",
                        },
                        {
                            "label": "Bounce Rate",
                            "current": "45.2%",
                            "previous": "42.0%",
                            "change": "+3.2%",
                            "direction": "negative",
                        },
                    ],
                },
                "gsc": {
                    "metrics": [
                        {
                            "label": "Clicks",
                            "current": "567",
                            "previous": "580",
                            "change": "-2.2%",
                            "direction": "negative",
                        },
                        {
                            "label": "Impressions",
                            "current": "12,345",
                            "previous": "11,000",
                            "change": "+12.2%",
                            "direction": "positive",
                        },
                    ],
                },
                "ai_highlights": "Sessions increased significantly compared to last week.",
                "charts": {
                    "sessions_users": "iVBORw0KGgoAAAANS",
                    "gsc_trend": "iVBORw0KGgoAAAANS",
                    "top_queries": None,
                    "top_pages": None,
                },
            },
        ],
    }


@pytest.fixture
def minimal_context():
    """Context with minimal data — no GA4, no GSC, no charts."""
    return {
        "subject": "Weekly Report",
        "schedule": "Weekly",
        "generated_at": "2025-03-10 08:00 UTC",
        "projects": [
            {
                "name": "Empty Site",
                "period": "Mar 3 \u2013 Mar 9, 2025",
                "comparison_label": {"current": "This week", "previous": "Last week"},
                "ga4": None,
                "gsc": None,
                "ai_highlights": None,
                "charts": {
                    "sessions_users": None,
                    "gsc_trend": None,
                    "top_queries": None,
                    "top_pages": None,
                },
            },
        ],
    }


def test_template_renders_without_error(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert len(html) > 100


def test_template_contains_subject(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "Daily Analytics Report" in html


def test_template_contains_schedule_badge(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "Daily" in html


def test_template_contains_project_name(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "My Website" in html


def test_template_shows_positive_change_in_green(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "#28a745" in html


def test_template_shows_negative_change_in_red(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "#dc3545" in html


def test_template_includes_ai_highlights(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "Sessions increased significantly" in html


def test_template_skips_missing_ga4(template_env, minimal_context):
    template = template_env.get_template("report.html")
    html = template.render(**minimal_context)

    assert "Google Analytics" not in html


def test_template_skips_missing_gsc(template_env, minimal_context):
    template = template_env.get_template("report.html")
    html = template.render(**minimal_context)

    assert "Search Console" not in html


def test_template_single_project_has_no_divider(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "<hr" not in html


def test_template_multiple_projects_have_divider(template_env, full_context):
    second_project = {
        "name": "Second Site",
        "period": "March 10, 2025",
        "comparison_label": {"current": "Mar 10", "previous": "Mar 3"},
        "ga4": None,
        "gsc": None,
        "ai_highlights": None,
        "charts": {
            "sessions_users": None,
            "gsc_trend": None,
            "top_queries": None,
            "top_pages": None,
        },
    }
    full_context["projects"].append(second_project)

    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "<hr" in html
    assert "Second Site" in html


def test_template_contains_generation_timestamp(template_env, full_context):
    template = template_env.get_template("report.html")
    html = template.render(**full_context)

    assert "2025-03-10 08:00 UTC" in html
