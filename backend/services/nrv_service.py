"""
TASK-038 — IAS 2 Net Realisable Value (NRV) inventory write-down service.

For each (product, warehouse) with positive on-hand quantity, compares the
carrying cost (average_cost from `inventory`) against an NRV estimate
(selling_price · (1 - selling_cost_rate)). Where NRV < cost, records a
write-down in `inventory_nrv_tests` and optionally posts a JE.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)
_D4 = Decimal("0.0001")


def run_nrv_test(
    db,
    company_id: str,
    as_of_date: Optional[date] = None,
    selling_cost_rate: Decimal = Decimal("0.05"),
    post_journal: bool = False,
    inventory_account_id: Optional[int] = None,
    writedown_expense_account_id: Optional[int] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> dict:
    as_of = as_of_date or date.today()

    rows = db.execute(text("""
        SELECT
            inv.product_id,
            inv.warehouse_id,
            inv.quantity           AS qty_on_hand,
            COALESCE(inv.average_cost, p.cost_price, 0) AS unit_cost,
            COALESCE(p.selling_price, 0)                AS unit_selling
        FROM inventory inv
        JOIN products p ON p.id = inv.product_id
        WHERE COALESCE(p.is_active, TRUE) = TRUE
          AND COALESCE(inv.quantity, 0) > 0
    """)).fetchall()

    total_writedown = Decimal("0")
    test_rows_written = 0

    for row in rows:
        qty = Decimal(str(row.qty_on_hand or 0))
        cost = Decimal(str(row.unit_cost or 0))
        selling = Decimal(str(row.unit_selling or 0))
        if qty <= 0 or cost <= 0:
            continue
        nrv = (selling * (Decimal("1") - Decimal(str(selling_cost_rate)))).quantize(_D4, rounding=ROUND_HALF_UP)
        cost_value = (qty * cost).quantize(_D4, rounding=ROUND_HALF_UP)
        nrv_value = (qty * nrv).quantize(_D4, rounding=ROUND_HALF_UP)
        writedown = max(Decimal("0"), cost_value - nrv_value).quantize(_D4, rounding=ROUND_HALF_UP)
        if writedown <= 0:
            continue
        db.execute(text("""
            INSERT INTO inventory_nrv_tests (as_of_date, product_id, warehouse_id,
                cost_value, nrv_value, writedown_amount, notes)
            VALUES (:dt, :pid, :wid, :cv, :nv, :wd, :nt)
        """), {
            "dt": as_of,
            "pid": row.product_id,
            "wid": row.warehouse_id,
            "cv": str(cost_value),
            "nv": str(nrv_value),
            "wd": str(writedown),
            "nt": f"NRV test: qty={qty} cost={cost} nrv={nrv}",
        })
        total_writedown += writedown
        test_rows_written += 1

    journal_entry_id = None
    if post_journal and total_writedown > 0:
        if not (inventory_account_id and writedown_expense_account_id):
            raise ValueError("post_journal=True requires inventory_account_id + writedown_expense_account_id")
        if not user_id:
            raise ValueError("post_journal=True requires user_id")
        from services.gl_service import create_journal_entry
        from utils.fiscal_lock import check_fiscal_period_open

        # Fiscal-period lock: block posting into a closed period.
        check_fiscal_period_open(db, str(as_of))
        journal_entry_id, _ = create_journal_entry(
            db,
            company_id=company_id,
            date=str(as_of),
            description=f"IAS 2 NRV write-down as of {as_of}",
            lines=[
                {"account_id": writedown_expense_account_id,
                 "debit": float(total_writedown), "credit": 0,
                 "description": "Inventory NRV write-down expense"},
                {"account_id": inventory_account_id,
                 "debit": 0, "credit": float(total_writedown),
                 "description": "Inventory reduced to NRV"},
            ],
            user_id=user_id,
            username=username or "nrv_service",
            source="nrv_test",
            status="posted",
        )
        db.execute(text("""
            UPDATE inventory_nrv_tests SET journal_entry_id = :jeid
            WHERE as_of_date = :dt AND journal_entry_id IS NULL
        """), {"jeid": journal_entry_id, "dt": as_of})

    db.commit()
    return {
        "as_of_date": str(as_of),
        "rows": test_rows_written,
        "total_writedown": str(total_writedown),
        "journal_entry_id": journal_entry_id,
    }
