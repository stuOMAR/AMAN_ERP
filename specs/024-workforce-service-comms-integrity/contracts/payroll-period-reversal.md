# Contract: Payroll Period Reversal

## Purpose
Single canonical workflow to reverse a locked payroll period: GL inverse, WPS supersession, compensating bank movements, audit.

## Helper

`services/payroll/period_reversal.py::reverse_payroll_period(period_id, reason) -> ReversalResult`

## Preconditions
- `payroll_periods.state = 'locked'`.
- Caller has `payroll.reverse` sensitive permission.

## Side Effects (in one `transactional()`)

1. `payroll_periods.state = 'reversed'`.
2. `gl_service.reverse(source='payroll', source_id=period_id, je_source=JESource.PAYROLL_REVERSE)` — posts inverse JE balanced under `gl.je_epsilon`.
3. For each affected `payroll_runs` row:
   - Insert compensating `bank_transactions` rows: `direction='credit'`, `amount=-original`, `external_ref='reversal:<original_external_ref>'`, idempotent on partial unique.
   - Set `wps_superseded_by_run_id=NULL` (will be set when re-run is created).
4. `audit_writer.log_activity(action='payroll.period.reversed', target=period_id, payload=sanitize_for_audit({reason}))`.

## Idempotency
Re-call with same `period_id` returns the existing reversal record without duplicating GL or bank rows.

## Errors

| Code | When |
|------|------|
| 409 `payroll.period_not_locked` | State is not `locked`. |
| 409 `payroll.period_already_reversed` | (returned with existing reversal id; not an error to caller; HTTP 200 with `idempotent_replay=true`). |
| 403 `payroll.reverse.forbidden` | No `payroll.reverse` permission. |
