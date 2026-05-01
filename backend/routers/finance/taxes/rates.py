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
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

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
    current_user: dict = Depends(get_current_user)
):
    """جلب جميع أنواع الضرائب — مع فلتر اختياري حسب الدولة"""
    with transactional(current_user.company_id) as db:
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
    """إنشاء نوع ضريبة جديد"""
    with transactional(current_user.company_id) as db:
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
    """تحديث نوع ضريبة"""
    with transactional(current_user.company_id) as db:
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


# ==================== TAX GROUPS ====================

