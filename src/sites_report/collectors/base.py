"""Abstract base class for data source collectors."""

import datetime
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from sites_report.config import GoogleConfig, ProjectConfig

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """Raised when a data collection operation fails."""


def retry_on_transient[T](
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    is_retryable: Callable[[Exception], bool],
    context: str = "",
) -> T:
    """Call *fn()* with exponential backoff on retryable exceptions.

    On each retryable failure, sleeps ``base_delay * 2^attempt`` seconds
    (with ±25 % jitter) before retrying.  Non-retryable exceptions and
    exhausted attempts re-raise the original exception.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if base_delay <= 0:
        raise ValueError(f"base_delay must be > 0, got {base_delay}")
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            try:
                retryable = is_retryable(exc)
            except Exception:  # noqa: BLE001
                logger.debug("is_retryable check failed, treating as non-retryable", exc_info=True)
                raise exc from None
            if not retryable or attempt + 1 >= max_attempts:
                if attempt > 0 and attempt + 1 >= max_attempts:
                    ctx = f" ({context})" if context else ""
                    logger.error(
                        "Retries exhausted%s after %d/%d attempts: %s",
                        ctx,
                        attempt + 1,
                        max_attempts,
                        exc,
                    )
                raise
            delay = base_delay * (2**attempt)
            delay *= random.uniform(0.75, 1.25)
            ctx = f" ({context})" if context else ""
            logger.warning(
                "Transient error%s, retrying in %.1fs (attempt %d/%d): %s",
                ctx,
                delay,
                attempt + 1,
                max_attempts,
                exc,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


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
