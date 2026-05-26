"""Notifications dispatcher — dispatch with idempotency-key + dedupe-window.

Contract: see specs/024-workforce-service-comms-integrity/contracts/notifications-dispatcher.md
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def dispatch(
    conn: Any,
    *,
    tenant_id: str | int,
    event_type: str,
    channel: str,
    recipient: str,
    template_code: Optional[str] = None,
    locale: str = "en",
    payload: Optional[dict] = None,
    commit: bool = True,
) -> dict:
    """Dispatch a notification.

    Computes idempotency key and checks dedupe window before inserting.
    """
    # Compute idempotency key
    payload_for_key = json.dumps(payload or {}, sort_keys=True, default=str)
    key_input = f"{tenant_id}:{event_type}:{channel}:{recipient}:{template_code}:{payload_for_key}"
    idempotency_key = hashlib.md5(key_input.encode()).hexdigest()

    # Check dedupe window
    setting = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'notifications.dedupe_window_seconds'
        """),
    ).fetchone()
    window_seconds = int(setting[0]) if setting else 300

    existing = conn.execute(
        text("""
            SELECT 1 FROM notifications_queue
            WHERE tenant_id = :tnt AND idempotency_key = :key
              AND state IN ('pending', 'sending', 'sent')
              AND created_at > now() - (:ws || ' seconds')::interval
            LIMIT 1
        """),
        {"tnt": str(tenant_id), "key": idempotency_key, "ws": window_seconds},
    ).fetchone()

    if existing:
        return {"dispatched": False, "reason": "notifications.duplicate_in_window"}

    # Insert into queue
    row = conn.execute(
        text("""
            INSERT INTO notifications_queue
                (tenant_id, idempotency_key, event_type, channel, recipient,
                 template_code, locale, payload, state, created_at)
            VALUES
                (:tnt, :key, :event, :channel, :recipient,
                 :template, :locale, :payload, 'pending', now())
            RETURNING id
        """),
        {
            "tnt": str(tenant_id), "key": idempotency_key, "event": event_type,
            "channel": channel, "recipient": recipient,
            "template": template_code, "locale": locale,
            "payload": json.dumps(payload, default=str) if payload else None,
        },
    ).fetchone()
    if commit:
        conn.commit()

    return {"dispatched": True, "queue_id": row[0], "idempotency_key": idempotency_key}


def dispatch_user_notification(
    conn: Any,
    *,
    tenant_id: int | str,
    recipient_id: int,
    event_type: str,
    channel: str,
    title: str,
    body: str,
    template_code: Optional[str] = None,
    locale: str = "en",
    feature_source: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    link: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Queue a user-targeted notification through the canonical dispatcher."""
    return dispatch(
        conn,
        tenant_id=str(tenant_id),
        event_type=event_type,
        channel=channel,
        recipient=f"user:{int(recipient_id)}",
        template_code=template_code,
        locale=locale,
        payload={
            "recipient_id": recipient_id,
            "title": title,
            "body": body,
            "feature_source": feature_source,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "link": link,
        },
        commit=commit,
    )


async def dispatch_notification(
    *,
    channel: str,
    subject: str,
    body: str,
    tenant_id: int | str,
    metadata: Optional[dict] = None,
    recipient: Optional[str] = None,
    template_code: Optional[str] = None,
    locale: str = "en",
) -> dict:
    """Async compatibility wrapper used by older notification producers."""
    from database import get_db_connection

    metadata = metadata or {}
    resolved_recipient = (
        recipient
        or metadata.get("recipient")
        or (f"user:{metadata['recipient_id']}" if metadata.get("recipient_id") is not None else None)
        or "system"
    )

    conn = get_db_connection(str(tenant_id))
    try:
        return dispatch(
            conn,
            tenant_id=str(tenant_id),
            event_type=str(metadata.get("event_type") or "notification.generic"),
            channel=channel,
            recipient=str(resolved_recipient),
            template_code=template_code,
            locale=locale,
            payload={**metadata, "subject": subject, "body": body},
        )
    finally:
        conn.close()
