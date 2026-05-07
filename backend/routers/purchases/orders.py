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


@router.get("/orders", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_orders(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض أوامر الشراء"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        query_str = """
            SELECT po.id, po.po_number, p.name as supplier_name, po.order_date, 
                   po.expected_date, po.total, po.status
            FROM purchase_orders po
            LEFT JOIN parties p ON po.party_id = p.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}
        
        query_str += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        
        query_str += " ORDER BY po.created_at DESC LIMIT :limit OFFSET :skip"
        
        result = db.execute(text(query_str), params).fetchall()
        
        return [{
            "id": row.id,
            "po_number": row.po_number,
            "supplier_name": row.supplier_name,
            "order_date": row.order_date,
            "expected_date": row.expected_date,
            "total": row.total,
            "status": row.status
        } for row in result]

@router.get("/orders/{id}", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchase_order(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل أمر الشراء"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        po = db.execute(text("""
            SELECT po.*, p.name as supplier_name, p.party_code as supplier_code 
            FROM purchase_orders po
            LEFT JOIN parties p ON po.party_id = p.id
            WHERE po.id = :id
        """), {"id": id}).fetchone()
        
        if not po:
            raise HTTPException(**http_error(404, "purchase_order_not_found"))
            
        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if po.branch_id:
            validate_branch_access(current_user, po.branch_id)
        
        if not po:
            raise HTTPException(**http_error(404, "purchase_order_not_found"))
            
        lines = db.execute(text("""
            SELECT l.*, p.product_name, p.product_code 
            FROM purchase_order_lines l
            LEFT JOIN products p ON l.product_id = p.id
            WHERE l.po_id = :id
        """), {"id": id}).fetchall()
        
        # Fetch Related Documents
        # 1. Journal Entries (Linked by Reference)
        jes = db.execute(text("""
            SELECT je.id, je.entry_number, je.entry_date, je.description,
                   COALESCE((SELECT SUM(jl.debit) FROM journal_lines jl WHERE jl.journal_entry_id = je.id), 0) as total_debit
            FROM journal_entries je
            WHERE je.status = 'posted' AND (je.reference = :ref OR je.description LIKE :desc_ref)
            ORDER BY je.entry_date DESC
        """), {"ref": po.po_number, "desc_ref": f"%{po.po_number}%"}).fetchall()
        
        po_data = {
            "id": po.id,
            "po_number": po.po_number,
            "supplier_id": po.party_id,
            "supplier_name": po.supplier_name,
            "supplier_code": po.supplier_code,
            "order_date": po.order_date,
            "expected_date": po.expected_date,
            "status": po.status,
            "subtotal": po.subtotal,
            "tax_amount": po.tax_amount,
            "discount": po.discount,
            "total": po.total,
            "branch_id": po.branch_id,
            "notes": po.notes,
            "currency": po.currency,
            "exchange_rate": po.exchange_rate,
            "items": [{
                "id": l.id,
                "product_id": l.product_id,
                "product_name": l.product_name or l.description,
                "product_code": l.product_code,
                "description": l.description,
                "quantity": l.quantity,
                "unit_price": l.unit_price,
                "tax_rate": l.tax_rate,
                "discount": l.discount,
                "total": l.total,
                "received_quantity": l.received_quantity
            } for l in lines],
            "related_documents": {
                "journal_entries": [{
                    "id": j.id,
                    "entry_number": j.entry_number,
                    "date": j.entry_date,
                    "description": j.description,
                    "amount": j.total_debit
                } for j in jes],
                # 3. Inventory Transactions
                "inventory_transactions": [{
                    "id": t.id,
                    "date": t.created_at,
                    "type": t.transaction_type,
                    "quantity": t.quantity,
                    "product_name": t.product_name
                } for t in db.execute(text("""
                    SELECT t.id, t.created_at, t.transaction_type, t.quantity, p.product_name
                    FROM inventory_transactions t
                    JOIN products p ON t.product_id = p.id
                    WHERE t.reference_document = :ref
                    ORDER BY t.created_at DESC
                """), {"ref": po.po_number}).fetchall()]
            }
        }
        
        return po_data

@router.post("/orders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_order(
    po: POCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء أمر شراء جديد"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            # Generate Sequential PO Number
            from utils.accounting import generate_sequential_number
            po_num = generate_sequential_number(db, f"PO-{datetime.now().year}", "purchase_orders", "po_number")
            
            # Calculate Totals (TASK-027: unified via compute_invoice_totals)
            from utils.accounting import compute_invoice_totals, compute_line_amounts
    
            lines_data = []
            for item in po.items:
                # Validate quantities and prices
                if _dec(item.quantity) <= 0:
                    raise HTTPException(status_code=400, detail=f"الكمية يجب أن تكون أكبر من صفر: {item.description}")
                if _dec(item.unit_price) < 0:
                    raise HTTPException(status_code=400, detail=f"سعر الوحدة لا يمكن أن يكون سالباً: {item.description}")
    
                line_total_gross = (_dec(item.quantity) * _dec(item.unit_price)).quantize(_D2, ROUND_HALF_UP)
                line_discount = _dec(item.discount)
                if line_discount < 0:
                    raise HTTPException(status_code=400, detail=f"الخصم لا يمكن أن يكون سالباً: {item.description}")
                if line_discount > line_total_gross:
                    raise HTTPException(status_code=400, detail=f"الخصم ({line_discount}) يتجاوز إجمالي السطر ({line_total_gross}): {item.description}")
    
                tax_info = resolve_line_tax(po.branch_id, item.product_id, db, po.order_date)
                la = compute_line_amounts(item.quantity, item.unit_price, tax_info["tax_rate"], item.discount)
                lines_data.append({
                    "product_id": item.product_id,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "tax_rate": tax_info["tax_rate"],
                    "tax_rate_id": tax_info["tax_rate_id"],
                    "discount": item.discount,
                    "total": str(la["line_total"]),
                })
    
            header_discount_pct = (
                _dec(po.effect_percentage)
                if getattr(po, "effect_type", "discount") == "discount"
                else Decimal("0")
            )
            markup_amount = (
                _dec(po.markup_amount)
                if getattr(po, "effect_type", "discount") == "markup"
                else Decimal("0")
            )

            totals = compute_invoice_totals([
                {
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "tax_rate": it["tax_rate"],
                    "discount": it["discount"],
                }
                for it in lines_data
            ], header_discount_pct=header_discount_pct, markup_amount=markup_amount)
            subtotal = totals["subtotal"]
            total_tax = totals["total_tax"]
            total_discount = totals["total_discount"]
            grand_total = totals["grand_total"]
            
            # Insert PO Header
            result = db.execute(text("""
                INSERT INTO purchase_orders (
                    po_number, party_id, branch_id, order_date, expected_date,
                    subtotal, tax_amount, discount, total, status, notes, created_by,
                    currency, exchange_rate, party_site_id
                ) VALUES (
                    :num, :supp, :bid, :date, :exp,
                    :sub, :tax, :disc, :total, 'draft', :notes, :user,
                    :currency, :exchange_rate, :party_site_id
                ) RETURNING id
            """), {
                "num": po_num,
                "supp": po.supplier_id,
                "bid": po.branch_id,
                "date": po.order_date,
                "exp": po.expected_date,
                "sub": subtotal,
                "tax": total_tax,
                "disc": total_discount,
                "total": grand_total,
                "notes": po.notes,
                "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                "currency": po.currency,
                "exchange_rate": po.exchange_rate,
                "party_site_id": po.party_site_id,
            }).fetchone()
            
            po_id = result[0]
            
            # Insert Lines
            for line in lines_data:
                db.execute(text("""
                    INSERT INTO purchase_order_lines (
                        po_id, product_id, description, quantity, unit_price, 
                        tax_rate, tax_rate_id, discount, total
                    ) VALUES (
                        :po_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :disc, :total
                    )
                """), {
                    "po_id": po_id,
                    "pid": line["product_id"],
                    "desc": line["description"],
                    "qty": line["quantity"],
                    "price": line["unit_price"],
                    "tax_rate": line["tax_rate"],
                    "tax_rate_id": line.get("tax_rate_id"),
                    "disc": line["discount"],
                    "total": line["total"]
                })
                
    
            supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": po.supplier_id}).scalar()
            # AUDIT LOG
            log_activity(
                db,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
                action="purchase_order.create",
                resource_type="purchase_order",
                resource_id=str(po_id),
                details={"po_number": po_num, "total": grand_total, "supplier_name": supp_name},
                request=request,
                branch_id=po.branch_id
            )
    
            # Submit for approval if workflow exists
            approval_result = None
            try:
                from utils.approval_utils import try_submit_for_approval
                user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
                approval_result = try_submit_for_approval(
                    db,
                    document_type="purchase_order",
                    document_id=po_id,
                    document_number=po_num,
                    amount=grand_total,
                    submitted_by=user_id,
                    description=f"أمر شراء {po_num} - {supp_name} - {grand_total:,.2f}",
                    link=f"/purchases/orders/{po_id}"
                )
                if approval_result:
                    db.commit()
            except Exception:
                pass  # Non-blocking
    
            response = {"message": "تم إنشاء أمر الشراء بنجاح", "id": po_id}
            if approval_result:
                response["approval"] = approval_result
            return response
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# === Purchase Order Approval & Receipt ===

@router.put("/orders/{id}/approve", dependencies=[Depends(require_permission("buying.approve"))], response_model=Dict[str, Any])
def approve_purchase_order(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد أمر الشراء"""
    with transactional(current_user.company_id) as db:
        try:
            # Check current status
            po = db.execute(text("""
                SELECT id, status, po_number, party_id as supplier_id, branch_id, total, order_date FROM purchase_orders WHERE id = :id
            """), {"id": id}).fetchone()
            
            if not po:
                raise HTTPException(**http_error(404, "purchase_order_not_found"))
            
            if po.status != 'draft':
                raise HTTPException(status_code=400, detail="يمكن اعتماد أوامر الشراء في حالة 'مسودة' فقط")
    
            # PUR-F1: Budget guard on PO approval.
            # When an active budget exists for the PO's branch/fiscal period,
            # refuse to approve if (used_budget + po.total) would exceed
            # total_budget, unless the caller has 'buying.override_budget'.
            try:
                perms = getattr(current_user, "permissions", []) or []
                can_override = "*" in perms or "buying.override_budget" in perms or "accounting.admin" in perms
                if not can_override and po.total and _dec(po.total) > 0:
                    po_year = po.order_date.year if po.order_date else None
                    bud = db.execute(text("""
                        SELECT id, total_budget, used_budget
                        FROM budgets
                        WHERE status = 'active'
                          AND (:branch IS NULL OR branch_id = :branch OR branch_id IS NULL)
                          AND (fiscal_year = :yr OR fiscal_year IS NULL)
                          AND (start_date IS NULL OR start_date <= :od)
                          AND (end_date   IS NULL OR end_date   >= :od)
                        ORDER BY (branch_id IS NULL) ASC, fiscal_year DESC NULLS LAST, id DESC
                        LIMIT 1
                    """), {"branch": po.branch_id, "yr": po_year, "od": po.order_date}).fetchone()
                    if bud and bud.total_budget and _dec(bud.total_budget) > 0:
                        remaining = _dec(bud.total_budget) - _dec(bud.used_budget or 0)
                        if _dec(po.total) > remaining:
                            raise HTTPException(
                                status_code=400,
                                detail=(
                                    f"تجاوز الميزانية: قيمة أمر الشراء {po.total} تتجاوز المتاح "
                                    f"{remaining} في الميزانية النشطة. "
                                    f"يلزم صلاحية buying.override_budget لتجاوز هذا القيد."
                                ),
                            )
            except HTTPException:
                raise
            except Exception as be:
                logger.warning(f"PUR-F1 budget check skipped (non-blocking): {be}")
    
            # Update status to approved
            db.execute(text("""
                UPDATE purchase_orders 
                SET status = 'approved', updated_at = NOW()
                WHERE id = :id
            """), {"id": id})
            
            
            # Get supplier info for notification
            supplier = db.execute(text("""
                SELECT name, email, phone FROM parties WHERE id = :id
            """), {"id": po.supplier_id}).fetchone()
            
            # AUDIT LOG
            log_activity(
                db,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
                action="purchase_order.approve",
                resource_type="purchase_order",
                resource_id=str(id),
                details={"po_number": po.po_number, "supplier_name": supplier.name if supplier else None},
                request=request,
                branch_id=None
            )
    
            # Notify purchasing team about PO approval
            try:
                db.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'purchase_order', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE
                    AND u.role IN ('admin', 'superuser')
                """), {
                    "title": "✅ تم اعتماد أمر شراء",
                    "message": f"تم اعتماد أمر الشراء {po.po_number}" + (f" — المورد: {supplier.name}" if supplier else ""),
                    "link": f"/buying/orders/{id}"
                })
                db.commit()
            except Exception:
                pass  # Non-blocking
    
            return {
                "message": "تم اعتماد أمر الشراء بنجاح",
                "id": id,
                "status": "approved",
                "supplier_notified": bool(supplier and (supplier.email or supplier.phone))
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.post("/orders/{id}/receive", dependencies=[Depends(require_permission("buying.receive"))], response_model=Dict[str, Any])
def receive_purchase_order(
    id: int,
    receive_data: POReceiveRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """استلام أمر الشراء (جزئي أو كامل)"""
    with transactional(current_user.company_id) as db:
        try:
            # Check PO exists and is approved
            po = db.execute(text("""
                SELECT id, status, po_number, party_id as supplier_id, branch_id, exchange_rate, currency 
                FROM purchase_orders WHERE id = :id
            """), {"id": id}).fetchone()
            
            if not po:
                raise HTTPException(**http_error(404, "purchase_order_not_found"))
            
            if po.status not in ('approved', 'partial'):
                raise HTTPException(status_code=400, detail="يجب اعتماد أمر الشراء أولاً قبل الاستلام")
    
            # QA-F1: block receiving when any quality inspection tied to this PO is FAILED.
            try:
                failed_insp = db.execute(text("""
                    SELECT COUNT(*) FROM quality_inspections
                    WHERE reference_type = 'purchase_order'
                      AND reference_id = :po_id
                      AND UPPER(COALESCE(status, '')) IN ('FAILED', 'REJECTED')
                """), {"po_id": id}).scalar() or 0
                if failed_insp > 0:
                    raise HTTPException(
                        status_code=409,
                        detail="لا يمكن استلام هذا الأمر: يوجد فحص جودة فاشل مرتبط به"
                    )
            except HTTPException:
                raise
            except Exception:
                # quality_inspections table may not exist yet on some tenants; skip silently.
                pass
    
            # Get all lines with their current received quantities
            lines = db.execute(text("""
                SELECT l.id, l.product_id, l.quantity, l.unit_price, COALESCE(l.received_quantity, 0) as received_quantity,
                       p.product_name
                FROM purchase_order_lines l
                LEFT JOIN products p ON l.product_id = p.id
                WHERE l.po_id = :po_id
            """), {"po_id": id}).fetchall()
            
            lines_map = {line.id: line for line in lines}
            
            # Process received items
            total_received = 0
            total_expected = 0
            receipt_details = []
            receipt_value_base = Decimal('0')
            exchange_rate = _dec(po.exchange_rate or 1)
            
            for item in receive_data.items:
                line = lines_map.get(item.line_id)
                if not line:
                    raise HTTPException(status_code=400, detail=f"البند {item.line_id} غير موجود في أمر الشراء")
                
                # Defensive quantity casting
                line_qty = _dec(line.quantity or 0)
                line_received = _dec(line.received_quantity or 0)
                item_qty = _dec(item.received_quantity or 0)
                
                remaining = line_qty - line_received
                if item_qty > remaining:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"الكمية المستلمة ({item_qty}) أكبر من المتبقية ({remaining}) للمنتج {line.product_name}"
                    )
                
                if item_qty > 0:
                    # Update received quantity on line
                    new_received = line_received + item_qty
                    db.execute(text("""
                        UPDATE purchase_order_lines 
                        SET received_quantity = :received
                        WHERE id = :line_id
                    """), {"received": new_received, "line_id": item.line_id})
                    
                    # Add to inventory
                    if line.product_id:
                        # Check if inventory record exists
                        existing = db.execute(text("""
                            SELECT id, quantity FROM inventory 
                            WHERE product_id = :pid AND warehouse_id = :wid
                            FOR UPDATE
                        """), {"pid": line.product_id, "wid": receive_data.warehouse_id}).fetchone()
                        
                        if existing:
                            db.execute(text("""
                                UPDATE inventory SET quantity = quantity + :qty, updated_at = NOW()
                                WHERE id = :id
                            """), {"qty": item_qty, "id": existing.id})
                        else:
                            db.execute(text("""
                                INSERT INTO inventory (product_id, warehouse_id, quantity, reserved_quantity)
                                VALUES (:pid, :wid, :qty, 0)
                            """), {"pid": line.product_id, "wid": receive_data.warehouse_id, "qty": item_qty})
                        
                        # Create inventory transaction (replacing non-existent stock_movements)
                        unit_price = _dec(line.unit_price or 0)
                        db.execute(text("""
                            INSERT INTO inventory_transactions (
                                product_id, warehouse_id, transaction_type, 
                                reference_type, reference_id, reference_document,
                                quantity, unit_cost, total_cost, created_by
                            ) VALUES (
                                :pid, :wid, 'purchase_in', 
                                'purchase_order', :po_id, :po_num,
                                :qty, :cost, :total_cost, :uid
                            )
                        """), {
                            "pid": line.product_id, 
                            "wid": receive_data.warehouse_id, 
                            "qty": item_qty,
                            "po_id": id,
                            "po_num": po.po_number,
                            "cost": unit_price,
                            "total_cost": _dec(item_qty) * unit_price,
                            "uid": int(current_user.get("id") if isinstance(current_user, dict) else current_user.id)
                        })
                    
                    receipt_details.append({
                        "product": line.product_name,
                        "received": str(item_qty)
                    })
                    
                    # Calculate accrual value
                    unit_price_base = (_dec(line.unit_price or 0) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
                    receipt_value_base += (_dec(item_qty) * unit_price_base).quantize(_D2, ROUND_HALF_UP)
            
            # Calculate new total received vs expected
            updated_lines = db.execute(text("""
                SELECT SUM(quantity) as total_qty, SUM(COALESCE(received_quantity, 0)) as total_received
                FROM purchase_order_lines WHERE po_id = :po_id
            """), {"po_id": id}).fetchone()
            
            total_expected_dec = _dec(updated_lines.total_qty or 0)
            total_received_dec = _dec(updated_lines.total_received or 0)
            
            # Determine new status
            if total_received_dec >= total_expected_dec:
                new_status = 'received'
            elif total_received_dec > 0:
                new_status = 'partial'
            else:
                new_status = po.status
            
            # Update PO status
            db.execute(text("""
                UPDATE purchase_orders SET status = :status WHERE id = :id
            """), {"status": new_status, "id": id})
            
            # --- ACCOUNTING ENTRY (ACCRUAL) ---
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, datetime.now().date())
    
            if receipt_value_base > _D2:
                acc_inventory = get_mapped_account_id(db, "acc_map_inventory")
                acc_unbilled = get_mapped_account_id(db, "acc_map_unbilled_purchases")
                
                if acc_inventory and acc_unbilled:
                    je_lines = [
                        {"account_id": acc_inventory, "debit": receipt_value_base, "credit": 0, "description": f"Inventory Receipt - {po.po_number}", "amount_currency": (receipt_value_base / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate else receipt_value_base, "currency": po.currency},
                        {"account_id": acc_unbilled, "debit": 0, "credit": receipt_value_base, "description": f"Unbilled Accrual - {po.po_number}", "amount_currency": (receipt_value_base / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate else receipt_value_base, "currency": po.currency}
                    ]
                    
                    gl_create_journal_entry(
                        db=db,
                        company_id=current_user.company_id,
                        date=str(datetime.now().date()),
                        description=f"استحقاق توريد بضاعة - {po.po_number}",
                        reference=po.po_number,
                        lines=je_lines,
                        user_id=int(current_user.get("id") if isinstance(current_user, dict) else current_user.id),
                        branch_id=po.branch_id,
                        currency=po.currency,
                        exchange_rate=1.0,  # amounts already in base currency
                        source="purchase_order_receipt",
                        source_id=id
                    )
            
            
            # AUDIT LOG
            log_activity(
                db,
                user_id=int(current_user.get("id") if isinstance(current_user, dict) else current_user.id),
                username=str(current_user.get("username") if isinstance(current_user, dict) else current_user.username),
                action="purchase_order.receive",
                resource_type="purchase_order",
                resource_id=str(id),
                details={
                    "po_number": str(po.po_number), 
                    "status": str(new_status),
                    "items_received": receipt_details
                },
                request=request,
                branch_id=int(po.branch_id) if po.branch_id else None
            )
            
            return {
                "message": "تم استلام البضاعة بنجاح",
                "id": int(id),
                "status": str(new_status),
                "total_expected": str(total_expected_dec),
                "total_received": str(total_received_dec),
                "remaining": str(total_expected_dec - total_received_dec)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# === Purchases Summary ===
@router.get("/summary", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchases_summary(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ملخص إحصائيات المشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        if branch_id:
            supplier_count = db.execute(text("""
                SELECT COUNT(DISTINCT party_id) FROM invoices 
                WHERE invoice_type = 'purchase' AND branch_id = :bid
            """), {"bid": branch_id}).scalar() or 0
            
            total_payables = db.execute(text("""
                SELECT COALESCE(SUM((total - paid_amount) * exchange_rate), 0) FROM invoices 
                WHERE invoice_type = 'purchase' AND branch_id = :bid AND status != 'paid'
            """), {"bid": branch_id}).scalar() or 0
        else:
            supplier_count = db.execute(text("SELECT COUNT(*) FROM parties WHERE is_supplier = TRUE")).scalar() or 0
            # Use party_site_balances for per-branch, per-currency balances
            total_balance = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0)
                FROM party_site_balances psb
                JOIN party_sites ps ON psb.party_site_id = ps.id
                JOIN parties p ON ps.party_id = p.id
                LEFT JOIN currencies c ON psb.currency = c.code
                WHERE (p.is_supplier = TRUE OR p.party_type = 'supplier')
                AND psb.balance < 0
            """)).scalar() or 0
            total_payables = abs(total_balance)
        
        # 3. Monthly Purchases (Total of invoices - returns in current month)
        first_day = date.today().replace(day=1)
        # Note: invoices now use party_id. We might need to join parties to ensure it's a supplier invoice? 
        # But invoice_type='purchase' is sufficient context usually.
        mp_query = """
            SELECT (
                (SELECT COALESCE(SUM(total * exchange_rate), 0) FROM invoices WHERE (invoice_type = 'purchase') AND status != 'cancelled' AND invoice_date >= :first_day {branch_filter}) -
                (SELECT COALESCE(SUM(total * exchange_rate), 0) FROM invoices WHERE (invoice_type = 'purchase_return') AND status != 'cancelled' AND invoice_date >= :first_day {branch_filter})
            )
        """
        mp_params = {"first_day": first_day}
        
        if branch_id:
             mp_params["bid"] = branch_id
             mp_query = mp_query.format(branch_filter="AND branch_id = :bid")
        else:
             mp_query = mp_query.format(branch_filter="")

        monthly_purchases = db.execute(text(mp_query), mp_params).scalar() or 0
        
        return {
            "supplier_count": supplier_count,
            "total_payables": total_payables,
            "monthly_purchases": monthly_purchases
        }

@router.get("/rfq", dependencies=[Depends(require_permission("buying.view"))], response_model=List[Dict[str, Any]])
def list_rfqs(status: Optional[str] = None, current_user=Depends(get_current_user)):
    """List Rfqs."""
    with transactional(current_user.company_id) as db:
        q = "SELECT * FROM request_for_quotations WHERE 1=1"
        params = {}
        if status:
            q += " AND status = :status"
            params["status"] = status
        q += " ORDER BY created_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
@router.get("/rfq/{rfq_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_rfq(rfq_id: int, current_user=Depends(get_current_user)):
    """Get RFQ."""
    with transactional(current_user.company_id) as db:
        rfq = db.execute(text("SELECT * FROM request_for_quotations WHERE id = :id"), {"id": rfq_id}).fetchone()
        if not rfq:
            raise HTTPException(status_code=404, detail="RFQ not found")
        lines = db.execute(text("SELECT * FROM rfq_lines WHERE rfq_id = :id"), {"id": rfq_id}).fetchall()
        responses = db.execute(text("SELECT * FROM rfq_responses WHERE rfq_id = :id ORDER BY total_price ASC"), {"id": rfq_id}).fetchall()
        return {
            "rfq": dict(rfq._mapping),
            "lines": [dict(r._mapping) for r in lines],
            "responses": [dict(r._mapping) for r in responses],
        }
@router.post("/rfq", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_rfq(data: dict, request: Request, current_user=Depends(get_current_user)):
    """Create RFQ."""
    with transactional(current_user.company_id) as db:
        try:
            import uuid
            rfq_num = f"RFQ-{uuid.uuid4().hex[:8].upper()}"
            rfq = db.execute(text("""
                INSERT INTO request_for_quotations (rfq_number, title, description, status, deadline, branch_id, created_by)
                VALUES (:num, :title, :desc, 'draft', :deadline, :branch, :uid)
                RETURNING *
            """), {
                "num": rfq_num, "title": data["title"], "desc": data.get("description"),
                "deadline": data.get("deadline"), "branch": data.get("branch_id"), "uid": current_user.id,
            }).fetchone()
            for line in data.get("lines", []):
                db.execute(text("""
                    INSERT INTO rfq_lines (rfq_id, product_id, product_name, quantity, unit, specifications)
                    VALUES (:rid, :pid, :pname, :qty, :unit, :specs)
                """), {"rid": rfq.id, "pid": line.get("product_id"), "pname": line.get("product_name"),
                       "qty": line["quantity"], "unit": line.get("unit"), "specs": line.get("specifications")})
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.rfq.create", resource_type="rfq",
                resource_id=str(rfq.id), details={"rfq_number": rfq_num, "title": data["title"]},
                request=request
            )
            return dict(rfq._mapping)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.put("/rfq/{rfq_id}/send", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def send_rfq(rfq_id: int, request: Request, current_user=Depends(get_current_user)):
    """Send RFQ."""
    with transactional(current_user.company_id) as db:
        db.execute(text("UPDATE request_for_quotations SET status = 'sent', updated_at = NOW() WHERE id = :id"), {"id": rfq_id})
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.rfq.send", resource_type="rfq",
            resource_id=str(rfq_id), details={},
            request=request
        )
        return {"message": "RFQ sent to suppliers"}
@router.post("/rfq/{rfq_id}/responses", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def add_rfq_response(rfq_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """Add RFQ Response."""
    with transactional(current_user.company_id) as db:
        try:
            result = db.execute(text("""
                INSERT INTO rfq_responses (rfq_id, supplier_id, supplier_name, unit_price, total_price, delivery_days, notes)
                VALUES (:rid, :sid, :sname, :uprice, :total, :days, :notes)
                RETURNING *
            """), {
                "rid": rfq_id, "sid": data["supplier_id"], "sname": data.get("supplier_name"),
                "uprice": data.get("unit_price", 0), "total": data.get("total_price", 0),
                "days": data.get("delivery_days"), "notes": data.get("notes"),
            }).fetchone()
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.rfq.add_response", resource_type="rfq_response",
                resource_id=str(result.id), details={"rfq_id": rfq_id, "supplier_id": data["supplier_id"]},
                request=request
            )
            return dict(result._mapping)
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/rfq/{rfq_id}/compare", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def compare_rfq_responses(rfq_id: int, current_user=Depends(get_current_user)):
    """Compare RFQ Responses."""
    with transactional(current_user.company_id) as db:
        responses = db.execute(text("""
            SELECT * FROM rfq_responses WHERE rfq_id = :rid ORDER BY total_price ASC
        """), {"rid": rfq_id}).fetchall()
        data = [dict(r._mapping) for r in responses]
        best = data[0] if data else None
        return {"responses": data, "recommended": best}
@router.post("/rfq/{rfq_id}/convert", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def convert_rfq_to_po(rfq_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """Convert selected RFQ response to Purchase Order."""
    with transactional(current_user.company_id) as db:
        try:
            response_id = data.get("response_id")
            resp = db.execute(text("SELECT * FROM rfq_responses WHERE id = :id AND rfq_id = :rid"),
                              {"id": response_id, "rid": rfq_id}).fetchone()
            if not resp:
                raise HTTPException(status_code=404, detail="Response not found")
            db.execute(text("UPDATE rfq_responses SET is_selected = true WHERE id = :id"), {"id": response_id})
            db.execute(text("UPDATE request_for_quotations SET status = 'converted', updated_at = NOW() WHERE id = :id"), {"id": rfq_id})
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.rfq.convert", resource_type="rfq",
                resource_id=str(rfq_id), details={"response_id": response_id, "supplier_id": resp.supplier_id},
                request=request
            )
            return {"message": "RFQ converted. Create PO from supplier.", "supplier_id": resp.supplier_id, "total_price": str(resp.total_price)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ---------- PUR-002: Supplier Ratings ----------

@router.get("/agreements", dependencies=[Depends(require_permission("buying.view"))], response_model=List[Dict[str, Any]])
def list_agreements(status: Optional[str] = None, current_user=Depends(get_current_user)):
    """List Agreements."""
    with transactional(current_user.company_id) as db:
        q = "SELECT * FROM purchase_agreements WHERE 1=1"
        params = {}
        if status:
            q += " AND status = :status"
            params["status"] = status
        q += " ORDER BY created_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
@router.get("/agreements/{agr_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_agreement(agr_id: int, current_user=Depends(get_current_user)):
    """Get Agreement."""
    with transactional(current_user.company_id) as db:
        agr = db.execute(text("SELECT * FROM purchase_agreements WHERE id = :id"), {"id": agr_id}).fetchone()
        if not agr:
            raise HTTPException(status_code=404, detail="Agreement not found")
        lines = db.execute(text("SELECT * FROM purchase_agreement_lines WHERE agreement_id = :id"), {"id": agr_id}).fetchall()
        return {"agreement": dict(agr._mapping), "lines": [dict(r._mapping) for r in lines]}
@router.post("/agreements", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_agreement(data: dict, request: Request, current_user=Depends(get_current_user)):
    """Create Agreement."""
    with transactional(current_user.company_id) as db:
        try:
            import uuid
            agr_num = f"PA-{uuid.uuid4().hex[:8].upper()}"
            total = sum((_dec(l.get("unit_price", 0)) * _dec(l.get("quantity", 0))) for l in data.get("lines", []))
            total = total.quantize(_D2, ROUND_HALF_UP)
            agr = db.execute(text("""
                INSERT INTO purchase_agreements (agreement_number, supplier_id, agreement_type, title,
                    start_date, end_date, total_amount, status, branch_id, created_by)
                VALUES (:num, :sid, :type, :title, :start, :end, :total, 'draft', :branch, :uid)
                RETURNING *
            """), {
                "num": agr_num, "sid": data["supplier_id"],
                "type": data.get("agreement_type", "blanket"), "title": data.get("title"),
                "start": data.get("start_date"), "end": data.get("end_date"),
                "total": total, "branch": data.get("branch_id"), "uid": current_user.id,
            }).fetchone()
            for line in data.get("lines", []):
                db.execute(text("""
                    INSERT INTO purchase_agreement_lines (agreement_id, product_id, product_name, quantity, unit_price)
                    VALUES (:aid, :pid, :pname, :qty, :price)
                """), {"aid": agr.id, "pid": line.get("product_id"), "pname": line.get("product_name"),
                       "qty": line.get("quantity", 0), "price": line.get("unit_price", 0)})
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.agreement.create", resource_type="purchase_agreement",
                resource_id=str(agr.id), details={"agreement_number": agr_num, "supplier_id": data["supplier_id"]},
                request=request
            )
            return dict(agr._mapping)
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.put("/agreements/{agr_id}/activate", dependencies=[Depends(require_permission("buying.approve"))], response_model=Dict[str, Any])
def activate_agreement(agr_id: int, request: Request, current_user=Depends(get_current_user)):
    """Activate Agreement."""
    with transactional(current_user.company_id) as db:
        db.execute(text("UPDATE purchase_agreements SET status = 'active' WHERE id = :id"), {"id": agr_id})
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.agreement.activate", resource_type="purchase_agreement",
            resource_id=str(agr_id), details={},
            request=request
        )
        return {"message": "Agreement activated"}
@router.post("/agreements/{agr_id}/call-off", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_call_off(agr_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """Create a call-off (partial order) against a blanket agreement."""
    with transactional(current_user.company_id) as db:
        try:
            agr = db.execute(text("SELECT * FROM purchase_agreements WHERE id = :id AND status = 'active'"), {"id": agr_id}).fetchone()
            if not agr:
                raise HTTPException(status_code=404, detail="Active agreement not found")
            amount = _dec(data.get("amount", 0))
            consumed_amount = _dec(agr.consumed_amount)
            total_amount = _dec(agr.total_amount)
            if consumed_amount + amount > total_amount:
                raise HTTPException(status_code=400, detail="Call-off exceeds agreement total")
            db.execute(text("UPDATE purchase_agreements SET consumed_amount = consumed_amount + :amt WHERE id = :id"),
                       {"amt": amount, "id": agr_id})
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.agreement.call_off", resource_type="purchase_agreement",
                resource_id=str(agr_id), details={"amount": str(amount)},
                request=request
            )
            remaining = (total_amount - consumed_amount - amount).quantize(_D2, ROUND_HALF_UP)
            return {"message": f"Call-off of {str(amount)} created", "remaining": str(remaining)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# =====================================================================
# Blanket Purchase Orders (US10)
# =====================================================================

from schemas.blanket_po import BlanketPOCreate, ReleaseOrderCreate, PriceAmendRequest

BLANKET_PO_STATUSES = {"draft", "active", "expired", "completed", "cancelled"}
