"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from decimal import Decimal
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error
from pydantic import BaseModel
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_module, resolve_branch_scope
from database import get_db_connection
from utils.tx import transactional
from utils.accounting import get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.exports import generate_excel, generate_pdf, create_export_response
from utils.audit import log_activity
from services.gl_service import create_journal_entry
from schemas import UserResponse
from schemas.manufacturing_advanced import (
    WorkCenterCreate, WorkCenterResponse,
    RouteCreate, RouteResponse,
    BOMCreate, BOMResponse,
    ProductionOrderCreate, ProductionOrderResponse,
    ProductionOrderOperationResponse, MRPPlanResponse,
    EquipmentCreate, EquipmentResponse,
    MaintenanceLogCreate, MaintenanceLogResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import ActualCostUpdate, QCCheckCreate, calculate_production_cost, check_inventory_sufficiency


def _validate_order_warehouse_access(conn, current_user: UserResponse, *warehouse_ids: Optional[int]) -> None:
    from utils.permissions import validate_branch_access

    for warehouse_id in warehouse_ids:
        if not warehouse_id:
            continue
        warehouse = conn.execute(
            text("SELECT branch_id FROM warehouses WHERE id = :wid"),
            {"wid": warehouse_id},
        ).fetchone()
        if not warehouse:
            raise HTTPException(**http_error(404, "warehouse_not_found"))
        if warehouse.branch_id:
            validate_branch_access(current_user, warehouse.branch_id)

@router.get("/orders/cost-estimate", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def estimate_production_cost(request: Request, 
    bom_id: int = Query(..., description="BOM ID"),
    quantity: float = Query(..., description="Production quantity"),
    current_user: UserResponse = Depends(get_current_user)
):
    """Estimate production cost before creating an order."""
    conn = get_db_connection(current_user.company_id)
    try:
        bom = conn.execute(text("SELECT * FROM bill_of_materials WHERE id = :bid AND is_deleted = false"), {"bid": bom_id}).fetchone()
        if not bom:
            raise HTTPException(**http_error(404, "bom_not_found", request))
        cost = calculate_production_cost(conn, bom_id, quantity)
        return cost
    finally:
        conn.close()


@router.get("/orders/check-materials", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def check_materials_availability(
    bom_id: int = Query(..., description="BOM ID"),
    quantity: float = Query(..., description="Production quantity"),
    warehouse_id: Optional[int] = Query(None, description="Source warehouse ID"),
    current_user: UserResponse = Depends(get_current_user)
):
    """Check if enough raw materials are available for production."""
    conn = get_db_connection(current_user.company_id)
    try:
        is_sufficient, shortages = check_inventory_sufficiency(conn, bom_id, quantity, warehouse_id)
        return {"is_sufficient": is_sufficient, "shortages": shortages}
    finally:
        conn.close()

@router.get("/orders", response_model=List[ProductionOrderResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_production_orders(
    branch_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user)
):
    """List Production Orders."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    conn = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT po.*, p.product_name as product_name, b.name as bom_name,
                   po.order_number, po.status, po.produced_quantity, po.scrapped_quantity, po.created_at
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
        """
        params = {"limit": limit, "offset": offset}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "po.branch_id", params, prefix="WHERE")
        if branch_filter:
            query += f" {branch_filter}"
        query += " ORDER BY po.id DESC LIMIT :limit OFFSET :offset"
        orders_db = conn.execute(text(query), params).fetchall()

        result = []
        for o in orders_db:
            order_dict = dict(o._mapping)
            # Fetch operations status
            ops = conn.execute(text("""
                SELECT poo.*, mo.description as operation_description
                FROM production_order_operations poo
                LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
                WHERE poo.production_order_id = :poid
                ORDER BY mo.sequence
            """), {"poid": o.id}).fetchall()
            order_dict['operations'] = [dict(op._mapping) for op in ops]
            result.append(order_dict)

        return result
    finally:
        conn.close()
 
@router.get("/orders/{order_id}", response_model=ProductionOrderResponse, dependencies=[Depends(require_permission("manufacturing.view"))])
def get_production_order(request: Request, order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Get Production Order."""
    conn = get_db_connection(current_user.company_id)
    try:
        o = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :oid
        """), {"oid": order_id}).fetchone()
        
        if not o:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if o.branch_id:
            validate_branch_access(current_user, o.branch_id)
            
        order_dict = dict(o._mapping)
        
        # Fetch operations
        ops = conn.execute(text("""
            SELECT poo.*, mo.description as operation_description, wc.name as work_center_name, wc.cost_per_hour
            FROM production_order_operations poo
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            LEFT JOIN work_centers wc ON poo.work_center_id = wc.id
            WHERE poo.production_order_id = :poid
            ORDER BY mo.sequence
        """), {"poid": order_id}).fetchall()
        order_dict['operations'] = [dict(op._mapping) for op in ops]
        
        # Calculate Labor & Overhead Cost
        total_labor_cost = 0
        for op in ops:
            duration_hours = (op.actual_run_time or 0) / 60.0
            rate = op.cost_per_hour or 0
            total_labor_cost += (duration_hours * rate)
            
        order_dict['total_labor_overhead_cost'] = total_labor_cost
        
        # Calculate Material Cost (from transactions if exists, else estimate from BOM)
        mat_cost_query = conn.execute(text("""
            SELECT SUM(ABS(quantity) * unit_cost) 
            FROM inventory_transactions 
            WHERE reference_type = 'production_order' AND reference_id = :oid AND transaction_type = 'production_out'
        """), {"oid": order_id}).scalar()
        
        current_material_cost = mat_cost_query or 0
        
        # If 0 (maybe draft), estimate from BOM
        if current_material_cost == 0 and o.status == 'draft':
             bom_cost = conn.execute(text("""
                SELECT SUM(bc.quantity * p.cost_price)
                FROM bom_components bc
                JOIN products p ON bc.component_product_id = p.id
                WHERE bc.bom_id = :bid AND bc.is_deleted = false
             """), {"bid": o.bom_id}).scalar()
             current_material_cost = (bom_cost or 0) * o.quantity

        order_dict['total_material_cost'] = current_material_cost
        order_dict['unit_production_cost'] = (current_material_cost + total_labor_cost) / (o.quantity or 1)
        
        return order_dict
    finally:
        conn.close()

@router.get("/operations", response_model=List[ProductionOrderOperationResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_all_operations(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    work_center_id: Optional[int] = None,
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """List All Operations."""
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT poo.*, mo.description as operation_description, wc.name as work_center_name,
                   po.order_number, p.product_name
            FROM production_order_operations poo
            JOIN production_orders po ON poo.production_order_id = po.id
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            LEFT JOIN work_centers wc ON poo.work_center_id = wc.id
            LEFT JOIN products p ON po.product_id = p.id
            WHERE 1=1
        """
        params = {}
        
        query += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        
        if work_center_id:
            query += " AND poo.work_center_id = :wcid"
            params["wcid"] = work_center_id
            
        if status:
            query += " AND poo.status = :status"
            params["status"] = status
            
        # Filter by Planned Date (using planned_start_date if available, or just filtering logic)
        # Note: We assume planned_start_date exists in production_order_operations table.
        if start_date:
            query += " AND (poo.planned_start_time >= :start_date OR po.start_date >= :start_date)"
            params["start_date"] = start_date
            
        if end_date:
            query += " AND (poo.planned_end_time <= :end_date OR po.due_date <= :end_date)"
            params["end_date"] = end_date

        query += " ORDER BY poo.planned_start_time ASC, po.id ASC"
        
        ops = conn.execute(text(query), params).fetchall()
        return [dict(op._mapping) for op in ops]
    finally:
        conn.close()

@router.post("/orders", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_production_order(order: ProductionOrderCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Production Order."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        _validate_order_warehouse_access(conn, current_user, order.warehouse_id, order.destination_warehouse_id)
        # Generate Order Number if not provided
        if not order.order_number:
            order.order_number = f"MFG-{datetime.now().strftime('%y%m%d%H%M%S')}"

        # Auto-detect default routing if route_id not provided
        route_id = order.route_id
        if not route_id and order.product_id:
            default_route = conn.execute(text("""
                SELECT id FROM manufacturing_routes
                WHERE product_id = :pid AND is_active = true AND is_deleted = false
                ORDER BY is_default DESC, id ASC
                LIMIT 1
            """), {"pid": order.product_id}).fetchone()
            if default_route:
                route_id = default_route.id

        # 1. Create Order Header
        new_order = conn.execute(text("""
            INSERT INTO production_orders (order_number, product_id, bom_id, route_id, quantity, 
                                         status, start_date, due_date, warehouse_id, destination_warehouse_id, notes, created_by)
            VALUES (:num, :pid, :bid, :rid, :qty, :status, :start, :due, :whid, :dwhid, :notes, :uid)
            RETURNING *
        """), {
            "num": order.order_number, "pid": order.product_id, "bid": order.bom_id,
            "rid": route_id, "qty": order.quantity, "status": order.status or 'draft',
            "start": order.start_date, "due": order.due_date, 
            "whid": order.warehouse_id, "dwhid": order.destination_warehouse_id,
            "notes": order.notes, "uid": current_user.id
        }).fetchone()
        new_order_id = new_order.id

        # 2. Create Order Operations (Copy from Route) & calculate labor cost
        total_labor_cost = Decimal("0")
        if route_id:
            route_ops = conn.execute(text("""
                SELECT * FROM manufacturing_operations WHERE route_id = :rid AND is_deleted = false ORDER BY sequence
            """), {"rid": route_id}).fetchall()

            for op in route_ops:
                conn.execute(text("""
                    INSERT INTO production_order_operations (production_order_id, operation_id, work_center_id, status, sequence)
                    VALUES (:poid, :opid, :wcid, 'pending', :seq)
                """), {
                    "poid": new_order_id, "opid": op.id, "wcid": op.work_center_id, "seq": op.sequence
                })
                # Calculate labor cost: (setup_time + cycle_time * qty) / 60 * labor_rate
                setup = Decimal(str(op.setup_time or 0))
                run = Decimal(str(op.cycle_time or 0)) * Decimal(str(order.quantity))
                rate = Decimal(str(getattr(op, 'labor_rate_per_hour', 0) or 0))
                total_labor_cost += ((setup + run) / Decimal("60")) * rate

            # Update standard labor cost on the order
            if total_labor_cost > 0:
                conn.execute(text("""
                    UPDATE production_orders
                    SET actual_labor_cost = :lc
                    WHERE id = :oid
                """), {"lc": round(total_labor_cost, 4), "oid": new_order_id})

        trans.commit()
        
        # Re-fetch for response
        # Using the same logic as list_production_orders but for single ID
        # ... or just calling list structure. 
        # For simplicity, returning the created object with empty operations if correct, 
        # but better to re-query to match response model fields like product_name which are joins.
        
        # Re-query
        o = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :oid
        """), {"oid": new_order_id}).fetchone()
        
        order_dict = dict(o._mapping)
        
        ops = conn.execute(text("""
            SELECT poo.*, mo.description as operation_description
            FROM production_order_operations poo
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            WHERE poo.production_order_id = :poid
            ORDER BY mo.sequence
        """), {"poid": new_order_id}).fetchall()
        order_dict['operations'] = [dict(op._mapping) for op in ops]
        
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_production_order", resource_type="production_orders",
                     resource_id=str(new_order_id),
                     details={"order_number": order.order_number, "product_id": order.product_id, "quantity": float(order.quantity)},
                     request=request)
        return order_dict

    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error creating production order: {e}")
        raise HTTPException(**http_error(400, "production_create_failed", request))
    finally:
        conn.close()

@router.post("/orders/{order_id}/start", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def start_production_order(order_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Start Production Order."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # Check current status \u2014 T10.2 #199: lock the row to prevent
        # two concurrent ``/start`` calls from both passing the status
        # check and double-consuming inventory.
        order = conn.execute(text("""
            SELECT po.*, p.cost_price as product_cost 
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            WHERE po.id=:id
            FOR UPDATE OF po
        """), {"id": order_id}).fetchone()
        
        if not order:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        
        if order.status not in ['draft', 'confirmed']:
            logger.warning(f"Cannot start order {order_id} with status {order.status}")
            raise HTTPException(**http_error(400, "cannot_start_order_state", request))

        # Check inventory sufficiency before starting
        if order.bom_id:
            is_sufficient, shortages = check_inventory_sufficiency(
                conn, order.bom_id, order.quantity, order.warehouse_id, lock_rows=True
            )
            if not is_sufficient:
                shortage_details = "; ".join(
                    f"{s['product_name']}: need {s['required']}, have {s['available']} (short {s['shortage']})"
                    for s in shortages
                )
                logger.warning(f"Insufficient raw materials for order {order_id}: {shortage_details}")
                raise HTTPException(**http_error(400, "insufficient_raw_materials_start", request))

        # Update status to in_progress
        updated = conn.execute(text("""
            UPDATE production_orders 
            SET status='in_progress', start_date=CURRENT_DATE
            WHERE id=:id
            RETURNING *
        """), {"id": order_id}).fetchone()
        
        # 1. Consume Raw Materials
        # Get BOM components
        # T10.2 #206 — initialise outside the ``if order.bom_id`` block
        # so the audit log on line ~487 doesn't raise NameError when the
        # production order has no BOM attached.
        total_material_cost = Decimal("0")
        if order.bom_id:
            from services.costing_service import CostingService

            components = conn.execute(text("""
                SELECT bc.*, p.cost_price, p.product_name, p.id as product_id
                FROM bom_components bc
                JOIN products p ON bc.component_product_id = p.id
                WHERE bc.bom_id = :bid AND bc.is_deleted = false
            """), {"bid": order.bom_id}).fetchall()
            
            total_material_cost = Decimal("0")
            
            for comp in components:
                waste_factor = 1 + Decimal(str(comp.waste_percentage or 0)) / Decimal("100")
                # Variable BOM: quantity is % of order quantity
                if comp.is_percentage:
                    required_qty = (Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order.quantity))) * waste_factor
                else:
                    required_qty = Decimal(str(comp.quantity)) * Decimal(str(order.quantity)) * waste_factor

                # T058: Use actual costing for material cost
                actual_unit_cost = Decimal("0")
                if order.warehouse_id:
                    # T058: Use CostingService.consume_layers for FIFO/LIFO products.
                    # Do not fall back to product master cost on layer shortage.
                    method = CostingService._get_product_costing_method(conn, comp.product_id, order.warehouse_id)
                    if method in ("fifo", "lifo"):
                        try:
                            cogs = CostingService.consume_layers(
                                conn,
                                product_id=comp.product_id,
                                warehouse_id=order.warehouse_id,
                                quantity=float(required_qty),
                                sale_document_type="production_out",
                                sale_document_id=order_id,
                                costing_method=method,
                            )
                        except ValueError as exc:
                            raise HTTPException(status_code=400, detail=str(exc))
                        actual_unit_cost = (cogs / required_qty).quantize(Decimal("0.0001")) if required_qty > 0 else Decimal("0")
                    else:
                        # WAC: lock inventory and use average_cost as the actual issue cost.
                        inv_row = conn.execute(text("""
                            SELECT quantity, reserved_quantity, average_cost
                            FROM inventory
                            WHERE product_id = :pid AND warehouse_id = :wh
                            FOR UPDATE
                        """), {"pid": comp.product_id, "wh": order.warehouse_id}).fetchone()
                        available = (
                            Decimal(str(inv_row.quantity or 0)) - Decimal(str(inv_row.reserved_quantity or 0))
                        ) if inv_row else Decimal("0")
                        if available < required_qty:
                            raise HTTPException(
                                status_code=400,
                                detail=f"المخزون غير كافٍ للمادة {comp.product_name}. المتوفر: {available}, المطلوب: {required_qty}"
                            )
                        actual_unit_cost = Decimal(str(inv_row.average_cost or comp.cost_price or 0)) if inv_row else Decimal(str(comp.cost_price or 0))

                    # T058: Deduct from inventory
                    deducted = conn.execute(text("""
                        UPDATE inventory SET quantity = quantity - :qty, updated_at = NOW()
                        WHERE product_id = :pid AND warehouse_id = :wh
                          AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                        RETURNING id
                    """), {"wh": order.warehouse_id, "pid": comp.product_id, "qty": float(required_qty)}).fetchone()
                    if not deducted:
                        raise HTTPException(
                            status_code=400,
                            detail=f"تعذر سحب المادة {comp.product_name}: الكمية المتاحة غير كافية"
                        )

                else:
                    actual_unit_cost = Decimal(str(comp.cost_price or 0))

                cost = required_qty * actual_unit_cost
                total_material_cost += cost
                
                # T059: Create Transaction with actual cost
                if order.warehouse_id:
                    conn.execute(text("""
                        INSERT INTO inventory_transactions 
                        (product_id, warehouse_id, transaction_type, quantity, reference_id, reference_type, notes, created_by, unit_cost, total_cost)
                        VALUES (:pid, :whid, 'production_out', :qty, :ref, 'production_order', :notes, :uid, :uc, :tc)
                    """), {
                        "pid": comp.product_id, "whid": order.warehouse_id, "qty": -float(required_qty),
                        "ref": order_id, "notes": f"Consumed for Order {order.order_number}", "uid": current_user.id,
                        "uc": str(actual_unit_cost.quantize(Decimal("0.0001"))),
                        "tc": str(cost.quantize(Decimal("0.01"))),
                    })

            # 2. Journal Entry (WIP)
            # Find accounts from mappings
            settings_res = conn.execute(text("SELECT setting_key, setting_value FROM company_settings WHERE setting_key IN ('acc_map_wip', 'acc_map_raw_materials', 'acc_map_inventory')")).fetchall()
            settings = {s.setting_key: s.setting_value for s in settings_res}
            
            wip_acc_id = settings.get('acc_map_wip')
            rm_acc_id = settings.get('acc_map_raw_materials') or settings.get('acc_map_inventory')
            
            if wip_acc_id and rm_acc_id and total_material_cost > 0:
                # Validate fiscal period is open before creating GL entry
                check_fiscal_period_open(conn, date.today())

                # TASK-015: route through centralized GL service
                create_journal_entry(
                    db=conn,
                    company_id=current_user.company_id,
                    date=date.today().isoformat(),
                    description=f"Material Consumption for Production Order {order.order_number}",
                    lines=[
                        {"account_id": int(wip_acc_id), "debit": total_material_cost, "credit": 0,
                         "description": "WIP - Material Consumption"},
                        {"account_id": int(rm_acc_id), "debit": 0, "credit": total_material_cost,
                         "description": "Raw Material Inventory"},
                    ],
                    user_id=current_user.id,
                    reference=order.order_number,
                    status="posted",
                    currency=get_base_currency(conn),
                    source="ProductionStart",
                    source_id=order_id,
                    username=getattr(current_user, "username", None),
                    idempotency_key=f"mfg-start-{order_id}",
                )

        trans.commit()

        # Audit log
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="start_production", resource_type="production_orders",
                     resource_id=str(order_id),
                     details={"material_cost": total_material_cost},
                     request=request)

        # Re-fetch full object
        o = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :oid
        """), {"oid": order_id}).fetchone()
        
        order_dict = dict(o._mapping)
        order_dict['operations'] = [] 
        return order_dict
        
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(400, "invalid_data"))
    finally:
        conn.close()

@router.post("/orders/{order_id}/complete", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def complete_production_order(order_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Complete Production Order."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # T060: Lock production order with SELECT ... FOR UPDATE
        order = conn.execute(text("""
            SELECT po.*, p.cost_price as product_cost, b.yield_quantity,
                   wc.cost_per_hour, wc.default_expense_account_id as overhead_account_id
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            LEFT JOIN manufacturing_routes mr ON po.route_id = mr.id 
            LEFT JOIN manufacturing_operations mo ON mr.id = mo.route_id AND mo.sequence = 1
            LEFT JOIN work_centers wc ON mo.work_center_id = wc.id
            WHERE po.id=:id
            FOR UPDATE OF po
        """), {"id": order_id}).fetchone()
        
        if not order:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        
        if order.status != 'in_progress':
            logger.warning(f"Cannot complete order {order_id} with status {order.status}")
            raise HTTPException(**http_error(400, "cannot_complete_order_state", request))

        # Update status to completed
        updated = conn.execute(text("""
            UPDATE production_orders 
            SET status='completed', produced_quantity=quantity, updated_at=NOW()
            WHERE id=:id
            RETURNING *
        """), {"id": order_id}).fetchone()
        
        # 2. Journal Entry (FG Capitalization)
        # Calculate Costs
        
        # A. Material Cost: use the actual production_out inventory transactions
        # created when the order started, not current product master costs.
        material_cost_row = conn.execute(text("""
            SELECT COALESCE(
                       SUM(ABS(total_cost)),
                       SUM(ABS(quantity) * unit_cost),
                       0
                   ) AS total_material_cost
            FROM inventory_transactions
            WHERE reference_type = 'production_order'
              AND reference_id = :oid
              AND transaction_type = 'production_out'
        """), {"oid": order_id}).fetchone()
        total_material_cost = Decimal(str(material_cost_row.total_material_cost or 0))

        # B. Labor & Overhead Cost
        # Calculate actual run time from operations
        # Calculate actual run time from operations joined with work centers for cost
        ops_costs = conn.execute(text("""
            SELECT SUM((poo.actual_run_time / 60.0) * COALESCE(wc.cost_per_hour, 0)) as total_cost
            FROM production_order_operations poo
            LEFT JOIN work_centers wc ON poo.work_center_id = wc.id
            WHERE poo.production_order_id = :oid
        """), {"oid": order_id}).fetchone()
        
        total_labor_overhead_cost = Decimal(str(ops_costs.total_cost or 0))
        
        total_production_cost = total_material_cost + total_labor_overhead_cost
        
        # Debit: Inventory (FG)
        # Credit: WIP
        settings_res = conn.execute(text("SELECT setting_key, setting_value FROM company_settings WHERE setting_key IN ('acc_map_wip', 'acc_map_finished_goods', 'acc_map_inventory', 'acc_map_labor_cost', 'acc_map_mfg_overhead')")).fetchall()
        settings = {s.setting_key: s.setting_value for s in settings_res}
        
        wip_acc_id = settings.get('acc_map_wip')
        fg_acc_id = settings.get('acc_map_finished_goods') or settings.get('acc_map_inventory')
        
        # Credit Accounts for Labor/Overhead absorption (Contra-expense or Liability)
        # Using a simplistic approach: Credit a "Manufacturing Absorbed Costs" account or Payroll
        # For this phase, we credit WIP for the total transfer to FG, 
        # BUT we also need to Debit WIP and Credit Labor/Overhead for the added value FIRST.
        
        labor_absorption_acc_id = settings.get('acc_map_labor_cost') # e.g., Payroll Payable or Absorbed Labor
        overhead_absorption_acc_id = settings.get('acc_map_mfg_overhead') # e.g., Factory Overhead Absorption

        if wip_acc_id and fg_acc_id and total_production_cost > 0:
            # Validate fiscal period is open before creating GL entry
            check_fiscal_period_open(conn, date.today())

            # TASK-015: centralized GL posting — build single balanced JE
            je_lines = []
            absorb_acc = None
            if total_labor_overhead_cost > 0 and (labor_absorption_acc_id or overhead_absorption_acc_id):
                absorb_acc = labor_absorption_acc_id or overhead_absorption_acc_id
                if absorb_acc:
                    je_lines.append({"account_id": int(wip_acc_id),
                                     "debit": total_labor_overhead_cost, "credit": 0,
                                     "description": "WIP - Labor & Overhead Absorption"})
                    je_lines.append({"account_id": int(absorb_acc),
                                     "debit": 0, "credit": total_labor_overhead_cost,
                                     "description": "Absorbed Manufacturing Costs"})

            je_lines.append({"account_id": int(fg_acc_id),
                             "debit": total_production_cost, "credit": 0,
                             "description": "Finished Goods Inventory"})
            je_lines.append({"account_id": int(wip_acc_id),
                             "debit": 0, "credit": total_production_cost,
                             "description": "WIP - FG Transfer"})

            create_journal_entry(
                db=conn,
                company_id=current_user.company_id,
                date=date.today().isoformat(),
                description=(
                    f"Production Completion (Mat: {total_material_cost}, "
                    f"Lab/OH: {total_labor_overhead_cost})"
                ),
                lines=je_lines,
                user_id=current_user.id,
                reference=order.order_number,
                status="posted",
                currency=get_base_currency(conn),
                source="ProductionComplete",
                source_id=order_id,
                username=getattr(current_user, "username", None),
                idempotency_key=f"mfg-complete-{order_id}",
            )

        # T061-T062: Compute finished-good unit cost and update inventory only
        # after costing succeeds.
        from services.costing_service import CostingService

        produced_qty = Decimal(str(order.quantity or 0))
        by_products = []
        if order.bom_id:
            by_products = conn.execute(text("""
                SELECT *
                FROM bom_outputs
                WHERE bom_id = :bid AND is_deleted = false
            """), {"bid": order.bom_id}).fetchall()

        allocation_pcts = [
            max(Decimal("0"), Decimal(str(bp.cost_allocation_percentage or 0)))
            for bp in by_products
        ]
        total_alloc_pct = sum(allocation_pcts, Decimal("0"))
        alloc_scale = (Decimal("100") / total_alloc_pct) if total_alloc_pct > Decimal("100") else Decimal("1")
        by_product_total_cost = sum(
            (total_production_cost * pct * alloc_scale / Decimal("100"))
            for pct in allocation_pcts
        )
        main_total_cost = total_production_cost - by_product_total_cost
        main_unit_cost = (main_total_cost / produced_qty).quantize(Decimal("0.0001")) if produced_qty > 0 else Decimal("0")

        if order.destination_warehouse_id and produced_qty > 0:
            CostingService.update_cost(
                conn,
                product_id=order.product_id,
                warehouse_id=order.destination_warehouse_id,
                new_qty=float(produced_qty),
                new_price=float(main_unit_cost),
            )

            main_method = CostingService._get_product_costing_method(conn, order.product_id, order.destination_warehouse_id)
            if main_method in ("fifo", "lifo"):
                CostingService.create_cost_layer(
                    conn,
                    product_id=order.product_id,
                    warehouse_id=order.destination_warehouse_id,
                    quantity=float(produced_qty),
                    unit_cost=float(main_unit_cost),
                    source_document_type="production_order",
                    source_document_id=order_id,
                    costing_method=main_method,
                )

            conn.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:pid, :whid, :qty, :cost, NOW())
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                              updated_at = NOW()
            """), {
                "whid": order.destination_warehouse_id,
                "pid": order.product_id,
                "qty": float(produced_qty),
                "cost": float(main_unit_cost),
            })

            conn.execute(text("""
                INSERT INTO inventory_transactions
                (product_id, warehouse_id, transaction_type, quantity, reference_id, reference_type,
                 notes, created_by, unit_cost, total_cost)
                VALUES (:pid, :whid, 'production_in', :qty, :ref, 'production_order',
                        :notes, :uid, :uc, :tc)
            """), {
                "pid": order.product_id,
                "whid": order.destination_warehouse_id,
                "qty": float(produced_qty),
                "ref": order_id,
                "notes": f"Production Receipt for Order {order.order_number}",
                "uid": current_user.id,
                "uc": str(main_unit_cost),
                "tc": str(main_total_cost.quantize(Decimal("0.01"))),
            })

            for idx, bp in enumerate(by_products):
                bp_qty = Decimal(str(bp.quantity or 0)) * produced_qty
                if bp_qty <= 0:
                    continue
                bp_total_cost = (total_production_cost * allocation_pcts[idx] * alloc_scale / Decimal("100"))
                bp_unit_cost = (bp_total_cost / bp_qty).quantize(Decimal("0.0001")) if bp_qty > 0 else Decimal("0")

                CostingService.update_cost(
                    conn,
                    product_id=bp.product_id,
                    warehouse_id=order.destination_warehouse_id,
                    new_qty=float(bp_qty),
                    new_price=float(bp_unit_cost),
                )

                bp_method = CostingService._get_product_costing_method(conn, bp.product_id, order.destination_warehouse_id)
                if bp_method in ("fifo", "lifo"):
                    CostingService.create_cost_layer(
                        conn,
                        product_id=bp.product_id,
                        warehouse_id=order.destination_warehouse_id,
                        quantity=float(bp_qty),
                        unit_cost=float(bp_unit_cost),
                        source_document_type="production_order",
                        source_document_id=order_id,
                        costing_method=bp_method,
                    )

                conn.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                    VALUES (:pid, :whid, :qty, :cost, NOW())
                    ON CONFLICT (product_id, warehouse_id)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                  updated_at = NOW()
                """), {
                    "whid": order.destination_warehouse_id,
                    "pid": bp.product_id,
                    "qty": float(bp_qty),
                    "cost": float(bp_unit_cost),
                })

                conn.execute(text("""
                    INSERT INTO inventory_transactions
                    (product_id, warehouse_id, transaction_type, quantity, reference_id, reference_type,
                     notes, created_by, unit_cost, total_cost)
                    VALUES (:pid, :whid, 'production_in', :qty, :ref, 'production_order',
                            :notes, :uid, :uc, :tc)
                """), {
                    "pid": bp.product_id,
                    "whid": order.destination_warehouse_id,
                    "qty": float(bp_qty),
                    "ref": order_id,
                    "notes": f"By-product Receipt for Order {order.order_number}",
                    "uid": current_user.id,
                    "uc": str(bp_unit_cost),
                    "tc": str(bp_total_cost.quantize(Decimal("0.01"))),
                })

        trans.commit()

        # Audit log
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="complete_production", resource_type="production_orders",
                     resource_id=str(order_id),
                     details={"quantity": float(order.quantity), "total_cost": total_production_cost},
                     request=request)

        # Re-fetch full object
        o = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :oid
        """), {"oid": order_id}).fetchone()
        
        order_dict = dict(o._mapping)
        order_dict['operations'] = [] 
        return order_dict
        
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(400, "invalid_data"))
    finally:
        conn.close()


