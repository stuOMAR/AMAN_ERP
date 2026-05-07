# Contract: CRM Velocity & Funnel

**Module**: `services/crm/velocity.py`, `services/crm/funnel.py`.
**Tables read**: `opportunities`, `opportunity_stage_history`.

## Purpose

Replace heuristic CRM metrics (`updated_at − created_at` etc.) with deterministic formulas backed by stage history.

## Sales Velocity

`velocity(pipeline_id, window_days) = (won_value × win_rate) / avg_cycle_days`

- `won_value` — `Σ value` of opportunities transitioning to `won` within the window.
- `win_rate` — `count(won) / count(closed)` within the window, where `closed = won ∪ lost`.
- `avg_cycle_days` — `avg(entered_at(won) − entered_at(first_stage))` over won opportunities in the window.

If `closed = 0` for the window: `velocity = 0` and the response includes `confidence='insufficient_data'`.

## Funnel Conversion

`conversion(pipeline_id, from_stage, to_stage, window_days)`
`= count(transitions from_stage→to_stage in window) / count(opportunities entering from_stage in window)`

Returns 0 with `confidence='insufficient_data'` when the denominator is 0.

## Inputs / outputs

- `GET /crm/velocity?pipeline_id=...&window_days=90` → `{ velocity, won_value, win_rate, avg_cycle_days, confidence }`.
- `GET /crm/funnel?pipeline_id=...&window_days=90` → `[ { from, to, conversion_rate, confidence }, ... ]`.

## Determinism

Pure functions of `opportunity_stage_history`. Fixture-based regression tests (when added) verify exact numeric outputs.

## Audit

Read-only; not audited beyond standard request log.
