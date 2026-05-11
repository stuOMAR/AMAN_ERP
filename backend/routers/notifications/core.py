
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.limiter import limiter
from utils.ws_manager import ws_manager
import html as html_lib
import logging

logger = logging.getLogger("aman.notifications")

router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: int
    title: str
    message: Optional[str]
    link: Optional[str]
    is_read: bool
    type: str
    created_at: datetime

class NotificationCreate(BaseModel):
    user_id: int
    title: str
    message: Optional[str] = None
    link: Optional[str] = None
    type: str = "info"
    send_email: bool = False
    send_sms: bool = False


# ===================== User Notifications =====================

@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """جلب إشعارات المستخدم الحالي"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return []

    with transactional(company_id) as db:
        result = db.execute(text("""
            SELECT id, user_id, title, message, link, is_read, 
                   type, created_at
            FROM notifications 
            WHERE user_id = :uid 
            ORDER BY created_at DESC 
            LIMIT :limit
        """), {"uid": current_user.id, "limit": limit}).fetchall()
        return [dict(r._mapping) for r in result]

@router.get("/unread-count", response_model=Dict[str, Any])
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    """عدد الإشعارات غير المقروءة"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"count": 0}

    with transactional(company_id) as db:
        count = db.execute(text("""
            SELECT COUNT(*) FROM notifications 
            WHERE user_id = :uid AND is_read = FALSE
        """), {"uid": current_user.id}).scalar()
        return {"count": count}

@router.put("/{notification_id}/read", response_model=Dict[str, Any])
async def mark_read(notification_id: int, current_user: dict = Depends(get_current_user)):
    """تحديد إشعار كمقروء"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"success": False}

    with transactional(company_id) as db:
        db.execute(text("""
            UPDATE notifications 
            SET is_read = TRUE 
            WHERE id = :id AND user_id = :uid
        """), {"id": notification_id, "uid": current_user.id})
        return {"success": True}

@router.post("/mark-all-read", response_model=Dict[str, Any])
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    """تحديد الكل كمقروء"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"success": False}

    with transactional(company_id) as db:
        db.execute(text("""
            UPDATE notifications 
            SET is_read = TRUE 
            WHERE user_id = :uid AND is_read = FALSE
        """), {"uid": current_user.id})
        return {"success": True}


# ===================== Create Notification with Email/SMS =====================

