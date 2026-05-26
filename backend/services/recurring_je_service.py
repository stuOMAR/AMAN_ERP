"""
Recurring JE Template Service.

Runs recurring journal-entry templates on a schedule, routes through
gl_service for posting, and supports manual approval/rejection of
entries that exceed the review threshold.

Contract: specs/022-audit-security-finance-integrity/contracts/recurring-template.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import text

from services.audit_writer import log_activity

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    posted: bool
    pending_review_id: int | None
    journal_entry_id: int | None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _acquire_advisory_lock(conn, template_id: int) -> bool:
    """pg_try_advisory_xact_lock keyed by template_id — returns True if acquired."""
    row = conn.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": template_id}
    ).fetchone()
    return bool(row and row[0])


def _load_template(conn, tenant_id: int, template_id: int) -> dict | None:
    row = conn.execute(
        text("""
            SELECT t.*,
                   (SELECT COALESCE(SUM(debit), 0) FROM jsonb_to_recordset(t.lines)
                        AS (debit numeric) ) AS computed_amount
              FROM recurring_journal_templates t
             WHERE t.id = :tid
               AND t.tenant_id = :tnt
        """),
        {"tid": template_id, "tnt": tenant_id},
    ).fetchone()
    return dict(row._mapping) if row else None


def _compute_amount(template: dict) -> Decimal:
    """Compute the entry amount from the template's line definitions."""
    lines = template.get("lines") or []
    total = Decimal("0")
    for line in lines:
        d = line.get("debit") or 0
        total += Decimal(str(d))
    return total


def _notify_approvers(conn, tenant_id: int, pending_id: int, template_id: int):
    """Enqueue notification for reviewers (fire-and-forget)."""
    try:
        conn.execute(
            text("""
                INSERT INTO notifications (tenant_id, module, subject, body, created_at)
                VALUES (:tnt, 'recurring', :subj, :body, now())
            """),
            {
                "tnt": tenant_id,
                "subj": f"Recurring JE #{template_id} pending review",
                "body": f"Recurring template {template_id} generated a pending review (#{pending_id}).",
            },
        )
    except Exception:
        logger.debug("Notification insert skipped (table may not exist)", exc_info=True)


# ── Public API ─────────────────────────────────────────────────────────────────


def run_template(conn, tenant_id: int, template_id: int, *, run_date: date) -> RunResult:
    """Execute a recurring template for *run_date*.

    Uses an advisory lock keyed by *template_id* to prevent concurrent
    duplicate runs.
    """
    if not _acquire_advisory_lock(conn, template_id):
        logger.info("Advisory lock not acquired for template %s — skipping", template_id)
        return RunResult(posted=False, pending_review_id=None, journal_entry_id=None)

    template = _load_template(conn, tenant_id, template_id)
    if template is None:
        raise ValueError(f"Template {template_id} not found for tenant {tenant_id}")

    expense_category_id = template.get("expense_category_id")
    if expense_category_id is None:
        raise ValueError(
            f"Recurring template {template_id} has no expense_category_id configured"
        )

    # Validate that category exists and is not soft-deleted
    cat_row = conn.execute(
        text("SELECT 1 FROM expense_categories WHERE id = :cid AND deleted_at IS NULL"),
        {"cid": expense_category_id},
    ).fetchone()
    if not cat_row:
        raise ValueError(
            f"expense_category_id={expense_category_id} references a deleted or missing category"
        )

    amount = _compute_amount(template)
    auto_approve = bool(template.get("auto_approve", False))
    review_threshold = template.get("review_threshold")
    threshold = Decimal(str(review_threshold)) if review_threshold is not None else None

    can_auto_post = auto_approve and (threshold is None or amount < threshold)

    if can_auto_post:
        # Post directly via gl_service
        from services.gl_service import create_journal_entry

        # Check fiscal period before posting (Constitution §3: skipped periods must be flagged)
        from utils.fiscal_lock import check_fiscal_period_open
        period_open = check_fiscal_period_open(conn, str(run_date), raise_error=False)
        if not period_open:
            # Write a pending review row for the skipped period
            try:
                conn.execute(text("""
                    INSERT INTO recurring_je_pending_review
                        (tenant_id, template_id, amount, expense_category_id, lines, run_date, status, created_at)
                    VALUES (:tnt, :tid, :amt, :cat, CAST(:lines AS JSONB), :rdate, 'skipped_closed_period', now())
                    ON CONFLICT DO NOTHING
                """), {
                    "tnt": tenant_id,
                    "tid": template_id,
                    "amt": str(amount),
                    "cat": expense_category_id,
                    "lines": __import__("json").dumps(template.get("lines") or []),
                    "rdate": run_date,
                })
                # Advance next_run_date so we don't retry the same closed period
                next_run = run_date + relativedelta(months=1)
                conn.execute(text("""
                    UPDATE recurring_journal_templates
                       SET last_run = :run_date, next_run_date = :next_run, updated_at = now()
                     WHERE id = :tid
                """), {"run_date": run_date, "next_run": next_run, "tid": template_id})
            except Exception as skip_err:
                logger.warning("recurring: failed to record skipped period for template %s: %s", template_id, skip_err)

            logger.info("Recurring template %s skipped: fiscal period %s is closed", template_id, run_date)
            return RunResult(posted=False, pending_review_id=None, journal_entry_id=None)

        lines = template.get("lines") or []
        je_id, je_number = create_journal_entry(
            conn,
            company_id=str(tenant_id),
            date=str(run_date),
            description=template.get("description", "Recurring JE"),
            lines=lines,
            user_id=template.get("created_by", 1),
            source="recurring",
            source_id=template_id,
            idempotency_key=f"recurring:{template_id}:{run_date.isoformat()}",
        )

        log_activity(
            conn,
            action="recurring.auto_post",
            entity_type="recurring_template",
            entity_id=template_id,
            actor_id=template.get("created_by"),
            details={"amount": str(amount), "je_id": je_id, "run_date": run_date.isoformat()},
            critical=False,
        )

        conn.execute(
            text("""
                UPDATE recurring_journal_templates
                   SET last_run = :run_date, updated_at = now()
                 WHERE id = :tid
            """),
            {"run_date": run_date, "tid": template_id},
        )

        return RunResult(posted=True, pending_review_id=None, journal_entry_id=je_id)

    # Write pending review row
    pending_row = conn.execute(
        text("""
            INSERT INTO recurring_je_pending_review
                (tenant_id, template_id, amount, expense_category_id, lines, run_date, status, created_at)
            VALUES (:tnt, :tid, :amt, :cat, CAST(:lines AS JSONB), :rdate, 'pending', now())
            RETURNING id
        """),
        {
            "tnt": tenant_id,
            "tid": template_id,
            "amt": str(amount),
            "cat": expense_category_id,
            "lines": __import__("json").dumps(template.get("lines") or []),
            "rdate": run_date,
        },
    ).fetchone()

    pending_id = pending_row[0]

    _notify_approvers(conn, tenant_id, pending_id, template_id)

    log_activity(
        conn,
        action="recurring.pending_review",
        entity_type="recurring_template",
        entity_id=template_id,
        actor_id=template.get("created_by"),
        details={"pending_id": pending_id, "amount": str(amount), "run_date": run_date.isoformat()},
        critical=False,
    )

    conn.execute(
        text("""
            UPDATE recurring_journal_templates
               SET last_run = :run_date, updated_at = now()
             WHERE id = :tid
        """),
        {"run_date": run_date, "tid": template_id},
    )

    return RunResult(posted=False, pending_review_id=pending_id, journal_entry_id=None)


