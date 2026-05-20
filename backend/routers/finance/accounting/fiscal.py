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
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
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


def _require_company_wide_branch_scope(current_user: Any, request: Request) -> None:
    scope = resolve_branch_scope(current_user, None)
    if scope.get("branch_ids") is not None:
        raise HTTPException(**http_error(403, "access_denied", request))


router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/fiscal-years", dependencies=[Depends(require_permission("accounting.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_fiscal_years(request: Request, current_user: dict = Depends(get_current_user)):
    """قائمة السنوات المالية"""
    with transactional(current_user.company_id) as db:
        try:
            params: Dict[str, Any] = {}
            period_branch_filter = branch_scope_filter_from_scope(
                resolve_branch_scope(current_user, None), "fp.branch_id", params
            )
            rows = db.execute(text(f"""
                SELECT fy.*,
                       cu_closed.username AS closed_by_name,
                       cu_reopened.username AS reopened_by_name,
                       a.name AS retained_earnings_account_name,
                       a.account_number AS retained_earnings_account_number,
                       (SELECT COUNT(*) FROM fiscal_periods fp WHERE fp.fiscal_year = fy.year {period_branch_filter}) AS period_count,
                       (SELECT COUNT(*) FROM fiscal_periods fp WHERE fp.fiscal_year = fy.year AND fp.is_closed = TRUE {period_branch_filter}) AS closed_period_count
                FROM fiscal_years fy
                LEFT JOIN company_users cu_closed ON fy.closed_by = cu_closed.id
                LEFT JOIN company_users cu_reopened ON fy.reopened_by = cu_reopened.id
                LEFT JOIN accounts a ON fy.retained_earnings_account_id = a.id
                ORDER BY fy.year DESC
            """), params).fetchall()

            result = []
            for r in rows:
                result.append({
                    "id": r.id,
                    "year": r.year,
                    "start_date": str(r.start_date),
                    "end_date": str(r.end_date),
                    "status": r.status,
                    "retained_earnings_account_id": r.retained_earnings_account_id,
                    "retained_earnings_account_name": r.retained_earnings_account_name,
                    "retained_earnings_account_number": r.retained_earnings_account_number,
                    "closing_entry_id": r.closing_entry_id,
                    "closed_by": r.closed_by,
                    "closed_by_name": r.closed_by_name,
                    "closed_at": str(r.closed_at) if r.closed_at else None,
                    "reopened_by": r.reopened_by,
                    "reopened_by_name": r.reopened_by_name,
                    "reopened_at": str(r.reopened_at) if r.reopened_at else None,
                    "period_count": r.period_count,
                    "closed_period_count": r.closed_period_count,
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching fiscal years: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/fiscal-years", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_fiscal_year(
    request: Request,
    data: FiscalYearCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء سنة مالية جديدة"""
    with transactional(current_user.company_id) as db:
        try:
            _require_company_wide_branch_scope(current_user, request)

            # Check duplicate
            existing = db.execute(text("SELECT 1 FROM fiscal_years WHERE year = :y"), {"y": data.year}).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail=i18n_message("fiscal_year_already_exists", request))
    
            # Find retained earnings account if not specified
            re_account_id = data.retained_earnings_account_id
            if not re_account_id:
                re_acc = db.execute(text("""
                    SELECT id FROM accounts
                    WHERE account_type = 'equity'
                      AND (account_code = 'RET' OR account_number = '32'
                           OR LOWER(name_en) LIKE '%retained%earnings%')
                    LIMIT 1
                """)).fetchone()
                if re_acc:
                    re_account_id = re_acc.id
    
            result = db.execute(text("""
                INSERT INTO fiscal_years (year, start_date, end_date, retained_earnings_account_id)
                VALUES (:year, :start, :end, :re_acc)
                RETURNING id
            """), {
                "year": data.year,
                "start": data.start_date,
                "end": data.end_date,
                "re_acc": re_account_id
            })
            fy_id = result.scalar()
    
            # Auto-create 12 monthly fiscal periods if none exist for this year
            period_count = db.execute(text(
                "SELECT COUNT(*) FROM fiscal_periods WHERE fiscal_year = :y"
            ), {"y": data.year}).scalar()
    
            if period_count == 0:
                months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                             "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
                for m in range(1, 13):
                    import calendar
                    start_d = date(data.year, m, 1)
                    last_day = calendar.monthrange(data.year, m)[1]
                    end_d = date(data.year, m, last_day)
                    # Only create if within fiscal year range
                    if end_d >= data.start_date and start_d <= data.end_date:
                        db.execute(text("""
                            INSERT INTO fiscal_periods (name, start_date, end_date, fiscal_year, is_closed)
                            VALUES (:name, :start, :end, :year, false)
                        """), {
                            "name": f"{months_ar[m-1]} {data.year}",
                            "start": start_d,
                            "end": end_d,
                            "year": data.year
                        })
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.fiscal_year.create",
                         resource_type="fiscal_year", resource_id=str(fy_id),
                         details={"year": data.year})
    
            return {"success": True, "id": fy_id, "message": i18n_message("fiscal_year_created", request)}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating fiscal year: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.get("/fiscal-years/{year}/preview-closing", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def preview_year_end_closing(
    request: Request,
    year: int,
    current_user: dict = Depends(get_current_user)
):
    """معاينة قيد الإقفال قبل التنفيذ - عرض الإيرادات والمصاريف"""
    with transactional(current_user.company_id) as db:
        scope = resolve_branch_scope(current_user, None)
        revenue_params = {"start": None, "end": None}
        expense_params = {"start": None, "end": None}
        revenue_branch_filter = branch_scope_filter_from_scope(scope, "je.branch_id", revenue_params)
        expense_branch_filter = branch_scope_filter_from_scope(scope, "je.branch_id", expense_params)

        # Get fiscal year
        fy = db.execute(text("SELECT * FROM fiscal_years WHERE year = :y"), {"y": year}).fetchone()
        if not fy:
            raise HTTPException(status_code=404, detail=i18n_message("fiscal_year_not_found", request))
        if fy.status == 'closed':
            raise HTTPException(status_code=400, detail=i18n_message("fiscal_year_already_closed", request))
        revenue_params.update({"start": fy.start_date, "end": fy.end_date})
        expense_params.update({"start": fy.start_date, "end": fy.end_date})

        # Get all revenue accounts with their balances for this year
        revenue_accounts = db.execute(text(f"""
            SELECT a.id, a.account_number, a.name, a.name_en,
                   COALESCE(SUM(jl.credit - jl.debit), 0) AS balance
            FROM accounts a
            JOIN journal_lines jl ON jl.account_id = a.id
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE a.account_type = 'revenue'
            AND je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted'
            {revenue_branch_filter}
            GROUP BY a.id, a.account_number, a.name, a.name_en
            HAVING COALESCE(SUM(jl.credit - jl.debit), 0) != 0
            ORDER BY a.account_number
        """), revenue_params).fetchall()

        # Get all expense accounts with their balances for this year
        expense_accounts = db.execute(text(f"""
            SELECT a.id, a.account_number, a.name, a.name_en,
                   COALESCE(SUM(jl.debit - jl.credit), 0) AS balance
            FROM accounts a
            JOIN journal_lines jl ON jl.account_id = a.id
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE a.account_type = 'expense'
            AND je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted'
            {expense_branch_filter}
            GROUP BY a.id, a.account_number, a.name, a.name_en
            HAVING COALESCE(SUM(jl.debit - jl.credit), 0) != 0
            ORDER BY a.account_number
        """), expense_params).fetchall()

        total_revenue = sum(_dec(r.balance) for r in revenue_accounts)
        total_expenses = sum(_dec(r.balance) for r in expense_accounts)
        net_income = (total_revenue - total_expenses).quantize(_D4, ROUND_HALF_UP)

        # Get retained earnings account
        re_acc = None
        if fy.retained_earnings_account_id:
            re_acc = db.execute(text(
                "SELECT id, account_number, name, name_en FROM accounts WHERE id = :id"
            ), {"id": fy.retained_earnings_account_id}).fetchone()

        return {
            "year": year,
            "start_date": str(fy.start_date),
            "end_date": str(fy.end_date),
            "revenue_accounts": [
                {"id": r.id, "account_number": r.account_number, "name": r.name,
                 "name_en": r.name_en, "balance": str(_dec(r.balance).quantize(_D4, ROUND_HALF_UP))}
                for r in revenue_accounts
            ],
            "expense_accounts": [
                {"id": r.id, "account_number": r.account_number, "name": r.name,
                 "name_en": r.name_en, "balance": str(_dec(r.balance).quantize(_D4, ROUND_HALF_UP))}
                for r in expense_accounts
            ],
            "total_revenue": str(total_revenue.quantize(_D4, ROUND_HALF_UP)),
            "total_expenses": str(total_expenses.quantize(_D4, ROUND_HALF_UP)),
            "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP)),
            "retained_earnings_account": {
                "id": re_acc.id, "account_number": re_acc.account_number,
                "name": re_acc.name, "name_en": re_acc.name_en
            } if re_acc else None,
            "result_type": "profit" if net_income >= 0 else "loss"
        }
@router.post("/fiscal-years/{year}/close", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def close_fiscal_year(
    request: Request,
    year: int,
    data: FiscalYearClose = FiscalYearClose(),
    current_user: dict = Depends(get_current_user)
):
    """إقفال السنة المالية - ترحيل الأرباح/الخسائر إلى حقوق الملكية"""
    with transactional(current_user.company_id) as db:
        try:
            _require_company_wide_branch_scope(current_user, request)

            # 1. Validate fiscal year exists and is open
            fy = db.execute(text("SELECT * FROM fiscal_years WHERE year = :y FOR UPDATE"), {"y": year}).fetchone()
            if not fy:
                raise HTTPException(status_code=404, detail=i18n_message("fiscal_year_not_found", request))
            if fy.status == 'closed':
                raise HTTPException(status_code=400, detail=i18n_message("fiscal_year_already_closed", request))
    
            # 2. Determine retained earnings account
            re_account_id = data.retained_earnings_account_id or fy.retained_earnings_account_id
            if not re_account_id:
                re_acc = db.execute(text("""
                    SELECT id FROM accounts
                    WHERE account_type = 'equity'
                      AND (account_code = 'RET' OR account_number = '32'
                           OR LOWER(name_en) LIKE '%retained%earnings%')
                    LIMIT 1
                """)).fetchone()
                if re_acc:
                    re_account_id = re_acc.id
                else:
                    raise HTTPException(**http_error(400, "retained_earnings_not_found_manual", request))
    
            # 3. Calculate total revenue and expenses for the year
            revenue_data = db.execute(text("""
                SELECT a.id, COALESCE(SUM(jl.credit - jl.debit), 0) AS balance
                FROM accounts a
                JOIN journal_lines jl ON jl.account_id = a.id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                WHERE a.account_type = 'revenue'
                  AND je.entry_date BETWEEN :start AND :end
                  AND je.status = 'posted'
                GROUP BY a.id
                HAVING COALESCE(SUM(jl.credit - jl.debit), 0) != 0
            """), {"start": fy.start_date, "end": fy.end_date}).fetchall()
    
            expense_data = db.execute(text("""
                SELECT a.id, COALESCE(SUM(jl.debit - jl.credit), 0) AS balance
                FROM accounts a
                JOIN journal_lines jl ON jl.account_id = a.id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                WHERE a.account_type = 'expense'
                  AND je.entry_date BETWEEN :start AND :end
                  AND je.status = 'posted'
                GROUP BY a.id
                HAVING COALESCE(SUM(jl.debit - jl.credit), 0) != 0
            """), {"start": fy.start_date, "end": fy.end_date}).fetchall()
    
            total_revenue = sum(_dec(r.balance) for r in revenue_data)
            total_expenses = sum(_dec(r.balance) for r in expense_data)
            net_income = (total_revenue - total_expenses).quantize(_D4, ROUND_HALF_UP)
    
            if not revenue_data and not expense_data:
                raise HTTPException(**http_error(400, "no_revenue_expense_movements_year", request))
    
            # 4. Build and create the closing journal entry via centralized GL service
            closing_lines = []
    
            # A) Close revenue accounts (debit revenue to zero it out)
            for rev in revenue_data:
                balance = _dec(rev.balance).quantize(_D4, ROUND_HALF_UP)
                closing_lines.append({
                    "account_id": rev.id,
                    "debit": abs(balance),
                    "credit": 0,
                    "description": f"إقفال حساب إيرادات - {year}",
                })
    
            # B) Close expense accounts (credit expense to zero it out)
            for exp in expense_data:
                balance = _dec(exp.balance).quantize(_D4, ROUND_HALF_UP)
                closing_lines.append({
                    "account_id": exp.id,
                    "debit": 0,
                    "credit": abs(balance),
                    "description": f"إقفال حساب مصاريف - {year}",
                })
    
            # C) Transfer net income to retained earnings
            if net_income >= 0:
                closing_lines.append({
                    "account_id": re_account_id,
                    "debit": 0,
                    "credit": abs(net_income),
                    "description": f"ترحيل صافي ربح {year} إلى الأرباح المبقاة",
                })
            else:
                closing_lines.append({
                    "account_id": re_account_id,
                    "debit": abs(net_income),
                    "credit": 0,
                    "description": f"ترحيل صافي خسارة {year} إلى الأرباح المبقاة",
                })
    
            entry_id, entry_num = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(fy.end_date),
                description=f"قيد إقفال السنة المالية {year} - ترحيل صافي {'الربح' if net_income >= 0 else 'الخسارة'} إلى الأرباح المبقاة",
                lines=closing_lines,
                user_id=current_user.id,
                reference=f"Year-End Closing {year}",
                source="fiscal_year_closing",
                source_id=fy.id,
            )
    
            # 6. Close fiscal periods for this year (if requested)
            closed_periods = 0
            if data.close_periods:
                closed_periods = db.execute(text("""
                    UPDATE fiscal_periods
                    SET is_closed = TRUE, closed_by = :user, closed_at = NOW()
                    WHERE fiscal_year = :year AND is_closed = FALSE
                """), {"year": year, "user": current_user.id}).rowcount
                db.execute(text("""
                    UPDATE fiscal_period_locks fpl
                    SET is_locked = TRUE,
                        locked_at = COALESCE(fpl.locked_at, NOW()),
                        locked_by = COALESCE(fpl.locked_by, :user),
                        reason = COALESCE(fpl.reason, :reason)
                    FROM fiscal_periods fp
                    WHERE fp.fiscal_year = :year
                      AND fpl.period_start = fp.start_date
                      AND fpl.period_end = fp.end_date
                """), {
                    "year": year,
                    "user": current_user.id,
                    "reason": f"Fiscal year close {year}",
                })
                db.execute(text("""
                    INSERT INTO fiscal_period_locks
                        (period_name, period_start, period_end, is_locked,
                         locked_at, locked_by, reason)
                    SELECT fp.name, fp.start_date, fp.end_date, TRUE,
                           NOW(), :user, :reason
                    FROM fiscal_periods fp
                    WHERE fp.fiscal_year = :year
                      AND NOT EXISTS (
                          SELECT 1 FROM fiscal_period_locks fpl
                          WHERE fpl.period_start = fp.start_date
                            AND fpl.period_end = fp.end_date
                      )
                """), {
                    "year": year,
                    "user": current_user.id,
                    "reason": f"Fiscal year close {year}",
                })
    
            # 7. Mark fiscal year as closed
            db.execute(text("""
                UPDATE fiscal_years
                SET status = 'closed',
                    closing_entry_id = :entry_id,
                    retained_earnings_account_id = :re_acc,
                    closed_by = :user,
                    closed_at = NOW()
                WHERE year = :year
            """), {
                "entry_id": entry_id,
                "re_acc": re_account_id,
                "user": current_user.id,
                "year": year
            })
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.fiscal_year.close",
                         resource_type="fiscal_year", resource_id=str(fy.id),
                         details={"year": year, "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP))})
    
            return {
                "success": True,
                "message": i18n_message("fiscal_year_closed", request),
                "closing_entry_id": entry_id,
                "closing_entry_number": entry_num,
                "total_revenue": str(total_revenue.quantize(_D4, ROUND_HALF_UP)),
                "total_expenses": str(total_expenses.quantize(_D4, ROUND_HALF_UP)),
                "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP)),
                "result_type": "profit" if net_income >= 0 else "loss",
                "closed_periods": closed_periods
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error closing fiscal year {year}: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/fiscal-years/{year}/reopen", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def reopen_fiscal_year(
    request: Request,
    year: int,
    data: FiscalYearReopen = FiscalYearReopen(),
    current_user: dict = Depends(get_current_user)
):
    """إعادة فتح سنة مالية مقفلة - عكس قيد الإقفال"""
    with transactional(current_user.company_id) as db:
        try:
            # 1. Validate
            fy = db.execute(text("SELECT * FROM fiscal_years WHERE year = :y FOR UPDATE"), {"y": year}).fetchone()
            if not fy:
                raise HTTPException(status_code=404, detail=i18n_message("fiscal_year_not_found", request))
            if fy.status != 'closed':
                raise HTTPException(status_code=400, detail=i18n_message("fiscal_year_not_locked", request))
    
            # 2. Reverse the closing journal entry
            if fy.closing_entry_id:
                closing_entry = db.execute(text("""
                    SELECT entry_number, branch_id, currency, exchange_rate
                    FROM journal_entries
                    WHERE id = :id
                """), {"id": fy.closing_entry_id}).fetchone()
    
                closing_lines = db.execute(text("""
                    SELECT account_id, debit, credit FROM journal_lines
                    WHERE journal_entry_id = :id
                """), {"id": fy.closing_entry_id}).fetchall()
    
                rev_lines = []
                for line in closing_lines:
                    rev_lines.append({
                        "account_id": line.account_id,
                        "debit": _dec(line.credit or 0),
                        "credit": _dec(line.debit or 0),
                        "description": f"عكس إقفال {year}",
                    })
    
                reversal_date = str(date.today())
                check_fiscal_period_open(db, reversal_date)
    
                rev_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=reversal_date,
                    description=f"عكس قيد إقفال السنة المالية {year}" + (f" - {data.reason}" if data.reason else ""),
                    lines=rev_lines,
                    user_id=current_user.id,
                    branch_id=closing_entry.branch_id if closing_entry else None,
                    reference=f"Reversal of Year-End Closing {year}",
                    currency=closing_entry.currency if closing_entry else None,
                    exchange_rate=_dec(closing_entry.exchange_rate or 1) if closing_entry else Decimal("1"),
                    source="fiscal_year_reopen",
                    source_id=fy.id,
                )
    
                # Mark original closing entry as voided
                db.execute(text("""
                    UPDATE journal_entries SET status = 'void' WHERE id = :id
                """), {"id": fy.closing_entry_id})
    
            # 3. Reopen fiscal periods
            db.execute(text("""
                UPDATE fiscal_periods
                SET is_closed = FALSE, closed_by = NULL, closed_at = NULL
                WHERE fiscal_year = :year
            """), {"year": year})
            db.execute(text("""
                UPDATE fiscal_period_locks fpl
                SET is_locked = FALSE,
                    unlocked_at = NOW(),
                    unlocked_by = :user
                FROM fiscal_periods fp
                WHERE fp.fiscal_year = :year
                  AND fpl.period_start = fp.start_date
                  AND fpl.period_end = fp.end_date
                  AND fpl.is_locked = TRUE
            """), {"year": year, "user": current_user.id})
    
            # 4. Update fiscal year status
            db.execute(text("""
                UPDATE fiscal_years
                SET status = 'open',
                    closing_entry_id = NULL,
                    reopened_by = :user,
                    reopened_at = NOW()
                WHERE year = :year
            """), {"user": current_user.id, "year": year})
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.fiscal_year.reopen",
                         resource_type="fiscal_year", resource_id=str(fy.id),
                         details={"year": year, "reason": data.reason})
    
            return {
                "success": True,
                "message": i18n_message("fiscal_year_reopened", request),
                "reversal_entry_id": rev_id if fy.closing_entry_id else None,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error reopening fiscal year {year}: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.get("/fiscal-years/{year}/periods", dependencies=[Depends(require_permission("accounting.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_fiscal_periods(
    request: Request,
    year: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب الفترات المحاسبية لسنة مالية"""
    with transactional(current_user.company_id) as db:
        params: Dict[str, Any] = {"year": year}
        period_branch_filter = branch_scope_filter_from_scope(
            resolve_branch_scope(current_user, None), "fp.branch_id", params
        )
        entry_params: Dict[str, Any] = {}
        entry_branch_filter = branch_scope_filter_from_scope(
            resolve_branch_scope(current_user, None),
            "je.branch_id",
            entry_params,
            branch_param="entry_branch_id",
            branches_param="entry_allowed_branch_ids",
        )
        for key, value in entry_params.items():
            params[key] = value
        rows = db.execute(text(f"""
            SELECT fp.*,
                   cu.username AS closed_by_name,
                   (SELECT COUNT(*) FROM journal_entries je
                    WHERE je.entry_date BETWEEN fp.start_date AND fp.end_date
                    AND je.status = 'posted' {entry_branch_filter}) AS entry_count
            FROM fiscal_periods fp
            LEFT JOIN company_users cu ON fp.closed_by = cu.id
            WHERE fp.fiscal_year = :year {period_branch_filter}
            ORDER BY fp.start_date
        """), params).fetchall()

        return [{
            "id": r.id,
            "name": r.name,
            "start_date": str(r.start_date),
            "end_date": str(r.end_date),
            "is_closed": r.is_closed,
            "closed_by": r.closed_by,
            "closed_by_name": r.closed_by_name,
            "closed_at": str(r.closed_at) if r.closed_at else None,
            "entry_count": r.entry_count,
        } for r in rows]
@router.post("/fiscal-periods/{period_id}/toggle-close", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def toggle_fiscal_period(
    request: Request,
    period_id: int,
    current_user: dict = Depends(get_current_user)
):
    """فتح/إغلاق فترة محاسبية"""
    with transactional(current_user.company_id) as db:
        try:
            _require_company_wide_branch_scope(current_user, request)

            period = db.execute(text("SELECT * FROM fiscal_periods WHERE id = :id"), {"id": period_id}).fetchone()
            if not period:
                raise HTTPException(**http_error(404, "accounting_period_not_found", request))
    
            # Check if the parent fiscal year is closed
            if period.fiscal_year:
                fy = db.execute(text(
                    "SELECT status FROM fiscal_years WHERE year = :y"
                ), {"y": period.fiscal_year}).fetchone()
                if fy and fy.status == 'closed' and period.is_closed:
                    raise HTTPException(**http_error(400, "cannot_open_period_closed_year", request))
    
            new_status = not period.is_closed
            db.execute(text("""
                UPDATE fiscal_periods
                SET is_closed = :closed,
                    closed_by = CASE WHEN :closed THEN :user ELSE NULL END,
                    closed_at = CASE WHEN :closed THEN NOW() ELSE NULL END
                WHERE id = :id
            """), {"closed": new_status, "user": current_user.id, "id": period_id})
    
            # Sync fiscal_period_locks table
            if new_status:
                # Closing: ensure a lock row exists
                db.execute(text("""
                    INSERT INTO fiscal_period_locks (period_name, period_start, period_end, is_locked, locked_at, locked_by, reason)
                    VALUES (:name, :start, :end, TRUE, NOW(), :user, 'Manual close')
                    ON CONFLICT (period_start, period_end) DO UPDATE SET
                        is_locked = TRUE, locked_at = NOW(), locked_by = :user
                """), {"name": period.name, "start": period.start_date, "end": period.end_date, "user": current_user.id})
            else:
                # Opening: unlock the matching row
                db.execute(text("""
                    UPDATE fiscal_period_locks
                    SET is_locked = FALSE, unlocked_at = NOW(), unlocked_by = :user
                    WHERE period_start = :start AND period_end = :end
                """), {"start": period.start_date, "end": period.end_date, "user": current_user.id})
    
            action = "إغلاق" if new_status else "فتح"
    
            # Audit log for fiscal period lock/unlock (FR-024)
            log_activity(
                db,
                user_id=current_user.id,
                username=current_user.username,
                action=f"fiscal_period.{'lock' if new_status else 'unlock'}",
                resource_type="fiscal_period",
                resource_id=str(period_id),
                details={"period_name": period.name, "new_status": "locked" if new_status else "unlocked"},
            )
    
            return {"success": True, "message": i18n_message("fiscal_period_action", request), "is_closed": new_status}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== ACC-003: Recurring Journal Templates ====================

@router.get("/closing-entries/preview", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def preview_closing_entries(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """معاينة قيود الإقفال التلقائي للإيرادات والمصاريف"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        if not start_date:
            start_date = date.today().replace(month=1, day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", params)

        revenues = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT a.id, a.account_number, a.name, a.name_en,
                   COALESCE(SUM(jl.credit - jl.debit), 0) as balance
            FROM accounts a
            JOIN journal_lines jl ON a.id = jl.account_id
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE a.account_type = 'revenue'
            AND je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted' {branch_filter}
            GROUP BY a.id, a.account_number, a.name, a.name_en
            HAVING COALESCE(SUM(jl.credit - jl.debit), 0) != 0
            ORDER BY a.account_number
        """), params).fetchall()

        expenses = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT a.id, a.account_number, a.name, a.name_en,
                   COALESCE(SUM(jl.debit - jl.credit), 0) as balance
            FROM accounts a
            JOIN journal_lines jl ON a.id = jl.account_id
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE a.account_type = 'expense'
            AND je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted' {branch_filter}
            GROUP BY a.id, a.account_number, a.name, a.name_en
            HAVING COALESCE(SUM(jl.debit - jl.credit), 0) != 0
            ORDER BY a.account_number
        """), params).fetchall()

        income_summary = db.execute(text(
            "SELECT id, account_number, name FROM accounts WHERE account_number = '3200' OR name LIKE '%ملخص الدخل%' LIMIT 1"
        )).fetchone()
        retained_earnings = db.execute(text(
            "SELECT id, account_number, name FROM accounts WHERE account_number IN ('RET', '3100', '32') OR name LIKE '%أرباح مبقاة%' OR name LIKE '%Retained%' ORDER BY account_number LIMIT 1"
        )).fetchone()

        total_revenue = sum((_dec(r.balance) for r in revenues), Decimal('0'))
        total_expense = sum((_dec(r.balance) for r in expenses), Decimal('0'))
        net_income = (total_revenue - total_expense).quantize(_D4, ROUND_HALF_UP)

        return {
            "period": {"start": str(start_date), "end": str(end_date)},
            "revenues": [dict(r._mapping) for r in revenues],
            "expenses": [dict(r._mapping) for r in expenses],
            "total_revenue": str(total_revenue.quantize(_D4, ROUND_HALF_UP)),
            "total_expense": str(total_expense.quantize(_D4, ROUND_HALF_UP)),
            "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP)),
            "income_summary_account": dict(income_summary._mapping) if income_summary else None,
            "retained_earnings_account": dict(retained_earnings._mapping) if retained_earnings else None,
        }
@router.post("/closing-entries/generate", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def generate_closing_entries(
    request: Request,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """توليد قيود الإقفال التلقائي: إقفال الإيرادات والمصاريف → ملخص الدخل → أرباح مبقاة"""
    with transactional(current_user.company_id) as db:
        try:
            start_date_str = data.get("start_date", str(date.today().replace(month=1, day=1)))
            end_date_str = data.get("end_date", str(date.today()))
            retained_earnings_id = data.get("retained_earnings_account_id")
            income_summary_id = data.get("income_summary_account_id")
            use_income_summary = data.get("use_income_summary", False) and income_summary_id
            entry_date_str = data.get("entry_date", end_date_str)
    
            branch_id = validate_branch_access(current_user, data.get("branch_id"))
            params = {"start": start_date_str, "end": end_date_str}
            branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
            if branch_id:
                params["branch_id"] = branch_id
    
            if not retained_earnings_id:
                ret = db.execute(text(
                    "SELECT id FROM accounts WHERE account_number IN ('RET', '3100', '32') OR name LIKE '%أرباح مبقاة%' OR name LIKE '%Retained%' ORDER BY account_number LIMIT 1"
                )).fetchone()
                if not ret:
                    raise HTTPException(**http_error(400, "retained_earnings_not_found", request))
                retained_earnings_id = ret.id
    
            revenues = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT a.id, a.account_number, a.name,
                       COALESCE(SUM(jl.credit - jl.debit), 0) as balance
                FROM accounts a
                JOIN journal_lines jl ON a.id = jl.account_id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type = 'revenue'
                GROUP BY a.id, a.account_number, a.name
                HAVING COALESCE(SUM(jl.credit - jl.debit), 0) != 0
            """), params).fetchall()
    
            expenses = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT a.id, a.account_number, a.name,
                       COALESCE(SUM(jl.debit - jl.credit), 0) as balance
                FROM accounts a
                JOIN journal_lines jl ON a.id = jl.account_id
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type = 'expense'
                GROUP BY a.id, a.account_number, a.name
                HAVING COALESCE(SUM(jl.debit - jl.credit), 0) != 0
            """), params).fetchall()
    
            total_revenue = sum(_dec(r.balance) for r in revenues)
            total_expense = sum(_dec(r.balance) for r in expenses)
            net_income = (total_revenue - total_expense).quantize(_D4, ROUND_HALF_UP)
    
            created_entries = []
            target_account_id = income_summary_id if use_income_summary else retained_earnings_id
    
            # Entry 1: Close Revenue accounts
            if revenues:
                lines1 = []
    
                for rev in revenues:
                    bal = _dec(rev.balance).quantize(_D4, ROUND_HALF_UP)
                    lines1.append({
                        "account_id": rev.id,
                        "debit": bal,
                        "credit": 0,
                        "description": f"إقفال {rev.name}",
                    })
    
                lines1.append({
                    "account_id": target_account_id,
                    "debit": 0,
                    "credit": total_revenue,
                    "description": "إجمالي الإيرادات المقفلة",
                })
    
                eid1, num1 = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=entry_date_str,
                    description=f"إقفال حسابات الإيرادات - {start_date_str} إلى {end_date_str}",
                    lines=lines1,
                    user_id=current_user.id,
                    branch_id=branch_id or getattr(current_user, "branch_id", None),
                    reference="CLOSING-REVENUE",
                    source="closing_entries_revenue",
                )
    
                created_entries.append({"id": eid1, "type": "close_revenue", "number": num1})
    
            # Entry 2: Close Expense accounts
            if expenses:
                lines2 = []
    
                for exp in expenses:
                    bal = _dec(exp.balance).quantize(_D4, ROUND_HALF_UP)
                    lines2.append({
                        "account_id": exp.id,
                        "debit": 0,
                        "credit": bal,
                        "description": f"إقفال {exp.name}",
                    })
    
                lines2.append({
                    "account_id": target_account_id,
                    "debit": total_expense,
                    "credit": 0,
                    "description": "إجمالي المصاريف المقفلة",
                })
    
                eid2, num2 = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=entry_date_str,
                    description=f"إقفال حسابات المصاريف - {start_date_str} إلى {end_date_str}",
                    lines=lines2,
                    user_id=current_user.id,
                    branch_id=branch_id or getattr(current_user, "branch_id", None),
                    reference="CLOSING-EXPENSE",
                    source="closing_entries_expense",
                )
    
                created_entries.append({"id": eid2, "type": "close_expense", "number": num2})
    
            # Entry 3: Transfer Income Summary → Retained Earnings
            if use_income_summary and net_income != 0:
                lines3 = []
    
                if net_income > 0:
                    # Profit: Debit Income Summary, Credit Retained Earnings
                    lines3.append({
                        "account_id": income_summary_id,
                        "debit": net_income,
                        "credit": 0,
                        "description": "إقفال ملخص الدخل",
                    })
                    lines3.append({
                        "account_id": retained_earnings_id,
                        "debit": 0,
                        "credit": net_income,
                        "description": "صافي أرباح الفترة",
                    })
                else:
                    loss = abs(net_income)
                    # Loss: Credit Income Summary, Debit Retained Earnings
                    lines3.append({
                        "account_id": income_summary_id,
                        "debit": 0,
                        "credit": loss,
                        "description": "إقفال ملخص الدخل",
                    })
                    lines3.append({
                        "account_id": retained_earnings_id,
                        "debit": loss,
                        "credit": 0,
                        "description": "صافي خسائر الفترة",
                    })
    
                eid3, num3 = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=entry_date_str,
                    description=f"ترحيل ملخص الدخل إلى الأرباح المبقاة - صافي: {net_income}",
                    lines=lines3,
                    user_id=current_user.id,
                    branch_id=branch_id or getattr(current_user, "branch_id", None),
                    reference="CLOSING-TRANSFER",
                    source="closing_entries_transfer",
                )
    
                created_entries.append({"id": eid3, "type": "transfer_to_retained", "number": num3})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.closing_entries.generate",
                         resource_type="closing_entries", resource_id=str(len(created_entries)),
                         details={"entries_count": len(created_entries), "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP))})
    
            return {
                "success": True,
                "entries": created_entries,
                "total_revenue": str(total_revenue.quantize(_D4, ROUND_HALF_UP)),
                "total_expense": str(total_expense.quantize(_D4, ROUND_HALF_UP)),
                "net_income": str(net_income.quantize(_D4, ROUND_HALF_UP)),
                "message": i18n_message("closing_entries_generated", request),
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ═══════════════════════════════════════════════════════════
# GL-004: Bad Debt Provision (مخصص ديون معدومة)
# ═══════════════════════════════════════════════════════════
