# Contract: Reconciliation Finalize (`services/reconciliation_service.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def finalize_reconciliation(
    conn,
    tenant_id: int,
    reconciliation_id: int,
    *,
    actor_id: int,
) -> FinalizeResult: ...
```

`FinalizeResult`:

```python
@dataclass
class FinalizeResult:
    ok: bool
    drift_report: DriftReport | None  # populated when ok = False or for audit when ok = True
    finalized_at: datetime | None

@dataclass
class DriftReport:
    gl_total: Decimal
    bank_total: Decimal
    difference: Decimal
    tolerance: Decimal
    unmatched_lines: list[UnmatchedLine]  # bank ↔ GL diffs by line
```

## Behavior

- MUST `SELECT FOR UPDATE` the reconciliation row to prevent concurrent finalize.
- MUST recompute GL balance via `gl_service.get_account_balance(account_id, as_of=cut_off)` (no other source).
- MUST compute bank/treasury total from the reconciliation's matched + unmatched lines.
- MUST refuse finalize when `abs(gl_total - bank_total) > tolerance`; tolerance from `company_settings.reconciliation.drift_tolerance` (Decimal, default `0.01`).
- On reject: returns `ok = False` with the structured `DriftReport`; reconciliation stays in `draft`.
- On accept: sets `finalized_at = clock_timestamp()`, transitions state, and emits `log_activity(action="reconciliation.finalize", entity_type="reconciliation", entity_id=reconciliation_id, details=..., critical=True)`.

## Concurrency

- Two concurrent calls on the same reconciliation: only one acquires the lock; the other receives a clear `ConflictError` (HTTP 409 at the router boundary).

## Errors

- `ReconciliationDriftError` — drift > tolerance.
- `ReconciliationStateError` — already finalized.
- `ConflictError` — concurrent finalize.

## HTTP wiring

- `POST /api/finance/reconciliations/{id}/finalize` returns:
  - 200 with `FinalizeResult` on success;
  - 409 with `DriftReport` on drift;
  - 409 with state error on already-finalized.
