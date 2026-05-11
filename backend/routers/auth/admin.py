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

from .core import AdminTwoFASetup, AdminTwoFAVerify, _require_system_admin, get_current_user, oauth2_scheme, oauth2_scheme_optional

@router.post("/admin/2fa/setup", tags=["Authentication"], response_model=Dict[str, Any])
def admin_2fa_setup(
    body: AdminTwoFASetup,
    current_user=Depends(get_current_user),
):
    """Generate a new TOTP secret for a system-admin account (disabled until verified)."""
    _require_system_admin(current_user)
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pyotp not installed",
        )

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=body.username, issuer_name="AMAN ERP Admin")

    db = get_system_db()
    try:
        db.execute(
            text(
                """
                INSERT INTO system_admin_2fa (admin_username, secret_key, is_enabled, created_at, updated_at)
                VALUES (:u, :s, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (admin_username) DO UPDATE SET
                    secret_key = EXCLUDED.secret_key,
                    is_enabled = FALSE,
                    verified_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"u": body.username, "s": secret},
        )
        db.commit()
    finally:
        db.close()

    return {"secret": secret, "provisioning_uri": uri}


@router.post("/admin/2fa/verify", tags=["Authentication"], response_model=Dict[str, Any])
def admin_2fa_verify(request: Request, 
    body: AdminTwoFAVerify,
    current_user=Depends(get_current_user),
):
    """Verify a TOTP code and enable DB-backed admin 2FA."""
    _require_system_admin(current_user)
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pyotp not installed",
        )

    db = get_system_db()
    try:
        row = db.execute(
            text(
                "SELECT id, secret_key FROM system_admin_2fa WHERE admin_username = :u"
            ),
            {"u": body.username},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "2fa_not_setup", request))
        if not pyotp.TOTP(row.secret_key).verify(body.code, valid_window=1):
            raise HTTPException(**http_error(400, "code_incorrect", request))
        db.execute(
            text(
                "UPDATE system_admin_2fa SET is_enabled = TRUE, "
                "verified_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :id"
            ),
            {"id": row.id},
        )
        db.commit()
        return {"enabled": True, "username": body.username}
    finally:
        db.close()


@router.post("/admin/2fa/disable", tags=["Authentication"], response_model=Dict[str, Any])
def admin_2fa_disable(
    body: AdminTwoFASetup,
    current_user=Depends(get_current_user),
):
    """Disable DB-backed admin 2FA (env fallback still applies if configured)."""
    _require_system_admin(current_user)
    db = get_system_db()
    try:
        db.execute(
            text(
                "UPDATE system_admin_2fa SET is_enabled = FALSE, "
                "updated_at = CURRENT_TIMESTAMP WHERE admin_username = :u"
            ),
            {"u": body.username},
        )
        db.commit()
        return {"enabled": False, "username": body.username}
    finally:
        db.close()
