"""SMTP email sender for HTML analytics reports."""

from __future__ import annotations

import base64
import logging
import re
import smtplib
import uuid
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sites_report.config import EmailConfig

logger = logging.getLogger(__name__)

_BASE64_IMG_RE = re.compile(r'src="data:image/png;base64,([^"]+)"')


class EmailError(Exception):
    """Raised when email sending fails."""


def _extract_inline_images(html: str) -> tuple[str, list[tuple[str, bytes]]]:
    """Replace inline base64 PNG images with CID references.

    Returns the modified HTML and a list of ``(cid, png_bytes)`` tuples.
    """
    images: list[tuple[str, bytes]] = []

    def _replace(match: re.Match[str]) -> str:
        cid = f"chart-{uuid.uuid4().hex[:12]}@sites-report"
        try:
            png_bytes = base64.b64decode(match.group(1))
        except ValueError:
            logger.error("Failed to decode base64 image (CID %s)", cid)
            raise
        images.append((cid, png_bytes))
        return f'src="cid:{cid}"'

    modified = _BASE64_IMG_RE.sub(_replace, html)
    return modified, images


def send_email(cfg: EmailConfig, to: str, subject: str, html: str) -> None:
    """Send an HTML email via SMTP with STARTTLS (port 587).

    Assumes the server supports STARTTLS. Does not support implicit
    TLS on port 465 (``SMTP_SSL``) or plain SMTP on port 25.

    Inline base64 PNG images are automatically extracted and attached
    as MIME image parts with ``Content-ID`` references so that email
    clients (notably Gmail) display them correctly.  Image-free emails
    are sent as plain ``MIMEText`` messages.

    Raises :class:`EmailError` on any SMTP or connection failure.
    """
    try:
        cid_html, images = _extract_inline_images(html)

        if images:
            msg = MIMEMultipart("related")
            msg.attach(MIMEText(cid_html, "html"))
            for cid, png_bytes in images:
                img_part = MIMEImage(png_bytes, _subtype="png")
                img_part.add_header("Content-ID", f"<{cid}>")
                img_part.add_header("Content-Disposition", "inline")
                msg.attach(img_part)
        else:
            msg = MIMEText(html, "html")

        msg["Subject"] = subject
        msg["From"] = cfg.from_address
        msg["To"] = to
    except (TypeError, ValueError, AttributeError, UnicodeEncodeError) as exc:
        logger.error("Failed to construct email for %s: %s", to, exc)
        raise EmailError(f"Failed to construct email for {to}: {exc}") from exc

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
        logger.info("Email sent to %s: %s", to, subject)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        raise EmailError(f"Failed to send email to {to}: {exc}") from exc
