"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Request
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
from utils.permissions import require_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.currency_display import display_currency_fields, resolve_display_currency
from utils.fiscal_lock import create_fiscal_lock_table, check_fiscal_period_open
from utils.duplicate_detection import find_duplicate_parties, find_duplicate_products
from utils.tax_precision import CALCULATION_VERSION, get_idempotency_key, money_str, rate_str
from services.gl_service import create_journal_entry

logger = logging.getLogger(__name__)

def _u(current_user, key, default=None):
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)

router = APIRouter()

from .core import FiscalPeriodLockRequest, ZakatCalculateRequest, _zakat_balance_query, _zakat_account_breakdown


def zakat_branch_scope_key(branch_scope: dict) -> tuple[str, list[int] | None]:
    """Compute a deterministic scope key for zakat calculations.

    Returns (scope_key, branch_ids_or_None).
    """
    if branch_scope.get("branch_id") is not None:
        return f"branch:{branch_scope['branch_id']}", None

    branch_ids = branch_scope.get("branch_ids")
    if branch_ids is None:
        return "all:company", None

    sorted_ids = sorted(int(b) for b in branch_ids)
    if not sorted_ids:
        return "branches:none", []
    return "branches:" + ",".join(str(b) for b in sorted_ids), sorted_ids

@router.post("/accounting/zakat/calculate", dependencies=[Depends(require_permission("accounting.manage"))],
             tags=["Zakat"], response_model=Dict[str, Any])
