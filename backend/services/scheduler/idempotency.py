"""T016: Scheduler idempotency layer.

Uses ``scheduled_job_runs`` table with UNIQUE ``(job_id, scheduled_for, attempt)``
to prevent double-fire of critical scheduled jobs.

Usage::

    from services.scheduler import idempotent_run

    with idempotent_run("closing_payroll", scheduled_for=now):
        # Job body — only executes if not already running/completed
        ...
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

logger = logging.getLogger(__name__)


class IdempotentSkip(Exception):
    """Raised when a job run is absorbed as duplicate."""


@contextmanager
def idempotent_run(
    job_id: str,
    scheduled_for: datetime,
    attempt: int = 1,
    tenant_id: str | None = None,
) -> Generator[None, None, None]:
    """Context manager for idempotent scheduled job execution.

    Inserts a row into ``scheduled_job_runs`` with status ``running``.
    On success, updates to ``succeeded``. On failure, updates to ``failed``.
    If a row already exists for ``(job_id, scheduled_for, attempt)``, the
    job is skipped with status ``idempotent_skip``.

    Raises:
        IdempotentSkip: If the job is already running/completed for this
            ``(job_id, scheduled_for, attempt)``.
    """
    from database import get_tenant_db

    run_id = None
    try:
        with get_tenant_db(tenant_id) as db:
            # Try to insert the running row
            result = db.execute(
                """
                INSERT INTO scheduled_job_runs
                    (job_id, scheduled_for, attempt, status, started_at, tenant_id)
                VALUES
                    (:job_id, :scheduled_for, :attempt, 'running', NOW(), :tenant_id)
                ON CONFLICT (job_id, scheduled_for, attempt) DO NOTHING
                RETURNING id
                """,
                {"job_id": job_id, "scheduled_for": scheduled_for,
                 "attempt": attempt, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                # Row already exists — skip
                logger.info(
                    "Idempotent skip: job=%s scheduled_for=%s attempt=%d",
                    job_id, scheduled_for, attempt,
                )
                raise IdempotentSkip(
                    f"Job {job_id} already run for {scheduled_for} attempt {attempt}"
                )
            run_id = row[0]
            db.commit()

        # Execute the job body
        yield

        # Mark succeeded
        with get_tenant_db(tenant_id) as db:
            db.execute(
                "UPDATE scheduled_job_runs SET status = 'succeeded', finished_at = NOW() WHERE id = :id",
                {"id": run_id},
            )
            db.commit()

    except IdempotentSkip:
        raise
    except Exception as exc:
        # Mark failed
        if run_id is not None:
            try:
                with get_tenant_db(tenant_id) as db:
                    db.execute(
                        "UPDATE scheduled_job_runs SET status = 'failed', finished_at = NOW(), error = :error WHERE id = :id",
                        {"id": run_id, "error": str(exc)[:2000]},
                    )
                    db.commit()
            except Exception:
                logger.exception("Failed to update scheduled_job_runs status")
        raise
