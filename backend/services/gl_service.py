import logging
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from datetime import datetime
from typing import List, Dict, Optional, Any
from decimal import Decimal, ROUND_HALF_UP

from utils.accounting import generate_sequential_number, update_account_balance
from utils.audit import log_activity

logger = logging.getLogger(__name__)
_D2 = Decimal("0.01")


def round_amount(value: Decimal | float | str, precision: int = 4) -> Decimal:
    """Round a monetary amount to the given decimal precision using ROUND_HALF_UP.

    Policy:
      - Amounts (SAR): NUMERIC(18,4) → 4 decimal places
      - FX rates: NUMERIC(18,6) → 6 decimal places
      - Intermediate calculations: full precision, round only at persistence boundary
    """
    d = Decimal(str(value))
    quantizer = Decimal(10) ** -precision
    return d.quantize(quantizer, rounding=ROUND_HALF_UP)


def round_fx_rate(value: Decimal | float | str) -> Decimal:
    """Round an FX rate to 6 decimal places (NUMERIC(18,6))."""
    return round_amount(value, precision=6)


def round_je_amount(value: Decimal | float | str) -> Decimal:
    """Round a JE line amount to 4 decimal places (NUMERIC(18,4))."""
    return round_amount(value, precision=4)


def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))


def validate_je_lines(lines: List[Dict[str, Any]]) -> tuple[Decimal, Decimal]:
    """
    Pure validation helper for journal-entry lines (TASK-032 testable surface).

    Enforces the four hard invariants required by double-entry bookkeeping:
      1. At least one line is present.
      2. No line has a negative debit or credit.
      3. No line has both debit and credit > 0.
    4. Totals are non-zero and balanced below 0.01 difference.

    Returns `(total_debit, total_credit)` — both quantized to 2 decimals.
    Raises HTTPException(400) on violation. Pure (no I/O).
    """
    if not lines:
        raise HTTPException(status_code=400, detail="يجب إضافة سطر واحد على الأقل في القيد")

    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for i, line in enumerate(lines):
        d = _dec(line.get("debit", 0)).quantize(_D2, ROUND_HALF_UP)
        c = _dec(line.get("credit", 0)).quantize(_D2, ROUND_HALF_UP)
        if d < 0 or c < 0:
            raise HTTPException(status_code=400, detail=f"السطر {i+1}: لا يمكن إدخال مبالغ سالبة")
        if d > 0 and c > 0:
            raise HTTPException(status_code=400, detail=f"السطر {i+1}: لا يمكن أن يكون مدين ودائن معاً في نفس السطر")
        total_debit += d
        total_credit += c

    if total_debit == 0 and total_credit == 0:
        raise HTTPException(status_code=400, detail="لا يمكن إنشاء قيد بمبالغ صفرية")

    if abs(total_debit - total_credit) >= _D2:
        raise HTTPException(status_code=400, detail="القيود غير موزونة (المدين لا يساوي الدائن)")

    return total_debit, total_credit


def validate_period(db, entry_date: str, status: str = "posted") -> None:
    """Uniform fiscal-period validation.

    Consults ``company_settings.fiscal.allow_drafts_in_closed_period``:
      - If ``false`` (default): both draft and posted entries are blocked in closed periods.
      - If ``true``: only posted entries are blocked; drafts are allowed.

    Raises HTTPException(400) on violation.
    """
    from utils.fiscal_lock import check_fiscal_period_open

    if status == "posted":
        check_fiscal_period_open(db, entry_date)
        return

    # Draft entry — check if drafts are allowed in closed periods
    try:
        row = db.execute(text(
            "SELECT setting_value FROM company_settings "
            "WHERE setting_key = 'fiscal.allow_drafts_in_closed_period'"
        )).fetchone()
        allow_drafts = row and row[0] and str(row[0]).lower() in ("true", "1", "yes")
    except Exception:
        allow_drafts = False

    if not allow_drafts:
        check_fiscal_period_open(db, entry_date)


