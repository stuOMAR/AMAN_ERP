# Contract: Production Completion (Partial, Actual Cost)

**Module**: `services/manufacturing/production_complete.py`.
**Endpoint**: `POST /manufacturing/orders/{id}/complete` (sensitive).

## Purpose

Replace the all-or-nothing planned-cost completion with a partial-completion path that posts JEs at **actual** cost per batch, against the BOM **snapshot** taken at MO start.

## Inputs

```
{
  "qty": <Decimal>,                  // ≤ remaining_qty
  "warehouse_id": <int>,             // FG warehouse
  "labor_minutes_by_employee": {...},
  "overhead_minutes_by_workstation": {...},
  "scrap_lines": [ { item_id, qty, reason }, ... ],
  "byproduct_lines": [ { item_id, qty }, ... ]
}
```

## Behavior

1. Validate `mo.state ∈ {released, in_progress, qc_pending}`.
2. Validate `qty ≤ mo.remaining_qty` and `qty ≤ planned_qty × (1 + mfg.yield_tolerance)`.
3. Inside `transactional()` with row lock on MO:
   - For each input in BOM snapshot, consume `bom_qty_per_unit × qty / yield_pct` from the configured input warehouse via `wac_per_warehouse.apply_outbound`.
   - Compute `actual_material_cost = Σ outbound_cost`.
   - Compute `actual_labor_cost = Σ minutes × rate` from attendance link (if enabled). Else use `planned_labor_cost × (qty / planned_qty)`.
   - Compute `actual_overhead_cost = Σ minutes × workstation.overhead_rate (or global)`.
   - Determine FG qty = `qty − Σ scrap_lines.qty − Σ byproduct_lines.qty`. By-products allocated per `byproduct_allocator`.
   - `wac_per_warehouse.apply_inbound(fg_item, fg_warehouse, fg_qty, total_actual_cost / fg_qty)`.
   - For each scrap line: `wac_per_warehouse.apply_outbound(scrap input)` and `gl_service.post(source='mfg_scrap', ...)` — also writes a `scrap_movements` row.
   - For each by-product line: `wac_per_warehouse.apply_inbound(...)` at allocated cost; `gl_service.post(source='mfg_byproduct', ...)`.
   - `gl_service.post(source='mfg_completion', source_id=mo.id, ...)` — DR FG, CR WIP — for the FG amount.
   - Insert `production_completions` row.
   - Decrement `mo.remaining_qty -= qty`.
   - If `mo.remaining_qty == 0`:
     - If `qc_required` → `state='qc_pending'`.
     - Else → `state='completed'`.
4. Audit-write.

## Errors

- `409 mfg.completion.qty_exceeds_remaining`.
- `409 mfg.completion.yield_tolerance_exceeded`.
- `423 fiscal.period_locked` when posting period closed.
- `409 mfg.missing_account_mapping` when policy=`block` and a mapping is unresolved (else warning).

## Concurrency

Row lock on MO; per-warehouse stock locks via WAC service callers.

## Audit

`mfg.production.completed` (per batch), with sanitized payload.
