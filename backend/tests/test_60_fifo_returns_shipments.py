"""T3.9 — FIFO/LIFO accuracy in purchase returns + warehouse shipments.

Scenario covered (FIFO):

  1. Purchase 10 units @ 100 → cost_layer L1 (qty=10, cost=100)
  2. Purchase  5 units @ 120 → cost_layer L2 (qty=5,  cost=120)
  3. Sell      8 units       → consume_layers FIFO ⇒ L1 remaining=2, L2 remaining=5
  4. Purchase return 2 of the original purchase ⇒ handle_return must
     **reduce L1's remaining_quantity** (because L1 is the layer the
     supplier produced) instead of creating a new positive layer.

  Expected residual valuation after step (4):
      L1 remaining = 0 @ 100   →   0
      L2 remaining = 5 @ 120   →  600
  Total inventory value = 600, total qty = 5, weighted-average = 120.

If `handle_return` regressed to "create a new layer at unit_cost" we would
end up with three layers (2 @ 100, 5 @ 120, 2 @ 100) and the qty would
incorrectly stay at 9 instead of dropping to 5.

The test wires straight against the test database (psycopg2) so that the
real CostingService SQL queries are exercised end-to-end.
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

# Prevent config.py from blowing up on missing SECRET_KEY when we import
# CostingService (database.py is pulled in transitively by other test files
# in the same session, but in isolation we set a placeholder).
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-t3-9")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from services.costing_service import CostingService  # noqa: E402

TEST_DB_URL = os.environ.get(
    "AMAN_TEST_DB_URL",
    "postgresql://aman:YourPassword123%21%40%23@localhost:5432/aman_d24b1b1c",
)


def _connect():
    return psycopg2.connect(TEST_DB_URL)


class _DBConnAdapter:
    """Same shape as the adapter used in test_58: SQLAlchemy-ish .execute
    over psycopg2 so CostingService can run unmodified."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, stmt, params=None):
        sql = str(stmt)
        sql = re.sub(r":(\w+)", r"%(\1)s", sql)
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

        return _Result(cur)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    # CostingService.update_cost calls .in_transaction()/.begin*() — provide
    # no-op stubs because we're already inside a transaction here.
    def in_transaction(self):
        return True

    def begin_nested(self):
        from contextlib import nullcontext
        return nullcontext()

    def begin(self):
        from contextlib import nullcontext
        return nullcontext()


@pytest.fixture
def costing_db():
    raw = _connect()
    raw.autocommit = False
    db = _DBConnAdapter(raw)
    yield db
    raw.rollback()
    raw.close()


@pytest.fixture
def fixture_ids(costing_db):
    """Insert a throwaway product + warehouse + supplier, return their ids.

    Everything created here is rolled back by the costing_db fixture.
    """
    db = costing_db
    # Pick an existing branch (any) to satisfy NOT NULL constraints if any.
    pid = db.execute("""
        INSERT INTO products (product_code, product_name, cost_price)
        VALUES ('T39_PROD', 'T3.9 Product', 0)
        RETURNING id
    """).scalar()
    wid = db.execute("""
        INSERT INTO warehouses (warehouse_code, warehouse_name)
        VALUES ('T39_WH', 'T3.9 Warehouse')
        RETURNING id
    """).scalar()
    db.execute("""
        INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost)
        VALUES (%(pid)s, %(wid)s, 0, 0)
    """ % {"pid": pid, "wid": wid})
    return {"product_id": pid, "warehouse_id": wid}


def _layers(db, pid, wid):
    rows = db.execute("""
        SELECT id, original_quantity, remaining_quantity, unit_cost, source_document_type, source_document_id, is_exhausted
        FROM cost_layers
        WHERE product_id = :pid AND warehouse_id = :wid
        ORDER BY id ASC
    """, {"pid": pid, "wid": wid}).fetchall()
    return rows


