"""
Security Router - SEC-001, SEC-002, SEC-003, SEC-201, SEC-202
المصادقة الثنائية (2FA) + سياسات كلمات المرور + إدارة الجلسات
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from database import get_db_connection, hash_password, verify_password
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import logging
import re

logger = logging.getLogger("aman.security")

router = APIRouter(prefix="/security", tags=["Security"])


# ===================== 2FA Schemas =====================

class TwoFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_data: str

class TwoFAVerifyRequest(BaseModel):
    code: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

class PasswordPolicySchema(BaseModel):
    min_length: int = 8
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_numbers: bool = True
    require_special: bool = True
    max_age_days: int = 90
    prevent_reuse: int = 5

    @classmethod
    def __get_validators__(cls):
        yield from super().__get_validators__()

    def model_post_init(self, __context):
        if self.min_length < 1:
            raise ValueError("min_length must be at least 1")
        if self.min_length > 128:
            raise ValueError("min_length must not exceed 128")
        if self.max_age_days < 0:
            raise ValueError("max_age_days must be non-negative")
        if self.prevent_reuse < 0:
            raise ValueError("prevent_reuse must be non-negative")
        if self.prevent_reuse > 50:
            raise ValueError("prevent_reuse must not exceed 50")


# ===================== 2FA Setup & Verification =====================

@router.post("/2fa/setup", response_model=Dict[str, Any])
def setup_2fa(current_user=Depends(get_current_user)):
    """
    إعداد المصادقة الثنائية - يولّد مفتاح سري ورمز QR
    """
    with transactional(current_user.company_id) as db:
        try:
            import pyotp
            import base64
    
            # Check if already enabled
            existing = db.execute(text("""
                SELECT is_enabled FROM user_2fa_settings WHERE user_id = :uid
            """), {"uid": current_user.id}).fetchone()
    
            if existing and existing.is_enabled:
                raise HTTPException(**http_error(400, "2fa_already_enabled"))
    
            # Generate TOTP secret
            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            provisioning_uri = totp.provisioning_uri(
                name=current_user.username,
                issuer_name="AMAN ERP"
            )
    
            # Store secret (not yet enabled)
            db.execute(text("""
                INSERT INTO user_2fa_settings (user_id, secret_key, is_enabled)
                VALUES (:uid, :secret, FALSE)
                ON CONFLICT (user_id) DO UPDATE SET secret_key = :secret, is_enabled = FALSE
            """), {"uid": current_user.id, "secret": secret})
    
            return {
                "secret": secret,
                "provisioning_uri": provisioning_uri,
                "qr_data": provisioning_uri,  # Frontend can use a QR library
                "message": i18n_message("twofa_scan_qr_prompt")
            }
        except HTTPException:
            raise
        except ImportError:
            raise HTTPException(**http_error(500, "pyotp_not_installed"))
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/2fa/verify", response_model=Dict[str, Any])
def verify_2fa(data: TwoFAVerifyRequest, current_user=Depends(get_current_user)):
    """
    التحقق من رمز 2FA وتفعيله
    """
    with transactional(current_user.company_id) as db:
        try:
            import pyotp
    
            settings_row = db.execute(text("""
                SELECT secret_key, is_enabled FROM user_2fa_settings WHERE user_id = :uid
            """), {"uid": current_user.id}).fetchone()
    
            if not settings_row or not settings_row.secret_key:
                raise HTTPException(**http_error(400, "2fa_setup_required"))
    
            totp = pyotp.TOTP(settings_row.secret_key)
            if not totp.verify(data.code, valid_window=1):
                raise HTTPException(**http_error(400, "2fa_code_invalid_or_expired"))
    
            # Enable 2FA
            db.execute(text("""
                UPDATE user_2fa_settings SET is_enabled = TRUE, verified_at = CURRENT_TIMESTAMP
                WHERE user_id = :uid
            """), {"uid": current_user.id})
    
            # SEC-FIX: Generate backup codes with better entropy (12 chars) and hash before storage
            import hashlib
            backup_codes = [pyotp.random_base32()[:12] for _ in range(8)]
            hashed_codes = [hashlib.sha256(code.encode()).hexdigest() for code in backup_codes]
            db.execute(text("""
                UPDATE user_2fa_settings SET backup_codes = :codes WHERE user_id = :uid
            """), {"uid": current_user.id, "codes": ",".join(hashed_codes)})
    
            log_activity(db, current_user.id, current_user.username, "enable_2fa",
                         "security", str(current_user.id), {})
    
            return {
                "message": i18n_message("2fa_enabled_success"),
                "backup_codes": backup_codes,
                "warning": i18n_message("backup_codes_warning")
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/2fa/disable", response_model=Dict[str, Any])
def disable_2fa(data: TwoFAVerifyRequest, current_user=Depends(get_current_user)):
    """تعطيل المصادقة الثنائية (يتطلب رمز تأكيد)"""
    with transactional(current_user.company_id) as db:
        try:
            import pyotp
    
            settings_row = db.execute(text("""
                SELECT secret_key, is_enabled FROM user_2fa_settings WHERE user_id = :uid
            """), {"uid": current_user.id}).fetchone()
    
            if not settings_row or not settings_row.is_enabled:
                raise HTTPException(**http_error(400, "2fa_setup_required"))
    
            totp = pyotp.TOTP(settings_row.secret_key)
            if not totp.verify(data.code, valid_window=1):
                raise HTTPException(**http_error(400, "2fa_code_invalid"))
    
            db.execute(text("""
                UPDATE user_2fa_settings SET is_enabled = FALSE, secret_key = NULL, backup_codes = NULL
                WHERE user_id = :uid
            """), {"uid": current_user.id})
    
            log_activity(db, current_user.id, current_user.username, "disable_2fa",
                         "security", str(current_user.id), {})
    
            return {"message": i18n_message("2fa_disabled_success")}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/2fa/status", response_model=Dict[str, Any])
def get_2fa_status(current_user=Depends(get_current_user)):
    """حالة المصادقة الثنائية للمستخدم الحالي"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"is_enabled": False}

    with transactional(company_id) as db:
        try:
            row = db.execute(text("""
                SELECT is_enabled, verified_at FROM user_2fa_settings WHERE user_id = :uid
            """), {"uid": current_user.id}).fetchone()
    
            return {
                "is_enabled": row.is_enabled if row else False,
                "verified_at": str(row.verified_at) if row and row.verified_at else None
            }
        except Exception:
            return {"is_enabled": False}


