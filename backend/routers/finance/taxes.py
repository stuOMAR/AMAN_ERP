"""
وحدة الضرائب — AMAN ERP
إدارة أنواع الضرائب، الإقرارات الضريبية، المدفوعات، التسويات، وتقارير VAT
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from datetime import date
from pydantic import BaseModel
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import (
    generate_sequential_number,
    get_mapped_account_id,
    get_base_currency
)
from decimal import Decimal, ROUND_HALF_UP
import logging

router = APIRouter(prefix="/taxes", tags=["Taxes"], dependencies=[Depends(require_module("taxes"))])
logger = logging.getLogger(__name__)
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

# ==================== TAX RATES CRUD ====================

@router.get("/rates", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def list_tax_rates(
    is_active: Optional[bool] = None,
    country_code: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب جميع أنواع الضرائب — مع فلتر اختياري حسب الدولة"""
    db = get_db_connection(current_user.company_id)
    try:
        where = "WHERE 1=1"
        params = {}
        if is_active is not None:
            where += " AND is_active = :active"
            params["active"] = is_active
        if country_code:
            where += " AND (country_code = :cc OR country_code IS NULL)"
            params["cc"] = country_code

        rows = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT id, tax_code, tax_name, tax_name_en, rate_type, rate_value,
                   description, effective_from, effective_to, is_active, country_code, created_at
            FROM tax_rates {where}
            ORDER BY created_at DESC
        """), params).fetchall()

        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def get_tax_rate(rate_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل نوع ضريبة"""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("SELECT * FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "tax_type_not_found"))
        return dict(row._mapping)
    finally:
        db.close()


@router.post("/rates", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))])
def create_tax_rate(
    request: Request,
    data: TaxRateCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء نوع ضريبة جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        exists = db.execute(text("SELECT 1 FROM tax_rates WHERE tax_code = :code"), {"code": data.tax_code}).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="كود الضريبة موجود مسبقاً")

        result = db.execute(text("""
            INSERT INTO tax_rates (tax_code, tax_name, tax_name_en, rate_type, rate_value,
                                   description, effective_from, effective_to, is_active, country_code)
            VALUES (:code, :name, :name_en, :rate_type, :rate_value,
                    :desc, :eff_from, :eff_to, :active, :cc)
            RETURNING id
        """), {
            "code": data.tax_code, "name": data.tax_name, "name_en": data.tax_name_en,
            "rate_type": data.rate_type, "rate_value": data.rate_value,
            "desc": data.description, "eff_from": data.effective_from,
            "eff_to": data.effective_to, "active": data.is_active,
            "cc": data.country_code.upper() if data.country_code else None
        })
        new_id = result.fetchone()[0]
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.rate.create", resource_type="tax_rate",
                     resource_id=str(new_id), details={"tax_code": data.tax_code, "rate": data.rate_value},
                     request=request)

        return {"success": True, "id": new_id, "message": "تم إنشاء نوع الضريبة بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating tax rate: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))])
def update_tax_rate(
    rate_id: int, request: Request, data: TaxRateUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث نوع ضريبة"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT 1 FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "tax_type_not_found"))

        updates = []
        params = {"id": rate_id}
        for field, val in data.dict(exclude_unset=True).items():
            updates.append(f"{field} = :{field}")
            params[field] = val

        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        db.execute(text(f"UPDATE tax_rates SET {', '.join(updates)} WHERE id = :id"), params)  # noqa: sql-lint
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.rate.update", resource_type="tax_rate",
                     resource_id=str(rate_id), details=params, request=request)

        return {"success": True, "message": "تم تحديث نوع الضريبة بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating tax rate: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))])
def delete_tax_rate(rate_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """حذف نوع ضريبة (إيقاف تفعيل فقط)"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT tax_code FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "tax_type_not_found"))

        db.execute(text("UPDATE tax_rates SET is_active = FALSE WHERE id = :id"), {"id": rate_id})
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.rate.delete", resource_type="tax_rate",
                     resource_id=str(rate_id), details={"tax_code": existing.tax_code},
                     request=request)

        return {"success": True, "message": "تم إيقاف نوع الضريبة بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== TAX GROUPS ====================

@router.get("/groups", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def list_tax_groups(current_user: dict = Depends(get_current_user)):
    """جلب مجموعات الضرائب"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT id, group_code, group_name, group_name_en, description, tax_ids, is_active, created_at
            FROM tax_groups ORDER BY created_at DESC
        """)).fetchall()

        result = []
        for r in rows:
            item = dict(r._mapping)
            tax_ids = item.get("tax_ids") or []
            if tax_ids:
                safe_ids = [tid for tid in tax_ids if isinstance(tid, int)]
                if safe_ids:
                    placeholders = ",".join([f":tid_{i}" for i in range(len(safe_ids))])
                    id_params = {f"tid_{i}": tid for i, tid in enumerate(safe_ids)}
                    taxes = db.execute(text(f"SELECT id, tax_name, rate_value FROM tax_rates WHERE id IN ({placeholders})"), id_params).fetchall()  # noqa: sql-lint
                    item["taxes"] = [dict(t._mapping) for t in taxes]
                    combined_rate = sum((_dec(t.rate_value) for t in taxes), Decimal("0"))
                    item["combined_rate"] = float(combined_rate.quantize(_D4, ROUND_HALF_UP))
                else:
                    item["taxes"] = []
                    item["combined_rate"] = 0
            else:
                item["taxes"] = []
                item["combined_rate"] = 0
            result.append(item)

        return result
    finally:
        db.close()


@router.post("/groups", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))])
def create_tax_group(request: Request, data: TaxGroupCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء مجموعة ضريبية جديدة"""
    db = get_db_connection(current_user.company_id)
    try:
        exists = db.execute(text("SELECT 1 FROM tax_groups WHERE group_code = :code"), {"code": data.group_code}).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="كود المجموعة موجود مسبقاً")

        import json
        result = db.execute(text("""
            INSERT INTO tax_groups (group_code, group_name, group_name_en, description, tax_ids, is_active)
            VALUES (:code, :name, :name_en, :desc, CAST(:tax_ids AS jsonb), :active)
            RETURNING id
        """), {
            "code": data.group_code, "name": data.group_name, "name_en": data.group_name_en,
            "desc": data.description, "tax_ids": json.dumps(data.tax_ids), "active": data.is_active
        })
        new_id = result.fetchone()[0]
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.group.create", resource_type="tax_group",
                     resource_id=str(new_id), details={"group_code": data.group_code},
                     request=request)

        return {"success": True, "id": new_id, "message": "تم إنشاء المجموعة الضريبية بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== TAX RETURNS (الإقرارات الضريبية) ====================

@router.get("/returns", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
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
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        where = "WHERE 1=1"
        params = {}
        if status:
            where += " AND tr.status = :status"
            params["status"] = status
        if tax_type:
            where += " AND tr.tax_type = :tax_type"
            params["tax_type"] = tax_type
        if branch_id:
            where += " AND tr.branch_id = :branch_id"
            params["branch_id"] = branch_id
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

        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/returns/{return_id}", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def get_tax_return(return_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل إقرار ضريبي"""
    db = get_db_connection(current_user.company_id)
    try:
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
    finally:
        db.close()


@router.post("/returns", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))])
def create_tax_return(
    request: Request,
    data: TaxReturnCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء إقرار ضريبي جديد — يحسب المبالغ تلقائياً من الفواتير"""
    branch_id = validate_branch_access(current_user, data.branch_id)
    db = get_db_connection(current_user.company_id)
    try:
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

        params = {"start": start_date, "end": end_date}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND i.branch_id = :branch_id"
            params["branch_id"] = branch_id

        # Check for duplicate
        dup = db.execute(text(
            "SELECT 1 FROM tax_returns WHERE tax_period = :period AND tax_type = :type AND status != 'cancelled'"
        ), {"period": period, "type": data.tax_type}).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail=f"يوجد إقرار ضريبي لنفس الفترة ({period}) بالفعل")

        # Output VAT (sales)
        output = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable,
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date >= :start AND i.invoice_date < :end {branch_filter}
        """), params).fetchone()

        # Sales returns
        output_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable,
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date >= :start AND i.invoice_date < :end {branch_filter}
        """), params).fetchone()

        # Input VAT (purchases)
        input_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable,
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date >= :start AND i.invoice_date < :end {branch_filter}
        """), params).fetchone()

        # Purchase returns
        input_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable,
                COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date >= :start AND i.invoice_date < :end {branch_filter}
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

        result = db.execute(text("""
            INSERT INTO tax_returns (return_number, tax_period, tax_type, taxable_amount, tax_amount,
                                     penalty_amount, interest_amount, total_amount, due_date,
                                     status, notes, created_by, branch_id, jurisdiction_code)
            VALUES (:num, :period, :type, :taxable, :tax, 0, 0, :total, :due, 'draft', :notes, :user, :bid, :jc)
            RETURNING id
        """), {
            "num": return_number, "period": period, "type": data.tax_type,
            "taxable": float(taxable_amount.quantize(_D2, ROUND_HALF_UP)),
            "tax": float(tax_amount.quantize(_D2, ROUND_HALF_UP)),
            "total": float(tax_amount.quantize(_D2, ROUND_HALF_UP)),
            "due": data.due_date, "notes": data.notes, "user": current_user.id,
            "bid": branch_id, "jc": jurisdiction_code
        })
        new_id = result.fetchone()[0]
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.return.create", resource_type="tax_return",
                     resource_id=str(new_id),
                     details={"period": period, "tax_amount": float(tax_amount.quantize(_D2, ROUND_HALF_UP)), "return_number": return_number},
                     request=request)

        return {
            "success": True, "id": new_id, "return_number": return_number,
            "message": "تم إنشاء الإقرار الضريبي بنجاح",
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
        db.rollback()
        logger.error(f"Error creating tax return: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/returns/{return_id}/file", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))])
