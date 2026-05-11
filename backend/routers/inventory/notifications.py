"""
Inventory Module - Notifications
"""

from fastapi import Request, APIRouter, Depends, HTTPException
from sqlalchemy import text
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from typing import Any, Dict, List

notifications_router = APIRouter()
logger = logging.getLogger(__name__)


@notifications_router.get("/notifications", dependencies=[Depends(require_permission("notifications.view"))], response_model=Dict[str, Any])
def get_notifications(request: Request, 
    current_user: dict = Depends(get_current_user)
):
    """عرض إشعارات المستخدم"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    if not company_id:
        return []
    db = get_db_connection(company_id)
    try:
        result = db.execute(text("""
            SELECT * FROM notifications
            WHERE user_id = :user OR user_id IS NULL
            ORDER BY created_at DESC
            LIMIT 50
        """), {"user": user_id}).fetchall()

        # Convert rows to dicts safely
        notifications = []
        for r in result:
            if hasattr(r, '_mapping'):
                n_dict = dict(r._mapping)
            else:
                n_dict = dict(r)
            notifications.append(n_dict)

        return notifications
    except Exception:
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Failed to fetch inventory notifications")
        raise HTTPException(**http_error(500, "notifications_load_failed", request))
    finally:
        db.close()


@notifications_router.get("/notifications/unread-count", dependencies=[Depends(require_permission("notifications.view"))], response_model=Dict[str, Any])
def get_unread_count(request: Request, 
    current_user: dict = Depends(get_current_user)
):
    """عدد الإشعارات غير المقروءة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    if not company_id:
        return {"count": 0}
    db = get_db_connection(company_id)
    try:
        count = db.execute(text("""
            SELECT COUNT(*) FROM notifications
            WHERE (user_id = :user OR user_id IS NULL) AND is_read = FALSE
        """), {"user": user_id}).scalar()
        return {"count": count}
    except Exception:
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Failed to fetch unread notification count")
        raise HTTPException(**http_error(500, "notifications_count_failed", request))
    finally:
        db.close()


@notifications_router.post("/notifications/{id}/read", dependencies=[Depends(require_permission("notifications.view"))], response_model=Dict[str, Any])
def mark_notification_read(request: Request, 
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """تحديد الإشعار كمقروء"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else getattr(current_user, "company_id", None)
    if not company_id:
        return {"success": False}
    db = get_db_connection(company_id)
    try:
        db.execute(text("""
            UPDATE notifications SET is_read = TRUE, read_at = NOW() WHERE id = :id
        """), {"id": id})
        db.commit()
        return {"message": i18n_message("notification_marked_read", request)}
    finally:
        db.close()


@notifications_router.post("/notifications/read-all", dependencies=[Depends(require_permission("notifications.view"))], response_model=Dict[str, Any])
def mark_all_notifications_read(request: Request, 
    current_user: dict = Depends(get_current_user)
):
    """تحديد جميع الإشعارات كمقروءة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    db = get_db_connection(company_id)
    try:
        db.execute(text("""
            UPDATE notifications SET is_read = TRUE, read_at = NOW()
            WHERE (user_id = :user OR user_id IS NULL) AND is_read = FALSE
        """), {"user": user_id})
        db.commit()
        return {"message": i18n_message("all_notifications_marked_read", request)}
    finally:
        db.close()
