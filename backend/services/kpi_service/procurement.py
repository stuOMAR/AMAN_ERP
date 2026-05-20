"""kpi_service.procurement — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter, kpi_item, ratio_status, _gl_balance, _count_table, _sum_column
)
from utils.accounting import get_base_currency
from utils.currency_display import document_amount_base_sql


def get_procurement_kpis(db, start_date: date, end_date: date,
                         branch_id: Optional[int] = None) -> dict:
    """KPIs for Purchase Manager."""
    invoice_branch_sql, invoice_bp = build_branch_filter(branch_id, table_alias="i")
    po_branch_sql, po_bp = build_branch_filter(branch_id, table_alias="po")
    base_currency = get_base_currency(db) or "SAR"

    # Total PO Value
    po_value = 0
    try:
        po_total_base_sql = document_amount_base_sql("po.total", "po")
        po_value = float(db.execute(text(f"""
            SELECT COALESCE(SUM({po_total_base_sql}), 0)
            FROM purchase_orders po
            WHERE po.order_date BETWEEN :s AND :e {po_branch_sql}
        """), {"s": start_date, "e": end_date, "base_currency": base_currency, **po_bp}).scalar() or 0)
    except Exception:
        pass
    po_count = _count_table(db, "purchase_orders", branch_id, "order_date", start_date, end_date)

    # Pending RFQs
    pending_rfqs = _count_table(db, "purchase_orders", branch_id, extra_where="status = 'draft'")

    # AP Aging
    ap_balance = _gl_balance(db, "payable", end_date, branch_id, debit_minus_credit=False)

    # Top 10 Suppliers
    top_suppliers = []
    try:
        invoice_total_base_sql = document_amount_base_sql("i.total", "i")
        rows = db.execute(text(f"""
            SELECT p.name, COALESCE(SUM({invoice_total_base_sql}), 0) as total
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase' AND i.invoice_date BETWEEN :s AND :e {invoice_branch_sql}
            GROUP BY p.name ORDER BY total DESC LIMIT 10
        """), {"s": start_date, "e": end_date, "base_currency": base_currency, **invoice_bp}).fetchall()
        top_suppliers = [{"name": r[0], "value": Decimal(str(r[1]))} for r in rows]
    except Exception:
        pass

    # Supplier On-Time Delivery (approximate — no actual_delivery_date column)
    on_time_pct = 0
    try:
        on_time = db.execute(text("""
            SELECT
                COUNT(CASE WHEN updated_at <= expected_date THEN 1 END),
                COUNT(*)
            FROM purchase_orders
            WHERE status = 'received'
        """)).fetchone()
        if on_time and on_time[1] > 0:
            on_time_pct = (on_time[0] / on_time[1]) * 100
    except Exception:
        pass

    # Avg Lead Time (approximate using updated_at as receive date)
    avg_lead_time = 0
    try:
        lt = db.execute(text("""
            SELECT AVG(EXTRACT(DAY FROM (updated_at - order_date)))
            FROM purchase_orders
            WHERE status = 'received'
        """)).scalar()
        avg_lead_time = float(lt or 0)
    except Exception:
        pass

    kpis = [
        kpi_item("po_value", "Total PO Value", "إجمالي قيمة أوامر الشراء", po_value, base_currency),
        kpi_item("po_count", "Purchase Orders", "عدد أوامر الشراء", po_count, ""),
        kpi_item("pending_rfqs", "Pending RFQs", "طلبات عروض أسعار معلقة", pending_rfqs, ""),
        kpi_item("on_time_delivery", "Supplier On-Time Delivery", "التسليم في الموعد", on_time_pct, "%",
                 benchmark=95.0, benchmark_source="Best Practice",
                 status=ratio_status(on_time_pct, 95, 80)),
        kpi_item("ap_balance", "Accounts Payable", "رصيد الذمم الدائنة", ap_balance, base_currency),
        kpi_item("avg_lead_time", "Avg Lead Time", "متوسط وقت التسليم", avg_lead_time, "days",
                 benchmark=14, benchmark_source="Industry Avg",
                 status=ratio_status(avg_lead_time, 14, 30, higher_is_better=False)),
    ]

    charts = [
        {"id": "top_suppliers", "type": "bar", "title": "Top 10 Suppliers",
         "title_ar": "أعلى 10 موردين", "data": top_suppliers},
    ]

    alerts = []
    if pending_rfqs > 5:
        alerts.append({"severity": "medium", "code": "PENDING_RFQS",
                        "message": i18n_message("kpi_pending_rfqs"),
                        "message_ar": f"{pending_rfqs} طلب عرض سعر بانتظار المراجعة",
                        "count": pending_rfqs, "link": "/buying/rfq"})

    return {"role": "procurement", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Warehouse Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

