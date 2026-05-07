"""T170: Adapter health contract — uniform health_check() interface."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AdapterHealth:
    status: str  # ok | degraded | down
    latency_ms: float
    last_success_at: datetime | None = None
    last_error: str | None = None


async def check_adapter_health(adapter_name: str, check_fn: Any) -> dict[str, Any]:
    """Run a health check and return standardized result.

    Args:
        adapter_name: Name of the adapter.
        check_fn: Async callable that returns True if healthy.

    Returns:
        Dict with status, latency_ms, last_success_at, last_error.
    """
    start = time.monotonic()
    try:
        healthy = await check_fn() if check_fn else True
        latency = (time.monotonic() - start) * 1000
        return {
            "status": "ok" if healthy else "down",
            "latency_ms": round(latency, 2),
            "last_success_at": datetime.utcnow().isoformat() if healthy else None,
            "last_error": None if healthy else "Check returned false",
        }
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return {
            "status": "down",
            "latency_ms": round(latency, 2),
            "last_success_at": None,
            "last_error": str(exc)[:200],
        }
