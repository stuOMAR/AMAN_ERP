# Contract: Audit Writer (`services/audit_writer.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def log_activity(
    conn,
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    details: dict | AuditDetails | None = None,
    critical: bool = False,
) -> None: ...
```

## Behavior

- MUST use the caller's session/connection (`conn`); MUST NOT open a new transaction; MUST NOT issue `COMMIT` or `ROLLBACK`.
- MUST sanitize `details` via `sanitize_for_audit(details, context=action)` before persistence.
- MUST insert into `audit_outbox` (not `audit_logs`).
- MUST stamp `enqueued_at` with DB time (`clock_timestamp()`); MUST NOT pass an application-clock value.
- MUST raise on failure; MUST NOT swallow exceptions.
- MUST NOT itself catch and ignore SQL errors — callers wrap behavior.

## Forbidden patterns (CI-enforced by `scripts/audit_writer_lint.py`)

- Direct `INSERT INTO audit_logs` anywhere outside `audit_outbox_worker.flush()`.
- `conn.commit()` / `conn.rollback()` reachable from `log_activity` (AST scan).
- `try: ... except Exception: pass` inside the writer.

## Outbox flush worker

```python
def flush(batch_size: int, max_runtime_seconds: int) -> FlushReport: ...
```

- MUST select with `FOR UPDATE SKIP LOCKED` ordered by `enqueued_at`.
- MUST insert into `audit_logs` and update `audit_outbox.flushed_at` in one transaction per batch.
- MUST exponentially back off failing rows up to a configured cap; MUST surface a backlog metric.
- MUST be tenant-aware: iterate tenants and acquire `get_db_connection(company_id)` per tenant.

## Errors

- `AuditWriteError` — raised when sanitization or insert fails. Caller decides whether to fail the business operation.
