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
from utils.tax_precision import rate_str
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/groups", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_tax_groups(current_user: dict = Depends(get_current_user)):
    """جلب مجموعات الضرائب"""
    with transactional(current_user.company_id) as db:
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
                    item["combined_rate"] = rate_str(combined_rate)
                else:
                    item["taxes"] = []
                    item["combined_rate"] = 0
            else:
                item["taxes"] = []
                item["combined_rate"] = 0
            result.append(item)

        return result


@router.post("/groups", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_group(request: Request, data: TaxGroupCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء مجموعة ضريبية جديدة"""
    with transactional(current_user.company_id) as db:
        try:
            exists = db.execute(text("SELECT 1 FROM tax_groups WHERE group_code = :code"), {"code": data.group_code}).fetchone()
            if exists:
                raise HTTPException(**http_error(400, "tax_group_code_already_exists", request))
    
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
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.group.create", resource_type="tax_group",
                         resource_id=str(new_id), details={"group_code": data.group_code},
                         request=request)
    
            return {"success": True, "id": new_id, "message": i18n_message("tax_group_created", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ==================== TAX RETURNS (الإقرارات الضريبية) ====================
