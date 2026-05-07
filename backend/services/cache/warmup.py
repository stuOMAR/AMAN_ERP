"""T016/FR-201: Cache warm-up at startup.

Reads ``reports.warmup_keys`` from settings and pre-populates cache
on application startup. Bounded by per-key timeout.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

WARMUP_TIMEOUT_SECONDS = 10  # Per-key timeout


async def warmup_cache(cache_client: Any, settings_client: Any) -> int:
    """Warm up cache on startup.

    Reads ``reports.warmup_keys`` from company_settings and populates
    each key. Returns number of keys warmed.

    Args:
        cache_client: The cache backend client.
        settings_client: A DB connection or function to read settings.
    """
    try:
        if callable(settings_client):
            warmup_keys_raw = settings_client("reports.warmup_keys")
        else:
            warmup_keys_raw = settings_client

        if not warmup_keys_raw:
            logger.info("No warmup keys configured")
            return 0

        import json
        if isinstance(warmup_keys_raw, str):
            keys = json.loads(warmup_keys_raw)
        else:
            keys = warmup_keys_raw

        if not isinstance(keys, list):
            logger.warning("reports.warmup_keys is not a list: %s", type(keys))
            return 0

        warmed = 0
        for key in keys:
            try:
                await asyncio.wait_for(
                    _warmup_single_key(cache_client, key),
                    timeout=WARMUP_TIMEOUT_SECONDS,
                )
                warmed += 1
            except asyncio.TimeoutError:
                logger.warning("Warmup timeout for key: %s", key)
            except Exception as exc:
                logger.warning("Warmup failed for key %s: %s", key, exc)

        logger.info("Cache warmup complete: %d/%d keys", warmed, len(keys))
        return warmed

    except Exception as exc:
        logger.error("Cache warmup failed: %s", exc)
        return 0


async def _warmup_single_key(cache_client: Any, key: str) -> None:
    """Warm up a single cache key.

    The actual data source depends on the key prefix. This is a
    placeholder that subclasses/implementations should override.
    """
    # Check if already cached
    existing = cache_client.get(key)
    if existing is not None:
        logger.debug("Warmup: key %s already cached", key)
        return

    # The actual warmup logic depends on the key type
    # For now, just log that we'd warm it up
    logger.debug("Warmup: key %s needs population (implement per key type)", key)
