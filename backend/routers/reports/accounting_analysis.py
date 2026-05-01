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

@router.get("/accounting/budget-vs-actual", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_budget_report(
    budget_id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة الميزانية التقديرية مع الفعلي"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        # 1. Get Budget info
        budget = db.execute(text("SELECT * FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
        if not budget:
             raise HTTPException(**http_error(404, "budget_not_found"))
             
        start_date = budget.start_date
        end_date = budget.end_date
        
        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        params = {"start": start_date, "end": end_date, "bid": budget_id}
        if branch_id: params["branch_id"] = branch_id

        # 2. Get Budget Items vs Actuals
        query = f"""
            SELECT 
                a.id as account_id, a.account_number, a.name, a.name_en,
                bi.planned_amount,
                COALESCE(actuals.balance, 0) as actual_amount
            FROM budget_items bi
            JOIN accounts a ON bi.account_id = a.id
            LEFT JOIN (
                SELECT 
                    jl.account_id,
                    SUM(CASE 
                        WHEN a2.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                        ELSE jl.credit - jl.debit
                    END) as balance
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a2 ON jl.account_id = a2.id
                WHERE je.entry_date BETWEEN :start AND :end
                  AND je.status = 'posted'
                  {branch_filter}
                GROUP BY jl.account_id
            ) as actuals ON bi.account_id = actuals.account_id
            WHERE bi.budget_id = :bid
            ORDER BY a.account_number
        """
        
        items = db.execute(text(query), params).fetchall()
        
        report_data = []
        for r in items:
            planned = Decimal(str(r.planned_amount or 0))
            actual = Decimal(str(r.actual_amount or 0))
            variance = planned - actual
            performance = (actual / planned * 100) if planned != 0 else 0
            
            report_data.append({
                "account_id": r.account_id,
                "account_number": r.account_number,
                "name": r.name,
                "name_en": r.name_en,
                "planned": planned,
                "actual": actual,
                "variance": variance,
                "performance_pct": performance
            })
            
        return {
            "budget": dict(budget._mapping),
            "data": report_data
        }
    finally:
        db.close()

def _get_cashflow_data(db, start_date, end_date, branch_id=None):
    """Internal helper: returns cash flow data for programmatic use."""
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    params = {"start": start_date, "end": end_date}
    if branch_id: params["branch_id"] = branch_id

    # 1. Get all Cash/Bank GL Account IDs
    # From treasury_accounts table
    treasury_gl_ids = [row[0] for row in db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE is_active = true")).fetchall() if row[0]]
    
    # From legacy codes (BOX, BNK)
    legacy_gl_ids = [row[0] for row in db.execute(text("SELECT id FROM accounts WHERE account_code IN ('BOX', 'BNK')")).fetchall()]
    
    # Combine and deduplicate
    all_cash_ids = list(set(treasury_gl_ids + legacy_gl_ids))
    
    if not all_cash_ids:
        return {
            "period": {"start": start_date, "end": end_date},
            "inflows": [], "outflows": [], "total_inflow": 0, "total_outflow": 0, "net_cash_flow": 0
        }

    # Use parameterized query for safety
    params["cash_ids"] = all_cash_ids

    # Inflows (Debit Cash/Bank)
    inflow_query = f"""
        SELECT 
            a_other.account_type, 
            a_other.name as category,
            SUM(jl_other.credit) as amount
        FROM journal_lines jl_cash
        JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
        JOIN accounts a_cash ON jl_cash.account_id = a_cash.id
        JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id
        JOIN accounts a_other ON jl_other.account_id = a_other.id
        WHERE a_cash.id = ANY(:cash_ids)
          AND jl_cash.debit > 0
          AND a_other.id != a_cash.id
          AND je.entry_date BETWEEN :start AND :end
          AND je.status = 'posted'
          {branch_filter}
        GROUP BY a_other.account_type, a_other.name
    """
    
    inflows = db.execute(text(inflow_query), params).fetchall()
    
    # Outflows (Credit Cash/Bank)
    outflow_query = f"""
        SELECT 
            a_other.account_type, 
            a_other.name as category,
            SUM(jl_other.debit) as amount
        FROM journal_lines jl_cash
        JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
        JOIN accounts a_cash ON jl_cash.account_id = a_cash.id
        JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id
        JOIN accounts a_other ON jl_other.account_id = a_other.id
        WHERE a_cash.id = ANY(:cash_ids)
          AND jl_cash.credit > 0
          AND a_other.id != a_cash.id
          AND je.entry_date BETWEEN :start AND :end
          AND je.status = 'posted'
          {branch_filter}
        GROUP BY a_other.account_type, a_other.name
    """
    
    outflows = db.execute(text(outflow_query), params).fetchall()
    
    return {
        "period": {"start": start_date, "end": end_date},
        "inflows": [dict(r._mapping) for r in inflows],
        "outflows": [dict(r._mapping) for r in outflows],
        "total_inflow": Decimal(str(sum((Decimal(str(r.amount or 0)) for r in inflows), Decimal(0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        "total_outflow": Decimal(str(sum((Decimal(str(r.amount or 0)) for r in outflows), Decimal(0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        "net_cash_flow": Decimal(str((sum((Decimal(str(r.amount or 0)) for r in inflows), Decimal(0)) - sum((Decimal(str(r.amount or 0)) for r in outflows), Decimal(0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
    }

@router.get("/accounting/cashflow", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_cashflow_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير التدفقات النقدية (مبسط)"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()
        return _get_cashflow_data(db, start_date, end_date, branch_id)
    finally:
        db.close()


@router.get("/accounting/cashflow-ias7", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_cashflow_ias7(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    قائمة التدفقات النقدية حسب معيار IAS 7
    Cash Flow Statement — Operating / Investing / Financing
    """
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        params = {"start": start_date, "end": end_date}
        if branch_id:
            params["branch_id"] = branch_id

        # Get Cash/Bank accounts
        treasury_gl_ids = [row[0] for row in db.execute(text(
            "SELECT gl_account_id FROM treasury_accounts WHERE is_active = true"
        )).fetchall() if row[0]]
        legacy_gl_ids = [row[0] for row in db.execute(text(
            "SELECT id FROM accounts WHERE account_code IN ('BOX', 'BNK')"
        )).fetchall()]
        cash_ids = list(set(treasury_gl_ids + legacy_gl_ids))
        if not cash_ids:
            cash_ids = [row[0] for row in db.execute(text(
                "SELECT id FROM accounts WHERE account_type IN ('cash', 'bank', 'current_asset') AND (name ILIKE '%نقد%' OR name ILIKE '%بنك%' OR name ILIKE '%صندوق%' OR name_en ILIKE '%cash%' OR name_en ILIKE '%bank%')"
            )).fetchall()]
        if not cash_ids:
            return {"period": {"start": start_date, "end": end_date}, "operating": {}, "investing": {}, "financing": {}, "net_change": 0, "opening_cash": 0, "closing_cash": 0}

        params["cash_ids"] = cash_ids

        # IAS 7 classification: based on actual account_type and account name heuristics
        # Only valid types: asset, liability, equity, revenue, expense

        def classify(account_type, account_name=''):
            at = (account_type or '').lower()
            name_lower = (account_name or '').lower()

            # Equity → Financing
            if at == 'equity':
                return 'financing'

            # Revenue and Expense → Operating
            if at in ('revenue', 'expense'):
                return 'operating'

            # Liability: check name for long-term/loan → Financing, else Operating
            if at == 'liability':
                if any(kw in name_lower for kw in ['قرض', 'loan', 'long', 'طويل', 'سند', 'bond']):
                    return 'financing'
                return 'operating'

            # Asset: check name for fixed asset/investment → Investing, else Operating
            if at == 'asset':
                if any(kw in name_lower for kw in ['أصل ثابت', 'fixed', 'استثمار', 'invest', 'عقار', 'property', 'معدات', 'equipment', 'إهلاك', 'depreciation', 'أراضي', 'land']):
                    return 'investing'
                return 'operating'

            return 'operating'

        # Inflows (debit to cash accounts)
        inflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   SUM(jl_other.credit) as amount
            FROM journal_lines jl_cash
            JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
            JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id AND jl_other.account_id != jl_cash.account_id
            JOIN accounts a_other ON jl_other.account_id = a_other.id
            WHERE jl_cash.account_id = ANY(:cash_ids)
              AND jl_cash.debit > 0
              AND je.entry_date BETWEEN :start AND :end
              AND je.status = 'posted'
              {branch_filter}
            GROUP BY a_other.account_type, a_other.name
        """), params).fetchall()

        # Outflows (credit to cash accounts)
        outflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   SUM(jl_other.debit) as amount
            FROM journal_lines jl_cash
            JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
            JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id AND jl_other.account_id != jl_cash.account_id
            JOIN accounts a_other ON jl_other.account_id = a_other.id
            WHERE jl_cash.account_id = ANY(:cash_ids)
              AND jl_cash.credit > 0
              AND je.entry_date BETWEEN :start AND :end
              AND je.status = 'posted'
              {branch_filter}
            GROUP BY a_other.account_type, a_other.name
        """), params).fetchall()

        # Opening cash balance
        opening_cash = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE jl.account_id = ANY(:cash_ids)
              AND je.entry_date < :start
              AND je.status = 'posted'
              {branch_filter}
        """), params).scalar() or 0

        # Build activities
        activities = {'operating': [], 'investing': [], 'financing': []}
        totals = {'operating': Decimal('0'), 'investing': Decimal('0'), 'financing': Decimal('0')}

        for row in inflows:
            activity = classify(row.account_type, row.account_name)
            amt = Decimal(str(row.amount or 0))
            activities[activity].append({
                "description": row.account_name,
                "account_type": row.account_type,
                "amount": Decimal(str(amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                "direction": "inflow"
            })
            totals[activity] += amt

        for row in outflows:
            activity = classify(row.account_type, row.account_name)
            amt = Decimal(str(row.amount or 0))
            activities[activity].append({
                "description": row.account_name,
                "account_type": row.account_type,
                "amount": Decimal(str((-amt).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                "direction": "outflow"
            })
            totals[activity] -= amt

        net_change = totals['operating'] + totals['investing'] + totals['financing']

        return {
            "period": {"start": start_date, "end": end_date},
            "operating": {
                "items": activities['operating'],
                "total": Decimal(str(totals['operating'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "investing": {
                "items": activities['investing'],
                "total": Decimal(str(totals['investing'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "financing": {
                "items": activities['financing'],
                "total": Decimal(str(totals['financing'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "net_change": Decimal(str(net_change.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
            "opening_cash": Decimal(str(Decimal(str(opening_cash)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
            "closing_cash": Decimal(str((Decimal(str(opening_cash)) + net_change).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        }
    finally:
        db.close()


@router.get("/accounting/fx-gain-loss", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_fx_gain_loss_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    currency: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير فروق أسعار العملة — الأرباح والخسائر المحققة وغير المحققة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params: dict = {"start": start_date, "end": end_date}
        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id
        currency_filter = "AND je.currency = :currency" if currency else ""
        if currency:
            params["currency"] = currency

        # Realized FX gain/loss: journal entries tagged as FX revaluation
        realized = db.execute(text(f"""
            SELECT
                je.id,
                je.entry_date,
                je.reference,
                je.currency,
                je.description,
                SUM(CASE WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit ELSE 0 END) as fx_gain,
                SUM(CASE WHEN a.account_type = 'expense' THEN jl.debit - jl.credit ELSE 0 END) as fx_loss
            FROM journal_entries je
            JOIN journal_lines jl ON je.id = jl.journal_entry_id
            JOIN accounts a ON jl.account_id = a.id
            WHERE je.status = 'posted'
              AND je.entry_date BETWEEN :start AND :end
              AND (
                  LOWER(je.description) LIKE '%%fx%%' OR
                  LOWER(je.description) LIKE '%%revaluation%%' OR
                  LOWER(je.description) LIKE '%%فروق عملة%%' OR
                  LOWER(je.reference) LIKE '%%fx%%' OR
                  je.source IN ('fx_revaluation', 'fx_adjustment')
              )
              {branch_filter}
            GROUP BY je.id, je.entry_date, je.reference, je.currency, je.description
            ORDER BY je.entry_date
        """), params).fetchall()

        # Get base currency
        base_ccy = db.execute(text(
            "SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1"
        )).scalar() or 'SAR'

        # FX amounts from foreign currency invoices difference
        invoice_fx = db.execute(text(f"""
            SELECT
                i.currency,
                COUNT(*) as invoice_count,
                SUM(i.total) as fc_total,
                SUM(i.total * COALESCE(i.exchange_rate, 1.0)) as lc_total,
                CASE WHEN i.invoice_type = 'sales' THEN 'receivable' ELSE 'payable' END as direction
            FROM invoices i
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              AND COALESCE(i.exchange_rate, 1.0) != 1.0
              {currency_filter}
            GROUP BY i.currency, i.invoice_type
            ORDER BY i.currency
        """), {**params, "base_ccy": base_ccy}).fetchall()

        # Unrealized FX: open foreign currency invoices at current rates
        rate_rows = db.execute(text(
            "SELECT code, COALESCE(current_rate, 1.0) as rate FROM currencies WHERE is_active = TRUE"
        )).fetchall()
        current_rates = {r.code: Decimal(str(r.rate)) for r in rate_rows}

        open_invoices = db.execute(text(f"""
            SELECT
                i.invoice_number, i.invoice_type, i.currency,
                COALESCE(i.exchange_rate, 1.0) as booked_rate,
                (i.total - COALESCE(i.paid_amount, 0)) as open_fc_amount,
                p.name as party_name
            FROM invoices i
            LEFT JOIN parties p ON p.id = i.party_id
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
              {currency_filter}
        """), {**params, "base_ccy": base_ccy}).fetchall()

        unrealized_list = []
        total_unrealized_gain = Decimal("0")
        total_unrealized_loss = Decimal("0")
        for inv in open_invoices:
            booked = Decimal(str(inv.booked_rate))
            current = current_rates.get(inv.currency, booked)
            open_fc = Decimal(str(inv.open_fc_amount or 0))
            diff = open_fc * (current - booked)
            if inv.invoice_type == 'purchase':
                diff = -diff
            unrealized_list.append({
                "invoice_number": inv.invoice_number,
                "party": inv.party_name,
                "invoice_type": inv.invoice_type,
                "currency": inv.currency,
                "open_fc_amount": round(open_fc, 2),
                "booked_rate": booked,
                "current_rate": current,
                "unrealized_fx": round(diff, 2),
            })
            if diff >= 0:
                total_unrealized_gain += diff
            else:
                total_unrealized_loss += abs(diff)

        realized_list = [{
            "entry_id": r.id,
            "date": r.entry_date,
            "reference": r.reference,
            "currency": r.currency,
            "notes": r.description,
            "fx_gain": Decimal(str(r.fx_gain or 0)),
            "fx_loss": Decimal(str(r.fx_loss or 0)),
            "net": Decimal(str((r.fx_gain or 0) - (r.fx_loss or 0))),
        } for r in realized]

        exposure_list = [{
            "currency": r.currency,
            "direction": r.direction,
            "invoice_count": r.invoice_count,
            "fc_total": Decimal(str(r.fc_total or 0)),
            "lc_total": Decimal(str(r.lc_total or 0)),
        } for r in invoice_fx]

        total_gain = sum(r["fx_gain"] for r in realized_list)
        total_loss = sum(r["fx_loss"] for r in realized_list)

        return {
            "period": {"start": start_date, "end": end_date},
            "realized_entries": realized_list,
            "currency_exposure": exposure_list,
            "unrealized": {
                "invoices": unrealized_list,
                "total_unrealized_gain": round(total_unrealized_gain, 2),
                "total_unrealized_loss": round(total_unrealized_loss, 2),
                "net_unrealized": round(total_unrealized_gain - total_unrealized_loss, 2),
            },
            "summary": {
                "total_fx_gain": round(total_gain + total_unrealized_gain, 2),
                "total_fx_loss": round(total_loss + total_unrealized_loss, 2),
                "net_fx": round((total_gain + total_unrealized_gain) - (total_loss + total_unrealized_loss), 2),
            }
        }
    finally:
        db.close()


@router.get("/accounting/horizontal-analysis", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def horizontal_analysis(
    periods: str = "2026-01-01:2026-12-31,2025-01-01:2025-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحليل أفقي — اتجاه الأرقام عبر الفترات"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(status_code=400, detail="يجب فترتين على الأقل")

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""

        all_accounts = db.execute(text("SELECT id, account_number, name, name_en, account_type FROM accounts ORDER BY account_number")).fetchall()

        results = []
        for acct in all_accounts:
            a = acct._mapping
            period_balances = []
            for p in parsed:
                params = {"acct": a["id"], "start": p["start"], "end": p["end"]}
                if branch_id:
                    params["branch_id"] = branch_id
                bal = db.execute(text(f"""
                    SELECT COALESCE(SUM(
                        CASE WHEN a.account_type IN ('liability', 'equity', 'revenue')
                             THEN jl.credit - jl.debit
                             ELSE jl.debit - jl.credit
                        END
                    ), 0) as net
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    WHERE jl.account_id = :acct AND je.entry_date BETWEEN :start AND :end
                      AND je.status = 'posted' {branch_filter}
                """), params).scalar()
                period_balances.append(Decimal(str(bal)))

            if not any(abs(b) > 0.01 for b in period_balances):
                continue

            changes = []
            for i in range(len(period_balances) - 1):
                curr, prev = period_balances[i], period_balances[i + 1]
                abs_change = curr - prev
                pct_change = (abs_change / abs(prev) * 100) if prev != 0 else None
                changes.append({"absolute": round(abs_change, 2), "percentage": round(pct_change, 2) if pct_change is not None else None})

            results.append({
                "account_number": a["account_number"], "name": a["name"],
                "account_type": a["account_type"], "periods": period_balances, "changes": changes,
                "trend": "increasing" if all(period_balances[i] >= period_balances[i+1] for i in range(len(period_balances)-1)) else
                         "decreasing" if all(period_balances[i] <= period_balances[i+1] for i in range(len(period_balances)-1)) else "mixed"
            })

        return {"report_name": "التحليل الأفقي", "periods": [f"{p['start']}→{p['end']}" for p in parsed], "data": results}
    finally:
        db.close()


@router.get("/accounting/financial-ratios", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def financial_ratios(
    as_of_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحليل النسب المالية — سيولة / ربحية / ملاءة"""
    branch_id = validate_branch_access(current_user, branch_id)
    d = datetime.strptime(as_of_date, "%Y-%m-%d").date() if as_of_date else date.today()
    start_of_year = d.replace(month=1, day=1)
    db = get_db_connection(current_user.company_id)
    try:
        def acct_sum(type_like, start=None, end=None):
            params = {}
            date_filter = ""
            if start and end:
                date_filter = "AND je.entry_date BETWEEN :start AND :end"
                params["start"] = start
                params["end"] = end
            br = "AND je.branch_id = :branch_id" if branch_id else ""
            if branch_id:
                params["branch_id"] = branch_id
            return Decimal(str(db.execute(text(f"""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_type = :atype AND je.status = 'posted' {date_filter} {br}
            """), {**params, "atype": type_like}).scalar()))

        def code_sum(like_pattern, start=None, end=None):
            params = {"p": like_pattern}
            df = ""
            if start and end:
                df = "AND je.entry_date BETWEEN :start AND :end"
                params["start"] = start
                params["end"] = end
            br = "AND je.branch_id = :branch_id" if branch_id else ""
            if branch_id:
                params["branch_id"] = branch_id
            return Decimal(str(db.execute(text(f"""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_number LIKE :p AND je.status='posted' {df} {br}
            """), params).scalar()))

        # Balance Sheet items (cumulative to date)
        total_assets = acct_sum("asset", None, None)
        current_assets = code_sum("11%")
        fixed_assets = code_sum("12%")
        total_liabilities = abs(acct_sum("liability"))
        current_liabilities = abs(code_sum("21%"))
        equity = abs(acct_sum("equity"))

        # P&L items (YTD)
        revenue = abs(acct_sum("revenue", start_of_year, d))
        expenses = acct_sum("expense", start_of_year, d)
        net_income = revenue - expenses
        cogs = code_sum("51%", start_of_year, d)
        gross_profit = revenue - cogs

        # Inventory
        inventory = code_sum("1103%")  # net balance
        ar = code_sum("1102%")
        ap = abs(code_sum("2101%"))

        # Ratios
        ratios = {
            "liquidity": {
                "current_ratio": round(current_assets / current_liabilities, 2) if current_liabilities else None,
                "quick_ratio": round((current_assets - abs(inventory)) / current_liabilities, 2) if current_liabilities else None,
                "cash_ratio": round(code_sum("1101%") / current_liabilities, 2) if current_liabilities else None,
            },
            "profitability": {
                "gross_profit_margin": round(gross_profit / revenue * 100, 2) if revenue else None,
                "net_profit_margin": round(net_income / revenue * 100, 2) if revenue else None,
                "return_on_assets": round(net_income / total_assets * 100, 2) if total_assets else None,
                "return_on_equity": round(net_income / equity * 100, 2) if equity else None,
            },
            "solvency": {
                "debt_to_equity": round(total_liabilities / equity, 2) if equity else None,
                "debt_to_assets": round(total_liabilities / total_assets, 2) if total_assets else None,
                "equity_ratio": round(equity / total_assets * 100, 2) if total_assets else None,
            },
            "activity": {
                "ar_turnover": round(revenue / ar, 2) if ar else None,
                "ar_days": round(365 / (revenue / ar), 1) if ar and revenue else None,
                "ap_turnover": round(cogs / ap, 2) if ap else None,
                "ap_days": round(365 / (cogs / ap), 1) if ap and cogs else None,
                "inventory_turnover": round(cogs / abs(inventory), 2) if inventory else None,
                "inventory_days": round(365 / (cogs / abs(inventory)), 1) if inventory and cogs else None,
            }
        }

        return {
            "report_name": "تحليل النسب المالية",
            "as_of_date": str(d),
            "summary": {
                "total_assets": round(total_assets, 2), "current_assets": round(current_assets, 2),
                "total_liabilities": round(total_liabilities, 2), "equity": round(equity, 2),
                "revenue_ytd": round(revenue, 2), "net_income_ytd": round(net_income, 2),
            },
            "ratios": ratios,
        }
    finally:
        db.close()


@router.get("/accounting/cost-center-report", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def cost_center_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير مراكز التكلفة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        params = {"start": s, "end": e}
        br = "AND je.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        rows = db.execute(text(f"""
            SELECT cc.id, cc.center_name, cc.center_code,
                   COALESCE(SUM(jl.debit), 0) as total_debit,
                   COALESCE(SUM(jl.credit), 0) as total_credit,
                   COALESCE(SUM(jl.debit - jl.credit), 0) as net
            FROM cost_centers cc
            LEFT JOIN journal_lines jl ON cc.id = jl.cost_center_id
            LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
                AND je.entry_date BETWEEN :start AND :end AND je.status = 'posted' {br}
            GROUP BY cc.id, cc.center_name, cc.center_code
            ORDER BY net DESC
        """), params).fetchall()

        return {
            "report_name": "تقرير مراكز التكلفة",
            "period": {"start": str(s), "end": str(e)},
            "data": [dict(r._mapping) for r in rows],
            "total_net": sum(Decimal(str(r.net)) for r in rows),
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-104: Inventory Reports
# ═══════════════════════════════════════════════════════════

@router.get("/accounting/profit-loss/detailed", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def detailed_profit_loss(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = "customer",  # customer, product, category
    branch_id: Optional[int] = None,
    format: Optional[str] = None,  # excel, pdf, None=json
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير أرباح وخسائر تفصيلي — مجمَّع حسب العميل أو المنتج أو فئة المنتج.
    Detailed P&L Report — grouped by customer, product, or product category.
    Shows Revenue, COGS, Gross Profit, Gross Margin% per group.
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()

        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        params = {"start": s_date, "end": e_date}
        if branch_id:
            params["branch_id"] = branch_id

        if group_by == "product":
            group_col = "COALESCE(p.product_name, il.description, 'غير محدد')"
            group_label = "product_name"
            join_extra = "LEFT JOIN products p ON il.product_id = p.id"
        elif group_by == "category":
            group_col = "COALESCE(pc.name, 'غير مصنف')"
            group_label = "category"
            join_extra = """LEFT JOIN products p ON il.product_id = p.id
                           LEFT JOIN product_categories pc ON p.category_id = pc.id"""
        else:  # customer
            group_col = "COALESCE(pa.name, c.name, 'غير محدد')"
            group_label = "customer_name"
            join_extra = """LEFT JOIN parties pa ON i.party_id = pa.id
                           LEFT JOIN customers c ON i.party_id = c.id"""

        # Revenue from sales invoices
        revenue_query = f"""
            SELECT {group_col} as group_name,
                   SUM(il.quantity * il.unit_price - COALESCE(il.discount, 0)) as revenue,
                   SUM(il.quantity * COALESCE(p2.cost_price, 0)) as cogs,
                   COUNT(DISTINCT i.id) as invoice_count,
                   SUM(il.quantity) as total_qty
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            LEFT JOIN products p2 ON il.product_id = p2.id
            {join_extra}
            WHERE i.invoice_type = 'sales'
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              {branch_filter}
            GROUP BY {group_col}
            ORDER BY revenue DESC
        """

        rows = db.execute(text(revenue_query), params).fetchall()

        report_rows = []
        total_revenue = 0
        total_cogs = 0

        for r in rows:
            revenue = Decimal(str(r.revenue or 0))
            cogs = Decimal(str(r.cogs or 0))
            gross_profit = revenue - cogs
            margin = round((gross_profit / revenue * 100), 1) if revenue > 0 else 0

            total_revenue += revenue
            total_cogs += cogs

            report_rows.append({
                group_label: r.group_name or "غير محدد",
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_margin_pct": margin,
                "invoice_count": r.invoice_count or 0,
                "total_qty": float(r.total_qty or 0),
            })

        total_gp = total_revenue - total_cogs
        overall_margin = round((total_gp / total_revenue * 100), 1) if total_revenue > 0 else 0

        result = {
            "report_name": f"Detailed P&L by {group_by.title()} — أرباح وخسائر تفصيلي",
            "period": {"start": str(s_date), "end": str(e_date)},
            "group_by": group_by,
            "details": report_rows,
            "totals": {
                "total_revenue": round(total_revenue, 2),
                "total_cogs": round(total_cogs, 2),
                "total_gross_profit": round(total_gp, 2),
                "overall_gross_margin_pct": overall_margin,
            }
        }

        if format in ("excel", "pdf"):
            export_data = []
            for r in report_rows:
                export_data.append({
                    f"{'العميل' if group_by == 'customer' else 'المنتج' if group_by == 'product' else 'الفئة'} / {group_by.title()}": r[group_label],
                    "الإيرادات / Revenue": r["revenue"],
                    "تكلفة المبيعات / COGS": r["cogs"],
                    "الربح الإجمالي / Gross Profit": r["gross_profit"],
                    "هامش الربح % / Margin %": f"{r['gross_margin_pct']}%",
                    "عدد الفواتير / Invoices": r["invoice_count"],
                })
            columns = list(export_data[0].keys()) if export_data else []

            # Generate chart for top items
            chart_image = None
            try:
                top_items = report_rows[:10]
                if top_items:
                    chart_labels = [r[group_label][:20] for r in top_items]
                    chart_image = generate_chart_image(
                        "bar", chart_labels,
                        [
                            {"label": "Revenue / الإيرادات", "data": [r["revenue"] for r in top_items], "color": "#2563EB"},
                            {"label": "COGS / التكلفة", "data": [r["cogs"] for r in top_items], "color": "#DC2626"},
                            {"label": "Gross Profit / الربح", "data": [r["gross_profit"] for r in top_items], "color": "#16A34A"},
                        ],
                        title=f"Detailed P&L by {group_by.title()} — أرباح وخسائر تفصيلي"
                    )
            except Exception:
                pass

            if format == "excel":
                buffer = generate_excel_with_chart(export_data, columns, sheet_name=f"P&L by {group_by}",
                    chart_type="bar", chart_config={"title": f"P&L by {group_by}", "x_col": 0, "y_cols": [1, 2, 3]})
                return create_export_response(buffer, f"detailed_pl_{group_by}_{s_date}_{e_date}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                pdf_data = [columns] + [[str(row.get(c, '')) for c in columns] for row in export_data]
                buffer = generate_pdf(pdf_data,
                    title=f"Detailed P&L by {group_by.title()} — تقرير أرباح وخسائر تفصيلي",
                    subtitle=f"{s_date} → {e_date}",
                    chart_image=chart_image, orientation="landscape")
                return create_export_response(buffer, f"detailed_pl_{group_by}_{s_date}_{e_date}.pdf", "application/pdf")

        return result
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales Commission Report (تقرير عمولات المبيعات)
# ═══════════════════════════════════════════════════════════

