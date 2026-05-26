"""
Phase 6 ext — Shipping REST surface.

  POST /shipping/shipments              — create a shipment via a carrier.
  POST /shipping/shipments/{id}/track   — refresh & return tracking events.
  GET  /shipping/shipments              — list shipments.
  GET  /shipping/carriers               — list registered carriers.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from integrations.shipping import get_carrier, ShipmentRequest
from integrations.shipping.registry import _REGISTRY as _SHIP_REGISTRY
from routers.auth import get_current_user
from utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shipping", tags=["shipping"])


def _close(db):
    try:
        db.close()
    except Exception:
        pass


def _load_cfg(db, carrier: str, request: Request = None) -> Dict[str, Any]:
    row = db.execute(
        text("SELECT setting_value FROM company_settings WHERE setting_key = :k LIMIT 1"),
        {"k": f"shipping_carriers.{carrier.lower()}"},
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(**http_error(412, "shipping_carrier_not_configured", request, carrier=carrier))
    try:
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception:
        raise HTTPException(**http_error(500, "shipping_config_invalid_json", request))


class AddressModel(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    line1: str = ""
    line2: Optional[str] = None
    line3: Optional[str] = None
    city: str = ""
    state: Optional[str] = None
    postal: Optional[str] = None
    country: str = "SA"
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None


class CreateShipmentRequest(BaseModel):
    carrier: str = Field(..., description="aramex | dhl")
    reference: str
    origin: AddressModel
    destination: AddressModel
    weight_kg: Decimal
    service_code: Optional[str] = None
    declared_value: Optional[Decimal] = None
    currency: str = "SAR"
    cod_amount: Optional[Decimal] = None
    description: str = ""
    invoice_id: Optional[int] = None
    delivery_order_id: Optional[int] = None


@router.post("/shipments",
             dependencies=[Depends(require_permission("inventory.shipments_create"))], response_model=Dict[str, Any])
def create_shipment(body: CreateShipmentRequest, request: Request, current_user=Depends(get_current_user)):
    """Create Shipment."""
    db = get_db_connection(current_user.company_id)
    try:
        cfg = _load_cfg(db, body.carrier, request)
        carrier = get_carrier(body.carrier, **cfg)
        req = ShipmentRequest(
            reference=body.reference,
            origin=body.origin.dict(),
            destination=body.destination.dict(),
            weight_kg=body.weight_kg,
            service_code=body.service_code,
            declared_value=body.declared_value,
            currency=body.currency,
            cod_amount=body.cod_amount,
            description=body.description,
        )
        result = carrier.create_shipment(req)
        row = db.execute(
            text("""
                INSERT INTO shipments
                    (carrier, tracking_number, reference, invoice_id,
                     delivery_order_id, status, cost, currency, label_url,
                     awb_label, carrier_response, created_by)
                VALUES (:c, :trk, :ref, :inv, :do, :st, :cost, :cur, :lbl,
                        :awb, CAST(:resp AS JSONB), :uid)
                RETURNING id
            """),
            {
                "c": body.carrier.lower(),
                "trk": result.tracking_number,
                "ref": body.reference,
                "inv": body.invoice_id,
                "do": body.delivery_order_id,
                "st": result.status,
                "cost": result.cost,
                "cur": result.currency or body.currency,
                "lbl": result.label_url,
                "awb": result.awb_label,
                "resp": json.dumps(result.gateway_response or {}),
                "uid": current_user.id,
            },
        ).fetchone()
        db.commit()
        return {
            "id": row[0],
            "carrier": body.carrier,
            "tracking_number": result.tracking_number,
            "status": result.status,
            "label_url": result.label_url,
            "error_message": result.error_message,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("shipment create failed")
        raise HTTPException(**http_error(500, "shipping_create_failed", request))
    finally:
        _close(db)


@router.post("/shipments/{shipment_id}/track",
             dependencies=[Depends(require_permission("inventory.shipments_view"))], response_model=Dict[str, Any])
def track_shipment(shipment_id: int, request: Request, current_user=Depends(get_current_user)):
    """Track Shipment."""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text("SELECT carrier, tracking_number FROM shipments WHERE id = :id"),
            {"id": shipment_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "shipping_shipment_not_found", request))
        carrier_name, tracking = row[0], row[1]
        if not tracking:
            raise HTTPException(**http_error(400, "shipping_no_tracking", request))
        cfg = _load_cfg(db, carrier_name, request)
        carrier = get_carrier(carrier_name, **cfg)
        events = carrier.track(tracking)
        return {
            "shipment_id": shipment_id,
            "carrier": carrier_name,
            "tracking_number": tracking,
            "events": [
                {"code": e.code, "description": e.description,
                 "location": e.location,
                 "timestamp": e.timestamp.isoformat() if e.timestamp else None}
                for e in events
            ],
        }
    finally:
        _close(db)


@router.get("/shipments",
            dependencies=[Depends(require_permission("inventory.shipments_view"))], response_model=List[Dict[str, Any]])
def list_shipments(limit: int = 50, current_user=Depends(get_current_user)):
    """List Shipments."""
    limit = max(1, min(int(limit), 500))
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""SELECT id, carrier, tracking_number, reference, status,
                           cost, currency, created_at
                      FROM shipments ORDER BY id DESC LIMIT :n"""),
            {"n": limit},
        ).fetchall()
        return [
            {
                "id": r[0], "carrier": r[1], "tracking_number": r[2],
                "reference": r[3], "status": r[4],
                "cost": str(r[5]) if r[5] is not None else None,
                "currency": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    finally:
        _close(db)


@router.get("/carriers", response_model=Dict[str, Any])
def list_carriers() -> List[str]:
    """List Carriers."""
    return sorted(_SHIP_REGISTRY.keys())
