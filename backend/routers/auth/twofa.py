"""auth sub-router — split from monolithic auth.py (T6.3).

Mounted under the parent router via auth/__init__.py.
"""
from fastapi import APIRouter, HTTPException, status, Request
from utils.i18n import http_error
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from jose import jwt, JWTError
from datetime import datetime, timezone
from typing import Any, Dict
import logging
from database import get_system_db, get_db_connection
from config import settings
from schemas import Token
from utils.audit import log_activity
from utils.limiter import limiter

logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='api/auth/login')
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl='api/auth/login', auto_error=False)

router = APIRouter()

from .core import TwoFALoginRequest, _get_client_ip, _hash_token, clear_failed_attempts, create_access_token, create_refresh_token, record_failed_attempt  # noqa: E402

@router.post("/2fa/verify-login", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def verify_2fa_login(request: Request, body: TwoFALoginRequest):
    """
    التحقق من رمز 2FA بعد تسجيل الدخول الأولي
    يُستخدم بعد أن يعيد /auth/login الحقل requires_2fa: true
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="رمز التحقق غير صالح أو منتهي",
    )

    try:
        payload = jwt.decode(body.temp_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"leeway": settings.JWT_LEEWAY_SECONDS})
        if payload.get("token_use") != "2fa_challenge":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    username = payload.get("sub")
    user_id = payload.get("user_id")
    company_id = payload.get("company_id")

    if not all([username, user_id, company_id]):
        raise credentials_exception

    with get_db_connection(company_id) as company_conn:
        # Verify TOTP code
        tfa_row = company_conn.execute(
            text("SELECT secret_key FROM user_2fa_settings WHERE user_id = :uid AND is_enabled = TRUE"),
            {"uid": user_id}
        ).fetchone()

        if not tfa_row:
            raise credentials_exception

        import pyotp
        totp = pyotp.TOTP(tfa_row.secret_key)
        if not totp.verify(body.code, valid_window=1):
            record_failed_attempt(request, username)
            raise HTTPException(**http_error(401, "2fa_invalid_code"))

        clear_failed_attempts(request, username)

        # Now complete the full login: fetch user data and issue full JWT
        result = company_conn.execute(
            text("""
                SELECT id, username, email, full_name, role, permissions, is_active
                FROM company_users WHERE id = :uid AND is_active = true
            """),
            {"uid": user_id}
        ).fetchone()

        if not result:
            raise credentials_exception

        company_conn.execute(
            text("UPDATE company_users SET last_login = :now WHERE id = :uid"),
            {"now": datetime.now(timezone.utc), "uid": user_id}
        )

        allowed_branches_rows = company_conn.execute(
            text("SELECT branch_id FROM user_branches WHERE user_id = :uid"),
            {"uid": user_id}
        ).fetchall()
        allowed_branches = [r[0] for r in allowed_branches_rows] if allowed_branches_rows else []

        # Permissions
        role_permissions = []
        if result[4]:  # role
            try:
                role_res = company_conn.execute(
                    text("SELECT permissions FROM roles WHERE role_name = :r"),
                    {"r": result[4]}
                ).scalar()
                if role_res:
                    role_permissions = role_res
            except Exception:
                pass

        user_permissions = result[5]
        if isinstance(user_permissions, dict) and user_permissions.get('all') is True:
            user_permissions = ["*"]
        elif not isinstance(user_permissions, list):
            user_permissions = []

        final_permissions = list(set((role_permissions or []) + user_permissions))
        if result[4] in ['admin', 'system_admin', 'superuser'] or result[1] == 'admin':
            final_permissions = ["*"]
        elif "*" in final_permissions:
            final_permissions = ["*"]

        # Company info
        db = get_system_db()
        try:
            company_info = db.execute(
                text("SELECT currency, enabled_modules, company_name FROM system_companies WHERE id = :id"),
                {"id": company_id}
            ).fetchone()
            company_info[0] if company_info else "SAR"
            enabled_modules = company_info[1] if company_info and company_info[1] else []
            if isinstance(enabled_modules, str):
                import json
                try:
                    enabled_modules = json.loads(enabled_modules)
                except Exception:
                    enabled_modules = []
        finally:
            db.close()

        auth_payload = {
            "sub": result[1],
            "user_id": result[0],
            "company_id": company_id,
            "role": result[4],
            "permissions": final_permissions,
            "enabled_modules": enabled_modules,
            "allowed_branches": allowed_branches,
            "type": "company_user"
        }
        access_token = create_access_token(auth_payload)
        refresh_token = create_refresh_token(auth_payload)

        try:
            log_activity(
                company_conn,
                user_id=result[0],
                username=result[1],
                action="auth.login_2fa",
                resource_type="user",
                resource_id=str(result[0]),
                details={"method": "2fa"},
                request=request,
            )
            company_conn.commit()
        except Exception as log_err:
            logger.warning(f"2FA login audit log failed: {log_err}")

        # Record session
        try:
            session_token_hash = _hash_token(access_token)
            user_agent = request.headers.get("user-agent", "")[:500]
            client_ip = _get_client_ip(request)
            company_conn.execute(text("""
                INSERT INTO user_sessions (user_id, token_hash, ip_address, user_agent, login_time, last_activity, is_active)
                VALUES (:uid, :thash, :ip, :ua, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE)
            """), {"uid": result[0], "thash": session_token_hash, "ip": client_ip, "ua": user_agent})
            company_conn.commit()
        except Exception as sess_err:
            logger.warning(f"Failed to create 2FA user_session: {sess_err}")

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user={
                "id": result[0],
                "username": result[1],
                "email": result[2],
                "full_name": result[3],
                "role": result[4],
                "permissions": final_permissions,
                "enabled_modules": enabled_modules,
                "allowed_branches": allowed_branches,
            },
            company_id=company_id
        )


