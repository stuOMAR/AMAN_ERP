# Contract: Webhook Rate Limit (`services/webhook_rate_limit.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def check_and_consume(tenant_id: int, integration: str, *, request_id: str | None = None) -> RateLimitDecision: ...
```

`RateLimitDecision`:

```python
@dataclass
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int | None
    reason: str | None  # e.g., "tenant_quota_exceeded"
```

## Behavior

- MUST be backed by Redis using a token-bucket Lua script (`INCR` + `EXPIRE` atomic).
- Key format: `webhook:ratelimit:{tenant_id}:{integration}`.
- Window and max requests come from `company_settings.webhook.ratelimit.window_seconds` and `.max_requests`. Per-integration overrides allowed via `company_settings.webhook.ratelimit.<integration>.max_requests`.
- On `allowed = false`, the inbound webhook handler MUST:
  - return HTTP 429 with `Retry-After` header,
  - emit `log_activity(action="webhook.rate_limited", entity_type="integration", entity_id=integration_id, details={"request_id": ..., "reason": ...}, critical=False)`.

## Failure modes

- If Redis is unreachable, MUST fail-open with a metric and structured log; SHOULD NOT block legitimate inbound webhooks. (Constitution gate: this is documented in `research.md` and accepted as the safer default for inbound integrations.)

## Forbidden patterns

- Per-process counters; per-integration ad-hoc limits outside this helper.
