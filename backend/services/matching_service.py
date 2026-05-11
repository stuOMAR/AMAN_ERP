"""Three-way matching service: PO ↔ GRN ↔ Invoice.

Auto-triggered on purchase invoice creation when linked to a PO.
Compares each invoice line against PO line quantities/prices and GRN received quantities.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

logger = logging.getLogger(__name__)

_D4 = Decimal("0.0001")
_D2 = Decimal("0.01")
_ZERO = Decimal("0")


def _dec(val) -> Decimal:
    if val is None:
        return _ZERO
    return Decimal(str(val))


def _pct(actual: Decimal, expected: Decimal) -> Decimal:
    """Compute variance percentage: abs((actual - expected) / expected) * 100."""
    if expected == 0:
        return Decimal("100") if actual != 0 else _ZERO
    return (abs(actual - expected) / abs(expected) * 100).quantize(_D2, ROUND_HALF_UP)


def _find_tolerance(db, supplier_id: int | None):
    """Find best-fit tolerance: supplier-specific first, then global default."""
    if supplier_id:
        row = db.execute(text(
            "SELECT id, quantity_percent, quantity_absolute, price_percent, price_absolute "
            "FROM match_tolerances WHERE supplier_id = :sid ORDER BY id LIMIT 1"
        ), {"sid": supplier_id}).fetchone()
        if row:
            return row

    # Fallback: global tolerance (supplier_id IS NULL)
    row = db.execute(text(
        "SELECT id, quantity_percent, quantity_absolute, price_percent, price_absolute "
        "FROM match_tolerances WHERE supplier_id IS NULL ORDER BY id LIMIT 1"
    )).fetchone()
    return row


def _within_tolerance(variance_pct: Decimal, variance_abs: Decimal,
                      tol_pct: Decimal, tol_abs: Decimal) -> bool:
    """Pass if EITHER % or absolute threshold is satisfied (spec requirement)."""
    if tol_pct > 0 and variance_pct <= tol_pct:
        return True
    if tol_abs > 0 and variance_abs <= tol_abs:
        return True
    # If no tolerance configured, only exact match passes
    if tol_pct == 0 and tol_abs == 0:
        return variance_pct == 0 and variance_abs == 0
    return False


def perform_match(db, invoice_id: int, po_id: int, supplier_id: int | None = None,
                  user_id: int | None = None) -> dict:
    """Run 3-way match for a purchase invoice linked to a PO.

    Returns dict with match_id, match_status, and line details.
    """
    # 1. Fetch PO lines (lock for consistency)
    po_lines = db.execute(text("""
        SELECT id, product_id, quantity, unit_price, COALESCE(received_quantity, 0) as received_quantity
        FROM purchase_order_lines
        WHERE po_id = :po_id
        FOR UPDATE
    """), {"po_id": po_id}).fetchall()

    if not po_lines:
        logger.warning("No PO lines found for PO %s — skipping match", po_id)
        return {"match_id": None, "match_status": "skipped"}

    # 2. Fetch invoice lines (with po_line_id for line-level matching)
    inv_lines = db.execute(text("""
        SELECT id, product_id, po_line_id, quantity, unit_price
        FROM invoice_lines
        WHERE invoice_id = :inv_id
        FOR UPDATE
    """), {"inv_id": invoice_id}).fetchall()

    # Build invoice lines map by po_line_id. PO-linked invoices must not fall
    # back to product_id because duplicate products on a PO are common.
    inv_map: dict[int | None, list] = {}
    for il in inv_lines:
        if il.po_line_id:
            inv_map.setdefault(il.po_line_id, []).append(il)

    # 3. Find applicable tolerance
    tol = _find_tolerance(db, supplier_id)
    tol_id = tol.id if tol else None
    tol_qty_pct = _dec(tol.quantity_percent) if tol else _ZERO
    tol_qty_abs = _dec(tol.quantity_absolute) if tol else _ZERO
    tol_price_pct = _dec(tol.price_percent) if tol else _ZERO
    tol_price_abs = _dec(tol.price_absolute) if tol else _ZERO

    # 4. Create match header
    result = db.execute(text("""
        INSERT INTO three_way_matches (purchase_order_id, invoice_id, match_status, matched_by, created_by)
        VALUES (:po_id, :inv_id, 'matched', :user_id, :user_str)
        RETURNING id
    """), {
        "po_id": po_id,
        "inv_id": invoice_id,
        "user_id": user_id,
        "user_str": str(user_id) if user_id else None,
    })
    match_id = result.scalar()

    # 5. Match each PO line
    overall_status = "matched"
    line_results = []

    for pol in po_lines:
        po_qty = _dec(pol.quantity)
        po_price = _dec(pol.unit_price)
        recv_qty = _dec(pol.received_quantity)

        # Find matching invoice line by po_line_id only.
        candidates = inv_map.get(pol.id, [])
        if not candidates:
            continue
        inv_line = candidates.pop(0)  # consume first match

        inv_qty = _dec(inv_line.quantity) if inv_line else _ZERO
        inv_price = _dec(inv_line.unit_price) if inv_line else _ZERO
        inv_line_id = inv_line.id if inv_line else None

        # Compute variances
        qty_var_abs = max(_ZERO, inv_qty - recv_qty).quantize(_D4, ROUND_HALF_UP)
        qty_var_pct = _pct(qty_var_abs, recv_qty)
        price_var_abs = abs(inv_price - po_price).quantize(_D4, ROUND_HALF_UP)
        price_var_pct = _pct(inv_price, po_price)

        # Determine line status
        qty_ok = _within_tolerance(qty_var_pct, qty_var_abs, tol_qty_pct, tol_qty_abs)
        price_ok = _within_tolerance(price_var_pct, price_var_abs, tol_price_pct, tol_price_abs)

        if qty_ok and price_ok:
            line_status = "matched"
        elif not qty_ok and not price_ok:
            line_status = "both_mismatch"
        elif not qty_ok:
            line_status = "quantity_mismatch"
        else:
            line_status = "price_mismatch"

        if line_status != "matched":
            overall_status = "held"

        # Insert match line
        db.execute(text("""
            INSERT INTO three_way_match_lines (
                match_id, po_line_id, grn_ids, invoice_line_id,
                po_quantity, received_quantity, invoiced_quantity,
                po_unit_price, invoiced_unit_price,
                quantity_variance_pct, quantity_variance_abs,
                price_variance_pct, price_variance_abs,
                tolerance_id, line_status, created_by
            ) VALUES (
                :mid, :pol_id, :grn_ids, :il_id,
                :po_qty, :recv_qty, :inv_qty,
                :po_price, :inv_price,
                :qty_vpct, :qty_vabs,
                :price_vpct, :price_vabs,
                :tol_id, :status, :user_str
            )
        """), {
            "mid": match_id,
            "pol_id": pol.id,
            "grn_ids": None,  # No separate GRN table; receipt tracked on PO lines
            "il_id": inv_line_id,
            "po_qty": po_qty,
            "recv_qty": recv_qty,
            "inv_qty": inv_qty,
            "po_price": po_price,
            "inv_price": inv_price,
            "qty_vpct": qty_var_pct,
            "qty_vabs": qty_var_abs,
            "price_vpct": price_var_pct,
            "price_vabs": price_var_abs,
            "tol_id": tol_id,
            "status": line_status,
            "user_str": str(user_id) if user_id else None,
        })

        line_results.append({
            "po_line_id": pol.id,
            "line_status": line_status,
            "qty_variance": str(qty_var_pct),
            "price_variance": str(price_var_pct),
        })

    # 6. Update overall match status
    db.execute(text(
        "UPDATE three_way_matches SET match_status = :status WHERE id = :id"
    ), {"status": overall_status, "id": match_id})

    logger.info("3-way match #%s for invoice %s / PO %s → %s",
                match_id, invoice_id, po_id, overall_status)

    return {
        "match_id": match_id,
        "match_status": overall_status,
        "lines": line_results,
    }
