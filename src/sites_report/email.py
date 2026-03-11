"""SMTP email sender for HTML analytics reports."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from sites_report.config import EmailConfig

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Raised when email sending fails."""


def send_email(cfg: EmailConfig, to: str, subject: str, html: str) -> None:
    """Send an HTML email via SMTP with STARTTLS (port 587).

    Assumes the server supports STARTTLS. Does not support implicit
    TLS on port 465 (``SMTP_SSL``) or plain SMTP on port 25.

    Images are expected to be base64-encoded inline in *html*,
    so a simple ``MIMEText`` message is sufficient (no multipart).

    Raises :class:`EmailError` on any SMTP or connection failure.
    """
    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = cfg.from_address
    msg["To"] = to

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
        logger.info("Email sent to %s: %s", to, subject)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        raise EmailError(f"Failed to send email to {to}: {exc}") from exc
