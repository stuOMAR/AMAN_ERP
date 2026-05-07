"""FIFO/LIFO Costing endpoints — cost layers, method changes, valuation."""

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from typing import Optional

from database import db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, resolve_branch_scope, validate_branch_access
from services.costing_service import CostingService
from schemas.costing import (
    CostLayerRead,
    CostingMethodChange,
    CostingMethodChangeResult,
    ConsumptionHistoryRead,
    InventoryValuationReport,
)

costing_router = APIRouter(prefix="/costing", tags=["Inventory Costing"])


@costing_router.get(
    "/layers",
    response_model=list[CostLayerRead],
    dependencies=[Depends(require_permission("inventory.costing_view"))],
)
def list_cost_layers(
    product_id: Optional[int] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    include_exhausted: bool = Query(False),
    current_user=Depends(get_current_user),
):
    """List cost layers with optional product/warehouse filter."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if hasattr(current_user, "company_id") else current_user.get("company_id")
    with db_connection(company_id) as conn:
        if warehouse_id:
            wh_row = conn.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).fetchone()
            if wh_row:
                validate_branch_access(current_user, wh_row.branch_id)
                if branch_scope["branch_id"] is not None and wh_row.branch_id != branch_scope["branch_id"]:
                    return []
                if branch_scope["branch_ids"] is not None and wh_row.branch_id not in branch_scope["branch_ids"]:
                    return []
        rows = CostingService.get_cost_layers(
            conn, product_id=product_id, warehouse_id=warehouse_id,
            include_exhausted=include_exhausted,
            branch_id=branch_scope["branch_id"], branch_ids=branch_scope["branch_ids"],
        )
        return [dict(r._mapping) for r in rows]


@costing_router.get(
    "/layers/{product_id}",
    response_model=list[CostLayerRead],
    dependencies=[Depends(require_permission("inventory.costing_view"))],
)
def get_product_layers(
    product_id: int,
    warehouse_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    include_exhausted: bool = Query(False),
    current_user=Depends(get_current_user),
):
    """Get all cost layers for a specific product."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if hasattr(current_user, "company_id") else current_user.get("company_id")
    with db_connection(company_id) as conn:
        if warehouse_id:
            wh_row = conn.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).fetchone()
            if wh_row:
                validate_branch_access(current_user, wh_row.branch_id)
                if branch_scope["branch_id"] is not None and wh_row.branch_id != branch_scope["branch_id"]:
                    return []
                if branch_scope["branch_ids"] is not None and wh_row.branch_id not in branch_scope["branch_ids"]:
                    return []
        rows = CostingService.get_cost_layers(
            conn, product_id=product_id, warehouse_id=warehouse_id, include_exhausted=include_exhausted,
            branch_id=branch_scope["branch_id"], branch_ids=branch_scope["branch_ids"],
        )
        return [dict(r._mapping) for r in rows]


@costing_router.put(
    "/method",
    response_model=CostingMethodChangeResult,
    dependencies=[Depends(require_permission("inventory.costing_manage"))],
)
def change_costing_method(
    data: CostingMethodChange,
    current_user=Depends(get_current_user),
):
    """Change the costing method (FIFO/LIFO) for a product/warehouse."""
    company_id = current_user.company_id if hasattr(current_user, "company_id") else current_user.get("company_id")
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user.get("id"))
    with db_connection(company_id) as conn:
        if data.warehouse_id:
            wh_row = conn.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": data.warehouse_id}).fetchone()
            if wh_row:
                validate_branch_access(current_user, wh_row.branch_id)
        result = CostingService.change_costing_method(
            conn,
            product_id=data.product_id,
            warehouse_id=data.warehouse_id,
            new_method=data.new_method.value,
            user_id=user_id,
        )
        conn.commit()
        return result


@costing_router.get(
    "/valuation",
    response_model=InventoryValuationReport,
    dependencies=[Depends(require_permission("inventory.costing_view"))],
)
def get_valuation_report(
    as_of_date: Optional[date] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    current_user=Depends(get_current_user),
):
    """Get inventory valuation report by costing method."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if hasattr(current_user, "company_id") else current_user.get("company_id")
    with db_connection(company_id) as conn:
        if warehouse_id:
            wh_row = conn.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).fetchone()
            if wh_row:
                validate_branch_access(current_user, wh_row.branch_id)
                if branch_scope["branch_id"] is not None and wh_row.branch_id != branch_scope["branch_id"]:
                    return {"as_of_date": str(as_of_date or "current"), "items": [], "grand_total": 0}
                if branch_scope["branch_ids"] is not None and wh_row.branch_id not in branch_scope["branch_ids"]:
                    return {"as_of_date": str(as_of_date or "current"), "items": [], "grand_total": 0}
        return CostingService.calculate_inventory_valuation(
            conn,
            as_of_date=as_of_date,
            warehouse_id=warehouse_id,
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
        )


@costing_router.get(
    "/consumption/{product_id}",
    response_model=list[ConsumptionHistoryRead],
    dependencies=[Depends(require_permission("inventory.costing_view"))],
)
def get_consumption_history(
    product_id: int,
    warehouse_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    current_user=Depends(get_current_user),
):
    """Get consumption history for a product's cost layers."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if hasattr(current_user, "company_id") else current_user.get("company_id")
    with db_connection(company_id) as conn:
        if warehouse_id:
            wh_row = conn.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).fetchone()
            if wh_row:
                validate_branch_access(current_user, wh_row.branch_id)
                if branch_scope["branch_id"] is not None and wh_row.branch_id != branch_scope["branch_id"]:
                    return []
                if branch_scope["branch_ids"] is not None and wh_row.branch_id not in branch_scope["branch_ids"]:
                    return []
        rows = CostingService.get_consumption_history(
            conn,
            product_id=product_id,
            warehouse_id=warehouse_id,
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
        )
        return [dict(r._mapping) for r in rows]
