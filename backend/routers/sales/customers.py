"""Sales customers and customer groups endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from .schemas import CustomerCreate, CustomerGroupCreate

customers_router = APIRouter()
logger = logging.getLogger(__name__)


# --- Summary ---
@customers_router.get("/summary", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_sales_summary(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """ملخص المبيعات"""
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND branch_id = :branch_id"
            params["branch_id"] = branch_id

        total_customers = db.execute(text(f"SELECT COUNT(*) FROM parties WHERE is_customer = TRUE {branch_filter}"), params).scalar()
        total_invoices = db.execute(text(f"SELECT COUNT(*) FROM invoices WHERE invoice_type = 'sales' {branch_filter}"), params).scalar()
        total_revenue = db.execute(text(f"SELECT COALESCE(SUM(total), 0) FROM invoices WHERE invoice_type = 'sales' AND status != 'cancelled' {branch_filter}"), params).scalar()
        total_receivables = db.execute(text(f"SELECT COALESCE(SUM((total - COALESCE(paid_amount, 0)) * COALESCE(exchange_rate, 1)), 0) FROM invoices WHERE invoice_type = 'sales' AND status IN ('unpaid', 'partial') {branch_filter}"), params).scalar()

        # Monthly sales - current month
        monthly_sales = db.execute(text(f"""
            SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0)
            FROM invoices
            WHERE invoice_type = 'sales' AND status != 'cancelled'
            AND date_trunc('month', invoice_date) = date_trunc('month', CURRENT_DATE)
            {branch_filter}
        """), params).scalar()

        unpaid_count = db.execute(text(f"SELECT COUNT(*) FROM invoices WHERE invoice_type = 'sales' AND status IN ('unpaid', 'partial') {branch_filter}"), params).scalar()

        return {
            "total_customers": total_customers,
            "customer_count": total_customers,
            "total_invoices": total_invoices,
            "total_revenue": str(total_revenue or 0),
            "total_receivables": str(total_receivables or 0),
            "monthly_sales": str(monthly_sales or 0),
            "unpaid_count": unpaid_count
        }
    finally:
        db.close()


# --- Customer Endpoints ---
@customers_router.get("/customers", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_customers(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """عرض قائمة العملاء"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT p.id, p.party_code, p.name, p.email, p.phone, p.mobile, p.address,
                   p.city, p.country, p.tax_number, p.current_balance,
                   p.credit_limit, p.payment_terms, p.status, p.notes,
                   p.party_group_id as group_id, g.group_name as group_name,
                   p.name_en, p.currency, p.created_at
            FROM parties p
            LEFT JOIN party_groups g ON p.party_group_id = g.id
            WHERE p.party_type = 'customer' OR p.is_customer = TRUE
        """
        params = {}
        if branch_id:
            query += " AND p.branch_id = :branch_id"
            params["branch_id"] = branch_id
        else:
            # PTY-005: Enforce allowed_branches when no branch_id specified
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND p.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

        query += " ORDER BY p.name"
        result = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@customers_router.get("/customers/{customer_id}/transactions", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def get_customer_transactions(customer_id: int, current_user: dict = Depends(get_current_user)):
    """كشف حساب عميل"""
    db = get_db_connection(current_user.company_id)
    try:
        # PTY-008: Check branch access for the customer before returning transactions
        customer_branch = db.execute(text(
            "SELECT branch_id FROM parties WHERE id = :cid AND (party_type = 'customer' OR is_customer = TRUE)"
        ), {"cid": customer_id}).fetchone()
        if not customer_branch:
            raise HTTPException(**http_error(404, "customer_not_found"))
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if customer_branch.branch_id and customer_branch.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك الوصول لبيانات عميل خارج فروعك")

        result = db.execute(text("""
            SELECT 'invoice' as type, invoice_number as reference, 
                   invoice_date as date, total as amount, status
            FROM invoices 
            WHERE party_id = :cid AND invoice_type = 'sales'
            
            UNION ALL
            
            SELECT 'payment' as type, voucher_number as reference,
                   voucher_date as date, amount, status
            FROM payment_vouchers
            WHERE party_id = :cid AND party_type = 'customer' AND voucher_type = 'receipt'
            
            UNION ALL
            
            SELECT 'return' as type, return_number as reference,
                   return_date as date, total as amount, status
            FROM sales_returns
            WHERE party_id = :cid
            
            ORDER BY date DESC
        """), {"cid": customer_id}).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@customers_router.post("/customers", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(["parties.manage", "sales.create"]))], response_model=Dict[str, Any])
def create_customer(request: Request, customer: CustomerCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء عميل جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        # Generate Customer Code
        from utils.accounting import generate_sequential_number
        customer_code = generate_sequential_number(db, "CUST", "parties", "party_code")

        result = db.execute(text("""
            INSERT INTO parties (
                party_code, name, name_en, party_type, is_customer, email, phone, mobile, address, city, country,
                tax_number, credit_limit, payment_terms, notes, status, party_group_id,
                branch_id, currency
            )
            VALUES (
                :code, :name, :name_en, 'customer', TRUE, :email, :phone, :mobile, :address, :city, :country,
                :tax, :credit_limit, :payment_terms, :notes, :status, :group_id,
                :branch_id, :currency
            ) RETURNING id
        """), {
            "code": customer_code, "name": customer.name, "name_en": customer.name_en,
            "email": customer.email, "phone": customer.phone, "mobile": customer.mobile,
            "address": customer.address, "city": customer.city, "country": customer.country,
            "tax": customer.tax_number,
            "credit_limit": customer.credit_limit, "payment_terms": customer.payment_terms,
            "notes": customer.notes, "status": customer.status, "group_id": customer.group_id,
            "branch_id": customer.branch_id, "currency": customer.currency
        }).fetchone()

        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.customer.create",
            resource_type="customer",
            resource_id=str(result[0]),
            details={"customer_code": customer_code, "name": customer.name},
            request=request,
            branch_id=customer.branch_id
        )
        return {"id": result[0], "party_code": customer_code}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating customer: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@customers_router.get("/customers/{customer_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_customer(customer_id: int, current_user: dict = Depends(get_current_user)):
    """عرض بيانات عميل محدد"""
    db = get_db_connection(current_user.company_id)
    try:
        customer = db.execute(text("""
            SELECT p.id, p.party_code, p.name, p.name_en, p.party_type, p.is_customer, p.email, p.phone, p.mobile, 
                   p.address, p.city, p.country, p.tax_number, p.credit_limit, p.payment_terms, p.notes, 
                   p.status, p.party_group_id as group_id, p.branch_id, p.currency, p.current_balance
            FROM parties p
            WHERE p.id = :cid AND (p.party_type = 'customer' OR p.is_customer = TRUE)
        """), {"cid": customer_id}).fetchone()

        if not customer:
            raise HTTPException(**http_error(404, "customer_not_found"))

        # PTY-001: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if customer.branch_id and customer.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك الوصول لبيانات عميل خارج فروعك")

        return dict(customer._mapping)
    finally:
        db.close()


@customers_router.put("/customers/{customer_id}", response_model=dict, dependencies=[Depends(require_permission(["parties.manage", "sales.edit"]))])
def update_customer(customer_id: int, customer: CustomerCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """تحديث عميل"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check if exists
        existing = db.execute(text("SELECT id, branch_id FROM parties WHERE id = :id AND (party_type = 'customer' OR is_customer = TRUE)"), {"id": customer_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "customer_not_found"))

        # PTY-002: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if existing.branch_id and existing.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك تعديل عميل خارج فروعك")

        db.execute(text("""
            UPDATE parties 
            SET name = :name, name_en = :name_en, email = :email, phone = :phone, mobile = :mobile, 
                address = :address, city = :city, country = :country, tax_number = :tax, 
                credit_limit = :credit_limit, payment_terms = :payment_terms, notes = :notes, 
                status = :status, party_group_id = :group_id, branch_id = :branch_id, currency = :currency
            WHERE id = :id
        """), {
            "id": customer_id, "name": customer.name, "name_en": customer.name_en,
            "email": customer.email, "phone": customer.phone, "mobile": customer.mobile,
            "address": customer.address, "city": customer.city, "country": customer.country,
            "tax": customer.tax_number,
            "credit_limit": customer.credit_limit, "payment_terms": customer.payment_terms,
            "notes": customer.notes, "status": customer.status, "group_id": customer.group_id,
            "branch_id": customer.branch_id, "currency": customer.currency
        })

        db.commit()

        # PTY-009: Log activity for customer update
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.customer.update",
            resource_type="customer",
            resource_id=str(customer_id),
            details={"name": customer.name},
            request=request,
            branch_id=customer.branch_id
        )

        return {"success": True, "id": customer_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating customer: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@customers_router.get("/customers/{customer_id}/outstanding-invoices", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def get_customer_outstanding_invoices(
    customer_id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Fetch unpaid/partial invoices for a customer"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT id, invoice_number, invoice_date, total, paid_amount, status, invoice_type,
                   (total - COALESCE(paid_amount, 0)) as remaining_balance,
                   currency, exchange_rate
            FROM invoices
            WHERE party_id = :cid
              AND status IN ('unpaid', 'partial')
        """
        params = {"cid": customer_id}
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


# --- Customer Groups ---
@customers_router.get("/customer-groups", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_customer_groups(current_user: dict = Depends(get_current_user)):
    """قائمة مجموعات العملاء"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT g.*, (SELECT COUNT(*) FROM parties p WHERE p.party_group_id = g.id AND (p.party_type = 'customer' OR p.is_customer = TRUE)) as customer_count
            FROM party_groups g
            ORDER BY g.group_name
        """)).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@customers_router.post("/customer-groups", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_customer_group(
    group: CustomerGroupCreate, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مجموعة عملاء جديدة"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            INSERT INTO party_groups (group_name, group_name_en, description, discount_percentage, effect_type, application_scope, payment_days, status)
            VALUES (:name, :name_en, :desc, :discount, :effect_type, :application_scope, :days, :status)
            RETURNING id
        """), {
            "name": group.group_name, "name_en": group.group_name_en,
            "desc": group.description, "discount": group.discount_percentage,
            "effect_type": group.effect_type, "application_scope": group.application_scope,
            "days": group.payment_days, "status": group.status
        }).fetchone()
        db.commit()

        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="sales.customer_group.create",
            resource_type="customer_group",
            resource_id=str(result[0]),
            details={"group_name": group.group_name},
            request=request
        )

        return {"id": result[0], "group_name": group.group_name}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@customers_router.put("/customer-groups/{group_id}", dependencies=[Depends(require_permission("sales.edit"))], response_model=Dict[str, Any])
