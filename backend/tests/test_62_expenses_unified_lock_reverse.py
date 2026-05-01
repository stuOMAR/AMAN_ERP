"""T3.11 / T3.12 / T3.13 — unified expenses path, approval lock, reversal.

Three audit items pinned by this file:

* **T3.11** — there must be exactly one path that creates the
  ``journal_entries`` row for an expense, and that row must always
  exist (as ``draft`` for unapproved expenses, transitioning to
  ``posted`` on approval). The duplicate ``POST /treasury/transactions/expense``
  endpoint must delegate to the unified flow rather than carry its
  own JE-creation logic.

* **T3.12** — the approval handler must take a row-level lock on the
  expense before doing any work, otherwise two concurrent approvers
  could each post a JE.

* **T3.13** — there must be a ``POST /expenses/{id}/reverse`` endpoint
  that creates a reversing JE via ``services.gl_service.reverse_journal_entry``
  and flips the expense to ``approval_status='reversed'``. Net effect
  on AP/Cash must be zero (reversing entry swaps debit/credit of every
  line of the original).

The math contract for the reversal — that mirroring debit/credit on
the same accounts produces a net zero impact — is also verified
directly against ``reverse_journal_entry`` so the linchpin is proven
once at the SQL/account-balance level instead of being implied by an
HTTP round-trip.
"""

from __future__ import annotations

import os
import re
import sys
from decimal import Decimal

import psycopg2
import psycopg2.extras
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-t3-11")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

EXP_PATH = os.path.join(ROOT, "routers", "finance", "expenses.py")
TR_PATH = os.path.join(ROOT, "routers", "finance", "treasury.py")
GL_PATH = os.path.join(ROOT, "services", "gl_service.py")


# ──────────────────────────────────────────────────────────────────
# Filesystem regressions — pin the policy decisions in code.
# ──────────────────────────────────────────────────────────────────

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_t3_11_expenses_always_creates_je_with_status_field():
    src = _read(EXP_PATH)
    # The unified create path must thread `je_status=` (draft for
    # pending, posted for auto-approved).
    assert "je_status=je_status" in src, (
        "create_expense must pass je_status to create_expense_journal_entry"
    )
    assert "\"posted\" if approval_status == \"approved\" else \"draft\"" in src, (
        "JE status must be derived from approval_status — draft when pending"
    )
    # The legacy "if approval_status == 'approved': create JE" gate
    # must not be the only place a JE is created.
    assert src.count("create_expense_journal_entry(") >= 2, (
        "JE helper should be invoked from both the unified create path "
        "and the legacy fallback in approve_expense"
    )


def test_t3_11_treasury_endpoint_delegates_to_unified_path():
    src = _read(TR_PATH)
    assert "from routers.finance.expenses import create_expense as unified_create_expense" in src, (
        "treasury /transactions/expense must delegate to the unified expenses flow"
    )
    # The duplicated JE-construction logic in treasury.py must be gone.
    assert "INSERT INTO treasury_transactions" not in src.split("/transactions/expense")[1].split("/transactions/transfer")[0], (
        "treasury create_expense shim must not insert into treasury_transactions; "
        "the unified expenses path handles the JE/balance update"
    )


def test_t3_11_gl_service_exposes_post_draft_helper():
    src = _read(GL_PATH)
    assert "def post_draft_journal_entry(" in src, (
        "gl_service must expose post_draft_journal_entry for T3.11 approval flip"
    )
    assert "status = 'posted'" in src or 'status = \'posted\'' in src, (
        "post_draft_journal_entry must flip status to posted"
    )


def test_t3_12_approve_expense_takes_for_update_lock():
    src = _read(EXP_PATH)
    # The lock must be inside the approve handler, before the SELECT
    # that fetches the expense details.
    approve_block = src.split("async def approve_expense(")[1].split("@router")[0]
    assert "FROM expenses WHERE id = :id AND is_deleted = false FOR UPDATE" in approve_block, (
        "T3.12: approve_expense must SELECT ... FOR UPDATE on the expense row "
        "before any approval work"
    )


def test_t3_13_reverse_endpoint_exists_and_uses_reverse_helper():
    src = _read(EXP_PATH)
    assert '@router.post("/{expense_id}/reverse"' in src, (
        "T3.13: POST /expenses/{id}/reverse must exist"
    )
    rev_block = src.split("async def reverse_expense(")[1].split("@router")[0]
    assert "from services.gl_service import reverse_journal_entry" in rev_block
    assert "reverse_journal_entry(" in rev_block
    assert "approval_status = 'reversed'" in rev_block
    # Treasury and project actuals must be unwound.
    assert "current_balance = current_balance + :amt" in rev_block
    assert "actual_cost - :amt" in rev_block


# ──────────────────────────────────────────────────────────────────
# End-to-end: post + reverse a JE through the new helpers and assert
# every involved account balance returns to its starting value.
# ──────────────────────────────────────────────────────────────────

TEST_DB_URL = os.environ.get(
    "AMAN_TEST_DB_URL",
    "postgresql://aman:YourPassword123%21%40%23@localhost:5432/aman_d24b1b1c",
)


def _connect():
    return psycopg2.connect(TEST_DB_URL)


