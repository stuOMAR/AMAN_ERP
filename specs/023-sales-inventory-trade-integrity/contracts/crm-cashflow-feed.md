# Contract: CRM → Cash-Flow Feed

**Module**: `services/crm/cashflow_feed.py`
**Endpoint**: `GET /crm/cashflow-forecast?window_start=...&window_end=...&currency=...`.

## Purpose

Expose probability-weighted CRM forecast as a stream that the finance cash-flow forecaster consumes — without coupling the two modules tightly.

## Behavior

For each open opportunity in the requested window:

- Bucket key = `expected_close_date`.
- Contribution = `expected_value × probability` (probability sourced from `opportunity_stage.probability` or explicit override).
- Convert to requested currency via canonical FX service at `expected_close_date` (or today if rate not available, with a warning).

Returns:

```
{
  "currency": "...",
  "buckets": [
    { "date": "YYYY-MM-DD", "expected_inflow": <Decimal>, "opportunity_count": <int> },
    ...
  ]
}
```

Buckets cover every day in the window (zero-fill).

## Inputs

- `window_start`, `window_end` — required, `window_end ≤ window_start + crm.cashflow_horizon_days`.
- `currency` — defaults to tenant's reporting currency.

## Errors

- `422 crm.cashflow.window_too_long` if window exceeds horizon.

## Concurrency

Read-only.

## Audit

Not audited.
