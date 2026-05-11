"""
Optimistic Locking Utility.

Provides helpers for version-checked UPDATE operations to prevent
lost updates when two users edit the same record concurrently.

Usage:
    from utils.optimistic_lock import optimistic_update

    result = optimistic_update(
        conn, "assets",
        record_id=asset_id,
        expected_version=data.version,
        set_clause="name = :name, cost = :cost",
        params={"name": "X", "cost": 100},
        extra_where="AND status != 'disposed'",
    )
    # result is the updated row with new version, or raises 409
"""

from fastapi import HTTPException
from sqlalchemy import text

from utils.i18n import http_error


def optimistic_update(
    conn,
    table: str,
    *,
    record_id: int,
    expected_version: int,
    set_clause: str,
    params: dict,
    extra_where: str = "",
    id_column: str = "id",
    request=None,
) -> int:
    """Execute a version-checked UPDATE and return the new version.

    Raises:
        HTTPException 404 — record not found
        HTTPException 409 — version conflict (concurrent edit detected)
    """
    params = {**params, "_id": record_id, "_ver": expected_version}

    sql = text( # noqa: sql-lint
        f"UPDATE {table} SET {set_clause}, version = version + 1 "
        f"WHERE {id_column} = :_id AND version = :_ver {extra_where} "
        f"RETURNING version"
    )

    row = conn.execute(sql, params).fetchone()
    if row is None:
        # Distinguish 404 vs 409
        exists = conn.execute(
            text(f"SELECT version FROM {table} WHERE {id_column} = :_id"), # noqa: sql-lint
            {"_id": record_id},
        ).fetchone()
        if exists is None:
            raise HTTPException(**http_error(404, "record_not_found", request))
        raise HTTPException(**http_error(409, "record_changed_reload", request))
    return row.version
