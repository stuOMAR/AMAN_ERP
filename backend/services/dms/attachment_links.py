"""DMS attachment links — typed FK table replacing related_module/related_id.

Contract: see specs/024-workforce-service-comms-integrity/contracts/dms-attachment-links.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def link(
    conn: Any,
    *,
    tenant_id: int,
    document_id: int,
    entity_type: str,
    entity_id: int,
) -> dict:
    """Link a document to an entity."""
    # Check for duplicate
    existing = conn.execute(
        text("""
            SELECT 1 FROM dms_attachment_links
            WHERE tenant_id = :tnt AND document_id = :did
              AND entity_type = :etype AND entity_id = :eid
        """),
        {"tnt": tenant_id, "did": document_id, "etype": entity_type, "eid": entity_id},
    ).fetchone()

    if existing:
        raise ValueError("attachment.duplicate_link")

    row = conn.execute(
        text("""
            INSERT INTO dms_attachment_links
                (tenant_id, document_id, entity_type, entity_id, created_at)
            VALUES (:tnt, :did, :etype, :eid, now())
            RETURNING id
        """),
        {"tnt": tenant_id, "did": document_id, "etype": entity_type, "eid": entity_id},
    ).fetchone()
    conn.commit()
    return {"id": row[0], "document_id": document_id, "entity_type": entity_type, "entity_id": entity_id}


def unlink(
    conn: Any,
    *,
    tenant_id: int,
    document_id: int,
    entity_type: str,
    entity_id: int,
) -> bool:
    """Remove a document-entity link."""
    result = conn.execute(
        text("""
            DELETE FROM dms_attachment_links
            WHERE tenant_id = :tnt AND document_id = :did
              AND entity_type = :etype AND entity_id = :eid
        """),
        {"tnt": tenant_id, "did": document_id, "etype": entity_type, "eid": entity_id},
    )
    conn.commit()
    return result.rowcount > 0


def list_for_entity(
    conn: Any,
    *,
    tenant_id: int,
    entity_type: str,
    entity_id: int,
) -> list[dict]:
    """List documents linked to an entity."""
    rows = conn.execute(
        text("""
            SELECT l.id, l.document_id, d.file_name, d.file_size,
                   COALESCE(d.state, 'clean') AS state, d.created_at
            FROM dms_attachment_links l
            JOIN documents d ON d.id = l.document_id
            WHERE l.tenant_id = :tnt AND l.entity_type = :etype AND l.entity_id = :eid
              AND COALESCE(d.is_deleted, FALSE) = FALSE
            ORDER BY l.created_at DESC
        """),
        {"tnt": tenant_id, "etype": entity_type, "eid": entity_id},
    ).fetchall()

    return [
        {
            "link_id": r[0], "document_id": r[1], "filename": r[2],
            "file_size": r[3], "state": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


def list_links_for_document(
    conn: Any,
    *,
    tenant_id: int,
    document_id: int,
) -> list[dict]:
    """List entities linked to a document."""
    rows = conn.execute(
        text("""
            SELECT id, entity_type, entity_id, created_at
            FROM dms_attachment_links
            WHERE tenant_id = :tnt AND document_id = :did
            ORDER BY created_at DESC
        """),
        {"tnt": tenant_id, "did": document_id},
    ).fetchall()

    return [
        {
            "link_id": r[0], "entity_type": r[1], "entity_id": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]
