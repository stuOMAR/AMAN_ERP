"""Subscription billing service.

Handles enrollment lifecycle: enroll, billing, proration, cancellation,
trial management, and failed payment handling.
"""

import calendar
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

from services.gl_service import create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from services.tax_engine import resolve_line_tax

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_D4 = Decimal("0.0001")


def _dec(val) -> Decimal:
    if val is None:
        return _ZERO
    return Decimal(str(val))


def _billing_period_end(start: date, frequency: str) -> date:
    """Compute billing period end date from start and frequency.

    Uses calendar-aware logic so that a plan starting on the 31st
    correctly bills through Feb 28/29, then returns to Mar 31, etc.
    """
    def _advance_months(d: date, months: int) -> date:
        """Advance a date by N months, clamping to the last day of the target month."""
        month = d.month + months
        year = d.year
        while month > 12:
            month -= 12
            year += 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(d.day, last_day)
        return date(year, month, day)

    if frequency == "monthly":
        return _advance_months(start, 1) - timedelta(days=1)
    elif frequency == "quarterly":
        return _advance_months(start, 3) - timedelta(days=1)
    elif frequency == "annual":
        return _advance_months(start, 12) - timedelta(days=1)
    else:
        # Default to monthly
        return _advance_months(start, 1) - timedelta(days=1)


def _next_billing(current: date, frequency: str) -> date:
    """Compute next billing date after current period."""
    end = _billing_period_end(current, frequency)
    return end + timedelta(days=1)


def _months_in_frequency(frequency: str) -> int:
    """Return number of months covered by a billing frequency."""
    return {"monthly": 1, "quarterly": 3, "annual": 12}.get(frequency, 1)


def _create_deferred_revenue_schedule(
    db, *, subscription_invoice_id: int, enrollment_id: int,
    amount: Decimal, billing_start: date, frequency: str, user: str | None = None
) -> int:
    """Create straight-line monthly deferred revenue recognition rows.

    For non-monthly billing, splits total amount evenly across months and inserts
    one row per month into deferred_revenue_schedules.
    Returns count of rows inserted.
    """
    months = _months_in_frequency(frequency)
    if months <= 1:
        return 0  # monthly — no deferral needed

    monthly_amount = (amount / Decimal(str(months))).quantize(_D4, rounding=ROUND_HALF_UP)
    # Adjust last month for rounding remainder
    remainder = amount - (monthly_amount * (months - 1))

    count = 0
    recognition = billing_start
    for i in range(months):
        rec_amount = remainder if i == months - 1 else monthly_amount
        db.execute(
            text(
                "INSERT INTO deferred_revenue_schedules "
                "(subscription_invoice_id, enrollment_id, recognition_date, amount, "
                " status, created_by) "
                "VALUES (:siid, :eid, :rd, :amt, 'pending', :usr)"
            ),
            {
                "siid": subscription_invoice_id,
                "eid": enrollment_id,
                "rd": recognition,
                "amt": str(rec_amount),
                "usr": user,
            },
        )
        count += 1
        # Advance to first of next month
        if recognition.month == 12:
            recognition = date(recognition.year + 1, 1, 1)
        else:
            recognition = date(recognition.year, recognition.month + 1, 1)

    return count


# ── Enrollment ──

