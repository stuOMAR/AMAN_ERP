"""Payroll bank movements — records GL bank entries for payroll disbursement.

Contract: partial-unique idempotent insert ensures bank movements are recorded
exactly once per (period_id, run_id).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def record_payroll_bank_movements(
    conn: Any,
    *,
    tenant_id: int,
    period_id: int,
    run_id: int,
    treasury_account_id: int,
    total_amount: float,
    currency: str = "SAR",
    description: Optional[str] = None,
) -> dict:
    """Record bank movements for a payroll run.

    Idempotent: if movements already exist for this (period_id, run_id),
    returns the existing record.

    Returns dict with movement details.
    """
    # Check if already recorded
    existing = conn.execute(
        text("""
            SELECT id, total_amount, created_at
            FROM payroll_bank_movements
            WHERE tenant_id = :tid AND period_id = :pid AND run_id = :rid
        """),
        {"tid": tenant_id, "pid": period_id, "rid": run_id},
    ).fetchone()

    if existing:
        return {
            "id": existing[0],
            "total_amount": float(existing[1]),
            "created_at": existing[2].isoformat() if existing[2] else None,
            "already_recorded": True,
        }

    # Insert new movement record
    row = conn.execute(
        text("""
            INSERT INTO payroll_bank_movements
                (tenant_id, period_id, run_id, treasury_account_id,
                 total_amount, currency, description, created_at)
            VALUES
                (:tid, :pid, :rid, :treasury_id,
                 :amount, :currency, :desc, now())
            RETURNING id, total_amount, created_at
        """),
        {
            "tid": tenant_id,
            "pid": period_id,
            "rid": run_id,
            "treasury_id": treasury_account_id,
            "amount": total_amount,
            "currency": currency,
            "desc": description or f"Payroll disbursement for period {period_id}, run {run_id}",
        },
    ).fetchone()

    conn.commit()

    return {
        "id": row[0],
        "total_amount": float(row[1]),
        "created_at": row[2].isoformat() if row[2] else None,
        "already_recorded": False,
    }


def get_bank_movements(
    conn: Any,
    *,
    tenant_id: int,
    period_id: Optional[int] = None,
    run_id: Optional[int] = None,
) -> list[dict]:
    """Retrieve bank movement records for a period or run."""
    conditions = ["tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id}

    if period_id is not None:
        conditions.append("period_id = :pid")
        params["pid"] = period_id
    if run_id is not None:
        conditions.append("run_id = :rid")
        params["rid"] = run_id

    where = " AND ".join(conditions)
    rows = conn.execute(
        text(f"""
            SELECT id, period_id, run_id, treasury_account_id,
                   total_amount, currency, description, created_at
            FROM payroll_bank_movements
            WHERE {where}
            ORDER BY created_at DESC
        """),
        params,
    ).fetchall()

    return [
        {
            "id": r[0],
            "period_id": r[1],
            "run_id": r[2],
            "treasury_account_id": r[3],
            "total_amount": float(r[4]),
            "currency": r[5],
            "description": r[6],
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]
