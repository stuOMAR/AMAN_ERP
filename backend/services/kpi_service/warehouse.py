"""kpi_service.warehouse — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter, kpi_item, ratio_status, _count_table
)
from utils.accounting import get_base_currency


def get_warehouse_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """KPIs for Inventory / Warehouse Manager."""
    base_currency = get_base_currency(db) or "SAR"

    # Inventory Valuation at Cost (always in base currency)
    # T068: NOTE: Uses products.cost_price for fast approximate KPI.
    # For financial valuation, use CostingService.calculate_inventory_valuation
    # which reads from cost_layers for FIFO/LIFO accuracy.
    inv_valuation_cost = 0
    try:
        wh_branch_sql, wh_bp = build_branch_filter(branch_id, table_alias="w")
        iv = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT COALESCE(SUM(i.quantity * COALESCE(p.cost_price, 0)), 0)
            FROM inventory i JOIN products p ON i.product_id = p.id
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
            WHERE 1=1 {wh_branch_sql}
        """), wh_bp).scalar()
        inv_valuation_cost = float(iv or 0)
    except Exception:
        pass

    # Inventory Valuation at Selling Price (always in base currency)
    inv_valuation_sell = 0
    try:
        iv_sell = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT COALESCE(SUM(i.quantity * COALESCE(p.selling_price, 0)), 0)
            FROM inventory i JOIN products p ON i.product_id = p.id
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
            WHERE 1=1 {wh_branch_sql}
        """), wh_bp).scalar()
        inv_valuation_sell = float(iv_sell or 0)
    except Exception:
        pass

    # Potential Profit (always in base currency)
    potential_profit = inv_valuation_sell - inv_valuation_cost

    # Stock Turnover = COGS / Avg Inventory Value
    cogs = 0
    try:
        cogs_branch_sql, cogs_bp = build_branch_filter(branch_id)
        cogs_r = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND a.account_code LIKE '5%'
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
              {cogs_branch_sql}
        """), {"s": start_date, "e": end_date, **cogs_bp}).scalar()
        cogs = float(cogs_r or 0)
    except Exception:
        pass

    stock_turnover = cogs / inv_valuation_cost if inv_valuation_cost > 0 else 0
    dio = 365 / stock_turnover if stock_turnover > 0 else 0

    # Total SKUs & Active
    total_products = _count_table(db, "products")
    active_products = _count_table(db, "products", extra_where="is_active = true")

    # Low Stock Count — P1 #99: available = quantity - reserved_quantity
    low_stock = 0
    try:
        ls = db.execute(text("""
            SELECT COUNT(DISTINCT p.id)
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            WHERE (i.quantity - COALESCE(i.reserved_quantity, 0)) <= COALESCE(p.reorder_level, 0)
              AND p.is_active = true AND p.reorder_level > 0
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
        kpi_item("inv_valuation_cost", "Inventory at Cost", "قيمة المخزون بالتكلفة", inv_valuation_cost, base_currency),
        kpi_item("inv_valuation_sell", "Inventory at Selling Price", "قيمة المخزون بسعر البيع", inv_valuation_sell, base_currency),
        kpi_item("potential_profit", "Potential Profit", "الربح المحتمل", potential_profit, base_currency,
                 status="good" if potential_profit > 0 else "warning"),
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
                        "message": i18n_message("kpi_low_stock_products"),
                        "message_ar": f"{low_stock} منتج تحت حد إعادة الطلب",
                        "count": low_stock, "link": "/stock/products?filter=low_stock"})
    if out_of_stock > 0:
        alerts.append({"severity": "high", "code": "OUT_OF_STOCK",
                        "message": i18n_message("kpi_out_of_stock_products"),
                        "message_ar": f"{out_of_stock} منتج نفد من المخزون",
                        "count": out_of_stock, "link": "/stock/products?filter=out_of_stock"})

    return {"role": "warehouse", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# HR Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

