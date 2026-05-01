"""
Inventory Module - Warehouses CRUD + Current Stock
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
from schemas import WarehouseCreate, WarehouseResponse

warehouses_router = APIRouter()
logger = logging.getLogger(__name__)


@warehouses_router.get("/warehouses", response_model=List[WarehouseResponse], dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def list_warehouses(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT w.id, w.warehouse_name as name, w.warehouse_code as code, 
                   w.branch_id, COALESCE(b.branch_name, '') as branch_name
            FROM warehouses w
            LEFT JOIN branches b ON w.branch_id = b.id
            WHERE 1=1
        """
        params = {}
        if branch_id:
            query += " AND w.branch_id = :bid"
            params["bid"] = branch_id
        else:
            # INV-002: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND w.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

        query += " ORDER BY w.id"
        result = db.execute(text(query), params).fetchall()
        return [{
            "id": r.id,
            "name": r.name,
            "code": r.code,
            "branch_id": r.branch_id,
            "branch_name": r.branch_name
        } for r in result]
    except Exception:
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Error fetching warehouses")
        raise HTTPException(status_code=500, detail="تعذّر جلب المستودعات")
    finally:
        db.close()


@warehouses_router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))])
def create_warehouse(warehouse: WarehouseCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        # Check duplicate code
        exists = db.execute(text("SELECT 1 FROM warehouses WHERE warehouse_code = :code"), {"code": warehouse.code}).scalar()
        if exists:
            raise HTTPException(status_code=400, detail="كود المستودع موجود مسبقاً")

        result = db.execute(text("""
            INSERT INTO warehouses (warehouse_name, warehouse_code, branch_id) 
            VALUES (:name, :code, :branch_id) RETURNING id
        """), {"name": warehouse.name, "code": warehouse.code, "branch_id": warehouse.branch_id}).fetchone()
        db.commit()

        # Get branch name if branch_id is set
        branch_name = None
        if warehouse.branch_id:
            branch_name = db.execute(text("SELECT branch_name FROM branches WHERE id = :id"), {"id": warehouse.branch_id}).scalar()

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.create", resource_type="warehouse",
            resource_id=str(result[0]), details={"name": warehouse.name, "code": warehouse.code},
            request=request, branch_id=warehouse.branch_id
        )

        return {**warehouse.model_dump(), "id": result[0], "branch_name": branch_name}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@warehouses_router.put("/warehouses/{id}", response_model=WarehouseResponse, dependencies=[Depends(require_permission("stock.manage"))])
def update_warehouse(id: int, warehouse: WarehouseCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id, branch_id FROM warehouses WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if existing.branch_id and existing.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك تعديل مستودع خارج فروعك")

        db.execute(text("""
            UPDATE warehouses SET warehouse_name = :name, warehouse_code = :code, branch_id = :branch_id
            WHERE id = :id
        """), {"name": warehouse.name, "code": warehouse.code, "branch_id": warehouse.branch_id, "id": id})
        db.commit()

        # Get branch name if branch_id is set
        branch_name = None
        if warehouse.branch_id:
            branch_name = db.execute(text("SELECT branch_name FROM branches WHERE id = :id"), {"id": warehouse.branch_id}).scalar()

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.update", resource_type="warehouse",
            resource_id=str(id), details={"name": warehouse.name},
            request=request, branch_id=warehouse.branch_id
        )

        return {**warehouse.model_dump(), "id": id, "branch_name": branch_name}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@warehouses_router.delete("/warehouses/{id}", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def delete_warehouse(id: int, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        # INV-001: Check existence
        warehouse = db.execute(text("""
            SELECT w.id, w.warehouse_name, w.branch_id, w.is_default
            FROM warehouses w WHERE w.id = :id
        """), {"id": id}).fetchone()
        if not warehouse:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-001: Block deleting default warehouse
        if getattr(warehouse, 'is_default', False):
            raise HTTPException(status_code=400, detail="لا يمكن حذف المستودع الافتراضي")

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if warehouse.branch_id and warehouse.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك حذف مستودع خارج فروعك")

        # INV-001: Check if warehouse has inventory
        stock = db.execute(text(
            "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE warehouse_id = :id"
        ), {"id": id}).scalar()
        if stock and abs(float(stock)) > 0.01:
            raise HTTPException(status_code=400, detail="لا يمكن حذف مستودع به رصيد مخزون")

        # INV-001: Check pending transactions
        txn_count = db.execute(text(
            "SELECT COUNT(*) FROM inventory_transactions WHERE warehouse_id = :id"
        ), {"id": id}).scalar()
        if txn_count and txn_count > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف مستودع له حركات سابقة")

        db.execute(text("DELETE FROM warehouses WHERE id = :id"), {"id": id})
        db.commit()

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.delete", resource_type="warehouse",
            resource_id=str(id), details={"name": warehouse.warehouse_name},
            request=request, branch_id=warehouse.branch_id
        )

        return {"message": "تم حذف المستودع بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@warehouses_router.get("/warehouses/{id}", response_model=WarehouseResponse, dependencies=[Depends(require_permission("stock.view"))])
def get_warehouse(id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل مستودع"""
    db = get_db_connection(current_user.company_id)
    try:
        warehouse = db.execute(text("""
            SELECT w.id, w.warehouse_name as name, w.warehouse_code as code, 
                   w.branch_id, b.branch_name
            FROM warehouses w
            LEFT JOIN branches b ON w.branch_id = b.id
            WHERE w.id = :id
        """), {"id": id}).fetchone()
        if not warehouse:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if warehouse.branch_id and warehouse.branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك الوصول لمستودع خارج فروعك")

        return {"id": warehouse.id, "name": warehouse.name, "code": warehouse.code, "branch_id": warehouse.branch_id, "branch_name": warehouse.branch_name}
    finally:
        db.close()


@warehouses_router.get("/warehouses/{id}/current-stock", dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))], response_model=List[Dict[str, Any]])
def get_warehouse_current_stock(id: int, current_user: dict = Depends(get_current_user)):
    """جرد المستودع: المنتجات والكميات (مخصص للمستودع المحدد)"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check if warehouse exists
        exists = db.execute(text("SELECT 1 FROM warehouses WHERE id = :id"), {"id": id}).scalar()
        if not exists:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        result = db.execute(text("""
            SELECT p.id, p.product_name, p.product_code, i.quantity, u.unit_name
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE i.warehouse_id = :id AND i.quantity != 0
            ORDER BY p.product_name
        """), {"id": id}).fetchall()

        return [
            {
                "id": row.id,
                "product_name": row.product_name,
                "product_code": row.product_code,
                "quantity": str(row.quantity),
                "unit_name": row.unit_name or "قطعة"
            }
            for row in result
        ]
    finally:
        db.close()
