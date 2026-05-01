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

def _compute_net_income_from_gl(db, *, end_date, start_date=None, branch_id=None) -> Decimal:
    """
    Single source of truth for net income = Revenue − Expense from journal_lines.
    Used by both the income statement and the balance sheet (retained earnings).
    """
    branch_filter = ""
    params: dict = {"as_of": end_date}
    if start_date:
        date_clause = "je.entry_date BETWEEN :start AND :as_of"
        params["start"] = start_date
    else:
        date_clause = "je.entry_date <= :as_of"
    if branch_id:
        branch_filter = "AND je.branch_id = :branch"
        params["branch"] = branch_id

    row = db.execute(text(f"""
        SELECT
            COALESCE(SUM(CASE WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN a.account_type = 'expense'  THEN jl.debit - jl.credit ELSE 0 END), 0) AS net_income
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.account_type IN ('revenue', 'expense')
          AND {date_clause}
          AND je.status = 'posted'
          {branch_filter}
    """), params).fetchone()
    return Decimal(str(row.net_income)) if row else Decimal("0")

# --- Schemas ---
class TrialBalanceItem(BaseModel):
    account_id: int
    account_number: str
    name: str
    name_en: Optional[str]
    account_type: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal

class TrialBalanceResponse(BaseModel):
    period: Dict[str, date]
    data: List[TrialBalanceItem]
    totals: Dict[str, Decimal]

class FinancialStatementItem(BaseModel):
    id: int
    account_number: str
    name: str
    name_en: Optional[str] = None
    account_type: str
    balance: Decimal
    level: int = 0
    parent_id: Optional[int] = None
    children: List['FinancialStatementItem'] = []

class FinancialStatementResponse(BaseModel):
    period: Dict[str, date]
    data: List[FinancialStatementItem]
    total: Decimal

def _get_trial_balance_data(db, start_date, end_date, branch_id=None):
    """Internal helper: returns trial balance data for programmatic use."""
    params = {"start": start_date, "end": end_date}
    
    branch_filter = ""
    if branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        params["branch_id"] = branch_id

    query = f"""
        WITH opening_bal AS (
            SELECT 
                jl.account_id,
                SUM(jl.debit) as open_debit,
                SUM(jl.credit) as open_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE je.entry_date < :start
            AND je.status = 'posted'
            {branch_filter}
            GROUP BY jl.account_id
        ),
        movement AS (
            SELECT 
                jl.account_id,
                SUM(jl.debit) as period_debit,
                SUM(jl.credit) as period_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted'
            {branch_filter}
            GROUP BY jl.account_id
        )
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type,
            COALESCE(o.open_debit, 0) as open_debit,
            COALESCE(o.open_credit, 0) as open_credit,
            COALESCE(m.period_debit, 0) as period_debit,
            COALESCE(m.period_credit, 0) as period_credit
        FROM accounts a
        LEFT JOIN opening_bal o ON a.id = o.account_id
        LEFT JOIN movement m ON a.id = m.account_id
        WHERE (o.open_debit IS NOT NULL OR o.open_credit IS NOT NULL OR m.period_debit IS NOT NULL OR m.period_credit IS NOT NULL)
        ORDER BY a.account_number
    """
    
    result = db.execute(text(query), params).fetchall()
    
    data = []
    total_open_dr = total_open_cr = total_period_dr = total_period_cr = total_close_dr = total_close_cr = 0
    
    for row in result:
        acct_type = row.account_type
        
        # Net opening balance by account type direction
        raw_open_dr = Decimal(str(row.open_debit))
        raw_open_cr = Decimal(str(row.open_credit))
        open_net = raw_open_dr - raw_open_cr  # positive = debit balance
        
        # Debit-normal accounts (asset, expense): show net in DR if positive
        # Credit-normal accounts (liability, equity, revenue): show net in CR if positive
        if acct_type in ('asset', 'expense'):
            o_dr = open_net if open_net > 0 else 0
            o_cr = abs(open_net) if open_net < 0 else 0
        else:
            # For credit-normal accounts, flip: negative net means debit excess
            o_cr = abs(open_net) if open_net < 0 else 0  # credit-normal: net < 0 means excess debit
            o_dr = open_net if open_net > 0 else 0
            # Actually: credit-normal: positive credit balance = credit - debit > 0 → net < 0
            # Recalculate: for credit-normal, opening = CR - DR (if positive → show in CR column)
            credit_net = raw_open_cr - raw_open_dr
            o_cr = credit_net if credit_net > 0 else 0
            o_dr = abs(credit_net) if credit_net < 0 else 0
        
        # Period movement
        p_dr = Decimal(str(row.period_debit))
        p_cr = Decimal(str(row.period_credit))
        
        # Closing
        # Standard Accounting logic: (DR_open + DR_period) - (CR_open + CR_period)
        # If positive -> Closing DR. If negative -> Closing CR.
        net_total = (o_dr + p_dr) - (o_cr + p_cr)
        
        c_dr = net_total if net_total > 0 else 0
        c_cr = abs(net_total) if net_total < 0 else 0
        
        data.append({
            "account_id": row.id,
            "account_number": row.account_number,
            "name": row.name,
            "name_en": row.name_en,
            "account_type": row.account_type,
            "opening_debit": o_dr,
            "opening_credit": o_cr,
            "period_debit": p_dr,
            "period_credit": p_cr,
            "closing_debit": c_dr,
            "closing_credit": c_cr
        })
        
        total_open_dr += o_dr
        total_open_cr += o_cr
        total_period_dr += p_dr
        total_period_cr += p_cr
        total_close_dr += c_dr
        total_close_cr += c_cr
        
    return {
        "period": {"start": start_date, "end": end_date},
        "data": data,
        "totals": {
            "opening_debit": total_open_dr,
            "opening_credit": total_open_cr,
            "period_debit": total_period_dr,
            "period_credit": total_period_cr,
            "closing_debit": total_close_dr,
            "closing_credit": total_close_cr
        }
    }

