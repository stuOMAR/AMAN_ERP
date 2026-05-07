"""T11 — Application-layer PII encryption helper.

Wraps :mod:`utils.field_encryption` (AES-256-GCM, tenant-derived key) with
the same plaintext-tolerant semantics used by :mod:`utils.secret_settings`,
but tailored for *row-level* PII columns rather than ``company_settings``
key/value rows.

Audit references: P1 #50, #56, #66 — sensitive HR/banking columns
(``iban``, ``tax_id``, ``social_security``, ``national_id``,
``bank_account_number``) currently sit in plaintext. The helpers here
deliver the encrypt-on-write / decrypt-on-read pieces. Schema-side, the
matching ``ALTER COLUMN ... TYPE TEXT`` lives in
``db_ddl/tenant_schema.py`` (so the longer ciphertext fits) and the
backfill is handled by ``scripts/encrypt_existing_pii.py``.

Design rules:
  * Reads tolerate legacy plaintext (zero-downtime rollout).
  * Writes always emit ciphertext. If no key is configured the underlying
    :func:`field_encryption.encrypt` raises and the route fails loudly.
  * Tenant scoping is mandatory — every helper requires the caller's
    ``company_id`` so HKDF salt is per-tenant.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from utils.field_encryption import (
    FieldEncryptionError,
    decrypt as _decrypt,
    encrypt as _encrypt,
    is_encrypted,
)

# Registry of known PII columns. Used by the backfill script to know
# which (table, column) pairs to walk. Routers don't have to consult
# this — they just call :func:`encrypt_pii` / :func:`decrypt_pii`.
PII_FIELDS: Dict[str, frozenset] = {
    "treasury_accounts":      frozenset({"iban", "account_number"}),
    "supplier_bank_accounts": frozenset({"iban", "account_number"}),
    "customer_bank_accounts": frozenset({"iban", "account_number"}),
    "parties":                frozenset({"iban", "tax_number"}),
    "employees":              frozenset({"tax_id", "social_security"}),
}


def encrypt_pii(value: Optional[str], *, tenant_id: str) -> Optional[str]:
    """Encrypt a PII value for storage.

    Returns the value unchanged when it is ``None`` or empty (no point
    encrypting nothing). Otherwise emits a base64 token. Raises
    :class:`FieldEncryptionError` if no encryption key is configured.
    """
    if value is None or value == "":
        return value
    if is_encrypted(value):
        # Caller already encrypted — keep idempotent.
        return value
    return _encrypt(value, tenant_id=tenant_id)


def decrypt_pii(value: Optional[str], *, tenant_id: str) -> Optional[str]:
    """Decrypt a PII token, tolerating legacy plaintext.

    Corrupt/wrong-key ciphertext returns ``None`` rather than leaking the
    base64 token to the caller.
    """
    if value is None or value == "":
        return value
    if not is_encrypted(value):
        return value
    try:
        return _decrypt(value, tenant_id=tenant_id)
    except FieldEncryptionError:
        return None


def encrypt_row(row: Mapping[str, Any], fields: Iterable[str], *,
                tenant_id: str) -> Dict[str, Any]:
    """Return a copy of ``row`` with the named PII fields encrypted."""
    out = dict(row)
    for f in fields:
        if f in out and out[f] is not None:
            out[f] = encrypt_pii(out[f], tenant_id=tenant_id)
    return out


def decrypt_row(row: Mapping[str, Any], fields: Iterable[str], *,
                tenant_id: str) -> Dict[str, Any]:
    """Return a copy of ``row`` with the named PII fields decrypted."""
    out = dict(row)
    for f in fields:
        if f in out and out[f] is not None:
            out[f] = decrypt_pii(out[f], tenant_id=tenant_id)
    return out


def mask_iban(iban: Optional[str]) -> str:
    """Return an IBAN safe for low-trust UI surfaces (logs, lists).

    Format: keep 2-letter country code + last 4 digits, mask the middle.
    Accepts already-decrypted plaintext input. Empty/None → ``""``.
    """
    if not iban:
        return ""
    s = str(iban).strip().replace(" ", "")
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}{'*' * (len(s) - 6)}{s[-4:]}"
