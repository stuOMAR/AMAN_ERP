"""
T6.2 — Employee repository.

Wraps raw SQL for the ``employees`` table and related HR queries.
"""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy import text


class EmployeeRepository:
    def __init__(self, db):
        self._db = db

    # ── Queries ────────────────────────────────────────────────────────────────

    def list(
        self,
        *,
        department_id: Optional[int] = None,
        branch_id: Optional[int] = None,
        status: Optional[str] = "active",
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        where = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if department_id:
            where.append("e.department_id = :department_id")
            params["department_id"] = department_id
        if branch_id:
            where.append("e.branch_id = :branch_id")
            params["branch_id"] = branch_id
        if status:
            where.append("e.status = :status")
            params["status"] = status
        if search:
            where.append("(e.first_name ILIKE :q OR e.last_name ILIKE :q OR e.employee_code ILIKE :q)")
            params["q"] = f"%{search}%"

        sql = f"""
            SELECT e.id,
                   e.employee_code,
                   e.first_name,
                   e.last_name,
                   e.email,
                   e.phone,
                   e.status,
                   e.salary,
                   e.housing_allowance,
                   e.transport_allowance,
                   e.other_allowances,
                   e.currency,
                   e.nationality,
                   e.hire_date,
                   e.termination_date,
                   e.branch_id,
                   e.department_id,
                   d.department_name
              FROM employees e
         LEFT JOIN departments d ON e.department_id = d.id
             WHERE {' AND '.join(where)}
          ORDER BY e.first_name, e.last_name
             LIMIT :limit OFFSET :offset
        """
        rows = self._db.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_by_id(self, employee_id: int) -> Optional[dict]:
        row = self._db.execute(
            text("""
                SELECT e.*,
                       d.department_name,
                       b.branch_name,
                       ep.position_name
                  FROM employees e
             LEFT JOIN departments d ON e.department_id = d.id
             LEFT JOIN branches b ON e.branch_id = b.id
             LEFT JOIN employee_positions ep ON e.position_id = ep.id
                 WHERE e.id = :id
            """),
            {"id": employee_id},
        ).fetchone()
        return dict(row._mapping) if row else None

    def get_by_number(self, employee_code: str) -> Optional[dict]:
        row = self._db.execute(
            text("SELECT * FROM employees WHERE employee_code = :code"),
            {"code": employee_code},
        ).fetchone()
        return dict(row._mapping) if row else None

    def count(
        self,
        *,
        status: Optional[str] = None,
        department_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> int:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if status:
            where.append("status = :status")
            params["status"] = status
        if department_id:
            where.append("department_id = :department_id")
            params["department_id"] = department_id
        if branch_id:
            where.append("branch_id = :branch_id")
            params["branch_id"] = branch_id
        sql = f"SELECT COUNT(*) FROM employees WHERE {' AND '.join(where)}"
        return int(self._db.execute(text(sql), params).scalar() or 0)

    def sum_salary(
        self,
        *,
        status: Optional[str] = "active",
        branch_id: Optional[int] = None,
    ) -> float:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if status:
            where.append("status = :status")
            params["status"] = status
        if branch_id:
            where.append("branch_id = :branch_id")
            params["branch_id"] = branch_id
        sql = f"SELECT COALESCE(SUM(salary),0) FROM employees WHERE {' AND '.join(where)}"
        return float(self._db.execute(text(sql), params).scalar() or 0)

    def get_unpaid_leave_days(self, employee_id: int) -> float:
        """Sum of unpaid leave days from leave_requests for this employee."""
        val = self._db.execute(
            text("""
                SELECT COALESCE(SUM(duration_days), 0)
                  FROM leave_requests
                 WHERE employee_id = :eid
                   AND leave_type = 'unpaid'
                   AND status = 'approved'
            """),
            {"eid": employee_id},
        ).scalar()
        return float(val or 0)

    # ── Mutations ──────────────────────────────────────────────────────────────

    def insert(self, data: dict) -> int:
        keys = list(data.keys())
        cols = ", ".join(keys)
        vals = ", ".join(f":{k}" for k in keys)
        row = self._db.execute(
            text(f"INSERT INTO employees ({cols}) VALUES ({vals}) RETURNING id"),
            data,
        ).fetchone()
        return int(row[0])

    def update(self, employee_id: int, data: dict) -> None:
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["_id"] = employee_id
        self._db.execute(
            text(f"UPDATE employees SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id = :_id"),
            data,
        )

    def update_status(self, employee_id: int, status: str) -> None:
        self._db.execute(
            text("UPDATE employees SET status=:s, updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
            {"s": status, "id": employee_id},
        )

    def terminate(
        self, employee_id: int, *, termination_date: str, termination_reason: str
    ) -> None:
        self._db.execute(
            text("""
                UPDATE employees
                   SET status = 'terminated',
                       termination_date = :td,
                       notes = COALESCE(notes || E'\n', '') || :tr,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id
            """),
            {"td": termination_date, "tr": termination_reason, "id": employee_id},
        )
