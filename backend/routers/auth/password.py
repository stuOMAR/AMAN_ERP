"""auth sub-router — split from monolithic auth.py (T6.3).

Mounted under the parent router via auth/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form, Body
from utils.i18n import http_error
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import text, create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr
import logging
import os
import secrets
import hashlib
import ipaddress
from database import get_system_db, verify_password, get_db_connection, hash_password, engine as system_engine
from utils.tx import transactional
from config import settings
from schemas import Token, UserResponse
from utils.audit import log_activity, log_system_activity
from utils.limiter import limiter
from utils.auth_cookies import set_auth_cookies, clear_auth_cookies

logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='api/auth/login')
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl='api/auth/login', auto_error=False)

router = APIRouter()

from .core import ForgotPasswordRequest, ResetPasswordRequest, invalidate_user_tokens, oauth2_scheme, oauth2_scheme_optional

@router.post("/forgot-password", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """
    طلب إعادة تعيين كلمة المرور — يُلزم المستخدم بتحديد كود الشركة لتجنّب
    الاستعلامات عبر المستأجرين وتسريب المعلومات. الاستجابة ثابتة الشكل وثابتة
    الزمن تقريبًا لمنع تعداد البريد الإلكتروني.
    """
    import time as _time
    started = _time.monotonic()
    _MIN_ELAPSED = 0.35  # seconds — constant-time floor

    _ensure_reset_table()
    email = body.email.strip().lower()
    company_code = (body.company_code or "").strip()

    # SEC-FIX: unified success message; do not expose whether email/tenant exists
    success_msg = {"message": "إذا كان البريد مسجلاً، سيتم إرسال رابط إعادة التعيين"}

    def _constant_time_return(value):
        elapsed = _time.monotonic() - started
        if elapsed < _MIN_ELAPSED:
            _time.sleep(_MIN_ELAPSED - elapsed)
        return value

    if not email or not company_code:
        return _constant_time_return(success_msg)

    db = get_system_db()
    try:
        # SEC-FIX: look up the single tenant the user claims to belong to.
        company_row = db.execute(
            text(
                "SELECT id FROM system_companies "
                "WHERE status = 'active' "
                "  AND (LOWER(company_code) = LOWER(:c) OR LOWER(id) = LOWER(:c))"
            ),
            {"c": company_code},
        ).fetchone()

        found_user = None
        found_company = None

        if company_row:
            company_id = company_row[0]
            try:
                company_db = get_db_connection(company_id)
                user = company_db.execute(
                    text(
                        "SELECT id, username, email, full_name FROM company_users "
                        "WHERE LOWER(email) = :email AND is_active = true"
                    ),
                    {"email": email},
                ).fetchone()
                company_db.close()
                if user:
                    found_user = user
                    found_company = company_id
            except Exception as lookup_exc:
                logger.debug(f"forgot-password tenant lookup failed: {lookup_exc}")

        if not found_user:
            return _constant_time_return(success_msg)

        # Generate secure reset token
        reset_token = secrets.token_urlsafe(48)
        token_hash = _hash_reset_token(reset_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Store token
        with system_engine.connect() as conn:
            # Invalidate old tokens
            conn.execute(text(
                "UPDATE password_reset_tokens SET used = TRUE WHERE username = :username AND used = FALSE"
            ), {"username": found_user.username})

            conn.execute(text("""
                INSERT INTO password_reset_tokens (username, company_id, email, token_hash, expires_at)
                VALUES (:username, :cid, :email, :hash, :exp)
            """), {
                "username": found_user.username,
                "cid": found_company,
                "email": email,
                "hash": token_hash,
                "exp": expires_at
            })
            conn.commit()

        # Build reset URL — skip placeholder production URLs
        prod_url = settings.FRONTEND_URL_PRODUCTION
        if prod_url and prod_url.startswith("https://your-domain"):
            prod_url = None
        frontend_url = prod_url or settings.FRONTEND_URL or "http://localhost:5173"
        reset_url = f"{frontend_url}/reset-password?token={reset_token}"

        # SEC-FIX: Never log full reset token — only log a prefix for debugging
        logger.info(f"Password reset generated for {email} (token prefix: {reset_token[:8]}...)")

        # Send email
        email_sent = False
        smtp_configured = bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)
        if smtp_configured:
            try:
                from utils.email import send_email
                from services.email_service import get_base_template

                body_html = get_base_template(f"""
                    <h2>إعادة تعيين كلمة المرور</h2>
                    <p>مرحباً {found_user.full_name or found_user.username}،</p>
                    <p>لقد تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بك.</p>
                    <p>اضغط على الزر أدناه لإعادة التعيين:</p>
                    <p style="text-align: center;">
                        <a href="{reset_url}" class="btn">إعادة تعيين كلمة المرور</a>
                    </p>
                    <div class="info-box">
                        <p>⏰ هذا الرابط صالح لمدة <strong>ساعة واحدة</strong> فقط.</p>
                        <p>إذا لم تطلب إعادة التعيين، تجاهل هذا البريد.</p>
                    </div>
                """)

                email_sent = send_email(
                    to_emails=[email],
                    subject="🔐 إعادة تعيين كلمة المرور - AMAN ERP",
                    body=body_html
                )
                if email_sent:
                    logger.info(f"🔐 Password reset email sent to {email}")
                else:
                    logger.warning(f"⚠️ Email send returned False for {email}, check SMTP credentials")
            except Exception as e:
                logger.error(f"❌ Failed to send reset email: {e}")
        else:
            logger.warning("⚠️ SMTP not configured — reset URL logged above for development use")

        # SEC-FIX-001: Never expose reset token in API response
        # In development, log the URL server-side only
        if not smtp_configured or not email_sent:
            logger.warning(f"SMTP not available — password reset token generated but not delivered for {email}")
            # Return the same generic message regardless (prevent email enumeration)

        return _constant_time_return(success_msg)

    except Exception as e:
        logger.error(f"Forgot password error: {e}")
        return _constant_time_return(success_msg)
    finally:
        db.close()


@router.post("/reset-password", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """
    إعادة تعيين كلمة المرور باستخدام التوكن المُرسل بالبريد
    """
    _ensure_reset_table()
    token_hash = _hash_reset_token(body.token)

    # SEC-FIX-004: Enforce strong password policy
    from utils.sql_safety import validate_password_strength
    validate_password_strength(body.new_password)

    with system_engine.connect() as conn:
        # Find valid token
        token_row = conn.execute(text("""
            SELECT username, company_id, email FROM password_reset_tokens
            WHERE token_hash = :hash AND used = FALSE AND expires_at > CURRENT_TIMESTAMP
        """), {"hash": token_hash}).fetchone()

        if not token_row:
            raise HTTPException(400, "الرابط غير صالح أو منتهي الصلاحية")

        username = token_row.username
        company_id = token_row.company_id

        # Update password in company database
        try:
            company_db = get_db_connection(company_id)
            new_hash = hash_password(body.new_password)

            # SEC-FIX: Check password history to prevent reuse
            try:
                from routers.security import get_password_policy
                policy = get_password_policy(company_db)
                prevent_reuse = policy.get("prevent_reuse", 5)
                if prevent_reuse > 0:
                    user_row = company_db.execute(
                        text("SELECT id FROM company_users WHERE username = :user"),
                        {"user": username}
                    ).fetchone()
                    if user_row:
                        old_passwords = company_db.execute(text("""
                            SELECT password_hash FROM password_history
                            WHERE user_id = :uid ORDER BY created_at DESC LIMIT :limit
                        """), {"uid": user_row[0], "limit": prevent_reuse}).fetchall()
                        for old_pw in old_passwords:
                            if verify_password(body.new_password, old_pw[0]):
                                raise HTTPException(400, f"لا يمكن استخدام كلمة مرور مستخدمة في آخر {prevent_reuse} مرات")
            except HTTPException:
                raise
            except Exception as hist_err:
                logger.warning(f"Password history check skipped: {hist_err}")

            company_db.execute(
                text("UPDATE company_users SET password = :pwd, updated_at = CURRENT_TIMESTAMP WHERE username = :user"),
                {"pwd": new_hash, "user": username}
            )
            # Save to password history
            try:
                user_id = company_db.execute(
                    text("SELECT id FROM company_users WHERE username = :user"),
                    {"user": username}
                ).scalar()
                if user_id:
                    company_db.execute(text("""
                        INSERT INTO password_history (user_id, password_hash)
                        VALUES (:uid, :pw)
                    """), {"uid": user_id, "pw": new_hash})
            except Exception:
                logger.warning("Failed to save password history for reset")
            company_db.commit()
            company_db.close()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update password: {e}")
            raise HTTPException(500, "فشل في تحديث كلمة المرور")

        # Mark token as used
        conn.execute(text(
            "UPDATE password_reset_tokens SET used = TRUE WHERE token_hash = :hash"
        ), {"hash": token_hash})
        conn.commit()

        # SEC-FIX-007: Invalidate all existing tokens for this user
        invalidate_user_tokens(company_id, username, reason="password_reset")

        log_system_activity(
            action="auth.password_reset",
            performed_by=username,
            description=f"Password reset via email for user {username}",
            request=request
        )

        return {"message": "تم تغيير كلمة المرور بنجاح. يرجى تسجيل الدخول"}


# ═══════════════════════════════════════════════════════════════════════════════
# SEC-FIX: 2FA LOGIN VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

