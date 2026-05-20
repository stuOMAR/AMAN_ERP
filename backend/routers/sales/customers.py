"""Sales customers and customer groups endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.cache import cached
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from .schemas import CustomerCreate, CustomerGroupCreate

customers_router = APIRouter()
logger = logging.getLogger(__name__)


def _company_id(user) -> str:
    return user.get("company_id") if isinstance(user, dict) else user.company_id


def _user_id(user) -> int:
    return user.get("id") if isinstance(user, dict) else user.id


def _username(user) -> str:
    return user.get("username") if isinstance(user, dict) else user.username


# --- Summary ---
@customers_router.get("/summary", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
@cached("sales_kpi", expire=30)
def get_sales_summary(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """ملخص المبيعات (مُكَش بـ TTL 30s — يُلغى تلقائياً عند أي post عبر invalidate_aggregates('sales_kpi'))"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(_company_id(current_user))
    try:
        params = {}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        total_customers = db.execute(text(f"SELECT COUNT(*) FROM parties WHERE is_customer = TRUE {branch_filter}"), params).scalar()
        total_invoices = db.execute(text(f"SELECT COUNT(*) FROM invoices WHERE invoice_type = 'sales' {branch_filter}"), params).scalar()
        total_revenue = db.execute(text(f"SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) FROM invoices WHERE invoice_type = 'sales' AND status != 'cancelled' {branch_filter}"), params).scalar()
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
    """عرض قائمة العملاء مع أرصدة من party_site_balances"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(_company_id(current_user))
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        branch_cur = base_cur
        if branch_id:
            branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur

        # Subquery for balance
        if branch_id:
            balance_subquery = """
                SELECT ps.party_id,
                       COALESCE(SUM(psb.balance), 0) as total_balance,
                       psb.currency as bal_currency
                FROM party_sites ps
                LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                WHERE psb.company_branch_id = :bid
                GROUP BY ps.party_id, psb.currency
            """
            balance_params = {"bid": branch_id}
        else:
            balance_subquery = """
                SELECT ps.party_id,
                       COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_balance,
                       :base_cur as bal_currency
                FROM party_sites ps
                LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON psb.currency = c.code
                GROUP BY ps.party_id
            """
            balance_params = {"base_cur": base_cur}

        query = f"""
            SELECT p.id, p.party_code, p.name, p.email, p.phone, p.mobile, p.address,
                   p.city, p.country, p.tax_number,
                   COALESCE(bal.total_balance, 0) as current_balance,
                   COALESCE(bal.bal_currency, :display_cur) as balance_currency,
                   p.credit_limit, p.payment_terms, p.status, p.notes,
                   p.party_group_id as group_id, g.group_name as group_name,
                   p.branch_id,
                   p.name_en, p.currency, p.created_at
            FROM parties p
            LEFT JOIN party_groups g ON p.party_group_id = g.id
            LEFT JOIN ({balance_subquery}) bal ON bal.party_id = p.id
            WHERE (p.party_type = 'customer' OR p.is_customer = TRUE)
        """
        params = {"display_cur": branch_cur, **balance_params}

        query += " ORDER BY p.name"
        result = db.execute(text(query), params).fetchall()
        
        customers = []
        for row in result:
            d = dict(row._mapping)
            # Fix 5: use str(Decimal) not float() for monetary balance values
            d["balance_display"] = str(d.get("current_balance") or "0")
            d["display_currency"] = d.get("balance_currency") or branch_cur
            customers.append(d)
        return customers
    finally:
        db.close()


@customers_router.get("/customers/{customer_id}/transactions", dependencies=[Depends(require_permission("sales.view"))])
def get_customer_transactions(
    customer_id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """كشف حساب عميل"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(_company_id(current_user))
    try:
        customer_exists = db.execute(text(
            "SELECT 1 FROM parties WHERE id = :cid AND (party_type = 'customer' OR is_customer = TRUE)"
        ), {"cid": customer_id}).fetchone()
        if not customer_exists:
            raise HTTPException(**http_error(404, "customer_not_found"))

        params = {"cid": customer_id}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        # Get invoices
        invoices = db.execute(text(f"""
            SELECT id, invoice_number, invoice_date, total, paid_amount, status, currency
            FROM invoices 
            WHERE party_id = :cid AND invoice_type = 'sales'
            {branch_filter}
            ORDER BY invoice_date DESC
        """), params).fetchall()

        # Get receipts
        receipts = db.execute(text(f"""
            SELECT id, voucher_number, voucher_date, amount, status, currency
            FROM payment_vouchers
            WHERE party_id = :cid AND party_type = 'customer' AND voucher_type = 'receipt'
            {branch_filter}
            ORDER BY voucher_date DESC
        """), params).fetchall()

        return {
            "customer": {"id": customer_id},
            "invoices": [dict(row._mapping) for row in invoices],
            "receipts": [dict(row._mapping) for row in receipts],
        }
    finally:
        db.close()


