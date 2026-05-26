"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from database import get_db_connection
from utils.audit import log_activity
from schemas import UserResponse
from schemas.manufacturing_advanced import (
    MRPPlanResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/mrp/calculate/{order_id}", response_model=MRPPlanResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def calculate_mrp_for_order(request: Request, order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Calculate MRP For Order."""
    conn = get_db_connection(current_user.company_id)
    try:
        order = conn.execute(text("SELECT * FROM production_orders WHERE id = :id"), {"id": order_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "order_not_found", request))
        
        # Branch validation
        from utils.permissions import validate_branch_access
        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)
        
        if not order.bom_id:
            raise HTTPException(**http_error(400, "order_has_no_bom", request))

        # Fetch BOM components
        components = conn.execute(text("""
            SELECT bc.*, p.product_name, p.reorder_level, p.lead_time_days,
                   COALESCE((SELECT SUM(quantity) FROM inventory WHERE product_id = p.id), 0) as on_hand
            FROM bom_components bc
            JOIN products p ON bc.component_product_id = p.id
            WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": order.bom_id}).fetchall()

        # Check pending purchase orders for on_order_quantity
        mrp_items = []
        for comp in components:
            # Handle waste percentage & variable BOM (is_percentage)
            waste_factor = 1 + Decimal(str(comp.waste_percentage or 0)) / Decimal("100")
            if comp.is_percentage:
                required = (Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order.quantity))) * waste_factor
            else:
                required = Decimal(str(comp.quantity)) * Decimal(str(order.quantity)) * waste_factor
            required = round(required, 4)

            on_hand = Decimal(str(comp.on_hand or 0))

            # T10.1 P1 #73 — read open purchase ORDERS, not invoices.
            # ``purchase_invoice_items`` represents what was already
            # received and billed; the audit complained that this is
            # double-counting. Switch to ``purchase_order_lines`` joined
            # to ``purchase_orders`` (the upstream supply commitment).
            on_order = conn.execute(text("""
                SELECT COALESCE(SUM(pol.quantity - COALESCE(pol.received_quantity, 0)), 0)
                FROM purchase_order_lines pol
                JOIN purchase_orders po ON pol.po_id = po.id
                WHERE pol.product_id = :pid
                  AND po.status IN ('draft', 'approved', 'sent', 'partially_received')
            """), {"pid": comp.component_product_id}).scalar() or 0
            on_order = Decimal(str(on_order))

            available = on_hand + on_order
            shortage = max(Decimal("0"), round(required - available, 4))

            if shortage > 0:
                action = "purchase_order"
            elif required > on_hand and on_order > 0:
                action = "wait_for_po"
            else:
                action = "none"

            mrp_items.append({
                "product_id": comp.component_product_id,
                "product_name": comp.product_name,
                "required_quantity": required,
                "available_quantity": available,
                "on_hand_quantity": on_hand,
                "on_order_quantity": on_order,
                "shortage_quantity": shortage,
                "lead_time_days": int(comp.lead_time_days or 1),
                "suggested_action": action,
                "status": "pending"
            })

        # Save MRP Plan to database
        plan_row = conn.execute(text("""
            INSERT INTO mrp_plans (plan_name, production_order_id, status, calculated_at)
            VALUES (:name, :oid, 'draft', NOW())
            RETURNING *
        """), {"name": f"MRP for {order.order_number}", "oid": order_id}).fetchone()

        for item in mrp_items:
            conn.execute(text("""
                INSERT INTO mrp_items (mrp_plan_id, product_id, required_quantity, available_quantity, shortage_quantity, suggested_action, status)
                VALUES (:pid, :prod, :req, :avail, :short, :action, :status)
            """), {
                "pid": plan_row.id, "prod": item["product_id"],
                "req": item["required_quantity"], "avail": item["available_quantity"],
                "short": item["shortage_quantity"], "action": item["suggested_action"],
                "status": item["status"]
            })

        conn.commit()

        return {
            "id": plan_row.id,
            "plan_name": plan_row.plan_name,
            "production_order_id": order_id,
            "status": "draft",
            "calculated_at": plan_row.calculated_at,
            "items": mrp_items
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error calculating MRP for order {order_id}: {e}")
        raise HTTPException(**http_error(500, "mrp_calculation_failed", request))
    finally:
        conn.close()

@router.get("/mrp/plans", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def list_mrp_plans(
    branch_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """List MRP Plans."""
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT mp.*, po.order_number 
            FROM mrp_plans mp
            LEFT JOIN production_orders po ON mp.production_order_id = po.id
            WHERE 1=1
        """
        params = {}
        query += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        query += " ORDER BY mp.calculated_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        plans = conn.execute(text(query), params).fetchall()
        result = []
        for p in plans:
            pd = dict(p._mapping)
            items = conn.execute(text("""
                SELECT mi.*, pr.product_name 
                FROM mrp_items mi
                JOIN products pr ON mi.product_id = pr.id
                WHERE mi.mrp_plan_id = :pid
            """), {"pid": p.id}).fetchall()
            pd['items'] = [dict(i._mapping) for i in items]
            result.append(pd)
        return result
    finally:
        conn.close()

# ==========================================
# 6. EQUIPMENT & MAINTENANCE
# ==========================================

@router.get("/capacity-plans", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=List[Dict[str, Any]])
def list_capacity_plans(
    request: Request,
    work_center_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """خطط الطاقة الإنتاجية"""
    conn = get_db_connection(current_user.company_id)
    try:
        q = """
            SELECT cp.*, wc.name as work_center_name
            FROM capacity_plans cp
            LEFT JOIN work_centers wc ON wc.id = cp.work_center_id
            WHERE 1=1 AND cp.is_deleted = false
        """
        params = {}
        if work_center_id:
            q += " AND cp.work_center_id = :wc"
            params["wc"] = work_center_id
        if date_from:
            q += " AND cp.plan_date >= :df"
            params["df"] = date_from
        if date_to:
            q += " AND cp.plan_date <= :dt"
            params["dt"] = date_to
        q += " ORDER BY cp.plan_date DESC"
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.error(f"Error listing capacity plans: {e}")
        raise HTTPException(**http_error(500, "capacity_plan_fetch_failed", request))
    finally:
        conn.close()


@router.post("/capacity-plans", dependencies=[Depends(require_permission("manufacturing.manage"))], response_model=Dict[str, Any])
def create_capacity_plan(plan: dict, request: Request, current_user=Depends(get_current_user)):
    """إنشاء خطة طاقة إنتاجية"""
    conn = get_db_connection(current_user.company_id)
    try:
        eff = 0
        if plan.get("available_hours") and plan.get("actual_hours"):
            eff = round(Decimal(str(plan["actual_hours"])) / Decimal(str(plan["available_hours"])) * 100, 2)
        result = conn.execute(text("""
            INSERT INTO capacity_plans (work_center_id, plan_date, available_hours,
                planned_hours, actual_hours, efficiency_pct, notes)
            VALUES (:wc, :pd, :ah, :ph, :ach, :eff, :n)
            RETURNING id
        """), {
            "wc": plan["work_center_id"], "pd": plan["plan_date"],
            "ah": plan.get("available_hours", 8), "ph": plan.get("planned_hours", 0),
            "ach": plan.get("actual_hours", 0), "eff": eff, "n": plan.get("notes")
        })
        plan_id = result.fetchone()[0]
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_capacity_plan", resource_type="capacity_plans",
                     resource_id=str(plan_id), request=request)
        return {"id": plan_id, "message": i18n_message("capacity_plan_created", request)}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating capacity plan: {e}")
        raise HTTPException(**http_error(500, "capacity_plan_create_failed", request))
    finally:
        conn.close()


@router.put("/capacity-plans/{plan_id}", dependencies=[Depends(require_permission("manufacturing.manage"))], response_model=Dict[str, Any])
def update_capacity_plan(plan_id: int, plan: dict, request: Request, current_user=Depends(get_current_user)):
    """تحديث خطة طاقة إنتاجية"""
    conn = get_db_connection(current_user.company_id)
    try:
        eff = 0
        if plan.get("available_hours") and plan.get("actual_hours"):
            eff = round(Decimal(str(plan["actual_hours"])) / Decimal(str(plan["available_hours"])) * 100, 2)
        conn.execute(text("""
            UPDATE capacity_plans SET available_hours = :ah, planned_hours = :ph,
                actual_hours = :ach, efficiency_pct = :eff, notes = :n
            WHERE id = :id
        """), {
            "ah": plan.get("available_hours"), "ph": plan.get("planned_hours"),
            "ach": plan.get("actual_hours"), "eff": eff, "n": plan.get("notes"), "id": plan_id
        })
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_capacity_plan", resource_type="capacity_plans",
                     resource_id=str(plan_id), request=request)
        return {"message": i18n_message("capacity_plan_updated", request)}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating capacity plan {plan_id}: {e}")
        raise HTTPException(**http_error(500, "capacity_plan_update_failed", request))
    finally:
        conn.close()
