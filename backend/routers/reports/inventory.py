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
_D2 = Decimal('0.01')


def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal('0')

@router.get("/inventory/valuation", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def inventory_valuation_report(
    warehouse_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقييم المخزون بالتكلفة وسعر البيع — T067: uses CostingService"""
    db = get_db_connection(current_user.company_id)
    try:
        from services.costing_service import CostingService
        from utils.permissions import validate_branch_access

        # T067: Validate branch access
        if warehouse_id:
            wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).scalar()
            if wh_branch:
                validate_branch_access(current_user, wh_branch)

        # T067: Use CostingService for valuation
        branch_ids = None
        if branch_id:
            branch_ids = [branch_id]
        elif hasattr(current_user, 'allowed_branches'):
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_ids = allowed

        valuation = CostingService.calculate_inventory_valuation(
            db,
            warehouse_id=warehouse_id,
            branch_id=branch_id,
            branch_ids=branch_ids,
        )

        # Get selling price data
        wh_filter = "AND i.warehouse_id = :wh" if warehouse_id else ""
        params = {}
        if warehouse_id:
            params["wh"] = warehouse_id

        rows = db.execute(text(f""" # noqa: sql-lint
            SELECT p.id, p.sku, p.product_name, p.selling_price,
                   COALESCE(SUM(i.quantity), 0) as total_qty,
                   w.warehouse_name
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id {wh_filter}
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.selling_price, w.warehouse_name
            HAVING COALESCE(SUM(i.quantity), 0) != 0
            ORDER BY p.product_name
        """), params).fetchall()

        # Build lookup from costing service
        cost_lookup = {}
        for item in valuation.get("items", []):
            cost_lookup[item["product_id"]] = item

        items = []
        grand_total_cost = Decimal("0")
        grand_total_sell = Decimal("0")
        for r in rows:
            m = r._mapping
            pid = m["id"]
            cost_data = cost_lookup.get(pid, {})
            cost_price = Decimal(str(cost_data.get("weighted_avg_cost", 0)))
            qty = Decimal(str(m["total_qty"]))
            val_cost = qty * cost_price
            val_sell = qty * Decimal(str(m["selling_price"] or 0))
            grand_total_cost += val_cost
            grand_total_sell += val_sell
            items.append({
                "product_id": pid, "sku": m["sku"], "product_name": m["product_name"],
                "warehouse": m["warehouse_name"], "quantity": float(qty),
                "cost_price": cost_price,
                "selling_price": Decimal(str(m["selling_price"] or 0)),
                "total_value_cost": round(val_cost, 2),
                "total_value_sell": round(val_sell, 2),
                "potential_profit": round(val_sell - val_cost, 2),
            })

        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        return {
            "report_name": "تقييم المخزون",
            "currency": base_cur,
            "items": items,
            "totals": {
                "cost_value": round(grand_total_cost, 2),
                "sell_value": round(grand_total_sell, 2),
                "potential_profit": round(grand_total_sell - grand_total_cost, 2),
            }
        }
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
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة البضاعة المباعة (مع تحويل العملات)"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        branch_rate = Decimal('1')
        if branch_id:
            branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
            if branch_cur != base_cur:
                rate_val = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": branch_cur}).scalar()
                if rate_val and rate_val > 0:
                    branch_rate = _dec(rate_val)
        else:
            branch_cur = base_cur

        params = {"start": s, "end": e}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND inv.branch_id = :branch_id"
            params["branch_id"] = branch_id

        rows = db.execute(text(f""" # noqa: sql-lint
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   SUM(ABS(il.quantity)) as sold_qty,
                   SUM(ABS(il.quantity) * COALESCE(il.unit_cost, p.cost_price, 0)) as cogs_total,
                   SUM(il.quantity * il.unit_price * COALESCE(inv.exchange_rate, 1)) as revenue_total
            FROM invoice_lines il
            JOIN invoices inv ON il.invoice_id = inv.id
            JOIN products p ON il.product_id = p.id
            WHERE inv.invoice_type = 'sales' AND inv.status != 'cancelled'
              AND inv.invoice_date BETWEEN :start AND :end
              {branch_filter}
            GROUP BY p.id, p.sku, p.product_name, p.cost_price
            ORDER BY cogs_total DESC
        """), params).fetchall()

        items = []
        total_cogs = Decimal("0")
        total_rev = Decimal("0")
        for r in rows:
            m = r._mapping
            cogs = Decimal(str(m["cogs_total"] or 0))
            rev = Decimal(str(m["revenue_total"] or 0))
            # Convert to display currency if needed
            if branch_rate != 1:
                cogs = (cogs / branch_rate).quantize(_D2)
                rev = (rev / branch_rate).quantize(_D2)
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
            "branch_id": branch_id,
            "currency": branch_cur,
            "items": items,
            "totals": {"cogs": round(total_cogs, 2), "revenue": round(total_rev, 2),
                       "gross_profit": round(total_rev - total_cogs, 2)},
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-106: Product Profitability Report (Frozen Cost)
# ═══════════════════════════════════════════════════════════

@router.get("/inventory/profitability", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def product_profitability_report(
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير ربحية المنتجات (باستخدام التكلفة المحفوظة وقت الفاتورة + تحويل العملات)"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        # Get base currency
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"

        params = {"start": s, "end": e}

        if branch_id:
            # Specific branch: show in branch's local currency
            branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
            branch_rate = Decimal('1')
            if branch_cur != base_cur:
                rate_val = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": branch_cur}).scalar()
                if rate_val and rate_val > 0:
                    branch_rate = _dec(rate_val)

            params["branch_id"] = branch_id
            rows = db.execute(text(f""" # noqa: sql-lint
                SELECT 
                    p.id as product_id,
                    p.product_name,
                    p.sku,
                    i.currency as inv_currency,
                    i.exchange_rate as inv_rate,
                    SUM(il.quantity) as sold_qty,
                    SUM(il.quantity * il.unit_price * COALESCE(i.exchange_rate, 1)) AS revenue_sar,
                    SUM(il.quantity * COALESCE(il.unit_cost, p.cost_price, 0)) AS cogs_sar
                FROM invoice_lines il
                JOIN products p ON p.id = il.product_id
                JOIN invoices i ON i.id = il.invoice_id
                WHERE i.invoice_type = 'sales'
                  AND i.status NOT IN ('cancelled', 'draft')
                  AND i.invoice_date BETWEEN :start AND :end
                  AND i.branch_id = :branch_id
                GROUP BY p.id, p.product_name, p.sku, i.currency, i.exchange_rate
                ORDER BY revenue_sar DESC
            """), params).fetchall()

            # Aggregate by product (may have mixed currencies within branch)
            product_data = {}
            for r in rows:
                pid = r.product_id
                if pid not in product_data:
                    product_data[pid] = {
                        "product_id": pid,
                        "product_name": r.product_name,
                        "sku": r.sku,
                        "sold_qty": Decimal('0'),
                        "revenue_sar": Decimal('0'),
                        "cogs_sar": Decimal('0'),
                    }
                product_data[pid]["sold_qty"] += _dec(r.sold_qty)
                product_data[pid]["revenue_sar"] += _dec(r.revenue_sar)
                product_data[pid]["cogs_sar"] += _dec(r.cogs_sar)

            # Convert to branch currency
            items = []
            total_revenue = Decimal('0')
            total_cogs = Decimal('0')
            total_profit = Decimal('0')

            for pid, d in product_data.items():
                rev = (d["revenue_sar"] / branch_rate).quantize(_D2) if branch_rate != 1 else d["revenue_sar"]
                cogs = (d["cogs_sar"] / branch_rate).quantize(_D2) if branch_rate != 1 else d["cogs_sar"]
                profit = rev - cogs
                margin = round((profit / rev * 100), 2) if rev > 0 else 0

                total_revenue += rev
                total_cogs += cogs
                total_profit += profit

                items.append({
                    "product_id": pid,
                    "product_name": d["product_name"],
                    "sku": d["sku"],
                    "sold_qty": float(d["sold_qty"]),
                    "revenue": float(rev),
                    "cogs": float(cogs),
                    "gross_profit": float(profit),
                    "margin_pct": margin,
                })

            display_currency = branch_cur

        else:
            # All branches: convert everything to base currency (SAR)
            rows = db.execute(text(f""" # noqa: sql-lint
                SELECT 
                    p.id as product_id,
                    p.product_name,
                    p.sku,
                    SUM(il.quantity) as sold_qty,
                    SUM(il.quantity * il.unit_price * COALESCE(i.exchange_rate, 1)) AS revenue_sar,
                    SUM(il.quantity * COALESCE(il.unit_cost, p.cost_price, 0)) AS cogs_sar
                FROM invoice_lines il
                JOIN products p ON p.id = il.product_id
                JOIN invoices i ON i.id = il.invoice_id
                WHERE i.invoice_type = 'sales'
                  AND i.status NOT IN ('cancelled', 'draft')
                  AND i.invoice_date BETWEEN :start AND :end
                GROUP BY p.id, p.product_name, p.sku
                ORDER BY revenue_sar DESC
            """), params).fetchall()

            items = []
            total_revenue = Decimal('0')
            total_cogs = Decimal('0')
            total_profit = Decimal('0')

            for r in rows:
                rev = _dec(r.revenue_sar)
                cogs = _dec(r.cogs_sar)
                profit = rev - cogs
                margin = round((profit / rev * 100), 2) if rev > 0 else 0

                total_revenue += rev
                total_cogs += cogs
                total_profit += profit

                items.append({
                    "product_id": r.product_id,
                    "product_name": r.product_name,
                    "sku": r.sku,
                    "sold_qty": float(r.sold_qty or 0),
                    "revenue": float(rev),
                    "cogs": float(cogs),
                    "gross_profit": float(profit),
                    "margin_pct": margin,
                })

            display_currency = base_cur

        overall_margin = round((total_profit / total_revenue * 100), 2) if total_revenue > 0 else 0

        # Sort by gross_profit descending
        items.sort(key=lambda x: x["gross_profit"], reverse=True)

        return {
            "report_name": "تقرير ربحية المنتجات",
            "report_name_en": "Product Profitability Report",
            "period": {"start": str(s), "end": str(e)},
            "branch_id": branch_id,
            "currency": display_currency,
            "items": items,
            "totals": {
                "revenue": float(total_revenue),
                "cogs": float(total_cogs),
                "gross_profit": float(total_profit),
                "margin_pct": overall_margin,
            }
        }
    finally:
        db.close()


@router.get("/inventory/profitability/summary", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))], response_model=Dict[str, Any])
def profitability_summary(
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص الربحية الإجمالي (مع تحويل العملات)"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        params = {"start": s, "end": e}

        if branch_id:
            branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
            branch_rate = Decimal('1')
            if branch_cur != base_cur:
                rate_val = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": branch_cur}).scalar()
                if rate_val and rate_val > 0:
                    branch_rate = _dec(rate_val)
            params["branch_id"] = branch_id
        else:
            branch_cur = base_cur
            branch_rate = Decimal('1')

        result = db.execute(text(f""" # noqa: sql-lint
            SELECT 
                COUNT(DISTINCT i.id) as invoice_count,
                SUM(il.quantity) as total_qty,
                SUM(il.quantity * il.unit_price * COALESCE(i.exchange_rate, 1)) AS total_revenue_sar,
                SUM(il.quantity * COALESCE(il.unit_cost, p.cost_price, 0)) AS total_cogs_sar
            FROM invoice_lines il
            JOIN products p ON p.id = il.product_id
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.invoice_type = 'sales'
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              {"AND i.branch_id = :branch_id" if branch_id else ""}
        """), params).fetchone()

        revenue = _dec(result.total_revenue_sar or 0)
        cogs = _dec(result.total_cogs_sar or 0)

        # Convert to display currency
        if branch_rate != 1:
            revenue = (revenue / branch_rate).quantize(_D2)
            cogs = (cogs / branch_rate).quantize(_D2)

        profit = revenue - cogs
        margin = round((profit / revenue * 100), 2) if revenue > 0 else 0

        return {
            "period": {"start": str(s), "end": str(e)},
            "branch_id": branch_id,
            "currency": branch_cur,
            "invoice_count": result.invoice_count or 0,
            "total_qty": float(result.total_qty or 0),
            "total_revenue": float(revenue),
            "total_cogs": float(cogs),
            "gross_profit": float(profit),
            "margin_pct": margin,
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales & Purchases Reports
# ═══════════════════════════════════════════════════════════

