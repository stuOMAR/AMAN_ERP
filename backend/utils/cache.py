
import json
import logging
from typing import Any, Optional, Callable
import hashlib
from datetime import date, datetime, timedelta
from uuid import UUID
from decimal import Decimal
from functools import wraps
from config import settings

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> Any:
    """Custom JSON encoder — handles types not natively JSON-serialisable."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

class MemoryCache:
    def __init__(self):
        self._cache = {}
        self._expiry = {}
        import time
        self._time = time
        
    def get(self, key: str) -> Optional[Any]:
        if key in self._expiry:
            if self._time.time() > self._expiry[key]:
                del self._cache[key]
                del self._expiry[key]
                return None
        return self._cache.get(key)
        
    def set(self, key: str, value: Any, expire: int = 300):
        self._cache[key] = value
        self._expiry[key] = self._time.time() + expire
        
    def delete(self, key: str):
        if key in self._cache:
            del self._cache[key]
        if key in self._expiry:
            del self._expiry[key]
            
    def delete_pattern(self, pattern: str):
        keys_to_delete = [k for k in self._cache.keys() if pattern in k]
        for k in keys_to_delete:
            del self._cache[k]
            if k in self._expiry:
                del self._expiry[k]

    def flush(self):
        self._cache.clear()
        self._expiry.clear()

    def set_nx(self, key: str, value: Any, expire: int = 30) -> bool:
        """T7.4: stampede-lock primitive (set if absent). Returns True if
        the key was set (caller acquired the lock)."""
        if key in self._cache:
            # Honour TTL
            if key in self._expiry and self._time.time() > self._expiry[key]:
                del self._cache[key]
                del self._expiry[key]
            else:
                return False
        self._cache[key] = value
        self._expiry[key] = self._time.time() + expire
        return True


class RedisCache:
    def __init__(self, url: str):
        try:
            import redis
            self.redis = redis.from_url(url)
            self.enabled = True
        except (ImportError, Exception) as e:
            logger.warning(f"Redis not available, falling back to memory cache: {e}")
            self.enabled = False
            self.memory = MemoryCache()

    def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return self.memory.get(key)
        try:
            val = self.redis.get(key)
            if val:
                # SEC-FIX: use json instead of pickle to prevent RCE
                return json.loads(val.decode('utf-8'))
            return None
        except Exception as e:  # Redis failure
            logger.error(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: Any, expire: int = 300):
        if not self.enabled:
            return self.memory.set(key, value, expire)
        try:
            self.redis.setex(key, timedelta(seconds=expire), json.dumps(value, default=_json_default))
        except Exception as e:
            logger.error(f"Redis set error: {e}")

    def delete(self, key: str):
        if not self.enabled:
            return self.memory.delete(key)
        try:
            self.redis.delete(key)
        except Exception:
            pass
            
    def delete_pattern(self, pattern: str):
        if not self.enabled:
            return self.memory.delete_pattern(pattern)
        try:
            # Not extremely efficient for production redis but okay here
            keys = self.redis.keys(f"*{pattern}*")
            if keys:
                self.redis.delete(*keys)
        except Exception:
            pass

    def set_nx(self, key: str, value: Any, expire: int = 30) -> bool:
        """T7.4: distributed stampede-lock primitive (Redis SET NX EX).
        Returns True if the lock was acquired (key did not exist).
        Falls back to in-memory MemoryCache when Redis is disabled."""
        if not self.enabled:
            return self.memory.set_nx(key, value, expire)
        try:
            payload = json.dumps(value, default=_json_default)
            # nx=True ensures we only set if absent; ex sets TTL atomically.
            return bool(self.redis.set(key, payload, nx=True, ex=expire))
        except Exception as e:
            logger.error(f"Redis set_nx error: {e}")
            return False

# Initialize cache
if settings.REDIS_URL:
    cache = RedisCache(settings.REDIS_URL)
else:
    cache = MemoryCache()


def tenant_key(company_id: Any, *parts: Any) -> str:
    """
    SEC-05: Build a cache key that is guaranteed to be tenant-scoped.

    Always use this helper (or the @cached decorator with company_specific=True)
    when caching tenant data. Passing raw keys like f"invoices:{id}" to
    cache.get/set directly risks cross-tenant collision if two tenants share
    numeric IDs.

    Example:
        key = tenant_key(current_user.company_id, "invoices", invoice_id)
        # → "t:abc12345:invoices:42"
    """
    if not company_id:
        raise ValueError("tenant_key() requires a non-empty company_id")
    return "t:" + ":".join(str(p) for p in (company_id, *parts))


def cached(prefix: str, expire: int = 300, company_specific: bool = True):
    """
    Decorator for caching FastAPI endpoint responses.
    
    Usage:
        @router.get("/heavy-query")
        @cached("dashboard_stats", expire=120)
        def get_stats(current_user = Depends(get_current_user)):
            ...
    
    Args:
        prefix: Cache key prefix (e.g., "dashboard", "reports")
        expire: Cache TTL in seconds (default: 5 minutes)
        company_specific: If True, includes company_id in cache key

    T7.4 features:
        * Honours ``?no_cache=1`` query parameter (Request kwarg) — bypasses
          read but still refreshes the entry.
        * Single-flight stampede protection: on cache miss, only one worker
          computes; siblings briefly poll for the freshly-cached result.
        * Records hit/miss counters exposed via :func:`cache_stats`.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from function name + arguments
            key_parts = [prefix, func.__name__]
            
            # Add company_id if available
            current_user = kwargs.get('current_user')
            if company_specific and current_user:
                if isinstance(current_user, dict):
                    cid = current_user.get('company_id', '')
                else:
                    cid = getattr(current_user, 'company_id', '')
                key_parts.append(str(cid))

            # Hash relevant kwargs (excluding current_user)
            relevant_kwargs = {
                k: str(v) for k, v in kwargs.items()
                if k not in ('current_user', 'db', 'request') and v is not None
            }
            if relevant_kwargs:
                args_hash = hashlib.md5(
                    json.dumps(relevant_kwargs, sort_keys=True, default=str).encode()
                ).hexdigest()[:12]
                key_parts.append(args_hash)

            cache_key = ":".join(key_parts)

            # T7.4: ?no_cache=1 → skip read, still refresh.
            no_cache = _request_wants_fresh(kwargs.get('request'))

            # Try cache
            if not no_cache:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    _record_hit()
                    logger.debug(f"Cache HIT: {cache_key}")
                    if isinstance(cached_result, dict) and "_cache_meta" not in cached_result:
                        cached_result["_cache_meta"] = {
                            "cached": True,
                            "ttl_seconds": expire,
                            "recompute_param": "?no_cache=1",
                        }
                    return cached_result
                _record_miss()

            # T7.4: stampede / thundering-herd protection. Only one worker
            # acquires the compute lock; siblings poll briefly for the
            # newly-set value before falling through to compute themselves.
            lock_key = f"lock:{cache_key}"
            acquired = cache.set_nx(lock_key, "1", expire=_LOCK_TTL_SECONDS) if not no_cache else True
            if not acquired:
                import time
                deadline = time.time() + _LOCK_WAIT_SECONDS
                while time.time() < deadline:
                    waited = cache.get(cache_key)
                    if waited is not None:
                        _record_hit()
                        if isinstance(waited, dict) and "_cache_meta" not in waited:
                            waited["_cache_meta"] = {
                                "cached": True,
                                "ttl_seconds": expire,
                                "recompute_param": "?no_cache=1",
                                "via": "stampede_wait",
                            }
                        return waited
                    time.sleep(0.05)
                # Lock holder slow / crashed — fall through and compute.

            try:
                # Execute function
                result = func(*args, **kwargs)

                # Store in cache
                try:
                    cache.set(cache_key, result, expire)
                    logger.debug(f"Cache SET: {cache_key} (TTL={expire}s)")
                except Exception as e:
                    logger.warning(f"Cache set failed: {e}")

                return result
            finally:
                if acquired:
                    try:
                        cache.delete(lock_key)
                    except Exception:
                        pass

        return wrapper
    return decorator


