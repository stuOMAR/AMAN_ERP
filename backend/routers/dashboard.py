from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import logging
from datetime import date, timedelta, datetime
import json
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access
from utils.cache import cached
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
    # Enforce branch restriction
    branch_id = validate_branch_access(current_user, branch_id)
    
    db = get_db_connection(get_user_company_id(current_user))
    try:
        # Dates
        today = date.today()
        this_month_start = today.replace(day=1)
        prev_month_end = this_month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        
        # Shared filters
        branch_filter_cash = ""
        params_cash = {}
        if branch_id:
            branch_filter_cash = "AND branch_id = :branch_id"
            params_cash["branch_id"] = branch_id

        def calculate_period_stats(start_dt, end_dt=None):
            """Calculate sales/profit/cash for the period.

            Sales come from the unified `get_sales_total` source (invoices +
            POS, base currency, gross including tax) so Dashboard matches
            the Reports page. COGS, opex and net profit come from posted
            GL entries via `get_gl_profit_breakdown`.
            """
            # Unified gross sales (T3.1)
            sales_data = get_sales_total(
                db, start_date=start_dt, end_date=end_dt, branch_id=branch_id
            )
            total_sales = float(sales_data["total_sales"])

            # GL-based profit breakdown
            gl = get_gl_profit_breakdown(
                db, start_date=start_dt, end_date=end_dt, branch_id=branch_id
            )
            total_expenses = float(gl["operating_expenses"])
            cogs = float(gl["cogs"])
            net_profit = float(gl["net_profit"])

            # Cash balance: branch- and period-aware via journal lines, or
            # cumulative via accounts.balance for the company-wide all-time
            # view (kept fast for the dashboard summary card).
            branch_filter_je = ""
            date_filter_je = ""
            params_gl: dict = {}
            if branch_id:
                branch_filter_je = "AND je.branch_id = :branch_id"
                params_gl["branch_id"] = branch_id
            if start_dt:
                date_filter_je += " AND je.entry_date >= :start_dt"
                params_gl["start_dt"] = start_dt
            if end_dt:
                date_filter_je += " AND je.entry_date <= :end_dt"
                params_gl["end_dt"] = end_dt

            treasury_ids = [row[0] for row in db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE is_active = true")).fetchall() if row[0]]
            legacy_ids = [row[0] for row in db.execute(text("SELECT id FROM accounts WHERE account_code LIKE 'BOX%' OR account_code LIKE 'BNK%'")).fetchall()]
            all_cash_ids = list(set(treasury_ids + legacy_ids))

            cash_balance = 0
            if all_cash_ids:
                # SEC-003: parameterized IN clause
                id_params = {f"cid_{i}": cid for i, cid in enumerate(all_cash_ids)}
                id_placeholders = ", ".join(f":cid_{i}" for i in range(len(all_cash_ids)))
                if branch_id or start_dt or end_dt:
                    cash_balance = db.execute(text(f"""
                        SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                        FROM journal_lines jl
                        JOIN journal_entries je ON jl.journal_entry_id = je.id
                        JOIN accounts a ON jl.account_id = a.id
                        WHERE a.id IN ({id_placeholders})
                        {branch_filter_je} {date_filter_je}
                    """), {**params_gl, **id_params}).scalar() or 0
                else:
                    cash_balance = db.execute(text(f"""
                        SELECT COALESCE(SUM(balance), 0) FROM accounts
                        WHERE id IN ({id_placeholders})
                    """), id_params).scalar() or 0

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
        
        # Trends
        def calc_change(curr, prev):
            if prev == 0:
                return 0 if curr == 0 else 100
            pct = ((curr - prev) / abs(prev)) * 100
            # Cap extreme percentages at ±999%
            pct = max(-999, min(999, pct))
            return round(pct, 1)

        # Cash on Hand (GL-linked snapshot)
        cash_sql = f"""
            SELECT COALESCE(SUM(a.balance), 0) 
            FROM treasury_accounts ta
            JOIN accounts a ON ta.gl_account_id = a.id
            WHERE ta.is_active = TRUE {branch_filter_cash.replace('branch_id =', 'ta.branch_id =')}
        """
        cash = db.execute(text(cash_sql), params_cash).scalar() or 0

        # Low Stock
        low_stock_query = f"""
            SELECT COUNT(*) FROM (
                SELECT p.id
                FROM products p
                LEFT JOIN (
                    SELECT product_id, SUM(quantity) as total_qty 
                    FROM inventory inv
                    {"JOIN warehouses w ON inv.warehouse_id = w.id" if branch_id else ""}
                    {"WHERE w.branch_id = :branch_id" if branch_id else ""}
                    GROUP BY product_id
                ) inv_sum ON p.id = inv_sum.product_id
                WHERE (COALESCE(inv_sum.total_qty, 0) <= p.reorder_level)
                OR (p.reorder_level = 0 AND COALESCE(inv_sum.total_qty, 0) <= 5)
            ) as low_stock_items
        """
        low_stock = db.execute(text(low_stock_query), params_cash).scalar() or 0

        # Reserved Stock
        reserved_stock_query = f"""
            SELECT p.product_name, SUM(inv.reserved_quantity) as reserved_qty
            FROM inventory inv
            JOIN products p ON inv.product_id = p.id
            {"JOIN warehouses w ON inv.warehouse_id = w.id" if branch_id else ""}
            WHERE inv.reserved_quantity > 0
            {"AND w.branch_id = :branch_id" if branch_id else ""}
            GROUP BY p.product_name
        """
        reserved_stock_data = db.execute(text(reserved_stock_query), params_cash).fetchall()
        reserved_stock_list = [{"product": row.product_name, "quantity": int(row.reserved_qty)} for row in reserved_stock_data]

        return {
            "sales": cumulative["sales"],
            "sales_change": calc_change(current["sales"], previous["sales"]),
            "expenses": cumulative["expenses"],
            "expenses_change": calc_change(current["expenses"], previous["expenses"]),
            "cogs": cumulative.get("cogs", 0),
            "profit": cumulative["profit"],
            "net_profit": cumulative["profit"],
            "profit_change": calc_change(current["profit"], previous["profit"]),
            "cash": cumulative["cash"],
            "cash_change": calc_change(current["cash"], previous["cash"]),
            "cash_status": "Stable" if cumulative["cash"] > 0 else "Low",
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(get_user_company_id(current_user))
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        if branch_id:
            params["branch_id"] = branch_id
        
        branch_cond_inv = "AND branch_id = :branch_id" if branch_id else ""
        branch_cond_exp = "AND ta.branch_id = :branch_id" if branch_id else ""

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
            {branch_cond_inv.replace('branch_id =', 'branch_id =')}
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
            result.append({
                "date": day.isoformat(),
                "sales": s,
                "expenses": e,
                "profit": s - e # Simplified (Revenue - Expense), neglecting COGS daily calc complexity for speed
            })
            
        return result
    finally:
        db.close()

@router.get("/charts/products", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission("dashboard.view"))])
def get_top_products(
    limit: int = 5,
    branch_id: int = None,
    current_user: dict = Depends(get_current_user)
):
    """أكثر المنتجات مبيعاً"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(get_user_company_id(current_user))
    try:
        params = {"limit": limit}
        branch_filter = ""
        if branch_id:
            params["branch_id"] = branch_id
            branch_filter = "AND i.branch_id = :branch_id"

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
            {branch_filter.replace('i.branch_id', 'val.branch_id')}
            GROUP BY p.id, p.product_name
            ORDER BY value DESC
            LIMIT :limit
        """), params).fetchall()


        return [{"name": row.name, "value": float(row.value)} for row in result]
    finally:
        db.close()
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
    {"id": "sales_today", "type": "stat", "title": "مبيعات اليوم", "x": 0, "y": 0, "w": 1, "h": 1, "config": {"period": "today"}},
    {"id": "sales_month", "type": "stat", "title": "مبيعات الشهر", "x": 1, "y": 0, "w": 1, "h": 1, "config": {"period": "month"}},
    {"id": "expenses_month", "type": "stat", "title": "مصروفات الشهر", "x": 2, "y": 0, "w": 1, "h": 1, "config": {"period": "month"}},
    {"id": "cash_balance", "type": "stat", "title": "الرصيد النقدي", "x": 3, "y": 0, "w": 1, "h": 1, "config": {}},
    {"id": "financial_chart", "type": "chart", "title": "المبيعات والمصروفات", "x": 0, "y": 1, "w": 2, "h": 2, "config": {"days": 30}},
    {"id": "top_products", "type": "chart", "title": "أفضل المنتجات", "x": 2, "y": 1, "w": 2, "h": 2, "config": {"limit": 5}},
    {"id": "low_stock", "type": "list", "title": "المخزون المنخفض", "x": 0, "y": 3, "w": 2, "h": 1, "config": {"limit": 10}},
    {"id": "pending_tasks", "type": "list", "title": "المهام المعلقة", "x": 2, "y": 3, "w": 2, "h": 1, "config": {"limit": 10}},
]


