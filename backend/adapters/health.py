"""T171: Adapter health registry — all adapters with health checks."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Adapter name -> check function
_ADAPTERS: dict[str, Callable[[], Awaitable[bool]]] = {}


def register_adapter(name: str, check_fn: Callable[[], Awaitable[bool]]) -> None:
    """Register an adapter health check."""
    _ADAPTERS[name] = check_fn


async def get_all_adapter_health() -> dict[str, dict[str, Any]]:
    """Run all registered adapter health checks."""
    from services.health.adapter import check_adapter_health

    results = {}
    for name, check_fn in _ADAPTERS.items():
        results[name] = await check_adapter_health(name, check_fn)
    return results


# ── Register built-in adapters ───────────────────────────────────────────

async def _check_db() -> bool:
    """Check database connectivity."""
    try:
        from database import get_db
        from sqlalchemy import text
        db = next(get_db())
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    """Check Redis connectivity."""
    try:
        from utils.cache import cache
        cache.set("_health_check", "1", expire=5)
        return cache.get("_health_check") == "1"
    except Exception:
        return False


async def _check_worker() -> bool:
    """Check worker is running."""
    # Placeholder — in production, check scheduler heartbeat
    return True


# Auto-register built-in adapters
register_adapter("db", _check_db)
register_adapter("redis", _check_redis)
register_adapter("worker", _check_worker)