def enroll_customer(db, *, customer_id: int, plan_id: int, enrollment_date: date | None = None, user: str | None = None) -> dict:
    """Enroll a customer in a subscription plan.

    If the plan has trial_period_days > 0, sets trial status and trial_end_date.
    Returns dict with enrollment_id.
    """
    today = enrollment_date or date.today()

    plan = db.execute(
        text("SELECT * FROM subscription_plans WHERE id = :pid AND is_deleted = false AND is_active = true"),
        {"pid": plan_id},
    ).fetchone()
    if not plan:
        raise ValueError(f"Plan {plan_id} not found or inactive")

    # Check customer exists
    customer = db.execute(
        text("SELECT id FROM parties WHERE id = :cid"),
        {"cid": customer_id},
    ).fetchone()
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    # Prevent duplicate active enrollment for same customer + plan
    existing = db.execute(
        text(
            "SELECT id FROM subscription_enrollments "
            "WHERE customer_id = :cid AND plan_id = :pid "
            "  AND status IN ('active', 'paused', 'trial') AND is_deleted = false "
            "FOR UPDATE"
        ),
        {"cid": customer_id, "pid": plan_id},
    ).fetchone()
    if existing:
        raise ValueError(f"Customer {customer_id} already has an active enrollment in plan {plan_id}")

    trial_days = plan.trial_period_days or 0
    if trial_days > 0:
        status = "trial"
        trial_end = today + timedelta(days=trial_days)
        next_billing = trial_end + timedelta(days=1)
    else:
        status = "active"
        trial_end = None
        next_billing = _next_billing(today, plan.billing_frequency)

    row = db.execute(
        text(
            "INSERT INTO subscription_enrollments "
            "(customer_id, plan_id, start_date, trial_end_date, next_billing_date, status, "
            " created_by, updated_by) "
            "VALUES (:cid, :pid, :ed, :ted, :nbd, :st, :usr, :usr) "
            "RETURNING id"
        ),
        {
            "cid": customer_id,
            "pid": plan_id,
            "ed": today,
            "ted": trial_end,
            "nbd": next_billing,
            "st": status,
            "usr": user,
        },
    ).fetchone()
    enrollment_id = row[0]
    db.commit()

    logger.info(
        "Enrolled customer %d in plan %d (status=%s, enrollment=%d)",
        customer_id, plan_id, status, enrollment_id,
    )
    return {"enrollment_id": enrollment_id, "status": status}


# ── Invoice Generation ──

