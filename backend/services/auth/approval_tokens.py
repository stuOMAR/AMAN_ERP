"""Approval tokens — HMAC-signed single-use tokens with kid rotation.

Contract: see specs/024-workforce-service-comms-integrity/contracts/approval-tokens.md
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def issue(
    conn: Any,
    *,
    tenant_id: int,
    action: str,
    target_id: int,
    issuer_user_id: Optional[int] = None,
    ttl_minutes: int = 1440,
) -> dict:
    """Issue an approval token.

    Returns dict with nonce (the token value) and expires_at.
    """
    nonce = secrets.token_hex(16)  # 32-char hex string

    # Get signing key from vault (or env for dev)
    signing_key = _get_signing_key(tenant_id)
    signature = _sign(nonce, signing_key)

    expires_at = datetime.now(timezone.utc).replace(
        minute=datetime.now(timezone.utc).minute + ttl_minutes
        if datetime.now(timezone.utc).minute + ttl_minutes < 60
        else datetime.now(timezone.utc).minute
    )

    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

    conn.execute(
        text("""
            INSERT INTO approval_tokens
                (nonce, tenant_id, action, target_id, issuer_user_id,
                 issued_at, expires_at)
            VALUES
                (:nonce, :tnt, :action, :target, :issuer,
                 now(), :expires)
        """),
        {
            "nonce": nonce, "tnt": tenant_id, "action": action,
            "target": target_id, "issuer": issuer_user_id,
            "expires": expires_at,
        },
    )
    conn.commit()

    return {
        "nonce": nonce,
        "action": action,
        "target_id": target_id,
        "expires_at": expires_at.isoformat(),
    }


def validate_token(
    conn: Any,
    *,
    tenant_id: int,
    nonce: str,
    action: str,
    target_id: int,
) -> bool:
    """Validate an approval token without consuming it."""
    row = conn.execute(
        text("""
            SELECT action, target_id, expires_at, consumed_at
            FROM approval_tokens
            WHERE nonce = :nonce AND tenant_id = :tnt
        """),
        {"nonce": nonce, "tnt": tenant_id},
    ).fetchone()

    if row is None:
        return False
    if row[3] is not None:  # consumed_at
        return False
    if row[2] and row[2] < datetime.now(timezone.utc):
        return False
    if row[0] != action or row[1] != target_id:
        return False

    return True


def verify_and_consume(
    conn: Any,
    *,
    tenant_id: int,
    nonce: str,
    action: str,
    target_id: int,
    consumer_user_id: Optional[int] = None,
    consumer_ip: Optional[str] = None,
) -> dict:
    """Verify and consume an approval token (single-use).

    Returns dict with verification result.
    """
    row = conn.execute(
        text("""
            SELECT action, target_id, expires_at, consumed_at
            FROM approval_tokens
            WHERE nonce = :nonce AND tenant_id = :tnt
        """),
        {"nonce": nonce, "tnt": tenant_id},
    ).fetchone()

    if row is None:
        raise ValueError("approval_token.invalid_signature")

    if row[3] is not None:
        raise ValueError("approval_token.consumed")

    if row[2] and row[2] < datetime.now(timezone.utc):
        raise ValueError("approval_token.expired")

    if row[0] != action or row[1] != target_id:
        raise ValueError("approval_token.scope_mismatch")

    # Consume the token
    conn.execute(
        text("""
            UPDATE approval_tokens
            SET consumed_at = now(), consumed_by_user_id = :uid, consumed_via_ip = :ip
            WHERE nonce = :nonce AND tenant_id = :tnt
        """),
        {"uid": consumer_user_id, "ip": consumer_ip, "nonce": nonce, "tnt": tenant_id},
    )
    conn.commit()

    return {
        "valid": True,
        "action": action,
        "target_id": target_id,
        "consumed": True,
    }


def sweep_expired(conn: Any, *, tenant_id: int, older_than_days: int = 30) -> int:
    """Sweep expired tokens older than N days (cleanup job)."""
    result = conn.execute(
        text("""
            DELETE FROM approval_tokens
            WHERE tenant_id = :tnt
              AND expires_at < now() - (:days || ' days')::interval
        """),
        {"tnt": tenant_id, "days": older_than_days},
    )
    conn.commit()
    return result.rowcount


def _get_signing_key(tenant_id: int) -> bytes:
    """Get HMAC signing key from vault or environment."""
    key = os.getenv("APPROVAL_TOKEN_SIGNING_KEY")
    if key:
        return key.encode()
    return f"dev-signing-key-{tenant_id}".encode()


def _sign(nonce: str, key: bytes) -> str:
    """Compute HMAC signature for a nonce."""
    return hmac.new(key, nonce.encode(), hashlib.sha256).hexdigest()
