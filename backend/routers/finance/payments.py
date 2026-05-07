"""
Phase 6 — Payment gateway REST surface.

Endpoints
---------
  POST /finance/payments/charge               — create a charge on a provider.
  POST /finance/payments/webhook/{provider}   — ingest gateway webhook (public).
  GET  /finance/payments/{provider}/{charge}  — fetch local record.
  POST /finance/payments/{provider}/{charge}/refund — refund.

Gateway credentials are resolved per-tenant from `company_settings` by key
`payment_gateways.<provider>` (JSON). This keeps secrets out of source.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from decimal import Decimal
from typing import Any, Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from integrations.payments import get_gateway
from routers.auth import get_current_user
from utils.permissions import require_permission

try:  # event bus is optional in some deployments
    from utils.event_bus import publish as _bus_publish
except Exception:  # pragma: no cover - defensive
    _bus_publish = None  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/finance/payments", tags=["payments"])


# ── PAY-F1: pre-signature rate limit (per client IP + provider) ──────────
# Sliding-window limiter kept in-process to shed trivial DoS traffic before
# we do the (expensive) signature verification and DB writes.
_WEBHOOK_RL_WINDOW_SEC = 60
_WEBHOOK_RL_MAX_HITS = 120  # 2 rps per (ip, provider)
_webhook_hits: Dict[str, Deque[float]] = defaultdict(deque)
_webhook_rl_lock = threading.Lock()


def _webhook_rate_limit(ip: str, provider: str) -> bool:
    """Return True when the caller is under the limit, False when throttled."""
    key = f"{ip}:{provider}"
    now = time.monotonic()
    cutoff = now - _WEBHOOK_RL_WINDOW_SEC
    with _webhook_rl_lock:
        bucket = _webhook_hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _WEBHOOK_RL_MAX_HITS:
            return False
        bucket.append(now)
    return True


def _close(db):
    try:
        db.close()
    except Exception:
        pass


def _load_gateway_config(db, provider: str, *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch tenant-scoped gateway credentials from `company_settings`."""
    row = db.execute(
        text("""
            SELECT setting_value FROM company_settings
             WHERE setting_key = :k
             LIMIT 1
        """),
        {"k": f"payment_gateways.{provider.lower()}"},
    ).fetchone()
    if not row or not row[0]:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            f"payment gateway '{provider}' is not configured for this tenant",
        )
    try:
        cfg = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        raise HTTPException(500, f"gateway config is not valid JSON: {e}")
    if tenant_id:
        try:
            from services.integration_keys_service import get_active_key
            for key_name in ("secret_key", "webhook_secret", "api_key", "client_secret"):
                vault_value = get_active_key(
                    db,
                    integration_type="payments",
                    provider=provider.lower(),
                    key_name=key_name,
                    tenant_id=tenant_id,
                )
                if vault_value:
                    cfg[key_name] = vault_value
        except Exception:
            logger.exception("payment key vault lookup failed for provider=%s", provider)
    return cfg


# ═══════════════════════════════════════════════════════════════════════════
# Create charge
# ═══════════════════════════════════════════════════════════════════════════

class ChargeRequest(BaseModel):
    provider: str = Field(..., description="stripe | tap | paytabs")
    amount: Decimal
    currency: str = Field(..., min_length=3, max_length=10)
    source: Dict[str, Any]
    invoice_id: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None


