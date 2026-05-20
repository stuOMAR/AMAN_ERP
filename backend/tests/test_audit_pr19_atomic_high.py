"""Audit PR 19 — verify atomic-transaction wrapping on the 21
CC-ATOMIC High findings (plus PR19-fix follow-ups).

Each handler must:
  1. open a single ``transactional(<tenant>)`` block (or equivalent);
  2. NOT contain explicit ``db.commit()`` / ``db.rollback()`` /
     ``_close(db)`` / ``db.close()`` inside the handler body;
  3. NOT re-open ``get_db_connection(...)`` inside the handler body.

PR19-fix findings (the post-review tightening):
  * F-NEW-052 (einvoice_submit) — adapter network call must run *outside*
    ``transactional(...)`` so the DB connection isn't held during the
    HTTPS round-trip; persistence happens in a follow-up short tx.
  * F-NEW-053 (einvoice_outbox_relay) — each outbox row must be wrapped
    in ``db.begin_nested()`` so a DB error on one row cannot roll back
    sibling rows whose ZATCA submission has already been accepted.
  * F-NEW-150 (scan_dunning) — same per-row savepoint pattern so the
    batch scanner is genuinely best-effort per-row.
  * Collateral: every caller of ``ensure_treasury_gl_accounts(...)`` that
    runs inside a ``transactional(...)`` block must pass ``commit=False``
    so the helper does not auto-commit mid-flight.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _read(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8", errors="ignore")


def _slice_handler(body: str, fn: str) -> str:
    m = re.search(rf"^(?:async\s+)?def {re.escape(fn)}\(", body, re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    rest = body[m.end():]
    nxt = re.search(r"^(?:async def |def |class |@router\.|@rev_router\.)", rest, re.MULTILINE)
    end = m.end() + (nxt.start() if nxt else len(rest))
    return body[start:end]


# ──────────────────────────────────────────────────────────────────────
# (finding_id, file, handler_name)
# ──────────────────────────────────────────────────────────────────────
HANDLERS = [
    ("F-NEW-051", "routers/finance/accounting_depth.py", "cgu_create"),
    ("F-NEW-052", "routers/finance/accounting_depth.py", "einvoice_submit"),
    ("F-NEW-053", "routers/finance/accounting_depth.py", "einvoice_outbox_relay"),
    ("F-NEW-066", "routers/finance/bank_feeds.py", "import_statement"),
    ("F-NEW-094", "routers/finance/cost_centers.py", "update_cost_center"),
    ("F-NEW-096", "routers/finance/costing_policies.py", "set_costing_policy"),
    ("F-NEW-099", "routers/finance/currencies.py", "create_currency"),
    ("F-NEW-101", "routers/finance/currencies.py", "update_currency"),
    ("F-NEW-105", "routers/finance/currencies.py", "add_exchange_rate"),
    ("F-NEW-108", "routers/finance/currencies.py", "create_revaluation"),
    ("F-NEW-115", "routers/finance/expenses.py", "reverse_expense"),
    ("F-NEW-134", "routers/finance/payments.py", "webhook"),
    ("F-NEW-137", "routers/finance/petty_cash.py", "replenish_fund"),
    ("F-NEW-138", "routers/finance/petty_cash.py", "disburse_fund"),
    ("F-NEW-150", "routers/finance/subscriptions.py", "scan_dunning"),
    ("F-NEW-152", "routers/finance/tax_compliance.py", "update_company_tax_settings"),
    ("F-NEW-153", "routers/finance/tax_compliance.py", "update_branch_tax_setting"),
    ("F-NEW-154", "routers/finance/treasury.py", "create_treasury_account"),
    ("F-NEW-156", "routers/finance/treasury.py", "update_treasury_account"),
    ("F-NEW-158", "routers/finance/treasury.py", "delete_treasury_account"),
    ("F-NEW-161", "routers/finance/treasury.py", "create_transfer"),
]


def test_pr19_closes_21_findings():
    assert len(HANDLERS) == 21


def test_every_handler_uses_transactional_and_no_manual_lifecycle():
    """Each handler body must contain at least one ``with transactional(``
    call AND must NOT contain explicit ``db.commit()`` / ``db.rollback()``
    / ``_close(db)`` / ``db.close()`` / ``db = get_db_connection(``."""
    fail: list[str] = []
    for fid, rel, fn in HANDLERS:
        body = _read(rel)
        h = _slice_handler(body, fn)
        if not h:
            fail.append(f"{fid}: handler {fn} not found in {rel}")
            continue
        if "with transactional(" not in h:
            fail.append(f"{fid}: {fn} missing `with transactional(...)`")
        for forbidden in (
            "db.commit()",
            "db.rollback()",
            "_close(db)",
            "db.close()",
        ):
            if forbidden in h:
                fail.append(f"{fid}: {fn} still contains {forbidden}")
        if re.search(r"\bdb\s*=\s*get_db_connection\(", h):
            fail.append(f"{fid}: {fn} still re-opens get_db_connection(...)")
    assert not fail, "Atomic-wrap regressions:\n  " + "\n  ".join(fail)


# ── PR19-fix tightenings ─────────────────────────────────────────────


def test_einvoice_submit_does_not_call_adapter_inside_transactional():
    """F-NEW-052 (PR19-fix): the ZATCA/ETA adapter.submit() call must
    NOT run while a tenant transaction is open. The fixed handler
    runs the network call *between* two ``transactional(...)`` blocks
    (one for the fiscal-lock check, one for persistence)."""
    body = _read("routers/finance/accounting_depth.py")
    h = _slice_handler(body, "einvoice_submit")
    assert h, "einvoice_submit handler not found"

    # Walk line-by-line, tracking whether we're currently inside a
    # ``with transactional(...)`` block by indentation. The block opens
    # at the ``with`` line at indent W; everything indented > W is
    # inside; the first non-blank line at indent ≤ W closes the block.
    inside = False
    block_indent = 0
    submit_inside = False
    submit_seen = False
    for line in h.splitlines():
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip())
        if inside and ind <= block_indent:
            inside = False
        stripped = line.strip()
        if stripped.startswith("with transactional("):
            inside = True
            block_indent = ind
            continue
        if "adapter.submit(payload)" in stripped:
            submit_seen = True
            if inside:
                submit_inside = True
                break
    assert submit_seen, "F-NEW-052: adapter.submit(payload) call site not found"
    assert not submit_inside, (
        "F-NEW-052 (PR19-fix): adapter.submit(payload) is still inside a "
        "`with transactional(...)` block; move the network call outside."
    )


def test_einvoice_outbox_relay_uses_per_row_savepoint():
    """F-NEW-053 (PR19-fix): each outbox row must be wrapped in
    ``db.begin_nested()`` so a DB error on one row cannot roll back
    siblings whose ZATCA submission already succeeded."""
    body = _read("routers/finance/accounting_depth.py")
    h = _slice_handler(body, "einvoice_outbox_relay")
    assert h, "einvoice_outbox_relay handler not found"
    # We expect at least two `with db.begin_nested()` blocks (one for
    # the network-failure path, one for the success-persist path).
    nested = h.count("db.begin_nested()")
    assert nested >= 2, (
        f"F-NEW-053 (PR19-fix): outbox-relay must wrap each row's DB "
        f"writes in db.begin_nested(); found {nested} occurrences "
        "(expected ≥ 2 — one for failure, one for success)."
    )


def test_scan_dunning_uses_per_row_savepoint():
    """F-NEW-150 (PR19-fix): the dunning scanner is a best-effort
    batch — a failure on one subscription must not roll back siblings."""
    body = _read("routers/finance/subscriptions.py")
    h = _slice_handler(body, "scan_dunning")
    assert h, "scan_dunning handler not found"
    assert "db.begin_nested()" in h, (
        "F-NEW-150 (PR19-fix): scan_dunning must wrap each row in "
        "db.begin_nested() so a per-row failure does not roll back "
        "the rest of the batch."
    )


def test_ensure_treasury_gl_accounts_callers_pass_commit_false():
    """PR19-fix collateral: every caller of
    ``ensure_treasury_gl_accounts(...)`` that runs inside a
    ``transactional(...)`` block must pass ``commit=False`` so the
    helper does not auto-commit mid-flight, which would land the
    skeleton GL accounts even if the surrounding work fails."""
    fail: list[str] = []
    for rel in (
        "routers/finance/notes.py",
        "routers/finance/checks.py",
        "routers/finance/treasury.py",
    ):
        body = _read(rel)
        for m in re.finditer(
            r"ensure_treasury_gl_accounts\(([^)]*)\)",
            body,
            re.DOTALL,
        ):
            args = m.group(1)
            # If the file uses `with transactional(` at all, every call
            # site must pass commit=False.
            if "with transactional(" not in body:
                continue
            if "commit=False" not in args:
                line_no = body[: m.start()].count("\n") + 1
                fail.append(
                    f"{rel}:{line_no} ensure_treasury_gl_accounts(...) "
                    "missing commit=False inside a transactional() file"
                )
    assert not fail, "ensure_treasury_gl_accounts auto-commit risks:\n  " + "\n  ".join(fail)
