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
from utils.permissions import require_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from services.gl_service import (
    create_journal_entry as gl_create_journal_entry,
    reverse_journal_entry as gl_reverse_journal_entry,
)
from utils.fiscal_lock import check_fiscal_period_open
from schemas.accounting import AccountCreate, AccountUpdate, FiscalYearCreate, FiscalYearClose, FiscalYearReopen
from utils.cache import cache
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')


def _user_field(current_user: Any, field: str, default: Any = None) -> Any:
    if isinstance(current_user, dict):
        return current_user.get(field, default)
    return getattr(current_user, field, default)


def _normalize_currency(value: Any, fallback: str = "SAR") -> str:
    currency = str(value or fallback or "SAR").strip().upper()
    return currency or str(fallback or "SAR").strip().upper()


def _currency_rate(db, currency: str, base_currency: str) -> Decimal:
    currency = _normalize_currency(currency, base_currency)
    base_currency = _normalize_currency(base_currency)
    if currency == base_currency:
        return Decimal("1")

    row = db.execute(
        text("""
            SELECT NULLIF(current_rate, 0) AS rate
            FROM currencies
            WHERE UPPER(code) = UPPER(:code)
            LIMIT 1
        """),
        {"code": currency},
    ).fetchone()
    rate = _dec(row.rate if row and row.rate else 1)
    return rate if rate > 0 else Decimal("1")


def _branch_currency(db, branch_id: Optional[int], base_currency: str) -> str:
    if branch_id is None:
        return _normalize_currency(base_currency)
    row = db.execute(
        text("SELECT COALESCE(default_currency, :base) AS currency FROM branches WHERE id = :id"),
        {"id": branch_id, "base": base_currency},
    ).fetchone()
    return _normalize_currency(row.currency if row else base_currency, base_currency)


def _first_int(values: Any) -> Optional[int]:
    for value in values or []:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _require_company_wide_branch_scope(current_user: Any, request: Request) -> None:
    scope = resolve_branch_scope(current_user, None)
    if scope.get("branch_ids") is not None:
        raise HTTPException(**http_error(403, "access_denied", request))


def _resolve_coa_display_currency(db, branch_scope: Dict[str, Any], current_user: Any, base_currency: str) -> Dict[str, Any]:
    base_currency = _normalize_currency(base_currency)
    branch_id = branch_scope.get("branch_id")
    branch_ids = branch_scope.get("branch_ids")
    display_branch_id = branch_id

    if display_branch_id is None:
        if branch_ids:
            allowed_first = _first_int(_user_field(current_user, "allowed_branches", []))
            branch_set = {int(value) for value in branch_ids}
            display_branch_id = allowed_first if allowed_first in branch_set else int(branch_ids[0])
        elif branch_ids is None:
            allowed_first = _first_int(_user_field(current_user, "allowed_branches", []))
            if allowed_first:
                display_branch_id = allowed_first
            else:
                row = db.execute(text("""
                    SELECT id
                    FROM branches
                    WHERE is_active = TRUE
                    ORDER BY is_default DESC, id ASC
                    LIMIT 1
                """)).fetchone()
                display_branch_id = int(row.id) if row else None

    display_currency = _branch_currency(db, display_branch_id, base_currency)
    rate = _currency_rate(db, display_currency, base_currency)
    return {
        "currency": display_currency,
        "base_currency": base_currency,
        "rate": rate,
        "display_branch_id": display_branch_id,
        "is_multi_currency_scope": branch_id is None,
    }


def _base_to_display(value: Decimal, display_meta: Dict[str, Any]) -> Decimal:
    amount = _dec(value)
    if display_meta.get("currency") != display_meta.get("base_currency"):
        rate = _dec(display_meta.get("rate") or 1)
        if rate > 0:
            amount = amount / rate
    return amount

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec, _account_code_to_module

