"""DMS quotas admin endpoint.

GET /api/dms/quotas — view storage quotas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from database import get_db_connection
from services.permissions.sensitive import require_sensitive_permission

router = APIRouter(prefix="/api/dms", tags=["DMS Admin"])


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


@router.get("/quotas")
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
                WHERE tenant_id = :tnt AND deleted_at IS NULL
            """),
            {"tnt": int(tenant_id)},
        ).fetchone()

        used_bytes = int(usage[0]) if usage else 0
        doc_count = int(usage[1]) if usage else 0

        return {
            "tenant_id": int(tenant_id),
            "quota_mb": max_mb,
            "used_mb": round(used_bytes / (1024 * 1024), 2),
            "remaining_mb": round(max_mb - used_bytes / (1024 * 1024), 2),
            "document_count": doc_count,
        }
    finally:
        conn.close()


@router.get("/quarantine")
def list_quarantined(
    current_user=Depends(require_sensitive_permission("dms.audit_admin")),
):
    """List quarantined documents."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT id, filename, file_size, quarantine_path,
                       scanned_at, scan_engine, created_at
                FROM documents
                WHERE tenant_id = :tnt AND state = 'quarantined'
                ORDER BY scanned_at DESC
            """),
            {"tnt": int(tenant_id)},
        ).fetchall()

        return [
            {
                "id": r[0], "filename": r[1], "file_size": r[2],
                "quarantine_path": r[3],
                "scanned_at": r[4].isoformat() if r[4] else None,
                "scan_engine": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()
