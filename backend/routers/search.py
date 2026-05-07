"""T141: Search router — /search/registry endpoint.

Extends existing search.py with the registry endpoint.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/registry")
async def get_search_registry():
    """Return the search entity registry.

    The frontend uses this to render cross-entity search results.
    """
    from services.search.registry import get_registry

    return {"entities": get_registry()}


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(20, ge=1, le=100),
):
    """Cross-entity search endpoint with query logging."""
    from services.search.registry import get_registry
    from services.search.logging import log_search_query
    from database import get_tenant_db

    start = time.monotonic()
    registry = get_registry()
    results = []
    entity_hits: dict[str, int] = {}

    for entity in registry:
        # Placeholder: actual search implementation per entity
        entity_results = {"entity": entity["entity_code"], "items": [], "count": 0}
        results.append(entity_results)
        entity_hits[entity["entity_code"]] = 0

    latency_ms = int((time.monotonic() - start) * 1000)
    total_count = sum(r["count"] for r in results)

    # Log the query
    try:
        with get_tenant_db() as db:
            log_search_query(db, "", "", q, total_count, latency_ms, entity_hits)
    except Exception:
        pass

    return {
        "query": q,
        "results": results,
        "total_count": total_count,
        "latency_ms": latency_ms,
    }