@router.post("/send", dependencies=[Depends(require_permission(["notifications.send", "admin"]))], response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def create_and_send_notification(
    data: NotificationCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    إنشاء إشعار مع إرسال اختياري عبر البريد الإلكتروني و SMS
    """
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "notifications_no_company", request))

    db = get_db_connection(company_id)
    try:
        # 1. Create in-app notification
        notif_row = db.execute(text("""
            INSERT INTO notifications (user_id, title, message, link, is_read, type, created_at)
            VALUES (:uid, :title, :msg, :link, FALSE, :type, CURRENT_TIMESTAMP)
            RETURNING id, created_at
        """), {
            "uid": data.user_id,
            "title": data.title,
            "msg": data.message,
            "link": data.link,
            "type": data.type
        }).fetchone()

        results = {"in_app": True, "email": None, "sms": None}

        # Push via WebSocket in real-time
        if notif_row:
            try:
                await push_notification(company_id, data.user_id, {
                    "id": notif_row.id,
                    "title": data.title,
                    "message": data.message,
                    "link": data.link,
                    "type": data.type,
                    "is_read": False,
                    "created_at": notif_row.created_at.isoformat() if notif_row.created_at else None
                })
            except Exception:
                logger.debug("WS push during notification create failed")

        # 2. Send email if requested
        if data.send_email:
            try:
                from services.email_service import send_notification_email, get_base_template
                safe_title = html_lib.escape(str(data.title or ""))
                safe_message = html_lib.escape(str(data.message or ""))
                safe_link = html_lib.escape(str(data.link or ""), quote=True)
                html_body = get_base_template(f"""
                    <h2>{safe_title}</h2>
                    <p>{safe_message}</p>
                    {"<a href='" + safe_link + "' class='btn'>عرض التفاصيل</a>" if data.link else ""}
                """)
                results["email"] = send_notification_email(db, data.user_id, data.title, html_body, tenant_id=company_id)
            except Exception:
                logger.exception("Email notification failed")
                results["email"] = False

        # 3. Send SMS if requested
        if data.send_sms:
            try:
                from services.email_service import send_notification_sms
                sms_text = f"{data.title}: {data.message or ''}"[:160]
                results["sms"] = send_notification_sms(db, data.user_id, sms_text, tenant_id=company_id)
            except Exception:
                logger.exception("SMS notification failed")
                results["sms"] = False

        db.commit()
        return {"message": i18n_message("notification_sent", request), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error sending notification: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== Notification Settings (SMTP / SMS) =====================

@router.get("/settings", dependencies=[Depends(require_permission("settings.view"))], response_model=Dict[str, Any])
async def get_notification_settings(current_user: dict = Depends(get_current_user)):
    """إعدادات البريد الإلكتروني و SMS"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {}

    with transactional(company_id) as db:
        keys = [
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_from_email',
            'smtp_from_name', 'smtp_tls',
            'sms_api_url', 'sms_sender_name',
            'notification_email_enabled', 'notification_sms_enabled'
        ]
        # Don't return passwords
        rows = db.execute(text("""
            SELECT setting_key, setting_value FROM company_settings
            WHERE setting_key = ANY(:keys)
        """), {"keys": keys}).fetchall()

        settings = {r.setting_key: r.setting_value for r in rows}
        # Mask sensitive fields
        settings["smtp_password"] = "********" if settings.get("smtp_host") else ""
        settings["sms_api_key"] = "********" if settings.get("sms_api_url") else ""
        return settings


@router.put("/settings", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
async def update_notification_settings(
    data: dict,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث إعدادات البريد الإلكتروني و SMS"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "settings_no_company", request))

    db = get_db_connection(company_id)
    try:
        allowed_keys = [
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_from_email', 'smtp_from_name', 'smtp_tls',
            'sms_api_url', 'sms_api_key', 'sms_sender_name',
            'notification_email_enabled', 'notification_sms_enabled'
        ]

        # T021: Input validation for notification settings
        if "smtp_port" in data:
            try:
                port_val = int(data["smtp_port"])
                if port_val < 1 or port_val > 65535:
                    raise HTTPException(**http_error(400, "smtp_port_range", request))
            except (ValueError, TypeError):
                raise HTTPException(**http_error(400, "smtp_port_invalid", request))
        if "smtp_host" in data and data["smtp_host"] != "********":
            if not isinstance(data["smtp_host"], str) or not data["smtp_host"].strip():
                raise HTTPException(**http_error(400, "smtp_host_empty", request))

        for key, value in data.items():
            if key not in allowed_keys:
                continue
            if value == "********":  # Don't update masked values
                continue

            # T2.5: encrypt sensitive secrets (smtp_password, sms_api_key) at rest.
            from utils.secret_settings import is_secret_key, encrypt_value
            stored = encrypt_value(str(value), tenant_id=company_id) if is_secret_key(key) else str(value)
            db.execute(text("""
                INSERT INTO company_settings (setting_key, setting_value)
                VALUES (:key, :val)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = :val
            """), {"key": key, "val": stored})

        db.commit()
        log_activity(
            db=db,
            user_id=getattr(current_user, "id", None),
            username=getattr(current_user, "username", ""),
            action="notification_settings_updated",
            resource_type="notification_settings",
            details={"updated_keys": [k for k in data if k in allowed_keys and data[k] != "********"]},
            request=request,
        )
        return {"message": i18n_message(("notification_settings_updated", request))}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating notification settings: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== Notification Preferences =====================

class PreferenceUpdate(BaseModel):
    event_type: str
    email_enabled: bool = True
    in_app_enabled: bool = True
    push_enabled: bool = True


@router.get("/preferences", response_model=List[Dict[str, Any]])
async def get_preferences(current_user: dict = Depends(get_current_user)):
    """جلب تفضيلات الإشعارات للمستخدم"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return []
    user_id = getattr(current_user, "id", None) or getattr(current_user, "user_id", None)
    with transactional(company_id) as db:
        rows = db.execute(text(
            "SELECT event_type, email_enabled, in_app_enabled, push_enabled "
            "FROM notification_preferences WHERE user_id = :uid"
        ), {"uid": user_id}).fetchall()
        return [
            {
                "event_type": r.event_type,
                "email_enabled": r.email_enabled,
                "in_app_enabled": r.in_app_enabled,
                "push_enabled": r.push_enabled,
            }
            for r in rows
        ]


@router.put("/preferences", response_model=Dict[str, Any])
async def update_preference(body: PreferenceUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    """تحديث تفضيل إشعار واحد (upsert)"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "company_id_required", request))
    user_id = getattr(current_user, "id", None) or getattr(current_user, "user_id", None)
    db = get_db_connection(company_id)
    try:
        existing = db.execute(text(
            "SELECT id FROM notification_preferences WHERE user_id = :uid AND event_type = :evt"
        ), {"uid": user_id, "evt": body.event_type}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE notification_preferences
                SET email_enabled = :email, in_app_enabled = :inapp, push_enabled = :push, updated_at = NOW()
                WHERE user_id = :uid AND event_type = :evt
            """), {
                "uid": user_id, "evt": body.event_type,
                "email": body.email_enabled, "inapp": body.in_app_enabled, "push": body.push_enabled,
            })
        else:
            db.execute(text("""
                INSERT INTO notification_preferences (user_id, event_type, email_enabled, in_app_enabled, push_enabled)
                VALUES (:uid, :evt, :email, :inapp, :push)
            """), {
                "uid": user_id, "evt": body.event_type,
                "email": body.email_enabled, "inapp": body.in_app_enabled, "push": body.push_enabled,
            })
        db.commit()
        log_activity(
            db=db,
            user_id=user_id,
            action="notification_preference_updated",
            resource_type="notification_preference",
            details={"event_type": body.event_type, "email": body.email_enabled, "in_app": body.in_app_enabled, "push": body.push_enabled},
            request=request,
        )
        return {"detail": "Preference updated"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating preference: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/test-email", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
async def test_email_connection(request: Request, current_user: dict = Depends(get_current_user)):
    """اختبار اتصال SMTP"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "test_no_company", request))

    db = get_db_connection(company_id)
    try:
        from services.email_service import get_email_service_from_settings, get_base_template

        service = get_email_service_from_settings(db, tenant_id=company_id)
        if not service:
            raise HTTPException(**http_error(400, "smtp_settings_incomplete", request))

        user = db.execute(text("SELECT email FROM company_users WHERE id = :id"), {"id": current_user.id}).fetchone()
        if not user or not user.email:
            raise HTTPException(**http_error(400, "no_email_for_account", request))

        html = get_base_template("""
            <h2>✅ اختبار ناجح!</h2>
            <p>تم الاتصال بخادم SMTP بنجاح. هذه رسالة اختبار من نظام AMAN ERP.</p>
        """)
        success = service.send(user.email, "اختبار اتصال AMAN ERP", html)

        if success:
            return {"message": i18n_message("test_message_sent", request), "sent_to": user.email}
        else:
            raise HTTPException(**http_error(500, "test_email_send_failed", request))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing email connection: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== WebSocket Endpoint =====================

@router.websocket("/ws")
async def notifications_ws(ws: WebSocket, token: Optional[str] = None):
    """
    WebSocket endpoint for real-time notifications.
    Connect: ws://host/api/notifications/ws?token=JWT_TOKEN
    Support Cookie-based auth if token is missing.
    """
    from jose import jwt, JWTError
    from config import settings as app_settings

    # Authenticate via token query param OR cookies
    actual_token = token
    if not actual_token:
        actual_token = ws.cookies.get("access_token")

    if not actual_token:
        await ws.close(code=4001, reason="Missing token")
        return

    try:
        payload = jwt.decode(actual_token, app_settings.SECRET_KEY, algorithms=[app_settings.ALGORITHM],
                             options={"leeway": app_settings.JWT_LEEWAY_SECONDS})
        user_id = payload.get("user_id")
        company_id = payload.get("company_id")
        if not user_id or not company_id:
            await ws.close(code=4001, reason="Invalid token")
            return
    except JWTError:
        await ws.close(code=4001, reason="Invalid token")
        return

    connected = await ws_manager.connect(ws, company_id, user_id)
    if not connected:
        return
    try:
        while True:
            # Keep alive — client can send pings, we just read and discard
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(ws, company_id, user_id)
    except Exception:
        ws_manager.disconnect(ws, company_id, user_id)


# ===================== Push Helper =====================

async def push_notification(company_id: str, user_id: int, notification: dict):
    """
    Helper to push a notification to a connected user via WebSocket.
    Call this from any router after inserting a notification into the DB.
    
    Usage:
        from routers.notifications import push_notification
        await push_notification(company_id, user_id, {
            "id": notif_id, "title": "...", "message": "...",
            "type": "info", "link": "/...", "is_read": False,
            "created_at": datetime.now().isoformat()
        })
    """
    try:
        await ws_manager.send_to_user(company_id, user_id, {
            "event": "new_notification",
            "data": notification
        })
    except Exception as e:
        logger.debug(f"WS push failed for {company_id}:{user_id}: {e}")


# ===================== Unsubscribe Endpoint =====================

@router.get("/unsubscribe")
async def unsubscribe_from_notifications(
    token: str,
    company_id: Optional[str] = None,
):
    """Honour a one-click unsubscribe link included in email footers.

    Verifies the HMAC token and disables the matching notification preference
    (or all preferences when event_type is absent).
    Returns a plain HTML confirmation page.
    """
    from services.email_service import verify_unsubscribe_token
    from fastapi.responses import HTMLResponse

    payload = verify_unsubscribe_token(token)
    if not payload:
        return HTMLResponse(
            "<h2>رابط إلغاء الاشتراك غير صالح أو منتهي الصلاحية.</h2>",
            status_code=400,
        )

    user_id = payload["user_id"]
    event_type = payload.get("event_type")

    # Attempt to update notification preferences in the user's company DB.
    # We need company_id — callers should embed it in the unsubscribe URL.
    if company_id:
        try:
            from database import get_db_connection
            with transactional(company_id) as db:
                if event_type:
                    db.execute(
                        text(
                            "UPDATE notification_preferences "
                            "SET email_enabled = FALSE, updated_at = NOW() "
                            "WHERE user_id = :uid AND event_type = :evt"
                        ),
                        {"uid": user_id, "evt": event_type},
                    )
                else:
                    db.execute(
                        text(
                            "UPDATE notification_preferences "
                            "SET email_enabled = FALSE, updated_at = NOW() "
                            "WHERE user_id = :uid"
                        ),
                        {"uid": user_id},
                    )
        except Exception as exc:
            logger.warning("Unsubscribe DB update failed: %s", exc)

    scope = f"إشعارات '{event_type}'" if event_type else "جميع الإشعارات البريدية"
    return HTMLResponse(
        f"<h2>✅ تم إلغاء اشتراكك من {scope} بنجاح.</h2>"
        "<p>يمكنك إعادة تفعيل الإشعارات في إعدادات حسابك.</p>",
        status_code=200,
    )

