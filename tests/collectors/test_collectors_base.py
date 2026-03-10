"""Tests for the abstract collector base class."""

import datetime

import pytest

from sites_report.collectors.base import Collector, CollectorError
from sites_report.config import ProjectConfig


def test_collector_cannot_be_instantiated():
    with pytest.raises(TypeError, match="abstract method"):
        Collector()  # type: ignore[abstract]


def test_subclass_without_fetch_cannot_be_instantiated():
    class Incomplete(Collector):
        pass

    with pytest.raises(TypeError, match="abstract method"):
        Incomplete()  # type: ignore[abstract]


def test_concrete_collector_can_be_instantiated():
    class Concrete(Collector):
        def fetch(
            self, project: ProjectConfig, date: datetime.date
        ) -> dict[str, int | float | str | None]:
            return {"sessions": 42}

    collector = Concrete()
    assert isinstance(collector, Collector)


def test_collector_error_is_exception_subclass():
    assert issubclass(CollectorError, Exception)


def test_collector_error_can_be_raised_and_caught():
    with pytest.raises(CollectorError, match="API timeout"):
        raise CollectorError("API timeout")
