"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging

from utils.cache import invalidate_aggregates
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from utils.decimal_helper import dec as _dec, D2 as _D2, D4 as _D4
from utils.tax_precision import money_str, rate_str, require_idempotency_key
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.treasury_balance import recalc_treasury_from_gl
from services.tax_engine import get_active_tax_for_branch, resolve_line_tax_group
from schemas.purchases import (
    SupplierPaymentCreate, SupplierPaymentPreviewRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _idempotent_invoice_replay(db, idempotency_key: str, invoice_type: str):
    row = db.execute(text("""
        SELECT id, invoice_number
        FROM invoices
        WHERE idempotency_key = :key
          AND invoice_type = :invoice_type
        LIMIT 1
    """), {"key": idempotency_key, "invoice_type": invoice_type}).fetchone()
    if not row:
        return None
    return {
        "success": True,
        "id": row.id,
        "invoice_number": row.invoice_number,
        "idempotent_replay": True,
    }


def _resolve_note_line_tax(db, branch_id: int, product_id, document_date, party_id: int):
    if product_id:
        taxes = resolve_line_tax_group(branch_id, product_id, db, document_date, customer_id=party_id)
        tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
        tax_rate_id = taxes[0]["tax_rate_id"] if len(taxes) == 1 else None
        return tax_rate_id, tax_rate
    info = get_active_tax_for_branch(branch_id, db, document_date)
    return info.get("id"), _dec(info.get("rate", 0))


def _purchase_payment_invoice_types(voucher_type: str) -> tuple[str, ...]:
    return (
        ('purchase_return', 'purchase_credit_note')
        if voucher_type == 'refund'
        else ('purchase', 'purchase_debit_note')
    )


def _fetch_supplier_open_invoices(db, supplier_id: int, branch_id: int, voucher_type: str):
    return db.execute(text("""
        SELECT id, invoice_number, invoice_date, total, COALESCE(paid_amount, 0) AS paid_amount,
               status, invoice_type, currency, COALESCE(exchange_rate, 1) AS exchange_rate,
               (total - COALESCE(paid_amount, 0)) AS remaining_balance
        FROM invoices
        WHERE party_id = :sid
          AND branch_id = :branch_id
          AND invoice_type = ANY(:types)
          AND status IN ('unpaid', 'partial', 'posted')
          AND COALESCE(total, 0) > COALESCE(paid_amount, 0)
        ORDER BY invoice_date ASC, id ASC
    """), {
        "sid": supplier_id,
        "branch_id": branch_id,
        "types": list(_purchase_payment_invoice_types(voucher_type)),
    }).fetchall()


def _allocation_preview_rows(invoice_rows, allocations, voucher_rate: Decimal):
    invoice_by_id = {int(row.id): row for row in invoice_rows}
    rows = []
    total_allocated = Decimal("0")

    for alloc in allocations:
        invoice_id = int(alloc["invoice_id"])
        invoice = invoice_by_id.get(invoice_id)
        if not invoice:
            continue
        allocated_amount = _dec(alloc["allocated_amount"]).quantize(_D4, ROUND_HALF_UP)
        if allocated_amount <= 0:
            continue
        inv_rate = _dec(invoice.exchange_rate or 1)
        invoice_currency_amount = (allocated_amount * (voucher_rate / inv_rate)).quantize(_D4, ROUND_HALF_UP)
        remaining = _dec(invoice.remaining_balance or 0).quantize(_D4, ROUND_HALF_UP)
        total_allocated = (total_allocated + allocated_amount).quantize(_D4, ROUND_HALF_UP)
        rows.append({
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "invoice_currency": invoice.currency,
            "invoice_exchange_rate": rate_str(inv_rate),
            "remaining_balance": money_str(remaining),
            "allocated_amount": money_str(allocated_amount),
            "invoice_currency_amount": money_str(invoice_currency_amount),
            "exceeds_remaining": invoice_currency_amount > (remaining + _D2),
        })
    return rows, total_allocated


@router.post(
    "/payments/preview",
    dependencies=[
        Depends(require_permission("buying.view")),
        Depends(require_permission("treasury.view")),
    ],
    response_model=Dict[str, Any],
)
def preview_supplier_payment(request: Request, data: SupplierPaymentPreviewRequest, current_user: dict = Depends(get_current_user)):
    """Preview supplier payment allocation/FX without changing state."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        base_currency = get_base_currency(db)
        voucher_type = data.voucher_type or "payment"
        voucher_rate = _dec(data.exchange_rate or 1)
        if voucher_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
        validated_branch_id = validate_branch_access(current_user, data.branch_id, request)
        if validated_branch_id is None:
            raise HTTPException(**http_error(400, "branch_required", request))

        if not data.supplier_id:
            amount = _dec(data.amount or 0).quantize(_D4, ROUND_HALF_UP)
            return {
                "amount": money_str(amount),
                "currency": data.currency or base_currency,
                "exchange_rate": rate_str(voucher_rate),
                "allocations": [],
                "lines": [],
                "total_allocated": money_str(0),
                "unallocated_amount": money_str(amount),
                "over_allocated": False,
                "amount_is_positive": amount > Decimal("0"),
                "has_unallocated_amount": amount > _D2,
                "has_allocations": False,
                "has_open_invoices": False,
                "can_auto_allocate": False,
                "treasury_amount": None,
                "treasury_currency": None,
                "transaction_rate": None,
            }

        supplier_exists = db.execute(text("""
            SELECT 1
            FROM parties
            WHERE id = :sid AND (is_supplier = TRUE OR party_type = 'supplier')
        """), {"sid": data.supplier_id}).fetchone()
        if not supplier_exists:
            raise HTTPException(**http_error(404, "supplier_not_found", request))

        invoice_rows = _fetch_supplier_open_invoices(db, data.supplier_id, validated_branch_id, voucher_type)
        amount = _dec(data.amount or 0).quantize(_D4, ROUND_HALF_UP)
        requested_allocations = [
            {"invoice_id": int(a.invoice_id), "allocated_amount": _dec(a.allocated_amount)}
            for a in data.allocations
            if _dec(a.allocated_amount) > 0
        ]

        if data.pay_all:
            requested_allocations = []
            for inv in invoice_rows:
                inv_rate = _dec(inv.exchange_rate or 1)
                remaining_in_voucher = (_dec(inv.remaining_balance or 0) * (inv_rate / voucher_rate)).quantize(_D4, ROUND_HALF_UP)
                if remaining_in_voucher > 0:
                    requested_allocations.append({"invoice_id": int(inv.id), "allocated_amount": remaining_in_voucher})
            amount = sum((_dec(a["allocated_amount"]) for a in requested_allocations), Decimal("0")).quantize(_D4, ROUND_HALF_UP)
        elif data.fill_invoice_id:
            invoice = next((inv for inv in invoice_rows if int(inv.id) == int(data.fill_invoice_id)), None)
            if invoice:
                inv_rate = _dec(invoice.exchange_rate or 1)
                amount_in_voucher = (_dec(invoice.remaining_balance or 0) * (inv_rate / voucher_rate)).quantize(_D4, ROUND_HALF_UP)
                requested_allocations = [a for a in requested_allocations if int(a["invoice_id"]) != int(data.fill_invoice_id)]
                if amount_in_voucher > 0:
                    requested_allocations.append({"invoice_id": int(invoice.id), "allocated_amount": amount_in_voucher})
        elif data.auto_allocate and amount > 0:
            requested_allocations = []
            remaining_voucher = amount
            for inv in invoice_rows:
                if remaining_voucher <= 0:
                    break
                inv_rate = _dec(inv.exchange_rate or 1)
                remaining_in_voucher = (_dec(inv.remaining_balance or 0) * (inv_rate / voucher_rate)).quantize(_D4, ROUND_HALF_UP)
                allocation = min(remaining_voucher, remaining_in_voucher).quantize(_D4, ROUND_HALF_UP)
                if allocation > 0:
                    requested_allocations.append({"invoice_id": int(inv.id), "allocated_amount": allocation})
                    remaining_voucher = (remaining_voucher - allocation).quantize(_D4, ROUND_HALF_UP)

        rows, total_allocated = _allocation_preview_rows(invoice_rows, requested_allocations, voucher_rate)
        if amount <= 0 and total_allocated > 0:
            amount = total_allocated
        unallocated = (amount - total_allocated).quantize(_D4, ROUND_HALF_UP)

        selected_treasury_id = data.treasury_account_id or data.bank_account_id
        treasury_amount = None
        treasury_currency = None
        transaction_rate = None
        if selected_treasury_id:
            treasury = validate_treasury_account_access(
                db, current_user, selected_treasury_id, validated_branch_id
            )
            treasury_currency = treasury["currency"] or (data.currency or base_currency)
            treasury_rate = Decimal("1")
            if treasury_currency != base_currency:
                row = db.execute(text("""
                    SELECT current_rate
                    FROM currencies
                    WHERE code = :code
                    LIMIT 1
                """), {"code": treasury_currency}).fetchone()
                if row:
                    treasury_rate = _dec(row.current_rate or 1)
            if data.transaction_rate and _dec(data.transaction_rate) > 0:
                transaction_rate = _dec(data.transaction_rate)
            else:
                transaction_rate = (voucher_rate / treasury_rate).quantize(_D4, ROUND_HALF_UP)
            treasury_amount = (amount * transaction_rate).quantize(_D4, ROUND_HALF_UP)

        return {
            "amount": money_str(amount),
            "currency": data.currency or base_currency,
            "exchange_rate": rate_str(voucher_rate),
            "allocations": [
                {"invoice_id": row["invoice_id"], "allocated_amount": row["allocated_amount"]}
                for row in rows
            ],
            "lines": rows,
            "total_allocated": money_str(total_allocated),
            "unallocated_amount": money_str(unallocated),
            "over_allocated": total_allocated > (amount + _D2) or any(row["exceeds_remaining"] for row in rows),
            "amount_is_positive": amount > Decimal("0"),
            "has_unallocated_amount": unallocated > _D2,
            "has_allocations": bool(rows),
            "has_open_invoices": bool(invoice_rows),
            "can_auto_allocate": amount > Decimal("0") and bool(invoice_rows),
            "treasury_amount": money_str(treasury_amount) if treasury_amount is not None else None,
            "treasury_currency": treasury_currency,
            "transaction_rate": rate_str(transaction_rate) if transaction_rate is not None else None,
        }


@router.post(
    "/payments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("buying.create")),
        Depends(require_permission("treasury.create")),
    ],
    response_model=Dict[str, Any],
)
def create_supplier_payment(request: Request, data: SupplierPaymentCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء سند صرف/قبض لمورد"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else current_user.username
    with transactional(company_id) as db:
        try:
            from utils.accounting import generate_sequential_number, get_base_currency
            base_currency = get_base_currency(db)
            idempotency_key = require_idempotency_key(request, operation="supplier payment")
            existing_voucher = db.execute(text("""
                SELECT id, voucher_number
                FROM payment_vouchers
                WHERE idempotency_key = :key
                LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing_voucher:
                return {
                    "id": existing_voucher.id,
                    "voucher_number": existing_voucher.voucher_number,
                    "idempotent_replay": True,
                    "message": i18n_message("payment_saved_success", request),
                }
            # Validate amount
            if data.amount is None or _dec(data.amount) <= 0:
                raise HTTPException(**http_error(400, "amount_must_be_positive"))
    
            # Fiscal-period lock: payment voucher posts at voucher_date.
            check_fiscal_period_open(db, data.voucher_date)

            voucher_rate = _dec(data.exchange_rate or 1)
            if voucher_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            validated_branch_id = validate_branch_access(current_user, data.branch_id, request)
            if validated_branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
            
            # T028: Lock individual balance rows first, then aggregate in Python.
            balance_rows = db.execute(text("""
                SELECT
                    psb.balance,
                    COALESCE(c.current_rate, 1) AS current_rate
                FROM party_site_balances psb
                JOIN party_sites ps ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON c.code = psb.currency
                WHERE ps.party_id = :sid
                  AND psb.account_type = 'payable'
                  AND psb.company_branch_id = :branch_id
                FOR UPDATE OF psb
            """), {"sid": data.supplier_id, "branch_id": validated_branch_id}).fetchall()
            if not balance_rows:
                supplier_exists = db.execute(text("""
                    SELECT 1 FROM parties
                    WHERE id = :sid AND (is_supplier = TRUE OR party_type = 'supplier')
                """), {"sid": data.supplier_id}).fetchone()
                if not supplier_exists:
                    raise HTTPException(**http_error(404, "supplier_not_found"))
            supplier_balance_base = sum(
                ((_dec(r.balance) * _dec(r.current_rate or 1)).quantize(_D2, ROUND_HALF_UP) for r in balance_rows),
                Decimal("0"),
            )
            
            # For payments (not refunds), warn if paying more than owed
            selected_treasury_id = data.treasury_account_id or data.bank_account_id
            selected_treasury = None
            if selected_treasury_id:
                selected_treasury = validate_treasury_account_access(
                    db, current_user, selected_treasury_id, validated_branch_id
                )
            amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
            if data.voucher_type != 'refund' and amount_base > (supplier_balance_base + _D2):
                allow_overpayment = db.execute(text("""
                    SELECT LOWER(COALESCE(setting_value, 'false'))
                    FROM company_settings
                    WHERE setting_key = 'buying.allow_overpayment'
                """)).scalar() in ("1", "true", "yes", "on")
                if not allow_overpayment:
                    raise HTTPException(**http_error(400, "supplier_overpayment_not_allowed", request))
                logger.warning(
                    "Supplier payment %s exceeds base balance %s for supplier %s",
                    data.amount,
                    supplier_balance_base,
                    data.supplier_id,
                )
            
            # Prefix based on type
            prefix = "PAY" if data.voucher_type != 'refund' else "RCT"
            voucher_num = generate_sequential_number(db, f"{prefix}-{date.today().year}", "payment_vouchers", "voucher_number")
            
            # 1. Insert Voucher Header
            result = db.execute(text("""
                INSERT INTO payment_vouchers (
                    voucher_number, voucher_type, voucher_date, party_type, party_id, 
                    amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                    reference, notes, status, created_by, branch_id, currency, exchange_rate, idempotency_key
                ) VALUES (
                    :vnum, :type, :vdate, 'supplier', :supp,
                    :amt, :method, :bank, :treasury, :check_num, :check_date,
                    :ref, :notes, 'posted', :user, :bid, :curr, :rate, :idempotency_key
                )
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id
            """), {
                "vnum": voucher_num, "type": data.voucher_type or 'payment', "vdate": data.voucher_date, "supp": data.supplier_id,
                "amt": data.amount, "method": data.payment_method, 
                "bank": data.bank_account_id if data.payment_method != 'cash' else None,
                "treasury": data.treasury_account_id or (data.bank_account_id if data.payment_method == 'cash' else None), 
                "check_num": data.check_number, "check_date": data.check_date,
                "ref": data.reference, "notes": data.notes, "user": user_id, "bid": validated_branch_id,
                "curr": data.currency or base_currency, "rate": voucher_rate,
                "idempotency_key": idempotency_key,
            }).fetchone()
            if not result:
                existing_voucher = db.execute(text("""
                    SELECT id, voucher_number
                    FROM payment_vouchers
                    WHERE idempotency_key = :key
                    LIMIT 1
                """), {"key": idempotency_key}).fetchone()
                if existing_voucher:
                    return {
                        "id": existing_voucher.id,
                        "voucher_number": existing_voucher.voucher_number,
                        "idempotent_replay": True,
                        "message": i18n_message("payment_saved_success", request),
                    }
                raise HTTPException(**http_error(409, "duplicate_idempotency_key", request))
            
            voucher_id = result[0]
            
            # 2. Process Allocations
            total_allocated = Decimal('0')
            for alloc in data.allocations:
                if alloc.allocated_amount is None or alloc.allocated_amount <= 0:
                    raise HTTPException(**http_error(400, "allocation_must_be_positive", request))
    
                inv_row = db.execute(text("""
                    SELECT id, party_id, invoice_type, total, COALESCE(paid_amount, 0) AS paid_amount,
                           currency, exchange_rate, branch_id
                    FROM invoices
                    WHERE id = :id
                    FOR UPDATE
                """), {"id": alloc.invoice_id}).fetchone()
                if not inv_row:
                    raise HTTPException(status_code=404, detail=i18n_message("allocation_invoice_not_found", request))
                if int(inv_row.party_id) != int(data.supplier_id):
                    raise HTTPException(status_code=400, detail=i18n_message("allocation_invoice_supplier_mismatch", request))
                # T029: Allow refund allocations to purchase returns and credit notes
                valid_types = ('purchase', 'purchase_debit_note') if data.voucher_type != 'refund' else ('purchase_return', 'purchase_credit_note')
                if inv_row.invoice_type not in valid_types:
                    raise HTTPException(status_code=400, detail=i18n_message("allocation_only_purchase_invoices_type", request))
                if inv_row.branch_id is None or int(inv_row.branch_id) != int(validated_branch_id):
                    raise HTTPException(**http_error(403, "access_denied", request))
    
                alloc_amount = _dec(alloc.allocated_amount)
                total_allocated = (total_allocated + alloc_amount).quantize(_D4, ROUND_HALF_UP)
    
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                """), {"vid": voucher_id, "iid": alloc.invoice_id, "amt": alloc_amount})
                
                inv_curr = inv_row.currency or base_currency
                inv_rate = _dec(inv_row.exchange_rate or 1)
                if inv_rate <= 0:
                    raise HTTPException(status_code=400, detail=i18n_message("allocation_invoice_rate_invalid", request))
    
                # if voucher is SYP (rate 1) and invoice is USD (rate 3.75)
                # allocated 375 SYP -> debt reduction = 375 / 3.75 = 100 USD
                reduction = (alloc_amount * (voucher_rate / inv_rate)).quantize(_D4, ROUND_HALF_UP)
    
                remaining = (_dec(inv_row.total or 0) - _dec(inv_row.paid_amount or 0)).quantize(_D4, ROUND_HALF_UP)
                if reduction > remaining + _D2:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"قيمة التخصيص للفواتير تتجاوز المتبقي في الفاتورة {alloc.invoice_id}. "
                            f"المتبقي: {remaining}, المطلوب تخصيصه: {reduction}"
                        )
                    )
    
                db.execute(text("""
                    UPDATE invoices
                    SET paid_amount = LEAST(total, COALESCE(paid_amount, 0) + :amt),
                        status = CASE
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) >= total - 0.01 THEN 'paid'
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) > 0.01 THEN 'partial'
                            ELSE status
                        END
                    WHERE id = :iid
                """), {"amt": reduction, "iid": alloc.invoice_id})
    
            if total_allocated > (_dec(data.amount) + _D2):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"إجمالي التخصيصات ({total_allocated}) أكبر من مبلغ السند ({data.amount})."
                    )
                )
            
            # 3. Update Supplier Balance via party_site_balances
            amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
            balance_change_fc = _dec(data.amount) if data.voucher_type != 'refund' else -_dec(data.amount)
            update_party_site_balance(
                db,
                party_id=data.supplier_id,
                branch_id=validated_branch_id or data.branch_id,
                currency=data.currency or base_currency,
                amount=balance_change_fc,
                document_type="supplier_payment" if data.voucher_type != 'refund' else "supplier_refund",
            )
            
            # 4. Create GL Entry
            # Dynamic Treasury Lookup
            treasury_id = selected_treasury_id
            cash_acc = None
            voucher_currency = data.currency or base_currency
            treasury_curr = voucher_currency
            treasury_rate = voucher_rate
            amount_treasury_curr = _dec(data.amount)
            
            if treasury_id:
                # Fetch treasury account details
                treasury = selected_treasury
                if treasury:
                    cash_acc = treasury["gl_account_id"]
                    treasury_curr = treasury["currency"] or voucher_currency
                    
                    # Fetch current rate for treasury currency
                    treasury_rate = Decimal('1')
                    if treasury_curr != base_currency:
                         # Try to get rate from currencies table
                         curr_data = db.execute(text("SELECT current_rate FROM currencies WHERE code = :code"), {"code": treasury_curr}).fetchone()
                         if curr_data:
                             treasury_rate = _dec(curr_data.current_rate or 1)
                    
                    # Calculate amount in treasury's currency
                    if data.transaction_rate and data.transaction_rate > 0:
                        amount_treasury_curr = (_dec(data.amount) * _dec(data.transaction_rate)).quantize(_D4, ROUND_HALF_UP)
                    else:
                        amount_treasury_curr = (_dec(data.amount) * (voucher_rate / treasury_rate)).quantize(_D4, ROUND_HALF_UP)
                    
                    amount_base_cash = (amount_treasury_curr * treasury_rate).quantize(_D2, ROUND_HALF_UP)
                    
            # Fallback to legacy mappings if no treasury linked
            if not cash_acc:
                cash_acc = get_mapped_account_id(db, "acc_map_cash_main")
                if data.payment_method in ['bank', 'check']: 
                    cash_acc = get_mapped_account_id(db, "acc_map_bank")
    
            ap_acc = get_mapped_account_id(db, "acc_map_ap")
            # Ensure we have a base amount for the cash side (defaulting to voucher's base if not set)
            amount_base_cash = locals().get('amount_base_cash', amount_base)
    
            if ap_acc and cash_acc:
                je_lines = []
                if data.voucher_type == 'refund':
                    # Receipt: Debit Cash, Credit AP
                    je_lines.append({"account_id": cash_acc, "debit": amount_base_cash, "credit": 0, "description": "قبض", "amount_currency": amount_treasury_curr, "currency": treasury_curr})
                    je_lines.append({"account_id": ap_acc, "debit": 0, "credit": amount_base, "description": "من مورد", "amount_currency": data.amount, "currency": voucher_currency})
                else:
                    # Payment: Debit AP, Credit Cash
                    je_lines.append({"account_id": ap_acc, "debit": amount_base, "credit": 0, "description": "صرف", "amount_currency": data.amount, "currency": voucher_currency})
                    je_lines.append({"account_id": cash_acc, "debit": 0, "credit": amount_base_cash, "description": "من خزينة", "amount_currency": amount_treasury_curr, "currency": treasury_curr})
                
                # 5. Handle Exchange Difference to Balance the JE
                diff = (amount_base - amount_base_cash).quantize(_D2, ROUND_HALF_UP)
                if diff.copy_abs() > _D2:
                    fx_acc = get_mapped_account_id(db, "acc_map_fx_difference") or get_mapped_account_id(db, "acc_map_expense_other")
                    if fx_acc:
                        # Logic: If diff (AP-Cash) is +ve, we need More Credit (if Payment) or More Debit (if Refund)
                        je_diff = -diff if data.voucher_type != 'refund' else diff # Adjustment to Debit
                        if je_diff > 0:
                            je_lines.append({"account_id": fx_acc, "debit": abs(je_diff), "credit": 0, "description": "فرق سعر صرف"})
                        else:
                            je_lines.append({"account_id": fx_acc, "debit": 0, "credit": abs(je_diff), "description": "فرق سعر صرف"})
    
                gl_create_journal_entry(
                    db=db,
                    company_id=company_id,
                    date=str(data.voucher_date),
                    description=f"{'سند قبض من' if data.voucher_type=='refund' else 'سند صرف لـ'} مورد {voucher_num} ({voucher_currency})",
                    reference=voucher_num,
                    lines=je_lines,
                    user_id=user_id,
                    branch_id=validated_branch_id,
                    currency=voucher_currency,
                    exchange_rate=Decimal("1"),  # amounts already in base currency
                    source="payment_voucher",
                    source_id=voucher_id,
                    idempotency_key=idempotency_key,
                )

                if treasury_id:
                    recalc_treasury_from_gl(db, treasury_id)
    
            # T12 — scoped invalidation: supplier payment hits treasury + AP + reports.
            invalidate_aggregates(str(company_id),
                                  "treasury", "purchases", "reports",
                                  "dashboard")
            
    
            supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.supplier_id}).scalar()
            log_activity(
                db_conn=db,
                user_id=user_id,
                username=username,
                action="buying.supplier_payment.create",
                resource_type="payment_voucher",
                resource_id=str(voucher_id),
                details={"voucher_number": voucher_num, "amount": data.amount, "supplier_name": supp_name},
                request=request,
                branch_id=validated_branch_id
            )
    
            # Notify finance team
            try:
                db.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'supplier_payment', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                    AND u.id != :current_uid
                """), {
                    "title": i18n_message("notif_payment_made", request),
                    "message": i18n_message("payment_made_details", request),
                    "link": f"/buying/payments/{voucher_id}",
                    "current_uid": user_id
                })
            except Exception:
                logger.exception("Failed to create supplier payment notification")
    
            return {"id": voucher_id, "message": i18n_message("payment_saved_success", request)}
    
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error creating payment")
            raise HTTPException(**http_error(500, "error_creating_payment_voucher", request))
        
