from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation
import json
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, check_permission, resolve_branch_scope, branch_scope_filter_from_scope
from utils.cache import cached
from utils.accounting import get_base_currency
from utils.currency_display import branch_amount_base_sql, document_amount_base_sql
from services.sales_service import get_sales_total, get_gl_profit_breakdown
import time

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger(__name__)

# Cache for system stats to avoid slowness
_system_stats_cache = {
    "data": None,
    "last_updated": 0
}
CACHE_DURATION = 600 # 10 minutes for system-wide stats


def _cash_status(cash, monthly_expenses) -> str:
    """T10.2 #114 — burn-rate aware cash status.

    Returns:
      ``Critical``   if cash <= 0
      ``Low``        if cash < 1× monthly_expenses (under one month runway)
      ``Adequate``   if cash < 3× monthly_expenses
      ``Healthy``    otherwise
    """
    try:
        cash = Decimal(str(cash or 0))
        monthly_expenses = Decimal(str(monthly_expenses or 0))
    except (TypeError, ValueError, InvalidOperation):
        return "Unknown"
    if cash <= 0:
        return "Critical"
    if monthly_expenses <= 0:
        return "Healthy"
    if cash < monthly_expenses:
        return "Low"
    if cash < monthly_expenses * 3:
        return "Adequate"
    return "Healthy"


def _dashboard_display_currency(db, branch_scope: dict) -> dict:
    """Resolve the currency for branch-scoped dashboard values.

    Aggregated dashboard numbers are computed in company base currency. For a
    single-currency branch scope, convert those base amounts to that branch
    currency. For mixed-currency scopes, keep base currency.
    """
    base_currency = (get_base_currency(db) or "SAR").upper()

    branch_id = branch_scope.get("branch_id") if branch_scope else None
    branch_ids = branch_scope.get("branch_ids") if branch_scope else None

    currencies = []
    if branch_id:
        row = db.execute(text("SELECT default_currency FROM branches WHERE id = :id"), {"id": branch_id}).fetchone()
        if row and row.default_currency:
            currencies = [str(row.default_currency).upper()]
    elif branch_ids is not None:
        if branch_ids:
            rows = db.execute(
                text("SELECT DISTINCT COALESCE(default_currency, :base) AS currency FROM branches WHERE id = ANY(:ids)"),
                {"ids": branch_ids, "base": base_currency},
            ).fetchall()
            currencies = [str(row.currency).upper() for row in rows if row.currency]
    else:
        rows = db.execute(
            text("SELECT DISTINCT COALESCE(default_currency, :base) AS currency FROM branches WHERE is_active = TRUE"),
            {"base": base_currency},
        ).fetchall()
        currencies = [str(row.currency).upper() for row in rows if row.currency]

    unique = sorted(set(currencies))
    display_currency = unique[0] if len(unique) == 1 else base_currency
    if len(unique) > 1:
        default_filter = ""
        params = {"base": base_currency}
        if branch_ids is not None:
            if branch_ids:
                default_filter = "AND id = ANY(:ids)"
                params["ids"] = branch_ids
            else:
                default_filter = "AND 1=0"
        row = db.execute(text(f"""
            SELECT COALESCE(default_currency, :base) AS currency
            FROM branches
            WHERE is_active = TRUE {default_filter}
            ORDER BY is_default DESC, id ASC
            LIMIT 1
        """), params).fetchone()
        if row and row.currency:
            display_currency = str(row.currency).upper()
    rate = Decimal("1")
    if display_currency != base_currency:
        rate_row = db.execute(
            text("SELECT NULLIF(current_rate, 0) AS rate FROM currencies WHERE code = :code LIMIT 1"),
            {"code": display_currency},
        ).fetchone()
        try:
            rate = Decimal(str(rate_row.rate if rate_row and rate_row.rate else 1))
        except (InvalidOperation, TypeError, ValueError):
            rate = Decimal("1")
        if rate <= 0:
            rate = Decimal("1")

    return {
        "currency": display_currency,
        "base_currency": base_currency,
        "rate": rate,
        "is_multi_currency_scope": len(unique) > 1,
    }


def _base_to_display_amount(value, display_meta: dict) -> float:
    amount = Decimal(str(value or 0))
    rate = display_meta.get("rate") or Decimal("1")
    if display_meta.get("currency") != display_meta.get("base_currency") and rate:
        amount = amount / rate
    return float(amount)


def _convert_stats_from_base(stats: dict, display_meta: dict) -> dict:
    converted = dict(stats)
    for key in ("sales", "cogs", "expenses", "profit", "cash"):
        converted[key] = _base_to_display_amount(converted.get(key), display_meta)
    return converted


def get_user_company_id(user):
    cid = getattr(user, "company_id", None)
    if cid is None and isinstance(user, dict):
        cid = user.get("company_id")
    if not cid:
            raise HTTPException(**http_error(400, "company_id_missing"))
    return cid

