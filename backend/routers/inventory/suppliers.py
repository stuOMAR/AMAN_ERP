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
from utils.permissions import require_permission
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
    """عرض قائمة الموردين"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT
                id,
                name,
                name_en,
                phone,
                email,
                address,
                tax_number,
                commercial_register,
                currency,
                status = 'active' as is_active,
                created_at,
                party_group_id as group_id,
                COALESCE(current_balance, 0) as current_balance
            FROM parties p
            WHERE p.is_supplier = TRUE
        """
        params = {"limit": limit, "skip": skip}

        # PTY-006/019: Apply branch_id filter if provided, else enforce allowed_branches
        if branch_id:
            query += " AND p.branch_id = :branch_id"
            params["branch_id"] = branch_id
        else:
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND p.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

        query += " ORDER BY p.created_at DESC LIMIT :limit OFFSET :skip"
        result = db.execute(text(query), params).fetchall()

        suppliers = []
        for row in result:
            suppliers.append({
                "id": row.id,
                "name": row.name,
                "name_en": row.name_en,
                "phone": row.phone,
                "email": row.email,
                "address": row.address,
                "tax_number": row.tax_number,
                "commercial_register": row.commercial_register,
                "currency": row.currency,
                "group_id": getattr(row, 'group_id', None),
                "current_balance": float(row.current_balance or 0),
                "is_active": row.is_active,
                "created_at": row.created_at
            })
        return suppliers
    finally:
        db.close()


@suppliers_router.get("/suppliers/{id}", response_model=SupplierResponse, dependencies=[Depends(require_permission("buying.view"))])
def get_supplier(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """عرض تفاصيل مورد محدد"""
    db = get_db_connection(current_user.company_id)
    try:
        supplier = db.execute(text("""
            SELECT
                id, name, name_en, phone, email, address, tax_number,
                commercial_register, currency, branch_id,
                status = 'active' as is_active, created_at,
                party_group_id as group_id,
                COALESCE(current_balance, 0) as current_balance
            FROM parties
            WHERE id = :id AND is_supplier = TRUE
        """), {"id": id}).fetchone()

        if not supplier:
            raise HTTPException(**http_error(404, "supplier_not_found"))

        # PTY-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if supplier.branch_id and supplier.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك الوصول لبيانات مورد خارج فروعك")

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
            "current_balance": float(supplier.current_balance or 0),
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
    """إنشاء مورد جديد"""
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
                    phone, email, address, tax_number, branch_id, is_supplier, status, currency
                ) VALUES (
                    :code, :name, :name_en, :phone, :email, :address, :tax, :branch_id, TRUE, 'active', :currency
                ) RETURNING id, current_balance, created_at
            """), {
                "code": code,
                "name": supplier.name,
                "name_en": supplier.name_en,
                "phone": supplier.phone,
                "email": supplier.email,
                "address": supplier.address,
                "tax": supplier.tax_number,
                "branch_id": supplier.branch_id,
                "currency": supplier.currency
            }).fetchone()
            pid = result[0]

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

        # PTY-004: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if existing.branch_id and existing.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك تعديل مورد خارج فروعك")

        db.execute(text("""
            UPDATE parties SET
                name = :name,
                name_en = :name_en,
                phone = :phone,
                email = :email,
                address = :address,
                tax_number = :tax,
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

        # PTY-003: Branch access enforcement for delete
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if supplier.branch_id and supplier.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك حذف مورد خارج فروعك")

        # Check if supplier has balance
        balance = db.execute(text("SELECT COALESCE(current_balance, 0) FROM parties WHERE id = :id"), {"id": id}).scalar()
        if balance and abs(balance) > 0.01:
            raise HTTPException(status_code=400, detail="لا يمكن حذف مورد له رصيد مستحق")

        # Check if supplier has transactions
        usage = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM invoices WHERE (party_id = :id OR supplier_id = :id) AND invoice_type IN ('purchase', 'purchase_return')
                UNION ALL
                SELECT 1 FROM purchase_orders WHERE party_id = :id OR supplier_id = :id
            ) AS usage
        """), {"id": id}).scalar()

        if usage and usage > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف مورد له معاملات سابقة")

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

        return {"message": "تم حذف المورد بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting supplier: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