@router.get("/accounts", dependencies=[Depends(require_permission("accounting.view"))], response_model=Any)
@limiter.limit("200/minute")
async def get_chart_of_accounts(
    request: Request,
    search: Optional[str] = None,
    account_type: Optional[str] = None,
    branch_id: Optional[int] = None,
    page: Optional[int] = None,
    page_size: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """Fetch all accounts for the current company, optionally filtered by branch balance"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    
    # Balances are computed live from journal_lines — no caching
    # (accounts/treasury/journal entries can change at any time)
    use_cache = False

    try:

        # Build WHERE clauses for search and type filter
        where_extra = ""
        extra_params = {}
        
        if search:
            where_extra += " AND (a.name ILIKE :search OR a.name_en ILIKE :search OR a.account_number ILIKE :search OR a.account_code ILIKE :search)"
            extra_params["search"] = f"%{search}%"
        if account_type:
            where_extra += " AND a.account_type = :acct_type"
            extra_params["acct_type"] = account_type

        branch_params = {}
        activity_scope_filter = "TRUE"
        treasury_scope_filter = "TRUE"
        scoped_line_condition = "TRUE"
        restrict_visible_accounts = branch_scope["branch_id"] is not None or branch_scope["branch_ids"] is not None

        if branch_scope["branch_id"] is not None:
            branch_params["branch_id"] = branch_scope["branch_id"]
            activity_scope_filter = "je.branch_id = :branch_id"
            treasury_scope_filter = "ta.branch_id = :branch_id"
        elif branch_scope["branch_ids"] is not None:
            if branch_scope["branch_ids"]:
                branch_params["allowed_branch_ids"] = branch_scope["branch_ids"]
                activity_scope_filter = "je.branch_id = ANY(:allowed_branch_ids)"
                treasury_scope_filter = "ta.branch_id = ANY(:allowed_branch_ids)"
            else:
                activity_scope_filter = "FALSE"
                treasury_scope_filter = "FALSE"

        visibility_ctes = ""
        visibility_condition = ""
        rollup_visibility_filter = ""
        if restrict_visible_accounts:
            visibility_ctes = f"""
                scoped_activity AS (
                    SELECT DISTINCT jl.account_id
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.journal_entry_id
                    WHERE je.status = 'posted'
                      AND {activity_scope_filter}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM treasury_accounts ta_owner
                          WHERE ta_owner.is_active = TRUE
                            AND ta_owner.gl_account_id = jl.account_id
                      )
                ),
                scoped_treasury AS (
                    SELECT DISTINCT ta.gl_account_id AS account_id
                    FROM treasury_accounts ta
                    WHERE ta.is_active = TRUE
                      AND ta.gl_account_id IS NOT NULL
                      AND {treasury_scope_filter}
                ),
                visible_seed AS (
                    SELECT account_id FROM scoped_activity
                    UNION
                    SELECT account_id FROM scoped_treasury
                ),
                visible_accounts(id) AS (
                    SELECT account_id FROM visible_seed
                    UNION
                    SELECT parent.id
                    FROM accounts child
                    JOIN visible_accounts va ON va.id = child.id
                    JOIN accounts parent ON parent.id = child.parent_id
                ),
            """
            visibility_condition = "AND a.id IN (SELECT id FROM visible_accounts)"
            rollup_visibility_filter = "AND d.descendant_id IN (SELECT id FROM visible_accounts)"
            scoped_line_condition = f"""
                (
                    EXISTS (SELECT 1 FROM scoped_treasury st WHERE st.account_id = acc.id)
                    OR (
                        NOT EXISTS (
                            SELECT 1
                            FROM treasury_accounts ta_owner
                            WHERE ta_owner.is_active = TRUE
                              AND ta_owner.gl_account_id = acc.id
                        )
                        AND {activity_scope_filter}
                    )
                )
            """

        ctes = f"""
            WITH RECURSIVE
                {visibility_ctes}
                line_balances AS (
                    SELECT
                        acc.id AS account_id,
                        CASE
                            WHEN acc.account_type IN ('asset', 'expense') THEN
                                COALESCE(SUM(COALESCE(jl.debit, 0) - COALESCE(jl.credit, 0)), 0)
                            ELSE
                                COALESCE(SUM(COALESCE(jl.credit, 0) - COALESCE(jl.debit, 0)), 0)
                        END AS balance_base,
                        COALESCE(SUM(
                            CASE
                                WHEN acc.currency IS NULL OR jl.currency IS NULL OR UPPER(jl.currency) <> UPPER(acc.currency) THEN 0
                                WHEN acc.account_type IN ('asset', 'expense') THEN
                                    CASE WHEN COALESCE(jl.debit, 0) > 0 THEN COALESCE(jl.amount_currency, 0) ELSE -COALESCE(jl.amount_currency, 0) END
                                ELSE
                                    CASE WHEN COALESCE(jl.credit, 0) > 0 THEN COALESCE(jl.amount_currency, 0) ELSE -COALESCE(jl.amount_currency, 0) END
                            END
                        ), 0) AS balance_currency
                    FROM accounts acc
                    JOIN journal_lines jl ON jl.account_id = acc.id
                    JOIN journal_entries je ON je.id = jl.journal_entry_id
                    WHERE je.status = 'posted' AND {scoped_line_condition}
                    GROUP BY acc.id, acc.account_type, acc.currency
                ),
                account_descendants(account_id, descendant_id) AS (
                    SELECT id, id FROM accounts
                    UNION ALL
                    SELECT d.account_id, child.id
                    FROM account_descendants d
                    JOIN accounts child ON child.parent_id = d.descendant_id
                ),
                account_rollups AS (
                    SELECT
                        d.account_id,
                        COALESCE(SUM(lb.balance_base), 0) AS balance_base
                    FROM account_descendants d
                    LEFT JOIN line_balances lb ON lb.account_id = d.descendant_id {rollup_visibility_filter}
                    GROUP BY d.account_id
                )
        """

        all_params = {**branch_params, **extra_params}
        query = f"""
            {ctes}
            SELECT
                a.id, a.account_number, a.account_code, a.name, a.name_en, a.account_type,
                a.parent_id, a.currency, a.is_active, a.is_header,
                COALESCE(ar.balance_base, 0) AS balance_base,
                COALESCE(lb.balance_base, 0) AS own_balance_base,
                CASE WHEN COALESCE(a.is_header, FALSE) THEN 0 ELSE COALESCE(lb.balance_currency, 0) END AS balance_currency
            FROM accounts a
            LEFT JOIN account_rollups ar ON ar.account_id = a.id
            LEFT JOIN line_balances lb ON lb.account_id = a.id
            WHERE 1=1 {where_extra} {visibility_condition}
            ORDER BY a.account_number ASC
        """

        count_query = f"""
            {ctes}
            SELECT COUNT(*)
            FROM accounts a
            WHERE 1=1 {where_extra} {visibility_condition}
        """
        total_count = db.execute(text(count_query), all_params).scalar() or 0

        if page is not None and page >= 1:
            query += " LIMIT :limit OFFSET :offset"
            all_params["limit"] = page_size
            all_params["offset"] = (page - 1) * page_size

        result = db.execute(text(query), all_params)
            
        accounts = [dict(row._mapping) for row in result]

        # ── MODULE-001: Add module_tag to each account based on account_code ──
        for acc in accounts:
            acc["module_tag"] = _account_code_to_module(acc.get("account_code", ""))

        # ── CURRENCY-CONVERT: SQL balance is natural balance in base currency.
        # The main display amount follows the selected branch/main-branch currency;
        # original account currency remains available as balance_currency.
        base_currency = get_base_currency(db)
        display_meta = _resolve_coa_display_currency(db, branch_scope, current_user, base_currency)

        rate_rows = db.execute(text("""
            SELECT code, current_rate FROM currencies WHERE is_active = TRUE
        """)).fetchall()
        rate_map = {_normalize_currency(row[0], base_currency): _dec(row[1]) for row in rate_rows}
        rate_map[_normalize_currency(base_currency)] = Decimal("1")

        for acc in accounts:
            acc_currency = _normalize_currency(acc.get("currency"), "") if acc.get("currency") else ""
            raw_balance = _dec(acc.get("balance_base", 0))
            raw_own_balance = _dec(acc.get("own_balance_base", 0))
            raw_balance_currency = _dec(acc.get("balance_currency", 0))
            display_balance = _base_to_display(raw_balance, display_meta)
            display_own_balance = _base_to_display(raw_own_balance, display_meta)

            acc["base_balance"] = str(raw_balance.quantize(_D2, ROUND_HALF_UP))
            acc["own_base_balance"] = str(raw_own_balance.quantize(_D2, ROUND_HALF_UP))
            acc["balance"] = str(display_balance.quantize(_D2, ROUND_HALF_UP))
            acc["own_balance"] = str(display_own_balance.quantize(_D2, ROUND_HALF_UP))
            acc["is_aggregated_balance"] = bool(acc.get("is_header"))
            acc["balance_origin"] = "aggregate" if acc["is_aggregated_balance"] else "own"
            acc["balance_currency"] = str(raw_balance_currency.quantize(_D2, ROUND_HALF_UP))
            acc["exchange_rate"] = str(rate_map.get(acc_currency, Decimal("1")).quantize(_D4, ROUND_HALF_UP))
            acc["display_exchange_rate"] = str(_dec(display_meta.get("rate") or Decimal("1")).quantize(_D4, ROUND_HALF_UP))
            acc["display_currency"] = display_meta.get("currency")
            acc["base_currency"] = display_meta.get("base_currency")
            acc["is_multi_currency_scope"] = display_meta.get("is_multi_currency_scope", False)
        
        # Pagination result structure
        if page is not None and page >= 1:
            return {
                "data": accounts,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size
            }
        
        return accounts
    except Exception as e:
        logger.error(f"Error fetching accounts: {str(e)}")
        raise HTTPException(**http_error(500, "account_tree_fetch_error", request))
    finally:
        db.close()

@router.post("/accounts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def create_account(
    request: Request,
    account: AccountCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء حساب جديد في شجرة الحسابات"""
    db = get_db_connection(current_user.company_id)
    try:
        # ACC-FIX-04 (P1): Validate account_type enum against DB CHECK constraint values.
        valid_types = {"asset", "liability", "equity", "revenue", "expense"}
        if account.account_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"نوع الحساب غير صالح. القيم المسموحة: {sorted(valid_types)}",
            )

        # ACC-FIX-04 (P1): Validate parent_id FK exists and has the same account_type
        # so the chart of accounts stays consistent (no Asset under Revenue).
        if account.parent_id is not None:
            parent = db.execute(
                text("SELECT id, account_type, is_header FROM accounts WHERE id = :pid"),
                {"pid": account.parent_id},
            ).fetchone()
            if not parent:
                raise HTTPException(**http_error(400, "parent_account_not_found", request))
            if parent.account_type != account.account_type:
                raise HTTPException(**http_error(400, "account_type_must_match_parent", request))

        # Check if account number already exists
        exists = db.execute(text("SELECT 1 FROM accounts WHERE account_number = :num"), {"num": account.account_number}).fetchone()
        if exists:
            raise HTTPException(**http_error(400, "account_number_exists", request))

        # Check if account code already exists
        if account.account_code:
            code_exists = db.execute(text("SELECT 1 FROM accounts WHERE account_code = :code"), {"code": account.account_code}).fetchone()
            if code_exists:
                raise HTTPException(**http_error(400, "account_code_exists", request))

        db.execute(text("""
            INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, currency, is_header, balance, is_active)
            VALUES (:num, :code, :name, :name_en, :type, :parent, :curr, :is_header, 0, true)
        """), {
            "num": account.account_number,
            "code": account.account_code,
            "name": account.name,
            "name_en": account.name_en,
            "type": account.account_type,
            "parent": account.parent_id,
            "curr": account.currency,
            "is_header": account.is_header
        })
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="accounting.account.create",
            resource_type="account",
            resource_id=account.account_number,
            details={"name": account.name, "type": account.account_type},
            request=request
        )

        return {"success": True, "message": i18n_message("account_created", request)}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating account: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        # Invalidate cache
        try:
            cache.delete(f"chart_of_accounts:{current_user.company_id}")
        except Exception:
            pass
        db.close()

