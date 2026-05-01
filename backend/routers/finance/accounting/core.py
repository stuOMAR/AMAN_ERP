"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from utils.cache import invalidate_company_cache
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from schemas.accounting import AccountCreate, AccountUpdate, FiscalYearCreate, FiscalYearClose, FiscalYearReopen
from utils.cache import cache
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")

@router.get("/summary", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_accounting_summary(
    request: Request,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ملخص إحصائيات المحاسبة"""
    branch_id = validate_branch_access(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        if branch_id:
            # Calculate branch-specific summary
            # Standard: Asset/Expense balance = Debit - Credit, Others = Credit - Debit
            # Revenue summary
            total_income = db.execute(text("""
                SELECT COALESCE(SUM(jl.credit - jl.debit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_type = 'revenue' AND je.branch_id = :branch_id
            """), {"branch_id": branch_id}).scalar() or 0
            
            # Expense summary
            total_expenses = db.execute(text("""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_type = 'expense' AND je.branch_id = :branch_id
            """), {"branch_id": branch_id}).scalar() or 0
            
            # Cash/Bank summary
            # Cash/Bank summary
            # Dynamic Treasury Lookup
            treasury_ids = [row[0] for row in db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE is_active = true")).fetchall() if row[0]]
            legacy_ids = [row[0] for row in db.execute(text("SELECT id FROM accounts WHERE account_code LIKE 'BOX%' OR account_code LIKE 'BNK%'")).fetchall()]
            all_cash_ids = list(set(treasury_ids + legacy_ids))
            
            cash_balance = 0
            if all_cash_ids:
                 cash_balance = db.execute(text("""
                    SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    WHERE a.id = ANY(:cash_ids)
                    AND je.branch_id = :branch_id
                """), {"cash_ids": all_cash_ids, "branch_id": branch_id}).scalar() or 0
        else:
            # 1. Total Income (Revenue accounts balance)
            total_income = db.execute(text("SELECT COALESCE(SUM(balance), 0) FROM accounts WHERE account_type = 'revenue'")).scalar() or 0
            
            # 2. Total Expenses (Expense accounts balance)
            total_expenses = db.execute(text("SELECT COALESCE(SUM(balance), 0) FROM accounts WHERE account_type = 'expense'")).scalar() or 0
            
            # 3. Cash/Bank Balance (Asset accounts with BOX or BNK codes OR linked to treasury)
            # Dynamic Treasury Lookup
            treasury_ids = [row[0] for row in db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE is_active = true")).fetchall() if row[0]]
            legacy_ids = [row[0] for row in db.execute(text("SELECT id FROM accounts WHERE account_code LIKE 'BOX%' OR account_code LIKE 'BNK%'")).fetchall()]
            all_cash_ids = list(set(treasury_ids + legacy_ids))
            
            cash_balance = 0
            if all_cash_ids:
                cash_balance = db.execute(text("""
                    SELECT COALESCE(SUM(balance), 0) FROM accounts 
                    WHERE id = ANY(:cash_ids)
                """), {"cash_ids": all_cash_ids}).scalar() or 0
        
        return {
            "total_income": float(total_income),
            "total_expenses": float(total_expenses),
            "net_profit": float(total_income - total_expenses),
            "cash_balance": float(cash_balance)
        }
# ── MODULE-001: Map account_code to the module it belongs to ──
# Used to show module tags in COA and for module-based filtering
_ACCOUNT_MODULE_MAP = {
    # Manufacturing (legacy codes)
    "RM-INV":   "manufacturing",
    "FG-INV":   "manufacturing",
    "WIP":      "manufacturing",
    "CGS-MFG":  "manufacturing",
    "LABOR":    "manufacturing",
    "MFG-OH":   "manufacturing",
    # Inventory / Stock (legacy codes)
    "INV":      "stock",
    "INV-ADJ":  "stock",
    # POS (legacy codes)
    "CASH-OS":  "pos",
    # Services (legacy codes)
    "SALE-S":   "services",
    # HR (legacy codes)
    "SAL":      "hr",
    "GOSI-EXP": "hr",
    "ADV":      "hr",
}

# Numeric code prefix → module mapping (for SOCPA/IFRS-coded accounts)
# يغطي كل الحسابات المُزروعة من industry_coa_templates
_NUMERIC_CODE_MODULE_MAP = {
    "13":    "stock",           # مخزون — كل حسابات المخزون
    "130":   "stock",           # فرعيات المخزون
    "1301":  "stock",           # بضاعة بالطريق / WIP
    "1302":  "stock",           # مخزون إنتاج تام / بضاعة لدى وكلاء
    "1303":  "stock",           # قطع غيار / أصول بيولوجية
    "1304":  "stock",           # أصول بيولوجية فرعية
    "1305":  "stock",           # أصول بيولوجية أشجار
    "510":   "stock",           # تكلفة بضاعة فرعية
    "51010": "stock",           # COGS variants
    "51020": "stock",           # فروقات جرد / عمولات
    "51030": "manufacturing",   # تكاليف غير مباشرة
    "51040": "manufacturing",   # هدر إنتاج
    "51050": "manufacturing",   # فروقات تكلفة معيارية
    "16030": "manufacturing",   # معدات صناعية / ثقيلة
    "16040": "manufacturing",   # خطوط إنتاج / سقالات
    "18004": "manufacturing",   # إهلاك متراكم — آلات
    "18005": "manufacturing",   # إهلاك متراكم — خطوط إنتاج
    "41010": "sales",           # إيرادات فرعية
    "41020": "sales",           # مردودات / مبيعات فرعية
    "41030": "sales",           # خصم / إيرادات فرعية
    "41040": "sales",           # مردودات أدوية / أعلاف
    "61030": "hr",              # أجور عمال مباشرة
    "61040": "hr",              # أجور خدمة
    "15020": "projects",        # تكاليف مشاريع مؤجلة / WIP خدمات
    "21090": "projects",        # محتجزات موردين
    "21100": "projects",        # مقاولين من الباطن
}

def _account_code_to_module(code: str) -> str | None:
    """Return the module key this account belongs to, or None for core/shared accounts."""
    if not code:
        return None
    # 1) Check exact match (legacy codes)
    m = _ACCOUNT_MODULE_MAP.get(code)
    if m:
        return m
    # 2) Check numeric prefix (longest prefix first)
    for prefix_len in (5, 4, 3, 2):
        if len(code) >= prefix_len:
            prefix = code[:prefix_len]
            m = _NUMERIC_CODE_MODULE_MAP.get(prefix)
            if m:
                return m
    return None
def _create_entry_from_template(db, tmpl, lines, current_user):
    """Helper: إنشاء قيد يومي من قالب متكرر"""

    today = date.today()
    entry_status = "posted" if tmpl.auto_post else "draft"
    description = f"{tmpl.name} - {today.strftime('%Y-%m-%d')}"
    if tmpl.description:
        description = f"{tmpl.description} ({today.strftime('%Y-%m-%d')})"

    # Fiscal-period lock: refuse to generate recurring posts into a
    # closed period (only when we're about to post, not for drafts).
    if entry_status == "posted":
        check_fiscal_period_open(db, today)

    je_lines = []
    for line in lines:
        je_lines.append({
            "account_id": line.account_id,
            "debit": _dec(line.debit or 0),
            "credit": _dec(line.credit or 0),
            "description": line.description or "",
            "cost_center_id": line.cost_center_id,
        })

    entry_id, _ = gl_create_journal_entry(
        db=db,
        company_id=current_user.company_id,
        date=str(today),
        description=description,
        lines=je_lines,
        user_id=current_user.id,
        branch_id=tmpl.branch_id or getattr(current_user, "branch_id", None),
        reference=tmpl.reference or f"REC-{tmpl.id}",
        status=entry_status,
        currency=tmpl.currency or get_base_currency(db),
        exchange_rate=_dec(tmpl.exchange_rate or 1),
        source="recurring_template",
        source_id=tmpl.id,
    )

    # Update template tracking
    freq_map = {
        "daily": relativedelta(days=1),
        "weekly": relativedelta(weeks=1),
        "monthly": relativedelta(months=1),
        "quarterly": relativedelta(months=3),
        "yearly": relativedelta(years=1),
    }
    next_date = today + freq_map.get(tmpl.frequency, relativedelta(months=1))

    new_run_count = (tmpl.run_count or 0) + 1
    should_deactivate = tmpl.max_runs and new_run_count >= tmpl.max_runs

    db.execute(text("""
        UPDATE recurring_journal_templates SET
            last_run_date = :today,
            next_run_date = :next,
            run_count = :count,
            is_active = :active,
            updated_at = NOW()
        WHERE id = :id
    """), {
        "today": today,
        "next": next_date,
        "count": new_run_count,
        "active": not should_deactivate,
        "id": tmpl.id,
    })

    return entry_id
# ==================== ACC-005: Opening Balances ====================

class ProvisionRequest(BaseModel):
    amount: float
    description: Optional[str] = None
    branch_id: Optional[int] = None

class FXRevaluationRequest(BaseModel):
    currency_code: str
    new_rate: float
    branch_id: Optional[int] = None

