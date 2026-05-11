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
from utils.permissions import require_permission, require_sensitive_permission, resolve_branch_scope, branch_scope_filter_from_scope
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown
from routers.reports.accounting_statements import get_profit_loss, get_balance_sheet, get_trial_balance, get_general_ledger

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/accounting/profit-loss/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def compare_profit_loss(
    periods: str = "2025-01-01:2025-12-31,2024-01-01:2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة قوائم الدخل بين فترات متعددة
    periods: comma-separated pairs start:end  e.g. 2025-01-01:2025-12-31,2024-01-01:2024-12-31
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(**http_error(400, "at_least_two_periods_for_comparison", request))

        # Fetch all revenue/expense accounts once
        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts WHERE account_type IN ('revenue', 'expense')
            ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for p in parsed:
            params = {"start": p["start"], "end": p["end"]}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(CASE
                        WHEN a.account_type = 'expense' THEN jl.debit - jl.credit
                        WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit
                        ELSE 0
                    END), 0) as balance
                FROM accounts a
                JOIN journal_lines jl ON a.id = jl.account_id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type IN ('revenue', 'expense')
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: Decimal(str(r.balance)) for r in balances}

            accounts_with_bal = []
            total_rev = 0
            total_exp = 0
            for a in account_list:
                bal = bal_map.get(a["id"], 0)
                accounts_with_bal.append({**a, "balance": bal})
                if a["account_type"] == "revenue":
                    total_rev += bal
                elif a["account_type"] == "expense":
                    total_exp += bal

            period_results.append({
                "period": {"start": str(p["start"]), "end": str(p["end"]), "label": p.get("label", "")},
                "accounts": accounts_with_bal,
                "total_revenue": total_rev,
                "total_expense": total_exp,
                "net_income": total_rev - total_exp,
            })

        # Build flat comparison table
        comparison = _build_comparison_table(account_list, period_results, "revenue_expense")

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_revenue": pr["total_revenue"],
                "total_expense": pr["total_expense"],
                "net_income": pr["net_income"],
            } for pr in period_results],
            "comparison": comparison,
        }
    finally:
        db.close()


@router.get("/accounting/balance-sheet/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def compare_balance_sheet(
    periods: str = "2025-12-31,2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة الميزانية العمومية بين تواريخ متعددة
    periods: comma-separated dates  e.g. 2025-12-31,2024-12-31
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        dates = [d.strip() for d in periods.split(",") if d.strip()]
        if len(dates) < 2:
            raise HTTPException(**http_error(400, "at_least_two_dates_required", request))

        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts WHERE account_type IN ('asset', 'liability', 'equity')
            ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for d in dates:
            params = {"end": d}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(CASE
                        WHEN a.account_type IN ('asset', 'expense') THEN jl.debit - jl.credit
                        ELSE jl.credit - jl.debit
                    END), 0) as balance
                FROM accounts a
                JOIN journal_lines jl ON a.id = jl.account_id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date <= :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type IN ('asset', 'liability', 'equity')
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: Decimal(str(r.balance)) for r in balances}

            accounts_with_bal = []
            total_assets = 0
            total_liab = 0
            total_equity = 0
            for a in account_list:
                bal = bal_map.get(a["id"], 0)
                accounts_with_bal.append({**a, "balance": bal})
                if a["account_type"] == "asset":
                    total_assets += bal
                elif a["account_type"] == "liability":
                    total_liab += bal
                elif a["account_type"] == "equity":
                    total_equity += bal

            period_results.append({
                "period": {"date": d, "label": d},
                "accounts": accounts_with_bal,
                "total_assets": total_assets,
                "total_liabilities": total_liab,
                "total_equity": total_equity,
            })

        comparison = _build_comparison_table(account_list, period_results, "balance_sheet")

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_assets": pr["total_assets"],
                "total_liabilities": pr["total_liabilities"],
                "total_equity": pr["total_equity"],
            } for pr in period_results],
            "comparison": comparison,
        }
    finally:
        db.close()


