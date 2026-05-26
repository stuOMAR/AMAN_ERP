"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
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
    RouteCreate, RouteResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/routes", response_model=List[RouteResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_routes(
    branch_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """List Routes."""
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT r.*, p.product_name as product_name
            FROM manufacturing_routes r
            LEFT JOIN products p ON r.product_id = p.id
            WHERE r.is_deleted = false
        """
        params = {}
        branch_condition = branch_scope_filter_from_scope(branch_scope, "w.branch_id", params).strip()
        if branch_condition:
            query += """
                AND r.product_id IN (
                    SELECT DISTINCT inv.product_id
                    FROM inventory inv
                    JOIN warehouses w ON inv.warehouse_id = w.id
                    WHERE 1=1 {branch_condition}
                )
            """.format(branch_condition=branch_condition)
        query += " ORDER BY r.name LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        routes_db = conn.execute(text(query), params).fetchall()
        
        result = []
        for r in routes_db:
            route_dict = dict(r._mapping)
            # Fetch operations
            ops = conn.execute(text("""
                SELECT mo.*, wc.name as work_center_name 
                FROM manufacturing_operations mo
                LEFT JOIN work_centers wc ON mo.work_center_id = wc.id
                WHERE mo.route_id = :rid AND mo.is_deleted = false
                ORDER BY mo.sequence
            """), {"rid": r.id}).fetchall()
            route_dict['operations'] = [dict(op._mapping) for op in ops]
            result.append(route_dict)
            
        return result
    finally:
        conn.close()

@router.post("/routes", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_route(route: RouteCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Route."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # Create Header
        new_route = conn.execute(text("""
            INSERT INTO manufacturing_routes (name, product_id, bom_id, is_default, is_active, description)
            VALUES (:name, :pid, :bid, :default, :active, :desc)
            RETURNING *
        """), {
            "name": route.name, "pid": route.product_id,
            "bid": route.bom_id, "default": route.is_default,
            "active": route.is_active, "desc": route.description
        }).fetchone()
        
        # Create Operations
        for op in route.operations:
            conn.execute(text("""
                INSERT INTO manufacturing_operations (route_id, sequence, name, work_center_id, description, setup_time, cycle_time, labor_rate_per_hour)
                VALUES (:rid, :seq, :name, :wcid, :desc, :setup, :cycle, :labor)
            """), {
                "rid": new_route.id, "seq": op.sequence, "name": op.name, "wcid": op.work_center_id,
                "desc": op.description, "setup": op.setup_time, "cycle": op.cycle_time,
                "labor": op.labor_rate_per_hour
            })
            
        trans.commit()
        
        # Re-fetch the newly created route with operations
        route_dict = dict(new_route._mapping)
        ops = conn.execute(text("""
            SELECT mo.*, wc.name as work_center_name 
            FROM manufacturing_operations mo
            LEFT JOIN work_centers wc ON mo.work_center_id = wc.id
            WHERE mo.route_id = :rid AND mo.is_deleted = false
            ORDER BY mo.sequence
        """), {"rid": new_route.id}).fetchall()
        route_dict['operations'] = [dict(op._mapping) for op in ops]
        # Add product_name from join
        if route.product_id:
            prod = conn.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": route.product_id}).fetchone()
            route_dict['product_name'] = prod.product_name if prod else None
        else:
            route_dict['product_name'] = None
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_route", resource_type="manufacturing_routes",
                     resource_id=str(new_route.id), details={"name": route.name},
                     request=request)
        return route_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error creating route: {e}")
        raise HTTPException(**http_error(400, "route_create_failed", request))
    finally:
        conn.close()

@router.put("/routes/{route_id}", response_model=RouteResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def update_route(route_id: int, route: RouteCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update Route."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        existing = conn.execute(text("SELECT * FROM manufacturing_routes WHERE id = :id AND is_deleted = false"), {"id": route_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "route_not_found", request))

        conn.execute(text("""
            UPDATE manufacturing_routes SET name=:name, product_id=:pid, bom_id=:bid, is_default=:default, is_active=:active, description=:desc, updated_at=NOW()
            WHERE id=:id
        """), {"name": route.name, "pid": route.product_id, "bid": route.bom_id, "default": route.is_default, "active": route.is_active, "desc": route.description, "id": route_id})

        # Replace operations: delete old ones & insert new
        conn.execute(text("DELETE FROM manufacturing_operations WHERE route_id = :rid"), {"rid": route_id})
        for op in route.operations:
            conn.execute(text("""
                INSERT INTO manufacturing_operations (route_id, sequence, name, work_center_id, description, setup_time, cycle_time, labor_rate_per_hour)
                VALUES (:rid, :seq, :name, :wcid, :desc, :setup, :cycle, :labor)
            """), {"rid": route_id, "seq": op.sequence, "name": op.name, "wcid": op.work_center_id, "desc": op.description, "setup": op.setup_time, "cycle": op.cycle_time, "labor": op.labor_rate_per_hour})

        trans.commit()

        route_row = conn.execute(text("""
            SELECT r.*, p.product_name FROM manufacturing_routes r LEFT JOIN products p ON r.product_id = p.id WHERE r.id = :id AND r.is_deleted = false
        """), {"id": route_id}).fetchone()
        route_dict = dict(route_row._mapping)
        ops = conn.execute(text("""
            SELECT mo.*, wc.name as work_center_name FROM manufacturing_operations mo
            LEFT JOIN work_centers wc ON mo.work_center_id = wc.id WHERE mo.route_id = :rid AND mo.is_deleted = false ORDER BY mo.sequence
        """), {"rid": route_id}).fetchall()
        route_dict['operations'] = [dict(op._mapping) for op in ops]
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_route", resource_type="manufacturing_routes",
                     resource_id=str(route_id), details={"name": route.name},
                     request=request)
        return route_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error updating route {route_id}: {e}")
        raise HTTPException(**http_error(400, "route_update_failed", request))
    finally:
        conn.close()

# ==========================================
# 3. BILL OF MATERIALS (BOM)
# ==========================================

@router.delete("/routes/{route_id}", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.delete"]))], response_model=Dict[str, Any])
def delete_route(route_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete Route."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # Check if in use by any production orders
        in_use = conn.execute(text("""
            SELECT COUNT(*) FROM production_orders WHERE route_id = :id AND status NOT IN ('cancelled', 'completed')
        """), {"id": route_id}).scalar()
        if in_use > 0:
            logger.warning(f"Cannot delete route {route_id}: used in {in_use} active order(s)")
            raise HTTPException(**http_error(400, "routing_has_active_production_orders", request))
        
        conn.execute(text("UPDATE manufacturing_operations SET is_deleted = true, deleted_at = NOW(), updated_at = NOW() WHERE route_id = :id"), {"id": route_id})
        result = conn.execute(text("UPDATE manufacturing_routes SET is_deleted = true, deleted_at = NOW(), updated_at = NOW() WHERE id = :id AND is_deleted = false"), {"id": route_id})
        
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "route_not_found", request))
        
        trans.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_route", resource_type="manufacturing_routes",
                     resource_id=str(route_id), request=request)
        return {"message": i18n_message("route_deleted_success", request)}
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error deleting route {route_id}: {e}")
        raise HTTPException(**http_error(400, "routing_delete_failed", request))
    finally:
        conn.close()


