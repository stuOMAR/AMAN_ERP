"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import logging

from utils.cache import invalidate_company_cache
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission, require_module, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from services.gl_service import create_journal_entry as gl_create_journal_entry
from services.tax_engine import resolve_line_tax
from schemas.purchases import (
    PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest,
    SupplierPaymentCreate,
)

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal("0")


router = APIRouter()
logger = logging.getLogger(__name__)


def _require_account_map(db, key: str, label_ar: str) -> int:
    """Return required mapped account id or raise a clear 400 if missing."""
    acc_id = get_mapped_account_id(db, key)
    if not acc_id:
        raise HTTPException(
            status_code=400,
            detail=f"لم يتم ضبط حساب {label_ar} في إعدادات ربط الحسابات ({key})"
        )
    return int(acc_id)


def _parties_has_balance_currency(db) -> bool:
    """Return True when tenant parties table has balance_currency column."""
    return bool(db.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'parties'
              AND column_name = 'balance_currency'
        )
    """)).scalar())


@router.post("/invoices/preview", dependencies=[Depends(require_permission("buying.create"))])
def preview_purchase_invoice_totals(invoice: PurchaseCreate, current_user: dict = Depends(get_current_user)):
    """حساب إجماليات فاتورة المشتريات بدون حفظ"""
    from utils.accounting import compute_invoice_totals, compute_line_amounts

    lines_data = [
        {"quantity": item.quantity, "unit_price": item.unit_price, "tax_rate": item.tax_rate, "discount": item.discount}
        for item in invoice.items
    ]
    totals = compute_invoice_totals(lines_data, invoice.effect_percentage or 0, invoice.markup_amount or 0, discount_is_percent=False)

    line_details = []
    for item in invoice.items:
        la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate, item.discount, discount_is_percent=False)
        line_details.append({
            "product_id": item.product_id,
            "description": item.description,
            "quantity": float(item.quantity),
            "unit_price": float(item.unit_price),
            "tax_rate": float(item.tax_rate),
            "discount": float(item.discount),
            "subtotal": float(la["subtotal"]),
            "discount_amount": float(la["discount_amount"]),
            "taxable": float(la["taxable"]),
            "tax_amount": float(la["tax_amount"]),
            "line_total": float(la["line_total"]),
        })

    paid = float(invoice.paid_amount or 0)
    grand = float(totals["grand_total"])

    return {
        "lines": line_details,
        "subtotal": float(totals["subtotal"]),
        "total_discount": float(totals["total_discount"]),
        "total_tax": float(totals["total_tax"]),
        "grand_total": grand,
        "paid_amount": paid,
        "remaining_balance": grand - paid,
        "currency": invoice.currency or "SAR",
    }


@router.get("/invoices", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_invoices(
    supplier_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض فواتير المشتريات"""
    from repositories import InvoiceRepository
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        repo = InvoiceRepository(db)
        base_currency = get_base_currency(db)
        rows = repo.list(
            invoice_type="purchase",
            party_id=supplier_id,
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
            limit=limit,
            offset=skip,
        )
        return [
            {
                "id": r["id"],
                "invoice_number": r["invoice_number"],
                "supplier_name": r["party_name"],
                "invoice_date": r["invoice_date"],
                "total": r["total"],
                "currency": r.get("currency") or base_currency,
                "exchange_rate": r.get("exchange_rate") or 1,
                "base_currency": base_currency,
                "total_base": float(_dec(r["total"]) * _dec(r.get("exchange_rate") or 1)),
                "status": r["status"],
            }
            for r in rows
        ]

# NOTE: Supplier CRUD endpoints consolidated in inventory/suppliers.py
# The frontend uses inventoryAPI for all supplier operations.
# Purchase-specific supplier helpers (outstanding invoices, transactions) remain below.

