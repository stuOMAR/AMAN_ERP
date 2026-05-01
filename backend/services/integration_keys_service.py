"""
Phase 5 / T5.3 — Integration Keys vault.

Provides a single helper API for routers and adapters to:
  * Insert a new key for a (integration_type, provider, key_name) tuple.
  * Rotate a key without downtime: the new key becomes ``active`` and the
    old one is moved to ``rotated`` (still readable for in-flight requests
    until ``valid_to``).
  * Resolve the currently active plaintext value at runtime (decrypts on
    the fly using ``utils.field_encryption``).

All ciphertexts are stored AES-256-GCM via :func:`utils.field_encryption.encrypt`,
so rotation of the master key follows the existing field-encryption playbook.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import text

from utils.field_encryption import decrypt, encrypt, is_encrypted

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def insert_key(
    db,
    *,
    integration_type: str,
    provider: str,
    key_name: str,
    plaintext_value: str,
    tenant_id: str,
    valid_to: Optional[datetime] = None,
    branch_id: Optional[int] = None,
    created_by: Optional[int] = None,
    activate: bool = True,
) -> int:
    """Store a new key. Returns the row id.

    If ``activate`` is True any existing active key for the same triple is
    moved to ``rotated`` first (linking to the new id).
    """
    cipher = encrypt(plaintext_value, tenant_id=tenant_id)
    new_id = db.execute(
        text("""
            INSERT INTO integration_keys (
                integration_type, provider, key_name, encrypted_value,
                key_status, valid_from, valid_to, branch_id, created_by
            ) VALUES (
                :it, :pr, :kn, :ev,
                :st, CURRENT_TIMESTAMP, :vt, :br, :cu
            )
            RETURNING id
        """),
        {
            "it": integration_type, "pr": provider, "kn": key_name,
            "ev": cipher,
            "st": "active" if activate else "pending",
            "vt": valid_to, "br": branch_id, "cu": created_by,
        },
    ).scalar()

    if activate:
        # Mark all previously-active keys for this triple as rotated.
        db.execute(
            text("""
                UPDATE integration_keys
                   SET key_status = 'rotated',
                       rotated_at = CURRENT_TIMESTAMP,
                       rotated_to_id = :nid,
                       valid_to = COALESCE(valid_to, CURRENT_TIMESTAMP + INTERVAL '1 hour'),
                       updated_at = CURRENT_TIMESTAMP
                 WHERE integration_type = :it AND provider = :pr AND key_name = :kn
                   AND key_status = 'active'
                   AND id <> :nid
            """),
            {"nid": new_id, "it": integration_type, "pr": provider, "kn": key_name},
        )
    return int(new_id)


def revoke_key(db, key_id: int) -> None:
    db.execute(
        text("""
            UPDATE integration_keys
               SET key_status = 'revoked',
                   valid_to = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = :id
        """),
        {"id": key_id},
    )


def get_active_key(
    db, *, integration_type: str, provider: str, key_name: str, tenant_id: str
) -> Optional[str]:
    """Return the decrypted plaintext for the currently active key (or None)."""
    row = db.execute(
        text("""
            SELECT encrypted_value
              FROM integration_keys
             WHERE integration_type = :it AND provider = :pr AND key_name = :kn
               AND key_status = 'active'
               AND (valid_to IS NULL OR valid_to > CURRENT_TIMESTAMP)
             ORDER BY id DESC
             LIMIT 1
        """),
        {"it": integration_type, "pr": provider, "kn": key_name},
    ).fetchone()
    if not row:
        return None
    cipher = row[0]
    if cipher is None:
        return None
    if is_encrypted(cipher):
        try:
            return decrypt(cipher, tenant_id=tenant_id)
        except Exception:
            logger.exception("[integration_keys] decrypt failed for %s/%s/%s",
                             integration_type, provider, key_name)
            return None
    # Defence-in-depth: tolerate a stray plaintext row.
    return cipher


def list_keys(
    db,
    *,
    integration_type: Optional[str] = None,
    provider: Optional[str] = None,
    include_revoked: bool = False,
) -> List[dict]:
    where = ["1=1"]
    params: dict = {}
    if integration_type:
        where.append("integration_type = :it"); params["it"] = integration_type
    if provider:
        where.append("provider = :pr"); params["pr"] = provider
    if not include_revoked:
        where.append("key_status <> 'revoked'")
    rows = db.execute(
        text(f"""
            SELECT id, integration_type, provider, key_name, key_status,
                   valid_from, valid_to, rotated_at, rotated_to_id,
                   branch_id, created_by, created_at
              FROM integration_keys
             WHERE {' AND '.join(where)}
             ORDER BY integration_type, provider, key_name, id DESC
        """),
        params,
    ).fetchall()
    return [
        {
            "id": r[0], "integration_type": r[1], "provider": r[2],
            "key_name": r[3], "key_status": r[4],
            "valid_from": r[5].isoformat() if r[5] else None,
            "valid_to": r[6].isoformat() if r[6] else None,
            "rotated_at": r[7].isoformat() if r[7] else None,
            "rotated_to_id": r[8],
            "branch_id": r[9], "created_by": r[10],
            "created_at": r[11].isoformat() if r[11] else None,
        }
        for r in rows
    ]


__all__ = ["insert_key", "revoke_key", "get_active_key", "list_keys"]
