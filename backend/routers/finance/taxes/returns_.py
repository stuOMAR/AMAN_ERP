"""taxes sub-router — split from monolithic taxes.py (T6.3).

Mounted under the parent router via taxes/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging
import json
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.tax_precision import CALCULATION_VERSION, money_str, q_money, require_idempotency_key, serialize_tax_row
from schemas.taxes import TaxReturnCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _dec  # noqa: E402


def _tax_period_bounds(period: str, request: Request | None = None) -> tuple[str, str]:
    try:
        if "-Q" in period:
            year_text, quarter_text = period.split("-Q")
            year = int(year_text)
            quarter = int(quarter_text)
            if quarter < 1 or quarter > 4:
                raise ValueError
            month_start = (quarter - 1) * 3 + 1
            month_end = quarter * 3
            start_date = f"{year}-{month_start:02d}-01"
            end_date = f"{year + 1}-01-01" if month_end == 12 else f"{year}-{month_end + 1:02d}-01"
            return start_date, end_date

        year_text, month_text = period.split("-")
        year = int(year_text)
        month = int(month_text)
        if month < 1 or month > 12:
            raise ValueError
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
        return start_date, end_date
    except (TypeError, ValueError):
        raise HTTPException(**http_error(422, "invalid_tax_period", request))


def _calculate_tax_return_preview(db, *, period: str, branch_id: int | None, request: Request | None = None) -> dict[str, Any]:
    start_date, end_date = _tax_period_bounds(period, request)
    params: dict[str, Any] = {"start": start_date, "end": end_date}
    branch_filter = ""
    if branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        params["branch_id"] = branch_id

    vat_out_id = get_mapped_account_id(db, "acc_map_vat_out")
    vat_in_id = get_mapped_account_id(db, "acc_map_vat_in")
    if not vat_out_id or not vat_in_id:
        raise HTTPException(**http_error(400, "input_output_tax_accounts_not_configured", request))

    tax_rows = db.execute(text(  # noqa
        f"""
        SELECT
            jl.account_id,
            COALESCE(SUM(jl.debit), 0) AS debit,
            COALESCE(SUM(jl.credit), 0) AS credit
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        WHERE jl.account_id IN (:vat_out_id, :vat_in_id)
          AND je.status = 'posted'
          AND je.entry_date >= :start AND je.entry_date < :end
          {branch_filter}
        GROUP BY jl.account_id
    """), {**params, "vat_out_id": vat_out_id, "vat_in_id": vat_in_id}).fetchall()

    tax_by_account = {row.account_id: row for row in tax_rows}
    out_row = tax_by_account.get(vat_out_id)
    in_row = tax_by_account.get(vat_in_id)
    net_output_vat = (_dec(out_row.credit) - _dec(out_row.debit)) if out_row else Decimal("0")
    net_input_vat = (_dec(in_row.debit) - _dec(in_row.credit)) if in_row else Decimal("0")

    taxable_amount = db.execute(text(  # noqa
        f"""
        SELECT COALESCE(SUM(jl.credit - jl.debit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE a.account_type = 'revenue'
          AND je.status = 'posted'
          AND je.entry_date >= :start AND je.entry_date < :end
          AND EXISTS (
              SELECT 1
              FROM journal_lines tax_jl
              WHERE tax_jl.journal_entry_id = je.id
                AND tax_jl.account_id = :vat_out_id
          )
          {branch_filter}
    """), {**params, "vat_out_id": vat_out_id}).scalar() or Decimal("0")

    taxable_amount = q_money(taxable_amount)
    net_output_vat = q_money(net_output_vat)
    net_input_vat = q_money(net_input_vat)
    tax_amount = q_money(net_output_vat - net_input_vat)
    base_currency = get_base_currency(db)

    details = {
        "version": CALCULATION_VERSION,
        "period_start": start_date,
        "period_end": end_date,
        "branch_id": branch_id,
        "source": "journal_lines",
        "method": "posted_vat_account_lines_net_output_minus_net_input",
        "amount_currency": base_currency,
        "currency_method": "invoice amounts converted to company base currency using locked invoice exchange_rate",
        "inputs": {
            "output_vat": money_str(net_output_vat),
            "input_vat": money_str(net_input_vat),
            "taxable_amount": money_str(taxable_amount),
        },
    }
    return {
        "period_start": start_date,
        "period_end": end_date,
        "taxable_amount": taxable_amount,
        "tax_amount": tax_amount,
        "total_amount": tax_amount,
        "output_vat": net_output_vat,
        "input_vat": net_input_vat,
        "base_currency": base_currency,
        "details": details,
    }


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

        rows = db.execute(text(  # noqa
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


@router.post("/returns/preview", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=Dict[str, Any])
def preview_tax_return(
    data: TaxReturnCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Preview authoritative VAT return totals before creating the return."""
    branch_id = validate_branch_access(current_user, data.branch_id)
    with transactional(current_user.company_id) as db:
        preview = _calculate_tax_return_preview(db, period=data.tax_period, branch_id=branch_id, request=request)
        return {
            "success": True,
            "tax_period": data.tax_period,
            "tax_type": data.tax_type,
            "branch_id": branch_id,
            "period_start": preview["period_start"],
            "period_end": preview["period_end"],
            "taxable_amount": money_str(preview["taxable_amount"]),
            "tax_amount": money_str(preview["tax_amount"]),
            "submitted_tax_due": money_str(preview["total_amount"]),
            "total_amount": money_str(preview["total_amount"]),
            "currency": preview["base_currency"],
            "summary": {
                "output_vat": money_str(preview["output_vat"]),
                "input_vat": money_str(preview["input_vat"]),
                "net_payable": money_str(preview["tax_amount"]),
                "taxable_amount": money_str(preview["taxable_amount"]),
            },
            "calculation_details": preview["details"],
        }


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
            idempotency_key = require_idempotency_key(
                request,
                operation="tax return create",
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
            preview = _calculate_tax_return_preview(db, period=period, branch_id=branch_id, request=request)
            preview["period_start"]
            end_date = preview["period_end"]

            check_fiscal_period_open(db, end_date)

            submitted_tax_due = data.submitted_tax_due
            if submitted_tax_due is None:
                submitted_tax_due = data.submitted_grand_total
            if submitted_tax_due is None:
                raise HTTPException(**http_error(422, "submitted_tax_due_required", request))
            if q_money(submitted_tax_due) != q_money(preview["total_amount"]):
                raise HTTPException(
                    **http_error(
                        422,
                        "submitted_tax_due_mismatch",
                        request,
                        submitted=money_str(submitted_tax_due),
                        expected=money_str(preview["total_amount"]),
                    )
                )
    
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
            net_output_vat = preview["output_vat"]
            net_input_vat = preview["input_vat"]
            taxable_amount = preview["taxable_amount"]
            tax_amount = preview["tax_amount"]
    
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

            base_currency = preview["base_currency"]
            details = preview["details"]
    
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
            require_idempotency_key(request, operation="tax return file")
            row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id FOR UPDATE"), {"id": return_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_return_not_found"))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            if row.status == "filed":
                return {
                    "success": True,
                    "message": i18n_message("tax_return_submitted_success", request),
                    "status": "filed",
                    "filed_date": str(row.filed_date) if row.filed_date else None,
                    "total_amount": money_str(row.total_amount),
                    "idempotent": True,
                }
            if row.status != "draft":
                raise HTTPException(**http_error(400, "tax_return_only_draft_submittable", request))

            check_fiscal_period_open(db, date.today())
            preview = _calculate_tax_return_preview(
                db,
                period=row.tax_period,
                branch_id=row.branch_id,
                request=request,
            )
            if q_money(row.tax_amount) != q_money(preview["total_amount"]):
                raise HTTPException(
                    **http_error(
                        422,
                        "tax_return_stale_recalculate_required",
                        request,
                        submitted=money_str(row.tax_amount),
                        expected=money_str(preview["total_amount"]),
                    )
                )
            submitted_tax_due = (body or {}).get("submitted_tax_due") or (body or {}).get("submitted_grand_total")
            if submitted_tax_due is None:
                raise HTTPException(**http_error(422, "submitted_tax_due_required", request))
            if q_money(submitted_tax_due) != q_money(preview["total_amount"]):
                raise HTTPException(
                    **http_error(
                        422,
                        "submitted_tax_due_mismatch",
                        request,
                        submitted=money_str(submitted_tax_due),
                        expected=money_str(preview["total_amount"]),
                    )
                )
    
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
            require_idempotency_key(request, operation="tax return cancel")
            row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id FOR UPDATE"), {"id": return_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_return_not_found"))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            if row.status == "cancelled":
                return {
                    "success": True,
                    "message": i18n_message("tax_return_cancelled", request),
                    "idempotent": True,
                }
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
