"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from datetime import date, timedelta
from decimal import Decimal
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, resolve_branch_scope, branch_scope_filter_from_scope

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/hr/payroll/trend", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["hr.reports", "reports.view"]))])
def get_payroll_trend(
    months: int = 12,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """اتجاه تكاليف الرواتب الشهرية"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        # Calculate start date (first day of month, 'months' ago)
        today = date.today()
        start_date = (today.replace(day=1) - timedelta(days=months*30)).replace(day=1)
        
        params = {"start": start_date}
        
        # Note: Payroll Periods are generally company-wide, but we can filter entries by employee branch if needed.
        # However, payroll_periods table is the main grouper.
        # Let's group by period end_date or start_date.
        
        query = """
            SELECT 
                TO_CHAR(p.end_date, 'YYYY-MM') as month,
                COALESCE(SUM(pe.net_salary), 0) as total_net,
                COALESCE(SUM(pe.basic_salary + pe.housing_allowance + pe.transport_allowance + pe.other_allowances), 0) as total_gross
            FROM payroll_periods p
            JOIN payroll_entries pe ON p.id = pe.period_id
            JOIN employees e ON pe.employee_id = e.id
            WHERE p.status = 'posted'
            AND p.end_date >= :start
        """
        
        query += f"\n{branch_scope_filter_from_scope(branch_scope, 'e.branch_id', params)}"
            
        query += """
            GROUP BY TO_CHAR(p.end_date, 'YYYY-MM')
            ORDER BY month
        """
        
        result = db.execute(text(query), params).fetchall()
        
        # Fill missing months? For now just return data
        return [
            {
                "month": row.month, 
                "total_net": Decimal(str(row.total_net)), 
                "total_gross": Decimal(str(row.total_gross))
            } 
            for row in result
        ]
    finally:
        db.close()

@router.get("/hr/leaves/usage", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["hr.reports", "reports.view"]))])
def get_leave_usage(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """إحصائيات الإجازات حسب النوع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1) # Start of year
        if not end_date:
            end_date = date.today()
            
        params = {"start": start_date, "end": end_date}
        
        branch_filter = branch_scope_filter_from_scope(branch_scope, "e.branch_id", params)

        # Group by Leave Type
        query = f"""
            SELECT 
                l.leave_type,
                COUNT(*) as request_count,
                COALESCE(SUM(l.end_date - l.start_date + 1), 0) as total_days
            FROM leave_requests l
            JOIN employees e ON l.employee_id = e.id
            WHERE l.status = 'approved'
            AND l.start_date BETWEEN :start AND :end
            {branch_filter}
            GROUP BY l.leave_type
        """
        
        result = db.execute(text(query), params).fetchall()
        
        return [
            {
                "type": row.leave_type,
                "count": row.request_count,
                "days": int(row.total_days)
            }
            for row in result
        ]
    finally:
        db.close()