@router.delete("/accounts/{account_id}", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def delete_account(
    request: Request,
    account_id: int,
    current_user: dict = Depends(get_current_user)
):
    """حذف حساب من شجرة الحسابات (بشرط عدم وجود حركات أو أبناء)"""
    with transactional(current_user.company_id) as db:
        try:
            _require_company_wide_branch_scope(current_user, request)

            # 1. Check if has children
            has_children = db.execute(text("SELECT 1 FROM accounts WHERE parent_id = :id"), {"id": account_id}).fetchone()
            if has_children:
                raise HTTPException(**http_error(400, "account_has_sub_accounts", request))
    
            # 2. Check if has transactions (journal lines)
            has_tx = db.execute(text("SELECT 1 FROM journal_lines WHERE account_id = :id"), {"id": account_id}).fetchone()
            if has_tx:
                raise HTTPException(**http_error(400, "account_has_journal_entries", request))
    
            # 2b. Check if linked to treasury accounts
            has_treasury = db.execute(text("SELECT 1 FROM treasury_accounts WHERE gl_account_id = :id"), {"id": account_id}).fetchone()
            if has_treasury:
                raise HTTPException(**http_error(400, "account_linked_to_treasury", request))
    
            # 2c. Check if used in budget items
            has_budget = db.execute(text("SELECT 1 FROM budget_items WHERE account_id = :id LIMIT 1"), {"id": account_id}).fetchone()
            if has_budget:
                raise HTTPException(**http_error(400, "account_used_in_budgets", request))
    
            # 2d. Check if used in company_settings as mapped account
            has_mapping = db.execute(text("SELECT 1 FROM company_settings WHERE setting_value = :id_str AND setting_key LIKE 'acc_map_%' LIMIT 1"), {"id_str": str(account_id)}).fetchone()
            if has_mapping:
                raise HTTPException(**http_error(400, "account_used_as_default", request))
    
            # 3. Check for balance
            balance_row = db.execute(text("SELECT balance FROM accounts WHERE id = :id"), {"id": account_id}).fetchone()
            if balance_row and _dec(balance_row[0]).copy_abs() > _D2:
                raise HTTPException(**http_error(400, "account_has_nonzero_balance", request))
    
            # Capture account info before delete
            acct = db.execute(text("SELECT account_code, name FROM accounts WHERE id = :id"), {"id": account_id}).fetchone()
            
            db.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})
            
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.account.delete",
                         resource_type="account", resource_id=str(account_id),
                         details={"account_code": acct[0] if acct else None, "name": acct[1] if acct else None},
                         request=request)
            
            # Invalidate cache
            try:
                cache.delete(f"chart_of_accounts:{current_user.company_id}")
            except Exception:
                pass
                
            return {"success": True, "message": i18n_message("account_deleted", request)}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting account: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.put("/accounts/{account_id}", dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def update_account(
    request: Request,
    account_id: int,
    account_data: AccountUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update account details"""
    with transactional(current_user.company_id) as db:
        try:
            # Check if account exists
            existing = db.execute(text("SELECT 1 FROM accounts WHERE id = :id"), {"id": account_id}).fetchone()
            if not existing:
                 raise HTTPException(**http_error(404, "account_not_found"))
    
            payload = account_data.dict(exclude_unset=True)
    
            # Check for duplicate account_code
            new_code = payload.get("account_code")
            if new_code:
                dup = db.execute(text("SELECT 1 FROM accounts WHERE account_code = :code AND id != :id"), {"code": new_code, "id": account_id}).fetchone()
                if dup:
                    raise HTTPException(status_code=400, detail=i18n_message("account_code_already_in_use", request))
                 
            db.execute(text("""
                UPDATE accounts 
                SET name = COALESCE(:name, name),
                    name_en = COALESCE(:name_en, name_en),
                    account_code = COALESCE(:code, account_code),
                    account_type = COALESCE(:account_type, account_type),
                    parent_id = :parent_id,
                    currency = COALESCE(:currency, currency),
                    is_header = COALESCE(:is_header, is_header),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "name": payload.get("name"),
                "name_en": payload.get("name_en"),
                "code": new_code,
                "account_type": payload.get("account_type"),
                "parent_id": payload.get("parent_id"),
                "currency": payload.get("currency"),
                "is_header": payload.get("is_header"),
                "is_active": payload.get("is_active"),
                "id": account_id
            })
            
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.account.update",
                         resource_type="account", resource_id=str(account_id),
                         details={"fields": list(payload.keys())},
                         request=request)
            
            # Invalidate cache
            try:
                cache.delete(f"chart_of_accounts:{current_user.company_id}")
            except Exception:
                pass
                
            return {"success": True, "message": i18n_message("account_updated", request)}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating account: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/opening-balances", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_opening_balances(
    request: Request,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """جلب الأرصدة الافتتاحية - آخر قيد أرصدة افتتاحية مع أرصدة جميع الحسابات"""
    with transactional(current_user.company_id) as db:
        # Find existing opening balance entry
        ob_query = """
            SELECT je.id, je.entry_number, je.entry_date, je.status, je.description
            FROM journal_entries je
            WHERE je.reference = 'OPENING-BALANCE'
        """
        ob_params = {}
        if branch_id:
            ob_query += " AND je.branch_id = :branch_id"
            ob_params["branch_id"] = branch_id
        ob_query += " ORDER BY je.entry_date DESC, je.id DESC LIMIT 1"
        ob_entry = db.execute(text(ob_query), ob_params).fetchone()

        # Get all accounts with their current balance
        accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts
            ORDER BY account_number
        """)).fetchall()

        ob_lines = []
        if ob_entry:
            ob_lines = db.execute(text("""
                SELECT account_id, debit, credit, description
                FROM journal_lines
                WHERE journal_entry_id = :eid
            """), {"eid": ob_entry.id}).fetchall()

        ob_map = {l.account_id: {"debit": _dec(l.debit or 0), "credit": _dec(l.credit or 0)} for l in ob_lines}

        result = []
        for a in accounts:
            am = dict(a._mapping)
            ob = ob_map.get(a.id, {"debit": 0, "credit": 0})
            am["opening_debit"] = ob["debit"]
            am["opening_credit"] = ob["credit"]
            result.append(am)

        return {
            "entry": dict(ob_entry._mapping) if ob_entry else None,
            "accounts": result,
        }
@router.post("/opening-balances", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def save_opening_balances(
    request: Request,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """حفظ الأرصدة الافتتاحية (ينشئ أو يحدث قيد الأرصدة الافتتاحية)"""
    with transactional(current_user.company_id) as db:
        try:
            lines = data.get("lines", [])
            entry_date = data.get("date", str(date.today()))
    
            # Fiscal-period lock: opening balances must land in an open period.
            check_fiscal_period_open(db, entry_date)
    
            # Filter to only lines with actual values
            valid_lines = [l for l in lines if _dec(l.get("debit", 0)) != 0 or _dec(l.get("credit", 0)) != 0]
            if not valid_lines:
                raise HTTPException(**http_error(400, "no_balances_to_save", request))
    
            total_debit = sum(_dec(l.get("debit", 0)) for l in valid_lines)
            total_credit = sum(_dec(l.get("credit", 0)) for l in valid_lines)
    
            # Find existing opening balance entry
            existing = db.execute(text("""
                SELECT id, status FROM journal_entries
                WHERE reference = 'OPENING-BALANCE'
                ORDER BY entry_date DESC, id DESC
                LIMIT 1
            """)).fetchone()
    
            if existing:
                # Audit F-NEW-009 / F-NEW-035: posted entries are immutable.
                # Reverse via gl_service so the audit trail is preserved
                # (a balanced reversing JE is created and balances neutralised
                # centrally). For drafts (no balance impact) a hard delete is
                # safe. We then create the new opening-balance entry below.
                if existing.status == 'posted':
                    gl_reverse_journal_entry(
                        db,
                        je_id=existing.id,
                        user_id=current_user.id,
                        company_id=current_user.company_id,
                        reversal_date=entry_date,
                        reason="opening_balance_replaced",
                        request=request,
                    )
                else:
                    # Draft: no posted balance impact, hard delete is safe.
                    db.execute(
                        text("DELETE FROM journal_lines WHERE journal_entry_id = :eid"),
                        {"eid": existing.id},
                    )
                    db.execute(
                        text(
                            "DELETE FROM journal_entries "
                            "WHERE id = :eid AND status = 'draft'"
                        ),
                        {"eid": existing.id},
                    )
    
            # Default behavior is strict: reject imbalanced opening balances.
            # Admin can explicitly allow suspense adjustment by passing allow_auto_balance=true.
            diff = (total_debit - total_credit).quantize(_D4, ROUND_HALF_UP)
            if diff.copy_abs() > _D4:
                allow_auto_balance = bool(data.get("allow_auto_balance", False))
                if not allow_auto_balance:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "الأرصدة الافتتاحية غير متوازنة. "
                            f"الفرق الحالي: {diff}. "
                            "صحّح الأرصدة أو أعد الطلب مع allow_auto_balance=true للموازنة الاستثنائية."
                        ),
                    )
    
                suspense = db.execute(text(
                    "SELECT id FROM accounts WHERE account_number = '3100' OR (account_type = 'equity' AND name LIKE '%افتتا%') LIMIT 1"
                )).fetchone()
                if not suspense:
                    suspense = db.execute(text(
                        "SELECT id FROM accounts WHERE account_type = 'equity' ORDER BY account_number LIMIT 1"
                    )).fetchone()
                if not suspense:
                    raise HTTPException(**http_error(400, "equity_account_not_found_for_offset", request))
    
                valid_lines.append({
                    "account_id": suspense.id,
                    "debit": max(-diff, Decimal("0")).quantize(_D4, ROUND_HALF_UP),
                    "credit": max(diff, Decimal("0")).quantize(_D4, ROUND_HALF_UP),
                    "description": "فرق الأرصدة الافتتاحية / Opening Balance Difference"
                })
    
            gl_lines = []
            for line in valid_lines:
                gl_lines.append({
                    "account_id": int(line["account_id"]),
                    "debit": _dec(line.get("debit", 0)),
                    "credit": _dec(line.get("credit", 0)),
                    "description": line.get("description", "رصيد افتتاحي"),
                })
    
            entry_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=entry_date,
                description="أرصدة افتتاحية / Opening Balances",
                lines=gl_lines,
                user_id=current_user.id,
                branch_id=data.get("branch_id") or getattr(current_user, "branch_id", None),
                reference="OPENING-BALANCE",
                source="opening_balances",
            )
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.opening_balances.save",
                         resource_type="opening_balances", resource_id=str(entry_id),
                         details={"lines_count": len(valid_lines)})
            return {"success": True, "entry_id": entry_id, "lines_count": len(valid_lines),
                    "message": i18n_message("opening_balances_saved_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== ACC-006: Automatic Closing Entries ====================
