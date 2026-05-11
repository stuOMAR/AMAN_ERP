"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, resolve_branch_scope, branch_scope_filter_from_scope
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/purchases/summary", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص المشتريات"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            import calendar
            last_day = calendar.monthrange(start_date.year, start_date.month)[1]
            end_date = start_date.replace(day=last_day)
            
        params = {"start": start_date, "end": end_date}
        
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
        
        summary = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(total * COALESCE(exchange_rate, 1.0)), 0) as total_purchases,
                COALESCE(SUM(paid_amount * COALESCE(exchange_rate, 1.0)), 0) as total_paid,
                COALESCE(SUM((total - paid_amount) * COALESCE(exchange_rate, 1.0)), 0) as total_due
            FROM invoices 
            WHERE invoice_type = 'purchase' 
            AND status NOT IN ('cancelled', 'draft')
            AND invoice_date BETWEEN :start AND :end
            {branch_filter}
        """), params).fetchone()
        
        return {
            "period": {"start": start_date, "end": end_date},
            "stats": {
                "invoice_count": summary.count,
                "total_purchases": Decimal(str(summary.total_purchases or 0)),
                "total_paid": Decimal(str(summary.total_paid or 0)),
                "total_due": Decimal(str(summary.total_due or 0))
            }
        }
    finally:
        db.close()

@router.get("/purchases/trend", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_trend(
    days: int = 30,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """اتجاه المشتريات اليومي"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        result = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                invoice_date as date,
                COUNT(*) as count,
                COALESCE(SUM(total * COALESCE(exchange_rate, 1.0)), 0) as total
            FROM invoices 
            WHERE invoice_type = 'purchase' 
            AND status NOT IN ('cancelled', 'draft')
            AND invoice_date >= :start
            {branch_filter}
            GROUP BY invoice_date
            ORDER BY invoice_date
        """), params).fetchall()
        
        return [{"date": row.date, "count": row.count, "total": Decimal(str(row.total))} for row in result]
    finally:
        db.close()

@router.get("/purchases/by-supplier", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_by_supplier(
    limit: int = 5,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """أكبر الموردين"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)

        result = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                p.name as name,
                COUNT(i.id) as invoice_count,
                COALESCE(SUM(i.total * COALESCE(i.exchange_rate, 1.0)), 0) as total_purchases
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase'
            AND i.status NOT IN ('cancelled', 'draft')
            {branch_filter}
            GROUP BY p.id, p.name
            ORDER BY total_purchases DESC
            LIMIT :limit
        """), params).fetchall()
        
        return [{"name": row.name, "count": row.invoice_count, "value": Decimal(str(row.total_purchases))} for row in result]
    finally:
        db.close()


@router.get("/purchases/aging", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_aging_report(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير أعمار الذمم الدائنة (مستحقات الموردين)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "sl.branch_id", params)

        # Query net supplier exposure from supplier_subledger. Aging by open
        # document allocation is not available for every document type, so the
        # report uses supplier/currency net balance and the oldest contributing
        # date while preserving reconciliation to AP/subledger totals.
        results = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                p.name as supplier_name,
                NULL::text AS document_number,
                MIN(sl.document_date) AS document_date,
                MIN(sl.document_date) AS due_date,
                SUM(sl.credit - sl.debit) as due_amount_fc,
                SUM(sl.base_credit - sl.base_debit) as due_amount,
                GREATEST(CURRENT_DATE - MIN(sl.document_date), 0) as days_old,
                sl.currency
            FROM supplier_subledger sl
            JOIN parties p ON sl.party_id = p.id
            WHERE 1=1
            {branch_filter}
            GROUP BY sl.party_id, p.name, sl.currency
            HAVING SUM(sl.base_credit - sl.base_debit) > 0.01
            ORDER BY days_old DESC
        """), params).fetchall()

        report = []
        totals = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        for row in results:
            bucket = "0-30"
            days = row.days_old or 0
            if days > 90:
                bucket = "90+"
            elif days > 60:
                bucket = "61-90"
            elif days > 30:
                bucket = "31-60"

            amount = Decimal(str(row.due_amount or 0))
            totals[bucket] += amount
            report.append({
                "supplier": row.supplier_name,
                "invoice": row.document_number or "-",
                "date": row.document_date,
                "due_date": row.due_date,
                "amount": amount,
                "amount_fc": Decimal(str(row.due_amount_fc or 0)),
                "currency": row.currency,
                "days": days,
                "bucket": bucket,
            })

        return report
    finally:
        db.close()


@router.get("/purchases/supplier-statement/{supplier_id}", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_supplier_statement(
    supplier_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """كشف حساب مورد تفصيلي"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()
            
        params = {"sid": supplier_id, "start": start_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        # T036: Opening balance from supplier_subledger (includes all document types)
        opening_balance = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT (COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)) as balance
            FROM supplier_subledger
            WHERE party_id = :sid AND document_date < :start
            {branch_filter}
        """), params).scalar() or 0

        # T036: Transactions from supplier_subledger (includes all document types)
        params["end"] = end_date
        transactions = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT
                document_id as id,
                document_date as date,
                document_number as ref,
                document_type as type,
                credit,
                debit,
                party_id,
                branch_id
            FROM supplier_subledger
            WHERE party_id = :sid AND document_date BETWEEN :start AND :end
            {branch_filter}
            ORDER BY document_date
        """), params).fetchall()

        # 3. Running Balance
        statement = []
        running_balance = Decimal(str(opening_balance))
        
        for t in transactions:
            credit = Decimal(str(t.credit)) # Purchase increases debt
            debit = Decimal(str(t.debit))   # Payment reduces debt
            
            balance_after = running_balance + credit - debit
            statement.append({
                "date": t.date,
                "ref": t.ref,
                "type": t.type,
                "debit": debit,
                "credit": credit,
                "balance": balance_after
            })
            running_balance = balance_after

        return {
            "supplier_id": supplier_id,
            "period": {"start": start_date, "end": end_date},
            "opening_balance": Decimal(str(opening_balance)),
            "transactions": statement,
            "closing_balance": running_balance
        }
    finally:
        db.close()

# --- HR Reports ---