def test_purchase_return_reduces_original_layer(costing_db, fixture_ids):
    """T3.9 DoD: purchase → sale → purchase-return matches expected residual."""
    db = costing_db
    pid = fixture_ids["product_id"]
    wid = fixture_ids["warehouse_id"]

    # Step 1+2: two purchase layers
    l1 = CostingService.create_cost_layer(
        db, pid, wid, 10, 100,
        source_document_type="purchase_invoice", source_document_id=9001,
        costing_method="fifo",
    )
    l2 = CostingService.create_cost_layer(
        db, pid, wid, 5, 120,
        source_document_type="purchase_invoice", source_document_id=9002,
        costing_method="fifo",
    )
    # Reflect inventory so consume_layers' availability check passes
    db.execute("""
        UPDATE inventory SET quantity = 15 WHERE product_id = :pid AND warehouse_id = :wid
    """, {"pid": pid, "wid": wid})

    # Step 3: sell 8 → FIFO consumes from L1
    cogs = CostingService.consume_layers(
        db, pid, wid, 8,
        sale_document_type="sales_invoice", sale_document_id=7001,
        costing_method="fifo",
    )
    assert Decimal(cogs) == Decimal("800"), f"FIFO COGS for 8 units expected 800, got {cogs}"
    db.execute("""
        UPDATE inventory SET quantity = quantity - 8 WHERE product_id = :pid AND warehouse_id = :wid
    """, {"pid": pid, "wid": wid})

    after_sale = _layers(db, pid, wid)
    assert len(after_sale) == 2
    l1_row = next(r for r in after_sale if r.id == l1)
    l2_row = next(r for r in after_sale if r.id == l2)
    assert Decimal(l1_row.remaining_quantity) == Decimal("2")
    assert Decimal(l2_row.remaining_quantity) == Decimal("5")

    # Step 4: purchase return of 2 against the original purchase invoice 9001.
    # handle_return must reduce L1, not create a new layer.
    result = CostingService.handle_return(
        db,
        product_id=pid,
        warehouse_id=wid,
        quantity=2,
        unit_cost=100,
        source_document_type="purchase_return",
        source_document_id=8001,
        costing_method="fifo",
        original_source_document_type="purchase_invoice",
        original_source_document_id=9001,
    )
    db.execute("""
        UPDATE inventory SET quantity = quantity - 2 WHERE product_id = :pid AND warehouse_id = :wid
    """, {"pid": pid, "wid": wid})

    assert result["strategy"] == "reduce_layer", (
        f"purchase return must reduce the original layer, got strategy={result['strategy']}"
    )
    assert result["new_layer_id"] is None, "purchase return must NOT create a new cost layer"

    final_layers = _layers(db, pid, wid)
    # Still exactly two layers — no fresh return layer.
    assert len(final_layers) == 2, f"expected 2 layers, got {len(final_layers)}: {final_layers}"
    l1_final = next(r for r in final_layers if r.id == l1)
    l2_final = next(r for r in final_layers if r.id == l2)
    assert Decimal(l1_final.remaining_quantity) == Decimal("0"), (
        f"L1 should be drained after return (2 sold + 0 returnable from layer = was 2 remaining, "
        f"now reduced by 2), got {l1_final.remaining_quantity}"
    )
    assert l1_final.is_exhausted is True
    assert Decimal(l2_final.remaining_quantity) == Decimal("5")
    assert l2_final.is_exhausted is False

    # Residual valuation
    residual_qty = Decimal(l1_final.remaining_quantity) + Decimal(l2_final.remaining_quantity)
    residual_value = (
        Decimal(l1_final.remaining_quantity) * Decimal(l1_final.unit_cost)
        + Decimal(l2_final.remaining_quantity) * Decimal(l2_final.unit_cost)
    )
    assert residual_qty == Decimal("5")
    assert residual_value == Decimal("600")
    # Weighted average of the residual is L2's cost only.
    assert (residual_value / residual_qty) == Decimal("120")


