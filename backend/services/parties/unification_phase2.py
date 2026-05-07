"""T288: Party unification phase 2 — handles writes to unified party model."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def create_party_with_role(
    db: Any,
    tenant_id: str,
    legal_name: str,
    role: str,  # customer | supplier | employee
    display_name: str | None = None,
    tax_number: str | None = None,
    country: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Create a party and assign a role in one transaction.

    This is the unified write path. Legacy direct inserts should
    route through this service.
    """
    import uuid
    from sqlalchemy import text

    party_id = str(uuid.uuid4())
    role_id = str(uuid.uuid4())

    try:
        # Insert party
        db.execute(
            text("""
                INSERT INTO parties (id, tenant_id, legal_name, display_name, tax_number, country)
                VALUES (:id, :tid, :name, :display, :tax, :country)
            """),
            {"id": party_id, "tid": tenant_id, "name": legal_name,
             "display": display_name or legal_name, "tax": tax_number, "country": country},
        )

        # Insert role
        db.execute(
            text("""
                INSERT INTO party_roles (id, party_id, role, started_at, metadata)
                VALUES (:id, :pid, :role, NOW(), :meta)
            """),
            {"id": role_id, "pid": party_id, "role": role,
             "meta": str(metadata) if metadata else None},
        )

        db.commit()

        logger.info("Created party %s with role %s", party_id, role)
        return {"party_id": party_id, "role_id": role_id, "role": role}

    except Exception as exc:
        db.rollback()
        logger.error("Failed to create party with role: %s", exc)
        raise


async def get_party_by_legacy_id(
    db: Any,
    tenant_id: str,
    legacy_id: str,
    role: str,
) -> dict[str, Any] | None:
    """Look up a party by legacy ID during transition."""
    from sqlalchemy import text

    try:
        result = db.execute(
            text("""
                SELECT p.id, p.legal_name, p.display_name, pr.role
                FROM parties p
                JOIN party_roles pr ON pr.party_id = p.id
                WHERE pr.legacy_id = :lid AND pr.role = :role AND p.tenant_id = :tid
            """),
            {"lid": legacy_id, "role": role, "tid": tenant_id},
        )
        row = result.fetchone()
        if row:
            return {"party_id": row[0], "legal_name": row[1], "display_name": row[2], "role": row[3]}
        return None
    except Exception:
        return None