def generate_subscription_invoice(db, *, enrollment_id: int, user: str | None = None,
                                   company_id: str | None = None) -> dict:
    """Generate an invoice for the current billing period of an enrollment.

    Creates an invoice record linked via subscription_invoices, posts a balanced
    GL journal entry (DR Receivable, CR Revenue/Deferred Revenue, CR VAT Payable),
    and stores tax/journal info on the subscription_invoices record.
    Returns dict with invoice_id and subscription_invoice_id.
    """
    enrollment = db.execute(
        text(
            "SELECT e.*, p.base_amount, p.currency, p.billing_frequency, p.name AS plan_name "
            "FROM subscription_enrollments e "
            "JOIN subscription_plans p ON p.id = e.plan_id "
            "WHERE e.id = :eid AND e.is_deleted = false "
            "FOR UPDATE OF e"
        ),
        {"eid": enrollment_id},
    ).fetchone()
    if not enrollment:
        raise ValueError(f"Enrollment {enrollment_id} not found")

    if enrollment.status not in ("active", "at_risk"):
        raise ValueError(f"Cannot bill enrollment in '{enrollment.status}' status")

    billing_start = enrollment.next_billing_date
    billing_end = _billing_period_end(billing_start, enrollment.billing_frequency)
    amount = _dec(enrollment.base_amount).quantize(_D4, rounding=ROUND_HALF_UP)
    currency = enrollment.currency or "SAR"

    # Idempotency: check if invoice already exists for this period
    existing_invoice = db.execute(
        text(
            "SELECT id, invoice_id FROM subscription_invoices "
            "WHERE enrollment_id = :eid AND billing_period_start = :bps AND is_deleted = false"
        ),
        {"eid": enrollment_id, "bps": billing_start},
    ).fetchone()
    if existing_invoice:
        logger.info(
            "Invoice already exists for enrollment %d period %s (id=%d)",
            enrollment_id, billing_start, existing_invoice.id,
        )
        return {"invoice_id": existing_invoice.invoice_id, "subscription_invoice_id": existing_invoice.id,
                "journal_entry_id": None, "duplicate": True}

    # Fiscal period check
    check_fiscal_period_open(db, billing_start)

    # VAT calculation (resolved via tax engine)
    from utils.accounting import compute_invoice_totals
    
    # Get default branch for tax resolution (subscriptions don't have branch_id)
    default_branch = db.execute(text(
        "SELECT id FROM branches WHERE is_default = TRUE AND is_active = TRUE LIMIT 1"
    )).fetchone()
    _branch_id = default_branch.id if default_branch else None
    
    if _branch_id:
        tax_info = resolve_line_tax(_branch_id, None, db, billing_start, customer_id=enrollment.customer_id)
        _tax_rate_pct = tax_info["tax_rate"]
    else:
        _tax_rate_pct = Decimal("0")  # No branch = no tax
    
    _totals = compute_invoice_totals([
        {"quantity": 1, "unit_price": amount, "tax_rate": _tax_rate_pct, "discount": 0}
    ])
    tax_amount = _totals["total_tax"]
    total_with_tax = _totals["grand_total"]

    # Create the main invoice
    inv_row = db.execute(
        text(
            "INSERT INTO invoices "
            "(invoice_type, party_id, invoice_date, due_date, total, paid_amount, "
            " status, notes, created_by, updated_by) "
            "VALUES ('sales', :cid, :dt, :due, :amt, 0, 'pending', :notes, :usr, :usr) "
            "RETURNING id"
        ),
        {
            "cid": enrollment.customer_id,
            "dt": billing_start,
            "due": billing_end,
            "amt": str(total_with_tax),
            "notes": f"Subscription: {enrollment.plan_name} ({billing_start} - {billing_end})",
            "usr": user,
        },
    ).fetchone()
    invoice_id = inv_row[0]

    # Determine revenue account: deferred revenue for non-monthly prepaid, else revenue
    is_deferred = enrollment.billing_frequency != "monthly"

    # Fetch configured account IDs (use system defaults if not configured)
    ar_account = db.execute(text(
        "SELECT id FROM accounts WHERE account_type = 'receivable' AND is_active = true LIMIT 1"
    )).fetchone()
    revenue_account = db.execute(text(
        "SELECT id FROM accounts WHERE account_type = 'revenue' AND is_active = true LIMIT 1"
    )).fetchone()
    vat_account = db.execute(text(
        "SELECT id FROM accounts WHERE name ILIKE '%vat%payable%' OR name ILIKE '%ضريبة%' LIMIT 1"
    )).fetchone()
    deferred_account = db.execute(text(
        "SELECT id FROM accounts WHERE name ILIKE '%deferred%revenue%' OR name ILIKE '%إيراد%مؤجل%' LIMIT 1"
    )).fetchone()

    ar_account_id = ar_account.id if ar_account else None
    revenue_account_id = revenue_account.id if revenue_account else None
    vat_account_id = vat_account.id if vat_account else None
    deferred_account_id = deferred_account.id if deferred_account else None

    # Use deferred revenue account for non-monthly, fall back to regular revenue
    cr_revenue_account_id = deferred_account_id if (is_deferred and deferred_account_id) else revenue_account_id

    # Post GL journal entry
    je_id = None
    entry_number = None
    if ar_account_id and cr_revenue_account_id:
        je_lines = [
            {"account_id": ar_account_id, "debit": total_with_tax, "credit": _ZERO,
             "description": f"Subscription receivable: {enrollment.plan_name}"},
            {"account_id": cr_revenue_account_id, "debit": _ZERO, "credit": amount,
             "description": f"Subscription {'deferred ' if is_deferred else ''}revenue: {enrollment.plan_name}"},
        ]
        if vat_account_id and tax_amount > _ZERO:
            je_lines.append(
                {"account_id": vat_account_id, "debit": _ZERO, "credit": tax_amount,
                 "description": f"VAT on subscription: {enrollment.plan_name}"}
            )

        try:
            je_id, entry_number = create_journal_entry(
                db=db,
                company_id=company_id or "1",
                date=str(billing_start),
                description=f"اشتراك: {enrollment.plan_name} ({billing_start} - {billing_end})",
                lines=je_lines,
                user_id=int(user) if user else 1,
                branch_id=None,
                source="subscription",
                source_id=enrollment_id,
                currency=currency,
                idempotency_key=f"sub-{enrollment_id}-{billing_start}",
            )
        except Exception:
            logger.exception("Failed to post GL entry for subscription enrollment %d", enrollment_id)

    # Link via subscription_invoices (with new columns)
    si_row = db.execute(
        text(
            "INSERT INTO subscription_invoices "
            "(enrollment_id, invoice_id, billing_period_start, billing_period_end, "
            " amount, tax_rate, tax_amount, currency, journal_entry_id, "
            " is_prorated, created_by, updated_by) "
            "VALUES (:eid, :iid, :bps, :bpe, :amt, :tr, :ta, :cur, :jeid, "
            "        false, :usr, :usr) "
            "RETURNING id"
        ),
        {
            "eid": enrollment_id,
            "iid": invoice_id,
            "bps": billing_start,
            "bpe": billing_end,
            "amt": str(amount),
            "tr": str(_tax_rate_pct * Decimal("100")),
            "ta": str(tax_amount),
            "cur": currency,
            "jeid": je_id,
            "usr": user,
        },
    ).fetchone()

    # Create deferred revenue amortization schedule for non-monthly plans
    if is_deferred:
        _create_deferred_revenue_schedule(
            db,
            subscription_invoice_id=si_row[0],
            enrollment_id=enrollment_id,
            amount=amount,
            billing_start=billing_start,
            frequency=enrollment.billing_frequency,
            user=user,
        )

    # Advance next_billing_date
    new_next = billing_end + timedelta(days=1)
    db.execute(
        text(
            "UPDATE subscription_enrollments SET next_billing_date = :nbd, updated_at = NOW() "
            "WHERE id = :eid"
        ),
        {"nbd": new_next, "eid": enrollment_id},
    )

    db.commit()
    logger.info(
        "Generated invoice %d for enrollment %d (period %s - %s, amount %s, tax %s, je=%s)",
        invoice_id, enrollment_id, billing_start, billing_end, amount, tax_amount, je_id,
    )
    return {"invoice_id": invoice_id, "subscription_invoice_id": si_row[0], "journal_entry_id": je_id}


