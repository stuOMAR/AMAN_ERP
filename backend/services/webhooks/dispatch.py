"""Webhook dispatch service.

Feature 023 — Unified dispatcher for outbound webhooks.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)


def dispatch(
    db: Any,
    *,
    tenant_id: int,
    event: str,
    payload: dict,
) -> int | None:
    """Dispatch a webhook event.

    Looks up active webhook subscriptions for the tenant and event,
    then queues delivery via the webhook_outbox table.

    Returns the outbox row id, or None if no subscribers.
    """
    # Find active subscriptions for this event. The public admin UI stores
    # webhook subscriptions in the legacy `webhooks` table; the dispatcher
    # queues deliveries into the canonical outbox.
    subs = db.execute(
        text("""
            SELECT id, url, secret
              FROM webhooks
             WHERE is_active = true
               AND events @> CAST(:event_json AS JSONB)
        """),
        {"event_json": json.dumps([event])},
    ).fetchall()

    if not subs:
        return None

    outbox_id = None
    for sub in subs:
        try:
            safe_payload = sanitize_for_audit(payload or {}, context="webhook_dispatch")
            payload_json = json.dumps(safe_payload, default=str, sort_keys=True)
            result = db.execute(
                text("""
                    INSERT INTO webhook_outbox (
                        tenant_id, webhook_id, event, payload,
                        state, attempts, next_attempt_at, created_at, updated_at
                    )
                    SELECT
                        :tid, :sub_id, :event, CAST(:payload AS JSONB),
                        'pending', 0, clock_timestamp(), clock_timestamp(), clock_timestamp()
                    WHERE NOT EXISTS (
                        SELECT 1
                          FROM webhook_outbox
                         WHERE tenant_id = :tid
                           AND webhook_id = :sub_id
                           AND event = :event
                           AND payload = CAST(:payload AS JSONB)
                           AND state IN ('pending', 'processing', 'sent')
                    )
                    RETURNING id
                """),
                {
                    "tid": tenant_id,
                    "sub_id": sub.id,
                    "event": event,
                    "payload": payload_json,
                },
            )
            row = result.fetchone()
            if row:
                outbox_id = row.id
        except Exception:
            logger.warning("webhook dispatch failed for subscription %s", sub.id)

    return outbox_id
