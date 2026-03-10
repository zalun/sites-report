"""Tests for the abstract collector base class."""

from __future__ import annotations

import datetime

import pytest

from sites_report.collectors.base import Collector, CollectorError
from sites_report.config import ProjectConfig


class TestCollectorABC:
    def test_collector_cannot_be_instantiated(self):
        with pytest.raises(TypeError, match="abstract method"):
            Collector()  # type: ignore[abstract]

    def test_subclass_without_fetch_cannot_be_instantiated(self):
        class Incomplete(Collector):
            pass

        with pytest.raises(TypeError, match="abstract method"):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_collector_can_be_instantiated(self):
        class Concrete(Collector):
            def fetch(self, project: ProjectConfig, date: datetime.date) -> dict:
                return {"sessions": 42}

        collector = Concrete()
        assert isinstance(collector, Collector)


class TestCollectorError:
    def test_is_exception_subclass(self):
        assert issubclass(CollectorError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(CollectorError, match="API timeout"):
            raise CollectorError("API timeout")