@router.get("/stats", response_model=Dict[str, Any], dependencies=[Depends(require_permission("dashboard.view"))])
@cached("dashboard_stats", expire=60)
def get_dashboard_stats(
    branch_id: int = None,
    current_user: dict = Depends(get_current_user)
):
    """احصائيات رئيسية للوحة التحكم مع مقارنة بالفترة السابقة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    
    db = get_db_connection(get_user_company_id(current_user))
    try:
        # Dates
        today = date.today()
        this_month_start = today.replace(day=1)
        prev_month_end = this_month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        
        # Shared filters
        params_cash = {}
        warehouse_branch_filter = branch_scope_filter_from_scope(branch_scope, "w.branch_id", params_cash)

        def calculate_period_stats(start_dt, end_dt=None):
            """Calculate sales/profit/cash for the period.

            Sales come from the unified `get_sales_total` source (invoices +
            POS, base currency, gross including tax) so Dashboard matches
            the Reports page. COGS, opex and net profit come from posted
            GL entries via `get_gl_profit_breakdown`.
            """
            # Unified gross sales (T3.1)
            sales_data = get_sales_total(
                db,
                start_date=start_dt,
                end_date=end_dt,
                branch_id=branch_scope["branch_id"],
                branch_ids=branch_scope["branch_ids"],
            )
            total_sales = float(sales_data["total_sales"])

            # GL-based profit breakdown
            gl = get_gl_profit_breakdown(
                db,
                start_date=start_dt,
                end_date=end_dt,
                branch_id=branch_scope["branch_id"],
                branch_ids=branch_scope["branch_ids"],
            )
            total_expenses = float(gl["operating_expenses"])
            cogs = float(gl["cogs"])
            net_profit = float(gl["net_profit"])

            # Cash balance follows treasury ownership. A branch-owned bank/cash
            # account belongs to its treasury branch even if an old JE line was
            # posted with a different journal branch.
            date_filter_je = ""
            params_gl: dict = {}
            branch_filter_treasury = branch_scope_filter_from_scope(branch_scope, "ta.branch_id", params_gl)
            if start_dt:
                date_filter_je += " AND je.entry_date >= :start_dt"
                params_gl["start_dt"] = start_dt
            if end_dt:
                date_filter_je += " AND je.entry_date <= :end_dt"
                params_gl["end_dt"] = end_dt

            if start_dt or end_dt:
                cash_balance = db.execute(text(f"""
                    SELECT COALESCE(SUM(COALESCE(jl.debit, 0) - COALESCE(jl.credit, 0)), 0)
                    FROM treasury_accounts ta
                    JOIN journal_lines jl ON jl.account_id = ta.gl_account_id
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    WHERE ta.is_active = TRUE
                      AND ta.gl_account_id IS NOT NULL
                      AND je.status = 'posted'
                      {branch_filter_treasury} {date_filter_je}
                """), params_gl).scalar() or 0
            else:
                cash_balance = db.execute(text(f"""
                    SELECT COALESCE(SUM(COALESCE(a.balance, 0)), 0)
                    FROM treasury_accounts ta
                    JOIN accounts a ON a.id = ta.gl_account_id
                    WHERE ta.is_active = TRUE
                      AND ta.gl_account_id IS NOT NULL
                      {branch_filter_treasury}
                """), params_gl).scalar() or 0

            return {
                "sales": total_sales,
                "cogs": cogs,
                "expenses": total_expenses,
                "profit": net_profit,
                "cash": float(cash_balance),
            }

        # Calculate cumulative stats (matching accounting summary - all-time balances)
        cumulative = calculate_period_stats(None)
        # Calculate current and previous period stats for trend comparison only
        current = calculate_period_stats(this_month_start)
        previous = calculate_period_stats(prev_month_start, prev_month_end)
        display_meta = _dashboard_display_currency(db, branch_scope)
        cumulative = _convert_stats_from_base(cumulative, display_meta)
        current = _convert_stats_from_base(current, display_meta)
        previous = _convert_stats_from_base(previous, display_meta)
        
        # Trends
        # T10.2 #115: previously hard-clamped at ±999% so the dashboard
        # silently hid catastrophic moves. We now keep ``change`` as the
        # display-friendly clamp AND emit ``change_unbounded`` as the
        # raw value so power users / alerts can detect outliers.
        def calc_change(curr, prev):
            if prev == 0:
                return 0 if curr == 0 else 100
            pct = ((curr - prev) / abs(prev)) * 100
            return round(pct, 1)

        def calc_change_clamped(curr, prev):
            pct = calc_change(curr, prev)
            return max(-999.0, min(999.0, pct))

        # T10.2 #112 — a duplicate cash query lived here that summed
        # ``a.balance`` directly from ``treasury_accounts JOIN accounts``.
        # Its result was never used (the response below returns
        # ``cumulative["cash"]``) and produced a different number than
        # the GL-linked snapshot. Removed; the GL-linked value is the
        # single source of truth.

        # Low Stock — P1 #99: available stock = on-hand minus reserved.
        # Reservations (sales orders, transfers, manufacturing) are not
        # truly available, so they must be subtracted before comparing
        # to the reorder level.
        low_stock_query = f"""
            SELECT COUNT(*) FROM (
                SELECT p.id
                FROM products p
                LEFT JOIN (
                    SELECT product_id,
                           SUM(quantity) as total_qty,
                           SUM(COALESCE(reserved_quantity, 0)) as reserved
                    FROM inventory inv
                    {"JOIN warehouses w ON inv.warehouse_id = w.id" if warehouse_branch_filter else ""}
                    {warehouse_branch_filter.replace('AND', 'WHERE', 1) if warehouse_branch_filter else ""}
                    GROUP BY product_id
                                ) inv_sum ON p.id = inv_sum.product_id
                                WHERE p.reorder_level > 0
                                    AND (COALESCE(inv_sum.total_qty, 0) - COALESCE(inv_sum.reserved, 0) <= p.reorder_level)
            ) as low_stock_items
        """
        low_stock = db.execute(text(low_stock_query), params_cash).scalar() or 0

        # Reserved Stock
        reserved_stock_query = f"""
            SELECT p.product_name, SUM(inv.reserved_quantity) as reserved_qty
            FROM inventory inv
            JOIN products p ON inv.product_id = p.id
            {"JOIN warehouses w ON inv.warehouse_id = w.id" if warehouse_branch_filter else ""}
            WHERE inv.reserved_quantity > 0
            {warehouse_branch_filter}
            GROUP BY p.product_name
        """
        reserved_stock_data = db.execute(text(reserved_stock_query), params_cash).fetchall()
        reserved_stock_list = [{"product": row.product_name, "quantity": int(row.reserved_qty)} for row in reserved_stock_data]

        return {
            "display_currency": display_meta["currency"],
            "base_currency": display_meta["base_currency"],
            "is_multi_currency_scope": display_meta["is_multi_currency_scope"],
            "sales": cumulative["sales"],
            "sales_change": calc_change_clamped(current["sales"], previous["sales"]),
            "sales_change_unbounded": calc_change(current["sales"], previous["sales"]),
            "expenses": cumulative["expenses"],
            "expenses_change": calc_change_clamped(current["expenses"], previous["expenses"]),
            "expenses_change_unbounded": calc_change(current["expenses"], previous["expenses"]),
            "cogs": cumulative.get("cogs", 0),
            "profit": cumulative["profit"],
            "net_profit": cumulative["profit"],
            "profit_change": calc_change_clamped(current["profit"], previous["profit"]),
            "profit_change_unbounded": calc_change(current["profit"], previous["profit"]),
            "cash": cumulative["cash"],
            "cash_change": calc_change_clamped(current["cash"], previous["cash"]),
            # T10.2 #114: cash_status now reflects burn-rate, not just
            # "any positive balance". Compares the cash balance against
            # the most recent month's expenses to detect impending
            # shortfalls (less than one month of runway = ``Low``).
            "cash_status": _cash_status(cumulative["cash"], current["expenses"]),
            "low_stock": int(low_stock),
            "reserved_stock": reserved_stock_list
        }
    except Exception:
        logger.exception("Dashboard calculation error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/charts/financial", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission("dashboard.view"))])
@cached("dashboard_charts_financial", expire=60)
def get_financial_chart(
    days: int = 30,
    branch_id: int = None,
    current_user: dict = Depends(get_current_user)
):
    """الرسم البياني المالي (مبيعات vs مصروفات)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(get_user_company_id(current_user)) as db:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        branch_cond_inv = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
        branch_cond_exp = branch_scope_filter_from_scope(branch_scope, "ta.branch_id", params)
        display_meta = _dashboard_display_currency(db, branch_scope)

        # Fetch Sales by Date
        sales_data = db.execute(text(f"""
            WITH all_sales AS (
                SELECT invoice_date as sale_date, COALESCE(total * exchange_rate, 0) as total, branch_id
                FROM invoices
                WHERE invoice_type = 'sales' AND invoice_date >= :start AND status != 'cancelled'
                
                UNION ALL
                
                SELECT CAST(order_date AS DATE) as sale_date, COALESCE(total_amount, 0) as total, branch_id
                FROM pos_orders
                WHERE order_date >= :start AND status = 'paid'
            )
            SELECT sale_date, SUM(total) as total
            FROM all_sales
            WHERE 1=1
            {branch_cond_inv}
            GROUP BY sale_date
        """), params).fetchall()
        sales_map = {}
        for row in sales_data:
            d = row.sale_date
            if isinstance(d, datetime): d = d.date()
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            sales_map[key] = float(row.total)

        # Fetch Expenses by Date
        expenses_data = db.execute(text(f"""
            SELECT t.transaction_date, COALESCE(SUM(t.amount), 0) as total
            FROM treasury_transactions t
            JOIN treasury_accounts ta ON t.treasury_id = ta.id
            WHERE t.transaction_type = 'expense' AND t.transaction_date >= :start
            {branch_cond_exp}
            GROUP BY t.transaction_date
        """), params).fetchall()
        expenses_map = {}
        for row in expenses_data:
            d = row.transaction_date
            if isinstance(d, datetime): d = d.date()
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            expenses_map[key] = float(row.total)

        # Merge
        result = []
        for i in range(days + 1):
            day = start_date + timedelta(days=i)
            day_key = day.isoformat()
            s = sales_map.get(day_key, 0)
            e = expenses_map.get(day_key, 0)
            # T10.2 #111: the daily series cannot compute true net profit
            # (no daily COGS). Expose it as ``daily_pl`` (revenue minus
            # expenses) instead of the misleading ``profit`` label and
            # keep ``profit`` as a deprecated alias for client compat.
            daily_pl = s - e
            result.append({
                "date": day.isoformat(),
                "sales": _base_to_display_amount(s, display_meta),
                "expenses": _base_to_display_amount(e, display_meta),
                "daily_pl": _base_to_display_amount(daily_pl, display_meta),
                "profit": _base_to_display_amount(daily_pl, display_meta),  # deprecated alias — do not use; see daily_pl
                "display_currency": display_meta["currency"],
                "base_currency": display_meta["base_currency"],
            })
            
        return result