# ── Proration ──

def prorate_plan_change(db, *, enrollment_id: int, new_plan_id: int, user: str | None = None) -> dict:
    """Change an enrollment's plan with proration.

    Credits unused portion of old plan, charges prorated amount of new plan.
    Returns dict with credit_amount, charge_amount, net_amount, new_invoice_id.
    """
    enrollment = db.execute(
        text(
            "SELECT e.*, p.base_amount AS old_amount, p.billing_frequency AS old_freq, p.name AS old_plan_name "
            "FROM subscription_enrollments e "
            "JOIN subscription_plans p ON p.id = e.plan_id "
            "WHERE e.id = :eid AND e.is_deleted = false "
            "FOR UPDATE OF e"
        ),
        {"eid": enrollment_id},
    ).fetchone()
    if not enrollment:
        raise ValueError(f"Enrollment {enrollment_id} not found")
    if enrollment.status not in ("active", "trial"):
        raise ValueError(f"Cannot change plan in '{enrollment.status}' status")

    new_plan = db.execute(
        text("SELECT * FROM subscription_plans WHERE id = :pid AND is_deleted = false AND is_active = true"),
        {"pid": new_plan_id},
    ).fetchone()
    if not new_plan:
        raise ValueError(f"New plan {new_plan_id} not found or inactive")
    if enrollment.plan_id == new_plan_id:
        return {
            "credit_amount": str(_ZERO.quantize(_D4, rounding=ROUND_HALF_UP)),
            "charge_amount": str(_ZERO.quantize(_D4, rounding=ROUND_HALF_UP)),
            "net_amount": str(_ZERO.quantize(_D4, rounding=ROUND_HALF_UP)),
            "new_invoice_id": None,
            "duplicate": True,
        }

    today = date.today()
    old_amount = _dec(enrollment.old_amount)
    new_amount = _dec(new_plan.base_amount)

    # Calculate proration: how much of the current period is remaining
    period_end = _billing_period_end(enrollment.next_billing_date - timedelta(days=1), enrollment.old_freq)
    # next_billing_date was already advanced, so period start is the day after the previous period end
    # Actually, next_billing_date IS the start of the next period. Current period start = next_billing - period_length
    # Simpler: use days remaining / total days
    period_start = enrollment.start_date  # approximate
    # Better: compute from enrollment's last billing
    last_invoice = db.execute(
        text(
            "SELECT billing_period_start, billing_period_end FROM subscription_invoices "
            "WHERE enrollment_id = :eid AND is_deleted = false "
            "ORDER BY billing_period_end DESC LIMIT 1"
        ),
        {"eid": enrollment_id},
    ).fetchone()

    if last_invoice:
        period_start = last_invoice.billing_period_start
        period_end = last_invoice.billing_period_end
    else:
        period_start = enrollment.start_date
        period_end = _billing_period_end(period_start, enrollment.old_freq)

    total_days = (period_end - period_start).days + 1
    remaining_days = max((period_end - today).days + 1, 0)

    if total_days > 0 and remaining_days > 0:
        daily_old = old_amount / Decimal(str(total_days))
        credit = (daily_old * Decimal(str(remaining_days))).quantize(_D4, rounding=ROUND_HALF_UP)

        daily_new = new_amount / Decimal(str(total_days))
        charge = (daily_new * Decimal(str(remaining_days))).quantize(_D4, rounding=ROUND_HALF_UP)
    else:
        credit = _ZERO
        charge = _ZERO

    net = (charge - credit).quantize(_D4, rounding=ROUND_HALF_UP)

    # Create prorated invoice if net > 0
    invoice_id = None
    if net > _ZERO:
        inv_row = db.execute(
            text(
                "INSERT INTO invoices "
                "(invoice_type, party_id, invoice_date, due_date, total, paid_amount, "
                " status, notes, created_by, updated_by) "
                "VALUES ('sales', :cid, :dt, :due, :amt, 0, 'pending', :notes, :usr, :usr) "
                "RETURNING id"
            ),
            {
                "cid": enrollment.customer_id,
                "dt": today,
                "due": today + timedelta(days=30),
                "amt": str(net),
                "notes": f"Plan change proration: {enrollment.old_plan_name} -> {new_plan.name}",
                "usr": user,
            },
        ).fetchone()
        invoice_id = inv_row[0]

        db.execute(
            text(
                "INSERT INTO subscription_invoices "
                "(enrollment_id, invoice_id, billing_period_start, billing_period_end, "
                " is_prorated, proration_details, created_by, updated_by) "
                "VALUES (:eid, :iid, :bps, :bpe, true, :pd, :usr, :usr)"
            ),
            {
                "eid": enrollment_id,
                "iid": invoice_id,
                "bps": today,
                "bpe": period_end,
                "pd": json.dumps({
                    "credit": str(credit),
                    "charge": str(charge),
                    "net": str(net),
                    "old_plan_id": enrollment.plan_id,
                    "new_plan_id": new_plan_id,
                }),
                "usr": user,
            },
        )

    # Update enrollment to new plan
    db.execute(
        text(
            "UPDATE subscription_enrollments "
            "SET plan_id = :pid, updated_at = NOW(), updated_by = :usr "
            "WHERE id = :eid"
        ),
        {"pid": new_plan_id, "eid": enrollment_id, "usr": user},
    )
    db.commit()

    logger.info(
        "Plan change for enrollment %d: credit=%s, charge=%s, net=%s",
        enrollment_id, credit, charge, net,
    )
    return {
        "credit_amount": str(credit),
        "charge_amount": str(charge),
        "net_amount": str(net),
        "new_invoice_id": invoice_id,
    }


