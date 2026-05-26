"""Phase 6 extensions — SMS + shipping + bank-feeds + encryption + multi-book + WHT."""

from __future__ import annotations

from decimal import Decimal


# ═══════════════════════════════════════════════════════════════════════════
# SMS integration framework
# ═══════════════════════════════════════════════════════════════════════════

def test_sms_registry_resolves_known_providers():
    from integrations.sms import get_gateway
    from integrations.sms.twilio_adapter import TwilioGateway
    from integrations.sms.unifonic_adapter import UnifonicGateway
    from integrations.sms.taqnyat_adapter import TaqnyatGateway

    tw = get_gateway("twilio", account_sid="AC", auth_token="tok", from_number="+1")
    un = get_gateway("unifonic", app_sid="app", sender_id="Brand")
    tq = get_gateway("taqnyat", bearer_token="tok", sender="Brand")
    assert isinstance(tw, TwilioGateway)
    assert isinstance(un, UnifonicGateway)
    assert isinstance(tq, TaqnyatGateway)


def test_sms_gsm7_segment_counts():
    from integrations.sms.twilio_adapter import _segments

    assert _segments("hello") == 1                 # 5 chars
    assert _segments("a" * 160) == 1               # GSM-7 boundary
    assert _segments("a" * 161) == 2               # multi-segment GSM-7
    assert _segments("مرحبا") == 1                 # Arabic → UCS-2, <=70
    assert _segments("م" * 71) == 2                 # Arabic >70 → 2 parts


def test_sms_unknown_provider_raises():
    from integrations.sms import get_gateway
    import pytest
    with pytest.raises(ValueError):
        get_gateway("fakeprovider", foo="bar")


# ═══════════════════════════════════════════════════════════════════════════
# Shipping integration framework
# ═══════════════════════════════════════════════════════════════════════════

def test_shipping_registry_resolves_carriers():
    from integrations.shipping import get_carrier
    from integrations.shipping.aramex_adapter import AramexCarrier
    from integrations.shipping.dhl_adapter import DHLCarrier

    ax = get_carrier("aramex", username="u", password="p",
                     account_number="123", account_pin="456")
    dh = get_carrier("dhl", username="u", password="p", account_number="999")
    assert isinstance(ax, AramexCarrier)
    assert isinstance(dh, DHLCarrier)


def test_shipping_request_dataclass_defaults():
    from integrations.shipping.base import ShipmentRequest

    req = ShipmentRequest(
        reference="R-1",
        origin={"country": "SA"},
        destination={"country": "AE"},
        weight_kg=Decimal("2.5"),
    )
    assert req.currency == "SAR"
    assert req.description == ""
    assert req.cod_amount is None


# ═══════════════════════════════════════════════════════════════════════════
# MT940 bank-statement parser
# ═══════════════════════════════════════════════════════════════════════════

MT940_SAMPLE = """:20:STMT0001
:25:SA03800000000123456789
:28C:00001/001
:60F:C240115EUR1500,00
:61:2401150115D50,00NTRFNONREF//BREF123
Rent payment
:86:RENT JAN 2024
:61:2401160116C250,00NMSCINV001//BREF456
:86:Customer transfer - INV001
:62F:C240116EUR1700,00
"""


def test_mt940_parses_opening_closing_and_signed_amounts():
    from integrations.bank_feeds import parse_mt940

    statements = parse_mt940(MT940_SAMPLE)
    assert len(statements) == 1
    s = statements[0]
    assert s.account == "SA03800000000123456789"
    assert s.currency == "EUR"
    assert s.opening_balance == Decimal("1500.00")
    assert s.closing_balance == Decimal("1700.00")
    assert len(s.transactions) == 2

    debit, credit = s.transactions
    assert debit.amount == Decimal("-50.00")
    assert debit.transaction_type == "NTRF"
    assert debit.bank_reference == "BREF123"
    assert "RENT JAN 2024" in debit.description
    assert credit.amount == Decimal("250.00")
    assert credit.transaction_type == "NMSC"


def test_csv_statement_parser_roundtrip():
    from integrations.bank_feeds import parse_csv_statement, CSVStatementConfig

    csv_raw = (
        "Date,Description,Amount,Reference,Balance\n"
        "2024-01-15,Rent,-50.00,INV-RENT,1450.00\n"
        "2024-01-16,Customer Xfer,250.00,INV-001,1700.00\n"
    )
    rows = parse_csv_statement(csv_raw, CSVStatementConfig())
    assert len(rows) == 2
    assert rows[0]["amount"] == Decimal("-50.00")
    assert rows[1]["amount"] == Decimal("250.00")
    assert rows[1]["reference"] == "INV-001"


