
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

logger = logging.getLogger(__name__)
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown

router = APIRouter(prefix="/reports", tags=["Reports"])


# ---------------------------------------------------------------------------
# Shared GL query helpers (Constitution: no duplicated report SQL)
# ---------------------------------------------------------------------------

def _compute_net_income_from_gl(db, *, end_date, start_date=None, branch_id=None) -> Decimal:
    """
    Single source of truth for net income = Revenue − Expense from journal_lines.
    Used by both the income statement and the balance sheet (retained earnings).
    """
    branch_filter = ""
    params: dict = {"as_of": end_date}
    if start_date:
        date_clause = "je.entry_date BETWEEN :start AND :as_of"
        params["start"] = start_date
    else:
        date_clause = "je.entry_date <= :as_of"
    if branch_id:
        branch_filter = "AND je.branch_id = :branch"
        params["branch"] = branch_id

    row = db.execute(text(f"""
        SELECT
            COALESCE(SUM(CASE WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN a.account_type = 'expense'  THEN jl.debit - jl.credit ELSE 0 END), 0) AS net_income
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN accounts a ON jl.account_id = a.id
        WHERE a.account_type IN ('revenue', 'expense')
          AND {date_clause}
          AND je.status = 'posted'
          {branch_filter}
    """), params).fetchone()
    return Decimal(str(row.net_income)) if row else Decimal("0")

# --- Schemas ---
class TrialBalanceItem(BaseModel):
    account_id: int
    account_number: str
    name: str
    name_en: Optional[str]
    account_type: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal

class TrialBalanceResponse(BaseModel):
    period: Dict[str, date]
    data: List[TrialBalanceItem]
    totals: Dict[str, Decimal]

class FinancialStatementItem(BaseModel):
    id: int
    account_number: str
    name: str
    name_en: Optional[str] = None
    account_type: str
    balance: Decimal
    level: int = 0
    parent_id: Optional[int] = None
    children: List['FinancialStatementItem'] = []

class FinancialStatementResponse(BaseModel):
    period: Dict[str, date]
    data: List[FinancialStatementItem]
    total: Decimal

