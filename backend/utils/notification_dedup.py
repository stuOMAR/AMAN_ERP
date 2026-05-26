"""
Notification deduplication utility.

Prevents duplicate notifications within a configurable time window.
Uses Redis if available, falls back to DB-based dedup.

Constitution §17: Notification channels must be idempotent.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def _make_dedup_key(user_id: int, event_type: str, reference_id: Optional[str] = None) -> str:
    """Generate a dedup key for a notification."""
    payload = f"{user_id}:{event_type}:{reference_id or ''}"
    return f"notif_dedup:{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def is_duplicate_notification(
    db,
    user_id: int,
    event_type: str,
    reference_id: Optional[str] = None,
    window_seconds: int = 300,
) -> bool:
    """Check if a similar notification was sent recently.

    Returns True if a duplicate exists within the window (should skip).
    Returns False if this is a new notification (should send).
    """
    try:
        from sqlalchemy import text
        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)

        existing = db.execute(text("""
            SELECT id FROM notifications
            WHERE user_id = :uid
              AND event_type = :event_type
              AND (reference_id = :ref_id OR (:ref_id IS NULL AND reference_id IS NULL))
              AND created_at >= :cutoff
            LIMIT 1
        """), {
            "uid": user_id,
            "event_type": event_type,
            "ref_id": str(reference_id) if reference_id else None,
            "cutoff": cutoff,
        }).fetchone()

        return existing is not None
    except Exception as e:
        logger.warning("Notification dedup check failed: %s", e)
        return False  # Fail open — send the notification


def should_send_notification(
    db,
    user_id: int,
    event_type: str,
    reference_id: Optional[str] = None,
    window_seconds: int = 300,
) -> bool:
    """Returns True if the notification should be sent (not a duplicate)."""
    return not is_duplicate_notification(db, user_id, event_type, reference_id, window_seconds)
