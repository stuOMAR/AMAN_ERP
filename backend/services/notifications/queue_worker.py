"""Notifications queue worker — FOR UPDATE SKIP LOCKED claim loop with backoff + DLQ.

Contract: see specs/024-workforce-service-comms-integrity/contracts/notifications-dispatcher.md
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text

logger = logging.getLogger(__name__)


def process_queue(
    conn: Any,
    *,
    tenant_id: int,
    channel: str,
    handler: Callable,
    batch_size: int = 10,
) -> dict:
    """Process pending notifications for a channel.

    Uses FOR UPDATE SKIP LOCKED to safely claim rows.
    """
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
        {"tnt": tenant_id, "ch": channel, "limit": batch_size},
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
            handler(
                recipient=row[1],
                template_code=row[2],
                locale=row[3],
                payload=payload,
            )

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

            if attempts >= max_attempts:
                # Move to DLQ
                conn.execute(
                    text("""
                        UPDATE notifications_queue
                        SET state = 'dlq', dlq_at = now(),
                            attempts = :attempts, last_error = :err
                        WHERE id = :nid
                    """),
                    {"attempts": attempts, "err": str(e)[:1000], "nid": notif_id},
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
                    {"attempts": attempts, "backoff": backoff, "err": str(e)[:1000], "nid": notif_id},
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
