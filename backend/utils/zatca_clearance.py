"""T1.5c: ZATCA Phase 2 clearance helper.

Wires the existing per-jurisdiction ZATCA adapter into the invoice
creation flow. Three layers cooperate:

  1.  ``utils.zatca.process_invoice_for_zatca`` — generates the LOCAL
      artefacts (TLV QR, hash, optional signature) and persists them on
      the invoice. Always runs regardless of enforcement.
  2.  This module — when ``settings.ZATCA_PHASE2_ENFORCE`` is true AND the
      tenant is configured for SA, calls the registered adapter's
      ``submit()`` to obtain remote acceptance from ZATCA. Records the
      outcome on ``invoices.zatca_clearance_status``.
  3.  ``routers/finance/accounting_depth.py:einvoice_outbox_relay`` —
      retries any payload that this module could not deliver synchronously
      (network failures or "offline" responses).

Failure mode contract for the caller (``routers/sales/invoices.py``):

  * ``cleared`` / ``reported``  → invoice is final; nothing to do.
  * ``pending_clearance``       → invoice persisted; outbox will retry.
                                   Caller continues the success path but
                                   should display the pending state to
                                   the operator.
  * ``rejected``                 → ZATCA refused the document. Caller
                                   MUST raise HTTP 422 so the operator
                                   sees the error and can correct the
                                   data; the invoice row is rolled back
                                   by the surrounding transaction.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

from config import settings

logger = logging.getLogger(__name__)


def _enqueue_outbox(db, *, invoice_id: int, payload: Dict[str, Any],
                    adapter_code: str, last_error: str) -> None:
    """Insert a row in ``einvoice_outbox`` for the relay worker."""
    try:
        db.execute(text("""
            INSERT INTO einvoice_outbox
                (invoice_id, adapter, payload, status, attempts,
                 idempotency_key, last_error, last_attempt_at, next_attempt_at)
            VALUES (:iid, :adp, CAST(:pl AS JSONB), 'pending', 1,
                    :idem, :err, CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP + INTERVAL '5 minutes')
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO UPDATE SET payload = EXCLUDED.payload,
                          last_error = EXCLUDED.last_error,
                          next_attempt_at = EXCLUDED.next_attempt_at,
                          updated_at = CURRENT_TIMESTAMP
        """), {
            "iid": invoice_id,
            "adp": adapter_code,
            "pl": json.dumps(payload, default=str, ensure_ascii=False),
            "idem": f"einvoice:{adapter_code}:{invoice_id}",
            "err": last_error[:500],
        })
    except Exception:
        logger.exception("zatca_clearance: failed to enqueue outbox row")


def _update_invoice_clearance(db, invoice_id: int, *,
                              status_value: str,
                              uuid: Optional[str] = None,
                              error: Optional[str] = None,
                              cleared: bool = False) -> None:
    db.execute(
        text("""
            UPDATE invoices SET
              zatca_clearance_status = :s,
              zatca_cleared_uuid     = COALESCE(:u, zatca_cleared_uuid),
              zatca_cleared_at       = CASE WHEN :cleared THEN CURRENT_TIMESTAMP
                                            ELSE zatca_cleared_at END,
              zatca_clearance_error  = :err
            WHERE id = :id
        """),
        {"s": status_value, "u": uuid, "cleared": cleared,
         "err": (error or "")[:500] if error else None, "id": invoice_id},
    )


def attempt_clearance(db, *, invoice_id: int, jurisdiction: str,
                      invoice_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt synchronous ZATCA clearance for ``invoice_id``.

    Returns a dict ``{"status": <one of cleared|reported|pending_clearance|
    rejected|not_required>, "error": Optional[str], "uuid": Optional[str]}``.
    Never raises — the caller decides whether to fail the request based on
    the returned status (rejected only).

    Pre-conditions: ``invoices`` row already exists in this transaction;
    ``utils.zatca.process_invoice_for_zatca`` has already populated the
    local artefacts (hash/QR).
    """
    # Enforcement gate. When the flag is off, do nothing — callers continue
    # to rely on the legacy local-only artefact generation.
    if not getattr(settings, "ZATCA_PHASE2_ENFORCE", False):
        return {"status": "not_required", "error": None, "uuid": None}

    # Only wire up SA tenants. Other jurisdictions are out of scope here.
    if (jurisdiction or "").upper() != "SA":
        _update_invoice_clearance(db, invoice_id, status_value="not_required")
        return {"status": "not_required", "error": None, "uuid": None}

    try:
        from integrations.einvoicing.registry import get_adapter
        adapter = get_adapter("SA")
    except Exception as e:
        logger.exception("zatca_clearance: get_adapter failed")
        _enqueue_outbox(db, invoice_id=invoice_id, payload=invoice_payload,
                        adapter_code="SA",
                        last_error=f"adapter_init: {e}")
        _update_invoice_clearance(db, invoice_id,
                                  status_value="pending_clearance",
                                  error=f"adapter_init: {e}")
        return {"status": "pending_clearance", "error": str(e), "uuid": None}

    try:
        result = adapter.submit({"id": invoice_id, **invoice_payload})
    except Exception as e:
        logger.exception("zatca_clearance: adapter.submit threw")
        _enqueue_outbox(db, invoice_id=invoice_id, payload=invoice_payload,
                        adapter_code="SA", last_error=f"submit_exc: {e}")
        _update_invoice_clearance(db, invoice_id,
                                  status_value="pending_clearance",
                                  error=f"submit_exc: {e}")
        return {"status": "pending_clearance", "error": str(e), "uuid": None}

    outcome = (result.status or "").lower()
    response = result.response or {}
    is_offline = bool(response.get("offline"))
    document_uuid = result.document_uuid

    # Success.
    if outcome in ("accepted", "cleared", "reported", "ok", "success") and not is_offline:
        terminal = "cleared" if outcome == "cleared" else "reported" \
                   if outcome == "reported" else "cleared"
        _update_invoice_clearance(db, invoice_id, status_value=terminal,
                                  uuid=document_uuid, cleared=True, error=None)
        return {"status": terminal, "error": None, "uuid": document_uuid}

    # Hard rejection — caller will roll back the transaction.
    if outcome == "rejected":
        err = result.error_message or "ZATCA rejected the invoice"
        _update_invoice_clearance(db, invoice_id, status_value="rejected",
                                  uuid=document_uuid, error=err)
        return {"status": "rejected", "error": err, "uuid": document_uuid}

    # Anything else (offline, error, transient) — enqueue and stay pending.
    err = result.error_message or (
        "offline: adapter unconfigured (no PCSID/secret) — payload saved for retry"
        if is_offline else f"transient: status={outcome}"
    )
    _enqueue_outbox(db, invoice_id=invoice_id, payload=invoice_payload,
                    adapter_code="SA", last_error=err)
    _update_invoice_clearance(db, invoice_id,
                              status_value="pending_clearance",
                              uuid=document_uuid, error=err)
    return {"status": "pending_clearance", "error": err, "uuid": document_uuid}