@router.get("/invoices/{id}", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchase_invoice(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل فاتورة مشتريات مع المنتجات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        # 1. Fetch Invoice Header
        invoice = db.execute(text("""
            SELECT i.*, p.name as supplier_name, p.party_code as supplier_code
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.id = :id AND i.invoice_type = 'purchase'
        """), {"id": id}).fetchone()
        
        if not invoice:
            raise HTTPException(**http_error(404, "invoice_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, invoice.branch_id)

        # Get base currency for fallback
        base_currency = get_base_currency(db)

        # 2. Fetch Invoice Lines
        lines = db.execute(text("""
            SELECT il.*, p.product_name, p.product_code 
            FROM invoice_lines il
            LEFT JOIN products p ON il.product_id = p.id
            WHERE il.invoice_id = :id
        """), {"id": id}).fetchall()

        # 2.5 Calculate Returned Quantities
        # Fetch sum of quantities from all Return Invoices linked to this Reference Invoice
        returned_stats = db.execute(text("""
            SELECT il.product_id, SUM(il.quantity) as returned_qty
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.related_invoice_id = :id 
              AND i.invoice_type = 'purchase_return' 
              AND i.status != 'void'
            GROUP BY il.product_id
        """), {"id": id}).fetchall()
        
        returned_map = {row.product_id: _dec(row.returned_qty or 0) for row in returned_stats}
        
        # 3. Construct Response
        return {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "supplier_id": invoice.party_id,
            "supplier_name": invoice.supplier_name,
            "status": invoice.status,
            "subtotal": invoice.subtotal,
            "tax_amount": invoice.tax_amount,
            "discount": invoice.discount,
            "total": invoice.total,
            "paid_amount": str(invoice.paid_amount or 0),
            "currency": invoice.currency or base_currency,
            "exchange_rate": str(invoice.exchange_rate or 1.0),
            "notes": invoice.notes,
            "items": [{
                "id": l.id,
                "product_id": l.product_id,
                "product_name": l.product_name or l.description,
                "description": l.description,
                "quantity": l.quantity,
                "unit_price": l.unit_price,
                "tax_rate": l.tax_rate,
                "discount": l.discount,
                "total": l.total,
                "returned_quantity": str(returned_map.get(l.product_id, Decimal('0'))),
                "remaining_quantity": str(max(Decimal('0'), _dec(l.quantity) - returned_map.get(l.product_id, Decimal('0'))))
            } for l in lines]
        }

@router.post("/invoices", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
async def create_purchase_invoice(
    invoice: PurchaseCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مشتريات (إضافة للمخزون + قيد محاسبي)"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            validated_branch_id = validate_branch_access(current_user, invoice.branch_id)
            selected_treasury = None
            if invoice.treasury_id:
                selected_treasury = validate_treasury_account_access(
                    db, current_user, invoice.treasury_id, validated_branch_id
                )

            # --- 0. Currency & Exchange Rate Logic ---
            # Get Company Base Currency
            base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
            if not base_currency_row:
                 base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
            
            base_currency = base_currency_row[0] if base_currency_row else "SAR"
    
            inv_currency = invoice.currency or base_currency
            exchange_rate = _dec(invoice.exchange_rate or 1)
    
            def conversion_rate_needed(rate_val):
                d_rate = _dec(rate_val)
                return rate_val is None or d_rate <= 0 or d_rate == Decimal('1')
    
            # If currency is different from base and no rate provided, fetch latest rate
            if inv_currency != base_currency and conversion_rate_needed(invoice.exchange_rate):
                 rate_row = db.execute(text("""
                    SELECT rate FROM exchange_rates 
                    WHERE currency_id = (SELECT id FROM currencies WHERE code = :code) 
                    AND rate_date <= :date 
                    ORDER BY rate_date DESC LIMIT 1
                 """), {"code": inv_currency, "date": invoice.invoice_date}).fetchone()
                 
                 if not rate_row:
                     raise HTTPException(status_code=400, detail=f"No exchange rate found for {inv_currency}")
                 exchange_rate = _dec(rate_row.rate)
    
            if inv_currency != base_currency and exchange_rate <= 0:
                raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero")
                 
            def to_base(amount):
                return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
            # 1. Generate Sequential Invoice Number
            from utils.accounting import generate_sequential_number
            inv_num = generate_sequential_number(db, f"PINV-{datetime.now().year}", "invoices", "invoice_number")
    
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, invoice.invoice_date)
    
            # 2. Preparation (Warehouse)
            wh_id = invoice.warehouse_id
            if not wh_id:
                 wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_default = TRUE")).scalar() or 1
    
            # 2.5 Validate Warehouse-Branch Association
            if wh_id and invoice.branch_id:
                wh_check = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": wh_id}).fetchone()
                if wh_check and wh_check[0] and wh_check[0] != invoice.branch_id:
                    raise HTTPException(status_code=400, detail="المستودع المختار لا يتبع للفرع الحالي")
    
            # 2.6 Check for linked PO and fetch received quantities
            po_received_map = {} # product_id -> received_qty
            if invoice.original_invoice_id:
                po_lines = db.execute(text("""
                    SELECT product_id, received_quantity 
                    FROM purchase_order_lines 
                    WHERE po_id = :po_id
                """), {"po_id": invoice.original_invoice_id}).fetchall()
                for pol in po_lines:
                    po_received_map[pol.product_id] = _dec(pol.received_quantity or 0)
    
                # QA-F1: block invoicing when a linked quality inspection has FAILED.
                try:
                    failed_insp = db.execute(text("""
                        SELECT COUNT(*) FROM quality_inspections
                        WHERE reference_type = 'purchase_order'
                          AND reference_id = :po_id
                          AND UPPER(COALESCE(status, '')) IN ('FAILED', 'REJECTED')
                    """), {"po_id": invoice.original_invoice_id}).scalar() or 0
                    if failed_insp > 0:
                        raise HTTPException(
                            status_code=409,
                            detail="لا يمكن إنشاء فاتورة شراء: يوجد فحص جودة فاشل على أمر الشراء"
                        )
                except HTTPException:
                    raise
                except Exception:
                    # quality_inspections table may not exist on some tenants; skip silently.
                    pass
    
            # 3. Calculate Totals (tax resolved via engine)
            from utils.accounting import compute_invoice_totals as _cit, compute_line_amounts as _cla
    
            lines_data = []
            _branch_id = validated_branch_id or invoice.branch_id
            _doc_date = invoice.invoice_date if hasattr(invoice, 'invoice_date') and invoice.invoice_date else None
            for item in invoice.items:
                tax_info = resolve_line_tax(_branch_id, item.product_id, db, _doc_date, customer_id=invoice.supplier_id)
                la = _cla(item.quantity, item.unit_price, tax_info["tax_rate"], item.discount)
                lines_data.append({
                    "product_id": item.product_id,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "tax_rate": tax_info["tax_rate"],
                    "tax_rate_id": tax_info["tax_rate_id"],
                    "discount": item.discount,
                    "markup": getattr(item, "markup", 0.0),
                    "total": la["line_total"],
                })
    
            header_discount_pct = (
                _dec(invoice.effect_percentage)
                if getattr(invoice, "effect_type", "discount") == "discount"
                else Decimal("0")
            )
            markup_amount = (
                _dec(invoice.markup_amount)
                if getattr(invoice, "effect_type", "discount") == "markup"
                else Decimal("0")
            )

            _totals = _cit([
                {
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "tax_rate": it["tax_rate"],
                    "discount": it["discount"],
                }
                for it in lines_data
            ], header_discount_pct=header_discount_pct, markup_amount=markup_amount)
            subtotal = _totals["subtotal"]
            total_tax = _totals["total_tax"]
            total_discount = _totals["total_discount"]
            grand_total = _totals["grand_total"]
            
            # 3. Handle Payment & Debt
            paid_amount = _dec(invoice.paid_amount)
            if invoice.payment_method in ["cash", "bank"] and paid_amount == 0:
                paid_amount = grand_total
                 
            remaining_balance = grand_total - paid_amount
            
            # Determine Status
            inv_status = "paid"
            if remaining_balance > _D2:
                inv_status = "partial" if paid_amount > 0 else "unpaid"
    
            # 4. Insert Invoice Header
            result = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date, due_date,
                    subtotal, tax_amount, discount, total, paid_amount, status, notes, 
                    down_payment_method, created_by, branch_id, warehouse_id,
                    currency, exchange_rate, effect_type, effect_percentage, markup_amount
                ) VALUES (
                    :num, 'purchase', :party_id, :date, :due,
                    :sub, :tax, :disc, :total, :paid, :status, :notes, 
                    :dp_method, :user, :branch, :wh,
                    :currency, :exchange_rate, :effect_type, :effect_perc, :markup_amt
                ) RETURNING id
            """), {
                "num": inv_num,
                "party_id": invoice.supplier_id,
                "date": invoice.invoice_date,
                "due": invoice.due_date,
                "sub": subtotal,
                "tax": total_tax,
                "disc": total_discount,
                "total": grand_total,
                "paid": paid_amount,
                "status": inv_status,
                "notes": invoice.notes,
                "dp_method": invoice.down_payment_method,
                "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                "branch": validated_branch_id or invoice.branch_id,
                "wh": wh_id,
                "currency": inv_currency,
                "exchange_rate": exchange_rate,
                "effect_type": invoice.effect_type,
                "effect_perc": invoice.effect_percentage,
                "markup_amt": invoice.markup_amount
            }).fetchone()
            
            invoice_id = result[0]

            # Update party_site_id if provided
            if invoice.party_site_id:
                db.execute(text("UPDATE invoices SET party_site_id = :sid WHERE id = :iid"),
                          {"sid": invoice.party_site_id, "iid": invoice_id})
            
            # 5. Insert Invoice Lines & Update Stock
            receipt_accrual_reversal_base = Decimal('0')
    
            for line in lines_data:
                # Calculate cost in base currency
                new_price_fc = _dec(line["unit_price"])
                new_price_bc = to_base(new_price_fc)
                
                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price, 
                        tax_rate, tax_rate_id, discount, markup, total, unit_cost
                    ) VALUES (
                        :inv_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :disc, :markup, :total, :unit_cost
                    )
                """), {
                    "inv_id": invoice_id,
                    "pid": line["product_id"],
                    "desc": line["description"],
                    "qty": line["quantity"],
                    "price": line["unit_price"],
                    "tax_rate": line["tax_rate"],
                    "tax_rate_id": line.get("tax_rate_id"),
                    "disc": line["discount"],
                    "markup": line.get("markup", 0.0),
                    "total": line["total"],
                    "unit_cost": new_price_bc
                })
                
                # Stock Update & WAC Calculation
                if line["product_id"] and not invoice.is_prepayment:
                    # 1. Update Cost using Strategy Pattern (Global, Warehouse, etc.)
                    from services.costing_service import CostingService
                    
                    # We need to pass the base currency price
                    new_price_fc = _dec(line["unit_price"])
                    new_price_bc = to_base(new_price_fc)
                    
                    CostingService.update_cost(
                        db, 
                        product_id=line["product_id"], 
                        warehouse_id=wh_id, 
                        new_qty=str(_dec(line["quantity"])), 
                        new_price=new_price_bc
                    )
    
                    # 2a. FIFO/LIFO: Create cost layer if product uses layer-based costing
                    try:
                        method = CostingService._get_product_costing_method(db, line["product_id"], wh_id)
                        if method in ("fifo", "lifo"):
                            CostingService.create_cost_layer(
                                db,
                                product_id=line["product_id"],
                                warehouse_id=wh_id,
                                quantity=str(_dec(line["quantity"])),
                                unit_cost=new_price_bc,
                                source_document_type="purchase_invoice",
                                source_document_id=invoice_id,
                                costing_method=method,
                            )
                    except Exception as layer_err:
                        import logging
                        logging.getLogger(__name__).warning("Cost layer creation failed: %s", layer_err)
    
                    # 2. Update Inventory Quantity (Avoid double counting if already received via PO)
                    received_qty = po_received_map.get(line["product_id"], 0)
                    invoice_qty = _dec(line["quantity"])
                    
                    # The quantity to actually ADD to inventory now
                    qty_to_add = invoice_qty
                    qty_already_received = Decimal('0')
                    
                    if invoice.original_invoice_id:
                        # If we already received some, only add the difference
                        qty_already_received = min(invoice_qty, received_qty)
                        qty_to_add = max(0, invoice_qty - received_qty)
                        
                        # Accumulate value to reverse from "Unbilled Purchases" instead of Dr Inventory
                        receipt_accrual_reversal_base += qty_already_received * new_price_bc
                    
                    if qty_to_add > 0:
                        inv_exists = db.execute(text("""
                            SELECT 1 FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
                        """), {"pid": line["product_id"], "wh": wh_id}).fetchone()
                        
                        if inv_exists:
                            db.execute(text("""
                                UPDATE inventory SET quantity = quantity + :qty 
                                WHERE product_id = :pid AND warehouse_id = :wh
                            """), {"qty": qty_to_add, "pid": line["product_id"], "wh": wh_id})
                        else:
                            db.execute(text("""
                                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost)
                                VALUES (:pid, :wh, :qty, :cost)
                            """), {"pid": line["product_id"], "wh": wh_id, "qty": qty_to_add, "cost": new_price_bc})
                        
                    # 4. Log Inventory Transaction (Only if not prepayment)
                    db.execute(text("""
                        INSERT INTO inventory_transactions (
                            product_id, warehouse_id, transaction_type, 
                            reference_type, reference_id, reference_document,
                            quantity, unit_cost, total_cost, created_by
                        ) VALUES (
                            :pid, :wh, 'purchase', 'invoice', :inv_id, :inv_num,
                            :qty, :cost, :total_cost, :user
                        )
                    """), {
                        "pid": line["product_id"],
                        "wh": wh_id,
                        "inv_id": invoice_id,
                        "inv_num": inv_num,
                        "qty": line["quantity"],
                        "cost": new_price_bc,
                        "total_cost": to_base(line["total"]),
                        "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id
                    })
    
            # 6. Update Supplier Balance via party_site_balances
            if remaining_balance > _D2:
                gl_remaining = to_base(remaining_balance)
                update_party_site_balance(db, party_id=invoice.supplier_id, branch_id=validated_branch_id or invoice.branch_id,
                                   currency=inv_currency, amount=-float(remaining_balance))
                
            # 7. Record Payment Transaction
            if paid_amount and paid_amount > 0:
                from utils.accounting import generate_sequential_number
                v_num = generate_sequential_number(db, f"PAY-{datetime.now().year}", "payment_vouchers", "voucher_number")
                # Determine actual payment method for the voucher
                # If main method is 'credit', check down_payment_method
                actual_method = invoice.payment_method
                if invoice.payment_method == 'credit':
                    actual_method = invoice.down_payment_method or 'cash'
                
                pay_id = db.execute(text("""
                    INSERT INTO payment_vouchers (
                        voucher_number, voucher_type, voucher_date, 
                        party_type, party_id, amount, payment_method, 
                        reference, status, created_by,
                        currency, exchange_rate, treasury_account_id
                    ) VALUES (
                        :num, 'payment', :date, 
                        'supplier', :pid, :amt, :method, 
                        :ref, 'posted', :user,
                        :currency, :exchange_rate, :treasury_id
                    ) RETURNING id
                """), {
                    "num": v_num,
                    "date": invoice.invoice_date,
                    "pid": invoice.supplier_id,
                    "amt": paid_amount,
                    "method": actual_method,
                    "ref": f"Payment for {inv_num}",
                    "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                    "currency": inv_currency,
                    "exchange_rate": exchange_rate,
                    "treasury_id": invoice.treasury_id
                }).scalar()
    
                # Create Allocation
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:pid, :iid, :amt)
                """), {
                    "pid": pay_id,
                    "iid": invoice_id,
                    "amt": paid_amount
                })
    
            # 8. GL Entry (Automated using Dynamic Mappings)
            if invoice.is_prepayment:
                acc_inventory = _require_account_map(db, "acc_map_prepayment_supplier", "دفعة مقدمة للمورد")
            else:
                acc_inventory = _require_account_map(db, "acc_map_inventory", "المخزون")

            acc_vat_in = _require_account_map(db, "acc_map_vat_in", "ضريبة مدخلات") if _dec(total_tax) > _D2 else None

            # Calculate Base Currency Amounts for GL (must be before acc_ap check)
            gl_total = to_base(grand_total)
            gl_subtotal = to_base(subtotal)
            gl_tax = to_base(total_tax)
            gl_paid = to_base(paid_amount)
            gl_net_purchases = gl_subtotal - to_base(total_discount)

            acc_ap = _require_account_map(db, "acc_map_ap", "الذمم الدائنة") if (gl_total - gl_paid) > _D2 else None
            acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
            acc_bank = get_mapped_account_id(db, "acc_map_bank")
            
            je_lines = []
    
            # A. Inventory (Debit) - Net of Discount (Base Currency)
            # Handle Accrual Reversal if created from PO
            gl_inventory_debit = gl_net_purchases - receipt_accrual_reversal_base
            
            # FC equivalents for amount_currency
            fc_net_purchases = subtotal - total_discount
            fc_accrual_reversal = (receipt_accrual_reversal_base / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate != 0 else Decimal('0')
            fc_inventory_debit = fc_net_purchases - fc_accrual_reversal
            
            if gl_inventory_debit > _D2:
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": fc_inventory_debit if inv_currency != base_currency else gl_inventory_debit,
                    "credit": 0,
                    "description": f"Purchase Stock - {inv_num}",
                    "amount_currency": fc_inventory_debit if inv_currency != base_currency else gl_inventory_debit,
                    "currency": inv_currency
                })
            
            if receipt_accrual_reversal_base > _D2:
                acc_unbilled = get_mapped_account_id(db, "acc_map_unbilled_purchases")
                if acc_unbilled:
                    je_lines.append({
                        "account_id": acc_unbilled,
                        "debit": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                        "credit": 0,
                        "description": f"Reverse Unbilled Accrual - {inv_num}",
                        "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                        "currency": inv_currency
                    })
                    # Balance update handled by the JE lines loop below
                else:
                     # Fallback if mapping missing but we have reversal value (should not happen if system setup right)
                     je_lines.append({
                         "account_id": acc_inventory,
                         "debit": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                         "credit": 0,
                         "description": f"Purchase Stock (No Accrual Map) - {inv_num}",
                         "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                         "currency": inv_currency
                     })
                
            # B. VAT Input (Debit) (Base Currency)
            if gl_tax > 0:
                je_lines.append({
                    "account_id": acc_vat_in,
                    "debit": total_tax if inv_currency != base_currency else gl_tax,
                    "credit": 0,
                    "description": f"VAT Input - {inv_num}",
                    "amount_currency": total_tax, "currency": inv_currency
                })
                
            # C. Credit Side (Cash/Bank/AP)
            actual_pay_method = invoice.payment_method
            if invoice.payment_method == 'credit':
                 actual_pay_method = invoice.down_payment_method or 'cash'
                 
            if gl_paid > 0:
                 if actual_pay_method == "cash" or actual_pay_method == "check": 
                      # Use selected treasury account if provided, else fallback to default cash map
                      cash_acc_id = acc_cash
                      if actual_pay_method == "check":
                          cash_acc_id = acc_bank # Default for checks
                      
                      if selected_treasury:
                          cash_acc_id = selected_treasury["gl_account_id"]

                      if not cash_acc_id:
                          raise HTTPException(
                              status_code=400,
                              detail="لم يتم ضبط حساب النقدية/البنك للدفع النقدي"
                          )
    
                      je_lines.append({
                          "account_id": cash_acc_id,
                          "debit": 0,
                          "credit": paid_amount if inv_currency != base_currency else gl_paid,
                          "description": f"Purchase {actual_pay_method.capitalize()} - {inv_num}",
                          "amount_currency": paid_amount, "currency": inv_currency
                      })
                 elif actual_pay_method == "bank":
                      # Use selected treasury account if provided, else fallback to default bank map
                      bank_acc_id = acc_bank
                      if selected_treasury:
                          bank_acc_id = selected_treasury["gl_account_id"]
                      if not bank_acc_id:
                          raise HTTPException(
                              status_code=400,
                              detail="لم يتم ضبط حساب البنك للدفع البنكي"
                          )
                      je_lines.append({
                          "account_id": bank_acc_id,
                          "debit": 0,
                          "credit": paid_amount if inv_currency != base_currency else gl_paid,
                          "description": f"Purchase Bank - {inv_num}",
                          "amount_currency": paid_amount, "currency": inv_currency
                      })
            
            remaining_gl = gl_total - gl_paid     
            if remaining_gl > _D2:
                 je_lines.append({
                     "account_id": acc_ap,
                     "debit": 0,
                     "credit": remaining_balance if inv_currency != base_currency else remaining_gl,
                     "description": f"Purchase Credit - {inv_num}",
                     "amount_currency": remaining_balance, "currency": inv_currency
                 })
            
            # Insert Journal Entry
            if je_lines:
                gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=str(invoice.invoice_date),
                    description=f"Purchase Invoice {inv_num} ({inv_currency})",
                    reference=inv_num,
                    lines=je_lines,
                    user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                    branch_id=invoice.branch_id,
                    currency=inv_currency,
                    exchange_rate=exchange_rate,
                    source="purchase_invoice",
                    source_id=invoice_id
                )
    
            # --- 8. Insert Currency Transaction (if Foreign Currency) ---
            if inv_currency != base_currency:
                 db.execute(text("""
                     INSERT INTO currency_transactions (
                         transaction_type, transaction_id, account_id, 
                         currency_code, exchange_rate, amount_fc, amount_bc, description
                     ) VALUES (
                         'purchase', :tid, :aid, :curr, :rate, :fc, :bc, :desc
                     )
                 """), {
                     "tid": invoice_id,
                     "aid": acc_ap, # Tracking AP in foreign currency
                     "curr": inv_currency,
                     "rate": exchange_rate,
                     "fc": grand_total,
                     "bc": to_base(grand_total),
                     "desc": f"Purchase Invoice {inv_num}"
                 })
    
    
            supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": invoice.supplier_id}).scalar()
            # AUDIT LOG
            log_activity(
                db,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
                action="purchase_invoice.create",
                resource_type="invoice",
                resource_id=str(invoice_id),
                details={"invoice_number": inv_num, "total": grand_total, "supplier_id": invoice.supplier_id, "supplier_name": supp_name},
                request=request,
                branch_id=invoice.branch_id
            )
    
            # ── 3-Way Matching: auto-match if invoice is linked to a PO ──
            match_result = None
            if invoice.original_invoice_id:
                try:
                    from services.matching_service import perform_match
                    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
                    match_result = perform_match(
                        db,
                        invoice_id=invoice_id,
                        po_id=invoice.original_invoice_id,
                        supplier_id=invoice.supplier_id,
                        user_id=user_id,
                    )
                    db.commit()
                    # Notify if match has exceptions
                    if match_result and match_result.get("match_status") == "exception":
                        try:
                            from services.notification_service import NotificationService
                            ns = NotificationService(db)
                            ns.dispatch(
                                recipient_id=user_id,
                                event_type="invoice_held",
                                title="فاتورة مشتريات معلّقة - مطابقة ثلاثية",
                                body=f"الفاتورة {inv_num} تحتوي على فروقات تحتاج مراجعة",
                                reference_type="three_way_match",
                                reference_id=match_result.get("match_id"),
                            )
                        except Exception as notif_err:
                            logger.warning("Failed to dispatch matching notification: %s", notif_err)
                except Exception as match_err:
                    logger.warning("3-way matching failed for invoice %s: %s", invoice_id, match_err)
    
            return {"success": True, "message": "تم إنشاء فاتورة المشتريات بنجاح", "invoice_id": invoice_id, "match_result": match_result}
    
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating purchase invoice: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# === Purchase Returns ===