@router.get("/charts/products", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission("dashboard.view"))])
def get_top_products(
    limit: int = 5,
    branch_id: int = None,
    current_user: dict = Depends(get_current_user)
):
    """أكثر المنتجات مبيعاً"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(get_user_company_id(current_user)) as db:
        params = {"limit": limit}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "val.branch_id", params)

        result = db.execute(text(f"""
            WITH all_items AS (
                SELECT 
                    il.product_id,
                    il.total * i.exchange_rate as value,
                    i.branch_id
                FROM invoice_lines il
                JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
                
                UNION ALL
                
                SELECT 
                    pi.product_id,
                    pi.total as value,
                    po.branch_id
                FROM pos_order_lines pi
                JOIN pos_orders po ON pi.order_id = po.id
                WHERE po.status = 'paid'
            )
            SELECT 
                p.product_name as name,
                COALESCE(SUM(val.value), 0) as value
            FROM all_items val
            JOIN products p ON val.product_id = p.id
            WHERE 1=1
            {branch_filter}
            GROUP BY p.id, p.product_name
            ORDER BY value DESC
            LIMIT :limit
        """), params).fetchall()


        return [{"name": row.name, "value": float(row.value)} for row in result]
@router.get("/system-stats", response_model=Dict[str, Any])
def get_system_stats(
    current_user: dict = Depends(get_current_user)
):
    """احصائيات النظام (للمدير العام فقط)"""
    # Verify System Admin Role
    if current_user.role != 'system_admin':
            raise HTTPException(**http_error(403, "access_denied_system_admin_only"))
    
    # Return immediately from cache
    if _system_stats_cache["data"]:
        return _system_stats_cache["data"]
    
    # If cache empty (initial boot), return zeroed status instead of hanging
    return {
        "total_companies": 0,
        "total_users": 0,
        "active_users": 0,
        "system_status": "Starting..."
    }

async def update_system_stats_task():
    """المهمة الخلفية لتحديث إحصائيات النظام بشكل دوري"""
    from database import engine
    from config import settings
    from sqlalchemy import create_engine
    import asyncio
    
    logger.info("📡 System Stats Worker Started")
    
    while True:
        try:
            # 1. Total Companies
            with engine.connect() as db:
                companies_res = db.execute(text("SELECT id FROM system_companies WHERE status = 'active'")).fetchall()
                total_companies = len(companies_res)
                
                # Active Users (last 24 hours from GLOBAL activity log)
                active_users_res = db.execute(text("""
                    SELECT COUNT(DISTINCT performed_by) 
                    FROM system_activity_log 
                    WHERE created_at >= (CURRENT_TIMESTAMP - INTERVAL '24 hours')
                """)).scalar() or 0

            # 2. Total Registered Users (Aggregated across all company DBs)
            total_users = 0
            # Use small batch sizes to be nice to the DB and prevent connection saturation
            for (cid,) in companies_res:
                 company_engine = None
                 try:
                     db_url = settings.get_company_database_url(cid)
                     company_engine = create_engine(db_url, pool_pre_ping=True)
                     with company_engine.connect() as company_conn:
                          count = company_conn.execute(text("SELECT COUNT(*) FROM company_users")).scalar() or 0
                          total_users += count
                 except Exception:
                      pass
                 finally:
                      if company_engine:
                          company_engine.dispose()
                 
                 # Micro-sleep between companies to prevent CPU/Connection spikes
                 await asyncio.sleep(0.01)

            stats = {
                "total_companies": total_companies,
                "total_users": total_users,
                "active_users": active_users_res,
                "system_status": "Healthy"
            }
            
            # Update cache
            _system_stats_cache["data"] = stats
            _system_stats_cache["last_updated"] = time.time()
            
            logger.info(f"📊 System Stats UPDATED: Companies={total_companies}, Users={total_users}")
            
        except Exception as e:
            logger.error(f"❌ System stats worker error: {str(e)}")
        
        # Wait 15 minutes before next update
        await asyncio.sleep(900) 


# ===================== DASH-001: Customizable Dashboard Layouts =====================

class WidgetConfig(BaseModel):
    id: str  # Unique widget ID (e.g., "sales_today", "low_stock")
    type: str  # Widget type: "stat", "chart", "list", "table"
    title: str  # Display title
    x: int = 0  # Grid column position
    y: int = 0  # Grid row position
    w: int = 1  # Width (grid cols)
    h: int = 1  # Height (grid rows)
    config: Optional[Dict[str, Any]] = {}  # Widget-specific config (period, limit, etc.)

class LayoutCreate(BaseModel):
    layout_name: str = "default"
    widgets: List[WidgetConfig] = []

class LayoutUpdate(BaseModel):
    widgets: List[WidgetConfig]


# Default widgets for new users
DEFAULT_WIDGETS = [
    {"id": "sales_today", "type": "stat", "title": "dashboard_sales_today", "x": 0, "y": 0, "w": 1, "h": 1, "config": {"period": "today"}},
    {"id": "sales_month", "type": "stat", "title": "dashboard_sales_month", "x": 1, "y": 0, "w": 1, "h": 1, "config": {"period": "month"}},
    {"id": "expenses_month", "type": "stat", "title": "dashboard_expenses_month", "x": 2, "y": 0, "w": 1, "h": 1, "config": {"period": "month"}},
    {"id": "cash_balance", "type": "stat", "title": "dashboard_cash_balance", "x": 3, "y": 0, "w": 1, "h": 1, "config": {}},
    {"id": "financial_chart", "type": "chart", "title": "dashboard_financial_chart", "x": 0, "y": 1, "w": 2, "h": 2, "config": {"days": 30}},
    {"id": "top_products", "type": "chart", "title": "dashboard_top_products", "x": 2, "y": 1, "w": 2, "h": 2, "config": {"limit": 5}},
    {"id": "low_stock", "type": "list", "title": "dashboard_low_stock", "x": 0, "y": 3, "w": 2, "h": 1, "config": {"limit": 10}},
    {"id": "pending_tasks", "type": "list", "title": "dashboard_pending_tasks", "x": 2, "y": 3, "w": 2, "h": 1, "config": {"limit": 10}},
]


def _translate_widgets(widgets: list, request: Request) -> list:
    """Helper to translate widget titles using the request locale."""
    translated = []
    for w in widgets:
        w_copy = dict(w)
        if "title" in w_copy:
            w_copy["title"] = i18n_message(w_copy["title"], request)
        translated.append(w_copy)
    return translated


@router.get("/layouts", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def get_dashboard_layouts(request: Request, current_user=Depends(get_current_user)):
    """جلب تخطيطات لوحة التحكم للمستخدم"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        rows = db.execute(text("""
            SELECT id, layout_name, is_active, widgets, created_at, updated_at
            FROM dashboard_layouts WHERE user_id = :uid ORDER BY updated_at DESC
        """), {"uid": current_user.id}).fetchall()

        if not rows:
            # Return default layout
            return {"layouts": [{"id": 0, "layout_name": "default", "is_active": True,
                                 "widgets": _translate_widgets(DEFAULT_WIDGETS, request)}]}

        return {"layouts": [
            {
                "id": r.id,
                "layout_name": r.layout_name,
                "is_active": r.is_active,
                "widgets": _translate_widgets(r.widgets if isinstance(r.widgets, list) else json.loads(r.widgets) if r.widgets else DEFAULT_WIDGETS, request),
                "created_at": str(r.created_at) if r.created_at else None,
                "updated_at": str(r.updated_at) if r.updated_at else None
            } for r in rows
        ]}
    except Exception as e:
        logger.warning(f"Dashboard layouts fetch: {e}")
        return {"layouts": [{"id": 0, "layout_name": "default", "is_active": True,
                             "widgets": _translate_widgets(DEFAULT_WIDGETS, request)}]}
    finally:
        db.close()


@router.post("/layouts", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def save_dashboard_layout(request: Request, data: LayoutCreate, current_user=Depends(get_current_user)):
    """حفظ تخطيط لوحة التحكم"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        widgets_json = json.dumps([w.dict() for w in data.widgets]) if data.widgets else json.dumps(DEFAULT_WIDGETS)

        result = db.execute(text("""
            INSERT INTO dashboard_layouts (user_id, layout_name, widgets, is_active)
            VALUES (:uid, :name, :widgets::jsonb, TRUE)
            ON CONFLICT (user_id, layout_name) DO UPDATE
            SET widgets = :widgets::jsonb, updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """), {"uid": current_user.id, "name": data.layout_name, "widgets": widgets_json})

        layout_id = result.fetchone()[0]
        db.commit()
        return {"id": layout_id, "message": i18n_message("layout_saved", request)}
    except Exception:
        db.rollback()
        logger.exception("Failed to save dashboard layout")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/layouts/{layout_id}", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def update_dashboard_layout(layout_id: int, data: LayoutUpdate, request: Request, current_user=Depends(get_current_user)):
    """تحديث تخطيط لوحة التحكم (تغيير ترتيب/حجم الـ widgets)"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        widgets_json = json.dumps([w.dict() for w in data.widgets])

        db.execute(text("""
            UPDATE dashboard_layouts SET widgets = :widgets::jsonb, updated_at = CURRENT_TIMESTAMP
            WHERE id = :lid AND user_id = :uid
        """), {"lid": layout_id, "uid": current_user.id, "widgets": widgets_json})
        db.commit()
        return {"message": i18n_message("dashboard_layout_updated", request)}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/layouts/{layout_id}", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def delete_dashboard_layout(layout_id: int, request: Request, current_user=Depends(get_current_user)):
    """حذف تخطيط لوحة التحكم"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        db.execute(text("""
            DELETE FROM dashboard_layouts WHERE id = :lid AND user_id = :uid
        """), {"lid": layout_id, "uid": current_user.id})
        db.commit()
        return {"message": i18n_message("dashboard_layout_deleted", request)}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== DASH-002: Additional Widgets Data =====================

@router.get("/widgets/sales-summary", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def widget_sales_summary(
    period: str = "today",
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """
    Widget المبيعات (اليوم / الأسبوع / الشهر)
    period: today, week, month, quarter, year
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        today = date.today()
        if period == "today":
            start_date = today
        elif period == "week":
            start_date = today - timedelta(days=today.weekday())
        elif period == "month":
            start_date = today.replace(day=1)
        elif period == "quarter":
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            start_date = today.replace(month=quarter_month, day=1)
        elif period == "year":
            start_date = today.replace(month=1, day=1)
        else:
            start_date = today

        display_meta = _dashboard_display_currency(db, branch_scope)
        params = {"start": start_date, "end": today, "base_currency": display_meta["base_currency"]}
        invoice_total_base_sql = document_amount_base_sql("i.total", "i")
        pos_total_base_sql = branch_amount_base_sql("o.total_amount", "o.branch_id")
        invoice_branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, branch_param="bid")
        pos_branch_filter = branch_scope_filter_from_scope(branch_scope, "o.branch_id", params, branch_param="pos_bid")

        # Total Sales
        sales = db.execute(text(f"""
            SELECT COALESCE(SUM({invoice_total_base_sql}), 0) as total,
                   COUNT(*) as count
            FROM invoices i
            WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
            AND i.invoice_date >= :start AND i.invoice_date <= :end {invoice_branch_filter}
        """), params).fetchone()

        # POS Sales
        pos = db.execute(text(f"""
            SELECT COALESCE(SUM({pos_total_base_sql}), 0) as total,
                   COUNT(*) as count
            FROM pos_orders o
            WHERE o.status = 'paid'
            AND CAST(o.order_date AS DATE) >= :start AND CAST(o.order_date AS DATE) <= :end
            {pos_branch_filter}
        """), params).fetchone()

        total_sales = float(sales.total or 0) + float(pos.total or 0)
        total_count = int(sales.count or 0) + int(pos.count or 0)

        # Previous period comparison
        period_days = (today - start_date).days + 1
        prev_start = start_date - timedelta(days=period_days)
        prev_end = start_date - timedelta(days=1)
        params_prev = {"start": prev_start, "end": prev_end, "base_currency": display_meta["base_currency"]}
        invoice_branch_filter_prev = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params_prev, branch_param="bid")
        pos_branch_filter_prev = branch_scope_filter_from_scope(branch_scope, "o.branch_id", params_prev, branch_param="pos_bid")

        prev_sales = db.execute(text(f"""
            SELECT COALESCE(SUM({invoice_total_base_sql}), 0) as total
            FROM invoices i
            WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
            AND i.invoice_date >= :start AND i.invoice_date <= :end {invoice_branch_filter_prev}
        """), params_prev).scalar() or 0

        prev_pos = db.execute(text(f"""
            SELECT COALESCE(SUM({pos_total_base_sql}), 0) as total
            FROM pos_orders o
            WHERE o.status = 'paid'
            AND CAST(o.order_date AS DATE) >= :start AND CAST(o.order_date AS DATE) <= :end
            {pos_branch_filter_prev}
        """), params_prev).scalar() or 0

        prev_total = float(prev_sales) + float(prev_pos)
        change = round(((total_sales - prev_total) / prev_total * 100), 1) if prev_total > 0 else (100 if total_sales > 0 else 0)

        return {
            "display_currency": display_meta["currency"],
            "base_currency": display_meta["base_currency"],
            "is_multi_currency_scope": display_meta["is_multi_currency_scope"],
            "period": period,
            "total": _base_to_display_amount(total_sales, display_meta),
            "count": total_count,
            "change_percent": change,
            "previous_total": _base_to_display_amount(prev_total, display_meta)
        }
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/top-products", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def widget_top_products(
    limit: int = 10,
    period: str = "month",
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget أفضل المنتجات مبيعاً"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        today = date.today()
        if period == "week":
            start_date = today - timedelta(days=7)
        elif period == "month":
            start_date = today.replace(day=1)
        elif period == "year":
            start_date = today.replace(month=1, day=1)
        else:
            start_date = today.replace(day=1)

        display_meta = _dashboard_display_currency(db, branch_scope)
        params = {"start": start_date, "limit": limit, "base_currency": display_meta["base_currency"]}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, branch_param="bid")
        line_total_base_sql = document_amount_base_sql("il.total", "i")

        result = db.execute(text(f"""
            SELECT p.product_name as name,
                   SUM(il.quantity) as qty,
                   SUM({line_total_base_sql}) as value
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            JOIN products p ON il.product_id = p.id
            WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
            AND i.invoice_date >= :start {branch_filter}
            GROUP BY p.id, p.product_name
            ORDER BY value DESC LIMIT :limit
        """), params).fetchall()

        return {"display_currency": display_meta["currency"], "base_currency": display_meta["base_currency"], "products": [
            {"name": r.name, "quantity": float(r.qty or 0), "value": _base_to_display_amount(r.value or 0, display_meta)}
            for r in result
        ]}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/low-stock", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def widget_low_stock(
    limit: int = 10,
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget المخزون المنخفض"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        params = {"limit": limit}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "w.branch_id", params, branch_param="bid")
        branch_join = "JOIN warehouses w ON inv.warehouse_id = w.id" if branch_filter else ""

        result = db.execute(text(f"""
            SELECT p.id, p.product_name, p.sku, p.reorder_level,
                   COALESCE(inv_sum.total_qty, 0) - COALESCE(inv_sum.reserved_qty, 0) as current_stock
            FROM products p
            LEFT JOIN (
                SELECT inv.product_id,
                       SUM(inv.quantity) as total_qty,
                       SUM(COALESCE(inv.reserved_quantity, 0)) as reserved_qty
                FROM inventory inv
                {branch_join}
                WHERE 1=1 {branch_filter}
                GROUP BY inv.product_id
            ) inv_sum ON p.id = inv_sum.product_id
            WHERE p.is_active = TRUE
              AND p.reorder_level > 0
              AND (COALESCE(inv_sum.total_qty, 0) - COALESCE(inv_sum.reserved_qty, 0) <= p.reorder_level)
            ORDER BY current_stock ASC
            LIMIT :limit
        """), params).fetchall()

        return {"items": [
            {
                "id": r.id,
                "product_name": r.product_name,
                "sku": r.sku,
                "current_stock": float(r.current_stock),
                "reorder_level": float(r.reorder_level or 0),
                "shortage": max(float(r.reorder_level or 0) - float(r.current_stock), 0.0),
            }
            for r in result
        ]}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/pending-tasks", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def widget_pending_tasks(
    limit: int = 10,
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget المهام المعلقة (فواتير غير مدفوعة، طلبات معلقة، إلخ).

    P1 #10 fix: enforce branch scoping. ``branch_id`` is validated against
    the caller's allowed branches. When omitted and the caller is not an
    admin, results are restricted to ``current_user.allowed_branches``.
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        tasks = []

        scope_params: Dict[str, Any] = {}

        def scope_clause(col):
            return branch_scope_filter_from_scope(branch_scope, col, scope_params, branch_param="bid")

        # Unpaid invoices (filter by branch_id)
        try:
            unpaid = db.execute(text(f"""
                SELECT COUNT(*) as cnt, COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as total
                FROM invoices WHERE status IN ('pending', 'partially_paid')
                AND invoice_type = 'sales'
                {scope_clause('branch_id')}
            """), scope_params).fetchone()
            if unpaid and unpaid.cnt > 0:
                tasks.append({
                    "type": "unpaid_invoices",
                    "label": f"{unpaid.cnt} فاتورة غير مدفوعة",
                    "value": float(unpaid.total),
                    "link": "/accounting/invoices?status=pending"
                })
        except Exception:
            pass

        # Pending purchase orders (filter by branch_id)
        try:
            pending_po = db.execute(text(f"""
                SELECT COUNT(*) as cnt FROM purchase_orders
                WHERE status = 'pending'
                {scope_clause('branch_id')}
            """), scope_params).scalar() or 0
            if pending_po > 0:
                tasks.append({
                    "type": "pending_purchases",
                    "label": f"{pending_po} أمر شراء معلق",
                    "link": "/purchases/orders?status=pending"
                })
        except Exception:
            pass

        # Pending approvals — approval_requests has no branch_id; filter via
        # the requesting user's employee branch when scope is constrained.
        try:
            approval_scope = scope_clause('e.branch_id')
            if approval_scope:
                pending_approvals = db.execute(text(f"""
                    SELECT COUNT(*) FROM approval_requests ar
                    LEFT JOIN employees e ON e.user_id = ar.requested_by
                    WHERE ar.status = 'pending'
                    {approval_scope}
                """), scope_params).scalar() or 0
            else:
                pending_approvals = db.execute(text(
                    "SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'"
                )).scalar() or 0
            if pending_approvals > 0:
                tasks.append({
                    "type": "pending_approvals",
                    "label": f"{pending_approvals} طلب اعتماد معلق",
                    "link": "/approvals"
                })
        except Exception:
            pass

        # Leave requests pending — JOIN employees to honour branch scope.
        try:
            pending_leaves = db.execute(text(f"""
                SELECT COUNT(*) FROM leave_requests lr
                JOIN employees e ON e.id = lr.employee_id
                WHERE lr.status = 'pending'
                {scope_clause('e.branch_id')}
            """), scope_params).scalar() or 0
            if pending_leaves > 0:
                tasks.append({
                    "type": "pending_leaves",
                    "label": f"{pending_leaves} طلب إجازة معلق",
                    "link": "/hr/leaves"
                })
        except Exception:
            pass

        # Overdue invoices (filter by branch_id)
        try:
            overdue = db.execute(text(f"""
                SELECT COUNT(*) as cnt FROM invoices
                WHERE status IN ('pending', 'partially_paid')
                AND due_date < CURRENT_DATE AND invoice_type = 'sales'
                {scope_clause('branch_id')}
            """), scope_params).scalar() or 0
            if overdue > 0:
                tasks.append({
                    "type": "overdue_invoices",
                    "label": f"{overdue} فاتورة متأخرة عن السداد",
                    "link": "/accounting/invoices?overdue=true"
                })
        except Exception:
            pass

        return {"tasks": tasks[:limit]}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/cash-flow", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def widget_cash_flow(
    days: int = 30,
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget التدفق النقدي"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "ta.branch_id", params, branch_param="bid")

        # Cash inflows (receipts) by day
        inflows = db.execute(text(f"""
            SELECT t.transaction_date as dt,
                   COALESCE(SUM(t.amount), 0) as total
            FROM treasury_transactions t
            JOIN treasury_accounts ta ON t.treasury_id = ta.id
            WHERE t.transaction_type IN ('receipt', 'deposit', 'income')
            AND t.transaction_date >= :start {branch_filter}
            GROUP BY t.transaction_date
        """), params).fetchall()
        inflow_map = {}
        for r in inflows:
            d = r.dt
            if isinstance(d, datetime): d = d.date()
            inflow_map[d.isoformat()] = float(r.total)

        # Cash outflows (payments) by day
        outflows = db.execute(text(f"""
            SELECT t.transaction_date as dt,
                   COALESCE(SUM(t.amount), 0) as total
            FROM treasury_transactions t
            JOIN treasury_accounts ta ON t.treasury_id = ta.id
            WHERE t.transaction_type IN ('payment', 'expense', 'withdrawal')
            AND t.transaction_date >= :start {branch_filter}
            GROUP BY t.transaction_date
        """), params).fetchall()
        outflow_map = {}
        for r in outflows:
            d = r.dt
            if isinstance(d, datetime): d = d.date()
            outflow_map[d.isoformat()] = float(r.total)

        # Build daily series
        result = []
        running_net = 0
        for i in range(days + 1):
            day = start_date + timedelta(days=i)
            day_key = day.isoformat()
            inflow = inflow_map.get(day_key, 0)
            outflow = outflow_map.get(day_key, 0)
            running_net += inflow - outflow
            result.append({
                "date": day_key,
                "inflow": inflow,
                "outflow": outflow,
                "net": running_net
            })

        return {"data": result}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/available", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def get_available_widgets(current_user=Depends(get_current_user)):
    """قائمة الـ widgets المتاحة للإضافة"""
    widget_permissions = {
        "sales_today": "sales.view",
        "sales_week": "sales.view",
        "sales_month": "sales.view",
        "top_products": "sales.view",
        "recent_invoices": "sales.view",
        "receivables_aging": "sales.view",
        "expenses_month": "reports.financial",
        "cash_balance": "accounting.view",
        "profit_month": "reports.financial",
        "financial_chart": "reports.financial",
        "cash_flow": "accounting.view",
        "low_stock": "inventory.view",
    }
    user_perms = current_user.get("permissions", []) if isinstance(current_user, dict) else getattr(current_user, "permissions", []) or []
    widgets = [
        {"id": "sales_today", "type": "stat", "title": i18n_message("dashboard_sales_today", request), "default_w": 1, "default_h": 1},
        {"id": "sales_week", "type": "stat", "title": i18n_message("dashboard_sales_week", request), "default_w": 1, "default_h": 1},
        {"id": "sales_month", "type": "stat", "title": i18n_message("dashboard_sales_month", request), "default_w": 1, "default_h": 1},
        {"id": "expenses_month", "type": "stat", "title": i18n_message("dashboard_expenses_month", request), "default_w": 1, "default_h": 1},
        {"id": "cash_balance", "type": "stat", "title": i18n_message("dashboard_cash_balance", request), "default_w": 1, "default_h": 1},
        {"id": "profit_month", "type": "stat", "title": i18n_message("dashboard_profit_month", request), "default_w": 1, "default_h": 1},
        {"id": "financial_chart", "type": "chart", "title": i18n_message("dashboard_financial_chart", request), "default_w": 2, "default_h": 2},
        {"id": "top_products", "type": "chart", "title": i18n_message("dashboard_top_products", request), "default_w": 2, "default_h": 2},
        {"id": "cash_flow", "type": "chart", "title": i18n_message("dashboard_cash_flow", request), "default_w": 2, "default_h": 2},
        {"id": "low_stock", "type": "list", "title": i18n_message("dashboard_low_stock", request), "default_w": 2, "default_h": 1},
        {"id": "pending_tasks", "type": "list", "title": i18n_message("dashboard_pending_tasks", request), "default_w": 2, "default_h": 1},
        {"id": "recent_invoices", "type": "table", "title": i18n_message("dashboard_recent_invoices", request), "default_w": 2, "default_h": 2},
        {"id": "receivables_aging", "type": "chart", "title": "أعمار الذمم المدينة", "default_w": 2, "default_h": 1},
    ]
    return {
        "widgets": [
            widget for widget in widgets
            if not widget_permissions.get(widget["id"]) or check_permission(user_perms, widget_permissions[widget["id"]])
        ]
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Industry-specific endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/industry-widgets", dependencies=[Depends(require_permission("dashboard.view"))], response_model=Dict[str, Any])
def get_industry_widgets(current_user = Depends(get_current_user)):
    """Return industry-specific dashboard widgets based on company's industry type."""
    company_id = get_user_company_id(current_user)
    with transactional(company_id) as db:
        industry_type = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
        ).scalar() or "general"
        
        widgets = _get_industry_widgets(industry_type, db)
        return {"industry_type": industry_type, "widgets": widgets}