# ==================== Export Endpoints ====================

from utils.exports import generate_pdf, generate_excel, generate_excel_with_chart, generate_chart_image, create_export_response

@router.get("/accounting/profit-loss/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def export_profit_loss(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير قائمة الدخل (PDF/Excel)"""
    # Parse dates
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        raise HTTPException(**http_error(400, ("invalid_date_format", request)))

    # Reuse get_profit_loss logic (call it directly or refactor)
    # For simplicity, calling the function logic essentially
    data = get_profit_loss(start_date=s_date, end_date=e_date, branch_id=branch_id, current_user=current_user)
    
    # Flatten data for export
    flat_data = []
    
    def flatten(nodes, indent=0):
        for node in nodes:
            flat_data.append({
                "Account Number": node["account_number"],
                "Account Name": f"{'  ' * indent}{node['name']}",
                "Balance": f"{Decimal(str(node['balance'])):,.2f}",
                "Type": node["account_type"]
            })
            if node.get("children"):
                flatten(node["children"], indent + 1)
                
    flatten(data["data"])
    
    # Add Total Row
    flat_data.append({
        "Account Number": "",
        "Account Name": "Net Income / صافي الدخل",
        "Balance": f"{Decimal(str(data['total'])):,.2f}",
        "Type": ""
    })
    
    if format == "excel":
        buffer = generate_excel(flat_data, ["Account Number", "Account Name", "Balance"])
        return create_export_response(buffer, f"profit_loss_{s_date}_{e_date}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        # Prepare PDF data (List of Lists)
        pdf_data = [["Account #", "Account Name", "Balance"]]
        for row in flat_data:
            pdf_data.append([row["Account Number"], row["Account Name"], row["Balance"]])
            
        buffer = generate_pdf(pdf_data, f"Profit & Loss ({s_date} to {e_date})")
        return create_export_response(buffer, f"profit_loss_{s_date}_{e_date}.pdf", "application/pdf")

@router.get("/accounting/balance-sheet/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def export_balance_sheet(
    format: str = "pdf",
    as_of_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير الميزانية العمومية (PDF/Excel)"""
    try:
        target_date = datetime.strptime(as_of_date, "%Y-%m-%d").date() if as_of_date else date.today()
    except ValueError:
        raise HTTPException(**http_error(400, ("invalid_date_format", request)))
        
    data = get_balance_sheet(as_of_date=target_date, branch_id=branch_id, current_user=current_user)
    
    flat_data = []
    def flatten(nodes, indent=0):
        for node in nodes:
            flat_data.append({
                "Account Number": node.get("account_number", ""),
                "Account Name": f"{'  ' * indent}{node['name']}",
                "Balance": f"{Decimal(str(node['balance'])):,.2f}",
                "Type": node["account_type"]
            })
            if node.get("children"):
                flatten(node["children"], indent + 1)
    
    flatten(data["data"])
    
    # Add Totals? The hierarchical view already sums up, but get_balance_sheet 
    # returns structure where roots Sum up to Total Assets (Left side) = Liabilities + Equity (Right Side)
    # Ideally logic should separate Assets vs Liab/Equity
    
    if format == "excel":
        buffer = generate_excel(flat_data, ["Account Number", "Account Name", "Balance", "Type"])
        return create_export_response(buffer, f"balance_sheet_{target_date}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        pdf_data = [["Account #", "Account Name", "Balance", "Type"]]
        for row in flat_data:
            pdf_data.append([row["Account Number"], row["Account Name"], row["Balance"], row["Type"]])
            
        buffer = generate_pdf(pdf_data, f"Balance Sheet (As of {target_date})")
        return create_export_response(buffer, f"balance_sheet_{target_date}.pdf", "application/pdf")


@router.get("/accounting/trial-balance/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def compare_trial_balance(
    periods: str = "2025-01-01:2025-12-31,2024-01-01:2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة ميزان المراجعة بين فترات متعددة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(**http_error(400, "at_least_two_periods_required", request))

        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for p in parsed:
            params = {"start": p["start"], "end": p["end"]}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(jl.debit), 0) as total_debit,
                    COALESCE(SUM(jl.credit), 0) as total_credit
                FROM accounts a
                JOIN journal_lines jl ON a.id = jl.account_id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: {"debit": Decimal(str(r.total_debit)), "credit": Decimal(str(r.total_credit))} for r in balances}

            accounts_with_bal = []
            sum_debit = 0
            sum_credit = 0
            for a in account_list:
                b = bal_map.get(a["id"], {"debit": 0, "credit": 0})
                accounts_with_bal.append({**a, "debit": b["debit"], "credit": b["credit"]})
                sum_debit += b["debit"]
                sum_credit += b["credit"]

            period_results.append({
                "period": {"start": str(p["start"]), "end": str(p["end"]), "label": p.get("label", "")},
                "accounts": accounts_with_bal,
                "total_debit": sum_debit,
                "total_credit": sum_credit,
            })

        # Build comparison rows
        rows = []
        for a in account_list:
            period_values = []
            has_data = False
            for pr in period_results:
                acc = next((x for x in pr["accounts"] if x["id"] == a["id"]), None)
                if acc and (acc.get("debit", 0) != 0 or acc.get("credit", 0) != 0):
                    has_data = True
                period_values.append({
                    "debit": acc["debit"] if acc else 0,
                    "credit": acc["credit"] if acc else 0,
                })
            if has_data:
                rows.append({
                    "account_id": a["id"],
                    "account_number": a["account_number"],
                    "name": a["name"],
                    "name_en": a.get("name_en"),
                    "account_type": a["account_type"],
                    "periods": period_values,
                })

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_debit": pr["total_debit"],
                "total_credit": pr["total_credit"],
            } for pr in period_results],
            "comparison": rows,
        }
    finally:
        db.close()


def _parse_periods(periods_str: str):
    """Parse 'start:end,start:end' or 'start:end' strings into list of dicts"""
    result = []
    for part in periods_str.split(","):
        part = part.strip()
        if ":" in part:
            s, e = part.split(":", 1)
            result.append({"start": s.strip(), "end": e.strip()})
        else:
            # Single date: treat as full year
            result.append({"start": f"{part.strip()[:4]}-01-01", "end": part.strip()})
    return result


def _build_comparison_table(account_list, period_results, mode):
    """Build a flat comparison table with all periods side by side"""
    rows = []
    for a in account_list:
        period_values = []
        has_data = False
        for pr in period_results:
            acc = next((x for x in pr["accounts"] if x["id"] == a["id"]), None)
            bal = acc["balance"] if acc else 0
            if bal != 0:
                has_data = True
            period_values.append(bal)
        if has_data:
            period_changes = []
            period_change_pct = []
            for idx in range(len(period_values) - 1):
                delta = period_values[idx] - period_values[idx + 1]
                period_changes.append(delta)
                period_change_pct.append(
                    round((delta / abs(period_values[idx + 1]) * 100), 2)
                    if period_values[idx + 1] != 0 else 0
                )

            # Backward-compatible first-pair fields for existing clients.
            change = period_changes[0] if period_changes else 0
            change_pct = period_change_pct[0] if period_change_pct else 0

            rows.append({
                "account_id": a["id"],
                "account_number": a["account_number"],
                "name": a["name"],
                "name_en": a.get("name_en"),
                "account_type": a["account_type"],
                "periods": period_values,
                "change": change,
                "change_pct": round(change_pct, 2),
                "period_changes": period_changes,
                "period_change_pct": period_change_pct,
            })
    return rows

# ═══════════════════════════════════════════════════════════
# RPT-101/102: Export Endpoints for All Reports (PDF/Excel)
# ═══════════════════════════════════════════════════════════

@router.get("/accounting/trial-balance/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def export_trial_balance(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير ميزان المراجعة (PDF/Excel)"""
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    data = get_trial_balance(start_date=str(s), end_date=str(e), branch_id=branch_id, current_user=current_user)

    flat = []
    for r in data["data"]:
        flat.append({
            "رقم الحساب": r["account_number"], "اسم الحساب": r["name"],
            "رصيد افتتاحي مدين": f"{r['opening_debit']:,.2f}", "رصيد افتتاحي دائن": f"{r['opening_credit']:,.2f}",
            "حركة مدين": f"{r['period_debit']:,.2f}", "حركة دائن": f"{r['period_credit']:,.2f}",
            "رصيد ختامي مدين": f"{r['closing_debit']:,.2f}", "رصيد ختامي دائن": f"{r['closing_credit']:,.2f}",
        })
    cols = ["رقم الحساب", "اسم الحساب", "رصيد افتتاحي مدين", "رصيد افتتاحي دائن", "حركة مدين", "حركة دائن", "رصيد ختامي مدين", "رصيد ختامي دائن"]
    fname = f"trial_balance_{s}_{e}"

    if format == "excel":
        buf = generate_excel(flat, cols, "Trial Balance")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r.get(c, "") for c in cols] for r in flat], f"Trial Balance ({s} → {e})", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


@router.get("/accounting/general-ledger/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def export_general_ledger(
    account_id: int,
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير دفتر الأستاذ لحساب معين"""
    data = get_general_ledger(account_id=account_id, start_date=start_date, end_date=end_date, branch_id=branch_id, current_user=current_user)
    flat = []
    balance = Decimal("0")
    for e_row in data["entries"]:
        balance += e_row["debit"] - e_row["credit"]
        flat.append({
            "التاريخ": e_row["entry_date"], "رقم القيد": e_row["entry_number"],
            "البيان": e_row["description"] or "", "المرجع": e_row["reference"] or "",
            "مدين": f"{e_row['debit']:,.2f}", "دائن": f"{e_row['credit']:,.2f}",
            "الرصيد": f"{balance:,.2f}",
        })
    cols = ["التاريخ", "رقم القيد", "البيان", "المرجع", "مدين", "دائن", "الرصيد"]
    fname = f"general_ledger_{account_id}"

    if format == "excel":
        buf = generate_excel(flat, cols, "General Ledger")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r.get(c, "") for c in cols] for r in flat], f"General Ledger — Account {account_id}", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


@router.get("/accounting/cashflow/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))], response_model=Dict[str, Any])
def export_cashflow(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير تقرير التدفقات النقدية"""
    from routers.reports.accounting_analysis import get_cashflow_report
    data = get_cashflow_report(start_date=start_date, end_date=end_date, branch_id=branch_id, current_user=current_user)
    flat = []
    for item in data.get("inflows", []):
        flat.append({"Section": "تدفقات داخلة", "Item": item.get("category", ""), "Amount": f"{Decimal(str(item.get('amount', 0))):,.2f}"})
    flat.append({"Section": "تدفقات داخلة", "Item": "المجموع", "Amount": f"{Decimal(str(data.get('total_inflow', 0))):,.2f}"})
    for item in data.get("outflows", []):
        flat.append({"Section": "تدفقات خارجة", "Item": item.get("category", ""), "Amount": f"{Decimal(str(item.get('amount', 0))):,.2f}"})
    flat.append({"Section": "تدفقات خارجة", "Item": "المجموع", "Amount": f"{Decimal(str(data.get('total_outflow', 0))):,.2f}"})
    flat.append({"Section": "", "Item": "صافي التدفقات النقدية", "Amount": f"{Decimal(str(data.get('net_cash_flow', 0))):,.2f}"})
    cols = ["Section", "Item", "Amount"]
    fname = f"cashflow_{start_date}_{end_date}"
    if format == "excel":
        buf = generate_excel(flat, cols, "Cash Flow")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r[c] for c in cols] for r in flat], "Cash Flow Statement", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


