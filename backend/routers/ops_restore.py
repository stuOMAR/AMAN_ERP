"""T285: Ops restore router — dry-run + execute restore.

Gated by require_sensitive_permission('ops.restore').
Confirm token is HMAC-signed via feature 022 vault keys.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from utils.i18n import http_error
from services.permissions.sensitive import require_sensitive_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops-restore"])


class RestoreDryRunRequest(BaseModel):
    backup_id: str


class RestoreConfirmRequest(BaseModel):
    backup_id: str
    confirm_token: str


@router.get("/backups")
async def list_backups(current_user=Depends(require_sensitive_permission("ops.restore", audit_view=True))):
    """List backup runs."""
    from database import get_tenant_db
    from sqlalchemy import text

    company_id = (
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", None)
    )
    with get_tenant_db(company_id) as db:
        result = db.execute(text(
            "SELECT id, backup_id, started_at, finished_at, size_bytes, checksum, offsite_uri, status "
            "FROM backup_runs ORDER BY started_at DESC LIMIT 50"
        ))
        rows = result.fetchall()

    return [
        {
            "id": str(r[0]), "backup_id": str(r[1]),
            "started_at": r[2].isoformat() if r[2] else None,
            "finished_at": r[3].isoformat() if r[3] else None,
            "size_bytes": r[4], "checksum": r[5],
            "offsite_uri": r[6], "status": r[7],
        }
        for r in rows
    ]


@router.post("/restore/dry-run")
async def restore_dry_run(
    body: RestoreDryRunRequest,
    request: Request,
    current_user=Depends(require_sensitive_permission("ops.restore", critical=True, audit_view=False)),
):
    """Step 1: Validate backup + compute missing/extra tenants."""
    from services.ops.restore import dry_run_restore

    result = await dry_run_restore(body.backup_id)
    if not result:
        raise HTTPException(**http_error(404, "backup_not_found", request))
    return result


@router.post("/restore")
async def restore_execute(
    body: RestoreConfirmRequest,
    request: Request,
    current_user=Depends(require_sensitive_permission("ops.restore", critical=True, audit_view=False)),
):
    """Step 2: Execute restore with confirm token. Audited."""
    from services.ops.restore import execute_restore

    result = await execute_restore(body.backup_id, body.confirm_token)
    if not result.get("success"):
        raise HTTPException(**http_error(400, "restore_failed", request))
    return result
