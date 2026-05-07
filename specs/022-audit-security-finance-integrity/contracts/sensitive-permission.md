# Contract: Sensitive-Permission Decorator (`services/permissions/sensitive.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def require_sensitive_permission(
    scope: str,
    *,
    critical: bool = False,
    audit_view: bool = True,
    require_step_up: bool | None = None,  # None = use company policy
) -> Callable: ...
```

Used as a FastAPI dependency:

```python
@router.post("/finance/journal", dependencies=[Depends(require_sensitive_permission("finance.post", critical=True))])
def post_je(...): ...
```

## Behavior

- MUST call existing `require_permission(scope)` first; reject 403 on failure.
- MUST enforce step-up authentication (TOTP / recent reauth) when `require_step_up` resolves to `True` for the calling tenant.
- MUST tag the request scope with `critical` so audit downstream attaches `critical = True`.
- When `audit_view = True` and the request is GET-style, MUST emit a uniform report-view audit row through `log_activity(...)` after the handler returns successfully.
- MUST register the decorated route in a process-wide `SENSITIVE_REGISTRY` at import time.

## Startup discovery

- A startup hook compares `SENSITIVE_REGISTRY` against `services/permissions/sensitive_routes.yaml` (path glob → required scope).
- Missing wraps:
  - in production: `SystemExit(1)` with a structured error listing the offenders.
  - in dev/CI: same exit, runnable via `python -m backend.scripts.permissions_discover --strict`.

## Coverage list (initial scope)

The YAML MUST cover at minimum:

- `POST/PUT/PATCH /api/finance/**` (posting, edits, reversals)
- `POST /api/finance/reconciliations/*/finalize`
- `GET /api/reports/finance/**`, `GET /api/reports/kpi/**`
- `GET/POST/PUT/DELETE /api/admin/credentials/**`
- `GET/POST/PUT /api/hr/employees/*/salary`, `**/iban`, `**/national_id`
- `POST /api/hr/payroll/**`
- `GET/POST/PUT /api/admin/settings/**`
- `GET/POST/PUT /api/admin/account-classifications/**`

## Forbidden patterns

- New sensitive endpoints added without entry in the YAML AND without the decorator (CI fails the build).
