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


@router.get("/supplier-groups", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_supplier_groups(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض مجموعات الموردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
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

@router.post("/supplier-groups", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_supplier_group(
    group: SupplierGroupCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مجموعة موردين جديدة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
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
            return {"message": i18n_message("group_created_success", request)}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.put("/supplier-groups/{id}", dependencies=[Depends(require_permission("buying.edit"))], response_model=Dict[str, Any])
def update_supplier_group(
    id: int,
    group: SupplierGroupCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث مجموعة موردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
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
            return {"message": i18n_message("group_updated_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.delete("/supplier-groups/{id}", dependencies=[Depends(require_permission("buying.delete"))], response_model=Dict[str, Any])
def delete_supplier_group(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف مجموعة موردين"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            # Check usage first
            usage = db.execute(text("SELECT COUNT(*) FROM parties WHERE party_group_id = :id"), {"id": id}).scalar()
            if usage > 0:
                raise HTTPException(**http_error(400, "supplier_group_has_suppliers", request))
                
            result = db.execute(text("DELETE FROM supplier_groups WHERE id = :id"), {"id": id})
            
            if result.rowcount == 0:
                raise HTTPException(**http_error(404, "group_not_found"))
                
    
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
            return {"message": i18n_message("group_deleted_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# === Purchase Orders ===

@router.get("/suppliers/{id}/transactions", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_supplier_transactions(id: int, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """جلب سجل حركات المورد (فواتير ودفعات)"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        # 1. Fetch Invoices
        inv_query = """
            SELECT id, invoice_number, invoice_date, total, paid_amount, status, currency, exchange_rate
            FROM invoices
            WHERE party_id = :id AND invoice_type = 'purchase'
        """
        inv_params = {"id": id}
        
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        branch_scope = resolve_branch_scope(current_user, branch_id)
        
        inv_query += branch_scope_filter_from_scope(branch_scope, "branch_id", inv_params)
        
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
            "exchange_rate": str(_dec(r.exchange_rate or Decimal("1")))
        } for r in invoices_res]
        
        # Calculate total purchases in Base Currency
        total_purchases = sum((_dec(r.total) * _dec(r.exchange_rate or Decimal("1")) for r in invoices_res), Decimal('0')).quantize(_D2, ROUND_HALF_UP)
        
        # 2. Fetch Payments (Vouchers)
        # Note: payment_vouchers table has currency field
        pay_query = """
            SELECT id, voucher_number, voucher_date, amount, payment_method, status, currency
            FROM payment_vouchers
            WHERE party_id = :id AND party_type = 'supplier' AND voucher_type = 'payment'
        """
        pay_params = {"id": id}
        pay_query += branch_scope_filter_from_scope(branch_scope, "branch_id", pay_params)
            
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
        receipt_params = {"id": id}
        receipt_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", receipt_params)
        receipts_res = db.execute(text(f"""
            SELECT id, voucher_number, voucher_date, amount, payment_method, status, currency
            FROM payment_vouchers
            WHERE party_id = :id AND party_type = 'supplier' AND voucher_type = 'refund'
            {receipt_branch_filter}
            ORDER BY voucher_date DESC
        """), receipt_params).fetchall()
        
        receipts = [{
            "id": r.id,
            "voucher_number": r.voucher_number,
            "date": r.voucher_date,
            "amount": str(r.amount),
            "method": r.payment_method,
            "status": r.status,
            "currency": r.currency or base_currency
        } for r in receipts_res]

        # 4. Get basic info for header - using party_site_balances
        supplier = db.execute(text("SELECT name as supplier_name, currency FROM parties WHERE id = :id"), {"id": id}).fetchone()
        
        supplier_currency = supplier.currency if supplier and supplier.currency else base_currency
        
        # Compute balance from party_site_balances
        if branch_id:
            # Specific branch: show balance in branch's local currency
            bal_row = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance), 0) as total, psb.currency
                FROM party_sites ps
                JOIN party_site_balances psb ON psb.party_site_id = ps.id
                WHERE ps.party_id = :pid AND psb.company_branch_id = :bid
                GROUP BY psb.currency
            """), {"pid": id, "bid": branch_id}).fetchone()
            if bal_row:
                balance = _dec(bal_row.total or 0)
                balance_currency = bal_row.currency
            else:
                balance = Decimal('0')
                balance_currency = base_currency
            balance_bc = balance
        else:
            # All branches: total converted to SAR
            total_sar = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_sar
                FROM party_sites ps
                JOIN party_site_balances psb ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON psb.currency = c.code
                WHERE ps.party_id = :pid
            """), {"pid": id}).scalar() or 0
            balance = _dec(total_sar)
            balance_bc = balance
            balance_currency = base_currency

        # Get party sites
        party_sites = db.execute(text("""
            SELECT ps.id, ps.site_name, ps.currency, ps.is_default,
                   COALESCE(SUM(psb.balance), 0) as site_balance
            FROM party_sites ps
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            WHERE ps.party_id = :pid AND ps.is_active = TRUE
            GROUP BY ps.id, ps.site_name, ps.currency, ps.is_default
            ORDER BY ps.is_default DESC, ps.site_name
        """), {"pid": id}).fetchall()

        return {
            "supplier": {
                "name": supplier.supplier_name if supplier else "Unknown",
                "balance": str(balance.quantize(_D2, ROUND_HALF_UP)),
                "balance_bc": str(balance_bc.quantize(_D2, ROUND_HALF_UP)),
                "currency": balance_currency,
                "total_purchases": str(total_purchases),
                "party_sites": [dict(s._mapping) for s in party_sites]
            },
            "invoices": invoices,
            "payments": payments,
            "receipts": receipts
        }

@router.get("/supplier-ratings", dependencies=[Depends(require_permission("buying.view"))], response_model=List[Dict[str, Any]])
def list_supplier_ratings(supplier_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """List Supplier Ratings."""
    with transactional(current_user.company_id) as db:
        q = "SELECT * FROM supplier_ratings WHERE 1=1"
        params = {}
        if supplier_id:
            q += " AND supplier_id = :sid"
            params["sid"] = supplier_id
        q += " ORDER BY rated_at DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
@router.get("/supplier-ratings/summary/{supplier_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def supplier_rating_summary(supplier_id: int, current_user=Depends(get_current_user)):
    """Supplier Rating Summary."""
    with transactional(current_user.company_id) as db:
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
@router.post("/supplier-ratings", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def rate_supplier(data: dict, request: Request, current_user=Depends(get_current_user)):
    """Rate Supplier."""
    with transactional(current_user.company_id) as db:
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
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="buying.supplier_rating.create", resource_type="supplier_rating",
                resource_id=str(result.id), details={"supplier_id": data["supplier_id"], "overall_score": str(overall)},
                request=request
            )
            return dict(result._mapping)
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ---------- PUR-003: Purchase Agreements (Blanket PO) ----------
