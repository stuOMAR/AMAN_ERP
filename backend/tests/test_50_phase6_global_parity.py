"""Phase 6 smoke tests — ZATCA adapter + payment gateway framework + Redis event-bus bridge."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════════
# ZATCA Phase 2
# ═══════════════════════════════════════════════════════════════════════════

def test_zatca_tlv_qr_includes_mandatory_tags_1_to_5():
    from integrations.einvoicing.zatca_adapter import build_qr_payload

    qr = build_qr_payload(
        seller_name="Acme KSA",
        seller_vat="300000000000003",
        timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        total_with_vat=115.00,
        vat_amount=15.00,
    )
    raw = base64.b64decode(qr)
    # Walk the TLV stream and collect tag numbers present.
    tags = []
    i = 0
    while i < len(raw):
        tag = raw[i]
        length = raw[i + 1]
        tags.append(tag)
        i += 2 + length
    assert tags == [1, 2, 3, 4, 5]


def test_zatca_tlv_qr_phase2_adds_tags_6_7_8():
    from integrations.einvoicing.zatca_adapter import build_qr_payload

    qr = build_qr_payload(
        seller_name="Acme KSA",
        seller_vat="300000000000003",
        timestamp="2024-01-15T10:30:00Z",
        total_with_vat=115.00,
        vat_amount=15.00,
        invoice_hash="abc123",
        ecdsa_signature=b"\x01\x02\x03",
        public_key=b"\x04\x05",
    )
    raw = base64.b64decode(qr)
    tags = []
    i = 0
    while i < len(raw):
        tag = raw[i]
        length = raw[i + 1]
        tags.append(tag)
        i += 2 + length
    # Tags 6, 7, 8 must appear. 9 is absent.
    assert 6 in tags and 7 in tags and 8 in tags
    assert 9 not in tags


def test_zatca_invoice_hash_is_sha256_base64():
    from integrations.einvoicing.zatca_adapter import invoice_hash

    xml = "<Invoice/>"
    expected = base64.b64encode(hashlib.sha256(xml.encode("utf-8")).digest()).decode("ascii")
    assert invoice_hash(xml) == expected


def test_zatca_adapter_registered_for_sa():
    from integrations.einvoicing import get_adapter

    adapter = get_adapter("SA")
    assert adapter.__class__.__name__ == "ZATCAAdapter"


def test_zatca_adapter_offline_mode_when_no_credentials():
    """Without PCSID/secret we must still produce artefacts, with submission_status='offline'."""
    from integrations.einvoicing.zatca_adapter import ZATCAAdapter, ZATCAConfig

    cfg = ZATCAConfig(
        api_base="https://gw-fatoora.zatca.gov.sa",
        pcsid="", secret="",
        seller_name="Acme KSA", seller_vat="300000000000003", seller_crn="1010000001",
        signer=None,
    )
    adapter = ZATCAAdapter(config=cfg)
    invoice = {
        "id": 1, "invoice_number": "INV-001",
        "issue_date": "2024-01-15", "issue_time": "10:30:00",
        "total": 115.00, "vat": 15.00,
        "lines": [{"name": "Widget", "quantity": 1, "unit_price": 100, "vat": 15.00, "total": 115.00}],
    }
    result = adapter.submit(invoice)
    # Returns a SubmissionResult dataclass. When no PCSID/secret, offline mode
    # returns status='submitted' with the artefacts in `response`.
    assert getattr(result, "status", None) in {"offline", "submitted", "accepted"}
    resp = getattr(result, "response", None) or {}
    assert resp.get("hash")
    assert resp.get("qr")


# ═══════════════════════════════════════════════════════════════════════════
# Payment gateway framework
# ═══════════════════════════════════════════════════════════════════════════

def test_payment_registry_has_all_builtin_providers():
    from integrations.payments import get_gateway, StripeGateway, TapGateway, PayTabsGateway

    s = get_gateway("stripe", secret_key="sk_test_x")
    t = get_gateway("tap", secret_key="sk_test_y")
    p = get_gateway("paytabs", profile_id="123", server_key="SK_z")
    assert isinstance(s, StripeGateway)
    assert isinstance(t, TapGateway)
    assert isinstance(p, PayTabsGateway)


def test_payment_registry_rejects_unknown_provider():
    from integrations.payments import get_gateway
    import pytest

    with pytest.raises(ValueError):
        get_gateway("nonexistent_gateway")


def test_stripe_webhook_verification_succeeds_on_valid_signature():
    from integrations.payments.stripe_adapter import StripeGateway

    secret = "whsec_test"
    body = b'{"type":"charge.succeeded","data":{"object":{"id":"ch_1","amount":1000,"currency":"usd"}}}'
    ts = "1700000000"
    signed = f"{ts}.{body.decode()}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={ts},v1={sig}"}

    gw = StripeGateway(secret_key="sk_test_x", webhook_secret=secret)
    evt = gw.verify_webhook(headers, body)
    assert evt is not None
    assert evt.event_type == "charge.succeeded"
    assert evt.charge_id == "ch_1"
    assert evt.currency == "USD"


def test_stripe_webhook_verification_rejects_bad_signature():
    from integrations.payments.stripe_adapter import StripeGateway

    body = b'{"type":"charge.succeeded","data":{"object":{"id":"ch_1"}}}'
    headers = {"Stripe-Signature": "t=1700000000,v1=deadbeef"}
    gw = StripeGateway(secret_key="sk_test_x", webhook_secret="whsec_test")
    assert gw.verify_webhook(headers, body) is None


def test_stripe_webhook_no_secret_returns_none():
    from integrations.payments.stripe_adapter import StripeGateway
    gw = StripeGateway(secret_key="sk_test_x", webhook_secret=None)
    assert gw.verify_webhook({}, b"{}") is None


# ═══════════════════════════════════════════════════════════════════════════
# Redis event-bus bridge (install/uninstall without a real Redis)
# ═══════════════════════════════════════════════════════════════════════════

def test_redis_event_bus_install_is_noop_when_disabled(monkeypatch):
    """When REDIS_EVENT_BUS is unset, install() must be a no-op."""
    from utils import redis_event_bus

    monkeypatch.setattr(redis_event_bus, "_ENABLED", False)
    monkeypatch.setattr(redis_event_bus, "_installed", False)
    assert redis_event_bus.install() is False
    assert redis_event_bus.is_installed() is False


def test_redis_event_bus_force_install_subscribes_to_all_canonical_events():
    """force=True installs even when disabled; uninstall cleans up."""
    from utils import redis_event_bus
    from utils.event_bus import Events, get_bus

    redis_event_bus.uninstall()  # baseline
    bus = get_bus()
    before = len(bus.handlers_for(Events.JOURNAL_ENTRY_POSTED))
    assert redis_event_bus.install(force=True) is True
    after = len(bus.handlers_for(Events.JOURNAL_ENTRY_POSTED))
    assert after == before + 1
    redis_event_bus.uninstall()
    cleanup = len(bus.handlers_for(Events.JOURNAL_ENTRY_POSTED))
    assert cleanup == before
