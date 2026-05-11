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

from .core import LogoutRequest, RefreshTokenRequest, _get_client_ip, _hash_token, _is_user_tokens_invalidated, add_token_to_blacklist, check_rate_limit, clear_failed_attempts, create_access_token, create_refresh_token, is_token_blacklisted, oauth2_scheme, oauth2_scheme_optional, record_failed_attempt

@router.post("/login", response_model=Token)
@limiter.limit("10/minute")  # SEC-FIX: Production rate limit (reverted from 1000 testing value)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    company_code: Optional[str] = Form(None),  # رمز الشركة — إلزامي لمستخدمي الشركات
):
    """
    تسجيل الدخول.
    - مستخدم النظام (admin): username + password فقط.
    - موظف شركة: company_code + username + password.
      الـ company_code يُحدد الشركة بشكل حصري — لا يوجد أي بحث في شركات أخرى.
    """
    # Rate limit check (IP + username)
    check_rate_limit(request, form_data.username)
    
    db = get_system_db()
    
    try:
        # Check if system admin
        result = db.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = :username"),
            {"username": form_data.username}
        ).fetchone()
        
        if result and form_data.username == "admin":
            # System admin login - verify password using bcrypt
            from database import verify_password as verify_pwd
            
            admin_hash = getattr(settings, 'ADMIN_PASSWORD_HASH', None)
            if not admin_hash:
                admin_hash = os.environ.get('ADMIN_PASSWORD_HASH', None)
            
            if not admin_hash:
                # SECURITY: No hash configured — reject login entirely
                logger.critical("⚠️ ADMIN_PASSWORD_HASH not configured! Admin login DISABLED.")
                raise HTTPException(
                    **http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "login_server_error", request)
                )
            
            if not verify_pwd(form_data.password, admin_hash):
                record_failed_attempt(request, form_data.username)
                raise HTTPException(
                    **http_error(status.HTTP_401_UNAUTHORIZED, "invalid_password", request),
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            # SEC-FIX / SEC-08: Require TOTP for admin. DB-backed secret
            # (system_admin_2fa table) takes precedence over ADMIN_TOTP_SECRET
            # environment variable — lets ops rotate / disable without a restart.
            admin_totp_secret = None
            admin_2fa_row_id = None
            try:
                row = db.execute(
                    text(
                        "SELECT id, secret_key, is_enabled FROM system_admin_2fa "
                        "WHERE admin_username = :u"
                    ),
                    {"u": form_data.username},
                ).fetchone()
                if row and row.is_enabled and row.secret_key:
                    admin_totp_secret = row.secret_key
                    admin_2fa_row_id = row.id
            except Exception:
                # Table may not exist yet on freshly-bootstrapped systems
                logger.debug("system_admin_2fa lookup skipped", exc_info=True)

            if not admin_totp_secret:
                admin_totp_secret = (
                    getattr(settings, 'ADMIN_TOTP_SECRET', None)
                    or os.environ.get('ADMIN_TOTP_SECRET')
                )

            if admin_totp_secret:
                # Check if 2FA code was provided via company_code field (reused for admin TOTP)
                totp_code = company_code  # Admin doesn't need company_code, reuse for TOTP
                if not totp_code:
                    clear_failed_attempts(request, form_data.username)
                    # Return 2FA challenge
                    temp_payload = {
                        "sub": form_data.username,
                        "token_use": "2fa_challenge",
                        "type": "admin_2fa_temp",
                    }
                    temp_token = jwt.encode(
                        {**temp_payload, "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                         "iat": datetime.now(timezone.utc)},
                        settings.SECRET_KEY, algorithm=settings.ALGORITHM
                    )
                    return {
                        "requires_2fa": True,
                        "temp_token": temp_token,
                        "message": i18n_message("admin_2fa_required", request)
                    }
                else:
                    import pyotp
                    totp = pyotp.TOTP(admin_totp_secret)
                    if not totp.verify(totp_code, valid_window=1):
                        record_failed_attempt(request, form_data.username)
                        raise HTTPException(
                            **http_error(status.HTTP_401_UNAUTHORIZED, "2fa_invalid_code", request)
                        )
                    # Record successful 2FA use for audit rotation
                    if admin_2fa_row_id:
                        try:
                            db.execute(
                                text(
                                    "UPDATE system_admin_2fa SET "
                                    "last_used_at = CURRENT_TIMESTAMP "
                                    "WHERE id = :id"
                                ),
                                {"id": admin_2fa_row_id},
                            )
                            db.commit()
                        except Exception:
                            logger.debug("2fa last_used update failed", exc_info=True)
            
            clear_failed_attempts(request, form_data.username)
            auth_payload = {
                "sub": form_data.username,
                "role": "system_admin",
                "type": "system_admin",
                "company_id": None,
                "permissions": ["*"]
            }
            access_token = create_access_token(auth_payload)
            refresh_token = create_refresh_token(auth_payload)
            # LOG SYSTEM ADMIN LOGIN
            log_system_activity(
                action="auth.login",
                performed_by=form_data.username,
                description="System administrator logged in",
                request=request
            )

            # TASK-030: set HttpOnly refresh cookie + CSRF cookie.
            set_auth_cookies(response, refresh_token, request)

            return Token(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                user={"username": form_data.username, "role": "system_admin", "company_id": None, "permissions": ["*"]}
            )
        
        # ── تسجيل دخول موظف الشركة ──────────────────────────────────────────
        # company_code إلزامي — بدونه لا نبحث في أي شركة
        if not company_code:
            record_failed_attempt(request, form_data.username)
            raise HTTPException(
                **http_error(status.HTTP_400_BAD_REQUEST, "company_code_required", request)
            )

        # التحقق من أن الشركة موجودة ونشطة
        company = db.execute(
            text("SELECT id, database_name, status FROM system_companies WHERE id = :code AND status = 'active'"),
            {"code": company_code.strip()}
        ).fetchone()

        if not company:
            record_failed_attempt(request, form_data.username)
            raise HTTPException(
                **http_error(status.HTTP_401_UNAUTHORIZED, "company_code_invalid_or_inactive", request),
                headers={"WWW-Authenticate": "Bearer"}
            )

        company_id, db_name, company_status = company
        conn_url = settings.get_company_database_url(company_id)
        if not conn_url:
            raise HTTPException(**http_error(500, "db_connection_error", request))

        try:
            company_engine = create_engine(conn_url, pool_pre_ping=True)
            with company_engine.connect() as company_conn:
                result = company_conn.execute(
                    text("""
                        SELECT id, username, password, email, full_name, role, permissions, is_active
                        FROM company_users WHERE username = :username AND is_active = true
                    """),
                    {"username": form_data.username}
                ).fetchone()

                if not result or not verify_password(form_data.password, result[2]):
                    company_engine.dispose()
                    record_failed_attempt(request, form_data.username)
                    raise HTTPException(
                        **http_error(status.HTTP_401_UNAUTHORIZED, "invalid_username_or_password", request),
                        headers={"WWW-Authenticate": "Bearer"}
                    )

                # ── SEC-FIX: 2FA Challenge ──────────────────────────────────
                # Check if user has 2FA enabled — if so, return temp token instead of full JWT
                try:
                    tfa_row = company_conn.execute(
                        text("SELECT is_enabled FROM user_2fa_settings WHERE user_id = :uid"),
                        {"uid": result[0]}
                    ).fetchone()
                    if tfa_row and tfa_row.is_enabled:
                        # Issue a short-lived temp token for 2FA verification (5 min)
                        temp_payload = {
                            "sub": result[1],
                            "user_id": result[0],
                            "company_id": company_id,
                            "token_use": "2fa_challenge",
                            "type": "2fa_temp",
                        }
                        temp_token = jwt.encode(
                            {**temp_payload, "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                             "iat": datetime.now(timezone.utc)},
                            settings.SECRET_KEY, algorithm=settings.ALGORITHM
                        )
                        clear_failed_attempts(request, form_data.username)
                        company_engine.dispose()
                        return {
                            "requires_2fa": True,
                            "temp_token": temp_token,
                            "message": i18n_message("2fa_required", request)
                        }
                except Exception as tfa_err:
                    logger.warning(f"2FA check failed, proceeding without 2FA: {tfa_err}")

                # ── تسجيل الدخول ناجح ──────────────────────────────────────
                company_conn.execute(
                    text("UPDATE company_users SET last_login = :now WHERE id = :user_id"),
                    {"now": datetime.now(timezone.utc), "user_id": result[0]}
                )

                allowed_branches_rows = company_conn.execute(
                    text("SELECT branch_id FROM user_branches WHERE user_id = :uid"),
                    {"uid": result[0]}
                ).fetchall()
                allowed_branches = [r[0] for r in allowed_branches_rows] if allowed_branches_rows else []

                login_branch_id = allowed_branches[0] if allowed_branches else None
                if not login_branch_id:
                    default_branch = company_conn.execute(
                        text("SELECT id FROM branches WHERE is_default = true LIMIT 1")
                    ).fetchone()
                    login_branch_id = default_branch[0] if default_branch else None

                try:
                    log_activity(
                        company_conn,
                        user_id=result[0],
                        username=result[1],
                        action="auth.login",
                        resource_type="user",
                        resource_id=str(result[0]),
                        details={"method": "password", "company_code": company_code},
                        request=request,
                        branch_id=login_branch_id
                    )
                    log_system_activity(
                        action="auth.login",
                        company_id=company_id,
                        performed_by=result[1],
                        description="User logged in via company_code",
                        request=request
                    )
                except Exception as log_err:
                    logger.warning(f"Logging failed: {log_err}")

                company_conn.commit()

                # تحديث فهرس المستخدمين المركزي
                try:
                    db.execute(
                        text("""
                            INSERT INTO system_user_index (username, company_id, is_active)
                            VALUES (:username, :company_id, true)
                            ON CONFLICT (username, company_id) DO UPDATE
                            SET is_active = true, updated_at = CURRENT_TIMESTAMP
                        """),
                        {"username": form_data.username, "company_id": company_id}
                    )
                    db.commit()
                except Exception:
                    pass

                # الصلاحيات
                role_permissions = []
                if result[5]:
                    try:
                        role_res = company_conn.execute(
                            text("SELECT permissions FROM roles WHERE role_name = :r"),
                            {"r": result[5]}
                        ).scalar()
                        if role_res:
                            role_permissions = role_res
                    except Exception as e:
                        logger.warning(f"Could not fetch roles: {e}")

                user_permissions = result[6]
                if isinstance(user_permissions, dict) and user_permissions.get('all') is True:
                    user_permissions = ["*"]
                elif not isinstance(user_permissions, list):
                    user_permissions = []

                final_permissions = list(set((role_permissions or []) + user_permissions))
                if result[5] in ['admin', 'system_admin', 'superuser'] or result[1] == 'admin':
                    final_permissions = ["*"]
                elif "*" in final_permissions:
                    final_permissions = ["*"]

                # معلومات الشركة
                company_info = db.execute(
                    text("SELECT currency, enabled_modules, company_name FROM system_companies WHERE id = :id"),
                    {"id": company_id}
                ).fetchone()

                currency = company_info[0] if company_info else "SAR"
                enabled_modules = company_info[1] if company_info and company_info[1] else []

                if isinstance(enabled_modules, str):
                    import json
                    try:
                        enabled_modules = json.loads(enabled_modules)
                    except Exception:
                        enabled_modules = []

                auth_payload = {
                    "sub": result[1],
                    "user_id": result[0],
                    "company_id": company_id,
                    "role": result[5],
                    "permissions": final_permissions,
                    "enabled_modules": enabled_modules,
                    "allowed_branches": allowed_branches,
                    "type": "company_user"
                }
                access_token = create_access_token(auth_payload)
                refresh_token = create_refresh_token(auth_payload)

                decimal_places = 2
                company_country = "SA"
                company_timezone = "Asia/Riyadh"
                industry_type = None
                try:
                    dp_res = company_conn.execute(
                        text("SELECT setting_value FROM company_settings WHERE setting_key = 'decimal_places'")
                    ).scalar()
                    if dp_res:
                        decimal_places = int(dp_res)
                    cc_res = company_conn.execute(
                        text("SELECT setting_value FROM company_settings WHERE setting_key = 'company_country'")
                    ).scalar()
                    if cc_res:
                        company_country = cc_res
                    tz_res = company_conn.execute(
                        text("SELECT setting_value FROM company_settings WHERE setting_key = 'timezone'")
                    ).scalar()
                    if tz_res:
                        company_timezone = tz_res
                    it_res = company_conn.execute(
                        text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
                    ).scalar()
                    if it_res:
                        industry_type = it_res
                except Exception as e:
                    logger.warning(f"Failed to fetch settings: {e}")

                company_engine.dispose()
                clear_failed_attempts(request, form_data.username)
                logger.info(f"✅ Login: {result[1]} -> company:{company_id}")

                # SEC-FIX-006: Record session in user_sessions table
                try:
                    session_token_hash = _hash_token(access_token)
                    user_agent = request.headers.get("user-agent", "")[:500]
                    client_ip = _get_client_ip(request)

                    # SEC-09: concurrent-session limit. When
                    # MAX_CONCURRENT_SESSIONS is set (>0), close the
                    # oldest active sessions so that at most that many
                    # remain for this user. Defaults to unlimited.
                    try:
                        max_sessions = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "0") or 0)
                    except ValueError:
                        max_sessions = 0
                    if max_sessions > 0:
                        company_conn.execute(text("""
                            UPDATE user_sessions
                            SET is_active = FALSE
                            WHERE user_id = :uid
                              AND is_active = TRUE
                              AND id IN (
                                SELECT id FROM user_sessions
                                WHERE user_id = :uid AND is_active = TRUE
                                ORDER BY last_activity DESC
                                OFFSET :keep
                              )
                        """), {"uid": result[0], "keep": max_sessions - 1})

                    company_conn.execute(text("""
                        INSERT INTO user_sessions (user_id, token_hash, ip_address, user_agent, login_time, last_activity, is_active)
                        VALUES (:uid, :thash, :ip, :ua, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE)
                    """), {
                        "uid": result[0],
                        "thash": session_token_hash,
                        "ip": client_ip,
                        "ua": user_agent
                    })
                    company_conn.commit()
                except Exception as sess_err:
                    logger.warning(f"Failed to create user_session: {sess_err}")

                # Feature 022: Device fingerprint + geo event for login risk
                try:
                    from services.login_risk import evaluate_login_risk
                    evaluate_login_risk(
                        company_conn, tenant_id=int(company_id),
                        user_id=result[0],
                        user_agent=request.headers.get("user-agent", ""),
                        ip_address=_get_client_ip(request),
                    )
                    company_conn.commit()
                except Exception:
                    logger.debug("login_risk evaluation skipped", exc_info=True)

                # TASK-030: set HttpOnly refresh cookie + CSRF cookie.
                set_auth_cookies(response, refresh_token, request)

                return Token(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type="bearer",
                    user={
                        "id": result[0],
                        "username": result[1],
                        "email": result[3],
                        "full_name": result[4],
                        "role": result[5],
                        "permissions": final_permissions,
                        "enabled_modules": enabled_modules,
                        "industry_type": industry_type,
                        "currency": currency,
                        "country": company_country,
                        "decimal_places": decimal_places,
                        "timezone": company_timezone,
                        "allowed_branches": allowed_branches
                    },
                    company_id=company_id
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Login error for company {company_id}: {e}")
            logger.exception("Unexpected error")
            raise HTTPException(**http_error(500, "server_error_during_login", request))

    finally:
        db.close()

@router.post("/logout", response_model=Dict[str, Any])
async def logout(
    response: Response,
    request: Request,
    body: Optional[LogoutRequest] = Body(default=None),
    token: str = Depends(oauth2_scheme)
):
    """تسجيل الخروج - يتم إضافة التوكن إلى القائمة السوداء"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"verify_exp": False})
        username = payload.get("sub")
    except JWTError:
        username = None
    add_token_to_blacklist(token, username=username, reason="logout")
    if body and body.refresh_token:
        add_token_to_blacklist(body.refresh_token, username=username, reason="logout_refresh")
    # TASK-030: also blacklist the refresh cookie if present.
    cookie_refresh = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if cookie_refresh:
        add_token_to_blacklist(cookie_refresh, username=username, reason="logout_refresh_cookie")

    # SEC-FIX: Deactivate user session on logout
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"verify_exp": False})
        company_id = payload.get("company_id")
        user_id = payload.get("user_id")
        if company_id and user_id:
            token_hash = _hash_token(token)
            with get_db_connection(company_id) as sess_conn:
                sess_conn.execute(text("""
                    UPDATE user_sessions SET is_active = FALSE
                    WHERE user_id = :uid AND token_hash = :thash
                """), {"uid": user_id, "thash": token_hash})
                sess_conn.commit()
    except Exception as e:
        logger.warning(f"Session deactivation on logout failed: {e}")

    # TASK-030: clear HttpOnly refresh + CSRF cookies.
    clear_auth_cookies(response)

    return {"message": i18n_message(("logout_success", request))}


@router.get("/csrf", response_model=Dict[str, Any])
async def get_csrf_token(request: Request, response: Response):
    """
    TASK-030: bootstrap endpoint. Sets a fresh non-HttpOnly `csrf_token`
    cookie (readable by JS) and returns its value in the JSON body so
    SPA clients can prime their state on first load before any mutating
    request. Safe to call anonymously — the token is just an opaque
    random value used for the double-submit-cookie check.
    """
    from utils.auth_cookies import set_csrf_cookie
    token = set_csrf_cookie(response, request=request)
    return {"csrf_token": token}


@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token(
    request: Request,
    response: Response,
    body: Optional[RefreshTokenRequest] = Body(default=None),
    token: Optional[str] = Depends(oauth2_scheme_optional)
):
    """تجديد الجلسة باستخدام refresh token (دوار)"""
    credentials_exception = HTTPException(
        **http_error(status.HTTP_401_UNAUTHORIZED, "refresh_token_invalid", request),
        headers={"WWW-Authenticate": "Bearer"},
    )

    provided_refresh_token = None
    # TASK-030: prefer HttpOnly cookie over body/header when present.
    cookie_refresh = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if cookie_refresh:
        provided_refresh_token = cookie_refresh.strip()
    elif body and body.refresh_token:
        provided_refresh_token = body.refresh_token.strip()
    elif token:
        provided_refresh_token = token

    if not provided_refresh_token:
        raise HTTPException(
            **http_error(status.HTTP_400_BAD_REQUEST, "refresh_token_required", request)
        )
    
    if is_token_blacklisted(provided_refresh_token):
        raise credentials_exception
        
    try:
        payload = jwt.decode(provided_refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"leeway": settings.JWT_LEEWAY_SECONDS})
        if payload.get("token_use") != "refresh":
            raise credentials_exception

        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception

        # SEC-FIX: Re-verify user is still active in DB before issuing new tokens
        company_id = payload.get("company_id")
        user_id = payload.get("user_id")
        if company_id and user_id:
            try:
                with get_db_connection(company_id) as check_conn:
                    active = check_conn.execute(
                        text("SELECT is_active FROM company_users WHERE id = :uid"),
                        {"uid": user_id}
                    ).scalar()
                    if not active:
                        raise credentials_exception
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Could not verify user active status during refresh: {e}")

        # SEC-FIX: Check user-level token invalidation
        if company_id and username:
            token_iat = payload.get("iat", 0)
            if _is_user_tokens_invalidated(company_id, username, token_iat):
                raise credentials_exception

        # BUG-C3: Re-read fresh role, permissions, enabled_modules from DB on
        # every refresh so that revocations take effect immediately instead of
        # waiting up to the refresh-token TTL.
        fresh_role = payload.get("role")
        fresh_permissions = payload.get("permissions")
        fresh_enabled_modules = payload.get("enabled_modules")
        fresh_allowed_branches = payload.get("allowed_branches")
        fresh_user_id = payload.get("user_id")
        if company_id and username:
            try:
                with get_db_connection(company_id) as _conn:
                    row = _conn.execute(text("""
                        SELECT id, role, permissions, is_active
                        FROM company_users WHERE username = :u
                    """), {"u": username}).fetchone()
                    if not row or not row.is_active:
                        raise credentials_exception
                    fresh_user_id = row.id
                    fresh_role = row.role
                    # company_users.permissions is JSONB; can be dict or list
                    perms = row.permissions
                    if isinstance(perms, dict):
                        fresh_permissions = perms.get("permissions") or list(perms.keys())
                        fresh_enabled_modules = perms.get("enabled_modules") or fresh_enabled_modules
                    elif isinstance(perms, list):
                        fresh_permissions = perms
                    # Allowed branches
                    branches = _conn.execute(text(
                        "SELECT branch_id FROM user_branches WHERE user_id = :uid"
                    ), {"uid": row.id}).fetchall()
                    if branches:
                        fresh_allowed_branches = [b[0] for b in branches]
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Refresh: DB re-read failed, falling back to payload claims: {e}")

        # Create new token with FRESH claims and fresh expiry
        new_payload = {
            "sub": payload.get("sub"),
            "type": payload.get("type"),
            "company_id": company_id,
            "role": fresh_role,
            "permissions": fresh_permissions,
            "enabled_modules": fresh_enabled_modules,
        }

        # Include optional fields
        if fresh_user_id:
            new_payload["user_id"] = fresh_user_id
        if fresh_allowed_branches:
            new_payload["allowed_branches"] = fresh_allowed_branches
        
        new_access_token = create_access_token(new_payload)
        new_refresh_token = create_refresh_token(new_payload)
        
        # Rotate refresh token: revoke old one and return new one
        add_token_to_blacklist(provided_refresh_token, username=username, reason="refresh_rotate")

        # TASK-030: rotate HttpOnly refresh cookie + CSRF cookie.
        set_auth_cookies(response, new_refresh_token, request)

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }
    except JWTError:
        raise credentials_exception


# ═══════════════════════════════════════════════════════════════════════════════
# FORGOT / RESET PASSWORD
# ═══════════════════════════════════════════════════════════════════════════════

