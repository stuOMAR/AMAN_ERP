"""
Credential Vault — single source of truth for all integration secrets.

All reads/writes go through this module.  Secrets are envelope-encrypted at
rest using the existing tenant-aware key derivation from
``utils.field_encryption``.

Contract: see specs/022-audit-security-finance-integrity/contracts/credential-vault.md

Required vault keys (Feature 024 additions):
  - ``approval_token_signing_key``  — HMAC signing key for single-use approval tokens (kid rotation supported)
  - ``dek_pii_<tenant_id>``         — per-tenant DEK for PII at-rest encryption (salary, IBAN, national ID)
  - ``clamav.endpoint``             — ClamAV daemon socket or host:port
  - ``clamav.auth``                 — optional ClamAV auth token
  - ``smtp.host``, ``smtp.port``, ``smtp.username``, ``smtp.password`` — SMTP provider
  - ``sms.api_key``, ``sms.sender`` — SMS provider
  - ``push.api_key``, ``push.project_id`` — push notification provider
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from database import db_connection, get_db_connection
from utils.field_encryption import decrypt, encrypt, is_encrypted
from utils.audit import log_activity

logger = logging.getLogger(__name__)

_SECRET_KEY_PATTERNS = (
    "smtp_password", "zatca_", "sms_api_key", "payment_secret",
    "bank_feed_", "ldap_password", "shipping_api_key",
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encrypt_secret(plaintext: str, tenant_id: str) -> bytes:
    """Envelope-encrypt the plaintext secret, returning raw bytes for BYTEA storage."""
    token = encrypt(plaintext, tenant_id=str(tenant_id))
    return token.encode("utf-8")


def _decrypt_secret(ciphertext: bytes, tenant_id: str) -> str:
    """Decrypt a BYTEA ciphertext back to plaintext."""
    token = ciphertext.decode("utf-8") if isinstance(ciphertext, bytes) else ciphertext
    return decrypt(token, tenant_id=str(tenant_id))


def _get_setting(conn, key: str, default: Any = None) -> Any:
    row = conn.execute(
        text("SELECT setting_value FROM company_settings WHERE setting_key = :k"),
        {"k": key},
    ).scalar()
    return row if row is not None else default


def _credential_ref(row) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "integration": row.integration,
        "name": row.name,
        "key_version": row.key_version,
        "metadata": row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
        "status": row.status,
        "consecutive_failures": row.consecutive_failures,
        "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── public API ────────────────────────────────────────────────────────────────

def create_credential(
    tenant_id: int,
    integration: str,
    name: str,
    secret: str,
    metadata: Optional[dict] = None,
    expires_at: Optional[datetime] = None,
    actor_id: Optional[int] = None,
) -> dict:
    """Create a new credential in the vault. Returns a credential ref (no plaintext)."""
    tid = str(tenant_id)
    ciphertext = _encrypt_secret(secret, tid)
    meta_json = json.dumps(metadata or {}, default=str)

    with db_connection(tid) as conn:
        row = conn.execute(
            text("""
                INSERT INTO integration_credentials
                    (tenant_id, integration, name, secret_ciphertext, key_version,
                     metadata, status, expires_at, created_by)
                VALUES
                    (:tid, :integ, :name, :ct, 1,
                     CAST(:meta AS JSONB), 'active', :exp, :actor)
                RETURNING id, tenant_id, integration, name, key_version, metadata,
                          status, consecutive_failures, rotated_at, expires_at,
                          created_by, created_at
            """),
            {
                "tid": tenant_id, "integ": integration, "name": name,
                "ct": ciphertext, "meta": meta_json, "exp": expires_at,
                "actor": actor_id,
            },
        ).fetchone()
        conn.commit()

        ref = _credential_ref(row)

    log_activity(
        None,  # audit goes through outbox on next business txn; standalone commit
        user_id=actor_id or 0,
        username=str(actor_id or "system"),
        action="credential.create",
        resource_type="integration_credential",
        resource_id=str(ref["id"]),
        details={"integration": integration, "name": name},
        critical=True,
    )
    return ref


def get_credential(tenant_id: int, integration: str, name: str) -> dict:
    """Return decrypted credential dict. Refuses to return soft_deleted rows."""
    tid = str(tenant_id)

    with db_connection(tid) as conn:
        row = conn.execute(
            text("""
                SELECT id, tenant_id, integration, name, secret_ciphertext,
                       key_version, metadata, status, consecutive_failures,
                       rotated_at, expires_at, created_by, created_at
                  FROM integration_credentials
                 WHERE tenant_id = :tid
                   AND integration = :integ
                   AND name = :name
                   AND status != 'soft_deleted'
                 ORDER BY id DESC
                 LIMIT 1
            """),
            {"tid": tenant_id, "integ": integration, "name": name},
        ).fetchone()

    if row is None:
        raise LookupError(f"Credential not found: {integration}/{name}")

    plaintext = _decrypt_secret(row.secret_ciphertext, tid)
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "integration": row.integration,
        "name": row.name,
        "secret": plaintext,
        "key_version": row.key_version,
        "metadata": row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
        "status": row.status,
    }


def rotate_credential(
    tenant_id: int,
    credential_id: int,
    new_secret: str,
    *,
    grace_seconds: int,
    actor_id: int,
) -> dict:
    """Rotate a credential. Old row stays in 'rotating' for grace_seconds."""
    tid = str(tenant_id)
    ciphertext = _encrypt_secret(new_secret, tid)

    with db_connection(tid) as conn:
        old = conn.execute(
            text("""
                SELECT id, integration, name, status
                  FROM integration_credentials
                 WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": credential_id, "tid": tenant_id},
        ).fetchone()

        if old is None:
            raise LookupError(f"Credential {credential_id} not found")
        if old.status == "soft_deleted":
            raise ValueError("Cannot rotate a soft_deleted credential")

        conn.execute(
            text("""
                UPDATE integration_credentials
                   SET status = 'rotating',
                       rotated_at = now(),
                       expires_at = now() + (:grace || ' seconds')::interval,
                       updated_at = now()
                 WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": credential_id, "tid": tenant_id, "grace": grace_seconds},
        )

        new_ver = conn.execute(
            text("""
                SELECT COALESCE(MAX(key_version), 0) + 1
                  FROM integration_credentials
                 WHERE tenant_id = :tid
                   AND integration = :integ
                   AND name = :name
            """),
            {"tid": tenant_id, "integ": old.integration, "name": old.name},
        ).scalar()

        row = conn.execute(
            text("""
                INSERT INTO integration_credentials
                    (tenant_id, integration, name, secret_ciphertext, key_version,
                     metadata, status, created_by)
                VALUES
                    (:tid, :integ, :name, :ct, :ver,
                     '{}', 'active', :actor)
                RETURNING id, tenant_id, integration, name, key_version, metadata,
                          status, consecutive_failures, rotated_at, expires_at,
                          created_by, created_at
            """),
            {
                "tid": tenant_id, "integ": old.integration, "name": old.name,
                "ct": ciphertext, "ver": new_ver, "actor": actor_id,
            },
        ).fetchone()
        conn.commit()

        ref = _credential_ref(row)

    log_activity(
        None,
        user_id=actor_id,
        username=str(actor_id),
        action="credential.rotate",
        resource_type="integration_credential",
        resource_id=str(credential_id),
        details={"new_credential_id": ref["id"], "grace_seconds": grace_seconds},
        critical=True,
    )
    return ref


def soft_delete_credential(tenant_id: int, credential_id: int, *, actor_id: int) -> None:
    """Soft-delete a credential (terminal until restore)."""
    tid = str(tenant_id)

    with db_connection(tid) as conn:
        conn.execute(
            text("""
                UPDATE integration_credentials
                   SET status = 'soft_deleted',
                       deleted_at = now(),
                       updated_at = now()
                 WHERE id = :cid AND tenant_id = :tid
                   AND status != 'soft_deleted'
            """),
            {"cid": credential_id, "tid": tenant_id},
        )
        conn.commit()

    log_activity(
        None,
        user_id=actor_id,
        username=str(actor_id),
        action="credential.soft_delete",
        resource_type="integration_credential",
        resource_id=str(credential_id),
        critical=True,
    )


def restore_credential(tenant_id: int, credential_id: int, *, actor_id: int) -> dict:
    """Restore a soft_deleted credential back to active."""
    tid = str(tenant_id)

    with db_connection(tid) as conn:
        row = conn.execute(
            text("""
                UPDATE integration_credentials
                   SET status = 'active',
                       deleted_at = NULL,
                       updated_at = now()
                 WHERE id = :cid AND tenant_id = :tid
                   AND status = 'soft_deleted'
                RETURNING id, tenant_id, integration, name, key_version, metadata,
                          status, consecutive_failures, rotated_at, expires_at,
                          created_by, created_at
            """),
            {"cid": credential_id, "tid": tenant_id},
        ).fetchone()
        conn.commit()

    if row is None:
        raise LookupError(f"Credential {credential_id} not found or not soft_deleted")

    ref = _credential_ref(row)

    log_activity(
        None,
        user_id=actor_id,
        username=str(actor_id),
        action="credential.restore",
        resource_type="integration_credential",
        resource_id=str(credential_id),
        critical=True,
    )
    return ref


def record_failure(tenant_id: int, credential_id: int) -> None:
    """Increment consecutive_failures and alert when threshold is reached."""
    tid = str(tenant_id)

    with db_connection(tid) as conn:
        row = conn.execute(
            text("""
                UPDATE integration_credentials
                   SET consecutive_failures = consecutive_failures + 1,
                       updated_at = now()
                 WHERE id = :cid AND tenant_id = :tid
                RETURNING consecutive_failures, integration, name
            """),
            {"cid": credential_id, "tid": tenant_id},
        ).fetchone()

        if row is None:
            return

        failures = row.consecutive_failures
        threshold_raw = _get_setting(conn, "bank_feed.failure_alert_threshold", "3")
        threshold = int(threshold_raw)

        if failures >= threshold:
            conn.execute(
                text("""
                    INSERT INTO notification_queue
                        (tenant_id, notification_type, channel, priority,
                         subject, body, payload)
                    VALUES
                        (:tid, 'credential_failure_alert', 'in_app', 'high',
                         :subject, :body, CAST(:payload AS JSONB))
                """),
                {
                    "tid": tenant_id,
                    "subject": f"Credential failure alert: {row.integration}/{row.name}",
                    "body": (
                        f"Credential {row.name} for {row.integration} has "
                        f"failed {failures} consecutive times (threshold: {threshold})."
                    ),
                    "payload": json.dumps({
                        "credential_id": credential_id,
                        "integration": row.integration,
                        "name": row.name,
                        "consecutive_failures": failures,
                        "threshold": threshold,
                    }),
                },
            )
        conn.commit()


def record_success(tenant_id: int, credential_id: int) -> None:
    """Reset consecutive_failures to 0 after a successful use."""
    tid = str(tenant_id)

    with db_connection(tid) as conn:
        conn.execute(
            text("""
                UPDATE integration_credentials
                   SET consecutive_failures = 0,
                       updated_at = now()
                 WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": credential_id, "tid": tenant_id},
        )
        conn.commit()


__all__ = [
    "create_credential",
    "get_credential",
    "rotate_credential",
    "soft_delete_credential",
    "restore_credential",
    "record_failure",
    "record_success",
]
