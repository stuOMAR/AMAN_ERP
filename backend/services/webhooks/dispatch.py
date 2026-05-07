"""Webhook dispatch service.

Feature 023 — Unified dispatcher for outbound webhooks.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

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
    # Find active subscriptions for this event
    subs = db.execute(
        text("""
            SELECT id, url, secret FROM webhook_subscriptions
            WHERE tenant_id = :tid
              AND :event = ANY(events)
              AND is_active = true
        """),
        {"tid": tenant_id, "event": event},
    ).fetchall()

    if not subs:
        return None

    outbox_id = None
    for sub in subs:
        try:
            result = db.execute(
                text("""
                    INSERT INTO webhook_outbox (
                        tenant_id, subscription_id, event, payload,
                        state, attempts, created_at, updated_at
                    ) VALUES (
                        :tid, :sub_id, :event, :payload,
                        'pending', 0, clock_timestamp(), clock_timestamp()
                    )
                    RETURNING id
                """),
                {
                    "tid": tenant_id,
                    "sub_id": sub.id,
                    "event": event,
                    "payload": json.dumps(payload),
                },
            )
            row = result.fetchone()
            if row:
                outbox_id = row.id
        except Exception as e:
            logger.warning(f"webhook dispatch: failed for sub={sub.id}: {e}")

    return outbox_id