def _get_industry_widgets(industry_type: str, db) -> list:
    """Generate industry-specific widget data."""
    from services.industry_coa_templates import normalize_industry_key
    industry_type = normalize_industry_key(industry_type)
    widgets = []
    
    try:
        if industry_type == "restaurant":
            # Food cost % — uses journal_lines (debit/credit) + accounts
            food_cost = db.execute(text("""
                SELECT COALESCE(
                    (SELECT SUM(CASE WHEN a.account_number LIKE '510%' THEN jl.debit - jl.credit ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN a.account_number LIKE '410%' THEN jl.credit - jl.debit ELSE 0 END), 0) * 100
                     FROM journal_lines jl JOIN accounts a ON jl.account_id = a.id
                     JOIN journal_entries j ON jl.journal_entry_id = j.id AND j.status = 'posted'
                     WHERE j.entry_date >= date_trunc('month', CURRENT_DATE)), 0)
            """)).scalar() or 0
            widgets.append({"key": "food_cost_pct", "value": round(float(food_cost), 1), "label_ar": "نسبة تكلفة الطعام", "label_en": "Food Cost %", "icon": "🍽️", "target": 30})
            
        elif industry_type == "manufacturing":
            # WIP value — account 13010
            wip = db.execute(text("""
                SELECT COALESCE(SUM(
                    CASE WHEN a.account_number = '13010' THEN jl.debit - jl.credit ELSE 0 END
                ), 0) FROM journal_lines jl JOIN accounts a ON jl.account_id = a.id
                JOIN journal_entries je ON jl.journal_entry_id = je.id AND je.status = 'posted'
            """)).scalar() or 0
            widgets.append({"key": "wip_value", "value": float(wip), "label_ar": "قيمة الإنتاج تحت التشغيل", "label_en": "WIP Value", "icon": "🏭"})
            
        elif industry_type == "construction":
            # Active projects count
            projects = db.execute(text(
                "SELECT COUNT(*) FROM projects WHERE status NOT IN ('completed', 'cancelled', 'on_hold')"
            )).scalar() or 0
            widgets.append({"key": "active_projects", "value": projects, "label_ar": "مشاريع نشطة", "label_en": "Active Projects", "icon": "🏗️"})
            
        elif industry_type == "pharmacy":
            # Count products with reorder_level > 0 as a proxy for tracked items
            tracked = db.execute(text("""
                SELECT COUNT(*) FROM products 
                WHERE is_active = true AND reorder_level > 0
            """)).scalar() or 0
            widgets.append({"key": "tracked_drugs", "value": tracked, "label_ar": "أصناف تحت المراقبة", "label_en": "Tracked Items", "icon": "💊"})
            
        elif industry_type in ("retail", "ecommerce"):
            # Today's POS sales — uses invoices table
            today_sales = db.execute(text("""
                SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) FROM invoices 
                WHERE DATE(created_at) = CURRENT_DATE AND invoice_type = 'sales'
            """)).scalar() or 0
            widgets.append({"key": "today_sales", "value": float(today_sales), "label_ar": "مبيعات اليوم", "label_en": "Today's Sales", "icon": "🛍️"})
            
        elif industry_type == "logistics":
            # Active shipments — uses delivery_orders
            try:
                shipments = db.execute(text("""
                    SELECT COUNT(*) FROM delivery_orders WHERE status NOT IN ('delivered', 'cancelled')
                """)).scalar() or 0
            except Exception:
                shipments = 0
            widgets.append({"key": "active_shipments", "value": shipments, "label_ar": "شحنات نشطة", "label_en": "Active Shipments", "icon": "🚛"})
    except Exception as e:
        logger.warning(f"Industry widget query failed for '{industry_type}': {e}")
    
    return widgets


