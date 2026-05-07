"""HR PII gate — single canonical path for reads/writes of sensitive HR fields.

Fields: salary, iban, national_id, passport_number, bank_account_number, gosi_number.

Contract: see specs/024-workforce-service-comms-integrity/contracts/hr-pii-gate.md
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from utils.field_encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

PII_FIELDS = frozenset({
    "salary",
    "iban",
    "national_id",
    "passport_number",
    "bank_account_number",
    "gosi_number",
})

_MASK = "****"


def encrypt_pii(field_name: str, plaintext: str, *, tenant_id: str) -> bytes:
    """Encrypt a PII field value. Returns bytes suitable for BYTEA storage."""
    if field_name not in PII_FIELDS:
        raise ValueError(f"Unknown PII field: {field_name}")
    token = encrypt(plaintext, tenant_id=tenant_id)
    return token.encode("utf-8")


def decrypt_pii(field_name: str, ciphertext: bytes, *, tenant_id: str) -> str:
    """Decrypt a PII field value. Only path to plaintext at rest."""
    if field_name not in PII_FIELDS:
        raise ValueError(f"Unknown PII field: {field_name}")
    token = ciphertext.decode("utf-8") if isinstance(ciphertext, bytes) else ciphertext
    return decrypt(token, tenant_id=tenant_id)


def mask_employee_dict(employee: dict) -> dict:
    """Return a copy of employee dict with PII fields masked."""
    out = dict(employee)
    for field in PII_FIELDS:
        if field in out and out[field] is not None:
            out[field] = _MASK
            out[f"{field}_masked"] = True
        else:
            out[f"{field}_masked"] = False
    return out


def unmask_field(
    field_name: str,
    employee_id: int,
    request_user: Any,
    *,
    tenant_id: str,
    has_pii_permission: bool,
    conn: Any = None,
) -> str:
    """Return plaintext for a single PII field. Raises 403 without hr.pii."""
    if field_name not in PII_FIELDS:
        raise ValueError(f"Unknown PII field: {field_name}")
    if not has_pii_permission:
        raise PermissionError("pii.forbidden")

    from sqlalchemy import text

    col_encrypted = f"{field_name}_encrypted"
    row = conn.execute(
        text(f"SELECT {col_encrypted} FROM employees WHERE id = :eid AND tenant_id = :tid"),
        {"eid": employee_id, "tid": int(tenant_id)},
    ).fetchone()

    if row is None or row[0] is None:
        return ""

    plaintext = decrypt_pii(field_name, row[0], tenant_id=tenant_id)

    # Audit the unmasked read
    _audit_unmask(field_name, employee_id, request_user, tenant_id=tenant_id, conn=conn)

    return plaintext


def _audit_unmask(
    field_name: str,
    employee_id: int,
    request_user: Any,
    *,
    tenant_id: str,
    conn: Any,
) -> None:
    """Log an audit event for PII unmask."""
    try:
        from services.audit_writer import log_activity

        user_id = (
            request_user.get("id")
            if isinstance(request_user, dict)
            else getattr(request_user, "id", None)
        )
        log_activity(
            conn,
            action="hr.pii.read",
            entity_type="employee",
            entity_id=str(employee_id),
            actor_id=user_id,
            details={"fields_unmasked": [field_name]},
            critical=True,
        )
        conn.commit()
    except Exception:
        logger.debug("PII audit log failed (non-critical)", exc_info=True)


__all__ = [
    "PII_FIELDS",
    "encrypt_pii",
    "decrypt_pii",
    "mask_employee_dict",
    "unmask_field",
]
