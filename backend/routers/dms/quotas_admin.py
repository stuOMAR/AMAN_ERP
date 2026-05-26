"""DMS quotas and quarantine admin endpoints."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from database import get_db_connection
from services.dms.documents import is_document_storage_path, tenant_numeric_id
from services.dms.quotas import recompute_quotas
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import http_error
from utils.tax_precision import require_idempotency_key

router = APIRouter(prefix="/dms", tags=["DMS Admin"])


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


def _tenant_response_id(tenant_id: str):
    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        return tenant_id


@router.get("/quotas")
@router.get("/admin/quotas")
def get_quotas(
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """View storage quotas for the tenant."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        # Get tenant quota setting
        tenant_quota = conn.execute(
            text("""
                SELECT setting_value FROM company_settings
                WHERE setting_key = 'dms.tenant_quota_mb'
            """),
        ).fetchone()
        max_mb = int(tenant_quota[0]) if tenant_quota else 51200

        # Get current usage
        usage = conn.execute(
            text("""
                SELECT COALESCE(SUM(file_size), 0), COUNT(*)
                FROM documents
                WHERE COALESCE(is_deleted, FALSE) = FALSE
            """),
        ).fetchone()

        used_bytes = int(usage[0]) if usage else 0
        doc_count = int(usage[1]) if usage else 0

        return {
            "tenant_id": _tenant_response_id(tenant_id),
            "quota_mb": max_mb,
            "used_mb": round(used_bytes / (1024 * 1024), 2),
            "remaining_mb": round(max_mb - used_bytes / (1024 * 1024), 2),
            "document_count": doc_count,
        }
    finally:
        conn.close()


@router.get("/quarantine")
@router.get("/admin/quarantine")
def list_quarantined(
    limit: int = Query(25, ge=1, le=100),
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """List quarantined documents."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT id, file_name, file_size,
                       scanned_at, scan_engine, created_at
                FROM documents
                WHERE COALESCE(is_deleted, FALSE) = FALSE
                  AND state = 'quarantined'
                ORDER BY scanned_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        return [
            {
                "id": r[0], "filename": r[1], "file_size": r[2],
                "quarantine_ref": f"document:{r[0]}",
                "scanned_at": r[3].isoformat() if r[3] else None,
                "scan_engine": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/scan-stats")
@router.get("/admin/scan-stats")
def get_scan_stats(
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """Return scan-state counts for the tenant's canonical DMS documents."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT COALESCE(state, 'clean') AS state, COUNT(*) AS count
                FROM documents
                WHERE COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY COALESCE(state, 'clean')
            """),
        ).fetchall()
        latest = conn.execute(
            text("""
                SELECT MAX(scanned_at) AS latest_scanned_at,
                       MAX(created_at) FILTER (WHERE state = 'quarantined') AS latest_quarantine_at
                FROM documents
                WHERE COALESCE(is_deleted, FALSE) = FALSE
            """),
        ).fetchone()
        counts = {str(r[0] or "unknown"): int(r[1] or 0) for r in rows}
        total = sum(counts.values())
        return {
            "tenant_id": _tenant_response_id(tenant_id),
            "total": total,
            "pending_scan": counts.get("pending_scan", 0),
            "clean": counts.get("clean", 0),
            "quarantined": counts.get("quarantined", 0),
            "unknown": counts.get("unknown", 0),
            "by_state": counts,
            "latest_scanned_at": latest[0].isoformat() if latest and latest[0] else None,
            "latest_quarantine_at": latest[1].isoformat() if latest and latest[1] else None,
        }
    finally:
        conn.close()


@router.post("/storage/recalculate")
@router.post("/admin/storage/recalculate")
def recalculate_storage(
    request: Request,
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """Recompute the tenant storage quota row from canonical DMS documents."""
    require_idempotency_key(request, operation="DMS storage recalculation")
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = recompute_quotas(conn, tenant_id=tenant_numeric_id(tenant_id))
        quota = get_quotas(current_user=current_user)
        return {**result, "quota": quota}
    finally:
        conn.close()


@router.post("/quarantine/{document_id}/release")
@router.post("/admin/quarantine/{document_id}/release")
def release_quarantined_document(
    document_id: int,
    request: Request,
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """Release a quarantined document after an administrator review."""
    require_idempotency_key(request, operation="DMS quarantine release")
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        row = conn.execute(
            text("""
                SELECT id, file_path, quarantine_path, state
                FROM documents
                WHERE id = :id AND COALESCE(is_deleted, FALSE) = FALSE
            """),
            {"id": document_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "document_not_found", request))
        if row.state != "quarantined":
            raise HTTPException(**http_error(409, "dms.not_quarantined", request))

        file_path = str(row.file_path or "")
        quarantine_path = str(row.quarantine_path or "")
        if not file_path:
            raise HTTPException(**http_error(500, "dms.release_failed", request))
        if quarantine_path and quarantine_path != file_path and os.path.exists(quarantine_path):
            if not is_document_storage_path(conn, tenant_id=tenant_id, file_path=quarantine_path):
                raise HTTPException(**http_error(403, "forbidden", request))
            if file_path and not is_document_storage_path(conn, tenant_id=tenant_id, file_path=file_path):
                raise HTTPException(**http_error(403, "forbidden", request))
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            os.replace(quarantine_path, file_path)

        conn.execute(
            text("""
                UPDATE documents
                   SET state = 'clean',
                       quarantine_path = NULL,
                       scanned_at = now(),
                       updated_at = now()
                 WHERE id = :id
            """),
            {"id": document_id},
        )
        conn.commit()
        return {"id": document_id, "state": "clean", "released": True}
    except HTTPException:
        conn.rollback()
        raise
    except OSError:
        conn.rollback()
        raise HTTPException(**http_error(500, "dms.release_failed", request))
    finally:
        conn.close()
