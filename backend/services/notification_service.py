"""Unified Notification Service — dispatches notifications through enabled channels.

Channels: in_app (DB insert + WebSocket push), email, push (Firebase FCM).

Usage:
    await notification_service.dispatch(
        db=db,
        company_id=company_id,
        recipient_id=user_id,
        event_type="leave_approved",
        title="Leave Approved",
        body="Your leave request has been approved.",
        feature_source="self_service",
        reference_type="leave_request",
        reference_id=42,
    )
"""

import html
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger("aman.notification_service")

# Channels supported by the dispatcher
_CHANNEL_IN_APP = "in_app"
_CHANNEL_EMAIL = "email"
_CHANNEL_PUSH = "push"
_PREF_CACHE_TTL_SECONDS = 300
_preference_cache: dict[tuple[str, int, str], tuple[float, list[str]]] = {}


class NotificationService:
    """Dispatch notifications to one or more channels based on user preferences."""

    async def dispatch(
        self,
        db,
        company_id: str,
        recipient_id: int,
        event_type: str,
        title: str,
        body: str,
        feature_source: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        link: Optional[str] = None,
        depth: int = 0,
    ) -> None:
        """Send a notification to all enabled channels for the recipient.

        Falls back to all channels enabled when no preference row exists.
        depth guard prevents infinite dispatch loops (max 5 levels).
        """
        if depth >= 5:
            logger.warning(
                "Notification dispatch depth limit reached for user %s (%s) — aborting",
                recipient_id, event_type,
            )
            return
        # T10.1 P1 #91 — per-user-per-hour notification rate limit, so a
        # runaway producer (e.g. a bad scheduler loop) cannot flood a
        # single user. Limit is read from ``company_settings`` key
        # ``notification_rate_per_hour`` (default 50). Setting to 0
        # disables the cap.
        if not self._rate_limit_ok(db, company_id, recipient_id):
            logger.warning(
                "Notification rate limit exceeded for user %s in company %s — dropping %s",
                recipient_id, company_id, event_type,
            )
            return
        channels = self._get_enabled_channels(db, company_id, recipient_id, event_type)
        for channel in channels:
            try:
                await self._dispatch_channel(
                    db=db,
                    company_id=company_id,
                    recipient_id=recipient_id,
                    channel=channel,
                    event_type=event_type,
                    title=title,
                    body=body,
                    feature_source=feature_source,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    link=link,
                )
            except Exception:
                # T023: On failure, update delivery tracking columns
                logger.warning(
                    "Failed to dispatch %s notification to user %s (%s)",
                    channel, recipient_id, event_type,
                )
                self._mark_delivery_failed(db, recipient_id, channel)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit_ok(self, db, company_id: str, recipient_id: int) -> bool:
        """Return False when the user has exceeded their hourly cap.

        Reads ``notification_rate_per_hour`` from ``company_settings``;
        default 50, ``0`` disables. Counts rows in ``notifications``
        sent to ``recipient_id`` in the last 60 minutes.
        """
        try:
            limit_row = db.execute(text(
                "SELECT setting_value FROM company_settings "
                "WHERE setting_key = 'notification_rate_per_hour'"
            )).scalar()
            try:
                limit = int(limit_row) if limit_row not in (None, "") else 50
            except (ValueError, TypeError):
                limit = 50
            if limit <= 0:
                return True
            recent = db.execute(text(
                "SELECT COUNT(*) FROM notifications "
                "WHERE recipient_id = :uid "
                "  AND created_at >= NOW() - INTERVAL '1 hour'"
            ), {"uid": recipient_id}).scalar() or 0
            return int(recent) < limit
        except Exception:
            # Fail open — never block business flow on a metering bug.
            logger.exception("notification rate-limit check failed; allowing dispatch")
            return True

    def _get_enabled_channels(self, db, company_id: str, user_id: int, event_type: str) -> list[str]:
        """Return list of channels enabled for this user+event_type.

        Defaults to all three channels when no preference row is found.
        """
        cache_key = (str(company_id), int(user_id), event_type)
        cached = _preference_cache.get(cache_key)
        now = time.time()
        if cached and cached[0] > now:
            return list(cached[1])

        row = db.execute(
            text(
                "SELECT email_enabled, in_app_enabled, push_enabled "
                "FROM notification_preferences "
                "WHERE user_id = :uid AND event_type = :evt "
                "LIMIT 1"
            ),
            {"uid": user_id, "evt": event_type},
        ).fetchone()

        if row is None:
            channels = [_CHANNEL_IN_APP, _CHANNEL_EMAIL, _CHANNEL_PUSH]
            _preference_cache[cache_key] = (now + _PREF_CACHE_TTL_SECONDS, channels)
            return channels

        enabled = []
        if row.in_app_enabled:
            enabled.append(_CHANNEL_IN_APP)
        if row.email_enabled:
            enabled.append(_CHANNEL_EMAIL)
        if row.push_enabled:
            enabled.append(_CHANNEL_PUSH)
        _preference_cache[cache_key] = (now + _PREF_CACHE_TTL_SECONDS, enabled)
        return enabled

    async def _dispatch_channel(
        self,
        db,
        company_id: str,
        recipient_id: int,
        channel: str,
        event_type: str,
        title: str,
        body: str,
        feature_source: Optional[str],
        reference_type: Optional[str],
        reference_id: Optional[int],
        link: Optional[str],
    ) -> None:
        if channel == _CHANNEL_IN_APP:
            await self._send_in_app(
                db=db,
                company_id=company_id,
                recipient_id=recipient_id,
                event_type=event_type,
                title=title,
                body=body,
                feature_source=feature_source,
                reference_type=reference_type,
                reference_id=reference_id,
                link=link,
            )
        elif channel == _CHANNEL_EMAIL:
            self._send_email(db=db, recipient_id=recipient_id, title=title, body=body, tenant_id=company_id)
        elif channel == _CHANNEL_PUSH:
            await self._send_push(
                db=db,
                recipient_id=recipient_id,
                title=title,
                body=body,
            )

    async def _send_in_app(
        self,
        db,
        company_id: str,
        recipient_id: int,
        event_type: str,
        title: str,
        body: str,
        feature_source: Optional[str],
        reference_type: Optional[str],
        reference_id: Optional[int],
        link: Optional[str],
    ) -> None:
        """Insert notification row and push via WebSocket."""
        # Sanitize user-supplied content before persisting / sending
        title = html.escape(title)
        body = html.escape(body)
        now = datetime.now(timezone.utc)
        result = db.execute(
            text(
                "INSERT INTO notifications "
                "(user_id, title, message, body, link, is_read, type, "
                " channel, event_type, feature_source, reference_type, reference_id, "
                " status, sent_at, company_id, created_at) "
                "VALUES "
                "(:uid, :title, :msg, :body, :link, false, 'info', "
                " 'in_app', :evt, :fsrc, :rtype, :rid, "
                " 'sent', :now, :cid, :now) "
                "RETURNING id"
            ),
            {
                "uid": recipient_id,
                "title": title,
                "msg": body,
                "body": body,
                "link": link,
                "evt": event_type,
                "fsrc": feature_source,
                "rtype": reference_type,
                "rid": reference_id,
                "now": now,
                "cid": company_id,
            },
        )
        db.commit()
        notif_id = result.scalar()

        # Push via WebSocket (best-effort)
        try:
            from utils.ws_manager import ws_manager

            await ws_manager.send_to_user(
                company_id,
                recipient_id,
                {
                    "type": "notification",
                    "id": notif_id,
                    "title": title,
                    "body": body,
                    "event_type": event_type,
                    "link": link,
                },
            )
        except Exception as exc:
            logger.debug("WebSocket push skipped (user not connected): %s", exc)

    def _send_email(self, db, recipient_id: int, title: str, body: str, *, tenant_id: Optional[str] = None) -> None:
        """Send email notification via existing email_service."""
        try:
            from services.email_service import send_notification_email

            html_body = f"<p>{html.escape(str(body or ''))}</p>"
            subject = html.escape(str(title or "Notification"))
            send_notification_email(db, recipient_id, subject, html_body, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Email notification failed for user %s: %s", recipient_id, exc)

    async def _send_push(self, db, recipient_id: int, title: str, body: str) -> None:
        """Send Firebase FCM push notification (best-effort; token lookup required)."""
        try:
            import firebase_admin.messaging as fcm

            token = self._get_fcm_token(db, recipient_id)
            if not token:
                return
            message = fcm.Message(
                notification=fcm.Notification(title=title, body=body),
                token=token,
            )
            fcm.send(message)
        except ImportError:
            logger.debug("firebase-admin not available; skipping push notification")
        except Exception as exc:
            logger.warning("Push notification failed for user %s: %s", recipient_id, exc)

    def _get_fcm_token(self, db, user_id: int) -> Optional[str]:
        """Look up the FCM device token for a user.

        Priority: push_devices table (mobile app) → company_users.fcm_token (legacy).
        """
        try:
            row = db.execute(
                text("""SELECT fcm_token FROM push_devices
                        WHERE user_id = :uid AND is_active = TRUE
                        ORDER BY last_seen_at DESC LIMIT 1"""),
                {"uid": user_id},
            ).fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            pass  # table may not exist yet in all tenant DBs
        row = db.execute(
            text("SELECT fcm_token FROM company_users WHERE id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
        return row.fcm_token if row and hasattr(row, "fcm_token") else None

    def _mark_delivery_failed(
        self,
        db,
        recipient_id: int,
        channel: str,
        *,
        notification_id: Optional[int] = None,
    ) -> None:
        """T023: Mark a notification as failed for retry tracking.

        When ``notification_id`` is provided the update targets that specific
        row; otherwise the most-recent unread in_app notification for the
        recipient is updated as a best-effort fallback.
        """
        try:
            if notification_id is not None:
                db.execute(
                    text(
                        "UPDATE notifications SET delivery_status = 'failed', "
                        "delivery_channel = :channel, retry_count = 0, last_retry_at = NOW() "
                        "WHERE id = :notif_id"
                    ),
                    {"channel": channel, "notif_id": notification_id},
                )
            else:
                db.execute(
                    text(
                        "UPDATE notifications SET delivery_status = 'failed', "
                        "delivery_channel = :channel, retry_count = 0, last_retry_at = NOW() "
                        "WHERE id = ("
                        "  SELECT id FROM notifications "
                        "  WHERE user_id = :uid AND channel = 'in_app' "
                        "  ORDER BY created_at DESC LIMIT 1"
                        ")"
                    ),
                    {"channel": channel, "uid": recipient_id},
                )
            db.commit()
        except Exception:
            pass  # Column may not exist yet in all tenant schemas


# Module-level singleton
notification_service = NotificationService()


def _update_delivery_status(db, notif_id: int, status: str, channel: str) -> None:
    """Update delivery tracking columns on a notification row (best-effort)."""
    try:
        db.execute(
            text(
                "UPDATE notifications SET delivery_status = :status, "
                "delivery_channel = :channel WHERE id = :id"
            ),
            {"status": status, "channel": channel, "id": notif_id},
        )
        db.commit()
    except Exception:
        pass  # Column may not exist yet if migration hasn't run
