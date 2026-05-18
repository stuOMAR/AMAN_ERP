"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, resolve_branch_scope, branch_scope_filter_from_scope
from utils.cache import cached
from utils.exports import generate_excel, generate_excel_with_chart, generate_pdf, generate_chart_image, create_export_response
from services.sales_service import get_sales_total, get_gl_profit_breakdown

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/sales/summary", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))])
def get_sales_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص المبيعات (إجمالي، عدد الفواتير، الأرباح التقريبية)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
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
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
        )

        # Approximate tax extracted from gross totals (assumes embedded tax
        # at the line-level rate; falls back to 15 % when no lines exist).
        params = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        tax_row = db.execute(text( # noqa: sql-lint
                    f"""
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
                        COALESCE((SELECT AVG(tax_rate) FROM invoice_lines WHERE invoice_id = all_sales.id), 0)
                    ELSE
                        COALESCE((SELECT AVG(tax_rate) FROM pos_order_lines WHERE order_id = all_sales.id), 0)
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
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        start_date = date.today() - timedelta(days=days)
        params = {"start": start_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
        
        result = db.execute(text( # noqa: sql-lint
                    f"""
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
            {branch_filter}
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "s.branch_id", params)

        result = db.execute(text( # noqa: sql-lint
                    f"""
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
            {branch_filter}
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {"limit": limit}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "cl.branch_id", params)

        result = db.execute(text( # noqa: sql-lint
                    f"""
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
            {branch_filter}
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"cid": customer_id, "start": start_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        # 1. Get Opening Balance (Combined: invoices + POS + payment vouchers)
        # AUDIT-H3: opening balance must include sales credit notes
        # (debit-balance reductions), debit notes (additions), and
        # approved sales returns. Without these, statement opening drifts
        # from party_site_balances.
        opening_balance = db.execute(text( # noqa: sql-lint
                    f"""
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

                -- Debit notes raise AR
                SELECT
                    (total * COALESCE(exchange_rate, 1.0)) as debit,
                    0 as credit,
                    invoice_date as sale_date,
                    branch_id,
                    party_id
                FROM invoices
                WHERE invoice_type = 'sales_debit_note'
                  AND status NOT IN ('cancelled', 'draft')

                UNION ALL

                -- Credit notes reduce AR
                SELECT
                    0 as debit,
                    (total * COALESCE(exchange_rate, 1.0)) as credit,
                    invoice_date as sale_date,
                    branch_id,
                    party_id
                FROM invoices
                WHERE invoice_type = 'sales_credit_note'
                  AND status NOT IN ('cancelled', 'draft')

                UNION ALL

                -- Approved sales returns reduce AR
                SELECT
                    0 as debit,
                    (sr.total * COALESCE(sr.exchange_rate, 1.0)) as credit,
                    sr.return_date as sale_date,
                    sr.branch_id,
                    sr.party_id
                FROM sales_returns sr
                WHERE sr.status = 'approved'

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
            {branch_filter}
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
        # AUDIT-H3: transactions list must mirror the opening-balance
        # source set so debit/credit notes and approved returns appear
        # as their own rows (and the running balance reconciles).
        params["end"] = end_date
        transactions = db.execute(text( # noqa: sql-lint
                    f"""
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
                    id, invoice_date as date, invoice_number as ref,
                    'debit_note' as type, (total * COALESCE(exchange_rate, 1.0)) as debit,
                    0 as credit,
                    currency, exchange_rate, branch_id, party_id
                FROM invoices
                WHERE invoice_type = 'sales_debit_note'
                  AND status NOT IN ('cancelled', 'draft')

                UNION ALL

                SELECT
                    id, invoice_date as date, invoice_number as ref,
                    'credit_note' as type, 0 as debit,
                    (total * COALESCE(exchange_rate, 1.0)) as credit,
                    currency, exchange_rate, branch_id, party_id
                FROM invoices
                WHERE invoice_type = 'sales_credit_note'
                  AND status NOT IN ('cancelled', 'draft')

                UNION ALL

                SELECT
                    sr.id, sr.return_date as date, sr.return_number as ref,
                    'return' as type, 0 as debit,
                    (sr.total * COALESCE(sr.exchange_rate, 1.0)) as credit,
                    sr.currency, sr.exchange_rate, sr.branch_id, sr.party_id
                FROM sales_returns sr
                WHERE sr.status = 'approved'

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
            {branch_filter}
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
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        invoice_branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
        pos_branch_filter = branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        # Get all unpaid invoices + POS credit orders with days overdue
        # Get base currency for POS
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)

        results = db.execute(text( # noqa: sql-lint
                    f"""
            -- AUDIT-H3: aging must reflect debit notes (raise AR),
            -- credit notes (lower AR), and approved sales returns
            -- (lower AR), otherwise AR aging always overstates the
            -- real exposure once any credit-side document is issued.
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
            {invoice_branch_filter}

            UNION ALL

            -- Sales debit notes carry the same AR sign as a sales invoice.
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
            WHERE i.invoice_type = 'sales_debit_note'
              AND i.status NOT IN ('draft', 'cancelled', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
            {invoice_branch_filter}

            UNION ALL

            -- Sales credit notes reduce AR — emit them as a negative
            -- aging row so the bucket totals net correctly.
            SELECT
                p.name as customer_name,
                i.invoice_number,
                i.invoice_date,
                i.due_date,
                -1 * i.total as due_amount_fc,
                -1 * i.total * COALESCE(i.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - i.invoice_date, 0) as days_old,
                i.currency
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'sales_credit_note'
              AND i.status NOT IN ('draft', 'cancelled')
            {invoice_branch_filter}

            UNION ALL

            -- Approved sales returns reduce AR similarly.
            SELECT
                p.name as customer_name,
                sr.return_number as invoice_number,
                sr.return_date as invoice_date,
                sr.return_date as due_date,
                -1 * sr.total as due_amount_fc,
                -1 * sr.total * COALESCE(sr.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - sr.return_date, 0) as days_old,
                sr.currency
            FROM sales_returns sr
            JOIN parties p ON sr.party_id = p.id
            WHERE sr.status = 'approved'
              {branch_scope_filter_from_scope(branch_scope, "sr.branch_id", params)}

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
            {pos_branch_filter}

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

@router.get("/sales/aging/export", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))], response_model=Dict[str, Any])
def export_aging(format: str = "pdf", branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """تصدير تقرير أعمار الديون"""
    data = get_aging_report(branch_id=branch_id, current_user=current_user)
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

@router.get("/sales/by-cashier", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))], response_model=Dict[str, Any])
def sales_by_cashier(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المبيعات حسب البائع/الكاشير"""
    db = get_db_connection(current_user.company_id)
    s = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.today().replace(month=1, day=1)
    e = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    branch_scope = resolve_branch_scope(current_user, branch_id)
    params = {"start": s, "end": e}
    invoice_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
    pos_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
    try:
        rows = db.execute(text( # noqa: sql-lint
                    f"""
            WITH all_sales AS (
                SELECT created_by, 
                       total * COALESCE(exchange_rate, 1) AS sale_total, 
                       paid_amount * COALESCE(exchange_rate, 1) AS paid_amount, 
                       invoice_date::date AS sale_date
                FROM invoices
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                  AND invoice_date BETWEEN :start AND :end
                  {invoice_branch_filter}

                UNION ALL

                SELECT created_by, total_amount AS sale_total, paid_amount, order_date::date AS sale_date
                FROM pos_orders
                WHERE status != 'cancelled'
                  AND order_date::date BETWEEN :start AND :end
                  {pos_branch_filter}
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
        """), params).fetchall()

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


@router.get("/sales/target-vs-actual", dependencies=[Depends(require_permission(["sales.reports", "reports.view"]))], response_model=Dict[str, Any])
def sales_target_vs_actual(
    year: int = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المبيعات المستهدفة vs الفعلية (شهري)"""
    db = get_db_connection(current_user.company_id)
    yr = year or date.today().year
    branch_scope = resolve_branch_scope(current_user, branch_id)
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
        params = {"y": yr}
        invoice_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
        pos_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)

        actuals = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT EXTRACT(MONTH FROM sale_date)::int as month,
                   COALESCE(SUM(total_amount), 0) as actual
            FROM (
                SELECT invoice_date::date AS sale_date, 
                       total * COALESCE(exchange_rate, 1) AS total_amount
                FROM invoices
                WHERE invoice_type = 'sales' AND status != 'cancelled'
                  AND EXTRACT(YEAR FROM invoice_date) = :y
                  {invoice_branch_filter}

                UNION ALL

                SELECT order_date::date AS sale_date, total_amount
                FROM pos_orders
                WHERE status != 'cancelled'
                  AND EXTRACT(YEAR FROM order_date) = :y
                  {pos_branch_filter}
            ) t
            GROUP BY month
            ORDER BY month
        """), params).fetchall()

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

@router.get("/sales/commissions/report", dependencies=[Depends(require_permission(["sales.view", "reports.view"]))], response_model=Dict[str, Any])
def sales_commission_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    salesperson_id: Optional[int] = None,
    branch_id: Optional[int] = None,
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
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT sc.*, 
                   COALESCE(sc.salesperson_name, cu.full_name, '') as sp_name
            FROM sales_commissions sc
            LEFT JOIN company_users cu ON sc.salesperson_id = cu.id
            WHERE sc.invoice_date BETWEEN :start AND :end
        """
        params = {"start": s_date, "end": e_date}
        query += f"\n{branch_scope_filter_from_scope(branch_scope, 'sc.branch_id', params)}"

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