@router.get("/gl-rules", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
def get_company_gl_rules(current_user = Depends(get_current_user)):
    """Return GL auto-posting rules for the company's industry type."""
    company_id = get_user_company_id(current_user)
    with transactional(company_id) as db:
        industry_type = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
        ).scalar() or "general"
        
        from services.industry_gl_rules import get_gl_rules_summary, get_default_accounts
        from services.industry_coa_templates import normalize_industry_key
        industry_type = normalize_industry_key(industry_type)
        return {
            "industry_type": industry_type,
            "rules": get_gl_rules_summary(industry_type),
            "default_accounts": get_default_accounts(industry_type),
        }


@router.get("/coa-summary", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
def get_company_coa_summary(current_user = Depends(get_current_user)):
    """Return COA template summary for the company's industry type."""
    company_id = get_user_company_id(current_user)
    with transactional(company_id) as db:
        industry_type = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
        ).scalar() or "general"
        
        from services.industry_coa_templates import get_industry_coa_summary, normalize_industry_key
        industry_type = normalize_industry_key(industry_type)
        return get_industry_coa_summary(industry_type)


# ═══════════════════════════════════════════════════════
# BI Analytics Dashboard Endpoints (US9)
# ═══════════════════════════════════════════════════════

class WidgetCreate(BaseModel):
    widget_type: str
    title: str
    data_source: str
    filters: Optional[dict] = None
    position: Optional[dict] = None
    sort_order: Optional[int] = 0

class DashboardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    access_roles: Optional[List[str]] = None
    branch_scope: Optional[str] = "all"
    refresh_interval_minutes: Optional[int] = 15
    widgets: Optional[List[WidgetCreate]] = None

class DashboardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    access_roles: Optional[List[str]] = None
    branch_scope: Optional[str] = None
    refresh_interval_minutes: Optional[int] = None
    widgets: Optional[List[WidgetCreate]] = None


VALID_WIDGET_TYPES = {"kpi_card", "bar_chart", "line_chart", "pie_chart", "table", "gauge"}
VALID_DATA_SOURCES = {"revenue", "expenses", "cash_position", "top_customers", "inventory_turnover", "ar_aging", "ap_aging", "sales_pipeline", "custom_query"}

MV_MAP = {
    "revenue": "mv_revenue_summary",
    "expenses": "mv_expense_summary",
    "cash_position": "mv_cash_position",
    "top_customers": "mv_top_customers",
    "inventory_turnover": "mv_inventory_turnover",
    "ar_aging": "mv_ar_aging",
    "ap_aging": "mv_ap_aging",
    "sales_pipeline": "mv_sales_pipeline",
}


def _query_widget_data(db, data_source: str, filters: dict = None):
    """Query materialized view for widget data, applying optional filters."""
    mv_name = MV_MAP.get(data_source)
    if not mv_name:
        return []

    conditions = []
    params = {}

    if filters and filters.get("branch_id"):
        conditions.append("branch_id = :branch_id")
        params["branch_id"] = filters["branch_id"]
    elif filters and filters.get("branch_ids") is not None:
        branch_ids = list(filters.get("branch_ids") or [])
        if branch_ids:
            conditions.append("branch_id = ANY(:branch_ids)")
            params["branch_ids"] = branch_ids
        else:
            conditions.append("1=0")

    # Date filters apply to revenue/expenses views that have a period column
    if data_source in ("revenue", "expenses") and filters:
        if filters.get("date_from"):
            conditions.append("period >= :date_from")
            params["date_from"] = filters["date_from"]
        if filters.get("date_to"):
            conditions.append("period <= :date_to")
            params["date_to"] = filters["date_to"]

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    if data_source == "revenue":
        query = f"SELECT period, branch_id, total_revenue FROM {mv_name}{where_clause} ORDER BY period"
    elif data_source == "expenses":
        query = f"SELECT period, branch_id, total_expenses FROM {mv_name}{where_clause} ORDER BY period"
    elif data_source == "cash_position":
        query = f"SELECT account_id, account_name, account_number, balance FROM {mv_name} ORDER BY balance DESC"
    elif data_source == "top_customers":
        query = f"SELECT party_id, customer_name, invoice_count, total_amount FROM {mv_name} ORDER BY total_amount DESC LIMIT 20"
    elif data_source == "ar_aging":
        query = f"SELECT party_id, customer_name, current_bucket, days_31_60, days_61_90, days_over_90 FROM {mv_name}"
    elif data_source == "ap_aging":
        query = f"SELECT party_id, supplier_name, current_bucket, days_31_60, days_61_90, days_over_90 FROM {mv_name}"
    elif data_source == "inventory_turnover":
        query = f"SELECT product_id, product_name, total_sold, current_stock, turnover_ratio FROM {mv_name} ORDER BY turnover_ratio DESC LIMIT 20"
    elif data_source == "sales_pipeline":
        query = f"SELECT stage, deal_count, total_value, avg_probability FROM {mv_name}"
    else:
        return []

    try:
        rows = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.warning(f"Widget data query failed for {data_source}: {e}")
        return []