# ── Pause / Resume ──

def pause_enrollment(db, *, enrollment_id: int, user: str | None = None) -> None:
    """Pause an active subscription."""
    result = db.execute(
        text(
            "UPDATE subscription_enrollments SET status = 'paused', updated_at = NOW(), updated_by = :usr "
            "WHERE id = :eid AND status IN ('active', 'at_risk') AND is_deleted = false"
        ),
        {"eid": enrollment_id, "usr": user},
    )
    if result.rowcount == 0:
        raise ValueError(f"Enrollment {enrollment_id} not found or not in pauseable state")
    db.commit()
    logger.info("Paused enrollment %d", enrollment_id)


def resume_enrollment(db, *, enrollment_id: int, user: str | None = None) -> None:
    """Resume a paused subscription.

    Instead of resetting billing to today, checks the last paid invoice to determine
    whether the pre-paid period has remaining days. If it does, next_billing_date stays
    at the end of the pre-paid period. If the pre-paid period has already passed,
    next_billing_date is set to today so billing triggers immediately.
    """
    enrollment = db.execute(
        text(
            "SELECT * FROM subscription_enrollments "
            "WHERE id = :eid AND status = 'paused' AND is_deleted = false "
            "FOR UPDATE"
        ),
        {"eid": enrollment_id},
    ).fetchone()
    if not enrollment:
        raise ValueError(f"Enrollment {enrollment_id} not found or not paused")

    today = date.today()

    # Check last paid invoice to see if pre-paid period still covers today
    last_invoice = db.execute(
        text(
            "SELECT billing_period_end FROM subscription_invoices "
            "WHERE enrollment_id = :eid AND is_deleted = false "
            "ORDER BY billing_period_end DESC LIMIT 1"
        ),
        {"eid": enrollment_id},
    ).fetchone()

    if last_invoice and last_invoice.billing_period_end >= today:
        # Pre-paid period still active — bill after it ends
        next_bill = last_invoice.billing_period_end + timedelta(days=1)
    else:
        # Pre-paid period expired — bill immediately
        next_bill = today

    db.execute(
        text(
            "UPDATE subscription_enrollments "
            "SET status = 'active', next_billing_date = :nbd, "
            "    failed_payment_count = 0, updated_at = NOW(), updated_by = :usr "
            "WHERE id = :eid"
        ),
        {"nbd": next_bill, "eid": enrollment_id, "usr": user},
    )
    db.commit()
    logger.info("Resumed enrollment %d (next_billing=%s)", enrollment_id, next_bill)