def update_customer_group(
    group_id: int, 
    group: CustomerGroupCreate, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تعديل مجموعة عملاء"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            UPDATE party_groups SET 
                group_name = :name, group_name_en = :name_en, description = :desc, 
                discount_percentage = :discount, effect_type = :effect_type, application_scope = :application_scope, payment_days = :days, status = :status
            WHERE id = :id
        """), {
            "id": group_id, "name": group.group_name, "name_en": group.group_name_en,
            "desc": group.description, "discount": group.discount_percentage,
            "effect_type": group.effect_type, "application_scope": group.application_scope,
            "days": group.payment_days, "status": group.status
        })
        db.commit()

        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="sales.customer_group.update",
            resource_type="customer_group",
            resource_id=str(group_id),
            details={"group_name": group.group_name},
            request=request
        )

        return {"success": True}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@customers_router.delete("/customer-groups/{group_id}", dependencies=[Depends(require_permission("sales.delete"))], response_model=Dict[str, Any])
def delete_customer_group(
    group_id: int, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف مجموعة عملاء"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check if any customers linked
        count = db.execute(text("SELECT COUNT(*) FROM parties WHERE party_group_id = :id"), {"id": group_id}).scalar()
        if count > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف المجموعة لأنها مرتبطة بعملاء")
        db.execute(text("DELETE FROM party_groups WHERE id = :id"), {"id": group_id})
        db.commit()

        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="sales.customer_group.delete",
            resource_type="customer_group",
            resource_id=str(group_id),
            details=None,
            request=request
        )

        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