@router.get("/analytics", dependencies=[Depends(require_permission("dashboard.analytics_view"))], response_model=Dict[str, Any])
def list_analytics_dashboards(current_user: dict = Depends(get_current_user)):
    """List available analytics dashboards filtered by user role + branch."""
    company_id = get_user_company_id(current_user)
    with transactional(company_id) as db:
        user_role = getattr(current_user, "role", "")
        try:
            rows = db.execute(text("""
                SELECT id, name, description, is_system, access_roles, branch_scope,
                       refresh_interval_minutes, created_at, created_by
                FROM analytics_dashboards
                ORDER BY is_system DESC, name
            """)).fetchall()
        except Exception as e:
            if "does not exist" in str(e):
                return {"dashboards": []}
            raise

        dashboards = []
        for row in rows:
            d = dict(row._mapping)
            roles = d.get("access_roles") or []
            if user_role == "system_admin" or not roles or user_role in roles:
                dashboards.append(d)

        return {"dashboards": dashboards}


@router.get("/analytics/widget-data/{widget_id}", dependencies=[Depends(require_permission("dashboard.analytics_view"))], response_model=Dict[str, Any])
def get_widget_data(widget_id: int, current_user: dict = Depends(get_current_user)):
    """Refresh data for a single widget."""
    company_id = get_user_company_id(current_user)
    branch_scope = resolve_branch_scope(current_user, None)
    with transactional(company_id) as db:
        widget = db.execute(text("""
            SELECT id, widget_type, title, data_source, filters
            FROM analytics_dashboard_widgets WHERE id = :id
        """), {"id": widget_id}).fetchone()

        if not widget:
            raise HTTPException(**http_error(404, "widget_not_found"))

        wd = dict(widget._mapping)
        widget_filters = wd.get("filters") or {}
        if branch_scope["branch_id"] is not None:
            widget_filters["branch_id"] = branch_scope["branch_id"]
        elif branch_scope["branch_ids"] is not None:
            widget_filters["branch_ids"] = branch_scope["branch_ids"]

        return {
            "widget_id": widget_id,
            "data": _query_widget_data(db, wd["data_source"], widget_filters),
            "freshness": _mv_freshness(db, wd["data_source"]),
        }


def _mv_freshness(db, data_source: str) -> Dict[str, Any]:
    """T10.1 P1 #11 — return MV last-refresh timestamp for the freshness badge."""
    mv_name = MV_MAP.get(data_source)
    if not mv_name:
        return {"mv_name": None, "last_refreshed_at": None, "stale_minutes": None}
    try:
        row = db.execute(text("""
            SELECT last_refreshed_at,
                   EXTRACT(EPOCH FROM (NOW() - last_refreshed_at)) / 60.0 AS age_min
              FROM analytics_mv_freshness
             WHERE mv_name = :n
        """), {"n": mv_name}).fetchone()
        if not row:
            return {"mv_name": mv_name, "last_refreshed_at": None, "stale_minutes": None}
        return {
            "mv_name": mv_name,
            "last_refreshed_at": row.last_refreshed_at.isoformat() if row.last_refreshed_at else None,
            "stale_minutes": int(row.age_min) if row.age_min is not None else None,
        }
    except Exception:
        return {"mv_name": mv_name, "last_refreshed_at": None, "stale_minutes": None}