# ===================== Password Policies =====================

def validate_password(password: str, policy: dict) -> dict:
    """Validate a password against the company's password policy."""
    errors = []
    min_length = policy.get("min_length", 8)

    if len(password) < min_length:
        errors.append(f"يجب ألا تقل كلمة المرور عن {min_length} أحرف")
    if policy.get("require_uppercase", True) and not re.search(r'[A-Z]', password):
        errors.append("يجب أن تحتوي على حرف كبير واحد على الأقل")
    if policy.get("require_lowercase", True) and not re.search(r'[a-z]', password):
        errors.append("يجب أن تحتوي على حرف صغير واحد على الأقل")
    if policy.get("require_numbers", True) and not re.search(r'\d', password):
        errors.append("يجب أن تحتوي على رقم واحد على الأقل")
    if policy.get("require_special", True) and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("يجب أن تحتوي على رمز خاص واحد على الأقل")

    return {"valid": len(errors) == 0, "errors": errors}


def get_password_policy(db) -> dict:
    """Get password policy from company_settings."""
    try:
        import json
        row = db.execute(text("""
            SELECT setting_value FROM company_settings WHERE setting_key = 'password_policy'
        """)).scalar()
        if row:
            return json.loads(row)
    except Exception:
        pass
    # Default policy
    return {
        "min_length": 8,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_numbers": True,
        "require_special": True,
        "max_age_days": 90,
        "prevent_reuse": 5
    }


