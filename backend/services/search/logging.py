"""T142: Search query logging — writes to search_query_logs with cleanup."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def log_search_query(
    db: Any,
    tenant_id: str,
    actor_id: str,
    query: str,
    result_count: int,
    latency_ms: int,
    entity_hits: dict[str, int],
) -> None:
    """Write a search query log entry.

    Args:
        db: Database connection.
        tenant_id: Tenant identifier.
        actor_id: User who performed the search.
        query: The search query string.
        result_count: Total number of results.
        latency_ms: Query latency in milliseconds.
        entity_hits: Dict of {entity_code: count}.
    """
    import json
    from sqlalchemy import text

    try:
        db.execute(
            text("""
                INSERT INTO search_query_logs
                    (tenant_id, actor_id, query, result_count, latency_ms, entity_hits)
                VALUES (:tid, :aid, :query, :count, :latency, :hits)
            """),
            {
                "tid": tenant_id,
                "aid": actor_id,
                "query": query[:256],
                "count": max(0, result_count),
                "latency": max(0, latency_ms),
                "hits": json.dumps(entity_hits),
            },
        )
        db.commit()
    except Exception as exc:
        logger.error("Failed to log search query: %s", exc)


def cleanup_old_logs(db: Any, retention_days: int = 90) -> int:
    """Delete search query logs older than retention_days.

    Returns number of deleted rows.
    """
    from sqlalchemy import text

    try:
        result = db.execute(
            text("DELETE FROM search_query_logs WHERE created_at < NOW() - INTERVAL ':days days'"),
            {"days": retention_days},
        )
        db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old search query logs", deleted)
        return deleted
    except Exception as exc:
        logger.error("Search log cleanup failed: %s", exc)
        return 0
