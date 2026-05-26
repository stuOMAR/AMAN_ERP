"""Notifications queue worker — FOR UPDATE SKIP LOCKED claim loop with backoff + DLQ.

Contract: see specs/024-workforce-service-comms-integrity/contracts/notifications-dispatcher.md
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Callable

from sqlalchemy import text

from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    return str(sanitize_for_audit(f"{exc.__class__.__name__}", context="notification_queue_worker"))


def process_queue(
    conn: Any,
    *,
    tenant_id: str | int,
    channel: str,
    handler: Callable,
    batch_size: int = 10,
) -> dict:
    """Process pending notifications for a channel.

    Uses FOR UPDATE SKIP LOCKED to safely claim rows.
    """
    # 0. Stale lock recovery — reset stuck 'sending' state
    try:
        conn.execute(
            text("""
                UPDATE notifications_queue
                SET state = 'pending', next_attempt_at = now()
                WHERE tenant_id = :tnt AND channel = :ch AND state = 'sending'
                  AND claimed_at < now() - INTERVAL '5 minutes'
            """),
            {"tnt": str(tenant_id), "ch": channel},
        )
        conn.commit()
    except Exception:
        logger.error("Failed stale lock recovery for notification queue")

    # Get max attempts setting
    setting = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'notifications.max_attempts'
        """),
    ).fetchone()
    max_attempts = int(setting[0]) if setting else 5

    # Claim rows
    rows = conn.execute(
        text("""
            SELECT id, recipient, template_code, locale, payload, attempts
            FROM notifications_queue
            WHERE tenant_id = :tnt AND channel = :ch AND state = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= now())
            ORDER BY created_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"tnt": str(tenant_id), "ch": channel, "limit": batch_size},
    ).fetchall()

    processed = 0
    failed = 0
    dlq = 0

    for row in rows:
        notif_id = row[0]
        payload = json.loads(row[4]) if row[4] else {}

        # Mark as sending
        conn.execute(
            text("""
                UPDATE notifications_queue
                SET state = 'sending', claimed_at = now()
                WHERE id = :nid
            """),
            {"nid": notif_id},
        )
        conn.commit()

        try:
            res = handler(
                recipient=row[1],
                template_code=row[2],
                locale=row[3],
                payload=payload,
            )

            # Raise exception if handler returned False to trigger failure/retry path
            if res is False:
                raise RuntimeError("Notification delivery handler returned False")

            # Mark as sent
            conn.execute(
                text("""
                    UPDATE notifications_queue
                    SET state = 'sent', sent_at = now()
                    WHERE id = :nid
                """),
                {"nid": notif_id},
            )
            processed += 1

        except Exception as e:
            attempts = row[5] + 1
            safe_error = _safe_error(e)

            if attempts >= max_attempts:
                # Move to DLQ
                conn.execute(
                    text("""
                        UPDATE notifications_queue
                        SET state = 'dlq', dlq_at = now(),
                            attempts = :attempts, last_error = :err
                        WHERE id = :nid
                    """),
                    {"attempts": attempts, "err": safe_error[:1000], "nid": notif_id},
                )
                dlq += 1
            else:
                # Exponential backoff with jitter
                backoff = min(300, 2 ** attempts) + random.randint(0, 30)
                conn.execute(
                    text("""
                        UPDATE notifications_queue
                        SET state = 'pending', attempts = :attempts,
                            next_attempt_at = now() + (:backoff || ' seconds')::interval,
                            last_error = :err
                        WHERE id = :nid
                    """),
                    {"attempts": attempts, "backoff": backoff, "err": safe_error[:1000], "nid": notif_id},
                )
                failed += 1

        conn.commit()

    return {
        "channel": channel,
        "claimed": len(rows),
        "processed": processed,
        "failed": failed,
        "dlq": dlq,
    }
