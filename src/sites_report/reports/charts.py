"""Chart generation for analytics reports."""

from __future__ import annotations

import logging
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

_FIG_WIDTH = 8
_FIG_HEIGHT = 4
_DPI = 75

_COLOR_PRIMARY = "#4285f4"  # blue
_COLOR_SECONDARY = "#ea4335"  # red
_COLOR_BARS = "#34a853"  # green


def _render_to_png(fig: plt.Figure) -> bytes:
    """Render a matplotlib figure to PNG bytes and close it."""
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    finally:
        plt.close(fig)
    buf.seek(0)
    return buf.read()


def _style_axes(ax: plt.Axes) -> None:
    """Apply consistent styling: hide top/right spines, light y-grid."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.3)
    ax.set_axisbelow(True)


def sessions_users_trend(data: list[dict]) -> bytes | None:
    """Dual-line chart: sessions and users over time.

    Expects dicts with keys: date, sessions, users.
    """
    if not data:
        return None

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    try:
        dates = [d["date"] for d in data]
        sessions = [d["sessions"] for d in data]
        users = [d["users"] for d in data]

        ax.plot(dates, sessions, color=_COLOR_PRIMARY, marker="o", markersize=4, label="Sessions")
        ax.plot(dates, users, color=_COLOR_SECONDARY, marker="o", markersize=4, label="Users")
        ax.set_title("Sessions & Users")
        ax.legend()
        _style_axes(ax)
        fig.autofmt_xdate()

        return _render_to_png(fig)
    except KeyError as exc:
        logger.error("sessions_users_trend: missing key %s in data (%d rows)", exc, len(data))
        plt.close(fig)
        return None


def gsc_clicks_impressions_trend(data: list[dict]) -> bytes | None:
    """Dual-axis chart: clicks (left) and impressions (right) over time.

    Expects dicts with keys: date, clicks, impressions.
    """
    if not data:
        return None

    fig, ax1 = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    try:
        dates = [d["date"] for d in data]
        clicks = [d["clicks"] for d in data]
        impressions = [d["impressions"] for d in data]

        ax1.plot(dates, clicks, color=_COLOR_PRIMARY, marker="o", markersize=4, label="Clicks")
        ax1.set_ylabel("Clicks", color=_COLOR_PRIMARY)
        ax1.tick_params(axis="y", labelcolor=_COLOR_PRIMARY)
        _style_axes(ax1)

        ax2 = ax1.twinx()
        ax2.plot(
            dates,
            impressions,
            color=_COLOR_SECONDARY,
            marker="s",
            markersize=4,
            label="Impressions",
        )
        ax2.set_ylabel("Impressions", color=_COLOR_SECONDARY)
        ax2.tick_params(axis="y", labelcolor=_COLOR_SECONDARY)
        ax2.spines["top"].set_visible(False)

        ax1.set_title("Clicks & Impressions")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2)
        fig.autofmt_xdate()

        return _render_to_png(fig)
    except KeyError as exc:
        logger.error(
            "gsc_clicks_impressions_trend: missing key %s in data (%d rows)",
            exc,
            len(data),
        )
        plt.close(fig)
        return None


def top_search_queries(data: list[dict], *, limit: int = 10) -> bytes | None:
    """Horizontal bar chart of top search queries by clicks.

    Expects dicts with keys: query, clicks.
    """
    if not data:
        return None

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    try:
        entries = data[:limit]
        queries = [d["query"] for d in reversed(entries)]
        clicks = [d["clicks"] for d in reversed(entries)]

        ax.barh(queries, clicks, color=_COLOR_PRIMARY)
        ax.set_title("Top Search Queries")
        ax.set_xlabel("Clicks")
        _style_axes(ax)
        fig.tight_layout()

        return _render_to_png(fig)
    except KeyError as exc:
        logger.error("top_search_queries: missing key %s in data (%d rows)", exc, len(data))
        plt.close(fig)
        return None


def top_pages(data: list[dict], *, limit: int = 10) -> bytes | None:
    """Horizontal bar chart of top pages by pageviews.

    Expects dicts with keys: page_path, pageviews.
    """
    if not data:
        return None

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    try:
        entries = data[:limit]
        paths = [d["page_path"] for d in reversed(entries)]
        views = [d["pageviews"] for d in reversed(entries)]

        ax.barh(paths, views, color=_COLOR_BARS)
        ax.set_title("Top Pages")
        ax.set_xlabel("Pageviews")
        _style_axes(ax)
        fig.tight_layout()

        return _render_to_png(fig)
    except KeyError as exc:
        logger.error("top_pages: missing key %s in data (%d rows)", exc, len(data))
        plt.close(fig)
        return None
