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
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.tax_precision import rate_str, serialize_tax_row
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate
from services.tax_engine import (
    validate_tax_access, update_tax_rate as engine_update_tax_rate,
    get_active_tax_for_branch, get_active_tax_for_country,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _D4

@router.get("/rates", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_tax_rates(
    is_active: Optional[bool] = None,
    country_code: Optional[str] = None,
    all_branches: Optional[bool] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب أنواع الضرائب — مفلترة حسب دولة فرع المستخدم (والضرائب العالمية)"""
    with transactional(current_user.company_id) as db:
        where = "WHERE 1=1"
        params = {}

        # When all_branches=true or no country_code specified, show all taxes
        if not all_branches and country_code:
            where += " AND (country_code = :cc OR country_code IS NULL)"
            params["cc"] = country_code.upper()
        elif not all_branches:
            # Get user's branch country_code as fallback
            user_branch = db.execute(text("""
                SELECT b.country_code
                FROM company_users cu
                JOIN user_branches ub ON cu.id = ub.user_id
                JOIN branches b ON ub.branch_id = b.id
                WHERE cu.id = :uid
                ORDER BY b.is_default DESC
                LIMIT 1
            """), {"uid": current_user.id}).fetchone()

            user_cc = (user_branch.country_code or "SA").upper() if user_branch else "SA"
            where += " AND (country_code = :cc OR country_code IS NULL)"
            params["cc"] = user_cc

        if is_active is not None:
            where += " AND is_active = :active"
            params["active"] = is_active

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT id, tax_code, tax_name, tax_name_en, rate_type, rate_value,
                   description, effective_from, effective_to, is_active, country_code,
                   is_default, legal_entity_id, created_at
            FROM tax_rates {where}
            ORDER BY created_at DESC
        """), params).fetchall()

        return [serialize_tax_row(r, money_fields=[], rate_fields=["rate_value"]) for r in rows]


@router.get("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=Dict[str, Any])
def get_tax_rate(rate_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل نوع ضريبة"""
    with transactional(current_user.company_id) as db:
        row = db.execute(text("SELECT * FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "tax_type_not_found"))
        return dict(row._mapping)


@router.post("/rates", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_rate(
    request: Request,
    data: TaxRateCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء نوع ضريبة جديد (مع التحقق من الدولة)"""
    with transactional(current_user.company_id) as db:
        try:
            # Validate user's branch country matches requested country
            if data.country_code:
                user_branch = db.execute(text("""
                    SELECT b.country_code
                    FROM company_users cu
                    JOIN user_branches ub ON cu.id = ub.user_id
                    JOIN branches b ON ub.branch_id = b.id
                    WHERE cu.id = :uid
                    ORDER BY b.is_default DESC
                    LIMIT 1
                """), {"uid": current_user.id}).fetchone()

                user_cc = (user_branch.country_code or "SA").upper() if user_branch else "SA"
                requested_cc = data.country_code.upper()

                if user_cc != requested_cc:
                    raise HTTPException(**http_error(
                        403, "cross_country_tax_create",
                        detail=f"Cannot create tax for country '{requested_cc}' from a '{user_cc}' branch"
                    ))

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
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.rate.create", resource_type="tax_rate",
                         resource_id=str(new_id), details={"tax_code": data.tax_code, "rate": data.rate_value},
                         request=request)
    
            return {"success": True, "id": new_id, "message": "تم إنشاء نوع الضريبة بنجاح"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating tax rate: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def update_tax_rate(
    rate_id: int, request: Request, data: TaxRateUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث نوع ضريبة (append-only — لا يُعدّل السجل الحالي، يُنشئ سجلاً جديداً)"""
    with transactional(current_user.company_id) as db:
        try:
            # Validate access: user's branch country must match tax country
            validate_tax_access(current_user.id, rate_id, db)

            # Require effective_from and reason for rate changes
            if data.rate_value is not None:
                if not data.effective_from:
                    raise HTTPException(**http_error(400, "effective_from_required",
                        detail="effective_from is required when changing rate_value"))
                if not data.reason:
                    raise HTTPException(**http_error(400, "reason_required",
                        detail="reason is required when changing rate_value"))

                # Use engine for immutable rate update
                new_record = engine_update_tax_rate(
                    tax_id=rate_id,
                    new_rate=Decimal(str(data.rate_value)),
                    effective_from=data.effective_from,
                    changed_by=current_user.id,
                    reason=data.reason,
                    db=db,
                )

                log_activity(db, user_id=current_user.id, username=current_user.username,
                             action="taxes.rate.update", resource_type="tax_rate",
                             resource_id=str(rate_id),
                             details={"old_rate": str(new_record.get("rate_value")), "new_rate": str(data.rate_value),
                                       "effective_from": str(data.effective_from), "reason": data.reason},
                             request=request)

                return {"success": True, "new_tax_id": new_record["id"],
                        "message": "تم تحديث نوع الضريبة بنجاح (سجل جديد)"}

            # For non-rate updates (name, description, etc.) — direct update is OK
            existing = db.execute(text("SELECT 1 FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "tax_type_not_found"))

            updates = []
            params = {"id": rate_id}
            for field, val in data.dict(exclude_unset=True).items():
                if field in ("reason",):  # skip non-column fields
                    continue
                updates.append(f"{field} = :{field}")
                params[field] = val

            if not updates:
                raise HTTPException(**http_error(400, "no_data_to_update"))

            db.execute(text(f"UPDATE tax_rates SET {', '.join(updates)} WHERE id = :id"), params)  # noqa: sql-lint

            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.rate.update", resource_type="tax_rate",
                         resource_id=str(rate_id), details=params, request=request)

            return {"success": True, "message": "تم تحديث نوع الضريبة بنجاح"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error updating tax rate: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/rates/{rate_id}", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def delete_tax_rate(rate_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """حذف نوع ضريبة (إيقاف تفعيل فقط)"""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT tax_code FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "tax_type_not_found"))
    
            db.execute(text("UPDATE tax_rates SET is_active = FALSE WHERE id = :id"), {"id": rate_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.rate.delete", resource_type="tax_rate",
                         resource_id=str(rate_id), details={"tax_code": existing.tax_code},
                         request=request)
    
            return {"success": True, "message": "تم إيقاف نوع الضريبة بنجاح"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/rates/branch/{branch_id}", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=Dict[str, Any])
def get_tax_for_branch(
    branch_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب الضريبة النشطة لفرع معين — تُستخدم في الواجهة لجلب الضريبة تلقائياً عند اختيار الفرع"""
    branch_id = validate_branch_access(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        try:
            tax_info = get_active_tax_for_branch(branch_id, db)
            return {
                "tax_rate_id": tax_info.get("id"),
                "tax_rate": rate_str(tax_info["rate"]),
                "tax_name": tax_info.get("name"),
                "country_code": tax_info.get("country_code"),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching tax for branch {branch_id}: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/rates/{rate_id}/history", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def get_tax_rate_history(
    rate_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب سجل التعديلات لنوع ضريبة (audit trail)"""
    with transactional(current_user.company_id) as db:
        # Verify tax exists
        tax = db.execute(text("SELECT id, tax_code FROM tax_rates WHERE id = :id"), {"id": rate_id}).fetchone()
        if not tax:
            raise HTTPException(**http_error(404, "tax_type_not_found"))

        rows = db.execute(text("""
            SELECT h.id, h.tax_rate_id, h.changed_by,
                   h.old_rate, h.new_rate,
                   h.old_name, h.new_name,
                   h.old_country, h.new_country,
                   h.reason, h.changed_at,
                   cu.full_name as changed_by_name
            FROM tax_rate_history h
            LEFT JOIN company_users cu ON h.changed_by = cu.id
            WHERE h.tax_rate_id = :tid
            ORDER BY h.changed_at DESC
        """), {"tid": rate_id}).fetchall()

        return [dict(r._mapping) for r in rows]


# ==================== TAX GROUPS ====================