@router.post("/change-password", response_model=Dict[str, Any])
def change_password(data: PasswordChangeRequest, current_user=Depends(get_current_user)):
    """تغيير كلمة المرور مع التحقق من السياسة"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "not_available"))

    with transactional(company_id) as db:
        try:
            # Verify current password
            user = db.execute(text("SELECT password FROM company_users WHERE id = :id"),
                              {"id": current_user.id}).fetchone()
            if not user or not verify_password(data.current_password, user.password):
                raise HTTPException(**http_error(400, "current_password_incorrect"))
    
            # Validate new password against policy
            policy = get_password_policy(db)
            validation = validate_password(data.new_password, policy)
            if not validation["valid"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"{i18n_message('password_policy_not_met')}:\n" + "\n".join(validation["errors"]),
                )
    
            # Check reuse prevention
            prevent_reuse = policy.get("prevent_reuse", 5)
            if prevent_reuse > 0:
                old_passwords = db.execute(text("""
                    SELECT password_hash FROM password_history
                    WHERE user_id = :uid ORDER BY created_at DESC LIMIT :limit
                """), {"uid": current_user.id, "limit": prevent_reuse}).fetchall()
    
                for old_pw in old_passwords:
                    if verify_password(data.new_password, old_pw.password_hash):
                        raise HTTPException(
                            **http_error(400, "password_reuse_not_allowed", prevent_reuse=prevent_reuse)
                        )
    
            # Update password
            new_hash = hash_password(data.new_password)
            db.execute(text("""
                UPDATE company_users SET password = :pw, updated_at = CURRENT_TIMESTAMP WHERE id = :id
            """), {"pw": new_hash, "id": current_user.id})
    
            # Save to password history
            db.execute(text("""
                INSERT INTO password_history (user_id, password_hash)
                VALUES (:uid, :pw)
            """), {"uid": current_user.id, "pw": new_hash})
    
    
            # SEC-FIX-012: Invalidate all other tokens/sessions for this user (mandatory)
            from routers.auth import invalidate_user_tokens
            try:
                invalidate_user_tokens(company_id, current_user.username, reason="password_change")
            except Exception as inv_err:
                logger.error(f"Token invalidation after password change failed: {inv_err}")
                # Fallback: deactivate all sessions in DB directly
                try:
                    db.execute(text("""
                        UPDATE user_sessions SET is_active = FALSE WHERE user_id = :uid
                    """), {"uid": current_user.id})
                    db.commit()
                except Exception:
                    logger.exception("Session deactivation fallback also failed")
    
            log_activity(db, current_user.id, current_user.username, "change_password",
                         "security", str(current_user.id), {})
    
            return {"message": i18n_message("password_changed_success")}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/password-policy", dependencies=[Depends(require_permission(["settings.view", "security.view"]))], response_model=Dict[str, Any])
def get_password_policy_endpoint(current_user=Depends(get_current_user)):
    """جلب سياسة كلمات المرور الحالية"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return get_password_policy(None)

    with transactional(company_id) as db:
        return get_password_policy(db)


@router.put("/password-policy", dependencies=[Depends(require_permission(["settings.edit", "security.manage"]))], response_model=Dict[str, Any])
def update_password_policy(data: PasswordPolicySchema, current_user=Depends(get_current_user)):
    """تحديث سياسة كلمات المرور"""
    with transactional(current_user.company_id) as db:
        try:
            import json
            policy_json = json.dumps(data.dict())
    
            db.execute(text("""
                INSERT INTO company_settings (setting_key, setting_value)
                VALUES ('password_policy', :val)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = :val
            """), {"val": policy_json})
    
            return {"message": i18n_message("password_policy_updated")}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Active Sessions =====================

@router.get("/sessions", response_model=Dict[str, Any])
def list_active_sessions(current_user=Depends(get_current_user)):
    """جلب الجلسات النشطة للمستخدم"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"sessions": []}

    with transactional(company_id) as db:
        try:
            rows = db.execute(text("""
                SELECT id, ip_address, user_agent, login_time, last_activity, is_active
                FROM user_sessions
                WHERE user_id = :uid AND is_active = TRUE
                ORDER BY last_activity DESC
            """), {"uid": current_user.id}).fetchall()
    
            sessions = []
            for r in rows:
                s = dict(r._mapping)
                for k in ["login_time", "last_activity"]:
                    if s.get(k):
                        s[k] = str(s[k])
                sessions.append(s)
    
            return {"sessions": sessions}
        except Exception:
            return {"sessions": []}


@router.delete("/sessions/{session_id}", response_model=Dict[str, Any])
def terminate_session(session_id: int, current_user=Depends(get_current_user)):
    """إنهاء جلسة محددة"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "not_available"))

    with transactional(company_id) as db:
        try:
            db.execute(text("""
                UPDATE user_sessions SET is_active = FALSE
                WHERE id = :sid AND user_id = :uid
            """), {"sid": session_id, "uid": current_user.id})
            return {"message": i18n_message("session_terminated")}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/sessions", response_model=Dict[str, Any])