@router.get("/accounting/trial-balance", response_model=TrialBalanceResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_trial_balance", expire=60)
def get_trial_balance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ميزان المراجعة لفترة محددة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1) # Start of year
        if not end_date:
            end_date = date.today()
        return _get_trial_balance_data(db, start_date, end_date, branch_id)
    finally:
        db.close()

def _get_profit_loss_data(db, start_date, end_date, branch_id=None):
    """Internal helper to get profit loss data"""
    params = {"start": start_date, "end": end_date}
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    if branch_id: params["branch_id"] = branch_id

    # Fetch all accounts and their period balances
    query = f"""
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id,
            COALESCE(SUM(CASE 
                WHEN a.account_type = 'expense' THEN jl.debit - jl.credit
                WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit
                ELSE 0 
            END), 0) as balance
        FROM accounts a
        LEFT JOIN journal_lines jl ON a.id = jl.account_id
        LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE a.account_type IN ('revenue', 'expense')
        AND (je.id IS NULL OR (je.entry_date BETWEEN :start AND :end AND je.status = 'posted' {branch_filter}))
        GROUP BY a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id
        ORDER BY a.account_number
    """
    
    accounts = [dict(row._mapping) for row in db.execute(text(query), params).fetchall()]
    
    # Build hierarchy
    account_map = {a["id"]: {**a, "children": [], "level": 0} for a in accounts}
    roots = []
    
    # First pass: map children and find roots
    for acc_id, acc in account_map.items():
        parent_id = acc["parent_id"]
        if parent_id and parent_id in account_map:
            account_map[parent_id]["children"].append(acc)
        else:
            roots.append(acc)
    
    # Second pass: Roll up balances and set levels
    def rollup(node, level):
        node["level"] = level
        child_sum = 0
        for child in node["children"]:
            child_sum += rollup(child, level + 1)
        node["balance"] = Decimal(str(node["balance"])) + child_sum
        return node["balance"]

    total_revenue = 0
    total_expense = 0
    for root in roots:
        bal = rollup(root, 0)
        if root["account_type"] == 'revenue':
            total_revenue += bal
        elif root["account_type"] == 'expense':
            total_expense += bal
    
    # Net Income = Revenue - Expenses (not Revenue + Expenses)
    net_income = total_revenue - total_expense
        
    return {
        "period": {"start": start_date, "end": end_date},
        "data": roots,
        "total": net_income
    }

