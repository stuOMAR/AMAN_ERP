"""T013: Cache observability middleware.

Provides the ``@cache_observable`` decorator for FastAPI endpoints that
sets ``X-Cache-Hit`` and ``X-Cache-TTL`` response headers.

Usage::

    @router.get("/reports/income_statement")
    @cache_observable("income_statement", "reports.cache.ttl.income_statement")
    async def income_statement(...):
        ...
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ── Header names ─────────────────────────────────────────────────────────
HEADER_CACHE_HIT = "X-Cache-Hit"
HEADER_CACHE_TTL = "X-Cache-TTL"
HEADER_CACHE_KEY = "X-Cache-Key"


class CacheObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware that adds cache observability headers to responses.

    Endpoints opt in via the ``@cache_observable`` decorator which sets
    ``request.state.cache_observable = True`` and stores metadata.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only add headers if the endpoint opted in
        observable = getattr(request.state, "cache_observable", False)
        if not observable:
            return response

        cache_hit = getattr(request.state, "cache_hit", None)
        cache_ttl = getattr(request.state, "cache_ttl_remaining", None)

        if cache_hit is not None:
            response.headers[HEADER_CACHE_HIT] = "true" if cache_hit else "false"
        if cache_ttl is not None:
            response.headers[HEADER_CACHE_TTL] = str(int(cache_ttl))

        return response


def cache_observable(report_code: str, ttl_setting: str) -> Callable:
    """Decorator that marks an endpoint as cache-observable.

    The middleware will add X-Cache-Hit / X-Cache-TTL headers.

    Args:
        report_code: The report code for observability logging.
        ttl_setting: The settings key for the TTL (e.g., ``reports.cache.ttl.income_statement``).
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = kwargs.get("request")
            if request is None:
                # Try to find request in args
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is not None:
                request.state.cache_observable = True
                request.state.cache_report_code = report_code
                request.state.cache_ttl_setting = ttl_setting

            start = time.monotonic()
            result = await func(*args, **kwargs)
            elapsed = time.monotonic() - start

            if request is not None:
                logger.debug(
                    "cache_observable: report=%s latency=%.3fs hit=%s",
                    report_code, elapsed,
                    getattr(request.state, "cache_hit", None),
                )

            return result

        wrapper._cache_observable = True
        wrapper._report_code = report_code
        wrapper._ttl_setting = ttl_setting
        return wrapper

    return decorator


def set_cache_hit(request: Request, hit: bool, ttl_remaining: float | None = None) -> None:
    """Call this from the endpoint/service to report cache hit/miss."""
    request.state.cache_hit = hit
    if ttl_remaining is not None:
        request.state.cache_ttl_remaining = ttl_remaining
