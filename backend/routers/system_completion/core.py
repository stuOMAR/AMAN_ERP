"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from typing import Any, Dict, Optional
from pydantic import BaseModel
from decimal import Decimal
import logging
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
from utils.duplicate_detection import find_duplicate_parties, find_duplicate_products
from utils.tax_precision import money_str

logger = logging.getLogger(__name__)

def _u(current_user, key, default=None):
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)

router = APIRouter()

def _u(current_user, key, default=None):
    """Safely get attribute from dict or Pydantic model."""
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)


# ═══════════════════════════════════════════════════════════════════════════════
#  1. BANK STATEMENT IMPORT
#     استيراد كشف الحساب البنكي (CSV/Excel)
# ═══════════════════════════════════════════════════════════════════════════════

class BankImportLineUpdate(BaseModel):
    status: Optional[str] = None  # matched, unmatched, ignored
    matched_transaction_id: Optional[int] = None
    account_id: Optional[int] = None
    notes: Optional[str] = None


class ZakatCalculateRequest(BaseModel):
    fiscal_year: int
    method: str = "net_assets"  # net_assets (ZATCA, default), net_current_assets, adjusted_profit
    zakat_rate: Optional[Decimal] = None
    use_gregorian_rate: bool = False
    branch_id: Optional[int] = None  # Filter by branch (None = all branches)
    notes: Optional[str] = None


def _zakat_scope_filter(branch_scope) -> tuple[str, dict, bool]:
    if isinstance(branch_scope, dict):
        if branch_scope.get("branch_id") is not None:
            return "AND je.branch_id = :branch_id", {"branch_id": branch_scope["branch_id"]}, True
        if branch_scope.get("branch_ids") is not None:
            ids = list(branch_scope.get("branch_ids") or [])
            if not ids:
                return "AND 1=0", {}, True
            return "AND je.branch_id = ANY(:branch_ids)", {"branch_ids": ids}, True
        return "", {}, False
    if branch_scope:
        return "AND je.branch_id = :branch_id", {"branch_id": branch_scope}, True
    return "", {}, False


def _zakat_balance_query(account_filter: str, account_types: list, branch_id=None, sign="debit"):
    """
    Build a balance query that supports branch filtering.
    When branch_id is None: use accounts.balance (fast, all branches).
    When branch_id is set: compute from journal_lines (branch-specific).
    sign='debit' means debit-normal (assets/expenses), 'credit' means credit-normal (liabilities/equity/revenue).
    Returns (sql_string, params_dict).
    """
    type_list = "','".join(account_types)
    branch_filter, branch_params, scoped = _zakat_scope_filter(branch_id)
    if scoped:
        if sign == "debit":
            agg = "SUM(jl.debit - jl.credit)"
        else:
            agg = "SUM(jl.credit - jl.debit)"
        sql = f"""
            SELECT COALESCE({agg}, 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id AND je.status = 'posted'
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type IN ('{type_list}')
            AND ({account_filter})
            {branch_filter}
        """
        return sql, branch_params
    else:
        # For all branches: use ABS(balance) for credit-normal accounts
        if sign == "credit":
            sql = f"""
                SELECT COALESCE(SUM(ABS(a.balance)), 0)
                FROM accounts a WHERE a.account_type IN ('{type_list}')
                AND ({account_filter})
            """
        else:
            sql = f"""
                SELECT COALESCE(SUM(a.balance), 0)
                FROM accounts a WHERE a.account_type IN ('{type_list}')
                AND ({account_filter})
            """
        return sql, {}


def _zakat_account_breakdown(db, account_filter: str, account_types: list, branch_id=None, sign="debit"):
    """
    Return list of individual accounts that matched the filter, with their balances.
    Used for debugging/audit to show which accounts contributed.
    """
    type_list = "','".join(account_types)
    branch_filter, branch_params, scoped = _zakat_scope_filter(branch_id)
    if scoped:
        if sign == "debit":
            agg = "SUM(jl.debit - jl.credit)"
        else:
            agg = "SUM(jl.credit - jl.debit)"
        sql = f"""
            SELECT a.account_code, a.name, a.name_en, {agg} as balance
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id AND je.status = 'posted'
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type IN ('{type_list}')
            AND ({account_filter})
            {branch_filter}
            GROUP BY a.id, a.account_code, a.name, a.name_en
            HAVING {agg} != 0
            ORDER BY a.account_code
        """
        rows = db.execute(text(sql), branch_params).fetchall()
    else:
        sql = f"""
            SELECT a.account_code, a.name, a.name_en, a.balance
            FROM accounts a WHERE a.account_type IN ('{type_list}')
            AND ({account_filter})
            AND a.balance != 0
            ORDER BY a.account_code
        """
        rows = db.execute(text(sql)).fetchall()
    return [{"code": r.account_code, "name": r.name, "name_en": r.name_en, "balance": money_str(r.balance)} for r in rows]


class FiscalPeriodLockRequest(BaseModel):
    period_name: str
    period_start: str
    period_end: str
    reason: Optional[str] = None


class DuplicateCheckPartyRequest(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_number: Optional[str] = None
    exclude_id: Optional[int] = None


class DuplicateCheckProductRequest(BaseModel):
    product_name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    exclude_id: Optional[int] = None


@router.post("/parties/check-duplicates", dependencies=[Depends(require_permission("parties.view"))],
             tags=["Duplicate Detection"], response_model=Dict[str, Any])
def check_party_duplicates(body: DuplicateCheckPartyRequest,
                           current_user: dict = Depends(get_current_user)):
    """فحص التكرارات قبل إضافة عميل/مورد"""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        matches = find_duplicate_parties(
            db, name=body.name, phone=body.phone, email=body.email,
            tax_number=body.tax_number, exclude_id=body.exclude_id
        )
        return {
            "has_duplicates": len(matches) > 0,
            "count": len(matches),
            "matches": matches
        }


@router.post("/inventory/check-duplicates", dependencies=[Depends(require_permission("inventory.view"))],
             tags=["Duplicate Detection"], response_model=Dict[str, Any])
def check_product_duplicates(body: DuplicateCheckProductRequest,
                             current_user: dict = Depends(get_current_user)):
    """فحص التكرارات قبل إضافة منتج"""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        matches = find_duplicate_products(
            db, product_name=body.product_name, sku=body.sku,
            barcode=body.barcode, exclude_id=body.exclude_id
        )
        return {
            "has_duplicates": len(matches) > 0,
            "count": len(matches),
            "matches": matches
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  6. BACKUP / RESTORE
#     النسخ الاحتياطي واستعادة البيانات (pg_dump)
# ═══════════════════════════════════════════════════════════════════════════════

class PrintTemplateCreate(BaseModel):
    template_type: str  # invoice, quotation, receipt, delivery_order, purchase_order, payslip
    name: str
    html_template: str
    css_styles: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    is_default: bool = False
    paper_size: str = "A4"
    orientation: str = "portrait"

