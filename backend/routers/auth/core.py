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
from typing import Optional
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

# Module-level cache for the rate-limiter Redis client (None = uninitialized
# or no Redis available). Declared at module scope so ``global _rate_redis``
# inside ``_get_rate_redis`` resolves on first call.
_rate_redis = None

def _get_rate_redis():
    """Return a Redis client for rate limiting (lazy init, graceful fallback)."""
    global _rate_redis
    if _rate_redis is not None:
        return _rate_redis
    try:
        import redis as _redis_lib
        if settings.REDIS_URL:
            _rate_redis = _redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2, decode_responses=True)
            _rate_redis.ping()  # verify connectivity
            return _rate_redis
    except Exception as e:
        logger.warning(f"Redis unavailable for rate-limiter, falling back to in-memory: {e}")
    _rate_redis = None
    return None

# In-memory fallback (single-worker only, cleared on restart)
_login_attempts = {}
_username_attempts = {}

_trusted_proxy_networks_cache = None
_trusted_proxy_raw_cache = None


def _get_trusted_proxy_networks():
    """Parse configured trusted proxy IPs/CIDRs once per config value."""
    global _trusted_proxy_networks_cache, _trusted_proxy_raw_cache
    raw = (getattr(settings, "TRUSTED_PROXIES", "") or "").strip()
    if raw == _trusted_proxy_raw_cache and _trusted_proxy_networks_cache is not None:
        return _trusted_proxy_networks_cache

    networks = []
    if raw:
        for item in raw.split(","):
            val = item.strip()
            if not val:
                continue
            try:
                networks.append(ipaddress.ip_network(val, strict=False))
            except ValueError:
                logger.warning(f"Ignoring invalid TRUSTED_PROXIES entry: {val}")

    _trusted_proxy_raw_cache = raw
    _trusted_proxy_networks_cache = networks
    return networks


def _is_trusted_proxy(client_ip: str) -> bool:
    if not client_ip:
        return False
    networks = _get_trusted_proxy_networks()
    if not networks:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(ip in net for net in networks)


