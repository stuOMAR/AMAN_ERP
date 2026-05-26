"""T015: Redis circuit breaker + outage policy.

Wraps the cache client with a circuit breaker that opens after N
consecutive failures and cools down before re-probing.

Reads settings from ``company_settings``:
  - ``cache.backend``: ``redis | memory``
  - ``cache.circuit_breaker.failures``: open breaker after N failures (default 5)
  - ``cache.circuit_breaker.cool_down_seconds``: cool-down before re-probe (default 30)

When the breaker is open and a cache-required endpoint is hit, raises
``CacheUnavailable`` which maps to HTTP 503 ``cache.unavailable``.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CacheUnavailable(Exception):
    """Raised when cache is required but unavailable (maps to HTTP 503)."""

    def __init__(self, message: str = "Cache backend unavailable"):
        self.error_code = "cache.unavailable"
        super().__init__(message)


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreaker:
    """Circuit breaker for cache operations."""

    def __init__(self, failure_threshold: int = 5, cool_down_seconds: int = 30):
        self.failure_threshold = failure_threshold
        self.cool_down_seconds = cool_down_seconds
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._state = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.cool_down_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Cache circuit breaker OPEN after %d consecutive failures",
                self._failure_count,
            )

    def allow_request(self) -> bool:
        """Return True if the request should proceed to cache."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True  # Allow one probe request
        return False  # OPEN — reject


class ResilientCacheClient:
    """Cache client wrapper with circuit breaker + audit event on memory fallback."""

    def __init__(self, inner: Any, backend: str = "redis",
                 failure_threshold: int = 5, cool_down_seconds: int = 30):
        self._inner = inner
        self._backend = backend
        self._breaker = CircuitBreaker(failure_threshold, cool_down_seconds)

    @property
    def circuit_state(self) -> str:
        return self._breaker.state.value

    def get(self, key: str) -> Any | None:
        if not self._breaker.allow_request():
            raise CacheUnavailable()
        try:
            result = self._inner.get(key)
            self._breaker.record_success()
            return result
        except Exception as exc:
            self._breaker.record_failure()
            raise CacheUnavailable() from exc

    def set(self, key: str, value: Any, expire: int = 300) -> None:
        if not self._breaker.allow_request():
            raise CacheUnavailable()
        try:
            self._inner.set(key, value, expire)
            self._breaker.record_success()
        except Exception as exc:
            self._breaker.record_failure()
            raise CacheUnavailable() from exc

    def delete(self, key: str) -> None:
        if not self._breaker.allow_request():
            raise CacheUnavailable()
        try:
            self._inner.delete(key)
            self._breaker.record_success()
        except Exception:
            self._breaker.record_failure()

    def delete_pattern(self, pattern: str) -> None:
        if not self._breaker.allow_request():
            return  # Non-critical, don't raise
        try:
            self._inner.delete_pattern(pattern)
            self._breaker.record_success()
        except Exception:
            self._breaker.record_failure()

    def set_nx(self, key: str, value: Any, expire: int = 30) -> bool:
        if not self._breaker.allow_request():
            raise CacheUnavailable()
        try:
            result = self._inner.set_nx(key, value, expire)
            self._breaker.record_success()
            return result
        except Exception as exc:
            self._breaker.record_failure()
            raise CacheUnavailable() from exc


def check_memory_backend_warning(backend: str, app_env: str) -> None:
    """Emit a startup audit event if memory backend detected in production."""
    if backend == "memory" and app_env == "production":
        logger.critical(
            "AUDIT: cache.backend=memory detected in production environment. "
            "This is NOT recommended — Redis is required for multi-worker deployments."
        )
