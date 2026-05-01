"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/inventory/valuation", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def inventory_valuation_report(
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقييم المخزون بالتكلفة المتوسطة"""
    db = get_db_connection(current_user.company_id)
    try:
        wh_filter = "AND i.warehouse_id = :wh" if warehouse_id else ""
        params = {}
        if warehouse_id:
            params["wh"] = warehouse_id

        rows = db.execute(text(f"""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as total_qty,
                   COALESCE(SUM(i.quantity), 0) * COALESCE(p.cost_price, 0) as total_value,
                   w.warehouse_name
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id {wh_filter}
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price, w.warehouse_name
            HAVING COALESCE(SUM(i.quantity), 0) != 0
            ORDER BY total_value DESC
        """), params).fetchall()

        items = []
        grand_total = Decimal("0")
        for r in rows:
            m = r._mapping
            val = Decimal(str(m["total_value"] or 0))
            grand_total += val
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "warehouse": m["warehouse_name"], "quantity": float(m["total_qty"]),
                "cost_price": Decimal(str(m["cost_price"] or 0)),
                "total_value": round(val, 2),
            })

        return {"report_name": "تقييم المخزون", "items": items, "grand_total": round(grand_total, 2)}
    finally:
        db.close()


@router.get("/inventory/turnover", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def inventory_turnover_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير دوران المخزون"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    days_in_period = max((e - s).days, 1)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as current_qty,
                   COALESCE(sold.qty, 0) as sold_qty
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN (
                SELECT il.product_id, SUM(ABS(il.quantity)) as qty
                FROM invoice_lines il
                JOIN invoices inv ON il.invoice_id = inv.id
                WHERE inv.invoice_type = 'sales' AND inv.status != 'cancelled'
                  AND inv.invoice_date BETWEEN :start AND :end
                GROUP BY il.product_id
            ) sold ON sold.product_id = p.id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price, sold.qty
            HAVING COALESCE(SUM(i.quantity), 0) > 0 OR COALESCE(sold.qty, 0) > 0
            ORDER BY sold.qty DESC NULLS LAST
        """), {"start": s, "end": e}).fetchall()

        items = []
        for r in rows:
            m = r._mapping
            avg_inv = float(m["current_qty"] or 0)
            sold = float(m["sold_qty"] or 0)
            cogs_val = sold * Decimal(str(m["cost_price"] or 0))
            turnover = cogs_val / (avg_inv * Decimal(str(m["cost_price"] or 1))) if avg_inv > 0 and m["cost_price"] else 0
            days_on_hand = round(days_in_period / turnover, 1) if turnover > 0 else None

            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "current_stock": avg_inv, "sold_qty": sold,
                "cogs_value": round(cogs_val, 2),
                "turnover_ratio": round(turnover, 2),
                "days_on_hand": days_on_hand,
            })

        return {"report_name": "دوران المخزون", "period": {"start": str(s), "end": str(e)}, "items": items}
    finally:
        db.close()


@router.get("/inventory/dead-stock", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def dead_stock_report(
    days_threshold: int = 90,
    current_user: dict = Depends(get_current_user)
):
    """المخزون الراكد — منتجات بدون حركة لفترة محددة"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as stock_qty,
                   COALESCE(SUM(i.quantity), 0) * COALESCE(p.cost_price, 0) as stock_value,
                   MAX(it.created_at) as last_movement
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN inventory_transactions it ON p.id = it.product_id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price
            HAVING COALESCE(SUM(i.quantity), 0) > 0
               AND (MAX(it.created_at) IS NULL OR MAX(it.created_at) < NOW() - :days * INTERVAL '1 day')
            ORDER BY stock_value DESC
        """), {"days": days_threshold}).fetchall()

        items = []
        total_val = Decimal("0")
        for r in rows:
            m = r._mapping
            val = Decimal(str(m["stock_value"] or 0))
            total_val += val
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "stock_qty": float(m["stock_qty"]),
                "cost_price": Decimal(str(m["cost_price"] or 0)),
                "stock_value": round(val, 2),
                "last_movement": str(m["last_movement"]) if m["last_movement"] else "لا توجد حركة",
            })

        return {
            "report_name": f"المخزون الراكد (>{days_threshold} يوم)",
            "days_threshold": days_threshold,
            "items": items,
            "total_dead_stock_value": round(total_val, 2),
            "count": len(items),
        }
    finally:
        db.close()


@router.get("/inventory/cogs", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def cogs_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة البضاعة المباعة"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   SUM(ABS(il.quantity)) as sold_qty,
                   SUM(ABS(il.quantity) * COALESCE(il.unit_cost, p.cost_price, 0)) as cogs_total,
                   SUM(il.quantity * il.unit_price) as revenue_total
            FROM invoice_lines il
            JOIN invoices inv ON il.invoice_id = inv.id
            JOIN products p ON il.product_id = p.id
            WHERE inv.invoice_type = 'sales' AND inv.status != 'cancelled'
              AND inv.invoice_date BETWEEN :start AND :end
            GROUP BY p.id, p.sku, p.product_name, p.cost_price
            ORDER BY cogs_total DESC
        """), {"start": s, "end": e}).fetchall()

        items = []
        total_cogs = Decimal("0")
        total_rev = Decimal("0")
        for r in rows:
            m = r._mapping
            cogs = Decimal(str(m["cogs_total"] or 0))
            rev = Decimal(str(m["revenue_total"] or 0))
            gross = rev - cogs
            margin = (gross / rev * 100) if rev > 0 else 0
            total_cogs += cogs
            total_rev += rev
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "sold_qty": float(m["sold_qty"] or 0),
                "unit_cost": Decimal(str(m["cost_price"] or 0)),
                "cogs": round(cogs, 2), "revenue": round(rev, 2),
                "gross_profit": round(gross, 2), "margin_pct": round(margin, 2),
            })

        return {
            "report_name": "تكلفة البضاعة المباعة",
            "period": {"start": str(s), "end": str(e)},
            "items": items,
            "totals": {"cogs": round(total_cogs, 2), "revenue": round(total_rev, 2),
                       "gross_profit": round(total_rev - total_cogs, 2)},
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales & Purchases Reports
# ═══════════════════════════════════════════════════════════

