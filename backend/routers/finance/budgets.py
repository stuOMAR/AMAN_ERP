from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import text
from schemas import UserResponse
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access, require_module
from utils.audit import log_activity
from utils.limiter import limiter
from utils.fiscal_lock import check_fiscal_period_open
from schemas.budgets import BudgetItemCreate, BudgetCreate, BudgetResponse, BudgetReportItem
import logging

router = APIRouter(prefix="/accounting/budgets", tags=["Budgets"], dependencies=[Depends(require_module("budgets"))])
logger = logging.getLogger(__name__)
_D2 = Decimal("0.01")


def _q_money(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(_D2, rounding=ROUND_HALF_UP)


def _money_str(value) -> str:
    return format(_q_money(value), "f")


def _q_pct(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(_D2, rounding=ROUND_HALF_UP)


def _pct_str(value) -> str:
    return format(_q_pct(value), "f")


def _count_budget_months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _get_budget_for_branch_scope(
    conn,
    current_user: UserResponse,
    budget_id: int,
    request: Request,
    columns: str = "id, status, branch_id",
    for_update: bool = False,
):
    params = {"id": budget_id}
    branch_filter = branch_scope_filter(current_user, None, "branch_id", params)
    lock_clause = " FOR UPDATE" if for_update else ""
    budget = conn.execute(text(
        f"SELECT {columns} FROM budgets WHERE id = :id {branch_filter}{lock_clause}"  # noqa
    ), params).fetchone()
    if not budget:
        raise HTTPException(**http_error(404, "budget_not_found", request))
    return budget


# --- Endpoints ---

@router.post("/", response_model=BudgetResponse, dependencies=[Depends(require_permission("accounting.budgets.manage"))])
@limiter.limit("100/minute")
def create_budget(budget: BudgetCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Budget."""
    with transactional(current_user.company_id) as conn:
        try:
            # Check if name exists
            exists = conn.execute(text("SELECT 1 FROM budgets WHERE name = :name"), {"name": budget.name}).fetchone()
            if exists:
                raise HTTPException(**http_error(400, "budget_name_already_exists", request))
                
            result = conn.execute(text("""
                INSERT INTO budgets (name, budget_name, start_date, end_date, description, status, created_by, branch_id, cost_center_id)
                VALUES (:name, :name, :start, :end, :desc, 'draft', :uid, :branch_id, :cost_center_id)
                RETURNING id, created_at, status
            """), {
                "name": budget.name,
                "start": budget.start_date,
                "end": budget.end_date,
                "desc": budget.description,
                "uid": current_user.id,
                "branch_id": budget.branch_id,
                "cost_center_id": budget.cost_center_id
            }).fetchone()
            
            
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.create", resource_type="budget",
                         resource_id=str(result.id), details={"name": budget.name},
                         request=request)
            
            return {
                "id": result.id,
                "name": budget.name,
                "start_date": budget.start_date,
                "end_date": budget.end_date,
                "description": budget.description,
                "status": result.status,
                "created_at": str(result.created_at),
                "branch_id": budget.branch_id,
                "cost_center_id": budget.cost_center_id
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating budget: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/", response_model=List[BudgetResponse], dependencies=[Depends(require_permission("accounting.budgets.view"))])
@limiter.limit("200/minute")
def list_budgets(request: Request, branch_id: Optional[int] = None, cost_center_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user)):
    """List Budgets."""
    with transactional(current_user.company_id) as conn:
        params = {}
        branch_filter = branch_scope_filter(current_user, branch_id, "b.branch_id", params)
        cc_filter = ""
        if cost_center_id:
            cc_filter = "AND b.cost_center_id = :cc_id"
            params["cc_id"] = cost_center_id
        results = conn.execute(text(f"SELECT b.* FROM budgets b WHERE 1=1 {branch_filter} {cc_filter} ORDER BY b.created_at DESC"), params).fetchall()
        return [
            {
                "id": row.id,
                "name": row.name,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "description": row.description,
                "status": row.status,
                "created_at": str(row.created_at),
                "branch_id": row.branch_id,
                "cost_center_id": row.cost_center_id
            }
            for row in results
        ]

@router.delete("/{budget_id}", dependencies=[Depends(require_permission("accounting.budgets.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def delete_budget(budget_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete Budget."""
    with transactional(current_user.company_id) as conn:
        try:
            # Verify budget exists
            budget = _get_budget_for_branch_scope(conn, current_user, budget_id, request)
            if budget.status == 'active':
                raise HTTPException(**http_error(400, "cannot_delete_active_budget", request))
                
            conn.execute(text("DELETE FROM budgets WHERE id = :id"), {"id": budget_id})
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.delete", resource_type="budget",
                         resource_id=str(budget_id), details={},
                         request=request)
            return {"message": i18n_message("budget_deleted", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.post("/{budget_id}/items", dependencies=[Depends(require_permission("accounting.budgets.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def set_budget_items(
    budget_id: int, 
    items: List[BudgetItemCreate], 
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """Set Budget Items."""
    with transactional(current_user.company_id) as conn:
        try:
            # Verify budget exists and derive any monthly inputs on the backend.
            budget = _get_budget_for_branch_scope(
                conn,
                current_user,
                budget_id,
                request,
                "id, branch_id, start_date, end_date",
            )
            budget_months = Decimal(_count_budget_months(budget.start_date, budget.end_date))
                
            # Insert or Update items
            for item in items:
                planned_amount = item.planned_amount
                if planned_amount is None and item.monthly_amount is not None:
                    planned_amount = _q_money(item.monthly_amount * budget_months)
                planned_amount = _q_money(planned_amount)

                # Check if exists
                exists = conn.execute(text("SELECT id FROM budget_items WHERE budget_id=:bid AND account_id=:aid"), 
                                      {"bid": budget_id, "aid": item.account_id}).fetchone()
                
                if exists:
                    conn.execute(text("""
                        UPDATE budget_items SET planned_amount = :amount, notes = :notes
                        WHERE id = :id
                    """), {"amount": planned_amount, "notes": item.notes, "id": exists.id})
                else:
                    conn.execute(text("""
                        INSERT INTO budget_items (budget_id, account_id, planned_amount, notes)
                        VALUES (:bid, :aid, :amount, :notes)
                    """), {
                        "bid": budget_id, 
                        "aid": item.account_id, 
                        "amount": planned_amount,
                        "notes": item.notes
                    })
            
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.items.update", resource_type="budget",
                         resource_id=str(budget_id), details={"items_count": len(items)},
                         request=request)
            return {"message": i18n_message("budget_items_updated", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/{budget_id}/report", response_model=List[BudgetReportItem], dependencies=[Depends(require_permission("accounting.budgets.view"))])
@limiter.limit("200/minute")
def get_budget_report(
    request: Request,
    budget_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """Get Budget Report."""
    with transactional(current_user.company_id) as conn:
        try:
            budget = conn.execute(text("SELECT start_date, end_date FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
            if not budget:
                 raise HTTPException(**http_error(404, "budget_not_found", request))
                 
            # Determine actual report range
            report_start = from_date if from_date else budget.start_date
            report_end = to_date if to_date else budget.end_date
            
            # Calculate scaling factor (Month-based)
            # We count any month touched by the range as 1 month.
            budget_months = Decimal(_count_budget_months(budget.start_date, budget.end_date))
            report_months = Decimal(_count_budget_months(report_start, report_end))
            
            scaling_factor = Decimal("0")
            if budget_months > 0:
                # Factor = (Months in report) / (Total months in budget)
                scaling_factor = report_months / budget_months
            
            params = {
                "bid": budget_id, 
                "start": report_start, 
                "end": report_end,
                "factor": scaling_factor
            }
            branch_filter = branch_scope_filter(current_user, branch_id, "je.branch_id", params)

            # Build optional cost center filter for actuals
            cost_center_filter = ""
            if cost_center_id:
                cost_center_filter = "AND jl.cost_center_id = :cost_center_id"
                params["cost_center_id"] = cost_center_id
                
            # Query Explanation:
            # 1. Get all budget items for this budget.
            # 2. Join with Accounts to get names.
            # 3. Join with Journal Lines (via Journal Entries) filtered by Date Range to calculate ACTUAL.
            #    Actual for Expense = Debit - Credit. 
            #    Actual for Revenue = Credit - Debit. 
            #    (Assuming we generally budget Expenses and Revenues).
            # 4. Scale planned_amount by the time period ratio.
            
            query = f"""
                WITH Actuals AS (
                    SELECT 
                        jl.account_id,
                        SUM(
                            CASE 
                                WHEN a.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                                ELSE jl.credit - jl.debit
                            END
                        ) as actual_amount
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    WHERE je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted'
                    {branch_filter}
                    {cost_center_filter}
                    GROUP BY jl.account_id
                )
                SELECT 
                    bi.account_id,
                    a.account_number,
                    a.name as account_name,
                    bi.planned_amount * :factor as planned_amount,
                    COALESCE(act.actual_amount, 0) as actual_amount
                FROM budget_items bi
                JOIN accounts a ON bi.account_id = a.id
                LEFT JOIN Actuals act ON bi.account_id = act.account_id
                WHERE bi.budget_id = :bid
                ORDER BY a.account_number
            """
            
            rows = conn.execute(text(query), params).fetchall()
            
            report = []
            for row in rows:
                planned = _q_money(row.planned_amount)
                actual = _q_money(row.actual_amount)
                variance = planned - actual # Positive means under budget (good for expense), Negative means over budget
                is_over_budget = actual > planned
                
                usage_pct = _q_pct((actual / planned * Decimal("100")) if planned != 0 else Decimal("0"))
                variance_pct = _q_pct(((actual - planned) / planned * Decimal("100")) if planned != 0 else Decimal("0"))
                
                report.append({
                    "account_id": row.account_id,
                    "account_name": row.account_name,
                    "account_number": row.account_number,
                    "planned": planned,
                    "actual": actual,
                    "variance": variance,
                    "usage_percentage": usage_pct,
                    "usage_percentage_capped": min(usage_pct, Decimal("100")),
                    "variance_percentage": variance_pct,
                    "is_over_budget": is_over_budget
                })
                
            return report
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# --- New Endpoints: Budget Lifecycle, Alerts, Stats ---

@router.put("/{budget_id}", response_model=BudgetResponse, dependencies=[Depends(require_permission("accounting.budgets.manage"))])
@limiter.limit("100/minute")
def update_budget(budget_id: int, budget: BudgetCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update budget details"""
    with transactional(current_user.company_id) as conn:
        try:
            existing = conn.execute(text("SELECT * FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "budget_not_found", request))
            
            # Check name uniqueness (exclude current)
            dup = conn.execute(text("SELECT 1 FROM budgets WHERE name = :name AND id != :id"), 
                              {"name": budget.name, "id": budget_id}).fetchone()
            if dup:
                raise HTTPException(**http_error(400, "budget_name_already_exists", request))
            
            conn.execute(text("""
                UPDATE budgets SET name = :name, budget_name = :name, start_date = :start, end_date = :end, 
                description = :desc, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "name": budget.name, "start": budget.start_date, "end": budget.end_date,
                "desc": budget.description, "id": budget_id
            })
            
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.update", resource_type="budget",
                         resource_id=str(budget_id), details={"name": budget.name},
                         request=request)
            
            updated = conn.execute(text("SELECT * FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
            return {
                "id": updated.id, "name": updated.name,
                "start_date": updated.start_date, "end_date": updated.end_date,
                "description": updated.description, "status": updated.status,
                "created_at": str(updated.created_at),
                "branch_id": updated.branch_id,
                "cost_center_id": updated.cost_center_id
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error updating budget: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{budget_id}/activate", dependencies=[Depends(require_permission("accounting.budgets.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def activate_budget(budget_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Activate a draft budget"""
    with transactional(current_user.company_id) as conn:
        try:
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                existing_log = conn.execute(text("""
                    SELECT id FROM audit_logs
                    WHERE action = 'budgets.activate'
                      AND resource_id = :resource_id
                      AND details ->> 'idempotency_key' = :key
                """), {"resource_id": str(budget_id), "key": idempotency_key}).fetchone()
                if existing_log:
                    return {"message": i18n_message("budget_activated", request)}

            budget = _get_budget_for_branch_scope(conn, current_user, budget_id, request)
            if budget.status != 'draft':
                raise HTTPException(**http_error(400, "only_draft_budgets_can_be_activated", request))
            
            # Check it has items
            items_count = conn.execute(text("SELECT COUNT(*) FROM budget_items WHERE budget_id = :id"), {"id": budget_id}).scalar()
            if items_count == 0:
                raise HTTPException(**http_error(400, "cannot_activate_budget_with_no_items", request))
            
            conn.execute(text("UPDATE budgets SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": budget_id})
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.activate", resource_type="budget",
                         resource_id=str(budget_id), details={"idempotency_key": idempotency_key},
                         request=request)
            return {"message": i18n_message("budget_activated", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{budget_id}/close", dependencies=[Depends(require_permission("accounting.budgets.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def close_budget(budget_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Close an active budget"""
    with transactional(current_user.company_id) as conn:
        try:
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                existing_log = conn.execute(text("""
                    SELECT id FROM audit_logs
                    WHERE action = 'budgets.close'
                      AND resource_id = :resource_id
                      AND details ->> 'idempotency_key' = :key
                """), {"resource_id": str(budget_id), "key": idempotency_key}).fetchone()
                if existing_log:
                    return {"message": i18n_message("budget_closed", request)}

            budget = _get_budget_for_branch_scope(conn, current_user, budget_id, request, for_update=True)

            # Audit F-NEW-013: closing a budget is a dated mutation that
            # affects period reporting; reject if today's period is locked.
            check_fiscal_period_open(conn, date.today(), request=request)

            if budget.status not in ('active', 'draft'):
                raise HTTPException(**http_error(400, "budget_is_already_closed", request))
            
            conn.execute(text("UPDATE budgets SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": budget_id})
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.close", resource_type="budget",
                         resource_id=str(budget_id), details={"idempotency_key": idempotency_key},
                         request=request)
            return {"message": i18n_message("budget_closed", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/{budget_id}/items", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def get_budget_items(request: Request, budget_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Get all budget items with account details"""
    with transactional(current_user.company_id) as conn:
        budget = _get_budget_for_branch_scope(
            conn,
            current_user,
            budget_id,
            request,
            "id, status, branch_id, start_date, end_date",
        )
        budget_months = Decimal(_count_budget_months(budget.start_date, budget.end_date))
        
        rows = conn.execute(text("""
            SELECT bi.id, bi.account_id, bi.planned_amount, bi.notes,
                   a.account_number, a.name as account_name, a.account_type
            FROM budget_items bi
            JOIN accounts a ON bi.account_id = a.id
            WHERE bi.budget_id = :bid
            ORDER BY a.account_number
        """), {"bid": budget_id}).fetchall()
        
        return [
            {
                "id": row.id,
                "account_id": row.account_id,
                "planned_amount": _money_str(row.planned_amount),
                "monthly_amount": _money_str(_q_money(row.planned_amount) / budget_months if budget_months else Decimal("0")),
                "notes": row.notes,
                "account_number": row.account_number,
                "account_name": row.account_name,
                "account_type": row.account_type
            }
            for row in rows
        ]


@router.get("/alerts/overruns", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def get_budget_overrun_alerts(
    request: Request,
    threshold: Decimal = Decimal("80.0"),
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """Get budget items that are at or over the threshold percentage of planned amount"""
    with transactional(current_user.company_id) as conn:
        try:
            params = {"threshold": threshold}
            branch_filter = branch_scope_filter(current_user, branch_id, "b.branch_id", params)
            
            # Only check active budgets
            rows = conn.execute(text(f"""
                WITH Actuals AS (
                    SELECT 
                        jl.account_id,
                        b.id as budget_id,
                        SUM(
                            CASE 
                                WHEN a.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                                ELSE jl.credit - jl.debit
                            END
                        ) as actual_amount
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    JOIN budgets b ON je.entry_date BETWEEN b.start_date AND b.end_date
                    JOIN budget_items bi ON bi.budget_id = b.id AND bi.account_id = jl.account_id
                    WHERE je.status = 'posted'
                    AND b.status = 'active'
                    {branch_filter}
                    GROUP BY jl.account_id, b.id
                )
                SELECT 
                    b.id as budget_id,
                    b.name as budget_name,
                    bi.account_id,
                    a.account_number,
                    a.name as account_name,
                    bi.planned_amount,
                    COALESCE(act.actual_amount, 0) as actual_amount,
                    CASE WHEN bi.planned_amount > 0 
                        THEN ROUND((COALESCE(act.actual_amount, 0) / bi.planned_amount * 100)::numeric, 2)
                        ELSE 0 
                    END as usage_percentage
                FROM budget_items bi
                JOIN budgets b ON bi.budget_id = b.id
                JOIN accounts a ON bi.account_id = a.id
                LEFT JOIN Actuals act ON bi.account_id = act.account_id AND b.id = act.budget_id
                WHERE b.status = 'active'
                AND bi.planned_amount > 0
                {branch_filter}
                AND COALESCE(act.actual_amount, 0) / bi.planned_amount * 100 >= :threshold
                ORDER BY usage_percentage DESC
            """), params).fetchall()
            
            alerts = []
            for row in rows:
                planned = _q_money(row.planned_amount)
                actual = _q_money(row.actual_amount)
                pct = _q_pct(row.usage_percentage)
                
                severity = "warning"  # 80-100%
                if pct >= 100:
                    severity = "critical"  # Over 100%
                elif pct >= 90:
                    severity = "danger"  # 90-100%
                
                alerts.append({
                    "budget_id": row.budget_id,
                    "budget_name": row.budget_name,
                    "account_id": row.account_id,
                    "account_number": row.account_number,
                    "account_name": row.account_name,
                    "planned": _money_str(planned),
                    "actual": _money_str(actual),
                    "variance": _money_str(planned - actual),
                    "usage_percentage": _pct_str(pct),
                    "usage_percentage_capped": _pct_str(min(pct, Decimal("100"))),
                    "severity": severity
                })
            
            return alerts
        except Exception as e:
            logger.error(f"Error fetching budget overrun alerts: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/stats/summary", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_budget_stats(request: Request, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user)):
    """Get overall budget statistics with currency conversion"""
    with transactional(current_user.company_id) as conn:
        try:
            params = {}
            branch_filter = branch_scope_filter(current_user, branch_id, "b.branch_id", params)
            
            # Budget counts by status
            counts = conn.execute(text(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE b.status = 'draft') as draft_count,
                    COUNT(*) FILTER (WHERE b.status = 'active') as active_count,
                    COUNT(*) FILTER (WHERE b.status = 'closed') as closed_count
                FROM budgets b
                WHERE 1=1 {branch_filter}
            """), params).fetchone()
            
            # Total planned with currency conversion
            # When branch_id is specified: use amounts as-is (local currency)
            # When branch_id is null (all branches): convert to SAR using exchange rates
            if branch_id:
                params["actual_branch_id"] = branch_id
                totals = conn.execute(text(f"""
                    SELECT 
                        COALESCE(SUM(bi.planned_amount), 0) as total_planned,
                        COALESCE(SUM(
                            (SELECT COALESCE(SUM(
                                CASE 
                                    WHEN a.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                                    ELSE jl.credit - jl.debit
                                END
                            ), 0)
                            FROM journal_lines jl
                            JOIN journal_entries je ON jl.journal_entry_id = je.id
                            JOIN accounts a ON jl.account_id = a.id
                            WHERE jl.account_id = bi.account_id
                            AND je.entry_date BETWEEN b.start_date AND b.end_date
                            AND je.status = 'posted'
                            AND je.branch_id = :actual_branch_id)
                        ), 0) as total_actual
                    FROM budget_items bi
                    JOIN budgets b ON bi.budget_id = b.id
                    WHERE b.status IN ('active', 'draft') {branch_filter}
                """), params).fetchone()
            else:
                # All branches: convert to SAR using branch currency and latest exchange rates
                # Filter journal entries by budget's branch to get correct actual per branch
                totals = conn.execute(text(f"""
                    SELECT 
                        COALESCE(SUM(bi.planned_amount * COALESCE(
                            (SELECT er.rate FROM exchange_rates er 
                             JOIN currencies c ON c.id = er.currency_id
                             WHERE c.code = br.default_currency 
                             AND er.rate_date = (SELECT MAX(rate_date) FROM exchange_rates)
                             LIMIT 1),
                            1::numeric
                        )), 0) as total_planned,
                        COALESCE(SUM(
                            (SELECT COALESCE(SUM(
                                (CASE 
                                    WHEN a.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                                    ELSE jl.credit - jl.debit
                                END) * COALESCE(
                                    (SELECT er2.rate FROM exchange_rates er2
                                     JOIN currencies c2 ON c2.id = er2.currency_id
                                     WHERE c2.code = COALESCE(br.default_currency, 'SAR')
                                     AND er2.rate_date = (SELECT MAX(rate_date) FROM exchange_rates)
                                     LIMIT 1),
                                    1::numeric
                                )
                            ), 0)
                            FROM journal_lines jl
                            JOIN journal_entries je ON jl.journal_entry_id = je.id
                            JOIN accounts a ON jl.account_id = a.id
                            WHERE jl.account_id = bi.account_id
                            AND je.entry_date BETWEEN b.start_date AND b.end_date
                            AND je.status = 'posted'
                            AND je.branch_id = b.branch_id)
                        ), 0) as total_actual
                    FROM budget_items bi
                    JOIN budgets b ON bi.budget_id = b.id
                    LEFT JOIN branches br ON br.id = b.branch_id
                    WHERE b.status IN ('active', 'draft') {branch_filter}
                """), params).fetchone()
            
            total_planned = _q_money(totals.total_planned if totals else 0)
            total_actual = _q_money(totals.total_actual if totals else 0)
            
            # Count overrun items
            overruns = conn.execute(text(f"""
                WITH ActualAmounts AS (
                    SELECT 
                        bi.id as item_id,
                        bi.planned_amount,
                        COALESCE(SUM(
                            CASE 
                                WHEN a.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                                ELSE jl.credit - jl.debit
                            END
                        ), 0) as actual_amount
                    FROM budget_items bi
                    JOIN budgets b ON bi.budget_id = b.id
                    JOIN accounts a ON bi.account_id = a.id
                    LEFT JOIN journal_lines jl ON jl.account_id = bi.account_id
                    LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id 
                        AND je.entry_date BETWEEN b.start_date AND b.end_date
                        AND je.status = 'posted'
                    WHERE b.status = 'active'
                    AND bi.planned_amount > 0
                    {branch_filter}
                    GROUP BY bi.id, bi.planned_amount
                )
                SELECT COUNT(*) as overrun_count
                FROM ActualAmounts
                WHERE actual_amount > planned_amount
            """), params).scalar() or 0
            
            return {
                "total_budgets": counts.total,
                "draft_count": counts.draft_count,
                "active_count": counts.active_count,
                "closed_count": counts.closed_count,
                "total_planned": _money_str(total_planned),
                "total_actual": _money_str(total_actual),
                "total_variance": _money_str(total_planned - total_actual),
                "overall_usage_pct": _pct_str((total_actual / total_planned * Decimal("100")) if total_planned > 0 else Decimal("0")),
                "overrun_items_count": overruns
            }
        except Exception as e:
            logger.error(f"Error fetching budget stats: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# =====================================================
# 8.13 BUDGETS IMPROVEMENTS
# =====================================================

# ---------- BDG-001: Budget by Cost Center ----------

@router.get("/by-cost-center", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_all_cc_budgets(request: Request, current_user: UserResponse = Depends(get_current_user)):
    """List all budgets that have a cost center assigned."""
    with transactional(current_user.company_id) as conn:
        try:
            params: Dict[str, Any] = {}
            branch_filter = branch_scope_filter(current_user, None, "b.branch_id", params)
            rows = conn.execute(text(f"""
                SELECT b.*, COALESCE(SUM(bi.planned_amount),0) as total_planned
                FROM budgets b
                LEFT JOIN budget_items bi ON bi.budget_id = b.id
                WHERE b.cost_center_id IS NOT NULL {branch_filter}
                GROUP BY b.id ORDER BY b.start_date DESC
            """), params).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            logger.error(f"Error listing cost center budgets: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/by-cost-center", dependencies=[Depends(require_permission("accounting.budgets.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_budget_by_cost_center(request: Request, data: dict, current_user: UserResponse = Depends(get_current_user)):
    """Create a budget allocated to a specific cost center."""
    with transactional(current_user.company_id) as conn:
        try:
            exists = conn.execute(text("SELECT 1 FROM budgets WHERE name = :name"), {"name": data["name"]}).fetchone()
            if exists:
                raise HTTPException(**http_error(400, "budget_name_exists", request))
            branch_id = validate_branch_access(current_user, data.get("branch_id"), request)
            result = conn.execute(text("""
                INSERT INTO budgets (name, start_date, end_date, description, status, created_by,
                    cost_center_id, budget_type, fiscal_year, branch_id)
                VALUES (:name, :start, :end, :desc, 'draft', :uid, :ccid, :btype, :fy, :branch_id)
                RETURNING id, created_at, status
            """), {
                "name": data["name"], "start": data["start_date"], "end": data["end_date"],
                "desc": data.get("description"), "uid": current_user.id,
                "ccid": data["cost_center_id"],
                "btype": data.get("budget_type", "annual"),
                "fy": data.get("fiscal_year"),
                "branch_id": branch_id,
            }).fetchone()
            log_activity(conn, user_id=current_user.id, username=current_user.username,
                         action="budgets.create_by_cost_center", resource_type="budget",
                         resource_id=str(result.id),
                         details={"name": data["name"], "cost_center_id": data["cost_center_id"]},
                         request=request)
            return {"id": result.id, "name": data["name"], "status": "draft",
                    "cost_center_id": data["cost_center_id"], "branch_id": branch_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/by-cost-center/{cc_id}", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_budgets_by_cc(request: Request, cc_id: int, current_user: UserResponse = Depends(get_current_user)):
    """List Budgets By Cc."""
    with transactional(current_user.company_id) as conn:
        params: Dict[str, Any] = {"cc": cc_id}
        branch_filter = branch_scope_filter(current_user, None, "b.branch_id", params)
        rows = conn.execute(text(f"""
            SELECT b.*, COALESCE(SUM(bi.planned_amount),0) as total_planned
            FROM budgets b
            LEFT JOIN budget_items bi ON bi.budget_id = b.id
            WHERE b.cost_center_id = :cc {branch_filter}
            GROUP BY b.id ORDER BY b.start_date DESC
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]


# ---------- BDG-002: Multi-Year & Quarterly Budgets ----------

@router.get("/multi-year", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_multi_year_budgets(
    request: Request,
    fiscal_year: Optional[int] = None,
    budget_type: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """List Multi Year Budgets."""
    with transactional(current_user.company_id) as conn:
        q = "SELECT * FROM budgets WHERE budget_type IN ('multi_year','quarterly')"
        params = {}
        q += " " + branch_scope_filter(current_user, None, "branch_id", params)
        if fiscal_year:
            q += " AND fiscal_year = :fy"
            params["fy"] = fiscal_year
        if budget_type:
            q += " AND budget_type = :bt"
            params["bt"] = budget_type
        q += " ORDER BY fiscal_year DESC, start_date"
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/comparison", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def compare_budgets(
    request: Request,
    budget_ids: str,
    current_user: UserResponse = Depends(get_current_user)
):
    """Compare multiple budgets side by side. budget_ids = comma-separated."""
    with transactional(current_user.company_id) as conn:
        try:
            ids = [int(x.strip()) for x in budget_ids.split(",") if x.strip()]
            if len(ids) < 2:
                raise HTTPException(**http_error(400, "need_at_least_2_budget_ids", request))
            placeholders = ",".join([f":id{i}" for i in range(len(ids))])
            params = {f"id{i}": v for i, v in enumerate(ids)}
            branch_filter = branch_scope_filter(current_user, None, "b.branch_id", params)
            budgets = conn.execute(text(f"""
                SELECT b.id, b.name, b.start_date, b.end_date, b.fiscal_year, b.budget_type,
                       COALESCE(SUM(bi.planned_amount),0) as total_planned,
                       COALESCE(SUM(bi.actual_amount),0) as total_actual
                FROM budgets b
                LEFT JOIN budget_items bi ON bi.budget_id = b.id
                WHERE b.id IN ({placeholders}) {branch_filter}
                GROUP BY b.id ORDER BY b.start_date
            """), params).fetchall()
            return [dict(r._mapping) for r in budgets]
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# --- IMPORTANT: /{budget_id} must be LAST so it doesn't shadow static routes like /multi-year ---
@router.get("/{budget_id}", dependencies=[Depends(require_permission("accounting.budgets.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_budget_detail(request: Request, budget_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Get budget with summary info"""
    with transactional(current_user.company_id) as conn:
        budget = _get_budget_for_branch_scope(
            conn,
            current_user,
            budget_id,
            request,
            columns="id, name, start_date, end_date, description, status, created_at, branch_id",
        )
        
        # Summary: total planned, items count
        summary = conn.execute(text("""
            SELECT 
                COUNT(*) as items_count,
                COALESCE(SUM(planned_amount), 0) as total_planned
            FROM budget_items WHERE budget_id = :id
        """), {"id": budget_id}).fetchone()
        
        return {
            "id": budget.id,
            "name": budget.name,
            "start_date": str(budget.start_date),
            "end_date": str(budget.end_date),
            "description": budget.description,
            "status": budget.status,
            "created_at": str(budget.created_at),
            "items_count": summary.items_count,
            "total_planned": _money_str(summary.total_planned)
        }