@router.get("/layouts", dependencies=[Depends(require_permission("dashboard.view"))])
def get_dashboard_layouts(current_user=Depends(get_current_user)):
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
                                 "widgets": DEFAULT_WIDGETS}]}

        return {"layouts": [
            {
                "id": r.id,
                "layout_name": r.layout_name,
                "is_active": r.is_active,
                "widgets": r.widgets if isinstance(r.widgets, list) else json.loads(r.widgets) if r.widgets else DEFAULT_WIDGETS,
                "created_at": str(r.created_at) if r.created_at else None,
                "updated_at": str(r.updated_at) if r.updated_at else None
            } for r in rows
        ]}
    except Exception as e:
        logger.warning(f"Dashboard layouts fetch: {e}")
        return {"layouts": [{"id": 0, "layout_name": "default", "is_active": True,
                             "widgets": DEFAULT_WIDGETS}]}
    finally:
        db.close()


@router.post("/layouts", dependencies=[Depends(require_permission("dashboard.view"))])
def save_dashboard_layout(data: LayoutCreate, current_user=Depends(get_current_user)):
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
        return {"id": layout_id, "message": "تم حفظ التخطيط بنجاح"}
    except Exception:
        db.rollback()
        logger.exception("Failed to save dashboard layout")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/layouts/{layout_id}", dependencies=[Depends(require_permission("dashboard.view"))])
