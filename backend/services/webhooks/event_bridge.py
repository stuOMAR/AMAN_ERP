"""Bridge in-process domain events to outbound webhook outbox rows."""
from __future__ import annotations

import logging
from typing import Any

from database import get_db_connection
from services.webhooks.dispatch import dispatch
from utils.event_bus import Events, get_bus

logger = logging.getLogger(__name__)

_REGISTERED = False


def _tenant_numeric(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _handle_event(event) -> None:
    payload = dict(event.payload or {})
    company_id = payload.get("company_id") or payload.get("tenant_id")
    if not company_id:
        return
    conn = get_db_connection(str(company_id))
    try:
        dispatch(
            conn,
            tenant_id=_tenant_numeric(company_id),
            event=event.name,
            payload=payload,
        )
        conn.commit()
    except Exception:
        logger.warning("webhook event bridge dispatch failed for %s", event.name)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def register_webhook_event_bridge() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    bus = get_bus()
    for event_name in (
        Events.JOURNAL_ENTRY_POSTED,
        Events.JOURNAL_ENTRY_REVERSED,
        Events.SALES_INVOICE_POSTED,
        Events.SALES_INVOICE_CANCELLED,
        Events.SALES_PAYMENT_RECEIVED,
        Events.PURCHASE_INVOICE_POSTED,
        Events.PURCHASE_PAYMENT_MADE,
        Events.INVENTORY_MOVEMENT_POSTED,
        Events.PAYROLL_RUN_POSTED,
    ):
        bus.subscribe(event_name, _handle_event)
    _REGISTERED = True