def calculate_zakat(request: Request, body: ZakatCalculateRequest, current_user: dict = Depends(get_current_user)):
    """
    حساب الزكاة الشرعية — Sharia-compliant Zakat Calculation
    Supports branch filtering via branch_id parameter.
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    branch_scope = resolve_branch_scope(current_user, body.branch_id)
    selected_branch_id = branch_scope["branch_id"]
    scope_key, scoped_branch_ids = zakat_branch_scope_key(branch_scope)
    if selected_branch_id:
        scope_key = f"branch:{selected_branch_id}"
    with transactional(company_id) as db:
        try:
            display_meta = resolve_display_currency(db, branch_scope)
            base_currency = get_base_currency(db)
            base_display_meta = {
                "currency": base_currency,
                "base_currency": base_currency,
                "rate": Decimal("1"),
                "is_multi_currency_scope": bool(display_meta.get("is_multi_currency_scope")),
                "display_currency_mode": "company_base",
            }
            idempotency_key = get_idempotency_key(
                request,
                fallback=f"zakat-calc:{body.fiscal_year}:{body.method}:branch:{selected_branch_id or 'all'}:{body.use_gregorian_rate}",
            )

            if selected_branch_id:
                country_row = db.execute(text("SELECT country_code FROM branches WHERE id = :id"), {"id": selected_branch_id}).fetchone()
                country_code = (country_row.country_code if country_row and country_row.country_code else "SA").upper()
            else:
                country_row = db.execute(text("SELECT setting_value FROM company_settings WHERE setting_key = 'company_country'")).fetchone()
                country_code = (country_row.setting_value if country_row and country_row.setting_value else "SA").upper()

            if body.use_gregorian_rate:
                rate_row = db.execute(text(
                    "SELECT setting_value FROM company_settings WHERE setting_key = 'tax.zakat.gregorian_rate'"
                )).fetchone()
                if not rate_row:
                    raise HTTPException(**http_error(400, "zakat_rate_not_configured_company_settings", request))
                rate = Decimal(str(rate_row.setting_value))
            else:
                rate_row = db.execute(text("""
                    SELECT default_rate
                    FROM tax_regimes
                    WHERE country_code = :cc AND tax_type = 'zakat' AND is_active = TRUE
                    LIMIT 1
                """), {"cc": country_code}).fetchone()
                if not rate_row:
                    raise HTTPException(status_code=400, detail=i18n_message("zakat_not_configured_country", request))
                rate = Decimal(str(rate_row.default_rate))
            branch_id = branch_scope
    
            if body.method == "net_current_assets":
                # ══════════════════════════════════════════════════════════════
                # طريقة صافي الأصول المتداولة — Net Current Assets Method
                # وفقاً لمعايير AAOIFI وجمهور الفقهاء
                # الوعاء = النقد + عروض التجارة + المدينون المرجوون
                #        + استثمارات المضاربة - الالتزامات المتداولة
                # ══════════════════════════════════════════════════════════════
    
                # ── النقد (أصل الأصول المالية في الزكاة بالإجماع) ──
                cash_filter = """
                        a.account_number LIKE '1101%%'
                        OR a.account_number LIKE '11001%%'
                        OR a.account_number LIKE '11010%%'
                        OR a.account_number LIKE '11020%%'
                        OR a.name LIKE '%%نقد%%' OR a.name LIKE '%%صندوق%%'
                        OR a.name LIKE '%%بنك%%' OR a.name LIKE '%%كاش%%'
                        OR a.name_en LIKE '%%cash%%' OR a.name_en LIKE '%%bank%%'
                """
                cash_exclude = """
                    AND a.name NOT LIKE '%%مجمع%%'
                    AND a.name NOT LIKE '%%استثمار%%'
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%invest%%')
                """
                cash_full_filter = f"({cash_filter}) {cash_exclude}"
                cash_sql, cash_params = _zakat_balance_query(cash_full_filter, ['asset'], branch_id)
                cash = db.execute(text(cash_sql), cash_params).scalar() or 0
                cash_accounts = _zakat_account_breakdown(db, cash_full_filter, ['asset'], branch_id)
    
                # ── تصفية النقد — استبعاد شبه النقد والودائع الاستثمارية ──
                quasi_filter = """
                        a.name LIKE '%%نقد معادل%%' OR a.name LIKE '%%شبه نقد%%'
                        OR a.name LIKE '%%وديعة استثمار%%' OR a.name LIKE '%%سندات خزانة%%'
                        OR a.name_en LIKE '%%cash equivalent%%' OR a.name_en LIKE '%%treasury bill%%'
                        OR a.name_en LIKE '%%money market%%'
                """
                quasi_sql, quasi_params = _zakat_balance_query(quasi_filter, ['asset'], branch_id)
                quasi_cash = db.execute(text(quasi_sql), quasi_params).scalar() or 0
    
                net_cash = Decimal(str(cash)) - Decimal(str(quasi_cash))
    
                # ── عروض التجارة (كل مال أُعِد للبيع في سوقه خلال السنة) ──
                trade_filter = """
                        a.account_number LIKE '1103%%'
                        OR a.account_number LIKE '13001%%'
                        OR a.account_number LIKE '13010%%'
                        OR a.name LIKE '%%مخزون%%' OR a.name LIKE '%%بضاع%%'
                        OR a.name LIKE '%%عروض%%تجار%%'
                        OR a.name_en LIKE '%%inventory%%' OR a.name_en LIKE '%%stock%%'
                        OR a.name_en LIKE '%%goods%%'
                """
                trade_exclude = """
                    AND a.name NOT LIKE '%%تحت التصنيع%%'
                    AND a.name NOT LIKE '%%مواد خام%%'
                    AND a.name NOT LIKE '%%قطع غيار%%'
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%raw material%%')
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%work in progress%%')
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%spare part%%')
                """
                trade_full_filter = f"({trade_filter}) {trade_exclude}"
                trade_sql, trade_params = _zakat_balance_query(trade_full_filter, ['asset'], branch_id)
                trade_goods = db.execute(text(trade_sql), trade_params).scalar() or 0
                trade_accounts = _zakat_account_breakdown(db, trade_full_filter, ['asset'], branch_id)
    
                # ── تصفية عروض التجارة — استبعاد البضاعة الكاسدة ──
                stale_filter = """
                        a.name LIKE '%%كاسد%%' OR a.name LIKE '%%راكد%%'
                        OR a.name LIKE '%%تالف%%' OR a.name LIKE '%%منتهي الصلاحية%%'
                        OR a.name_en LIKE '%%obsolete%%' OR a.name_en LIKE '%%stale%%'
                        OR a.name_en LIKE '%%expired%%' OR a.name_en LIKE '%%damaged%%'
                """
                stale_sql, stale_params = _zakat_balance_query(stale_filter, ['asset'], branch_id)
                stale_inventory = db.execute(text(stale_sql), stale_params).scalar() or 0
    
                net_trade_goods = Decimal(str(trade_goods)) - Decimal(str(stale_inventory))
    
                # ── المدينون المرجوون ──
                recv_filter = """
                        a.account_number LIKE '1102%%' OR a.account_number LIKE '1108%%'
                        OR a.account_number LIKE '1109%%'
                        OR a.account_number LIKE '12001%%' OR a.account_number LIKE '12010%%'
                        OR a.account_number LIKE '12020%%'
                        OR a.name LIKE '%%عملاء%%' OR a.name LIKE '%%مدين%%'
                        OR a.name_en LIKE '%%receivable%%'
                """
                recv_exclude = """
                    AND a.name NOT LIKE '%%مشكوك%%'
                    AND a.name NOT LIKE '%%معدوم%%'
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%doubtful%%')
                    AND (a.name_en IS NULL OR a.name_en NOT LIKE '%%bad debt%%')
                """
                recv_full_filter = f"({recv_filter}) {recv_exclude}"
                recv_sql, recv_params = _zakat_balance_query(recv_full_filter, ['asset'], branch_id)
                receivables = db.execute(text(recv_sql), recv_params).scalar() or 0
                recv_accounts = _zakat_account_breakdown(db, recv_full_filter, ['asset'], branch_id)
    
                # ── استثمارات المضاربة (قصيرة الأجل) ──
                tinv_filter = """
                        a.name LIKE '%%أسهم%%متاجر%%' OR a.name LIKE '%%محفظة%%مضارب%%'
                        OR a.name LIKE '%%استثمار%%قصير%%'
                        OR a.name_en LIKE '%%trading%%invest%%'
                        OR a.name_en LIKE '%%short%%term%%invest%%'
                """
                tinv_sql, tinv_params = _zakat_balance_query(tinv_filter, ['asset'], branch_id)
                trading_investments = db.execute(text(tinv_sql), tinv_params).scalar() or 0
    
                # ── الالتزامات المتداولة (تُخصم من الوعاء) ──
                cl_filter = """
                        a.account_number LIKE '21%%'
                        OR a.name LIKE '%%دائن%%' OR a.name LIKE '%%مورد%%'
                        OR a.name LIKE '%%مستحق%%' OR a.name LIKE '%%مصروف%%مستحق%%'
                        OR a.name LIKE '%%قرض%%قصير%%'
                        OR a.name_en LIKE '%%payable%%' OR a.name_en LIKE '%%accrued%%'
                        OR a.name_en LIKE '%%supplier%%' OR a.name_en LIKE '%%short%%term%%loan%%'
                        OR a.name_en LIKE '%%current%%liabilit%%'
                """
                cl_sql, cl_params = _zakat_balance_query(cl_filter, ['liability', 'current_liability'], branch_id, sign="credit")
                current_liabilities = db.execute(text(cl_sql), cl_params).scalar() or 0
                cl_accounts = _zakat_account_breakdown(db, cl_filter, ['liability', 'current_liability'], branch_id, sign="credit")
    
                # ── الأصول المستبعدة (للعرض فقط) ──
                fa_filter = """
                        a.account_number LIKE '12%%' OR a.account_number LIKE '15%%'
                        OR a.account_number LIKE '16%%'
                        OR a.name LIKE '%%أصول ثابتة%%' OR a.name LIKE '%%معدات%%'
                        OR a.name LIKE '%%مباني%%' OR a.name LIKE '%%سيارات%%'
                        OR a.name LIKE '%%أثاث%%' OR a.name LIKE '%%أراضي%%'
                        OR a.name LIKE '%%مجمع%%'
                        OR a.name_en LIKE '%%fixed asset%%' OR a.name_en LIKE '%%equipment%%'
                        OR a.name_en LIKE '%%building%%' OR a.name_en LIKE '%%vehicle%%'
                        OR a.name_en LIKE '%%furniture%%' OR a.name_en LIKE '%%depreciation%%'
                """
                fa_sql, fa_params = _zakat_balance_query(fa_filter, ['asset'], branch_id)
                fixed_assets = db.execute(text(fa_sql), fa_params).scalar() or 0
    
                intang_filter = """
                        a.account_number LIKE '13%%' OR a.account_number LIKE '18%%'
                        OR a.name LIKE '%%شهرة%%' OR a.name LIKE '%%براءة%%'
                        OR a.name LIKE '%%علامة تجارية%%' OR a.name LIKE '%%رخصة%%'
                        OR a.name LIKE '%%غير ملموس%%'
                        OR a.name_en LIKE '%%intangible%%' OR a.name_en LIKE '%%goodwill%%'
                        OR a.name_en LIKE '%%patent%%' OR a.name_en LIKE '%%trademark%%'
                """
                intang_sql, intang_params = _zakat_balance_query(intang_filter, ['asset'], branch_id)
                intangible_assets = db.execute(text(intang_sql), intang_params).scalar() or 0
    
                wip_filter = """
                        a.account_number LIKE '1110%%'
                        OR a.name LIKE '%%تحت الإنشاء%%' OR a.name LIKE '%%تحت التصنيع%%'
                        OR a.name LIKE '%%مواد خام%%' OR a.name LIKE '%%قطع غيار%%'
                        OR a.name_en LIKE '%%work in progress%%' OR a.name_en LIKE '%%under construction%%'
                        OR a.name_en LIKE '%%raw material%%' OR a.name_en LIKE '%%spare part%%'
                """
                wip_sql, wip_params = _zakat_balance_query(wip_filter, ['asset'], branch_id)
                wip = db.execute(text(wip_sql), wip_params).scalar() or 0
    
                # ── حساب الوعاء الزكوي ──
                # الوعاء = النقد + عروض التجارة + المدينون المرجوون + استثمارات المضاربة
                #        - الالتزامات المتداولة (الديون الحالة)
                gross_zakatable = net_cash + net_trade_goods + Decimal(str(receivables)) + Decimal(str(trading_investments))
                cl_decimal = Decimal(str(current_liabilities))
                zakat_base = max(Decimal('0'), gross_zakatable - cl_decimal)
    
                zakat_amount = (zakat_base * rate / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
                additions = [
                    {"label": "Cash & Bank Balances", "label_ar": "النقد والأرصدة البنكية", "amount": money_str(cash)},
                ]
                if quasi_cash:
                    additions.append({"label": "Less: Quasi-Cash / Investment Deposits", "label_ar": "(-) النقد المعادل / ودائع استثمارية", "amount": money_str(-quasi_cash)})
                additions.append({"label": "Net Cash", "label_ar": "صافي النقد", "amount": money_str(net_cash), "is_subtotal": True})
    
                additions.append({"label": "Trade Goods (Inventory for Sale)", "label_ar": "عروض التجارة (المخزون المعد للبيع)", "amount": money_str(trade_goods)})
                if stale_inventory:
                    additions.append({"label": "Less: Stale/Obsolete Inventory", "label_ar": "(-) بضاعة كاسدة / راكدة", "amount": money_str(-stale_inventory)})
                additions.append({"label": "Net Trade Goods", "label_ar": "صافي عروض التجارة", "amount": money_str(net_trade_goods), "is_subtotal": True})
    
                if receivables:
                    additions.append({"label": "Collectible Receivables", "label_ar": "المدينون المرجوون (مرجو تحصيلهم)", "amount": money_str(receivables)})
                if trading_investments:
                    additions.append({"label": "Trading Investments (Short-term)", "label_ar": "استثمارات المضاربة (قصيرة الأجل)", "amount": money_str(trading_investments)})
    
                total_additions = money_str(gross_zakatable)
    
                deductions = []
                if current_liabilities:
                    deductions.append({"label": "Current Liabilities (Short-term Debts)", "label_ar": "الالتزامات المتداولة (الديون الحالة قصيرة الأجل)", "amount": money_str(cl_decimal)})
                total_deductions = money_str(cl_decimal)
    
                # الأصول المستبعدة (للعرض فقط — informational)
                excluded_info = []
                if fixed_assets:
                    excluded_info.append({"label": "Fixed Assets (non-zakatable)", "label_ar": "الأصول الثابتة (قنية — لا تُزكّى)", "amount": money_str(fixed_assets)})
                if intangible_assets:
                    excluded_info.append({"label": "Intangible Assets", "label_ar": "الأصول المعنوية (غير ملموسة)", "amount": money_str(intangible_assets)})
                if wip:
                    excluded_info.append({"label": "Work In Progress / Raw Materials", "label_ar": "تحت الإنشاء / مواد خام", "amount": money_str(wip)})
    
                details = {
                    "method_name_ar": "طريقة صافي الأصول المتداولة",
                    "method_name_en": "Net Current Assets Method (AAOIFI)",
                    "sharia_basis": "النقد + عروض التجارة + المدينون المرجوون - الديون الحالة (وفقاً لجمهور الفقهاء ومعايير AAOIFI)",
                    "excluded_assets": excluded_info,
                    "zakat_base": money_str(zakat_base),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": rate_str(rate),
                    "account_breakdown": {
                        "cash": cash_accounts,
                        "trade_goods": trade_accounts,
                        "receivables": recv_accounts,
                        "current_liabilities": cl_accounts
                    }
                }
    
            elif body.method == "net_assets":
                # ── طريقة صافي الملكية — ZATCA (المعتمدة نظامياً في السعودية) ──
                # الطريقة الملزمة للشركات السعودية التي تمسك حسابات نظامية
    
                # 1. Equity components
                eq_sql, eq_params = _zakat_balance_query("1=1", ['equity'], branch_id, sign="credit")
                equity = db.execute(text(eq_sql), eq_params).scalar() or 0
    
                # 2. Long-term liabilities
                lt_filter = """
                        a.name LIKE '%%طويل%%' OR a.name_en LIKE '%%long%%term%%'
                        OR a.account_number LIKE '22%%'
                """
                lt_sql, lt_params = _zakat_balance_query(lt_filter, ['long_term_liability', 'liability'], branch_id, sign="credit")
                lt_liabilities = db.execute(text(lt_sql), lt_params).scalar() or 0
    
                # 3. Provisions
                prov_filter = "a.name LIKE '%%مخصص%%' OR a.name_en LIKE '%%provision%%'"
                prov_sql, prov_params = _zakat_balance_query(prov_filter, ['liability', 'equity'], branch_id, sign="credit")
                provisions = db.execute(text(prov_sql), prov_params).scalar() or 0
    
                # 4. Net profit
                rev_sql, rev_params = _zakat_balance_query("1=1", ['revenue', 'income'], branch_id, sign="credit")
                revenue = db.execute(text(rev_sql), rev_params).scalar() or 0
                exp_sql, exp_params = _zakat_balance_query("1=1", ['expense', 'cogs'], branch_id, sign="debit")
                expenses = db.execute(text(exp_sql), exp_params).scalar() or 0
                net_profit = Decimal(str(revenue)) - Decimal(str(expenses))
    
                total_add = Decimal(str(equity)) + Decimal(str(lt_liabilities)) + Decimal(str(provisions))
                if net_profit > 0:
                    total_add += net_profit
    
                # 5. Fixed assets (fixed: removed overly-broad '%أصل%' pattern)
                zatca_fa_filter = """
                        a.name LIKE '%%أصول ثابتة%%' OR a.name LIKE '%%معدات%%'
                        OR a.name LIKE '%%آلات%%' OR a.name LIKE '%%مباني%%'
                        OR a.name LIKE '%%سيارات%%' OR a.name LIKE '%%أثاث%%'
                        OR a.name LIKE '%%أراضي%%' OR a.name LIKE '%%مجمع%%'
                        OR a.name_en LIKE '%%fixed%%asset%%' OR a.name_en LIKE '%%equipment%%'
                        OR a.name_en LIKE '%%machine%%' OR a.name_en LIKE '%%building%%'
                        OR a.name_en LIKE '%%vehicle%%' OR a.name_en LIKE '%%furniture%%'
                        OR a.name_en LIKE '%%depreciation%%'
                        OR a.account_number LIKE '12%%' OR a.account_number LIKE '15%%'
                        OR a.account_number LIKE '16%%'
                """
                zatca_fa_sql, zatca_fa_params = _zakat_balance_query(zatca_fa_filter, ['asset'], branch_id)
                fixed_assets = db.execute(text(zatca_fa_sql), zatca_fa_params).scalar() or 0
    
                # 6. Long-term investments (fixed: removed overly-broad '%استثمار%' pattern)
                zatca_inv_filter = """
                        a.name LIKE '%%استثمار%%طويل%%'
                        OR a.name_en LIKE '%%long%%invest%%'
                        OR a.account_number LIKE '14%%'
                """
                zatca_inv_sql, zatca_inv_params = _zakat_balance_query(zatca_inv_filter, ['asset'], branch_id)
                lt_investments = db.execute(text(zatca_inv_sql), zatca_inv_params).scalar() or 0
    
                # 7. Intangible assets (شهرة، براءات، علامات تجارية — non-zakatable per ZATCA)
                # NOTE: account_code LIKE '13%%' is NOT used broadly because 13001 is inventory (مخزون بضاعة).
                #       Instead we use specific sub-codes 1301-1305 and name-based matching.
                zatca_intang_filter = """
                        a.name LIKE '%%شهرة%%' OR a.name LIKE '%%براءة%%'
                        OR a.name LIKE '%%علامة تجارية%%' OR a.name LIKE '%%رخصة%%'
                        OR a.name LIKE '%%غير ملموس%%' OR a.name LIKE '%%أصول معنوية%%'
                        OR a.name_en LIKE '%%intangible%%' OR a.name_en LIKE '%%goodwill%%'
                        OR a.name_en LIKE '%%patent%%' OR a.name_en LIKE '%%trademark%%'
                        OR a.account_number LIKE '1301%%' OR a.account_number LIKE '1302%%'
                        OR a.account_number LIKE '1303%%' OR a.account_number LIKE '1304%%'
                        OR a.account_number LIKE '1305%%' OR a.account_number LIKE '18%%'
                """
                zatca_intang_sql, zatca_intang_params = _zakat_balance_query(zatca_intang_filter, ['asset'], branch_id)
                intangible_assets = db.execute(text(zatca_intang_sql), zatca_intang_params).scalar() or 0
    
                # 8. Work in progress / under construction (non-zakatable)
                zatca_wip_filter = """
                        a.name LIKE '%%تحت الإنشاء%%' OR a.name LIKE '%%تحت التنفيذ%%'
                        OR a.name LIKE '%%مشروعات تحت%%'
                        OR a.name_en LIKE '%%under construction%%' OR a.name_en LIKE '%%work in progress%%'
                        OR a.account_number LIKE '17%%'
                """
                zatca_wip_sql, zatca_wip_params = _zakat_balance_query(zatca_wip_filter, ['asset'], branch_id)
                wip = db.execute(text(zatca_wip_sql), zatca_wip_params).scalar() or 0
    
                total_ded = Decimal(str(fixed_assets)) + Decimal(str(lt_investments)) + Decimal(str(intangible_assets)) + Decimal(str(wip))
                zakat_base = max(Decimal('0'), total_add - total_ded)
                zakat_amount = (zakat_base * rate / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
                additions = [
                    {"label": "Equity (Capital + Reserves + RE)", "label_ar": "حقوق الملكية (رأس المال + احتياطيات + أرباح مبقاة)", "amount": money_str(equity)},
                    {"label": "Long-term Liabilities", "label_ar": "الالتزامات طويلة الأجل", "amount": money_str(lt_liabilities)},
                    {"label": "Provisions", "label_ar": "المخصصات", "amount": money_str(provisions)},
                    {"label": "Net Profit", "label_ar": "صافي الربح", "amount": money_str(net_profit) if net_profit > 0 else "0.00"},
                ]
                total_additions = money_str(total_add)
    
                deductions = [
                    {"label": "Fixed Assets & Equipment", "label_ar": "الأصول الثابتة والمعدات", "amount": money_str(fixed_assets)},
                    {"label": "Intangible Assets (Goodwill, Patents)", "label_ar": "الأصول المعنوية (شهرة، براءات)", "amount": money_str(intangible_assets)},
                    {"label": "Long-term Investments", "label_ar": "الاستثمارات طويلة الأجل", "amount": money_str(lt_investments)},
                ]
                if wip:
                    deductions.append({"label": "Work in Progress / Under Construction", "label_ar": "مشروعات تحت التنفيذ", "amount": money_str(wip)})
                total_deductions = money_str(total_ded)
    
                details = {
                    "method_name_ar": "طريقة صافي الملكية — ZATCA (المعتمدة نظامياً)",
                    "method_name_en": "Net Equity Method — ZATCA (Regulatory)",
                    "note": "الطريقة المعتمدة نظامياً من هيئة الزكاة والضريبة والجمارك للشركات السعودية",
                    "zakat_base": money_str(zakat_base),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": rate_str(rate)
                }
    
            else:  # adjusted_profit
                # Revenue
                ap_rev_sql, ap_rev_params = _zakat_balance_query("1=1", ['revenue', 'income', 'other_income'], branch_id, sign="credit")
                revenue = db.execute(text(ap_rev_sql), ap_rev_params).scalar() or 0
    
                # Expenses
                ap_exp_sql, ap_exp_params = _zakat_balance_query("1=1", ['expense', 'cogs', 'other_expense'], branch_id, sign="debit")
                expenses = db.execute(text(ap_exp_sql), ap_exp_params).scalar() or 0
    
                net_profit = Decimal(str(revenue)) - Decimal(str(expenses))
    
                # Add-backs: Non-deductible items
                dep_filter = "a.name LIKE '%%استهلاك%%' OR a.name LIKE '%%إهلاك%%' OR a.name_en LIKE '%%depreciation%%' OR a.name_en LIKE '%%amortization%%'"
                dep_sql, dep_params = _zakat_balance_query(dep_filter, ['expense'], branch_id, sign="debit")
                depreciation = db.execute(text(dep_sql), dep_params).scalar() or 0
    
                provexp_filter = "a.name LIKE '%%مخصص%%' OR a.name_en LIKE '%%provision%%'"
                provexp_sql, provexp_params = _zakat_balance_query(provexp_filter, ['expense'], branch_id, sign="debit")
                provision_expense = db.execute(text(provexp_sql), provexp_params).scalar() or 0
    
                pen_filter = "a.name LIKE '%%غرام%%' OR a.name LIKE '%%جزاء%%' OR a.name_en LIKE '%%penalty%%' OR a.name_en LIKE '%%fine%%'"
                pen_sql, pen_params = _zakat_balance_query(pen_filter, ['expense'], branch_id, sign="debit")
                penalties = db.execute(text(pen_sql), pen_params).scalar() or 0
    
                total_add_backs = Decimal(str(depreciation)) + Decimal(str(provision_expense)) + Decimal(str(penalties))
                adjusted_profit = net_profit + total_add_backs
    
                zakat_base = max(Decimal('0'), adjusted_profit)
                zakat_amount = (zakat_base * rate / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
                additions = [
                    {"label": "Revenue", "label_ar": "الإيرادات", "amount": money_str(revenue)},
                    {"label": "Less: Expenses", "label_ar": "(-) المصروفات", "amount": money_str(-expenses) if expenses else "0.00"},
                    {"label": "Net Profit", "label_ar": "صافي الربح", "amount": money_str(net_profit), "is_subtotal": True},
                    {"label": "Add: Depreciation", "label_ar": "(+) الاستهلاك/الإهلاك", "amount": money_str(depreciation)},
                    {"label": "Add: Provisions", "label_ar": "(+) المخصصات", "amount": money_str(provision_expense)},
                    {"label": "Add: Penalties & Fines", "label_ar": "(+) الغرامات والجزاءات", "amount": money_str(penalties)},
                ]
                total_additions = money_str(adjusted_profit)
                deductions = []
                total_deductions = "0.00"
    
                details = {
                    "method_name_ar": "طريقة الربح المُعدَّل",
                    "method_name_en": "Adjusted Profit Method",
                    "zakat_base": money_str(zakat_base),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": rate_str(rate)
                }
    
            method_names = {
                "net_assets": "صافي الملكية — ZATCA",
                "net_current_assets": "صافي الأصول المتداولة",
                "adjusted_profit": "الربح المُعدَّل"
            }

            def stringify_tax_numbers(value):
                if isinstance(value, list):
                    return [stringify_tax_numbers(item) for item in value]
                if isinstance(value, dict):
                    out = {}
                    for key, item in value.items():
                        if key in {"amount", "zakat_base", "zakat_amount", "total_additions", "total_deductions"}:
                            out[key] = money_str(item)
                        elif key in {"applied_rate", "zakat_rate"}:
                            out[key] = rate_str(item)
                        else:
                            out[key] = stringify_tax_numbers(item)
                    return out
                return value

            additions = stringify_tax_numbers(additions)
            deductions = stringify_tax_numbers(deductions)
            details = stringify_tax_numbers(details)
            total_additions = money_str(total_additions)
            total_deductions = money_str(total_deductions)
            calculation_details = {
                "version": CALCULATION_VERSION,
                "country_code": country_code,
                "branch_scope": branch_scope,
                "method": body.method,
                "rate_source": "company_settings" if body.use_gregorian_rate else "tax_regimes",
                "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                "amount_currency": base_currency,
                "currency_method": "GL balances are calculated and stored in company base currency",
            }
    
            # Save calculation
            existing_calc = db.execute(text("""
                SELECT id
                FROM zakat_calculations
                WHERE fiscal_year = :fy
                  AND branch_scope_key = :scope_key
                FOR UPDATE
            """), {"fy": body.fiscal_year, "scope_key": scope_key}).fetchone()
            params_calc = {
                "fy": body.fiscal_year, "method": body.method,
                "branch_id": selected_branch_id,
                "scope_key": scope_key,
                "branch_ids": json.dumps(scoped_branch_ids) if scoped_branch_ids is not None else None,
                "base": zakat_base, "rate": rate,
                "amt": zakat_amount, "details": json.dumps(details),
                "calc_details": json.dumps(calculation_details),
                "calc_version": CALCULATION_VERSION,
                "currency": base_currency,
                "base_currency": base_currency,
                "idempotency_key": idempotency_key,
                "uid": user_id, "notes": body.notes
            }
            if existing_calc:
                db.execute(text("""
                    UPDATE zakat_calculations
                       SET method = :method,
                           branch_id = :branch_id,
                           branch_scope_key = :scope_key,
                           branch_ids = :branch_ids,
                           zakat_base = :base,
                           zakat_rate = :rate,
                           zakat_amount = :amt,
                           details = CAST(:details AS jsonb),
                           calculation_details = CAST(:calc_details AS jsonb),
                           calculation_version = :calc_version,
                           currency = :currency,
                           base_currency = :base_currency,
                           idempotency_key = :idempotency_key,
                           status = 'calculated',
                           calculated_by = :uid,
                           calculated_at = CURRENT_TIMESTAMP,
                           updated_at = CURRENT_TIMESTAMP,
                           notes = :notes
                     WHERE id = :id
                """), {**params_calc, "id": existing_calc.id})
            else:
                db.execute(text("""
                    INSERT INTO zakat_calculations (
                        fiscal_year, branch_id, branch_scope_key, branch_ids,
                        method, zakat_base, zakat_rate, zakat_amount,
                        details, calculation_details, calculation_version, currency, base_currency,
                        idempotency_key, status, calculated_by, notes
                    ) VALUES (
                        :fy, :branch_id, :scope_key, :branch_ids,
                        :method, :base, :rate, :amt,
                        CAST(:details AS jsonb), CAST(:calc_details AS jsonb), :calc_version,
                        :currency, :base_currency, :idempotency_key, 'calculated', :uid, :notes
                    )
                """), params_calc)
    
            return {
                **display_currency_fields(base_display_meta),
                "fiscal_year": body.fiscal_year,
                "method": body.method,
                "method_ar": method_names.get(body.method, body.method),
                "details": details,
                "additions": additions,
                "total_additions": total_additions,
                "deductions": deductions,
                "total_deductions": total_deductions,
                "zakat_base": money_str(zakat_base),
                "zakat_rate": rate_str(rate),
                "rate_display": f"{rate_str(rate)}%",
                "zakat_amount": money_str(zakat_amount),
                "branch_id": selected_branch_id,
                "calculation_version": CALCULATION_VERSION,
                "message": i18n_message("zakat_due_amount", request)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/accounting/zakat/{fiscal_year}/post",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Zakat"], response_model=Dict[str, Any])
def post_zakat_entry(
    fiscal_year: int,
    request: Request,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """ترحيل قيد الزكاة — Dr: مصروف زكاة → Cr: زكاة مستحقة"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    branch_scope = resolve_branch_scope(current_user, branch_id)
    selected_branch_id = branch_scope["branch_id"]
    scope_key, _scoped_branch_ids = zakat_branch_scope_key(branch_scope)
    if selected_branch_id:
        scope_key = f"branch:{selected_branch_id}"
    with transactional(company_id) as db:
        try:
            idempotency_key = get_idempotency_key(
                request,
                fallback=f"zakat-post:{fiscal_year}:branch:{selected_branch_id or 'all'}",
            )
            zakat = db.execute(text(
                """
                SELECT *
                FROM zakat_calculations
                WHERE fiscal_year = :fy
                  AND branch_scope_key = :scope_key
                FOR UPDATE
                """
            ), {"fy": fiscal_year, "scope_key": scope_key}).fetchone()
    
            if not zakat:
                raise HTTPException(**http_error(404, "zakat_not_calculated", request))
            if zakat.status == 'posted':
                raise HTTPException(**http_error(400, "zakat_already_posted", request))
    
            amount = Decimal(str(zakat.zakat_amount))
            if amount <= 0:
                raise HTTPException(**http_error(400, "zakat_amount_zero", request))
    
            # Phase 5 / ZAK-F01: enforce fiscal lock on zakat posting date
            check_fiscal_period_open(db, f"{fiscal_year}-12-31")
    
            currency = get_base_currency(db)
    
            # TASK-015: route through centralized GL service (idempotent, validated, audited)
            exp_acc = get_mapped_account_id(db, "acc_map_zakat_expense")
            pay_acc = get_mapped_account_id(db, "acc_map_zakat_payable")
            if not exp_acc or not pay_acc:
                raise HTTPException(**http_error(400, "zakat_accounts_not_mapped", request))
    
            lines = [
                {"account_id": exp_acc, "debit": amount, "credit": 0, "description": "مصروف زكاة"},
                {"account_id": pay_acc, "debit": 0, "credit": amount, "description": "زكاة مستحقة"},
            ]
            je_id, je_number = create_journal_entry(
                db=db,
                company_id=company_id,
                date=f"{fiscal_year}-12-31",
                description=f"زكاة عام {fiscal_year}",
                lines=lines,
                user_id=user_id,
                reference=f"ZAKAT-{fiscal_year}",
                branch_id=selected_branch_id,
                status="posted",
                currency=currency,
                source="Zakat",
                source_id=fiscal_year,
                username=_u(current_user, "username", ""),
                idempotency_key=idempotency_key,
            )
    
            db.execute(text("""
                UPDATE zakat_calculations
                   SET status = 'posted', journal_entry_id = :jeid, updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id
            """), {"jeid": je_id, "id": zakat.id})
    
    
            log_activity(db, user_id, _u(current_user, "username", ""),
                         "zakat.post", "zakat_calculation", str(fiscal_year),
                         {"amount": money_str(amount), "journal_entry": je_number, "branch_id": selected_branch_id})
    
            return {
                "journal_entry_id": je_id,
                "entry_number": je_number,
                "amount": money_str(amount),
                "branch_id": selected_branch_id,
                "message": i18n_message("zakat_entry_posted", request)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ═══════════════════════════════════════════════════════════════════════════════
#  3. CONSOLIDATION REPORTS
#     تقارير توحيد القوائم المالية (متعدد الشركات)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/accounting/fiscal-periods", dependencies=[Depends(require_permission("accounting.view"))],
            tags=["Fiscal Periods"], response_model=List[Dict[str, Any]])
