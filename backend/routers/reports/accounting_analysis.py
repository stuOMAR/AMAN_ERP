"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import Request, APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, resolve_branch_scope, branch_scope_filter_from_scope
from utils.exports import generate_chart_image, generate_excel_with_chart, generate_pdf, create_export_response

logger = logging.getLogger(__name__)
router = APIRouter()
_D1 = Decimal("0.1")
_D2 = Decimal("0.01")


def _q(value, places: Decimal = _D2) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(places, rounding=ROUND_HALF_UP)


def _decimal_str(value, places: Decimal = _D2) -> str:
    return format(_q(value, places), "f")


def _scoped_branch_filter(branch_id, column, params, *, branch_scope=None):
    if branch_scope is not None:
        return branch_scope_filter_from_scope(branch_scope, column, params)
    if branch_id:
        params["branch_id"] = branch_id
        return f"AND {column} = :branch_id"
    return ""


def _parse_periods(periods_str: str):
    """Parse 'start:end,start:end' or 'start:end' strings into list of dicts"""
    result = []
    for part in periods_str.split(","):
        part = part.strip()
        if ":" in part:
            s, e = part.split(":", 1)
            result.append({"start": s.strip(), "end": e.strip()})
        else:
            result.append({"start": f"{part.strip()[:4]}-01-01", "end": part.strip()})
    return result


@router.get("/accounting/budget-vs-actual", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_budget_report(
    budget_id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة الميزانية التقديرية مع الفعلي"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        # 1. Get Budget info
        budget = db.execute(text("SELECT * FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
        if not budget:
             raise HTTPException(**http_error(404, "budget_not_found"))
             
        start_date = budget.start_date
        end_date = budget.end_date
        
        params = {"start": start_date, "end": end_date, "bid": budget_id}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

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

def _get_cashflow_data(db, start_date, end_date, branch_id=None, branch_scope=None):
    """Internal helper: returns cash flow data for programmatic use."""
    params = {"start": start_date, "end": end_date}
    branch_filter = _scoped_branch_filter(branch_id, "je.branch_id", params, branch_scope=branch_scope)

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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()
        return _get_cashflow_data(db, start_date, end_date, branch_scope=branch_scope)
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

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

        # IAS 7 classification: prefer explicit per-account override
        # (T10.1 P1 #84 — accounts.cash_flow_classification), then
        # fall back to a heuristic on type + Arabic/English keywords.
        # Only valid types: asset, liability, equity, revenue, expense.

        def classify(account_type, account_name='', explicit=None):
            if explicit in ('operating', 'investing', 'financing'):
                return explicit
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

        # Inflows (debit to cash accounts) — also pulls explicit
        # ``cash_flow_classification`` for P1 #84 override.
        inflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   a_other.cash_flow_classification as explicit_class,
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
            GROUP BY a_other.account_type, a_other.name, a_other.cash_flow_classification
        """), params).fetchall()

        # Outflows (credit to cash accounts)
        outflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   a_other.cash_flow_classification as explicit_class,
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
            GROUP BY a_other.account_type, a_other.name, a_other.cash_flow_classification
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
            activity = classify(row.account_type, row.account_name, getattr(row, 'explicit_class', None))
            amt = Decimal(str(row.amount or 0))
            activities[activity].append({
                "description": row.account_name,
                "account_type": row.account_type,
                "amount": Decimal(str(amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                "direction": "inflow"
            })
            totals[activity] += amt

        for row in outflows:
            activity = classify(row.account_type, row.account_name, getattr(row, 'explicit_class', None))
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params: dict = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)
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
                SUM(i.total * COALESCE(i.exchange_rate, 1::numeric)) as lc_total,
                CASE WHEN i.invoice_type = 'sales' THEN 'receivable' ELSE 'payable' END as direction
            FROM invoices i
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              AND COALESCE(i.exchange_rate, 1::numeric) != 1::numeric
              {currency_filter}
            GROUP BY i.currency, i.invoice_type
            ORDER BY i.currency
        """), {**params, "base_ccy": base_ccy}).fetchall()

        # Unrealized FX: open foreign currency invoices at current rates
        rate_rows = db.execute(text(
            "SELECT code, COALESCE(current_rate, 1::numeric) as rate FROM currencies WHERE is_active = TRUE"
        )).fetchall()
        current_rates = {r.code: Decimal(str(r.rate)) for r in rate_rows}

        open_invoices = db.execute(text(f"""
            SELECT
                i.invoice_number, i.invoice_type, i.currency,
                COALESCE(i.exchange_rate, 1::numeric) as booked_rate,
                (i.total - COALESCE(i.paid_amount, 0)) as open_fc_amount,
                p.name as party_name
            FROM invoices i
            LEFT JOIN parties p ON p.id = i.party_id
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > :min_open_amount
              {currency_filter}
        """), {**params, "base_ccy": base_ccy, "min_open_amount": Decimal("0.01")}).fetchall()

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
                "open_fc_amount": _q(open_fc),
                "booked_rate": booked,
                "current_rate": current,
                "unrealized_fx": _q(diff),
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
                "total_unrealized_gain": _q(total_unrealized_gain),
                "total_unrealized_loss": _q(total_unrealized_loss),
                "net_unrealized": _q(total_unrealized_gain - total_unrealized_loss),
            },
            "summary": {
                "total_fx_gain": _q(total_gain + total_unrealized_gain),
                "total_fx_loss": _q(total_loss + total_unrealized_loss),
                "net_fx": _q((total_gain + total_unrealized_gain) - (total_loss + total_unrealized_loss)),
            }
        }
    finally:
        db.close()


