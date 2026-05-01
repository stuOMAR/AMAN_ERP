"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from decimal import Decimal
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error
from pydantic import BaseModel
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import require_permission, require_module
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

def calculate_production_cost(conn, bom_id: int, order_quantity: float, order_id: int = None):
    """
    Calculate total production cost breakdown for a production order.
    Returns dict with material_cost, labor_cost, overhead_cost, total_cost, and unit_cost.
    """
    # A. Material Cost (from BOM components × quantity × cost_price)
    total_material_cost = Decimal("0")
    component_details = []
    
    if bom_id:
        components = conn.execute(text("""
            SELECT bc.*, p.cost_price, p.product_name
            FROM bom_components bc
            JOIN products p ON bc.component_product_id = p.id
            WHERE bc.bom_id = :bid AND bc.is_deleted = false
        """), {"bid": bom_id}).fetchall()
        
        for comp in components:
            waste_factor = 1 + Decimal(str(comp.waste_percentage or 0)) / Decimal("100")
            # Handle percentage-based BOM components
            if comp.is_percentage:
                base_qty = Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order_quantity))
                required_qty = base_qty * waste_factor
            else:
                required_qty = Decimal(str(comp.quantity)) * Decimal(str(order_quantity)) * waste_factor
            unit_cost = Decimal(str(comp.cost_price or 0))
            line_cost = required_qty * unit_cost
            total_material_cost += line_cost
            component_details.append({
                "product_name": comp.product_name,
                "product_id": comp.component_product_id,
                "base_qty": (Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order_quantity))) if comp.is_percentage else Decimal(str(comp.quantity)) * Decimal(str(order_quantity)),
                "waste_qty": required_qty - ((Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order_quantity))) if comp.is_percentage else Decimal(str(comp.quantity)) * Decimal(str(order_quantity))),
                "total_qty": required_qty,
                "unit_cost": unit_cost,
                "total_cost": line_cost,
            })
    
    # B. Labor Cost (from production_order_operations × work_center cost_per_hour)
    total_labor_cost = Decimal("0")
    total_overhead_cost = Decimal("0")
    
    if order_id:
        ops_data = conn.execute(text("""
            SELECT poo.actual_run_time, wc.cost_per_hour
            FROM production_order_operations poo
            LEFT JOIN work_centers wc ON poo.work_center_id = wc.id
            WHERE poo.production_order_id = :oid
        """), {"oid": order_id}).fetchall()
        
        for op in ops_data:
            duration_hours = Decimal(str(op.actual_run_time or 0)) / Decimal("60")
            rate = Decimal(str(op.cost_per_hour or 0))
            total_labor_cost += duration_hours * rate
        
        # C. Overhead = configurable percentage of labor cost (default 30%)
        # Read from company_settings if available
        overhead_rate_row = conn.execute(text(
            "SELECT setting_value FROM company_settings WHERE setting_key = 'mfg_overhead_rate'"
        )).fetchone()
        overhead_rate = Decimal(str(overhead_rate_row.setting_value)) if overhead_rate_row else Decimal("0.30")
        total_overhead_cost = total_labor_cost * overhead_rate
    
    total_cost = total_material_cost + total_labor_cost + total_overhead_cost
    unit_cost = total_cost / Decimal(str(order_quantity)) if order_quantity else Decimal("0")
    
    return {
        "material_cost": round(total_material_cost, 2),
        "labor_cost": round(total_labor_cost, 2),
        "overhead_cost": round(total_overhead_cost, 2),
        "total_cost": round(total_cost, 2),
        "unit_cost": round(unit_cost, 4),
        "components": component_details,
    }


# ---- Helper: Check Inventory Sufficiency ----
def check_inventory_sufficiency(conn, bom_id: int, order_quantity: float, warehouse_id: int = None):
    """
    Check if enough raw materials are available in inventory for a production order.
    Returns (is_sufficient: bool, shortages: list).
    """
    if not bom_id:
        return True, []
    
    components = conn.execute(text("""
        SELECT bc.*, p.product_name
        FROM bom_components bc
        JOIN products p ON bc.component_product_id = p.id
        WHERE bc.bom_id = :bid AND bc.is_deleted = false
    """), {"bid": bom_id}).fetchall()
    
    shortages = []
    for comp in components:
        waste_factor = 1 + Decimal(str(comp.waste_percentage or 0)) / Decimal("100")
        # Variable BOM: quantity is a percentage of the order quantity
        base_qty = (Decimal(str(comp.quantity)) / Decimal("100") * Decimal(str(order_quantity))) if comp.is_percentage else Decimal(str(comp.quantity))
        required_qty = base_qty * Decimal(str(order_quantity)) * waste_factor if not comp.is_percentage else base_qty * waste_factor
        
        # Check available quantity
        if warehouse_id:
            inv = conn.execute(text("""
                SELECT COALESCE(quantity, 0) as qty FROM inventory 
                WHERE product_id = :pid AND warehouse_id = :whid
            """), {"pid": comp.component_product_id, "whid": warehouse_id}).fetchone()
        else:
            inv = conn.execute(text("""
                SELECT COALESCE(SUM(quantity), 0) as qty FROM inventory 
                WHERE product_id = :pid
            """), {"pid": comp.component_product_id}).fetchone()
        
        available = Decimal(str(inv.qty)) if inv else Decimal("0")
        
        if available < required_qty:
            shortages.append({
                "product_id": comp.component_product_id,
                "product_name": comp.product_name,
                "required": round(required_qty, 4),
                "available": round(available, 4),
                "shortage": round(required_qty - available, 4),
            })
    
    return len(shortages) == 0, shortages


class QCCheckCreate(BaseModel):
    check_name: str
    check_type: Optional[str] = "visual"
    specification: Optional[str] = None
    failure_action: Optional[str] = "warn"
    operation_id: Optional[int] = None
    notes: Optional[str] = None


class QCResultRecord(BaseModel):
    actual_value: str
    result: str   # "pass" | "fail" | "warning"
    notes: Optional[str] = None


class ActualCostUpdate(BaseModel):
    actual_material_cost: Optional[float] = None
    actual_labor_cost: Optional[float] = None
    actual_overhead_cost: Optional[float] = None


