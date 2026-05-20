"""kpi_service.charts — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter
)
from utils.accounting import get_base_currency
from utils.currency_display import document_amount_base_sql


def _build_revenue_expense_chart(db, start_date: date, end_date: date,
                                  branch_id: Optional[int] = None) -> list:
    """Monthly revenue vs expenses trend chart."""
    branch_sql, bp = build_branch_filter(branch_id, table_alias="je")
    data = []
    try:
        rows = db.execute(text(f"""
            SELECT
                TO_CHAR(je.entry_date, 'YYYY-MM') as month,
                COALESCE(SUM(CASE WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit ELSE 0 END), 0) as revenue,
                COALESCE(SUM(CASE WHEN a.account_type = 'expense' THEN jl.debit - jl.credit ELSE 0 END), 0) as expenses
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE je.entry_date BETWEEN :s AND :e AND je.status = 'posted' {branch_sql}
            GROUP BY TO_CHAR(je.entry_date, 'YYYY-MM')
            ORDER BY month
        """), {"s": start_date, "e": end_date, **bp}).fetchall()
        data = [{"month": r[0], "revenue": Decimal(str(r[1])), "expenses": Decimal(str(r[2]))} for r in rows]
    except Exception:
        pass
    return [{"id": "revenue_vs_expenses", "type": "line", "title": "Revenue vs Expenses",
             "title_ar": "الإيرادات مقابل المصروفات", "data": data}]


def _build_sales_trend_chart(db, start_date: date, end_date: date,
                              branch_id: Optional[int] = None) -> list:
    """Daily sales trend."""
    branch_sql, bp = build_branch_filter(branch_id, table_alias="i")
    total_base_sql = document_amount_base_sql("i.total", "i")
    base_currency = get_base_currency(db) or "SAR"
    data = []
    try:
        rows = db.execute(text(f"""
            SELECT DATE(i.invoice_date) as day, COALESCE(SUM({total_base_sql}), 0)
            FROM invoices i
            WHERE i.invoice_type = 'sales' AND i.invoice_date BETWEEN :s AND :e AND i.status != 'cancelled' {branch_sql}
            GROUP BY DATE(i.invoice_date) ORDER BY day
        """), {"s": start_date, "e": end_date, "base_currency": base_currency, **bp}).fetchall()
        data = [{"date": str(r[0]), "value": Decimal(str(r[1]))} for r in rows]
    except Exception:
        pass
    return [{"id": "sales_trend", "type": "line", "title": "Sales Trend",
             "title_ar": "اتجاه المبيعات", "data": data}]


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Aging Builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_ar_aging(db, as_of: date, branch_id: Optional[int] = None) -> list:
    """AR Aging buckets: 0-30, 31-60, 61-90, 90+."""
    branch_sql, bp = build_branch_filter(branch_id, table_alias="i")
    due_base_sql = document_amount_base_sql("(i.total - COALESCE(i.paid_amount, 0))", "i")
    base_currency = get_base_currency(db) or "SAR"
    aging = [
        {"bucket": "0-30", "bucket_ar": "0-30 يوم", "value": 0},
        {"bucket": "31-60", "bucket_ar": "31-60 يوم", "value": 0},
        {"bucket": "61-90", "bucket_ar": "61-90 يوم", "value": 0},
        {"bucket": "90+", "bucket_ar": "أكثر من 90 يوم", "value": 0},
    ]
    try:
        rows = db.execute(text(f"""
            SELECT
                CASE
                    WHEN (:today - i.due_date) <= 30 THEN '0-30'
                    WHEN (:today - i.due_date) <= 60 THEN '31-60'
                    WHEN (:today - i.due_date) <= 90 THEN '61-90'
                    ELSE '90+'
                END as bucket,
                COALESCE(SUM({due_base_sql}), 0)
            FROM invoices i
            WHERE i.invoice_type = 'sales' AND i.status IN ('sent', 'partially_paid') AND i.due_date IS NOT NULL {branch_sql}
            GROUP BY bucket
        """), {"today": as_of, "base_currency": base_currency, **bp}).fetchall()
        bucket_map = {r[0]: Decimal(str(r[1])) for r in rows}
        for a in aging:
            a["value"] = bucket_map.get(a["bucket"], 0)
    except Exception:
        pass
    return aging


def _build_ap_aging(db, as_of: date, branch_id: Optional[int] = None) -> list:
    """AP Aging buckets."""
    branch_sql, bp = build_branch_filter(branch_id, table_alias="i")
    due_base_sql = document_amount_base_sql("(i.total - COALESCE(i.paid_amount, 0))", "i")
    base_currency = get_base_currency(db) or "SAR"
    aging = [
        {"bucket": "0-30", "bucket_ar": "0-30 يوم", "value": 0},
        {"bucket": "31-60", "bucket_ar": "31-60 يوم", "value": 0},
        {"bucket": "61-90", "bucket_ar": "61-90 يوم", "value": 0},
        {"bucket": "90+", "bucket_ar": "أكثر من 90 يوم", "value": 0},
    ]
    try:
        rows = db.execute(text(f"""
            SELECT
                CASE
                    WHEN (:today - i.due_date) <= 30 THEN '0-30'
                    WHEN (:today - i.due_date) <= 60 THEN '31-60'
                    WHEN (:today - i.due_date) <= 90 THEN '61-90'
                    ELSE '90+'
                END as bucket,
                COALESCE(SUM({due_base_sql}), 0)
            FROM invoices i
            WHERE i.invoice_type IN ('purchase', 'purchase_debit_note')
              AND i.status NOT IN ('draft', 'cancelled', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
              AND i.due_date IS NOT NULL {branch_sql}
            GROUP BY bucket
        """), {"today": as_of, "base_currency": base_currency, **bp}).fetchall()
        bucket_map = {r[0]: Decimal(str(r[1] or 0)) for r in rows}
        for a in aging:
            a["value"] = bucket_map.get(a["bucket"], 0)
    except Exception:
        pass
    return aging


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Alert Builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_executive_alerts(db, branch_id: Optional[int] = None) -> list:
    """Build executive alerts from various sources."""
    alerts = []

    # Overdue invoices
    try:
        ov = db.execute(text("""
            SELECT COUNT(*) FROM invoices
            WHERE invoice_type = 'sales' AND status IN ('sent','partially_paid') AND due_date < CURRENT_DATE
        """)).scalar()
        if ov and int(ov) > 0:
            alerts.append({"severity": "high", "code": "OVERDUE_AR",
                            "message": i18n_message("kpi_overdue_invoices"),
                            "message_ar": f"{ov} فاتورة عميل متأخرة",
                            "count": int(ov), "link": "/sales/invoices?status=overdue"})
    except Exception:
        pass

    # Low stock
    try:
        ls = db.execute(text("""
            SELECT COUNT(DISTINCT p.id) FROM products p
            JOIN inventory i ON p.id = i.product_id
            WHERE i.quantity <= COALESCE(p.reorder_level, 0) AND p.is_active = true AND p.reorder_level > 0
        """)).scalar()
        if ls and int(ls) > 0:
            alerts.append({"severity": "medium", "code": "LOW_STOCK",
                            "message": i18n_message("kpi_low_stock_products"),
                            "message_ar": f"{ls} منتج تحت حد إعادة الطلب",
                            "count": int(ls), "link": "/stock/products?filter=low_stock"})
    except Exception:
        pass

    # Pending approvals
    try:
        pa = db.execute(text("""
            SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'
        """)).scalar()
        if pa and int(pa) > 0:
            alerts.append({"severity": "medium", "code": "PENDING_APPROVALS",
                            "message": i18n_message("kpi_pending_approvals"),
                            "message_ar": f"{pa} طلب اعتماد معلق",
                            "count": int(pa), "link": "/approvals"})
    except Exception:
        pass

    return alerts


def _build_financial_alerts(db, current_ratio: float, quick_ratio: float,
                             budget_variance: float, branch_id: Optional[int] = None) -> list:
    """Build financial alerts."""
    alerts = []
    if current_ratio > 0 and current_ratio < 1.0:
        alerts.append({"severity": "high", "code": "LOW_LIQUIDITY",
                        "message": i18n_message("kpi_current_ratio_low"),
                        "message_ar": f"نسبة التداول {current_ratio:.2f} — تحت 1.0 (خطر سيولة)",
                        "link": "/reports/balance-sheet"})
    if abs(budget_variance) > 15:
        alerts.append({"severity": "high", "code": "BUDGET_OVERRUN",
                        "message": i18n_message("kpi_budget_variance_high"),
                        "message_ar": f"انحراف الميزانية {budget_variance:+.1f}% — يتجاوز حد 15%",
                        "link": "/reports/budget-vs-actual"})
    return alerts