def test_handle_return_falls_back_to_consume_when_original_layer_drained(
    costing_db, fixture_ids
):
    """If the original layer is fully consumed, the return must still drain stock.

    Scenario: buy 5 @ 100, sell 5 (drains L1), buy 5 @ 120 (L2). Now return 2
    against the original purchase. There is nothing left of L1 to reduce, so
    the return must consume FIFO from remaining layers and *not* leave the
    inventory at the wrong level.
    """
    db = costing_db
    pid = fixture_ids["product_id"]
    wid = fixture_ids["warehouse_id"]

    CostingService.create_cost_layer(
        db, pid, wid, 5, 100,
        source_document_type="purchase_invoice", source_document_id=9100,
        costing_method="fifo",
    )
    db.execute("UPDATE inventory SET quantity = 5 WHERE product_id = :pid AND warehouse_id = :wid",
               {"pid": pid, "wid": wid})
    CostingService.consume_layers(
        db, pid, wid, 5,
        sale_document_type="sales_invoice", sale_document_id=7100,
        costing_method="fifo",
    )
    db.execute("UPDATE inventory SET quantity = 0 WHERE product_id = :pid AND warehouse_id = :wid",
               {"pid": pid, "wid": wid})
    CostingService.create_cost_layer(
        db, pid, wid, 5, 120,
        source_document_type="purchase_invoice", source_document_id=9101,
        costing_method="fifo",
    )
    db.execute("UPDATE inventory SET quantity = 5 WHERE product_id = :pid AND warehouse_id = :wid",
               {"pid": pid, "wid": wid})

    result = CostingService.handle_return(
        db,
        product_id=pid, warehouse_id=wid,
        quantity=2, unit_cost=100,
        source_document_type="purchase_return", source_document_id=8100,
        original_source_document_type="purchase_invoice",
        original_source_document_id=9100,  # original layer is fully drained
        costing_method="fifo",
    )
    # L1 has remaining=0 (already consumed by the sale), so the return falls
    # through to consuming from L2.
    assert result["strategy"] in ("reduce_layer+consume_overflow",), (
        f"expected fallback to consume overflow, got {result['strategy']}"
    )

    layers = _layers(db, pid, wid)
    l2 = next(line for line in layers if Decimal(line.unit_cost) == Decimal("120"))
    assert Decimal(l2.remaining_quantity) == Decimal("3"), (
        f"L2 should be reduced by the overflow (5-2=3), got {l2.remaining_quantity}"
    )


def test_handle_return_legacy_path_creates_new_layer_when_no_original_ref(
    costing_db, fixture_ids
):
    """Calling handle_return without original_source_document_* keeps the
    legacy "create a fresh layer" behaviour for backwards compatibility."""
    db = costing_db
    pid = fixture_ids["product_id"]
    wid = fixture_ids["warehouse_id"]

    result = CostingService.handle_return(
        db,
        product_id=pid, warehouse_id=wid,
        quantity=3, unit_cost=99,
        source_document_type="purchase_return", source_document_id=8200,
        # No original_source_document_* on purpose.
        costing_method="fifo",
    )
    assert result["strategy"] == "new_layer"
    assert result["new_layer_id"] is not None

    layer = db.execute("""
        SELECT remaining_quantity, unit_cost, source_document_type
        FROM cost_layers WHERE id = :id
    """, {"id": result["new_layer_id"]}).fetchone()
    assert Decimal(layer.remaining_quantity) == Decimal("3")
    assert Decimal(layer.unit_cost) == Decimal("99")
    assert layer.source_document_type == "purchase_return"


def test_purchase_return_router_wires_handle_return():
    """Filesystem regression: purchases return router must call handle_return
    with original_source_document_type='purchase_invoice' on the return path.

    After T6.3 the monolithic purchases.py was split into a package — scan
    the dedicated returns sub-router.
    """
    path = os.path.join(ROOT, "routers", "purchases", "returns.py")
    if not os.path.exists(path):
        # backward-compat fallback for pre-T6.3 layout
        path = os.path.join(ROOT, "routers", "purchases.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "CostingService.handle_return(" in src, (
        "purchase return path must invoke CostingService.handle_return"
    )
    assert 'original_source_document_type="purchase_invoice"' in src, (
        "purchase return must pass original_source_document_type='purchase_invoice' "
        "so the original cost layer is reduced rather than a new one created"
    )


def test_shipments_router_consumes_and_creates_layers():
    """Filesystem regression: routers/inventory/shipments.py must move cost
    layers from source warehouse to destination warehouse during confirm.
    """
    path = os.path.join(ROOT, "routers", "inventory", "shipments.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "CostingService.consume_layers(" in src, (
        "shipment confirm must consume layers at the source warehouse"
    )
    assert "CostingService.create_cost_layer(" in src, (
        "shipment confirm must create a cost layer at the destination warehouse"
    )
    assert 'source_document_type="shipment_receive"' in src, (
        "destination layer must be tagged shipment_receive for traceability"
    )
