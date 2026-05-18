"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Response
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
import io
import csv
import json
import logging
import subprocess
import os
from database import get_db_connection, engine as system_engine
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.fiscal_lock import create_fiscal_lock_table, check_fiscal_period_open
from utils.duplicate_detection import find_duplicate_parties, find_duplicate_products
from services.gl_service import create_journal_entry

logger = logging.getLogger(__name__)

def _u(current_user, key, default=None):
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)

router = APIRouter()

@router.get("/reports/consolidation/trial-balance",
            dependencies=[Depends(require_permission("accounting.view"))], tags=["Consolidation"], response_model=Dict[str, Any])
def consolidated_trial_balance(
    request: Request,
    company_ids: Optional[str] = None,  # comma-separated
    as_of_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    ميزان مراجعة موحّد — يجمع أرصدة الحسابات من عدة شركات
    """
    try:
        with system_engine.connect() as sys_conn:
            # Get user's accessible companies
            user_id = _u(current_user, "user_id")
            if company_ids:
                ids = [c.strip() for c in company_ids.split(",")]
            else:
                companies = sys_conn.execute(text("""
                    SELECT DISTINCT company_id FROM users WHERE id = :uid
                """), {"uid": user_id}).fetchall()
                ids = [c.company_id for c in companies]

            if not ids:
                # Use current company
                ids = [_u(current_user, "company_id")]

            consolidated = {}
            company_details = []

            for cid in ids:
                try:
                    with transactional(cid) as db:
                        # Get company name
                        comp_name = db.execute(text(
                            "SELECT setting_value FROM company_settings WHERE setting_key = 'company_name' LIMIT 1"
                        )).scalar() or cid

                        company_details.append({"id": cid, "name": comp_name})

                        accounts = db.execute(text("""
                            SELECT a.account_code, a.name, a.name_en,
                                   a.account_type,
                                   COALESCE(a.balance, 0) as balance
                            FROM accounts a
                            WHERE a.is_active = true
                            ORDER BY a.account_code
                        """)).fetchall()

                        for acc in accounts:
                            code = acc.account_code
                            if code not in consolidated:
                                consolidated[code] = {
                                    "account_code": code,
                                    "account_name": acc.name,
                                    "account_name_en": acc.name_en or '',
                                    "account_type": acc.account_type,
                                    "total_debit": 0,
                                    "total_credit": 0,
                                    "net_balance": 0,
                                    "company_balances": {}
                                }

                            bal = float(acc.balance or 0)
                            # Debit-normal: asset, expense. Credit-normal: liability, equity, revenue
                            if acc.account_type in ('asset', 'expense'):
                                consolidated[code]["total_debit"] += abs(bal) if bal >= 0 else 0
                                consolidated[code]["total_credit"] += abs(bal) if bal < 0 else 0
                            else:
                                consolidated[code]["total_credit"] += abs(bal) if bal >= 0 else 0
                                consolidated[code]["total_debit"] += abs(bal) if bal < 0 else 0

                            consolidated[code]["net_balance"] += bal
                            consolidated[code]["company_balances"][cid] = bal

                except Exception as e:
                    logger.error(f"Consolidation error for company {cid}: {e}")
                    continue

            # Sort by account code
            result = sorted(consolidated.values(), key=lambda x: x['account_code'])

            # Round
            for r in result:
                r["total_debit"] = round(r["total_debit"], 2)
                r["total_credit"] = round(r["total_credit"], 2)
                r["net_balance"] = round(r["net_balance"], 2)

            total_debit = sum(r["total_debit"] for r in result)
            total_credit = sum(r["total_credit"] for r in result)

            return {
                "companies": company_details,
                "as_of_date": as_of_date or date.today().isoformat(),
                "accounts": result,
                "totals": {
                    "total_debit": round(total_debit, 2),
                    "total_credit": round(total_credit, 2),
                    "difference": round(total_debit - total_credit, 2)
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Consolidation trial balance failed: {e}")
        raise HTTPException(**http_error(500, "internal_error", request))


@router.get("/reports/consolidation/income-statement",
            dependencies=[Depends(require_permission("accounting.view"))], tags=["Consolidation"], response_model=Dict[str, Any])
def consolidated_income_statement(
    company_ids: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """قائمة دخل موحّدة"""
    if company_ids:
        ids = [c.strip() for c in company_ids.split(",")]
    else:
        ids = [_u(current_user, "company_id")]

    total_revenue = 0
    total_cogs = 0
    total_expenses = 0
    company_results = []

    for cid in ids:
        try:
            with transactional(cid) as db:
                comp_name = db.execute(text(
                    "SELECT setting_value FROM company_settings WHERE setting_key = 'company_name' LIMIT 1"
                )).scalar() or cid

                revenue = db.execute(text("""
                    SELECT COALESCE(SUM(a.balance), 0)
                    FROM accounts a WHERE a.account_type = 'revenue'
                """)).scalar() or 0

                # COGS included within expense accounts
                cogs = 0

                expenses = db.execute(text("""
                    SELECT COALESCE(SUM(a.balance), 0)
                    FROM accounts a WHERE a.account_type = 'expense'
                """)).scalar() or 0

                rev = float(revenue)
                c = float(cogs)
                exp = float(expenses)

                company_results.append({
                    "company_id": cid,
                    "company_name": comp_name,
                    "revenue": rev,
                    "cogs": c,
                    "gross_profit": rev - c,
                    "expenses": exp,
                    "net_income": rev - c - exp
                })

                total_revenue += rev
                total_cogs += c
                total_expenses += exp

        except Exception as e:
            logger.error(f"Consolidation IS error {cid}: {e}")

    return {
        "companies": company_results,
        "consolidated": {
            "total_revenue": round(total_revenue, 2),
            "total_cogs": round(total_cogs, 2),
            "gross_profit": round(total_revenue - total_cogs, 2),
            "total_expenses": round(total_expenses, 2),
            "net_income": round(total_revenue - total_cogs - total_expenses, 2)
        }
    }


@router.get("/reports/consolidation/balance-sheet",
            dependencies=[Depends(require_permission("accounting.view"))], tags=["Consolidation"], response_model=Dict[str, Any])
def consolidated_balance_sheet(
    company_ids: Optional[str] = None,
    as_of_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """ميزانية عمومية موحّدة — Assets = Liabilities + Equity across all companies"""
    if company_ids:
        ids = [c.strip() for c in company_ids.split(",")]
    else:
        ids = [_u(current_user, "company_id")]

    total_assets = 0
    total_liabilities = 0
    total_equity = 0
    company_results = []

    for cid in ids:
        try:
            with transactional(cid) as db:
                comp_name = db.execute(text(
                    "SELECT setting_value FROM company_settings WHERE setting_key = 'company_name' LIMIT 1"
                )).scalar() or cid

                assets = db.execute(text("""
                    SELECT COALESCE(SUM(a.balance), 0)
                    FROM accounts a WHERE a.account_type = 'asset'
                """)).scalar() or 0

                liabilities = db.execute(text("""
                    SELECT COALESCE(SUM(a.balance), 0)
                    FROM accounts a WHERE a.account_type = 'liability'
                """)).scalar() or 0

                equity = db.execute(text("""
                    SELECT COALESCE(SUM(a.balance), 0)
                    FROM accounts a WHERE a.account_type = 'equity'
                """)).scalar() or 0

                a = float(assets)
                l = float(liabilities)
                e = float(equity)

                company_results.append({
                    "company_id": cid,
                    "company_name": comp_name,
                    "total_assets": round(a, 2),
                    "total_liabilities": round(l, 2),
                    "total_equity": round(e, 2),
                    "balance_check": round(a - l - e, 2),
                })

                total_assets += a
                total_liabilities += l
                total_equity += e

        except Exception as e:
            logger.error(f"Consolidation BS error {cid}: {e}")

    return {
        "as_of_date": as_of_date or date.today().isoformat(),
        "companies": company_results,
        "consolidated": {
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "total_equity": round(total_equity, 2),
            "balance_check": round(total_assets - total_liabilities - total_equity, 2),
        }
    }


@router.get("/reports/fx-gain-loss",
            dependencies=[Depends(require_permission("accounting.view"))], tags=["FX Reports"], response_model=Dict[str, Any])
def fx_gain_loss_report(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    currency: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير فروق العملة — الأرباح والخسائر المحققة وغير المحققة
    FX Gain/Loss Report — Realized (from posted JEs) + Unrealized (open foreign currency balances)
    """
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        try:
            f_date = from_date or date.today().replace(day=1).isoformat()
            t_date = to_date or date.today().isoformat()
            params: dict = {"from": f_date, "to": t_date}
            currency_cond = " AND jl.currency = :currency" if currency else ""
            if currency:
                params["currency"] = currency
    
            # ── 1. Realized FX: Journal lines on accounts whose name/type indicates FX ─
            realized_rows = db.execute(text(f"""
                SELECT
                    je.id as je_id,
                    je.reference,
                    je.entry_date,
                    jl.description,
                    jl.currency,
                    COALESCE(jl.debit, 0) as debit_amount,
                    COALESCE(jl.credit, 0) as credit_amount,
                    a.account_code,
                    a.name as account_name,
                    a.account_type
                FROM journal_entries je
                JOIN journal_lines jl ON jl.journal_entry_id = je.id
                JOIN accounts a ON a.id = jl.account_id
                WHERE je.entry_date BETWEEN :from AND :to
                  AND je.status = 'posted'
                  AND (
                      a.name ILIKE '%%فرق عملة%%'
                      OR a.name ILIKE '%%fx%%'
                      OR a.name ILIKE '%%exchange%%'
                      OR a.name ILIKE '%%أرباح صرف%%'
                      OR a.name ILIKE '%%خسائر صرف%%'
                  )
                  {currency_cond}
                ORDER BY je.entry_date
            """), params).fetchall()
    
            realized_gains  = sum(float(r.credit_amount) for r in realized_rows)
            realized_losses = sum(float(r.debit_amount)  for r in realized_rows)
    
            # ── 2. Unrealized FX: Open foreign-currency invoices vs current rates ──
            base_ccy = db.execute(text(
                "SELECT COALESCE(code, 'SYP') FROM currencies WHERE is_base = TRUE LIMIT 1"
            )).scalar() or "SYP"
    
            fc_cond = ""
            fc_params: dict = {"base": base_ccy}
            if currency:
                fc_cond = " AND i.currency = :currency"
                fc_params["currency"] = currency
    
            open_inv_rows = db.execute(text(f"""
                SELECT
                    i.id, i.invoice_number, i.invoice_date, i.invoice_type,
                    i.currency,
                    COALESCE(i.exchange_rate, 1.0) as booked_rate,
                    (i.total - COALESCE(i.paid_amount, 0)) as open_fc_amount,
                    p.name as party_name
                FROM invoices i
                LEFT JOIN parties p ON p.id = i.party_id
                WHERE i.currency != :base
                  AND i.status NOT IN ('cancelled', 'draft', 'paid')
                  AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
                  {fc_cond}
            """), fc_params).fetchall()
    
            rate_rows = db.execute(text(
                "SELECT code, COALESCE(current_rate, 1.0) as rate FROM currencies WHERE is_active = TRUE"
            )).fetchall()
            current_rates = {r.code: float(r.rate) for r in rate_rows}
    
            unrealized = []
            total_unrealized_gain  = 0.0
            total_unrealized_loss  = 0.0
            for inv in open_inv_rows:
                curr     = inv.currency
                booked   = float(inv.booked_rate)
                current  = current_rates.get(curr, booked)
                open_fc  = float(inv.open_fc_amount or 0)
                diff     = open_fc * (current - booked)
                # For purchase invoices (liability), a weaker base currency = loss
                if inv.invoice_type == 'purchase':
                    diff = -diff
                unrealized.append({
                    "invoice_number": inv.invoice_number,
                    "party": inv.party_name,
                    "invoice_type": inv.invoice_type,
                    "currency": curr,
                    "open_fc_amount": round(open_fc, 2),
                    "booked_rate": booked,
                    "current_rate": current,
                    "booked_base": round(open_fc * booked, 2),
                    "current_base": round(open_fc * current, 2),
                    "unrealized_fx": round(diff, 2),
                })
                if diff >= 0:
                    total_unrealized_gain += diff
                else:
                    total_unrealized_loss += abs(diff)
    
            return {
                "report_name": "تقرير فروق العملة",
                "period": {"from": f_date, "to": t_date},
                "realized": {
                    "entries": [{
                        "je_id": r.je_id, "ref": r.reference,
                        "date": str(r.entry_date), "description": r.description,
                        "currency": r.currency,
                        "debit": float(r.debit_amount), "credit": float(r.credit_amount),
                        "account": r.account_name,
                    } for r in realized_rows],
                    "total_gains":  round(realized_gains, 2),
                    "total_losses": round(realized_losses, 2),
                    "net": round(realized_gains - realized_losses, 2),
                },
                "unrealized": {
                    "invoices": unrealized,
                    "total_unrealized_gain":  round(total_unrealized_gain, 2),
                    "total_unrealized_loss":  round(total_unrealized_loss, 2),
                    "net": round(total_unrealized_gain - total_unrealized_loss, 2),
                },
                "summary": {
                    "total_fx_gain":  round(realized_gains + total_unrealized_gain, 2),
                    "total_fx_loss":  round(realized_losses + total_unrealized_loss, 2),
                    "net_fx": round(
                        (realized_gains + total_unrealized_gain)
                        - (realized_losses + total_unrealized_loss), 2
                    ),
                },
            }
        except Exception as e:
            logger.error(f"FX gain/loss report error: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ═══════════════════════════════════════════════════════════════════════════════
#  4. FISCAL PERIOD LOCK MANAGEMENT
#     إدارة قفل الفترة المحاسبية
# ═══════════════════════════════════════════════════════════════════════════════

