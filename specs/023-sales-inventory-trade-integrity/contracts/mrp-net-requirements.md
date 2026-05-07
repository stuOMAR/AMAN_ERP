# Contract: MRP Net Requirements

**Module**: `services/manufacturing/mrp.py`.
**Endpoint**: `POST /manufacturing/mrp/run` (sensitive).
**Job**: scheduled at `mfg.mrp_interval_minutes` if enabled.

## Purpose

Compute net material requirements over a horizon, exploding multi-level BOMs with yield + scrap %, and generate consolidated MRP recommendations. Detect cycles deterministically.

## Inputs

- `horizon_days` (default `mrp.horizon_days`).
- Optional list of `item_ids` to scope.
- Sources of demand: `sales_orders` (open + within horizon), `forecasts.confirmed_demand`.

## Behavior

1. Build dependency graph from `bom_lines` for in-scope items; run Tarjan SCC. Any SCC of size > 1 ⇒ raise `BomCycleError(path=[...])`.
2. For each demand item, compute net = `gross_demand − on_hand − on_order + safety_stock`.
3. Explode net through BOM levels, applying `yield_pct` and `scrap_pct` per line.
4. Aggregate per `(item_id, warehouse_id)`. Warehouse defaults to the item's primary; otherwise `item_warehouse_settings.preferred_warehouse_id`.
5. Persist into `mrp_recommendations` with shared `run_id` (UUID).
6. Optionally convert (per supplier) into draft POs when caller specifies `auto_create=true`.

## Performance

10000 items ≤ 5 minutes. Algorithm: topological order over the SCC-collapsed DAG; arithmetic in `Decimal`.

## Errors

- `BomCycleError(path=[...])` — actionable, includes cycle path.
- `MissingItemDemand` — when scope filter excludes all items.

## Concurrency

Per-tenant advisory lock prevents concurrent runs from interleaving.

## Audit

`mfg.mrp.run_started`, `mfg.mrp.run_completed`, `mfg.mrp.cycle_detected`.
