"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.accounting import get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from schemas.assets import (
    AssetCreate, AssetUpdate, AssetDisposal, LeasePaymentCreate,
    AssetTransferCreate, AssetRevaluationCreate, MaintenanceComplete,
    LeaseContractCreate, DecliningBalanceInput, UnitsOfProductionInput,
    InsuranceCreate, MaintenanceCreate, AssetQRUpdate, ImpairmentTestInput,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/reports/register", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def asset_register_report(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير سجل الأصول الثابتة"""
    with transactional(current_user.company_id) as conn:
        params = {}
        branch_filter = "AND a.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        rows = conn.execute(text(f"""
            SELECT
                a.id, a.code, a.name, a.type, a.purchase_date,
                a.cost, a.residual_value, a.life_years,
                a.depreciation_method, a.status, a.currency,
                COALESCE(ds.total_depreciation, 0) as accumulated_depreciation,
                a.cost - COALESCE(ds.total_depreciation, 0) as net_book_value,
                b.branch_name as branch_name
            FROM assets a
            LEFT JOIN branches b ON a.branch_id = b.id
            LEFT JOIN (
                SELECT asset_id, SUM(amount) as total_depreciation
                FROM asset_depreciation_schedule
                WHERE posted = TRUE
                GROUP BY asset_id
            ) ds ON ds.asset_id = a.id
            WHERE 1=1 {branch_filter}
            ORDER BY a.code
        """), params).fetchall()

        items = []
        for r in rows:
            # F-NEW-063 (R-FLOAT-MONEY, Req 8.5): emit Decimal money as
            # canonical strings so 4-dp precision survives the wire.
            items.append({
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "category": r.type,
                "purchase_date": str(r.purchase_date) if r.purchase_date else None,
                "original_cost": str(_dec(r.cost or 0).quantize(_D2, ROUND_HALF_UP)),
                "cost": str(_dec(r.cost or 0).quantize(_D2, ROUND_HALF_UP)),
                "residual_value": str(_dec(r.residual_value or 0).quantize(_D2, ROUND_HALF_UP)),
                "life_years": r.life_years,
                "depreciation_method": r.depreciation_method,
                "accumulated_depreciation": str(_dec(r.accumulated_depreciation or 0).quantize(_D2, ROUND_HALF_UP)),
                "net_book_value": str(_dec(r.net_book_value or 0).quantize(_D2, ROUND_HALF_UP)),
                "status": r.status,
                "currency": r.currency,
                "branch": r.branch_name,
            })

        return {"items": items, "count": len(items)}


@router.get("/reports/depreciation-summary", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def asset_depreciation_summary(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص إهلاك الأصول الثابتة"""
    with transactional(current_user.company_id) as conn:
        params = {}
        branch_filter = "AND a.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        rows = conn.execute(text(f"""
            SELECT
                a.id, a.code, a.name, a.type,
                a.cost, a.residual_value, a.life_years,
                a.depreciation_method, a.currency, a.status,
                COALESCE(ds.total_depreciation, 0) as total_depreciation,
                COALESCE(ds.periods_posted, 0) as periods_posted,
                CASE WHEN a.life_years > 0 AND a.cost > a.residual_value
                     THEN ROUND((a.cost - a.residual_value) / a.life_years, 2)
                     ELSE 0 END as annual_depreciation
            FROM assets a
            LEFT JOIN (
                SELECT asset_id,
                       SUM(amount) as total_depreciation,
                       COUNT(*) as periods_posted
                FROM asset_depreciation_schedule
                WHERE posted = TRUE
                GROUP BY asset_id
            ) ds ON ds.asset_id = a.id
            WHERE a.status != 'disposed' {branch_filter}
            ORDER BY a.code
        """), params).fetchall()

        items = []
        for r in rows:
            cost = _dec(r.cost or 0)
            total_depr = _dec(r.total_depreciation or 0)
            net_book_value = (cost - total_depr).quantize(_D2, ROUND_HALF_UP)
            depreciation_pct = ((total_depr / cost) * Decimal('100')).quantize(Decimal('0.1'), ROUND_HALF_UP) if cost > 0 else Decimal('0')
            items.append({
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "category": r.type,
                # F-NEW-063: Decimal-string serialisation.
                "cost": str(cost.quantize(_D2, ROUND_HALF_UP)),
                "residual_value": str(_dec(r.residual_value or 0).quantize(_D2, ROUND_HALF_UP)),
                "life_years": r.life_years,
                "depreciation_method": r.depreciation_method,
                "annual_depreciation": str(_dec(r.annual_depreciation or 0).quantize(_D2, ROUND_HALF_UP)),
                "total_depreciation": str(total_depr.quantize(_D2, ROUND_HALF_UP)),
                "accumulated_depreciation": str(total_depr.quantize(_D2, ROUND_HALF_UP)),
                "net_book_value": str(net_book_value),
                "nbv": str(net_book_value),
                "periods_posted": r.periods_posted,
                "currency": r.currency,
                "depreciation_pct": str(depreciation_pct),
            })

        return {"items": items, "count": len(items)}


# ─────────────────────────────────────────────────────────────
# Depreciation run — post pending schedule entries to GL
# Dr Depreciation Expense / Cr Accumulated Depreciation
# Idempotent per (asset_id, fiscal_year, schedule_id).
# ─────────────────────────────────────────────────────────────
@router.get("/reports/net-book-value", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def asset_net_book_value_report(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير صافي القيمة الدفترية للأصول"""
    with transactional(current_user.company_id) as conn:
        params = {}
        branch_filter = "AND a.branch_id = :branch_id" if branch_id else ""
        if branch_id:
            params["branch_id"] = branch_id

        rows = conn.execute(text(f"""
            SELECT
                a.id, a.code, a.name, a.type,
                a.cost, a.currency, a.status, a.purchase_date,
                COALESCE(ds.total_depreciation, 0) as accumulated_depreciation,
                a.cost - COALESCE(ds.total_depreciation, 0) as net_book_value
            FROM assets a
            LEFT JOIN (
                SELECT asset_id, SUM(amount) as total_depreciation
                FROM asset_depreciation_schedule
                WHERE posted = TRUE
                GROUP BY asset_id
            ) ds ON ds.asset_id = a.id
            WHERE a.status != 'disposed' {branch_filter}
            ORDER BY (a.cost - COALESCE(ds.total_depreciation, 0)) DESC
        """), params).fetchall()

        items = []
        for r in rows:
            cost = _dec(r.cost or 0).quantize(_D2, ROUND_HALF_UP)
            acc_depr = _dec(r.accumulated_depreciation or 0).quantize(_D2, ROUND_HALF_UP)
            nbv = _dec(r.net_book_value or 0).quantize(_D2, ROUND_HALF_UP)
            items.append({
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "category": r.type,
                # F-NEW-063: Decimal-string serialisation.
                "original_cost": str(cost),
                "cost": str(cost),
                "accumulated_depreciation": str(acc_depr),
                "total_depreciation": str(acc_depr),
                "net_book_value": str(nbv),
                "nbv": str(nbv),
                "status": r.status,
                "currency": r.currency,
                "purchase_date": str(r.purchase_date) if r.purchase_date else None,
            })

        return {"items": items, "count": len(items)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PARAMETERIZED ROUTES (/{asset_id}) come BELOW the static routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