@customers_router.post("/customers", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(["parties.manage", "sales.create"]))], response_model=Dict[str, Any])
def create_customer(request: Request, customer: CustomerCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء عميل جديد مع إنشاء موقع افتراضي تلقائياً"""
    db = get_db_connection(_company_id(current_user))
    try:
        # Generate Customer Code
        from utils.accounting import generate_sequential_number
        customer_code = generate_sequential_number(db, "CUST", "parties", "party_code")

        result = db.execute(text("""
            INSERT INTO parties (
                party_code, name, name_en, party_type, is_customer, email, phone, mobile, address, city, country,
                tax_number, tax_exempt, credit_limit, payment_terms, notes, status, party_group_id,
                branch_id, currency
            )
            VALUES (
                :code, :name, :name_en, 'customer', TRUE, :email, :phone, :mobile, :address, :city, :country,
                :tax, :tax_exempt, :credit_limit, :payment_terms, :notes, :status, :group_id,
                :branch_id, :currency
            ) RETURNING id
        """), {
            "code": customer_code, "name": customer.name, "name_en": customer.name_en,
            "email": customer.email, "phone": customer.phone, "mobile": customer.mobile,
            "address": customer.address, "city": customer.city, "country": customer.country,
            "tax": customer.tax_number, "tax_exempt": customer.tax_exempt or False,
            "credit_limit": customer.credit_limit, "payment_terms": customer.payment_terms,
            "notes": customer.notes, "status": customer.status, "group_id": customer.group_id,
            "branch_id": customer.branch_id, "currency": customer.currency
        }).fetchone()
        pid = result[0]

        # إنشاء موقع افتراضي للعميل
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        cust_currency = customer.currency or base_cur
        
        site = db.execute(text("""
            INSERT INTO party_sites (party_id, site_name, site_name_en, country, country_code, currency, phone, is_default, is_active)
            VALUES (:pid, :name, :name_en, :country, :cc, :cur, :phone, TRUE, TRUE)
            RETURNING id
        """), {
            "pid": pid,
            "name": customer.name,
            "name_en": customer.name_en,
            "country": customer.country or "",
            "cc": "",
            "cur": cust_currency,
            "phone": customer.phone
        }).fetchone()
        
        # تحديث default_site_id
        site_id = site.id
        db.execute(text("UPDATE parties SET default_site_id = :sid WHERE id = :pid"),
                  {"sid": site_id, "pid": pid})

        db.commit()

        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
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
def get_customer(customer_id: int, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """عرض بيانات عميل محدد مع أرصدة من party_site_balances"""
    db = get_db_connection(_company_id(current_user))
    try:
        customer = db.execute(text("""
            SELECT p.id, p.party_code, p.name, p.name_en, p.party_type, p.is_customer, p.email, p.phone, p.mobile, 
                   p.address, p.city, p.country, p.tax_number, p.credit_limit, p.payment_terms, p.notes, 
                   p.status, p.party_group_id as group_id, p.branch_id, p.currency
            FROM parties p
            WHERE p.id = :cid AND (p.party_type = 'customer' OR p.is_customer = TRUE)
        """), {"cid": customer_id}).fetchone()

        if not customer:
            raise HTTPException(**http_error(404, "customer_not_found"))

        d = dict(customer._mapping)

        # Compute balance from party_site_balances
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        if branch_id:
            # Specific branch: show balance in branch's local currency
            bal_row = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance), 0) as total, psb.currency
                FROM party_sites ps
                JOIN party_site_balances psb ON psb.party_site_id = ps.id
                WHERE ps.party_id = :cid AND psb.company_branch_id = :bid
                GROUP BY psb.currency
            """), {"cid": customer_id, "bid": branch_id}).fetchone()
            if bal_row:
                d["balance"] = str(bal_row.total or "0")
                d["balance_bc"] = str(bal_row.total or "0")
                d["balance_currency"] = bal_row.currency
            else:
                d["balance"] = "0"
                d["balance_bc"] = "0"
                d["balance_currency"] = base_cur
        else:
            # All branches: total converted to SAR
            total_sar = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_sar
                FROM party_sites ps
                JOIN party_site_balances psb ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON psb.currency = c.code
                WHERE ps.party_id = :cid
            """), {"cid": customer_id}).scalar() or 0
            d["balance"] = str(total_sar)
            d["balance_bc"] = str(total_sar)
            d["balance_currency"] = base_cur

        # Get party sites
        sites = db.execute(text("""
            SELECT ps.id, ps.site_name, ps.currency, ps.is_default,
                   COALESCE(SUM(psb.balance), 0) as site_balance
            FROM party_sites ps
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            WHERE ps.party_id = :cid AND ps.is_active = TRUE
            GROUP BY ps.id, ps.site_name, ps.currency, ps.is_default
            ORDER BY ps.is_default DESC, ps.site_name
        """), {"cid": customer_id}).fetchall()
        d["party_sites"] = [dict(s._mapping) for s in sites]

        return d
    finally:
        db.close()


@customers_router.put("/customers/{customer_id}", response_model=dict, dependencies=[Depends(require_permission(["parties.manage", "sales.edit"]))])
def update_customer(customer_id: int, customer: CustomerCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """تحديث عميل"""
    db = get_db_connection(_company_id(current_user))
    try:
        # Check if exists
        existing = db.execute(text("SELECT id, branch_id FROM parties WHERE id = :id AND (party_type = 'customer' OR is_customer = TRUE)"), {"id": customer_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "customer_not_found"))

        db.execute(text("""
            UPDATE parties 
            SET name = :name, name_en = :name_en, email = :email, phone = :phone, mobile = :mobile, 
                address = :address, city = :city, country = :country, tax_number = :tax, 
                tax_exempt = :tax_exempt,
                credit_limit = :credit_limit, payment_terms = :payment_terms, notes = :notes, 
                status = :status, party_group_id = :group_id, branch_id = :branch_id, currency = :currency
            WHERE id = :id
        """), {
            "id": customer_id, "name": customer.name, "name_en": customer.name_en,
            "email": customer.email, "phone": customer.phone, "mobile": customer.mobile,
            "address": customer.address, "city": customer.city, "country": customer.country,
            "tax": customer.tax_number, "tax_exempt": customer.tax_exempt or False,
            "credit_limit": customer.credit_limit, "payment_terms": customer.payment_terms,
            "notes": customer.notes, "status": customer.status, "group_id": customer.group_id,
            "branch_id": customer.branch_id, "currency": customer.currency
        })

        db.commit()

        # PTY-009: Log activity for customer update
        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(_company_id(current_user))
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
        query += branch_scope_filter_from_scope(branch_scope, "branch_id", params)

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
    db = get_db_connection(_company_id(current_user))
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
    db = get_db_connection(_company_id(current_user))
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
            user_id=_user_id(current_user),
            username=_username(current_user),
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
    db = get_db_connection(_company_id(current_user))
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
            user_id=_user_id(current_user),
            username=_username(current_user),
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
    db = get_db_connection(_company_id(current_user))
    try:
        # Check if any customers linked
        count = db.execute(text("SELECT COUNT(*) FROM parties WHERE party_group_id = :id"), {"id": group_id}).scalar()
        if count > 0:
            raise HTTPException(**http_error(400, "customer_group_has_customers", request))
        db.execute(text("DELETE FROM party_groups WHERE id = :id"), {"id": group_id})
        db.commit()

        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
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