def _get_client_ip(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    xff = request.headers.get("X-Forwarded-For", "")

    if not xff:
        return client_ip

    if not _is_trusted_proxy(client_ip):
        logger.warning(
            f"Rejected X-Forwarded-For from untrusted source: client_ip={client_ip}, xff={xff}"
        )
        return client_ip

    forwarded_ip = xff.split(",")[0].strip()
    try:
        ipaddress.ip_address(forwarded_ip)
    except ValueError:
        logger.warning(
            f"Rejected malformed X-Forwarded-For value from trusted proxy {client_ip}: {xff}"
        )
        return client_ip

    return forwarded_ip


def check_rate_limit(request: Request, username: str = None):
    """Check if IP or username has exceeded login attempt limit."""
    client_ip = _get_client_ip(request)
    if client_ip in ("testclient",):
        return

    r = _get_rate_redis()
    if r is not None:
        # --- Redis path ---
        try:
            ip_key = f"rl:ip:{client_ip}"
            ip_count = r.get(ip_key)
            if ip_count and int(ip_count) >= MAX_LOGIN_ATTEMPTS:
                ttl = r.ttl(ip_key)
                minutes = max(int(ttl / 60) + 1, 1) if ttl and ttl > 0 else 1
                raise HTTPException(429, f"تم تجاوز عدد المحاولات المسموح. يرجى الانتظار {minutes} دقيقة")

            if username:
                user_key = f"rl:user:{username}"
                user_count = r.get(user_key)
                if user_count and int(user_count) >= MAX_USERNAME_ATTEMPTS:
                    ttl = r.ttl(user_key)
                    minutes = max(int(ttl / 60) + 1, 1) if ttl and ttl > 0 else 1
                    logger.warning(f"🔒 Username '{username}' locked out - too many attempts")
                    raise HTTPException(429, f"تم تجاوز عدد المحاولات لهذا المستخدم. يرجى الانتظار {minutes} دقيقة")
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Redis rate-limit read error: {e}")
            # Fall through to memory check

    # --- In-memory fallback ---
    now = datetime.now(timezone.utc)
    if client_ip in _login_attempts:
        info = _login_attempts[client_ip]
        if (now - info["last_attempt"]).total_seconds() > LOCKOUT_SECONDS:
            del _login_attempts[client_ip]
        elif info["count"] >= MAX_LOGIN_ATTEMPTS:
            remaining = LOCKOUT_SECONDS - (now - info["last_attempt"]).total_seconds()
            minutes = max(int(remaining / 60) + 1, 1)
            raise HTTPException(429, f"تم تجاوز عدد المحاولات المسموح. يرجى الانتظار {minutes} دقيقة")

    if username and username in _username_attempts:
        info = _username_attempts[username]
        if (now - info["last_attempt"]).total_seconds() > LOCKOUT_SECONDS:
            del _username_attempts[username]
        elif info["count"] >= MAX_USERNAME_ATTEMPTS:
            remaining = LOCKOUT_SECONDS - (now - info["last_attempt"]).total_seconds()
            minutes = max(int(remaining / 60) + 1, 1)
            logger.warning(f"🔒 Username '{username}' locked out - too many attempts")
            raise HTTPException(429, f"تم تجاوز عدد المحاولات لهذا المستخدم. يرجى الانتظار {minutes} دقيقة")


def record_failed_attempt(request: Request, username: str = None):
    """Record a failed login attempt for both IP and username."""
    client_ip = _get_client_ip(request)

    r = _get_rate_redis()
    if r is not None:
        try:
            ip_key = f"rl:ip:{client_ip}"
            pipe = r.pipeline()
            pipe.incr(ip_key)
            pipe.expire(ip_key, LOCKOUT_SECONDS)
            if username:
                user_key = f"rl:user:{username}"
                pipe.incr(user_key)
                pipe.expire(user_key, LOCKOUT_SECONDS)
            pipe.execute()
            return
        except Exception as e:
            logger.error(f"Redis rate-limit write error: {e}")

    # In-memory fallback
    now = datetime.now(timezone.utc)
    if client_ip in _login_attempts:
        _login_attempts[client_ip]["count"] += 1
        _login_attempts[client_ip]["last_attempt"] = now
    else:
        _login_attempts[client_ip] = {"count": 1, "last_attempt": now}
    if username:
        if username in _username_attempts:
            _username_attempts[username]["count"] += 1
            _username_attempts[username]["last_attempt"] = now
        else:
            _username_attempts[username] = {"count": 1, "last_attempt": now}


def clear_failed_attempts(request: Request, username: str = None):
    """Clear failed attempts on successful login."""
    client_ip = _get_client_ip(request)

    r = _get_rate_redis()
    if r is not None:
        try:
            r.delete(f"rl:ip:{client_ip}")
            if username:
                r.delete(f"rl:user:{username}")
            return
        except Exception:
            pass

    # In-memory fallback
    _login_attempts.pop(client_ip, None)
    if username:
        _username_attempts.pop(username, None)


# ============ SEC-201: Persistent Token Blacklist ============
# In-memory cache + DB persistence for token blacklist
_token_blacklist_cache = set()  # Local cache for fast lookup
_blacklist_initialized = False


def _ensure_blacklist_table():
    """Create token_blacklist table in system DB if not exists"""
    global _blacklist_initialized
    if _blacklist_initialized:
        return
    try:
        from database import engine as sys_engine
        with sys_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS token_blacklist (
                    id SERIAL PRIMARY KEY,
                    token_hash VARCHAR(64) NOT NULL UNIQUE,
                    expires_at TIMESTAMP NOT NULL,
                    blacklisted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    username VARCHAR(100),
                    reason VARCHAR(50) DEFAULT 'logout'
                );
                CREATE INDEX IF NOT EXISTS idx_token_blacklist_hash ON token_blacklist(token_hash);
                CREATE INDEX IF NOT EXISTS idx_token_blacklist_expires ON token_blacklist(expires_at);
            """))
            conn.commit()
        _blacklist_initialized = True
    except Exception as e:
        logger.warning(f"Token blacklist table init failed: {e}")


def _hash_token(token: str) -> str:
    """Hash token for storage (don't store raw tokens)"""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def add_token_to_blacklist(token: str, username: str = None, reason: str = "logout"):
    """Add token to blacklist (DB + cache)"""
    _ensure_blacklist_table()
    token_hash = _hash_token(token)
    _token_blacklist_cache.add(token_hash)

    try:
        # Extract expiry from token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"verify_exp": False})
        exp = payload.get("exp")
        if exp:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
        else:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        from database import engine as sys_engine
        with sys_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO token_blacklist (token_hash, expires_at, username, reason)
                VALUES (:hash, :exp, :user, :reason)
                ON CONFLICT (token_hash) DO NOTHING
            """), {"hash": token_hash, "exp": expires_at, "user": username, "reason": reason})
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to persist token blacklist: {e}")


def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted (cache first, then DB)"""
    token_hash = _hash_token(token)

    # Fast cache check
    if token_hash in _token_blacklist_cache:
        return True

    # DB fallback (after restart, cache is empty)
    try:
        _ensure_blacklist_table()
        from database import engine as sys_engine
        with sys_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM token_blacklist WHERE token_hash = :hash AND expires_at > CURRENT_TIMESTAMP"
            ), {"hash": token_hash}).fetchone()
            if row:
                _token_blacklist_cache.add(token_hash)  # Populate cache
                return True
    except Exception:
        pass

    return False