@router.post(
    "/charge",
    dependencies=[Depends(require_permission("finance.accounting_post"))],
)
def create_charge(body: ChargeRequest, current_user=Depends(get_current_user)):
    """Create Charge."""
    db = get_db_connection(current_user.company_id)
    try:
        # idempotency — if we've already charged this key, return the prior row.
        if body.idempotency_key:
            prior = db.execute(
                text("""SELECT id, provider, charge_id, status, amount, currency
                          FROM gateway_charges
                         WHERE idempotency_key = :k AND provider = :p
                         LIMIT 1"""),
                {"k": body.idempotency_key, "p": body.provider},
            ).fetchone()
            if prior:
                return {
                    "id": prior[0], "provider": prior[1], "charge_id": prior[2],
                    "status": prior[3], "amount": str(prior[4]), "currency": prior[5],
                    "idempotent_replay": True,
                }

        cfg = _load_gateway_config(db, body.provider, tenant_id=current_user.company_id)
        gateway = get_gateway(body.provider, **cfg)
        result = gateway.create_charge(
            amount=body.amount,
            currency=body.currency,
            source=body.source,
            metadata=body.metadata,
        )

        row = db.execute(
            text("""
                INSERT INTO gateway_charges
                    (provider, charge_id, invoice_id, amount, currency,
                     status, error_message, gateway_response, idempotency_key,
                     created_by)
                VALUES (:p, :c, :inv, :amt, :cur, :st, :err,
                        CAST(:resp AS JSONB), :idem, :uid)
                RETURNING id
            """),
            {
                "p": body.provider,
                "c": result.charge_id or f"local-{body.idempotency_key or 'pending'}",
                "inv": body.invoice_id,
                "amt": result.amount or body.amount,
                "cur": (result.currency or body.currency).upper(),
                "st": result.status,
                "err": result.error_message,
                "resp": json.dumps(result.gateway_response or {}),
                "idem": body.idempotency_key,
                "uid": current_user.id,
            },
        ).fetchone()
        db.commit()

        if _bus_publish and result.status == "captured":
            try:
                _bus_publish("payment.captured", {
                    "charge_id": result.charge_id,
                    "provider": body.provider,
                    "amount": str(result.amount or body.amount),
                    "currency": (result.currency or body.currency).upper(),
                    "invoice_id": body.invoice_id,
                })
            except Exception:
                logger.exception("payment.captured publish failed")

        return {
            "id": row[0],
            "provider": body.provider,
            "charge_id": result.charge_id,
            "status": result.status,
            "amount": str(result.amount or body.amount),
            "currency": (result.currency or body.currency).upper(),
            "error_message": result.error_message,
            "gateway_response": result.gateway_response,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("payment charge failed")
        raise HTTPException(500, f"payment charge failed: {e}")
    finally:
        _close(db)


# ═══════════════════════════════════════════════════════════════════════════
# Webhook (unauthenticated — we verify via signature)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/webhook/{provider}/{company_id}")
async def webhook(provider: str, company_id: str, request: Request):
    """
    Tenant-scoped webhook endpoint.

    Providers are configured to POST to
    `https://…/finance/payments/webhook/{provider}/{company_id}` so the
    tenant is known from the URL and we can load the right secrets.
    """
    # Feature 022: per-tenant Redis token-bucket rate limit
    try:
        from services.webhook_rate_limit import check_and_consume
        tenant_id_int = int(company_id) if company_id.isdigit() else 0
        decision = check_and_consume(tenant_id_int, provider)
        if not decision.allowed:
            logger.warning("webhook rate-limited tenant=%s provider=%s", company_id, provider)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="tenant webhook quota exceeded",
                headers={"Retry-After": str(decision.retry_after_seconds or 60)},
            )
    except HTTPException:
        raise
    except Exception:
        logger.debug("webhook_rate_limit check skipped", exc_info=True)

    # PAY-F1: cheap pre-signature throttle (per caller IP + provider).
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _webhook_rate_limit(client_ip, provider):
        logger.warning("webhook rate-limited ip=%s provider=%s", client_ip, provider)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many webhook requests",
        )

    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}

    tenant_db = get_db_connection(company_id)
    try:
        cfg = _load_gateway_config(tenant_db, provider, tenant_id=company_id)
        gateway = get_gateway(provider, **cfg)
        verified = gateway.verify_webhook(headers, raw)
    except HTTPException:
        _close(tenant_db)
        raise

    if not verified:
        try:
            tenant_db.execute(
                text("""INSERT INTO gateway_webhook_events
                            (provider, event_type, payload, verified)
                        VALUES (:p, :t, CAST(:pl AS JSONB), FALSE)"""),
                {"p": provider, "t": "unverified",
                 "pl": json.dumps({"raw": raw.decode("utf-8", errors="replace")[:65_000]})},
            )
            tenant_db.commit()
        except Exception:
            tenant_db.rollback()
        finally:
            _close(tenant_db)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "webhook signature invalid")

    # Persist + update charge status in matched tenant
    try:
        tenant_db.execute(
            text("""INSERT INTO gateway_webhook_events
                        (provider, event_type, charge_id, payload, verified)
                    VALUES (:p, :t, :c, CAST(:pl AS JSONB), TRUE)"""),
            {"p": provider, "t": verified.event_type,
             "c": verified.charge_id,
             "pl": json.dumps(verified.payload)},
        )
        new_status = None
        if "succeeded" in verified.event_type or "captured" in verified.event_type:
            new_status = "captured"
        elif "failed" in verified.event_type:
            new_status = "failed"
        elif "refund" in verified.event_type:
            new_status = "refunded"
        elif "cancel" in verified.event_type:
            new_status = "cancelled"
        if new_status and verified.charge_id:
            tenant_db.execute(
                text("""UPDATE gateway_charges
                           SET status = :s, updated_at = CURRENT_TIMESTAMP,
                               gateway_response = CAST(:pl AS JSONB)
                         WHERE provider = :p AND charge_id = :c"""),
                {"s": new_status, "p": provider, "c": verified.charge_id,
                 "pl": json.dumps(verified.payload)},
            )
        tenant_db.commit()
        if _bus_publish and new_status:
            try:
                _bus_publish(f"payment.{new_status}", {
                    "provider": provider,
                    "charge_id": verified.charge_id,
                    "company_id": company_id,
                })
            except Exception:
                pass
        return {"status": "ok", "event_type": verified.event_type}
    finally:
        _close(tenant_db)


