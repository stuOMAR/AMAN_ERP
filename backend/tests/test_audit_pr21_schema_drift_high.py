"""Audit PR 21 — verify the 16 R-SCHEMA-DRIFT High findings are closed.

The audit's R-SCHEMA-DRIFT rule fires when the frontend payload sent
to a route does not match the backend's Pydantic schema:

  * ``fe_missing_required`` — the FE payload omits a field the schema
    declares as required.
  * ``fe_extra_field``      — the FE payload includes a field the
    schema does not accept (Pydantic v2 with ``model_config =
    {"extra": "ignore"}`` silently drops it, but it still signals
    drift between FE intent and BE contract).

PR21 closes all 16 by editing the FE payloads (or interposing a
service-layer ``withoutCurrentRate(...)`` stripper). This test
asserts the FE-side state matches what the BE schema actually
declares.

The test is static-source only (greps over ``frontend/src``); no
HTTP / DB fixtures.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


# ──────────────────────────────────────────────────────────────────────
# Per-finding alignment.
#
# (finding_id, fe_path, must_contain, must_not_contain, schema_path,
#  schema_class, required_fields)
#
# ``must_contain``  : substring(s) that MUST appear in the FE file.
# ``must_not_contain``: substring(s) that MUST be absent.
# The schema check pulls the class block out of the BE schema file and
# asserts the listed fields are present (pinned in case the BE
# contract is later relaxed).
# ──────────────────────────────────────────────────────────────────────
ALIGNMENTS = [
    # ── F-NEW-028 — POST /api/external/api-keys ──────────────────────
    ("F-NEW-028",
     "frontend/src/pages/Settings/ApiKeys.jsx",
     ["name: form.name.trim()"],
     [],
     "backend/routers/external.py",
     "APIKeyCreate",
     ["name"]),
    # ── F-NEW-029 — POST /api/external/wht/rates ─────────────────────
    ("F-NEW-029",
     "frontend/src/pages/Taxes/WithholdingTax.jsx",
     ["name: rateForm.name.trim()"],
     [],
     "backend/routers/external.py",
     "WHTRateCreate",
     ["name"]),
    # ── F-NEW-031 / F-NEW-034 — accounts.create / update strip rate ──
    ("F-NEW-031",
     "frontend/src/services/accounting.js",
     ["create: (data) => withPermission('accounting.edit', () => api.post('/accounting/accounts', withoutCurrentRate(data))"],
     [],
     "backend/schemas/accounting.py",
     "AccountCreate",
     ["name"]),
    ("F-NEW-034",
     "frontend/src/services/accounting.js",
     ["update: (id, data) => withPermission('accounting.edit', () => api.put(`/accounting/accounts/${id}`, withoutCurrentRate(data))"],
     [],
     "backend/schemas/accounting.py",
     "AccountUpdate",
     []),
    # ── F-NEW-040 — POST /api/accounting/fx-revaluation ──────────────
    ("F-NEW-040",
     "frontend/src/pages/Settings/tabs/AccountingMappingSettings.jsx",
     ["currency_code: fxCurrencyCode", "new_rate: String(fxNewRate)"],
     [],
     "backend/routers/finance/accounting/core.py",
     "FXRevaluationRequest",
     ["currency_code", "new_rate"]),
    # ── F-NEW-045 — POST /api/accounting/provisions/bad-debt ─────────
    ("F-NEW-045",
     "frontend/src/pages/Settings/tabs/AccountingMappingSettings.jsx",
     ["createBadDebtProvision({ amount: String(badDebtAmount) })"],
     ["overdue_days", "badDebtDays"],
     "backend/routers/finance/accounting/core.py",
     "ProvisionRequest",
     ["amount"]),
    # ── F-NEW-070 / F-NEW-076 — budgets create / update strip rate ───
    ("F-NEW-070",
     "frontend/src/services/accounting.js",
     ["create: (data) => withPermission('accounting.budgets.manage', () => api.post('/accounting/budgets/', withoutCurrentRate(data))"],
     [],
     "backend/schemas/budgets.py",
     "BudgetCreate",
     []),
    ("F-NEW-076",
     "frontend/src/services/accounting.js",
     ["update: (id, data) => withPermission('accounting.budgets.manage', () => api.put(`/accounting/budgets/${id}`, withoutCurrentRate(data))"],
     [],
     "backend/schemas/budgets.py",
     "BudgetCreate",
     []),
    # ── F-NEW-082 — POST /api/finance/cashflow/generate ──────────────
    ("F-NEW-082",
     "frontend/src/pages/CashFlow/ForecastGenerate.jsx",
     ["name: formData.name.trim()"],
     [],
     "backend/schemas/cashflow.py",
     "ForecastGenerateRequest",
     ["name"]),
    # ── F-NEW-093 / F-NEW-095 — cost-centers create / update ─────────
    ("F-NEW-093",
     "frontend/src/services/accounting.js",
     ["create: (data) => api.post('/cost-centers/', withoutCurrentRate(data))"],
     [],
     None, None, []),
    ("F-NEW-095",
     "frontend/src/services/accounting.js",
     ["update: (id, data) => api.put(`/cost-centers/${id}`, withoutCurrentRate(data))"],
     [],
     None, None, []),
    # ── F-NEW-107 — POST /api/accounting/currencies/rates ────────────
    ("F-NEW-107",
     "frontend/src/pages/Accounting/CurrencyList.jsx",
     ["rate: Number(rateData.rate)"],
     [],
     "backend/schemas/__init__.py",
     "ExchangeRateCreate",
     ["currency_id", "rate"]),
    # ── F-NEW-111 — POST /api/expenses/ ──────────────────────────────
    ("F-NEW-111",
     "frontend/src/pages/Expenses/ExpenseForm.jsx",
     ["expense_date: formData.expense_date"],
     [],
     "backend/schemas/expenses.py",
     "ExpenseCreate",
     ["expense_date", "expense_type", "amount"]),
    # ── F-NEW-121 — POST /api/accounting/intercompany/entities ───────
    ("F-NEW-121",
     "frontend/src/pages/Intercompany/EntityGroupTree.jsx",
     ["name: form.name.trim()"],
     [],
     "backend/schemas/intercompany.py",
     "EntityGroupCreate",
     ["name"]),
    # ── F-NEW-160 — POST /api/treasury/transactions/expense ──────────
    ("F-NEW-160",
     "frontend/src/pages/Treasury/ExpenseForm.jsx",
     ["transaction_date: form.transaction_date"],
     [],
     "backend/schemas/treasury.py",
     "TransactionCreate",
     ["transaction_date", "transaction_type"]),
    # ── F-NEW-163 — POST /api/treasury/transactions/transfer ─────────
    ("F-NEW-163",
     "frontend/src/pages/Treasury/TransferForm.jsx",
     ["transaction_date: form.transaction_date"],
     [],
     "backend/schemas/treasury.py",
     "TransactionCreate",
     ["transaction_date", "transaction_type"]),
]


def test_pr21_closes_16_findings():
    """Sanity: PR21 closes exactly the 16 R-SCHEMA-DRIFT High findings."""
    assert len(ALIGNMENTS) == 16
    ids = [a[0] for a in ALIGNMENTS]
    assert len(set(ids)) == 16


def test_frontend_payloads_match_backend_schema():
    """For each finding, the FE file must contain the expected payload
    pattern (and not the audited-out fields)."""
    fail: list[str] = []
    for fid, fe_rel, must_contain, must_not_contain, _bs, _bc, _br in ALIGNMENTS:
        fe_path = ROOT / fe_rel
        if not fe_path.is_file():
            fail.append(f"{fid}: FE file not found: {fe_rel}")
            continue
        body = _read(fe_rel)
        for snippet in must_contain:
            if snippet not in body:
                fail.append(
                    f"{fid}: expected snippet missing from {fe_rel}\n"
                    f"      expected: {snippet!r}"
                )
        for snippet in must_not_contain:
            if snippet in body:
                fail.append(
                    f"{fid}: forbidden snippet present in {fe_rel}\n"
                    f"      forbidden: {snippet!r}"
                )
    assert not fail, "FE payload alignment failures:\n  " + "\n  ".join(fail)


def test_backend_schemas_still_declare_audited_required_fields():
    """Pin the BE-side contract: the audited required fields must
    still be present on the schema. A future relaxation that drops
    the field on the BE would silently re-open the drift.
    """
    fail: list[str] = []
    for fid, _fe, _mc, _mn, schema_rel, schema_class, required_fields in ALIGNMENTS:
        if not schema_rel or not schema_class:
            continue
        body = _read(schema_rel)
        m = re.search(
            rf"class\s+{re.escape(schema_class)}\s*\([^)]*\):(.*?)(?=^class |\Z)",
            body,
            re.DOTALL | re.MULTILINE,
        )
        if not m:
            fail.append(f"{fid}: schema {schema_class} not found in {schema_rel}")
            continue
        cls_body = m.group(1)
        for field in required_fields:
            # Field must be declared as `<field>:` somewhere in the class body.
            if not re.search(rf"^\s+{re.escape(field)}\s*:", cls_body, re.MULTILINE):
                fail.append(
                    f"{fid}: schema {schema_class} no longer declares {field!r} "
                    f"in {schema_rel}"
                )
    assert not fail, "BE schema regressions:\n  " + "\n  ".join(fail)


def test_account_strip_helper_exists():
    """``withoutCurrentRate(...)`` is the FE-side stripper that closes
    F-NEW-031 / 034 / 070 / 076 / 093 / 095. Without it, FE payloads
    would re-introduce ``current_rate`` whenever a form spread the
    full record into the create/update body."""
    body = _read("frontend/src/services/accounting.js")
    assert "const withoutCurrentRate = (data) =>" in body, (
        "PR21: services/accounting.js must define withoutCurrentRate(...) "
        "to drop current_rate from FE payloads."
    )
    assert "delete payload.current_rate" in body, (
        "PR21: withoutCurrentRate(...) must actually delete the field."
    )
    # Every audited callsite must wrap the body through it.
    expected_callsites = (
        "post('/accounting/accounts', withoutCurrentRate(data))",
        "put(`/accounting/accounts/${id}`, withoutCurrentRate(data))",
        "post('/accounting/budgets/', withoutCurrentRate(data))",
        "put(`/accounting/budgets/${id}`, withoutCurrentRate(data))",
        "post('/cost-centers/', withoutCurrentRate(data))",
        "put(`/cost-centers/${id}`, withoutCurrentRate(data))",
    )
    missing = [c for c in expected_callsites if c not in body]
    assert not missing, (
        "PR21: the following audited create/update sites do not pass "
        "the body through withoutCurrentRate(...):\n  " + "\n  ".join(missing)
    )
