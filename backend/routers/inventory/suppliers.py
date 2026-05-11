"""
Inventory Module - Suppliers CRUD
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from .schemas import SupplierCreate, SupplierResponse

suppliers_router = APIRouter()
logger = logging.getLogger(__name__)


@suppliers_router.get("/suppliers", response_model=List[SupplierResponse], dependencies=[Depends(require_permission("buying.view"))])
def list_suppliers(
    skip: int = 0,
    limit: int = 100,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة الموردين مع أرصدة حسب الفرع والموقع"""
    db = get_db_connection(current_user.company_id)
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        
        # Get branch currency if branch_id is provided
        branch_cur = base_cur
        if branch_id:
            branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
        
        # Subquery to get aggregated balance per party
        if branch_id:
            # When branch is selected: show balance in branch's local currency
            balance_subquery = """
                SELECT ps.party_id,
                       COALESCE(SUM(psb.balance), 0) as total_balance,
                       psb.currency as balance_currency
                FROM party_sites ps
                LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                WHERE psb.company_branch_id = :bid
                GROUP BY ps.party_id, psb.currency
            """
            balance_params = {"bid": branch_id}
        else:
            # When all branches: show total in base currency
            balance_subquery = """
                SELECT ps.party_id,
                       COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_balance,
                       :base_cur as balance_currency
                FROM party_sites ps
                LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON psb.currency = c.code
                GROUP BY ps.party_id
            """
            balance_params = {"base_cur": base_cur}

        query = f"""
            SELECT
                p.id,
                p.name,
                p.name_en,
                p.phone,
                p.email,
                p.address,
                p.tax_number,
                p.commercial_register,
                p.currency,
                p.status = 'active' as is_active,
                p.created_at,
                p.party_group_id as group_id,
                COALESCE(bal.total_balance, 0) as current_balance,
                COALESCE(bal.balance_currency, :display_cur) as balance_currency,
                ps_default.site_name as site_name,
                ps_default.id as site_id
            FROM parties p
            LEFT JOIN party_sites ps_default ON ps_default.party_id = p.id AND ps_default.is_default = TRUE
            LEFT JOIN ({balance_subquery}) bal ON bal.party_id = p.id
            WHERE p.is_supplier = TRUE
        """
        params = {"limit": limit, "skip": skip, "display_cur": branch_cur, **balance_params}

        query += " ORDER BY p.name ASC LIMIT :limit OFFSET :skip"
        result = db.execute(text(query), params).fetchall()

        suppliers = []
        for row in result:
            d = dict(row._mapping)
            display_currency = d.get("balance_currency") or base_cur
            
            suppliers.append({
                "id": d["id"],
                "name": d["name"],
                "name_en": d["name_en"],
                "phone": d["phone"],
                "email": d["email"],
                "address": d["address"],
                "tax_number": d["tax_number"],
                "commercial_register": d["commercial_register"],
                "currency": d["currency"],
                "group_id": d.get("group_id"),
                "current_balance": float(d["current_balance"] or 0),
                "balance_display": float(d["current_balance"] or 0),
                "display_currency": display_currency,
                "balance_sar": float(d["current_balance"] or 0) if display_currency == base_cur else float(d["current_balance"] or 0) * float(db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": display_currency}).scalar() or 1),
                "site_id": d.get("site_id"),
                "site_name": d.get("site_name"),
                "is_active": d["is_active"],
                "created_at": d["created_at"]
            })
        return suppliers
    finally:
        db.close()


@suppliers_router.get("/suppliers/{id}", response_model=SupplierResponse, dependencies=[Depends(require_permission("buying.view"))])
def get_supplier(
    id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض تفاصيل مورد محدد مع مواقعه وأرصدة كل موقع"""
    db = get_db_connection(current_user.company_id)
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        
        supplier = db.execute(text("""
            SELECT
                p.id, p.name, p.name_en, p.phone, p.email, p.address, p.tax_number,
                p.commercial_register, p.currency, p.branch_id,
                p.status = 'active' as is_active, p.created_at,
                p.party_group_id as group_id
            FROM parties p
            WHERE p.id = :id AND p.is_supplier = TRUE
        """), {"id": id}).fetchone()

        if not supplier:
            raise HTTPException(**http_error(404, "supplier_not_found"))

        # Get party sites
        sites = db.execute(text("""
            SELECT ps.id, ps.site_name, ps.currency, ps.country, ps.payment_terms, ps.is_default
            FROM party_sites ps
            WHERE ps.party_id = :pid AND ps.is_active = TRUE
            ORDER BY ps.is_default DESC, ps.site_name
        """), {"pid": id}).fetchall()

        # Get balances per site per branch
        balance_query = """
            SELECT ps.id as site_id, ps.site_name, ps.currency as site_currency,
                   psb.company_branch_id, b.branch_name, psb.account_type, psb.currency, psb.balance
            FROM party_sites ps
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            LEFT JOIN branches b ON psb.company_branch_id = b.id
            WHERE ps.party_id = :pid AND ps.is_active = TRUE
        """
        balance_params = {"pid": id}
        
        if branch_id:
            balance_query += " AND (psb.company_branch_id = :bid OR psb.company_branch_id IS NULL)"
            balance_params["bid"] = branch_id
        
        balance_query += " ORDER BY ps.site_name, b.branch_name"
        balance_rows = db.execute(text(balance_query), balance_params).fetchall()
        
        # Group balances by site
        sites_data = []
        total_sar = 0
        for site in sites:
            site_balances = [r for r in balance_rows if r.site_id == site.id and r.balance is not None]
            balance_list = []
            site_total = 0
            for b in site_balances:
                bal = float(b.balance)
                if b.currency != base_cur:
                    rate = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": b.currency}).scalar()
                    bal_sar = bal * float(rate or 1)
                else:
                    bal_sar = bal
                site_total += bal_sar
                balance_list.append({
                    "branch_id": b.company_branch_id,
                    "branch_name": b.branch_name,
                    "account_type": b.account_type,
                    "currency": b.currency,
                    "balance": bal
                })
            
            total_sar += site_total
            sites_data.append({
                "id": site.id,
                "site_name": site.site_name,
                "currency": site.currency,
                "country": site.country,
                "payment_terms": site.payment_terms,
                "is_default": site.is_default,
                "balances": balance_list,
                "total_sar": site_total
            })

        return {
            "id": supplier.id,
            "name": supplier.name,
            "name_en": supplier.name_en,
            "phone": supplier.phone,
            "email": supplier.email,
            "address": supplier.address,
            "tax_number": supplier.tax_number,
            "commercial_register": supplier.commercial_register,
            "currency": supplier.currency,
            "branch_id": supplier.branch_id,
            "group_id": getattr(supplier, 'group_id', None),
            "current_balance": total_sar,
            "balance": total_sar,
            "balance_bc": total_sar,
            "sites": sites_data,
            "balances": [b for site in sites_data for b in site["balances"]],
            "is_active": supplier.is_active,
            "created_at": supplier.created_at
        }
    finally:
        db.close()


@suppliers_router.post("/suppliers", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(["parties.manage", "buying.create"]))])
def create_supplier(
    supplier: SupplierCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مورد جديد مع إنشاء موقع افتراضي تلقائياً"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import generate_sequential_number
        code = generate_sequential_number(db, "SUP", "parties", "party_code")

        # Merge if tax number exists
        existing_id = None
        if supplier.tax_number:
            existing_id = db.execute(text("SELECT id FROM parties WHERE tax_number = :tax LIMIT 1"), {"tax": supplier.tax_number}).scalar()

        if existing_id:
            db.execute(text("UPDATE parties SET is_supplier = TRUE WHERE id = :id"), {"id": existing_id})
            pid = existing_id
            result = db.execute(text("SELECT current_balance, created_at FROM parties WHERE id = :id"), {"id": pid}).fetchone()
        else:
            result = db.execute(text("""
                INSERT INTO parties (
                    party_code, name, name_en, 
                    phone, email, address, tax_number, tax_exempt, branch_id, is_supplier, status, currency
                ) VALUES (
                    :code, :name, :name_en, :phone, :email, :address, :tax, :tax_exempt, :branch_id, TRUE, 'active', :currency
                ) RETURNING id, current_balance, created_at
            """), {
                "code": code,
                "name": supplier.name,
                "name_en": supplier.name_en,
                "phone": supplier.phone,
                "email": supplier.email,
                "address": supplier.address,
                "tax": supplier.tax_number,
                "tax_exempt": supplier.tax_exempt or False,
                "branch_id": supplier.branch_id,
                "currency": supplier.currency
            }).fetchone()
            pid = result[0]

        # إنشاء موقع افتراضي للمورد
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        sup_currency = supplier.currency or base_cur
        
        # التحقق إذا يوجد موقع افتراضي
        existing_site = db.execute(text(
            "SELECT id FROM party_sites WHERE party_id = :pid AND is_default = TRUE LIMIT 1"
        ), {"pid": pid}).fetchone()
        
        if not existing_site:
            db.execute(text("""
                INSERT INTO party_sites (party_id, site_name, site_name_en, country, country_code, currency, phone, is_default, is_active)
                VALUES (:pid, :name, :name_en, :country, :cc, :cur, :phone, TRUE, TRUE)
            """), {
                "pid": pid,
                "name": supplier.name,
                "name_en": supplier.name_en,
                "country": supplier.address or "",
                "cc": "",
                "cur": sup_currency,
                "phone": supplier.phone
            })
            
            # تحديث default_site_id
            site_id = db.execute(text("SELECT LASTVAL() as id"), {}).fetchone().id
            db.execute(text("UPDATE parties SET default_site_id = :sid WHERE id = :pid"),
                      {"sid": site_id, "pid": pid})

        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="inventory.supplier.create",
            resource_type="supplier",
            resource_id=str(pid),
            details={"name": supplier.name},
            request=None,
            branch_id=supplier.branch_id
        )

        return {
            **supplier.model_dump(),
            "id": pid,
            "current_balance": float(result.current_balance or 0),
            "is_active": True,
            "created_at": result.created_at
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating supplier: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@suppliers_router.put("/suppliers/{id}", response_model=SupplierResponse, dependencies=[Depends(require_permission(["parties.manage", "buying.edit"]))])
def update_supplier(
    id: int,
    supplier: SupplierCreate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث بيانات مورد"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        existing = db.execute(text("SELECT id, created_at, current_balance, branch_id FROM parties WHERE id = :id AND is_supplier = TRUE"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "supplier_not_found"))

        db.execute(text("""
            UPDATE parties SET
                name = :name,
                name_en = :name_en,
                phone = :phone,
                email = :email,
                address = :address,
                tax_number = :tax,
                tax_exempt = :tax_exempt,
                branch_id = :branch_id,
                currency = :currency,
                updated_at = NOW()
            WHERE id = :id
        """), {
            "id": id,
            "name": supplier.name,
            "name_en": supplier.name_en,
            "phone": supplier.phone,
            "email": supplier.email,
            "address": supplier.address,
            "tax": supplier.tax_number,
            "tax_exempt": supplier.tax_exempt or False,
            "branch_id": supplier.branch_id,
            "currency": supplier.currency
        })

        db.commit()

        log_activity(
            db,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="inventory.supplier.update",
            resource_type="supplier",
            resource_id=str(id),
            details={"name": supplier.name},
            request=None,
            branch_id=supplier.branch_id
        )

        return {
            **supplier.model_dump(),
            "id": id,
            "current_balance": float(existing.current_balance or 0),
            "is_active": True,
            "created_at": existing.created_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating supplier: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@suppliers_router.delete("/suppliers/{id}", dependencies=[Depends(require_permission(["parties.manage", "buying.delete"]))], response_model=Dict[str, Any])
def delete_supplier(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف مورد"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        supplier = db.execute(text("SELECT id, name, branch_id FROM parties WHERE id = :id AND is_supplier = TRUE"), {"id": id}).fetchone()
        if not supplier:
            raise HTTPException(**http_error(404, "supplier_not_found"))

        # Check if supplier has balance
        balance = db.execute(text("SELECT COALESCE(current_balance, 0) FROM parties WHERE id = :id"), {"id": id}).scalar()
        if balance and abs(balance) > 0.01:
            raise HTTPException(**http_error(400, "cannot_delete_supplier_with_balance", request))

        # Check if supplier has transactions
        usage = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM invoices WHERE (party_id = :id OR supplier_id = :id) AND invoice_type IN ('purchase', 'purchase_return')
                UNION ALL
                SELECT 1 FROM purchase_orders WHERE party_id = :id OR supplier_id = :id
            ) AS usage
        """), {"id": id}).scalar()

        if usage and usage > 0:
            raise HTTPException(**http_error(400, "cannot_delete_supplier_with_transactions", request))

        # Delete supplier (set is_supplier to FALSE instead of actual delete to preserve data integrity)
        db.execute(text("UPDATE parties SET is_supplier = FALSE, status = 'inactive' WHERE id = :id"), {"id": id})
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="supplier.delete",
            resource_type="supplier",
            resource_id=str(id),
            details={"name": supplier.name},
            request=request,
            branch_id=None
        )

        return {"message": i18n_message("supplier_deleted_success", request)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting supplier: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
