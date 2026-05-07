
from sqlalchemy import text
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
from contextlib import nullcontext

# FIN-FIX: Precision constants for costing calculations
_D4 = Decimal('0.0001')
_dec = lambda v: Decimal(str(v or 0))

class CostingService:
    @staticmethod
    def get_active_policy(db):
        """Get the active costing policy for the current company context."""
        policy = db.execute(text("SELECT policy_type FROM costing_policies WHERE is_active = TRUE LIMIT 1")).scalar()
        return policy or 'global_wac'

    @staticmethod
    def calculate_new_cost(
        current_qty: float,
        current_cost: float,
        new_qty: float,
        new_price: float
    ) -> Decimal:
        """Standard WAC Formula using Decimal for precision."""
        d_curr_qty = _dec(current_qty)
        d_curr_cost = _dec(current_cost)
        d_new_qty = _dec(new_qty)
        d_new_price = _dec(new_price)

        # Guard: reset if current qty is negative (corrupted state)
        if d_curr_qty < 0:
            d_curr_qty = Decimal('0')
            d_curr_cost = Decimal('0')

        total_qty = d_curr_qty + d_new_qty
        if total_qty <= 0:
            return d_new_price.quantize(_D4, ROUND_HALF_UP)

        total_value = (d_curr_qty * d_curr_cost) + (d_new_qty * d_new_price)
        return (total_value / total_qty).quantize(_D4, ROUND_HALF_UP)


    @staticmethod
    def update_cost(
        db,
        product_id: int,
        warehouse_id: int,
        new_qty: float,
        new_price: float
    ):
        """
        Updates product cost based on the active policy.
        CALLED BEFORE INVENTORY QUANTITY UPDATE (to use current stock stats).
        """
        if hasattr(db, "in_transaction") and hasattr(db, "begin") and hasattr(db, "begin_nested"):
            tx_context = db.begin_nested() if db.in_transaction() else db.begin()
        elif hasattr(db, "begin"):
            tx_context = db.begin()
        else:
            tx_context = nullcontext()

        with tx_context:
            policy_type = CostingService.get_active_policy(db)
        
            # 1. Global WAC Strategy
            if policy_type == 'global_wac':
                # Calculate Global Stock
                current_stats = db.execute(text("""
                    SELECT cost_price, 
                           (SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE product_id = :pid) as total_qty
                    FROM products WHERE id = :pid
                """), {"pid": product_id}).fetchone()
                
                curr_qty = _dec(current_stats.total_qty or 0)
                curr_cost = _dec(current_stats.cost_price or 0)
                
                new_wac = CostingService.calculate_new_cost(curr_qty, curr_cost, new_qty, new_price)
                
                # Update Product Master (Global Cost)
                db.execute(text("UPDATE products SET cost_price = :cost, last_purchase_price = :last WHERE id = :pid"), 
                           {"cost": new_wac, "last": new_price, "pid": product_id})
                
                # Sync with inventory rows if they exist (for future per-wh compatibility)
                db.execute(text("UPDATE inventory SET average_cost = :cost WHERE product_id = :pid"),
                           {"cost": new_wac, "pid": product_id})
                
            # 2. Per-Warehouse WAC Strategy
            elif policy_type == 'per_warehouse_wac':
                # Calculate Warehouse Stock
                current_stats = db.execute(text("""
                    SELECT average_cost, quantity 
                    FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
                """), {"pid": product_id, "wh": warehouse_id}).fetchone()
                
                curr_cost = _dec(current_stats.average_cost or 0) if current_stats else Decimal('0')
                curr_qty = _dec(current_stats.quantity or 0) if current_stats else Decimal('0')
                
                new_wac = CostingService.calculate_new_cost(curr_qty, curr_cost, new_qty, new_price)
                
                # Update Inventory Cost (Warehouse Specific)
                exists = db.execute(text("SELECT 1 FROM inventory WHERE product_id=:pid AND warehouse_id=:wh"), 
                                         {"pid": product_id, "wh": warehouse_id}).scalar()
                
                if exists:
                    db.execute(text("""
                        UPDATE inventory SET average_cost = :cost, last_costing_update = CURRENT_TIMESTAMP
                        WHERE product_id = :pid AND warehouse_id = :wh
                    """), {"cost": new_wac, "pid": product_id, "wh": warehouse_id})
                else:
                    db.execute(text("""
                        INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, last_costing_update)
                        VALUES (:pid, :wh, 0, :cost, CURRENT_TIMESTAMP)
                    """), {"pid": product_id, "wh": warehouse_id, "cost": new_wac})
                    
                # Update Product Master for reporting (simple weighted average of all warehouse costs)
                # The warehouse row was ALREADY updated above, so just compute from existing inventory rows
                all_inventory = db.execute(text("""
                    SELECT SUM(quantity * average_cost) as total_val, SUM(quantity) as total_qty
                    FROM inventory WHERE product_id = :pid AND quantity > 0
                """), {"pid": product_id}).fetchone()
                
                cur_total_val = _dec(all_inventory.total_val or 0)
                cur_total_qty = _dec(all_inventory.total_qty or 0)
                
                # The inventory table already reflects the new cost; just compute the weighted average
                global_wac = (cur_total_val / cur_total_qty).quantize(_D4, ROUND_HALF_UP) if cur_total_qty > 0 else _dec(new_price)
                
                db.execute(text("UPDATE products SET cost_price = :cost, last_purchase_price = :last WHERE id = :pid"),
                           {"cost": global_wac, "last": new_price, "pid": product_id})

            # Create Snapshot after update
            CostingService.create_snapshot(db, warehouse_id, product_id)

    @staticmethod
    def get_cogs_cost(db, product_id: int, warehouse_id: Optional[int] = None) -> float:
        """Get the unit cost for COGS based on current policy."""
        policy_type = CostingService.get_active_policy(db)
        
        if policy_type == 'per_warehouse_wac' and warehouse_id:
            cost = db.execute(text("""
                SELECT average_cost FROM inventory 
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"pid": product_id, "wh": warehouse_id}).scalar()
            if cost is not None:
                return float(cost)
        
        # Default to Global Product Cost
        cost = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": product_id}).scalar()
        return float(cost or 0)

    @staticmethod
    def create_snapshot(db, warehouse_id=None, product_id=None):
        """Creates a snapshot of current costs for audit/history."""
        policy_type = CostingService.get_active_policy(db)
        query = """
            INSERT INTO inventory_cost_snapshots (warehouse_id, product_id, average_cost, quantity, policy_type)
            SELECT i.warehouse_id, i.product_id, i.average_cost, i.quantity, :policy
            FROM inventory i
            WHERE 1=1
        """
        params = {"policy": policy_type}
        if warehouse_id:
            query += " AND i.warehouse_id = :wh"
            params["wh"] = warehouse_id
        if product_id:
            query += " AND i.product_id = :pid"
            params["pid"] = product_id
            
        db.execute(text(query), params)

    @staticmethod
    def validate_policy_switch(db, new_policy_type):
        """Analyzes impact before switching policy."""
        # This is a simplified analysis for the MVP refinement
        # affected_products: products where costs differ between warehouses
        impact = db.execute(text("""
            SELECT 
                COUNT(DISTINCT product_id) as affected_products,
                SUM(ABS(average_cost - (SELECT cost_price FROM products p WHERE p.id = product_id))) as total_deviation
            FROM inventory
            WHERE quantity > 0
        """)).fetchone()
        
        return {
            "affected_products_count": impact.affected_products or 0,
            "total_cost_impact": float(impact.total_deviation or 0)
        }

    # ─────────────────────────────────────────────────────────────────────
    # FIFO / LIFO Cost Layer Management
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_product_costing_method(db, product_id: int, warehouse_id: Optional[int] = None) -> str:
        """Return costing method for a product (fifo/lifo/wac)."""
        if warehouse_id:
            row = db.execute(text("""
                SELECT costing_method FROM cost_layers
                WHERE product_id = :pid AND warehouse_id = :wid AND is_exhausted = FALSE
                ORDER BY id DESC LIMIT 1
            """), {"pid": product_id, "wid": warehouse_id}).fetchone()
            if row:
                return row[0]
        row = db.execute(text("""
            SELECT costing_method FROM cost_layers
            WHERE product_id = :pid AND is_exhausted = FALSE
            ORDER BY id DESC LIMIT 1
        """), {"pid": product_id}).fetchone()
        return row[0] if row else "wac"

    @staticmethod
    def create_cost_layer(
        db,
        product_id: int,
        warehouse_id: int,
        quantity,
        unit_cost,
        source_document_type: str,
        source_document_id: int,
        costing_method: str = "fifo",
    ) -> int:
        """Create a new cost layer on purchase receipt. Returns the layer ID."""
        qty = _dec(quantity)
        cost = _dec(unit_cost)
        row = db.execute(text("""
            INSERT INTO cost_layers
                (product_id, warehouse_id, costing_method, purchase_date, original_quantity,
                 remaining_quantity, unit_cost, source_document_type, source_document_id, is_exhausted)
            VALUES
                (:pid, :wid, :method, CURRENT_DATE, :qty, :qty, :cost, :sdt, :sdi, FALSE)
            RETURNING id
        """), {
            "pid": product_id, "wid": warehouse_id, "method": costing_method,
            "qty": str(qty), "cost": str(cost),
            "sdt": source_document_type, "sdi": source_document_id,
        })
        return row.scalar()

    @staticmethod
    def consume_layers(
        db,
        product_id: int,
        warehouse_id: int,
        quantity,
        sale_document_type: str,
        sale_document_id: int,
        costing_method: str = "fifo",
    ) -> Decimal:
        """
        Consume cost layers in FIFO (ASC) or LIFO (DESC) order.
        Returns total COGS for the consumed quantity.
        Raises ValueError if insufficient remaining quantity or available stock.
        """
        qty_remaining = _dec(quantity)

        # ── Constitution VIII: validate qty_available before consuming ──
        inv_row = db.execute(text("""
            SELECT quantity, reserved_quantity, available_quantity
            FROM inventory
            WHERE product_id = :pid AND warehouse_id = :wid
            FOR UPDATE
        """), {"pid": product_id, "wid": warehouse_id}).fetchone()

        if inv_row:
            on_hand = _dec(inv_row[0])
            reserved = _dec(inv_row[1])
            available = on_hand - reserved   # authoritative formula
            if qty_remaining > available:
                raise ValueError(
                    f"Insufficient available stock for product {product_id} in warehouse "
                    f"{warehouse_id}. Available: {available}, requested: {qty_remaining}."
                )
        # If no inventory row exists, layer check below will catch the shortfall.

        total_cogs = Decimal("0")
        order = "purchase_date ASC, id ASC" if costing_method == "fifo" else "purchase_date DESC, id DESC"

        layers = db.execute(text(f"""
            SELECT id, remaining_quantity, unit_cost
            FROM cost_layers
            WHERE product_id = :pid AND warehouse_id = :wid AND is_exhausted = FALSE
            ORDER BY {order}
            FOR UPDATE
        """), {"pid": product_id, "wid": warehouse_id}).fetchall()

        for layer in layers:
            if qty_remaining <= 0:
                break
            layer_id, layer_remaining, layer_cost = layer[0], _dec(layer[1]), _dec(layer[2])
            consume_qty = min(qty_remaining, layer_remaining)

            new_remaining = layer_remaining - consume_qty
            is_exhausted = new_remaining <= 0

            db.execute(text("""
                UPDATE cost_layers
                SET remaining_quantity = :rem, is_exhausted = :exh, updated_at = NOW()
                WHERE id = :id
            """), {"rem": str(new_remaining), "exh": is_exhausted, "id": layer_id})

            db.execute(text("""
                INSERT INTO cost_layer_consumptions
                    (cost_layer_id, quantity_consumed, sale_document_type, sale_document_id, consumed_at)
                VALUES (:lid, :qty, :sdt, :sdi, NOW())
            """), {"lid": layer_id, "qty": str(consume_qty), "sdt": sale_document_type, "sdi": sale_document_id})

            total_cogs += consume_qty * layer_cost
            qty_remaining -= consume_qty

        if qty_remaining > 0:
            raise ValueError(
                f"Insufficient cost layers for product {product_id} in warehouse {warehouse_id}. "
                f"Short by {qty_remaining} units."
            )

        return total_cogs

    @staticmethod
    def handle_return(
        db,
        product_id: int,
        warehouse_id: int,
        quantity,
        unit_cost,
        source_document_type: str,
        source_document_id: int,
        costing_method: str = "fifo",
        original_source_document_type: Optional[str] = None,
        original_source_document_id: Optional[int] = None,
    ) -> dict:
        """Reverse a goods movement against the **original** cost layer(s).

        Two scenarios:

        - **Purchase return** (returning goods to a supplier): the original
          purchase invoice produced one or more cost layers. We must reduce
          the *remaining quantity* of those layers — not create a fresh layer
          at an arbitrary cost — otherwise FIFO/LIFO valuation drifts and the
          inventory ends up double-counted (once in the original layer, once
          in a new bogus layer).

        - **Sales return** (customer returning goods to us): the original
          sale consumed cost layers. We bring back the consumed quantity by
          reversing the matching ``cost_layer_consumptions`` entries
          (newest-first, since the most recently consumed slice is the most
          likely to be returned). If we cannot match exact consumptions we
          fall back to creating a new layer at ``unit_cost``.

        Pass ``original_source_document_type`` / ``original_source_document_id``
        pointing at the *original* movement (e.g. the purchase invoice for a
        purchase return, the sales invoice for a sales return). When omitted
        the helper falls back to the legacy "create a new layer" behaviour
        for backwards compatibility, but call sites should always supply the
        original reference now.

        Returns a dict describing what changed:
            {"strategy": "reduce_layer"|"reverse_consumption"|"new_layer",
             "affected_layer_ids": [...], "new_layer_id": <id or None>}
        """
        qty = _dec(quantity)
        if qty <= 0:
            return {"strategy": "noop", "affected_layer_ids": [], "new_layer_id": None}

        # Strategy 1: purchase return — reduce remaining_quantity on layers
        # produced by the original purchase document.
        if (
            original_source_document_type
            and original_source_document_id
            and original_source_document_type in ("purchase_invoice", "purchase", "purchase_order")
        ):
            layers = db.execute(text("""
                SELECT id, remaining_quantity
                FROM cost_layers
                WHERE product_id = :pid
                  AND warehouse_id = :wid
                  AND source_document_type = :sdt
                  AND source_document_id   = :sdi
                ORDER BY purchase_date DESC, id DESC
                FOR UPDATE
            """), {
                "pid": product_id, "wid": warehouse_id,
                "sdt": original_source_document_type,
                "sdi": original_source_document_id,
            }).fetchall()

            qty_left = qty
            affected = []
            for layer in layers:
                if qty_left <= 0:
                    break
                lid = layer[0]
                rem = _dec(layer[1])
                take = min(qty_left, rem)
                new_rem = rem - take
                db.execute(text("""
                    UPDATE cost_layers
                       SET remaining_quantity = :rem,
                           is_exhausted       = :exh,
                           updated_at         = NOW()
                     WHERE id = :id
                """), {"rem": str(new_rem), "exh": new_rem <= 0, "id": lid})
                affected.append(lid)
                qty_left -= take

            # If we fully reversed against the original layers, done.
            if qty_left <= 0:
                return {
                    "strategy": "reduce_layer",
                    "affected_layer_ids": affected,
                    "new_layer_id": None,
                }
            # Otherwise the original layers were already consumed by sales.
            # Fall through to consume FIFO/LIFO as a real outflow so the
            # inventory valuation still drops by the returned qty.
            try:
                CostingService.consume_layers(
                    db,
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity=qty_left,
                    sale_document_type=source_document_type,
                    sale_document_id=source_document_id,
                    costing_method=costing_method,
                )
                return {
                    "strategy": "reduce_layer+consume_overflow",
                    "affected_layer_ids": affected,
                    "new_layer_id": None,
                }
            except ValueError:
                # Not enough stock at all — surface the error to the caller.
                raise

        # Strategy 2: sales return — reverse consumptions newest-first.
        if (
            original_source_document_type
            and original_source_document_id
            and original_source_document_type in ("sales_invoice", "invoice", "pos_sale")
        ):
            consumptions = db.execute(text("""
                SELECT clc.id, clc.cost_layer_id, clc.quantity_consumed,
                       cl.remaining_quantity, cl.original_quantity
                FROM cost_layer_consumptions clc
                JOIN cost_layers cl ON cl.id = clc.cost_layer_id
                WHERE clc.sale_document_type = :sdt
                  AND clc.sale_document_id   = :sdi
                  AND cl.product_id   = :pid
                  AND cl.warehouse_id = :wid
                ORDER BY clc.consumed_at DESC, clc.id DESC
                FOR UPDATE
            """), {
                "sdt": original_source_document_type,
                "sdi": original_source_document_id,
                "pid": product_id, "wid": warehouse_id,
            }).fetchall()

            qty_left = qty
            affected = []
            for c in consumptions:
                if qty_left <= 0:
                    break
                cid, lid, consumed = c[0], c[1], _dec(c[2])
                rem = _dec(c[3])
                give_back = min(qty_left, consumed)
                new_consumed = consumed - give_back
                if new_consumed <= 0:
                    db.execute(text("DELETE FROM cost_layer_consumptions WHERE id = :id"),
                               {"id": cid})
                else:
                    db.execute(text("""
                        UPDATE cost_layer_consumptions
                           SET quantity_consumed = :q, updated_at = NOW()
                         WHERE id = :id
                    """), {"q": str(new_consumed), "id": cid})
                # Restore the layer's remaining_quantity
                db.execute(text("""
                    UPDATE cost_layers
                       SET remaining_quantity = remaining_quantity + :q,
                           is_exhausted       = FALSE,
                           updated_at         = NOW()
                     WHERE id = :id
                """), {"q": str(give_back), "id": lid})
                affected.append(lid)
                qty_left -= give_back

            if qty_left <= 0:
                return {
                    "strategy": "reverse_consumption",
                    "affected_layer_ids": affected,
                    "new_layer_id": None,
                }
            # Could not reverse the full quantity from prior consumptions
            # (the original sale may not have used the layer system, e.g.
            # legacy data). Fall through to creating a fresh layer.

        # Legacy fallback: create a new cost layer at the supplied unit_cost.
        new_layer_id = CostingService.create_cost_layer(
            db, product_id, warehouse_id, qty, unit_cost,
            source_document_type, source_document_id, costing_method,
        )
        return {
            "strategy": "new_layer",
            "affected_layer_ids": [],
            "new_layer_id": new_layer_id,
        }

    @staticmethod
    def get_cost_layers(db, product_id=None, warehouse_id=None, include_exhausted=False, branch_id=None, branch_ids=None):
        """Get cost layers with optional filters."""
        conditions = ["1=1"]
        params = {}
        if product_id:
            conditions.append("cl.product_id = :pid")
            params["pid"] = product_id
        if warehouse_id:
            conditions.append("cl.warehouse_id = :wid")
            params["wid"] = warehouse_id
        elif branch_id:
            conditions.append("w.branch_id = :branch_id")
            params["branch_id"] = branch_id
        elif branch_ids is not None:
            if branch_ids:
                conditions.append("w.branch_id = ANY(:branch_ids)")
                params["branch_ids"] = branch_ids
            else:
                conditions.append("1=0")
        if not include_exhausted:
            conditions.append("cl.is_exhausted = FALSE")

        return db.execute(text(f"""
            SELECT cl.id, cl.product_id, cl.warehouse_id, cl.costing_method,
                   cl.purchase_date, cl.original_quantity, cl.remaining_quantity,
                   cl.unit_cost, cl.source_document_type, cl.source_document_id,
                   cl.is_exhausted, cl.created_at, cl.updated_at,
                   p.product_name as product_name, w.warehouse_name as warehouse_name
            FROM cost_layers cl
            LEFT JOIN products p ON p.id = cl.product_id
            LEFT JOIN warehouses w ON w.id = cl.warehouse_id
            WHERE {' AND '.join(conditions)}
            ORDER BY cl.purchase_date DESC, cl.id DESC
        """), params).fetchall()

    @staticmethod
    def change_costing_method(db, product_id: int, warehouse_id: Optional[int], new_method: str, user_id: str):
        """
        Change costing method for a product. Creates an opening layer consolidating
        remaining inventory at current average cost.
        """
        conditions = ["product_id = :pid", "is_exhausted = FALSE"]
        params = {"pid": product_id}
        if warehouse_id:
            conditions.append("warehouse_id = :wid")
            params["wid"] = warehouse_id

        # Sum up remaining inventory from existing layers
        agg = db.execute(text(f"""
            SELECT COALESCE(SUM(remaining_quantity), 0) as total_qty,
                   CASE WHEN SUM(remaining_quantity) > 0
                        THEN SUM(remaining_quantity * unit_cost) / SUM(remaining_quantity)
                        ELSE 0 END as avg_cost
            FROM cost_layers
            WHERE {' AND '.join(conditions)}
        """), params).fetchone()

        total_qty = _dec(agg[0])
        avg_cost = _dec(agg[1])

        # If no existing layers, check inventory/product cost
        if total_qty <= 0:
            if warehouse_id:
                inv = db.execute(text(
                    "SELECT quantity, average_cost FROM inventory WHERE product_id = :pid AND warehouse_id = :wid"
                ), {"pid": product_id, "wid": warehouse_id}).fetchone()
                if inv:
                    total_qty = _dec(inv[0])
                    avg_cost = _dec(inv[1])
            if total_qty <= 0:
                prod = db.execute(text(
                    "SELECT cost_price FROM products WHERE id = :pid"
                ), {"pid": product_id}).fetchone()
                avg_cost = _dec(prod[0]) if prod else Decimal("0")

        # Mark all existing layers as exhausted
        db.execute(text(f"""
            UPDATE cost_layers SET is_exhausted = TRUE, remaining_quantity = 0, updated_at = NOW()
            WHERE {' AND '.join(conditions)}
        """), params)

        # Create opening layer with new method if there's inventory
        opening_layer_id = None
        if total_qty > 0:
            wh = warehouse_id or db.execute(text(
                "SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1"
            )).scalar() or 1
            opening_layer_id = CostingService.create_cost_layer(
                db, product_id, wh, total_qty, avg_cost,
                "method_change", 0, new_method,
            )

        return {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "new_method": new_method,
            "opening_quantity": float(total_qty),
            "opening_unit_cost": float(avg_cost),
            "opening_layer_id": opening_layer_id,
        }

    @staticmethod
    def calculate_inventory_valuation(db, as_of_date=None, warehouse_id=None, branch_id=None, branch_ids=None):
        """Calculate inventory valuation grouped by product and costing method."""
        date_filter = ""
        params = {}
        scope_filter = ""
        if as_of_date:
            date_filter = "AND cl.purchase_date <= :cutoff"
            params["cutoff"] = str(as_of_date)
        if warehouse_id:
            scope_filter += " AND cl.warehouse_id = :warehouse_id"
            params["warehouse_id"] = warehouse_id
        elif branch_id:
            scope_filter += " AND w.branch_id = :branch_id"
            params["branch_id"] = branch_id
        elif branch_ids is not None:
            if branch_ids:
                scope_filter += " AND w.branch_id = ANY(:branch_ids)"
                params["branch_ids"] = branch_ids
            else:
                scope_filter += " AND 1=0"

        rows = db.execute(text(f"""
            SELECT cl.product_id, p.product_name as product_name, cl.costing_method,
                   SUM(cl.remaining_quantity) as total_quantity,
                   SUM(cl.remaining_quantity * cl.unit_cost) as total_value,
                   CASE WHEN SUM(cl.remaining_quantity) > 0
                        THEN SUM(cl.remaining_quantity * cl.unit_cost) / SUM(cl.remaining_quantity)
                        ELSE 0 END as weighted_avg_cost
            FROM cost_layers cl
            JOIN products p ON p.id = cl.product_id
            LEFT JOIN warehouses w ON w.id = cl.warehouse_id
            WHERE cl.is_exhausted = FALSE {date_filter} {scope_filter}
            GROUP BY cl.product_id, p.product_name, cl.costing_method
            HAVING SUM(cl.remaining_quantity) > 0
            ORDER BY p.product_name
        """), params).fetchall()

        items = []
        grand_total = Decimal("0")
        for r in rows:
            val = _dec(r[4])
            items.append({
                "product_id": r[0],
                "product_name": r[1],
                "costing_method": r[2],
                "total_quantity": float(_dec(r[3])),
                "total_value": float(val),
                "weighted_avg_cost": float(_dec(r[5])),
            })
            grand_total += val

        return {
            "as_of_date": str(as_of_date or "current"),
            "items": items,
            "grand_total": float(grand_total),
        }

    @staticmethod
    def get_consumption_history(db, product_id: int, warehouse_id=None, branch_id=None, branch_ids=None):
        """Get consumption history for a product's cost layers."""
        filters = ["cl.product_id = :pid"]
        params = {"pid": product_id}
        if warehouse_id:
            filters.append("cl.warehouse_id = :warehouse_id")
            params["warehouse_id"] = warehouse_id
        elif branch_id:
            filters.append("w.branch_id = :branch_id")
            params["branch_id"] = branch_id
        elif branch_ids is not None:
            if branch_ids:
                filters.append("w.branch_id = ANY(:branch_ids)")
                params["branch_ids"] = branch_ids
            else:
                filters.append("1=0")
        return db.execute(text("""
            SELECT clc.id, clc.cost_layer_id, clc.quantity_consumed,
                   clc.sale_document_type, clc.sale_document_id, clc.consumed_at,
                   cl.unit_cost, cl.costing_method, cl.purchase_date
            FROM cost_layer_consumptions clc
            JOIN cost_layers cl ON cl.id = clc.cost_layer_id
            LEFT JOIN warehouses w ON w.id = cl.warehouse_id
            WHERE """ + " AND ".join(filters) + """
            ORDER BY clc.consumed_at DESC
        """), params).fetchall()
