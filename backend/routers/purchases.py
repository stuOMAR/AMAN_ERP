from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import logging
from utils.cache import invalidate_company_cache

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal('0')

from database import get_db_connection
from routers.auth import get_current_user
from fastapi import Request
from utils.audit import log_activity
from utils.permissions import require_permission, require_module
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from schemas.purchases import PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest, SupplierPaymentCreate

router = APIRouter(prefix="/buying", tags=["Purchases"], dependencies=[Depends(require_module("buying"))])
logger = logging.getLogger(__name__)

# --- Endpoints ---

# === Supplier Groups ===

@router.get("/supplier-groups", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_supplier_groups(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض مجموعات الموردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        query = "SELECT * FROM supplier_groups WHERE 1=1"
        params = {}
        if branch_id:
            query += " AND (branch_id = :bid OR branch_id IS NULL)"
            params["bid"] = branch_id
        query += " ORDER BY id"
        result = db.execute(text(query), params).fetchall()
        groups = []
        for row in result:
            try:
                groups.append({
                    "id": row.id,
                    "group_name": row.group_name,
                    "group_name_en": row.group_name_en,
                    "description": row.description,
                    "discount_percentage": row.discount_percentage,
                    "effect_type": getattr(row, "effect_type", None),
                    "application_scope": getattr(row, "application_scope", None),
                    "payment_days": row.payment_days,
                    "status": row.status
                })
            except Exception as e:
                logger.error(f"Failed to parse supplier_group row: {e}")
        return groups
    finally:
        db.close()

@router.post("/supplier-groups", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))])
def create_supplier_group(
    group: SupplierGroupCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مجموعة موردين جديدة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        # Generate sequential group code
        from utils.accounting import generate_sequential_number
        group_code = generate_sequential_number(db, "SG", "supplier_groups", "group_code")
        
        db.execute(text("""
            INSERT INTO supplier_groups (
                group_code, group_name, group_name_en, description, 
                discount_percentage, payment_days, branch_id, status
            ) VALUES (
                :code, :name, :name_en, :desc, :disc, :days, :branch_id, :status
            )
        """), {
            "code": group_code,
            "name": group.group_name,
            "name_en": group.group_name_en,
            "desc": group.description,
            "disc": group.discount_percentage,
            "days": group.payment_days,
            "branch_id": group.branch_id,
            "status": group.status
        })
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="buying.supplier_group.create",
            resource_type="supplier_group",
            details={"group_name": group.group_name},
            request=request
        )
        return {"message": "تم إنشاء المجموعة بنجاح"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.put("/supplier-groups/{id}", dependencies=[Depends(require_permission("buying.edit"))])
def update_supplier_group(
    id: int,
    group: SupplierGroupCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث مجموعة موردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        result = db.execute(text("""
            UPDATE supplier_groups 
            SET group_name = :name,
                group_name_en = :name_en,
                description = :desc,
                discount_percentage = :disc,
                effect_type = :effect_type,
                application_scope = :application_scope,
                payment_days = :days,
                status = :status
            WHERE id = :id
        """), {
            "name": group.group_name,
            "name_en": group.group_name_en,
            "desc": group.description,
            "disc": group.discount_percentage,
            "effect_type": group.effect_type,
            "application_scope": group.application_scope,
            "days": group.payment_days,
            "status": group.status,
            "id": id
        })
        
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "group_not_found"))
            
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="buying.supplier_group.update",
            resource_type="supplier_group",
            resource_id=str(id),
            details={"group_name": group.group_name},
            request=request
        )
        return {"message": "تم تحديث المجموعة بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.delete("/supplier-groups/{id}", dependencies=[Depends(require_permission("buying.delete"))])
def delete_supplier_group(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف مجموعة موردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        # Check usage first
        usage = db.execute(text("SELECT COUNT(*) FROM parties WHERE party_group_id = :id"), {"id": id}).scalar()
        if usage > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف المجموعة لأنها مرتبطة بموردين")
            
        result = db.execute(text("DELETE FROM supplier_groups WHERE id = :id"), {"id": id})
        
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "group_not_found"))
            
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="buying.supplier_group.delete",
            resource_type="supplier_group",
            resource_id=str(id),
            details=None,
            request=request
        )
        return {"message": "تم حذف المجموعة بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# === Purchase Orders ===

@router.get("/orders", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_orders(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض أوامر الشراء"""
    from utils.permissions import validate_branch_access
    branch_id = validate_branch_access(current_user, branch_id)
    
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        query_str = """
            SELECT po.id, po.po_number, p.name as supplier_name, po.order_date, 
                   po.expected_date, po.total, po.status
            FROM purchase_orders po
            LEFT JOIN parties p ON po.party_id = p.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}
        
        if branch_id:
            query_str += " AND po.branch_id = :branch_id"
            params["branch_id"] = branch_id
        
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
    finally:
        db.close()

@router.get("/orders/{id}", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchase_order(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل أمر الشراء"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
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
            WHERE je.reference = :ref OR je.description LIKE :desc_ref
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
    finally:
        db.close()

@router.get("/suppliers/{id}/transactions", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_supplier_transactions(id: int, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """جلب سجل حركات المورد (فواتير ودفعات)"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        # 1. Fetch Invoices
        inv_query = """
            SELECT id, invoice_number, invoice_date, total, paid_amount, status, currency, exchange_rate
            FROM invoices
            WHERE party_id = :id AND invoice_type = 'purchase'
        """
        inv_params = {"id": id}
        
        from utils.accounting import get_base_currency
        from utils.permissions import validate_branch_access
        base_currency = get_base_currency(db)
        branch_id = validate_branch_access(current_user, branch_id)
        
        if branch_id:
            inv_query += " AND branch_id = :branch_id"
            inv_params["branch_id"] = branch_id
        
        inv_query += " ORDER BY invoice_date DESC"
        invoices_res = db.execute(text(inv_query), inv_params).fetchall()
        
        invoices = [{
            "id": r.id, 
            "invoice_number": r.invoice_number,
            "date": r.invoice_date,
            "total": str(_dec(r.total)), 
            "paid": str(_dec(r.paid_amount or 0)),
            "status": r.status,
            "currency": r.currency or base_currency,
            "exchange_rate": str(_dec(r.exchange_rate or 1.0))
        } for r in invoices_res]
        
        # Calculate total purchases in Base Currency
        total_purchases = sum((_dec(r.total) * _dec(r.exchange_rate or 1.0) for r in invoices_res), Decimal('0')).quantize(_D2, ROUND_HALF_UP)
        
        # 2. Fetch Payments (Vouchers)
        # Note: payment_vouchers table has currency field
        pay_query = """
            SELECT id, voucher_number, voucher_date, amount, payment_method, status, currency
            FROM payment_vouchers
            WHERE party_id = :id AND party_type = 'supplier' AND voucher_type = 'payment'
        """
        pay_params = {"id": id}
        if branch_id:
            pay_query += " AND branch_id = :branch_id"
            pay_params["branch_id"] = branch_id
            
        pay_query += " ORDER BY voucher_date DESC"
        payments_res = db.execute(text(pay_query), pay_params).fetchall()
        
        payments = [{
            "id": r.id,
            "voucher_number": r.voucher_number,
            "date": r.voucher_date,
            "amount": str(r.amount),
            "method": r.payment_method,
            "status": r.status,
            "currency": r.currency or base_currency
        } for r in payments_res]

        # 3. Fetch Receipts (Refund Vouchers)
        receipts_res = db.execute(text("""
            SELECT id, voucher_number, voucher_date, amount, payment_method, status, currency
            FROM payment_vouchers
            WHERE party_id = :id AND party_type = 'supplier' AND voucher_type = 'refund'
            ORDER BY voucher_date DESC
        """), {"id": id}).fetchall()
        
        receipts = [{
            "id": r.id,
            "voucher_number": r.voucher_number,
            "date": r.voucher_date,
            "amount": str(r.amount),
            "method": r.payment_method,
            "status": r.status,
            "currency": r.currency or base_currency
        } for r in receipts_res]

        # 4. Get basic info for header
        supplier = db.execute(text("SELECT name as supplier_name, current_balance, currency FROM parties WHERE id = :id"), {"id": id}).fetchone()
        
        supplier_currency = supplier.currency if supplier and supplier.currency else base_currency
        balance = _dec(supplier.current_balance or 0) if supplier else Decimal('0')
        exchange_rate = Decimal('1')
        
        if supplier_currency != base_currency:
             # Fetch current exchange rate
             rate_row = db.execute(text("SELECT current_rate FROM currencies WHERE code = :code"), {"code": supplier_currency}).scalar()
             if rate_row:
                   exchange_rate = _dec(rate_row)

        balance_bc = (balance * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        return {
            "supplier": {
                "name": supplier.supplier_name if supplier else "Unknown",
                "balance": str(balance.quantize(_D2, ROUND_HALF_UP)),
                "balance_bc": str(balance_bc),
                "currency": supplier_currency,
                "exchange_rate": str(exchange_rate),
                "total_purchases": str(total_purchases)
            },
            "invoices": invoices,
            "payments": payments,
            "receipts": receipts
        }
    finally:
        db.close()

@router.post("/orders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))])
def create_purchase_order(
    po: POCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء أمر شراء جديد"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
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

            la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate, item.discount)
            lines_data.append({
                "product_id": item.product_id,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "discount": item.discount,
                "total": str(la["line_total"]),
            })

        totals = compute_invoice_totals([
            {
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "discount": item.discount,
            }
            for item in po.items
        ])
        subtotal = totals["subtotal"]
        total_tax = totals["total_tax"]
        total_discount = totals["total_discount"]
        grand_total = totals["grand_total"]
        
        # Insert PO Header
        result = db.execute(text("""
            INSERT INTO purchase_orders (
                po_number, party_id, branch_id, order_date, expected_date,
                subtotal, tax_amount, discount, total, status, notes, created_by,
                currency, exchange_rate
            ) VALUES (
                :num, :supp, :bid, :date, :exp,
                :sub, :tax, :disc, :total, 'draft', :notes, :user,
                :currency, :exchange_rate
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
            "exchange_rate": po.exchange_rate
        }).fetchone()
        
        po_id = result[0]
        
        # Insert Lines
        for line in lines_data:
            db.execute(text("""
                INSERT INTO purchase_order_lines (
                    po_id, product_id, description, quantity, unit_price, 
                    tax_rate, discount, total
                ) VALUES (
                    :po_id, :pid, :desc, :qty, :price, :tax_rate, :disc, :total
                )
            """), {
                "po_id": po_id,
                "pid": line["product_id"],
                "desc": line["description"],
                "qty": line["quantity"],
                "price": line["unit_price"],
                "tax_rate": line["tax_rate"],
                "disc": line["discount"],
                "total": line["total"]
            })
            
        db.commit()

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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# === Purchase Order Approval & Receipt ===

@router.put("/orders/{id}/approve", dependencies=[Depends(require_permission("buying.approve"))])
def approve_purchase_order(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد أمر الشراء"""
    db = get_db_connection(current_user.company_id)
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
        
        db.commit()
        
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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.post("/orders/{id}/receive", dependencies=[Depends(require_permission("buying.receive"))])
def receive_purchase_order(
    id: int,
    receive_data: POReceiveRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """استلام أمر الشراء (جزئي أو كامل)"""
    db = get_db_connection(current_user.company_id)
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
                    exchange_rate=exchange_rate,
                    source="purchase_order_receipt",
                    source_id=id
                )
        
        db.commit()
        
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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# === Purchases Summary ===
@router.get("/summary", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchases_summary(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ملخص إحصائيات المشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
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
            total_balance = db.execute(text("SELECT COALESCE(SUM(current_balance), 0) FROM parties WHERE is_supplier = TRUE AND current_balance < 0")).scalar() or 0
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
    finally:
        db.close()

@router.get("/invoices", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_invoices(
    supplier_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض فواتير المشتريات"""
    from utils.permissions import validate_branch_access
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    validated_branch = validate_branch_access(current_user, branch_id)
    db = get_db_connection(company_id)
    try:
        query = """
            SELECT i.id, i.invoice_number, p.name as supplier_name, 
                   i.invoice_date, i.total, i.status
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase'
        """
        params = {"limit": limit, "skip": skip}
        
        if supplier_id:
            # Here 'supplier_id' parameter implies party_id of the supplier
            query += " AND i.party_id = :sid"
            params["sid"] = supplier_id
            
        if validated_branch:
            query += " AND i.branch_id = :bid"
            params["bid"] = validated_branch

        query += " ORDER BY i.created_at DESC LIMIT :limit OFFSET :skip"
        
        result = db.execute(text(query), params).fetchall()
        
        invoices = []
        for row in result:
            invoices.append({
                "id": row.id,
                "invoice_number": row.invoice_number,
                "supplier_name": row.supplier_name,
                "invoice_date": row.invoice_date,
                "total": row.total,
                "status": row.status
            })
        return invoices
    finally:
        db.close()

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
    db = get_db_connection(company_id)
    try:
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
    finally:
        db.close()

@router.post("/invoices", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))])
async def create_purchase_invoice(
    invoice: PurchaseCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مشتريات (إضافة للمخزون + قيد محاسبي)"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
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

        # 3. Calculate Totals (TASK-027: unified via compute_invoice_totals)
        from utils.accounting import compute_invoice_totals as _cit, compute_line_amounts as _cla

        lines_data = []
        for item in invoice.items:
            la = _cla(item.quantity, item.unit_price, item.tax_rate, item.discount)
            lines_data.append({
                "product_id": item.product_id,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "discount": item.discount,
                "markup": getattr(item, "markup", 0.0),
                "total": la["line_total"],
            })

        _totals = _cit([
            {
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "discount": item.discount,
            }
            for item in invoice.items
        ])
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
            "branch": invoice.branch_id,
            "wh": wh_id,
            "currency": inv_currency,
            "exchange_rate": exchange_rate,
            "effect_type": invoice.effect_type,
            "effect_perc": invoice.effect_percentage,
            "markup_amt": invoice.markup_amount
        }).fetchone()
        
        invoice_id = result[0]
        
        # 5. Insert Invoice Lines & Update Stock
        receipt_accrual_reversal_base = Decimal('0')

        for line in lines_data:
            db.execute(text("""
                INSERT INTO invoice_lines (
                    invoice_id, product_id, description, quantity, unit_price, 
                    tax_rate, discount, markup, total
                ) VALUES (
                    :inv_id, :pid, :desc, :qty, :price, :tax_rate, :disc, :markup, :total
                )
            """), {
                "inv_id": invoice_id,
                "pid": line["product_id"],
                "desc": line["description"],
                "qty": line["quantity"],
                "price": line["unit_price"],
                "tax_rate": line["tax_rate"],
                "disc": line["discount"],
                "markup": line.get("markup", 0.0),
                "total": line["total"]
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

        # 6. Update Supplier Balance (base + currency)
        if remaining_balance > _D2:
            gl_remaining = to_base(remaining_balance)
            db.execute(text("""
                UPDATE parties 
                SET current_balance = current_balance - :amount 
                WHERE id = :id
            """), {"amount": gl_remaining, "id": invoice.supplier_id})
            
            # Update balance_currency for FC invoices
            inv_currency = invoice.currency or base_currency
            if inv_currency != base_currency:
                db.execute(text("""
                    UPDATE parties
                    SET balance_currency = COALESCE(balance_currency, 0) - :amount
                    WHERE id = :id
                """), {"amount": remaining_balance, "id": invoice.supplier_id})
            
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
        acc_inventory = get_mapped_account_id(db, "acc_map_prepayment_supplier") if invoice.is_prepayment else get_mapped_account_id(db, "acc_map_inventory")
        acc_vat_in = get_mapped_account_id(db, "acc_map_vat_in")
        acc_ap = get_mapped_account_id(db, "acc_map_ap")
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_bank = get_mapped_account_id(db, "acc_map_bank")
        
        je_lines = []
        
        # Calculate Base Currency Amounts for GL
        gl_total = to_base(grand_total)
        gl_subtotal = to_base(subtotal)
        gl_tax = to_base(total_tax)
        gl_paid = to_base(paid_amount)
        gl_net_purchases = gl_subtotal - to_base(total_discount)

        # A. Inventory (Debit) - Net of Discount (Base Currency)
        # Handle Accrual Reversal if created from PO
        gl_inventory_debit = gl_net_purchases - receipt_accrual_reversal_base
        
        # FC equivalents for amount_currency
        fc_net_purchases = subtotal - total_discount
        fc_accrual_reversal = (receipt_accrual_reversal_base / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate != 0 else Decimal('0')
        fc_inventory_debit = fc_net_purchases - fc_accrual_reversal
        
        if gl_inventory_debit > _D2:
            je_lines.append({
                "account_id": acc_inventory, "debit": gl_inventory_debit, "credit": 0, 
                "description": f"Purchase Stock - {inv_num}",
                "amount_currency": fc_inventory_debit if inv_currency != base_currency else gl_inventory_debit,
                "currency": inv_currency
            })
        
        if receipt_accrual_reversal_base > _D2:
            acc_unbilled = get_mapped_account_id(db, "acc_map_unbilled_purchases")
            if acc_unbilled:
                je_lines.append({
                    "account_id": acc_unbilled, "debit": receipt_accrual_reversal_base, "credit": 0, 
                    "description": f"Reverse Unbilled Accrual - {inv_num}",
                    "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                    "currency": inv_currency
                })
                # Balance update handled by the JE lines loop below
            else:
                 # Fallback if mapping missing but we have reversal value (should not happen if system setup right)
                 je_lines.append({
                     "account_id": acc_inventory, "debit": receipt_accrual_reversal_base, "credit": 0, 
                     "description": f"Purchase Stock (No Accrual Map) - {inv_num}",
                     "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                     "currency": inv_currency
                 })
            
        # B. VAT Input (Debit) (Base Currency)
        if gl_tax > 0:
            je_lines.append({
                "account_id": acc_vat_in, "debit": gl_tax, "credit": 0, 
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
                  
                  if invoice.treasury_id:
                       t_acc = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": invoice.treasury_id}).fetchone()
                       if t_acc:
                            cash_acc_id = t_acc[0]

                  je_lines.append({
                      "account_id": cash_acc_id, "debit": 0, "credit": gl_paid, 
                      "description": f"Purchase {actual_pay_method.capitalize()} - {inv_num}",
                      "amount_currency": paid_amount, "currency": inv_currency
                  })
             elif actual_pay_method == "bank":
                  # Use selected treasury account if provided, else fallback to default bank map
                  bank_acc_id = acc_bank
                  if invoice.treasury_id:
                       t_acc = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": invoice.treasury_id}).fetchone()
                       if t_acc:
                            bank_acc_id = t_acc[0]
                  je_lines.append({
                      "account_id": bank_acc_id, "debit": 0, "credit": gl_paid, 
                      "description": f"Purchase Bank - {inv_num}",
                      "amount_currency": paid_amount, "currency": inv_currency
                  })
        
        remaining_gl = gl_total - gl_paid     
        if remaining_gl > _D2:
             je_lines.append({
                 "account_id": acc_ap, "debit": 0, "credit": remaining_gl, 
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

        db.commit()

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

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating purchase invoice: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# === Purchase Returns ===

@router.get("/returns", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_returns(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض مردودات المشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

        query_str = """
            SELECT i.id, i.invoice_number, p.name as supplier_name, 
                   i.invoice_date, i.total, i.status
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase_return'
        """
        params = {"limit": limit, "skip": skip}
        
        if branch_id:
            query_str += " AND i.branch_id = :branch_id"
            params["branch_id"] = branch_id
            
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
    finally:
        db.close()

@router.get("/returns/{id}", dependencies=[Depends(require_permission("buying.view"))])
def get_purchase_return(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل مردود مشتريات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
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
    finally:
        db.close()

@router.post("/returns", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))])
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

    db = get_db_connection(company_id)
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
                currency, exchange_rate
            ) VALUES (
                :num, :pid, :date, :due,
                :sub, :tax, :total, :paid,
                :status, 'purchase_return', :notes, :uid, :rel_id, :bid,
                :currency, :exchange_rate
            ) RETURNING id
        """), {
            "num": return_number, "pid": invoice.supplier_id, "date": invoice.invoice_date,
            "due": invoice.due_date, "sub": subtotal, "tax": tax_total, "total": total,
            "paid": invoice.paid_amount or 0,
            "status": return_status, "notes": invoice.notes, "uid": user_id,
            "rel_id": invoice.original_invoice_id, "bid": branch_id,
            "currency": invoice.currency or base_currency, "exchange_rate": invoice.exchange_rate or 1.0
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

        db.execute(text("""
            UPDATE parties 
            SET current_balance = COALESCE(current_balance, 0) + :amount 
            WHERE id = :id
        """), {"amount": gl_total, "id": invoice.supplier_id})

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
                exchange_rate=exchange_rate,
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

            # Update Supplier Balance (Refund INCREASES balance: Debit Cash, Credit AP)
            db.execute(text("""
                UPDATE parties
                SET current_balance = COALESCE(current_balance, 0) - :amt
                WHERE id = :sid
            """), {"amt": gl_paid, "sid": invoice.supplier_id})

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
                    exchange_rate=exchange_rate,
                    source="payment_voucher",
                    source_id=vid
                )

        db.commit()

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
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating return: {e}")
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء إنشاء مردود المشتريات")
    finally:
        db.close()

@router.post("/payments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))])
def create_supplier_payment(request: Request, data: SupplierPaymentCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء سند صرف/قبض لمورد"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import generate_sequential_number, get_base_currency
        base_currency = get_base_currency(db)
        # Validate amount
        if data.amount is None or data.amount <= 0:
            raise HTTPException(**http_error(400, "amount_must_be_positive"))

        # Fiscal-period lock: payment voucher posts at voucher_date.
        check_fiscal_period_open(db, data.voucher_date)
        
        # Check supplier balance (total owed)
        supplier_balance = db.execute(text("""
            SELECT COALESCE(current_balance, 0) as balance
            FROM parties
            WHERE id = :sid
            FOR UPDATE
        """), {"sid": data.supplier_id}).fetchone()
        if not supplier_balance:
            raise HTTPException(**http_error(404, "supplier_not_found"))
        
        # For payments (not refunds), warn if paying more than owed
        voucher_rate = _dec(data.exchange_rate or 1)
        if voucher_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
        if data.voucher_type != 'refund' and amount_base > (_dec(supplier_balance.balance) + _D2):
            # Allow overpayment but log warning (some businesses prepay)
            logger.warning(f"Supplier payment {data.amount} exceeds balance {supplier_balance.balance} for supplier {data.supplier_id}")
        
        # Prefix based on type
        prefix = "PAY" if data.voucher_type != 'refund' else "RCT"
        voucher_num = generate_sequential_number(db, f"{prefix}-{date.today().year}", "payment_vouchers", "voucher_number")
        
        # 1. Insert Voucher Header
        result = db.execute(text("""
            INSERT INTO payment_vouchers (
                voucher_number, voucher_type, voucher_date, party_type, party_id, 
                amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                reference, notes, status, created_by, branch_id, currency, exchange_rate
            ) VALUES (
                :vnum, :type, :vdate, 'supplier', :supp,
                :amt, :method, :bank, :treasury, :check_num, :check_date,
                :ref, :notes, 'posted', :user, :bid, :curr, :rate
            ) RETURNING id
        """), {
            "vnum": voucher_num, "type": data.voucher_type or 'payment', "vdate": data.voucher_date, "supp": data.supplier_id,
            "amt": data.amount, "method": data.payment_method, 
            "bank": data.bank_account_id if data.payment_method != 'cash' else None,
            "treasury": data.treasury_account_id or (data.bank_account_id if data.payment_method == 'cash' else None), 
            "check_num": data.check_number, "check_date": data.check_date,
            "ref": data.reference, "notes": data.notes, "user": current_user.id, "bid": data.branch_id,
            "curr": data.currency, "rate": data.exchange_rate or 1.0
        }).fetchone()
        
        voucher_id = result[0]
        
        # 2. Process Allocations
        total_allocated = Decimal('0')
        for alloc in data.allocations:
            if alloc.allocated_amount is None or alloc.allocated_amount <= 0:
                raise HTTPException(status_code=400, detail="قيمة التخصيص يجب أن تكون أكبر من صفر")

            inv_row = db.execute(text("""
                SELECT id, party_id, invoice_type, total, COALESCE(paid_amount, 0) AS paid_amount,
                       currency, exchange_rate
                FROM invoices
                WHERE id = :id
                FOR UPDATE
            """), {"id": alloc.invoice_id}).fetchone()
            if not inv_row:
                raise HTTPException(status_code=404, detail=f"الفاتورة {alloc.invoice_id} غير موجودة")
            if int(inv_row.party_id) != int(data.supplier_id):
                raise HTTPException(status_code=400, detail=f"الفاتورة {alloc.invoice_id} لا تتبع المورد المحدد")
            if inv_row.invoice_type != 'purchase':
                raise HTTPException(status_code=400, detail=f"التخصيص مسموح لفواتير الشراء فقط. الفاتورة {alloc.invoice_id} نوعها {inv_row.invoice_type}")

            alloc_amount = _dec(alloc.allocated_amount)
            total_allocated = (total_allocated + alloc_amount).quantize(_D4, ROUND_HALF_UP)

            db.execute(text("""
                INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                VALUES (:vid, :iid, :amt)
            """), {"vid": voucher_id, "iid": alloc.invoice_id, "amt": alloc_amount})
            
            inv_curr = inv_row.currency or base_currency
            inv_rate = _dec(inv_row.exchange_rate or 1)
            if inv_rate <= 0:
                raise HTTPException(status_code=400, detail=f"سعر صرف الفاتورة {alloc.invoice_id} غير صالح")

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
        
        # 3. Update Supplier Balance (Base + Currency)
        amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
        balance_change = amount_base if data.voucher_type != 'refund' else -amount_base
        
        # Update base currency balance
        db.execute(text("""
            UPDATE parties
            SET current_balance = COALESCE(current_balance, 0) + :change
            WHERE id = :sid
        """), {"change": balance_change, "sid": data.supplier_id})
        
        # Update foreign currency balance if applicable
        balance_change_fc = _dec(data.amount) if data.voucher_type != 'refund' else -_dec(data.amount)
        if data.currency and data.currency != base_currency:
            db.execute(text("""
                UPDATE parties
                SET balance_currency = COALESCE(balance_currency, 0) + :change
                WHERE id = :sid
            """), {"change": balance_change_fc, "sid": data.supplier_id})
        
        # 4. Create GL Entry
        # Dynamic Treasury Lookup
        treasury_id = data.treasury_account_id or data.bank_account_id
        cash_acc = None
        treasury_curr = data.currency
        treasury_rate = voucher_rate
        amount_treasury_curr = _dec(data.amount)
        
        if treasury_id:
            # Fetch treasury account details
            treasury = db.execute(text("SELECT gl_account_id, currency FROM treasury_accounts WHERE id = :id"), {"id": treasury_id}).fetchone()
            if treasury:
                cash_acc = treasury.gl_account_id
                treasury_curr = treasury.currency or data.currency
                
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
                
                # Update Treasury account specific balance
                # Payment decreases balance (Credit Asset), Refund increases balance (Debit Asset)
                if data.voucher_type == 'refund':
                    balance_change_treasury = abs(amount_treasury_curr)
                else:
                    balance_change_treasury = -abs(amount_treasury_curr)

                db.execute(text("""
                    UPDATE treasury_accounts
                    SET current_balance = COALESCE(current_balance, 0) + :change
                    WHERE id = :id
                """), {"change": balance_change_treasury, "id": treasury_id})
        
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
                je_lines.append({"account_id": ap_acc, "debit": 0, "credit": amount_base, "description": "من مورد", "amount_currency": data.amount, "currency": data.currency})
            else:
                # Payment: Debit AP, Credit Cash
                je_lines.append({"account_id": ap_acc, "debit": amount_base, "credit": 0, "description": "صرف", "amount_currency": data.amount, "currency": data.currency})
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
                company_id=current_user.company_id,
                date=str(data.voucher_date),
                description=f"{'سند قبض من' if data.voucher_type=='refund' else 'سند صرف لـ'} مورد {voucher_num} ({data.currency})",
                reference=voucher_num,
                lines=je_lines,
                user_id=current_user.id,
                branch_id=data.branch_id,
                currency=data.currency,
                exchange_rate=data.exchange_rate or 1.0,
                source="payment_voucher",
                source_id=voucher_id
            )

        db.commit()
        invalidate_company_cache(str(current_user.company_id))
        

        supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.supplier_id}).scalar()
        log_activity(
            db_conn=db,
            user_id=current_user.id,
            username=current_user.username,
            action="buying.supplier_payment.create",
            resource_type="payment_voucher",
            resource_id=str(voucher_id),
            details={"voucher_number": voucher_num, "amount": data.amount, "supplier_name": supp_name},
            request=request,
            branch_id=data.branch_id
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
                "title": "💳 تم صرف سند لمورد",
                "message": f"تم صرف {data.amount:,.2f} للمورد {supp_name or ''} — سند {voucher_num}",
                "link": f"/buying/payments/{voucher_id}",
                "current_uid": current_user.id
            })
            db.commit()
        except Exception:
            pass

        return {"id": voucher_id, "message": "تم حفظ السند بنجاح"}

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating payment: {e}")
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء إنشاء سند الصرف")
    finally:
        db.close()
        
@router.get("/payments", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def list_supplier_payments(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """قائمة سندات الصرف"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

        query_str = """
            SELECT pv.id, pv.voucher_number, pv.voucher_date, pv.amount, pv.currency,
                   pv.payment_method, pv.status, p.name as supplier_name
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.voucher_type = 'payment' AND pv.party_type = 'supplier'
        """
        params = {}
        if branch_id:
            query_str += " AND (pv.branch_id = :branch_id OR pv.branch_id IS NULL)"
            params["branch_id"] = branch_id
        
        query_str += " ORDER BY pv.created_at DESC"
        
        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error listing payments: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/payments/{voucher_id}", response_model=dict, dependencies=[Depends(require_permission("buying.view"))])
def get_payment_details(voucher_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل سند صرف"""
    db = get_db_connection(current_user.company_id)
    try:
        header = db.execute(text("""
            SELECT pv.*, p.name as party_name, p.party_code
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.id = :id AND pv.party_type = 'supplier' AND pv.voucher_type = 'payment'
        """), {"id": voucher_id}).fetchone()
        
        if not header:
            raise HTTPException(status_code=404, detail="Payment not found")

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, header._mapping.get("branch_id"))

        allocations = db.execute(text("""
            SELECT pa.*, i.invoice_number
            FROM payment_allocations pa
            JOIN invoices i ON pa.invoice_id = i.id
            WHERE pa.voucher_id = :id
        """), {"id": voucher_id}).fetchall()
        
        return {
            **dict(header._mapping),
            "allocations": [dict(a._mapping) for a in allocations]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payment: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/suppliers/{supplier_id}/outstanding-invoices", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_supplier_outstanding_invoices(
    supplier_id: int, 
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Fetch unpaid/partial purchase invoices for a supplier"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT id, invoice_number, invoice_date, total, paid_amount, status, invoice_type,
                   currency, exchange_rate,
                   (total - COALESCE(paid_amount, 0)) as remaining_balance
            FROM invoices
            WHERE party_id = :sid
              AND invoice_type IN ('purchase', 'purchase_return')
              AND status IN ('unpaid', 'partial', 'posted')
        """
        params = {"sid": supplier_id}
        if branch_id:
            query += " AND branch_id = :bid"
            params["bid"] = branch_id
        
        query += " ORDER BY invoice_date ASC"
        
        result = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error fetching outstanding invoices: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.get("/invoices/{invoice_id}/payment-history", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_invoice_payment_history(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """سجل الدفعات لفاتورة شراء معينة"""
    db = get_db_connection(current_user.company_id)
    try:
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
    finally:
        db.close()
# ==================== INV-003: Purchase Credit Notes (إشعار دائن مشتريات) ====================
# Credit Note from Supplier: Reduces what we owe (e.g., supplier overcharged us, returns to supplier)
# GL: Debit AP (reduce payable), Credit Inventory/Expense + VAT Input

@router.get("/credit-notes", dependencies=[Depends(require_permission("buying.view"))])
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
    db = get_db_connection(current_user.company_id)
    try:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

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
        if branch_id:
            conditions.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa: sql-lint

        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa: sql-lint
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
    finally:
        db.close()
@router.get("/credit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))])
def get_purchase_credit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار دائن مشتريات"""
    db = get_db_connection(current_user.company_id)
    try:
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
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
    finally:
        db.close()
@router.post("/credit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))])
def create_purchase_credit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار دائن مشتريات
    GL: Debit AP, Credit Purchases/Inventory + VAT Input
    """
    db = get_db_connection(current_user.company_id)
    try:
        party_id = data.get("party_id")
        related_invoice_id = data.get("related_invoice_id")
        lines = data.get("lines", [])
        if not lines:
            raise HTTPException(**http_error(400, "min_one_item_required"))
        if not party_id:
            raise HTTPException(status_code=400, detail="يجب تحديد المورد")

        if related_invoice_id:
            orig = db.execute(text(
                "SELECT id, party_id, invoice_type FROM invoices WHERE id = :id"
            ), {"id": related_invoice_id}).fetchone()
            if not orig or orig.party_id != party_id:
                raise HTTPException(status_code=400, detail="الفاتورة المرتبطة غير موجودة أو لا تخص هذا المورد")

        inv_date = data.get("invoice_date", str(date.today()))
        base_currency = get_base_currency(db)
        currency = data.get("currency", base_currency)
        exchange_rate = _dec(data.get("exchange_rate", 1))
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        branch_id = data.get("branch_id") or (current_user.allowed_branches[0] if current_user.allowed_branches else None)

        subtotal = Decimal('0')
        tax_total = Decimal('0')
        discount_total = Decimal('0')
        computed_lines = []

        for line in lines:
            qty = _dec(line.get("quantity", 1))
            price = _dec(line.get("unit_price", 0))
            tax_rate = _dec(line.get("tax_rate", 0))
            disc = _dec(line.get("discount", 0))
            line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
            line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
            subtotal += line_net
            tax_total += line_tax
            discount_total += disc
            computed_lines.append({
                "product_id": line.get("product_id"),
                "description": line.get("description", ""),
                "quantity": qty, "unit_price": price,
                "tax_rate": tax_rate, "discount": disc, "total": line_total,
            })

        total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)

        inv_num = generate_sequential_number(db, "PCN", "invoices", "invoice_number")
        result = db.execute(text("""
            INSERT INTO invoices (
                invoice_number, invoice_type, party_id, invoice_date,
                subtotal, tax_amount, discount, total, paid_amount, status,
                notes, branch_id, related_invoice_id, currency, exchange_rate, created_by
            ) VALUES (
                :num, 'purchase_credit_note', :party, :date,
                :sub, :tax, :disc, :total, 0, 'posted',
                :notes, :branch, :rel, :curr, :rate, :user
            ) RETURNING id
        """), {
            "num": inv_num, "party": party_id, "date": inv_date,
            "sub": subtotal, "tax": tax_total, "disc": discount_total,
            "total": total, "notes": data.get("notes", ""),
            "branch": branch_id, "rel": related_invoice_id,
            "curr": currency, "rate": exchange_rate, "user": current_user.id,
        })
        note_id = result.fetchone()[0]

        for cl in computed_lines:
            db.execute(text("""
                INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:inv, :prod, :desc, :qty, :price, :tax, :disc, :total)
            """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                   "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                   "disc": cl["discount"], "total": cl["total"]})

        # GL: Debit AP, Credit Inventory + VAT
        acc_ap = get_mapped_account_id(db, "acc_map_ap")
        acc_inv = get_mapped_account_id(db, "acc_map_inventory")
        acc_vat = get_mapped_account_id(db, "acc_map_vat_in")

        if not acc_ap or not acc_inv:
            raise HTTPException(status_code=400, detail="إعدادات الحسابات غير مكتملة (AP / Inventory)")

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
            company_id=current_user.company_id,
            date=str(inv_date),
            description=f"إشعار دائن مشتريات {inv_num}",
            reference=inv_num,
            lines=je_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            currency=currency,
            exchange_rate=exchange_rate,
            source="purchase_credit_note",
            source_id=note_id
        )

        # Reduce related invoice balance
        if related_invoice_id:
            db.execute(text("""
                UPDATE invoices SET paid_amount = paid_amount + :amt,
                    status = CASE WHEN paid_amount + :amt >= total THEN 'paid' WHEN paid_amount + :amt > 0 THEN 'partial' ELSE status END
                WHERE id = :id
            """), {"amt": total, "id": related_invoice_id})

        # Update supplier balance (credit note REDUCES what we owe supplier)
        gl_total_base = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
        db.execute(text("""
            UPDATE parties SET current_balance = current_balance - :amt
            WHERE id = :pid
        """), {"amt": gl_total_base, "pid": party_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="buying.credit_note.create", resource_type="purchase_credit_note",
                     resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                     request=request, branch_id=branch_id)

        return {"success": True, "id": note_id, "invoice_number": inv_num,
                "journal_entry_id": je_id, "message": f"تم إنشاء الإشعار الدائن {inv_num} بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating purchase credit note: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# ==================== INV-004: Purchase Debit Notes (إشعار مدين مشتريات) ====================
# Debit Note to Supplier: Increases what we owe (e.g., undercharged, additional services)
# GL: Debit Inventory/Expense + VAT Input, Credit AP

@router.get("/debit-notes", dependencies=[Depends(require_permission("buying.view"))])
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
    db = get_db_connection(current_user.company_id)
    try:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

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
        if branch_id:
            conditions.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa: sql-lint
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa: sql-lint
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
    finally:
        db.close()
@router.get("/debit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))])
def get_purchase_debit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار مدين مشتريات"""
    db = get_db_connection(current_user.company_id)
    try:
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
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
    finally:
        db.close()
@router.post("/debit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))])
def create_purchase_debit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار مدين مشتريات
    GL: Debit Inventory/Expense + VAT Input, Credit AP
    """
    db = get_db_connection(current_user.company_id)
    try:
        party_id = data.get("party_id")
        related_invoice_id = data.get("related_invoice_id")
        lines = data.get("lines", [])
        if not lines:
            raise HTTPException(**http_error(400, "min_one_item_required"))
        if not party_id:
            raise HTTPException(status_code=400, detail="يجب تحديد المورد")

        inv_date = data.get("invoice_date", str(date.today()))
        base_currency = get_base_currency(db)
        currency = data.get("currency", base_currency)
        exchange_rate = _dec(data.get("exchange_rate", 1))
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        branch_id = data.get("branch_id") or (current_user.allowed_branches[0] if current_user.allowed_branches else None)

        subtotal = Decimal('0')
        tax_total = Decimal('0')
        discount_total = Decimal('0')
        computed_lines = []

        for line in lines:
            qty = _dec(line.get("quantity", 1))
            price = _dec(line.get("unit_price", 0))
            tax_rate = _dec(line.get("tax_rate", 0))
            disc = _dec(line.get("discount", 0))
            line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
            line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
            subtotal += line_net
            tax_total += line_tax
            discount_total += disc
            computed_lines.append({
                "product_id": line.get("product_id"),
                "description": line.get("description", ""),
                "quantity": qty, "unit_price": price,
                "tax_rate": tax_rate, "discount": disc, "total": line_total,
            })

        total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)

        inv_num = generate_sequential_number(db, "PDN", "invoices", "invoice_number")
        result = db.execute(text("""
            INSERT INTO invoices (
                invoice_number, invoice_type, party_id, invoice_date,
                subtotal, tax_amount, discount, total, paid_amount, status,
                notes, branch_id, related_invoice_id, currency, exchange_rate, created_by
            ) VALUES (
                :num, 'purchase_debit_note', :party, :date,
                :sub, :tax, :disc, :total, 0, 'unpaid',
                :notes, :branch, :rel, :curr, :rate, :user
            ) RETURNING id
        """), {
            "num": inv_num, "party": party_id, "date": inv_date,
            "sub": subtotal, "tax": tax_total, "disc": discount_total,
            "total": total, "notes": data.get("notes", ""),
            "branch": branch_id, "rel": related_invoice_id,
            "curr": currency, "rate": exchange_rate, "user": current_user.id,
        })
        note_id = result.fetchone()[0]

        for cl in computed_lines:
            db.execute(text("""
                INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:inv, :prod, :desc, :qty, :price, :tax, :disc, :total)
            """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                   "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                   "disc": cl["discount"], "total": cl["total"]})

        # GL: Debit Inventory + VAT, Credit AP
        acc_ap = get_mapped_account_id(db, "acc_map_ap")
        acc_inv = get_mapped_account_id(db, "acc_map_inventory")
        acc_vat = get_mapped_account_id(db, "acc_map_vat_in")

        if not acc_ap or not acc_inv:
            raise HTTPException(status_code=400, detail="إعدادات الحسابات غير مكتملة (AP / Inventory)")

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
            company_id=current_user.company_id,
            date=str(inv_date),
            description=f"إشعار مدين مشتريات {inv_num}",
            reference=inv_num,
            lines=je_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            currency=currency,
            exchange_rate=exchange_rate,
            source="purchase_debit_note",
            source_id=note_id
        )

        # Update supplier balance (debit note INCREASES what we owe supplier)
        gl_total_base = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
        db.execute(text("""
            UPDATE parties SET current_balance = current_balance + :amt
            WHERE id = :pid
        """), {"amt": gl_total_base, "pid": party_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="buying.debit_note.create", resource_type="purchase_debit_note",
                     resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                     request=request, branch_id=branch_id)

        return {"success": True, "id": note_id, "invoice_number": inv_num,
                "journal_entry_id": je_id, "message": f"تم إنشاء الإشعار المدين {inv_num} بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating purchase debit note: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# =====================================================
# 8.11 PURCHASES IMPROVEMENTS
# =====================================================

# ---------- PUR-001: Request for Quotations ----------

@router.get("/rfq", dependencies=[Depends(require_permission("buying.view"))])
def list_rfqs(status: Optional[str] = None, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM request_for_quotations WHERE 1=1"
        params = {}
        if status:
            q += " AND status = :status"
            params["status"] = status
        q += " ORDER BY created_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()
@router.get("/rfq/{rfq_id}", dependencies=[Depends(require_permission("buying.view"))])
def get_rfq(rfq_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
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
    finally:
        db.close()
@router.post("/rfq", dependencies=[Depends(require_permission("buying.create"))])
def create_rfq(data: dict, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
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
        db.commit()
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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.put("/rfq/{rfq_id}/send", dependencies=[Depends(require_permission("buying.create"))])
def send_rfq(rfq_id: int, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("UPDATE request_for_quotations SET status = 'sent', updated_at = NOW() WHERE id = :id"), {"id": rfq_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.rfq.send", resource_type="rfq",
            resource_id=str(rfq_id), details={},
            request=request
        )
        return {"message": "RFQ sent to suppliers"}
    finally:
        db.close()
@router.post("/rfq/{rfq_id}/responses", dependencies=[Depends(require_permission("buying.create"))])
def add_rfq_response(rfq_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
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
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.rfq.add_response", resource_type="rfq_response",
            resource_id=str(result.id), details={"rfq_id": rfq_id, "supplier_id": data["supplier_id"]},
            request=request
        )
        return dict(result._mapping)
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.post("/rfq/{rfq_id}/compare", dependencies=[Depends(require_permission("buying.view"))])
def compare_rfq_responses(rfq_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        responses = db.execute(text("""
            SELECT * FROM rfq_responses WHERE rfq_id = :rid ORDER BY total_price ASC
        """), {"rid": rfq_id}).fetchall()
        data = [dict(r._mapping) for r in responses]
        best = data[0] if data else None
        return {"responses": data, "recommended": best}
    finally:
        db.close()
@router.post("/rfq/{rfq_id}/convert", dependencies=[Depends(require_permission("buying.create"))])
def convert_rfq_to_po(rfq_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """Convert selected RFQ response to Purchase Order."""
    db = get_db_connection(current_user.company_id)
    try:
        response_id = data.get("response_id")
        resp = db.execute(text("SELECT * FROM rfq_responses WHERE id = :id AND rfq_id = :rid"),
                          {"id": response_id, "rid": rfq_id}).fetchone()
        if not resp:
            raise HTTPException(status_code=404, detail="Response not found")
        db.execute(text("UPDATE rfq_responses SET is_selected = true WHERE id = :id"), {"id": response_id})
        db.execute(text("UPDATE request_for_quotations SET status = 'converted', updated_at = NOW() WHERE id = :id"), {"id": rfq_id})
        db.commit()
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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# ---------- PUR-002: Supplier Ratings ----------

@router.get("/supplier-ratings", dependencies=[Depends(require_permission("buying.view"))])
def list_supplier_ratings(supplier_id: Optional[int] = None, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM supplier_ratings WHERE 1=1"
        params = {}
        if supplier_id:
            q += " AND supplier_id = :sid"
            params["sid"] = supplier_id
        q += " ORDER BY rated_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()
@router.get("/supplier-ratings/summary/{supplier_id}", dependencies=[Depends(require_permission("buying.view"))])
def supplier_rating_summary(supplier_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("""
            SELECT supplier_id,
                   COUNT(*) as total_ratings,
                   ROUND(AVG(quality_score),1) as avg_quality,
                   ROUND(AVG(delivery_score),1) as avg_delivery,
                   ROUND(AVG(price_score),1) as avg_price,
                   ROUND(AVG(service_score),1) as avg_service,
                   ROUND(AVG(overall_score),1) as avg_overall
            FROM supplier_ratings WHERE supplier_id = :sid
            GROUP BY supplier_id
        """), {"sid": supplier_id}).fetchone()
        if not row:
            return {"supplier_id": supplier_id, "total_ratings": 0, "avg_overall": 0}
        return dict(row._mapping)
    finally:
        db.close()
@router.post("/supplier-ratings", dependencies=[Depends(require_permission("buying.create"))])
def rate_supplier(data: dict, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = _dec(data.get("quality_score", 0)).quantize(Decimal('0.1'), ROUND_HALF_UP)
        d = _dec(data.get("delivery_score", 0)).quantize(Decimal('0.1'), ROUND_HALF_UP)
        p = _dec(data.get("price_score", 0)).quantize(Decimal('0.1'), ROUND_HALF_UP)
        s = _dec(data.get("service_score", 0)).quantize(Decimal('0.1'), ROUND_HALF_UP)
        overall = ((q + d + p + s) / Decimal('4')).quantize(Decimal('0.1'), ROUND_HALF_UP)
        result = db.execute(text("""
            INSERT INTO supplier_ratings (supplier_id, po_id, quality_score, delivery_score,
                price_score, service_score, overall_score, comments, rated_by)
            VALUES (:sid, :po, :q, :d, :p, :s, :o, :comments, :uid)
            RETURNING *
        """), {
            "sid": data["supplier_id"], "po": data.get("po_id"),
            "q": q, "d": d, "p": p, "s": s, "o": overall,
            "comments": data.get("comments"), "uid": current_user.id,
        }).fetchone()
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.supplier_rating.create", resource_type="supplier_rating",
            resource_id=str(result.id), details={"supplier_id": data["supplier_id"], "overall_score": str(overall)},
            request=request
        )
        return dict(result._mapping)
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# ---------- PUR-003: Purchase Agreements (Blanket PO) ----------

@router.get("/agreements", dependencies=[Depends(require_permission("buying.view"))])
def list_agreements(status: Optional[str] = None, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM purchase_agreements WHERE 1=1"
        params = {}
        if status:
            q += " AND status = :status"
            params["status"] = status
        q += " ORDER BY created_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()
@router.get("/agreements/{agr_id}", dependencies=[Depends(require_permission("buying.view"))])
def get_agreement(agr_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        agr = db.execute(text("SELECT * FROM purchase_agreements WHERE id = :id"), {"id": agr_id}).fetchone()
        if not agr:
            raise HTTPException(status_code=404, detail="Agreement not found")
        lines = db.execute(text("SELECT * FROM purchase_agreement_lines WHERE agreement_id = :id"), {"id": agr_id}).fetchall()
        return {"agreement": dict(agr._mapping), "lines": [dict(r._mapping) for r in lines]}
    finally:
        db.close()
@router.post("/agreements", dependencies=[Depends(require_permission("buying.create"))])
def create_agreement(data: dict, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
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
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.agreement.create", resource_type="purchase_agreement",
            resource_id=str(agr.id), details={"agreement_number": agr_num, "supplier_id": data["supplier_id"]},
            request=request
        )
        return dict(agr._mapping)
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.put("/agreements/{agr_id}/activate", dependencies=[Depends(require_permission("buying.approve"))])
def activate_agreement(agr_id: int, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("UPDATE purchase_agreements SET status = 'active' WHERE id = :id"), {"id": agr_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="buying.agreement.activate", resource_type="purchase_agreement",
            resource_id=str(agr_id), details={},
            request=request
        )
        return {"message": "Agreement activated"}
    finally:
        db.close()
@router.post("/agreements/{agr_id}/call-off", dependencies=[Depends(require_permission("buying.create"))])
def create_call_off(agr_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """Create a call-off (partial order) against a blanket agreement."""
    db = get_db_connection(current_user.company_id)
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
        db.commit()
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
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# =====================================================================
# Blanket Purchase Orders (US10)
# =====================================================================

from schemas.blanket_po import BlanketPOCreate, ReleaseOrderCreate, PriceAmendRequest

BLANKET_PO_STATUSES = {"draft", "active", "expired", "completed", "cancelled"}
@router.post("/blanket", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.blanket_manage"))])
def create_blanket_po(payload: BlanketPOCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a new blanket purchase order."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
        user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)

        total_qty = _dec(payload.total_quantity)
        unit_price = _dec(payload.unit_price)
        total_amount = (total_qty * unit_price).quantize(_D4, ROUND_HALF_UP)

        agr_number = generate_sequential_number(db, f"BPO-{datetime.now().year}", "blanket_purchase_orders", "agreement_number")

        result = db.execute(text("""
            INSERT INTO blanket_purchase_orders
                (supplier_id, agreement_number, total_quantity, unit_price, total_amount,
                 valid_from, valid_to, status, branch_id, currency, notes, created_by)
            VALUES (:supplier_id, :agr_num, :total_qty, :unit_price, :total_amount,
                    :valid_from, :valid_to, 'draft', :branch_id, :currency, :notes, :created_by)
            RETURNING id
        """), {
            "supplier_id": payload.supplier_id,
            "agr_num": agr_number,
            "total_qty": str(total_qty),
            "unit_price": str(unit_price),
            "total_amount": str(total_amount),
            "valid_from": payload.valid_from,
            "valid_to": payload.valid_to,
            "branch_id": payload.branch_id,
            "currency": payload.currency or "SAR",
            "notes": payload.notes,
            "created_by": username,
        })
        bpo_id = result.fetchone()[0]

        log_activity(db, user_id=user_id, username=username, action="blanket_po_created",
                     resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                     details={"agreement_number": agr_number, "supplier_id": payload.supplier_id},
                     request=request)
        db.commit()
        return {"id": bpo_id, "agreement_number": agr_number, "message": "Blanket PO created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create blanket PO: {e}")
        raise HTTPException(status_code=500, detail="Failed to create blanket PO")
    finally:
        db.close()
@router.get("/blanket", dependencies=[Depends(require_permission("buying.blanket_view"))])
def list_blanket_pos(
    status_filter: Optional[str] = None,
    supplier_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """List blanket purchase orders with remaining balance."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        conditions = []
        params = {"skip": skip, "limit": limit}

        if status_filter and status_filter in BLANKET_PO_STATUSES:
            conditions.append("b.status = :status")
            params["status"] = status_filter
        if supplier_id:
            conditions.append("b.supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id
        if branch_id:
            conditions.append("b.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT b.*, p.name AS supplier_name
                FROM blanket_purchase_orders b
                LEFT JOIN parties p ON p.id = b.supplier_id
                {where_clause}
                ORDER BY b.created_at DESC
                OFFSET :skip LIMIT :limit
            """), params).fetchall()
        except Exception as e:
            db.rollback()
            if "does not exist" in str(e):
                return {"blanket_pos": []}
            raise

        result = []
        for row in rows:
            d = dict(row._mapping)
            d["remaining_quantity"] = str(_dec(d["total_quantity"]) - _dec(d["released_quantity"]))
            d["remaining_amount"] = str(_dec(d["total_amount"]) - _dec(d["released_amount"]))
            result.append(d)

        return {"blanket_pos": result}
    finally:
        db.close()
@router.get("/blanket/{bpo_id}", dependencies=[Depends(require_permission("buying.blanket_view"))])
def get_blanket_po(bpo_id: int, current_user: dict = Depends(get_current_user)):
    """Get blanket PO details with release orders."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        bpo = db.execute(text("""
            SELECT b.*, p.name AS supplier_name
            FROM blanket_purchase_orders b
            LEFT JOIN parties p ON p.id = b.supplier_id
            WHERE b.id = :id
        """), {"id": bpo_id}).fetchone()

        if not bpo:
            raise HTTPException(status_code=404, detail="Blanket PO not found")

        d = dict(bpo._mapping)
        d["remaining_quantity"] = str(_dec(d["total_quantity"]) - _dec(d["released_quantity"]))
        d["remaining_amount"] = str(_dec(d["total_amount"]) - _dec(d["released_amount"]))

        releases = db.execute(text("""
            SELECT r.*, po.po_number
            FROM blanket_po_release_orders r
            LEFT JOIN purchase_orders po ON po.id = r.purchase_order_id
            WHERE r.blanket_po_id = :bpo_id
            ORDER BY r.release_date DESC
        """), {"bpo_id": bpo_id}).fetchall()

        d["releases"] = [dict(r._mapping) for r in releases]
        return d
    finally:
        db.close()
@router.put("/blanket/{bpo_id}/activate", dependencies=[Depends(require_permission("buying.blanket_manage"))])
def activate_blanket_po(bpo_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Activate a draft blanket PO."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        bpo = db.execute(text(
            "SELECT id, status FROM blanket_purchase_orders WHERE id = :id"
        ), {"id": bpo_id}).fetchone()

        if not bpo:
            raise HTTPException(status_code=404, detail="Blanket PO not found")
        if bpo._mapping["status"] != "draft":
            raise HTTPException(status_code=400, detail="Only draft blanket POs can be activated")

        db.execute(text(
            "UPDATE blanket_purchase_orders SET status = 'active', updated_at = NOW() WHERE id = :id"
        ), {"id": bpo_id})

        user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
        log_activity(db, user_id=user_id, username=username, action="blanket_po_activated",
                     resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                     details={"blanket_po_id": bpo_id}, request=request)
        db.commit()
        return {"message": "Blanket PO activated successfully"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.post("/blanket/{bpo_id}/release", dependencies=[Depends(require_permission("buying.blanket_release"))])
def create_release_order(bpo_id: int, payload: ReleaseOrderCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a release order against a blanket PO. Validates remaining quantity and warns if exceeds."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        bpo = db.execute(text("""
            SELECT * FROM blanket_purchase_orders WHERE id = :id
        """), {"id": bpo_id}).fetchone()

        if not bpo:
            raise HTTPException(status_code=404, detail="Blanket PO not found")

        bpo_data = dict(bpo._mapping)
        if bpo_data["status"] != "active":
            raise HTTPException(status_code=400, detail="Blanket PO must be active to release orders")

        release_qty = _dec(payload.release_quantity)
        released_qty = _dec(bpo_data["released_quantity"])
        total_qty = _dec(bpo_data["total_quantity"])
        unit_price = _dec(bpo_data["unit_price"])

        remaining_qty = total_qty - released_qty

        if release_qty > remaining_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Release quantity {str(release_qty)} exceeds remaining agreement quantity {str(remaining_qty)}"
            )

        release_amount = (release_qty * unit_price).quantize(_D4, ROUND_HALF_UP)
        release_dt = payload.release_date or date.today()
        username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
        user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)

        result = db.execute(text("""
            INSERT INTO blanket_po_release_orders
                (blanket_po_id, release_quantity, release_amount, release_date, created_by)
            VALUES (:bpo_id, :qty, :amount, :rel_date, :created_by)
            RETURNING id
        """), {
            "bpo_id": bpo_id,
            "qty": str(release_qty),
            "amount": str(release_amount),
            "rel_date": release_dt,
            "created_by": username,
        })
        release_id = result.fetchone()[0]

        # Update blanket PO consumed totals
        new_released_qty = released_qty + release_qty
        new_released_amt = _dec(bpo_data["released_amount"]) + release_amount
        new_status = "completed" if new_released_qty >= total_qty else "active"

        db.execute(text("""
            UPDATE blanket_purchase_orders
            SET released_quantity = :rel_qty, released_amount = :rel_amt,
                status = :status, updated_at = NOW()
            WHERE id = :id
        """), {
            "rel_qty": str(new_released_qty),
            "rel_amt": str(new_released_amt),
            "status": new_status,
            "id": bpo_id,
        })

        log_activity(db, user_id=user_id, username=username, action="blanket_po_release",
                     resource_type="blanket_po_release_order", resource_id=str(release_id),
                     details={"blanket_po_id": bpo_id, "release_quantity": str(release_qty)},
                     request=request)
        db.commit()

        response = {
            "id": release_id,
            "release_quantity": str(release_qty),
            "release_amount": str(release_amount),
            "remaining_quantity": str(total_qty - new_released_qty),
            "remaining_amount": str(_dec(bpo_data["total_amount"]) - new_released_amt),
            "message": "Release order created successfully",
        }
        return response
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create release order: {e}")
        raise HTTPException(status_code=500, detail="Failed to create release order")
    finally:
        db.close()
@router.put("/blanket/{bpo_id}/amend-price", dependencies=[Depends(require_permission("buying.blanket_manage"))])
def amend_blanket_po_price(bpo_id: int, payload: PriceAmendRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """Amend the unit price of a blanket PO with effective date tracking."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        bpo = db.execute(text("""
            SELECT id, unit_price, total_quantity, released_quantity, released_amount,
                   price_amendment_history, status
            FROM blanket_purchase_orders WHERE id = :id
        """), {"id": bpo_id}).fetchone()

        if not bpo:
            raise HTTPException(status_code=404, detail="Blanket PO not found")

        bpo_data = dict(bpo._mapping)
        if bpo_data["status"] not in ("draft", "active"):
            raise HTTPException(status_code=400, detail="Cannot amend price on a completed/cancelled/expired blanket PO")

        old_price = _dec(bpo_data["unit_price"])
        new_price = _dec(payload.new_price)
        total_qty = _dec(bpo_data["total_quantity"])
        new_total_amount = (total_qty * new_price).quantize(_D4, ROUND_HALF_UP)

        # Append to price amendment history
        history = bpo_data.get("price_amendment_history") or []
        history.append({
            "effective_date": str(payload.effective_date),
            "old_price": str(old_price),
            "new_price": str(new_price),
            "reason": payload.reason,
            "amended_at": datetime.now().isoformat(),
        })

        import json
        db.execute(text("""
            UPDATE blanket_purchase_orders
            SET unit_price = :new_price, total_amount = :new_total,
                price_amendment_history = :history::jsonb, updated_at = NOW()
            WHERE id = :id
        """), {
            "new_price": str(new_price),
            "new_total": str(new_total_amount),
            "history": json.dumps(history),
            "id": bpo_id,
        })

        user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
        log_activity(db, user_id=user_id, username=username, action="blanket_po_price_amended",
                     resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                     details={"old_price": str(old_price), "new_price": str(new_price)},
                     request=request)
        db.commit()

        return {
            "message": "Price amended successfully",
            "old_price": str(old_price),
            "new_price": str(new_price),
            "new_total_amount": str(new_total_amount),
            "remaining_amount": str(new_total_amount - _dec(bpo_data["released_amount"])),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to amend blanket PO price: {e}")
        raise HTTPException(status_code=500, detail="Failed to amend price")
    finally:
        db.close()