@router.get("/sales/summary", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_sales_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص المبيعات (إجمالي، عدد الفواتير، الأرباح التقريبية)"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # T3.1: unified gross sales source (matches Dashboard)
        sales = get_sales_total(
            db,
            start_date=start_date,
            end_date=end_date,
            branch_id=branch_id,
        )

        # Approximate tax extracted from gross totals (assumes embedded tax
        # at the line-level rate; falls back to 15 % when no lines exist).
        params = {"start": start_date, "end": end_date}
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        tax_row = db.execute(text(f"""
            WITH all_sales AS (
                SELECT
                    total,
                    COALESCE(exchange_rate, 1.0) as exchange_rate,
                    invoice_date as sale_date,
                    branch_id,
                    id,
                    'invoice' as source
                FROM invoices
                WHERE invoice_type = 'sales'
                AND status NOT IN ('cancelled', 'draft')

                UNION ALL

                SELECT
                    total_amount as total,
                    1.0 as exchange_rate,
                    CAST(order_date AS DATE) as sale_date,
                    branch_id,
                    id,
                    'pos' as source
                FROM pos_orders
                WHERE status IN ('paid', 'completed')
            )
            SELECT
                COALESCE(SUM((total * COALESCE(exchange_rate, 1.0) * (
                    CASE WHEN source = 'invoice' THEN
                        COALESCE((SELECT AVG(tax_rate) FROM invoice_lines WHERE invoice_id = all_sales.id), 0)
                    ELSE
                        COALESCE((SELECT AVG(tax_rate) FROM pos_order_lines WHERE order_id = all_sales.id), 0)
                    END
                ) / (100 + CASE WHEN source = 'invoice' THEN
                        COALESCE((SELECT AVG(tax_rate) FROM invoice_lines WHERE invoice_id = all_sales.id), 15)
                    ELSE
                        COALESCE((SELECT AVG(tax_rate) FROM pos_order_lines WHERE order_id = all_sales.id), 15)
                    END)) ), 0) as total_tax
            FROM all_sales
            WHERE sale_date BETWEEN :start AND :end
            {branch_filter}
        """), params).fetchone()

        # T3.1: shared GL profit breakdown
        gl = get_gl_profit_breakdown(
            db,
            start_date=start_date,
            end_date=end_date,
            branch_id=branch_id,
        )
        revenue = gl["net_revenue"]
        cogs = gl["cogs"]
        operating_expenses = gl["operating_expenses"]
        gross_profit = gl["gross_profit"]
        net_profit = gl["net_profit"]

        return {
            "period": {"start": start_date, "end": end_date},
            "stats": {
                "invoice_count": sales["invoice_count"],
                "total_sales": sales["total_sales"],
                "total_paid": sales["total_paid"],
                "total_due": sales["total_due"],
                "net_revenue": revenue,
                "total_tax": Decimal(str(tax_row.total_tax or 0)),
                "total_cogs": cogs,
                "gross_profit": gross_profit,
                "operating_expenses": operating_expenses,
                "net_profit": net_profit,
                "margin": (gross_profit / revenue * 100) if revenue > 0 else 0
            }
        }
    finally:
        db.close()

@router.get("/sales/trend", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_sales_trend(
    days: int = 30,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """اتجاه المبيعات اليومي"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id
        
        result = db.execute(text(f"""
            WITH all_sales AS (
                SELECT 
                    invoice_date as sale_date,
                    total * COALESCE(exchange_rate, 1.0) as total_bc,
                    branch_id
                FROM invoices 
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                
                UNION ALL
                
                SELECT 
                    CAST(order_date AS DATE) as sale_date,
                    total_amount as total_bc,
                    branch_id
                FROM pos_orders
                WHERE status IN ('paid', 'completed')
            )
            SELECT 
                sale_date as date,
                COUNT(*) as count,
                COALESCE(SUM(total_bc), 0) as total
            FROM all_sales 
            WHERE sale_date >= :start
            {branch_filter.replace('branch_id', 'branch_id')}
            GROUP BY sale_date
            ORDER BY sale_date
        """), params).fetchall()
        
        return [{"date": row.date, "count": row.count, "total": Decimal(str(row.total))} for row in result]
    finally:
        db.close()

@router.get("/sales/by-customer", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_sales_by_customer(
    limit: int = 5,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """أفضل العملاء"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        result = db.execute(text(f"""
            WITH all_sales AS (
                SELECT 
                    party_id, 
                    total * COALESCE(exchange_rate, 1.0) as total_bc,
                    branch_id
                FROM invoices 
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                
                UNION ALL
                
                SELECT 
                    customer_id as party_id, 
                    total_amount as total_bc,
                    branch_id
                FROM pos_orders
                WHERE status IN ('paid', 'completed')
            )
            SELECT 
                p.name as name,
                COUNT(s.party_id) as invoice_count,
                COALESCE(SUM(s.total_bc), 0) as total_sales
            FROM all_sales s
            JOIN parties p ON s.party_id = p.id
            WHERE 1=1
            {branch_filter.replace('i.branch_id', 's.branch_id')}
            GROUP BY p.id, p.name
            ORDER BY total_sales DESC
            LIMIT :limit
        """), params).fetchall()
        
        return [{"name": row.name, "count": row.invoice_count, "value": Decimal(str(row.total_sales))} for row in result]
    finally:
        db.close()

@router.get("/sales/by-product", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_sales_by_product(
    limit: int = 5,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """المنتجات الأكثر مبيعاً"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        result = db.execute(text(f"""
            WITH combined_lines AS (
                SELECT 
                    il.product_id,
                    il.quantity,
                    il.total * COALESCE(i.exchange_rate, 1.0) as total_bc,
                    i.branch_id
                FROM invoice_lines il
                JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'sales' AND i.status != 'cancelled'
                
                UNION ALL
                
                SELECT 
                    poi.product_id,
                    poi.quantity,
                    poi.total as total_bc,
                    po.branch_id
                FROM pos_order_lines poi
                JOIN pos_orders po ON poi.order_id = po.id
                WHERE po.status IN ('paid', 'completed')
            )
            SELECT 
                p.product_name as name,
                COALESCE(SUM(cl.quantity), 0) as quantity,
                COALESCE(SUM(cl.total_bc), 0) as total_sales
            FROM combined_lines cl
            JOIN products p ON cl.product_id = p.id
            WHERE 1=1
            {branch_filter.replace('i.branch_id', 'cl.branch_id')}
            GROUP BY p.id, p.product_name
            ORDER BY total_sales DESC
            LIMIT :limit
        """), params).fetchall()
        
        return [{"name": row.name, "quantity": Decimal(str(row.quantity)), "value": Decimal(str(row.total_sales))} for row in result]
    finally:
        db.close()

@router.get("/sales/customer-statement/{customer_id}", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_customer_statement(
    customer_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """كشف حساب عميل تفصيلي"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"cid": customer_id, "start": start_date}
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        # 1. Get Opening Balance (Combined: invoices + POS + payment vouchers)
        opening_balance = db.execute(text(f"""
            WITH all_movements AS (
                SELECT 
                    (total * COALESCE(exchange_rate, 1.0)) as debit, 
                    0 as credit,
                    invoice_date as sale_date,
                    branch_id,
                    party_id
                FROM invoices
                WHERE invoice_type = 'sales' AND status NOT IN ('cancelled', 'draft')
                
                UNION ALL
                
                SELECT 
                    total_amount as debit, 
                    0 as credit,
                    CAST(order_date AS DATE) as sale_date,
                    branch_id,
                    customer_id as party_id
                FROM pos_orders
                WHERE status IN ('paid', 'completed')
                
                UNION ALL
                
                SELECT 
                    0 as debit,
                    (amount * COALESCE(exchange_rate, 1.0)) as credit,
                    voucher_date as sale_date,
                    branch_id,
                    party_id
                FROM payment_vouchers
                WHERE party_type = 'customer' AND voucher_type = 'receipt' AND status != 'cancelled'
            )
            SELECT (COALESCE(SUM(debit), 0) - COALESCE(SUM(credit), 0)) as balance
            FROM all_movements
            WHERE party_id = :cid AND sale_date < :start
            {branch_filter.replace('branch_id', 'branch_id')}
        """), params).scalar() or 0

        # Also consider manual transactions or deprecated table structure if needed,
        # but for now we rely on invoices. Ideally we should query customer_transactions.
        # Let's check `customer_transactions` table existence in database.py
        # Creating a more robust query using `customer_transactions` if populated, 
        # but our Invoice creation (sales.py) doesn't seem to insert into `customer_transactions` yet explicitly based on my last read?
        # Re-checking sales.py: create_invoice updates `customers` balance but I didn't see insert into `customer_transactions`.
        # Wait, `database.py` has `customer_transactions`.
        # If I didn't implement writing to `customer_transactions` in `sales.py`, the statement will be empty if I rely on it.
        # For this version, I will rely on `invoices` and `customer_receipts` (if implemented).
        # Let's stick to `invoices` for now as primary source.

        # 2. Get Transactions (Combined: invoices + POS + payment vouchers)
        params["end"] = end_date
        transactions = db.execute(text(f"""
            WITH all_movements AS (
                SELECT 
                    id, invoice_date as date, invoice_number as ref, 
                    'invoice' as type, (total * COALESCE(exchange_rate, 1.0)) as debit,
                    0 as credit,
                    currency, exchange_rate, branch_id, party_id
                FROM invoices
                WHERE invoice_type = 'sales' AND status NOT IN ('cancelled', 'draft')
                
                UNION ALL
                
                SELECT 
                    id, CAST(order_date AS DATE) as date, order_number as ref, 
                    'pos_order' as type, total_amount as debit, 
                    0 as credit,
                    (SELECT COALESCE((SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1), (SELECT setting_value FROM company_settings WHERE setting_key = 'default_currency'), 'SYP')) as currency, 1.0 as exchange_rate, branch_id, customer_id as party_id
                FROM pos_orders
                WHERE status IN ('paid', 'completed')
                
                UNION ALL
                
                SELECT 
                    id, voucher_date as date, voucher_number as ref,
                    'receipt' as type, 0 as debit,
                    (amount * COALESCE(exchange_rate, 1.0)) as credit,
                    currency, exchange_rate, branch_id, party_id
                FROM payment_vouchers
                WHERE party_type = 'customer' AND voucher_type = 'receipt' AND status != 'cancelled'
            )
            SELECT * FROM all_movements
            WHERE party_id = :cid AND date BETWEEN :start AND :end
            {branch_filter.replace('branch_id', 'branch_id')}
            ORDER BY date
        """), params).fetchall()

        # 3. Running Balance
        statement = []
        running_balance = Decimal(str(opening_balance))
        
        for t in transactions:
            debit = Decimal(str(t.debit))
            credit = Decimal(str(t.credit or 0)) 
            
            balance_after = running_balance + debit - credit
            statement.append({
                "date": t.date,
                "ref": t.ref,
                "type": t.type,
                "debit": debit,
                "credit": credit,
                "balance": balance_after,
                "currency": t.currency,
                "original_amount": Decimal(str(t.debit / (t.exchange_rate if t.exchange_rate else 1)))
            })
            running_balance = balance_after

        return {
            "customer_id": customer_id,
            "period": {"start": start_date, "end": end_date},
            "opening_balance": Decimal(str(opening_balance)),
            "transactions": statement,
            "closing_balance": running_balance
        }
    finally:
        db.close()

@router.get("/sales/aging", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_aging_report(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير أعمار الديون"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id
        # Get all unpaid invoices + POS credit orders with days overdue
        # Get base currency for POS
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)

        results = db.execute(text(f"""
            SELECT 
                p.name as customer_name,
                i.invoice_number,
                i.invoice_date,
                i.due_date,
                (i.total - COALESCE(i.paid_amount, 0)) as due_amount_fc,
                (i.total - COALESCE(i.paid_amount, 0)) * COALESCE(i.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - COALESCE(i.due_date, i.invoice_date), 0) as days_old,
                i.currency
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'sales' 
            AND i.status NOT IN ('draft', 'cancelled', 'paid')
            AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
            {branch_filter}

            UNION ALL

            SELECT 
                COALESCE(p2.name, po.walk_in_customer_name, 'عميل عام') as customer_name,
                po.order_number as invoice_number,
                po.order_date::date as invoice_date,
                po.order_date::date as due_date,
                (po.total_amount - COALESCE(po.paid_amount, 0)) as due_amount_fc,
                (po.total_amount - COALESCE(po.paid_amount, 0)) as due_amount,
                GREATEST(CURRENT_DATE - po.order_date::date, 0) as days_old,
                :base_currency as currency
            FROM pos_orders po
            LEFT JOIN parties p2 ON po.customer_id = p2.id
            WHERE po.status NOT IN ('cancelled', 'refunded')
            AND (po.total_amount - COALESCE(po.paid_amount, 0)) > 0.01
            {branch_filter}

            ORDER BY days_old DESC
        """), {**params, "base_currency": base_currency}).fetchall()

        # Group buckets
        report = []
        for row in results:
            bucket = "0-30"
            days = row.days_old or 0
            if days > 90: bucket = "90+"
            elif days > 60: bucket = "61-90"
            elif days > 30: bucket = "31-60"
            
            report.append({
                "customer": row.customer_name,
                "invoice": row.invoice_number,
                "date": row.invoice_date,
                "due_date": row.due_date,
                "amount": Decimal(str(row.due_amount or 0)),
                "amount_fc": Decimal(str(row.due_amount_fc or 0)),
                "currency": row.currency,
                "days": days,
                "bucket": bucket
            })
            
        return report
    finally:
        db.close()

# --- Purchases Reports ---

@router.get("/purchases/summary", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص المشتريات"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            import calendar
            last_day = calendar.monthrange(start_date.year, start_date.month)[1]
            end_date = start_date.replace(day=last_day)
            
        params = {"start": start_date, "end": end_date}
        
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id
        
        summary = db.execute(text(f"""
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        result = db.execute(text(f"""
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        result = db.execute(text(f"""
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        results = db.execute(text(f"""
            SELECT 
                p.name as supplier_name,
                i.invoice_number,
                i.invoice_date,
                i.due_date,
                (i.total - COALESCE(i.paid_amount, 0)) as due_amount_fc,
                (i.total - COALESCE(i.paid_amount, 0)) * COALESCE(i.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - COALESCE(i.due_date, i.invoice_date), 0) as days_old,
                i.currency
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase'
            AND i.status NOT IN ('draft', 'cancelled', 'paid')
            AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
            {branch_filter}
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
                "invoice": row.invoice_number,
                "date": row.invoice_date,
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()
            
        params = {"sid": supplier_id, "start": start_date}
        branch_filter = "AND branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        # 1. Get Opening Balance (Before start_date)
        # For suppliers: Invoices (credit/increase) - Payments (debit/decrease)
        opening_balance = db.execute(text(f"""
            WITH all_movements AS (
                SELECT 
                    0 as debit, (total * COALESCE(exchange_rate, 1.0)) as credit,
                    invoice_date as txn_date,
                    branch_id,
                    party_id
                FROM invoices
                WHERE invoice_type = 'purchase' AND status NOT IN ('cancelled', 'draft')
                
                UNION ALL
                
                SELECT 
                    (amount * COALESCE(exchange_rate, 1.0)) as debit, 0 as credit,
                    voucher_date as txn_date,
                    branch_id,
                    party_id
                FROM payment_vouchers
                WHERE party_type = 'supplier' AND voucher_type = 'payment' AND status != 'cancelled'
            )
            SELECT (COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)) as balance
            FROM all_movements
            WHERE party_id = :sid AND txn_date < :start
            {branch_filter}
        """), params).scalar() or 0

        # 2. Get Transactions (invoices + payment vouchers)
        params["end"] = end_date
        transactions = db.execute(text(f"""
            WITH all_movements AS (
                SELECT 
                    id, invoice_date as date, invoice_number as ref, 
                    'invoice' as type, (total * COALESCE(exchange_rate, 1.0)) as credit, 0 as debit,
                    party_id, branch_id
                FROM invoices
                WHERE invoice_type = 'purchase' AND status NOT IN ('cancelled', 'draft')
                
                UNION ALL
                
                SELECT 
                    id, voucher_date as date, voucher_number as ref,
                    'payment' as type, 0 as credit,
                    (amount * COALESCE(exchange_rate, 1.0)) as debit,
                    party_id, branch_id
                FROM payment_vouchers
                WHERE party_type = 'supplier' AND voucher_type = 'payment' AND status != 'cancelled'
            )
            SELECT * FROM all_movements
            WHERE party_id = :sid AND date BETWEEN :start AND :end
            {branch_filter}
            ORDER BY date
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

@router.get("/hr/payroll/trend", response_model=List[Dict[str, Any]], dependencies=[Depends(require_permission(["hr.reports", "reports.view"]))])
def get_payroll_trend(
    months: int = 12,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """اتجاه تكاليف الرواتب الشهرية"""
    branch_id = validate_branch_access(current_user, branch_id)
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
        
        if branch_id:
            query += " AND e.branch_id = :branch_id"
            params["branch_id"] = branch_id
            
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1) # Start of year
        if not end_date:
            end_date = date.today()
            
        params = {"start": start_date, "end": end_date}
        
        branch_filter = ""
        if branch_id:
            branch_filter = "AND e.branch_id = :branch_id"
            params["branch_id"] = branch_id

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
def _get_trial_balance_data(db, start_date, end_date, branch_id=None):
    """Internal helper: returns trial balance data for programmatic use."""
    params = {"start": start_date, "end": end_date}
    
    branch_filter = ""
    if branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        params["branch_id"] = branch_id

    query = f"""
        WITH opening_bal AS (
            SELECT 
                jl.account_id,
                SUM(jl.debit) as open_debit,
                SUM(jl.credit) as open_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE je.entry_date < :start
            AND je.status = 'posted'
            {branch_filter}
            GROUP BY jl.account_id
        ),
        movement AS (
            SELECT 
                jl.account_id,
                SUM(jl.debit) as period_debit,
                SUM(jl.credit) as period_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE je.entry_date BETWEEN :start AND :end
            AND je.status = 'posted'
            {branch_filter}
            GROUP BY jl.account_id
        )
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type,
            COALESCE(o.open_debit, 0) as open_debit,
            COALESCE(o.open_credit, 0) as open_credit,
            COALESCE(m.period_debit, 0) as period_debit,
            COALESCE(m.period_credit, 0) as period_credit
        FROM accounts a
        LEFT JOIN opening_bal o ON a.id = o.account_id
        LEFT JOIN movement m ON a.id = m.account_id
        WHERE (o.open_debit IS NOT NULL OR o.open_credit IS NOT NULL OR m.period_debit IS NOT NULL OR m.period_credit IS NOT NULL)
        ORDER BY a.account_number
    """
    
    result = db.execute(text(query), params).fetchall()
    
    data = []
    total_open_dr = total_open_cr = total_period_dr = total_period_cr = total_close_dr = total_close_cr = 0
    
    for row in result:
        acct_type = row.account_type
        
        # Net opening balance by account type direction
        raw_open_dr = Decimal(str(row.open_debit))
        raw_open_cr = Decimal(str(row.open_credit))
        open_net = raw_open_dr - raw_open_cr  # positive = debit balance
        
        # Debit-normal accounts (asset, expense): show net in DR if positive
        # Credit-normal accounts (liability, equity, revenue): show net in CR if positive
        if acct_type in ('asset', 'expense'):
            o_dr = open_net if open_net > 0 else 0
            o_cr = abs(open_net) if open_net < 0 else 0
        else:
            # For credit-normal accounts, flip: negative net means debit excess
            o_cr = abs(open_net) if open_net < 0 else 0  # credit-normal: net < 0 means excess debit
            o_dr = open_net if open_net > 0 else 0
            # Actually: credit-normal: positive credit balance = credit - debit > 0 → net < 0
            # Recalculate: for credit-normal, opening = CR - DR (if positive → show in CR column)
            credit_net = raw_open_cr - raw_open_dr
            o_cr = credit_net if credit_net > 0 else 0
            o_dr = abs(credit_net) if credit_net < 0 else 0
        
        # Period movement
        p_dr = Decimal(str(row.period_debit))
        p_cr = Decimal(str(row.period_credit))
        
        # Closing
        # Standard Accounting logic: (DR_open + DR_period) - (CR_open + CR_period)
        # If positive -> Closing DR. If negative -> Closing CR.
        net_total = (o_dr + p_dr) - (o_cr + p_cr)
        
        c_dr = net_total if net_total > 0 else 0
        c_cr = abs(net_total) if net_total < 0 else 0
        
        data.append({
            "account_id": row.id,
            "account_number": row.account_number,
            "name": row.name,
            "name_en": row.name_en,
            "account_type": row.account_type,
            "opening_debit": o_dr,
            "opening_credit": o_cr,
            "period_debit": p_dr,
            "period_credit": p_cr,
            "closing_debit": c_dr,
            "closing_credit": c_cr
        })
        
        total_open_dr += o_dr
        total_open_cr += o_cr
        total_period_dr += p_dr
        total_period_cr += p_cr
        total_close_dr += c_dr
        total_close_cr += c_cr
        
    return {
        "period": {"start": start_date, "end": end_date},
        "data": data,
        "totals": {
            "opening_debit": total_open_dr,
            "opening_credit": total_open_cr,
            "period_debit": total_period_dr,
            "period_credit": total_period_cr,
            "closing_debit": total_close_dr,
            "closing_credit": total_close_cr
        }
    }

@router.get("/accounting/trial-balance", response_model=TrialBalanceResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_trial_balance", expire=60)
def get_trial_balance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ميزان المراجعة لفترة محددة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1) # Start of year
        if not end_date:
            end_date = date.today()
        return _get_trial_balance_data(db, start_date, end_date, branch_id)
    finally:
        db.close()

def _get_profit_loss_data(db, start_date, end_date, branch_id=None):
    """Internal helper to get profit loss data"""
    params = {"start": start_date, "end": end_date}
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    if branch_id: params["branch_id"] = branch_id

    # Fetch all accounts and their period balances
    query = f"""
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id,
            COALESCE(SUM(CASE 
                WHEN a.account_type = 'expense' THEN jl.debit - jl.credit
                WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit
                ELSE 0 
            END), 0) as balance
        FROM accounts a
        LEFT JOIN journal_lines jl ON a.id = jl.account_id
        LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE a.account_type IN ('revenue', 'expense')
        AND (je.id IS NULL OR (je.entry_date BETWEEN :start AND :end AND je.status = 'posted' {branch_filter}))
        GROUP BY a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id
        ORDER BY a.account_number
    """
    
    accounts = [dict(row._mapping) for row in db.execute(text(query), params).fetchall()]
    
    # Build hierarchy
    account_map = {a["id"]: {**a, "children": [], "level": 0} for a in accounts}
    roots = []
    
    # First pass: map children and find roots
    for acc_id, acc in account_map.items():
        parent_id = acc["parent_id"]
        if parent_id and parent_id in account_map:
            account_map[parent_id]["children"].append(acc)
        else:
            roots.append(acc)
    
    # Second pass: Roll up balances and set levels
    def rollup(node, level):
        node["level"] = level
        child_sum = 0
        for child in node["children"]:
            child_sum += rollup(child, level + 1)
        node["balance"] = Decimal(str(node["balance"])) + child_sum
        return node["balance"]

    total_revenue = 0
    total_expense = 0
    for root in roots:
        bal = rollup(root, 0)
        if root["account_type"] == 'revenue':
            total_revenue += bal
        elif root["account_type"] == 'expense':
            total_expense += bal
    
    # Net Income = Revenue - Expenses (not Revenue + Expenses)
    net_income = total_revenue - total_expense
        
    return {
        "period": {"start": start_date, "end": end_date},
        "data": roots,
        "total": net_income
    }

@router.get("/accounting/profit-loss", response_model=FinancialStatementResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_profit_loss", expire=60)
def get_profit_loss(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قائمة الدخل (الأرباح والخسائر) الهيكلية"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1)
        if not end_date:
            end_date = date.today()
            
        return _get_profit_loss_data(db, start_date, end_date, branch_id)
    finally:
        db.close()

def _get_balance_sheet_data(db, as_of_date, branch_id=None):
    """Internal helper to get balance sheet data"""
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    params = {"as_of": as_of_date}
    if branch_id: params["branch_id"] = branch_id

    # Balance Sheet follows Assets = Liabilities + Equity
    # We sum all transactions from the beginning of time up to as_of_date
    query = f"""
        SELECT 
            a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id,
            COALESCE(SUM(CASE 
                WHEN a.account_type IN ('asset', 'expense') THEN jl.debit - jl.credit
                ELSE jl.credit - jl.debit
            END), 0) as balance
        FROM accounts a
        LEFT JOIN journal_lines jl ON a.id = jl.account_id
        LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE a.account_type IN ('asset', 'liability', 'equity')
        AND (je.id IS NULL OR (je.entry_date <= :as_of AND je.status = 'posted' {branch_filter}))
        GROUP BY a.id, a.account_number, a.name, a.name_en, a.account_type, a.parent_id
        ORDER BY a.account_number
    """
    
    accounts = [dict(row._mapping) for row in db.execute(text(query), params).fetchall()]
    
    # Build hierarchy
    account_map = {a["id"]: {**a, "children": [], "level": 0} for a in accounts}
    roots = []
    
    for acc_id, acc in account_map.items():
        parent_id = acc["parent_id"]
        if parent_id and parent_id in account_map:
            account_map[parent_id]["children"].append(acc)
        else:
            roots.append(acc)
    
    def rollup(node, level):
        node["level"] = level
        child_sum = 0
        for child in node["children"]:
            child_sum += rollup(child, level + 1)
        node["balance"] = Decimal(str(node["balance"])) + child_sum
        return node["balance"]

    for root in roots:
        rollup(root, 0)
    
    # Calculate Retained Earnings (Net Income) using the shared helper
    # This ensures Balance Sheet balances: Assets = Liabilities + Equity + Retained Earnings
    retained_earnings = _compute_net_income_from_gl(
        db, end_date=as_of_date, branch_id=branch_id,
    )
    
    # Add retained earnings as a virtual equity item
    if retained_earnings != 0:
        roots.append({
            "id": -1,
            "account_number": "RE",
            "name": "Retained Earnings / الأرباح المبقاة",
            "name_en": "Retained Earnings",
            "account_type": "equity",
            "balance": retained_earnings,
            "children": [],
            "level": 0
        })

    # Compute totals
    total_assets = sum(r["balance"] for r in roots if r.get("account_type") == "asset")
    total_liabilities = sum(r["balance"] for r in roots if r.get("account_type") == "liability")
    total_equity = sum(r["balance"] for r in roots if r.get("account_type") == "equity")

    return {
        "period": {"start": as_of_date, "end": as_of_date},
        "data": roots,
        "total": total_assets,
        "as_of": as_of_date,
        "net_income": retained_earnings,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity
    }

@router.get("/accounting/balance-sheet", response_model=FinancialStatementResponse, dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
@cached("report_balance_sheet", expire=60)
def get_balance_sheet(
    as_of_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب الميزانية العمومية الهيكلية"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not as_of_date:
            as_of_date = date.today()
            
        return _get_balance_sheet_data(db, as_of_date, branch_id)
    finally:
        db.close()

@router.get("/accounting/budget-vs-actual", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def get_budget_report(
    budget_id: int,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة الميزانية التقديرية مع الفعلي"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        # 1. Get Budget info
        budget = db.execute(text("SELECT * FROM budgets WHERE id = :id"), {"id": budget_id}).fetchone()
        if not budget:
             raise HTTPException(**http_error(404, "budget_not_found"))
             
        start_date = budget.start_date
        end_date = budget.end_date
        
        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        params = {"start": start_date, "end": end_date, "bid": budget_id}
        if branch_id: params["branch_id"] = branch_id

        # 2. Get Budget Items vs Actuals
        query = f"""
            SELECT 
                a.id as account_id, a.account_number, a.name, a.name_en,
                bi.planned_amount,
                COALESCE(actuals.balance, 0) as actual_amount
            FROM budget_items bi
            JOIN accounts a ON bi.account_id = a.id
            LEFT JOIN (
                SELECT 
                    jl.account_id,
                    SUM(CASE 
                        WHEN a2.account_type IN ('expense', 'asset') THEN jl.debit - jl.credit
                        ELSE jl.credit - jl.debit
                    END) as balance
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a2 ON jl.account_id = a2.id
                WHERE je.entry_date BETWEEN :start AND :end
                  AND je.status = 'posted'
                  {branch_filter}
                GROUP BY jl.account_id
            ) as actuals ON bi.account_id = actuals.account_id
            WHERE bi.budget_id = :bid
            ORDER BY a.account_number
        """
        
        items = db.execute(text(query), params).fetchall()
        
        report_data = []
        for r in items:
            planned = Decimal(str(r.planned_amount or 0))
            actual = Decimal(str(r.actual_amount or 0))
            variance = planned - actual
            performance = (actual / planned * 100) if planned != 0 else 0
            
            report_data.append({
                "account_id": r.account_id,
                "account_number": r.account_number,
                "name": r.name,
                "name_en": r.name_en,
                "planned": planned,
                "actual": actual,
                "variance": variance,
                "performance_pct": performance
            })
            
        return {
            "budget": dict(budget._mapping),
            "data": report_data
        }
    finally:
        db.close()

def _get_cashflow_data(db, start_date, end_date, branch_id=None):
    """Internal helper: returns cash flow data for programmatic use."""
    branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
    params = {"start": start_date, "end": end_date}
    if branch_id: params["branch_id"] = branch_id

    # 1. Get all Cash/Bank GL Account IDs
    # From treasury_accounts table
    treasury_gl_ids = [row[0] for row in db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE is_active = true")).fetchall() if row[0]]
    
    # From legacy codes (BOX, BNK)
    legacy_gl_ids = [row[0] for row in db.execute(text("SELECT id FROM accounts WHERE account_code IN ('BOX', 'BNK')")).fetchall()]
    
    # Combine and deduplicate
    all_cash_ids = list(set(treasury_gl_ids + legacy_gl_ids))
    
    if not all_cash_ids:
        return {
            "period": {"start": start_date, "end": end_date},
            "inflows": [], "outflows": [], "total_inflow": 0, "total_outflow": 0, "net_cash_flow": 0
        }

    # Use parameterized query for safety
    params["cash_ids"] = all_cash_ids

    # Inflows (Debit Cash/Bank)
    inflow_query = f"""
        SELECT 
            a_other.account_type, 
            a_other.name as category,
            SUM(jl_other.credit) as amount
        FROM journal_lines jl_cash
        JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
        JOIN accounts a_cash ON jl_cash.account_id = a_cash.id
        JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id
        JOIN accounts a_other ON jl_other.account_id = a_other.id
        WHERE a_cash.id = ANY(:cash_ids)
          AND jl_cash.debit > 0
          AND a_other.id != a_cash.id
          AND je.entry_date BETWEEN :start AND :end
          AND je.status = 'posted'
          {branch_filter}
        GROUP BY a_other.account_type, a_other.name
    """
    
    inflows = db.execute(text(inflow_query), params).fetchall()
    
    # Outflows (Credit Cash/Bank)
    outflow_query = f"""
        SELECT 
            a_other.account_type, 
            a_other.name as category,
            SUM(jl_other.debit) as amount
        FROM journal_lines jl_cash
        JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
        JOIN accounts a_cash ON jl_cash.account_id = a_cash.id
        JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id
        JOIN accounts a_other ON jl_other.account_id = a_other.id
        WHERE a_cash.id = ANY(:cash_ids)
          AND jl_cash.credit > 0
          AND a_other.id != a_cash.id
          AND je.entry_date BETWEEN :start AND :end
          AND je.status = 'posted'
          {branch_filter}
        GROUP BY a_other.account_type, a_other.name
    """
    
    outflows = db.execute(text(outflow_query), params).fetchall()
    
    return {
        "period": {"start": start_date, "end": end_date},
        "inflows": [dict(r._mapping) for r in inflows],
        "outflows": [dict(r._mapping) for r in outflows],
        "total_inflow": Decimal(str(sum((Decimal(str(r.amount or 0)) for r in inflows), Decimal(0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        "total_outflow": Decimal(str(sum((Decimal(str(r.amount or 0)) for r in outflows), Decimal(0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        "net_cash_flow": Decimal(str((sum((Decimal(str(r.amount or 0)) for r in inflows), Decimal(0)) - sum((Decimal(str(r.amount or 0)) for r in outflows), Decimal(0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
    }

@router.get("/accounting/cashflow", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def get_cashflow_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير التدفقات النقدية (مبسط)"""
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()
        return _get_cashflow_data(db, start_date, end_date, branch_id)
    finally:
        db.close()


@router.get("/accounting/cashflow-ias7", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def get_cashflow_ias7(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    قائمة التدفقات النقدية حسب معيار IAS 7
    Cash Flow Statement — Operating / Investing / Financing
    """
    branch_id = validate_branch_access(current_user, branch_id)
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        params = {"start": start_date, "end": end_date}
        if branch_id:
            params["branch_id"] = branch_id

        # Get Cash/Bank accounts
        treasury_gl_ids = [row[0] for row in db.execute(text(
            "SELECT gl_account_id FROM treasury_accounts WHERE is_active = true"
        )).fetchall() if row[0]]
        legacy_gl_ids = [row[0] for row in db.execute(text(
            "SELECT id FROM accounts WHERE account_code IN ('BOX', 'BNK')"
        )).fetchall()]
        cash_ids = list(set(treasury_gl_ids + legacy_gl_ids))
        if not cash_ids:
            cash_ids = [row[0] for row in db.execute(text(
                "SELECT id FROM accounts WHERE account_type IN ('cash', 'bank', 'current_asset') AND (name ILIKE '%نقد%' OR name ILIKE '%بنك%' OR name ILIKE '%صندوق%' OR name_en ILIKE '%cash%' OR name_en ILIKE '%bank%')"
            )).fetchall()]
        if not cash_ids:
            return {"period": {"start": start_date, "end": end_date}, "operating": {}, "investing": {}, "financing": {}, "net_change": 0, "opening_cash": 0, "closing_cash": 0}

        params["cash_ids"] = cash_ids

        # IAS 7 classification: based on actual account_type and account name heuristics
        # Only valid types: asset, liability, equity, revenue, expense

        def classify(account_type, account_name=''):
            at = (account_type or '').lower()
            name_lower = (account_name or '').lower()

            # Equity → Financing
            if at == 'equity':
                return 'financing'

            # Revenue and Expense → Operating
            if at in ('revenue', 'expense'):
                return 'operating'

            # Liability: check name for long-term/loan → Financing, else Operating
            if at == 'liability':
                if any(kw in name_lower for kw in ['قرض', 'loan', 'long', 'طويل', 'سند', 'bond']):
                    return 'financing'
                return 'operating'

            # Asset: check name for fixed asset/investment → Investing, else Operating
            if at == 'asset':
                if any(kw in name_lower for kw in ['أصل ثابت', 'fixed', 'استثمار', 'invest', 'عقار', 'property', 'معدات', 'equipment', 'إهلاك', 'depreciation', 'أراضي', 'land']):
                    return 'investing'
                return 'operating'

            return 'operating'

        # Inflows (debit to cash accounts)
        inflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   SUM(jl_other.credit) as amount
            FROM journal_lines jl_cash
            JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
            JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id AND jl_other.account_id != jl_cash.account_id
            JOIN accounts a_other ON jl_other.account_id = a_other.id
            WHERE jl_cash.account_id = ANY(:cash_ids)
              AND jl_cash.debit > 0
              AND je.entry_date BETWEEN :start AND :end
              AND je.status = 'posted'
              {branch_filter}
            GROUP BY a_other.account_type, a_other.name
        """), params).fetchall()

        # Outflows (credit to cash accounts)
        outflows = db.execute(text(f"""
            SELECT a_other.account_type, a_other.name as account_name,
                   SUM(jl_other.debit) as amount
            FROM journal_lines jl_cash
            JOIN journal_entries je ON jl_cash.journal_entry_id = je.id
            JOIN journal_lines jl_other ON je.id = jl_other.journal_entry_id AND jl_other.account_id != jl_cash.account_id
            JOIN accounts a_other ON jl_other.account_id = a_other.id
            WHERE jl_cash.account_id = ANY(:cash_ids)
              AND jl_cash.credit > 0
              AND je.entry_date BETWEEN :start AND :end
              AND je.status = 'posted'
              {branch_filter}
            GROUP BY a_other.account_type, a_other.name
        """), params).fetchall()

        # Opening cash balance
        opening_cash = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE jl.account_id = ANY(:cash_ids)
              AND je.entry_date < :start
              AND je.status = 'posted'
              {branch_filter}
        """), params).scalar() or 0

        # Build activities
        activities = {'operating': [], 'investing': [], 'financing': []}
        totals = {'operating': Decimal('0'), 'investing': Decimal('0'), 'financing': Decimal('0')}

        for row in inflows:
            activity = classify(row.account_type, row.account_name)
            amt = Decimal(str(row.amount or 0))
            activities[activity].append({
                "description": row.account_name,
                "account_type": row.account_type,
                "amount": Decimal(str(amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                "direction": "inflow"
            })
            totals[activity] += amt

        for row in outflows:
            activity = classify(row.account_type, row.account_name)
            amt = Decimal(str(row.amount or 0))
            activities[activity].append({
                "description": row.account_name,
                "account_type": row.account_type,
                "amount": Decimal(str((-amt).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
                "direction": "outflow"
            })
            totals[activity] -= amt

        net_change = totals['operating'] + totals['investing'] + totals['financing']

        return {
            "period": {"start": start_date, "end": end_date},
            "operating": {
                "items": activities['operating'],
                "total": Decimal(str(totals['operating'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "investing": {
                "items": activities['investing'],
                "total": Decimal(str(totals['investing'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "financing": {
                "items": activities['financing'],
                "total": Decimal(str(totals['financing'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
            },
            "net_change": Decimal(str(net_change.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
            "opening_cash": Decimal(str(Decimal(str(opening_cash)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
            "closing_cash": Decimal(str((Decimal(str(opening_cash)) + net_change).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))),
        }
    finally:
        db.close()


@router.get("/accounting/fx-gain-loss", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def get_fx_gain_loss_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    currency: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير فروق أسعار العملة — الأرباح والخسائر المحققة وغير المحققة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params: dict = {"start": start_date, "end": end_date}
        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id
        currency_filter = "AND je.currency = :currency" if currency else ""
        if currency:
            params["currency"] = currency

        # Realized FX gain/loss: journal entries tagged as FX revaluation
        realized = db.execute(text(f"""
            SELECT
                je.id,
                je.entry_date,
                je.reference,
                je.currency,
                je.description,
                SUM(CASE WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit ELSE 0 END) as fx_gain,
                SUM(CASE WHEN a.account_type = 'expense' THEN jl.debit - jl.credit ELSE 0 END) as fx_loss
            FROM journal_entries je
            JOIN journal_lines jl ON je.id = jl.journal_entry_id
            JOIN accounts a ON jl.account_id = a.id
            WHERE je.status = 'posted'
              AND je.entry_date BETWEEN :start AND :end
              AND (
                  LOWER(je.description) LIKE '%%fx%%' OR
                  LOWER(je.description) LIKE '%%revaluation%%' OR
                  LOWER(je.description) LIKE '%%فروق عملة%%' OR
                  LOWER(je.reference) LIKE '%%fx%%' OR
                  je.source IN ('fx_revaluation', 'fx_adjustment')
              )
              {branch_filter}
            GROUP BY je.id, je.entry_date, je.reference, je.currency, je.description
            ORDER BY je.entry_date
        """), params).fetchall()

        # Get base currency
        base_ccy = db.execute(text(
            "SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1"
        )).scalar() or 'SAR'

        # FX amounts from foreign currency invoices difference
        invoice_fx = db.execute(text(f"""
            SELECT
                i.currency,
                COUNT(*) as invoice_count,
                SUM(i.total) as fc_total,
                SUM(i.total * COALESCE(i.exchange_rate, 1.0)) as lc_total,
                CASE WHEN i.invoice_type = 'sales' THEN 'receivable' ELSE 'payable' END as direction
            FROM invoices i
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              AND COALESCE(i.exchange_rate, 1.0) != 1.0
              {currency_filter}
            GROUP BY i.currency, i.invoice_type
            ORDER BY i.currency
        """), {**params, "base_ccy": base_ccy}).fetchall()

        # Unrealized FX: open foreign currency invoices at current rates
        rate_rows = db.execute(text(
            "SELECT code, COALESCE(current_rate, 1.0) as rate FROM currencies WHERE is_active = TRUE"
        )).fetchall()
        current_rates = {r.code: Decimal(str(r.rate)) for r in rate_rows}

        open_invoices = db.execute(text(f"""
            SELECT
                i.invoice_number, i.invoice_type, i.currency,
                COALESCE(i.exchange_rate, 1.0) as booked_rate,
                (i.total - COALESCE(i.paid_amount, 0)) as open_fc_amount,
                p.name as party_name
            FROM invoices i
            LEFT JOIN parties p ON p.id = i.party_id
            WHERE i.currency != :base_ccy
              AND i.status NOT IN ('cancelled', 'draft', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
              {currency_filter}
        """), {**params, "base_ccy": base_ccy}).fetchall()

        unrealized_list = []
        total_unrealized_gain = Decimal("0")
        total_unrealized_loss = Decimal("0")
        for inv in open_invoices:
            booked = Decimal(str(inv.booked_rate))
            current = current_rates.get(inv.currency, booked)
            open_fc = Decimal(str(inv.open_fc_amount or 0))
            diff = open_fc * (current - booked)
            if inv.invoice_type == 'purchase':
                diff = -diff
            unrealized_list.append({
                "invoice_number": inv.invoice_number,
                "party": inv.party_name,
                "invoice_type": inv.invoice_type,
                "currency": inv.currency,
                "open_fc_amount": round(open_fc, 2),
                "booked_rate": booked,
                "current_rate": current,
                "unrealized_fx": round(diff, 2),
            })
            if diff >= 0:
                total_unrealized_gain += diff
            else:
                total_unrealized_loss += abs(diff)

        realized_list = [{
            "entry_id": r.id,
            "date": r.entry_date,
            "reference": r.reference,
            "currency": r.currency,
            "notes": r.description,
            "fx_gain": Decimal(str(r.fx_gain or 0)),
            "fx_loss": Decimal(str(r.fx_loss or 0)),
            "net": Decimal(str((r.fx_gain or 0) - (r.fx_loss or 0))),
        } for r in realized]

        exposure_list = [{
            "currency": r.currency,
            "direction": r.direction,
            "invoice_count": r.invoice_count,
            "fc_total": Decimal(str(r.fc_total or 0)),
            "lc_total": Decimal(str(r.lc_total or 0)),
        } for r in invoice_fx]

        total_gain = sum(r["fx_gain"] for r in realized_list)
        total_loss = sum(r["fx_loss"] for r in realized_list)

        return {
            "period": {"start": start_date, "end": end_date},
            "realized_entries": realized_list,
            "currency_exposure": exposure_list,
            "unrealized": {
                "invoices": unrealized_list,
                "total_unrealized_gain": round(total_unrealized_gain, 2),
                "total_unrealized_loss": round(total_unrealized_loss, 2),
                "net_unrealized": round(total_unrealized_gain - total_unrealized_loss, 2),
            },
            "summary": {
                "total_fx_gain": round(total_gain + total_unrealized_gain, 2),
                "total_fx_loss": round(total_loss + total_unrealized_loss, 2),
                "net_fx": round((total_gain + total_unrealized_gain) - (total_loss + total_unrealized_loss), 2),
            }
        }
    finally:
        db.close()


def _get_general_ledger_data(db, account_id, start_date, end_date, branch_id=None):
    """Internal helper: returns general ledger data for programmatic use."""
    # ── Recursive CTE: collect selected account + all descendants ──
    tree_rows = db.execute(text("""
        WITH RECURSIVE account_tree AS (
            SELECT id, account_type, name, name_en, account_number, parent_id
            FROM accounts WHERE id = :account_id
            UNION ALL
            SELECT a.id, a.account_type, a.name, a.name_en, a.account_number, a.parent_id
            FROM accounts a
            INNER JOIN account_tree at ON a.parent_id = at.id
        )
        SELECT id, account_type, name, name_en, account_number FROM account_tree
    """), {"account_id": account_id}).fetchall()

    account_ids = [row.id for row in tree_rows]
    account_map = {row.id: f"{row.account_number} - {row.name}" for row in tree_rows}
    
    # Use the root account's type for sign convention
    root_row = next((r for r in tree_rows if r.id == account_id), None)
    acct_type = root_row.account_type if root_row else "asset"
    is_aggregated = len(account_ids) > 1

    # Build safe IN clause (account_ids are integers from DB — safe)
    ids_in = ",".join(str(i) for i in account_ids)

    branch_filter = ""
    params: dict = {"start": start_date, "end": end_date}
    if branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        params["branch_id"] = branch_id

    # Compute opening balance across all descendant accounts
    opening_query = f"""
        SELECT COALESCE(SUM(jl.debit), 0) as total_debit,
               COALESCE(SUM(jl.credit), 0) as total_credit
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE jl.account_id IN ({ids_in})
        AND je.entry_date < :start
        AND je.status = 'posted'
        {branch_filter}
    """
    opening_row = db.execute(text(opening_query), params).fetchone()
    opening_debit = Decimal(str(opening_row.total_debit)) if opening_row else 0
    opening_credit = Decimal(str(opening_row.total_credit)) if opening_row else 0
    if acct_type in ('asset', 'expense'):
        opening_balance = opening_debit - opening_credit
    else:
        opening_balance = opening_credit - opening_debit

    # Fetch journal lines across all descendant accounts
    query = f"""
        SELECT 
            je.entry_date,
            je.entry_number,
            je.description,
            je.reference,
            jl.debit,
            jl.credit,
            jl.description as line_description,
            jl.account_id
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE jl.account_id IN ({ids_in})
        AND je.entry_date BETWEEN :start AND :end
        AND je.status = 'posted'
        {branch_filter}
        ORDER BY je.entry_date ASC, je.id ASC, jl.id ASC
    """
    
    result = db.execute(text(query), params).fetchall()
    
    running_balance = opening_balance
    entries = []
    for row in result:
        debit = Decimal(str(row.debit))
        credit = Decimal(str(row.credit))
        if acct_type in ('asset', 'expense'):
            running_balance += debit - credit
        else:
            running_balance += credit - debit
        entries.append({
            "entry_date": str(row.entry_date),
            "entry_number": row.entry_number,
            "description": row.line_description or row.description,
            "reference": row.reference,
            "debit": debit,
            "credit": credit,
            "running_balance": round(running_balance, 2),
            "account_name": account_map.get(row.account_id, "") if is_aggregated else None,
        })
    
    return {
        "account_id": account_id,
        "period": {"start": start_date, "end": end_date},
        "opening_balance": round(opening_balance, 2),
        "entries": entries,
        "closing_balance": round(running_balance, 2),
        "is_aggregated": is_aggregated,
        "child_accounts_count": len(account_ids) - 1,
    }

@router.get("/accounting/general-ledger", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def get_general_ledger(
    account_id: int = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب دفتر الأستاذ العام - حركات حساب محدد مع كل حساباته الفرعية"""
    if not account_id:
        raise HTTPException(status_code=400, detail="يجب تحديد الحساب")
    
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1, month=1)
        if not end_date:
            end_date = date.today()
        return _get_general_ledger_data(db, account_id, start_date, end_date, branch_id)
    finally:
        db.close()


# ==================== ACC-004: Period Comparison Reports ====================

@router.get("/accounting/profit-loss/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def compare_profit_loss(
    periods: str = "2025-01-01:2025-12-31,2024-01-01:2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة قوائم الدخل بين فترات متعددة
    periods: comma-separated pairs start:end  e.g. 2025-01-01:2025-12-31,2024-01-01:2024-12-31
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(status_code=400, detail="يجب تحديد فترتين على الأقل للمقارنة")

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""

        # Fetch all revenue/expense accounts once
        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts WHERE account_type IN ('revenue', 'expense')
            ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for p in parsed:
            params = {"start": p["start"], "end": p["end"]}
            if branch_id:
                params["branch_id"] = branch_id

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(CASE
                        WHEN a.account_type = 'expense' THEN jl.debit - jl.credit
                        WHEN a.account_type = 'revenue' THEN jl.credit - jl.debit
                        ELSE 0
                    END), 0) as balance
                FROM accounts a
                LEFT JOIN journal_lines jl ON a.id = jl.account_id
                LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type IN ('revenue', 'expense')
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: Decimal(str(r.balance)) for r in balances}

            accounts_with_bal = []
            total_rev = 0
            total_exp = 0
            for a in account_list:
                bal = bal_map.get(a["id"], 0)
                accounts_with_bal.append({**a, "balance": bal})
                if a["account_type"] == "revenue":
                    total_rev += bal
                elif a["account_type"] == "expense":
                    total_exp += bal

            period_results.append({
                "period": {"start": str(p["start"]), "end": str(p["end"]), "label": p.get("label", "")},
                "accounts": accounts_with_bal,
                "total_revenue": total_rev,
                "total_expense": total_exp,
                "net_income": total_rev - total_exp,
            })

        # Build flat comparison table
        comparison = _build_comparison_table(account_list, period_results, "revenue_expense")

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_revenue": pr["total_revenue"],
                "total_expense": pr["total_expense"],
                "net_income": pr["net_income"],
            } for pr in period_results],
            "comparison": comparison,
        }
    finally:
        db.close()


@router.get("/accounting/balance-sheet/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def compare_balance_sheet(
    periods: str = "2025-12-31,2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة الميزانية العمومية بين تواريخ متعددة
    periods: comma-separated dates  e.g. 2025-12-31,2024-12-31
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        dates = [d.strip() for d in periods.split(",") if d.strip()]
        if len(dates) < 2:
            raise HTTPException(status_code=400, detail="يجب تحديد تاريخين على الأقل")

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""

        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts WHERE account_type IN ('asset', 'liability', 'equity')
            ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for d in dates:
            params = {"end": d}
            if branch_id:
                params["branch_id"] = branch_id

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(CASE
                        WHEN a.account_type IN ('asset', 'expense') THEN jl.debit - jl.credit
                        ELSE jl.credit - jl.debit
                    END), 0) as balance
                FROM accounts a
                LEFT JOIN journal_lines jl ON a.id = jl.account_id
                LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date <= :end
                    AND je.status = 'posted' {branch_filter}
                WHERE a.account_type IN ('asset', 'liability', 'equity')
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: Decimal(str(r.balance)) for r in balances}

            accounts_with_bal = []
            total_assets = 0
            total_liab = 0
            total_equity = 0
            for a in account_list:
                bal = bal_map.get(a["id"], 0)
                accounts_with_bal.append({**a, "balance": bal})
                if a["account_type"] == "asset":
                    total_assets += bal
                elif a["account_type"] == "liability":
                    total_liab += bal
                elif a["account_type"] == "equity":
                    total_equity += bal

            period_results.append({
                "period": {"date": d, "label": d},
                "accounts": accounts_with_bal,
                "total_assets": total_assets,
                "total_liabilities": total_liab,
                "total_equity": total_equity,
            })

        comparison = _build_comparison_table(account_list, period_results, "balance_sheet")

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_assets": pr["total_assets"],
                "total_liabilities": pr["total_liabilities"],
                "total_equity": pr["total_equity"],
            } for pr in period_results],
            "comparison": comparison,
        }
    finally:
        db.close()


# ==================== Export Endpoints ====================

from utils.exports import generate_pdf, generate_excel, generate_excel_with_chart, generate_chart_image, create_export_response

@router.get("/accounting/profit-loss/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def export_profit_loss(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير قائمة الدخل (PDF/Excel)"""
    branch_id = validate_branch_access(current_user, branch_id)
    
    # Parse dates
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Reuse get_profit_loss logic (call it directly or refactor)
    # For simplicity, calling the function logic essentially
    data = get_profit_loss(start_date=s_date, end_date=e_date, branch_id=branch_id, current_user=current_user)
    
    # Flatten data for export
    flat_data = []
    
    def flatten(nodes, indent=0):
        for node in nodes:
            flat_data.append({
                "Account Number": node["account_number"],
                "Account Name": f"{'  ' * indent}{node['name']}",
                "Balance": f"{Decimal(str(node['balance'])):,.2f}",
                "Type": node["account_type"]
            })
            if node.get("children"):
                flatten(node["children"], indent + 1)
                
    flatten(data["data"])
    
    # Add Total Row
    flat_data.append({
        "Account Number": "",
        "Account Name": "Net Income / صافي الدخل",
        "Balance": f"{Decimal(str(data['total'])):,.2f}",
        "Type": ""
    })
    
    if format == "excel":
        buffer = generate_excel(flat_data, ["Account Number", "Account Name", "Balance"])
        return create_export_response(buffer, f"profit_loss_{s_date}_{e_date}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        # Prepare PDF data (List of Lists)
        pdf_data = [["Account #", "Account Name", "Balance"]]
        for row in flat_data:
            pdf_data.append([row["Account Number"], row["Account Name"], row["Balance"]])
            
        buffer = generate_pdf(pdf_data, f"Profit & Loss ({s_date} to {e_date})")
        return create_export_response(buffer, f"profit_loss_{s_date}_{e_date}.pdf", "application/pdf")

@router.get("/accounting/balance-sheet/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def export_balance_sheet(
    format: str = "pdf",
    as_of_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير الميزانية العمومية (PDF/Excel)"""
    branch_id = validate_branch_access(current_user, branch_id)
    
    try:
        target_date = datetime.strptime(as_of_date, "%Y-%m-%d").date() if as_of_date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
    data = get_balance_sheet(as_of_date=target_date, branch_id=branch_id, current_user=current_user)
    
    flat_data = []
    def flatten(nodes, indent=0):
        for node in nodes:
            flat_data.append({
                "Account Number": node.get("account_number", ""),
                "Account Name": f"{'  ' * indent}{node['name']}",
                "Balance": f"{Decimal(str(node['balance'])):,.2f}",
                "Type": node["account_type"]
            })
            if node.get("children"):
                flatten(node["children"], indent + 1)
    
    flatten(data["data"])
    
    # Add Totals? The hierarchical view already sums up, but get_balance_sheet 
    # returns structure where roots Sum up to Total Assets (Left side) = Liabilities + Equity (Right Side)
    # Ideally logic should separate Assets vs Liab/Equity
    
    if format == "excel":
        buffer = generate_excel(flat_data, ["Account Number", "Account Name", "Balance", "Type"])
        return create_export_response(buffer, f"balance_sheet_{target_date}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        pdf_data = [["Account #", "Account Name", "Balance", "Type"]]
        for row in flat_data:
            pdf_data.append([row["Account Number"], row["Account Name"], row["Balance"], row["Type"]])
            
        buffer = generate_pdf(pdf_data, f"Balance Sheet (As of {target_date})")
        return create_export_response(buffer, f"balance_sheet_{target_date}.pdf", "application/pdf")


@router.get("/accounting/trial-balance/compare", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def compare_trial_balance(
    periods: str = "2025-01-01:2025-12-31,2024-01-01:2024-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """مقارنة ميزان المراجعة بين فترات متعددة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(status_code=400, detail="يجب تحديد فترتين على الأقل")

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""

        all_accounts = db.execute(text("""
            SELECT id, account_number, name, name_en, account_type, parent_id
            FROM accounts ORDER BY account_number
        """)).fetchall()
        account_list = [dict(r._mapping) for r in all_accounts]

        period_results = []
        for p in parsed:
            params = {"start": p["start"], "end": p["end"]}
            if branch_id:
                params["branch_id"] = branch_id

            balances = db.execute(text(f"""
                SELECT a.id,
                    COALESCE(SUM(jl.debit), 0) as total_debit,
                    COALESCE(SUM(jl.credit), 0) as total_credit
                FROM accounts a
                LEFT JOIN journal_lines jl ON a.id = jl.account_id
                LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
                    AND je.entry_date BETWEEN :start AND :end
                    AND je.status = 'posted' {branch_filter}
                GROUP BY a.id
            """), params).fetchall()
            bal_map = {r.id: {"debit": Decimal(str(r.total_debit)), "credit": Decimal(str(r.total_credit))} for r in balances}

            accounts_with_bal = []
            sum_debit = 0
            sum_credit = 0
            for a in account_list:
                b = bal_map.get(a["id"], {"debit": 0, "credit": 0})
                accounts_with_bal.append({**a, "debit": b["debit"], "credit": b["credit"]})
                sum_debit += b["debit"]
                sum_credit += b["credit"]

            period_results.append({
                "period": {"start": str(p["start"]), "end": str(p["end"]), "label": p.get("label", "")},
                "accounts": accounts_with_bal,
                "total_debit": sum_debit,
                "total_credit": sum_credit,
            })

        # Build comparison rows
        rows = []
        for a in account_list:
            period_values = []
            has_data = False
            for pr in period_results:
                acc = next((x for x in pr["accounts"] if x["id"] == a["id"]), None)
                if acc and (acc.get("debit", 0) != 0 or acc.get("credit", 0) != 0):
                    has_data = True
                period_values.append({
                    "debit": acc["debit"] if acc else 0,
                    "credit": acc["credit"] if acc else 0,
                })
            if has_data:
                rows.append({
                    "account_id": a["id"],
                    "account_number": a["account_number"],
                    "name": a["name"],
                    "name_en": a.get("name_en"),
                    "account_type": a["account_type"],
                    "periods": period_values,
                })

        return {
            "periods": [pr["period"] for pr in period_results],
            "summary": [{
                "period": pr["period"],
                "total_debit": pr["total_debit"],
                "total_credit": pr["total_credit"],
            } for pr in period_results],
            "comparison": rows,
        }
    finally:
        db.close()


def _parse_periods(periods_str: str):
    """Parse 'start:end,start:end' or 'start:end' strings into list of dicts"""
    result = []
    for part in periods_str.split(","):
        part = part.strip()
        if ":" in part:
            s, e = part.split(":", 1)
            result.append({"start": s.strip(), "end": e.strip()})
        else:
            # Single date: treat as full year
            result.append({"start": f"{part.strip()[:4]}-01-01", "end": part.strip()})
    return result


def _build_comparison_table(account_list, period_results, mode):
    """Build a flat comparison table with all periods side by side"""
    rows = []
    for a in account_list:
        period_values = []
        has_data = False
        for pr in period_results:
            acc = next((x for x in pr["accounts"] if x["id"] == a["id"]), None)
            bal = acc["balance"] if acc else 0
            if bal != 0:
                has_data = True
            period_values.append(bal)
        if has_data:
            # Calculate change between first two periods
            change = period_values[0] - period_values[1] if len(period_values) >= 2 else 0
            change_pct = (change / abs(period_values[1]) * 100) if len(period_values) >= 2 and period_values[1] != 0 else 0

            rows.append({
                "account_id": a["id"],
                "account_number": a["account_number"],
                "name": a["name"],
                "name_en": a.get("name_en"),
                "account_type": a["account_type"],
                "periods": period_values,
                "change": change,
                "change_pct": round(change_pct, 2),
            })
    return rows

# ═══════════════════════════════════════════════════════════
# RPT-101/102: Export Endpoints for All Reports (PDF/Excel)
# ═══════════════════════════════════════════════════════════

@router.get("/accounting/trial-balance/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def export_trial_balance(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير ميزان المراجعة (PDF/Excel)"""
    branch_id = validate_branch_access(current_user, branch_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    data = get_trial_balance(start_date=str(s), end_date=str(e), branch_id=branch_id, current_user=current_user)

    flat = []
    for r in data["data"]:
        flat.append({
            "رقم الحساب": r["account_number"], "اسم الحساب": r["name"],
            "رصيد افتتاحي مدين": f"{r['opening_debit']:,.2f}", "رصيد افتتاحي دائن": f"{r['opening_credit']:,.2f}",
            "حركة مدين": f"{r['period_debit']:,.2f}", "حركة دائن": f"{r['period_credit']:,.2f}",
            "رصيد ختامي مدين": f"{r['closing_debit']:,.2f}", "رصيد ختامي دائن": f"{r['closing_credit']:,.2f}",
        })
    cols = ["رقم الحساب", "اسم الحساب", "رصيد افتتاحي مدين", "رصيد افتتاحي دائن", "حركة مدين", "حركة دائن", "رصيد ختامي مدين", "رصيد ختامي دائن"]
    fname = f"trial_balance_{s}_{e}"

    if format == "excel":
        buf = generate_excel(flat, cols, "Trial Balance")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r.get(c, "") for c in cols] for r in flat], f"Trial Balance ({s} → {e})", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


@router.get("/accounting/general-ledger/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def export_general_ledger(
    account_id: int,
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير دفتر الأستاذ لحساب معين"""
    branch_id = validate_branch_access(current_user, branch_id)
    data = get_general_ledger(account_id=account_id, start_date=start_date, end_date=end_date, branch_id=branch_id, current_user=current_user)
    flat = []
    balance = Decimal("0")
    for e_row in data["entries"]:
        balance += e_row["debit"] - e_row["credit"]
        flat.append({
            "التاريخ": e_row["entry_date"], "رقم القيد": e_row["entry_number"],
            "البيان": e_row["description"] or "", "المرجع": e_row["reference"] or "",
            "مدين": f"{e_row['debit']:,.2f}", "دائن": f"{e_row['credit']:,.2f}",
            "الرصيد": f"{balance:,.2f}",
        })
    cols = ["التاريخ", "رقم القيد", "البيان", "المرجع", "مدين", "دائن", "الرصيد"]
    fname = f"general_ledger_{account_id}"

    if format == "excel":
        buf = generate_excel(flat, cols, "General Ledger")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r.get(c, "") for c in cols] for r in flat], f"General Ledger — Account {account_id}", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


@router.get("/accounting/cashflow/export", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def export_cashflow(
    format: str = "pdf",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تصدير تقرير التدفقات النقدية"""
    branch_id = validate_branch_access(current_user, branch_id)
    data = get_cashflow_report(start_date=start_date, end_date=end_date, branch_id=branch_id, current_user=current_user)
    flat = []
    for item in data.get("inflows", []):
        flat.append({"Section": "تدفقات داخلة", "Item": item.get("category", ""), "Amount": f"{Decimal(str(item.get('amount', 0))):,.2f}"})
    flat.append({"Section": "تدفقات داخلة", "Item": "المجموع", "Amount": f"{Decimal(str(data.get('total_inflow', 0))):,.2f}"})
    for item in data.get("outflows", []):
        flat.append({"Section": "تدفقات خارجة", "Item": item.get("category", ""), "Amount": f"{Decimal(str(item.get('amount', 0))):,.2f}"})
    flat.append({"Section": "تدفقات خارجة", "Item": "المجموع", "Amount": f"{Decimal(str(data.get('total_outflow', 0))):,.2f}"})
    flat.append({"Section": "", "Item": "صافي التدفقات النقدية", "Amount": f"{Decimal(str(data.get('net_cash_flow', 0))):,.2f}"})
    cols = ["Section", "Item", "Amount"]
    fname = f"cashflow_{start_date}_{end_date}"
    if format == "excel":
        buf = generate_excel(flat, cols, "Cash Flow")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    buf = generate_pdf([[r[c] for c in cols] for r in flat], "Cash Flow Statement", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


@router.get("/sales/aging/export", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def export_aging(format: str = "pdf", current_user: dict = Depends(get_current_user)):
    """تصدير تقرير أعمار الديون"""
    data = get_aging_report(current_user=current_user)
    flat = data if isinstance(data, list) else data.get("data", [])
    cols = list(flat[0].keys()) if flat else ["customer", "0-30", "31-60", "61-90", "90+", "total"]
    fname = "aging_report"
    if format == "excel":
        buf = generate_excel(flat, cols, "Aging")
        return create_export_response(buf, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    pdf_rows = [[str(r.get(c, "")) for c in cols] for r in flat]
    buf = generate_pdf(pdf_rows, "Accounts Receivable Aging", cols)
    return create_export_response(buf, f"{fname}.pdf", "application/pdf")


# ═══════════════════════════════════════════════════════════
# RPT-103: Advanced Financial Reports
# ═══════════════════════════════════════════════════════════

@router.get("/accounting/horizontal-analysis", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def horizontal_analysis(
    periods: str = "2026-01-01:2026-12-31,2025-01-01:2025-12-31",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحليل أفقي — اتجاه الأرقام عبر الفترات"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        parsed = _parse_periods(periods)
        if len(parsed) < 2:
            raise HTTPException(status_code=400, detail="يجب فترتين على الأقل")

        branch_filter = "AND je.branch_id = :branch_id" if branch_id else ""

        all_accounts = db.execute(text("SELECT id, account_number, name, name_en, account_type FROM accounts ORDER BY account_number")).fetchall()

        results = []
        for acct in all_accounts:
            a = acct._mapping
            period_balances = []
            for p in parsed:
                params = {"acct": a["id"], "start": p["start"], "end": p["end"]}
                if branch_id:
                    params["branch_id"] = branch_id
                bal = db.execute(text(f"""
                    SELECT COALESCE(SUM(
                        CASE WHEN a.account_type IN ('liability', 'equity', 'revenue')
                             THEN jl.credit - jl.debit
                             ELSE jl.debit - jl.credit
                        END
                    ), 0) as net
                    FROM journal_lines jl
                    JOIN journal_entries je ON jl.journal_entry_id = je.id
                    JOIN accounts a ON jl.account_id = a.id
                    WHERE jl.account_id = :acct AND je.entry_date BETWEEN :start AND :end
                      AND je.status = 'posted' {branch_filter}
                """), params).scalar()
                period_balances.append(Decimal(str(bal)))

            if not any(abs(b) > 0.01 for b in period_balances):
                continue

            changes = []
            for i in range(len(period_balances) - 1):
                curr, prev = period_balances[i], period_balances[i + 1]
                abs_change = curr - prev
                pct_change = (abs_change / abs(prev) * 100) if prev != 0 else None
                changes.append({"absolute": round(abs_change, 2), "percentage": round(pct_change, 2) if pct_change is not None else None})

            results.append({
                "account_number": a["account_number"], "name": a["name"],
                "account_type": a["account_type"], "periods": period_balances, "changes": changes,
                "trend": "increasing" if all(period_balances[i] >= period_balances[i+1] for i in range(len(period_balances)-1)) else
                         "decreasing" if all(period_balances[i] <= period_balances[i+1] for i in range(len(period_balances)-1)) else "mixed"
            })

        return {"report_name": "التحليل الأفقي", "periods": [f"{p['start']}→{p['end']}" for p in parsed], "data": results}
    finally:
        db.close()


@router.get("/accounting/financial-ratios", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def financial_ratios(
    as_of_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحليل النسب المالية — سيولة / ربحية / ملاءة"""
    branch_id = validate_branch_access(current_user, branch_id)
    d = datetime.strptime(as_of_date, "%Y-%m-%d").date() if as_of_date else date.today()
    start_of_year = d.replace(month=1, day=1)
    db = get_db_connection(current_user.company_id)
    try:
        def acct_sum(type_like, start=None, end=None):
            params = {}
            date_filter = ""
            if start and end:
                date_filter = "AND je.entry_date BETWEEN :start AND :end"
                params["start"] = start
                params["end"] = end
            br = "AND je.branch_id = :branch_id" if branch_id else ""
            if branch_id:
                params["branch_id"] = branch_id
            return Decimal(str(db.execute(text(f"""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_type = :atype AND je.status = 'posted' {date_filter} {br}
            """), {**params, "atype": type_like}).scalar()))

        def code_sum(like_pattern, start=None, end=None):
            params = {"p": like_pattern}
            df = ""
            if start and end:
                df = "AND je.entry_date BETWEEN :start AND :end"
                params["start"] = start
                params["end"] = end
            br = "AND je.branch_id = :branch_id" if branch_id else ""
            if branch_id:
                params["branch_id"] = branch_id
            return Decimal(str(db.execute(text(f"""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                JOIN accounts a ON jl.account_id = a.id
                WHERE a.account_number LIKE :p AND je.status='posted' {df} {br}
            """), params).scalar()))

        # Balance Sheet items (cumulative to date)
        total_assets = acct_sum("asset", None, None)
        current_assets = code_sum("11%")
        fixed_assets = code_sum("12%")
        total_liabilities = abs(acct_sum("liability"))
        current_liabilities = abs(code_sum("21%"))
        equity = abs(acct_sum("equity"))

        # P&L items (YTD)
        revenue = abs(acct_sum("revenue", start_of_year, d))
        expenses = acct_sum("expense", start_of_year, d)
        net_income = revenue - expenses
        cogs = code_sum("51%", start_of_year, d)
        gross_profit = revenue - cogs

        # Inventory
        inventory = code_sum("1103%")  # net balance
        ar = code_sum("1102%")
        ap = abs(code_sum("2101%"))

        # Ratios
        ratios = {
            "liquidity": {
                "current_ratio": round(current_assets / current_liabilities, 2) if current_liabilities else None,
                "quick_ratio": round((current_assets - abs(inventory)) / current_liabilities, 2) if current_liabilities else None,
                "cash_ratio": round(code_sum("1101%") / current_liabilities, 2) if current_liabilities else None,
            },
            "profitability": {
                "gross_profit_margin": round(gross_profit / revenue * 100, 2) if revenue else None,
                "net_profit_margin": round(net_income / revenue * 100, 2) if revenue else None,
                "return_on_assets": round(net_income / total_assets * 100, 2) if total_assets else None,
                "return_on_equity": round(net_income / equity * 100, 2) if equity else None,
            },
            "solvency": {
                "debt_to_equity": round(total_liabilities / equity, 2) if equity else None,
                "debt_to_assets": round(total_liabilities / total_assets, 2) if total_assets else None,
                "equity_ratio": round(equity / total_assets * 100, 2) if total_assets else None,
            },
            "activity": {
                "ar_turnover": round(revenue / ar, 2) if ar else None,
                "ar_days": round(365 / (revenue / ar), 1) if ar and revenue else None,
                "ap_turnover": round(cogs / ap, 2) if ap else None,
                "ap_days": round(365 / (cogs / ap), 1) if ap and cogs else None,
                "inventory_turnover": round(cogs / abs(inventory), 2) if inventory else None,
                "inventory_days": round(365 / (cogs / abs(inventory)), 1) if inventory and cogs else None,
            }
        }

        return {
            "report_name": "تحليل النسب المالية",
            "as_of_date": str(d),
            "summary": {
                "total_assets": round(total_assets, 2), "current_assets": round(current_assets, 2),
                "total_liabilities": round(total_liabilities, 2), "equity": round(equity, 2),
                "revenue_ytd": round(revenue, 2), "net_income_ytd": round(net_income, 2),
            },
            "ratios": ratios,
        }
    finally:
        db.close()


@router.get("/accounting/cost-center-report", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def cost_center_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير مراكز التكلفة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        params = {"start": s, "end": e}
        br = "AND je.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        rows = db.execute(text(f"""
            SELECT cc.id, cc.center_name, cc.center_code,
                   COALESCE(SUM(jl.debit), 0) as total_debit,
                   COALESCE(SUM(jl.credit), 0) as total_credit,
                   COALESCE(SUM(jl.debit - jl.credit), 0) as net
            FROM cost_centers cc
            LEFT JOIN journal_lines jl ON cc.id = jl.cost_center_id
            LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
                AND je.entry_date BETWEEN :start AND :end AND je.status = 'posted' {br}
            GROUP BY cc.id, cc.center_name, cc.center_code
            ORDER BY net DESC
        """), params).fetchall()

        return {
            "report_name": "تقرير مراكز التكلفة",
            "period": {"start": str(s), "end": str(e)},
            "data": [dict(r._mapping) for r in rows],
            "total_net": sum(Decimal(str(r.net)) for r in rows),
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-104: Inventory Reports
# ═══════════════════════════════════════════════════════════

@router.get("/inventory/valuation", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))])
def inventory_valuation_report(
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقييم المخزون بالتكلفة المتوسطة"""
    db = get_db_connection(current_user.company_id)
    try:
        wh_filter = "AND i.warehouse_id = :wh" if warehouse_id else ""
        params = {}
        if warehouse_id:
            params["wh"] = warehouse_id

        rows = db.execute(text(f"""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as total_qty,
                   COALESCE(SUM(i.quantity), 0) * COALESCE(p.cost_price, 0) as total_value,
                   w.warehouse_name
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id {wh_filter}
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price, w.warehouse_name
            HAVING COALESCE(SUM(i.quantity), 0) != 0
            ORDER BY total_value DESC
        """), params).fetchall()

        items = []
        grand_total = Decimal("0")
        for r in rows:
            m = r._mapping
            val = Decimal(str(m["total_value"] or 0))
            grand_total += val
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "warehouse": m["warehouse_name"], "quantity": float(m["total_qty"]),
                "cost_price": Decimal(str(m["cost_price"] or 0)),
                "total_value": round(val, 2),
            })

        return {"report_name": "تقييم المخزون", "items": items, "grand_total": round(grand_total, 2)}
    finally:
        db.close()


@router.get("/inventory/turnover", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))])
def inventory_turnover_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير دوران المخزون"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    days_in_period = max((e - s).days, 1)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as current_qty,
                   COALESCE(sold.qty, 0) as sold_qty
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN (
                SELECT il.product_id, SUM(ABS(il.quantity)) as qty
                FROM invoice_lines il
                JOIN invoices inv ON il.invoice_id = inv.id
                WHERE inv.invoice_type = 'sales' AND inv.status != 'cancelled'
                  AND inv.invoice_date BETWEEN :start AND :end
                GROUP BY il.product_id
            ) sold ON sold.product_id = p.id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price, sold.qty
            HAVING COALESCE(SUM(i.quantity), 0) > 0 OR COALESCE(sold.qty, 0) > 0
            ORDER BY sold.qty DESC NULLS LAST
        """), {"start": s, "end": e}).fetchall()

        items = []
        for r in rows:
            m = r._mapping
            avg_inv = float(m["current_qty"] or 0)
            sold = float(m["sold_qty"] or 0)
            cogs_val = sold * Decimal(str(m["cost_price"] or 0))
            turnover = cogs_val / (avg_inv * Decimal(str(m["cost_price"] or 1))) if avg_inv > 0 and m["cost_price"] else 0
            days_on_hand = round(days_in_period / turnover, 1) if turnover > 0 else None

            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "current_stock": avg_inv, "sold_qty": sold,
                "cogs_value": round(cogs_val, 2),
                "turnover_ratio": round(turnover, 2),
                "days_on_hand": days_on_hand,
            })

        return {"report_name": "دوران المخزون", "period": {"start": str(s), "end": str(e)}, "items": items}
    finally:
        db.close()


@router.get("/inventory/dead-stock", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))])
def dead_stock_report(
    days_threshold: int = 90,
    current_user: dict = Depends(get_current_user)
):
    """المخزون الراكد — منتجات بدون حركة لفترة محددة"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   COALESCE(SUM(i.quantity), 0) as stock_qty,
                   COALESCE(SUM(i.quantity), 0) * COALESCE(p.cost_price, 0) as stock_value,
                   MAX(it.created_at) as last_movement
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN inventory_transactions it ON p.id = it.product_id
            WHERE p.product_type != 'service'
            GROUP BY p.id, p.sku, p.product_name, p.cost_price
            HAVING COALESCE(SUM(i.quantity), 0) > 0
               AND (MAX(it.created_at) IS NULL OR MAX(it.created_at) < NOW() - :days * INTERVAL '1 day')
            ORDER BY stock_value DESC
        """), {"days": days_threshold}).fetchall()

        items = []
        total_val = Decimal("0")
        for r in rows:
            m = r._mapping
            val = Decimal(str(m["stock_value"] or 0))
            total_val += val
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "stock_qty": float(m["stock_qty"]),
                "cost_price": Decimal(str(m["cost_price"] or 0)),
                "stock_value": round(val, 2),
                "last_movement": str(m["last_movement"]) if m["last_movement"] else "لا توجد حركة",
            })

        return {
            "report_name": f"المخزون الراكد (>{days_threshold} يوم)",
            "days_threshold": days_threshold,
            "items": items,
            "total_dead_stock_value": round(total_val, 2),
            "count": len(items),
        }
    finally:
        db.close()


@router.get("/inventory/cogs", dependencies=[Depends(require_permission(["stock.view", "reports.view"]))])
def cogs_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة البضاعة المباعة"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        rows = db.execute(text("""
            SELECT p.id, p.sku, p.product_name, p.cost_price,
                   SUM(ABS(il.quantity)) as sold_qty,
                   SUM(ABS(il.quantity) * COALESCE(il.unit_cost, p.cost_price, 0)) as cogs_total,
                   SUM(il.quantity * il.unit_price) as revenue_total
            FROM invoice_lines il
            JOIN invoices inv ON il.invoice_id = inv.id
            JOIN products p ON il.product_id = p.id
            WHERE inv.invoice_type = 'sales' AND inv.status != 'cancelled'
              AND inv.invoice_date BETWEEN :start AND :end
            GROUP BY p.id, p.sku, p.product_name, p.cost_price
            ORDER BY cogs_total DESC
        """), {"start": s, "end": e}).fetchall()

        items = []
        total_cogs = Decimal("0")
        total_rev = Decimal("0")
        for r in rows:
            m = r._mapping
            cogs = Decimal(str(m["cogs_total"] or 0))
            rev = Decimal(str(m["revenue_total"] or 0))
            gross = rev - cogs
            margin = (gross / rev * 100) if rev > 0 else 0
            total_cogs += cogs
            total_rev += rev
            items.append({
                "product_id": m["id"], "sku": m["sku"], "product_name": m["product_name"],
                "sold_qty": float(m["sold_qty"] or 0),
                "unit_cost": Decimal(str(m["cost_price"] or 0)),
                "cogs": round(cogs, 2), "revenue": round(rev, 2),
                "gross_profit": round(gross, 2), "margin_pct": round(margin, 2),
            })

        return {
            "report_name": "تكلفة البضاعة المباعة",
            "period": {"start": str(s), "end": str(e)},
            "items": items,
            "totals": {"cogs": round(total_cogs, 2), "revenue": round(total_rev, 2),
                       "gross_profit": round(total_rev - total_cogs, 2)},
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales & Purchases Reports
# ═══════════════════════════════════════════════════════════

@router.get("/sales/by-cashier", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def sales_by_cashier(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المبيعات حسب البائع/الكاشير"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    try:
        rows = db.execute(text("""
            WITH all_sales AS (
                SELECT created_by, total AS sale_total, paid_amount, invoice_date::date AS sale_date
                FROM invoices
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                  AND invoice_date BETWEEN :start AND :end

                UNION ALL

                SELECT created_by, total_amount AS sale_total, paid_amount, order_date::date AS sale_date
                FROM pos_orders
                WHERE status != 'cancelled'
                  AND order_date::date BETWEEN :start AND :end
            )
            SELECT u.id, u.full_name,
                   COUNT(*) as invoice_count,
                   COALESCE(SUM(s.sale_total), 0) as total_sales,
                   COALESCE(SUM(s.paid_amount), 0) as total_collected,
                   COALESCE(AVG(s.sale_total), 0) as avg_invoice
            FROM all_sales s
            JOIN company_users u ON s.created_by = u.id
            GROUP BY u.id, u.full_name
            ORDER BY total_sales DESC
        """), {"start": s, "end": e}).fetchall()

        return {
            "report_name": "المبيعات حسب البائع",
            "period": {"start": str(s), "end": str(e)},
            "data": [{
                "user_id": r.id, "name": r.full_name,
                "invoice_count": r.invoice_count,
                "total_sales": round(Decimal(str(r.total_sales)), 2),
                "total_collected": round(Decimal(str(r.total_collected)), 2),
                "avg_invoice": round(Decimal(str(r.avg_invoice)), 2),
            } for r in rows],
        }
    finally:
        db.close()


@router.get("/sales/target-vs-actual", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def sales_target_vs_actual(
    year: int = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المبيعات المستهدفة vs الفعلية (شهري)"""
    db = get_db_connection(current_user.company_id)
    yr = year or date.today().year
    try:
        # Get monthly targets if exist
        targets = {}
        try:
            tgt_rows = db.execute(text(
                "SELECT month_number, target_amount FROM sales_targets WHERE year = :y"
            ), {"y": yr}).fetchall()
            for t in tgt_rows:
                targets[t.month_number] = Decimal(str(t.target_amount))
        except Exception:
            pass  # Table may not exist

        # Actual monthly sales (invoices + POS)
        actuals = db.execute(text("""
            SELECT EXTRACT(MONTH FROM sale_date)::int as month,
                   COALESCE(SUM(total_amount), 0) as actual
            FROM (
                SELECT invoice_date::date AS sale_date, total AS total_amount
                FROM invoices
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                  AND EXTRACT(YEAR FROM invoice_date) = :y

                UNION ALL

                SELECT order_date::date AS sale_date, total_amount
                FROM pos_orders
                WHERE status != 'cancelled'
                  AND EXTRACT(YEAR FROM order_date) = :y
            ) t
            GROUP BY month
            ORDER BY month
        """), {"y": yr}).fetchall()

        actual_map = {r.month: Decimal(str(r.actual)) for r in actuals}

        months = []
        for m in range(1, 13):
            target = targets.get(m, 0)
            actual = actual_map.get(m, 0)
            variance = actual - target
            pct = (actual / target * 100) if target > 0 else None
            months.append({
                "month": m, "target": round(target, 2), "actual": round(actual, 2),
                "variance": round(variance, 2), "achievement_pct": round(pct, 2) if pct is not None else None,
            })

        return {"report_name": "المبيعات المستهدفة vs الفعلية", "year": yr, "months": months}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Custom Report Builder
# ═══════════════════════════════════════════════════════════

class CustomReportConfig(BaseModel):
    source: Optional[str] = None  # 'sales', 'purchases', 'inventory', 'projects'
    table_name: Optional[str] = None  # alias for source (frontend compatibility)
    columns: List[str]
    filters: Optional[Dict[str, Any]] = {}
    sort_by: Optional[str] = None
    sort_order: Optional[str] = "desc"

    model_config = {"extra": "ignore"}

    @property
    def resolved_source(self) -> str:
        """Return source, falling back to table_name"""
        return self.source or self.table_name or "sales"

class CustomReportCreate(BaseModel):
    report_name: str
    description: Optional[str] = None
    config: CustomReportConfig

@router.post("/custom/preview", dependencies=[Depends(require_permission("reports.view"))])
async def preview_custom_report(
    config: CustomReportConfig,
    current_user: dict = Depends(get_current_user)
):
    """معاينة تقرير مخصص بناءً على التكوين"""
    db = get_db_connection(current_user.company_id)
    try:
        data = _generate_custom_report_data(db, config, current_user.id)
        return data
    except Exception as e:
        logger.error(f"Error previewing report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.post("/custom", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("reports.create"))])
async def create_custom_report(
    report: CustomReportCreate,
    current_user: dict = Depends(get_current_user)
):
    """حفظ تقرير مخصص"""
    db = get_db_connection(current_user.company_id)
    try:
        report_id = db.execute(text("""
            INSERT INTO custom_reports (
                report_name, description, config, created_by
            ) VALUES (:name, :desc, :config, :uid)
            RETURNING id
        """), {
            "name": report.report_name,
            "desc": report.description,
            "config": report.config.json(),
            "uid": current_user.id
        }).scalar()
        
        db.commit()
        return {"success": True, "id": report_id, "message": "تم حفظ التقرير بنجاح"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/custom", dependencies=[Depends(require_permission("reports.view"))])
async def list_custom_reports(current_user: dict = Depends(get_current_user)):
    """جلب قائمة التقارير المخصصة المحفوظة"""
    db = get_db_connection(current_user.company_id)
    try:
        reports = db.execute(text("""
            SELECT cr.*, u.full_name as created_by_name
            FROM custom_reports cr
            LEFT JOIN company_users u ON cr.created_by = u.id
            ORDER BY cr.created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in reports]
    finally:
        db.close()

@router.get("/custom/{report_id}", dependencies=[Depends(require_permission("reports.view"))])
async def get_custom_report(report_id: int, current_user: dict = Depends(get_current_user)):
    """تشغيل تقرير مخصص محفوظ"""
    db = get_db_connection(current_user.company_id)
    try:
        report = db.execute(text("SELECT * FROM custom_reports WHERE id = :id"), {"id": report_id}).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="التقرير غير موجود")
            
        config_dict = report.config if isinstance(report.config, dict) else json.loads(report.config)
        config = CustomReportConfig(**config_dict)
        
        data = _generate_custom_report_data(db, config, current_user.id)
        return {"report": dict(report._mapping), "results": data}
    except Exception as e:
        logger.error(f"Error executing saved report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.delete("/custom/{report_id}", dependencies=[Depends(require_permission("reports.delete"))])
async def delete_custom_report(report_id: int, current_user: dict = Depends(get_current_user)):
    """حذف تقرير مخصص"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM custom_reports WHERE id = :id"), {"id": report_id})
        db.commit()
        return {"success": True, "message": "تم حذف التقرير"}
    finally:
        db.close()

def _generate_custom_report_data(db, config: CustomReportConfig, user_id: int):
    """Engine to build dynamic SQL based on config"""
    
    # 1. Source Mapping
    source_map = {
        "sales": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'sales' AND i.status != 'cancelled'",
            "columns": {
                "invoice_number": "i.invoice_number",
                "date": "i.invoice_date",
                "customer": "p.name",
                "total": "i.total",
                "paid": "i.paid_amount",
                "status": "i.status",
                "branch_id": "i.branch_id"
            }
        },
        "purchases": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'purchase' AND i.status != 'cancelled'",
            "columns": {
                "invoice_number": "i.invoice_number",
                "date": "i.invoice_date",
                "supplier": "p.name",
                "total": "i.total",
                "paid": "i.paid_amount",
                "status": "i.status"
            }
        },
        "inventory": {
            "table": "products",
            "alias": "p",
            "joins": "LEFT JOIN inventory inv ON p.id = inv.product_id LEFT JOIN warehouses w ON inv.warehouse_id = w.id",
            "where": "1=1",
            "columns": {
                "sku": "p.sku",
                "product_name": "p.product_name",
                "warehouse": "w.warehouse_name",
                "quantity": "inv.quantity",
                "cost_price": "p.cost_price",
                "selling_price": "p.selling_price"
            }
        },
         "projects": {
            "table": "projects",
            "alias": "p",
            "joins": "LEFT JOIN customers c ON p.customer_id = c.id LEFT JOIN employees e ON p.manager_id = e.id",
            "where": "1=1",
            "columns": {
                "id": "p.id",
                "code": "p.project_code",
                "project_name": "p.project_name",
                "customer": "c.customer_name",
                "manager": "CONCAT(e.first_name, ' ', e.last_name)",
                "manager_id": "p.manager_id",
                "status": "p.status",
                "progress": "p.progress_percentage",
                "start_date": "p.start_date",
                "end_date": "p.end_date",
                "budget": "p.budget"
            }
        },
        "tasks": {
            "table": "tasks",
            "alias": "t",
            "joins": "LEFT JOIN projects p ON t.project_id = p.id",
            "where": "1=1",
            "columns": {
                "id": "t.id",
                "task_name": "t.task_name",
                "project_id": "t.project_id",
                "status": "t.status",
                "start_date": "t.start_date",
                "end_date": "t.end_date",
                "planned_hours": "t.planned_hours",
                "actual_hours": "t.actual_hours"
            }
        },
        "sales_invoices": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'sales' AND i.status != 'cancelled'",
            "columns": {
                "id": "i.id",
                "invoice_number": "i.invoice_number",
                "invoice_date": "i.invoice_date",
                "date": "i.invoice_date",
                "customer_id": "i.party_id",
                "customer": "p.name",
                "total_amount": "i.total",
                "total": "i.total",
                "status": "i.status"
            }
        },
        "expenses": {
            "table": "expenses",
            "alias": "ex",
            "joins": "",
            "where": "1=1",
            "columns": {
                "id": "ex.id",
                "expense_date": "ex.expense_date",
                "amount": "ex.amount",
                "category": "ex.category",
                "description": "ex.description",
                "project_id": "ex.project_id"
            }
        },
        "customers": {
            "table": "parties",
            "alias": "p",
            "joins": "",
            "where": "p.party_type = 'customer'",
            "columns": {
                "id": "p.id",
                "name": "p.name",
                "email": "p.email",
                "phone": "p.phone",
                "city": "p.city"
            }
        }
    }
    
    src = source_map.get(config.resolved_source)
    if not src:
        raise ValueError(f"Invalid Data Source: {config.resolved_source}")
        
    # 2. Build Query
    select_cols = []
    for col in config.columns:
        if col in src["columns"]:
            select_cols.append(f"{src['columns'][col]} as {col}")
    
    if not select_cols:
        select_cols = ["*"] # Fallback
        
    query = f"SELECT {', '.join(select_cols)} FROM {src['table']} {src['alias']} {src['joins']} WHERE {src['where']}"
    
    # 3. Apply Filters
    params = {}
    if config.filters:
        for key, value in config.filters.items():
            if key in src["columns"] and value:
                valid_key = key.replace(" ", "_") # Safety
                query += f" AND {src['columns'][key]} = :{valid_key}"
                params[valid_key] = value
                
            # Date Range special handling
            if key == "date_from" and "date" in src["columns"]:
                 query += f" AND {src['columns']['date']} >= :date_from"
                 params["date_from"] = value
            if key == "date_to" and "date" in src["columns"]:
                 query += f" AND {src['columns']['date']} <= :date_to"
                 params["date_to"] = value

    # 4. Sorting
    if config.sort_by and config.sort_by in src["columns"]:
        order = "DESC" if config.sort_order == "desc" else "ASC"
        query += f" ORDER BY {src['columns'][config.sort_by]} {order}"
    
    # Execute
    result = db.execute(text(query), params).fetchall()
    return [dict(r._mapping) for r in result]


# ═══════════════════════════════════════════════════════════
# RPT-103: Detailed P&L by Product/Customer/Category
# تقرير أرباح وخسائر تفصيلي
# ═══════════════════════════════════════════════════════════

@router.get("/accounting/profit-loss/detailed", dependencies=[Depends(require_permission(["accounting.view", "reports.view"]))])
def detailed_profit_loss(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = "customer",  # customer, product, category
    branch_id: Optional[int] = None,
    format: Optional[str] = None,  # excel, pdf, None=json
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير أرباح وخسائر تفصيلي — مجمَّع حسب العميل أو المنتج أو فئة المنتج.
    Detailed P&L Report — grouped by customer, product, or product category.
    Shows Revenue, COGS, Gross Profit, Gross Margin% per group.
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()

        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        params = {"start": s_date, "end": e_date}
        if branch_id:
            params["branch_id"] = branch_id

        if group_by == "product":
            group_col = "COALESCE(p.product_name, il.description, 'غير محدد')"
            group_label = "product_name"
            join_extra = "LEFT JOIN products p ON il.product_id = p.id"
        elif group_by == "category":
            group_col = "COALESCE(pc.name, 'غير مصنف')"
            group_label = "category"
            join_extra = """LEFT JOIN products p ON il.product_id = p.id
                           LEFT JOIN product_categories pc ON p.category_id = pc.id"""
        else:  # customer
            group_col = "COALESCE(pa.name, c.name, 'غير محدد')"
            group_label = "customer_name"
            join_extra = """LEFT JOIN parties pa ON i.party_id = pa.id
                           LEFT JOIN customers c ON i.party_id = c.id"""

        # Revenue from sales invoices
        revenue_query = f"""
            SELECT {group_col} as group_name,
                   SUM(il.quantity * il.unit_price - COALESCE(il.discount, 0)) as revenue,
                   SUM(il.quantity * COALESCE(p2.cost_price, 0)) as cogs,
                   COUNT(DISTINCT i.id) as invoice_count,
                   SUM(il.quantity) as total_qty
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            LEFT JOIN products p2 ON il.product_id = p2.id
            {join_extra}
            WHERE i.invoice_type = 'sales'
              AND i.status NOT IN ('cancelled', 'draft')
              AND i.invoice_date BETWEEN :start AND :end
              {branch_filter}
            GROUP BY {group_col}
            ORDER BY revenue DESC
        """

        rows = db.execute(text(revenue_query), params).fetchall()

        report_rows = []
        total_revenue = 0
        total_cogs = 0

        for r in rows:
            revenue = Decimal(str(r.revenue or 0))
            cogs = Decimal(str(r.cogs or 0))
            gross_profit = revenue - cogs
            margin = round((gross_profit / revenue * 100), 1) if revenue > 0 else 0

            total_revenue += revenue
            total_cogs += cogs

            report_rows.append({
                group_label: r.group_name or "غير محدد",
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_margin_pct": margin,
                "invoice_count": r.invoice_count or 0,
                "total_qty": float(r.total_qty or 0),
            })

        total_gp = total_revenue - total_cogs
        overall_margin = round((total_gp / total_revenue * 100), 1) if total_revenue > 0 else 0

        result = {
            "report_name": f"Detailed P&L by {group_by.title()} — أرباح وخسائر تفصيلي",
            "period": {"start": str(s_date), "end": str(e_date)},
            "group_by": group_by,
            "details": report_rows,
            "totals": {
                "total_revenue": round(total_revenue, 2),
                "total_cogs": round(total_cogs, 2),
                "total_gross_profit": round(total_gp, 2),
                "overall_gross_margin_pct": overall_margin,
            }
        }

        if format in ("excel", "pdf"):
            export_data = []
            for r in report_rows:
                export_data.append({
                    f"{'العميل' if group_by == 'customer' else 'المنتج' if group_by == 'product' else 'الفئة'} / {group_by.title()}": r[group_label],
                    "الإيرادات / Revenue": r["revenue"],
                    "تكلفة المبيعات / COGS": r["cogs"],
                    "الربح الإجمالي / Gross Profit": r["gross_profit"],
                    "هامش الربح % / Margin %": f"{r['gross_margin_pct']}%",
                    "عدد الفواتير / Invoices": r["invoice_count"],
                })
            columns = list(export_data[0].keys()) if export_data else []

            # Generate chart for top items
            chart_image = None
            try:
                top_items = report_rows[:10]
                if top_items:
                    chart_labels = [r[group_label][:20] for r in top_items]
                    chart_image = generate_chart_image(
                        "bar", chart_labels,
                        [
                            {"label": "Revenue / الإيرادات", "data": [r["revenue"] for r in top_items], "color": "#2563EB"},
                            {"label": "COGS / التكلفة", "data": [r["cogs"] for r in top_items], "color": "#DC2626"},
                            {"label": "Gross Profit / الربح", "data": [r["gross_profit"] for r in top_items], "color": "#16A34A"},
                        ],
                        title=f"Detailed P&L by {group_by.title()} — أرباح وخسائر تفصيلي"
                    )
            except Exception:
                pass

            if format == "excel":
                buffer = generate_excel_with_chart(export_data, columns, sheet_name=f"P&L by {group_by}",
                    chart_type="bar", chart_config={"title": f"P&L by {group_by}", "x_col": 0, "y_cols": [1, 2, 3]})
                return create_export_response(buffer, f"detailed_pl_{group_by}_{s_date}_{e_date}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                pdf_data = [columns] + [[str(row.get(c, '')) for c in columns] for row in export_data]
                buffer = generate_pdf(pdf_data,
                    title=f"Detailed P&L by {group_by.title()} — تقرير أرباح وخسائر تفصيلي",
                    subtitle=f"{s_date} → {e_date}",
                    chart_image=chart_image, orientation="landscape")
                return create_export_response(buffer, f"detailed_pl_{group_by}_{s_date}_{e_date}.pdf", "application/pdf")

        return result
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# RPT-105: Sales Commission Report (تقرير عمولات المبيعات)
# ═══════════════════════════════════════════════════════════

@router.get("/sales/commissions/report", dependencies=[Depends(require_permission(["sales.view", "reports.view"]))])
def sales_commission_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    salesperson_id: Optional[int] = None,
    status_filter: Optional[str] = None,  # pending, paid, all
    format: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير عمولات المبيعات مع إمكانية إنشاء قيد محاسبي عند الصرف.
    Sales Commission Report with GL integration.
    """
    db = get_db_connection(current_user.company_id)
    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(day=1, month=1)
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()

        query = """
            SELECT sc.*, 
                   COALESCE(sc.salesperson_name, cu.full_name, '') as sp_name
            FROM sales_commissions sc
            LEFT JOIN company_users cu ON sc.salesperson_id = cu.id
            WHERE sc.invoice_date BETWEEN :start AND :end
        """
        params = {"start": s_date, "end": e_date}

        if salesperson_id:
            query += " AND sc.salesperson_id = :sp_id"
            params["sp_id"] = salesperson_id
        if status_filter and status_filter != "all":
            query += " AND sc.status = :status"
            params["status"] = status_filter

        query += " ORDER BY sc.salesperson_id, sc.invoice_date"

        rows = db.execute(text(query), params).fetchall()

        # Build detailed report
        report_rows = []
        sp_summary = {}

        for r in rows:
            rm = r._mapping
            sp_id = rm.get("salesperson_id")
            sp_name = rm.get("sp_name") or rm.get("salesperson_name", "غير محدد")

            report_rows.append({
                "salesperson_id": sp_id,
                "salesperson_name": sp_name,
                "invoice_number": rm.get("invoice_number", ""),
                "invoice_date": str(rm.get("invoice_date", "")),
                "invoice_total": Decimal(str(rm.get("invoice_total", 0))),
                "commission_rate": float(rm.get("commission_rate", 0)),
                "commission_amount": Decimal(str(rm.get("commission_amount", 0))),
                "status": rm.get("status", "pending"),
            })

            if sp_id not in sp_summary:
                sp_summary[sp_id] = {
                    "salesperson_name": sp_name,
                    "total_sales": 0, "total_commission": 0,
                    "pending": 0, "paid": 0, "invoice_count": 0
                }
            sp_summary[sp_id]["total_sales"] += Decimal(str(rm.get("invoice_total", 0)))
            sp_summary[sp_id]["total_commission"] += Decimal(str(rm.get("commission_amount", 0)))
            sp_summary[sp_id]["invoice_count"] += 1
            if rm.get("status") == "paid":
                sp_summary[sp_id]["paid"] += Decimal(str(rm.get("commission_amount", 0)))
            else:
                sp_summary[sp_id]["pending"] += Decimal(str(rm.get("commission_amount", 0)))

        total_commission = sum(s["total_commission"] for s in sp_summary.values())
        total_pending = sum(s["pending"] for s in sp_summary.values())
        total_paid = sum(s["paid"] for s in sp_summary.values())

        result = {
            "report_name": "Sales Commission Report — تقرير عمولات المبيعات",
            "period": {"start": str(s_date), "end": str(e_date)},
            "details": report_rows,
            "salesperson_summary": [
                {"salesperson_id": k, **v} for k, v in sp_summary.items()
            ],
            "totals": {
                "total_commission": round(total_commission, 2),
                "total_pending": round(total_pending, 2),
                "total_paid": round(total_paid, 2),
                "salesperson_count": len(sp_summary),
                "record_count": len(report_rows),
            }
        }

        if format in ("excel", "pdf"):
            export_data = []
            for r in report_rows:
                export_data.append({
                    "مندوب المبيعات / Salesperson": r["salesperson_name"],
                    "رقم الفاتورة / Invoice #": r["invoice_number"],
                    "تاريخ الفاتورة / Date": r["invoice_date"],
                    "مبلغ الفاتورة / Invoice Total": r["invoice_total"],
                    "نسبة العمولة % / Rate %": r["commission_rate"],
                    "مبلغ العمولة / Commission": r["commission_amount"],
                    "الحالة / Status": "مدفوع" if r["status"] == "paid" else "معلق",
                })
            columns = list(export_data[0].keys()) if export_data else []

            # Generate chart for commission summary by salesperson
            chart_image = None
            try:
                summary_list = list(sp_summary.values())[:10]
                if summary_list:
                    chart_image = generate_chart_image(
                        "bar",
                        [s["salesperson_name"][:15] for s in summary_list],
                        [
                            {"label": "مبيعات / Sales", "data": [s["total_sales"] for s in summary_list], "color": "#2563EB"},
                            {"label": "عمولة / Commission", "data": [s["total_commission"] for s in summary_list], "color": "#16A34A"},
                        ],
                        title="Sales Commission by Salesperson — عمولات حسب المندوب"
                    )
            except Exception:
                pass

            if format == "excel":
                buffer = generate_excel_with_chart(export_data, columns, sheet_name="Commissions",
                    chart_type="bar", chart_config={"title": "Commission Report", "x_col": 0, "y_cols": [3, 5]})
                return create_export_response(buffer, f"commissions_{s_date}_{e_date}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                pdf_data = [columns] + [[str(row.get(c, '')) for c in columns] for row in export_data]
                buffer = generate_pdf(pdf_data,
                    title="Sales Commission Report — تقرير عمولات المبيعات",
                    subtitle=f"{s_date} → {e_date}",
                    chart_image=chart_image, orientation="landscape")
                return create_export_response(buffer, f"commissions_{s_date}_{e_date}.pdf", "application/pdf")

        return result
    finally:
        db.close()


# ===================== B8: KPI Dashboard =====================

@router.get("/kpi/dashboard", dependencies=[Depends(require_permission("reports.view"))])
def get_kpi_dashboard(current_user=Depends(get_current_user)):
    """لوحة مؤشرات الأداء الرئيسية"""
    db = get_db_connection(current_user.company_id)
    try:
        kpis = {}

        # Revenue KPI
        rev = db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) as current_month,
                   (SELECT COALESCE(SUM(total_amount), 0) FROM invoices
                    WHERE invoice_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                      AND invoice_date < date_trunc('month', CURRENT_DATE)) as last_month
            FROM invoices
            WHERE invoice_date >= date_trunc('month', CURRENT_DATE)
        """)).fetchone()
        if rev:
            r = dict(rev._mapping)
            current = Decimal(str(r.get("current_month", 0)))
            last = Decimal(str(r.get("last_month", 0)))
            kpis["revenue"] = {
                "value": current, "previous": last,
                "change_pct": round((current - last) / last * 100, 2) if last else 0
            }

        # Expenses KPI
        exp = db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) as current_month
            FROM expenses WHERE expense_date >= date_trunc('month', CURRENT_DATE)
        """)).fetchone()
        kpis["expenses"] = {"value": Decimal(str(dict(exp._mapping).get("current_month", 0)))} if exp else {"value": 0}

        # Outstanding receivables
        ar = db.execute(text("""
            SELECT COALESCE(SUM(balance_due), 0) as total
            FROM invoices WHERE status != 'paid' AND invoice_type = 'sale'
        """)).fetchone()
        kpis["accounts_receivable"] = {"value": Decimal(str(dict(ar._mapping).get("total", 0)))} if ar else {"value": 0}

        # Outstanding payables
        ap = db.execute(text("""
            SELECT COALESCE(SUM(balance_due), 0) as total
            FROM invoices WHERE status != 'paid' AND invoice_type = 'purchase'
        """)).fetchone()
        kpis["accounts_payable"] = {"value": Decimal(str(dict(ap._mapping).get("total", 0)))} if ap else {"value": 0}

        # Cash balance — pulled from GL (journal_lines) using company_settings
        # acc_map_cash_main + acc_map_bank so the KPI always matches the TB.
        cash = db.execute(text("""
            WITH cash_accs AS (
                SELECT CAST(setting_value AS INTEGER) AS account_id
                FROM company_settings
                WHERE setting_key IN ('acc_map_cash_main', 'acc_map_bank')
                  AND setting_value ~ '^[0-9]+$'
            )
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id IN (SELECT account_id FROM cash_accs)
              AND je.status = 'posted'
        """)).fetchone()
        kpis["cash_balance"] = {"value": Decimal(str(dict(cash._mapping).get("balance", 0)))} if cash else {"value": 0}

        # Inventory value
        inv = db.execute(text("""
            SELECT COALESCE(SUM(quantity_on_hand * unit_cost), 0) as total_value,
                   COUNT(*) as total_items
            FROM products WHERE is_active = TRUE
        """)).fetchone()
        if inv:
            d = dict(inv._mapping)
            kpis["inventory"] = {"value": Decimal(str(d.get("total_value", 0))), "items": int(d.get("total_items", 0))}

        # HR headcount
        hr = db.execute(text("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'active' THEN 1 END) as active
            FROM employees
        """)).fetchone()
        if hr:
            d = dict(hr._mapping)
            kpis["employees"] = {"total": int(d.get("total", 0)), "active": int(d.get("active", 0))}

        return kpis
    except Exception as e:
        logger.error(f"KPI Dashboard error: {e}")
        return {}
    finally:
        db.close()


# ============================================================
#   10 INDUSTRY-SPECIFIC REPORT ENDPOINTS
#   تقارير صناعية متخصصة ببيانات حقيقية من قاعدة البيانات
# ============================================================

def _period_params(from_date: Optional[date] = None, to_date: Optional[date] = None):
    """Return (from_date, to_date) defaulting to current month."""
    today = date.today()
    if not from_date:
        from_date = today.replace(day=1)
    if not to_date:
        to_date = today
    return from_date, to_date


def _gl_balance(db, account_prefix: str, from_date: date, to_date: date, side: str = "debit"):
    """Sum journal line debits/credits for accounts starting with prefix."""
    col = "debit" if side == "debit" else "credit"
    row = db.execute(text(f"""
        SELECT COALESCE(SUM(jl.{col}), 0) AS total
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE a.account_number LIKE :prefix
          AND je.entry_date BETWEEN :d1 AND :d2
          AND je.status = 'posted'
    """), {"prefix": f"{account_prefix}%", "d1": from_date, "d2": to_date}).fetchone()
    return Decimal(str(row.total)) if row else Decimal("0")


# ─── 1. Food Cost Report (FB - المطاعم) ───
@router.get("/industry/food-cost", dependencies=[Depends(require_permission("reports.view"))])
async def food_cost_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة الطعام — نسبة تكلفة المواد إلى الإيرادات"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # تكلفة البضاعة المباعة (COGS) = حسابات 510xx
        cogs = _gl_balance(db, "510", d1, d2, "debit")
        # إيرادات المبيعات = حسابات 410xx
        revenue = _gl_balance(db, "410", d1, d2, "credit")
        # مشتريات المواد الغذائية = حسابات 510 (debit) كمؤشر إضافي
        # مصاريف التشغيل = حسابات 6xxxx
        operating_exp = _gl_balance(db, "6", d1, d2, "debit")

        food_cost_pct = round((cogs / revenue * 100), 2) if revenue > 0 else 0
        gross_profit = revenue - cogs
        gross_margin = round((gross_profit / revenue * 100), 2) if revenue > 0 else 0
        net_profit = gross_profit - operating_exp

        # Top 10 most-sold items
        top_items = db.execute(text("""
            SELECT p.product_name, p.product_name_en,
                   SUM(il.quantity) AS qty_sold,
                   SUM(il.total) AS total_revenue,
                   SUM(il.quantity * p.cost_price) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale','pos_invoice')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en
            ORDER BY total_revenue DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        items = []
        for r in top_items:
            row = dict(r._mapping)
            cost = Decimal(str(row.get("total_cost") or 0))
            rev  = Decimal(str(row.get("total_revenue") or 0))
            row["cost_pct"] = round((cost / rev * 100), 2) if rev > 0 else 0
            items.append(row)

        return {
            "report_type": "food-cost",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "revenue": revenue,
                "cogs": cogs,
                "food_cost_pct": food_cost_pct,
                "gross_profit": gross_profit,
                "gross_margin_pct": gross_margin,
                "operating_expenses": operating_exp,
                "net_profit": net_profit,
            },
            "top_items": items,
        }
    except Exception as e:
        logger.error(f"Food cost report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 2. Production Cost Report (MF - التصنيع) ───
@router.get("/industry/production-cost", dependencies=[Depends(require_permission("reports.view"))])
async def production_cost_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة الإنتاج — مقارنة التكلفة المخططة بالفعلية"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # أوامر الإنتاج في الفترة
        orders = db.execute(text("""
            SELECT po.id, po.order_number, po.status,
                   p.product_name, p.product_name_en,
                   po.quantity AS planned_qty,
                   po.produced_quantity,
                   po.scrapped_quantity,
                   (po.quantity * p.cost_price) AS planned_cost,
                   p.cost_price
            FROM production_orders po
            JOIN products p ON p.id = po.product_id
            WHERE (po.start_date BETWEEN :d1 AND :d2 OR po.due_date BETWEEN :d1 AND :d2)
            ORDER BY po.created_at DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        total_planned = 0
        total_produced = 0
        total_scrapped = 0
        total_planned_cost = 0
        order_list = []
        for r in orders:
            row = dict(r._mapping)
            total_planned += float(row.get("planned_qty") or 0)
            total_produced += float(row.get("produced_quantity") or 0)
            total_scrapped += float(row.get("scrapped_quantity") or 0)
            total_planned_cost += Decimal(str(row.get("planned_cost") or 0))
            order_list.append(row)

        # تكلفة المواد الخام الفعلية من journal_lines (حسابات 510xx تصنيع)
        actual_material_cost = _gl_balance(db, "510", d1, d2, "debit")
        # مصاريف التصنيع غير المباشرة (حسابات 520xx)
        overhead_cost = _gl_balance(db, "520", d1, d2, "debit")

        efficiency = round((total_produced / total_planned * 100), 2) if total_planned > 0 else 0
        scrap_rate = round((total_scrapped / (total_produced + total_scrapped) * 100), 2) if (total_produced + total_scrapped) > 0 else 0
        variance = actual_material_cost - total_planned_cost
        variance_pct = round((variance / total_planned_cost * 100), 2) if total_planned_cost > 0 else 0

        return {
            "report_type": "production-cost",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_orders": len(order_list),
                "planned_qty": total_planned,
                "produced_qty": total_produced,
                "scrapped_qty": total_scrapped,
                "efficiency_pct": efficiency,
                "scrap_rate_pct": scrap_rate,
                "planned_cost": total_planned_cost,
                "actual_material_cost": actual_material_cost,
                "overhead_cost": overhead_cost,
                "total_actual_cost": actual_material_cost + overhead_cost,
                "variance": variance,
                "variance_pct": variance_pct,
            },
            "orders": order_list[:20],
        }
    except Exception as e:
        logger.error(f"Production cost report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 3. Progress Billing Report (CN - المقاولات) ───
@router.get("/industry/progress-billing", dependencies=[Depends(require_permission("reports.view"))])
async def progress_billing_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير مستخلصات المشاريع — نسبة الإنجاز والفواتير"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        projects = db.execute(text("""
            SELECT p.id, p.project_code, p.project_name, p.project_name_en,
                   p.status, p.planned_budget, p.actual_cost,
                   p.progress_percentage, p.contract_type,
                   p.start_date, p.end_date, p.customer_id,
                   COALESCE(exp_total.spent, 0) AS total_expenses
            FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) AS spent
                FROM project_expenses
                WHERE status != 'rejected'
                GROUP BY project_id
            ) exp_total ON exp_total.project_id = p.id
            WHERE p.status NOT IN ('cancelled')
            ORDER BY p.progress_percentage DESC
        """)).fetchall()

        project_list = []
        total_budget = 0
        total_invoiced = 0
        total_cost = 0
        for r in projects:
            row = dict(r._mapping)
            budget = Decimal(str(row.get("planned_budget") or 0))
            cost = Decimal(str(row.get("total_expenses") or 0)) or Decimal(str(row.get("actual_cost") or 0))
            # Use actual_cost as billed amount (represents invoiced work in progress billing)
            invoiced = Decimal(str(row.get("actual_cost") or 0))
            progress = float(row.get("progress_percentage") or 0)

            row["profit"] = invoiced - cost
            row["profit_margin_pct"] = round((row["profit"] / invoiced * 100), 2) if invoiced > 0 else 0
            row["billing_pct"] = round((invoiced / budget * 100), 2) if budget > 0 else 0
            row["cost_pct"] = round((cost / budget * 100), 2) if budget > 0 else 0

            total_budget += budget
            total_invoiced += invoiced
            total_cost += cost
            project_list.append(row)

        return {
            "report_type": "progress-billing",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_projects": len(project_list),
                "active_projects": sum(1 for p in project_list if p.get("status") == "in_progress"),
                "total_budget": total_budget,
                "total_invoiced": total_invoiced,
                "total_cost": total_cost,
                "overall_profit": total_invoiced - total_cost,
                "overall_billing_pct": round((total_invoiced / total_budget * 100), 2) if total_budget > 0 else 0,
            },
            "projects": project_list,
        }
    except Exception as e:
        logger.error(f"Progress billing report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 4. Drug Expiry Report (PH - الصيدليات) ───
@router.get("/industry/drug-expiry", dependencies=[Depends(require_permission("reports.view"))])
async def drug_expiry_report(
    days_ahead: int = 90,
    current_user: dict = Depends(get_current_user)
):
    """تقرير الأدوية/المنتجات قريبة الانتهاء"""
    db = get_db_connection(current_user.company_id)
    try:
        # INV-F4: normalize to UTC so cut-offs are deterministic regardless
        # of the server host timezone.
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=days_ahead)

        # من جدول product_batches
        batches = db.execute(text("""
            SELECT pb.batch_number, pb.expiry_date, pb.available_quantity,
                   pb.unit_cost,
                   p.product_name, p.product_name_en, p.product_code,
                   w.warehouse_name
            FROM product_batches pb
            JOIN products p ON p.id = pb.product_id
            LEFT JOIN warehouses w ON w.id = pb.warehouse_id
            WHERE pb.expiry_date IS NOT NULL
              AND pb.expiry_date <= :cutoff
              AND pb.available_quantity > 0
              AND pb.status = 'active'
            ORDER BY pb.expiry_date ASC
        """), {"cutoff": cutoff}).fetchall()

        expired = []
        expiring_30 = []
        expiring_60 = []
        expiring_90 = []
        total_value_at_risk = 0

        for r in batches:
            row = dict(r._mapping)
            exp_date = row.get("expiry_date")
            qty = float(row.get("available_quantity") or 0)
            cost = Decimal(str(row.get("unit_cost") or 0))
            row["value_at_risk"] = round(qty * cost, 2)
            total_value_at_risk += row["value_at_risk"]

            if exp_date:
                days_left = (exp_date - today).days
                row["days_left"] = days_left
                if days_left <= 0:
                    row["urgency"] = "expired"
                    expired.append(row)
                elif days_left <= 30:
                    row["urgency"] = "critical"
                    expiring_30.append(row)
                elif days_left <= 60:
                    row["urgency"] = "warning"
                    expiring_60.append(row)
                else:
                    row["urgency"] = "notice"
                    expiring_90.append(row)

        all_items = expired + expiring_30 + expiring_60 + expiring_90

        return {
            "report_type": "drug-expiry",
            "as_of": str(today),
            "days_ahead": days_ahead,
            "summary": {
                "total_items": len(all_items),
                "expired_count": len(expired),
                "expiring_30_days": len(expiring_30),
                "expiring_60_days": len(expiring_60),
                "expiring_90_days": len(expiring_90),
                "total_value_at_risk": round(total_value_at_risk, 2),
            },
            "items": all_items[:50],
        }
    except Exception as e:
        logger.error(f"Drug expiry report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 5. Fleet Efficiency Report (LG - اللوجستيات) ───
@router.get("/industry/fleet-tracking", dependencies=[Depends(require_permission("reports.view"))])
async def fleet_tracking_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير كفاءة الأسطول — أداء التوصيل والمركبات"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # بيانات التوصيل حسب المركبة
        vehicles = db.execute(text("""
            SELECT vehicle_number,
                   driver_name,
                   COUNT(*) AS total_deliveries,
                   COUNT(CASE WHEN status = 'delivered' THEN 1 END) AS completed,
                   COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
                   SUM(total_quantity) AS total_qty,
                   MIN(delivery_date) AS first_delivery,
                   MAX(delivery_date) AS last_delivery
            FROM delivery_orders
            WHERE delivery_date BETWEEN :d1 AND :d2
              AND vehicle_number IS NOT NULL AND vehicle_number != ''
            GROUP BY vehicle_number, driver_name
            ORDER BY total_deliveries DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        vehicle_list = []
        total_deliveries = 0
        total_completed = 0
        for r in vehicles:
            row = dict(r._mapping)
            completed = int(row.get("completed") or 0)
            total = int(row.get("total_deliveries") or 0)
            row["completion_rate"] = round((completed / total * 100), 2) if total > 0 else 0
            total_deliveries += total
            total_completed += completed
            vehicle_list.append(row)

        # ملخص عام
        overall = db.execute(text("""
            SELECT COUNT(*) AS total,
                   COUNT(CASE WHEN status = 'delivered' THEN 1 END) AS delivered,
                   COUNT(CASE WHEN status = 'in_transit' THEN 1 END) AS in_transit,
                   COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
                   COUNT(DISTINCT vehicle_number) AS vehicles_used,
                   COUNT(DISTINCT driver_name) AS drivers_used,
                   AVG(EXTRACT(EPOCH FROM (delivered_at - shipped_at))/3600) AS avg_delivery_hours
            FROM delivery_orders
            WHERE delivery_date BETWEEN :d1 AND :d2
        """), {"d1": d1, "d2": d2}).fetchone()

        summary = dict(overall._mapping) if overall else {}
        summary["on_time_rate"] = round((total_completed / total_deliveries * 100), 2) if total_deliveries > 0 else 0

        return {
            "report_type": "fleet-tracking",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": summary,
            "vehicles": vehicle_list,
        }
    except Exception as e:
        logger.error(f"Fleet tracking report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 6. Utilization Report (SV - الخدمات المهنية) ───
@router.get("/industry/utilization", dependencies=[Depends(require_permission("reports.view"))])
async def utilization_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير معدل الاستغلال — ساعات مفوترة مقابل ساعات متاحة"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # ساعات من project_tasks
        tasks = db.execute(text("""
            SELECT e.id AS employee_id,
                   COALESCE(e.first_name || ' ' || e.last_name, 'غير محدد') AS employee_name,
                   SUM(pt.actual_hours) AS billable_hours,
                   SUM(pt.planned_hours) AS planned_hours,
                   COUNT(pt.id) AS tasks_count,
                   COUNT(CASE WHEN pt.status = 'completed' THEN 1 END) AS completed_tasks
            FROM project_tasks pt
            LEFT JOIN employees e ON e.id = pt.assigned_to
            WHERE (pt.start_date BETWEEN :d1 AND :d2 OR pt.end_date BETWEEN :d1 AND :d2)
            GROUP BY e.id, e.first_name, e.last_name
            ORDER BY billable_hours DESC NULLS LAST
        """), {"d1": d1, "d2": d2}).fetchall()

        # عدد أيام العمل في الفترة (تقريبي: 22 يوم/شهر * 8 ساعات)
        work_days = max(1, (d2 - d1).days * 5 // 7)
        available_hours_per_person = work_days * 8

        employee_list = []
        total_billable = 0
        total_planned = 0
        for r in tasks:
            row = dict(r._mapping)
            billable = float(row.get("billable_hours") or 0)
            row["available_hours"] = available_hours_per_person
            row["utilization_pct"] = round((billable / available_hours_per_person * 100), 2) if available_hours_per_person > 0 else 0
            total_billable += billable
            total_planned += float(row.get("planned_hours") or 0)
            employee_list.append(row)

        # إيراد الخدمات
        svc_revenue = _gl_balance(db, "410", d1, d2, "credit")
        svc_expenses = _gl_balance(db, "6", d1, d2, "debit")
        effective_rate = round(svc_revenue / total_billable, 2) if total_billable > 0 else 0

        return {
            "report_type": "utilization",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_employees": len(employee_list),
                "total_billable_hours": total_billable,
                "total_planned_hours": total_planned,
                "avg_utilization_pct": round((total_billable / (available_hours_per_person * max(len(employee_list), 1)) * 100), 2) if employee_list else 0,
                "service_revenue": svc_revenue,
                "effective_hourly_rate": effective_rate,
                "operating_expenses": svc_expenses,
                "net_profit": svc_revenue - svc_expenses,
            },
            "employees": employee_list[:20],
        }
    except Exception as e:
        logger.error(f"Utilization report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 7. Workshop Revenue Report (WK - الورش) ───
@router.get("/industry/workshop-revenue", dependencies=[Depends(require_permission("reports.view"))])
async def workshop_revenue_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير إيرادات الورشة — حسب نوع الخدمة"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # إيرادات حسب المنتج/الخدمة
        by_service = db.execute(text("""
            SELECT COALESCE(p.product_name, il.description, 'أخرى') AS service_name,
                   COALESCE(p.product_name_en, il.description, 'Other') AS service_name_en,
                   p.product_type,
                   COUNT(DISTINCT i.id) AS job_count,
                   SUM(il.quantity) AS total_qty,
                   SUM(il.total) AS total_revenue,
                   SUM(il.quantity * COALESCE(p.cost_price, 0)) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            LEFT JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale', 'pos_invoice')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_type, il.description
            ORDER BY total_revenue DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        service_list = []
        total_revenue = 0
        total_cost = 0
        total_jobs = 0
        for r in by_service:
            row = dict(r._mapping)
            rev = Decimal(str(row.get("total_revenue") or 0))
            cost = Decimal(str(row.get("total_cost") or 0))
            row["margin"] = rev - cost
            row["margin_pct"] = round(((rev - cost) / rev * 100), 2) if rev > 0 else 0
            total_revenue += rev
            total_cost += cost
            total_jobs += int(row.get("job_count") or 0)
            service_list.append(row)

        # قطع الغيار المستخدمة (product_type = 'product')
        parts_count = sum(1 for s in service_list if s.get("product_type") == "product")
        services_count = sum(1 for s in service_list if s.get("product_type") == "service")

        return {
            "report_type": "workshop-revenue",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_jobs": total_jobs,
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "gross_profit": total_revenue - total_cost,
                "gross_margin_pct": round(((total_revenue - total_cost) / total_revenue * 100), 2) if total_revenue > 0 else 0,
                "parts_items": parts_count,
                "service_items": services_count,
                "avg_job_value": round(total_revenue / total_jobs, 2) if total_jobs > 0 else 0,
            },
            "services": service_list[:20],
        }
    except Exception as e:
        logger.error(f"Workshop revenue report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 8. E-Commerce Returns Report (EC - التجارة الإلكترونية) ───
@router.get("/industry/ecom-returns", dependencies=[Depends(require_permission("reports.view"))])
async def ecom_returns_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المرتجعات — نسبة المرتجعات وأسبابها"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # إجمالي المبيعات
        sales = db.execute(text("""
            SELECT COUNT(*) AS sale_count, COALESCE(SUM(total), 0) AS sale_total
            FROM invoices
            WHERE invoice_type IN ('sale', 'pos_invoice')
              AND invoice_date BETWEEN :d1 AND :d2
              AND status != 'cancelled'
        """), {"d1": d1, "d2": d2}).fetchone()
        sale_count = int(sales.sale_count) if sales else 0
        sale_total = Decimal(str(sales.sale_total)) if sales else 0

        # مبيعات مرتجعة
        returns = db.execute(text("""
            SELECT COUNT(*) AS return_count, COALESCE(SUM(total), 0) AS return_total
            FROM sales_returns
            WHERE return_date BETWEEN :d1 AND :d2
              AND status != 'cancelled'
        """), {"d1": d1, "d2": d2}).fetchone()
        return_count = int(returns.return_count) if returns else 0
        return_total = Decimal(str(returns.return_total)) if returns else 0

        return_rate = round((return_count / sale_count * 100), 2) if sale_count > 0 else 0
        value_return_rate = round((return_total / sale_total * 100), 2) if sale_total > 0 else 0

        # أكثر المنتجات مرتجعاً
        top_returns = db.execute(text("""
            SELECT p.product_name, p.product_name_en, p.product_code,
                   SUM(srl.quantity) AS returned_qty,
                   SUM(srl.total) AS return_value,
                   COUNT(DISTINCT sr.id) AS return_count
            FROM sales_return_lines srl
            JOIN sales_returns sr ON sr.id = srl.return_id
            LEFT JOIN products p ON p.id = srl.product_id
            WHERE sr.return_date BETWEEN :d1 AND :d2
              AND sr.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_code
            ORDER BY return_value DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        return {
            "report_type": "ecom-returns",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_sales": sale_count,
                "total_sales_value": sale_total,
                "total_returns": return_count,
                "total_return_value": return_total,
                "return_rate_pct": return_rate,
                "value_return_rate_pct": value_return_rate,
                "net_sales": sale_total - return_total,
            },
            "top_returned_products": [dict(r._mapping) for r in top_returns],
        }
    except Exception as e:
        logger.error(f"E-com returns report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 9. Agent Performance Report (WS - الجملة) ───
@router.get("/industry/agent-performance", dependencies=[Depends(require_permission("reports.view"))])
async def agent_performance_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير أداء الوكلاء/المناديب — مبيعات لكل مندوب/عميل"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # مبيعات حسب المندوب (created_by)
        by_agent = db.execute(text("""
            SELECT cu.username AS agent_name,
                   cu.full_name AS agent_full_name,
                   COUNT(i.id) AS invoice_count,
                   COALESCE(SUM(i.total), 0) AS total_sales,
                   COALESCE(SUM(i.paid_amount), 0) AS total_collected,
                   COUNT(DISTINCT i.party_id) AS customer_count
            FROM invoices i
            JOIN company_users cu ON cu.id = i.created_by
            WHERE i.invoice_type IN ('sale')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY cu.id, cu.username, cu.full_name
            ORDER BY total_sales DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        agent_list = []
        grand_total = 0
        for r in by_agent:
            row = dict(r._mapping)
            sales = Decimal(str(row.get("total_sales") or 0))
            collected = Decimal(str(row.get("total_collected") or 0))
            row["collection_rate_pct"] = round((collected / sales * 100), 2) if sales > 0 else 0
            row["avg_invoice_value"] = round(sales / max(int(row.get("invoice_count") or 1), 1), 2)
            grand_total += sales
            agent_list.append(row)

        # حساب النسبة من الإجمالي
        for agent in agent_list:
            agent["share_pct"] = round((Decimal(str(agent.get("total_sales") or 0)) / grand_total * 100), 2) if grand_total > 0 else 0

        # أكبر العملاء
        top_customers = db.execute(text("""
            SELECT pa.name AS customer_name, pa.name_en AS customer_name_en,
                   COUNT(i.id) AS order_count,
                   COALESCE(SUM(i.total), 0) AS total_value
            FROM invoices i
            JOIN parties pa ON pa.id = i.party_id
            WHERE i.invoice_type = 'sale'
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY pa.id, pa.name, pa.name_en
            ORDER BY total_value DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        return {
            "report_type": "agent-performance",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_agents": len(agent_list),
                "grand_total_sales": grand_total,
                "avg_sales_per_agent": round(grand_total / max(len(agent_list), 1), 2),
            },
            "agents": agent_list,
            "top_customers": [dict(r._mapping) for r in top_customers],
        }
    except Exception as e:
        logger.error(f"Agent performance report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 10. Crop Yield Report (AG - الزراعة) ───
@router.get("/industry/crop-yield", dependencies=[Depends(require_permission("reports.view"))])
async def crop_yield_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير إنتاجية المحاصيل — المنتجات الزراعية مقابل التكاليف"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # مبيعات المنتجات (= حصاد)
        harvests = db.execute(text("""
            SELECT p.product_name, p.product_name_en, p.product_code,
                   SUM(il.quantity) AS total_qty_sold,
                   SUM(il.total) AS total_revenue,
                   p.cost_price,
                   SUM(il.quantity * p.cost_price) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_code, p.cost_price
            ORDER BY total_revenue DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        crop_list = []
        total_revenue = 0
        total_cost = 0
        for r in harvests:
            row = dict(r._mapping)
            rev = Decimal(str(row.get("total_revenue") or 0))
            cost = Decimal(str(row.get("total_cost") or 0))
            row["profit"] = rev - cost
            row["margin_pct"] = round(((rev - cost) / rev * 100), 2) if rev > 0 else 0
            total_revenue += rev
            total_cost += cost
            crop_list.append(row)

        # تكاليف زراعية من GL (مصاريف 6xxxx)
        agri_expenses = _gl_balance(db, "6", d1, d2, "debit")
        # مشتريات مستلزمات (5xxxx)
        input_costs = _gl_balance(db, "5", d1, d2, "debit")

        return {
            "report_type": "crop-yield",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_crops": len(crop_list),
                "total_revenue": total_revenue,
                "total_direct_cost": total_cost,
                "gross_profit": total_revenue - total_cost,
                "gross_margin_pct": round(((total_revenue - total_cost) / total_revenue * 100), 2) if total_revenue > 0 else 0,
                "total_operating_expenses": agri_expenses,
                "total_input_costs": input_costs,
                "net_farm_income": total_revenue - input_costs - agri_expenses,
            },
            "crops": crop_list[:20],
        }
    except Exception as e:
        logger.error(f"Crop yield report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
