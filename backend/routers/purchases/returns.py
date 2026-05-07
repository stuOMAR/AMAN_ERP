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
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_module, resolve_branch_scope
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.party_balance import update_party_site_balance
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


@router.get("/returns", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_returns(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض مردودات المشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
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
def get_purchase_return(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل مردود مشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
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
            raise HTTPException(status_code=404, detail="مردود المشتريات غير موجود")

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
    # Get company_id and user_id robustly
    if isinstance(current_user, dict):
        company_id = current_user.get("company_id")
        user_id = current_user.get("id")
    else:
        company_id = getattr(current_user, "company_id", None)
        user_id = getattr(current_user, "id", None)

    with transactional(company_id) as db:
        try:
            # Resolve base currency
            from utils.accounting import get_base_currency
            base_currency = get_base_currency(db)
            
            # 1. Validate Supplier
            supplier = db.execute(text("SELECT * FROM parties WHERE id = :id AND is_supplier = TRUE"), {"id": invoice.supplier_id}).fetchone()
            if not supplier:
                raise HTTPException(**http_error(404, "supplier_not_found"))
    
            # 2. Generate Return Number (PR-YYYY-XXXX)
            year = date.today().year
            count = db.execute(text("SELECT count(*) FROM invoices WHERE invoice_type='purchase_return'")).scalar() or 0
            return_number = f"PR-{year}-{str(count + 1).zfill(4)}"
    
            # 3. Create Invoice Record (Type: purchase_return)
            # Calculate totals (including line discounts)
            subtotal = sum((_dec(item.quantity) * _dec(item.unit_price) - _dec(getattr(item, 'discount', 0) or 0)).quantize(_D2, ROUND_HALF_UP) for item in invoice.items)
            tax_total = sum(((_dec(item.quantity) * _dec(item.unit_price) - _dec(getattr(item, 'discount', 0) or 0)).quantize(_D2, ROUND_HALF_UP) * _dec(item.tax_rate) / Decimal('100')).quantize(_D2, ROUND_HALF_UP) for item in invoice.items)
            total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
    
            # Determine warehouse: Use original invoice's warehouse if possible
            wh_id = invoice.warehouse_id
            if not wh_id and invoice.original_invoice_id:
                # Try to fetch warehouse from original invoice (if stored in a column or logically linked)
                # Check if original invoice has a warehouse_id stored in its records
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
                 raise HTTPException(status_code=400, detail="يجب تعريف مستودع واحد على الأقل")
    
            # 3.5 Validate Warehouse-Branch Association (for Return)
            if wh_id and invoice.branch_id:
                wh_check = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": wh_id}).fetchone()
                if wh_check and wh_check[0] and wh_check[0] != invoice.branch_id:
                    raise HTTPException(status_code=400, detail="المستودع المختار لا يتبع للفرع الحالي")
    
            # Determine Branch
            branch_id = invoice.branch_id
            if not branch_id and invoice.original_invoice_id:
                branch_id = db.execute(text("SELECT branch_id FROM invoices WHERE id = :id"), {"id": invoice.original_invoice_id}).scalar()
    
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
            if invoice.paid_amount and invoice.paid_amount >= total - 0.01:
                return_status = 'paid'
            elif invoice.paid_amount and invoice.paid_amount > 0:
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
                "currency": invoice.currency or base_currency, "exchange_rate": invoice.exchange_rate or 1.0,
                "party_site_id": invoice.party_site_id,
            }).fetchone()[0]
    
            # 4. Add Items & Update Stock (DEDUCT)
            for item in invoice.items:
                item_total = ((_dec(item.quantity) * _dec(item.unit_price)) * (Decimal('1') + _dec(item.tax_rate) / Decimal('100'))).quantize(_D2, ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price,
                        tax_rate, discount, total
                    ) VALUES (
                        :iid, :pid, :desc, :qty, :price,
                        :tax, :disc, :total
                    )
                """), {
                    "iid": new_invoice_id, "pid": item.product_id, "desc": item.description,
                    "qty": item.quantity, "price": item.unit_price, "tax": item.tax_rate,
                    "disc": item.discount, "total": item_total
                })
    
                # Update Inventory (DECREASE QUANTITY)
                db.execute(text("""
                    UPDATE inventory 
                    SET quantity = quantity - :qty, last_movement_date = NOW()
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": abs(item.quantity), "pid": item.product_id, "wh": wh_id})
                
                # Log Transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, 
                        reference_type, reference_id,
                        quantity, notes, created_by
                    ) VALUES (
                        :pid, :wh, 'purchase_return',
                        'invoice', :ref_id,
                        :qty, 'مردود مشتريات', :uid
                    )
                """), {
                    "pid": item.product_id, "wh": wh_id, "ref_id": new_invoice_id,
                    "qty": -abs(item.quantity), "uid": user_id
                })
    
                # T3.9: reverse the original purchase's cost layer instead of
                # creating a new (positive) layer. handle_return now reduces the
                # remaining_quantity of the matching layer when we pass the
                # original purchase invoice id; this keeps FIFO/LIFO valuation
                # consistent across purchase returns.
                if invoice.original_invoice_id:
                    from services.costing_service import CostingService
                    try:
                        CostingService.handle_return(
                            db,
                            product_id=item.product_id,
                            warehouse_id=wh_id,
                            quantity=abs(item.quantity),
                            unit_cost=item.unit_price,
                            source_document_type="purchase_return",
                            source_document_id=new_invoice_id,
                            costing_method=CostingService.get_active_policy(db) or "fifo",
                            original_source_document_type="purchase_invoice",
                            original_source_document_id=invoice.original_invoice_id,
                        )
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
    
            # 5. Update Supplier Balance (Logic: Return reduces balance)
            exchange_rate = _dec(invoice.exchange_rate or 1)
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            def to_base(amount):
                return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
    
            gl_total = to_base(total)
            gl_subtotal = to_base(subtotal)
            gl_tax = to_base(tax_total)
    
            # Update supplier balance via party_site_balances
            update_party_site_balance(db, party_id=invoice.supplier_id, branch_id=branch_id,
                                      currency=invoice.currency or base_currency, amount=-float(gl_total))
    
            # 6. Accounting Entries (Return Itself)
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, invoice.invoice_date)
    
            # Credit: Inventory | Debit: Accounts Payable
            inventory_acc = get_mapped_account_id(db, "acc_map_inventory")
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
                if gl_tax > 0 and vat_acc:
                    je_lines.append({"account_id": vat_acc, "debit": 0, "credit": gl_tax, "description": "استرداد ضريبة", "amount_currency": tax_total, "currency": invoice.currency or base_currency})
    
                gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=str(invoice.invoice_date),
                    description=f"مردود مشتريات {return_number} ({invoice.currency})",
                    reference=return_number,
                    lines=je_lines,
                    user_id=user_id,
                    branch_id=invoice.branch_id,
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
                        currency, exchange_rate
                    ) VALUES (
                        :vnum, 'refund', :vdate, 'supplier', :supp,
                        :amt, :method, :notes, 'posted', :user,
                        :currency, :exchange_rate
                    ) RETURNING id
                """), {
                    "vnum": voucher_num, "vdate": invoice.invoice_date, "supp": invoice.supplier_id,
                    "amt": invoice.paid_amount, "method": invoice.payment_method or 'cash',
                    "notes": f"استرداد نقدي عن مردود {return_number}", "user": user_id,
                    "currency": invoice.currency or base_currency, "exchange_rate": exchange_rate
                }).fetchone()[0]
    
                # Allocation
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                """), {"vid": vid, "iid": new_invoice_id, "amt": invoice.paid_amount})
    
                # Update Supplier Balance via party_site_balances (Refund INCREASES balance: Debit Cash, Credit AP)
                update_party_site_balance(db, party_id=invoice.supplier_id, branch_id=branch_id,
                                          currency=invoice.currency or base_currency, amount=-float(gl_paid))
    
                # GL for Refund
                cash_acc = get_mapped_account_id(db, "acc_map_cash_main")
                if invoice.payment_method == 'bank': 
                    cash_acc = get_mapped_account_id(db, "acc_map_bank")
    
                if cash_acc and ap_acc:
                    je_lines_refund = [
                        {"account_id": cash_acc, "debit": gl_paid, "credit": 0, "description": "قبض", "amount_currency": invoice.paid_amount, "currency": invoice.currency or base_currency},
                        {"account_id": ap_acc, "debit": 0, "credit": gl_paid, "description": "تسوية مردود", "amount_currency": invoice.paid_amount, "currency": invoice.currency or base_currency}
                    ]
                    
                    gl_create_journal_entry(
                        db=db,
                        company_id=current_user.company_id,
                        date=str(invoice.invoice_date),
                        description=f"سند قبض مورد {voucher_num} ({invoice.currency})",
                        reference=voucher_num,
                        lines=je_lines_refund,
                        user_id=user_id,
                        branch_id=invoice.branch_id,
                        currency=invoice.currency or base_currency,
                        exchange_rate=1.0,  # amounts already in base currency
                        source="payment_voucher",
                        source_id=vid
                    )
    
    
            log_activity(
                db,
                user_id=user_id,
                username=getattr(current_user, "username", "unknown") if not isinstance(current_user, dict) else current_user.get("username", "unknown"),
                action="purchase_return.create",
                resource_type="invoice",
                resource_id=str(new_invoice_id),
                details={"return_number": return_number, "total": total, "supplier_id": invoice.supplier_id},
                request=request,
                branch_id=invoice.branch_id
            )
    
            return {"id": new_invoice_id, "message": "تم إنشاء مردود المشتريات بنجاح"}
    
        except ValueError as ve:
            pass
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            pass
            logger.error(f"Error creating return: {e}")
            raise HTTPException(status_code=500, detail="حدث خطأ أثناء إنشاء مردود المشتريات")

