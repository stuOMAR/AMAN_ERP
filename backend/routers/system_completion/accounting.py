"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
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

from .core import FiscalPeriodLockRequest, ZakatCalculateRequest

@router.post("/accounting/zakat/calculate", dependencies=[Depends(require_permission("accounting.manage"))],
             tags=["Zakat"], response_model=Dict[str, Any])
def calculate_zakat(body: ZakatCalculateRequest, current_user: dict = Depends(get_current_user)):
    """
    حساب الزكاة الشرعية — Sharia-compliant Zakat Calculation
    Supports branch filtering via branch_id parameter.
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            # Validate branch access
            branch_id = validate_branch_access(current_user, body.branch_id) if body.branch_id else None
    
            # Determine rate (Decimal for legal tax precision)
            rate = Decimal('2.57764') if body.use_gregorian_rate else Decimal(str(body.zakat_rate))
    
            if body.method == "net_current_assets":
                # ══════════════════════════════════════════════════════════════
                # طريقة صافي الأصول المتداولة — Net Current Assets Method
                # وفقاً لمعايير AAOIFI وجمهور الفقهاء
                # الوعاء = النقد + عروض التجارة + المدينون المرجوون
                #        + استثمارات المضاربة - الالتزامات المتداولة
                # ══════════════════════════════════════════════════════════════
    
                # ── النقد (أصل الأصول المالية في الزكاة بالإجماع) ──
                cash_filter = """
                        a.account_code LIKE '1101%%'
                        OR a.account_code LIKE '11001%%'
                        OR a.account_code LIKE '11010%%'
                        OR a.account_code LIKE '11020%%'
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
                        a.account_code LIKE '1103%%'
                        OR a.account_code LIKE '13001%%'
                        OR a.account_code LIKE '13010%%'
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
                        a.account_code LIKE '1102%%' OR a.account_code LIKE '1108%%'
                        OR a.account_code LIKE '1109%%'
                        OR a.account_code LIKE '12001%%' OR a.account_code LIKE '12010%%'
                        OR a.account_code LIKE '12020%%'
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
                        a.account_code LIKE '21%%'
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
                        a.account_code LIKE '12%%' OR a.account_code LIKE '15%%'
                        OR a.account_code LIKE '16%%'
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
                        a.account_code LIKE '13%%' OR a.account_code LIKE '18%%'
                        OR a.name LIKE '%%شهرة%%' OR a.name LIKE '%%براءة%%'
                        OR a.name LIKE '%%علامة تجارية%%' OR a.name LIKE '%%رخصة%%'
                        OR a.name LIKE '%%غير ملموس%%'
                        OR a.name_en LIKE '%%intangible%%' OR a.name_en LIKE '%%goodwill%%'
                        OR a.name_en LIKE '%%patent%%' OR a.name_en LIKE '%%trademark%%'
                """
                intang_sql, intang_params = _zakat_balance_query(intang_filter, ['asset'], branch_id)
                intangible_assets = db.execute(text(intang_sql), intang_params).scalar() or 0
    
                wip_filter = """
                        a.account_code LIKE '1110%%'
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
                    {"label": "Cash & Bank Balances", "label_ar": "النقد والأرصدة البنكية", "amount": float(Decimal(str(cash)).quantize(Decimal('0.01')))},
                ]
                if quasi_cash:
                    additions.append({"label": "Less: Quasi-Cash / Investment Deposits", "label_ar": "(-) النقد المعادل / ودائع استثمارية", "amount": float(Decimal(str(-quasi_cash)).quantize(Decimal('0.01')))})
                additions.append({"label": "Net Cash", "label_ar": "صافي النقد", "amount": float(net_cash.quantize(Decimal('0.01'))), "is_subtotal": True})
    
                additions.append({"label": "Trade Goods (Inventory for Sale)", "label_ar": "عروض التجارة (المخزون المعد للبيع)", "amount": float(Decimal(str(trade_goods)).quantize(Decimal('0.01')))})
                if stale_inventory:
                    additions.append({"label": "Less: Stale/Obsolete Inventory", "label_ar": "(-) بضاعة كاسدة / راكدة", "amount": float(Decimal(str(-stale_inventory)).quantize(Decimal('0.01')))})
                additions.append({"label": "Net Trade Goods", "label_ar": "صافي عروض التجارة", "amount": float(net_trade_goods.quantize(Decimal('0.01'))), "is_subtotal": True})
    
                if receivables:
                    additions.append({"label": "Collectible Receivables", "label_ar": "المدينون المرجوون (مرجو تحصيلهم)", "amount": float(Decimal(str(receivables)).quantize(Decimal('0.01')))})
                if trading_investments:
                    additions.append({"label": "Trading Investments (Short-term)", "label_ar": "استثمارات المضاربة (قصيرة الأجل)", "amount": float(Decimal(str(trading_investments)).quantize(Decimal('0.01')))})
    
                total_additions = str(gross_zakatable.quantize(Decimal('0.01')))
    
                deductions = []
                if current_liabilities:
                    deductions.append({"label": "Current Liabilities (Short-term Debts)", "label_ar": "الالتزامات المتداولة (الديون الحالة قصيرة الأجل)", "amount": float(cl_decimal.quantize(Decimal('0.01')))})
                total_deductions = str(cl_decimal.quantize(Decimal('0.01')))
    
                # الأصول المستبعدة (للعرض فقط — informational)
                excluded_info = []
                if fixed_assets:
                    excluded_info.append({"label": "Fixed Assets (non-zakatable)", "label_ar": "الأصول الثابتة (قنية — لا تُزكّى)", "amount": float(Decimal(str(fixed_assets)).quantize(Decimal('0.01')))})
                if intangible_assets:
                    excluded_info.append({"label": "Intangible Assets", "label_ar": "الأصول المعنوية (غير ملموسة)", "amount": float(Decimal(str(intangible_assets)).quantize(Decimal('0.01')))})
                if wip:
                    excluded_info.append({"label": "Work In Progress / Raw Materials", "label_ar": "تحت الإنشاء / مواد خام", "amount": float(Decimal(str(wip)).quantize(Decimal('0.01')))})
    
                details = {
                    "method_name_ar": "طريقة صافي الأصول المتداولة",
                    "method_name_en": "Net Current Assets Method (AAOIFI)",
                    "sharia_basis": "النقد + عروض التجارة + المدينون المرجوون - الديون الحالة (وفقاً لجمهور الفقهاء ومعايير AAOIFI)",
                    "excluded_assets": excluded_info,
                    "zakat_base": float(zakat_base.quantize(Decimal('0.01'))),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": float(rate),
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
                        OR a.account_code LIKE '22%%'
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
                        OR a.account_code LIKE '12%%' OR a.account_code LIKE '15%%'
                        OR a.account_code LIKE '16%%'
                """
                zatca_fa_sql, zatca_fa_params = _zakat_balance_query(zatca_fa_filter, ['asset'], branch_id)
                fixed_assets = db.execute(text(zatca_fa_sql), zatca_fa_params).scalar() or 0
    
                # 6. Long-term investments (fixed: removed overly-broad '%استثمار%' pattern)
                zatca_inv_filter = """
                        a.name LIKE '%%استثمار%%طويل%%'
                        OR a.name_en LIKE '%%long%%invest%%'
                        OR a.account_code LIKE '14%%'
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
                        OR a.account_code LIKE '1301%%' OR a.account_code LIKE '1302%%'
                        OR a.account_code LIKE '1303%%' OR a.account_code LIKE '1304%%'
                        OR a.account_code LIKE '1305%%' OR a.account_code LIKE '18%%'
                """
                zatca_intang_sql, zatca_intang_params = _zakat_balance_query(zatca_intang_filter, ['asset'], branch_id)
                intangible_assets = db.execute(text(zatca_intang_sql), zatca_intang_params).scalar() or 0
    
                # 8. Work in progress / under construction (non-zakatable)
                zatca_wip_filter = """
                        a.name LIKE '%%تحت الإنشاء%%' OR a.name LIKE '%%تحت التنفيذ%%'
                        OR a.name LIKE '%%مشروعات تحت%%'
                        OR a.name_en LIKE '%%under construction%%' OR a.name_en LIKE '%%work in progress%%'
                        OR a.account_code LIKE '17%%'
                """
                zatca_wip_sql, zatca_wip_params = _zakat_balance_query(zatca_wip_filter, ['asset'], branch_id)
                wip = db.execute(text(zatca_wip_sql), zatca_wip_params).scalar() or 0
    
                total_ded = Decimal(str(fixed_assets)) + Decimal(str(lt_investments)) + Decimal(str(intangible_assets)) + Decimal(str(wip))
                zakat_base = max(Decimal('0'), total_add - total_ded)
                zakat_amount = (zakat_base * rate / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
                additions = [
                    {"label": "Equity (Capital + Reserves + RE)", "label_ar": "حقوق الملكية (رأس المال + احتياطيات + أرباح مبقاة)", "amount": float(Decimal(str(equity)).quantize(Decimal('0.01')))},
                    {"label": "Long-term Liabilities", "label_ar": "الالتزامات طويلة الأجل", "amount": float(Decimal(str(lt_liabilities)).quantize(Decimal('0.01')))},
                    {"label": "Provisions", "label_ar": "المخصصات", "amount": float(Decimal(str(provisions)).quantize(Decimal('0.01')))},
                    {"label": "Net Profit", "label_ar": "صافي الربح", "amount": float(net_profit.quantize(Decimal('0.01'))) if net_profit > 0 else 0},
                ]
                total_additions = str(total_add.quantize(Decimal('0.01')))
    
                deductions = [
                    {"label": "Fixed Assets & Equipment", "label_ar": "الأصول الثابتة والمعدات", "amount": float(Decimal(str(fixed_assets)).quantize(Decimal('0.01')))},
                    {"label": "Intangible Assets (Goodwill, Patents)", "label_ar": "الأصول المعنوية (شهرة، براءات)", "amount": float(Decimal(str(intangible_assets)).quantize(Decimal('0.01')))},
                    {"label": "Long-term Investments", "label_ar": "الاستثمارات طويلة الأجل", "amount": float(Decimal(str(lt_investments)).quantize(Decimal('0.01')))},
                ]
                if wip:
                    deductions.append({"label": "Work in Progress / Under Construction", "label_ar": "مشروعات تحت التنفيذ", "amount": float(Decimal(str(wip)).quantize(Decimal('0.01')))})
                total_deductions = str(total_ded.quantize(Decimal('0.01')))
    
                details = {
                    "method_name_ar": "طريقة صافي الملكية — ZATCA (المعتمدة نظامياً)",
                    "method_name_en": "Net Equity Method — ZATCA (Regulatory)",
                    "note": "الطريقة المعتمدة نظامياً من هيئة الزكاة والضريبة والجمارك للشركات السعودية",
                    "zakat_base": float(zakat_base.quantize(Decimal('0.01'))),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": float(rate)
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
                    {"label": "Revenue", "label_ar": "الإيرادات", "amount": float(Decimal(str(revenue)).quantize(Decimal('0.01')))},
                    {"label": "Less: Expenses", "label_ar": "(-) المصروفات", "amount": float(Decimal(str(-expenses)).quantize(Decimal('0.01'))) if expenses else 0},
                    {"label": "Net Profit", "label_ar": "صافي الربح", "amount": float(net_profit.quantize(Decimal('0.01'))), "is_subtotal": True},
                    {"label": "Add: Depreciation", "label_ar": "(+) الاستهلاك/الإهلاك", "amount": float(Decimal(str(depreciation)).quantize(Decimal('0.01')))},
                    {"label": "Add: Provisions", "label_ar": "(+) المخصصات", "amount": float(Decimal(str(provision_expense)).quantize(Decimal('0.01')))},
                    {"label": "Add: Penalties & Fines", "label_ar": "(+) الغرامات والجزاءات", "amount": float(Decimal(str(penalties)).quantize(Decimal('0.01')))},
                ]
                total_additions = str(adjusted_profit.quantize(Decimal('0.01')))
                deductions = []
                total_deductions = "0.00"
    
                details = {
                    "method_name_ar": "طريقة الربح المُعدَّل",
                    "method_name_en": "Adjusted Profit Method",
                    "zakat_base": float(zakat_base.quantize(Decimal('0.01'))),
                    "rate_type": "gregorian" if body.use_gregorian_rate else "hijri",
                    "applied_rate": float(rate)
                }
    
            method_names = {
                "net_assets": "صافي الملكية — ZATCA",
                "net_current_assets": "صافي الأصول المتداولة",
                "adjusted_profit": "الربح المُعدَّل"
            }
    
            # Save calculation
            db.execute(text("""
                INSERT INTO zakat_calculations (
                    fiscal_year, method, zakat_base, zakat_rate, zakat_amount,
                    details, status, calculated_by, notes
                ) VALUES (:fy, :method, :base, :rate, :amt, :details, 'calculated', :uid, :notes)
                ON CONFLICT (fiscal_year) DO UPDATE SET
                    method = EXCLUDED.method, zakat_base = EXCLUDED.zakat_base,
                    zakat_rate = EXCLUDED.zakat_rate, zakat_amount = EXCLUDED.zakat_amount,
                    details = EXCLUDED.details, status = EXCLUDED.status,
                    calculated_at = CURRENT_TIMESTAMP, notes = EXCLUDED.notes
            """), {
                "fy": body.fiscal_year, "method": body.method,
                "base": zakat_base, "rate": body.zakat_rate,
                "amt": zakat_amount, "details": json.dumps(details),
                "uid": user_id, "notes": body.notes
            })
    
            return {
                "fiscal_year": body.fiscal_year,
                "method": body.method,
                "method_ar": method_names.get(body.method, body.method),
                "details": details,
                "additions": additions,
                "total_additions": total_additions,
                "deductions": deductions,
                "total_deductions": total_deductions,
                "zakat_base": str(zakat_base.quantize(Decimal('0.01'))),
                "zakat_rate": float(rate),
                "rate_display": f"{float(rate)}%" if body.use_gregorian_rate else f"{body.zakat_rate}%",
                "zakat_amount": str(zakat_amount),
                "branch_id": branch_id,
                "message": f"الزكاة المستحقة: {zakat_amount:,.2f}"
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/accounting/zakat/{fiscal_year}/post",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Zakat"], response_model=Dict[str, Any])
def post_zakat_entry(fiscal_year: int, current_user: dict = Depends(get_current_user)):
    """ترحيل قيد الزكاة — Dr: مصروف زكاة → Cr: زكاة مستحقة"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            zakat = db.execute(text(
                "SELECT * FROM zakat_calculations WHERE fiscal_year = :fy"
            ), {"fy": fiscal_year}).fetchone()
    
            if not zakat:
                raise HTTPException(404, "لم يتم حساب الزكاة لهذا العام")
            if zakat.status == 'posted':
                raise HTTPException(400, "تم ترحيل الزكاة بالفعل لهذا العام المالي")
    
            amount = Decimal(str(zakat.zakat_amount))
            if amount <= 0:
                raise HTTPException(400, "مبلغ الزكاة صفر")
    
            # Phase 5 / ZAK-F01: enforce fiscal lock on zakat posting date
            check_fiscal_period_open(db, f"{fiscal_year}-12-31")
    
            currency = get_base_currency(db)
    
            # TASK-015: route through centralized GL service (idempotent, validated, audited)
            exp_acc = get_mapped_account_id(db, "acc_map_zakat_expense")
            pay_acc = get_mapped_account_id(db, "acc_map_zakat_payable")
            if not exp_acc or not pay_acc:
                raise HTTPException(400, "حسابات الزكاة غير معرّفة في خريطة الحسابات")
    
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
                status="posted",
                currency=currency,
                source="Zakat",
                source_id=fiscal_year,
                username=_u(current_user, "username", ""),
                idempotency_key=f"zakat-{fiscal_year}",
            )
    
            db.execute(text("""
                UPDATE zakat_calculations SET status = 'posted', journal_entry_id = :jeid
                WHERE fiscal_year = :fy
            """), {"jeid": je_id, "fy": fiscal_year})
    
    
            log_activity(db, user_id, _u(current_user, "username", ""),
                         "zakat.post", "zakat_calculation", str(fiscal_year),
                         {"amount": str(amount), "journal_entry": je_number})
    
            return {
                "journal_entry_id": je_id,
                "entry_number": je_number,
                "amount": str(amount),
                "message": f"تم ترحيل قيد الزكاة بمبلغ {amount:,.2f}"
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
def create_fiscal_period(body: FiscalPeriodLockRequest, current_user: dict = Depends(get_current_user)):
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

        return {"id": period_id, "message": "تم إنشاء الفترة المحاسبية"}


@router.post("/accounting/fiscal-periods/{period_id}/lock",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Fiscal Periods"], response_model=Dict[str, Any])
def lock_fiscal_period(period_id: int, current_user: dict = Depends(get_current_user)):
    """قفل الفترة المحاسبية — منع إدخال أي قيود فيها"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        period = db.execute(text("SELECT * FROM fiscal_period_locks WHERE id = :id"), {"id": period_id}).fetchone()
        if not period:
            raise HTTPException(404, "الفترة غير موجودة")
        if period.is_locked:
            raise HTTPException(400, "الفترة مقفلة بالفعل")

        db.execute(text("""
            UPDATE fiscal_period_locks SET
                is_locked = true, locked_at = CURRENT_TIMESTAMP, locked_by = :uid
            WHERE id = :id
        """), {"uid": user_id, "id": period_id})

        log_activity(db, user_id, _u(current_user, "username", ""),
                     "fiscal_period.lock", "fiscal_period", str(period_id),
                     {"period_name": period.period_name})

        return {"message": f"تم قفل الفترة {period.period_name}"}


@router.post("/accounting/fiscal-periods/{period_id}/unlock",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Fiscal Periods"], response_model=Dict[str, Any])
def unlock_fiscal_period(period_id: int, current_user: dict = Depends(get_current_user)):
    """فتح الفترة المحاسبية"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        db.execute(text("""
            UPDATE fiscal_period_locks SET
                is_locked = false, unlocked_at = CURRENT_TIMESTAMP, unlocked_by = :uid
            WHERE id = :id
        """), {"uid": user_id, "id": period_id})

        return {"message": "تم فتح الفترة المحاسبية"}


# ═══════════════════════════════════════════════════════════════════════════════
#  5. DUPLICATE DETECTION ENDPOINTS
#     كشف التكرارات
# ═══════════════════════════════════════════════════════════════════════════════

