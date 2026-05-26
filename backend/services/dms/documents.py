"""Shared DMS document persistence helpers.

These helpers keep legacy module uploads attached to the canonical
``documents`` table so quota, scan-state, storage path, and attachment-link
features see the same files.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text

from services.dms.quotas import check_quota
from services.dms.storage_paths import (
    compute_checksum,
    compute_storage_path,
    ensure_directory,
    get_storage_root,
)
from services.dms.streaming_mime import validate_mime
from utils.sql_safety import validate_file_path_safety

logger = logging.getLogger(__name__)

LOCAL_DMS_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "dms"


class DMSQuotaExceeded(ValueError):
    """Raised when a document upload would exceed configured quota."""

    def __init__(self, quota: dict):
        super().__init__("dms.quota_exceeded")
        self.quota = quota


def tenant_numeric_id(tenant_id: Any) -> int:
    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        return 0


def _normalise_tags(tags: Any) -> str:
    if tags in (None, ""):
        return "[]"
    if isinstance(tags, (list, dict)):
        return json.dumps(tags)
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, (list, dict)):
                return json.dumps(parsed)
        except json.JSONDecodeError:
            pass
        return json.dumps([t.strip() for t in tags.split(",") if t.strip()])
    return "[]"


def _write_content(
    conn: Any,
    *,
    tenant_id: Any,
    document_id: int,
    filename: str,
    content: bytes,
) -> tuple[str, str, Optional[str]]:
    ext = os.path.splitext(filename or "")[1].lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    roots = [get_storage_root(conn, tenant_id=tenant_numeric_id(tenant_id)), str(LOCAL_DMS_ROOT)]

    last_error: Optional[OSError] = None
    for root in dict.fromkeys(roots):
        try:
            directory = compute_storage_path(tenant_id, document_id, filename, root)
            ensure_directory(directory)
            path = os.path.join(directory, stored_name)
            with open(path, "wb") as handle:
                handle.write(content)
            checksum = compute_checksum(path)
            mime_result = validate_mime(path)
            detected_mime = mime_result.get("detected_mime") if mime_result.get("valid") else None
            return path, checksum, detected_mime
        except OSError as exc:
            last_error = exc
            logger.warning("DMS storage root unavailable; trying fallback")

    if last_error:
        raise last_error
    raise OSError("dms.storage_unavailable")


def create_document_from_upload(
    conn: Any,
    *,
    tenant_id: Any,
    user_id: Optional[int],
    filename: str,
    content: bytes,
    content_type: Optional[str],
    title: Optional[str] = None,
    description: str = "",
    category: str = "general",
    tags: Any = None,
    access_level: str = "company",
    related_module: Optional[str] = None,
    related_id: Optional[int] = None,
) -> dict:
    """Create a canonical DMS document row and write content to DMS storage."""
    quota = check_quota(
        conn,
        tenant_id=tenant_numeric_id(tenant_id),
        user_id=user_id,
        file_size=len(content),
    )
    if not quota.get("allowed"):
        raise DMSQuotaExceeded(quota)

    used_title = title or filename or "document"
    doc_id = conn.execute(
        text("""
            INSERT INTO documents (
                title, description, category, file_name, file_size, mime_type,
                tags, access_level, related_module, related_id, state, created_by
            )
            VALUES (
                :title, :description, :category, :file_name, :file_size, :mime_type,
                CAST(:tags AS JSONB), :access_level, :related_module, :related_id,
                'pending_scan', :created_by
            )
            RETURNING id
        """),
        {
            "title": used_title,
            "description": description,
            "category": category or "general",
            "file_name": filename,
            "file_size": len(content),
            "mime_type": content_type,
            "tags": _normalise_tags(tags),
            "access_level": access_level or "company",
            "related_module": related_module,
            "related_id": related_id,
            "created_by": user_id,
        },
    ).scalar()

    file_path, checksum, detected_mime = _write_content(
        conn,
        tenant_id=tenant_id,
        document_id=doc_id,
        filename=filename,
        content=content,
    )

    conn.execute(
        text("""
            UPDATE documents
               SET file_path = :file_path,
                   checksum_sha256 = :checksum,
                   mime_type = COALESCE(:detected_mime, :mime_type),
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = :id
        """),
        {
            "id": doc_id,
            "file_path": file_path,
            "checksum": checksum,
            "detected_mime": detected_mime,
            "mime_type": content_type,
        },
    )
    conn.execute(
        text("""
            INSERT INTO document_versions (
                document_id, version_number, file_name, file_path, file_size,
                change_notes, uploaded_by
            )
            VALUES (:id, 1, :file_name, :file_path, :file_size, :notes, :user_id)
        """),
        {
            "id": doc_id,
            "file_name": filename,
            "file_path": file_path,
            "file_size": len(content),
            "notes": "Initial version",
            "user_id": user_id,
        },
    )

    if related_module and related_id:
        conn.execute(
            text("""
                INSERT INTO dms_attachment_links (
                    tenant_id, document_id, entity_type, entity_id, created_by_user_id, created_at
                )
                SELECT :tenant_id, :document_id, :entity_type, :entity_id, :user_id, now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM dms_attachment_links
                     WHERE tenant_id = :tenant_id
                       AND document_id = :document_id
                       AND entity_type = :entity_type
                       AND entity_id = :entity_id
                )
            """),
            {
                "tenant_id": tenant_numeric_id(tenant_id),
                "document_id": doc_id,
                "entity_type": related_module,
                "entity_id": int(related_id),
                "user_id": user_id,
            },
        )

    return {
        "id": doc_id,
        "file_path": file_path,
        "checksum_sha256": checksum,
        "mime_type": detected_mime or content_type,
    }


def save_document_version_from_upload(
    conn: Any,
    *,
    tenant_id: Any,
    document_id: int,
    version_number: int,
    user_id: Optional[int],
    filename: str,
    content: bytes,
    content_type: Optional[str],
    change_notes: Optional[str] = None,
) -> dict:
    quota = check_quota(
        conn,
        tenant_id=tenant_numeric_id(tenant_id),
        user_id=user_id,
        file_size=len(content),
    )
    if not quota.get("allowed"):
        raise DMSQuotaExceeded(quota)

    file_path, checksum, detected_mime = _write_content(
        conn,
        tenant_id=tenant_id,
        document_id=document_id,
        filename=filename,
        content=content,
    )
    conn.execute(
        text("""
            INSERT INTO document_versions (
                document_id, version_number, file_name, file_path, file_size,
                change_notes, uploaded_by
            )
            VALUES (:id, :version, :file_name, :file_path, :file_size, :notes, :user_id)
        """),
        {
            "id": document_id,
            "version": version_number,
            "file_name": filename,
            "file_path": file_path,
            "file_size": len(content),
            "notes": change_notes or f"Version {version_number}",
            "user_id": user_id,
        },
    )
    conn.execute(
        text("""
            UPDATE documents
               SET current_version = :version,
                   file_name = :file_name,
                   file_path = :file_path,
                   file_size = :file_size,
                   mime_type = COALESCE(:detected_mime, :mime_type),
                   checksum_sha256 = :checksum,
                   state = 'pending_scan',
                   updated_at = CURRENT_TIMESTAMP,
                   updated_by = :user_id
             WHERE id = :id
        """),
        {
            "id": document_id,
            "version": version_number,
            "file_name": filename,
            "file_path": file_path,
            "file_size": len(content),
            "detected_mime": detected_mime,
            "mime_type": content_type,
            "checksum": checksum,
            "user_id": user_id,
        },
    )
    return {"file_path": file_path, "checksum_sha256": checksum, "mime_type": detected_mime or content_type}


def is_document_storage_path(conn: Any, *, tenant_id: Any, file_path: str) -> bool:
    roots = [
        get_storage_root(conn, tenant_id=tenant_numeric_id(tenant_id)),
        str(LOCAL_DMS_ROOT),
    ]
    return any(validate_file_path_safety(file_path, root) for root in roots if root)