def cleanup_expired_blacklist():
    """Remove expired tokens from blacklist (called periodically)"""
    try:
        _ensure_blacklist_table()
        from database import engine as sys_engine
        with sys_engine.connect() as conn:
            deleted = conn.execute(text(
                "DELETE FROM token_blacklist WHERE expires_at < CURRENT_TIMESTAMP"
            )).rowcount
            conn.commit()
            if deleted:
                logger.info(f"🧹 Cleaned {deleted} expired tokens from blacklist")
    except Exception as e:
        logger.warning(f"Blacklist cleanup failed: {e}")


# ============ SEC-FIX-007: User-level token invalidation ============

def invalidate_user_tokens(company_id: str, username: str, reason: str = "password_change"):
    """
    Invalidate ALL tokens for a specific user.
    Uses Redis for fast checks + DB persistence.
    """
    invalidated_at = int(datetime.now(timezone.utc).timestamp())

    # Redis: set invalidation timestamp (fast path)
    r = _get_rate_redis()
    if r is not None:
        try:
            # Key expires after max token lifetime (refresh token days)
            ttl = getattr(settings, 'REFRESH_TOKEN_EXPIRE_DAYS', 7) * 86400
            r.setex(f"tok_inv:{company_id}:{username}", ttl, str(invalidated_at))
        except Exception as e:
            logger.warning(f"Redis token invalidation failed: {e}")

    # DB: persist for Redis-down scenario
    try:
        _ensure_blacklist_table()
        sentinel_hash = hashlib.sha256(
            f"user_inv:{company_id}:{username}:{invalidated_at}".encode()
        ).hexdigest()
        from database import engine as sys_engine
        with sys_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO token_blacklist (token_hash, expires_at, username, reason)
                VALUES (:hash, :exp, :user, :reason)
                ON CONFLICT (token_hash) DO NOTHING
            """), {
                "hash": sentinel_hash,
                "exp": datetime.now(timezone.utc) + timedelta(days=getattr(settings, 'REFRESH_TOKEN_EXPIRE_DAYS', 7)),
                "user": f"{company_id}:{username}",
                "reason": reason
            })
            conn.commit()
    except Exception as e:
        logger.warning(f"DB token invalidation failed: {e}")

    # Deactivate all sessions in company DB
    try:
        company_db = get_db_connection(company_id)
        company_db.execute(text("""
            UPDATE user_sessions SET is_active = FALSE
            WHERE user_id = (SELECT id FROM company_users WHERE username = :uname LIMIT 1)
        """), {"uname": username})
        company_db.commit()
        company_db.close()
    except Exception as e:
        logger.warning(f"Session deactivation failed: {e}")


def _is_user_tokens_invalidated(company_id: str, username: str, token_iat: int) -> bool:
    """Check if user's tokens were invalidated after this token was issued."""
    r = _get_rate_redis()
    if r is not None:
        try:
            inv_ts = r.get(f"tok_inv:{company_id}:{username}")
            if inv_ts and token_iat < int(inv_ts):
                return True
        except Exception:
            pass
    return False


# Legacy compatibility alias
token_blacklist = _token_blacklist_cache


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    to_encode.setdefault("token_use", "access")
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    to_encode.update({"token_use": "refresh"})
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                          options={"leeway": settings.JWT_LEEWAY_SECONDS})
    except JWTError:
        return None


