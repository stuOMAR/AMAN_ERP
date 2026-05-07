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
from utils.permissions import require_permission, require_sensitive_permission, validate_branch_access
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/kpi/dashboard", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
def get_kpi_dashboard(current_user=Depends(get_current_user)):
    """لوحة مؤشرات الأداء الرئيسية"""
    db = get_db_connection(current_user.company_id)
    try:
        kpis = {}

        # Revenue KPI (with exchange_rate conversion)
        rev = db.execute(text("""
            SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as current_month,
                   (SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) FROM invoices
                    WHERE invoice_type = 'sales' AND status != 'cancelled'
                      AND invoice_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                      AND invoice_date < date_trunc('month', CURRENT_DATE)) as last_month
            FROM invoices
            WHERE invoice_type = 'sales' AND status != 'cancelled'
              AND invoice_date >= date_trunc('month', CURRENT_DATE)
        """)).fetchone()
        if rev:
            r = dict(rev._mapping)
            current = Decimal(str(r.get("current_month", 0)))
            last = Decimal(str(r.get("last_month", 0)))
            kpis["revenue"] = {
                "value": current, "previous": last,
                "change_pct": round((current - last) / last * 100, 2) if last else 0
            }

        # Expenses KPI
        exp = db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) as current_month
            FROM expenses WHERE expense_date >= date_trunc('month', CURRENT_DATE)
        """)).fetchone()
        kpis["expenses"] = {"value": Decimal(str(dict(exp._mapping).get("current_month", 0)))} if exp else {"value": 0}

        # Outstanding receivables (converted to base)
        ar = db.execute(text("""
            SELECT COALESCE(SUM((total - COALESCE(paid_amount, 0)) * COALESCE(exchange_rate, 1)), 0) as total
            FROM invoices WHERE status IN ('unpaid', 'partial') AND invoice_type = 'sales'
        """)).fetchone()
        kpis["accounts_receivable"] = {"value": Decimal(str(dict(ar._mapping).get("total", 0)))} if ar else {"value": 0}

        # Outstanding payables (converted to base)
        ap = db.execute(text("""
            SELECT COALESCE(SUM((total - COALESCE(paid_amount, 0)) * COALESCE(exchange_rate, 1)), 0) as total
            FROM invoices WHERE status IN ('unpaid', 'partial') AND invoice_type = 'purchase'
        """)).fetchone()
        kpis["accounts_payable"] = {"value": Decimal(str(dict(ap._mapping).get("total", 0)))} if ap else {"value": 0}

        # Cash balance — pulled from GL (journal_lines) using company_settings
        # acc_map_cash_main + acc_map_bank so the KPI always matches the TB.
        cash = db.execute(text("""
            WITH cash_accs AS (
                SELECT CAST(setting_value AS INTEGER) AS account_id
                FROM company_settings
                WHERE setting_key IN ('acc_map_cash_main', 'acc_map_bank')
                  AND setting_value ~ '^[0-9]+$'
            )
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id IN (SELECT account_id FROM cash_accs)
              AND je.status = 'posted'
        """)).fetchone()
        kpis["cash_balance"] = {"value": Decimal(str(dict(cash._mapping).get("balance", 0)))} if cash else {"value": 0}

        # Inventory value (using cost_price from products)
        inv = db.execute(text("""
            SELECT COALESCE(SUM(i.quantity * p.cost_price), 0) as total_value,
                   COUNT(DISTINCT p.id) as total_items
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = TRUE
        """)).fetchone()
        if inv:
            d = dict(inv._mapping)
            kpis["inventory"] = {"value": Decimal(str(d.get("total_value", 0))), "items": int(d.get("total_items", 0))}

        # HR headcount
        hr = db.execute(text("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'active' THEN 1 END) as active
            FROM employees
        """)).fetchone()
        if hr:
            d = dict(hr._mapping)
            kpis["employees"] = {"total": int(d.get("total", 0)), "active": int(d.get("active", 0))}

        return kpis
    except Exception as e:
        logger.error(f"KPI Dashboard error: {e}")
        return {}
    finally:
        db.close()


# ============================================================
#   10 INDUSTRY-SPECIFIC REPORT ENDPOINTS
#   تقارير صناعية متخصصة ببيانات حقيقية من قاعدة البيانات
# ============================================================

