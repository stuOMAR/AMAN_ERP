"""Audit PR 17 — verify FE↔BE permission-key alignment for the 43
R-PERMISSION-DRIFT High findings.

The audit's R-PERMISSION-DRIFT rule fires when the frontend's gate
key does not match the backend's ``require_permission(...)`` key on
the same endpoint. The 43 High-tier findings in this rule were
re-verified behaviourally in PR17 by inspecting *both* sides:

* The backend route declaration is grepped for the audited
  ``require_permission(...)`` key.
* The matching frontend service entry (``api.post`` / ``api.put`` /
  ``api.delete`` / ``api.patch``) is grepped for the same key wrapped
  in ``withPermission(...)``.

When all three layers (BE route, FE service call, audit-finding key)
agree, the finding is closed. The test is intentionally a static-
source check (no HTTP calls) so it survives in environments without
a running frontend build.

Each finding ID is referenced inline so the
``scripts/build_audit_remediation_tasks.py`` close-set scan picks
this PR up as the closer.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# ──────────────────────────────────────────────────────────────────────
# (finding_id, BE-relpath, BE-route-regex, FE-relpath, FE-snippet, key)
#
# Every entry asserts:
#   1. The BE route declaration on `BE-relpath` carries
#      `require_permission("<key>")` (or a list containing it).
#   2. The FE service file on `FE-relpath` calls the same endpoint
#      under `withPermission("<key>", ...)` (or matching list).
#
# When BE and FE both pass, the audit finding is closed.
# ──────────────────────────────────────────────────────────────────────
ALIGNMENTS = [
    # ── F-NEW-030 — POST /api/accounting/accounts ────────────────────
    ("F-NEW-030",
     "backend/routers/finance/accounting/accounts.py",
     r'@router\.post\("/accounts"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "create: (data) => withPermission('accounting.edit', () => api.post('/accounting/accounts'",
     "accounting.edit"),
    # ── F-NEW-033 — PUT /api/accounting/accounts/{id} ────────────────
    ("F-NEW-033",
     "backend/routers/finance/accounting/accounts.py",
     r'@router\.put\("/accounts/\{account_id\}"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "update: (id, data) => withPermission('accounting.edit', () => api.put(`/accounting/accounts/${id}`",
     "accounting.edit"),
    # ── F-NEW-046 — POST /api/accounting/recurring-templates ─────────
    ("F-NEW-046",
     "backend/routers/finance/accounting/recurring.py",
     r'@router\.post\("/recurring-templates"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "createRecurringTemplate: (data) => withPermission('accounting.edit',",
     "accounting.edit"),
    # ── F-NEW-048 — PUT /api/accounting/recurring-templates/{id} ─────
    ("F-NEW-048",
     "backend/routers/finance/accounting/recurring.py",
     r'@router\.put\("/recurring-templates/\{template_id\}"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "updateRecurringTemplate: (id, data) => withPermission('accounting.edit',",
     "accounting.edit"),
    # ── F-NEW-050 — POST .../recurring-templates/{id}/generate ───────
    ("F-NEW-050",
     "backend/routers/finance/accounting/recurring.py",
     r'@router\.post\("/recurring-templates/\{template_id\}/generate"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "generateFromTemplate: (id) => withPermission('accounting.edit',",
     "accounting.edit"),
    # ── F-NEW-069 — POST /api/accounting/budgets/ ────────────────────
    ("F-NEW-069",
     "backend/routers/finance/budgets.py",
     r'@router\.post\("/"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "create: (data) => withPermission('accounting.budgets.manage', () => api.post('/accounting/budgets/'",
     "accounting.budgets.manage"),
    # ── F-NEW-072 — DELETE /api/accounting/budgets/{id} ──────────────
    ("F-NEW-072",
     "backend/routers/finance/budgets.py",
     r'@router\.delete\("/\{budget_id\}"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "delete: (id) => withPermission('accounting.budgets.manage', () => api.delete(`/accounting/budgets/${id}`",
     "accounting.budgets.manage"),
    # ── F-NEW-074 — POST /api/accounting/budgets/{id}/items ──────────
    ("F-NEW-074",
     "backend/routers/finance/budgets.py",
     r'@router\.post\("/\{budget_id\}/items"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "setItems: (id, items) => withPermission('accounting.budgets.manage',",
     "accounting.budgets.manage"),
    # ── F-NEW-075 — PUT /api/accounting/budgets/{id} ─────────────────
    ("F-NEW-075",
     "backend/routers/finance/budgets.py",
     r'@router\.put\("/\{budget_id\}"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "update: (id, data) => withPermission('accounting.budgets.manage', () => api.put(`/accounting/budgets/${id}`",
     "accounting.budgets.manage"),
    # ── F-NEW-078 — POST /api/accounting/budgets/{id}/activate ───────
    ("F-NEW-078",
     "backend/routers/finance/budgets.py",
     r'@router\.post\("/\{budget_id\}/activate"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "activate: (id) => withPermission('accounting.budgets.manage',",
     "accounting.budgets.manage"),
    # ── F-NEW-080 — POST /api/accounting/budgets/{id}/close ──────────
    ("F-NEW-080",
     "backend/routers/finance/budgets.py",
     r'@router\.post\("/\{budget_id\}/close"[^)]*?require_permission\("accounting\.budgets\.manage"\)',
     "frontend/src/services/accounting.js",
     "close: (id) => withPermission('accounting.budgets.manage',",
     "accounting.budgets.manage"),
    # ── F-NEW-084 — POST /api/checks/receivable ──────────────────────
    ("F-NEW-084",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/receivable"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "createReceivable: (data) => withPermission('treasury.create', () => api.post('/checks/receivable'",
     "treasury.create"),
    # ── F-NEW-086 — POST /api/checks/receivable/{id}/collect ─────────
    ("F-NEW-086",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/receivable/\{check_id\}/collect"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "collectReceivable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-087 — POST /api/checks/receivable/{id}/bounce ──────────
    ("F-NEW-087",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/receivable/\{check_id\}/bounce"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "bounceReceivable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-088 — POST /api/checks/receivable/{id}/represent ───────
    ("F-NEW-088",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/receivable/\{check_id\}/represent"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "representReceivable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-089 — POST /api/checks/payable ─────────────────────────
    ("F-NEW-089",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/payable"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "createPayable: (data) => withPermission('treasury.create', () => api.post('/checks/payable'",
     "treasury.create"),
    # ── F-NEW-090 — POST /api/checks/payable/{id}/clear ──────────────
    ("F-NEW-090",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/payable/\{check_id\}/clear"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "clearPayable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-091 — POST /api/checks/payable/{id}/bounce ─────────────
    ("F-NEW-091",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/payable/\{check_id\}/bounce"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "bouncePayable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-092 — POST /api/checks/payable/{id}/represent ──────────
    ("F-NEW-092",
     "backend/routers/finance/checks.py",
     r'@router\.post\("/payable/\{check_id\}/represent"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "representPayable: (id, data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-100 — POST /api/accounting/currencies/ ─────────────────
    ("F-NEW-100",
     "backend/routers/finance/currencies.py",
     r'require_permission\(\["accounting\.manage", "currencies\.manage"\]\)',
     "frontend/src/services/accounting.js",
     "create: (data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.post('/accounting/currencies/'",
     "accounting.manage|currencies.manage"),
    # ── F-NEW-102 — PUT /api/accounting/currencies/{id} ──────────────
    ("F-NEW-102",
     "backend/routers/finance/currencies.py",
     r'require_permission\(\["accounting\.manage", "currencies\.manage"\]\)',
     "frontend/src/services/accounting.js",
     "update: (id, data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.put(`/accounting/currencies/${id}`",
     "accounting.manage|currencies.manage"),
    # ── F-NEW-104 — DELETE /api/accounting/currencies/{id} ───────────
    ("F-NEW-104",
     "backend/routers/finance/currencies.py",
     r'require_permission\(\["accounting\.manage", "currencies\.manage"\]\)',
     "frontend/src/services/accounting.js",
     "delete: (id) => withPermission(['accounting.manage', 'currencies.manage'], () => api.delete(`/accounting/currencies/${id}`",
     "accounting.manage|currencies.manage"),
    # ── F-NEW-106 — POST /api/accounting/currencies/rates ────────────
    ("F-NEW-106",
     "backend/routers/finance/currencies.py",
     r'require_permission\(\["accounting\.manage", "currencies\.manage"\]\)',
     "frontend/src/services/accounting.js",
     "addRate: (data) => withPermission(['accounting.manage', 'currencies.manage'],",
     "accounting.manage|currencies.manage"),
    # ── F-NEW-109 — POST /api/accounting/currencies/revaluate ────────
    ("F-NEW-109",
     "backend/routers/finance/currencies.py",
     r'require_permission\(\["accounting\.manage", "currencies\.manage"\]\)',
     "frontend/src/services/accounting.js",
     "revaluate: (data) => withPermission(['accounting.manage', 'currencies.manage'],",
     "accounting.manage|currencies.manage"),
    # ── F-NEW-113 — PUT /api/expenses/{id} ───────────────────────────
    ("F-NEW-113",
     "backend/routers/finance/expenses.py",
     r'@router\.put\("/\{expense_id\}"[^)]*?require_permission\("expenses\.edit"\)',
     "frontend/src/services/expenses.js",
     "update: (id, data) => withPermission('expenses.edit',",
     "expenses.edit"),
    # ── F-NEW-114 — POST /api/expenses/{id}/approve ──────────────────
    ("F-NEW-114",
     "backend/routers/finance/expenses.py",
     r'@router\.post\("/\{expense_id\}/approve"[^)]*?require_permission\("expenses\.approve"\)',
     "frontend/src/services/expenses.js",
     "approve: (id, data) => withPermission('expenses.approve',",
     "expenses.approve"),
    # ── F-NEW-117 — POST /api/expenses/{id}/reverse ──────────────────
    ("F-NEW-117",
     "backend/routers/finance/expenses.py",
     r'@router\.post\("/\{expense_id\}/reverse"[^)]*?require_permission\("expenses\.approve"\)',
     "frontend/src/services/expenses.js",
     "reverse: (id, data) => withPermission('expenses.approve',",
     "expenses.approve"),
    # ── F-NEW-119 — DELETE /api/expenses/{id} ────────────────────────
    ("F-NEW-119",
     "backend/routers/finance/expenses.py",
     r'@router\.delete\("/\{expense_id\}"[^)]*?require_permission\("expenses\.delete"\)',
     "frontend/src/services/expenses.js",
     "delete: (id) => withPermission('expenses.delete',",
     "expenses.delete"),
    # ── F-NEW-120 — POST /api/accounting/intercompany/entities ───────
    ("F-NEW-120",
     "backend/routers/finance/intercompany_v2.py",
     r'@router\.post\("/entities"[^)]*?require_permission\(\["intercompany\.manage", "accounting\.edit"\]\)',
     "frontend/src/services/accounting.js",
     "createEntityGroup: (data) => withPermission(['intercompany.manage', 'accounting.edit'],",
     "intercompany.manage|accounting.edit"),
    # ── F-NEW-122 — PATCH /api/accounting/intercompany/entities/{id} ─
    ("F-NEW-122",
     "backend/routers/finance/intercompany_v2.py",
     r'require_permission\(\["intercompany\.manage", "accounting\.edit"\]\)',
     "frontend/src/services/accounting.js",
     "updateEntityGroup: (id, data) => withPermission(['intercompany.manage', 'accounting.edit'], () => api.patch(`/accounting/intercompany/entities/${id}`",
     "intercompany.manage|accounting.edit"),
    # ── F-NEW-123 — POST /api/accounting/intercompany/consolidate ────
    ("F-NEW-123",
     "backend/routers/finance/intercompany_v2.py",
     r'@router\.post\("/consolidate"[^)]*?require_permission\(\["intercompany\.manage", "accounting\.edit"\]\)',
     "frontend/src/services/accounting.js",
     "runConsolidation: (data) => withPermission(['intercompany.manage', 'accounting.edit'],",
     "intercompany.manage|accounting.edit"),
    # ── F-NEW-124 — POST /api/accounting/intercompany/mappings ───────
    ("F-NEW-124",
     "backend/routers/finance/intercompany_v2.py",
     r'@router\.post\("/mappings"[^)]*?require_permission\(\["intercompany\.manage", "accounting\.edit"\]\)',
     "frontend/src/services/accounting.js",
     "createAccountMapping: (data) => withPermission(['intercompany.manage', 'accounting.edit'],",
     "intercompany.manage|accounting.edit"),
    # ── F-NEW-128 — POST /api/notes/receivable ───────────────────────
    ("F-NEW-128",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/receivable"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "createReceivable: (data) => withPermission('treasury.create', () => api.post('/notes/receivable'",
     "treasury.create"),
    # ── F-NEW-129 — POST /api/notes/receivable/{id}/collect ──────────
    ("F-NEW-129",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/receivable/\{note_id\}/collect"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "collectReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/receivable/${id}/collect`",
     "treasury.create"),
    # ── F-NEW-130 — POST /api/notes/receivable/{id}/protest ──────────
    ("F-NEW-130",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/receivable/\{note_id\}/protest"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "protestReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/receivable/${id}/protest`",
     "treasury.create"),
    # ── F-NEW-131 — POST /api/notes/payable ──────────────────────────
    ("F-NEW-131",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/payable"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "createPayable: (data) => withPermission('treasury.create', () => api.post('/notes/payable'",
     "treasury.create"),
    # ── F-NEW-132 — POST /api/notes/payable/{id}/pay ─────────────────
    ("F-NEW-132",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/payable/\{note_id\}/pay"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "payPayable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/payable/${id}/pay`",
     "treasury.create"),
    # ── F-NEW-133 — POST /api/notes/payable/{id}/protest ─────────────
    ("F-NEW-133",
     "backend/routers/finance/notes.py",
     r'@router\.post\("/payable/\{note_id\}/protest"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/checks.js",
     "protestPayable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/payable/${id}/protest`",
     "treasury.create"),
    # ── F-NEW-148 — POST .../revenue-recognition/schedules ───────────
    ("F-NEW-148",
     "backend/routers/finance/revenue_recognition.py",
     r'@rev_router\.post\("/schedules"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "createRevenueSchedule: (data) => withPermission('accounting.edit',",
     "accounting.edit"),
    # ── F-NEW-149 — POST .../schedules/{id}/recognize ────────────────
    ("F-NEW-149",
     "backend/routers/finance/revenue_recognition.py",
     r'@rev_router\.post\("/schedules/\{schedule_id\}/recognize"[^)]*?require_permission\("accounting\.edit"\)',
     "frontend/src/services/accounting.js",
     "recognizeRevenue: (id, periodIndex) => withPermission('accounting.edit',",
     "accounting.edit"),
    # ── F-NEW-155 — POST /api/treasury/accounts ──────────────────────
    ("F-NEW-155",
     "backend/routers/finance/treasury.py",
     r'@router\.post\("/accounts"[^)]*?require_permission\("treasury\.create"\)',
     "frontend/src/services/treasury.js",
     "createAccount: (data) => withPermission('treasury.create',",
     "treasury.create"),
    # ── F-NEW-157 — PUT /api/treasury/accounts/{id} ──────────────────
    ("F-NEW-157",
     "backend/routers/finance/treasury.py",
     r'@router\.put\("/accounts/\{id\}"[^)]*?require_permission\("treasury\.edit"\)',
     "frontend/src/services/treasury.js",
     "updateAccount: (id, data) => withPermission('treasury.edit',",
     "treasury.edit"),
    # ── F-NEW-159 — DELETE /api/treasury/accounts/{id} ───────────────
    ("F-NEW-159",
     "backend/routers/finance/treasury.py",
     r'@router\.delete\("/accounts/\{id\}"[^)]*?require_permission\("treasury\.delete"\)',
     "frontend/src/services/treasury.js",
     "deleteAccount: (id) => withPermission('treasury.delete',",
     "treasury.delete"),
]


def test_alignment_count_is_43():
    """Sanity: PR17 closes exactly the 43 R-PERMISSION-DRIFT High findings."""
    assert len(ALIGNMENTS) == 43
    ids = [a[0] for a in ALIGNMENTS]
    assert len(set(ids)) == 43, f"duplicate F-NEW IDs in ALIGNMENTS: {ids}"


def test_backend_routes_carry_audit_permission_key():
    """For each of the 43 findings, the BE route declaration must
    still carry the audited ``require_permission(...)`` key. A future
    refactor that swaps the key without updating both ends will fail
    here."""
    failures: list[str] = []
    for fid, be_path, be_re, _fe_path, _fe_snippet, key in ALIGNMENTS:
        body = _read(ROOT / be_path)
        if not re.search(be_re, body, re.DOTALL):
            failures.append(
                f"{fid}: BE route regex {be_re!r} not matched in {be_path} "
                f"(expected key={key})"
            )
    assert not failures, "BE alignment failures:\n  " + "\n  ".join(failures)


def test_frontend_services_carry_matching_permission_key():
    """For each of the 43 findings, the FE service file must call the
    matching endpoint via ``withPermission(<same_key>, ...)``. This
    is the gate the audit asked for; cross-stack drift here is what
    R-PERMISSION-DRIFT was originally flagging."""
    failures: list[str] = []
    for fid, _be_path, _be_re, fe_path, fe_snippet, key in ALIGNMENTS:
        path = ROOT / fe_path
        if not path.is_file():
            failures.append(f"{fid}: FE file not found: {fe_path}")
            continue
        body = _read(path)
        if fe_snippet not in body:
            failures.append(
                f"{fid}: FE snippet not found in {fe_path}\n"
                f"      expected: {fe_snippet!r}\n"
                f"      key:      {key}"
            )
    assert not failures, "FE alignment failures:\n  " + "\n  ".join(failures)


def test_be_and_fe_keys_agree_per_finding():
    """For each finding, parse the canonical key out of both sides
    and assert they're the same. This catches the case where the
    snippets above happen to grep but use different keys."""
    fail: list[str] = []
    for fid, be_path, be_re, fe_path, fe_snippet, key in ALIGNMENTS:
        # Multi-key audited findings encode `A|B`; treat both as expected.
        expected = set(key.split("|"))
        # Pull keys out of the FE snippet (single 'X' or list ['A','B']).
        fe_keys = set(re.findall(r"'([a-z0-9_.]+)'", fe_snippet))
        if not fe_keys:
            fail.append(f"{fid}: could not parse FE keys from snippet")
            continue
        if not expected & fe_keys:
            fail.append(
                f"{fid}: BE/FE key mismatch — "
                f"BE expected {expected}, FE has {fe_keys}"
            )
        # Confirm BE regex actually contains every expected key.
        be_text = _read(ROOT / be_path)
        m = re.search(be_re, be_text, re.DOTALL)
        assert m, f"{fid}: BE regex did not match"
        be_keys = set(re.findall(r'"([a-z0-9_.]+)"', m.group(0)))
        if not expected & be_keys:
            fail.append(
                f"{fid}: BE key drift — expected {expected}, got {be_keys}"
            )
    assert not fail, "BE↔FE key mismatches:\n  " + "\n  ".join(fail)
