"""Abstract base class for data source collectors."""

import datetime
from abc import ABC, abstractmethod

from sites_report.config import ProjectConfig


class CollectorError(Exception):
    """Raised when a data collection operation fails."""


class Collector(ABC):
    """Interface for fetching daily analytics data from a source."""

    @abstractmethod
    def fetch(
        self, project: ProjectConfig, date: datetime.date
    ) -> dict[str, int | float | str | None]:
        """Fetch analytics data for a project on a given date.

        Returns a dict of column names to values matching the source's
        database table schema. Raises CollectorError on failure.
        """