def file_tax_return(
    return_id: int, request: Request,
    body: dict = None,
    current_user: dict = Depends(get_current_user)
):
    """تقديم الإقرار الضريبي (تغيير الحالة من draft إلى filed)"""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id"), {"id": return_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "tax_return_not_found"))
        if row.branch_id:
            validate_branch_access(current_user, row.branch_id)
        if row.status != "draft":
            raise HTTPException(status_code=400, detail="لا يمكن تقديم إقرار غير في حالة مسودة")

        penalty = _dec((body or {}).get("penalty_amount", 0)).quantize(_D2, ROUND_HALF_UP)
        interest = _dec((body or {}).get("interest_amount", 0)).quantize(_D2, ROUND_HALF_UP)
        total = (_dec(row.tax_amount) + penalty + interest).quantize(_D2, ROUND_HALF_UP)

        db.execute(text("""
            UPDATE tax_returns SET status = 'filed', filed_date = CURRENT_DATE,
                penalty_amount = :penalty, interest_amount = :interest, total_amount = :total
            WHERE id = :id
        """), {"id": return_id, "penalty": float(penalty), "interest": float(interest), "total": float(total)})
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.return.file", resource_type="tax_return",
                     resource_id=str(return_id),
                     details={"return_number": row.return_number, "total": float(total)},
                     request=request)

        return {
            "success": True,
            "message": "تم تقديم الإقرار الضريبي بنجاح",
            "status": "filed",
            "filed_date": str(date.today()),
            "total_amount": str(total)
        }
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/returns/{return_id}/cancel", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))])
def cancel_tax_return(return_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """إلغاء إقرار ضريبي"""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("SELECT * FROM tax_returns WHERE id = :id"), {"id": return_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "tax_return_not_found"))
        if row.branch_id:
            validate_branch_access(current_user, row.branch_id)
        if row.status == "paid":
            raise HTTPException(status_code=400, detail="لا يمكن إلغاء إقرار مدفوع")

        has_payments = db.execute(text(
            "SELECT 1 FROM tax_payments WHERE tax_return_id = :id AND status = 'confirmed'"
        ), {"id": return_id}).fetchone()
        if has_payments:
            raise HTTPException(status_code=400, detail="لا يمكن إلغاء إقرار له مدفوعات مؤكدة")

        db.execute(text("UPDATE tax_returns SET status = 'cancelled' WHERE id = :id"), {"id": return_id})
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.return.cancel", resource_type="tax_return",
                     resource_id=str(return_id), details={"return_number": row.return_number},
                     request=request)

        return {"success": True, "message": "تم إلغاء الإقرار الضريبي"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== TAX PAYMENTS ====================

@router.get("/payments", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def list_tax_payments(
    tax_return_id: Optional[int] = None,
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب مدفوعات الضرائب مع فلترة حسب الفرع والسنة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        where = "WHERE 1=1"
        params = {}
        if tax_return_id:
            where += " AND tp.tax_return_id = :return_id"
            params["return_id"] = tax_return_id
        if status:
            where += " AND tp.status = :status"
            params["status"] = status
        if branch_id:
            where += " AND tr.branch_id = :branch_id"
            params["branch_id"] = branch_id
        if year:
            where += " AND EXTRACT(YEAR FROM tp.payment_date) = :year"
            params["year"] = year

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT tp.*, tr.return_number, tr.tax_period, tr.tax_type,
                   tr.branch_id, tr.jurisdiction_code,
                   b.branch_name,
                   cu.username as created_by_name
            FROM tax_payments tp
            JOIN tax_returns tr ON tp.tax_return_id = tr.id
            LEFT JOIN branches b ON tr.branch_id = b.id
            LEFT JOIN company_users cu ON tp.created_by = cu.id
            {where}
            ORDER BY tp.payment_date DESC
        """), params).fetchall()

        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/payments", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))])
def create_tax_payment(
    request: Request,
    data: TaxPaymentCreate,
    current_user: dict = Depends(get_current_user)
):
    """تسجيل دفعة ضريبية مع قيد محاسبي تلقائي"""
    db = get_db_connection(current_user.company_id)
    try:
        tr = db.execute(text("SELECT * FROM tax_returns WHERE id = :id"), {"id": data.tax_return_id}).fetchone()
        if not tr:
            raise HTTPException(**http_error(404, "tax_return_not_found"))
        if tr.status in ("cancelled", "draft"):
            raise HTTPException(status_code=400, detail="لا يمكن الدفع على إقرار ملغى أو مسودة. يجب تقديمه أولاً")

        paid = db.execute(text(
            "SELECT COALESCE(SUM(amount), 0) FROM tax_payments WHERE tax_return_id = :id AND status = 'confirmed'"
        ), {"id": data.tax_return_id}).scalar()
        remaining = (_dec(tr.total_amount) - _dec(paid)).quantize(_D2, ROUND_HALF_UP)
        amount_dec = _dec(data.amount).quantize(_D2, ROUND_HALF_UP)
        if amount_dec > (remaining + _D2):
            raise HTTPException(status_code=400, detail=f"المبلغ يتجاوز المتبقي ({float(remaining):.2f})")

        payment_number = generate_sequential_number(db, "TP", "tax_payments", "payment_number")

        result = db.execute(text("""
            INSERT INTO tax_payments (payment_number, tax_return_id, payment_date, amount,
                                      payment_method, reference, status, notes, created_by)
            VALUES (:num, :return_id, :date, :amount, :method, :ref, 'confirmed', :notes, :user)
            RETURNING id
        """), {
            "num": payment_number, "return_id": data.tax_return_id,
            "date": data.payment_date, "amount": data.amount,
            "method": data.payment_method, "ref": data.reference,
            "notes": data.notes, "user": current_user.id
        })
        new_id = result.fetchone()[0]

        # ===== ACCOUNTING INTEGRATION =====
        # ACC-F (Phase 5 / TAX-F01): enforce fiscal lock on tax payment posting
        check_fiscal_period_open(db, data.payment_date)

        vat_account_id = get_mapped_account_id(db, "acc_map_vat_out")
        if not vat_account_id:
            raise HTTPException(status_code=400, detail="حساب ضريبة المخرجات (VAT Output) غير محدد في الإعدادات")

        bank_account_id = None
        if data.treasury_account_id:
            bank_row = db.execute(text(
                "SELECT gl_account_id FROM treasury_accounts WHERE id = :id"
            ), {"id": data.treasury_account_id}).fetchone()
            if bank_row:
                bank_account_id = bank_row.gl_account_id

        if not bank_account_id:
            bank_row = db.execute(text(
                "SELECT gl_account_id FROM treasury_accounts WHERE is_active = true AND gl_account_id IS NOT NULL LIMIT 1"
            )).fetchone()
            if bank_row:
                bank_account_id = bank_row.gl_account_id

        if vat_account_id and bank_account_id:
            base_currency = get_base_currency(db)
            
            je_lines = [
                {
                    "account_id": vat_account_id, "debit": float(amount_dec), "credit": 0,
                    "description": f"دفع ضريبة — {tr.tax_period}"
                },
                {
                    "account_id": bank_account_id, "debit": 0, "credit": float(amount_dec),
                    "description": f"دفع ضريبة — {tr.tax_period}"
                }
            ]
            
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, entry_number = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data.payment_date,
                description=f"دفع ضريبة — إقرار {tr.return_number} — فترة {tr.tax_period}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=tr.branch_id,
                reference=payment_number,
                currency=base_currency,
                exchange_rate=1.0,
                source="tax_payment",
                source_id=new_id
            )

        # Update return status if fully paid
        new_paid = (_dec(paid) + amount_dec).quantize(_D2, ROUND_HALF_UP)
        if new_paid >= (_dec(tr.total_amount).quantize(_D2, ROUND_HALF_UP) - _D2):
            db.execute(text("UPDATE tax_returns SET status = 'paid' WHERE id = :id"), {"id": data.tax_return_id})

        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.payment.create", resource_type="tax_payment",
                     resource_id=str(new_id),
                     details={"payment_number": payment_number, "amount": data.amount, "return": tr.return_number},
                     request=request)

        return {"success": True, "id": new_id, "payment_number": payment_number,
                "message": "تم تسجيل الدفعة الضريبية بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating tax payment: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== VAT REPORT ====================

@router.get("/vat-report", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
def get_vat_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب تقرير ضريبة القيمة المضافة للفترة المحددة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        output_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        input_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        output_vat_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        input_vat_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        net_output_taxable = (_dec(output_vat.taxable_amount) - _dec(output_vat_returns.taxable_amount)).quantize(_D2, ROUND_HALF_UP)
        net_output_vat = (_dec(output_vat.vat_amount) - _dec(output_vat_returns.vat_amount)).quantize(_D2, ROUND_HALF_UP)
        net_input_taxable = (_dec(input_vat.taxable_amount) - _dec(input_vat_returns.taxable_amount)).quantize(_D2, ROUND_HALF_UP)
        net_input_vat = (_dec(input_vat.vat_amount) - _dec(input_vat_returns.vat_amount)).quantize(_D2, ROUND_HALF_UP)
        net_vat_payable = (net_output_vat - net_input_vat).quantize(_D2, ROUND_HALF_UP)

        return {
            "period": {"start": start_date, "end": end_date},
            "output_vat": {"taxable": str(net_output_taxable), "vat": str(net_output_vat)},
            "input_vat": {"taxable": str(net_input_taxable), "vat": str(net_input_vat)},
            "net_vat_payable": str(net_vat_payable)
        }
    finally:
        db.close()


# ==================== TAX AUDIT ====================

@router.get("/audit-report", response_model=List[dict], dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
def get_tax_audit(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تدقيق ضريبي مفصل لكل معاملة خاضعة للضريبة بالفترة"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = "AND i.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        results = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT i.id, i.invoice_number, i.invoice_date, i.invoice_type,
                p.name as party_name, p.tax_number,
                SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate) as taxable_amount,
                SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)) as vat_amount
            FROM invoices i
            JOIN invoice_lines il ON i.id = il.invoice_id
            LEFT JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND il.tax_rate > 0 AND i.status != 'draft'
              {branch_filter}
            GROUP BY i.id, i.invoice_number, i.invoice_date, i.invoice_type, p.name, p.tax_number
            ORDER BY i.invoice_date DESC
        """), params).fetchall()

        return [
            {
                "id": r.id, "number": r.invoice_number, "date": r.invoice_date,
                "type": r.invoice_type, "party": r.party_name, "tax_number": r.tax_number,
                "taxable": str(_dec(r.taxable_amount or 0).quantize(_D2, ROUND_HALF_UP)), "vat": str(_dec(r.vat_amount or 0).quantize(_D2, ROUND_HALF_UP))
            }
            for r in results
        ]
    finally:
        db.close()


# ==================== TAX SUMMARY ====================

@router.get("/summary", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def get_tax_summary(
    branch_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص وحدة الضرائب (لوحة تحكم) مع فلترة حسب الفرع"""
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        # ── Branch/country aware rates count ──
        rate_where = "WHERE is_active = TRUE"
        rate_params = {}
        if branch_id:
            # Get branch country_code for filtering rates
            br = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
            if br and br.country_code:
                rate_where += " AND (country_code = :cc OR country_code IS NULL)"
                rate_params["cc"] = br.country_code
        rates_count = db.execute(text(f"SELECT COUNT(*) FROM tax_rates {rate_where}"), rate_params).scalar() or 0  # noqa: sql-lint

        # ── Returns stats with branch filter ──
        ret_where = "WHERE status != 'cancelled'"
        ret_params = {}
        if branch_id:
            ret_where += " AND branch_id = :branch_id"
            ret_params["branch_id"] = branch_id
        if year:
            ret_where += " AND tax_period LIKE :yp"
            ret_params["yp"] = f"{year}%"

        returns_stats = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status = 'filed') as filed,
                COUNT(*) FILTER (WHERE status = 'paid') as paid,
                COALESCE(SUM(total_amount) FILTER (WHERE status = 'filed'), 0) as pending_amount,
                COALESCE(SUM(total_amount) FILTER (WHERE status = 'paid'), 0) as paid_amount
            FROM tax_returns {ret_where}
        """), ret_params).fetchone()

        today = date.today()
        first_of_month = today.replace(day=1)
        vat_params = {"start": first_of_month, "end": today}
        vat_branch_filter = ""
        if branch_id:
            vat_branch_filter = "AND i.branch_id = :branch_id"
            vat_params["branch_id"] = branch_id

        current_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales' THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100) ELSE 0 END), 0) as output_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase' THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100) ELSE 0 END), 0) as input_vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_date >= :start AND i.invoice_date <= :end
            AND i.status NOT IN ('draft', 'cancelled') AND il.tax_rate > 0
            {vat_branch_filter}
        """), vat_params).fetchone()

        overdue_where = "WHERE status = 'filed' AND due_date < CURRENT_DATE"
        overdue_params = {}
        if branch_id:
            overdue_where += " AND branch_id = :branch_id"
            overdue_params["branch_id"] = branch_id
        overdue = db.execute(text(f"SELECT COUNT(*) FROM tax_returns {overdue_where}"), overdue_params).scalar() or 0  # noqa: sql-lint

        # ── Employee tax summary (withholding from payroll) ──
        emp_tax = {"total_employees": 0, "total_salary_tax": 0, "total_gosi": 0}
        try:
            emp_where = ""
            emp_params = {}
            if branch_id:
                emp_where = "AND e.branch_id = :branch_id"
                emp_params["branch_id"] = branch_id
            emp_row = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COUNT(DISTINCT pe.employee_id) as total_employees,
                       COALESCE(SUM(pe.gosi_employee_share), 0) as total_gosi,
                       COALESCE(SUM(pe.net_salary - pe.basic_salary), 0) as total_deductions
                FROM payroll_entries pe
                JOIN employees e ON pe.employee_id = e.id
                WHERE pe.status IN ('approved', 'paid') {emp_where}
            """), emp_params).fetchone()
            if emp_row:
                emp_tax["total_employees"] = emp_row.total_employees or 0
                emp_tax["total_gosi"] = float(emp_row.total_gosi or 0)
        except Exception:
            pass  # payroll tables may not exist yet

        return {
            "active_rates": rates_count,
            "returns": {
                "total": returns_stats.total or 0, "draft": returns_stats.draft or 0,
                "filed": returns_stats.filed or 0, "paid": returns_stats.paid or 0,
                "pending_amount": str(_dec(returns_stats.pending_amount or 0).quantize(_D2, ROUND_HALF_UP)),
                "paid_amount": str(_dec(returns_stats.paid_amount or 0).quantize(_D2, ROUND_HALF_UP))
            },
            "current_period": {
                "output_vat": str(_dec(current_vat.output_vat or 0).quantize(_D2, ROUND_HALF_UP)),
                "input_vat": str(_dec(current_vat.input_vat or 0).quantize(_D2, ROUND_HALF_UP)),
                "net_vat": str((_dec(current_vat.output_vat) - _dec(current_vat.input_vat)).quantize(_D2, ROUND_HALF_UP))
            },
            "overdue_returns": overdue,
            "employee_taxes": emp_tax,
            "branch_id": branch_id,
        }
    finally:
        db.close()


