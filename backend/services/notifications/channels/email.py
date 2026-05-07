"""Email channel adapter — reads templates, SMTP from vault."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def send_email(
    *,
    recipient: str,
    subject: str,
    body_html: str,
    body_text: str = "",
    smtp_config: Optional[dict] = None,
) -> bool:
    """Send an email via SMTP."""
    if not smtp_config:
        logger.warning("SMTP not configured; email not sent to %s", recipient)
        return False

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_config.get("from", "noreply@aman.sa")
    msg["To"] = recipient

    if body_text:
        msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(smtp_config["host"], smtp_config.get("port", 587)) as server:
            if smtp_config.get("use_tls", True):
                server.starttls()
            if smtp_config.get("username"):
                server.login(smtp_config["username"], smtp_config["password"])
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        raise
