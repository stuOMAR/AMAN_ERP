"""Audit PR 12 (Batch 12) — Missing BE permission on /api/reports/* surface.

Closes the 5 R-MISSING-PERMISSION High findings:

* F-NEW-164 — POST /api/reports/cache/refresh   (line ~45)  → reports.refresh / admin.cache (sensitive)
* F-NEW-165 — GET  /api/reports/income_statement (line ~69)  → accounting.view + reports.view
* F-NEW-166 — GET  /api/reports/trial_balance    (line ~88)  → accounting.view + reports.view
* F-NEW-167 — GET  /api/reports/balance_sheet    (line ~105) → accounting.view + reports.view
* F-NEW-169 — GET  /api/reports/period_stats     (line ~122) → accounting.view + reports.view

Plus the cross-cutting hardening that the audit's remediation_hint asks
for on the four read endpoints:

* F-NEW-168 — period_stats() must bind the tenant to current_user.company_id
              rather than trusting the ``tenant_id`` query string. The
              same hardening was applied to the other three GET endpoints
              for consistency (the audit's hint says "validate the tenant
              against the authenticated user's company_id").

Static-source assertions only — no DB fixture is needed; the audit-PR
family uses static-grep tests as the canonical regression bar.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_INIT = REPO_ROOT / "backend/routers/reports/__init__.py"


def _read() -> str:
    return REPORTS_INIT.read_text(encoding="utf-8")


def _slice(src: str, anchor: str, lines: int = 60) -> str:
    idx = src.find(anchor)
    assert idx >= 0, f"anchor not found: {anchor}"
    return "\n".join(src[idx:].splitlines()[:lines])


# ── module imports ─────────────────────────────────────────────────────────


def test_module_imports_required_symbols():
    """Batch 12 introduces Depends + the two permission helpers and fixes
    the http_error / get_current_user imports that were silently missing.
    """
    src = _read()
    assert re.search(r"^from fastapi import APIRouter, Depends\b", src, re.M)
    assert "from routers.auth import get_current_user" in src
    assert "from utils.i18n import http_error" in src
    assert "from utils.permissions import" in src
    assert "require_permission" in src
    assert "require_sensitive_permission" in src


# ── F-NEW-164: cache/refresh ───────────────────────────────────────────────


def test_cache_refresh_is_sensitive_gated():
    body = _slice(_read(), '"/cache/refresh"', lines=20)
    assert "require_sensitive_permission" in body, (
        "F-NEW-164: /cache/refresh is administrative; the audit asks for "
        "require_sensitive_permission(...) (or require_permission with the "
        "reports.refresh / admin.cache key)."
    )
    assert "reports.refresh" in body or "admin.cache" in body, (
        "F-NEW-164: must cite the reports.refresh or admin.cache key."
    )
    assert "critical=True" in body, (
        "F-NEW-164: cache-refresh is critical (drops + repopulates "
        "materialised views) — the dependency must mark critical=True."
    )


# ── F-NEW-165: /income_statement ───────────────────────────────────────────


def test_income_statement_has_permission_gate_and_tenant_binding():
    body = _slice(_read(), '"/income_statement"', lines=40)
    assert "require_permission" in body, (
        "F-NEW-165: /income_statement must add require_permission(...)"
    )
    assert "accounting.view" in body and "reports.view" in body, (
        "F-NEW-165: gate must accept either accounting.view or reports.view."
    )
    # Tenant binding hardening (audit hint).
    assert "current_user" in body and "company_id" in body, (
        "F-NEW-165: handler must bind the tenant to current_user.company_id."
    )


# ── F-NEW-166: /trial_balance ──────────────────────────────────────────────


def test_trial_balance_has_permission_gate_and_tenant_binding():
    body = _slice(_read(), '"/trial_balance"', lines=40)
    assert "require_permission" in body
    assert "accounting.view" in body and "reports.view" in body
    assert "current_user" in body and "company_id" in body, (
        "F-NEW-166: handler must bind the tenant to current_user.company_id."
    )


# ── F-NEW-167: /balance_sheet ──────────────────────────────────────────────


def test_balance_sheet_has_permission_gate_and_tenant_binding():
    body = _slice(_read(), '"/balance_sheet"', lines=40)
    assert "require_permission" in body
    assert "accounting.view" in body and "reports.view" in body
    assert "current_user" in body and "company_id" in body


# ── F-NEW-168 / F-NEW-169: /period_stats ───────────────────────────────────


def test_period_stats_has_permission_gate():
    body = _slice(_read(), '"/period_stats"', lines=50)
    assert "require_permission" in body, (
        "F-NEW-169: /period_stats must add require_permission(...)"
    )
    assert "accounting.view" in body and "reports.view" in body


def test_period_stats_binds_tenant_to_authenticated_user():
    """F-NEW-168 (R-TENANT-ISOLATION variant): period_stats opens a DB
    session but the handler used to take ``tenant_id`` straight from the
    query string. After Batch 12 the handler validates against
    ``current_user.company_id`` and falls back to it when omitted.
    """
    body = _slice(_read(), '"/period_stats"', lines=60)
    assert "current_user" in body and "company_id" in body, (
        "F-NEW-168: period_stats must bind to current_user.company_id."
    )
    assert "tenant_mismatch" in body, (
        "F-NEW-168: period_stats must reject tenant_id ≠ current_user.company_id."
    )
