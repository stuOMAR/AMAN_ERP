"""
T6.1 — Unified transactional context manager.

Provides a single, consistent surface for DB access across all routers so
that the repeated ``try/except/finally db.close()`` boilerplate is replaced
with a single ``with transactional(company_id) as db:`` block.

Design:
  * Opens a SQLAlchemy connection via :func:`database.get_db_connection`.
  * On clean exit → commits.
  * On any exception → rolls back, then re-raises so FastAPI can still
    turn it into an HTTP response.
  * Always closes the connection — even after re-raise.
  * Nested usage is safe: the inner `with` re-uses the same connection
    when the caller already holds one (pass ``db=existing_conn``).

Usage::

    from utils.tx import transactional

    @router.get("/items")
    def list_items(company_id = Depends(get_current_user_company)):
        with transactional(company_id) as db:
            rows = db.execute(text("SELECT ...")).fetchall()
            return [dict(r._mapping) for r in rows]

    # Re-use existing connection (no extra commit/rollback):
    def _inner_helper(db):
        db.execute(text("INSERT ..."), {...})

    @router.post("/items")
    def create_item(...):
        with transactional(company_id) as db:
            _inner_helper(db)
            # commit happens automatically at block exit

For backwards-compatible routers that already manually manage ``db``,
the context manager is purely opt-in — nothing forces adoption.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

from sqlalchemy.orm import Session

from database import get_db_connection

logger = logging.getLogger(__name__)


@contextmanager
def transactional(company_id: str, *, existing_db=None):
    """Context manager that wraps a DB session in an atomic transaction.

    If *existing_db* is provided the caller already owns the session — this
    manager becomes a no-op wrapper (no commit/rollback/close) to allow safe
    nesting without double-commit.
    """
    if existing_db is not None:
        # Nested / shared usage — yield the existing connection as-is.
        yield existing_db
        return

    db = get_db_connection(company_id)
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("[tx] rollback failed for company=%s", company_id)
        raise
    finally:
        try:
            db.close()
        except Exception:
            logger.exception("[tx] close failed for company=%s", company_id)


__all__ = ["transactional"]