def invalidate_cache(pattern: str):
    """Invalidate all cache keys matching a pattern"""
    cache.delete_pattern(pattern)


def invalidate_company_cache(company_id: str, module: str = ""):
    """Invalidate all cache for a specific company and optional module"""
    pattern = f"{module}:{company_id}" if module else str(company_id)
    cache.delete_pattern(pattern)


# ---------------------------------------------------------------------------
# T7.4 — stampede lock + hit/miss stats + ?no_cache=1 plumbing
# ---------------------------------------------------------------------------

# How long a compute lock lives (must exceed worst-case computation).
_LOCK_TTL_SECONDS = 30
# How long a sibling will wait for a peer's freshly-cached result before
# falling through and computing itself.
_LOCK_WAIT_SECONDS = 5

_stats = {"hits": 0, "misses": 0}


def _record_hit() -> None:
    _stats["hits"] += 1


def _record_miss() -> None:
    _stats["misses"] += 1


def cache_stats() -> dict:
    """T7.4: hit-rate metrics for ops dashboards. DoD: hit-rate > 60%."""
    h = _stats["hits"]
    m = _stats["misses"]
    total = h + m
    return {
        "hits": h,
        "misses": m,
        "total": total,
        "hit_rate": (h / total) if total else 0.0,
    }


def reset_cache_stats() -> None:
    _stats["hits"] = 0
    _stats["misses"] = 0


def _request_wants_fresh(request: Any) -> bool:
    """Return True if the incoming Request asked for ``?no_cache=1``.

    Accepts a FastAPI/Starlette Request, a plain mapping, or None.
    """
    if request is None:
        return False
    try:
        qp = getattr(request, "query_params", None)
        if qp is None and isinstance(request, dict):
            qp = request.get("query_params")
        if qp is None:
            return False
        val = qp.get("no_cache") if hasattr(qp, "get") else None
        if val is None:
            return False
        return str(val).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return False