# ==================== TAX SETTLEMENT ====================

@router.post("/settle", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))])
def create_tax_settlement(
    request: Request, body: dict,
    current_user: dict = Depends(get_current_user)
):
    """تسوية ضريبية — قيد محاسبي لتسوية رصيد ضريبة المدخلات مع المخرجات"""
    db = get_db_connection(current_user.company_id)
    try:
        start = body.get("period_start")
        end = body.get("period_end")
        branch_id = validate_branch_access(current_user, body.get("branch_id"))

        if not start or not end:
            raise HTTPException(status_code=400, detail="يجب تحديد فترة التسوية")

        params = {"start": start, "end": end}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND i.branch_id = :branch_id"
            params["branch_id"] = branch_id

        output = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft','cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        # T3.6 (audit #18): output VAT must be NET of sales returns; otherwise
        # we settle more than the company actually owes the tax authority.
        output_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft','cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        input_v = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft','cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        # T3.6 (audit #18): input VAT must be NET of purchase returns.
        input_returns = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft','cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        output_dec = (_dec(output) - _dec(output_returns)).quantize(_D2, ROUND_HALF_UP)
        input_dec = (_dec(input_v) - _dec(input_returns)).quantize(_D2, ROUND_HALF_UP)
        net = (output_dec - input_dec).quantize(_D2, ROUND_HALF_UP)

        vat_out_id = get_mapped_account_id(db, "acc_map_vat_out")
        vat_in_id = get_mapped_account_id(db, "acc_map_vat_in")

        if not vat_out_id or not vat_in_id:
            raise HTTPException(status_code=400, detail="حسابات ضريبة المدخلات/المخرجات غير معينة في الإعدادات")

        base_currency = get_base_currency(db)
        settle_amount = min(output_dec, input_dec)
        
        entry_number = None
        if settle_amount > Decimal("0"):
            # Fiscal-period lock: tax settlement posts at today's date.
            check_fiscal_period_open(db, date.today())

            je_lines = [
                {
                    "account_id": vat_out_id, "debit": float(settle_amount), "credit": 0,
                    "description": "تسوية ضريبة المخرجات"
                },
                {
                    "account_id": vat_in_id, "debit": 0, "credit": float(settle_amount),
                    "description": "تسوية ضريبة المدخلات مع المخرجات"
                }
            ]
            
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, entry_number = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=date.today().isoformat(),
                description=f"تسوية ضريبية — الفترة {start} إلى {end}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=f"TAX-SETTLE-{start}-{end}",
                currency=base_currency,
                exchange_rate=1.0,
                source="tax_settlement"
            )

        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.settlement.create", resource_type="tax_settlement",
                     resource_id=entry_number,
                     details={"period": f"{start} - {end}", "net": float(net), "je": entry_number},
                     request=request)

        return {
            "success": True, "message": "تم إنشاء التسوية الضريبية بنجاح",
            "journal_entry": entry_number,
            "output_vat": float(output_dec), "input_vat": float(input_dec),
            "net_amount": float(net),
            "settlement_type": "payable" if net >= Decimal("0") else "refundable"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating tax settlement: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== BRANCH TAX ANALYSIS ====================

@router.get("/branch-analysis", dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
def get_branch_tax_analysis(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تحليل ضريبي مفصل حسب الفرع — يعرض VAT مقسم لكل فرع
    يستخدم هذا التقرير لمعرفة حجم الالتزامات الضريبية لكل فرع
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not start_date:
            start_date = date.today().replace(month=1, day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = ""
        if branch_id:
            branch_filter = "AND i.branch_id = :branch_id"
            params["branch_id"] = branch_id

        rows = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT 
                b.id as branch_id, b.branch_name, b.branch_name_en,
                b.country_code as jurisdiction,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales'
                    THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100) ELSE 0 END), 0) as output_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase'
                    THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100) ELSE 0 END), 0) as input_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales'
                    THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate ELSE 0 END), 0) as taxable_sales,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase'
                    THEN (il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate ELSE 0 END), 0) as taxable_purchases,
                COUNT(DISTINCT i.id) as invoice_count
            FROM invoices i
            JOIN invoice_lines il ON i.id = il.invoice_id
            JOIN branches b ON i.branch_id = b.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND i.status NOT IN ('draft', 'cancelled')
              AND il.tax_rate > 0
              {branch_filter}
            GROUP BY b.id, b.branch_name, b.branch_name_en, b.country_code
            ORDER BY output_vat DESC
        """), params).fetchall()

        # Get return stats per branch
        ret_params = {"year_prefix": str(start_date.year) + "%"}
        ret_branch_filter = ""
        if branch_id:
            ret_branch_filter = "AND tr.branch_id = :branch_id"
            ret_params["branch_id"] = branch_id

        returns_by_branch = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT tr.branch_id,
                   COUNT(*) as returns_count,
                   COUNT(*) FILTER (WHERE tr.status = 'filed') as filed,
                   COUNT(*) FILTER (WHERE tr.status = 'paid') as paid,
                   COUNT(*) FILTER (WHERE tr.status = 'draft') as draft,
                   COALESCE(SUM(tr.total_amount), 0) as total_tax
            FROM tax_returns tr
            WHERE tr.status != 'cancelled'
              AND tr.tax_period LIKE :year_prefix
              {ret_branch_filter}
            GROUP BY tr.branch_id
        """), ret_params).fetchall()

        ret_map = {r.branch_id: dict(r._mapping) for r in returns_by_branch}

        result = []
        grand_output = Decimal("0")
        grand_input = Decimal("0")

        for r in rows:
            out = _dec(r.output_vat).quantize(_D2, ROUND_HALF_UP)
            inp = _dec(r.input_vat).quantize(_D2, ROUND_HALF_UP)
            net = (out - inp).quantize(_D2, ROUND_HALF_UP)
            grand_output += out
            grand_input += inp
            ret_info = ret_map.get(r.branch_id, {})

            result.append({
                "branch_id": r.branch_id,
                "branch_name": r.branch_name,
                "branch_name_en": r.branch_name_en,
                "jurisdiction": r.jurisdiction or "SA",
                "output_vat": float(out),
                "input_vat": float(inp),
                "net_vat": float(net),
                "taxable_sales": float(r.taxable_sales or 0),
                "taxable_purchases": float(r.taxable_purchases or 0),
                "invoice_count": r.invoice_count,
                "returns_count": ret_info.get("returns_count", 0),
                "returns_filed": ret_info.get("filed", 0),
                "returns_paid": ret_info.get("paid", 0),
                "returns_draft": ret_info.get("draft", 0),
            })

        return {
            "period": {"start": start_date, "end": end_date},
            "branches": result,
            "totals": {
                "output_vat": float(grand_output.quantize(_D2, ROUND_HALF_UP)),
                "input_vat": float(grand_input.quantize(_D2, ROUND_HALF_UP)),
                "net_vat": float((grand_output - grand_input).quantize(_D2, ROUND_HALF_UP)),
                "branch_count": len(result)
            }
        }
    finally:
        db.close()