# ---- Cancel / Delete / Update Production Orders ----

@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def cancel_production_order(order_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Cancel a production order. Only draft/confirmed orders can be cancelled."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        order = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :id
        """), {"id": order_id}).fetchone()
        
        if not order:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        
        if order.status not in ['draft', 'confirmed']:
            logger.warning(f"Cannot cancel order {order_id} with status {order.status}")
            raise HTTPException(**http_error(400, "cannot_cancel_order_state", request))
        
        conn.execute(text("""
            UPDATE production_orders SET status = 'cancelled', updated_at = NOW() WHERE id = :id
        """), {"id": order_id})
        
        trans.commit()
        
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="cancel_production_order", resource_type="production_orders",
                     resource_id=str(order_id), details={"order_number": order.order_number},
                     request=request)
        updated = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :id
        """), {"id": order_id}).fetchone()
        order_dict = dict(updated._mapping)
        order_dict['operations'] = []
        return order_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error cancelling production order {order_id}: {e}")
        raise HTTPException(**http_error(400, "production_cancel_failed", request))
    finally:
        conn.close()


@router.delete("/orders/{order_id}", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.delete"]))], response_model=Dict[str, Any])
def delete_production_order(order_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete a production order. Only draft orders can be deleted."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        order = conn.execute(text("SELECT * FROM production_orders WHERE id = :id"), {"id": order_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        if order.status != 'draft':
            raise HTTPException(**http_error(400, "only_draft_orders_deletable", request))
        
        # Delete operations first (cascade should handle, but be explicit)
        conn.execute(text("DELETE FROM production_order_operations WHERE production_order_id = :id"), {"id": order_id})
        conn.execute(text("DELETE FROM production_orders WHERE id = :id"), {"id": order_id})
        
        trans.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_production_order", resource_type="production_orders",
                     resource_id=str(order_id), request=request)
        return {"message": i18n_message("production_order_deleted_success", request)}
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error deleting production order {order_id}: {e}")
        raise HTTPException(**http_error(400, "production_delete_failed", request))
    finally:
        conn.close()


@router.put("/orders/{order_id}", response_model=ProductionOrderResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def update_production_order(order_id: int, order: ProductionOrderCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update a production order. Only draft orders can be updated."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        existing = conn.execute(text("SELECT * FROM production_orders WHERE id = :id"), {"id": order_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "order_not_found", request))
        from utils.permissions import validate_branch_access
        if existing.branch_id:
            validate_branch_access(current_user, existing.branch_id)
        if existing.status != 'draft':
            raise HTTPException(**http_error(400, "only_draft_orders_updatable", request))

        _validate_order_warehouse_access(conn, current_user, order.warehouse_id, order.destination_warehouse_id)
        
        updated = conn.execute(text("""
            UPDATE production_orders 
            SET product_id = :pid, bom_id = :bid, route_id = :rid, quantity = :qty,
                start_date = :start, due_date = :due, warehouse_id = :whid, 
                destination_warehouse_id = :dwhid, notes = :notes, updated_at = NOW()
            WHERE id = :id
            RETURNING *
        """), {
            "pid": order.product_id, "bid": order.bom_id, "rid": order.route_id,
            "qty": order.quantity, "start": order.start_date, "due": order.due_date,
            "whid": order.warehouse_id, "dwhid": order.destination_warehouse_id,
            "notes": order.notes, "id": order_id
        }).fetchone()
        
        if not updated:
            raise HTTPException(**http_error(500, "update_failed", request))
        
        # Re-create operations from new route if route changed
        if order.route_id and order.route_id != existing.route_id:
            conn.execute(text("DELETE FROM production_order_operations WHERE production_order_id = :id"), {"id": order_id})
            route_ops = conn.execute(text("""
                SELECT * FROM manufacturing_operations WHERE route_id = :rid AND is_deleted = false ORDER BY sequence
            """), {"rid": order.route_id}).fetchall()
            for op in route_ops:
                conn.execute(text("""
                    INSERT INTO production_order_operations (production_order_id, operation_id, work_center_id, status)
                    VALUES (:poid, :opid, :wcid, 'pending')
                """), {"poid": order_id, "opid": op.id, "wcid": op.work_center_id})
        
        trans.commit()
        
        # Re-fetch with joins
        o = conn.execute(text("""
            SELECT po.*, p.product_name as product_name, b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.id = :oid
        """), {"oid": order_id}).fetchone()
        order_dict = dict(o._mapping)
        
        ops = conn.execute(text("""
            SELECT poo.*, mo.description as operation_description
            FROM production_order_operations poo
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            WHERE poo.production_order_id = :poid
            ORDER BY mo.sequence
        """), {"poid": order_id}).fetchall()
        order_dict['operations'] = [dict(op._mapping) for op in ops]
        
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_production_order", resource_type="production_orders",
                     resource_id=str(order_id), details={"quantity": float(order.quantity)},
                     request=request)
        return order_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error updating production order {order_id}: {e}")
        raise HTTPException(**http_error(400, "production_update_failed", request))
    finally:
        conn.close()


# ---- Delete Work Center / Route / BOM ----

@router.post("/operations/{op_id}/start", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def start_operation(op_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Start Operation."""
    conn = get_db_connection(current_user.company_id)
    try:
        op = conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
        if not op:
            raise HTTPException(**http_error(404, "operation_not_found", request))
        
        # Branch validation via production order
        from utils.permissions import validate_branch_access
        po = conn.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": op.production_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)
        
        if op.status == 'in_progress':
            raise HTTPException(**http_error(400, "operation_already_in_progress", request))

        # Update status to in_progress
        conn.execute(text("""
            UPDATE production_order_operations 
            SET status = 'in_progress', 
                start_time = COALESCE(start_time, NOW()), 
                worker_id = :uid,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": op_id, "uid": current_user.id})
        
        conn.commit()
        
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="start_operation", resource_type="production_order_operations",
                     resource_id=str(op_id), request=request)
        # Re-fetch
        updated = conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
        return updated
    finally:
        conn.close()

@router.post("/operations/{op_id}/pause", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def pause_operation(op_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Pause Operation."""
    conn = get_db_connection(current_user.company_id)
    try:
        op = conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
        if not op or op.status != 'in_progress':
            raise HTTPException(**http_error(400, "only_in_progress_pausable", request))

        # Branch validation via production order
        from utils.permissions import validate_branch_access
        po = conn.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": op.production_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        # Update status
        conn.execute(text("""
            UPDATE production_order_operations 
            SET status = 'paused', updated_at = NOW()
            WHERE id = :id
        """), {"id": op_id})
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="pause_operation", resource_type="production_order_operations",
                     resource_id=str(op_id), request=request)
        return conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
    finally:
        conn.close()

@router.post("/operations/{op_id}/complete", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def complete_operation(op_id: int, completed_qty: float, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Complete Operation."""
    conn = get_db_connection(current_user.company_id)
    try:
        op = conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
        if not op:
            raise HTTPException(**http_error(404, "operation_not_found", request))

        # Branch validation via production order
        from utils.permissions import validate_branch_access
        po = conn.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": op.production_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        # Calculate duration if we have start_time
        duration = 0
        if op.start_time:
            # Simple duration calculation (minutes)
            res = conn.execute(text("SELECT EXTRACT(EPOCH FROM (NOW() - :start))/60"), {"start": op.start_time}).fetchone()
            duration = res[0] if res else 0

        conn.execute(text("""
            UPDATE production_order_operations 
            SET status = 'completed', 
                end_time = NOW(), 
                completed_quantity = :qty,
                actual_run_time = :duration,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": op_id, "qty": completed_qty, "duration": duration})
        
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="complete_operation", resource_type="production_order_operations",
                     resource_id=str(op_id), details={"completed_qty": completed_qty},
                     request=request)
        return conn.execute(text("SELECT * FROM production_order_operations WHERE id = :id"), {"id": op_id}).fetchone()
    finally:
        conn.close()

@router.get("/orders/operations/active", response_model=List[ProductionOrderOperationResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def get_active_operations(current_user: UserResponse = Depends(get_current_user)):
    """Get Active Operations."""
    conn = get_db_connection(current_user.company_id)
    try:
        # Fetch active or pending operations with order details
        res = conn.execute(text("""
            SELECT poo.*, po.order_number, wc.name as work_center_name, 
                   mo.description as operation_description, po.quantity as planned_quantity,
                   mo.cycle_time, mo.setup_time, p.product_name
            FROM production_order_operations poo
            JOIN production_orders po ON poo.production_order_id = po.id
            JOIN products p ON po.product_id = p.id
            JOIN work_centers wc ON poo.work_center_id = wc.id
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            WHERE poo.status IN ('pending', 'in_progress', 'paused')
            ORDER BY poo.start_time ASC NULLS LAST, poo.created_at ASC
        """)).fetchall()
        return res
    finally:
        conn.close()

# --- MRP (MFG-005) ---

@router.get("/orders/{order_id}/qc-checks", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=List[Dict[str, Any]])
def get_qc_checks(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """جلب فحوصات الجودة لأمر الإنتاج"""
    conn = get_db_connection(current_user.company_id)
    try:
        # Branch validation
        from utils.permissions import validate_branch_access
        po = conn.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        rows = conn.execute(text("""
            SELECT q.*, u.full_name as checked_by_name,
                   op.name as operation_name
            FROM mfg_qc_checks q
            LEFT JOIN company_users u ON q.checked_by = u.id
            LEFT JOIN manufacturing_operations op ON q.operation_id = op.id
            WHERE q.production_order_id = :oid AND q.is_deleted = false
            ORDER BY q.created_at
        """), {"oid": order_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post("/orders/{order_id}/qc-checks", status_code=201, dependencies=[Depends(require_permission("manufacturing.manage"))], response_model=Dict[str, Any])
def create_qc_check(
    order_id: int,
    qc: QCCheckCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """إضافة فحص جودة لأمر إنتاج"""
    conn = get_db_connection(current_user.company_id)
    try:
        order = conn.execute(text("SELECT id, status, branch_id FROM production_orders WHERE id=:id"), {"id": order_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "production_order_not_found"))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        if order.status not in ("in_progress", "confirmed"):
            raise HTTPException(**http_error(400, "quality_check_only_active_orders", request))

        qc_id = conn.execute(text("""
            INSERT INTO mfg_qc_checks (
                production_order_id, operation_id, check_name,
                check_type, specification, failure_action, notes,
                result, checked_by
            ) VALUES (:oid, :op, :name, :type, :spec, :action, :notes, 'pending', :uid)
            RETURNING id
        """), {
            "oid": order_id, "op": qc.operation_id, "name": qc.check_name,
            "type": qc.check_type, "spec": qc.specification,
            "action": qc.failure_action, "notes": qc.notes,
            "uid": current_user.id
        }).scalar()
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_qc_check", resource_type="mfg_qc_checks",
                     resource_id=str(qc_id), details={"order_id": order_id, "check_name": qc.check_name},
                     request=request)
        return {"success": True, "id": qc_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating QC check: {e}")
        raise HTTPException(**http_error(500, "quality_inspection_create_failed", request))
    finally:
        conn.close()


@router.post("/orders/{order_id}/calculate-cost", dependencies=[Depends(require_permission("manufacturing.manage"))], response_model=Dict[str, Any])
def calculate_actual_cost(order_id: int, request: Request, body: Optional[ActualCostUpdate] = None,
                          current_user: UserResponse = Depends(get_current_user)):
    """
    حساب التكلفة الفعلية لأمر الإنتاج — المواد + العمالة + الأعباء
    ومقارنتها بالتكلفة المعيارية (من BOM) لإنتاج تقرير الانحرافات
    """
    conn = get_db_connection(current_user.company_id)
    try:
        order = conn.execute(text("""
            SELECT po.*, p.product_name, p.cost_price as standard_unit_cost
            FROM production_orders po
            JOIN products p ON po.product_id = p.id
            WHERE po.id = :id
        """), {"id": order_id}).fetchone()

        if not order:
            raise HTTPException(**http_error(404, "production_order_not_found"))
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)

        qty = Decimal(str(order.quantity or 1))

        # ── 1. Actual Material Cost ──
        material_consumed = conn.execute(text("""
            SELECT COALESCE(SUM(ABS(it.quantity) * COALESCE(p.cost_price, 0)), 0)
            FROM inventory_transactions it
            JOIN products p ON p.id = it.product_id
            WHERE it.reference_type = 'production_order'
              AND it.reference_id = :oid
              AND it.quantity < 0
        """), {"oid": order_id}).scalar() or 0

        actual_material = Decimal(str(body.actual_material_cost)) if body and body.actual_material_cost is not None else Decimal(str(material_consumed))

        # ── 2. Actual Labor Cost ──
        labor_cost = conn.execute(text("""
            SELECT COALESCE(SUM(
                COALESCE(poo.actual_run_time, 0) / 60.0 * COALESCE(wc.cost_per_hour, 0)
            ), 0)
            FROM production_order_operations poo
            LEFT JOIN work_centers wc ON wc.id = poo.work_center_id
            WHERE poo.production_order_id = :oid
        """), {"oid": order_id}).scalar() or 0

        actual_labor = Decimal(str(body.actual_labor_cost)) if body and body.actual_labor_cost is not None else Decimal(str(labor_cost))

        # ── 3. Overhead ──
        settings = conn.execute(text("SELECT * FROM company_settings LIMIT 1")).fetchone()
        overhead_rate = Decimal(str(getattr(settings, 'mfg_overhead_rate', 0) or 0)) / Decimal("100")
        default_overhead = round(actual_labor * overhead_rate, 2) if overhead_rate > 0 else Decimal("0")
        actual_overhead = Decimal(str(body.actual_overhead_cost)) if body and body.actual_overhead_cost is not None else default_overhead

        actual_total = round(actual_material + actual_labor + actual_overhead, 2)

        # ── 4. Standard Cost (from BOM) ──
        standard_cost = Decimal("0")
        if order.bom_id:
            # BOM material cost from bom_components
            bom_material = conn.execute(text("""
                SELECT COALESCE(SUM(bc.quantity * COALESCE(p.cost_price, 0)), 0)
                FROM bom_components bc
                JOIN products p ON p.id = bc.component_product_id
                WHERE bc.bom_id = :boid AND bc.is_deleted = false
            """), {"boid": order.bom_id}).scalar() or 0

            # BOM operation cost from manufacturing_operations via route
            bom_ops = conn.execute(text("""
                SELECT COALESCE(SUM(
                    COALESCE(mo.cycle_time, 0) / 60.0 * COALESCE(wc.cost_per_hour, 0)
                ), 0)
                FROM manufacturing_operations mo
                LEFT JOIN work_centers wc ON wc.id = mo.work_center_id
                WHERE mo.route_id = (SELECT route_id FROM bill_of_materials WHERE id = :boid) AND mo.is_deleted = false
            """), {"boid": order.bom_id}).scalar() or 0

            standard_cost = (Decimal(str(bom_material)) + Decimal(str(bom_ops))) * qty
        else:
            standard_cost = Decimal(str(order.standard_unit_cost or 0)) * qty

        standard_cost = round(standard_cost, 2)

        # ── 5. Variance ──
        variance = round(actual_total - standard_cost, 2)
        variance_pct = round((variance / standard_cost * 100), 2) if standard_cost > 0 else Decimal("0")

        if variance > 0:
            variance_type = "unfavorable"
            variance_type_ar = "غير مواتٍ (تجاوز)"
        elif variance < 0:
            variance_type = "favorable"
            variance_type_ar = "مواتٍ (وفر)"
        else:
            variance_type = "none"
            variance_type_ar = "لا انحراف"

        # ── 6. Per-unit cost ──
        actual_qty = Decimal(str(order.produced_quantity or order.quantity or 1))
        actual_unit_cost = round(actual_total / actual_qty, 4) if actual_qty > 0 else Decimal("0")

        # ── Update production order with costs ──
        conn.execute(text("""
            UPDATE production_orders SET
                actual_material_cost = :mc, actual_labor_cost = :lc,
                actual_overhead_cost = :oc, actual_total_cost = :tc,
                standard_cost = :sc, variance_amount = :va,
                variance_percentage = :vp, costing_status = 'calculated',
                updated_at = NOW()
            WHERE id = :id
        """), {
            "mc": actual_material, "lc": actual_labor, "oc": actual_overhead,
            "tc": actual_total, "sc": standard_cost, "va": variance,
            "vp": variance_pct, "id": order_id
        })

        # ── Update product cost_price with actual cost ──
        conn.execute(text("""
            UPDATE products SET cost_price = :cost, updated_at = NOW()
            WHERE id = :pid
        """), {"cost": actual_unit_cost, "pid": order.product_id})

        # ── 7. GL posting for variance (actual vs standard) ──
        # Unfavorable (variance>0): Dr Variance Expense, Cr WIP — clears residual WIP
        # Favorable (variance<0):   Dr WIP, Cr Variance Expense — reverses over-transfer
        # Idempotent: re-runs of calculate-cost return the same JE, never double-post.
        variance_je_id = None
        if variance != 0:
            settings_res = conn.execute(text(
                "SELECT setting_key, setting_value FROM company_settings "
                "WHERE setting_key IN ('acc_map_wip', 'acc_map_mfg_variance', 'acc_map_mfg_overhead', 'acc_map_cogs')"
            )).fetchall()
            s = {r.setting_key: r.setting_value for r in settings_res}
            wip_acc = s.get('acc_map_wip')
            variance_acc = (
                s.get('acc_map_mfg_variance')
                or s.get('acc_map_mfg_overhead')
                or s.get('acc_map_cogs')
            )
            if wip_acc and variance_acc:
                check_fiscal_period_open(conn, date.today())
                abs_var = abs(variance)
                if variance > 0:
                    je_lines = [
                        {"account_id": int(variance_acc), "debit": abs_var, "credit": 0,
                         "description": "Manufacturing Variance (Unfavorable)"},
                        {"account_id": int(wip_acc), "debit": 0, "credit": abs_var,
                         "description": "WIP clearing — variance"},
                    ]
                else:
                    je_lines = [
                        {"account_id": int(wip_acc), "debit": abs_var, "credit": 0,
                         "description": "WIP clearing — favorable variance"},
                        {"account_id": int(variance_acc), "debit": 0, "credit": abs_var,
                         "description": "Manufacturing Variance (Favorable)"},
                    ]
                variance_je_id, _ = create_journal_entry(
                    db=conn,
                    company_id=current_user.company_id,
                    date=date.today().isoformat(),
                    description=(
                        f"Mfg Variance for PO {order.order_number} "
                        f"(Actual {actual_total} vs Standard {standard_cost})"
                    ),
                    lines=je_lines,
                    user_id=current_user.id,
                    reference=order.order_number,
                    status="posted",
                    currency=get_base_currency(conn),
                    source="ProductionVariance",
                    source_id=order_id,
                    username=getattr(current_user, "username", None),
                    idempotency_key=f"mfg-variance-{order_id}",
                )

        conn.commit()

        return {
            "order_id": order_id,
            "product_name": order.product_name,
            "planned_quantity": qty,
            "produced_quantity": actual_qty,
            "cost_breakdown": {
                "material_cost": actual_material,
                "labor_cost": actual_labor,
                "overhead_cost": actual_overhead,
                "total_actual_cost": actual_total,
                "unit_actual_cost": actual_unit_cost
            },
            "standard_cost": standard_cost,
            "variance": {
                "amount": variance,
                "percentage": variance_pct,
                "type": variance_type,
                "type_ar": variance_type_ar,
                "journal_entry_id": variance_je_id,
            },
            "costing_status": "calculated",
            "message": i18n_message("actual_cost_calculated", request)
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error calculating actual cost for order {order_id}: {e}")
        raise HTTPException(**http_error(500, "actual_cost_calc_failed", request))
    finally:
        conn.close()