# ═══════════════════════════════════════════════════════════════════════════
# Fetch / refund
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{provider}/{charge_id}",
            dependencies=[Depends(require_permission("finance.accounting_read"))])
def fetch_charge(provider: str, charge_id: str, current_user=Depends(get_current_user)):
    """Fetch Charge."""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text("""SELECT id, provider, charge_id, invoice_id, amount, currency,
                           status, error_message, created_at, updated_at
                      FROM gateway_charges
                     WHERE provider = :p AND charge_id = :c
                     LIMIT 1"""),
            {"p": provider, "c": charge_id},
        ).fetchone()
        if not row:
            raise HTTPException(404, "charge not found")
        return {
            "id": row[0], "provider": row[1], "charge_id": row[2],
            "invoice_id": row[3], "amount": str(row[4]), "currency": row[5],
            "status": row[6], "error_message": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
    finally:
        _close(db)


class RefundRequest(BaseModel):
    amount: Optional[Decimal] = None
    reason: Optional[str] = None


@router.post("/{provider}/{charge_id}/refund",
             dependencies=[Depends(require_permission("finance.accounting_post"))])
def refund_charge(provider: str, charge_id: str, body: RefundRequest,
                  current_user=Depends(get_current_user)):
    """Refund Charge."""
    db = get_db_connection(current_user.company_id)
    try:
        cfg = _load_gateway_config(db, provider, tenant_id=current_user.company_id)
        gateway = get_gateway(provider, **cfg)
        result = gateway.refund(charge_id, amount=body.amount, reason=body.reason)
        db.execute(
            text("""UPDATE gateway_charges
                       SET status = :s, updated_at = CURRENT_TIMESTAMP,
                           gateway_response = CAST(:pl AS JSONB)
                     WHERE provider = :p AND charge_id = :c"""),
            {"s": result.status, "p": provider, "c": charge_id,
             "pl": json.dumps(result.gateway_response or {})},
        )
        db.commit()
        return {"status": result.status, "charge_id": result.charge_id,
                "error_message": result.error_message}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("refund failed")
        raise HTTPException(500, f"refund failed: {e}")
    finally:
        _close(db)
