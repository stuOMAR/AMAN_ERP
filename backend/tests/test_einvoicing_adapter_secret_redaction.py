"""Audit PR 2 — verify einvoicing adapters never log raw secrets.

Closes F-NEW-001..004. Patches `requests` to a deterministic stub so we
exercise the network paths without making real HTTP calls. Spies on the
adapter's logger and asserts the test secret never appears in any record,
while a redacted preview (``****``) does appear.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

# These adapters are heavyweight modules — import only when the test runs
# so collection-time failures (e.g. missing optional deps) become test
# failures, not collection errors.


SECRET_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.SECRET_PAYLOAD.SIG"  # noqa: S105
SECRET_API_KEY = "ASP-API-KEY-SECRET-DO-NOT-LEAK-12345"  # noqa: S105


def _fake_response(status: int = 200, body: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.text = json.dumps(body or {})
    r.json.return_value = body or {}
    return r


@pytest.fixture
def caplog_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


# ──────────────────────────────────────────────────────────────────────
# ETA adapter — F-NEW-001..003
# ──────────────────────────────────────────────────────────────────────


def _build_eta_adapter(monkeypatch):
    from integrations.einvoicing.eta_adapter import EgyptETAAdapter

    a = EgyptETAAdapter(
        base_url="https://eta.example",
        token_url="https://id.example/token",
        client_id="cid",
        client_secret="csecret",
        issuer_id="issuer-1",
        dry_run=False,
    )
    # Skip the OAuth dance — return a fixed token.
    monkeypatch.setattr(a, "_get_token", lambda: SECRET_TOKEN)
    return a


def test_eta_submit_does_not_log_token(monkeypatch, caplog_at_debug):
    import integrations.einvoicing.eta_adapter as mod

    a = _build_eta_adapter(monkeypatch)
    monkeypatch.setattr(
        mod, "requests",
        MagicMock(post=lambda *a, **k: _fake_response(200, {"submissionId": "S1"}),
                  get=lambda *a, **k: _fake_response(200, {}),
                  put=lambda *a, **k: _fake_response(200, {}),
                  RequestException=Exception),
    )

    # Use the documented invoice envelope that build_document expects.
    a.submit({"id": 1, "invoice_number": "INV-1", "lines": []})

    blob = " | ".join(r.getMessage() for r in caplog_at_debug.records)
    assert "SECRET_PAYLOAD" not in blob
    assert SECRET_TOKEN not in blob
    assert "****" in blob  # redaction marker present


def test_eta_fetch_status_does_not_log_token(monkeypatch, caplog_at_debug):
    import integrations.einvoicing.eta_adapter as mod

    a = _build_eta_adapter(monkeypatch)
    monkeypatch.setattr(
        mod, "requests",
        MagicMock(get=lambda *a, **k: _fake_response(200, {"status": "valid"}),
                  RequestException=Exception),
    )
    a.fetch_status("uuid-1")
    blob = " | ".join(r.getMessage() for r in caplog_at_debug.records)
    assert SECRET_TOKEN not in blob
    assert "SECRET_PAYLOAD" not in blob


def test_eta_cancel_does_not_log_token(monkeypatch, caplog_at_debug):
    import integrations.einvoicing.eta_adapter as mod

    a = _build_eta_adapter(monkeypatch)
    monkeypatch.setattr(
        mod, "requests",
        MagicMock(put=lambda *a, **k: _fake_response(200, {}),
                  RequestException=Exception),
    )
    a.cancel("uuid-1", "manual")
    blob = " | ".join(r.getMessage() for r in caplog_at_debug.records)
    assert SECRET_TOKEN not in blob


def test_eta_http_error_does_not_log_token(monkeypatch, caplog_at_debug):
    import integrations.einvoicing.eta_adapter as mod

    a = _build_eta_adapter(monkeypatch)

    class FakeReqExc(Exception):
        pass

    def boom(*a, **k):
        raise FakeReqExc("connection refused")

    monkeypatch.setattr(
        mod, "requests",
        MagicMock(post=boom, RequestException=FakeReqExc),
    )
    a.submit({"id": 2, "invoice_number": "INV-2", "lines": []})
    blob = " | ".join(r.getMessage() for r in caplog_at_debug.records)
    assert SECRET_TOKEN not in blob


# ──────────────────────────────────────────────────────────────────────
# UAE FTA adapter — F-NEW-004
# ──────────────────────────────────────────────────────────────────────


def test_uae_fta_submit_does_not_log_api_key(monkeypatch, caplog_at_debug):
    import integrations.einvoicing.uae_fta_adapter as mod
    from integrations.einvoicing.uae_fta_adapter import UAEFTAAdapter

    a = UAEFTAAdapter(
        asp_endpoint="https://asp.example",
        api_key=SECRET_API_KEY,
        seller_trn="123456789012345",
        seller_name="Acme",
        dry_run=False,
    )
    monkeypatch.setattr(
        mod, "requests",
        MagicMock(post=lambda *a, **k: _fake_response(200, {"documentUuid": "U1", "status": "accepted"}),
                  RequestException=Exception),
    )

    a.submit({"id": 1, "invoice_number": "INV-1", "lines": []})
    blob = " | ".join(r.getMessage() for r in caplog_at_debug.records)
    assert SECRET_API_KEY not in blob
    assert "DO-NOT-LEAK" not in blob
    assert "****" in blob
