"""
AMAN ERP — Admin Account Classifications Router
Admin account-classification management endpoints.

Sensitive: admin.account_classifications, critical=True
Contract: specs/022-audit-security-finance-integrity/contracts/http-endpoints.md
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from services.permissions.sensitive import require_sensitive_permission
from utils.audit import log_activity

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/account-classifications",
    tags=["Admin Account Classifications"],
)


# ── Schemas ────────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {
    "asset", "liability", "equity", "revenue", "expense",
    "contra_asset", "contra_liability", "contra_equity",
    "contra_revenue", "contra_expense",
}

SIGN_MAP = {
    "asset": 1,
    "liability": -1,
    "equity": -1,
    "revenue": -1,
    "expense": 1,
    "contra_asset": -1,
    "contra_liability": 1,
    "contra_equity": 1,
    "contra_revenue": 1,
    "contra_expense": -1,
}


class ClassificationUpsert(BaseModel):
    account_id: int
    statement_category: str = Field(..., min_length=1)
    sign: int = Field(..., description="Must be -1 or 1")
    aggregation_hint: Optional[str] = None
    valid_from: date
    valid_to: Optional[date] = None


class ClassificationPreview(BaseModel):
    account_ids: List[int] = Field(..., min_length=1)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(require_sensitive_permission("admin.account_classifications", critical=True))],
)
def list_classifications(
    account_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    as_of: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
):
    """List account classifications with optional filters."""
    conn = get_db_connection(current_user["company_id"])
    try:
        query = """
            SELECT id, account_id, statement_category, sign, aggregation_hint,
                   valid_from, valid_to, is_active, created_at, updated_at
              FROM account_classifications
             WHERE tenant_id = :tnt
        """
        params: dict = {"tnt": current_user.get("tenant_id") or current_user.get("company_id")}

        if account_id is not None:
            query += " AND account_id = :acc"
            params["acc"] = account_id

        if is_active is not None:
            query += " AND is_active = :active"
            params["active"] = is_active

        if as_of is not None:
            query += " AND valid_from <= :as_of AND (valid_to IS NULL OR valid_to >= :as_of)"
            params["as_of"] = as_of

        query += " ORDER BY account_id, valid_from DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post(
    "",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_sensitive_permission("admin.account_classifications", critical=True))],
)
def upsert_classification(
    payload: ClassificationUpsert,
    current_user: dict = Depends(get_current_user),
):
    """Upsert an account classification."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")

    if payload.statement_category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid statement_category. Must be one of: {sorted(VALID_CATEGORIES)}",
        )

    if payload.sign not in (-1, 1):
        raise HTTPException(status_code=400, detail="sign must be -1 or 1")

    expected_sign = SIGN_MAP.get(payload.statement_category)
    if expected_sign is not None and payload.sign != expected_sign:
        raise HTTPException(
            status_code=400,
            detail=f"sign={payload.sign} does not match statement_category='{payload.statement_category}' "
                   f"(expected {expected_sign})",
        )

    conn = get_db_connection(current_user["company_id"])
    try:
        # Close previous active row (set valid_to = new valid_from - 1 day)
        conn.execute(
            text("""
                UPDATE account_classifications
                   SET valid_to = :new_start - INTERVAL '1 day', updated_at = now()
                 WHERE tenant_id = :tnt
                   AND account_id = :acc
                   AND is_active = TRUE
                   AND valid_to IS NULL
            """),
            {"tnt": tenant_id, "acc": payload.account_id, "new_start": payload.valid_from},
        )

        # Upsert (insert new row)
        row = conn.execute(
            text("""
                INSERT INTO account_classifications
                    (tenant_id, account_id, statement_category, sign, aggregation_hint,
                     valid_from, valid_to, is_active, created_at, updated_at)
                VALUES (:tnt, :acc, :cat, :sign, :hint,
                        :vfrom, :vto, TRUE, now(), now())
                RETURNING id, account_id, statement_category, sign, aggregation_hint,
                          valid_from, valid_to, is_active, created_at, updated_at
            """),
            {
                "tnt": tenant_id,
                "acc": payload.account_id,
                "cat": payload.statement_category,
                "sign": payload.sign,
                "hint": payload.aggregation_hint,
                "vfrom": payload.valid_from,
                "vto": payload.valid_to,
            },
        ).fetchone()

        log_activity(
            conn,
            action="account_classification.upsert",
            entity_type="account_classification",
            entity_id=row[0],
            actor_id=current_user.get("id"),
            details={
                "account_id": payload.account_id,
                "statement_category": payload.statement_category,
                "sign": payload.sign,
            },
            critical=True,
        )
        conn.commit()
        return dict(row._mapping)
    finally:
        conn.close()


@router.post(
    "/preview",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("admin.account_classifications", critical=True))],
)
def preview_classifications(
    payload: ClassificationPreview,
    current_user: dict = Depends(get_current_user),
):
    """Dry-run preview: return which reports would be affected by current classifications."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    conn = get_db_connection(current_user["company_id"])
    try:
        affected = []
        today = date.today()
        for acc_id in payload.account_ids:
            row = conn.execute(
                text("""
                    SELECT id, account_id, statement_category, sign, is_active
                      FROM account_classifications
                     WHERE tenant_id = :tnt
                       AND account_id = :acc
                       AND is_active = TRUE
                       AND valid_from <= :today
                       AND (valid_to IS NULL OR valid_to >= :today)
                     LIMIT 1
                """),
                {"tnt": tenant_id, "acc": acc_id, "today": today},
            ).fetchone()
            if row:
                rec = dict(row._mapping)
                reports = []
                cat = rec.get("statement_category")
                if cat in ("asset", "liability", "equity", "contra_asset", "contra_liability", "contra_equity"):
                    reports.append("balance_sheet")
                if cat in ("revenue", "expense", "contra_revenue", "contra_expense"):
                    reports.append("income_statement")
                reports.append("trial_balance")
                rec["affected_reports"] = reports
                affected.append(rec)
            else:
                affected.append({"account_id": acc_id, "classification": None, "affected_reports": []})

        return {
            "preview_date": today.isoformat(),
            "accounts": affected,
            "report_count": len(
                set(r for a in affected for r in a.get("affected_reports", []))
            ),
        }
    finally:
        conn.close()