def create_journal_entry(
    db,
    company_id: str,
    date: str,
    description: str,
    lines: List[Dict[str, Any]],
    user_id: int,
    branch_id: Optional[int] = None,
    reference: Optional[str] = None,
    status: str = "posted",
    currency: Optional[str] = None,
    exchange_rate: float = 1.0,
    source: str = "manual",
    source_id: Optional[int] = None,
    username: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    ledger_id: Optional[int] = None,
) -> tuple[int, str]:
    """
    Centralized function to create a journal entry, validate it, insert lines, 
    and update account balances if posted.
    
    lines format:
        [
            {
                "account_id": int,
                "debit": float,
                "credit": float,
                "description": str (optional),
                "cost_center_id": int (optional),
                "currency": str (optional),
                "amount_currency": float (optional)
            }
        ]
    """
    # 0. Normalize source to valid enum value
    from models.domain_models.je_source import JESource
    source = JESource.normalize(source) or "system"

    # 0b. Idempotency guard — if caller supplied a key, return existing JE
    if idempotency_key:
        existing = db.execute(text("""
            SELECT id, entry_number FROM journal_entries
            WHERE idempotency_key = :key
            LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if existing:
            logger.info("Idempotency hit: key=%s → JE %s", idempotency_key, existing[1])
            return existing[0], existing[1]

    # 1. Validation (TASK-032: extracted to validate_je_lines for property-testing)
    total_debit, total_credit = validate_je_lines(lines)

    # 1a. Configurable JE epsilon from company_settings
    try:
        epsilon_row = db.execute(text(
            "SELECT setting_value FROM company_settings WHERE setting_key = 'gl.je_epsilon'"
        )).fetchone()
        je_epsilon = Decimal(str(epsilon_row[0])) if epsilon_row and epsilon_row[0] else Decimal("0.005")
    except Exception:
        je_epsilon = Decimal("0.005")
    imbalance = abs(total_debit - total_credit)
    if imbalance > je_epsilon:
        from utils.i18n import http_error
        raise HTTPException(
            status_code=400,
            detail=http_error("je.epsilon_violation", imbalance=str(imbalance), epsilon=str(je_epsilon)),
        )

    if status not in ("draft", "posted"):
        status = "posted"

    # 1b. Source-level duplicate guard (prevents double-posting from same module action)
    if source and source != "manual" and source_id is not None:
        dup = db.execute(text("""
            SELECT id, entry_number FROM journal_entries
            WHERE source = :src AND source_id = :sid AND entry_date = :dt
            LIMIT 1
        """), {"src": source, "sid": source_id, "dt": date}).fetchone()
        if dup:
            logger.warning("Duplicate source posting blocked: source=%s source_id=%s date=%s → existing JE %s",
                           source, source_id, date, dup[1])
            return dup[0], dup[1]

    # 1c. Closed Period Check
    # T3.3 (audit #17): single source of truth via utils.fiscal_lock —
    # honours both fiscal_period_locks (admin lock) and fiscal_periods
    # (year-end close). Defense-in-depth: every router already calls
    # this guard, but gl_service enforces it again here as a backstop.
    # R2.3: consult company_settings.fiscal.allow_drafts_in_closed_period
    if date:
        validate_period(db, date, status)

    # 2. Header
    entry_number = generate_sequential_number(db, "JE", "journal_entries", "entry_number")

    # Multi-book: resolve ledger_id. If caller didn't specify, pick the tenant's
    # primary ledger (prefer local_gaap framework). Silent no-op if ledgers
    # table is absent (older tenants / pre-bootstrap).
    if ledger_id is None:
        try:
            active_count = db.execute(
                text("SELECT COUNT(*) FROM ledgers WHERE is_active = TRUE")
            ).scalar() or 0
            # Require explicit ledger when more than one active book exists.
            if active_count > 1:
                raise HTTPException(
                    status_code=400,
                    detail="ledger_id مطلوب عند تفعيل أكثر من دفتر محاسبي",
                )
            row_l = db.execute(text(
                "SELECT id FROM ledgers "
                "WHERE is_active = TRUE "
                "ORDER BY CASE framework WHEN 'local_gaap' THEN 0 WHEN 'ifrs' THEN 1 ELSE 2 END, id "
                "LIMIT 1"
            )).fetchone()
            if row_l:
                ledger_id = row_l[0]
        except HTTPException:
            raise
        except Exception:
            ledger_id = None  # ledgers table not provisioned yet — safe to omit
    
    # Get base currency
    if not currency:
        curr_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not curr_row:
            curr_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
        # T10.2 #123: default fallback aligned with COA seed (SAR), not SYP.
        currency = curr_row[0] if curr_row else "SAR"

    # Insert header
    try:
        res = db.execute(text("""
            INSERT INTO journal_entries 
            (entry_number, entry_date, description, reference, status, branch_id, created_by, currency, exchange_rate, posted_at, source, source_id, idempotency_key, ledger_id)
            VALUES 
            (:num, :date, :desc, :ref, :status, :branch_id, :user, :curr, :rate, :posted_at, :source, :s_id, :idem_key, :ledger_id)
            RETURNING id
        """), {
            "num": entry_number,
            "date": date,
            "desc": description,
            "ref": reference,
            "status": status,
            "branch_id": branch_id,
            "user": user_id,
            "curr": currency,
            "rate": _dec(exchange_rate).quantize(Decimal("0.000001"), ROUND_HALF_UP),
            "posted_at": datetime.now() if status == "posted" else None,
            "source": source,
            "s_id": source_id,
            "idem_key": idempotency_key,
            "ledger_id": ledger_id
        }).fetchone()
    except IntegrityError as e:
        # Race: a concurrent request landed the same idempotency_key or source triplet.
        db.rollback()
        if idempotency_key:
            row = db.execute(text(
                "SELECT id, entry_number FROM journal_entries WHERE idempotency_key = :k LIMIT 1"
            ), {"k": idempotency_key}).fetchone()
            if row:
                logger.info("Idempotency race resolved: key=%s → JE %s", idempotency_key, row[1])
                return row[0], row[1]
        if source and source != "manual" and source_id is not None:
            row = db.execute(text("""
                SELECT id, entry_number FROM journal_entries
                WHERE source = :s AND source_id = :sid AND entry_date = :d LIMIT 1
            """), {"s": source, "sid": source_id, "d": date}).fetchone()
            if row:
                logger.info("Source-duplicate race resolved: %s/%s → JE %s", source, source_id, row[1])
                return row[0], row[1]
        logger.exception("IntegrityError creating journal entry: %s", e)
        raise HTTPException(status_code=409, detail="تعذر إنشاء القيد — تعارض في البيانات")

    journal_id = res[0]

    # 3. Lines
    for line in lines:
        input_debit = _dec(line.get("debit", 0)).quantize(_D2, ROUND_HALF_UP)
        input_credit = _dec(line.get("credit", 0)).quantize(_D2, ROUND_HALF_UP)
        
        line_rate = _dec(line.get("exchange_rate", exchange_rate))
        if line_rate <= 0:
            raise HTTPException(status_code=400, detail="سعر الصرف يجب أن يكون أكبر من صفر")
        debit_base = (input_debit * line_rate).quantize(_D2, ROUND_HALF_UP)
        credit_base = (input_credit * line_rate).quantize(_D2, ROUND_HALF_UP)
        
        account_id = line["account_id"]
        line_currency = line.get("currency") or currency

        # Reject postings on header/group accounts. ``is_header`` may be missing
        # on legacy CoA rows — tolerate NULL.
        is_header = db.execute(
            text("SELECT COALESCE(is_header, FALSE) FROM accounts WHERE id = :id"),
            {"id": account_id},
        ).scalar()
        if is_header:
            raise HTTPException(
                status_code=400,
                detail=f"لا يمكن الترحيل على حساب إجمالي (header) رقم {account_id}",
            )
        
        if line.get("amount_currency"):
            line_amount_currency = _dec(line["amount_currency"]).quantize(_D2, ROUND_HALF_UP)
        else:
            line_amount_currency = (input_debit + input_credit).quantize(_D2, ROUND_HALF_UP)

        # txn_currency/txn_amount: preserve the *original* transaction currency
        # and amount when the booking-side functional currency differs from
        # the actual money currency (tri-currency journals). Defaults make
        # this transparent for legacy single-currency callers.
        line_txn_currency = (
            line.get("txn_currency")
            or line.get("transaction_currency")
            or line_currency
        )
        if line.get("txn_amount") is not None:
            line_txn_amount = _dec(line["txn_amount"]).quantize(_D2, ROUND_HALF_UP)
        elif line.get("transaction_amount") is not None:
            line_txn_amount = _dec(line["transaction_amount"]).quantize(_D2, ROUND_HALF_UP)
        else:
            line_txn_amount = line_amount_currency

        db.execute(text("""
            INSERT INTO journal_lines
            (journal_entry_id, account_id, debit, credit, description, cost_center_id,
             amount_currency, currency, txn_currency, txn_amount)
            VALUES
            (:jid, :aid, :deb, :cred, :desc, :cc_id,
             :amt_curr, :curr, :txn_curr, :txn_amt)
        """), {
            "jid": journal_id,
            "aid": account_id,
            "deb": debit_base,
            "cred": credit_base,
            "desc": line.get("description", description),
            "cc_id": line.get("cost_center_id") or None,
            "amt_curr": line_amount_currency,
            "curr": line_currency,
            "txn_curr": line_txn_currency,
            "txn_amt": line_txn_amount,
        })
        
        if status == "posted":
            update_account_balance(
                db, 
                account_id=account_id, 
                debit_base=debit_base, 
                credit_base=credit_base, 
                debit_curr=input_debit, 
                credit_curr=input_credit, 
                currency=line_currency
            )

    # Audit logging — internal to GL service for 100% coverage (FR-017)
    try:
        log_activity(
            db,
            user_id=user_id,
            username=username or "system",
            action="create_journal_entry",
            resource_type="journal_entry",
            resource_id=str(journal_id),
            details={"entry_number": entry_number, "source": source, "lines": len(lines), "status": status}
        )
    except Exception:
        logger.warning("Failed to log audit activity for JE %s", entry_number)

    # TASK-042: publish domain event(s). Handler failures are swallowed by the
    # bus — they cannot break the JE transaction.
    try:
        from utils.event_bus import publish, Events
        payload = {
            "journal_id": journal_id,
            "entry_number": entry_number,
            "source": source,
            "source_id": source_id,
            "status": status,
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "entry_date": str(date) if date else None,
            "company_id": company_id,
        }
        publish(Events.JOURNAL_ENTRY_POSTED, payload)
        # Fan out to domain-specific event based on `source` (TASK-042 completion).
        domain_event = _SOURCE_EVENT_MAP.get((source or "").lower())
        if domain_event:
            publish(domain_event, payload)
    except Exception:
        logger.debug("event_bus publish failed (non-fatal)")

    return journal_id, entry_number


# ────────────────────────────────────────────────────────────────────────
# T3.11: Post an existing *draft* JE (idempotent).
#
# Used by the unified expenses flow: on create the JE is inserted in
# `draft` so it shows up in GL without affecting balances; on approval
# we flip it to `posted` and apply the balances exactly once.
# ────────────────────────────────────────────────────────────────────────
def post_draft_journal_entry(db, je_id: int, user_id: int) -> bool:
    """Promote a draft journal entry to posted.

    Returns True if a state transition happened, False if the entry
    was already posted (idempotent). Raises HTTPException(404) if the
    JE doesn't exist.
    """
    row = db.execute(text(
        "SELECT id, status, entry_date, entry_number FROM journal_entries "
        "WHERE id = :id FOR UPDATE"
    ), {"id": je_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="القيد المحاسبي غير موجود")
    if row.status == "posted":
        return False
    if row.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"لا يمكن ترحيل قيد بحالة {row.status}",
        )
    # Re-check fiscal lock at posting time — the period might have
    # closed between draft creation and approval.
    if row.entry_date:
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, row.entry_date)

    db.execute(text(
        "UPDATE journal_entries "
        "SET status = 'posted', posted_at = :now "
        "WHERE id = :id"
    ), {"now": datetime.now(), "id": je_id})

    lines = db.execute(text(
        "SELECT account_id, debit, credit, currency, amount_currency "
        "FROM journal_lines WHERE journal_entry_id = :id"
    ), {"id": je_id}).fetchall()
    for ln in lines:
        deb = Decimal(str(ln.debit or 0))
        cred = Decimal(str(ln.credit or 0))
        amt_curr = Decimal(str(ln.amount_currency or 0))
        line_currency = ln.currency
        # Approximate per-currency split: when only one of debit/credit
        # is non-zero (true for every well-formed line), we can rebuild
        # the input figures. This mirrors the create-time call.
        input_debit = amt_curr if deb > 0 else Decimal("0")
        input_credit = amt_curr if cred > 0 else Decimal("0")
        update_account_balance(
            db,
            account_id=ln.account_id,
            debit_base=deb,
            credit_base=cred,
            debit_curr=input_debit,
            credit_curr=input_credit,
            currency=line_currency,
        )

    try:
        log_activity(
            db,
            user_id=user_id,
            username="system",
            action="post_journal_entry",
            resource_type="journal_entry",
            resource_id=str(je_id),
            details={"entry_number": row.entry_number},
        )
    except Exception:
        logger.warning("audit log failed for posting JE %s", je_id)
    return True


def reverse_journal_entry(
    db,
    je_id: int,
    user_id: int,
    company_id: str,
    reversal_date: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[int, str]:
    """Create a reversing JE for an existing posted JE.

    The reversing entry swaps debits and credits of every line and is
    posted with `source='reversal'`, `source_id=<original je_id>`. The
    original entry is left untouched (audit-friendly), but its
    `reversed_by_je_id` column (if present) is updated.
    """
    head = db.execute(text(
        "SELECT id, status, source, entry_date, entry_number, branch_id, currency, exchange_rate "
        "FROM journal_entries WHERE id = :id FOR UPDATE"
    ), {"id": je_id}).fetchone()
    if not head:
        raise HTTPException(status_code=404, detail="القيد الأصلي غير موجود")
    if head.status == "reversed":
        raise HTTPException(status_code=400, detail="تم عكس هذا القيد مسبقاً")
    if head.status != "posted":
        raise HTTPException(
            status_code=400,
            detail="لا يمكن عكس قيد غير مرحَّل",
        )
    # Block reversing a reversal entry (prevents infinite chains)
    if (head.source or "").strip().lower() in ("reversal",):
        raise HTTPException(status_code=400, detail="لا يمكن عكس قيد عكسي")
    # Guard: block if a reversal JE already exists for this entry
    already = db.execute(text(
        "SELECT id FROM journal_entries WHERE source = 'reversal' AND source_id = :id LIMIT 1"
    ), {"id": je_id}).fetchone()
    if already:
        raise HTTPException(status_code=400, detail="يوجد قيد عكسي لهذا القيد مسبقاً")

    src_lines = db.execute(text(
        "SELECT account_id, debit, credit, description, cost_center_id, "
        "       amount_currency, currency "
        "FROM journal_lines WHERE journal_entry_id = :id"
    ), {"id": je_id}).fetchall()
    if not src_lines:
        raise HTTPException(status_code=400, detail="القيد لا يحوي سطوراً")

    rev_lines = []
    for ln in src_lines:
        rev_lines.append({
            "account_id": ln.account_id,
            "debit": Decimal(str(ln.credit or 0)),
            "credit": Decimal(str(ln.debit or 0)),
            "description": (ln.description or "") + " — عكس",
            "cost_center_id": ln.cost_center_id,
            "currency": ln.currency,
            "amount_currency": Decimal(str(ln.amount_currency or 0)),
        })

    rev_id, rev_num = create_journal_entry(
        db=db,
        company_id=company_id,
        date=reversal_date or str(datetime.now().date()),
        description=f"عكس القيد {head.entry_number}" + (f" — {reason}" if reason else ""),
        lines=rev_lines,
        user_id=user_id,
        branch_id=head.branch_id,
        reference=f"REV-{head.entry_number}",
        status="posted",
        currency=head.currency,
        exchange_rate=float(head.exchange_rate or 1),
        source="reversal",
        source_id=je_id,
    )

    # Mark the original entry as reversed so it cannot be reversed again
    db.execute(text(
        "UPDATE journal_entries SET status = 'reversed' WHERE id = :id"
    ), {"id": je_id})

    return rev_id, rev_num


_SOURCE_EVENT_MAP: Dict[str, str] = {}


def _init_source_event_map() -> None:
    """Populated lazily on first import of Events to avoid circular imports."""
    try:
        from utils.event_bus import Events as _Events
        _SOURCE_EVENT_MAP.update({
            # Sales
            "sales-invoice": _Events.SALES_INVOICE_POSTED,
            "sales_invoice": _Events.SALES_INVOICE_POSTED,
            "salesreturn": _Events.SALES_INVOICE_CANCELLED,
            "salescreditnote": _Events.SALES_INVOICE_CANCELLED,
            "customerreceipt": _Events.SALES_PAYMENT_RECEIVED,
            "customerpayment": _Events.SALES_PAYMENT_RECEIVED,
            # Purchases
            "purchase_invoice": _Events.PURCHASE_INVOICE_POSTED,
            "purchase_order_receipt": _Events.PURCHASE_INVOICE_POSTED,
            "payment_voucher": _Events.PURCHASE_PAYMENT_MADE,
            # Inventory movements (stock impact)
            "shipment_dispatch": _Events.INVENTORY_MOVEMENT_POSTED,
            "shipment_receive": _Events.INVENTORY_MOVEMENT_POSTED,
            "deliveryorder": _Events.INVENTORY_MOVEMENT_POSTED,
            "landed_cost": _Events.INVENTORY_MOVEMENT_POSTED,
            # HR
            "payroll": _Events.PAYROLL_RUN_POSTED,
            "eos_settlement": _Events.PAYROLL_RUN_POSTED,
        })
    except Exception:
        logger.debug("Unable to initialise source→event map")


_init_source_event_map()