# ═══════════════════════════════════════════════════════════════════════════
# Field-level encryption
# ═══════════════════════════════════════════════════════════════════════════

def test_field_encryption_roundtrip(monkeypatch):
    import base64
    import os
    from utils import field_encryption as fe

    monkeypatch.setenv("FIELD_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(os.urandom(32)).decode())
    token = fe.encrypt("salary:15000 SAR", tenant_id="T1")
    assert token and token != "salary:15000 SAR"
    assert fe.decrypt(token, tenant_id="T1") == "salary:15000 SAR"
    assert fe.is_encrypted(token)
    # Deterministic fingerprint for indexed search
    fp1 = fe.fingerprint("300000000000003", tenant_id="T1")
    fp2 = fe.fingerprint("300000000000003", tenant_id="T1")
    assert fp1 == fp2 and len(fp1) == 22


def test_field_encryption_tenant_isolation(monkeypatch):
    import base64
    import os
    from utils import field_encryption as fe

    monkeypatch.setenv("FIELD_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(os.urandom(32)).decode())
    token = fe.encrypt("secret", tenant_id="tenant-A")
    try:
        out = fe.decrypt(token, tenant_id="tenant-B")
    except fe.FieldEncryptionError:
        return   # expected — different tenant key
    assert out != "secret"


def test_field_encryption_requires_key(monkeypatch):
    from utils import field_encryption as fe
    import pytest
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MASTER_SECRET", raising=False)
    with pytest.raises(fe.FieldEncryptionError):
        fe.encrypt("plaintext", tenant_id="T1")


# ═══════════════════════════════════════════════════════════════════════════
# WHT service (pure-function helpers — no DB required for compute)
# ═══════════════════════════════════════════════════════════════════════════

def test_wht_augment_payment_lines_inserts_wht_credit():
    from services.wht_service import augment_payment_lines, WHTBreakdown

    gross = Decimal("10000.00")
    br = WHTBreakdown(
        gross=gross, rate=Decimal("0.05"),
        wht_amount=Decimal("500.00"), net=Decimal("9500.00"),
        rule_id=1, country="SA", payment_type="royalties",
        gl_account_id=99,
    )
    lines = [
        {"account_id": 1001, "debit": 10000, "credit": 0},    # expense
        {"account_id": 2001, "debit": 0, "credit": 10000},    # bank (gross)
    ]
    new = augment_payment_lines(lines, br, bank_account_id=2001, expense_account_id=1001)
    # Bank credit reduced to net; a WHT credit line added.
    bank_line = next(line for line in new if line["account_id"] == 2001)
    assert Decimal(str(bank_line["credit"])) == Decimal("9500.00")
    wht_line = next(line for line in new if line["account_id"] == 99)
    assert Decimal(str(wht_line["credit"])) == Decimal("500.00")
    # Debit total still equals credit total.
    total_debit = sum(Decimal(str(line.get("debit", 0))) for line in new)
    total_credit = sum(Decimal(str(line.get("credit", 0))) for line in new)
    assert total_debit == total_credit == Decimal("10000.00")


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic v2 migration — schemas still construct & validate
# ═══════════════════════════════════════════════════════════════════════════

def test_campaign_schema_pydantic_v2_config():
    from schemas.campaign import CampaignRead, RecipientStatusRead
    # Pydantic v2 uses model_config; ensure from_attributes is set.
    assert CampaignRead.model_config.get("from_attributes") is True
    assert RecipientStatusRead.model_config.get("from_attributes") is True


def test_sso_schema_pydantic_v2_config():
    from schemas.sso import SsoConfigRead, GroupRoleMappingRead
    assert SsoConfigRead.model_config.get("from_attributes") is True
    assert GroupRoleMappingRead.model_config.get("from_attributes") is True


def test_pos_schema_validators_still_enforce_rules():
    import pytest
    from schemas.pos import OrderLineCreate, OrderPaymentCreate

    with pytest.raises(Exception):
        OrderLineCreate(product_id=1, quantity=Decimal("0"),
                        unit_price=Decimal("10"))
    with pytest.raises(Exception):
        OrderPaymentCreate(method="cash", amount=Decimal("0"))
    # Valid construction works
    ok = OrderLineCreate(product_id=1, quantity=Decimal("2"),
                         unit_price=Decimal("5"))
    assert ok.quantity == Decimal("2")
