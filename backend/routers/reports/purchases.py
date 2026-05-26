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
from utils.tax_precision import money_str

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
        
        summary = db.execute(text( # noqa
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

        result = db.execute(text( # noqa
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

        result = db.execute(text( # noqa
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
        # AUDIT-H4: the previous implementation read from
        # `supplier_subledger`, but no write path in the
        # purchases/sales/payment routers populates that table — so the
        # report was always empty (or stale). We now build aging from
        # the same tables that the actual `party_site_balances` posts
        # against: open purchase invoices, posted purchase returns,
        # purchase credit/debit notes — netted with supplier payments
        # via the standard `paid_amount` column on invoices.
        params = {}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
        branch_scope_filter_from_scope(branch_scope, "ri.branch_id", params)

        results = db.execute(text( # noqa
                    f"""
            -- Open purchase invoices: AP increases by remaining unpaid.
            SELECT
                p.name as supplier_name,
                i.invoice_number as document_number,
                i.invoice_date as document_date,
                COALESCE(i.due_date, i.invoice_date) as due_date,
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

            UNION ALL

            -- Purchase debit notes raise AP.
            SELECT
                p.name as supplier_name,
                i.invoice_number as document_number,
                i.invoice_date as document_date,
                COALESCE(i.due_date, i.invoice_date) as due_date,
                (i.total - COALESCE(i.paid_amount, 0)) as due_amount_fc,
                (i.total - COALESCE(i.paid_amount, 0)) * COALESCE(i.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - COALESCE(i.due_date, i.invoice_date), 0) as days_old,
                i.currency
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'purchase_debit_note'
              AND i.status NOT IN ('draft', 'cancelled', 'paid')
              AND (i.total - COALESCE(i.paid_amount, 0)) > 0.01
              {branch_filter}

            UNION ALL

            -- Purchase credit notes (and purchase returns persisted as
            -- credit-side invoices) reduce AP — emit as negative rows.
            SELECT
                p.name as supplier_name,
                i.invoice_number as document_number,
                i.invoice_date as document_date,
                i.invoice_date as due_date,
                -1 * i.total as due_amount_fc,
                -1 * i.total * COALESCE(i.exchange_rate, 1) as due_amount,
                GREATEST(CURRENT_DATE - i.invoice_date, 0) as days_old,
                i.currency
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type IN ('purchase_credit_note', 'purchase_return')
              AND i.status NOT IN ('draft', 'cancelled')
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


@router.get("/purchases/aging/summary", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["buying.reports", "reports.view"]))])
def get_purchases_aging_summary(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Purchases aging report with backend-owned bucket totals."""
    rows = get_purchases_aging_report(branch_id=branch_id, current_user=current_user)
    bucket_totals = {
        "0-30": Decimal("0"),
        "31-60": Decimal("0"),
        "61-90": Decimal("0"),
        "90+": Decimal("0"),
    }

    serialized_rows = []
    for row in rows:
        bucket = row.get("bucket")
        amount = Decimal(str(row.get("amount") or 0))
        if bucket in bucket_totals:
            bucket_totals[bucket] += amount
        serialized = dict(row)
        serialized["amount"] = money_str(amount)
        serialized["amount_fc"] = money_str(row.get("amount_fc"))
        serialized_rows.append(serialized)

    buckets = [
        {"name": name, "amount": money_str(amount)}
        for name, amount in bucket_totals.items()
    ]

    return {
        "items": serialized_rows,
        "buckets": buckets,
        "total_due": money_str(sum(bucket_totals.values(), Decimal("0"))),
    }


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

        # AUDIT-H4: build the statement from the tables that the
        # purchases routers actually post against. supplier_subledger
        # is currently never written, so the legacy implementation
        # always returned an empty statement.
        movements_cte = """
            WITH all_movements AS (
                -- Purchase invoices and debit notes increase AP.
                SELECT
                    i.id,
                    i.invoice_date as date,
                    i.invoice_number as ref,
                    CASE
                        WHEN i.invoice_type = 'purchase_debit_note' THEN 'debit_note'
                        ELSE 'invoice'
                    END as type,
                    (i.total * COALESCE(i.exchange_rate, 1.0)) as credit,
                    0 as debit,
                    i.party_id,
                    i.branch_id
                FROM invoices i
                WHERE i.invoice_type IN ('purchase', 'purchase_debit_note')
                  AND i.status NOT IN ('cancelled', 'draft')

                UNION ALL

                -- Purchase credit notes and returns reduce AP.
                SELECT
                    i.id,
                    i.invoice_date as date,
                    i.invoice_number as ref,
                    CASE
                        WHEN i.invoice_type = 'purchase_credit_note' THEN 'credit_note'
                        ELSE 'return'
                    END as type,
                    0 as credit,
                    (i.total * COALESCE(i.exchange_rate, 1.0)) as debit,
                    i.party_id,
                    i.branch_id
                FROM invoices i
                WHERE i.invoice_type IN ('purchase_credit_note', 'purchase_return')
                  AND i.status NOT IN ('cancelled', 'draft')

                UNION ALL

                -- Supplier payments / refunds reduce AP.
                SELECT
                    pv.id,
                    pv.voucher_date as date,
                    pv.voucher_number as ref,
                    'payment' as type,
                    0 as credit,
                    (pv.amount * COALESCE(pv.exchange_rate, 1.0)) as debit,
                    pv.party_id,
                    pv.branch_id
                FROM payment_vouchers pv
                WHERE pv.party_type = 'supplier'
                  AND pv.voucher_type = 'payment'
                  AND pv.status != 'cancelled'
            )
        """

        opening_balance = db.execute(text( # noqa
                    f"""
            {movements_cte}
            SELECT (COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)) as balance
            FROM all_movements
            WHERE party_id = :sid AND date < :start
            {branch_filter}
        """), params).scalar() or 0

        params["end"] = end_date
        transactions = db.execute(text( # noqa
                    f"""
            {movements_cte}
            SELECT id, date, ref, type, credit, debit, party_id, branch_id
            FROM all_movements
            WHERE party_id = :sid AND date BETWEEN :start AND :end
            {branch_filter}
            ORDER BY date
        """), params).fetchall()

        # 3. Running Balance
        statement = []
        running_balance = Decimal(str(opening_balance))

        for t in transactions:
            credit = Decimal(str(t.credit))  # Purchase increases debt
            debit = Decimal(str(t.debit))    # Payment reduces debt

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
