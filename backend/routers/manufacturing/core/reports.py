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

from .core import calculate_production_cost

@router.get("/reports/production-cost", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def report_production_cost(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Production Cost Report: Actual vs Estimated costs for completed production orders.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT po.id, po.order_number, po.product_id, p.product_name, po.quantity,
                   po.status, po.start_date, po.updated_at as completion_date,
                   b.name as bom_name
            FROM production_orders po
            LEFT JOIN products p ON po.product_id = p.id
            LEFT JOIN bill_of_materials b ON po.bom_id = b.id
            WHERE po.status = 'completed'
        """
        params = {}
        query += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        if start_date:
            query += " AND po.start_date >= :start"
            params["start"] = start_date
        if end_date:
            query += " AND po.updated_at <= :end"
            params["end"] = end_date
        query += " ORDER BY po.updated_at DESC"
        
        orders = conn.execute(text(query), params).fetchall()
        
        report_rows = []
        total_material = 0
        total_labor = 0
        total_overhead = 0
        total_production = 0
        
        for o in orders:
            cost = calculate_production_cost(conn, o.product_id if not o.bom_name else None, o.quantity, o.id)
            # Re-calculate with actual BOM
            if o.product_id:
                bom_row = conn.execute(text(
                    "SELECT id FROM bill_of_materials WHERE product_id = :pid AND is_active = true AND is_deleted = false LIMIT 1"
                ), {"pid": o.product_id}).fetchone()
                if bom_row:
                    cost = calculate_production_cost(conn, bom_row.id, o.quantity, o.id)
            
            row = {
                "order_id": o.id,
                "order_number": o.order_number,
                "product_name": o.product_name,
                "quantity": o.quantity,
                "start_date": str(o.start_date) if o.start_date else None,
                "completion_date": str(o.completion_date) if o.completion_date else None,
                "material_cost": cost["material_cost"],
                "labor_cost": cost["labor_cost"],
                "overhead_cost": cost["overhead_cost"],
                "total_cost": cost["total_cost"],
                "unit_cost": cost["unit_cost"],
            }
            report_rows.append(row)
            total_material += cost["material_cost"]
            total_labor += cost["labor_cost"]
            total_overhead += cost["overhead_cost"]
            total_production += cost["total_cost"]
        
        return {
            "report_name": "Production Cost Report",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "orders": report_rows,
            "totals": {
                "total_material_cost": round(total_material, 2),
                "total_labor_cost": round(total_labor, 2),
                "total_overhead_cost": round(total_overhead, 2),
                "total_production_cost": round(total_production, 2),
                "order_count": len(report_rows),
            }
        }
    finally:
        conn.close()


@router.get("/reports/work-center-efficiency", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def report_work_center_efficiency(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Work Center Efficiency Report: Utilization and performance of each work center.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        wc_params = {}
        wc_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", wc_params)
        wcs = conn.execute(text(f"SELECT * FROM work_centers WHERE is_deleted = false {wc_filter} ORDER BY name"), wc_params).fetchall()
        
        date_filter = ""
        params = {}
        if start_date:
            date_filter += " AND poo.start_time >= :start"
            params["start"] = start_date
        if end_date:
            date_filter += " AND poo.end_time <= :end"
            params["end"] = end_date
        
        report_rows = []
        for wc in wcs:
            stats = conn.execute(text(f"""
                SELECT 
                    COUNT(*) as total_operations,
                    COUNT(CASE WHEN poo.status = 'completed' THEN 1 END) as completed_operations,
                    COALESCE(SUM(poo.actual_run_time), 0) as total_run_time_min,
                    COALESCE(SUM(poo.completed_quantity), 0) as total_output,
                    COALESCE(AVG(poo.actual_run_time), 0) as avg_run_time_min
                FROM production_order_operations poo
                WHERE poo.work_center_id = :wcid {date_filter}
            """), {**params, "wcid": wc.id}).fetchone()
            
            capacity_hours = (wc.capacity_per_day or 8) * 22  # Approx monthly capacity
            used_hours = (stats.total_run_time_min or 0) / 60.0
            utilization = (used_hours / capacity_hours * 100) if capacity_hours > 0 else 0
            
            report_rows.append({
                "work_center_id": wc.id,
                "work_center_name": wc.name,
                "code": wc.code,
                "cost_per_hour": Decimal(str(wc.cost_per_hour or 0)),
                "total_operations": stats.total_operations,
                "completed_operations": stats.completed_operations,
                "total_run_time_hours": round(used_hours, 2),
                "total_output": Decimal(str(stats.total_output or 0)),
                "avg_cycle_time_min": round(Decimal(str(stats.avg_run_time_min or 0)), 2),
                "utilization_percent": round(utilization, 2),
                "total_cost": round(used_hours * Decimal(str(wc.cost_per_hour or 0)), 2),
            })
        
        return {
            "report_name": "Work Center Efficiency Report",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "work_centers": report_rows,
        }
    finally:
        conn.close()


@router.get("/reports/material-consumption", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def report_material_consumption(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Material Consumption Report: Raw materials consumed by production orders.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        date_filter = ""
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        date_filter += branch_scope_filter_from_scope(branch_scope, "it.branch_id", params)
        if start_date:
            date_filter += " AND it.created_at >= :start"
            params["start"] = start_date
        if end_date:
            date_filter += " AND it.created_at <= :end"
            params["end"] = end_date
        
        rows = conn.execute(text(f"""
            SELECT p.id as product_id, p.product_name, p.product_code,
                   SUM(ABS(it.quantity)) as total_consumed,
                   COUNT(DISTINCT it.reference_id) as order_count,
                   AVG(p.cost_price) as avg_unit_cost,
                   SUM(ABS(it.quantity) * COALESCE(p.cost_price, 0)) as total_cost
            FROM inventory_transactions it
            JOIN products p ON it.product_id = p.id
            WHERE it.transaction_type = 'production_out' 
              AND it.reference_type = 'production_order'
              {date_filter}
            GROUP BY p.id, p.product_name, p.product_code
            ORDER BY total_cost DESC
        """), params).fetchall()
        
        materials = []
        grand_total = 0
        for r in rows:
            mat = {
                "product_id": r.product_id,
                "product_name": r.product_name,
                "product_code": r.product_code,
                "total_consumed": round(Decimal(str(r.total_consumed or 0)), 4),
                "order_count": r.order_count,
                "avg_unit_cost": round(Decimal(str(r.avg_unit_cost or 0)), 4),
                "total_cost": round(Decimal(str(r.total_cost or 0)), 2),
            }
            materials.append(mat)
            grand_total += mat["total_cost"]
        
        return {
            "report_name": "Material Consumption Report",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "materials": materials,
            "grand_total_cost": round(grand_total, 2),
        }
    finally:
        conn.close()


@router.get("/reports/production-summary", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def report_production_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Production Summary Dashboard: Overview of all production activities.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        date_filter = ""
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        date_filter += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        if start_date:
            date_filter += " AND po.created_at >= :start"
            params["start"] = start_date
        if end_date:
            date_filter += " AND po.created_at <= :end"
            params["end"] = end_date
        
        # Order counts by status
        status_counts = conn.execute(text(f"""
            SELECT status, COUNT(*) as count, COALESCE(SUM(quantity), 0) as total_qty
            FROM production_orders po
            WHERE 1=1 {date_filter}
            GROUP BY status
        """), params).fetchall()
        
        by_status = {row.status: {"count": row.count, "total_qty": Decimal(str(row.total_qty))} for row in status_counts}
        
        # Top produced products
        top_products = conn.execute(text(f"""
            SELECT p.product_name, SUM(po.produced_quantity) as total_produced, COUNT(*) as order_count
            FROM production_orders po
            JOIN products p ON po.product_id = p.id
            WHERE po.status = 'completed' {date_filter}
            GROUP BY p.product_name
            ORDER BY total_produced DESC
            LIMIT 10
        """), params).fetchall()
        
        # Equipment maintenance due
        maint_due = conn.execute(text("""
            SELECT COUNT(*) FROM manufacturing_equipment 
            WHERE next_maintenance_date <= CURRENT_DATE + INTERVAL '7 days' AND status != 'decommissioned' AND is_deleted = false
        """)).scalar()
        
        return {
            "report_name": "Production Summary",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "orders_by_status": by_status,
            "total_orders": sum(s["count"] for s in by_status.values()),
            "top_produced_products": [
                {"product_name": r.product_name, "total_produced": Decimal(str(r.total_produced or 0)), "order_count": r.order_count}
                for r in top_products
            ],
            "equipment_maintenance_due": maint_due or 0,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# MFG-109: Direct Labor Report (تقرير العمالة المباشرة)
# ═══════════════════════════════════════════════════════════

@router.get("/reports/direct-labor", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def report_direct_labor(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    work_center_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    format: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    تقرير العمالة المباشرة: ساعات العمل الفعلية، التكلفة، الكفاءة لكل عامل/مركز عمل/أمر إنتاج.
    Direct Labor Report: Actual hours, cost, efficiency per worker/work center/production order.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        date_filter = ""
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        date_filter += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        if start_date:
            date_filter += " AND poo.start_time >= :start"
            params["start"] = start_date
        if end_date:
            date_filter += " AND poo.end_time <= :end"
            params["end"] = end_date
        if work_center_id:
            date_filter += " AND poo.work_center_id = :wcid"
            params["wcid"] = work_center_id

        # Per work center labor breakdown
        rows = conn.execute(text(f"""
            SELECT 
                wc.id as work_center_id,
                wc.name as work_center_name,
                wc.code as work_center_code,
                wc.cost_per_hour,
                po.id as order_id,
                po.order_number,
                p.product_name,
                po.quantity as order_quantity,
                COALESCE(mo.description, '') as operation_name,
                poo.status as operation_status,
                COALESCE(poo.actual_run_time, 0) as actual_run_time_min,
                COALESCE(
                    EXTRACT(EPOCH FROM (poo.planned_end_time - poo.planned_start_time)) / 60.0,
                    mo.cycle_time * po.quantity,
                    0
                ) as planned_run_time_min,
                COALESCE(poo.completed_quantity, 0) as completed_quantity,
                poo.start_time,
                poo.end_time
            FROM production_order_operations poo
            JOIN production_orders po ON poo.production_order_id = po.id
            JOIN products p ON po.product_id = p.id
            LEFT JOIN work_centers wc ON poo.work_center_id = wc.id
            LEFT JOIN manufacturing_operations mo ON poo.operation_id = mo.id
            WHERE poo.status IN ('completed', 'in_progress')
            {date_filter}
            ORDER BY wc.name, po.order_number, mo.sequence
        """), params).fetchall()

        # Build detailed report
        report_rows = []
        total_actual_hours = 0
        total_planned_hours = 0
        total_labor_cost = 0

        for r in rows:
            actual_hours = round(Decimal(str(r.actual_run_time_min or 0)) / Decimal("60"), 2)
            planned_hours = round(Decimal(str(r.planned_run_time_min or 0)) / Decimal("60"), 2)
            cost_per_hour = Decimal(str(r.cost_per_hour or 0))
            labor_cost = round(actual_hours * cost_per_hour, 2)
            efficiency = round((planned_hours / actual_hours * 100), 1) if actual_hours > 0 else 0

            total_actual_hours += actual_hours
            total_planned_hours += planned_hours
            total_labor_cost += labor_cost

            report_rows.append({
                "work_center": r.work_center_name or "غير محدد",
                "work_center_code": r.work_center_code or "",
                "order_number": r.order_number,
                "product_name": r.product_name,
                "operation": r.operation_name or "",
                "planned_hours": planned_hours,
                "actual_hours": actual_hours,
                "efficiency_pct": efficiency,
                "cost_per_hour": cost_per_hour,
                "labor_cost": labor_cost,
                "completed_qty": Decimal(str(r.completed_quantity or 0)),
                "cost_per_unit": round(labor_cost / Decimal(str(r.completed_quantity)), 2) if r.completed_quantity else 0,
            })

        # Summary by work center
        wc_summary = {}
        for r in report_rows:
            wc = r["work_center"]
            if wc not in wc_summary:
                wc_summary[wc] = {"hours": 0, "cost": 0, "operations": 0}
            wc_summary[wc]["hours"] += r["actual_hours"]
            wc_summary[wc]["cost"] += r["labor_cost"]
            wc_summary[wc]["operations"] += 1

        overall_efficiency = round((total_planned_hours / total_actual_hours * 100), 1) if total_actual_hours > 0 else 0

        result = {
            "report_name": "Direct Labor Report - تقرير العمالة المباشرة",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "details": report_rows,
            "work_center_summary": [
                {"work_center": k, "total_hours": round(v["hours"], 2), "total_cost": round(v["cost"], 2), "operations_count": v["operations"]}
                for k, v in wc_summary.items()
            ],
            "totals": {
                "total_actual_hours": round(total_actual_hours, 2),
                "total_planned_hours": round(total_planned_hours, 2),
                "overall_efficiency_pct": overall_efficiency,
                "total_labor_cost": round(total_labor_cost, 2),
                "total_operations": len(report_rows),
            }
        }

        # Export if format specified
        if format in ("excel", "pdf"):
            export_data = []
            for r in report_rows:
                export_data.append({
                    "مركز العمل / Work Center": r["work_center"],
                    "أمر الإنتاج / Order #": r["order_number"],
                    "المنتج / Product": r["product_name"],
                    "العملية / Operation": r["operation"],
                    "ساعات مخططة / Planned Hrs": r["planned_hours"],
                    "ساعات فعلية / Actual Hrs": r["actual_hours"],
                    "الكفاءة % / Efficiency": f"{r['efficiency_pct']}%",
                    "تكلفة الساعة / Cost/Hr": r["cost_per_hour"],
                    "تكلفة العمالة / Labor Cost": r["labor_cost"],
                })
            columns = list(export_data[0].keys()) if export_data else []
            period_str = f"{start_date or 'all'}_{end_date or 'all'}"
            if format == "excel":
                buffer = generate_excel(export_data, columns, sheet_name="Direct Labor")
                return create_export_response(buffer, f"direct_labor_{period_str}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                pdf_data = [columns] + [[str(row.get(c, '')) for c in columns] for row in export_data]
                buffer = generate_pdf(pdf_data, f"Direct Labor Report ({period_str})")
                return create_export_response(buffer, f"direct_labor_{period_str}.pdf", "application/pdf")

        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# MFG-107: Variable BOM — Compute Material Quantities
# ═══════════════════════════════════════════════════════════

@router.get("/cost-variance-report", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def cost_variance_report(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """تقرير الانحرافات — مقارنة التكلفة المعيارية بالفعلية لكل أوامر الإنتاج"""
    conn = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT po.id, po.order_number, po.product_id,
                   p.product_name, p.sku,
                   po.quantity, po.produced_quantity,
                   po.actual_material_cost, po.actual_labor_cost,
                   po.actual_overhead_cost, po.actual_total_cost,
                   po.standard_cost, po.variance_amount, po.variance_percentage,
                   po.costing_status, po.status, po.created_at
            FROM production_orders po
            JOIN products p ON p.id = po.product_id
            WHERE po.costing_status = 'calculated'
        """
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        query += branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        if from_date:
            query += " AND po.created_at >= :fd"
            params["fd"] = from_date
        if to_date:
            query += " AND po.created_at <= :td"
            params["td"] = to_date

        query += " ORDER BY ABS(COALESCE(po.variance_percentage, 0)) DESC"

        rows = conn.execute(text(query), params).fetchall()
        results = [dict(r._mapping) for r in rows]

        total_actual = sum(Decimal(str(r.get('actual_total_cost', 0) or 0)) for r in results)
        total_standard = sum(Decimal(str(r.get('standard_cost', 0) or 0)) for r in results)
        total_variance = round(total_actual - total_standard, 2)

        return {
            "orders": results,
            "summary": {
                "total_orders": len(results),
                "total_actual_cost": total_actual,
                "total_standard_cost": total_standard,
                "total_variance": total_variance,
                "overall_variance_pct": round((total_variance / total_standard * 100), 2) if total_standard else 0,
                "favorable_count": sum(1 for r in results if Decimal(str(r.get('variance_amount', 0) or 0)) < 0),
                "unfavorable_count": sum(1 for r in results if Decimal(str(r.get('variance_amount', 0) or 0)) > 0)
            }
        }
    finally:
        conn.close()


# ===================== B4: OEE + Capacity Planning =====================

@router.get("/oee", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def calculate_oee(
    work_center_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """حساب الفعالية الشاملة للمعدات OEE"""
    conn = get_db_connection(current_user.company_id)
    try:
        q = """
            SELECT cp.work_center_id, wc.name as work_center_name,
                   AVG(cp.efficiency_pct) as avg_efficiency,
                   SUM(cp.available_hours) as total_available,
                   SUM(cp.planned_hours) as total_planned,
                   SUM(cp.actual_hours) as total_actual
            FROM capacity_plans cp
            LEFT JOIN work_centers wc ON wc.id = cp.work_center_id
            WHERE 1=1 AND cp.is_deleted = false AND (wc.is_deleted = false OR wc.id IS NULL)
        """
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        q += branch_scope_filter_from_scope(branch_scope, "wc.branch_id", params)
        if work_center_id:
            q += " AND cp.work_center_id = :wc"
            params["wc"] = work_center_id
        if date_from:
            q += " AND cp.plan_date >= :df"
            params["df"] = date_from
        if date_to:
            q += " AND cp.plan_date <= :dt"
            params["dt"] = date_to
        q += " GROUP BY cp.work_center_id, wc.name ORDER BY wc.name"

        rows = conn.execute(text(q), params).fetchall()
        results = []
        for r in rows:
            d = dict(r._mapping)
            avail = Decimal(str(d.get("total_available") or 1))
            planned = Decimal(str(d.get("total_planned") or 0))
            actual = Decimal(str(d.get("total_actual") or 0))
            availability = min(actual / avail * 100, 100) if avail > 0 else 0
            performance = min(planned / actual * 100, 100) if actual > 0 else 0
            quality = 98.5  # placeholder - would come from QC data
            oee = round(availability * performance * quality / 10000, 2)
            d["availability"] = round(availability, 2)
            d["performance"] = round(performance, 2)
            d["quality"] = round(quality, 2)
            d["oee"] = oee
            results.append(d)
        return results
    except Exception as e:
        logger.error(f"Error calculating OEE: {e}")
        raise HTTPException(500, "فشل في حساب الفعالية الشاملة")
    finally:
        conn.close()


