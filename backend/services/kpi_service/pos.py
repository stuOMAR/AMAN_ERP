"""kpi_service.pos — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter, kpi_item
)
from utils.accounting import get_base_currency
from utils.currency_display import branch_amount_base_sql


def get_pos_kpis(db, start_date: date, end_date: date,
                 branch_id: Optional[int] = None) -> dict:
    """KPIs for Cashier / POS."""
    branch_sql, bp = build_branch_filter(branch_id, table_alias="o")
    base_currency = get_base_currency(db) or "SAR"
    order_total_base_sql = branch_amount_base_sql("o.total_amount", "o.branch_id")

    # Sales today
    today = date.today()
    sales_today = 0
    tx_count_today = 0
    try:
        pos_r = db.execute(text(f"""
            SELECT COALESCE(SUM({order_total_base_sql}), 0), COUNT(*)
            FROM pos_orders o
            WHERE DATE(o.order_date) = :today AND o.status = 'paid' {branch_sql}
        """), {"today": today, "base_currency": base_currency, **bp}).fetchone()
        if pos_r:
            sales_today = float(pos_r[0] or 0)
            tx_count_today = int(pos_r[1] or 0)
    except Exception:
        pass

    # Period sales
    period_sales = 0
    period_tx = 0
    try:
        ps = db.execute(text(f"""
            SELECT COALESCE(SUM({order_total_base_sql}), 0), COUNT(*)
            FROM pos_orders o
            WHERE o.order_date BETWEEN :s AND :e AND o.status = 'paid' {branch_sql}
        """), {"s": start_date, "e": end_date, "base_currency": base_currency, **bp}).fetchone()
        if ps:
            period_sales = float(ps[0] or 0)
            period_tx = int(ps[1] or 0)
    except Exception:
        pass

    # Average Basket Size
    avg_basket = period_sales / period_tx if period_tx > 0 else 0

    # Returns today
    returns_today = 0
    try:
        rt = db.execute(text(f"""
            SELECT COALESCE(SUM({order_total_base_sql}), 0) FROM pos_orders o
            WHERE DATE(o.order_date) = :today AND o.status = 'returned' {branch_sql}
        """), {"today": today, "base_currency": base_currency, **bp}).scalar()
        returns_today = float(rt or 0)
    except Exception:
        pass

    # Top Products Today
    top_products = []
    try:
        line_total_base_sql = branch_amount_base_sql("oi.total", "o.branch_id")
        rows = db.execute(text(f"""
            SELECT p.name, COALESCE(SUM(oi.quantity), 0) as qty, COALESCE(SUM({line_total_base_sql}), 0) as total
            FROM pos_order_lines oi
            JOIN pos_orders o ON oi.order_id = o.id
            JOIN products p ON oi.product_id = p.id
            WHERE DATE(o.order_date) = :today AND o.status = 'paid' {branch_sql}
            GROUP BY p.name ORDER BY total DESC LIMIT 5
        """), {"today": today, "base_currency": base_currency, **bp}).fetchall()
        top_products = [{"name": r[0], "quantity": int(r[1]), "value": Decimal(str(r[2]))} for r in rows]
    except Exception:
        pass

    # Cash vs Card split (from pos_payments table)
    cash_pct = 0
    card_pct = 0
    try:
        payment_amount_base_sql = branch_amount_base_sql("pp.amount", "o.branch_id")
        pm = db.execute(text(f"""
            SELECT pp.payment_method, COALESCE(SUM({payment_amount_base_sql}), 0)
            FROM pos_payments pp
            JOIN pos_orders o ON pp.order_id = o.id
            WHERE DATE(o.order_date) = :today AND o.status = 'paid' {branch_sql}
            GROUP BY pp.payment_method
        """), {"today": today, "base_currency": base_currency, **bp}).fetchall()
        total_pm = sum(float(r[1]) for r in pm) if pm else 0
        for r in pm:
            method = str(r[0]).lower()
            val = float(r[1])
            if 'cash' in method:
                cash_pct = (val / total_pm * 100) if total_pm > 0 else 0
            elif 'card' in method or 'visa' in method or 'mada' in method:
                card_pct = (val / total_pm * 100) if total_pm > 0 else 0
    except Exception:
        pass

    # Loyalty points
    loyalty_points = 0
    try:
        lp = db.execute(text("""
            SELECT COALESCE(SUM(points), 0) FROM pos_loyalty_transactions
            WHERE DATE(created_at) = :today AND txn_type = 'earn'
        """), {"today": today}).scalar()
        loyalty_points = int(lp or 0)
    except Exception:
        pass

    kpis = [
        kpi_item("sales_today", "Sales Today", "مبيعات اليوم", sales_today, base_currency),
        kpi_item("tx_count", "Transactions Today", "عدد العمليات اليوم", tx_count_today, ""),
        kpi_item("avg_basket", "Average Basket Size", "متوسط قيمة السلة", avg_basket, base_currency),
        kpi_item("returns_today", "Returns Today", "مرتجعات اليوم", returns_today, base_currency,
                 status="warning" if returns_today > 0 else "good"),
        kpi_item("cash_pct", "Cash %", "نسبة النقد", cash_pct, "%"),
        kpi_item("card_pct", "Card %", "نسبة البطاقات", card_pct, "%"),
        kpi_item("loyalty_points", "Loyalty Points Issued", "نقاط الولاء المصدرة", loyalty_points, "pts"),
    ]

    charts = [
        {"id": "top_products_today", "type": "bar", "title": "Top Products Today",
         "title_ar": "أعلى المنتجات اليوم", "data": top_products},
    ]

    alerts = []
    return {"role": "pos", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# CRM Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

