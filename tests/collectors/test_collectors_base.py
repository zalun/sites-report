"""Tests for the abstract collector base class."""

import datetime
from unittest import mock

import pytest

from sites_report.collectors.base import Collector, CollectorError, build_google_credentials
from sites_report.config import GoogleConfig, ProjectConfig


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


@mock.patch("google.oauth2.service_account.Credentials")
def test_build_google_credentials_loads_from_key_file(mock_creds_cls, tmp_path):
    key_file = tmp_path / "sa-key.json"
    key_file.write_text("{}")
    config = GoogleConfig(service_account_key=key_file)
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]

    result = build_google_credentials(config, scopes)

    assert mock_creds_cls.from_service_account_file.call_count == 1
    assert mock_creds_cls.from_service_account_file.call_args == mock.call(
        str(key_file), scopes=scopes,
    )
    assert result is mock_creds_cls.from_service_account_file.return_value


def test_build_google_credentials_raises_on_missing_key_file(tmp_path):
    key_file = tmp_path / "nonexistent.json"
    config = GoogleConfig(service_account_key=key_file)

    with pytest.raises(CollectorError, match="Service account key not found"):
        build_google_credentials(config, ["scope"])


@mock.patch("google.oauth2.service_account.Credentials")
def test_build_google_credentials_raises_on_invalid_key_file(mock_creds_cls, tmp_path):
    key_file = tmp_path / "bad-key.json"
    key_file.write_text("{}")
    config = GoogleConfig(service_account_key=key_file)
    mock_creds_cls.from_service_account_file.side_effect = ValueError("bad format")

    with pytest.raises(CollectorError, match="Invalid service account key"):
        build_google_credentials(config, ["scope"])


@mock.patch("google.oauth2.service_account.Credentials")
def test_build_google_credentials_raises_on_key_error(mock_creds_cls, tmp_path):
    key_file = tmp_path / "bad-key.json"
    key_file.write_text("{}")
    config = GoogleConfig(service_account_key=key_file)
    mock_creds_cls.from_service_account_file.side_effect = KeyError("client_email")

    with pytest.raises(CollectorError, match="Invalid service account key"):
        build_google_credentials(config, ["scope"])


@mock.patch("google.oauth2.service_account.Credentials")
def test_build_google_credentials_raises_on_os_error(mock_creds_cls, tmp_path):
    key_file = tmp_path / "unreadable.json"
    key_file.write_text("{}")
    config = GoogleConfig(service_account_key=key_file)
    mock_creds_cls.from_service_account_file.side_effect = OSError("Permission denied")

    with pytest.raises(CollectorError, match="Invalid service account key"):
        build_google_credentials(config, ["scope"])