def approve_pending(conn, tenant_id: int, pending_id: int, *, actor_id: int) -> RunResult:
    """Approve a pending recurring JE and post it via gl_service."""
    row = conn.execute(
        text("""
            SELECT * FROM recurring_je_pending_review
             WHERE id = :pid AND tenant_id = :tnt AND status = 'pending'
        """),
        {"pid": pending_id, "tnt": tenant_id},
    ).fetchone()

    if not row:
        raise ValueError(f"Pending review {pending_id} not found or not in 'pending' status")

    rec = dict(row._mapping)
    import json as _json

    lines = rec.get("lines")
    if isinstance(lines, str):
        lines = _json.loads(lines)

    run_date = rec.get("run_date") or date.today()

    from services.gl_service import create_journal_entry

    je_id, je_number = create_journal_entry(
        conn,
        company_id=str(tenant_id),
        date=str(run_date),
        description=f"Recurring JE (approved from pending #{pending_id})",
        lines=lines,
        user_id=actor_id,
        source="recurring",
        source_id=rec.get("template_id"),
        idempotency_key=f"recurring:approved:{pending_id}",
    )

    conn.execute(
        text("""
            UPDATE recurring_je_pending_review
               SET status = 'approved', approved_by = :actor, approved_at = now(), journal_entry_id = :je_id
             WHERE id = :pid
        """),
        {"actor": actor_id, "je_id": je_id, "pid": pending_id},
    )

    log_activity(
        conn,
        action="recurring.approved_post",
        entity_type="recurring_je_pending_review",
        entity_id=pending_id,
        actor_id=actor_id,
        details={"je_id": je_id, "amount": str(rec.get("amount"))},
        critical=True,
    )

    return RunResult(posted=True, pending_review_id=pending_id, journal_entry_id=je_id)


def reject_pending(
    conn, tenant_id: int, pending_id: int, *, actor_id: int, reason: str
) -> None:
    """Reject a pending recurring JE."""
    row = conn.execute(
        text("""
            SELECT id FROM recurring_je_pending_review
             WHERE id = :pid AND tenant_id = :tnt AND status = 'pending'
        """),
        {"pid": pending_id, "tnt": tenant_id},
    ).fetchone()

    if not row:
        raise ValueError(f"Pending review {pending_id} not found or not in 'pending' status")

    conn.execute(
        text("""
            UPDATE recurring_je_pending_review
               SET status = 'rejected', rejected_by = :actor, rejected_at = now(), rejection_reason = :reason
             WHERE id = :pid
        """),
        {"actor": actor_id, "reason": reason, "pid": pending_id},
    )

    log_activity(
        conn,
        action="recurring.rejected",
        entity_type="recurring_je_pending_review",
        entity_id=pending_id,
        actor_id=actor_id,
        details={"reason": reason},
        critical=False,
    )
