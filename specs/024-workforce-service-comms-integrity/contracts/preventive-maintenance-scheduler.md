# Contract: Preventive Maintenance Scheduler

## Worker

`services/fsm/maintenance/preventive_scheduler.py::run(tenant_id, as_of=now)` — invoked by APScheduler per-tenant under advisory lock.

## Behavior

- Iterates `maintenance_plans WHERE active=true AND next_due_at <= as_of + lead_days`.
- For each plan, computes `due_window_start` (period-floored timestamp).
- Dedupe: skip if a service order already exists with `(tenant_id, contract_id|asset_id|equipment_id, plan_id, due_window_start)` matching.
- Else creates a `service_orders` row with:
  - `kind='preventive'`, `contract_id` / `asset_id` / `equipment_id` from plan.
  - `scheduled_window` = (`due_window_start`, `due_window_start + cadence`).
  - Lines copied from `template_service_order_id` (if any).
- Updates `maintenance_plans.last_generated_at` and bumps `next_due_at` by cadence.
- Optional auto-assign via `technician_assignment_matcher`.
- Optional notification via `notifications.dispatch(channel='email', template_code='preventive_scheduled', ...)`.

## Idempotency Key
`(tenant_id, plan_id, due_window_start)` — unique partial index on the generated work-order side.

## Errors

| Code | When |
|------|------|
| 409 `preventive.duplicate_window` | Idempotent skip (returns existing service-order id). |
| 422 `preventive.invalid_cadence` | Cadence shape invalid. |
