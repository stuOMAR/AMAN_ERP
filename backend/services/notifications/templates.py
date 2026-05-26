"""Notification templates — sandboxed Jinja2 renderer with locale fallback.

Contract: see specs/024-workforce-service-comms-integrity/contracts/email-templates.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def render_template(
    conn: Any,
    *,
    tenant_id: str | int,
    code: str,
    locale: str = "en",
    context: dict = None,
) -> dict:
    """Render a notification template with Jinja2.

    Falls back: requested locale → 'en' → raise.
    """
    # Try requested locale
    row = conn.execute(
        text("""
            SELECT id, subject, body_html, body_text
            FROM email_templates
            WHERE tenant_id = :tnt AND code = :code AND locale = :loc
        """),
        {"tnt": str(tenant_id), "code": code, "loc": locale},
    ).fetchone()

    # Fallback to 'en'
    if row is None and locale != "en":
        row = conn.execute(
            text("""
                SELECT id, subject, body_html, body_text
                FROM email_templates
                WHERE tenant_id = :tnt AND code = :code AND locale = 'en'
            """),
            {"tnt": str(tenant_id), "code": code},
        ).fetchone()

    if row is None:
        raise LookupError("notifications.template_missing")

    from jinja2.sandbox import SandboxedEnvironment
    from jinja2 import BaseLoader, select_autoescape, TemplateSyntaxError

    env = SandboxedEnvironment(
        loader=BaseLoader(),
        autoescape=select_autoescape(['html', 'xml']),
    )
    context = context or {}

    try:
        subject = env.from_string(row[1] or "").render(**context) if row[1] else ""
        body_html = env.from_string(row[2] or "").render(**context) if row[2] else ""
        body_text = env.from_string(row[3] or "").render(**context) if row[3] else ""
    except TemplateSyntaxError:
        raise ValueError("template.invalid_jinja")

    return {
        "template_id": row[0],
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
        "locale": locale,
    }
