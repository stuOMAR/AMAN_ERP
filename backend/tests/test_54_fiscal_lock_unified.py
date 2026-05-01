"""T3.3 (audit #17) — unified fiscal period guard.

Verifies that the canonical `utils.fiscal_lock.check_fiscal_period_open`
honours BOTH legacy guard tables (fiscal_period_locks AND
fiscal_periods.is_closed) and that the broken
`from utils.accounting import check_fiscal_period_open` import has been
purged from the sales sub-routers.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from utils.fiscal_lock import check_fiscal_period_open


class _Row:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_db(*, lock_row=None, closed_row=None):
    """Build a SQLAlchemy-style db mock that returns the given rows from
    the two SELECTs in `check_fiscal_period_open`. Order: locks first,
    then closed-period query."""
    db = MagicMock()
    rows = iter([
        MagicMock(fetchone=MagicMock(return_value=lock_row)),
        MagicMock(fetchone=MagicMock(return_value=closed_row)),
    ])
    db.execute.side_effect = lambda *a, **kw: next(rows)
    return db


def test_open_period_passes():
    db = _make_db(lock_row=None, closed_row=None)
    assert check_fiscal_period_open(db, date(2026, 5, 1)) is True


def test_locked_period_blocks():
    lock = _Row(id=1, period_name="Q1-2026", locked_at="2026-04-01", locked_by=7)
    db = _make_db(lock_row=lock, closed_row=None)
    with pytest.raises(HTTPException) as exc:
        check_fiscal_period_open(db, date(2026, 2, 15))
    assert exc.value.status_code == 400
    assert "مقفلة" in str(exc.value.detail)


def test_closed_year_end_period_blocks():
    closed = _Row(id=99, name="2025-12")
    db = _make_db(lock_row=None, closed_row=closed)
    with pytest.raises(HTTPException) as exc:
        check_fiscal_period_open(db, date(2025, 12, 31))
    assert exc.value.status_code == 400
    assert "مغلقة" in str(exc.value.detail)


def test_locked_returns_false_when_raise_disabled():
    lock = _Row(id=1, period_name="Q1-2026", locked_at="2026-04-01", locked_by=7)
    db = _make_db(lock_row=lock, closed_row=None)
    assert check_fiscal_period_open(db, date(2026, 2, 15), raise_error=False) is False


def test_no_broken_accounting_import_in_sales_routers():
    """Regression for the original duplicate-mechanism bug: half of
    routers/sales used a non-existent `utils.accounting.check_fiscal_period_open`.
    """
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[1] / "routers" / "sales"
    for path in base.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from utils.accounting import check_fiscal_period_open" not in text, (
            f"{path} still imports check_fiscal_period_open from utils.accounting"
        )