@router.get("/payments", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def list_supplier_payments(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """قائمة سندات الصرف"""
    with transactional(current_user.company_id) as db:
        try:
            branch_scope = resolve_branch_scope(current_user, branch_id)
    
            query_str = """
                SELECT pv.id, pv.voucher_number, pv.voucher_date, pv.amount, pv.currency,
                       pv.payment_method, pv.status, p.name as supplier_name
                FROM payment_vouchers pv
                JOIN parties p ON pv.party_id = p.id
                WHERE pv.voucher_type = 'payment' AND pv.party_type = 'supplier'
            """
            params = {}
            query_str += branch_scope_filter_from_scope(branch_scope, "pv.branch_id", params)
            
            query_str += " ORDER BY pv.created_at DESC"
            
            result = db.execute(text(query_str), params).fetchall()
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error listing payments: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/payments/{voucher_id}", response_model=dict, dependencies=[Depends(require_permission("buying.view"))])
def get_payment_details(request: Request, voucher_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل سند صرف"""
    with transactional(current_user.company_id) as db:
        try:
            header = db.execute(text("""
                SELECT pv.*, p.name as party_name, p.party_code
                FROM payment_vouchers pv
                JOIN parties p ON pv.party_id = p.id
                WHERE pv.id = :id AND pv.party_type = 'supplier' AND pv.voucher_type = 'payment'
            """), {"id": voucher_id}).fetchone()
            
            if not header:
                raise HTTPException(**http_error(404, "payment_not_found", request))
    
            from utils.permissions import validate_branch_access
            validate_branch_access(current_user, header._mapping.get("branch_id"))
    
            allocations = db.execute(text("""
                SELECT pa.*, i.invoice_number
                FROM payment_allocations pa
                JOIN invoices i ON pa.invoice_id = i.id
                WHERE pa.voucher_id = :id
            """), {"id": voucher_id}).fetchall()
            
            total_allocated = sum(
                (_dec(a._mapping.get("allocated_amount") or 0) for a in allocations),
                Decimal("0"),
            )

            return {
                **dict(header._mapping),
                "total_allocated": money_str(total_allocated),
                "allocations": [dict(a._mapping) for a in allocations]
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting payment: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/suppliers/{supplier_id}/outstanding-invoices", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_supplier_outstanding_invoices(
    supplier_id: int, 
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Fetch unpaid/partial purchase invoices for a supplier"""
    with transactional(current_user.company_id) as db:
        try:
            branch_scope = resolve_branch_scope(current_user, branch_id)
            query = """
                SELECT id, invoice_number, invoice_date, total, paid_amount, status, invoice_type,
                       currency, exchange_rate,
                       (total - COALESCE(paid_amount, 0)) as remaining_balance
                FROM invoices
                WHERE party_id = :sid
                  AND invoice_type IN ('purchase', 'purchase_return', 'purchase_credit_note', 'purchase_debit_note')
                  AND status IN ('unpaid', 'partial', 'posted')
            """
            params = {"sid": supplier_id}
            query += branch_scope_filter_from_scope(branch_scope, "branch_id", params)
            
            query += " ORDER BY invoice_date ASC"
            
            result = db.execute(text(query), params).fetchall()
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error fetching outstanding invoices: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.get("/invoices/{invoice_id}/payment-history", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_invoice_payment_history(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """سجل الدفعات لفاتورة شراء معينة"""
    with transactional(current_user.company_id) as db:
        try:
            inv = db.execute(text("""
                SELECT id, branch_id
                FROM invoices
                WHERE id = :invoice_id
                  AND invoice_type IN ('purchase', 'purchase_return', 'purchase_credit_note', 'purchase_debit_note')
            """), {"invoice_id": invoice_id}).fetchone()
            if not inv:
                raise HTTPException(**http_error(404, "purchase_invoice_not_found"))
            validate_branch_access(current_user, inv.branch_id)

            result = db.execute(text("""
                SELECT 
                    pv.id as voucher_id,
                    pv.voucher_number,
                    pv.voucher_date,
                    pv.payment_method,
                    pa.allocated_amount
                FROM payment_allocations pa
                JOIN payment_vouchers pv ON pa.voucher_id = pv.id
                WHERE pa.invoice_id = :invoice_id
                  AND pv.voucher_type = 'payment'
                ORDER BY pv.voucher_date DESC
            """), {"invoice_id": invoice_id}).fetchall()
            
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error getting payment history: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== INV-003: Purchase Credit Notes (إشعار دائن مشتريات) ====================
# Credit Note from Supplier: Reduces what we owe (e.g., supplier overcharged us, returns to supplier)
# GL: Debit AP (reduce payable), Credit Inventory/Expense + VAT Input

@router.get("/credit-notes", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def list_purchase_credit_notes(
    party_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """قائمة إشعارات دائنة (مشتريات)"""
    with transactional(current_user.company_id) as db:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        conditions = ["i.invoice_type = 'purchase_credit_note'"]
        params = {}
        if party_id:
            conditions.append("i.party_id = :party_id")
            params["party_id"] = party_id
        if status_filter:
            conditions.append("i.status = :status")
            params["status"] = status_filter
        if date_from:
            conditions.append("i.invoice_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("i.invoice_date <= :date_to")
            params["date_to"] = date_to
        if search:
            conditions.append("(i.invoice_number ILIKE :search OR i.notes ILIKE :search)")
            params["search"] = f"%{search}%"
        branch_condition = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, prefix="").strip()
        if branch_condition:
            conditions.append(branch_condition)

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa

        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa
            f"""
            SELECT i.*, p.name AS party_name,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE {where}
            ORDER BY i.invoice_date DESC, i.id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total, "page": page,
            "pages": (total + limit - 1) // limit,
        }
@router.get("/credit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_purchase_credit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار دائن مشتريات"""
    with transactional(current_user.company_id) as db:
        note = db.execute(text("""
            SELECT i.*, p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'purchase_credit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "credit_note_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, note._mapping.get("branch_id"))

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(line._mapping) for line in lines]
        return result
@router.post("/credit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_credit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار دائن مشتريات
    GL: Debit AP, Credit Purchases/Inventory + VAT Input
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else current_user.username
    with transactional(company_id) as db:
        try:
            idempotency_key = require_idempotency_key(request, operation="purchase credit note")
            replay = _idempotent_invoice_replay(db, idempotency_key, "purchase_credit_note")
            if replay:
                replay["message"] = i18n_message("credit_note_created_number", request)
                return replay

            party_id = data.get("party_id")
            related_invoice_id = data.get("related_invoice_id")
            lines = data.get("lines", [])
            if not lines:
                raise HTTPException(**http_error(400, "min_one_item_required"))
            if not party_id:
                raise HTTPException(**http_error(400, "supplier_required", request))
    
            inv_date = data.get("invoice_date", str(date.today()))
            base_currency = get_base_currency(db)
            currency = data.get("currency", base_currency)
            exchange_rate = _dec(data.get("exchange_rate", 1))
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            branch_id = validate_branch_access(current_user, data.get("branch_id"), request)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))

            orig = None
            if related_invoice_id:
                orig = db.execute(text("""
                    SELECT id, party_id, invoice_type, branch_id, total, COALESCE(paid_amount, 0) AS paid_amount
                    FROM invoices
                    WHERE id = :id
                    FOR UPDATE
                """), {"id": related_invoice_id}).fetchone()
                if not orig or orig.party_id != party_id:
                    raise HTTPException(**http_error(400, "linked_invoice_not_for_supplier", request))
                if orig.branch_id is None or int(orig.branch_id) != int(branch_id):
                    raise HTTPException(**http_error(403, "access_denied", request))
    
            subtotal = Decimal('0')
            tax_total = Decimal('0')
            discount_total = Decimal('0')
            computed_lines = []
    
            for line in lines:
                qty = _dec(line.get("quantity", 1))
                price = _dec(line.get("unit_price", 0))
                disc = _dec(line.get("discount", 0))
                product_id = line.get("product_id")
                tax_rate_id, tax_rate = _resolve_note_line_tax(db, branch_id, product_id, inv_date, party_id)
                line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
                subtotal += line_net
                tax_total += line_tax
                discount_total += disc
                computed_lines.append({
                    "product_id": product_id,
                    "description": line.get("description", ""),
                    "quantity": qty, "unit_price": price,
                    "tax_rate": tax_rate, "tax_rate_id": tax_rate_id,
                    "discount": disc, "total": line_total,
                })
    
            total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
            if orig:
                remaining = (_dec(orig.total or 0) - _dec(orig.paid_amount or 0)).quantize(_D2, ROUND_HALF_UP)
                if total > remaining + _D2:
                    raise HTTPException(**http_error(400, "credit_note_exceeds_remaining_invoice", request))
    
            inv_num = generate_sequential_number(db, "PCN", "invoices", "invoice_number", branch_id=branch_id)
            result = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date,
                    subtotal, tax_amount, discount, total, paid_amount, status,
                    notes, branch_id, related_invoice_id, currency, exchange_rate, created_by, idempotency_key
                ) VALUES (
                    :num, 'purchase_credit_note', :party, :date,
                    :sub, :tax, :disc, :total, 0, 'posted',
                    :notes, :branch, :rel, :curr, :rate, :user, :idempotency_key
                )
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id
            """), {
                "num": inv_num, "party": party_id, "date": inv_date,
                "sub": subtotal, "tax": tax_total, "disc": discount_total,
                "total": total, "notes": data.get("notes", ""),
                "branch": branch_id, "rel": related_invoice_id,
                "curr": currency, "rate": exchange_rate, "user": user_id,
                "idempotency_key": idempotency_key,
            }).fetchone()
            if not result:
                replay = _idempotent_invoice_replay(db, idempotency_key, "purchase_credit_note")
                if replay:
                    replay["message"] = i18n_message("credit_note_created_number", request)
                    return replay
                raise HTTPException(**http_error(409, "duplicate_idempotency_key", request))
            note_id = result[0]
    
            for cl in computed_lines:
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, discount, total)
                    VALUES (:inv, :prod, :desc, :qty, :price, :tax, :tax_id, :disc, :total)
                """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                       "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                       "tax_id": cl["tax_rate_id"],
                       "disc": cl["discount"], "total": cl["total"]})
    
            # GL: Debit AP, Credit Inventory + VAT
            acc_ap = get_mapped_account_id(db, "acc_map_ap")
            acc_inv = get_mapped_account_id(db, "acc_map_inventory")
            acc_vat = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not acc_ap or not acc_inv:
                raise HTTPException(**http_error(400, "ap_inventory_accounts_incomplete", request))
    
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, inv_date)
    
            gl_sub = (_dec(subtotal) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_tax = (_dec(tax_total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_total = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
    
            je_lines = []
            # Debit: AP (reduces payable)
            je_lines.append({"account_id": acc_ap, "debit": gl_total, "credit": 0,
                             "description": f"إشعار دائن مشتريات - تخفيض ذمم {inv_num}",
                             "amount_currency": total, "currency": currency})
            # Credit: Inventory/Purchases
            if gl_sub > 0:
                je_lines.append({"account_id": acc_inv, "debit": 0, "credit": gl_sub,
                                 "description": f"إشعار دائن مشتريات - تخفيض مخزون {inv_num}",
                                 "amount_currency": subtotal, "currency": currency})
            # Credit: VAT Input
            if gl_tax > 0 and acc_vat:
                je_lines.append({"account_id": acc_vat, "debit": 0, "credit": gl_tax,
                                 "description": f"إشعار دائن مشتريات - عكس ضريبة {inv_num}",
                                 "amount_currency": tax_total, "currency": currency})
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=company_id,
                date=str(inv_date),
                description=f"إشعار دائن مشتريات {inv_num}",
                reference=inv_num,
                lines=je_lines,
                user_id=user_id,
                branch_id=branch_id,
                currency=currency,
                exchange_rate=Decimal("1"),  # amounts already in base currency
                source="purchase_credit_note",
                source_id=note_id,
                idempotency_key=idempotency_key,
            )
    
            # Reduce related invoice balance
            if related_invoice_id:
                db.execute(text("""
                    UPDATE invoices SET paid_amount = LEAST(total, COALESCE(paid_amount, 0) + :amt),
                        status = CASE
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) >= total THEN 'paid'
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) > 0 THEN 'partial'
                            ELSE status
                        END
                    WHERE id = :id
                """), {"amt": total, "id": related_invoice_id})
    
            # Update supplier balance via party_site_balances (credit note REDUCES what we owe supplier)
            (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            update_party_site_balance(
                db,
                party_id=party_id,
                branch_id=branch_id,
                currency=currency,
                amount=total,
                document_type="purchase_credit_note",
            )
    
            log_activity(db, user_id=user_id, username=username,
                         action="buying.credit_note.create", resource_type="purchase_credit_note",
                         resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                         request=request, branch_id=branch_id)
    
            return {"success": True, "id": note_id, "invoice_number": inv_num,
                    "journal_entry_id": je_id, "message": i18n_message("credit_note_created_number", request)}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error creating purchase credit note")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== INV-004: Purchase Debit Notes (إشعار مدين مشتريات) ====================
# Debit Note to Supplier: Increases what we owe (e.g., undercharged, additional services)
# GL: Debit Inventory/Expense + VAT Input, Credit AP

@router.get("/debit-notes", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def list_purchase_debit_notes(
    party_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """قائمة إشعارات مدينة (مشتريات)"""
    with transactional(current_user.company_id) as db:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        conditions = ["i.invoice_type = 'purchase_debit_note'"]
        params = {}
        if party_id:
            conditions.append("i.party_id = :party_id")
            params["party_id"] = party_id
        if status_filter:
            conditions.append("i.status = :status")
            params["status"] = status_filter
        if date_from:
            conditions.append("i.invoice_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("i.invoice_date <= :date_to")
            params["date_to"] = date_to
        if search:
            conditions.append("(i.invoice_number ILIKE :search OR i.notes ILIKE :search)")
            params["search"] = f"%{search}%"
        branch_condition = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, prefix="").strip()
        if branch_condition:
            conditions.append(branch_condition)

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa
            f"""
            SELECT i.*, p.name AS party_name,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE {where}
            ORDER BY i.invoice_date DESC, i.id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total, "page": page,
            "pages": (total + limit - 1) // limit,
        }
@router.get("/debit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_purchase_debit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار مدين مشتريات"""
    with transactional(current_user.company_id) as db:
        note = db.execute(text("""
            SELECT i.*, p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'purchase_debit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "debit_note_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, note._mapping.get("branch_id"))

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(line._mapping) for line in lines]
        return result
@router.post("/debit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_debit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار مدين مشتريات
    GL: Debit Inventory/Expense + VAT Input, Credit AP
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else current_user.username
    with transactional(company_id) as db:
        try:
            idempotency_key = require_idempotency_key(request, operation="purchase debit note")
            replay = _idempotent_invoice_replay(db, idempotency_key, "purchase_debit_note")
            if replay:
                replay["message"] = i18n_message("debit_note_created_number", request)
                return replay

            party_id = data.get("party_id")
            related_invoice_id = data.get("related_invoice_id")
            lines = data.get("lines", [])
            if not lines:
                raise HTTPException(**http_error(400, "min_one_item_required"))
            if not party_id:
                raise HTTPException(**http_error(400, "supplier_required", request))
    
            inv_date = data.get("invoice_date", str(date.today()))
            base_currency = get_base_currency(db)
            currency = data.get("currency", base_currency)
            exchange_rate = _dec(data.get("exchange_rate", 1))
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            branch_id = validate_branch_access(current_user, data.get("branch_id"), request)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
            if related_invoice_id:
                orig = db.execute(text("""
                    SELECT id, party_id, branch_id
                    FROM invoices
                    WHERE id = :id
                    FOR UPDATE
                """), {"id": related_invoice_id}).fetchone()
                if not orig or int(orig.party_id) != int(party_id):
                    raise HTTPException(**http_error(400, "linked_invoice_not_for_supplier", request))
                if orig.branch_id is None or int(orig.branch_id) != int(branch_id):
                    raise HTTPException(**http_error(403, "access_denied", request))
    
            subtotal = Decimal('0')
            tax_total = Decimal('0')
            discount_total = Decimal('0')
            computed_lines = []
    
            for line in lines:
                qty = _dec(line.get("quantity", 1))
                price = _dec(line.get("unit_price", 0))
                disc = _dec(line.get("discount", 0))
                product_id = line.get("product_id")
                tax_rate_id, tax_rate = _resolve_note_line_tax(db, branch_id, product_id, inv_date, party_id)
                line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
                subtotal += line_net
                tax_total += line_tax
                discount_total += disc
                computed_lines.append({
                    "product_id": product_id,
                    "description": line.get("description", ""),
                    "quantity": qty, "unit_price": price,
                    "tax_rate": tax_rate, "tax_rate_id": tax_rate_id,
                    "discount": disc, "total": line_total,
                })
    
            total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
    
            inv_num = generate_sequential_number(db, "PDN", "invoices", "invoice_number", branch_id=branch_id)
            result = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date,
                    subtotal, tax_amount, discount, total, paid_amount, status,
                    notes, branch_id, related_invoice_id, currency, exchange_rate, created_by, idempotency_key
                ) VALUES (
                    :num, 'purchase_debit_note', :party, :date,
                    :sub, :tax, :disc, :total, 0, 'unpaid',
                    :notes, :branch, :rel, :curr, :rate, :user, :idempotency_key
                )
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id
            """), {
                "num": inv_num, "party": party_id, "date": inv_date,
                "sub": subtotal, "tax": tax_total, "disc": discount_total,
                "total": total, "notes": data.get("notes", ""),
                "branch": branch_id, "rel": related_invoice_id,
                "curr": currency, "rate": exchange_rate, "user": user_id,
                "idempotency_key": idempotency_key,
            }).fetchone()
            if not result:
                replay = _idempotent_invoice_replay(db, idempotency_key, "purchase_debit_note")
                if replay:
                    replay["message"] = i18n_message("debit_note_created_number", request)
                    return replay
                raise HTTPException(**http_error(409, "duplicate_idempotency_key", request))
            note_id = result[0]
    
            for cl in computed_lines:
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, discount, total)
                    VALUES (:inv, :prod, :desc, :qty, :price, :tax, :tax_id, :disc, :total)
                """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                       "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                       "tax_id": cl["tax_rate_id"],
                       "disc": cl["discount"], "total": cl["total"]})
    
            # GL: Debit Inventory + VAT, Credit AP
            acc_ap = get_mapped_account_id(db, "acc_map_ap")
            acc_inv = get_mapped_account_id(db, "acc_map_inventory")
            acc_vat = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not acc_ap or not acc_inv:
                raise HTTPException(**http_error(400, "ap_inventory_accounts_incomplete", request))
    
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, inv_date)
    
            gl_sub = (_dec(subtotal) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_tax = (_dec(tax_total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_total = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
    
            je_lines = []
            # Debit: Inventory/Expense
            if gl_sub > 0:
                je_lines.append({"account_id": acc_inv, "debit": gl_sub, "credit": 0,
                                 "description": f"إشعار مدين مشتريات - زيادة مخزون {inv_num}",
                                 "amount_currency": subtotal, "currency": currency})
            # Debit: VAT Input
            if gl_tax > 0 and acc_vat:
                je_lines.append({"account_id": acc_vat, "debit": gl_tax, "credit": 0,
                                 "description": f"إشعار مدين مشتريات - ضريبة إضافية {inv_num}",
                                 "amount_currency": tax_total, "currency": currency})
            # Credit: AP
            je_lines.append({"account_id": acc_ap, "debit": 0, "credit": gl_total,
                             "description": f"إشعار مدين مشتريات - زيادة ذمم {inv_num}",
                             "amount_currency": total, "currency": currency})
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=company_id,
                date=str(inv_date),
                description=f"إشعار مدين مشتريات {inv_num}",
                reference=inv_num,
                lines=je_lines,
                user_id=user_id,
                branch_id=branch_id,
                currency=currency,
                exchange_rate=Decimal("1"),  # amounts already in base currency
                source="purchase_debit_note",
                source_id=note_id,
                idempotency_key=idempotency_key,
            )
    
            # Update supplier balance via party_site_balances (debit note INCREASES what we owe supplier)
            (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            update_party_site_balance(
                db,
                party_id=party_id,
                branch_id=branch_id,
                currency=currency,
                amount=-total,
                document_type="purchase_debit_note",
            )
    
            log_activity(db, user_id=user_id, username=username,
                         action="buying.debit_note.create", resource_type="purchase_debit_note",
                         resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                         request=request, branch_id=branch_id)
    
            return {"success": True, "id": note_id, "invoice_number": inv_num,
                    "journal_entry_id": je_id, "message": i18n_message("debit_note_created_number", request)}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error creating purchase debit note")
            raise HTTPException(**http_error(500, "internal_error"))
# =====================================================
# 8.11 PURCHASES IMPROVEMENTS
# =====================================================

# ---------- PUR-001: Request for Quotations ----------
