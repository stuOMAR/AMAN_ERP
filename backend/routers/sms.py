"""
Phase 6 ext — SMS gateway REST surface.

Endpoints
---------
  POST /sms/send                 — dispatch an SMS via a registered gateway.
  GET  /sms/logs                 — list recent SMS messages.
  GET  /sms/providers            — list registered providers.
  GET  /sms/{provider}/balance   — query gateway credit balance.

Gateway credentials are resolved per-tenant from `company_settings` by key
`sms_gateways.<provider>` (JSON), so secrets stay out of source.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from integrations.sms import get_gateway
from integrations.sms.registry import _REGISTRY as _SMS_REGISTRY
from routers.auth import get_current_user
from utils.i18n import http_error
from utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sms", tags=["sms"])


def _close(db):
    try:
        db.close()
    except Exception:
        pass


def _load_cfg(db, provider: str, request: Request) -> Dict[str, Any]:
    row = db.execute(
        text("SELECT setting_value FROM company_settings WHERE setting_key = :k LIMIT 1"),
        {"k": f"sms_gateways.{provider.lower()}"},
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(**http_error(412, "sms_gateway_not_configured", request, provider=provider))
    try:
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        raise HTTPException(**http_error(500, "sms_config_invalid_json", request))


class SendSMSRequest(BaseModel):
    provider: str = Field(..., description="twilio | unifonic | taqnyat")
    to: str
    message: str
    sender: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post(
    "/send",
    dependencies=[Depends(require_permission("notifications.send"))],
)
def send_sms(body: SendSMSRequest, request: Request, current_user=Depends(get_current_user)):
    """Send SMS."""
    db = get_db_connection(current_user.company_id)
    try:
        cfg = _load_cfg(db, body.provider, request)
        gw = get_gateway(body.provider, **cfg)
        result = gw.send(body.to, body.message, sender=body.sender, metadata=body.metadata)
        row = db.execute(
            text("""
                INSERT INTO sms_log
                    (provider, message_id, to_number, body, segments, status,
                     cost, error_message, gateway_response, created_by)
                VALUES (:p, :mid, :to, :body, :seg, :st, :cost, :err,
                        CAST(:resp AS JSONB), :uid)
                RETURNING id
            """),
            {
                "p": body.provider, "mid": result.message_id, "to": body.to,
                "body": body.message, "seg": result.segments,
                "st": result.status, "cost": result.cost,
                "err": result.error_message,
                "resp": json.dumps(result.gateway_response or {}),
                "uid": current_user.id,
            },
        ).fetchone()
        db.commit()
        return {
            "id": row[0],
            "provider": body.provider,
            "message_id": result.message_id,
            "status": result.status,
            "segments": result.segments,
            "cost": str(result.cost) if result.cost is not None else None,
            "error_message": result.error_message,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("sms.send failed")
        raise HTTPException(**http_error(500, "sms_send_failed", request, error=str(e)))
    finally:
        _close(db)


@router.get("/logs", dependencies=[Depends(require_permission("notifications.view"))])
def list_sms(limit: int = 50, current_user=Depends(get_current_user)) -> List[Dict[str, Any]]:
    """List SMS."""
    limit = max(1, min(int(limit), 500))
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""SELECT id, provider, message_id, to_number, segments,
                           status, cost, created_at
                      FROM sms_log ORDER BY id DESC LIMIT :n"""),
            {"n": limit},
        ).fetchall()
        return [
            {
                "id": r[0], "provider": r[1], "message_id": r[2],
                "to": r[3], "segments": r[4], "status": r[5],
                "cost": str(r[6]) if r[6] is not None else None,
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    finally:
        _close(db)


@router.get("/providers")
def list_providers() -> List[str]:
    """List Providers."""
    return sorted(_SMS_REGISTRY.keys())


@router.get("/{provider}/balance",
            dependencies=[Depends(require_permission("notifications.view"))])
def gateway_balance(provider: str, request: Request, current_user=Depends(get_current_user)):
    """Gateway Balance."""
    db = get_db_connection(current_user.company_id)
    try:
        cfg = _load_cfg(db, provider, request)
        gw = get_gateway(provider, **cfg)
        bal = gw.get_balance()
        return {"provider": provider, "balance": str(bal) if bal is not None else None}
    finally:
        _close(db)
