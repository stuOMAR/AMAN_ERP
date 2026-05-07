"""T260: Scheduler monitor — status reader for UI."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_scheduler_jobs() -> list[dict[str, Any]]:
    """List all scheduled jobs with status and timing info."""
    from services.scheduler import get_scheduler_instance

    scheduler = get_scheduler_instance()
    if not scheduler:
        return []

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "job_id": job.id,
            "name": job.name or job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "status": "scheduled" if job.next_run_time else "paused",
        })

    return jobs


async def trigger_job(job_id: str) -> bool:
    """Force-trigger a scheduled job."""
    from services.scheduler import get_scheduler_instance

    scheduler = get_scheduler_instance()
    if not scheduler:
        return False

    job = scheduler.get_job(job_id)
    if not job:
        return False

    try:
        job.modify(next_run_time=None)
        scheduler.wakeup()
        return True
    except Exception as exc:
        logger.error("Failed to trigger job %s: %s", job_id, exc)
        return False
