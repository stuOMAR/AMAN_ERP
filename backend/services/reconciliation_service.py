"""Reconciliation finalize — drift-guard with FOR UPDATE locking.

Contract: see specs/022-audit-security-finance-integrity/contracts/reconciliation-finalize.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from utils.audit import log_activity

logger = logging.getLogger(__name__)

_DEFAULT_TOLERANCE = Decimal("0.01")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class UnmatchedLine:
    line_id: int
    bank_amount: Decimal
    gl_amount: Decimal
    difference: Decimal


@dataclass
class DriftReport:
    gl_total: Decimal
    bank_total: Decimal
    difference: Decimal
    tolerance: Decimal
    unmatched_lines: list[UnmatchedLine] = field(default_factory=list)


@dataclass
class FinalizeResult:
    ok: bool
    drift_report: DriftReport | None
    finalized_at: datetime | None


# ── Errors ────────────────────────────────────────────────────────────────────

class ReconciliationDriftError(Exception):
    """Drift exceeds tolerance."""

    def __init__(self, report: DriftReport):
        self.drift_report = report
        super().__init__(
            f"Reconciliation drift {report.difference} exceeds "
            f"tolerance {report.tolerance}"
        )


class ReconciliationStateError(Exception):
    """Reconciliation is already finalized or in an unexpected state."""

    def __init__(self, reconciliation_id: int, current_state: str):
        self.reconciliation_id = reconciliation_id
        self.current_state = current_state
        super().__init__(
            f"Reconciliation {reconciliation_id} is '{current_state}', "
            "expected 'draft'"
        )


class ConflictError(Exception):
    """Concurrent finalize attempt (lock not acquired)."""

    def __init__(self, reconciliation_id: int):
        self.reconciliation_id = reconciliation_id
        super().__init__(
            f"Reconciliation {reconciliation_id} is locked by another transaction"
        )


# ── Tolerance lookup ─────────────────────────────────────────────────────────

def _get_tolerance(conn) -> Decimal:
    """Read reconciliation.drift_tolerance from company_settings."""
    row = conn.execute(
        text(
            """
            SELECT setting_value
            FROM company_settings
            WHERE setting_key = 'reconciliation.drift_tolerance'
            """
        )
    ).fetchone()
    if row and row[0]:
        return Decimal(str(row[0]))
    return _DEFAULT_TOLERANCE


# ── Public API ────────────────────────────────────────────────────────────────

def finalize_reconciliation(
    conn,
    tenant_id: int,
    reconciliation_id: int,
    *,
    actor_id: int,
) -> FinalizeResult:
    """Finalize a reconciliation with drift detection.

    Uses SELECT FOR UPDATE to prevent concurrent finalization.
    Returns ``FinalizeResult`` on success; raises on errors.
    """
    # 1. Acquire row lock
    recon = conn.execute(
        text(
            """
            SELECT id, status, account_id, cut_off, bank_total
            FROM reconciliations
            WHERE id = :rid
              AND tenant_id = current_setting('app.tenant_id', true)::bigint
            FOR UPDATE
            """
        ),
        {"rid": reconciliation_id},
    ).fetchone()

    if recon is None:
        raise ConflictError(reconciliation_id)

    if recon.status != "draft":
        raise ReconciliationStateError(reconciliation_id, recon.status)

    # 2. Compute GL balance
    gl_total_row = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(debit) - SUM(credit), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = :aid
              AND je.status = 'posted'
              AND je.entry_date <= :cut_off
            """
        ),
        {"aid": recon.account_id, "cut_off": recon.cut_off},
    ).fetchone()
    gl_total = Decimal(str(gl_total_row.balance)) if gl_total_row else Decimal("0")

    # 3. Compute bank total from matched + unmatched lines
    bank_lines = conn.execute(
        text(
            """
            SELECT id, bank_amount, gl_amount
            FROM reconciliation_lines
            WHERE reconciliation_id = :rid
            """
        ),
        {"rid": reconciliation_id},
    ).fetchall()

    bank_total = Decimal("0")
    unmatched: list[UnmatchedLine] = []
    for ln in bank_lines:
        b_amt = Decimal(str(ln.bank_amount or 0))
        g_amt = Decimal(str(ln.gl_amount or 0))
        bank_total += b_amt
        diff = b_amt - g_amt
        if diff != 0:
            unmatched.append(
                UnmatchedLine(
                    line_id=ln.id,
                    bank_amount=b_amt,
                    gl_amount=g_amt,
                    difference=diff,
                )
            )

    # 4. Drift check
    tolerance = _get_tolerance(conn)
    difference = abs(gl_total - bank_total)

    report = DriftReport(
        gl_total=gl_total,
        bank_total=bank_total,
        difference=difference,
        tolerance=tolerance,
        unmatched_lines=unmatched,
    )

    if difference > tolerance:
        logger.warning(
            "Reconciliation %s drift %s > tolerance %s",
            reconciliation_id,
            difference,
            tolerance,
        )
        raise ReconciliationDriftError(report)

    # 5. Accept — transition state
    finalized_at = conn.execute(text("SELECT clock_timestamp()")).scalar()

    conn.execute(
        text(
            """
            UPDATE reconciliations
            SET status = 'finalized',
                finalized_at = :now,
                gl_total = :gl_total,
                updated_at = :now
            WHERE id = :rid
            """
        ),
        {
            "rid": reconciliation_id,
            "gl_total": str(gl_total),
            "now": finalized_at,
        },
    )

    # 6. Critical audit
    log_activity(
        conn,
        user_id=actor_id,
        username="system",
        action="reconciliation.finalize",
        entity_type="reconciliation",
        entity_id=reconciliation_id,
        details={
            "gl_total": str(gl_total),
            "bank_total": str(bank_total),
            "difference": str(difference),
            "tolerance": str(tolerance),
            "unmatched_lines": len(unmatched),
        },
        critical=True,
    )

    return FinalizeResult(
        ok=True,
        drift_report=report,
        finalized_at=finalized_at,
    )
