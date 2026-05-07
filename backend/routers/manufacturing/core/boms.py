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

@router.get("/boms", response_model=List[BOMResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_boms(
    branch_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """List Boms."""
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT b.*, p.product_name as product_name, r.name as route_name
            FROM bill_of_materials b
            LEFT JOIN products p ON b.product_id = p.id
            LEFT JOIN manufacturing_routes r ON b.route_id = r.id
            WHERE b.is_deleted = false
        """
        params = {}
        branch_condition = branch_scope_filter_from_scope(branch_scope, "w.branch_id", params).strip()
        if branch_condition:
            query += """
                AND b.product_id IN (
                    SELECT DISTINCT inv.product_id
                    FROM inventory inv
                    JOIN warehouses w ON inv.warehouse_id = w.id
                    WHERE 1=1 {branch_condition}
                )
            """.format(branch_condition=branch_condition)
        query += " ORDER BY b.id DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        boms_db = conn.execute(text(query), params).fetchall()
        
        result = []
        for b in boms_db:
            bom_dict = dict(b._mapping)
            # Fetch components
            comps = conn.execute(text("""
                SELECT bc.*, p.product_name as component_name, u.unit_name as component_uom
                FROM bom_components bc
                LEFT JOIN products p ON bc.component_product_id = p.id
                LEFT JOIN product_units u ON p.unit_id = u.id
                WHERE bc.bom_id = :bid AND bc.is_deleted = false
            """), {"bid": b.id}).fetchall()
            bom_dict['components'] = [dict(c._mapping) for c in comps]
            
            # Fetch outputs (by-products)
            outputs = conn.execute(text("""
                SELECT bo.*, p.product_name 
                FROM bom_outputs bo
                LEFT JOIN products p ON bo.product_id = p.id
                WHERE bo.bom_id = :bid AND bo.is_deleted = false
            """), {"bid": b.id}).fetchall()
            bom_dict['outputs'] = [dict(o._mapping) for o in outputs]
            
            result.append(bom_dict)
            
        return result
    finally:
        conn.close()

@router.post("/boms", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_bom(bom: BOMCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create BOM."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        new_bom = conn.execute(text("""
            INSERT INTO bill_of_materials (product_id, code, name, yield_quantity, route_id, is_active, notes)
            VALUES (:pid, :code, :name, :yield_q, :rid, :active, :notes)
            RETURNING *
        """), {
            "pid": bom.product_id, "code": bom.code, "name": bom.name,
            "yield_q": bom.yield_quantity, "rid": bom.route_id, 
            "active": bom.is_active, "notes": bom.notes
        }).fetchone()
        
        for comp in bom.components:
            conn.execute(text("""
                INSERT INTO bom_components (bom_id, component_product_id, quantity, waste_percentage, cost_share_percentage, is_percentage, notes)
                VALUES (:bid, :cpid, :qty, :waste, :share, :is_pct, :notes)
            """), {
                "bid": new_bom.id, "cpid": comp.component_product_id,
                "qty": comp.quantity, "waste": comp.waste_percentage,
                "share": comp.cost_share_percentage,
                "is_pct": comp.is_percentage,
                "notes": comp.notes
            })

        for out in bom.outputs:
            conn.execute(text("""
                INSERT INTO bom_outputs (bom_id, product_id, quantity, cost_allocation_percentage, notes)
                VALUES (:bid, :pid, :qty, :share, :notes)
            """), {
                "bid": new_bom.id, "pid": out.product_id,
                "qty": out.quantity, "share": out.cost_allocation_percentage,
                "notes": out.notes
            })
            
        trans.commit()
        # Re-fetch the newly created BOM with its components and outputs
        bom_dict = dict(new_bom._mapping)
        # Add product_name and route_name from joins
        prod_route = conn.execute(text("""
            SELECT p.product_name, r.name as route_name
            FROM bill_of_materials b
            LEFT JOIN products p ON b.product_id = p.id
            LEFT JOIN manufacturing_routes r ON b.route_id = r.id
            WHERE b.id = :bid AND b.is_deleted = false
        """), {"bid": new_bom.id}).fetchone()
        if prod_route:
            bom_dict['product_name'] = prod_route.product_name
            bom_dict['route_name'] = prod_route.route_name
        
        # Fetch components
        comps = conn.execute(text("""
            SELECT bc.*, p.product_name as component_name, u.unit_name as component_uom
            FROM bom_components bc
            LEFT JOIN products p ON bc.component_product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": new_bom.id}).fetchall()
        bom_dict['components'] = [dict(c._mapping) for c in comps]
        
        # Fetch outputs
        outputs = conn.execute(text("""
            SELECT bo.*, p.product_name 
            FROM bom_outputs bo
            LEFT JOIN products p ON bo.product_id = p.id
            WHERE bo.bom_id = :bid AND bo.is_deleted = false
        """), {"bid": new_bom.id}).fetchall()
        bom_dict['outputs'] = [dict(o._mapping) for o in outputs]
        
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_bom", resource_type="bill_of_materials",
                     resource_id=str(new_bom.id), details={"name": bom.name, "code": bom.code},
                     request=request)
        return bom_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error creating BOM: {e}")
        raise HTTPException(status_code=400, detail="فشل في إنشاء قائمة المواد")
    finally:
        conn.close()

@router.get("/boms/{bom_id}", response_model=BOMResponse, dependencies=[Depends(require_permission("manufacturing.view"))])
def get_bom(bom_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Get BOM."""
    conn = get_db_connection(current_user.company_id)
    try:
        b = conn.execute(text("""
            SELECT b.*, p.product_name as product_name, r.name as route_name
            FROM bill_of_materials b
            LEFT JOIN products p ON b.product_id = p.id
            LEFT JOIN manufacturing_routes r ON b.route_id = r.id
            WHERE b.id = :bid AND b.is_deleted = false
        """), {"bid": bom_id}).fetchone()
        if not b:
            raise HTTPException(status_code=404, detail="BOM not found")
        bom_dict = dict(b._mapping)
        comps = conn.execute(text("""
            SELECT bc.*, p.product_name as component_name, u.unit_name as component_uom
            FROM bom_components bc
            LEFT JOIN products p ON bc.component_product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": bom_id}).fetchall()
        bom_dict['components'] = [dict(c._mapping) for c in comps]
        outputs = conn.execute(text("""
            SELECT bo.*, p.product_name FROM bom_outputs bo
            LEFT JOIN products p ON bo.product_id = p.id WHERE bo.bom_id = :bid AND bo.is_deleted = false
        """), {"bid": bom_id}).fetchall()
        bom_dict['outputs'] = [dict(o._mapping) for o in outputs]
        return bom_dict
    finally:
        conn.close()

@router.put("/boms/{bom_id}", response_model=BOMResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def update_bom(bom_id: int, bom: BOMCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update BOM."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        existing = conn.execute(text("SELECT * FROM bill_of_materials WHERE id = :id AND is_deleted = false"), {"id": bom_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="BOM not found")

        conn.execute(text("""
            UPDATE bill_of_materials SET product_id=:pid, code=:code, name=:name, yield_quantity=:yield_q,
                route_id=:rid, is_active=:active, notes=:notes, updated_at=NOW()
            WHERE id=:id
        """), {
            "pid": bom.product_id, "code": bom.code, "name": bom.name,
            "yield_q": bom.yield_quantity, "rid": bom.route_id,
            "active": bom.is_active, "notes": bom.notes, "id": bom_id
        })

        # Replace components
        conn.execute(text("DELETE FROM bom_components WHERE bom_id = :bid"), {"bid": bom_id})
        for comp in bom.components:
            conn.execute(text("""
                INSERT INTO bom_components (bom_id, component_product_id, quantity, waste_percentage, cost_share_percentage, is_percentage, notes)
                VALUES (:bid, :cpid, :qty, :waste, :share, :is_pct, :notes)
            """), {
                "bid": bom_id, "cpid": comp.component_product_id,
                "qty": comp.quantity, "waste": comp.waste_percentage,
                "share": comp.cost_share_percentage, "is_pct": comp.is_percentage, "notes": comp.notes
            })

        # Replace outputs
        conn.execute(text("DELETE FROM bom_outputs WHERE bom_id = :bid"), {"bid": bom_id})
        for out in bom.outputs:
            conn.execute(text("""
                INSERT INTO bom_outputs (bom_id, product_id, quantity, cost_allocation_percentage, notes)
                VALUES (:bid, :pid, :qty, :share, :notes)
            """), {"bid": bom_id, "pid": out.product_id, "qty": out.quantity, "share": out.cost_allocation_percentage, "notes": out.notes})

        trans.commit()

        # Re-fetch with joins
        b = conn.execute(text("""
            SELECT b.*, p.product_name as product_name, r.name as route_name
            FROM bill_of_materials b LEFT JOIN products p ON b.product_id = p.id
            LEFT JOIN manufacturing_routes r ON b.route_id = r.id WHERE b.id = :bid AND b.is_deleted = false
        """), {"bid": bom_id}).fetchone()
        bom_dict = dict(b._mapping)
        comps = conn.execute(text("""
            SELECT bc.*, p.product_name as component_name, u.unit_name as component_uom
            FROM bom_components bc LEFT JOIN products p ON bc.component_product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": bom_id}).fetchall()
        bom_dict['components'] = [dict(c._mapping) for c in comps]
        outputs = conn.execute(text("""
            SELECT bo.*, p.product_name FROM bom_outputs bo
            LEFT JOIN products p ON bo.product_id = p.id WHERE bo.bom_id = :bid AND bo.is_deleted = false
        """), {"bid": bom_id}).fetchall()
        bom_dict['outputs'] = [dict(o._mapping) for o in outputs]
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_bom", resource_type="bill_of_materials",
                     resource_id=str(bom_id), details={"name": bom.name},
                     request=request)
        return bom_dict
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error updating BOM {bom_id}: {e}")
        raise HTTPException(status_code=400, detail="فشل في تحديث قائمة المواد")
    finally:
        conn.close()


# ==========================================
# 4. PRODUCTION ORDERS
# ==========================================

# ---- Helper: Calculate Production Cost ----
@router.delete("/boms/{bom_id}", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.delete"]))], response_model=Dict[str, Any])
def delete_bom(bom_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete BOM."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # Check if in use
        in_use = conn.execute(text("""
            SELECT COUNT(*) FROM production_orders WHERE bom_id = :id AND status NOT IN ('cancelled', 'completed')
        """), {"id": bom_id}).scalar()
        if in_use > 0:
            logger.warning(f"Cannot delete BOM {bom_id}: used in {in_use} active order(s)")
            raise HTTPException(status_code=400, detail="لا يمكن حذف قائمة المواد لارتباطها بأوامر إنتاج نشطة")
        
        conn.execute(text("UPDATE bom_outputs SET is_deleted = true, deleted_at = NOW() WHERE bom_id = :id"), {"id": bom_id})
        conn.execute(text("UPDATE bom_components SET is_deleted = true, deleted_at = NOW() WHERE bom_id = :id"), {"id": bom_id})
        result = conn.execute(text("UPDATE bill_of_materials SET is_deleted = true, deleted_at = NOW(), updated_at = NOW() WHERE id = :id AND is_deleted = false"), {"id": bom_id})
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="BOM not found")
        
        trans.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_bom", resource_type="bill_of_materials",
                     resource_id=str(bom_id), request=request)
        return {"message": "BOM deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error deleting BOM {bom_id}: {e}")
        raise HTTPException(status_code=400, detail="فشل في حذف قائمة المواد")
    finally:
        conn.close()


# --- JOB CARDS (MFG-007) ---

@router.get("/boms/{bom_id}/compute-materials", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def compute_bom_materials(
    bom_id: int,
    quantity: float = Query(..., description="Production order quantity"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    احسب الكميات الفعلية للمكونات بناءً على كمية الإنتاج المطلوبة.
    يدعم BOMs النسبية (Variable BOM) والثابتة.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        bom = conn.execute(text("SELECT * FROM bill_of_materials WHERE id = :id AND is_deleted = false"), {"id": bom_id}).fetchone()
        if not bom:
            raise HTTPException(status_code=404, detail="BOM غير موجود")

        components = conn.execute(text("""
            SELECT bc.*, p.product_name, p.cost_price, u.unit_name
            FROM bom_components bc
            JOIN products p ON bc.component_product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": bom_id}).fetchall()

        result_components = []
        total_material_cost = Decimal("0")

        for c in components:
            waste_factor = 1 + (c.waste_percentage or 0) / 100.0
            if c.is_percentage:
                # Variable BOM: base qty = quantity% of order
                computed_qty = round((c.quantity / 100.0 * quantity) * waste_factor, 4)
            else:
                # Fixed BOM: qty per unit × order qty
                computed_qty = round(c.quantity * quantity * waste_factor, 4)

            unit_cost = Decimal(str(c.cost_price or 0))
            line_cost = computed_qty * unit_cost
            total_material_cost += line_cost

            # Check available inventory
            inv = conn.execute(text(
                "SELECT COALESCE(SUM(quantity), 0) as qty FROM inventory WHERE product_id = :pid"
            ), {"pid": c.component_product_id}).scalar()
            available = Decimal(str(inv))

            result_components.append({
                "component_product_id": c.component_product_id,
                "product_name": c.product_name,
                "unit": c.unit_name,
                "is_percentage": bool(c.is_percentage),
                "bom_quantity": Decimal(str(c.quantity)),
                "computed_quantity": computed_qty,
                "waste_percentage": Decimal(str(c.waste_percentage or 0)),
                "unit_cost": unit_cost,
                "line_cost": round(line_cost, 2),
                "available_inventory": round(available, 4),
                "sufficient": available >= computed_qty,
                "shortage": round(max(0.0, computed_qty - available), 4),
            })

        return {
            "bom_id": bom_id,
            "bom_name": bom.name,
            "production_quantity": quantity,
            "total_material_cost": round(total_material_cost, 2),
            "components": result_components,
            "all_sufficient": all(c["sufficient"] for c in result_components),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing BOM materials: {e}")
        raise HTTPException(status_code=500, detail="فشل في حساب المواد")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# MFG-108: In-Process QC Checks (فحص الجودة أثناء الإنتاج)
# ═══════════════════════════════════════════════════════════