@router.get("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_view"))], response_model=Dict[str, Any])
def get_analytics_dashboard(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Get a dashboard with its widget data queried from materialized views."""
    company_id = get_user_company_id(current_user)
    branch_scope = resolve_branch_scope(current_user, None)
    with transactional(company_id) as db:
        dashboard = db.execute(text("""
            SELECT id, name, description, is_system, access_roles, branch_scope,
                   refresh_interval_minutes, created_at, created_by
            FROM analytics_dashboards WHERE id = :id
        """), {"id": dashboard_id}).fetchone()

        if not dashboard:
            raise HTTPException(**http_error(404, "dashboard_not_found"))

        d = dict(dashboard._mapping)
        # Check role access
        user_role = current_user.get("role", "")
        roles = d.get("access_roles") or []
        if user_role != "system_admin" and roles and user_role not in roles:
            raise HTTPException(**http_error(403, "access_denied_dashboard"))

        # Load widgets
        widgets = db.execute(text("""
            SELECT id, widget_type, title, data_source, filters, position, sort_order
            FROM analytics_dashboard_widgets
            WHERE dashboard_id = :dashboard_id
            ORDER BY sort_order
        """), {"dashboard_id": dashboard_id}).fetchall()

        widget_list = []
        for w in widgets:
            wd = dict(w._mapping)
            widget_filters = wd.get("filters") or {}
            if branch_scope["branch_id"] is not None:
                widget_filters["branch_id"] = branch_scope["branch_id"]
            elif branch_scope["branch_ids"] is not None:
                widget_filters["branch_ids"] = branch_scope["branch_ids"]
            wd["data"] = _query_widget_data(db, wd["data_source"], widget_filters)
            widget_list.append(wd)

        d["widgets"] = widget_list
        return d


@router.post("/analytics", dependencies=[Depends(require_permission("dashboard.analytics_manage"))], response_model=Dict[str, Any])
def create_analytics_dashboard(payload: DashboardCreate, current_user: dict = Depends(get_current_user)):
    """Create a custom analytics dashboard."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        username = current_user.get("username", "unknown")
        result = db.execute(text("""
            INSERT INTO analytics_dashboards (name, description, access_roles, branch_scope, refresh_interval_minutes, created_by)
            VALUES (:name, :desc, :roles::jsonb, :scope, :interval, :created_by)
            RETURNING id
        """), {
            "name": payload.name,
            "desc": payload.description,
            "roles": json.dumps(payload.access_roles or []),
            "scope": payload.branch_scope or "all",
            "interval": payload.refresh_interval_minutes or 15,
            "created_by": username,
        })
        dashboard_id = result.fetchone()[0]

        # Create widgets if provided
        if payload.widgets:
            for w in payload.widgets:
                if w.widget_type not in VALID_WIDGET_TYPES:
                    raise HTTPException(status_code=400, detail=i18n_message("invalid_widget_type", request))
                if w.data_source not in VALID_DATA_SOURCES:
                    raise HTTPException(status_code=400, detail=i18n_message("invalid_data_source", request))
                db.execute(text("""
                    INSERT INTO analytics_dashboard_widgets
                        (dashboard_id, widget_type, title, data_source, filters, position, sort_order, created_by)
                    VALUES (:did, :wt, :title, :ds, :filters::jsonb, :pos::jsonb, :so, :cb)
                """), {
                    "did": dashboard_id,
                    "wt": w.widget_type,
                    "title": w.title,
                    "ds": w.data_source,
                    "filters": json.dumps(w.filters or {}),
                    "pos": json.dumps(w.position or {}),
                    "so": w.sort_order or 0,
                    "cb": username,
                })

        db.commit()
        return {"id": dashboard_id, "message": i18n_message("dashboard_created", request)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_create_failed"))
    finally:
        db.close()


@router.put("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_manage"))], response_model=Dict[str, Any])
def update_analytics_dashboard(dashboard_id: int, payload: DashboardUpdate, current_user: dict = Depends(get_current_user)):
    """Update dashboard layout and/or widgets."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        # Verify dashboard exists
        dashboard = db.execute(text(
            "SELECT id, is_system FROM analytics_dashboards WHERE id = :id"
        ), {"id": dashboard_id}).fetchone()

        if not dashboard:
            raise HTTPException(**http_error(404, "dashboard_not_found"))

        username = current_user.get("username", "unknown")

        # Update dashboard metadata
        updates = []
        params = {"id": dashboard_id, "updated_by": username}
        if payload.name is not None:
            updates.append("name = :name")
            params["name"] = payload.name
        if payload.description is not None:
            updates.append("description = :desc")
            params["desc"] = payload.description
        if payload.access_roles is not None:
            updates.append("access_roles = :roles::jsonb")
            params["roles"] = json.dumps(payload.access_roles)
        if payload.branch_scope is not None:
            updates.append("branch_scope = :scope")
            params["scope"] = payload.branch_scope
        if payload.refresh_interval_minutes is not None:
            updates.append("refresh_interval_minutes = :interval")
            params["interval"] = payload.refresh_interval_minutes

        if updates:
            updates.append("updated_by = :updated_by")
            updates.append("updated_at = NOW()")
            db.execute(text(f"UPDATE analytics_dashboards SET {', '.join(updates)} WHERE id = :id"), params)

        # Replace widgets if provided
        if payload.widgets is not None:
            db.execute(text("DELETE FROM analytics_dashboard_widgets WHERE dashboard_id = :did"), {"did": dashboard_id})
            for w in payload.widgets:
                if w.widget_type not in VALID_WIDGET_TYPES:
                    raise HTTPException(status_code=400, detail=i18n_message("invalid_widget_type", request))
                if w.data_source not in VALID_DATA_SOURCES:
                    raise HTTPException(status_code=400, detail=i18n_message("invalid_data_source", request))
                db.execute(text("""
                    INSERT INTO analytics_dashboard_widgets
                        (dashboard_id, widget_type, title, data_source, filters, position, sort_order, created_by)
                    VALUES (:did, :wt, :title, :ds, :filters::jsonb, :pos::jsonb, :so, :cb)
                """), {
                    "did": dashboard_id,
                    "wt": w.widget_type,
                    "title": w.title,
                    "ds": w.data_source,
                    "filters": json.dumps(w.filters or {}),
                    "pos": json.dumps(w.position or {}),
                    "so": w.sort_order or 0,
                    "cb": username,
                })

        db.commit()
        return {"message": i18n_message(("dashboard_updated_success", request))}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_update_failed"))
    finally:
        db.close()


@router.delete("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_manage"))], response_model=Dict[str, Any])
def delete_analytics_dashboard(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a custom analytics dashboard. System dashboards cannot be deleted."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        dashboard = db.execute(text(
            "SELECT id, is_system FROM analytics_dashboards WHERE id = :id"
        ), {"id": dashboard_id}).fetchone()

        if not dashboard:
            raise HTTPException(**http_error(404, "dashboard_not_found"))

        if dashboard._mapping.get("is_system"):
            raise HTTPException(**http_error(403, "system_dashboard_delete_forbidden"))

        # Widgets cascade-deleted via FK constraint
        db.execute(text("DELETE FROM analytics_dashboards WHERE id = :id"), {"id": dashboard_id})
        db.commit()
        return {"message": i18n_message(("dashboard_deleted_success", request))}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_delete_failed"))
    finally:
        db.close()
