"""kpi_service.warehouse — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    kpi_item, ratio_status, _count_table
)


def get_warehouse_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """KPIs for Inventory / Warehouse Manager."""

    # Inventory Valuation
    inv_valuation = 0
    try:
        iv = db.execute(text("""
            SELECT COALESCE(SUM(i.quantity * COALESCE(p.cost_price, 0)), 0)
            FROM inventory i JOIN products p ON i.product_id = p.id
        """)).scalar()
        inv_valuation = float(iv or 0)
    except Exception:
        pass

    # Stock Turnover = COGS / Avg Inventory Value
    cogs = 0
    try:
        cogs_r = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND a.account_code LIKE '5%'
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        cogs = float(cogs_r or 0)
    except Exception:
        pass

    stock_turnover = cogs / inv_valuation if inv_valuation > 0 else 0
    dio = 365 / stock_turnover if stock_turnover > 0 else 0

    # Total SKUs & Active
    total_products = _count_table(db, "products")
    active_products = _count_table(db, "products", extra_where="is_active = true")

    # Low Stock Count
    low_stock = 0
    try:
        ls = db.execute(text("""
            SELECT COUNT(DISTINCT p.id)
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            WHERE i.quantity <= COALESCE(p.reorder_level, 0) AND p.is_active = true AND p.reorder_level > 0
        """)).scalar()
        low_stock = int(ls or 0)
    except Exception:
        pass

    # Slow-Moving Items (no movement in 90+ days)
    slow_moving = 0
    try:
        sm = db.execute(text("""
            SELECT COUNT(DISTINCT p.id)
            FROM products p
            LEFT JOIN (
                SELECT DISTINCT product_id FROM inventory_transactions
                WHERE created_at >= CURRENT_DATE - INTERVAL '90 days'
            ) recent ON p.id = recent.product_id
            WHERE recent.product_id IS NULL AND p.is_active = true
        """)).scalar()
        slow_moving = int(sm or 0)
    except Exception:
        pass

    slow_moving_pct = (slow_moving / active_products * 100) if active_products > 0 else 0

    # Out of Stock
    out_of_stock = 0
    try:
        oos = db.execute(text("""
            SELECT COUNT(DISTINCT p.id) FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            WHERE p.is_active = true AND (i.quantity IS NULL OR i.quantity <= 0)
              AND p.product_type != 'service'
        """)).scalar()
        out_of_stock = int(oos or 0)
    except Exception:
        pass

    kpis = [
        kpi_item("inv_valuation", "Inventory Valuation", "تقييم المخزون", inv_valuation, "SAR"),
        kpi_item("stock_turnover", "Stock Turnover", "معدل دوران المخزون", stock_turnover, "x",
                 benchmark=6.0, benchmark_source="IAS 2",
                 status=ratio_status(stock_turnover, 6, 3)),
        kpi_item("dio", "Days Inventory Outstanding", "أيام دوران المخزون", dio, "days",
                 benchmark=60, benchmark_source="IAS 2",
                 status=ratio_status(dio, 60, 120, higher_is_better=False)),
        kpi_item("active_products", "Active Products", "المنتجات النشطة", active_products, ""),
        kpi_item("low_stock", "Low Stock Items", "منتجات تحت حد الطلب", low_stock, "",
                 status="danger" if low_stock > 0 else "good"),
        kpi_item("slow_moving_pct", "Slow-Moving Items", "المنتجات بطيئة الحركة", slow_moving_pct, "%",
                 benchmark=10, benchmark_source="Best Practice",
                 status=ratio_status(slow_moving_pct, 10, 25, higher_is_better=False)),
        kpi_item("out_of_stock", "Out of Stock", "منتجات نفدت", out_of_stock, "",
                 status="danger" if out_of_stock > 0 else "good"),
    ]

    charts = []
    alerts = []
    if low_stock > 0:
        alerts.append({"severity": "high", "code": "LOW_STOCK",
                        "message": f"{low_stock} products below reorder level",
                        "message_ar": f"{low_stock} منتج تحت حد إعادة الطلب",
                        "count": low_stock, "link": "/stock/products?filter=low_stock"})
    if out_of_stock > 0:
        alerts.append({"severity": "high", "code": "OUT_OF_STOCK",
                        "message": f"{out_of_stock} products out of stock",
                        "message_ar": f"{out_of_stock} منتج نفد من المخزون",
                        "count": out_of_stock, "link": "/stock/products?filter=out_of_stock"})

    return {"role": "warehouse", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# HR Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