# ── Cancellation ──

def cancel_enrollment(db, *, enrollment_id: int, reason: str | None = None, user: str | None = None) -> dict:
    """Cancel a subscription. Generates a final prorated invoice if applicable."""
    enrollment = db.execute(
        text(
            "SELECT e.*, p.base_amount, p.billing_frequency, p.name AS plan_name "
            "FROM subscription_enrollments e "
            "JOIN subscription_plans p ON p.id = e.plan_id "
            "WHERE e.id = :eid AND e.is_deleted = false "
            "FOR UPDATE OF e"
        ),
        {"eid": enrollment_id},
    ).fetchone()
    if not enrollment:
        raise ValueError(f"Enrollment {enrollment_id} not found")
    if enrollment.status == "cancelled":
        raise ValueError("Enrollment is already cancelled")

    db.execute(
        text(
            "UPDATE subscription_enrollments "
            "SET status = 'cancelled', cancelled_at = NOW(), cancellation_reason = :reason, "
            "    updated_at = NOW(), updated_by = :usr "
            "WHERE id = :eid"
        ),
        {"eid": enrollment_id, "reason": reason, "usr": user},
    )
    db.commit()

    logger.info("Cancelled enrollment %d (reason: %s)", enrollment_id, reason)
    return {"enrollment_id": enrollment_id, "status": "cancelled"}


# ── Failed Payment ──

def handle_failed_payment(db, *, enrollment_id: int, user: str | None = None) -> dict:
    """Increment failed payment counter. Mark at_risk after 3 failures."""
    enrollment = db.execute(
        text(
            "SELECT * FROM subscription_enrollments WHERE id = :eid AND is_deleted = false "
            "FOR UPDATE"
        ),
        {"eid": enrollment_id},
    ).fetchone()
    if not enrollment:
        raise ValueError(f"Enrollment {enrollment_id} not found")

    new_count = (enrollment.failed_payment_count or 0) + 1
    new_status = enrollment.status
    if new_count >= 3 and enrollment.status == "active":
        new_status = "at_risk"

    db.execute(
        text(
            "UPDATE subscription_enrollments "
            "SET failed_payment_count = :cnt, status = :st, updated_at = NOW(), updated_by = :usr "
            "WHERE id = :eid"
        ),
        {"cnt": new_count, "st": new_status, "eid": enrollment_id, "usr": user},
    )
    db.commit()

    logger.info(
        "Failed payment #%d for enrollment %d (status: %s)",
        new_count, enrollment_id, new_status,
    )
    return {"failed_count": new_count, "status": new_status}


# ── Trial Expiration ──

def check_trial_expirations(db, user: str = "system") -> int:
    """Convert expired trials to active status. Returns count of converted enrollments."""
    today = date.today()
    result = db.execute(
        text(
            "UPDATE subscription_enrollments "
            "SET status = 'active', updated_at = NOW(), updated_by = :usr "
            "WHERE status = 'trial' AND trial_end_date <= :today AND is_deleted = false"
        ),
        {"today": today, "usr": user},
    )
    count = result.rowcount
    if count > 0:
        db.commit()
        logger.info("Converted %d trial enrollments to active", count)
    return count


# ── Billing Due Check (for scheduler) ──

def check_billing_due(db, user: str = "system", company_id: str | None = None) -> list[dict]:
    """Find enrollments with billing due today or earlier and generate invoices.

    Returns list of generated invoice results.
    Processes each enrollment independently — a failure on one does not block others.
    """
    today = date.today()
    enrollments = db.execute(
        text(
            "SELECT id FROM subscription_enrollments "
            "WHERE next_billing_date <= :today "
            "  AND status IN ('active', 'at_risk') "
            "  AND is_deleted = false "
            "ORDER BY id"
        ),
        {"today": today},
    ).fetchall()

    results = []
    for row in enrollments:
        try:
            result = generate_subscription_invoice(
                db, enrollment_id=row.id, user=user, company_id=company_id
            )
            results.append(result)
        except Exception as e:
            logger.error("Failed to generate invoice for enrollment %d: %s", row.id, e)
            # Mark failed payment
            try:
                handle_failed_payment(db, enrollment_id=row.id, user=user)
            except Exception:
                logger.exception("Failed to handle payment failure for enrollment %d", row.id)
            # Continue to next enrollment — do not abort batch

    return results