def update_dashboard_layout(layout_id: int, data: LayoutUpdate, current_user=Depends(get_current_user)):
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
        return {"message": "تم تحديث التخطيط بنجاح"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/layouts/{layout_id}", dependencies=[Depends(require_permission("dashboard.view"))])
def delete_dashboard_layout(layout_id: int, current_user=Depends(get_current_user)):
    """حذف تخطيط لوحة التحكم"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        db.execute(text("""
            DELETE FROM dashboard_layouts WHERE id = :lid AND user_id = :uid
        """), {"lid": layout_id, "uid": current_user.id})
        db.commit()
        return {"message": "تم حذف التخطيط"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== DASH-002: Additional Widgets Data =====================

@router.get("/widgets/sales-summary", dependencies=[Depends(require_permission("dashboard.view"))])
def widget_sales_summary(
    period: str = "today",
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """
    Widget المبيعات (اليوم / الأسبوع / الشهر)
    period: today, week, month, quarter, year
    """
    branch_id = validate_branch_access(current_user, branch_id)
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

        params = {"start": start_date, "end": today}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND branch_id = :bid"
            params["bid"] = branch_id

        # Total Sales
        sales = db.execute(text(f"""
            SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as total,
                   COUNT(*) as count
            FROM invoices
            WHERE invoice_type = 'sales' AND status != 'cancelled'
            AND invoice_date >= :start AND invoice_date <= :end {branch_filter}
        """), params).fetchone()

        # POS Sales
        pos = db.execute(text(f"""
            SELECT COALESCE(SUM(total_amount), 0) as total,
                   COUNT(*) as count
            FROM pos_orders
            WHERE status = 'paid'
            AND CAST(order_date AS DATE) >= :start AND CAST(order_date AS DATE) <= :end
            {branch_filter}
        """), params).fetchone()

        total_sales = float(sales.total or 0) + float(pos.total or 0)
        total_count = int(sales.count or 0) + int(pos.count or 0)

        # Previous period comparison
        period_days = (today - start_date).days + 1
        prev_start = start_date - timedelta(days=period_days)
        prev_end = start_date - timedelta(days=1)
        params_prev = {"start": prev_start, "end": prev_end}
        if branch_id:
            params_prev["bid"] = branch_id

        prev_sales = db.execute(text(f"""
            SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as total
            FROM invoices
            WHERE invoice_type = 'sales' AND status != 'cancelled'
            AND invoice_date >= :start AND invoice_date <= :end {branch_filter}
        """), params_prev).scalar() or 0

        prev_pos = db.execute(text(f"""
            SELECT COALESCE(SUM(total_amount), 0) as total
            FROM pos_orders
            WHERE status = 'paid'
            AND CAST(order_date AS DATE) >= :start AND CAST(order_date AS DATE) <= :end
            {branch_filter}
        """), params_prev).scalar() or 0

        prev_total = float(prev_sales) + float(prev_pos)
        change = round(((total_sales - prev_total) / prev_total * 100), 1) if prev_total > 0 else (100 if total_sales > 0 else 0)

        return {
            "period": period,
            "total": total_sales,
            "count": total_count,
            "change_percent": change,
            "previous_total": prev_total
        }
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/top-products", dependencies=[Depends(require_permission("dashboard.view"))])
def widget_top_products(
    limit: int = 10,
    period: str = "month",
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget أفضل المنتجات مبيعاً"""
    branch_id = validate_branch_access(current_user, branch_id)
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

        params = {"start": start_date, "limit": limit}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND i.branch_id = :bid"
            params["bid"] = branch_id

        result = db.execute(text(f"""
            SELECT p.product_name as name,
                   SUM(il.quantity) as qty,
                   SUM(il.total * COALESCE(i.exchange_rate, 1)) as value
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            JOIN products p ON il.product_id = p.id
            WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
            AND i.invoice_date >= :start {branch_filter}
            GROUP BY p.id, p.product_name
            ORDER BY value DESC LIMIT :limit
        """), params).fetchall()

        return {"products": [
            {"name": r.name, "quantity": float(r.qty or 0), "value": float(r.value or 0)}
            for r in result
        ]}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/low-stock", dependencies=[Depends(require_permission("dashboard.view"))])
def widget_low_stock(
    limit: int = 10,
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget المخزون المنخفض"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        params = {"limit": limit}
        branch_join = ""
        branch_filter = ""
        if branch_id:
            branch_join = "JOIN warehouses w ON inv.warehouse_id = w.id"
            branch_filter = "AND w.branch_id = :bid"
            params["bid"] = branch_id

        result = db.execute(text(f"""
            SELECT p.id, p.product_name, p.sku, p.reorder_level,
                   COALESCE(inv_sum.total_qty, 0) as current_stock
            FROM products p
            LEFT JOIN (
                SELECT inv.product_id, SUM(inv.quantity) as total_qty
                FROM inventory inv
                {branch_join}
                WHERE 1=1 {branch_filter}
                GROUP BY inv.product_id
            ) inv_sum ON p.id = inv_sum.product_id
            WHERE p.is_active = TRUE
            AND (COALESCE(inv_sum.total_qty, 0) <= GREATEST(p.reorder_level, 5))
            ORDER BY COALESCE(inv_sum.total_qty, 0) ASC
            LIMIT :limit
        """), params).fetchall()

        return {"items": [
            {
                "id": r.id,
                "product_name": r.product_name,
                "sku": r.sku,
                "current_stock": float(r.current_stock),
                "reorder_level": float(r.reorder_level or 5)
            }
            for r in result
        ]}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/widgets/pending-tasks", dependencies=[Depends(require_permission("dashboard.view"))])
def widget_pending_tasks(
    limit: int = 10,
    current_user=Depends(get_current_user)
):
    """Widget المهام المعلقة (فواتير غير مدفوعة، طلبات معلقة، إلخ)"""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        tasks = []

        # Unpaid invoices
        try:
            unpaid = db.execute(text("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as total
                FROM invoices WHERE status IN ('pending', 'partially_paid') AND invoice_type = 'sales'
            """)).fetchone()
            if unpaid and unpaid.cnt > 0:
                tasks.append({
                    "type": "unpaid_invoices",
                    "label": f"{unpaid.cnt} فاتورة غير مدفوعة",
                    "value": float(unpaid.total),
                    "link": "/accounting/invoices?status=pending"
                })
        except Exception:
            pass

        # Pending purchase orders
        try:
            pending_po = db.execute(text("""
                SELECT COUNT(*) as cnt FROM purchase_orders WHERE status = 'pending'
            """)).scalar() or 0
            if pending_po > 0:
                tasks.append({
                    "type": "pending_purchases",
                    "label": f"{pending_po} أمر شراء معلق",
                    "link": "/purchases/orders?status=pending"
                })
        except Exception:
            pass

        # Pending approvals
        try:
            pending_approvals = db.execute(text("""
                SELECT COUNT(*) FROM approval_requests WHERE status = 'pending'
            """)).scalar() or 0
            if pending_approvals > 0:
                tasks.append({
                    "type": "pending_approvals",
                    "label": f"{pending_approvals} طلب اعتماد معلق",
                    "link": "/approvals"
                })
        except Exception:
            pass

        # Leave requests pending
        try:
            pending_leaves = db.execute(text("""
                SELECT COUNT(*) FROM leave_requests WHERE status = 'pending'
            """)).scalar() or 0
            if pending_leaves > 0:
                tasks.append({
                    "type": "pending_leaves",
                    "label": f"{pending_leaves} طلب إجازة معلق",
                    "link": "/hr/leaves"
                })
        except Exception:
            pass

        # Overdue invoices
        try:
            overdue = db.execute(text("""
                SELECT COUNT(*) as cnt FROM invoices
                WHERE status IN ('pending', 'partially_paid')
                AND due_date < CURRENT_DATE AND invoice_type = 'sales'
            """)).scalar() or 0
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


@router.get("/widgets/cash-flow", dependencies=[Depends(require_permission("dashboard.view"))])
def widget_cash_flow(
    days: int = 30,
    branch_id: int = None,
    current_user=Depends(get_current_user)
):
    """Widget التدفق النقدي"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND ta.branch_id = :bid"
            params["bid"] = branch_id

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


@router.get("/widgets/available", dependencies=[Depends(require_permission("dashboard.view"))])
def get_available_widgets(current_user=Depends(get_current_user)):
    """قائمة الـ widgets المتاحة للإضافة"""
    return {"widgets": [
        {"id": "sales_today", "type": "stat", "title": "مبيعات اليوم", "default_w": 1, "default_h": 1},
        {"id": "sales_week", "type": "stat", "title": "مبيعات الأسبوع", "default_w": 1, "default_h": 1},
        {"id": "sales_month", "type": "stat", "title": "مبيعات الشهر", "default_w": 1, "default_h": 1},
        {"id": "expenses_month", "type": "stat", "title": "مصروفات الشهر", "default_w": 1, "default_h": 1},
        {"id": "cash_balance", "type": "stat", "title": "الرصيد النقدي", "default_w": 1, "default_h": 1},
        {"id": "profit_month", "type": "stat", "title": "صافي الربح", "default_w": 1, "default_h": 1},
        {"id": "financial_chart", "type": "chart", "title": "المبيعات والمصروفات", "default_w": 2, "default_h": 2},
        {"id": "top_products", "type": "chart", "title": "أفضل المنتجات", "default_w": 2, "default_h": 2},
        {"id": "cash_flow", "type": "chart", "title": "التدفق النقدي", "default_w": 2, "default_h": 2},
        {"id": "low_stock", "type": "list", "title": "المخزون المنخفض", "default_w": 2, "default_h": 1},
        {"id": "pending_tasks", "type": "list", "title": "المهام المعلقة", "default_w": 2, "default_h": 1},
        {"id": "recent_invoices", "type": "table", "title": "آخر الفواتير", "default_w": 2, "default_h": 2},
        {"id": "receivables_aging", "type": "chart", "title": "أعمار الذمم المدينة", "default_w": 2, "default_h": 1},
    ]}


# ═══════════════════════════════════════════════════════════════════════════════
# Industry-specific endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/industry-widgets", dependencies=[Depends(require_permission("dashboard.view"))])
def get_industry_widgets(current_user = Depends(get_current_user)):
    """Return industry-specific dashboard widgets based on company's industry type."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        industry_type = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
        ).scalar() or "general"
        
        widgets = _get_industry_widgets(industry_type, db)
        return {"industry_type": industry_type, "widgets": widgets}
    finally:
        db.close()


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
                     JOIN journal_entries j ON jl.journal_entry_id = j.id
                     WHERE j.entry_date >= date_trunc('month', CURRENT_DATE)), 0)
            """)).scalar() or 0
            widgets.append({"key": "food_cost_pct", "value": round(float(food_cost), 1), "label_ar": "نسبة تكلفة الطعام", "label_en": "Food Cost %", "icon": "🍽️", "target": 30})
            
        elif industry_type == "manufacturing":
            # WIP value — account 13010
            wip = db.execute(text("""
                SELECT COALESCE(SUM(
                    CASE WHEN a.account_number = '13010' THEN jl.debit - jl.credit ELSE 0 END
                ), 0) FROM journal_lines jl JOIN accounts a ON jl.account_id = a.id
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
                SELECT COALESCE(SUM(total), 0) FROM invoices 
                WHERE DATE(created_at) = CURRENT_DATE AND invoice_type = 'sale'
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


@router.get("/gl-rules", dependencies=[Depends(require_permission("accounting.view"))])
def get_company_gl_rules(current_user = Depends(get_current_user)):
    """Return GL auto-posting rules for the company's industry type."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
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
    finally:
        db.close()


@router.get("/coa-summary", dependencies=[Depends(require_permission("accounting.view"))])
def get_company_coa_summary(current_user = Depends(get_current_user)):
    """Return COA template summary for the company's industry type."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        industry_type = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'industry_type'")
        ).scalar() or "general"
        
        from services.industry_coa_templates import get_industry_coa_summary, normalize_industry_key
        industry_type = normalize_industry_key(industry_type)
        return get_industry_coa_summary(industry_type)
    finally:
        db.close()


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


@router.get("/analytics", dependencies=[Depends(require_permission("dashboard.analytics_view"))])
def list_analytics_dashboards(current_user: dict = Depends(get_current_user)):
    """List available analytics dashboards filtered by user role + branch."""
    company_id = get_user_company_id(current_user)
    db = get_db_connection(company_id)
    try:
        user_role = getattr(current_user, "role", "")
        try:
            rows = db.execute(text("""
                SELECT id, name, description, is_system, access_roles, branch_scope,
                       refresh_interval_minutes, created_at, created_by
                FROM analytics_dashboards
                ORDER BY is_system DESC, name
            """)).fetchall()
        except Exception as e:
            db.rollback()
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
    finally:
        db.close()


@router.get("/analytics/widget-data/{widget_id}", dependencies=[Depends(require_permission("dashboard.analytics_view"))])
def get_widget_data(widget_id: int, current_user: dict = Depends(get_current_user)):
    """Refresh data for a single widget."""
    company_id = get_user_company_id(current_user)
    branch_id = validate_branch_access(current_user, None)
    db = get_db_connection(company_id)
    try:
        widget = db.execute(text("""
            SELECT id, widget_type, title, data_source, filters
            FROM analytics_dashboard_widgets WHERE id = :id
        """), {"id": widget_id}).fetchone()

        if not widget:
            raise HTTPException(**http_error(404, "widget_not_found"))

        wd = dict(widget._mapping)
        widget_filters = wd.get("filters") or {}
        if branch_id:
            widget_filters["branch_id"] = branch_id

        return {
            "widget_id": widget_id,
            "data": _query_widget_data(db, wd["data_source"], widget_filters)
        }
    finally:
        db.close()


@router.get("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_view"))])
def get_analytics_dashboard(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Get a dashboard with its widget data queried from materialized views."""
    company_id = get_user_company_id(current_user)
    branch_id = validate_branch_access(current_user, None)
    db = get_db_connection(company_id)
    try:
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
            if branch_id:
                widget_filters["branch_id"] = branch_id
            wd["data"] = _query_widget_data(db, wd["data_source"], widget_filters)
            widget_list.append(wd)

        d["widgets"] = widget_list
        return d
    finally:
        db.close()


@router.post("/analytics", dependencies=[Depends(require_permission("dashboard.analytics_manage"))])
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
                    raise HTTPException(status_code=400, detail=f"Invalid widget_type: {w.widget_type}")
                if w.data_source not in VALID_DATA_SOURCES:
                    raise HTTPException(status_code=400, detail=f"Invalid data_source: {w.data_source}")
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
        return {"id": dashboard_id, "message": "Dashboard created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_create_failed"))
    finally:
        db.close()


@router.put("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_manage"))])
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
                    raise HTTPException(status_code=400, detail=f"Invalid widget_type: {w.widget_type}")
                if w.data_source not in VALID_DATA_SOURCES:
                    raise HTTPException(status_code=400, detail=f"Invalid data_source: {w.data_source}")
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
        return {"message": "Dashboard updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_update_failed"))
    finally:
        db.close()


@router.delete("/analytics/{dashboard_id}", dependencies=[Depends(require_permission("dashboard.analytics_manage"))])
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
        return {"message": "Dashboard deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete analytics dashboard: {e}")
        raise HTTPException(**http_error(500, "dashboard_delete_failed"))
    finally:
        db.close()
