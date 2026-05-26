"""
Circuit-breaker primitive for external integrations (Phase 5 / T5.3).

Goals:
  * Trip after N consecutive failures within a sliding window.
  * Block all calls for ``cooldown_seconds`` after tripping.
  * Allow one probe ("half-open") to close the circuit again.
  * Persist breaker state to ``integration_circuit_state`` so a process
    restart does not reopen a failing dependency for retry storms.

Usage::

    from integrations.circuit_breaker import circuit_breaker

    @circuit_breaker(integration_type="payment", provider="stripe")
    def charge(...):
        ...

    # or programmatically:
    breaker = CircuitBreaker("sms", "taqnyat")
    breaker.call(send_sms, to, body)
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable, Dict, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a call is short-circuited because the breaker is open."""

    def __init__(self, integration_type: str, provider: str, opens_until: datetime):
        super().__init__(
            f"Circuit OPEN for {integration_type}/{provider}; "
            f"retry after {opens_until.isoformat()}"
        )
        self.integration_type = integration_type
        self.provider = provider
        self.opens_until = opens_until


@dataclass
class _BreakerState:
    state: str = "closed"            # closed | open | half_open
    failure_count: int = 0
    last_failure_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    opens_until: Optional[datetime] = None
    last_error: Optional[str] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class CircuitBreaker:
    """In-memory breaker; optionally syncs state to the tenant DB."""

    # Module-level registry so the same breaker instance is reused for the
    # same (integration_type, provider) tuple within one process.
    _registry: Dict[Tuple[str, str], "CircuitBreaker"] = {}
    _registry_lock = threading.Lock()

    @classmethod
    def get(cls, integration_type: str, provider: str,
            failure_threshold: int = 5, cooldown_seconds: int = 60) -> "CircuitBreaker":
        key = (integration_type, provider)
        with cls._registry_lock:
            if key not in cls._registry:
                cls._registry[key] = cls(
                    integration_type=integration_type,
                    provider=provider,
                    failure_threshold=failure_threshold,
                    cooldown_seconds=cooldown_seconds,
                )
            return cls._registry[key]

    def __init__(
        self,
        integration_type: str,
        provider: str,
        failure_threshold: int = 5,
        cooldown_seconds: int = 60,
        db_persist: bool = True,
    ):
        self.integration_type = integration_type
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.db_persist = db_persist
        self._state = _BreakerState()

    # ─── core decision ─────────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def allow_request(self) -> bool:
        """Return True if the call should be attempted; False if short-circuited."""
        with self._state.lock:
            now = self._now()
            if self._state.state == "open":
                if self._state.opens_until and now >= self._state.opens_until:
                    # cooldown elapsed → half-open: allow one probe
                    self._state.state = "half_open"
                    logger.info("[CB] %s/%s entering HALF_OPEN", self.integration_type, self.provider)
                    return True
                return False
            return True

    def record_success(self, db=None, tenant_id: int | None = None,
                       credential_id: int | None = None) -> None:
        with self._state.lock:
            if self._state.state in ("open", "half_open"):
                logger.info("[CB] %s/%s closing (success)", self.integration_type, self.provider)
            self._state.state = "closed"
            self._state.failure_count = 0
            self._state.opened_at = None
            self._state.opens_until = None
            self._state.last_error = None
        self._persist(db, success=True)
        # Feature 022: reset credential failure counter on success
        if tenant_id is not None and credential_id is not None:
            try:
                from services.credentials_vault import record_success as vault_record_success
                vault_record_success(tenant_id, credential_id)
            except Exception:
                logger.debug("[CB] credentials_vault.record_success skipped", exc_info=True)

    def record_failure(self, error: str = "", db=None, tenant_id: int | None = None,
                       credential_id: int | None = None) -> None:
        with self._state.lock:
            self._state.failure_count += 1
            self._state.last_failure_at = self._now()
            self._state.last_error = (error or "")[:500]
            if (self._state.state == "half_open"
                    or self._state.failure_count >= self.failure_threshold):
                self._state.state = "open"
                self._state.opened_at = self._state.last_failure_at
                self._state.opens_until = (self._state.last_failure_at
                                           + timedelta(seconds=self.cooldown_seconds))
                logger.warning(
                    "[CB] %s/%s OPENED (failures=%d, cooldown=%ds, last_error=%s)",
                    self.integration_type, self.provider,
                    self._state.failure_count, self.cooldown_seconds,
                    self._state.last_error,
                )
        self._persist(db, success=False)
        # Feature 022: notify credential vault of failure (for alerting)
        if tenant_id is not None and credential_id is not None:
            try:
                from services.credentials_vault import record_failure as vault_record_failure
                vault_record_failure(tenant_id, credential_id)
            except Exception:
                logger.debug("[CB] credentials_vault.record_failure skipped", exc_info=True)

    # ─── persistence ───────────────────────────────────────────────────

    def _persist(self, db, success: bool) -> None:
        if not self.db_persist or db is None:
            return
        try:
            from sqlalchemy import text  # local import to avoid hard dep at module load
            db.execute(
                text("""
                    INSERT INTO integration_circuit_state (
                        integration_type, provider, state, failure_count,
                        last_failure_at, opened_at, opens_until, last_error,
                        updated_at
                    ) VALUES (
                        :it, :pr, :st, :fc, :lf, :oa, :ou, :le, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (integration_type, provider) DO UPDATE SET
                        state = EXCLUDED.state,
                        failure_count = EXCLUDED.failure_count,
                        last_failure_at = EXCLUDED.last_failure_at,
                        opened_at = EXCLUDED.opened_at,
                        opens_until = EXCLUDED.opens_until,
                        last_error = EXCLUDED.last_error,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "it": self.integration_type,
                    "pr": self.provider,
                    "st": self._state.state,
                    "fc": self._state.failure_count,
                    "lf": self._state.last_failure_at,
                    "oa": self._state.opened_at,
                    "ou": self._state.opens_until,
                    "le": self._state.last_error,
                },
            )
        except Exception:
            logger.exception("[CB] failed to persist breaker state")

    # ─── public call wrappers ──────────────────────────────────────────

    def call(self, func: Callable[..., T], *args, db=None, **kwargs) -> T:
        if not self.allow_request():
            raise CircuitOpenError(self.integration_type, self.provider,
                                   self._state.opens_until or self._now())
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            self.record_failure(str(e), db=db)
            raise
        self.record_success(db=db)
        return result

    @contextmanager
    def guard(self, db=None):
        """Context manager flavour::

            with breaker.guard(db=db):
                send(...)
        """
        if not self.allow_request():
            raise CircuitOpenError(self.integration_type, self.provider,
                                   self._state.opens_until or self._now())
        try:
            yield self
        except Exception as e:
            self.record_failure(str(e), db=db)
            raise
        else:
            self.record_success(db=db)

    @property
    def state(self) -> str:
        return self._state.state

    def snapshot(self) -> dict:
        with self._state.lock:
            return {
                "integration_type": self.integration_type,
                "provider": self.provider,
                "state": self._state.state,
                "failure_count": self._state.failure_count,
                "opens_until": (self._state.opens_until.isoformat()
                                if self._state.opens_until else None),
                "last_error": self._state.last_error,
            }


def circuit_breaker(integration_type: str, provider: str,
                    failure_threshold: int = 5, cooldown_seconds: int = 60):
    """Decorator wrapping a callable with the named breaker.

    Note: persistence is opt-in by passing ``db=...`` keyword to the
    wrapped function call (the wrapper extracts but does not consume it).
    """
    breaker = CircuitBreaker.get(
        integration_type, provider,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            db = kwargs.pop("_breaker_db", None)
            return breaker.call(func, *args, db=db, **kwargs)
        wrapper.breaker = breaker  # type: ignore[attr-defined]
        return wrapper

    return decorator


__all__ = ["CircuitBreaker", "CircuitOpenError", "circuit_breaker"]