def terminate_all_sessions(current_user=Depends(get_current_user)):
    """إنهاء جميع الجلسات الأخرى"""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(**http_error(400, "not_available"))

    with transactional(company_id) as db:
        try:
            db.execute(text("""
                UPDATE user_sessions SET is_active = FALSE
                WHERE user_id = :uid
            """), {"uid": current_user.id})
            return {"message": i18n_message("all_sessions_terminated")}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== SEC-202: Password Expiry & Notifications =====================

@router.get("/password-expiry", response_model=Dict[str, Any])
def check_password_expiry(current_user=Depends(get_current_user)):
    """
    فحص حالة انتهاء صلاحية كلمة المرور
    يعيد: عدد الأيام المتبقية، هل منتهية، هل قريبة من الانتهاء
    """
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return {"expired": False, "days_remaining": 999, "warning": False}

    with transactional(company_id) as db:
        try:
            policy = get_password_policy(db)
            max_age_days = policy.get("max_age_days", 90)
    
            if max_age_days <= 0:
                return {"expired": False, "days_remaining": 999, "warning": False,
                        "message": i18n_message("password_expiry_policy_disabled")}
    
            # Get last password change date
            last_change = db.execute(text("""
                SELECT created_at FROM password_history
                WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1
            """), {"uid": current_user.id}).scalar()
    
            if not last_change:
                # No password history - check user created_at
                last_change = db.execute(text("""
                    SELECT COALESCE(updated_at, created_at) FROM company_users WHERE id = :uid
                """), {"uid": current_user.id}).scalar()
    
            if not last_change:
                return {"expired": False, "days_remaining": max_age_days, "warning": False}
    
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if hasattr(last_change, 'replace'):
                # Ensure timezone-naive comparison
                last_change = last_change.replace(tzinfo=None) if hasattr(last_change, 'tzinfo') and last_change.tzinfo else last_change
    
            days_since_change = (now - last_change).days
            days_remaining = max(0, max_age_days - days_since_change)
            is_expired = days_remaining == 0
            is_warning = 0 < days_remaining <= 7  # Warning 7 days before
    
            result = {
                "expired": is_expired,
                "days_remaining": days_remaining,
                "warning": is_warning,
                "max_age_days": max_age_days,
                "last_changed": str(last_change)
            }
    
            if is_expired:
                result["message"] = i18n_message("password_expired_change_now")
            elif is_warning:
                result["message"] = i18n_message("password_expiry_warning_in_days", days=days_remaining)
    
            return result
        except Exception as e:
            logger.warning(f"Password expiry check failed: {e}")
            return {"expired": False, "days_remaining": 999, "warning": False}


