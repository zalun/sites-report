"""Abstract base class for data source collectors."""

import datetime
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sites_report.config import GoogleConfig, ProjectConfig

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials

logger = logging.getLogger(__name__)


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


def build_google_credentials(
    google_config: GoogleConfig,
    scopes: list[str],
) -> ServiceAccountCredentials:
    """Load Google service account credentials from the configured key file."""
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials

    key_path = google_config.service_account_key
    if not key_path.is_file():
        logger.error("Service account key not found: %s", key_path)
        raise CollectorError(f"Service account key not found: {key_path}")
    try:
        return ServiceAccountCredentials.from_service_account_file(
            str(key_path),
            scopes=scopes,
        )
    except (ValueError, KeyError, OSError) as exc:
        logger.error("Invalid service account key '%s': %s", key_path, exc)
        raise CollectorError(f"Invalid service account key '{key_path}': {exc}") from exc