@router.get("/accounting/horizontal-analysis", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def horizontal_analysis(request: Request, 
    periods: str = "2026-01-01:2026-12-31,2025-01-01:2025-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحليل أفقي — اتجاه الأرقام عبر الفترات.

    T10.1 P1 #82 / #110h — old implementation issued one query per
    (account × period) which on a chart of 200 accounts and 4 periods
    means 800 round-trips and could freeze the system. We now compute
    all balances in a single query keyed by ``(account_id, period_idx)``
    and pivot in Python, and we wrap each period sub-query in
    try/except so a single failure does not silently drop a row.
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(**http_error(400, "must_be_two_lines", request))

        all_accounts = db.execute(text("SELECT id, account_number, name, name_en, account_type FROM accounts ORDER BY account_number")).fetchall()

        # P1 #82 — one query per period (instead of per account × period).
        # We assemble a {(account_id, period_idx): balance} map.
        balance_map: Dict[tuple, Decimal] = {}
        for idx, p in enumerate(parsed):
            params = {"start": p["start"], "end": p["end"]}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)
            try:
                rows = db.execute(text(f"""
                    SELECT jl.account_id,
                           COALESCE(SUM(
                               CASE WHEN a.account_type IN ('liability', 'equity', 'revenue')
                                    THEN jl.credit - jl.debit
                                    ELSE jl.debit - jl.credit
                               END
                           ), 0) AS net
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    WHERE je.entry_date BETWEEN :start AND :end
                      AND je.status = 'posted' {branch_filter}
                    GROUP BY jl.account_id
                """), params).fetchall()
                for r in rows:
                    balance_map[(r.account_id, idx)] = Decimal(str(r.net))
            except HTTPException:
                # F-NEW-294 (R-RECOVERABLE-500, Req 8.10): keep
                # caller-recoverable errors at their original 4xx status
                # rather than collapsing through to 500.
                raise
            except Exception as exc:
                # P1 #110h — surface the failure in the response instead
                # of silently producing a partial report.
                logger.exception("horizontal_analysis: period %s failed: %s", idx, exc)
                # F-NEW-294: a per-period SQL failure is a recoverable
                # validation/data error from the caller's viewpoint (bad
                # date range, missing branch, etc.). Map to HTTP 400
                # with a structured body instead of leaking 500.
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "horizontal_analysis_period_failed",
                        "period_index": idx + 1,
                        "reason": str(exc),
                    },
                )

        results = []
        for acct in all_accounts:
            a = acct._mapping
            period_balances = [balance_map.get((a["id"], i), Decimal("0")) for i in range(len(parsed))]

            if not any(b.copy_abs() > _D2 for b in period_balances):
                continue

            changes = []
            for i in range(len(period_balances) - 1):
                curr, prev = period_balances[i], period_balances[i + 1]
                abs_change = curr - prev
                pct_change = (abs_change / prev.copy_abs() * Decimal("100")) if prev != 0 else None
                changes.append({
                    "absolute": _decimal_str(abs_change),
                    "percentage": _decimal_str(pct_change) if pct_change is not None else None,
                })

            results.append({
                "account_number": a["account_number"], "name": a["name"],
                "account_type": a["account_type"], "periods": [_decimal_str(v) for v in period_balances], "changes": changes,
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
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
            br = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)
            return Decimal(str(db.execute(text(f"""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_type = :atype AND je.status = 'posted' {date_filter} {br}
            """), {**params, "atype": type_like}).scalar()))

        def code_sum(like_pattern, start=None, end=None):
            """Sum balances for accounts matching a code prefix.

            Uses account_classifications (aggregation_hint) when available,
            falling back to account_number LIKE for legacy compatibility.
            """
            # Try classifier-based lookup first
            try:
                hint = like_pattern.replace("%", "")
                hint_map = {"11": "current_asset", "12": "fixed_asset",
                            "21": "current_liability", "22": "long_term_liability"}
                hint_key = hint_map.get(hint)
                if hint_key:
                    acc_rows = db.execute(text("""
                        SELECT account_id FROM account_classifications
                        WHERE tenant_id = current_setting('app.tenant_id', true)::bigint
                          AND aggregation_hint = :hint AND is_active = true
                    """), {"hint": hint_key}).fetchall()
                    if acc_rows:
                        acc_ids = [r[0] for r in acc_rows]
                        params = {"acc_ids": acc_ids}
                        df = ""
                        if start and end:
                            df = "AND je.entry_date BETWEEN :start AND :end"
                            params["start"] = start
                            params["end"] = end
                        br = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)
                        return Decimal(str(db.execute(text(f"""
                            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                            FROM journal_lines jl
                            JOIN journal_entries je ON jl.journal_entry_id = je.id
                            WHERE jl.account_id = ANY(:acc_ids) AND je.status='posted' {df} {br}
                        """), params).scalar()))
            except Exception:
                pass  # fall through to legacy code-range

            # Legacy fallback: code-range check
            params = {"p": like_pattern}
            df = ""
            if start and end:
                df = "AND je.entry_date BETWEEN :start AND :end"
                params["start"] = start
                params["end"] = end
            br = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)
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
        code_sum("12%")
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
                "current_ratio": _q(current_assets / current_liabilities) if current_liabilities else None,
                "quick_ratio": _q((current_assets - abs(inventory)) / current_liabilities) if current_liabilities else None,
                "cash_ratio": _q(code_sum("1101%") / current_liabilities) if current_liabilities else None,
            },
            "profitability": {
                "gross_profit_margin": _q(gross_profit / revenue * 100) if revenue else None,
                "net_profit_margin": _q(net_income / revenue * 100) if revenue else None,
                "return_on_assets": _q(net_income / total_assets * 100) if total_assets else None,
                "return_on_equity": _q(net_income / equity * 100) if equity else None,
            },
            "solvency": {
                "debt_to_equity": _q(total_liabilities / equity) if equity else None,
                "debt_to_assets": _q(total_liabilities / total_assets) if total_assets else None,
                "equity_ratio": _q(equity / total_assets * 100) if total_assets else None,
            },
            "activity": {
                "ar_turnover": _q(revenue / ar) if ar else None,
                "ar_days": _q(Decimal("365") / (revenue / ar), _D1) if ar and revenue else None,
                "ap_turnover": _q(cogs / ap) if ap else None,
                "ap_days": _q(Decimal("365") / (cogs / ap), _D1) if ap and cogs else None,
                "inventory_turnover": _q(cogs / abs(inventory)) if inventory else None,
                "inventory_days": _q(Decimal("365") / (cogs / abs(inventory)), _D1) if inventory and cogs else None,
            }
        }

        return {
            "report_name": "تحليل النسب المالية",
            "as_of_date": str(d),
            "summary": {
                "total_assets": _q(total_assets), "current_assets": _q(current_assets),
                "total_liabilities": _q(total_liabilities), "equity": _q(equity),
                "revenue_ytd": _q(revenue), "net_income_ytd": _q(net_income),
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        params = {"start": s, "end": e}
        br = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

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
def detailed_profit_loss(request: Request, 
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()

        params = {"start": s_date, "end": e_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)

        if group_by == "product":
            group_col = "COALESCE(p.product_name, il.description, 'غير محدد')"
            group_label = "product_name"
            join_extra = "LEFT JOIN products p ON il.product_id = p.id"
        elif group_by == "category":
            group_col = "COALESCE(pc.category_name, 'غير مصنف')"
            group_label = "category"
            join_extra = """LEFT JOIN products p ON il.product_id = p.id
                           LEFT JOIN product_categories pc ON p.category_id = pc.id"""
        else:  # customer
            group_col = "COALESCE(pa.name, c.customer_name, 'غير محدد')"
            group_label = "customer_name"
            join_extra = """LEFT JOIN parties pa ON i.party_id = pa.id
                           LEFT JOIN customers c ON i.party_id = c.id"""

        # Revenue from sales invoices (converted to base currency)
        revenue_query = f"""
            SELECT {group_col} as group_name,
                   SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * COALESCE(i.exchange_rate, 1)) as revenue,
                   SUM(il.quantity * COALESCE(il.unit_cost, p2.cost_price, 0)) as cogs,
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
        total_revenue = Decimal("0")
        total_cogs = Decimal("0")

        for r in rows:
            revenue = Decimal(str(r.revenue or 0))
            cogs = Decimal(str(r.cogs or 0))
            gross_profit = revenue - cogs
            margin = _q((gross_profit / revenue * 100), _D1) if revenue > 0 else Decimal("0")

            total_revenue += revenue
            total_cogs += cogs

            report_rows.append({
                group_label: r.group_name or "غير محدد",
                "revenue": _decimal_str(revenue),
                "cogs": _decimal_str(cogs),
                "gross_profit": _decimal_str(gross_profit),
                "gross_margin_pct": _decimal_str(margin, _D1),
                "invoice_count": r.invoice_count or 0,
                "total_qty": _decimal_str(r.total_qty or 0),
            })

        total_gp = total_revenue - total_cogs
        overall_margin = _q((total_gp / total_revenue * 100), _D1) if total_revenue > 0 else Decimal("0")

        result = {
            "report_name": f"Detailed P&L by {group_by.title()} — أرباح وخسائر تفصيلي",
            "period": {"start": str(s_date), "end": str(e_date)},
            "group_by": group_by,
            "details": report_rows,
            "totals": {
                "total_revenue": _decimal_str(total_revenue),
                "total_cogs": _decimal_str(total_cogs),
                "total_gross_profit": _decimal_str(total_gp),
                "overall_gross_margin_pct": _decimal_str(overall_margin, _D1),
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
        raise HTTPException(**http_error(400, "invalid_date_format", request))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales Commission Report (تقرير عمولات المبيعات)
# ═══════════════════════════════════════════════════════════
