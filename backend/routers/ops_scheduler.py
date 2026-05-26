"""T263: Ops scheduler router — list jobs + run-now endpoint.

Gated by require_sensitive_permission('ops.scheduler.admin').
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from utils.i18n import http_error
from services.permissions.sensitive import require_sensitive_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/scheduler", tags=["ops-scheduler"])


@router.get("/jobs")
async def list_scheduler_jobs(
    current_user=Depends(require_sensitive_permission("ops.scheduler.admin", audit_view=True)),
):
    """List all scheduled jobs with status and next run."""
    from services.scheduler import get_scheduler_jobs

    jobs = get_scheduler_jobs()
    return {"jobs": jobs}


@router.post("/jobs/{job_id}/run-now")
async def run_job_now(
    job_id: str,
    request: Request,
    current_user=Depends(require_sensitive_permission("ops.scheduler.admin", critical=True, audit_view=False)),
):
    """Force-run a scheduled job. Gated by ops.scheduler.admin. Audited."""
    from services.scheduler import trigger_job
    from database import get_tenant_db
    from services.audit_writer import log_activity

    try:
        result = await trigger_job(job_id)
        if not result:
            raise HTTPException(**http_error(404, "scheduler_job_not_found", request, job_id=job_id))

        # Audit
        try:
            company_id = (
                current_user.get("company_id")
                if isinstance(current_user, dict)
                else getattr(current_user, "company_id", None)
            )
            with get_tenant_db(company_id) as db:
                log_activity(
                    db,
                    action="scheduler.run_now",
                    entity_type="scheduler_job",
                    entity_id=None,
                    details={"job_id": job_id, "forced": True},
                    critical=True,
                )
                db.commit()
        except Exception:
            pass

        return {"status": "triggered", "job_id": job_id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(**http_error(500, "scheduler_job_trigger_failed", request))
