"""T172: Health router — /health/detailed endpoint.

Aggregates adapter health checks and returns per-adapter + aggregate status.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health/detailed")
async def health_detailed():
    """Detailed health check aggregating all adapters.

    Returns per-adapter status + aggregate. Critical adapters (db, redis, worker)
    map to overall 'down'; non-critical can be 'degraded'.
    """
    from adapters.health import get_all_adapter_health

    adapters = await get_all_adapter_health()

    # Determine aggregate status
    critical = {"db", "redis", "worker"}
    has_critical_down = any(
        a["status"] == "down" for name, a in adapters.items() if name in critical
    )
    has_any_down = any(a["status"] == "down" for a in adapters.values())
    has_any_degraded = any(a["status"] == "degraded" for a in adapters.values())

    if has_critical_down:
        aggregate = "down"
    elif has_any_down or has_any_degraded:
        aggregate = "degraded"
    else:
        aggregate = "ok"

    return {
        "status": aggregate,
        "adapters": adapters,
    }


@router.get("/health")
async def health_simple():
    """Simple health check (liveness probe)."""
    return {"status": "ok"}
