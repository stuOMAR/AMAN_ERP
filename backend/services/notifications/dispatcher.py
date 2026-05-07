"""Notifications dispatcher — dispatch with idempotency-key + dedupe-window.

Contract: see specs/024-workforce-service-comms-integrity/contracts/notifications-dispatcher.md
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def dispatch(
    conn: Any,
    *,
    tenant_id: int,
    event_type: str,
    channel: str,
    recipient: str,
    template_code: Optional[str] = None,
    locale: str = "en",
    payload: Optional[dict] = None,
) -> dict:
    """Dispatch a notification.

    Computes idempotency key and checks dedupe window before inserting.
    """
    # Compute idempotency key
    key_input = f"{tenant_id}:{event_type}:{channel}:{recipient}:{template_code}"
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
        {"tnt": tenant_id, "key": idempotency_key, "ws": window_seconds},
    ).fetchone()

    if existing:
        return {"dispatched": False, "reason": "notifications.duplicate_in_window"}

    # Insert into queue
    import json as json_mod
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
            "tnt": tenant_id, "key": idempotency_key, "event": event_type,
            "channel": channel, "recipient": recipient,
            "template": template_code, "locale": locale,
            "payload": json_mod.dumps(payload) if payload else None,
        },
    ).fetchone()
    conn.commit()

    return {"dispatched": True, "queue_id": row[0], "idempotency_key": idempotency_key}
