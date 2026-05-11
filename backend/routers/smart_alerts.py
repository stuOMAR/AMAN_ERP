"""T4.3 — Smart Alerts CRUD router.

Endpoints:
  GET    /alerts/rules            — list rules
  POST   /alerts/rules            — create rule
  PUT    /alerts/rules/{id}       — update rule
  DELETE /alerts/rules/{id}       — delete rule
  GET    /alerts/                 — list fired alerts
  POST   /alerts/{id}/resolve     — mark alert resolved
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from typing import Any, Dict, List

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["Smart Alerts"])


# ── Alert Rules ───────────────────────────────────────────────────────────────

@router.get("/rules", dependencies=[Depends(require_permission("settings.view"))], response_model=List[Dict[str, Any]])
def list_alert_rules(current_user=Depends(get_current_user)):
    """List Alert Rules."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text(
            "SELECT id, name, rule_type, condition_json, threshold, enabled, "
            "notify_users, created_at, updated_at FROM alert_rules ORDER BY id"
        )).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/rules", status_code=201, dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
def create_alert_rule(data: dict, current_user=Depends(get_current_user)):
    """Create Alert Rule."""
    _validate_rule(data)
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("""
            INSERT INTO alert_rules (name, rule_type, condition_json, threshold, enabled, notify_users)
            VALUES (:name, :rule_type, :cond, :thr, :enabled, :users)
            RETURNING id
        """), {
            "name": data["name"],
            "rule_type": data["rule_type"],
            "cond": json.dumps(data.get("condition_json", {})),
            "thr": float(data.get("threshold", 0)),
            "enabled": data.get("enabled", True),
            "users": json.dumps(data.get("notify_users", [])),
        }).fetchone()
        db.commit()
        return {"id": row[0], "message": i18n_message("alert_rule_created", request)}
    except Exception:
        db.rollback()
        logger.exception("create_alert_rule error")
        raise HTTPException(**http_error(500, ("smart_alert_internal_error", request)))
    finally:
        db.close()


@router.put("/rules/{rule_id}", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
def update_alert_rule(rule_id: int, data: dict, current_user=Depends(get_current_user)):
    """Update Alert Rule."""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id FROM alert_rules WHERE id=:id"), {"id": rule_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, ("smart_alert_rule_not_found", request)))
        db.execute(text("""
            UPDATE alert_rules SET
                name = COALESCE(:name, name),
                rule_type = COALESCE(:rule_type, rule_type),
                condition_json = COALESCE(:cond, condition_json),
                threshold = COALESCE(:thr, threshold),
                enabled = COALESCE(:enabled, enabled),
                notify_users = COALESCE(:users, notify_users),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "name": data.get("name"),
            "rule_type": data.get("rule_type"),
            "cond": json.dumps(data["condition_json"]) if "condition_json" in data else None,
            "thr": float(data["threshold"]) if "threshold" in data else None,
            "enabled": data.get("enabled"),
            "users": json.dumps(data["notify_users"]) if "notify_users" in data else None,
            "id": rule_id,
        })
        db.commit()
        return {"success": True, "message": i18n_message("alert_rule_updated", request)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("update_alert_rule error")
        raise HTTPException(**http_error(500, ("smart_alert_internal_error", request)))
    finally:
        db.close()


@router.delete("/rules/{rule_id}", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
def delete_alert_rule(rule_id: int, current_user=Depends(get_current_user)):
    """Delete Alert Rule."""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id FROM alert_rules WHERE id=:id"), {"id": rule_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, ("smart_alert_rule_not_found", request)))
        db.execute(text("DELETE FROM alert_rules WHERE id=:id"), {"id": rule_id})
        db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, ("smart_alert_internal_error", request)))
    finally:
        db.close()


# ── Fired Alerts ──────────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(require_permission("settings.view"))], response_model=List[Dict[str, Any]])
def list_alerts(
    status: str = None,
    current_user=Depends(get_current_user),
):
    """List Alerts."""
    db = get_db_connection(current_user.company_id)
    try:
        q = """
            SELECT a.id, a.rule_id, r.name AS rule_name, r.rule_type,
                   a.triggered_at, a.details_json, a.status, a.resolved_at
            FROM alerts a
            JOIN alert_rules r ON a.rule_id = r.id
        """
        params: dict = {}
        if status:
            q += " WHERE a.status = :status"
            params["status"] = status
        q += " ORDER BY a.triggered_at DESC LIMIT 200"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/{alert_id}/resolve", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
def resolve_alert(alert_id: int, current_user=Depends(get_current_user)):
    """Resolve Alert."""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id FROM alerts WHERE id=:id"), {"id": alert_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, ("smart_alert_not_found", request)))
        db.execute(text("""
            UPDATE alerts SET status='resolved', resolved_at=CURRENT_TIMESTAMP WHERE id=:id
        """), {"id": alert_id})
        db.execute(text("""
            INSERT INTO alert_history (alert_id, action, actor, created_at)
            VALUES (:aid, 'resolved', :uid, CURRENT_TIMESTAMP)
        """), {"aid": alert_id, "uid": current_user.id})
        db.commit()
        return {"success": True, "message": i18n_message("alert_resolved", request)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, ("smart_alert_internal_error", request)))
    finally:
        db.close()


# ── helpers ───────────────────────────────────────────────────────────────────
_VALID_RULE_TYPES = {"low_stock", "overdue_receivable", "budget_overspend", "custom"}

def _validate_rule(data: dict):
    if not data.get("name"):
        raise HTTPException(**http_error(400, ("smart_alert_rule_name_required", request)))
    if data.get("rule_type") not in _VALID_RULE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"نوع القاعدة غير صالح. المسموح: {sorted(_VALID_RULE_TYPES)}",
        )
