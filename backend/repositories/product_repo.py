"""
T6.2 — Product/Inventory repository.

Wraps raw SQL for ``products`` and related inventory tables.
"""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy import text


class ProductRepository:
    def __init__(self, db):
        self._db = db

    # ── Queries ────────────────────────────────────────────────────────────────

    def list(
        self,
        *,
        category_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        branch_id: Optional[int] = None,
        branch_ids: Optional[list[int]] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        where = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if category_id:
            where.append("p.category_id = :category_id")
            params["category_id"] = category_id
        if is_active is not None:
            where.append("p.is_active = :is_active")
            params["is_active"] = is_active
        if search:
            # T10.1 P1 #110i — old query used ``ILIKE '%foo%'`` on both
            # ``product_name`` and ``product_code``, which forces a
            # sequential scan because the leading wildcard defeats the
            # default B-tree index. We now:
            #   • match ``product_code`` as a prefix (anchored ILIKE
            #     ``'foo%'``) so it can use the B-tree index on the
            #     column, and
            #   • keep substring search on ``product_name`` but rely on
            #     the trigram (``pg_trgm``) GIN index created in
            #     ``db_ddl/tenant_schema.py`` for #110i.
            where.append(
                "(p.product_name ILIKE :q_contains OR p.product_code ILIKE :q_prefix)"
            )
            params["q_contains"] = f"%{search}%"
            params["q_prefix"] = f"{search}%"

        inv_join = ""
        if branch_id:
            inv_join = """
                LEFT JOIN (
                    SELECT inv.product_id,
                           SUM(inv.quantity) AS stock_qty,
                           SUM(COALESCE(inv.reserved_quantity, 0)) AS reserved_qty,
                           SUM(COALESCE(inv.damaged_quantity, 0)) AS damaged_qty,
                           SUM(COALESCE(inv.available_quantity, inv.quantity - COALESCE(inv.reserved_quantity, 0) - COALESCE(inv.damaged_quantity, 0))) AS available_qty,
                           CASE WHEN SUM(inv.quantity) > 0 THEN
                               SUM(inv.average_cost * inv.quantity) / SUM(inv.quantity)
                           ELSE 0 END AS avg_cost
                      FROM inventory inv
                      JOIN warehouses w ON inv.warehouse_id = w.id
                     WHERE w.branch_id = :branch_id
                     GROUP BY inv.product_id
                ) inv_sum ON p.id = inv_sum.product_id
            """
            params["branch_id"] = branch_id
        elif branch_ids is not None:
            if branch_ids:
                inv_join = """
                    LEFT JOIN (
                        SELECT inv.product_id,
                               SUM(inv.quantity) AS stock_qty,
                               SUM(COALESCE(inv.reserved_quantity, 0)) AS reserved_qty,
                               SUM(COALESCE(inv.damaged_quantity, 0)) AS damaged_qty,
                               SUM(COALESCE(inv.available_quantity, inv.quantity - COALESCE(inv.reserved_quantity, 0) - COALESCE(inv.damaged_quantity, 0))) AS available_qty,
                               CASE WHEN SUM(inv.quantity) > 0 THEN
                                   SUM(inv.average_cost * inv.quantity) / SUM(inv.quantity)
                               ELSE 0 END AS avg_cost
                          FROM inventory inv
                          JOIN warehouses w ON inv.warehouse_id = w.id
                         WHERE w.branch_id = ANY(:branch_ids)
                         GROUP BY inv.product_id
                    ) inv_sum ON p.id = inv_sum.product_id
                """
                params["branch_ids"] = branch_ids
            else:
                inv_join = """
                    LEFT JOIN (
                        SELECT inv.product_id,
                               SUM(inv.quantity) AS stock_qty,
                               SUM(COALESCE(inv.reserved_quantity, 0)) AS reserved_qty,
                               SUM(COALESCE(inv.damaged_quantity, 0)) AS damaged_qty,
                               SUM(COALESCE(inv.available_quantity, 0)) AS available_qty,
                               CASE WHEN SUM(inv.quantity) > 0 THEN
                                   SUM(inv.average_cost * inv.quantity) / SUM(inv.quantity)
                               ELSE 0 END AS avg_cost
                          FROM inventory inv
                         WHERE 1=0
                         GROUP BY inv.product_id
                    ) inv_sum ON p.id = inv_sum.product_id
                """
        else:
            inv_join = """
                LEFT JOIN (
                    SELECT product_id,
                           SUM(quantity) AS stock_qty,
                           SUM(COALESCE(reserved_quantity, 0)) AS reserved_qty,
                           SUM(COALESCE(damaged_quantity, 0)) AS damaged_qty,
                           SUM(COALESCE(available_quantity, quantity - COALESCE(reserved_quantity, 0) - COALESCE(damaged_quantity, 0))) AS available_qty,
                           CASE WHEN SUM(quantity) > 0 THEN
                               SUM(average_cost * quantity) / SUM(quantity)
                           ELSE 0 END AS avg_cost
                      FROM inventory
                     GROUP BY product_id
                ) inv_sum ON p.id = inv_sum.product_id
            """

        sql = f"""
            SELECT p.*,
                   COALESCE(inv_sum.stock_qty, 0) AS current_stock,
                   COALESCE(inv_sum.reserved_qty, 0) AS reserved_quantity,
                   COALESCE(inv_sum.damaged_qty, 0) AS damaged_quantity,
                   COALESCE(inv_sum.available_qty, 0) AS available_stock,
                   COALESCE(inv_sum.avg_cost, p.cost_price, 0) AS branch_avg_cost
              FROM products p
              {inv_join}
             WHERE {' AND '.join(where)}
          ORDER BY p.product_name
             LIMIT :limit OFFSET :offset
        """
        rows = self._db.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_by_id(self, product_id: int) -> Optional[dict]:
        row = self._db.execute(
            text("""
                SELECT p.*,
                       c.category_name,
                       COALESCE(inv_sum.stock_qty, 0) AS current_stock
                  FROM products p
             LEFT JOIN product_categories c ON p.category_id = c.id
             LEFT JOIN (
                    SELECT product_id, SUM(quantity) AS stock_qty
                      FROM inventory GROUP BY product_id
                ) inv_sum ON p.id = inv_sum.product_id
                 WHERE p.id = :id
            """),
            {"id": product_id},
        ).fetchone()
        return dict(row._mapping) if row else None

    def get_by_code(self, product_code: str) -> Optional[dict]:
        row = self._db.execute(
            text("SELECT * FROM products WHERE product_code = :code"),
            {"code": product_code},
        ).fetchone()
        return dict(row._mapping) if row else None

    def get_stock(self, product_id: int, *, warehouse_id: Optional[int] = None) -> float:
        if warehouse_id:
            val = self._db.execute(
                text("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE product_id=:pid AND warehouse_id=:wid"),
                {"pid": product_id, "wid": warehouse_id},
            ).scalar()
        else:
            val = self._db.execute(
                text("SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE product_id=:pid"),
                {"pid": product_id},
            ).scalar()
        return float(val or 0)

    def list_low_stock(self, *, branch_id: Optional[int] = None) -> list[dict]:
        branch_join = ""
        branch_where = ""
        params: dict[str, Any] = {}
        if branch_id:
            branch_join = "JOIN warehouses w ON inv.warehouse_id = w.id"
            branch_where = "AND w.branch_id = :branch_id"
            params["branch_id"] = branch_id
        rows = self._db.execute(
            text(f"""
                SELECT p.id,
                       p.product_name,
                       p.product_code,
                       p.reorder_level,
                       COALESCE(inv_sum.qty, 0) AS current_stock
                  FROM products p
             LEFT JOIN (
                    SELECT inv.product_id, SUM(inv.quantity) AS qty
                      FROM inventory inv
                      {branch_join}
                     WHERE 1=1 {branch_where}
                     GROUP BY inv.product_id
                ) inv_sum ON p.id = inv_sum.product_id
                 WHERE COALESCE(inv_sum.qty, 0) <= p.reorder_level
                 ORDER BY (COALESCE(inv_sum.qty, 0) - p.reorder_level)
            """),
            params,
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    # ── Mutations ──────────────────────────────────────────────────────────────

    def insert(self, data: dict) -> int:
        keys = list(data.keys())
        cols = ", ".join(keys)
        vals = ", ".join(f":{k}" for k in keys)
        row = self._db.execute(
            text(f"INSERT INTO products ({cols}) VALUES ({vals}) RETURNING id"),
            data,
        ).fetchone()
        return int(row[0])

    def update(self, product_id: int, data: dict) -> None:
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["_id"] = product_id
        self._db.execute(
            text(f"UPDATE products SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id = :_id"),
            data,
        )

    def adjust_stock(
        self,
        product_id: int,
        warehouse_id: int,
        delta: float,
        *,
        reserved_delta: float = 0,
    ) -> None:
        """Atomically adjust quantity (and optional reserved) in inventory row."""
        self._db.execute(
            text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, reserved_quantity)
                VALUES (:pid, :wid, :delta, :rdelta)
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET
                    quantity          = inventory.quantity + EXCLUDED.quantity,
                    reserved_quantity = inventory.reserved_quantity + EXCLUDED.reserved_quantity,
                    updated_at        = CURRENT_TIMESTAMP
            """),
            {"pid": product_id, "wid": warehouse_id, "delta": delta, "rdelta": reserved_delta},
        )
