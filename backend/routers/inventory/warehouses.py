"""
Inventory Module - Warehouses CRUD + Current Stock
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from decimal import Decimal
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from schemas import WarehouseCreate, WarehouseResponse

warehouses_router = APIRouter()
logger = logging.getLogger(__name__)


@warehouses_router.get("/warehouses", response_model=List[WarehouseResponse], dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def list_warehouses(request: Request, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """List Warehouses."""
    if not current_user.company_id:
        raise HTTPException(**http_error(400, "company_id_missing", request))

    db = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        query = """
            SELECT w.id, w.warehouse_name as name, w.warehouse_code as code,
                   w.branch_id, COALESCE(b.branch_name, '') as branch_name,
                   w.gl_inventory_account_id,
                   a.account_code AS gl_inventory_account_code,
                   a.name AS gl_inventory_account_name
            FROM warehouses w
            LEFT JOIN branches b ON w.branch_id = b.id
            LEFT JOIN accounts a ON w.gl_inventory_account_id = a.id
            WHERE 1=1
        """
        params = {}
        query += branch_scope_filter_from_scope(branch_scope, "w.branch_id", params)

        query += " ORDER BY w.id"
        result = db.execute(text(query), params).fetchall()
        return [{
            "id": r.id,
            "name": r.name,
            "code": r.code,
            "branch_id": r.branch_id,
            "branch_name": r.branch_name,
            "gl_inventory_account_id": r.gl_inventory_account_id,
            "gl_inventory_account_code": r.gl_inventory_account_code,
            "gl_inventory_account_name": r.gl_inventory_account_name,
        } for r in result]
    except Exception:
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Error fetching warehouses")
        raise HTTPException(**http_error(500, "warehouse_load_failed", request))
    finally:
        db.close()


@warehouses_router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))])
def create_warehouse(warehouse: WarehouseCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create Warehouse."""
    db = get_db_connection(current_user.company_id)
    try:
        # INV-003: Branch access enforcement on creation
        if warehouse.branch_id:
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                if warehouse.branch_id not in allowed:
                    raise HTTPException(**http_error(403, "cross_branch_create_denied", request))

        # Check duplicate code
        exists = db.execute(text("SELECT 1 FROM warehouses WHERE warehouse_code = :code"), {"code": warehouse.code}).scalar()
        if exists:
            raise HTTPException(**http_error(400, "warehouse_code_duplicate", request))

        # F-31: validate the optional inventory account belongs to this tenant
        # and is a leaf (non-header) asset account so postings are allowed.
        if warehouse.gl_inventory_account_id is not None:
            acc_row = db.execute(
                text(
                    """
                    SELECT id, account_type, COALESCE(is_header, FALSE) AS is_header
                    FROM accounts
                    WHERE id = :id
                    """
                ),
                {"id": warehouse.gl_inventory_account_id},
            ).fetchone()
            if not acc_row:
                raise HTTPException(**http_error(400, "inventory_account_not_found", request))
            if acc_row.is_header:
                raise HTTPException(**http_error(400, "inventory_account_must_be_leaf", request))
            if (acc_row.account_type or "").lower() != "asset":
                raise HTTPException(**http_error(400, "inventory_account_must_be_asset", request))

        result = db.execute(text("""
            INSERT INTO warehouses (warehouse_name, warehouse_code, branch_id, gl_inventory_account_id)
            VALUES (:name, :code, :branch_id, :acc_id) RETURNING id
        """), {
            "name": warehouse.name,
            "code": warehouse.code,
            "branch_id": warehouse.branch_id,
            "acc_id": warehouse.gl_inventory_account_id,
        }).fetchone()

        # Get branch name if branch_id is set
        branch_name = None
        if warehouse.branch_id:
            branch_name = db.execute(text("SELECT branch_name FROM branches WHERE id = :id"), {"id": warehouse.branch_id}).scalar()

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.create", resource_type="warehouse",
            resource_id=str(result[0]),
            details={
                "name": warehouse.name,
                "code": warehouse.code,
                "gl_inventory_account_id": warehouse.gl_inventory_account_id,
            },
            request=request, branch_id=warehouse.branch_id
        )
        db.commit()

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
    """Update Warehouse."""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id, branch_id FROM warehouses WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if existing.branch_id and existing.branch_id not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_edit_denied", request))

        # BUG-FIX: Convert branch_id to int if it's None or invalid
        safe_branch_id = warehouse.branch_id if warehouse.branch_id is not None else None

        # F-31: validate the inventory account if provided. Allow clearing the
        # mapping back to NULL so the warehouse falls back to the global one.
        if warehouse.gl_inventory_account_id is not None:
            acc_row = db.execute(
                text(
                    """
                    SELECT id, account_type, COALESCE(is_header, FALSE) AS is_header
                    FROM accounts
                    WHERE id = :id
                    """
                ),
                {"id": warehouse.gl_inventory_account_id},
            ).fetchone()
            if not acc_row:
                raise HTTPException(**http_error(400, "inventory_account_not_found", request))
            if acc_row.is_header:
                raise HTTPException(**http_error(400, "inventory_account_must_be_leaf", request))
            if (acc_row.account_type or "").lower() != "asset":
                raise HTTPException(**http_error(400, "inventory_account_must_be_asset", request))

        db.execute(text("""
            UPDATE warehouses
            SET warehouse_name = :name,
                warehouse_code = :code,
                branch_id = :branch_id,
                gl_inventory_account_id = :acc_id
            WHERE id = :id
        """), {
            "name": warehouse.name,
            "code": warehouse.code,
            "branch_id": safe_branch_id,
            "acc_id": warehouse.gl_inventory_account_id,
            "id": id,
        })

        # Get branch name if branch_id is set
        branch_name = None
        if warehouse.branch_id:
            branch_name = db.execute(text("SELECT branch_name FROM branches WHERE id = :id"), {"id": warehouse.branch_id}).scalar()

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.update", resource_type="warehouse",
            resource_id=str(id),
            details={
                "name": warehouse.name,
                "gl_inventory_account_id": warehouse.gl_inventory_account_id,
            },
            request=request, branch_id=warehouse.branch_id
        )
        db.commit()

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
    """Delete Warehouse."""
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
            raise HTTPException(**http_error(400, "cannot_delete_default_warehouse", request))

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if warehouse.branch_id and warehouse.branch_id not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_delete_denied", request))

        # INV-001: Check if warehouse has inventory
        stock = db.execute(text(
            "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE warehouse_id = :id"
        ), {"id": id}).scalar()
        if stock and abs(Decimal(str(stock))) > Decimal("0.01"):
            raise HTTPException(**http_error(400, "cannot_delete_warehouse_with_stock", request))

        # INV-001: Check pending transactions
        txn_count = db.execute(text(
            "SELECT COUNT(*) FROM inventory_transactions WHERE warehouse_id = :id"
        ), {"id": id}).scalar()
        if txn_count and txn_count > 0:
            raise HTTPException(**http_error(400, "cannot_delete_warehouse_with_movements", request))

        # INV-DEL: Check active cost layers (FIFO/LIFO not exhausted)
        active_layers = db.execute(text(
            "SELECT COUNT(*) FROM cost_layers WHERE warehouse_id = :id AND is_exhausted = FALSE"
        ), {"id": id}).scalar()
        if active_layers and active_layers > 0:
            raise HTTPException(**http_error(400, "cannot_delete_warehouse_with_movements", request))

        # INV-DEL: Check pending/dispatched shipments referencing this warehouse
        pending_shipments = db.execute(text("""
            SELECT COUNT(*) FROM stock_shipments
            WHERE (source_warehouse_id = :id OR destination_warehouse_id = :id)
              AND status IN ('pending', 'dispatched')
        """), {"id": id}).scalar()
        if pending_shipments and pending_shipments > 0:
            raise HTTPException(**http_error(400, "cannot_delete_warehouse_with_movements", request))

        linked_docs = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM purchase_orders WHERE warehouse_id = :id
                UNION ALL
                SELECT 1 FROM delivery_orders WHERE warehouse_id = :id
            ) AS refs
        """), {"id": id}).scalar()
        if linked_docs and linked_docs > 0:
            raise HTTPException(**http_error(400, "cannot_delete_warehouse_with_movements", request))

        db.execute(text("DELETE FROM warehouses WHERE id = :id"), {"id": id})

        # INV-012: Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="warehouse.delete", resource_type="warehouse",
            resource_id=str(id), details={"name": warehouse.warehouse_name},
            request=request, branch_id=warehouse.branch_id
        )
        db.commit()

        return {"message": i18n_message("warehouse_deleted_success", request)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@warehouses_router.get("/warehouses/{id}", response_model=WarehouseResponse, dependencies=[Depends(require_permission("stock.view"))])
def get_warehouse(request: Request, id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل مستودع"""
    db = get_db_connection(current_user.company_id)
    try:
        warehouse = db.execute(text("""
            SELECT w.id, w.warehouse_name as name, w.warehouse_code as code,
                   w.branch_id, b.branch_name,
                   w.gl_inventory_account_id,
                   a.account_code AS gl_inventory_account_code,
                   a.name AS gl_inventory_account_name
            FROM warehouses w
            LEFT JOIN branches b ON w.branch_id = b.id
            LEFT JOIN accounts a ON w.gl_inventory_account_id = a.id
            WHERE w.id = :id
        """), {"id": id}).fetchone()
        if not warehouse:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-003: Branch access enforcement
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if warehouse.branch_id and warehouse.branch_id not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_access_denied", request))

        return {
            "id": warehouse.id,
            "name": warehouse.name,
            "code": warehouse.code,
            "branch_id": warehouse.branch_id,
            "branch_name": warehouse.branch_name,
            "gl_inventory_account_id": warehouse.gl_inventory_account_id,
            "gl_inventory_account_code": warehouse.gl_inventory_account_code,
            "gl_inventory_account_name": warehouse.gl_inventory_account_name,
        }
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