def check_password_expiry_on_login(company_conn, user_id: int, policy: dict = None) -> dict:
    """
    فحص انتهاء كلمة المرور عند تسجيل الدخول (يُستدعى من auth.py login)
    Returns dict with status info to include in login response
    """
    try:
        if not policy:
            policy = get_password_policy(company_conn)

        max_age_days = policy.get("max_age_days", 90)
        if max_age_days <= 0:
            return {}

        last_change = company_conn.execute(text("""
            SELECT created_at FROM password_history
            WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id}).scalar()

        if not last_change:
            last_change = company_conn.execute(text("""
                SELECT COALESCE(updated_at, created_at) FROM company_users WHERE id = :uid
            """), {"uid": user_id}).scalar()

        if not last_change:
            return {}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if hasattr(last_change, 'replace') and hasattr(last_change, 'tzinfo') and last_change.tzinfo:
            last_change = last_change.replace(tzinfo=None)

        days_since = (now - last_change).days
        days_remaining = max(0, max_age_days - days_since)

        if days_remaining == 0:
            return {"password_expired": True, "password_message": "كلمة المرور منتهية. يرجى تغييرها فوراً"}
        elif days_remaining <= 7:
            return {"password_warning": True,
                    "password_days_remaining": days_remaining,
                    "password_message": f"تنبيه: ستنتهي صلاحية كلمة المرور خلال {days_remaining} يوم"}
        return {}
    except Exception:
        return {}


# ===================== B1: Security Events =====================

@router.get("/events", dependencies=[Depends(require_permission(["security.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def list_security_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user=Depends(get_current_user)
):
    """سجل الأحداث الأمنية"""
    with transactional(current_user.company_id) as conn:
        q = "SELECT * FROM security_events WHERE 1=1"
        params = {}
        if event_type:
            q += " AND event_type = :et"
            params["et"] = event_type
        if severity:
            q += " AND severity = :sev"
            params["sev"] = severity
        q += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = limit
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/events/summary", dependencies=[Depends(require_permission(["security.view", "settings.view"]))], response_model=Dict[str, Any])
def security_events_summary(current_user=Depends(get_current_user)):
    """ملخص الأحداث الأمنية"""
    with transactional(current_user.company_id) as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM security_events")).scalar() or 0
        by_type = conn.execute(text(
            "SELECT event_type, COUNT(*) as cnt FROM security_events GROUP BY event_type ORDER BY cnt DESC"
        )).fetchall()
        by_severity = conn.execute(text(
            "SELECT severity, COUNT(*) as cnt FROM security_events GROUP BY severity ORDER BY cnt DESC"
        )).fetchall()
        recent = conn.execute(text(
            "SELECT COUNT(*) FROM security_events WHERE created_at >= NOW() - INTERVAL '24 hours'"
        )).scalar() or 0
        return {
            "total_events": total,
            "last_24h": recent,
            "by_type": [dict(r._mapping) for r in by_type],
            "by_severity": [dict(r._mapping) for r in by_severity]
        }


@router.get("/login-attempts", dependencies=[Depends(require_permission(["security.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def list_login_attempts(
    ip_address: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user=Depends(get_current_user)
):
    """سجل محاولات تسجيل الدخول"""
    with transactional(current_user.company_id) as conn:
        q = "SELECT * FROM login_attempts WHERE 1=1"
        params = {}
        if ip_address:
            q += " AND ip_address = :ip"
            params["ip"] = ip_address
        q += " ORDER BY attempted_at DESC LIMIT :lim"
        params["lim"] = limit
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/blocked-ips", dependencies=[Depends(require_permission(["security.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def get_blocked_ips(current_user=Depends(get_current_user)):
    """IP addresses blocked due to brute force"""
    with transactional(current_user.company_id) as conn:
        rows = conn.execute(text("""
            SELECT ip_address, COUNT(*) as failed_attempts,
                   MAX(attempted_at) as last_attempt
            FROM login_attempts
            WHERE success = FALSE
              AND attempted_at >= NOW() - INTERVAL '1 hour'
            GROUP BY ip_address
            HAVING COUNT(*) >= 5
            ORDER BY failed_attempts DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


def log_security_event(company_id: str, event_type: str, severity: str, user_id: int = None,
                       ip_address: str = None, user_agent: str = None, details: dict = None):
    """Utility to log security events from anywhere"""
    try:
        conn = get_db_connection(company_id)
        conn.execute(text("""
            INSERT INTO security_events (event_type, severity, user_id, ip_address, user_agent, details)
            VALUES (:et, :sev, :uid, :ip, :ua, :det::jsonb)
        """), {
            "et": event_type, "sev": severity, "uid": user_id,
            "ip": ip_address, "ua": user_agent,
            "det": __import__('json').dumps(details or {})
        })
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")


def check_brute_force(company_id: str, ip_address: str, max_attempts: int = 5, window_minutes: int = 60) -> bool:
    """Returns True if IP should be blocked"""
    try:
        conn = get_db_connection(company_id)
        count = conn.execute(text("""
            SELECT COUNT(*) FROM login_attempts
            WHERE ip_address = :ip AND success = FALSE
              AND attempted_at >= NOW() - INTERVAL :win
        """), {"ip": ip_address, "win": f"{window_minutes} minutes"}).scalar() or 0
        conn.close()
        return count >= max_attempts
    except Exception:
        return False
