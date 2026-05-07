# Contract: POS Offline Reconcile

**Module**: `services/pos/pos_offline_reconcile.py`
**Endpoints**: `POST /pos/offline/batches`, `GET /pos/offline/batches?device_id=...`, `POST /pos/offline/batches/{id}/retry`.
**Permission**: `pos.offline.submit` (device-scoped), `pos.offline.admin` (sensitive — admin retries).

## Purpose

Capture sales committed offline by a POS device, persist them idempotently, and replay them through the same online commit code path. Failures land in `manual_review` with a structured reason — never silently dropped.

## Inputs

- `POST /pos/offline/batches`:
```
{
  "device_id": "...",
  "batches": [
    {
      "client_uuid": "<uuid>",
      "occurred_at": "...",
      "warehouse_id": <int>,
      "lines": [...], "payments": [...], "taxes": [...]
    },
    ...
  ]
}
```

The server inserts each batch with `INSERT ... ON CONFLICT (tenant_id, device_id, client_uuid) DO NOTHING`. Re-submission is safe.

## Output

- `200 OK`: `{ "queued": n, "duplicates": m }`.

## Worker behavior

1. Pick `queued` rows whose `queued_at < now() - <small grace>`, `FOR UPDATE SKIP LOCKED`, batch size = 50.
2. Mark `state='reconciling'`.
3. Acquire `pos_stock_lock(warehouse_id)`.
4. Re-validate stock under current state.
5. Re-resolve prices/taxes if `payload.snapshot_pricing=false`. Mismatch with `payload.expected_unit_price` ⇒ `manual_review` with `pricing_mismatch`.
6. Re-check fiscal period; closed period without policy ⇒ `manual_review`/`closed_period`.
7. On success: run online commit code path (same module the live POS uses) with `idempotency_key = client_uuid`. Write `pos_sale_id` back; state `committed`; emit audit.
8. On hard failure (validation error from inputs we cannot ever recover from): state `failed`.
9. Stale batches (older than `pos.offline_batch_max_age_hours`) are routed straight to `manual_review` with `stale_batch`.

## Errors

- `409 pos.offline.duplicate` — already committed under same `client_uuid`.
- `423 pos.offline.locked` — temporary `pos_stock_lock` contention; row stays `queued` for retry.

## Concurrency

`(tenant_id, device_id, client_uuid)` is unique → idempotency.
`FOR UPDATE SKIP LOCKED` allows multiple workers safely.

## Audit

- `pos.offline.batch_committed`, `pos.offline.batch_manual_review`, `pos.offline.batch_failed` (all with sanitized `failure_detail`).
