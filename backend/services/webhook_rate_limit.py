"""
Webhook rate limiter — Redis token-bucket with Lua atomicity.

Contract: see specs/022-audit-security-finance-integrity/contracts/webhook-ratelimit.md
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Lua script (token bucket: INCR + TTL in one shot) ─────────────────────────

_LUA_TOKEN_BUCKET = """\
local key      = KEYS[1]
local max_req  = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])

local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, window)
end
local ttl = redis.call('TTL', key)
return {current, ttl}
"""

# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: Optional[int]
    reason: Optional[str]


# ── Redis helper (lazy, fail-open) ────────────────────────────────────────────

_redis_client = None
_redis_available = True
_lua_sha: Optional[str] = None


def _get_redis():
    global _redis_client, _lua_sha
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        url = __import__("os").environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        _lua_sha = _redis_client.script_load(_LUA_TOKEN_BUCKET)
    except Exception as exc:
        logger.warning("webhook_rate_limit: Redis unavailable (%s)", exc)
        _redis_client = None
    return _redis_client


def _get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute(
        text("SELECT setting_value FROM company_settings WHERE setting_key = :k"),
        {"k": key},
    ).scalar()
    return row if row is not None else default


# ── Public API ────────────────────────────────────────────────────────────────

def check_and_consume(
    tenant_id: int,
    integration: str,
    *,
    request_id: Optional[str] = None,
) -> RateLimitDecision:
    """Check the rate limit and consume one token.  Fail-open on Redis down."""
    global _redis_available

    # Lazy-import so the module loads even without redis-py installed.
    rds = _get_redis()
    if rds is None:
        return RateLimitDecision(
            allowed=True, remaining=-1, retry_after_seconds=None,
            reason="redis_unavailable_fail_open",
        )

    # Read limits from company_settings via system DB.
    # We use a raw connection to avoid per-request session overhead.
    from database import engine as sys_engine
    try:
        with sys_engine.connect() as conn:
            window_str = _get_setting(conn, "webhook.ratelimit.window_seconds", "60")
            max_req_str = _get_setting(conn, "webhook.ratelimit.max_requests", "120")

            # Per-integration override
            integ_max_key = f"webhook.ratelimit.{integration}.max_requests"
            integ_max = _get_setting(conn, integ_max_key, "")
            if integ_max:
                max_req_str = integ_max
    except Exception:
        logger.exception("webhook_rate_limit: failed to read settings, using defaults")
        window_str, max_req_str = "60", "120"

    window = int(window_str)
    max_requests = int(max_req_str)
    key = f"webhook:ratelimit:{tenant_id}:{integration}"

    try:
        if _lua_sha:
            result = rds.evalsha(_lua_sha, 1, key, max_requests, window)
        else:
            result = rds.eval(_LUA_TOKEN_BUCKET, 1, key, max_requests, window)
        current_count = int(result[0])
        ttl = int(result[1])
    except Exception as exc:
        logger.warning("webhook_rate_limit: Redis eval failed (%s) — fail-open", exc)
        _redis_available = False
        return RateLimitDecision(
            allowed=True, remaining=-1, retry_after_seconds=None,
            reason="redis_error_fail_open",
        )

    remaining = max(0, max_requests - current_count)

    if current_count > max_requests:
        return RateLimitDecision(
            allowed=False,
            remaining=0,
            retry_after_seconds=max(ttl, 1),
            reason="tenant_quota_exceeded",
        )

    return RateLimitDecision(
        allowed=True,
        remaining=remaining,
        retry_after_seconds=None,
        reason=None,
    )


__all__ = ["check_and_consume", "RateLimitDecision"]
