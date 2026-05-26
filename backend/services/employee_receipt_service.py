"""
Employee Receipt Settlement Service.

Manages the lifecycle of employee expense-receipt settlements:
  draft → submitted → approved → posted
  submitted → rejected → draft

Posting routes through gl_service. All actions are audited.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from services.audit_writer import log_activity

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"approved", "rejected"},
    "approved": {"posted"},
    "rejected": {"draft"},
}


def _get_settlement(conn, tenant_id: int, settlement_id: int) -> dict:
    row = conn.execute(
        text("""
            SELECT * FROM employee_receipt_settlements
             WHERE id = :sid AND tenant_id = :tnt
        """),
        {"sid": settlement_id, "tnt": tenant_id},
    ).fetchone()
    if not row:
        raise ValueError(f"Settlement {settlement_id} not found")
    return dict(row._mapping)


def _transition(current: str, target: str):
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Invalid state transition: {current} → {target}. "
            f"Allowed from '{current}': {VALID_TRANSITIONS.get(current, set())}"
        )


def submit_settlement(
    conn,
    tenant_id: int,
    employee_id: int,
    advance_id: int,
    receipt_id: int,
    amount: Decimal | float | str,
) -> dict:
    """Create a new settlement in *draft* and immediately transition to *submitted*."""
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError("Amount must be positive")

    row = conn.execute(
        text("""
            INSERT INTO employee_receipt_settlements
                (tenant_id, employee_id, advance_id, receipt_id, amount,
                 status, created_at, updated_at)
            VALUES (:tnt, :emp, :adv, :rcpt, :amt,
                    'submitted', now(), now())
            RETURNING id, status
        """),
        {
            "tnt": tenant_id,
            "emp": employee_id,
            "adv": advance_id,
            "rcpt": receipt_id,
            "amt": str(amount),
        },
    ).fetchone()

    settlement_id = row[0]

    log_activity(
        conn,
        action="settlement.submitted",
        entity_type="employee_receipt_settlement",
        entity_id=settlement_id,
        actor_id=employee_id,
        details={
            "amount": str(amount),
            "advance_id": advance_id,
            "receipt_id": receipt_id,
        },
        critical=False,
    )

    return {"id": settlement_id, "status": "submitted"}


def approve_settlement(
    conn, tenant_id: int, settlement_id: int, actor_id: int
) -> dict:
    """Approve a submitted settlement."""
    rec = _get_settlement(conn, tenant_id, settlement_id)
    _transition(rec["status"], "approved")

    conn.execute(
        text("""
            UPDATE employee_receipt_settlements
               SET status = 'approved', approved_by = :actor, approved_at = now(), updated_at = now()
             WHERE id = :sid AND tenant_id = :tnt
        """),
        {"actor": actor_id, "sid": settlement_id, "tnt": tenant_id},
    )

    log_activity(
        conn,
        action="settlement.approved",
        entity_type="employee_receipt_settlement",
        entity_id=settlement_id,
        actor_id=actor_id,
        details={"amount": str(rec.get("amount"))},
        critical=False,
    )

    return {"id": settlement_id, "status": "approved"}


def reject_settlement(
    conn, tenant_id: int, settlement_id: int, actor_id: int, reason: str
) -> None:
    """Reject a submitted settlement, transitioning back to *draft*."""
    rec = _get_settlement(conn, tenant_id, settlement_id)
    _transition(rec["status"], "rejected")

    conn.execute(
        text("""
            UPDATE employee_receipt_settlements
               SET status = 'rejected', rejected_by = :actor, rejected_at = now(),
                   rejection_reason = :reason, updated_at = now()
             WHERE id = :sid AND tenant_id = :tnt
        """),
        {"actor": actor_id, "reason": reason, "sid": settlement_id, "tnt": tenant_id},
    )

    log_activity(
        conn,
        action="settlement.rejected",
        entity_type="employee_receipt_settlement",
        entity_id=settlement_id,
        actor_id=actor_id,
        details={"reason": reason},
        critical=False,
    )


def post_settlement(
    conn, tenant_id: int, settlement_id: int, actor_id: int
) -> dict:
    """Post an approved settlement — creates a journal entry via gl_service."""
    rec = _get_settlement(conn, tenant_id, settlement_id)
    _transition(rec["status"], "posted")

    amount = Decimal(str(rec.get("amount") or 0))
    rec.get("employee_id")

    from services.gl_service import create_journal_entry

    # Build balanced JE lines — debit expense, credit advance receivable
    lines = [
        {
            "account_id": rec.get("expense_account_id") or 1,
            "debit": amount,
            "credit": 0,
            "description": f"Employee receipt settlement #{settlement_id}",
        },
        {
            "account_id": rec.get("advance_account_id") or 1,
            "debit": 0,
            "credit": amount,
            "description": f"Employee receipt settlement #{settlement_id}",
        },
    ]

    je_id, je_number = create_journal_entry(
        conn,
        company_id=str(tenant_id),
        date=str(date.today()),
        description=f"Employee receipt settlement #{settlement_id}",
        lines=lines,
        user_id=actor_id,
        source="settlement",
        source_id=settlement_id,
        idempotency_key=f"settlement:{settlement_id}",
    )

    conn.execute(
        text("""
            UPDATE employee_receipt_settlements
               SET status = 'posted', posted_by = :actor, posted_at = now(),
                   journal_entry_id = :je_id, updated_at = now()
             WHERE id = :sid AND tenant_id = :tnt
        """),
        {"actor": actor_id, "je_id": je_id, "sid": settlement_id, "tnt": tenant_id},
    )

    log_activity(
        conn,
        action="settlement.posted",
        entity_type="employee_receipt_settlement",
        entity_id=settlement_id,
        actor_id=actor_id,
        details={"je_id": je_id, "amount": str(amount)},
        critical=True,
    )

    return {"id": settlement_id, "status": "posted", "journal_entry_id": je_id}