class _DBConnAdapter:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, stmt, params=None):
        sql = re.sub(r":(\w+)", r"%(\1)s", str(stmt))
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor)
        cur.execute(sql, params or {})

        class _Result:
            def __init__(self, c):
                self.c = c
            def scalar(self):
                if self.c.description is None:
                    return None
                row = self.c.fetchone()
                return None if row is None else row[0]
            def fetchone(self):
                return None if self.c.description is None else self.c.fetchone()
            def fetchall(self):
                return [] if self.c.description is None else self.c.fetchall()
            def __iter__(self):
                return iter([] if self.c.description is None else self.c.fetchall())

        return _Result(cur)

    def commit(self):
        self.raw.commit()
    def rollback(self):
        self.raw.rollback()
    def in_transaction(self):
        return True
    def begin_nested(self):
        from contextlib import nullcontext
        return nullcontext()
    def begin(self):
        from contextlib import nullcontext
        return nullcontext()


@pytest.fixture
def gl_db():
    raw = _connect()
    raw.autocommit = False
    db = _DBConnAdapter(raw)
    yield db
    raw.rollback()
    raw.close()


def _ensure_account(db, code, name, atype):
    """Create or fetch an account row and return its id. The real schema
    uses (account_number, name, account_type) — account_code is optional.
    """
    row = db.execute(
        "SELECT id FROM accounts WHERE account_number = :code", {"code": code}
    ).fetchone()
    if row:
        return row[0]
    return db.execute(
        "INSERT INTO accounts (account_number, account_code, name, account_type, is_active) "
        "VALUES (:c, :c, :n, :t, TRUE) RETURNING id",
        {"c": code, "n": name, "t": atype},
    ).scalar()


def _balance(db, account_id):
    row = db.execute(
        "SELECT balance FROM accounts WHERE id = :id", {"id": account_id},
    ).fetchone()
    if not row:
        return Decimal("0")
    return Decimal(str(row[0] or 0))


def test_post_draft_then_reverse_yields_net_zero(gl_db):
    """Draft → post → reverse leaves total debit==credit on every account
    and the sum of (debit - credit) per account back to its baseline.
    """
    from services.gl_service import (
        create_journal_entry,
        post_draft_journal_entry,
        reverse_journal_entry,
    )

    exp_acc = _ensure_account(gl_db, "T3-11-EXP", "T3.11 expense test", "expense")
    cash_acc = _ensure_account(gl_db, "T3-11-CASH", "T3.11 cash test", "asset")

    exp0 = _balance(gl_db, exp_acc)
    cash0 = _balance(gl_db, cash_acc)

    # 1) Create as DRAFT — balances must not move.
    je_id, _je_num = create_journal_entry(
        db=gl_db,
        company_id="test",
        date="2026-05-01",
        description="T3.11 unit test",
        lines=[
            {"account_id": exp_acc, "debit": Decimal("250"), "credit": 0},
            {"account_id": cash_acc, "debit": 0, "credit": Decimal("250")},
        ],
        user_id=1,
        status="draft",
        source="t3_11_test",
        source_id=None,
    )
    assert _balance(gl_db, exp_acc) == exp0, "draft must not move expense balance"
    assert _balance(gl_db, cash_acc) == cash0, "draft must not move cash balance"

    # 2) Post the draft.
    assert post_draft_journal_entry(gl_db, je_id, user_id=1) is True
    # Idempotent: posting again is a no-op.
    assert post_draft_journal_entry(gl_db, je_id, user_id=1) is False
    # asset/expense balances grow on debit; cash is asset (debit-natural)
    # but our line credits it, so its balance should DROP by 250.
    assert _balance(gl_db, exp_acc) - exp0 == Decimal("250.00"), (
        f"expense moved by {_balance(gl_db, exp_acc) - exp0}"
    )
    assert _balance(gl_db, cash_acc) - cash0 == Decimal("-250.00"), (
        f"cash moved by {_balance(gl_db, cash_acc) - cash0}"
    )

    # 3) Reverse the posted JE — net effect on each account must be zero.
    rev_id, _ = reverse_journal_entry(
        gl_db, je_id=je_id, user_id=1, company_id="test",
        reversal_date="2026-05-01", reason="T3.13 unit test",
    )
    assert rev_id and rev_id != je_id
    assert _balance(gl_db, exp_acc) == exp0, (
        f"expense not back to baseline: {_balance(gl_db, exp_acc)} vs {exp0}"
    )
    assert _balance(gl_db, cash_acc) == cash0, (
        f"cash not back to baseline: {_balance(gl_db, cash_acc)} vs {cash0}"
    )


def test_reverse_rejects_draft_journal(gl_db):
    """T3.13: only posted entries can be reversed — drafts must error."""
    from fastapi import HTTPException
    from services.gl_service import create_journal_entry, reverse_journal_entry

    exp_acc = _ensure_account(gl_db, "T3-11-EXP2", "T3.11 expense test 2", "expense")
    cash_acc = _ensure_account(gl_db, "T3-11-CASH2", "T3.11 cash test 2", "asset")

    je_id, _ = create_journal_entry(
        db=gl_db, company_id="test", date="2026-05-01",
        description="T3.13 draft reverse guard",
        lines=[
            {"account_id": exp_acc, "debit": Decimal("10"), "credit": 0},
            {"account_id": cash_acc, "debit": 0, "credit": Decimal("10")},
        ],
        user_id=1, status="draft", source="t3_13_guard", source_id=None,
    )
    with pytest.raises(HTTPException) as exc:
        reverse_journal_entry(
            gl_db, je_id=je_id, user_id=1, company_id="test",
            reversal_date="2026-05-01",
        )
    assert exc.value.status_code == 400