@router.get("/accounting/profit-loss", response_model=FinancialStatementResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_profit_loss", expire=60)
def get_profit_loss(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قائمة الدخل (الأرباح والخسائر) الهيكلية"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1)
        if not end_date:
            end_date = date.today()
            
        return _get_profit_loss_data(db, start_date, end_date, branch_id)
    finally:
        db.close()

def _get_balance_sheet_data(db, as_of_date, branch_id=None):
    """Internal helper to get balance sheet data"""
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    params = {"as_of": as_of_date}
    if branch_id: params["branch_id"] = branch_id

    # Balance Sheet follows Assets = Liabilities + Equity
    # We sum all transactions from the beginning of time up to as_of_date
    query = f"""
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id,
            COALESCE(SUM(CASE 
                WHEN a.account_type IN ('asset', 'expense') THEN jl.debit - jl.credit
                ELSE jl.credit - jl.debit
            END), 0) as balance
        FROM accounts a
        LEFT JOIN journal_lines jl ON a.id = jl.account_id
        LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE a.account_type IN ('asset', 'liability', 'equity')
        AND (je.id IS NULL OR (je.entry_date <= :as_of AND je.status = 'posted' {branch_filter}))
        GROUP BY a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id
        ORDER BY a.account_number
    """
    
    accounts = [dict(row._mapping) for row in db.execute(text(query), params).fetchall()]
    
    # Build hierarchy
    account_map = {a["id"]: {**a, "children": [], "level": 0} for a in accounts}
    roots = []
    
    for acc_id, acc in account_map.items():
        parent_id = acc["parent_id"]
        if parent_id and parent_id in account_map:
            account_map[parent_id]["children"].append(acc)
        else:
            roots.append(acc)
    
    def rollup(node, level):
        node["level"] = level
        child_sum = 0
        for child in node["children"]:
            child_sum += rollup(child, level + 1)
        node["balance"] = Decimal(str(node["balance"])) + child_sum
        return node["balance"]

    for root in roots:
        rollup(root, 0)
    
    # Calculate Retained Earnings (Net Income) using the shared helper
    # This ensures Balance Sheet balances: Assets = Liabilities + Equity + Retained Earnings
    retained_earnings = _compute_net_income_from_gl(
        db, end_date=as_of_date, branch_id=branch_id,
    )
    
    # Add retained earnings as a virtual equity item
    if retained_earnings != 0:
        roots.append({
            "id": -1,
            "account_number": "RE",
            "name": "Retained Earnings / الأرباح المبقاة",
            "name_en": "Retained Earnings",
            "account_type": "equity",
            "balance": retained_earnings,
            "children": [],
            "level": 0
        })

    # Compute totals
    total_assets = sum(r["balance"] for r in roots if r.get("account_type") == "asset")
    total_liabilities = sum(r["balance"] for r in roots if r.get("account_type") == "liability")
    total_equity = sum(r["balance"] for r in roots if r.get("account_type") == "equity")

    return {
        "period": {"start": as_of_date, "end": as_of_date},
        "data": roots,
        "total": total_assets,
        "as_of": as_of_date,
        "net_income": retained_earnings,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity
    }

@router.get("/accounting/balance-sheet", response_model=FinancialStatementResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_balance_sheet", expire=60)
def get_balance_sheet(
    as_of_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب الميزانية العمومية الهيكلية"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not as_of_date:
            as_of_date = date.today()
            
        return _get_balance_sheet_data(db, as_of_date, branch_id)
    finally:
        db.close()

def _get_general_ledger_data(db, account_id, start_date, end_date, branch_id=None):
    """Internal helper: returns general ledger data for programmatic use."""
    # ── Recursive CTE: collect selected account + all descendants ──
    tree_rows = db.execute(text("""
        WITH RECURSIVE account_tree AS (
            SELECT id, account_type, name, name_en, account_number, parent_id
            FROM accounts WHERE id = :account_id
            UNION ALL
            SELECT a.id, a.account_type, a.name, a.name_en, a.account_number, a.parent_id
            FROM accounts a
            INNER JOIN account_tree at ON a.parent_id = at.id
        )
        SELECT id, account_type, name, name_en, account_number FROM account_tree
    """), {"account_id": account_id}).fetchall()

    account_ids = [row.id for row in tree_rows]
    account_map = {row.id: f"{row.account_number} - {row.name}" for row in tree_rows}
    
    # Use the root account's type for sign convention
    root_row = next((r for r in tree_rows if r.id == account_id), None)
    acct_type = root_row.account_type if root_row else "asset"
    is_aggregated = len(account_ids) > 1

    # Build safe IN clause (account_ids are integers from DB — safe)
    ids_in = ",".join(str(i) for i in account_ids)

    branch_filter = ""
    params: dict = {"start": start_date, "end": end_date}
    if branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        params["branch_id"] = branch_id

    # Compute opening balance across all descendant accounts
    opening_query = f"""
        SELECT COALESCE(SUM(jl.debit), 0) as total_debit,
               COALESCE(SUM(jl.credit), 0) as total_credit
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE jl.account_id IN ({ids_in})
        AND je.entry_date < :start
        AND je.status = 'posted'
        {branch_filter}
    """
    opening_row = db.execute(text(opening_query), params).fetchone()
    opening_debit = Decimal(str(opening_row.total_debit)) if opening_row else 0
    opening_credit = Decimal(str(opening_row.total_credit)) if opening_row else 0
    if acct_type in ('asset', 'expense'):
        opening_balance = opening_debit - opening_credit
    else:
        opening_balance = opening_credit - opening_debit

    # Fetch journal lines across all descendant accounts
    query = f"""
        SELECT 
            je.entry_date,
            je.entry_number,
            je.description,
            je.reference,
            jl.debit,
            jl.credit,
            jl.description as line_description,
            jl.account_id
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE jl.account_id IN ({ids_in})
        AND je.entry_date BETWEEN :start AND :end
        AND je.status = 'posted'
        {branch_filter}
        ORDER BY je.entry_date ASC, je.id ASC, jl.id ASC
    """
    
    result = db.execute(text(query), params).fetchall()
    
    running_balance = opening_balance
    entries = []
    for row in result:
        debit = Decimal(str(row.debit))
        credit = Decimal(str(row.credit))
        if acct_type in ('asset', 'expense'):
            running_balance += debit - credit
        else:
            running_balance += credit - debit
        entries.append({
            "entry_date": str(row.entry_date),
            "entry_number": row.entry_number,
            "description": row.line_description or row.description,
            "reference": row.reference,
            "debit": debit,
            "credit": credit,
            "running_balance": round(running_balance, 2),
            "account_name": account_map.get(row.account_id, "") if is_aggregated else None,
        })
    
    return {
        "account_id": account_id,
        "period": {"start": start_date, "end": end_date},
        "opening_balance": round(opening_balance, 2),
        "entries": entries,
        "closing_balance": round(running_balance, 2),
        "is_aggregated": is_aggregated,
        "child_accounts_count": len(account_ids) - 1,
    }

@router.get("/accounting/general-ledger", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def get_general_ledger(
    account_id: int = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب دفتر الأستاذ العام - حركات حساب محدد مع كل حساباته الفرعية"""
    if not account_id:
        raise HTTPException(status_code=400, detail="يجب تحديد الحساب")
    
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1)
        if not end_date:
            end_date = date.today()
        return _get_general_ledger_data(db, account_id, start_date, end_date, branch_id)
    finally:
        db.close()


# ==================== ACC-004: Period Comparison Reports ====================