@router.get("/me", response_model=UserResponse)
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """الحصول على معلومات المستخدم الحالي"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if is_token_blacklisted(token):
        raise credentials_exception
        
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                             options={"leeway": settings.JWT_LEEWAY_SECONDS})
        if payload.get("token_use") == "refresh":
            raise credentials_exception
        username: str = payload.get("sub")
        company_id: str = payload.get("company_id")
        permissions: list = payload.get("permissions")
        
        if username is None:
            raise credentials_exception
            
        # For system_admin, company_id is not required
        is_system_admin = payload.get("type") == "system_admin"
        if not is_system_admin and company_id is None:
            raise credentials_exception

        # SEC-FIX-007: Check user-level token invalidation (password change/reset)
        if not is_system_admin and company_id and username:
            token_iat = payload.get("iat", 0)
            if _is_user_tokens_invalidated(company_id, username, token_iat):
                raise credentials_exception
            
    except JWTError as e:
        logger.warning(f"Token decode failed: {e}")
        raise credentials_exception
    
    if payload.get("type") == "system_admin":
        return UserResponse(
            id=0,
            username=payload.get("sub"),
            email="admin@aman-erp.com",
            full_name="المدير العام للنظام",
            role="system_admin",
            is_active=True,
            company_id=None,
            currency=payload.get("currency", None),
            permissions=["*"]
        )
    
    company_id = payload.get("company_id")
    user_id = payload.get("user_id")
    
    if not company_id or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="بيانات غير كاملة")
    
    db = get_system_db()
    try:
        company = db.execute(
            text("SELECT database_name, currency FROM system_companies WHERE id = :id"),
            {"id": company_id}
        ).fetchone()
        
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الشركة غير موجودة")
        
        currency = company[1]
        
        try:
            with get_db_connection(company_id) as company_conn:
                result = company_conn.execute(
                    text("SELECT id, username, email, full_name, role, is_active, permissions FROM company_users WHERE id = :user_id"),
                    {"user_id": user_id}
                ).fetchone()
            
                if result:
                    # Process permissions (same logic as login)
                    user_permissions = result[6]
                
                    # Handle Legacy Format {'all': True}
                    if isinstance(user_permissions, dict) and user_permissions.get('all') is True:
                        user_permissions = ["*"]
                    elif not isinstance(user_permissions, list):
                        user_permissions = []

                    # Fetch Role Permissions
                    role_permissions = []
                    if result[4]:  # role
                        try:
                            role_res = company_conn.execute(
                                text("SELECT permissions FROM roles WHERE role_name = :r"),
                                {"r": result[4]}
                            ).scalar()
                            if role_res:
                                role_permissions = role_res if isinstance(role_res, list) else []
                        except Exception as e:
                            logger.warning(f"Failed to fetch role permissions for '{result[4]}': {e}")

                    final_permissions = list(set((role_permissions or []) + user_permissions))

                    # Fetch Allowed Branches
                    allowed_branches_rows = company_conn.execute(
                        text("SELECT branch_id FROM user_branches WHERE user_id = :uid"),
                        {"uid": user_id}
                    ).fetchall()
                    allowed_branches = [r[0] for r in allowed_branches_rows]

                    # Force Admin Access
                    if result[4] in ['admin', 'system_admin', 'superuser']:
                        final_permissions = ["*"]
                    elif "*" in final_permissions:
                        final_permissions = ["*"]

                    # Fetch Decimal Places Setting
                    decimal_places = 2
                    company_country = "SY"
                    company_timezone = "Asia/Damascus"
                    industry_type_me = None
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
                            industry_type_me = it_res
                    except Exception as e:
                        logger.warning(f"Failed to fetch settings in /me: {e}")

                    # Fetch company details
                    company_info = db.execute(
                        text("SELECT currency, enabled_modules FROM system_companies WHERE id = :id"),
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

                    return UserResponse(
                        id=result[0],
                        username=result[1],
                        email=result[2],
                        full_name=result[3],
                        role=result[4],
                        is_active=result[5],
                        company_id=company_id,
                        currency=currency,
                        country=company_country,
                        decimal_places=decimal_places,
                        timezone=company_timezone,
                        permissions=final_permissions,
                        allowed_branches=allowed_branches,
                        enabled_modules=enabled_modules,
                        industry_type=industry_type_me
                    )
        except (OperationalError, ProgrammingError):
            logger.exception("Current user lookup failed due to tenant DB/schema issue for company %s", company_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="بيانات الشركة غير جاهزة حالياً. يرجى إعادة تسجيل الدخول أو التواصل مع الدعم.",
            )

    finally:
        db.close()
    
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")


class SelfProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    data: SelfProfileUpdateRequest,
    token: str = Depends(oauth2_scheme)
):
    """Update currently logged-in user profile fields."""
    current_user = await get_current_user(token)
    company_id = getattr(current_user, "company_id", None)

    if not company_id:
        raise HTTPException(status_code=400, detail="غير متاح لمسؤولي النظام")

    updates = {}

    if data.full_name is not None:
        full_name = data.full_name.strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="الاسم الكامل لا يمكن أن يكون فارغا")
        updates["full_name"] = full_name

    if data.email is not None:
        updates["email"] = str(data.email).strip().lower()

    if not updates:
        raise HTTPException(**http_error(400, "no_data_to_update"))

    db = get_db_connection(company_id)
    try:
        if "email" in updates:
            existing_email = db.execute(
                text("""
                    SELECT id FROM company_users
                    WHERE lower(email) = :email AND id != :uid
                    LIMIT 1
                """),
                {"email": updates["email"], "uid": current_user.id}
            ).fetchone()
            if existing_email:
                raise HTTPException(status_code=400, detail="البريد الإلكتروني مستخدم من قبل مستخدم آخر")

        set_parts = []
        params = {"uid": current_user.id}

        if "full_name" in updates:
            set_parts.append("full_name = :full_name")
            params["full_name"] = updates["full_name"]
        if "email" in updates:
            set_parts.append("email = :email")
            params["email"] = updates["email"]

        set_parts.append("updated_at = CURRENT_TIMESTAMP")

        db.execute(
            text(f"UPDATE company_users SET {', '.join(set_parts)} WHERE id = :uid"),
            params
        )
        db.commit()

        try:
            log_activity(
                db,
                current_user.id,
                current_user.username,
                "update_profile",
                "company_users",
                str(current_user.id),
                {"updated_fields": list(updates.keys())}
            )
        except Exception:
            pass

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update self profile: {e}")
        raise HTTPException(status_code=500, detail="فشل تحديث بيانات الحساب")
    finally:
        db.close()

    return await get_current_user(token)


class ForgotPasswordRequest(BaseModel):
    email: str
    company_code: str  # SEC-FIX: require explicit tenant to avoid cross-tenant lookup


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ensure_reset_table():
    """Ensure password_reset_tokens table exists in system DB with all required columns"""
    try:
        with system_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    company_id VARCHAR(50),
                    email VARCHAR(255),
                    token_hash VARCHAR(255) NOT NULL UNIQUE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # Ensure columns exist for tables created before schema updates
            conn.execute(text("ALTER TABLE password_reset_tokens ADD COLUMN IF NOT EXISTS email VARCHAR(255)"))
            conn.execute(text("ALTER TABLE password_reset_tokens ADD COLUMN IF NOT EXISTS company_id VARCHAR(50)"))
            conn.commit()
    except Exception as e:
        logger.error(f"_ensure_reset_table error: {e}")


class TwoFALoginRequest(BaseModel):
    temp_token: str
    code: str


def get_current_user_company(current_user: UserResponse = Depends(get_current_user)):
    """Dependency that ensures a user is linked to a company and returns that company_id"""
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Unauthorized - User not linked to a company"
        )
    return current_user.company_id


# ==========================================================================
# SEC-08 — System-admin 2FA management (Phase-11 Sprint-5)
# ==========================================================================

class AdminTwoFASetup(BaseModel):
    username: str = "admin"


class AdminTwoFAVerify(BaseModel):
    username: str = "admin"
    code: str


def _require_system_admin(current_user):
    """Raise 403 unless the caller is a system administrator."""
    role = getattr(current_user, "role", None) or getattr(current_user, "type", None)
    if role != "system_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="يتطلب هذا الإجراء صلاحيات مسؤول النظام",
        )


