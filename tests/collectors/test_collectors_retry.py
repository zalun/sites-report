"""Tests for retry_on_transient() helper."""

from unittest import mock
from unittest.mock import MagicMock

import pytest

from sites_report.collectors.base import retry_on_transient

_PATCH_SLEEP = "sites_report.collectors.base.time.sleep"
_PATCH_UNIFORM = "sites_report.collectors.base.random.uniform"


class _TransientError(Exception):
    pass


class _PermanentError(Exception):
    pass


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, _TransientError)


@mock.patch(_PATCH_SLEEP)
def test_success_no_retry(mock_sleep: MagicMock) -> None:
    fn = MagicMock(return_value=42)
    result = retry_on_transient(fn, is_retryable=_is_retryable)
    assert result == 42
    assert fn.call_count == 1
    assert mock_sleep.call_count == 0


@mock.patch(_PATCH_SLEEP)
def test_transient_error_then_success(mock_sleep: MagicMock) -> None:
    fn = MagicMock(side_effect=[_TransientError("oops"), 42])
    result = retry_on_transient(fn, is_retryable=_is_retryable)
    assert result == 42
    assert fn.call_count == 2
    assert mock_sleep.call_count == 1


@mock.patch(_PATCH_SLEEP)
def test_exhausted_retries_raises(mock_sleep: MagicMock) -> None:
    fn = MagicMock(side_effect=_TransientError("fail"))
    with pytest.raises(_TransientError, match="fail"):
        retry_on_transient(fn, max_attempts=3, is_retryable=_is_retryable)
    assert fn.call_count == 3
    assert mock_sleep.call_count == 2


@mock.patch(_PATCH_SLEEP)
def test_permanent_error_raises_immediately(mock_sleep: MagicMock) -> None:
    fn = MagicMock(side_effect=_PermanentError("denied"))
    with pytest.raises(_PermanentError, match="denied"):
        retry_on_transient(fn, is_retryable=_is_retryable)
    assert fn.call_count == 1
    assert mock_sleep.call_count == 0


@mock.patch(_PATCH_UNIFORM, return_value=1.0)
@mock.patch(_PATCH_SLEEP)
def test_backoff_increases_exponentially(mock_sleep: MagicMock, _mock_uniform: MagicMock) -> None:
    fn = MagicMock(side_effect=[_TransientError("1"), _TransientError("2"), 42])
    retry_on_transient(fn, base_delay=2.0, is_retryable=_is_retryable)
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [2.0, 4.0]


@mock.patch(_PATCH_SLEEP)
def test_context_appears_in_log(mock_sleep: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    fn = MagicMock(side_effect=[_TransientError("boom"), 42])
    retry_on_transient(fn, is_retryable=_is_retryable, context="my-api call")
    assert "my-api call" in caplog.text


@mock.patch(_PATCH_SLEEP)
def test_is_retryable_crash_preserves_original_error(mock_sleep: MagicMock) -> None:
    """If is_retryable itself raises, the original exception should propagate."""

    def broken_retryable(exc: Exception) -> bool:
        raise ValueError("retryable check crashed")

    fn = MagicMock(side_effect=_TransientError("original"))
    with pytest.raises(_TransientError, match="original"):
        retry_on_transient(fn, is_retryable=broken_retryable)
    assert fn.call_count == 1
    assert mock_sleep.call_count == 0


def test_max_attempts_zero_raises_value_error() -> None:
    fn = MagicMock(return_value=42)
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        retry_on_transient(fn, max_attempts=0, is_retryable=_is_retryable)


def test_base_delay_zero_raises_value_error() -> None:
    fn = MagicMock(return_value=42)
    with pytest.raises(ValueError, match="base_delay must be > 0"):
        retry_on_transient(fn, base_delay=0, is_retryable=_is_retryable)


@mock.patch(_PATCH_SLEEP)
def test_exhaustion_logs_error(mock_sleep: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    fn = MagicMock(side_effect=_TransientError("server down"))
    with pytest.raises(_TransientError):
        retry_on_transient(fn, max_attempts=2, is_retryable=_is_retryable, context="test-ctx")
    assert "Retries exhausted" in caplog.text
    assert "test-ctx" in caplog.text
