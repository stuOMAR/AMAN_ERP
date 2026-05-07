# Contract: Recurring JE Template Service (`services/recurring_je_service.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def run_template(conn, tenant_id: int, template_id: int, *, run_date: date) -> RunResult: ...

def approve_pending(conn, tenant_id: int, pending_id: int, *, actor_id: int) -> RunResult: ...

def reject_pending(conn, tenant_id: int, pending_id: int, *, actor_id: int, reason: str) -> None: ...
```

`RunResult`:

```python
@dataclass
class RunResult:
    posted: bool
    pending_review_id: int | None
    journal_entry_id: int | None
```

## Behavior

- Scheduler invokes `run_template` for due templates per tenant under an advisory lock keyed by `template_id` to avoid double-runs.
- For each run:
  1. Resolve `expense_category_id` (NOT NULL — refuse with a configuration error if missing).
  2. Compute amount per the template formula.
  3. If `auto_approve = true` AND (`review_threshold IS NULL` OR `amount < review_threshold`), post the JE directly via `gl_service.post_journal_entry(...)`. Audit `recurring.auto_post`.
  4. Otherwise, write a `recurring_je_pending_review` row and dispatch a notification to approvers.
- Generated JE lines MUST carry the template's `expense_category_id`.

## Approval

- `approve_pending` posts the JE through `gl_service` and audits `recurring.approved_post` with `critical = true`.
- `reject_pending` cancels the pending row and audits `recurring.rejected` with the reason.

## Validation

- Refuse to run if `expense_category_id` references a deleted category.
- Refuse to run if the resulting JE would violate the JE epsilon rule (delegated to `gl_service`).

## Forbidden patterns

- Posting recurring JEs anywhere outside this service.
- Recurring template without a non-null `expense_category_id` post-migration (CI scan).
