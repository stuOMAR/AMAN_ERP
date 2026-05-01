"""
Phase 8.12 Sales Improvements:
  SALES-001: Quote → Order conversion
  SALES-002: Commission tracking
  SALES-003: Partial invoicing
  SALES-004: Smart credit limit
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.accounting import get_mapped_account_id, get_base_currency
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from utils.fiscal_lock import check_fiscal_period_open

logger = logging.getLogger(__name__)
sales_improvements_router = APIRouter()


# =====================================================
# SALES-001: Quote → Order Conversion
# =====================================================

@sales_improvements_router.post("/quotations/{sq_id}/convert", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def convert_quotation_to_order(sq_id: int, current_user=Depends(get_current_user)):
    """Auto-convert a sales quotation into a sales order."""
    db = get_db_connection(current_user.company_id)
    try:
        sq = db.execute(text("SELECT * FROM sales_quotations WHERE id = :id"), {"id": sq_id}).fetchone()
        if not sq:
            raise HTTPException(status_code=404, detail="Quotation not found")
        if hasattr(sq, 'converted_to_order_id') and sq.converted_to_order_id:
            raise HTTPException(status_code=400, detail="Already converted")

        # Generate SO number
        import uuid
        so_num = f"SO-{uuid.uuid4().hex[:8].upper()}"

        # Create order from quotation
        so = db.execute(text("""
            INSERT INTO sales_orders (
                so_number, customer_id, branch_id, order_date, status,
                total, discount, tax, grand_total, notes, currency, source_quotation_id, created_by
            ) VALUES (
                :num, :cid, :bid, NOW(), 'draft',
                :total, :disc, :tax, :grand, :notes, :curr, :sqid, :uid
            ) RETURNING id
        """), {
            "num": so_num, "cid": sq.customer_id,
            "bid": getattr(sq, 'branch_id', None),
            "total": str(getattr(sq, 'total', 0) or 0),
            "disc": str(getattr(sq, 'discount', 0) or 0),
            "tax": str(getattr(sq, 'tax', 0) or 0),
            "grand": str(getattr(sq, 'grand_total', 0) or 0),
            "notes": getattr(sq, 'notes', None),
            "curr": getattr(sq, 'currency', None),
            "sqid": sq_id, "uid": current_user.id,
        }).fetchone()

        # Copy lines
        lines = db.execute(text("SELECT * FROM sales_quotation_lines WHERE quotation_id = :id"), {"id": sq_id}).fetchall()
        for line in lines:
            db.execute(text("""
                INSERT INTO sales_order_lines (order_id, product_id, quantity, unit_price, discount, tax_rate, subtotal)
                VALUES (:oid, :pid, :qty, :price, :disc, :tax, :sub)
            """), {
                "oid": so.id, "pid": line.product_id,
                "qty": str(line.quantity or 0), "price": str(line.unit_price or 0),
                "disc": str(getattr(line, 'discount', 0) or 0),
                "tax": str(getattr(line, 'tax_rate', 0) or 0),
                "sub": str(getattr(line, 'subtotal', 0) or 0),
            })

        # Mark quotation as converted
        db.execute(text("""
            UPDATE sales_quotations SET converted_to_order_id = :oid, conversion_date = NOW()
            WHERE id = :id
        """), {"oid": so.id, "id": sq_id})

        db.commit()
        return {"message": "Quotation converted to order", "order_id": so.id, "so_number": so_num}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Quotation conversion error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# =====================================================
# SALES-002: Commission Tracking
# =====================================================

@sales_improvements_router.get("/commissions/rules", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_commission_rules(current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("SELECT * FROM commission_rules WHERE is_active = true ORDER BY id")).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@sales_improvements_router.post("/commissions/rules", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_commission_rule(data: dict, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            INSERT INTO commission_rules (name, salesperson_id, product_id, category_id,
                rate_type, rate, min_amount, max_amount, is_active, branch_id)
            VALUES (:name, :sp, :pid, :cat, :rtype, :rate, :min, :max, true, :branch)
            RETURNING *
        """), {
            "name": data["name"], "sp": data.get("salesperson_id"),
            "pid": data.get("product_id"), "cat": data.get("category_id"),
            "rtype": data.get("rate_type", "percentage"), "rate": data.get("rate", 0),
            "min": data.get("min_amount", 0), "max": data.get("max_amount"),
            "branch": data.get("branch_id"),
        }).fetchone()
        db.commit()
        return dict(result._mapping)
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@sales_improvements_router.get("/commissions", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_commissions(
    salesperson_id: Optional[int] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM sales_commissions WHERE 1=1"
        params = {}
        if salesperson_id:
            q += " AND salesperson_id = :sp"
            params["sp"] = salesperson_id
        if status:
            q += " AND status = :status"
            params["status"] = status
        if from_date:
            q += " AND invoice_date >= :from"
            params["from"] = from_date
        if to_date:
            q += " AND invoice_date <= :to"
            params["to"] = to_date
        q += " ORDER BY created_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@sales_improvements_router.post("/commissions/calculate", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def calculate_commission(data: dict, current_user=Depends(get_current_user)):
    """Calculate commission entry. If invoice_id provided, for that invoice only. Otherwise bulk-calculate all unprocessed invoices."""
    db = get_db_connection(current_user.company_id)
    try:
        invoice_id = data.get("invoice_id")

        # Bulk mode: calculate for all invoices not yet in sales_commissions
        if not invoice_id:
            already_processed = db.execute(text("SELECT invoice_id FROM sales_commissions")).fetchall()
            processed_ids = {r[0] for r in already_processed}

            # Check if salesperson_id column exists in invoices
            col_check = db.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='invoices' AND column_name='salesperson_id'
            """)).fetchone()
            has_salesperson = col_check is not None

            if has_salesperson:
                invoices = db.execute(text(
                    "SELECT * FROM invoices WHERE status='approved' AND salesperson_id IS NOT NULL ORDER BY created_at DESC LIMIT 100"
                )).fetchall()
            else:
                invoices = db.execute(text(
                    "SELECT * FROM invoices WHERE status='approved' ORDER BY created_at DESC LIMIT 100"
                )).fetchall()

            count = 0
            for inv in invoices:
                inv_id = getattr(inv, 'id', None)
                if inv_id in processed_ids:
                    continue
                sp_id = getattr(inv, 'salesperson_id', None) if has_salesperson else None
                if not sp_id:
                    continue
                rule = db.execute(text("""
                    SELECT * FROM commission_rules
                    WHERE is_active = true AND (salesperson_id = :sp OR salesperson_id IS NULL)
                    ORDER BY salesperson_id DESC NULLS LAST LIMIT 1
                """), {"sp": sp_id}).fetchone()
                rate = Decimal(str(rule.rate)) if rule else Decimal("0")
                if rate == 0:
                    continue
                total = Decimal(str(getattr(inv, 'grand_total', getattr(inv, 'total', 0)) or 0))
                commission = (total * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO sales_commissions (salesperson_id, salesperson_name, invoice_id, invoice_number,
                        invoice_date, invoice_total, commission_rate, commission_amount, status, branch_id)
                    VALUES (:sp, :spname, :inv, :invnum, :invdate, :total, :rate, :com, 'pending', :branch)
                    ON CONFLICT DO NOTHING
                """), {
                    "sp": sp_id, "spname": "",
                    "inv": inv_id, "invnum": getattr(inv, 'invoice_number', ''),
                    "invdate": getattr(inv, 'invoice_date', None),
                    "total": total, "rate": rate, "com": commission,
                    "branch": getattr(inv, 'branch_id', None),
                })
                count += 1
            db.commit()
            return {"count": count, "message": f"Calculated {count} commission entries"}

        # Single invoice mode
        inv = db.execute(text("SELECT * FROM invoices WHERE id = :id"), {"id": invoice_id}).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")

        salesperson_id = data.get("salesperson_id") or getattr(inv, "salesperson_id", None)
        if not salesperson_id:
            raise HTTPException(status_code=400, detail="No salesperson assigned")

        # Find applicable rule
        rule = db.execute(text("""
            SELECT * FROM commission_rules
            WHERE is_active = true AND (salesperson_id = :sp OR salesperson_id IS NULL)
            ORDER BY salesperson_id DESC NULLS LAST LIMIT 1
        """), {"sp": salesperson_id}).fetchone()

        rate = Decimal(str(rule.rate)) if rule else Decimal(str(data.get("rate", 0)))
        total = Decimal(str(getattr(inv, 'grand_total', getattr(inv, 'total', 0)) or 0))
        commission = (total * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if (rule and rule.rate_type == 'percentage') or not rule else rate

        result = db.execute(text("""
            INSERT INTO sales_commissions (salesperson_id, salesperson_name, invoice_id, invoice_number,
                invoice_date, invoice_total, commission_rate, commission_amount, status, branch_id)
            VALUES (:sp, :spname, :inv, :invnum, :invdate, :total, :rate, :com, 'pending', :branch)
            RETURNING *
        """), {
            "sp": salesperson_id,
            "spname": data.get("salesperson_name", ""),
            "inv": invoice_id,
            "invnum": getattr(inv, 'invoice_number', ''),
            "invdate": getattr(inv, 'invoice_date', None),
            "total": total, "rate": rate, "com": commission,
            "branch": getattr(inv, 'branch_id', None),
        }).fetchone()
        db.commit()
        return dict(result._mapping)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@sales_improvements_router.get("/commissions/summary", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def commission_summary(current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT salesperson_id, salesperson_name,
                   COUNT(*) as total_invoices,
                   SUM(invoice_total) as total_sales,
                   SUM(commission_amount) as total_commission,
                   SUM(CASE WHEN status='pending' THEN commission_amount ELSE 0 END) as pending,
                   SUM(CASE WHEN status='paid' THEN commission_amount ELSE 0 END) as paid
            FROM sales_commissions
            GROUP BY salesperson_id, salesperson_name
            ORDER BY total_commission DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@sales_improvements_router.post("/commissions/pay", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def pay_commission(data: dict, current_user=Depends(get_current_user)):
    """
    صرف العمولات وإنشاء قيد محاسبي.
    Pay commissions and create GL entry:
    Dr: Sales Commission Expense (acc_map_sales_commission / 5217)
    Cr: Bank/Cash (acc_map_bank)
    
    data: { "commission_ids": [1,2,3], "payment_date": "2026-01-15" }
    """
    db = get_db_connection(current_user.company_id)
    try:
        commission_ids = data.get("commission_ids", [])
        payment_date = data.get("payment_date", str(date.today()))
        
        if not commission_ids:
            raise HTTPException(status_code=400, detail="لم يتم تحديد عمولات للصرف")
        
        # Fetch pending commissions
        normalized_ids = [int(cid) for cid in commission_ids]
        commissions = db.execute(text("""
            SELECT * FROM sales_commissions
            WHERE id = ANY(:commission_ids) AND status = 'pending'
        """), {"commission_ids": normalized_ids}).fetchall()
        
        if not commissions:
            raise HTTPException(status_code=400, detail="لا توجد عمولات معلقة بالأرقام المحددة")
        
        total_amount = sum(Decimal(str(c.commission_amount)) for c in commissions)
        
        # Create GL Entry
        commission_acc = get_mapped_account_id(db, "acc_map_sales_commission")
        bank_acc = get_mapped_account_id(db, "acc_map_bank")
        base_currency = get_base_currency(db)
        
        je_id = None
        je_number = None
        if commission_acc and bank_acc:
            # Fiscal-period lock: block posting into a closed period.
            check_fiscal_period_open(db, str(payment_date))
            sp_names = set()
            for c in commissions:
                sp_names.add(c.salesperson_name or str(c.salesperson_id))

            # TASK-015: centralized GL posting
            je_id, je_number = create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(payment_date),
                description=f"صرف عمولات مبيعات — {', '.join(sp_names)} — {total_amount:.2f}",
                lines=[
                    {"account_id": commission_acc, "debit": total_amount, "credit": 0,
                     "description": f"عمولات مبيعات — {len(commissions)} عمولة"},
                    {"account_id": bank_acc, "debit": 0, "credit": total_amount,
                     "description": "صرف عمولات مبيعات"},
                ],
                user_id=current_user.id,
                status="posted",
                currency=base_currency,
                source="CommissionPayment",
                source_id=int(sorted(normalized_ids)[0]) if normalized_ids else None,
                username=getattr(current_user, "username", None),
                idempotency_key=f"commpay-{'-'.join(str(i) for i in sorted(normalized_ids))}",
            )
        
        # Update commission status
        db.execute(text("""
            UPDATE sales_commissions SET status = 'paid', updated_at = NOW()
            WHERE id = ANY(:commission_ids) AND status = 'pending'
        """), {"commission_ids": normalized_ids})
        
        db.commit()
        return {
            "success": True,
            "paid_count": len(commissions),
            "total_amount": round(total_amount, 2),
            "journal_entry_id": je_id,
            "message": f"تم صرف {len(commissions)} عمولة بمبلغ {total_amount:.2f} وإنشاء القيد المحاسبي"
        }
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# =====================================================
# SALES-003: Partial Invoicing
# =====================================================

@sales_improvements_router.post("/orders/{order_id}/partial-invoice", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_partial_invoice(order_id: int, data: dict, current_user=Depends(get_current_user)):
    """Create a partial invoice from a sales order."""
    db = get_db_connection(current_user.company_id)
    try:
        order = db.execute(text("SELECT * FROM sales_orders WHERE id = :id"), {"id": order_id}).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        lines = data.get("lines", [])  # [{order_line_id, quantity}]
        if not lines:
            raise HTTPException(status_code=400, detail="No lines specified")

        import uuid
        inv_num = f"INV-{uuid.uuid4().hex[:8].upper()}"
        total = 0

        # SALES-F1: accept optional invoice_date; default to today if not provided.
        raw_invoice_date = data.get("invoice_date")
        invoice_date_val = None
        if raw_invoice_date:
            try:
                invoice_date_val = (
                    raw_invoice_date
                    if hasattr(raw_invoice_date, "isoformat")
                    else datetime.fromisoformat(str(raw_invoice_date)).date()
                )
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="invalid invoice_date format (expected ISO 8601)")

        inv = db.execute(text("""
            INSERT INTO invoices (invoice_number, party_id, branch_id, invoice_date, type,
                status, is_partial, parent_order_id, created_by)
            VALUES (:num, :cid, :bid, COALESCE(:inv_date, CURRENT_DATE), 'sale', 'draft', true, :oid, :uid)
            RETURNING id
        """), {
            "num": inv_num, "cid": order.customer_id,
            "bid": getattr(order, 'branch_id', None),
            "inv_date": invoice_date_val,
            "oid": order_id, "uid": current_user.id,
        }).fetchone()

        for line_data in lines:
            ol = db.execute(text("SELECT * FROM sales_order_lines WHERE id = :id"),
                            {"id": line_data["order_line_id"]}).fetchone()
            if not ol:
                continue
            qty = min(Decimal(str(line_data["quantity"])), Decimal(str(ol.quantity)))
            subtotal = qty * Decimal(str(ol.unit_price))
            total += subtotal
            # Insert invoice line (format depends on existing schema)
            db.execute(text("""
                INSERT INTO invoice_lines (invoice_id, product_id, quantity, unit_price, subtotal)
                VALUES (:iid, :pid, :qty, :price, :sub)
            """), {"iid": inv.id, "pid": ol.product_id, "qty": qty,
                   "price": str(ol.unit_price or 0), "sub": subtotal})

        db.execute(text("UPDATE invoices SET total = :total, grand_total = :total WHERE id = :id"),
                   {"total": total, "id": inv.id})
        db.commit()
        return {"invoice_id": inv.id, "invoice_number": inv_num, "total": total}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# =====================================================
# SALES-004: Smart Credit Limit
# =====================================================

@sales_improvements_router.get("/customers/{party_id}/credit-status", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def get_credit_status(party_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        party = db.execute(text("SELECT id, name, credit_limit, credit_used FROM parties WHERE id = :id"),
                           {"id": party_id}).fetchone()
        if not party:
            raise HTTPException(status_code=404, detail="Customer not found")
        limit_ = Decimal(str(party.credit_limit or 0))
        used = Decimal(str(party.credit_used or 0))
        return {
            "party_id": party_id,
            "name": party.name,
            "credit_limit": str(limit_),
            "credit_used": str(used),
            "available": str(limit_ - used),
            "utilization_pct": str((used / limit_ * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if limit_ > 0 else "0",
        }
    finally:
        db.close()


@sales_improvements_router.put("/customers/{party_id}/credit-limit", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_credit_limit(party_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        old_limit = db.execute(text("SELECT credit_limit FROM parties WHERE id = :id"), {"id": party_id}).scalar()
        db.execute(text("UPDATE parties SET credit_limit = :lim WHERE id = :id"),
                   {"lim": data["credit_limit"], "id": party_id})
        db.commit()
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.credit_limit.update",
            resource_type="party",
            resource_id=str(party_id),
            details={"old_limit": str(old_limit or 0), "new_limit": data["credit_limit"]},
            request=request
        )
        return {"message": "Credit limit updated", "credit_limit": data["credit_limit"]}
    finally:
        db.close()


@sales_improvements_router.post("/credit-check", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def check_credit(data: dict, current_user=Depends(get_current_user)):
    """Check if a customer can place an order of given amount."""
    db = get_db_connection(current_user.company_id)
    try:
        party_id = data["party_id"]
        amount = Decimal(str(data["amount"]))
        party = db.execute(text("SELECT credit_limit, credit_used FROM parties WHERE id = :id"),
                           {"id": party_id}).fetchone()
        if not party:
            raise HTTPException(status_code=404, detail="Customer not found")
        limit_ = Decimal(str(party.credit_limit or 0))
        used = Decimal(str(party.credit_used or 0))
        available = limit_ - used
        approved = limit_ == 0 or amount <= available  # 0 = no limit
        return {
            "approved": approved,
            "credit_limit": str(limit_),
            "credit_used": str(used),
            "available": str(available),
            "requested": str(amount),
            "message": "Approved" if approved else f"Credit limit exceeded by {amount - available:.2f}"
        }
    finally:
        db.close()
