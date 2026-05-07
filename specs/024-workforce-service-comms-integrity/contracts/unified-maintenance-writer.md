# Contract: Unified Maintenance Writer

## Helper

`services/fsm/maintenance/unified_writer.py::create_work_order(source: 'asset'|'service'|'shopfloor', ...) -> service_order_id`

## Behavior

- All maintenance silos (asset module, service module, shopfloor maintenance) MUST call this helper.
- Writes one canonical row in `service_orders` with `kind='preventive'` (or `'break_fix'`) and `source_silo` tag.
- Posts inventory consumption (parts) via the canonical inventory writer (uses 023's `wac_per_warehouse`).
- Posts GL via `gl_service` under `JESource.SERVICE_INVOICE` when invoiced.

## Compatibility Views

For one release, `asset_maintenance_orders` and `shopfloor_maintenance_orders` are exposed as VIEWs over `service_orders` filtered by `source_silo`. Callers reading these views see no behavior change; writes through the views are forbidden (no rules; the underlying tables are dropped).

## CI Lint

`scripts/check_maintenance_writers.py` — flag any direct `INSERT INTO asset_maintenance_orders` / `shopfloor_maintenance_orders` / direct manipulation of legacy maintenance tables outside `unified_writer.py`.
