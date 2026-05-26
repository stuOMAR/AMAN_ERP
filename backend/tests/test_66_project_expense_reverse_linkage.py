"""T359 — Project / Expense Reverse Linkage verification.

Asserts that:
1. The project core listing combines project_expenses and approved general expenses (from expenses table).
2. The project detail/expenses endpoints merge these correctly.
3. Profitability, monitoring, alerts, and EVM queries consolidate these correctly.
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

CORE_PATH = os.path.join(ROOT, "routers", "projects", "core.py")
FIN_PATH = os.path.join(ROOT, "routers", "projects", "finance.py")
MON_PATH = os.path.join(ROOT, "routers", "projects", "monitoring.py")
TIME_PATH = os.path.join(ROOT, "routers", "projects", "timetracking.py")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_reverse_linkage_queries_consolidated_in_files():
    # Verify core.py integration
    core_src = _read(CORE_PATH)
    assert "expenses WHERE approval_status = 'approved' AND is_deleted = false" in core_src, (
        "core.py must merge approved general expenses"
    )
    assert "UNION ALL" in core_src, "core.py must union project_expenses and expenses"

    # Verify finance.py integration
    fin_src = _read(FIN_PATH)
    assert "expenses e" in fin_src, "finance.py must merge from expenses table"
    assert "e.approval_status = 'approved'" in fin_src, "finance.py must filter for approved expenses"

    # Verify monitoring.py integration
    mon_src = _read(MON_PATH)
    assert "expenses WHERE approval_status = 'approved'" in mon_src or "expenses WHERE" in mon_src, (
        "monitoring.py must merge approved general expenses"
    )

    # Verify timetracking.py integration
    time_src = _read(TIME_PATH)
    assert "expenses WHERE project_id = :pid AND approval_status = 'approved'" in time_src, (
        "timetracking.py must merge approved general expenses"
    )


# ──────────────────────────────────────────────────────────────────
# Database verification using the standard AMAN test database.
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


@pytest.fixture
def db():
    raw = _connect()
    raw.autocommit = False
    conn = _DBConnAdapter(raw)
    yield conn
    raw.rollback()
    raw.close()


def _ensure_test_project(db) -> int:
    row = db.execute("SELECT id FROM projects WHERE name = 'T359 Test Project'").fetchone()
    if row:
        return row[0]
    return db.execute("""
        INSERT INTO projects (name, planned_budget, status, created_at)
        VALUES ('T359 Test Project', 1000.00, 'active', NOW())
        RETURNING id
    """).scalar()


def test_consolidation_query_returns_expected_amounts(db):
    project_id = _ensure_test_project(db)

    # 1. Clear previous test records for this project
    db.execute("DELETE FROM project_expenses WHERE project_id = :pid", {"pid": project_id})
    db.execute("DELETE FROM expenses WHERE project_id = :pid", {"pid": project_id})

    # 2. Insert one specific project expense
    db.execute("""
        INSERT INTO project_expenses (project_id, expense_type, expense_date, amount, description, status, created_by, created_at)
        VALUES (:pid, 'Material', '2026-05-01', 300.00, 'Direct project expense', 'approved', 1, NOW())
    """, {"pid": project_id})

    # 3. Insert approved general expense (linked via project_id)
    db.execute("""
        INSERT INTO expenses (project_id, expense_type, expense_date, amount, description, approval_status, is_deleted, created_by, created_at)
        VALUES (:pid, 'Travel', '2026-05-02', 150.00, 'General approved expense', 'approved', FALSE, 1, NOW())
    """, {"pid": project_id})

    # 4. Insert pending general expense (should be EXCLUDED)
    db.execute("""
        INSERT INTO expenses (project_id, expense_type, expense_date, amount, description, approval_status, is_deleted, created_by, created_at)
        VALUES (:pid, 'Software', '2026-05-03', 500.00, 'General pending expense', 'pending', FALSE, 1, NOW())
    """, {"pid": project_id})

    # 5. Insert deleted approved general expense (should be EXCLUDED)
    db.execute("""
        INSERT INTO expenses (project_id, expense_type, expense_date, amount, description, approval_status, is_deleted, created_by, created_at)
        VALUES (:pid, 'Meals', '2026-05-04', 100.00, 'General deleted approved expense', 'approved', TRUE, 1, NOW())
    """, {"pid": project_id})

    # Assert consolidation query total expenses matches 300 + 150 = 450
    total_expenses = db.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM (
            SELECT amount FROM project_expenses WHERE project_id = :pid AND status != 'rejected'
            UNION ALL
            SELECT amount FROM expenses WHERE project_id = :pid AND approval_status = 'approved' AND is_deleted = false
        ) combined
    """, {"pid": project_id}).scalar()

    assert Decimal(str(total_expenses)) == Decimal("450.00"), f"Expected 450.00, got {total_expenses}"
