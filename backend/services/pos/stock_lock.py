"""POS per-warehouse stock lock — Redis primary, pg_advisory fallback.

Feature 023 — T045.  Contract: contracts/pos-stock-lock.md
"""
from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

LOCK_TTL_MS = 5000  # 5 seconds default
LOCK_RETRY_MS = 200
LOCK_MAX_WAIT_S = 5


class PosLockTimeout(Exception):
    def __init__(self, tenant_id: int, warehouse_id: int):
        self.tenant_id = tenant_id
        self.warehouse_id = warehouse_id
        super().__init__(f"Could not acquire POS lock for tenant={tenant_id}, warehouse={warehouse_id}")


def _lock_key(tenant_id: int, warehouse_id: int) -> str:
    return f"pos:lock:{tenant_id}:{warehouse_id}"


def _advisory_key(tenant_id: int, warehouse_id: int) -> int:
    """Generate a deterministic int64 for pg_advisory_xact_lock."""
    h = hashlib.sha256(f"{tenant_id}:{warehouse_id}".encode()).digest()
    return int.from_bytes(h[:8], "big", signed=True)


@contextmanager
def pos_stock_lock(db: Any, tenant_id: int, warehouse_id: int, *, ttl: int | None = None):
    """Context manager that acquires a per-warehouse lock for POS operations.

    Tries Redis SET NX PX first; falls back to pg_advisory_xact_lock.
    """
    ttl_ms = ttl or LOCK_TTL_MS
    lock_key = _lock_key(tenant_id, warehouse_id)
    acquired = False
    start = time.monotonic()

    # Try Redis
    try:
        import redis as redis_lib
        from config import settings
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        deadline = start + LOCK_MAX_WAIT_S
        while time.monotonic() < deadline:
            if r.set(lock_key, "1", nx=True, px=ttl_ms):
                acquired = True
                break
            time.sleep(LOCK_RETRY_MS / 1000)

        if not acquired:
            raise PosLockTimeout(tenant_id, warehouse_id)

        try:
            yield
        finally:
            # Safe release via Lua
            lua = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                r.eval(lua, 1, lock_key, "1")
            except Exception:
                pass
            r.close()
            return

    except ImportError:
        pass  # Redis not available, fall through to DB
    except PosLockTimeout:
        raise
    except Exception:
        logger.warning("Redis lock failed, falling back to pg_advisory", exc_info=True)

    # Fallback: pg_advisory_xact_lock
    from sqlalchemy import text
    adv_key = _advisory_key(tenant_id, warehouse_id)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": adv_key})
    try:
        yield
    finally:
        pass  # Advisory lock releases at transaction end
