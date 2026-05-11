"""taxes sub-router — split from monolithic taxes.py (T6.3).

Mounted under the parent router via taxes/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
import json
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.tax_precision import CALCULATION_VERSION, get_idempotency_key, money_str, q_money, serialize_tax_row
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/returns", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_tax_returns(
    status: Optional[str] = None,
    tax_type: Optional[str] = None,
    branch_id: Optional[int] = None,
    jurisdiction_code: Optional[str] = None,
    created_by: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب الإقرارات الضريبية مع فلترة حسب الفرع والمستخدم والسنة والنوع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        where = "WHERE 1=1"
        params = {}
        if status:
            where += " AND tr.status = :status"
            params["status"] = status
        if tax_type:
            where += " AND tr.tax_type = :tax_type"
            params["tax_type"] = tax_type
        where += f" {branch_scope_filter_from_scope(branch_scope, 'tr.branch_id', params)}"
        if jurisdiction_code:
            where += " AND tr.jurisdiction_code = :jc"
            params["jc"] = jurisdiction_code.upper()
        if created_by:
            where += " AND tr.created_by = :created_by"
            params["created_by"] = created_by
        if year:
            where += " AND tr.tax_period LIKE :year_prefix"
            params["year_prefix"] = f"{year}%"

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT tr.*,
                   cu.username as created_by_name,
                   b.branch_name as branch_name,
                   COALESCE((SELECT SUM(tp.amount) FROM tax_payments tp WHERE tp.tax_return_id = tr.id AND tp.status = 'confirmed'), 0) as paid_amount
            FROM tax_returns tr
            LEFT JOIN company_users cu ON tr.created_by = cu.id
            LEFT JOIN branches b ON tr.branch_id = b.id
            {where}
            ORDER BY tr.created_at DESC
        """), params).fetchall()

        return [serialize_tax_row(r, money_fields=["taxable_amount", "tax_amount", "total_amount", "paid_amount"]) for r in rows]


@router.get("/returns/{return_id}", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=Dict[str, Any])
def get_tax_return(return_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل إقرار ضريبي"""
    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            SELECT tr.*,
                   cu.username as created_by_name
            FROM tax_returns tr
            LEFT JOIN company_users cu ON tr.created_by = cu.id
            WHERE tr.id = :id
        """), {"id": return_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "tax_return_not_found"))
        if row.branch_id:
            validate_branch_access(current_user, row.branch_id)

        result = dict(row._mapping)

        # Get payments
        payments = db.execute(text("""
            SELECT tp.*, cu.username as created_by_name
            FROM tax_payments tp
            LEFT JOIN company_users cu ON tp.created_by = cu.id
            WHERE tp.tax_return_id = :id
            ORDER BY tp.payment_date DESC
        """), {"id": return_id}).fetchall()
        result["payments"] = [dict(p._mapping) for p in payments]
        paid_amount = sum((_dec(p.amount) for p in payments if p.status == "confirmed"), Decimal("0"))
        remaining_amount = _dec(result.get("total_amount", 0)) - paid_amount
        result["paid_amount"] = str(paid_amount.quantize(_D2, ROUND_HALF_UP))
        result["remaining_amount"] = str(remaining_amount.quantize(_D2, ROUND_HALF_UP))

        return result


