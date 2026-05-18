"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
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
from utils.permissions import (
    branch_scope_filter_from_scope,
    require_permission,
    require_sensitive_permission,
    require_module,
    resolve_branch_scope,
    validate_branch_access,
    validate_treasury_account_access,
)
from utils.accounting import (
    compute_invoice_totals,
    compute_line_amounts,
    get_mapped_account_id,
    generate_sequential_number,
    get_base_currency,
)
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from utils.decimal_helper import dec as _dec, D2 as _D2, D4 as _D4
from services.gl_service import create_journal_entry as gl_create_journal_entry
from services.tax_engine import resolve_line_tax
from utils.party_balance import update_party_site_balance
from schemas.purchases import (
    PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest,
    SupplierPaymentCreate,
)


def _line_key(product_id, unit_price, tax_rate, po_line_id=None):
    if po_line_id:
        return ("po_line", int(po_line_id))
    return (
        "product_price_tax",
        int(product_id),
        _dec(unit_price).quantize(_D2, ROUND_HALF_UP),
        _dec(tax_rate).quantize(_D2, ROUND_HALF_UP),
    )


def _line_tax_factor(invoice_tax_amount, original_rows) -> Decimal:
    raw_tax = Decimal("0")
    for row in original_rows:
        gross = (_dec(row.quantity) * _dec(row.unit_price)).quantize(_D2, ROUND_HALF_UP)
        taxable = gross - _dec(getattr(row, "discount", 0))
        raw_tax += (taxable * _dec(row.tax_rate) / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
    if raw_tax <= 0:
        return Decimal("1")
    factor = _dec(invoice_tax_amount) / raw_tax
    return max(Decimal("0"), min(Decimal("1"), factor))


def _reversal_taxable_amount(original_line, quantity) -> Decimal:
    original_qty = _dec(original_line.quantity)
    if original_qty <= 0:
        raise HTTPException(**http_error(400, "original_line_qty_invalid"))
    gross = (_dec(original_line.quantity) * _dec(original_line.unit_price)).quantize(_D2, ROUND_HALF_UP)
    taxable = gross - _dec(getattr(original_line, "discount", 0))
    ratio = _dec(quantity) / original_qty
    return (taxable * ratio).quantize(_D2, ROUND_HALF_UP)


def _reversal_discount_amount(original_line, quantity) -> Decimal:
    original_qty = _dec(original_line.quantity)
    if original_qty <= 0:
        return Decimal("0")
    ratio = _dec(quantity) / original_qty
    return (_dec(getattr(original_line, "discount", 0)) * ratio).quantize(_D2, ROUND_HALF_UP)


def _load_original_purchase_invoice_for_return(db, invoice_id: int, supplier_id: int):
    invoice = db.execute(text("""
        SELECT id, party_id, branch_id, invoice_type, invoice_date, tax_amount
        FROM invoices
        WHERE id = :id
        FOR UPDATE
    """), {"id": invoice_id}).fetchone()
    if not invoice:
        raise HTTPException(**http_error(404, "purchase_invoice_not_found"))
    if invoice.invoice_type != "purchase":
        raise HTTPException(**http_error(400, "return_must_link_invoice"))
    if int(invoice.party_id) != int(supplier_id):
        raise HTTPException(**http_error(400, "return_invoice_supplier_mismatch"))

    rows = db.execute(text("""
        SELECT id, product_id, po_line_id, quantity, unit_price, tax_rate, tax_rate_id, discount
        FROM invoice_lines
        WHERE invoice_id = :id
          AND product_id IS NOT NULL
        FOR UPDATE
    """), {"id": invoice_id}).fetchall()
    by_product: dict[int, list] = {}
    for row in rows:
        by_product.setdefault(int(row.product_id), []).append(row)

    returned = db.execute(text("""
        SELECT il.product_id, il.po_line_id, il.unit_price, il.tax_rate, COALESCE(SUM(il.quantity), 0) AS qty
        FROM invoices pr
        JOIN invoice_lines il ON il.invoice_id = pr.id
        WHERE pr.related_invoice_id = :id
          AND pr.invoice_type = 'purchase_return'
          AND COALESCE(pr.status, '') != 'cancelled'
          AND il.product_id IS NOT NULL
        GROUP BY il.product_id, il.po_line_id, il.unit_price, il.tax_rate
    """), {"id": invoice_id}).fetchall()
    used_qty = {
        _line_key(row.product_id, row.unit_price, row.tax_rate, row.po_line_id): _dec(row.qty)
        for row in returned
    }
    return invoice, by_product, used_qty, _line_tax_factor(invoice.tax_amount, rows)


def _original_purchase_line_for_return(original_lines: dict[int, list], product_id: int, unit_price):
    candidates = original_lines.get(int(product_id), [])
    if not candidates:
        raise HTTPException(**http_error(400, "item_not_in_invoice"))
    if len(candidates) == 1:
        return candidates[0]
    price = _dec(unit_price)
    matched = [row for row in candidates if _dec(row.unit_price) == price]
    if len(matched) == 1:
        return matched[0]
    raise HTTPException(**http_error(400, "multi_line_tax_ambiguity_purchase"))


router = APIRouter()
logger = logging.getLogger(__name__)


def _company_id(user) -> str:
    return user.get("company_id") if isinstance(user, dict) else user.company_id


def _user_id(user) -> int:
    return user.get("id") if isinstance(user, dict) else user.id


def _username(user) -> str:
    return user.get("username") if isinstance(user, dict) else user.username


@router.get("/returns", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_returns(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض مردودات المشتريات"""
    company_id = _company_id(current_user)
    with transactional(company_id) as db:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query_str = """
            SELECT i.id, i.invoice_number, p.name as supplier_name, 
                   i.invoice_date, i.total, i.status
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase_return'
        """
        params = {"limit": limit, "skip": skip}
        
        query_str += branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
            
        query_str += " ORDER BY i.created_at DESC LIMIT :limit OFFSET :skip"
        
        result = db.execute(text(query_str), params).fetchall()
        
        returns = []
        for row in result:
            returns.append({
                "id": row.id,
                "invoice_number": row.invoice_number,
                "supplier_name": row.supplier_name,
                "invoice_date": row.invoice_date,
                "total": row.total,
                "status": row.status
            })
        return returns

@router.get("/returns/{id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_purchase_return(request: Request, 
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل مردود مشتريات"""
    company_id = _company_id(current_user)
    with transactional(company_id) as db:
        # Get Invoice
        query = """
            SELECT i.*, p.name as supplier_name, p.party_code as supplier_code
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.id = :id AND i.invoice_type = 'purchase_return'
        """
        invoice = db.execute(text(query), {"id": id}).fetchone()
        
        if not invoice:
            raise HTTPException(**http_error(404, "return_not_found_msg", request))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, invoice.branch_id)

        # Get Items
        items_query = """
            SELECT ii.*, p.product_name, p.product_code
            FROM invoice_lines ii
            JOIN products p ON ii.product_id = p.id
            WHERE ii.invoice_id = :id
        """
        items = db.execute(text(items_query), {"id": id}).fetchall()
        
        return {
            "invoice": dict(invoice._mapping),
            "items": [dict(item._mapping) for item in items]
        }

@router.post("/returns", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_return(
    request: Request,
    invoice: PurchaseCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مردود مشتريات (خصم من المخزون + قيد دائن للمورد + سند قبض اختياري)"""
    company_id = _company_id(current_user)
    user_id = _user_id(current_user)

    with transactional(company_id) as db:
        try:
            # Resolve base currency
            from utils.accounting import get_base_currency
            base_currency = get_base_currency(db)
            
            # 1. Validate Supplier
            supplier = db.execute(text("SELECT * FROM parties WHERE id = :id AND is_supplier = TRUE"), {"id": invoice.supplier_id}).fetchone()
            if not supplier:
                raise HTTPException(**http_error(404, "supplier_not_found"))

            original_invoice = None
            original_lines = {}
            already_reversed_qty = {}
            original_tax_factor = Decimal("1")
            if invoice.original_invoice_id:
                original_invoice, original_lines, already_reversed_qty, original_tax_factor = _load_original_purchase_invoice_for_return(
                    db, invoice.original_invoice_id, invoice.supplier_id
                )

            branch_id = invoice.branch_id
            if original_invoice:
                if branch_id and original_invoice.branch_id is not None and int(branch_id) != int(original_invoice.branch_id):
                    raise HTTPException(**http_error(400, "return_branch_mismatch", request))
                branch_id = original_invoice.branch_id
            branch_id = validate_branch_access(current_user, branch_id)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
    
            # 2. Generate Return Number (PR-YYYY-XXXX)
            year = date.today().year
            count = db.execute(text("SELECT count(*) FROM invoices WHERE invoice_type='purchase_return'")).scalar() or 0
            return_number = f"PR-{year}-{str(count + 1).zfill(4)}"
    
            # 3. Create Invoice Record (Type: purchase_return)
            lines_to_save = []
            for item in invoice.items:
                if original_invoice:
                    if not item.product_id:
                        raise HTTPException(**http_error(400, "item_required_for_purchase_return", request))
                    original_line = _original_purchase_line_for_return(original_lines, item.product_id, item.unit_price)
                    reverse_key = _line_key(
                        original_line.product_id,
                        original_line.unit_price,
                        original_line.tax_rate,
                        getattr(original_line, "po_line_id", None),
                    )
                    already_qty = already_reversed_qty.get(reverse_key, Decimal("0"))
                    available_qty = _dec(original_line.quantity) - already_qty
                    if _dec(item.quantity) > available_qty:
                        raise HTTPException(**http_error(400, "return_qty_exceeds_invoice", request))
                    tax_info = {
                        "tax_rate": _dec(original_line.tax_rate),
                        "tax_rate_id": original_line.tax_rate_id,
                    }
                    taxable_base = _reversal_taxable_amount(original_line, item.quantity)
                    effective_discount = _reversal_discount_amount(original_line, item.quantity)
                    tax_amount = (taxable_base * tax_info["tax_rate"] / Decimal("100") * original_tax_factor).quantize(_D2, ROUND_HALF_UP)
                    line_total = (taxable_base + tax_amount).quantize(_D2, ROUND_HALF_UP)
                    already_reversed_qty[reverse_key] = already_qty + _dec(item.quantity)
                else:
                    tax_info = resolve_line_tax(branch_id, item.product_id, db, invoice.invoice_date, customer_id=invoice.supplier_id)
                    la = compute_line_amounts(item.quantity, item.unit_price, tax_info["tax_rate"], item.discount, discount_is_percent=False)
                    taxable_base = la["taxable"]
                    effective_discount = _dec(item.discount)
                    tax_amount = la["tax_amount"]
                    line_total = la["line_total"]
                lines_to_save.append({
                    "item": item,
                    "original_line": original_line if original_invoice else None,
                    "tax_rate": tax_info["tax_rate"],
                    "tax_rate_id": tax_info.get("tax_rate_id"),
                    "discount": effective_discount,
                    "taxable_base": taxable_base,
                    "tax_amount": tax_amount,
                    "line_total": line_total,
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
            if original_invoice:
                subtotal = sum((line["taxable_base"] for line in lines_to_save), Decimal("0")).quantize(_D2, ROUND_HALF_UP)
                tax_total = sum((line["tax_amount"] for line in lines_to_save), Decimal("0")).quantize(_D2, ROUND_HALF_UP)
                total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
            else:
                totals = compute_invoice_totals([
                    {
                        "quantity": line["item"].quantity,
                        "unit_price": line["item"].unit_price,
                        "tax_rate": line["tax_rate"],
                        "discount": line["item"].discount,
                    }
                    for line in lines_to_save
                ], header_discount_pct=header_discount_pct, markup_amount=markup_amount, discount_is_percent=False)
                subtotal = totals["subtotal"]
                tax_total = totals["total_tax"]
                total = totals["grand_total"]
    
            # Determine warehouse: Use original invoice's warehouse if possible
            wh_id = invoice.warehouse_id
            if not wh_id and invoice.original_invoice_id:
                orig_wh = db.execute(text("""
                    SELECT prl.warehouse_id
                    FROM invoice_lines il
                    JOIN po_receipt_lines prl ON prl.po_line_id = il.po_line_id
                    WHERE il.invoice_id = :id
                      AND il.po_line_id IS NOT NULL
                    GROUP BY prl.warehouse_id
                    ORDER BY SUM(prl.quantity) DESC
                    LIMIT 1
                """), {"id": invoice.original_invoice_id}).scalar()
                if orig_wh:
                    wh_id = orig_wh

            if not wh_id and invoice.original_invoice_id:
                orig_wh = db.execute(text("""
                    SELECT warehouse_id FROM inventory_transactions 
                    WHERE reference_id = :id AND reference_type = 'invoice' 
                    LIMIT 1
                """), {"id": invoice.original_invoice_id}).scalar()
                if orig_wh:
                    wh_id = orig_wh
    
            if not wh_id:
                wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_active=TRUE ORDER BY is_default DESC LIMIT 1")).scalar()
                if not wh_id:
                    wh_id = db.execute(text("SELECT id FROM warehouses LIMIT 1")).scalar()
            
            if not wh_id:
                 raise HTTPException(**http_error(400, "at_least_one_warehouse_required", request))
    
            # 3.5 Validate Warehouse-Branch Association (for Return)
            if wh_id and branch_id:
                wh_check = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": wh_id}).fetchone()
                if wh_check and wh_check[0] and wh_check[0] != branch_id:
                    raise HTTPException(**http_error(400, "warehouse_not_in_current_branch", request))
    
            for item in invoice.items:
                current_stock = db.execute(text(
                    "SELECT quantity FROM inventory WHERE product_id = :pid AND warehouse_id = :wh FOR UPDATE"
                ), {"pid": item.product_id, "wh": wh_id}).scalar() or 0
                # For returns, we check if we have the items? 
                # Actually, standard logic: You can't return what you don't have? 
                # Yes, we check stock availability to remove it.
                # Wait, if I bought 10, current stock 10. Return 5. Valid.
                # If I bought 10, sold 10. Current stock 0. Return 5?
                # You physically have the item to return? If stock is 0, implies you don't have it.
                # Unless you allow negative stock. 
                # We will enforce logic: Must have stock to return it.
                qty_to_check = abs(item.quantity)
                if qty_to_check > current_stock:
                    product_name = db.execute(text("SELECT product_name FROM products WHERE id=:id"), {"id": item.product_id}).scalar()
                    raise ValueError(f"الكمية المراد إرجاعها '{product_name}' ({qty_to_check}) غير متوفرة في المخزون الحالي ({current_stock})")
    
            # Create Invoice
            # Note: If paid_amount > 0, we mark as 'paid' or 'partial'.
            # For returns, 'paid' means the refund was processed.
            return_status = 'posted' # Default
            if invoice.paid_amount and _dec(invoice.paid_amount) >= total - _D2:
                return_status = 'paid'
            elif invoice.paid_amount and _dec(invoice.paid_amount) > 0:
                return_status = 'partial'
    
            new_invoice_id = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, party_id, invoice_date, due_date,
                    subtotal, tax_amount, total, paid_amount,
                    status, invoice_type, notes, created_by, related_invoice_id, branch_id,
                    currency, exchange_rate, party_site_id
                ) VALUES (
                    :num, :pid, :date, :due,
                    :sub, :tax, :total, :paid,
                    :status, 'purchase_return', :notes, :uid, :rel_id, :bid,
                    :currency, :exchange_rate, :party_site_id
                ) RETURNING id
            """), {
                "num": return_number, "pid": invoice.supplier_id, "date": invoice.invoice_date,
                "due": invoice.due_date, "sub": subtotal, "tax": tax_total, "total": total,
                "paid": invoice.paid_amount or 0,
                "status": return_status, "notes": invoice.notes, "uid": user_id,
                "rel_id": invoice.original_invoice_id, "bid": branch_id,
                "currency": invoice.currency or base_currency, "exchange_rate": 1.0 if invoice.exchange_rate is None else invoice.exchange_rate,
                "party_site_id": invoice.party_site_id,
            }).fetchone()[0]
    
            # 4. Add Items & Update Stock (DEDUCT)
            return_lines_data = []  # T024: Track actual costs per line
            for line in lines_to_save:
                item = line["item"]
                item_total = line["line_total"]
                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, po_line_id, description, quantity, unit_price,
                        tax_rate, tax_rate_id, discount, total
                    ) VALUES (
                        :iid, :pid, :po_line_id, :desc, :qty, :price,
                        :tax, :tax_id, :disc, :total
                    )
                """), {
                    "iid": new_invoice_id, "pid": item.product_id, "desc": item.description,
                    "po_line_id": getattr(line.get("original_line"), "po_line_id", None) if original_invoice else None,
                    "qty": item.quantity, "price": item.unit_price, "tax": line["tax_rate"],
                    "tax_id": line["tax_rate_id"],
                    "disc": line["discount"], "total": item_total
                })
    
                # T3.9: reverse the original purchase's cost layer instead of
                # creating a new (positive) layer. handle_return now reduces the
                # remaining_quantity of the matching layer when we pass the
                # original purchase invoice id; this keeps FIFO/LIFO valuation
                # consistent across purchase returns.
                from services.costing_service import CostingService
                return_qty = abs(_dec(item.quantity))
                return_unit_cost = _dec(item.unit_price)
                costing_method = CostingService._get_product_costing_method(db, item.product_id, wh_id)
                if costing_method in ("fifo", "lifo"):
                    try:
                        if invoice.original_invoice_id:
                            # Trace the original invoice line to the exact PO receipt layer.
                            original_line = line.get("original_line")
                            po_line_id = getattr(original_line, "po_line_id", None)
                            if not po_line_id:
                                raise HTTPException(**http_error(400, "po_line_link_missing", request))
                            receipt_row = db.execute(text("""
                                SELECT prl.id
                                FROM po_receipt_lines prl
                                WHERE prl.po_line_id = :po_line_id
                                  AND prl.product_id = :product_id
                                  AND prl.warehouse_id = :warehouse_id
                                ORDER BY prl.id ASC
                                LIMIT 1
                            """), {
                                "po_line_id": po_line_id,
                                "product_id": item.product_id,
                                "warehouse_id": wh_id,
                            }).fetchone()
                            if not receipt_row:
                                raise HTTPException(**http_error(400, "no_grn_linked_to_po_line", request))

                            result = CostingService.handle_return(
                                db,
                                product_id=item.product_id,
                                warehouse_id=wh_id,
                                quantity=return_qty,
                                unit_cost=float(return_unit_cost),
                                source_document_type="purchase_return",
                                source_document_id=new_invoice_id,
                                costing_method=costing_method,
                                # Legacy tests looked for original_source_document_type="purchase_invoice";
                                # production now traces the invoice line to the exact receipt layer.
                                original_source_document_type="po_receipt_line",
                                original_source_document_id=receipt_row.id,
                            )
                            return_unit_cost = _dec(result.get("restored_unit_cost", return_unit_cost))
                        else:
                            consumed_value = CostingService.consume_layers(
                                db,
                                product_id=item.product_id,
                                warehouse_id=wh_id,
                                quantity=return_qty,
                                sale_document_type="purchase_return",
                                sale_document_id=new_invoice_id,
                                costing_method=costing_method,
                            )
                            return_unit_cost = (_dec(consumed_value) / return_qty).quantize(_D4, ROUND_HALF_UP) if return_qty else Decimal("0")
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
                else:
                    inv_cost_row = db.execute(text("""
                        SELECT average_cost
                        FROM inventory
                        WHERE product_id = :pid AND warehouse_id = :wh
                        FOR UPDATE
                    """), {"pid": item.product_id, "wh": wh_id}).fetchone()
                    return_unit_cost = _dec(inv_cost_row.average_cost or item.unit_price) if inv_cost_row else return_unit_cost

                # Update Inventory (DECREASE QUANTITY) after costing succeeds.
                inv_update = db.execute(text("""
                    UPDATE inventory
                    SET quantity = quantity - :qty, last_movement_date = NOW(), updated_at = NOW()
                    WHERE product_id = :pid AND warehouse_id = :wh
                      AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                    RETURNING id
                """), {"qty": float(return_qty), "pid": item.product_id, "wh": wh_id}).fetchone()
                if not inv_update:
                    raise HTTPException(**http_error(400, "insufficient_stock_for_return", request))

                return_total_cost = (return_unit_cost * return_qty).quantize(_D2, ROUND_HALF_UP)
                return_lines_data.append({"return_total_cost": return_total_cost})

                # Log Transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type,
                        reference_type, reference_id,
                        quantity, unit_cost, total_cost, notes, created_by
                    ) VALUES (
                        :pid, :wh, 'purchase_return',
                        'purchase_return', :ref_id,
                        :qty, :unit_cost, :total_cost, 'مردود مشتريات', :uid
                    )
                """), {
                    "pid": item.product_id,
                    "wh": wh_id,
                    "ref_id": new_invoice_id,
                    "qty": -float(return_qty),
                    "unit_cost": float(return_unit_cost),
                    "total_cost": float(return_total_cost),
                    "uid": user_id,
                })
    
            # 5. Update Supplier Balance (Logic: Return reduces balance)
            exchange_rate = _dec(1 if invoice.exchange_rate is None else invoice.exchange_rate)
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            def to_base(amount):
                return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
    
            gl_total = to_base(total)
            gl_subtotal = to_base(subtotal)
            gl_tax = to_base(tax_total)

            # T024: Use actual cost from cost layers for inventory credit
            # Compute actual inventory cost from all line return_total_cost values
            actual_inventory_base = Decimal('0')
            for item_data in return_lines_data:
                actual_inventory_base += to_base(item_data.get("return_total_cost", 0))
            if actual_inventory_base > 0:
                gl_subtotal = actual_inventory_base

            # T025: Post price variance if invoice price differs from actual cost
            variance_base = gl_total - gl_subtotal - (gl_tax if gl_tax > 0 else 0)
            variance_acc = None
            if abs(variance_base) > _D2:
                variance_acc = get_mapped_account_id(db, "acc_map_purchase_variance") or get_mapped_account_id(db, "acc_map_price_variance")

            # Update supplier balance via party_site_balances
            # T026: Returns should be positive (reduces what we owe)
            update_party_site_balance(
                db,
                party_id=invoice.supplier_id,
                branch_id=branch_id,
                currency=invoice.currency or base_currency,
                amount=total,
                document_type="purchase_return",
            )
    
            # 6. Accounting Entries (Return Itself)
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, invoice.invoice_date)
    
            # Credit: Inventory | Debit: Accounts Payable
            # F-31: credit the source warehouse's inventory account so per-warehouse
            # valuation drops by the returned amount.
            from utils.inventory_accounts import resolve_warehouse_inventory_account
            inventory_acc = resolve_warehouse_inventory_account(db, wh_id)
            ap_acc = get_mapped_account_id(db, "acc_map_ap")
            vat_acc = get_mapped_account_id(db, "acc_map_vat_in")
    
            if inventory_acc and ap_acc:
                # Validate rounding: ensure debit (gl_total) matches credits (gl_subtotal + gl_tax)
                credit_sum = gl_subtotal + (gl_tax if gl_tax > 0 and vat_acc else 0)
                rounding_diff = abs(gl_total - credit_sum)
                if rounding_diff > 0 and rounding_diff <= 0.05:
                    # Fix small rounding difference by adjusting inventory credit
                    gl_subtotal = gl_total - (gl_tax if gl_tax > 0 and vat_acc else 0)
    
                je_lines = [
                    {"account_id": ap_acc, "debit": gl_total, "credit": 0, "description": "مردود مشتريات", "amount_currency": total, "currency": invoice.currency or base_currency},
                    {"account_id": inventory_acc, "debit": 0, "credit": gl_subtotal, "description": "تكلفة البضاعة", "amount_currency": subtotal, "currency": invoice.currency or base_currency}
                ]
                # T025: Add variance line if actual cost differs from invoice price
                if variance_acc and abs(variance_base) > _D2:
                    if variance_base > 0:
                        # Invoice price > actual cost: credit variance
                        je_lines.append({"account_id": variance_acc, "debit": 0, "credit": abs(variance_base), "description": "فرق سعر مردود", "currency": invoice.currency or base_currency})
                    else:
                        # Actual cost > invoice price: debit variance
                        je_lines.append({"account_id": variance_acc, "debit": abs(variance_base), "credit": 0, "description": "فرق سعر مردود", "currency": invoice.currency or base_currency})
                if gl_tax > 0 and vat_acc:
                    je_lines.append({"account_id": vat_acc, "debit": 0, "credit": gl_tax, "description": "استرداد ضريبة", "amount_currency": tax_total, "currency": invoice.currency or base_currency})
    
                gl_create_journal_entry(
                    db=db,
                    company_id=company_id,
                    date=str(invoice.invoice_date),
                    description=f"مردود مشتريات {return_number} ({invoice.currency})",
                    reference=return_number,
                    lines=je_lines,
                    user_id=user_id,
                    branch_id=branch_id,
                    currency=invoice.currency or base_currency,
                    exchange_rate=1.0,  # amounts already in base currency
                    source="purchase_return",
                    source_id=new_invoice_id
                )
    
            # 7. INTEGRATED REFUND (If paid_amount > 0)
            if invoice.paid_amount and invoice.paid_amount > 0:
                from utils.accounting import generate_sequential_number
                voucher_num = generate_sequential_number(db, f"RCT-{datetime.now().year}", "payment_vouchers", "voucher_number")
                
                gl_paid = to_base(invoice.paid_amount)
    
                # Create Voucher (Type: refund)
                vid = db.execute(text("""
                    INSERT INTO payment_vouchers (
                        voucher_number, voucher_type, voucher_date, party_type, party_id,
                amount, payment_method, notes, status, created_by,
                        currency, exchange_rate, treasury_account_id
                    ) VALUES (
                        :vnum, 'refund', :vdate, 'supplier', :supp,
                        :amt, :method, :notes, 'posted', :user,
                        :currency, :exchange_rate, :treasury_id
                    ) RETURNING id
                """), {
                    "vnum": voucher_num, "vdate": invoice.invoice_date, "supp": invoice.supplier_id,
                    "amt": invoice.paid_amount, "method": invoice.payment_method or 'cash',
                    "notes": f"استرداد نقدي عن مردود {return_number}", "user": user_id,
                    "currency": invoice.currency or base_currency, "exchange_rate": exchange_rate,
                    "treasury_id": invoice.treasury_id,
                }).fetchone()[0]
    
                # Allocation
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                """), {"vid": vid, "iid": new_invoice_id, "amt": invoice.paid_amount})
    
                # Refund received settles the positive return balance.
                update_party_site_balance(
                    db,
                    party_id=invoice.supplier_id,
                    branch_id=branch_id,
                    currency=invoice.currency or base_currency,
                    amount=-_dec(invoice.paid_amount),
                    document_type="supplier_refund",
                )
    
                # GL for Refund
                refund_treasury_id = invoice.treasury_id
                selected_treasury = None
                if refund_treasury_id:
                    selected_treasury = validate_treasury_account_access(
                        db, current_user, refund_treasury_id, branch_id
                    )

                cash_acc = selected_treasury["gl_account_id"] if selected_treasury else get_mapped_account_id(db, "acc_map_cash_main")
                if invoice.payment_method == 'bank' and not selected_treasury:
                    cash_acc = get_mapped_account_id(db, "acc_map_bank")
    
                if cash_acc and ap_acc:
                    je_lines_refund = [
                        {"account_id": cash_acc, "debit": gl_paid, "credit": 0, "description": "قبض", "amount_currency": invoice.paid_amount, "currency": invoice.currency or base_currency},
                        {"account_id": ap_acc, "debit": 0, "credit": gl_paid, "description": "تسوية مردود", "amount_currency": invoice.paid_amount, "currency": invoice.currency or base_currency}
                    ]
                    
                    gl_create_journal_entry(
                        db=db,
                        company_id=company_id,
                        date=str(invoice.invoice_date),
                        description=f"سند قبض مورد {voucher_num} ({invoice.currency})",
                        reference=voucher_num,
                        lines=je_lines_refund,
                        user_id=user_id,
                        branch_id=branch_id,
                        currency=invoice.currency or base_currency,
                        exchange_rate=1.0,  # amounts already in base currency
                        source="payment_voucher",
                        source_id=vid
                    )

                    if refund_treasury_id:
                        from utils.treasury_balance import recalc_treasury_from_gl
                        recalc_treasury_from_gl(db, refund_treasury_id)
    
    
            log_activity(
                db,
                user_id=user_id,
                username=_username(current_user),
                action="purchase_return.create",
                resource_type="invoice",
                resource_id=str(new_invoice_id),
                details={"return_number": return_number, "total": total, "supplier_id": invoice.supplier_id},
                request=request,
                branch_id=branch_id
            )
    
            return {"id": new_invoice_id, "message": i18n_message("purchase_return_created_success", request)}
    
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.exception("Error creating return")
            raise HTTPException(**http_error(500, "return_creation_error", request))


@router.post("/returns/{id}/cancel", dependencies=[Depends(require_sensitive_permission("buying.void"))], response_model=Dict[str, Any])
def cancel_purchase_return(request: Request, id: int, current_user: dict = Depends(get_current_user)):
    """Cancel a posted purchase return with stock, party-balance, GL, and refund reversal."""
    company_id = _company_id(current_user)
    user_id = _user_id(current_user)
    username = _username(current_user)

    with transactional(company_id) as db:
        inv = db.execute(text("""
            SELECT *
            FROM invoices
            WHERE id = :id
              AND invoice_type = 'purchase_return'
            FOR UPDATE
        """), {"id": id}).fetchone()
        if not inv:
            raise HTTPException(**http_error(404, "return_not_found_msg", request))
        validate_branch_access(current_user, inv.branch_id)
        if inv.status in ("cancelled", "void"):
            raise HTTPException(**http_error(400, "purchase_return_already_cancelled", request))

        reversal_date = datetime.now().date()
        check_fiscal_period_open(db, reversal_date, request=request)

        purchase_return_je = db.execute(text("""
            SELECT id
            FROM journal_entries
            WHERE source = 'purchase_return'
              AND source_id = :id
              AND status = 'posted'
            ORDER BY id DESC
            LIMIT 1
        """), {"id": id}).fetchone()
        if not purchase_return_je and _dec(inv.total) > _D2:
            raise HTTPException(**http_error(400, "purchase_return_no_je_to_reverse", request))

        lines = db.execute(text("""
            SELECT *
            FROM invoice_lines
            WHERE invoice_id = :id
              AND product_id IS NOT NULL
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService
        for line in lines:
            qty = _dec(line.quantity)
            tx = db.execute(text("""
                SELECT warehouse_id, unit_cost
                FROM inventory_transactions
                WHERE reference_type = 'purchase_return'
                  AND reference_id = :id
                  AND product_id = :product_id
                ORDER BY id ASC
                LIMIT 1
                FOR UPDATE
            """), {"id": id, "product_id": line.product_id}).fetchone()
            wh_id = tx.warehouse_id if tx and tx.warehouse_id else None
            if not wh_id:
                wh_id = db.execute(text("""
                    SELECT id
                    FROM warehouses
                    WHERE is_active = TRUE
                    ORDER BY is_default DESC, id ASC
                    LIMIT 1
                """)).scalar()
            if not wh_id:
                raise HTTPException(**http_error(400, "at_least_one_warehouse_required", request))

            unit_cost = _dec(tx.unit_cost) if tx and tx.unit_cost is not None else _dec(line.unit_price)
            costing_method = CostingService._get_product_costing_method(db, line.product_id, wh_id)
            if costing_method in ("fifo", "lifo"):
                CostingService.create_cost_layer(
                    db,
                    product_id=line.product_id,
                    warehouse_id=wh_id,
                    quantity=qty,
                    unit_cost=unit_cost,
                    source_document_type="purchase_return_cancel",
                    source_document_id=id,
                    costing_method=costing_method,
                )
            else:
                CostingService.update_cost(
                    db,
                    product_id=line.product_id,
                    warehouse_id=wh_id,
                    new_qty=qty,
                    new_price=unit_cost,
                )

            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:product_id, :warehouse_id, :qty, :unit_cost, NOW())
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                              updated_at = NOW()
            """), {
                "product_id": line.product_id,
                "warehouse_id": wh_id,
                "qty": qty,
                "unit_cost": unit_cost,
            })

            total_cost = (qty * unit_cost).quantize(_D2, ROUND_HALF_UP)
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, notes, created_by
                ) VALUES (
                    :product_id, :warehouse_id, 'purchase_return_cancel',
                    'purchase_return_cancel', :id, :doc,
                    :qty, :unit_cost, :total_cost, :notes, :user_id
                )
            """), {
                "product_id": line.product_id,
                "warehouse_id": wh_id,
                "id": id,
                "doc": inv.invoice_number,
                "qty": qty,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "notes": "Cancel purchase return stock reversal",
                "user_id": user_id,
            })

        update_party_site_balance(
            db,
            party_id=inv.party_id,
            branch_id=inv.branch_id,
            currency=inv.currency or get_base_currency(db),
            amount=-_dec(inv.total),
            document_type="purchase_return_cancel",
        )

        if purchase_return_je:
            from services.gl_service import reverse_journal_entry
            reverse_journal_entry(
                db,
                je_id=purchase_return_je.id,
                user_id=user_id,
                company_id=company_id,
                reversal_date=str(reversal_date),
                reason=f"Cancel purchase return {inv.invoice_number}",
                request=request,
            )

        refund_rows = db.execute(text("""
            SELECT pa.voucher_id,
                   pa.allocated_amount,
                   pv.treasury_account_id,
                   EXISTS (
                       SELECT 1
                       FROM journal_entries je
                       WHERE je.source = 'payment_voucher'
                         AND je.source_id = pv.id
                         AND je.status = 'posted'
                   ) AS has_payment_voucher_je
            FROM payment_allocations pa
            JOIN payment_vouchers pv ON pv.id = pa.voucher_id
            WHERE pa.invoice_id = :id
            FOR UPDATE OF pa, pv
        """), {"id": id}).fetchall()
        treasury_ids = set()
        refund_balance_reversal = Decimal("0")
        for row in refund_rows:
            refund_balance_reversal += _dec(row.allocated_amount)
            if row.has_payment_voucher_je:
                from services.gl_service import reverse_journal_entry
                voucher_je = db.execute(text("""
                    SELECT id
                    FROM journal_entries
                    WHERE source = 'payment_voucher'
                      AND source_id = :voucher_id
                      AND status = 'posted'
                    ORDER BY id DESC
                    LIMIT 1
                """), {"voucher_id": row.voucher_id}).fetchone()
                if voucher_je:
                    reverse_journal_entry(
                        db,
                        je_id=voucher_je.id,
                        user_id=user_id,
                        company_id=company_id,
                        reversal_date=str(reversal_date),
                        reason=f"Cancel refund for purchase return {inv.invoice_number}",
                        request=request,
                    )
            db.execute(text("DELETE FROM payment_allocations WHERE voucher_id = :voucher_id AND invoice_id = :id"),
                       {"voucher_id": row.voucher_id, "id": id})
            db.execute(text("UPDATE payment_vouchers SET status = 'void' WHERE id = :voucher_id"),
                       {"voucher_id": row.voucher_id})
            if row.treasury_account_id:
                treasury_ids.add(row.treasury_account_id)

        if refund_balance_reversal > _D2:
            update_party_site_balance(
                db,
                party_id=inv.party_id,
                branch_id=inv.branch_id,
                currency=inv.currency or get_base_currency(db),
                amount=refund_balance_reversal,
                document_type="supplier_refund_cancel",
            )

        db.execute(text("""
            UPDATE invoices
            SET status = 'cancelled',
                updated_at = NOW()
            WHERE id = :id
        """), {"id": id})

        if treasury_ids:
            from utils.treasury_balance import recalc_treasury_from_gl
            for treasury_id in treasury_ids:
                recalc_treasury_from_gl(db, treasury_id)

        log_activity(
            db,
            user_id=user_id,
            username=username,
            action="purchase_return.cancel",
            resource_type="invoice",
            resource_id=str(id),
            details={"return_number": inv.invoice_number, "total": str(inv.total or 0)},
            request=request,
            branch_id=inv.branch_id,
        )

        return {"success": True, "message": i18n_message("purchase_return_cancelled", request)}
