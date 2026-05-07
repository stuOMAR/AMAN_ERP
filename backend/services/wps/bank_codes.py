"""Bank codes registry — lookup Saudi bank codes for WPS file generation.

Contract: see specs/024-workforce-service-comms-integrity/contracts/bank-codes-registry.md
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def lookup(conn: Any, *, tenant_id: int, swift_bic: str) -> Optional[dict]:
    """Look up a bank code by SWIFT/BIC."""
    row = conn.execute(
        text("""
            SELECT id, code, name_ar, name_en, swift_bic, is_active
            FROM bank_codes
            WHERE tenant_id = :tid AND swift_bic = :swift AND is_active = true
        """),
        {"tid": tenant_id, "swift": swift_bic},
    ).fetchone()

    if row is None:
        return None
    return {
        "id": row[0],
        "code": row[1],
        "name_ar": row[2],
        "name_en": row[3],
        "swift_bic": row[4],
        "is_active": row[5],
    }


def lookup_by_code(conn: Any, *, tenant_id: int, code: str) -> Optional[dict]:
    """Look up a bank code by the short code (e.g., RJHI, NCBS)."""
    row = conn.execute(
        text("""
            SELECT id, code, name_ar, name_en, swift_bic, is_active
            FROM bank_codes
            WHERE tenant_id = :tid AND code = :code AND is_active = true
        """),
        {"tid": tenant_id, "code": code},
    ).fetchone()

    if row is None:
        return None
    return {
        "id": row[0],
        "code": row[1],
        "name_ar": row[2],
        "name_en": row[3],
        "swift_bic": row[4],
        "is_active": row[5],
    }


def list_active(conn: Any, *, tenant_id: int) -> list[dict]:
    """List all active bank codes for a tenant."""
    rows = conn.execute(
        text("""
            SELECT id, code, name_ar, name_en, swift_bic, is_active
            FROM bank_codes
            WHERE tenant_id = :tid AND is_active = true
            ORDER BY code
        """),
        {"tid": tenant_id},
    ).fetchall()

    return [
        {
            "id": r[0],
            "code": r[1],
            "name_ar": r[2],
            "name_en": r[3],
            "swift_bic": r[4],
            "is_active": r[5],
        }
        for r in rows
    ]
