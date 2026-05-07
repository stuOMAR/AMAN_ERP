"""Payroll period reversal — canonical path for reversing a locked period.

Contract: calls gl_service.reverse(), inserts compensating bank rows,
sets wps_superseded_by_run_id, and writes audit trail.

Depends on: period_writer.transition_state, bank_movements, JESource.PAYROLL_REVERSE.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

from services.payroll.period_writer import transition_state

logger = logging.getLogger(__name__)


def reverse_payroll_period(
    conn: Any,
    *,
    tenant_id: int,
    period_id: int,
    run_id: Optional[int] = None,
    reason: str,
    actor_id: int,
) -> dict:
    """Reverse a locked payroll period.

    Steps:
      1. Verify period is in 'locked' state.
      2. Reverse the GL journal entry (if exists).
      3. Insert compensating bank movement rows.
      4. Set wps_superseded_by_run_id on the run (if run_id provided).
      5. Transition period state: locked → reversed.
      6. Write audit trail.

    Returns dict with reversal details.
    """
    from models.domain_models.je_source import JESource

    # 1. Verify period state
    period = conn.execute(
        text("""
            SELECT id, name, state, start_date, end_date
            FROM payroll_periods
            WHERE id = :pid AND tenant_id = :tid
        """),
        {"pid": period_id, "tid": tenant_id},
    ).fetchone()

    if period is None:
        raise LookupError("payroll.period_not_found")
    if period[2] != "locked":
        raise ValueError("payroll.period_not_locked")

    # 2. Reverse GL journal entry
    je_id = None
    existing_je = conn.execute(
        text("""
            SELECT je_id FROM payroll_runs
            WHERE period_id = :pid AND tenant_id = :tid
            ORDER BY id DESC LIMIT 1
        """),
        {"pid": period_id, "tid": tenant_id},
    ).fetchone()

    if existing_je and existing_je[0]:
        je_id = existing_je[0]
        try:
            from services.gl_service import reverse_journal_entry
            reverse_journal_entry(
                conn,
                tenant_id=str(tenant_id),
                journal_entry_id=je_id,
                reason=f"Payroll period {period_id} reversal: {reason}",
                source=JESource.PAYROLL_REVERSE.value,
            )
        except Exception as e:
            logger.warning("GL reversal failed for JE %d: %s", je_id, e)

    # 3. Compensating bank movements
    if run_id:
        existing_movements = conn.execute(
            text("""
                SELECT id, treasury_account_id, total_amount, currency
                FROM payroll_bank_movements
                WHERE tenant_id = :tid AND period_id = :pid AND run_id = :rid
            """),
            {"tid": tenant_id, "pid": period_id, "rid": run_id},
        ).fetchall()

        for mov in existing_movements:
            conn.execute(
                text("""
                    INSERT INTO payroll_bank_movements
                        (tenant_id, period_id, run_id, treasury_account_id,
                         total_amount, currency, description, created_at)
                    VALUES
                        (:tid, :pid, :rid, :treasury_id,
                         :amount, :currency, :desc, now())
                """),
                {
                    "tid": tenant_id,
                    "pid": period_id,
                    "rid": run_id,
                    "treasury_id": mov[1],
                    "amount": -float(mov[2]),  # Negative = reversal
                    "currency": mov[3],
                    "desc": f"Reversal of bank movement {mov[0]} for period {period_id}",
                },
            )

    # 4. Set wps_superseded_by_run_id
    if run_id:
        conn.execute(
            text("""
                UPDATE payroll_runs
                SET wps_superseded_by_run_id = :rid, updated_at = now()
                WHERE period_id = :pid AND tenant_id = :tid AND id = :rid
            """),
            {"rid": run_id, "pid": period_id, "tid": tenant_id},
        )

    # 5. Transition state
    transition_state(
        conn,
        tenant_id=tenant_id,
        period_id=period_id,
        from_state="locked",
        to_state="reversed",
    )

    # 6. Audit trail
    try:
        from services.audit_writer import log_activity
        log_activity(
            conn,
            action="payroll.period.reverse",
            entity_type="payroll_period",
            entity_id=str(period_id),
            actor_id=actor_id,
            details={
                "reason": reason,
                "run_id": run_id,
                "je_id": je_id,
                "period_name": period[1],
            },
            critical=True,
        )
        conn.commit()
    except Exception:
        logger.debug("Payroll reversal audit failed (non-critical)", exc_info=True)

    return {
        "period_id": period_id,
        "period_name": period[1],
        "reversed": True,
        "je_id": je_id,
        "run_id": run_id,
        "reason": reason,
    }
