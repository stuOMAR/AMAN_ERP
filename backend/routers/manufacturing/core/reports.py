"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from database import get_db_connection
from utils.exports import generate_excel, generate_pdf, create_export_response
from schemas import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import calculate_production_cost  # noqa: E402

_D2 = Decimal("0.01")
_D1 = Decimal("0.1")


def _dec(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _q2(value) -> Decimal:
    return _dec(value).quantize(_D2, rounding=ROUND_HALF_UP)


def _q1(value) -> Decimal:
    return _dec(value).quantize(_D1, rounding=ROUND_HALF_UP)


def _pct(numerator, denominator, scale=_D2) -> Decimal:
    base = _dec(denominator)
    if base == 0:
        return Decimal("0").quantize(scale, rounding=ROUND_HALF_UP)
    return ((_dec(numerator) / base) * Decimal("100")).quantize(scale, rounding=ROUND_HALF_UP)


def _variance_direction(value: Decimal) -> str:
    if value > 0:
        return "unfavorable"
    if value < 0:
        return "favorable"
    return "none"


def _threshold_direction(value: Decimal, high: Decimal, medium: Decimal) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"

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
        total_material = Decimal("0")
        total_labor = Decimal("0")
        total_overhead = Decimal("0")
        total_production = Decimal("0")
        
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
            total_material += _dec(cost["material_cost"])
            total_labor += _dec(cost["labor_cost"])
            total_overhead += _dec(cost["overhead_cost"])
            total_production += _dec(cost["total_cost"])
        
        return {
            "report_name": "Production Cost Report",
            "period": {"start": str(start_date) if start_date else "All", "end": str(end_date) if end_date else "All"},
            "orders": report_rows,
            "totals": {
                "total_material_cost": _q2(total_material),
                "total_labor_cost": _q2(total_labor),
                "total_overhead_cost": _q2(total_overhead),
                "total_production_cost": _q2(total_production),
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
            
            capacity_hours = _dec(wc.capacity_per_day or Decimal("8")) * Decimal("22")
            used_hours = _dec(stats.total_run_time_min or 0) / Decimal("60")
            utilization = _pct(used_hours, capacity_hours) if capacity_hours > 0 else Decimal("0.00")
            cost_per_hour = _dec(wc.cost_per_hour or 0)
            
            report_rows.append({
                "work_center_id": wc.id,
                "work_center_name": wc.name,
                "code": wc.code,
                "cost_per_hour": cost_per_hour,
                "total_operations": stats.total_operations,
                "completed_operations": stats.completed_operations,
                "total_run_time_hours": _q2(used_hours),
                "total_output": _dec(stats.total_output or 0),
                "avg_cycle_time_min": _q2(stats.avg_run_time_min or 0),
                "utilization_percent": utilization,
                "utilization_direction": _threshold_direction(utilization, Decimal("70"), Decimal("40")),
                "total_cost": _q2(used_hours * cost_per_hour),
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
        
        total_orders = sum(row.count for row in status_counts)
        by_status = {}
        for row in status_counts:
            by_status[row.status] = {
                "count": row.count,
                "total_qty": _dec(row.total_qty),
                "share_pct": _q1(_pct(row.count, total_orders, _D1)),
            }
        completed_count = by_status.get("completed", {}).get("count", 0)
        
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
            "total_orders": total_orders,
            "completed_orders": completed_count,
            "in_progress_orders": by_status.get("in_progress", {}).get("count", 0),
            "completion_rate_pct": _q1(_pct(completed_count, total_orders, _D1)),
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
        results = []
        for row in rows:
            item = dict(row._mapping)
            standard = _q2(item.get("standard_cost"))
            actual = _q2(item.get("actual_total_cost"))
            variance = _q2(item.get("variance_amount") if item.get("variance_amount") is not None else actual - standard)
            variance_pct = _q2(
                item.get("variance_percentage")
                if item.get("variance_percentage") is not None
                else _pct(variance, standard)
            )
            direction = _variance_direction(variance)
            item.update({
                "estimated_cost": str(standard),
                "actual_cost": str(actual),
                "variance": str(variance),
                "variance_pct": str(variance_pct),
                "variance_direction": direction,
                "variance_prefix": "+" if variance > 0 else "",
                "is_unfavorable": direction == "unfavorable",
                "is_favorable": direction == "favorable",
            })
            results.append(item)

        total_actual = sum((_dec(r.get('actual_total_cost')) for r in results), Decimal("0"))
        total_standard = sum((_dec(r.get('standard_cost')) for r in results), Decimal("0"))
        total_variance = _q2(total_actual - total_standard)
        overall_variance_pct = _pct(total_variance, total_standard)
        summary_direction = _variance_direction(total_variance)

        return {
            "orders": results,
            "summary": {
                "total_orders": len(results),
                "total_actual_cost": _q2(total_actual),
                "total_standard_cost": _q2(total_standard),
                "total_variance": total_variance,
                "overall_variance_pct": overall_variance_pct,
                "variance_direction": summary_direction,
                "variance_prefix": "+" if total_variance > 0 else "",
                "favorable_count": sum(1 for r in results if Decimal(str(r.get('variance_amount', 0) or 0)) < 0),
                "unfavorable_count": sum(1 for r in results if Decimal(str(r.get('variance_amount', 0) or 0)) > 0)
            }
        }
    finally:
        conn.close()


# ===================== B4: OEE + Capacity Planning =====================

@router.get("/oee", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=Dict[str, Any])
def calculate_oee(
    request: Request,
    work_center_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    period_from: Optional[str] = None,
    period_to: Optional[str] = None,
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
        effective_from = date_from or period_from
        effective_to = date_to or period_to
        if effective_from:
            q += " AND cp.plan_date >= :df"
            params["df"] = effective_from
        if effective_to:
            q += " AND cp.plan_date <= :dt"
            params["dt"] = effective_to
        q += " GROUP BY cp.work_center_id, wc.name ORDER BY wc.name"

        rows = conn.execute(text(q), params).fetchall()
        results = []
        for r in rows:
            d = dict(r._mapping)
            avail = _dec(d.get("total_available") or 0)
            planned = _dec(d.get("total_planned") or 0)
            actual = _dec(d.get("total_actual") or 0)
            availability = min(_pct(actual, avail), Decimal("100.00")) if avail > 0 else Decimal("0.00")
            performance = min(_pct(planned, actual), Decimal("100.00")) if actual > 0 else Decimal("0.00")
            quality = Decimal("98.50")  # Backend-owned default until QC yield is available in capacity_plans.
            oee = _q2(availability * performance * quality / Decimal("10000"))
            d["availability"] = availability
            d["performance"] = performance
            d["quality"] = quality
            d["quality_source"] = "backend_default"
            d["oee"] = oee
            d["availability_direction"] = _threshold_direction(availability, Decimal("90"), Decimal("60"))
            d["performance_direction"] = _threshold_direction(performance, Decimal("95"), Decimal("60"))
            d["quality_direction"] = _threshold_direction(quality, Decimal("99.9"), Decimal("95"))
            d["oee_direction"] = _threshold_direction(oee, Decimal("85"), Decimal("60"))
            results.append(d)
        return results
    except Exception as e:
        logger.error(f"Error calculating OEE: {e}")
        raise HTTPException(**http_error(500, "oee_calc_failed", request))
    finally:
        conn.close()