# ==================== EMPLOYEE TAX OBLIGATIONS ====================

@router.get("/employee-taxes", dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "hr.view"]))])
def get_employee_tax_obligations(
    branch_id: Optional[int] = None,
    department_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير الالتزامات الضريبية للموظفين
    يشمل: ضريبة الدخل على الرواتب، التأمينات الاجتماعية (GOSI)، استقطاع ضريبي
    يمكن الفلترة حسب الفرع، القسم، الموظف، والسنة
    """
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not year:
            year = date.today().year

        where_parts = ["pe.status IN ('approved', 'paid')"]
        params = {"year": year}
        if branch_id:
            where_parts.append("e.branch_id = :branch_id")
            params["branch_id"] = branch_id
        if department_id:
            where_parts.append("e.department_id = :department_id")
            params["department_id"] = department_id
        if employee_id:
            where_parts.append("e.id = :employee_id")
            params["employee_id"] = employee_id

        where = " AND ".join(where_parts)

        employees = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT 
                e.id as employee_id, e.employee_code,
                CONCAT(e.first_name, ' ', e.last_name) as employee_name,
                e.tax_id, e.social_security,
                e.branch_id, b.branch_name, b.country_code as jurisdiction,
                d.name as department_name,
                COUNT(pe.id) as payslip_count,
                COALESCE(SUM(pe.basic_salary), 0) as total_basic,
                COALESCE(SUM(pe.housing_allowance), 0) as total_housing,
                COALESCE(SUM(pe.transport_allowance), 0) as total_transport,
                COALESCE(SUM(pe.other_allowances), 0) as total_other_allowances,
                COALESCE(SUM(pe.gross_salary), 0) as total_gross,
                COALESCE(SUM(pe.gosi_employee_share), 0) as total_gosi_employee,
                COALESCE(SUM(pe.gosi_employer_share), 0) as total_gosi_employer,
                COALESCE(SUM(pe.net_salary), 0) as total_net,
                COALESCE(SUM(pe.gross_salary - pe.net_salary), 0) as total_deductions
            FROM employees e
            JOIN payroll_entries pe ON pe.employee_id = e.id
            LEFT JOIN branches b ON e.branch_id = b.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE {where}
              AND EXTRACT(YEAR FROM pp.start_date) = :year
            GROUP BY e.id, e.employee_code, e.first_name, e.last_name, e.tax_id,
                     e.social_security, e.branch_id, b.branch_name, b.country_code,
                     d.name
            ORDER BY total_gross DESC
        """), params).fetchall()

        # Get GOSI settings for computation
        gosi = db.execute(text(
            "SELECT employee_share_pct, employer_share_pct, max_contributable_salary FROM gosi_settings LIMIT 1"
        )).fetchone()

        employee_list = []
        total_gosi_emp = Decimal("0")
        total_gosi_empr = Decimal("0")
        total_gross_all = Decimal("0")

        for emp in employees:
            gosi_emp = _dec(emp.total_gosi_employee).quantize(_D2, ROUND_HALF_UP)
            gosi_empr = _dec(emp.total_gosi_employer).quantize(_D2, ROUND_HALF_UP)
            gross = _dec(emp.total_gross).quantize(_D2, ROUND_HALF_UP)
            total_gosi_emp += gosi_emp
            total_gosi_empr += gosi_empr
            total_gross_all += gross

            # Compute income tax for employee's jurisdiction
            jurisdiction = emp.jurisdiction or "SA"
            tax_due = Decimal("0")
            tax_rate_dec = Decimal("0")
            if jurisdiction != "SA":
                # SA doesn't have personal income tax; other countries do
                regime = db.execute(text(
                    "SELECT default_rate FROM tax_regimes WHERE country_code = :cc AND tax_type = 'salary_tax' AND is_active = TRUE LIMIT 1"
                ), {"cc": jurisdiction}).fetchone()
                if regime:
                    tax_rate_dec = _dec(regime.default_rate)
                    tax_due = (gross * (tax_rate_dec / Decimal("100"))).quantize(_D2, ROUND_HALF_UP)

            employee_list.append({
                "employee_id": emp.employee_id,
                "employee_code": emp.employee_code,
                "employee_name": emp.employee_name,
                "tax_id": emp.tax_id,
                "social_security": emp.social_security,
                "branch_id": emp.branch_id,
                "branch_name": emp.branch_name,
                "jurisdiction": jurisdiction,
                "department_name": emp.department_name,
                "payslip_count": emp.payslip_count,
                "total_gross": float(gross),
                "total_basic": float(emp.total_basic or 0),
                "total_allowances": float(emp.total_housing or 0) + float(emp.total_transport or 0) + float(emp.total_other_allowances or 0),
                "gosi_employee": float(gosi_emp),
                "gosi_employer": float(gosi_empr),
                "income_tax_rate": float(tax_rate_dec),
                "income_tax_due": float(tax_due),
                "total_deductions": float(emp.total_deductions or 0),
                "total_net": float(emp.total_net or 0),
            })

        return {
            "year": year,
            "branch_id": branch_id,
            "employees": employee_list,
            "summary": {
                "total_employees": len(employee_list),
                "total_gross": float(total_gross_all.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_employee": float(total_gosi_emp.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_employer": float(total_gosi_empr.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_combined": float((total_gosi_emp + total_gosi_empr).quantize(_D2, ROUND_HALF_UP)),
            },
            "gosi_settings": {
                "employee_pct": float(gosi.employee_share_pct) if gosi else 0,
                "employer_pct": float(gosi.employer_share_pct) if gosi else 0,
                "max_salary": float(gosi.max_contributable_salary) if gosi else 0,
            } if gosi else None
        }
    except Exception as e:
        logger.error(f"Error fetching employee tax obligations: {e}")
        return {
            "year": year, "branch_id": branch_id,
            "employees": [], "summary": {"total_employees": 0, "total_gross": 0,
                "total_gosi_employee": 0, "total_gosi_employer": 0, "total_gosi_combined": 0},
            "gosi_settings": None
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# ██  Tax Filing Calendar  (TAX-002)
# ═══════════════════════════════════════════════════════════════

class TaxCalendarCreate(BaseModel):
    title: str
    tax_type: Optional[str] = None
    due_date: date
    reminder_days: Optional[list] = [7, 3, 1]
    is_recurring: Optional[bool] = False
    recurrence_months: Optional[int] = 3
    notes: Optional[str] = None

class TaxCalendarUpdate(BaseModel):
    title: Optional[str] = None
    tax_type: Optional[str] = None
    due_date: Optional[date] = None
    reminder_days: Optional[list] = None
    is_recurring: Optional[bool] = None
    recurrence_months: Optional[int] = None
    is_completed: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/calendar")
def list_tax_calendar(
    status: Optional[str] = None,
    tax_type: Optional[str] = None,
    current_user=Depends(require_permission(["taxes.view"]))
):
    """List tax calendar events with optional filters"""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["1=1"]
        params = {}
        if status == "completed":
            conditions.append("is_completed = true")
        elif status == "pending":
            conditions.append("is_completed = false")
        elif status == "overdue":
            conditions.append("is_completed = false AND due_date < CURRENT_DATE")
        if tax_type:
            conditions.append("tax_type = :tax_type")
            params["tax_type"] = tax_type

        where = " AND ".join(conditions)
        rows = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT *, 
                   CASE WHEN is_completed THEN 'completed'
                        WHEN due_date < CURRENT_DATE THEN 'overdue'
                        WHEN due_date <= CURRENT_DATE + INTERVAL '7 days' THEN 'upcoming'
                        ELSE 'pending' END as status
            FROM tax_calendar
            WHERE {where}
            ORDER BY due_date ASC
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.error(f"Error listing tax calendar: {e}")
        return []
    finally:
        db.close()


@router.get("/calendar/summary")
def tax_calendar_summary(
    current_user=Depends(require_permission(["taxes.view"]))
):
    """Get tax calendar summary stats"""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_completed = false AND due_date >= CURRENT_DATE) as pending,
                COUNT(*) FILTER (WHERE is_completed = false AND due_date < CURRENT_DATE) as overdue,
                COUNT(*) FILTER (WHERE is_completed = true) as completed,
                COUNT(*) FILTER (WHERE is_completed = false AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days') as upcoming_week,
                MIN(due_date) FILTER (WHERE is_completed = false AND due_date >= CURRENT_DATE) as next_due
            FROM tax_calendar
        """)).fetchone()
        return dict(row._mapping) if row else {}
    except Exception as e:
        logger.error(f"Error fetching calendar summary: {e}")
        return {}
    finally:
        db.close()


@router.get("/calendar/{item_id}")
def get_tax_calendar_item(
    item_id: int,
    current_user=Depends(require_permission(["taxes.view"]))
):
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("SELECT * FROM tax_calendar WHERE id = :id"), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(404, "Calendar item not found")
        return dict(row._mapping)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/calendar")
def create_tax_calendar_item(
    request: Request,
    data: TaxCalendarCreate,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    db = get_db_connection(current_user.company_id)
    try:
        import json
        row = db.execute(text("""
            INSERT INTO tax_calendar (title, tax_type, due_date, reminder_days, is_recurring, recurrence_months, notes, created_by)
            VALUES (:title, :tax_type, :due_date, CAST(:reminder_days AS jsonb), :is_recurring, :recurrence_months, :notes, :user_id)
            RETURNING *
        """), {
            "title": data.title,
            "tax_type": data.tax_type,
            "due_date": data.due_date,
            "reminder_days": json.dumps(data.reminder_days or [7, 3, 1]),
            "is_recurring": data.is_recurring,
            "recurrence_months": data.recurrence_months,
            "notes": data.notes,
            "user_id": current_user.id
        }).fetchone()
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.calendar.create", resource_type="tax_calendar",
                     resource_id=str(row.id), details={"title": data.title},
                     request=request)
        return dict(row._mapping)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating calendar item: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/calendar/{item_id}")
def update_tax_calendar_item(
    item_id: int,
    request: Request,
    data: TaxCalendarUpdate,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    db = get_db_connection(current_user.company_id)
    try:
        import json
        updates = []
        params = {"id": item_id}
        for field in ["title", "tax_type", "due_date", "is_recurring", "recurrence_months", "is_completed", "notes"]:
            val = getattr(data, field, None)
            if val is not None:
                updates.append(f"{field} = :{field}")
                params[field] = val
        if data.reminder_days is not None:
            updates.append("reminder_days = CAST(:reminder_days AS jsonb)")
            params["reminder_days"] = json.dumps(data.reminder_days)
        if not updates:
            raise HTTPException(400, "No fields to update")

        row = db.execute(text(  # noqa: sql-lint
            f"""

            UPDATE tax_calendar SET {', '.join(updates)} WHERE id = :id RETURNING *
        """), params).fetchone()
        if not row:
            raise HTTPException(404, "Calendar item not found")
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.calendar.update", resource_type="tax_calendar",
                     resource_id=str(item_id), details={"fields": list(params.keys())},
                     request=request)
        return dict(row._mapping)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating calendar item: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/calendar/{item_id}")
def delete_tax_calendar_item(
    item_id: int,
    request: Request,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("DELETE FROM tax_calendar WHERE id = :id"), {"id": item_id})
        if result.rowcount == 0:
            raise HTTPException(404, "Calendar item not found")
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.calendar.delete", resource_type="tax_calendar",
                     resource_id=str(item_id), details={},
                     request=request)
        return {"message": "Deleted"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/calendar/{item_id}/complete")
def complete_tax_calendar_item(
    item_id: int,
    request: Request,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    """Mark a tax calendar item as completed, optionally creating next recurrence"""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("SELECT * FROM tax_calendar WHERE id = :id"), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(404, "Calendar item not found")
        item = dict(row._mapping)

        db.execute(text("UPDATE tax_calendar SET is_completed = true WHERE id = :id"), {"id": item_id})

        # If recurring, create next occurrence
        new_id = None
        if item.get("is_recurring"):
            import json
            months = item.get("recurrence_months", 3)
            next_due = item["due_date"]
            from dateutil.relativedelta import relativedelta
            if hasattr(next_due, 'date'):
                next_due = next_due
            next_due = next_due + relativedelta(months=months)
            next_row = db.execute(text("""
                INSERT INTO tax_calendar (title, tax_type, due_date, reminder_days, is_recurring, recurrence_months, notes, created_by)
                VALUES (:title, :tax_type, :next_due, CAST(:reminder_days AS jsonb), true, :months, :notes, :user_id)
                RETURNING id
            """), {
                "title": item["title"],
                "tax_type": item.get("tax_type"),
                "next_due": next_due,
                "reminder_days": json.dumps(item.get("reminder_days", [7, 3, 1])),
                "months": months,
                "notes": item.get("notes"),
                "user_id": current_user.id
            }).fetchone()
            new_id = next_row[0] if next_row else None

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="taxes.calendar.complete", resource_type="tax_calendar",
                     resource_id=str(item_id), details={"next_recurrence_id": new_id},
                     request=request)
        return {"message": "Completed", "next_recurrence_id": new_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error completing calendar item: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
