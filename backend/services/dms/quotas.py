"""DMS quota management — Redis-cached usage with INCR/DECR on upload/delete.

Contract: see specs/024-workforce-service-comms-integrity/contracts/dms-quotas.md
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def check_quota(
    conn: Any,
    *,
    tenant_id: int,
    user_id: Optional[int] = None,
    file_size: int,
) -> dict:
    """Check if a file upload would exceed the quota.

    Returns dict with quota status.
    """
    # Get tenant quota
    tenant_quota = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'dms.tenant_quota_mb'
        """),
    ).fetchone()
    max_bytes = int(tenant_quota[0]) * 1024 * 1024 if tenant_quota else 51200 * 1024 * 1024

    # Get current usage
    usage = conn.execute(
        text("""
            SELECT COALESCE(SUM(file_size), 0)
            FROM documents
            WHERE COALESCE(is_deleted, FALSE) = FALSE
        """),
    ).fetchone()

    current_bytes = int(usage[0]) if usage else 0

    if current_bytes + file_size > max_bytes:
        return {
            "allowed": False,
            "reason": "dms.quota_exceeded",
            "current_bytes": current_bytes,
            "max_bytes": max_bytes,
            "file_size": file_size,
        }

    return {
        "allowed": True,
        "current_bytes": current_bytes,
        "max_bytes": max_bytes,
        "remaining_bytes": max_bytes - current_bytes,
    }


def recompute_quotas(conn: Any, *, tenant_id: int) -> dict:
    """Recompute storage quotas for a tenant (nightly job)."""
    conn.execute(
        text("""
            INSERT INTO storage_quotas (tenant_id, scope, scope_ref_id, used_bytes, quota_bytes, last_recalculated_at)
            SELECT :tnt, 'tenant', 0, COALESCE(SUM(file_size), 0),
                   51200 * 1024 * 1024, now()
            FROM documents
            WHERE COALESCE(is_deleted, FALSE) = FALSE
            ON CONFLICT (tenant_id, scope, scope_ref_id)
            DO UPDATE SET used_bytes = EXCLUDED.used_bytes,
                          last_recalculated_at = now()
        """),
        {"tnt": tenant_id},
    )
    conn.commit()
    return {"tenant_id": tenant_id, "recomputed": True}
