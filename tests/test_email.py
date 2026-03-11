from __future__ import annotations

import smtplib
from unittest import mock

import pytest

from sites_report.config import EmailConfig
from sites_report.email import EmailError, send_email

_P = "sites_report.email"

_CFG = EmailConfig(
    smtp_host="smtp.example.com",
    smtp_port=587,
    smtp_user="user@example.com",
    smtp_password="secret",
    from_address="reports@example.com",
)


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_happy_path(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value

    send_email(_CFG, "alice@example.com", "Daily Report", "<h1>Hi</h1>")

    assert mock_smtp_cls.call_count == 1
    assert mock_smtp_cls.call_args == mock.call("smtp.example.com", 587, timeout=30)
    assert smtp.starttls.call_count == 1
    assert smtp.login.call_count == 1
    assert smtp.login.call_args == mock.call("user@example.com", "secret")
    assert smtp.send_message.call_count == 1


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_headers(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value

    send_email(_CFG, "bob@example.com", "Weekly Report", "<p>content</p>")

    msg = smtp.send_message.call_args[0][0]
    assert msg["Subject"] == "Weekly Report"
    assert msg["From"] == "reports@example.com"
    assert msg["To"] == "bob@example.com"
    assert msg.get_content_type() == "text/html"


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_smtp_error(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value
    smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Bad credentials")

    match = r"Failed to send email to alice@example\.com"
    with pytest.raises(EmailError, match=match) as exc_info:
        send_email(_CFG, "alice@example.com", "Report", "<p>hi</p>")

    assert isinstance(exc_info.value.__cause__, smtplib.SMTPAuthenticationError)


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_connection_error(mock_smtp_cls: mock.MagicMock) -> None:
    mock_smtp_cls.side_effect = OSError("Connection refused")

    match = r"Failed to send email to alice@example\.com"
    with pytest.raises(EmailError, match=match) as exc_info:
        send_email(_CFG, "alice@example.com", "Report", "<p>hi</p>")

    assert isinstance(exc_info.value.__cause__, OSError)
