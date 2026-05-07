"""
T6.2 — Invoice repository.

Wraps all raw SQL for the ``invoices`` table behind a clean class API so
routers never touch ``db.execute(text(…))`` directly for invoice CRUD.

Only the methods wired up in the three priority routers are included here.
Other routers can import and use the same repo; new methods can be added
incrementally following the same pattern.
"""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy import text


class InvoiceRepository:
    def __init__(self, db):
        self._db = db

    # ── Queries ────────────────────────────────────────────────────────────────

    def list(
        self,
        *,
        invoice_type: Optional[str] = None,
        party_id: Optional[int] = None,
        status: Optional[str] = None,
        branch_id: Optional[int] = None,
        branch_ids: Optional[list[int]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return a list of invoice rows, optionally filtered."""
        where = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if invoice_type:
            where.append("i.invoice_type = :invoice_type")
            params["invoice_type"] = invoice_type
        if party_id:
            where.append("i.party_id = :party_id")
            params["party_id"] = party_id
        if status:
            where.append("i.status = :status")
            params["status"] = status
        if branch_id:
            where.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id
        elif branch_ids is not None:
            if branch_ids:
                where.append("i.branch_id = ANY(:branch_ids)")
                params["branch_ids"] = branch_ids
            else:
                where.append("1=0")

        sql = f"""
            SELECT i.id,
                   i.invoice_number,
                   i.invoice_type,
                   i.invoice_date,
                   i.total,
                   i.paid_amount,
                   i.status,
                   i.currency,
                   i.exchange_rate,
                   i.party_id,
                   p.name AS party_name
              FROM invoices i
         LEFT JOIN parties p ON i.party_id = p.id
             WHERE {' AND '.join(where)}
          ORDER BY i.invoice_date DESC, i.id DESC
             LIMIT :limit OFFSET :offset
        """
        rows = self._db.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_by_id(self, invoice_id: int) -> Optional[dict]:
        """Return a single invoice with joined party name, or None."""
        row = self._db.execute(
            text("""
                SELECT i.*,
                       p.name          AS party_name,
                       p.party_code    AS party_code,
                       p.tax_number    AS party_tax_number
                  FROM invoices i
             LEFT JOIN parties p ON i.party_id = p.id
                 WHERE i.id = :id
            """),
            {"id": invoice_id},
        ).fetchone()
        return dict(row._mapping) if row else None

    def get_by_number(self, invoice_number: str) -> Optional[dict]:
        row = self._db.execute(
            text("SELECT * FROM invoices WHERE invoice_number = :num"),
            {"num": invoice_number},
        ).fetchone()
        return dict(row._mapping) if row else None

    def count(
        self,
        *,
        invoice_type: Optional[str] = None,
        status: Optional[str] = None,
        branch_id: Optional[int] = None,
    ) -> int:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if invoice_type:
            where.append("invoice_type = :invoice_type")
            params["invoice_type"] = invoice_type
        if status:
            where.append("status = :status")
            params["status"] = status
        if branch_id:
            where.append("branch_id = :branch_id")
            params["branch_id"] = branch_id
        sql = f"SELECT COUNT(*) FROM invoices WHERE {' AND '.join(where)}"
        return int(self._db.execute(text(sql), params).scalar() or 0)

    def sum_total(
        self,
        *,
        invoice_type: Optional[str] = None,
        status_not: Optional[str] = None,
        branch_id: Optional[int] = None,
    ) -> float:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if invoice_type:
            where.append("invoice_type = :invoice_type")
            params["invoice_type"] = invoice_type
        if status_not:
            where.append("status != :status_not")
            params["status_not"] = status_not
        if branch_id:
            where.append("branch_id = :branch_id")
            params["branch_id"] = branch_id
        sql = f"SELECT COALESCE(SUM(total * exchange_rate), 0) FROM invoices WHERE {' AND '.join(where)}"
        return float(self._db.execute(text(sql), params).scalar() or 0)

    # ── Mutations ──────────────────────────────────────────────────────────────

    def insert(self, data: dict) -> int:
        """Insert a new invoice row and return its id."""
        keys = list(data.keys())
        cols = ", ".join(keys)
        vals = ", ".join(f":{k}" for k in keys)
        row = self._db.execute(
            text(f"INSERT INTO invoices ({cols}) VALUES ({vals}) RETURNING id"),
            data,
        ).fetchone()
        return int(row[0])

    def update(self, invoice_id: int, data: dict) -> None:
        """Update specific columns of an invoice."""
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["_id"] = invoice_id
        self._db.execute(
            text(f"UPDATE invoices SET {set_clause} WHERE id = :_id"),
            data,
        )

    def update_status(self, invoice_id: int, status: str) -> None:
        self._db.execute(
            text("UPDATE invoices SET status = :s, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"s": status, "id": invoice_id},
        )

    def update_paid_amount(self, invoice_id: int, paid_amount: float) -> None:
        self._db.execute(
            text("""
                UPDATE invoices
                   SET paid_amount = :amt,
                       status = CASE
                           WHEN :amt >= total THEN 'paid'
                           WHEN :amt > 0 THEN 'partial'
                           ELSE status
                       END,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id
            """),
            {"amt": paid_amount, "id": invoice_id},
        )

    def delete(self, invoice_id: int) -> None:
        self._db.execute(
            text("DELETE FROM invoices WHERE id = :id"),
            {"id": invoice_id},
        )

    # ── Line items ─────────────────────────────────────────────────────────────

    def get_lines(self, invoice_id: int) -> list[dict]:
        rows = self._db.execute(
            text("""
                SELECT il.*,
                       p.product_name,
                       p.product_code,
                       p.unit_of_measure
                  FROM invoice_lines il
             LEFT JOIN products p ON il.product_id = p.id
                 WHERE il.invoice_id = :id
                 ORDER BY il.id
            """),
            {"id": invoice_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def insert_line(self, data: dict) -> int:
        keys = list(data.keys())
        cols = ", ".join(keys)
        vals = ", ".join(f":{k}" for k in keys)
        row = self._db.execute(
            text(f"INSERT INTO invoice_lines ({cols}) VALUES ({vals}) RETURNING id"),
            data,
        ).fetchone()
        return int(row[0])

    def delete_lines(self, invoice_id: int) -> None:
        self._db.execute(
            text("DELETE FROM invoice_lines WHERE invoice_id = :id"),
            {"id": invoice_id},
        )