@router.post("/returns", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_return(
    request: Request,
    data: TaxReturnCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء إقرار ضريبي جديد — يحسب المبالغ تلقائياً من الفواتير"""
    branch_id = validate_branch_access(current_user, data.branch_id)
    with transactional(current_user.company_id) as db:
        try:
            idempotency_key = get_idempotency_key(
                request,
                fallback=f"tax-return:{data.tax_type}:{data.tax_period}:branch:{branch_id or 'all'}",
            )
            existing_by_key = db.execute(text(
                "SELECT id, return_number FROM tax_returns WHERE idempotency_key = :key LIMIT 1"
            ), {"key": idempotency_key}).fetchone()
            if existing_by_key:
                return {
                    "success": True,
                    "id": existing_by_key.id,
                    "return_number": existing_by_key.return_number,
                    "message": i18n_message("tax_return_found_duplicate", request),
                    "idempotent": True,
                }

            period = data.tax_period
            if "-Q" in period:
                year, q = period.split("-Q")
                quarter = int(q)
                month_start = (quarter - 1) * 3 + 1
                month_end = quarter * 3
                start_date = f"{year}-{month_start:02d}-01"
                if month_end == 12:
                    end_date = f"{int(year) + 1}-01-01"
                else:
                    end_date = f"{year}-{month_end + 1:02d}-01"
            else:
                parts = period.split("-")
                year, month = int(parts[0]), int(parts[1])
                start_date = f"{year}-{month:02d}-01"
                if month == 12:
                    end_date = f"{year + 1}-01-01"
                else:
                    end_date = f"{year}-{month + 1:02d}-01"

            check_fiscal_period_open(db, end_date)
    
            params = {"start": start_date, "end": end_date}
            branch_filter = ""
            if branch_id:
                branch_filter = "AND i.branch_id = :branch_id"
                params["branch_id"] = branch_id
    
            # Check for duplicate
            dup = db.execute(text(
                """
                SELECT 1
                FROM tax_returns
                WHERE tax_period = :period
                  AND tax_type = :type
                  AND COALESCE(branch_id, 0) = COALESCE(:branch_id, 0)
                  AND status != 'cancelled'
                """
            ), {"period": period, "type": data.tax_type, "branch_id": branch_id}).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail=i18n_message("tax_return_already_exists_period", request))
    
            # Output VAT (sales) — aggregate at invoice level to respect header discounts
            output = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT
                    COALESCE(SUM(inv.taxable_amount), 0) as taxable,
                    COALESCE(SUM(inv.vat_amount), 0) as vat
                FROM (
                    SELECT
                        i.id,
                        ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                        (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                    FROM invoices i
                    WHERE i.invoice_type = 'sales'
                      AND i.status NOT IN ('draft', 'cancelled')
                      AND i.invoice_date >= :start AND i.invoice_date < :end
                      {branch_filter}
                ) inv
            """), params).fetchone()
    
            # Sales returns — aggregate at invoice level
            output_returns = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT
                    COALESCE(SUM(inv.taxable_amount), 0) as taxable,
                    COALESCE(SUM(inv.vat_amount), 0) as vat
                FROM (
                    SELECT
                        i.id,
                        ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                        (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                    FROM invoices i
                    WHERE i.invoice_type = 'sales_return'
                      AND i.status NOT IN ('draft', 'cancelled')
                      AND i.invoice_date >= :start AND i.invoice_date < :end
                      {branch_filter}
                ) inv
            """), params).fetchone()
    
            # Input VAT (purchases) — aggregate at invoice level
            input_vat = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT
                    COALESCE(SUM(inv.taxable_amount), 0) as taxable,
                    COALESCE(SUM(inv.vat_amount), 0) as vat
                FROM (
                    SELECT
                        i.id,
                        ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                        (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                    FROM invoices i
                    WHERE i.invoice_type = 'purchase'
                      AND i.status NOT IN ('draft', 'cancelled')
                      AND i.invoice_date >= :start AND i.invoice_date < :end
                      {branch_filter}
                ) inv
            """), params).fetchone()
    
            # Purchase returns — aggregate at invoice level
            input_returns = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT
                    COALESCE(SUM(inv.taxable_amount), 0) as taxable,
                    COALESCE(SUM(inv.vat_amount), 0) as vat
                FROM (
                    SELECT
                        i.id,
                        ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                        (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                    FROM invoices i
                    WHERE i.invoice_type = 'purchase_return'
                      AND i.status NOT IN ('draft', 'cancelled')
                      AND i.invoice_date >= :start AND i.invoice_date < :end
                      {branch_filter}
                ) inv
            """), params).fetchone()
    
            net_output_vat = _dec(output.vat) - _dec(output_returns.vat)
            net_input_vat = _dec(input_vat.vat) - _dec(input_returns.vat)
            taxable_amount = _dec(output.taxable) - _dec(output_returns.taxable)
            tax_amount = net_output_vat - net_input_vat
    
            return_number = generate_sequential_number(db, "TR", "tax_returns", "return_number")
    
            # Resolve jurisdiction from branch
            jurisdiction_code = None
            if branch_id:
                br_row = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
                if br_row and br_row.country_code:
                    jurisdiction_code = br_row.country_code
            if not jurisdiction_code:
                cs_row = db.execute(text("SELECT setting_value FROM company_settings WHERE setting_key = 'company_country'")).fetchone()
                if cs_row:
                    jurisdiction_code = cs_row.setting_value

            base_currency = get_base_currency(db)
            details = {
                "version": CALCULATION_VERSION,
                "period_start": start_date,
                "period_end": end_date,
                "branch_id": branch_id,
                "source": "invoice_lines",
                "method": "net_output_vat_minus_net_input_vat",
                "amount_currency": base_currency,
                "currency_method": "invoice amounts converted to company base currency using locked invoice exchange_rate",
                "inputs": {
                    "output_vat": money_str(net_output_vat),
                    "input_vat": money_str(net_input_vat),
                    "taxable_amount": money_str(taxable_amount),
                },
            }
    
            result = db.execute(text("""
                INSERT INTO tax_returns (return_number, tax_period, tax_type, taxable_amount, tax_amount,
                                         penalty_amount, interest_amount, total_amount, due_date,
                                         status, notes, created_by, branch_id, jurisdiction_code,
                                         currency, base_currency, display_currency, exchange_rate,
                                         calculation_version, calculation_details, idempotency_key)
                VALUES (:num, :period, :type, :taxable, :tax, 0, 0, :total, :due,
                        'draft', :notes, :user, :bid, :jc,
                        :currency, :base_currency, :display_currency, 1,
                        :calc_version, CAST(:calc_details AS jsonb), :idempotency_key)
                RETURNING id
            """), {
                "num": return_number, "period": period, "type": data.tax_type,
                "taxable": q_money(taxable_amount),
                "tax": q_money(tax_amount),
                "total": q_money(tax_amount),
                "due": data.due_date, "notes": data.notes, "user": current_user.id,
                "bid": branch_id, "jc": jurisdiction_code,
                "currency": base_currency,
                "base_currency": base_currency,
                "display_currency": base_currency,
                "calc_version": CALCULATION_VERSION,
                "calc_details": json.dumps(details),
                "idempotency_key": idempotency_key,
            })
            new_id = result.fetchone()[0]
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.return.create", resource_type="tax_return",
                         resource_id=str(new_id),
                         details={"period": period, "tax_amount": money_str(tax_amount), "return_number": return_number},
                         request=request)
    
            return {
                "success": True, "id": new_id, "return_number": return_number,
                "message": i18n_message("tax_return_created_success", request),
                "summary": {
                    "output_vat": str(net_output_vat.quantize(_D2, ROUND_HALF_UP)),
                    "input_vat": str(net_input_vat.quantize(_D2, ROUND_HALF_UP)),
                    "net_payable": str(tax_amount.quantize(_D2, ROUND_HALF_UP)),
                    "taxable_amount": str(taxable_amount.quantize(_D2, ROUND_HALF_UP))
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating tax return: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/returns/{return_id}/file", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def file_tax_return(
    return_id: int, request: Request,
    body: dict = None,
    current_user: dict = Depends(get_current_user)
):
    """تقديم الإقرار الضريبي (تغيير الحالة من draft إلى filed)"""
    with transactional(current_user.company_id) as db:
        try:
            row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id FOR UPDATE"), {"id": return_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_return_not_found"))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            if row.status != "draft":
                raise HTTPException(**http_error(400, "tax_return_only_draft_submittable", request))

            check_fiscal_period_open(db, date.today())
    
            penalty = _dec((body or {}).get("penalty_amount", 0)).quantize(_D2, ROUND_HALF_UP)
            interest = _dec((body or {}).get("interest_amount", 0)).quantize(_D2, ROUND_HALF_UP)
            total = (_dec(row.tax_amount) + penalty + interest).quantize(_D2, ROUND_HALF_UP)
    
            db.execute(text("""
                UPDATE tax_returns SET status = 'filed', filed_date = CURRENT_DATE,
                    penalty_amount = :penalty, interest_amount = :interest,
                    total_amount = :total, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": return_id, "penalty": penalty, "interest": interest, "total": total})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.return.file", resource_type="tax_return",
                         resource_id=str(return_id),
                         details={"return_number": row.return_number, "total": money_str(total)},
                         request=request)
    
            return {
                "success": True,
                "message": i18n_message("tax_return_submitted_success", request),
                "status": "filed",
                "filed_date": str(date.today()),
                "total_amount": str(total)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/returns/{return_id}/cancel", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def cancel_tax_return(return_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """إلغاء إقرار ضريبي"""
    with transactional(current_user.company_id) as db:
        try:
            row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id FOR UPDATE"), {"id": return_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_return_not_found"))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            if row.status == "paid":
                raise HTTPException(**http_error(400, "tax_return_paid_cannot_cancel", request))
    
            has_payments = db.execute(text(
                "SELECT 1 FROM tax_payments WHERE tax_return_id = :id AND status = 'confirmed'"
            ), {"id": return_id}).fetchone()
            if has_payments:
                raise HTTPException(**http_error(400, "tax_return_confirmed_payments_cannot_cancel", request))
    
            check_fiscal_period_open(db, date.today())

            db.execute(text("UPDATE tax_returns SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": return_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.return.cancel", resource_type="tax_return",
                         resource_id=str(return_id), details={"return_number": row.return_number},
                         request=request)
    
            return {"success": True, "message": i18n_message("tax_return_cancelled", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ==================== TAX PAYMENTS ====================
