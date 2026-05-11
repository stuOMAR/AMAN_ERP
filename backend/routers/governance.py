"""Cross-module governance endpoints.

Covers finance, treasury, HR, approvals and document controls that sit above
individual domain routers: configuration tables, posting adjustments, quorum
escalation, geofencing and asset/lease remeasurement.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.accounting import get_mapped_account_id
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.i18n import http_error
from utils.permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Governance"])

_D2 = Decimal("0.01")


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


# ==========================================================================
# Overtime rates configuration
# ==========================================================================

class OvertimeRate(BaseModel):
    rate_key: str
    description: Optional[str] = None
    multiplier: float = Field(..., gt=0)
    is_active: bool = True


@router.get("/overtime-rates", dependencies=[Depends(require_permission(["hr.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def list_overtime_rates(current_user=Depends(get_current_user)):
    """List Overtime Rates."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(
            text("SELECT rate_key, description, multiplier, is_active FROM overtime_rates_config ORDER BY rate_key")
        ).fetchall()
        return [dict(r._mapping) for r in rows]


@router.put("/overtime-rates", dependencies=[Depends(require_permission(["hr.manage", "settings.edit"]))], response_model=Dict[str, Any])
def upsert_overtime_rate(body: OvertimeRate, current_user=Depends(get_current_user)):
    """Upsert Overtime Rate."""
    with transactional(current_user.company_id) as db:
        db.execute(
            text(
                """
                INSERT INTO overtime_rates_config (rate_key, description, multiplier, is_active, updated_at)
                VALUES (:k, :d, :m, :a, CURRENT_TIMESTAMP)
                ON CONFLICT (rate_key) DO UPDATE SET
                    description = EXCLUDED.description,
                    multiplier = EXCLUDED.multiplier,
                    is_active = EXCLUDED.is_active,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"k": body.rate_key, "d": body.description, "m": body.multiplier, "a": body.is_active},
        )
        return {"ok": True, "rate_key": body.rate_key}


# ==========================================================================
# Document permissions
# ==========================================================================

class DocPermissionCreate(BaseModel):
    document_id: int
    department_id: Optional[int] = None
    role_id: Optional[int] = None
    user_id: Optional[int] = None
    access_level: Literal["view", "edit", "owner"] = "view"


@router.post("/documents/{doc_id}/permissions", dependencies=[Depends(require_permission("dms.manage"))], response_model=Dict[str, Any])
def grant_document_permission(request: Request, 
    doc_id: int,
    body: DocPermissionCreate,
    current_user=Depends(get_current_user),
):
    """Grant Document Permission."""
    if body.department_id is None and body.role_id is None and body.user_id is None:
        raise HTTPException(**http_error(400, "section_role_or_user_required", request))
    with transactional(current_user.company_id) as db:
        db.execute(
            text(
                """
                INSERT INTO document_permissions
                    (document_id, department_id, role_id, user_id, access_level, granted_by)
                VALUES (:doc, :dept, :role, :usr, :lvl, :by)
                """
            ),
            {
                "doc": doc_id,
                "dept": body.department_id,
                "role": body.role_id,
                "usr": body.user_id,
                "lvl": body.access_level,
                "by": current_user.id,
            },
        )
        return {"ok": True}


@router.get("/documents/{doc_id}/permissions", dependencies=[Depends(require_permission("dms.view"))], response_model=List[Dict[str, Any]])
def list_document_permissions(doc_id: int, current_user=Depends(get_current_user)):
    """List Document Permissions."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(
            text(
                """
                SELECT id, document_id, department_id, role_id, user_id, access_level, granted_by, created_at
                FROM document_permissions
                WHERE document_id = :doc
                ORDER BY id DESC
                """
            ),
            {"doc": doc_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]


# ==========================================================================
# Geofences + check-in validation
# ==========================================================================

class GeofenceCreate(BaseModel):
    name: str
    branch_id: Optional[int] = None
    center_lat: float
    center_lng: float
    radius_m: int = Field(..., gt=0, le=50000)


class CheckInValidate(BaseModel):
    branch_id: int
    lat: float
    lng: float


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


@router.post("/geofences", dependencies=[Depends(require_permission(["hr.manage", "branches.manage"]))], response_model=Dict[str, Any])
def create_geofence(body: GeofenceCreate, current_user=Depends(get_current_user)):
    """Create Geofence."""
    with transactional(current_user.company_id) as db:
        row = db.execute(
            text(
                """
                INSERT INTO geofences (name, branch_id, center_lat, center_lng, radius_m)
                VALUES (:n, :b, :la, :lg, :r)
                RETURNING id
                """
            ),
            {"n": body.name, "b": body.branch_id, "la": body.center_lat, "lg": body.center_lng, "r": body.radius_m},
        ).fetchone()
        return {"id": row[0]}


@router.post("/attendance/validate-location", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def validate_checkin_location(body: CheckInValidate, current_user=Depends(get_current_user)):
    """Return ``inside=True`` when the caller is within any active geofence of the branch."""
    with transactional(current_user.company_id) as db:
        fences = db.execute(
            text(
                """
                SELECT id, name, center_lat, center_lng, radius_m
                FROM geofences
                WHERE is_active = TRUE AND branch_id = :b
                """
            ),
            {"b": body.branch_id},
        ).fetchall()
        if not fences:
            return {"inside": True, "reason": "no_geofence_configured"}
        nearest = None
        min_dist = None
        for f in fences:
            d = _haversine_m(body.lat, body.lng, float(f.center_lat), float(f.center_lng))
            if min_dist is None or d < min_dist:
                min_dist, nearest = d, f
            if d <= float(f.radius_m):
                return {"inside": True, "geofence_id": f.id, "distance_m": round(d, 2)}
        return {
            "inside": False,
            "nearest_geofence_id": nearest.id if nearest else None,
            "distance_m": round(min_dist, 2) if min_dist is not None else None,
        }


# ==========================================================================
# Approval SLA escalation scanner
# ==========================================================================

@router.post("/approvals/sla/escalate", dependencies=[Depends(require_permission("approvals.manage"))], response_model=Dict[str, Any])
def scan_and_escalate_sla(current_user=Depends(get_current_user)):
    """Scan ``approval_requests`` in ``pending`` status past their workflow SLA and escalate.

    Idempotent: rows already stamped ``sla_escalated_at`` are skipped.
    """
    with transactional(current_user.company_id) as db:
        rows = db.execute(
            text(
                """
                SELECT ar.id, ar.workflow_id, aw.sla_hours, aw.escalation_to
                FROM approval_requests ar
                JOIN approval_workflows aw ON aw.id = ar.workflow_id
                WHERE ar.status = 'pending'
                  AND ar.sla_escalated_at IS NULL
                  AND aw.sla_hours IS NOT NULL
                  AND ar.created_at < CURRENT_TIMESTAMP - (aw.sla_hours || ' hours')::interval
                """
            )
        ).fetchall()
        escalated = 0
        for r in rows:
            db.execute(
                text(
                    """
                    UPDATE approval_requests
                    SET escalated_to = COALESCE(:to, escalated_to),
                        escalated_at = CURRENT_TIMESTAMP,
                        sla_escalated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"to": r.escalation_to, "id": r.id},
            )
            escalated += 1
        return {"scanned": len(rows), "escalated": escalated}


# ==========================================================================
# Historical GOSI delta back-fill
# ==========================================================================

@router.post("/hr/gosi/historical-adjust", dependencies=[Depends(require_permission(["hr.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def adjust_historical_gosi(request: Request, current_user=Depends(get_current_user)):
    """Back-fill the 0.25 % employer-GOSI delta for payroll entries booked before
    the rate correction. Touches only entries flagged ``gosi_adjusted IS NOT TRUE``."""
    with transactional(current_user.company_id) as db:
        db.execute(text("ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS gosi_adjusted BOOLEAN DEFAULT FALSE"))
        db.execute(text("ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS gosi_adjustment NUMERIC(18,4) DEFAULT 0"))
        rows = db.execute(
            text(
                """
                UPDATE payroll_entries
                SET gosi_adjustment = ROUND(gross_salary * 0.0025::numeric, 4),
                    gosi_adjusted = TRUE
                WHERE COALESCE(gosi_adjusted, FALSE) = FALSE
                  AND gross_salary > 0
                RETURNING id
                """
            )
        ).fetchall()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="hr.gosi_adjust", resource_type="payroll_entry",
            details={"count": len(rows)},
            request=request,
        )
        return {"adjusted_rows": len(rows)}


# ==========================================================================
# Zakat base items mapping
# ==========================================================================

class ZakatBaseItem(BaseModel):
    account_id: int
    category: Literal["asset", "deductible", "addition", "exclude"]
    weight: float = 1.0
    notes: Optional[str] = None


@router.get("/zakat/base-items", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_zakat_base_items(current_user=Depends(get_current_user)):
    """List Zakat Base Items."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(
            text(
                """
                SELECT zbi.id, zbi.account_id, a.account_code, a.name, zbi.category, zbi.weight, zbi.notes
                FROM zakat_base_items zbi
                JOIN accounts a ON a.id = zbi.account_id
                ORDER BY zbi.category, a.account_code
                """
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/zakat/base-items", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def upsert_zakat_base_item(body: ZakatBaseItem, current_user=Depends(get_current_user)):
    """Upsert Zakat Base Item."""
    with transactional(current_user.company_id) as db:
        db.execute(
            text(
                """
                INSERT INTO zakat_base_items (account_id, category, weight, notes)
                VALUES (:a, :c, :w, :n)
                ON CONFLICT (account_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    weight = EXCLUDED.weight,
                    notes = EXCLUDED.notes
                """
            ),
            {"a": body.account_id, "c": body.category, "w": body.weight, "n": body.notes},
        )
        return {"ok": True}


# ==========================================================================
# Branch tax settings
# ==========================================================================

class BranchTaxSetting(BaseModel):
    branch_id: int
    default_tax_rate: float = Field(..., ge=0, le=100)
    tax_exempt: bool = False
    notes: Optional[str] = None


@router.get("/tax/branch-settings", dependencies=[Depends(require_permission(["taxes.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def list_branch_tax_settings(current_user=Depends(get_current_user)):
    """List Branch Tax Settings."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("SELECT * FROM branch_tax_settings")).fetchall()
        return [dict(r._mapping) for r in rows]


@router.put("/tax/branch-settings", dependencies=[Depends(require_permission(["taxes.manage", "settings.edit"]))], response_model=Dict[str, Any])
def upsert_branch_tax_setting(body: BranchTaxSetting, current_user=Depends(get_current_user)):
    """Upsert Branch Tax Setting."""
    with transactional(current_user.company_id) as db:
        db.execute(text("ALTER TABLE branch_tax_settings ADD COLUMN IF NOT EXISTS default_tax_rate DECIMAL(6,3) DEFAULT 0"))
        db.execute(text("ALTER TABLE branch_tax_settings ADD COLUMN IF NOT EXISTS tax_exempt BOOLEAN DEFAULT FALSE"))
        db.execute(text("ALTER TABLE branch_tax_settings ADD COLUMN IF NOT EXISTS notes TEXT"))
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_branch_tax_settings_branch ON branch_tax_settings(branch_id)"))
        db.execute(
            text(
                """
                INSERT INTO branch_tax_settings (branch_id, default_tax_rate, tax_exempt, notes)
                VALUES (:b, :r, :e, :n)
                ON CONFLICT (branch_id) DO UPDATE SET
                    default_tax_rate = EXCLUDED.default_tax_rate,
                    tax_exempt = EXCLUDED.tax_exempt,
                    notes = EXCLUDED.notes
                """
            ),
            {"b": body.branch_id, "r": body.default_tax_rate, "e": body.tax_exempt, "n": body.notes},
        )
        return {"ok": True, "branch_id": body.branch_id}


# ==========================================================================
# Notes receivable discount (bank discount with interest)
# ==========================================================================

class NoteDiscountRequest(BaseModel):
    note_id: int
    bank_account_id: int
    discount_rate: float = Field(..., ge=0, le=100)  # annual %
    days_to_maturity: int = Field(..., ge=0)
    date: Optional[str] = None


@router.post("/treasury/notes-receivable/{note_id}/discount",
             dependencies=[Depends(require_permission(["treasury.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def discount_note_receivable(
    note_id: int,
    body: NoteDiscountRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Record bank discounting of a note: DR Bank (net), DR Interest Expense, CR Notes Receivable (face)."""
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        note = db.execute(
            text(
                """
                SELECT id, face_value, COALESCE(status,'open') AS status
                FROM notes_receivable
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": note_id},
        ).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "note_not_found"))
        if note.status not in ("open", "issued"):
            raise HTTPException(**http_error(400, "cannot_deduct_non_open_voucher", request))

        face = _dec(note.face_value)
        rate = _dec(body.discount_rate) / Decimal("100")
        days = Decimal(str(body.days_to_maturity))
        interest = (face * rate * days / Decimal("365")).quantize(_D2)
        proceeds = (face - interest).quantize(_D2)

        txn_date = body.date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        interest_acc = get_mapped_account_id(db, "acc_map_interest_expense")
        notes_acc = get_mapped_account_id(db, "acc_map_notes_receivable")
        if not interest_acc or not notes_acc:
            raise HTTPException(**http_error(400, "receipt_voucher_accounts_not_configured", request))

        lines = [
            {"account_id": body.bank_account_id, "debit": float(proceeds), "credit": 0,
             "description": f"Discount NR #{note_id} proceeds"},
            {"account_id": interest_acc, "debit": float(interest), "credit": 0,
             "description": f"Discount NR #{note_id} interest"},
            {"account_id": notes_acc, "debit": 0, "credit": float(face),
             "description": f"Discount NR #{note_id} face"},
        ]
        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"Notes Receivable Discount #{note_id}",
            lines=lines,
            user_id=current_user.id,
            reference=f"NR-DISC-{note_id}",
            source="NoteDiscount",
            source_id=note_id,
            idempotency_key=f"nr_disc:{note_id}",
        )

        db.execute(
            text(
                """
                UPDATE notes_receivable
                SET status = 'discounted', updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"id": note_id},
        )
        db.commit()
        return {
            "note_id": note_id,
            "face_value": float(face),
            "interest": float(interest),
            "proceeds": float(proceeds),
            "journal_entry_id": je_id,
            "entry_number": je_num,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Note discount failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# Bounced check reversal
# ==========================================================================

class BounceRequest(BaseModel):
    date: Optional[str] = None
    notes: Optional[str] = None


@router.post("/treasury/checks-receivable/{check_id}/bounce",
             dependencies=[Depends(require_permission(["treasury.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def bounce_check_receivable(request: Request, 
    check_id: int,
    body: BounceRequest,
    current_user=Depends(get_current_user),
):
    """Reverse the originating deposit JE when a customer check bounces and mark the check as ``bounced``."""
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text(
                """
                SELECT id, amount, status, party_id
                FROM checks_receivable
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": check_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "check_not_found"))
        if row.status == "bounced":
            return {"ok": True, "already_bounced": True}

        txn_date = body.date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        bank_acc = get_mapped_account_id(db, "acc_map_bank")
        ar_acc = get_mapped_account_id(db, "acc_map_ar")
        if not bank_acc or not ar_acc:
            raise HTTPException(**http_error(400, "bank_ar_accounts_not_configured", request))

        amt = float(_dec(row.amount))
        lines = [
            {"account_id": ar_acc, "debit": amt, "credit": 0,
             "description": f"Check #{check_id} bounce — reinstate AR"},
            {"account_id": bank_acc, "debit": 0, "credit": amt,
             "description": f"Check #{check_id} bounce — reverse deposit"},
        ]
        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"Bounced check #{check_id}",
            lines=lines,
            user_id=current_user.id,
            reference=f"CHK-BNC-{check_id}",
            source="CheckBounce",
            source_id=check_id,
            idempotency_key=f"chk_bnc:{check_id}",
        )

        db.execute(
            text("UPDATE checks_receivable SET status='bounced', updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
            {"id": check_id},
        )
        db.commit()
        return {"check_id": check_id, "journal_entry_id": je_id, "entry_number": je_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Check bounce reversal failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# Asset revaluation (OCI / revaluation reserve)
# ==========================================================================

class AssetRevaluationRequest(BaseModel):
    new_value: float = Field(..., gt=0)
    date: Optional[str] = None
    notes: Optional[str] = None


@router.post("/assets/{asset_id}/revalue",
             dependencies=[Depends(require_permission(["assets.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def revalue_asset(request: Request, 
    asset_id: int,
    body: AssetRevaluationRequest,
    current_user=Depends(get_current_user),
):
    """Revalue a fixed asset; post the delta against the revaluation reserve (equity)."""
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text(
                """
                SELECT id, book_value, COALESCE(revaluation_reserve, 0) AS reserve, asset_account_id
                FROM assets
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": asset_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "asset_not_found"))

        old = _dec(row.book_value)
        new = _dec(body.new_value)
        delta = (new - old).quantize(_D2)
        if abs(delta) < _D2:
            return {"ok": True, "no_change": True}

        txn_date = body.date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        asset_acc = row.asset_account_id
        reserve_acc = get_mapped_account_id(db, "acc_map_revaluation_reserve")
        if not asset_acc or not reserve_acc:
            raise HTTPException(**http_error(400, "asset_revaluation_reserve_accounts_not_configured", request))

        if delta > 0:
            lines = [
                {"account_id": asset_acc, "debit": float(delta), "credit": 0, "description": f"Revaluation up asset #{asset_id}"},
                {"account_id": reserve_acc, "debit": 0, "credit": float(delta), "description": f"Revaluation reserve asset #{asset_id}"},
            ]
        else:
            abs_d = float(-delta)
            lines = [
                {"account_id": reserve_acc, "debit": abs_d, "credit": 0, "description": f"Revaluation down asset #{asset_id}"},
                {"account_id": asset_acc, "debit": 0, "credit": abs_d, "description": f"Asset write-down #{asset_id}"},
            ]

        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"Asset revaluation #{asset_id}",
            lines=lines,
            user_id=current_user.id,
            reference=f"ASSET-REVAL-{asset_id}",
            source="AssetRevaluation",
            source_id=asset_id,
            idempotency_key=f"asset_reval:{asset_id}:{txn_date}",
        )

        db.execute(
            text(
                """
                UPDATE assets
                SET book_value = :new,
                    revaluation_reserve = COALESCE(revaluation_reserve, 0) + :delta,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"new": float(new), "delta": float(delta), "id": asset_id},
        )
        db.commit()
        return {"asset_id": asset_id, "delta": float(delta), "journal_entry_id": je_id, "entry_number": je_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Asset revaluation failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# Units-of-production depreciation
# ==========================================================================

class UoPDepreciationRequest(BaseModel):
    units_produced: float = Field(..., gt=0)
    date: Optional[str] = None


@router.post("/assets/{asset_id}/depreciate-uop",
             dependencies=[Depends(require_permission(["assets.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def depreciate_asset_uop(request: Request, 
    asset_id: int,
    body: UoPDepreciationRequest,
    current_user=Depends(get_current_user),
):
    """Post units-of-production depreciation for the period."""
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text(
                """
                SELECT id, cost, salvage_value, book_value, depreciation_method,
                       expected_production_units, COALESCE(cumulative_production_units, 0) AS cum_units,
                       asset_account_id, accumulated_depreciation_account_id, depreciation_expense_account_id
                FROM assets
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": asset_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "asset_not_found"))
        if not row.expected_production_units or _dec(row.expected_production_units) <= 0:
            raise HTTPException(**http_error(400, "expected_production_units_غير_محددة_على_الأصل", request))

        depreciable_base = _dec(row.cost) - _dec(row.salvage_value)
        per_unit = (depreciable_base / _dec(row.expected_production_units)).quantize(Decimal("0.000001"))
        units = _dec(body.units_produced)
        period_dep = (per_unit * units).quantize(_D2)

        book = _dec(row.book_value)
        if period_dep > book:
            period_dep = book
        if period_dep <= Decimal("0"):
            return {"ok": True, "no_depreciation": True}

        txn_date = body.date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        if not row.depreciation_expense_account_id or not row.accumulated_depreciation_account_id:
            raise HTTPException(**http_error(400, "depreciation_accounts_not_configured_on_asset", request))

        lines = [
            {"account_id": row.depreciation_expense_account_id, "debit": float(period_dep), "credit": 0,
             "description": f"UoP depreciation asset #{asset_id}"},
            {"account_id": row.accumulated_depreciation_account_id, "debit": 0, "credit": float(period_dep),
             "description": f"Accumulated depreciation asset #{asset_id}"},
        ]
        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"UoP depreciation asset #{asset_id}",
            lines=lines,
            user_id=current_user.id,
            reference=f"ASSET-DEP-UOP-{asset_id}-{txn_date}",
            source="AssetUoPDepreciation",
            source_id=asset_id,
            idempotency_key=f"asset_dep_uop:{asset_id}:{txn_date}",
        )

        db.execute(
            text(
                """
                UPDATE assets
                SET book_value = book_value - :dep,
                    cumulative_production_units = COALESCE(cumulative_production_units, 0) + :units,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"dep": float(period_dep), "units": float(units), "id": asset_id},
        )
        db.commit()
        return {"asset_id": asset_id, "depreciation": float(period_dep), "units": float(units),
                "journal_entry_id": je_id, "entry_number": je_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("UoP depreciation failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# IFRS 16 lease modification (remeasurement)
# ==========================================================================

class LeaseModificationRequest(BaseModel):
    new_liability: float = Field(..., ge=0)
    new_rou_asset: float = Field(..., ge=0)
    modification_date: Optional[str] = None
    notes: Optional[str] = None


@router.post("/leases/{lease_id}/modify",
             dependencies=[Depends(require_permission(["accounting.manage"]))], response_model=Dict[str, Any])
def modify_lease(request: Request, 
    lease_id: int,
    body: LeaseModificationRequest,
    current_user=Depends(get_current_user),
):
    """Apply an IFRS 16 modification: adjust lease liability and ROU asset to new carrying amounts.

    Requires a ``leases`` table with ``liability_account_id`` and ``rou_asset_account_id`` columns.
    """
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text(
                """
                SELECT id,
                       COALESCE(current_liability, 0) AS liab,
                       COALESCE(rou_asset_value, 0) AS rou,
                       liability_account_id,
                       rou_asset_account_id
                FROM leases
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": lease_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "lease_not_found"))

        dliab = (_dec(body.new_liability) - _dec(row.liab)).quantize(_D2)
        drou = (_dec(body.new_rou_asset) - _dec(row.rou)).quantize(_D2)

        if abs(dliab) < _D2 and abs(drou) < _D2:
            return {"ok": True, "no_change": True}

        txn_date = body.modification_date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        if not row.liability_account_id or not row.rou_asset_account_id:
            raise HTTPException(**http_error(400, "lease_contract_accounts_not_configured", request))

        lines: List[dict] = []
        if drou > 0:
            lines.append({"account_id": row.rou_asset_account_id, "debit": float(drou), "credit": 0, "description": f"Lease #{lease_id} ROU up"})
        elif drou < 0:
            lines.append({"account_id": row.rou_asset_account_id, "debit": 0, "credit": float(-drou), "description": f"Lease #{lease_id} ROU down"})
        if dliab > 0:
            lines.append({"account_id": row.liability_account_id, "debit": 0, "credit": float(dliab), "description": f"Lease #{lease_id} liability up"})
        elif dliab < 0:
            lines.append({"account_id": row.liability_account_id, "debit": float(-dliab), "credit": 0, "description": f"Lease #{lease_id} liability down"})

        total_debit = sum(Decimal(str(l["debit"])) for l in lines)
        total_credit = sum(Decimal(str(l["credit"])) for l in lines)
        balance = (total_debit - total_credit).quantize(_D2)
        if balance != 0:
            plug_acc = get_mapped_account_id(db, "acc_map_lease_modification") or get_mapped_account_id(db, "acc_map_other_expense")
            if not plug_acc:
                raise HTTPException(**http_error(400, "lease_adjustment_account_not_configured", request))
            if balance > 0:
                lines.append({"account_id": plug_acc, "debit": 0, "credit": float(balance), "description": "Lease modification P&L"})
            else:
                lines.append({"account_id": plug_acc, "debit": float(-balance), "credit": 0, "description": "Lease modification P&L"})

        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"Lease modification #{lease_id}",
            lines=lines,
            user_id=current_user.id,
            reference=f"LEASE-MOD-{lease_id}-{txn_date}",
            source="LeaseModification",
            source_id=lease_id,
            idempotency_key=f"lease_mod:{lease_id}:{txn_date}",
        )

        db.execute(
            text(
                """
                UPDATE leases
                SET current_liability = :liab,
                    rou_asset_value = :rou,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"liab": body.new_liability, "rou": body.new_rou_asset, "id": lease_id},
        )
        db.commit()
        return {"lease_id": lease_id, "delta_liability": float(dliab), "delta_rou": float(drou),
                "journal_entry_id": je_id, "entry_number": je_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Lease modification failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# Field service request — close + post GL
# ==========================================================================

class ServiceRequestCloseRequest(BaseModel):
    revenue_amount: float = Field(0, ge=0)
    payment_method: Literal["cash", "bank", "ar"] = "ar"
    completion_date: Optional[str] = None
    notes: Optional[str] = None


@router.post("/service-requests/{request_id}/post-gl",
             dependencies=[Depends(require_permission(["services.edit", "accounting.manage"]))], response_model=Dict[str, Any])
def post_service_request_gl(
    request_id: int,
    body: ServiceRequestCloseRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Close a field service request and post the GL entry for revenue and accumulated cost.

    Convention:
      * Revenue: DR receivable/cash/bank, CR service revenue (``acc_map_service_revenue``
        with fallback to ``acc_map_sales``).
      * Cost (already recorded in ``service_request_costs``): DR cost-of-services
        (``acc_map_cogs_services`` -> fallback ``acc_map_cogs``), CR
        ``acc_map_service_cost_clearing`` (fallback ``acc_map_inventory``).

    Idempotent via ``service_request:{id}`` idempotency key.
    """
    from services import gl_service

    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text(
                """
                SELECT id, COALESCE(actual_cost, 0) AS cost, COALESCE(status, 'open') AS status
                FROM service_requests
                WHERE id = :id AND COALESCE(is_deleted, FALSE) = FALSE
                FOR UPDATE
                """
            ),
            {"id": request_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "maintenance_request_not_found"))
        if row.status in ("closed", "posted"):
            raise HTTPException(**http_error(400, "order_already_closed_and_posted", request))

        cost = _dec(row.cost)
        revenue = _dec(body.revenue_amount)
        if cost <= 0 and revenue <= 0:
            raise HTTPException(**http_error(400, "no_value_difference", request))

        txn_date = body.completion_date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        if body.payment_method == "cash":
            cash_acc = get_mapped_account_id(db, "acc_map_cash_main")
        elif body.payment_method == "bank":
            cash_acc = get_mapped_account_id(db, "acc_map_bank")
        else:
            cash_acc = get_mapped_account_id(db, "acc_map_ar")
        revenue_acc = (
            get_mapped_account_id(db, "acc_map_service_revenue")
            or get_mapped_account_id(db, "acc_map_sales")
        )
        cost_acc = (
            get_mapped_account_id(db, "acc_map_cogs_services")
            or get_mapped_account_id(db, "acc_map_cogs")
        )
        clearing_acc = (
            get_mapped_account_id(db, "acc_map_service_cost_clearing")
            or get_mapped_account_id(db, "acc_map_inventory")
        )
        # T10.1 P1 #110j — when the service consumed actual parts (rows in
        # service_request_costs with cost_type='parts' AND product_id), we
        # already decremented inventory in `add_service_cost`. The closing
        # JE must therefore credit the inventory account to mirror the
        # physical movement, not a generic clearing account.
        consumed_parts = db.execute(
            text(
                "SELECT COALESCE(SUM(total_cost), 0) AS parts_cost "
                "FROM service_request_costs "
                "WHERE service_request_id = :rid "
                "  AND COALESCE(is_deleted, FALSE) = FALSE "
                "  AND cost_type = 'parts' "
                "  AND product_id IS NOT NULL"
            ),
            {"rid": request_id},
        ).scalar() or 0
        parts_cost = _dec(consumed_parts)
        inventory_acc = get_mapped_account_id(db, "acc_map_inventory")
        if revenue > 0 and not (cash_acc and revenue_acc):
            raise HTTPException(**http_error(400, "revenue_accounts_not_configured", request))
        if cost > 0 and not (cost_acc and clearing_acc):
            raise HTTPException(**http_error(400, "cost_accounts_not_configured", request))

        lines: List[dict] = []
        if revenue > 0:
            lines.append({"account_id": cash_acc, "debit": float(revenue), "credit": 0,
                          "description": f"Service revenue SR#{request_id}"})
            lines.append({"account_id": revenue_acc, "debit": 0, "credit": float(revenue),
                          "description": f"Service revenue SR#{request_id}"})
        if cost > 0:
            lines.append({"account_id": cost_acc, "debit": float(cost), "credit": 0,
                          "description": f"Cost of services SR#{request_id}"})
            # P1 #110j — split the credit side: inventory for parts
            # actually drawn (already decremented physically), clearing
            # for labor/travel/other.
            non_parts = (cost - parts_cost) if cost > parts_cost else _dec(0)
            if parts_cost > 0 and inventory_acc:
                lines.append({"account_id": inventory_acc, "debit": 0, "credit": float(parts_cost),
                              "description": f"Service parts consumption SR#{request_id}"})
            else:
                non_parts = cost  # fallback when inventory mapping missing
            if non_parts > 0:
                lines.append({"account_id": clearing_acc, "debit": 0, "credit": float(non_parts),
                              "description": f"Service cost clearing SR#{request_id}"})

        je_id, je_num = gl_service.create_journal_entry(
            db,
            company_id=current_user.company_id,
            date=txn_date,
            description=f"Service request #{request_id} completion",
            lines=lines,
            user_id=current_user.id,
            reference=f"SR-GL-{request_id}",
            source="service_request",
            source_id=request_id,
            idempotency_key=f"service_request:{request_id}",
        )

        db.execute(
            text(
                """
                UPDATE service_requests
                SET status = 'closed',
                    closed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"id": request_id},
        )
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="service_request.post_gl", resource_type="service_request",
            resource_id=request_id,
            details={"revenue": float(revenue), "cost": float(cost), "je": je_num},
            request=request,
        )
        return {
            "request_id": request_id,
            "revenue": float(revenue),
            "cost": float(cost),
            "journal_entry_id": je_id,
            "entry_number": je_num,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Service GL posting failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# Bulk CGU impairment scan (IAS 36)
# ==========================================================================

class BulkImpairmentItem(BaseModel):
    cgu_id: int
    carrying_amount: float = Field(..., gt=0)
    value_in_use: Optional[float] = None
    fair_value_less_costs: Optional[float] = None


class BulkImpairmentRequest(BaseModel):
    as_of_date: Optional[str] = None
    post_journal: bool = False
    items: List[BulkImpairmentItem]


@router.post("/assets/cgu/impairment-bulk",
             dependencies=[Depends(require_permission(["assets.manage", "accounting.manage"]))], response_model=Dict[str, Any])
def run_bulk_cgu_impairment(request: Request, 
    body: BulkImpairmentRequest,
    current_user=Depends(get_current_user),
):
    """Run impairment tests for multiple cash-generating units in one request.

    Wraps ``services.impairment_service.record_impairment_test`` per row. When
    ``post_journal=True`` the impairment expense / accumulated impairment
    accounts must be configured via ``acc_map_impairment_expense`` and
    ``acc_map_accumulated_impairment``.
    """
    from datetime import date as _date
    from services.impairment_service import record_impairment_test

    if not body.items:
        raise HTTPException(**http_error(400, "items_فارغة", request))

    with transactional(current_user.company_id) as db:
        as_of = body.as_of_date or _date.today().isoformat()
        if body.post_journal:
            check_fiscal_period_open(db, as_of)
        exp_acc = get_mapped_account_id(db, "acc_map_impairment_expense") if body.post_journal else None
        acc_acc = get_mapped_account_id(db, "acc_map_accumulated_impairment") if body.post_journal else None
        if body.post_journal and not (exp_acc and acc_acc):
            raise HTTPException(**http_error(400, "cgu_accounts_not_configured", request))

        results = []
        total_loss = Decimal("0")
        for item in body.items:
            try:
                res = record_impairment_test(
                    db,
                    cgu_id=item.cgu_id,
                    carrying_amount=Decimal(str(item.carrying_amount)),
                    company_id=current_user.company_id,
                    value_in_use=Decimal(str(item.value_in_use)) if item.value_in_use is not None else None,
                    fair_value_less_costs=Decimal(str(item.fair_value_less_costs)) if item.fair_value_less_costs is not None else None,
                    as_of_date=_date.fromisoformat(as_of),
                    post_journal=body.post_journal,
                    impairment_expense_account_id=exp_acc,
                    accumulated_impairment_account_id=acc_acc,
                    user_id=current_user.id,
                    username=current_user.username,
                    details={"bulk": True},
                )
                total_loss += Decimal(str(res["impairment_loss"]))
                results.append(res)
            except ValueError as e:
                results.append({"cgu_id": item.cgu_id, "error": str(e)})
        return {"as_of_date": as_of, "count": len(results), "total_impairment_loss": float(total_loss), "tests": results}


# ==========================================================================
# Tenant ledger bootstrap
# ==========================================================================

class LedgerBootstrapRequest(BaseModel):
    include_ifrs: bool = True
    include_tax: bool = False
    include_management: bool = False
    base_currency: Optional[str] = None


@router.post("/accounting/ledgers/bootstrap",
             dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
def bootstrap_ledgers(
    body: LedgerBootstrapRequest,
    current_user=Depends(get_current_user),
):
    """Ensure the tenant has the standard set of accounting ledgers.

    Creates rows in ``ledgers`` if they do not exist. The ``primary`` ledger is
    seeded by ``database.create_all_tables`` already; this endpoint adds IFRS,
    tax and management ledgers idempotently.
    """
    with transactional(current_user.company_id) as db:
        targets = []
        if body.include_ifrs:
            targets.append(("ifrs", "IFRS Ledger", "ifrs"))
        if body.include_tax:
            targets.append(("tax", "Tax Ledger", "tax"))
        if body.include_management:
            targets.append(("mgmt", "Management Ledger", "mgmt"))
        created = []
        for code, name, framework in targets:
            row = db.execute(
                text(
                    """
                    INSERT INTO ledgers (code, name, is_primary, framework, currency, is_active)
                    VALUES (:c, :n, FALSE, :f, :cur, TRUE)
                    ON CONFLICT (code) DO NOTHING
                    RETURNING id
                    """
                ),
                {"c": code, "n": name, "f": framework, "cur": body.base_currency},
            ).fetchone()
            if row:
                created.append({"code": code, "id": row[0]})
        all_rows = db.execute(text("SELECT id, code, name, framework, is_primary, is_active FROM ledgers ORDER BY id")).fetchall()
        return {"created": created, "ledgers": [dict(r._mapping) for r in all_rows]}


# ==========================================================================
# POS offline batch sync (skeleton)
# ==========================================================================

class POSOfflineSale(BaseModel):
    client_uuid: str = Field(..., min_length=8, max_length=64)
    session_id: int
    payload: dict
    created_at: Optional[str] = None


class POSBatchSyncRequest(BaseModel):
    sales: List[POSOfflineSale]


@router.post("/pos/sync/batch", dependencies=[Depends(require_permission("pos.use"))], response_model=Dict[str, Any])
def pos_batch_sync(
    body: POSBatchSyncRequest,
    current_user=Depends(get_current_user),
):
    """Accept a batch of offline POS sales and queue them for processing.

    Idempotent on ``client_uuid``: rows already present in
    ``pos_offline_inbox`` are silently skipped, allowing the device to retry
    safely. The actual sale creation is performed by the regular POS endpoint
    once the row is dequeued by the POS worker.
    """
    if not body.sales:
        return {"accepted": 0, "duplicates": 0}

    with transactional(current_user.company_id) as db:
        accepted = 0
        duplicates = 0
        import json as _json
        for sale in body.sales:
            row = db.execute(
                text(
                    """
                    INSERT INTO pos_offline_inbox
                        (client_uuid, session_id, user_id, payload, client_created_at)
                    VALUES (:u, :s, :uid, CAST(:p AS JSONB), :ts)
                    ON CONFLICT (client_uuid) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "u": sale.client_uuid,
                    "s": sale.session_id,
                    "uid": current_user.id,
                    "p": _json.dumps(sale.payload, default=str, ensure_ascii=False),
                    "ts": sale.created_at,
                },
            ).fetchone()
            if row:
                accepted += 1
            else:
                duplicates += 1
        return {"accepted": accepted, "duplicates": duplicates, "queued": accepted}
