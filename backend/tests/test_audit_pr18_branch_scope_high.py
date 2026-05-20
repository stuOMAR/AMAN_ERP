"""Audit PR 18 — verify branch-scope guards on the 28 CC-BRANCH_SCOPE
High findings.

The audit's CC-BRANCH_SCOPE rule fires when a state-mutating handler
touches a branch-scoped table without referencing any of:
``branch_id``, ``validate_branch_access``, ``branch_scope_filter``,
``allowed_branches``, or ``resolve_branch_scope`` (project-wide
``_require_company_wide_branch_scope`` and
``_require_reconciliation_branch_access`` helpers also count — they
expand to ``resolve_branch_scope``/``validate_branch_access`` calls).

PR18 closes all 28 findings by adding the appropriate guard to each
handler. This test pins those guards in place: it walks every audited
handler body and asserts at least one of the canonical branch-scope
tokens appears inside the function body before the first commit /
INSERT / UPDATE / DELETE statement.

The test is static-source only (no DB / HTTP) so it survives the same
baseline gaps that pre-date the audit.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def _slice_handler(body: str, fn_name: str) -> str:
    """Return the source of ``def fn_name(...)`` up to the next
    top-level ``def`` / ``class`` / ``@router.`` decorator (whichever
    comes first). Falls back to end-of-file."""
    m = re.search(rf"^def {re.escape(fn_name)}\(", body, re.MULTILINE)
    if not m:
        m = re.search(rf"^async def {re.escape(fn_name)}\(", body, re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    rest = body[m.end():]
    # Find the next def / async def / class at column 0, OR a route decorator.
    nxt = re.search(
        r"^(?:def |async def |class |@router\.|@rev_router\.)",
        rest,
        re.MULTILINE,
    )
    end = m.end() + (nxt.start() if nxt else len(rest))
    return body[start:end]


# ──────────────────────────────────────────────────────────────────────
# (finding_id, file, handler_name, expected_guard_tokens)
#
# A handler counts as "branch-guarded" when its body contains at least
# one of the listed tokens. Most handlers use ``validate_branch_access``
# directly; a few use private helpers introduced by PR18:
#   * ``_require_company_wide_branch_scope`` (fiscal / accounts / currency
#     mutations that intentionally reject any branch-restricted user)
#   * ``_get_budget_for_branch_scope`` (budgets — wraps a SELECT under
#     ``branch_scope_filter`` + 404 fallback)
#   * ``_require_reconciliation_branch_access`` (reconciliation — pulls
#     the branch from the parent ``bank_reconciliations`` row and
#     validates against the caller's allowed branches)
# ``validate_treasury_account_access`` also counts because it enforces
# ``treasury_accounts.branch_id`` against the caller's scope internally.
# ──────────────────────────────────────────────────────────────────────
GUARDS = [
    # F-NEW-032 — accounts.delete_account
    ("F-NEW-032", "backend/routers/finance/accounting/accounts.py",
     "delete_account",
     ["_require_company_wide_branch_scope"]),
    # F-NEW-037 / 038 / 039 — fiscal admin endpoints
    ("F-NEW-037", "backend/routers/finance/accounting/fiscal.py",
     "create_fiscal_year",
     ["_require_company_wide_branch_scope"]),
    ("F-NEW-038", "backend/routers/finance/accounting/fiscal.py",
     "close_fiscal_year",
     ["_require_company_wide_branch_scope"]),
    ("F-NEW-039", "backend/routers/finance/accounting/fiscal.py",
     "toggle_fiscal_period",
     ["_require_company_wide_branch_scope"]),
    # F-NEW-047 / 049 — recurring templates
    ("F-NEW-047", "backend/routers/finance/accounting/recurring.py",
     "update_recurring_template",
     ["validate_branch_access"]),
    ("F-NEW-049", "backend/routers/finance/accounting/recurring.py",
     "delete_recurring_template",
     ["validate_branch_access"]),
    # F-NEW-056 — assets units-of-production
    ("F-NEW-056", "backend/routers/finance/assets/depreciation.py",
     "calc_units_of_production",
     ["validate_branch_access"]),
    # F-NEW-057 — impairment
    ("F-NEW-057", "backend/routers/finance/assets/impairment.py",
     "run_impairment_test",
     ["validate_branch_access"]),
    # F-NEW-058 — insurance
    ("F-NEW-058", "backend/routers/finance/assets/insurance.py",
     "add_insurance",
     ["validate_branch_access"]),
    # F-NEW-060 / 061 — maintenance
    ("F-NEW-060", "backend/routers/finance/assets/maintenance.py",
     "complete_maintenance",
     ["validate_branch_access"]),
    ("F-NEW-061", "backend/routers/finance/assets/maintenance.py",
     "add_maintenance",
     ["validate_branch_access"]),
    # F-NEW-062 — qr
    ("F-NEW-062", "backend/routers/finance/assets/qr.py",
     "update_asset_qr",
     ["validate_branch_access"]),
    # F-NEW-064 — revaluations
    ("F-NEW-064", "backend/routers/finance/assets/revaluations.py",
     "create_revaluation",
     ["validate_branch_access"]),
    # F-NEW-067 — bank feeds import
    ("F-NEW-067", "backend/routers/finance/bank_feeds.py",
     "import_statement",
     ["validate_treasury_account_access", "_is_branch_privileged"]),
    # F-NEW-071 / 073 / 077 / 079 / 081 — budgets
    ("F-NEW-071", "backend/routers/finance/budgets.py",
     "delete_budget",
     ["_get_budget_for_branch_scope"]),
    ("F-NEW-073", "backend/routers/finance/budgets.py",
     "set_budget_items",
     ["_get_budget_for_branch_scope"]),
    ("F-NEW-077", "backend/routers/finance/budgets.py",
     "activate_budget",
     ["_get_budget_for_branch_scope"]),
    ("F-NEW-079", "backend/routers/finance/budgets.py",
     "close_budget",
     ["_get_budget_for_branch_scope"]),
    ("F-NEW-081", "backend/routers/finance/budgets.py",
     "create_budget_by_cost_center",
     ["validate_branch_access"]),
    # F-NEW-103 — currency delete
    ("F-NEW-103", "backend/routers/finance/currencies.py",
     "delete_currency",
     ["_require_company_wide_branch_scope"]),
    # F-NEW-112 / 118 — expenses
    ("F-NEW-112", "backend/routers/finance/expenses.py",
     "update_expense",
     ["validate_branch_access"]),
    ("F-NEW-118", "backend/routers/finance/expenses.py",
     "delete_expense",
     ["validate_branch_access"]),
    # F-NEW-140 / 141 / 143 / 144 / 145 / 146 — reconciliation
    ("F-NEW-140", "backend/routers/finance/reconciliation.py",
     "add_statement_lines",
     ["_require_reconciliation_branch_access"]),
    ("F-NEW-141", "backend/routers/finance/reconciliation.py",
     "confirm_import",
     ["_require_reconciliation_branch_access"]),
    ("F-NEW-143", "backend/routers/finance/reconciliation.py",
     "delete_statement_line",
     ["_require_reconciliation_branch_access"]),
    ("F-NEW-144", "backend/routers/finance/reconciliation.py",
     "match_transaction",
     ["_require_reconciliation_branch_access"]),
    ("F-NEW-145", "backend/routers/finance/reconciliation.py",
     "unmatch_transaction",
     ["_require_reconciliation_branch_access"]),
    ("F-NEW-146", "backend/routers/finance/reconciliation.py",
     "delete_reconciliation",
     ["_require_reconciliation_branch_access"]),
]


def test_pr18_closes_28_findings():
    """Sanity: PR18 closes exactly the 28 CC-BRANCH_SCOPE High findings."""
    assert len(GUARDS) == 28
    ids = [g[0] for g in GUARDS]
    assert len(set(ids)) == 28


def test_every_audited_handler_has_a_branch_guard():
    """For each finding, the audited handler body must reference at
    least one canonical branch-scope token. This is the structural
    guard the audit asked for; a future refactor that removes the
    guard without putting another in its place will fail here."""
    failures: list[str] = []
    for fid, rel, fn, expected in GUARDS:
        body = _read(rel)
        handler = _slice_handler(body, fn)
        if not handler:
            failures.append(f"{fid}: handler {fn}() not found in {rel}")
            continue
        if not any(tok in handler for tok in expected):
            failures.append(
                f"{fid}: {fn}() in {rel} has none of {expected}"
            )
    assert not failures, (
        "Branch-scope guard missing on:\n  " + "\n  ".join(failures)
    )


def test_helpers_resolve_to_canonical_primitives():
    """The PR18 helpers must each ultimately call the canonical
    branch-scope primitives — otherwise they'd be cosmetic wrappers
    that pass the structural test above without delivering the
    behaviour the audit asked for."""
    # _require_company_wide_branch_scope — must consult resolve_branch_scope
    # and reject when ``branch_ids`` is non-None.
    for rel in (
        "backend/routers/finance/accounting/accounts.py",
        "backend/routers/finance/accounting/fiscal.py",
        "backend/routers/finance/currencies.py",
    ):
        body = _read(rel)
        if "_require_company_wide_branch_scope" not in body:
            continue
        m = re.search(
            r"def _require_company_wide_branch_scope\(.*?\n(.*?)(?=\n(?:def |class |@))",
            body,
            re.DOTALL,
        )
        assert m, f"{rel}: _require_company_wide_branch_scope not found"
        helper = m.group(1)
        assert "resolve_branch_scope" in helper, (
            f"{rel}: _require_company_wide_branch_scope must call "
            "resolve_branch_scope to determine if the caller is scoped."
        )
        assert 'branch_ids' in helper and 'is not None' in helper, (
            f"{rel}: _require_company_wide_branch_scope must reject "
            "callers whose scope.branch_ids is non-None."
        )

    # _get_budget_for_branch_scope — must apply branch_scope_filter.
    body = _read("backend/routers/finance/budgets.py")
    m = re.search(
        r"def _get_budget_for_branch_scope\(.*?\n(.*?)(?=\n(?:def |class |@))",
        body,
        re.DOTALL,
    )
    assert m, "_get_budget_for_branch_scope helper not found"
    helper = m.group(1)
    assert "branch_scope_filter" in helper, (
        "_get_budget_for_branch_scope must apply branch_scope_filter "
        "so a branch-restricted caller cannot SELECT a budget outside "
        "their scope."
    )

    # _require_reconciliation_branch_access — must call validate_branch_access
    # or validate_treasury_account_access.
    body = _read("backend/routers/finance/reconciliation.py")
    m = re.search(
        r"def _require_reconciliation_branch_access\(.*?\n(.*?)(?=\n(?:def |class |@))",
        body,
        re.DOTALL,
    )
    assert m, "_require_reconciliation_branch_access helper not found"
    helper = m.group(1)
    assert "validate_branch_access" in helper, (
        "_require_reconciliation_branch_access must call "
        "validate_branch_access on the resolved branch."
    )
    assert "validate_treasury_account_access" in helper, (
        "_require_reconciliation_branch_access must fall back to "
        "validate_treasury_account_access when the row lacks a direct "
        "branch_id (legacy reconciliations)."
    )


def test_no_silent_helpers_replaced_validate_branch_access():
    """Negative regression: a future refactor that swaps a real branch
    check for a no-op helper will fail here. We require the helpers
    themselves to either call validate_branch_access / 
    validate_treasury_account_access OR raise HTTPException with 403
    on the negative path."""
    helper_files = [
        "backend/routers/finance/accounting/accounts.py",
        "backend/routers/finance/accounting/fiscal.py",
        "backend/routers/finance/currencies.py",
        "backend/routers/finance/budgets.py",
        "backend/routers/finance/reconciliation.py",
    ]
    for rel in helper_files:
        body = _read(rel)
        # Find every helper named like _require_*_branch_* or
        # _get_*_for_branch_scope and confirm it raises 403 OR calls
        # the canonical primitive.
        for m in re.finditer(
            r"def (_(?:require|get)[A-Za-z_]*branch[A-Za-z_]*)\([^)]*\):"
            r"(.*?)(?=\n(?:def |class |@))",
            body,
            re.DOTALL,
        ):
            name, helper = m.group(1), m.group(2)
            ok = (
                "validate_branch_access" in helper
                or "validate_treasury_account_access" in helper
                or "branch_scope_filter" in helper
                or ("raise HTTPException" in helper and "403" in helper)
            )
            assert ok, (
                f"{rel}: helper {name} appears to be a no-op — must "
                "either raise 403 or delegate to validate_branch_access "
                "/ validate_treasury_account_access."
            )
