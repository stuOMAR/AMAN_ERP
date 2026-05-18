"""
AMAN ERP — Fiscal Period Lock
قفل الفترة المحاسبية — منع إدخال قيود في فترة مقفلة
"""

from fastapi import HTTPException
from sqlalchemy import text
from datetime import datetime
import logging

from utils.i18n import http_error

logger = logging.getLogger(__name__)


def check_fiscal_period_open(db, entry_date, raise_error=True, request=None):
    """
    Check if a fiscal period is open for the given date.
    Used as a utility function called from endpoints that create journal entries.

    T3.3 (audit #17): unified single source of truth. The function honours
    BOTH legacy guard tables — `fiscal_period_locks` (admin lock list with
    locked_at/locked_by audit trail) and `fiscal_periods.is_closed` (year-
    end close lifecycle). A date is open only when neither table marks it
    as locked / closed.

    Returns True if open, False if locked.
    Raises HTTPException(400) if locked and raise_error=True.
    """
    if isinstance(entry_date, str):
        entry_date = datetime.strptime(entry_date[:10], "%Y-%m-%d").date()

    try:
        # 1. Admin lock table — fiscal_period_locks
        locked = db.execute(text("""
            SELECT id, period_name, locked_at, locked_by
            FROM fiscal_period_locks
            WHERE :entry_date BETWEEN period_start AND period_end
            AND is_locked = true
            FOR UPDATE
            LIMIT 1
        """), {"entry_date": entry_date}).fetchone()

        if locked:
            if raise_error:
                locked_date = locked.locked_at.strftime("%Y-%m-%d") if locked.locked_at else "—"
                raise HTTPException(**http_error(400, "fiscal_period_locked", request, name=locked.period_name))
            return False

        # 2. Year-end closed period — fiscal_periods.is_closed
        # Wrapped in its own try/except so a missing legacy table doesn't
        # break tenants that only use fiscal_period_locks.
        try:
            closed = db.execute(text("""
                SELECT id, name
                FROM fiscal_periods
                WHERE :entry_date BETWEEN start_date AND end_date
                AND is_closed = TRUE
                LIMIT 1
            """), {"entry_date": entry_date}).fetchone()
        except Exception as e2:
            err2 = str(e2).lower()
            if "does not exist" in err2 or "undefinedtable" in err2:
                closed = None
            else:
                raise

        if closed:
            if raise_error:
                raise HTTPException(**http_error(400, "fiscal_period_closed_post", request, name=closed.name))
            return False

        return True

    except HTTPException:
        raise
    except Exception as e:
        # ACC-FIX-02 (P1): fail-safe behaviour when the fiscal_period_locks
        # table is unavailable. Previously this path silently allowed all
        # dates — letting a corrupt/missing schema disable period locks.
        # Now we log a WARNING (not DEBUG) and allow the write, but callers
        # can opt into strict mode (default True when raise_error=True) to
        # block postings until the admin fixes the table.
        err_str = str(e).lower()
        table_missing = "does not exist" in err_str or "undefinedtable" in err_str
        if table_missing:
            # ACC-FIX-02 (P1): fail-closed — block postings when fiscal lock
            # infrastructure is missing. This prevents silent bypass of period locks.
            logger.error(
                "Fiscal period check BLOCKED: fiscal_period_locks table is missing. "
                "Run migrations to restore fiscal lock infrastructure. Error: %s",
                e,
            )
            if raise_error:
                raise HTTPException(**http_error(500, "fiscal_lock_check_failed", request))
            return False
        # Unexpected DB error — don't silently allow; fail closed.
        logger.error("Fiscal period check failed with unexpected error: %s", e)
        if raise_error:
            raise HTTPException(**http_error(500, "fiscal_lock_check_failed", request))
        return False


def create_fiscal_lock_table(db):
    """DEPRECATED (ACC-F2).

    The canonical schema for ``fiscal_period_locks`` lives in
    ``backend/database.py :: create_all_tables()`` (with full foreign-key
    constraints). This helper is kept as a no-op for backward compatibility
    with legacy callers (notably ``routers/system_completion.py``). It must
    not shadow the authoritative definition; if the table is somehow
    missing it is a bootstrap bug, not something this helper should silently
    paper over.
    """
    import logging as _lg
    _lg.getLogger(__name__).info(
        "create_fiscal_lock_table() is deprecated; fiscal_period_locks is "
        "created by database.create_all_tables()."
    )
    return None
