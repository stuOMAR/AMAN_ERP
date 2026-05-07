# Contract: Auto-Reorder Scheduler

**Module**: `services/inventory/auto_reorder.py`.
**Job**: scheduled — every `inventory.auto_reorder_interval_minutes` (default 60).

## Purpose

Detect `(item, warehouse)` pairs whose on-hand has fallen below their reorder point, and produce `mrp_recommendations` rows (and optionally draft POs grouped per supplier).

## Behavior

1. Acquire per-tenant advisory lock.
2. Paginate through `item_warehouse_settings` rows in chunks of 1000:
   - Compute `available = on_hand + on_order − allocated_open`.
   - If `available < reorder_point`:
     - `recommended_qty = max(reorder_quantity, safety_stock + forecasted_demand_during_lead_time − available)`.
     - Insert `mrp_recommendations` row (state=`open`).
3. If `inventory.auto_reorder_enabled = true`, group recommendations by `(supplier_id, currency)` and create one draft PO per group.
4. Emit a `inventory.reorder_recommended` audit event per row.

## Performance

5000 pairs ≤ 30s; uses bulk SQL aggregate per chunk; index on `(item, warehouse)` and `inventory_transactions(occurred_at)` to keep the on_hand sub-query fast.

## Errors

Exceptions per row are caught, logged with sanitized context, do not abort the run.

## Audit

`inventory.reorder_run_completed` summary; `inventory.reorder_recommended` per recommendation.