def list_fiscal_periods(current_user: dict = Depends(get_current_user)):
    """List Fiscal Periods."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        create_fiscal_lock_table(db)
        rows = db.execute(text("""
            SELECT fp.*, cu.full_name as locked_by_name
            FROM fiscal_period_locks fp
            LEFT JOIN company_users cu ON cu.id = fp.locked_by
            ORDER BY fp.period_start DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/accounting/fiscal-periods", dependencies=[Depends(require_permission("accounting.manage"))],
             tags=["Fiscal Periods"], response_model=Dict[str, Any])
def create_fiscal_period(request: Request, body: FiscalPeriodLockRequest, current_user: dict = Depends(get_current_user)):
    """Create Fiscal Period."""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        create_fiscal_lock_table(db)

        result = db.execute(text("""
            INSERT INTO fiscal_period_locks (period_name, period_start, period_end, is_locked, reason)
            VALUES (:name, :start, :end, false, :reason)
            RETURNING id
        """), {
            "name": body.period_name, "start": body.period_start,
            "end": body.period_end, "reason": body.reason
        })
        period_id = result.fetchone()[0]

        return {"id": period_id, "message": i18n_message("accounting_period_created", request)}


@router.post("/accounting/fiscal-periods/{period_id}/lock",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Fiscal Periods"], response_model=Dict[str, Any])
def lock_fiscal_period(period_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """قفل الفترة المحاسبية — منع إدخال أي قيود فيها"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        period = db.execute(text("SELECT * FROM fiscal_period_locks WHERE id = :id"), {"id": period_id}).fetchone()
        if not period:
            raise HTTPException(**http_error(404, "fiscal_period_not_found", request))
        if period.is_locked:
            raise HTTPException(**http_error(400, "period_already_locked", request))

        db.execute(text("""
            UPDATE fiscal_period_locks SET
                is_locked = true, locked_at = CURRENT_TIMESTAMP, locked_by = :uid
            WHERE id = :id
        """), {"uid": user_id, "id": period_id})

        log_activity(db, user_id, _u(current_user, "username", ""),
                     "fiscal_period.lock", "fiscal_period", str(period_id),
                     {"period_name": period.period_name})

        return {"message": i18n_message("period_locked", request)}


@router.post("/accounting/fiscal-periods/{period_id}/unlock",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Fiscal Periods"], response_model=Dict[str, Any])
def unlock_fiscal_period(period_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """فتح الفترة المحاسبية"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        db.execute(text("""
            UPDATE fiscal_period_locks SET
                is_locked = false, unlocked_at = CURRENT_TIMESTAMP, unlocked_by = :uid
            WHERE id = :id
        """), {"uid": user_id, "id": period_id})

        return {"message": i18n_message("fiscal_period_opened", request)}


# ═══════════════════════════════════════════════════════════════════════════════
#  5. DUPLICATE DETECTION ENDPOINTS
#     كشف التكرارات
# ═══════════════════════════════════════════════════════════════════════════════
