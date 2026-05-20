"""
Stripe payment gateway adapter.

Uses the Stripe REST API directly via `requests` (no SDK dependency) so this
module stays lean. Supports:
  * Charges API (`/v1/charges`) for simple card / token sources.
  * PaymentIntents (`/v1/payment_intents`) when `source["type"] == "payment_intent"`.
  * Webhook signature verification per Stripe's `t=...,v1=...` scheme.
  * Refunds.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

import requests

from .base import ChargeResult, PaymentGateway, WebhookEvent

logger = logging.getLogger(__name__)

_ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG",
                 "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


def _to_minor(amount: Decimal, currency: str) -> int:
    """Convert major units → Stripe's integer minor units."""
    if currency.upper() in _ZERO_DECIMAL:
        return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class StripeGateway(PaymentGateway):
    provider = "stripe"

    def __init__(self, secret_key: str, webhook_secret: Optional[str] = None,
                 api_base: str = "https://api.stripe.com", timeout: int = 30):
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def create_charge(self, amount, currency, source, metadata=None) -> ChargeResult:
        amount = Decimal(str(amount))
        currency = (currency or "USD").upper()
        data: Dict[str, Any] = {
            "amount": _to_minor(amount, currency),
            "currency": currency.lower(),
        }
        if source.get("type") == "payment_intent":
            data["payment_method"] = source["payment_method_id"]
            data["confirm"] = "true"
            endpoint = "/v1/payment_intents"
        else:
            data["source"] = source.get("token") or source.get("source")
            data["description"] = (metadata or {}).get("description", "")
            endpoint = "/v1/charges"
        for k, v in (metadata or {}).items():
            data[f"metadata[{k}]"] = str(v)
        try:
            r = requests.post(self.api_base + endpoint, data=data,
                              auth=(self.secret_key, ""), timeout=self.timeout)
            body = r.json()
        except requests.RequestException as e:
            return ChargeResult(status="failed", error_message=str(e))
        if r.status_code >= 400:
            return ChargeResult(status="failed",
                                gateway_response=body,
                                error_message=(body.get("error") or {}).get("message"))
        status_map = {"succeeded": "captured", "pending": "pending",
                      "requires_action": "pending", "failed": "failed"}
        stripe_status = body.get("status", "succeeded")
        return ChargeResult(
            status=status_map.get(stripe_status, stripe_status),
            charge_id=body.get("id"),
            amount=amount,
            currency=currency,
            gateway_response=body,
        )

    def verify_webhook(self, headers, raw_body) -> Optional[WebhookEvent]:
        if not self.webhook_secret:
            return None
        sig_header = headers.get("Stripe-Signature") or headers.get("stripe-signature") or ""
        ts = None
        signatures: list[str] = []
        for part in sig_header.split(","):
            k, _, v = part.partition("=")
            if k == "t":
                ts = v
            elif k == "v1":
                signatures.append(v)
        if not ts or not signatures:
            return None
        signed = f"{ts}.{raw_body.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(self.webhook_secret.encode("utf-8"), signed,
                            hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, s) for s in signatures):
            return None
        try:
            payload = json.loads(raw_body)
        except Exception:
            return None
        data_obj = (payload.get("data") or {}).get("object") or {}
        amt = data_obj.get("amount")
        amount = Decimal(amt) / (1 if data_obj.get("currency", "").upper() in _ZERO_DECIMAL else 100) if amt is not None else None
        return WebhookEvent(
            event_type=payload.get("type") or "unknown",
            charge_id=data_obj.get("id"),
            amount=amount,
            currency=(data_obj.get("currency") or "").upper() or None,
            payload=payload,
        )

    def refund(self, charge_id, amount=None, reason=None) -> ChargeResult:
        data: Dict[str, Any] = {"charge": charge_id}
        if amount is not None:
            data["amount"] = int(Decimal(amount) * 100)
        if reason:
            data["reason"] = reason
        try:
            r = requests.post(self.api_base + "/v1/refunds", data=data,
                              auth=(self.secret_key, ""), timeout=self.timeout)
            body = r.json()
        except requests.RequestException as e:
            return ChargeResult(status="failed", error_message=str(e))
        if r.status_code >= 400:
            return ChargeResult(status="failed", gateway_response=body,
                                error_message=(body.get("error") or {}).get("message"))
        return ChargeResult(status="refunded", charge_id=body.get("id"),
                            gateway_response=body)
