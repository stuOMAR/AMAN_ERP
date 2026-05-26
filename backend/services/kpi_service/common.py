"""kpi_service.common — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def resolve_period(period: str, start_date: Optional[date] = None, end_date: Optional[date] = None) -> Tuple[date, date]:
    """Resolve period keyword to (start_date, end_date) tuple."""
    today = date.today()
    if period == "custom" and start_date and end_date:
        return (start_date, end_date)
    elif period == "today":
        return (today, today)
    elif period == "wtd":
        # Week starts Sunday in Saudi Arabia
        days_since_sunday = (today.weekday() + 1) % 7
        return (today - timedelta(days=days_since_sunday), today)
    elif period == "mtd":
        return (today.replace(day=1), today)
    elif period == "qtd":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        return (today.replace(month=quarter_month, day=1), today)
    elif period == "ytd":
        return (today.replace(month=1, day=1), today)
    elif period == "last_month":
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        return (last_month_end.replace(day=1), last_month_end)
    elif period == "last_quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        qstart = today.replace(month=quarter_month, day=1)
        prev_q_end = qstart - timedelta(days=1)
        prev_q_month = ((prev_q_end.month - 1) // 3) * 3 + 1
        return (prev_q_end.replace(month=prev_q_month, day=1), prev_q_end)
    else:
        # Default: MTD
        return (today.replace(day=1), today)


def get_previous_period(start_date: date, end_date: date) -> Tuple[date, date]:
    """Get the equivalent previous period for comparison."""
    delta = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=delta - 1)
    return (prev_start, prev_end)


def _branch_id_sequence(branch_id: Any) -> Optional[list[int]]:
    if isinstance(branch_id, (list, tuple, set)):
        return [int(b) for b in branch_id]
    return None


def build_branch_filter(branch_id: Optional[int], table_alias: str = "je") -> Tuple[str, dict]:
    """Build branch filter SQL clause and params."""
    branch_ids = _branch_id_sequence(branch_id)
    if branch_ids is not None:
        if not branch_ids:
            return ("AND 1=0", {})
        return (f"AND {table_alias}.branch_id = ANY(:branch_ids)", {"branch_ids": branch_ids})
    if branch_id:
        return (f"AND {table_alias}.branch_id = :branch_id", {"branch_id": branch_id})
    return ("", {})


def kpi_item(key: str, label_en: str, label_ar: str, value: Any, unit: str = "",
             trend_value: str = "", trend_direction: str = "neutral", trend_positive: bool = True,
             benchmark: Any = None, benchmark_source: str = "", status: str = "neutral") -> dict:
    """Build a standardized KPI item dict."""
    return {
        "key": key,
        "label": label_en,
        "label_ar": label_ar,
        "value": round(value, 2) if isinstance(value, (int, float)) else value,
        "unit": unit,
        "trend_value": trend_value,
        "trend_direction": trend_direction,
        "trend_positive": trend_positive,
        "benchmark": benchmark,
        "benchmark_source": benchmark_source,
        "status": status,
    }


def calc_trend(current: float, previous: float) -> Tuple[str, str, bool]:
    """Calculate trend value, direction, and whether it's positive.
    Returns (trend_value, trend_direction, trend_positive) assuming higher is better.
    """
    if previous == 0:
        if current > 0:
            return ("+100%", "up", True)
        return ("0%", "neutral", True)
    change = ((current - previous) / abs(previous)) * 100
    direction = "up" if change > 0 else ("down" if change < 0 else "neutral")
    positive = change >= 0
    return (f"{'+' if change >= 0 else ''}{change:.1f}%", direction, positive)


def calc_trend_inverse(current: float, previous: float) -> Tuple[str, str, bool]:
    """Like calc_trend but lower is better (e.g., expenses, DSO)."""
    trend_value, direction, _ = calc_trend(current, previous)
    positive = direction == "down" or direction == "neutral"
    return (trend_value, direction, positive)


def ratio_status(value: float, good: float, warning: float, higher_is_better: bool = True) -> str:
    """Determine status based on thresholds."""
    if higher_is_better:
        if value >= good:
            return "good"
        elif value >= warning:
            return "warning"
        return "danger"
    else:
        if value <= good:
            return "good"
        elif value <= warning:
            return "warning"
        return "danger"


# ═══════════════════════════════════════════════════════════════════════════════
# GL-Based Building Blocks (used by multiple KPIs)
# ═══════════════════════════════════════════════════════════════════════════════

def _gl_sum(db, account_type: str, start_date: date, end_date: date,
            branch_id: Optional[int] = None, debit_minus_credit: bool = True) -> float:
    """Sum journal lines for a given account type within a period."""
    branch_sql, params = build_branch_filter(branch_id)
    expr = "jl.debit - jl.credit" if debit_minus_credit else "jl.credit - jl.debit"
    result = db.execute(text(f"""
        SELECT COALESCE(SUM({expr}), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.account_type = :acct_type
          AND je.entry_date BETWEEN :start_dt AND :end_dt
          AND je.status = 'posted'
          {branch_sql}
    """), {"acct_type": account_type, "start_dt": start_date, "end_dt": end_date, **params}).scalar()
    return float(result or 0)


def _gl_balance(db, account_type: str, as_of: date,
                branch_id: Optional[int] = None, debit_minus_credit: bool = True) -> float:
    """Cumulative balance of accounts of a given type up to a date.
    Handles special sub-types (receivable, payable) via account_code patterns."""
    branch_sql, params = build_branch_filter(branch_id)
    expr = "jl.debit - jl.credit" if debit_minus_credit else "jl.credit - jl.debit"
    # Handle sub-types that don't exist as account_type values
    special_types = {
        "receivable": "(a.account_type = 'asset' AND a.account_code LIKE '12%')",
        "payable": "(a.account_type = 'liability' AND a.account_code LIKE '21%')",
    }
    if account_type in special_types:
        type_filter = special_types[account_type]
    else:
        type_filter = "a.account_type = :acct_type"
        params["acct_type"] = account_type
    result = db.execute(text(f"""
        SELECT COALESCE(SUM({expr}), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN accounts a ON jl.account_id = a.id
        WHERE {type_filter}
          AND je.entry_date <= :end_dt
          AND je.status = 'posted'
          {branch_sql}
    """), {"end_dt": as_of, **params}).scalar()
    return float(result or 0)


def _gl_balance_by_classification(db, classification: str, as_of: date,
                                   branch_id: Optional[int] = None) -> float:
    """Balance by account classification (current_asset, fixed_asset, current_liability, etc.).
    Uses account_number patterns since accounts table has no classification column."""
    branch_sql, params = build_branch_filter(branch_id)
    code_filters = {
        "current_asset": "(a.account_type = 'asset' AND a.account_number ~ '^1[1-5]')",
        "fixed_asset": "(a.account_type = 'asset' AND a.account_number ~ '^1[6-9]')",
        "current_liability": "(a.account_type = 'liability' AND a.account_number ~ '^21')",
        "long_term_liability": "(a.account_type = 'liability' AND a.account_number ~ '^22')",
    }
    filter_sql = code_filters.get(classification, f"a.account_type = '{classification}'")
    result = db.execute(text(f"""
        SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN accounts a ON jl.account_id = a.id
        WHERE {filter_sql}
          AND je.entry_date <= :end_dt
          AND je.status = 'posted'
          {branch_sql}
    """), {"end_dt": as_of, **params}).scalar()
    return float(result or 0)


def _count_table(db, table: str, branch_id: Optional[int] = None,
                 date_col: str = "created_at", start_date: Optional[date] = None,
                 end_date: Optional[date] = None, extra_where: str = "") -> int:
    """Count rows in a table with optional filters."""
    conditions = ["1=1"]
    params = {}
    branch_ids = _branch_id_sequence(branch_id)
    if branch_ids is not None:
        if branch_ids:
            conditions.append("branch_id = ANY(:branch_ids)")
            params["branch_ids"] = branch_ids
        else:
            conditions.append("1=0")
    elif branch_id:
        conditions.append("branch_id = :branch_id")
        params["branch_id"] = branch_id
    if start_date and date_col:
        conditions.append(f"{date_col} >= :start_dt")
        params["start_dt"] = start_date
    if end_date and date_col:
        conditions.append(f"{date_col} <= :end_dt")
        params["end_dt"] = end_date
    if extra_where:
        conditions.append(extra_where)
    where = " AND ".join(conditions)
    result = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}"), params).scalar()
    return int(result or 0)


def _sum_column(db, table: str, column: str, branch_id: Optional[int] = None,
                date_col: str = "created_at", start_date: Optional[date] = None,
                end_date: Optional[date] = None, extra_where: str = "") -> float:
    """Sum a column in a table with optional filters."""
    conditions = ["1=1"]
    params = {}
    branch_ids = _branch_id_sequence(branch_id)
    if branch_ids is not None:
        if branch_ids:
            conditions.append("branch_id = ANY(:branch_ids)")
            params["branch_ids"] = branch_ids
        else:
            conditions.append("1=0")
    elif branch_id:
        conditions.append("branch_id = :branch_id")
        params["branch_id"] = branch_id
    if start_date and date_col:
        conditions.append(f"{date_col} >= :start_dt")
        params["start_dt"] = start_date
    if end_date and date_col:
        conditions.append(f"{date_col} <= :end_dt")
        params["end_dt"] = end_date
    if extra_where:
        conditions.append(extra_where)
    where = " AND ".join(conditions)
    result = db.execute(text(f"SELECT COALESCE(SUM({column}), 0) FROM {table} WHERE {where}"), params).scalar()
    return float(result or 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Executive Dashboard KPIs (CEO / Admin)
# ═══════════════════════════════════════════════════════════════════════════════

