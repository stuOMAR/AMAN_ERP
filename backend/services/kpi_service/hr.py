"""kpi_service.hr — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter, kpi_item, ratio_status, _count_table
)
from utils.accounting import get_base_currency
from utils.currency_display import branch_amount_base_sql


def get_hr_kpis(db, start_date: date, end_date: date,
                branch_id: Optional[int] = None) -> dict:
    """KPIs for HR Manager."""
    branch_sql, bp = build_branch_filter(branch_id, "e")
    base_currency = get_base_currency(db) or "SAR"

    # Headcount
    headcount = _count_table(db, "employees", branch_id, extra_where="status = 'active'")

    # Saudization
    saudi_count = 0
    try:
        sc = db.execute(text(f"""
            SELECT COUNT(*) FROM employees
            WHERE status = 'active' AND (nationality = 'Saudi' OR nationality = 'سعودي')
            {branch_sql.replace('e.', '')}
        """), bp).scalar()
        saudi_count = int(sc or 0)
    except Exception:
        pass
    saudization = (saudi_count / headcount * 100) if headcount > 0 else 0

    # Nitaqat Band
    if saudization >= 40:
        nitaqat = "Platinum"
    elif saudization >= 26:
        nitaqat = "Green"
    elif saudization >= 10:
        nitaqat = "Yellow"
    else:
        nitaqat = "Red"

    # Payroll total this period (join via period_id to payroll_periods)
    payroll_total = 0
    try:
        payroll_base_sql = branch_amount_base_sql("pe.net_salary", "e.branch_id")
        pt = db.execute(text(f"""
            SELECT COALESCE(SUM({payroll_base_sql}), 0)
            FROM payroll_entries pe
            JOIN payroll_periods pp ON pe.period_id = pp.id
            JOIN employees e ON pe.employee_id = e.id
            WHERE pp.start_date >= :s AND pp.end_date <= :e {branch_sql}
        """), {"s": start_date, "e": end_date, "base_currency": base_currency, **bp}).scalar()
        payroll_total = float(pt or 0)
    except Exception:
        pass

    # Attendance rate
    attendance_rate = 0
    try:
        att = db.execute(text("""
            SELECT
                COUNT(CASE WHEN status = 'present' THEN 1 END),
                COUNT(*)
            FROM attendance
            WHERE date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if att and att[1] > 0:
            attendance_rate = (att[0] / att[1]) * 100
    except Exception:
        pass

    # Turnover rate (employees terminated / avg headcount * 100) annualized
    terminated = _count_table(db, "employees", date_col="termination_date",
                              start_date=start_date, end_date=end_date,
                              extra_where="status = 'terminated'")
    turnover_rate = (terminated / headcount * 100) if headcount > 0 else 0

    # Pending leave requests
    pending_leaves = _count_table(db, "leave_requests", extra_where="status = 'pending'")

    # Training hours (estimated from program date range)
    training_hours = 0
    try:
        th = db.execute(text("""
            SELECT COALESCE(SUM(
                EXTRACT(EPOCH FROM (COALESCE(end_date, start_date + INTERVAL '1 day') - start_date)) / 3600
            ), 0) FROM training_programs
            WHERE start_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        training_hours = float(th or 0)
    except Exception:
        pass
    training_per_emp = training_hours / headcount if headcount > 0 else 0

    kpis = [
        kpi_item("headcount", "Total Headcount", "إجمالي الموظفين", headcount, ""),
        kpi_item("saudization", "Saudization Rate", "نسبة السعودة", saudization, "%",
                 benchmark=26.0, benchmark_source="GAZT Nitaqat",
                 status=ratio_status(saudization, 26, 10)),
        kpi_item("nitaqat_band", "Nitaqat Band", "نطاق نطاقات", nitaqat, "",
                 status="good" if nitaqat in ("Platinum", "Green") else ("warning" if nitaqat == "Yellow" else "danger")),
        kpi_item("payroll_total", "Payroll Total", "إجمالي الرواتب", payroll_total, base_currency),
        kpi_item("attendance_rate", "Attendance Rate", "معدل الحضور", attendance_rate, "%",
                 benchmark=95.0, benchmark_source="HR Best Practice",
                 status=ratio_status(attendance_rate, 95, 85)),
        kpi_item("turnover_rate", "Turnover Rate", "معدل دوران الموظفين", turnover_rate, "%",
                 benchmark=10.0, benchmark_source="Industry Avg",
                 status=ratio_status(turnover_rate, 10, 25, higher_is_better=False)),
        kpi_item("pending_leaves", "Pending Leave Requests", "طلبات إجازة معلقة", pending_leaves, ""),
        kpi_item("training_per_emp", "Training Hours/Employee", "ساعات التدريب لكل موظف",
                 training_per_emp, "hrs",
                 benchmark=20.0, benchmark_source="Annual Target"),
    ]

    charts = []
    alerts = []
    if nitaqat in ("Red", "Yellow"):
        alerts.append({"severity": "high" if nitaqat == "Red" else "medium",
                        "code": "SAUDIZATION", "message": i18n_message("kpi_saudization", request),
                        "message_ar": f"نسبة السعودة {saudization:.1f}% — نطاق {'أحمر' if nitaqat == 'Red' else 'أصفر'}",
                        "link": "/hr/saudization"})
    if pending_leaves > 10:
        alerts.append({"severity": "medium", "code": "PENDING_LEAVES",
                        "message": i18n_message("kpi_pending_leaves", request),
                        "message_ar": f"{pending_leaves} طلب إجازة بانتظار الاعتماد",
                        "count": pending_leaves, "link": "/hr/leaves"})

    return {"role": "hr", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Manufacturing Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

