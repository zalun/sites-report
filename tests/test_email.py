from __future__ import annotations

import base64
import smtplib
from unittest import mock

import pytest

from sites_report.config import EmailConfig
from sites_report.email import EmailError, _extract_inline_images, send_email

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


def test_send_email_construction_error() -> None:
    match = r"Failed to construct email for alice@example\.com"
    with pytest.raises(EmailError, match=match) as exc_info:
        send_email(_CFG, "alice@example.com", "Report", None)  # type: ignore[arg-type]

    assert isinstance(exc_info.value.__cause__, (TypeError, AttributeError))


def test_email_config_repr_hides_password() -> None:
    assert "secret" not in repr(_CFG)


# --- CID image extraction tests ---

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_TINY_B64 = base64.b64encode(_TINY_PNG).decode()


def test_extract_inline_images_finds_images() -> None:
    html = (
        f'<img src="data:image/png;base64,{_TINY_B64}"/>'
        f'<img src="data:image/png;base64,{_TINY_B64}"/>'
    )
    modified, images = _extract_inline_images(html)

    assert len(images) == 2
    assert "data:image/png;base64," not in modified
    for cid, png_bytes in images:
        assert cid.endswith("@sites-report")
        assert png_bytes == _TINY_PNG
        assert f'src="cid:{cid}"' in modified


def test_extract_inline_images_no_images() -> None:
    html = "<p>No images here</p>"
    modified, images = _extract_inline_images(html)

    assert modified == html
    assert images == []


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_with_images_builds_multipart(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value
    html = f'<img src="data:image/png;base64,{_TINY_B64}"/>'

    send_email(_CFG, "alice@example.com", "Report", html)

    msg = smtp.send_message.call_args[0][0]
    assert msg.get_content_type() == "multipart/related"

    parts = list(msg.walk())
    # first child is text/html
    html_part = parts[1]
    assert html_part.get_content_type() == "text/html"
    assert "cid:" in html_part.get_payload(decode=True).decode()
    assert "data:image/png;base64," not in html_part.get_payload(decode=True).decode()

    # second child is image/png
    img_part = parts[2]
    assert img_part.get_content_type() == "image/png"
    assert img_part["Content-ID"].startswith("<chart-")
    assert img_part["Content-Disposition"] == "inline"


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_without_images_stays_simple(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value

    send_email(_CFG, "alice@example.com", "Report", "<p>plain</p>")

    msg = smtp.send_message.call_args[0][0]
    assert msg.get_content_type() == "text/html"


@mock.patch(f"{_P}.smtplib.SMTP")
def test_send_email_multipart_preserves_headers(mock_smtp_cls: mock.MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value
    html = f'<img src="data:image/png;base64,{_TINY_B64}"/>'

    send_email(_CFG, "bob@example.com", "Weekly Report", html)

    msg = smtp.send_message.call_args[0][0]
    assert msg["Subject"] == "Weekly Report"
    assert msg["From"] == "reports@example.com"
    assert msg["To"] == "bob@example.com"


