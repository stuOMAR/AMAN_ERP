# Contract: Returns Unified

**Module**: `services/returns_unified_service.py`
**Tables**: `returns_unified`, `returns_unified_lines` (compatibility views: `sales_returns`, `pos_returns`).
**Endpoints**: `POST /returns`, `POST /returns/{id}/post`, `POST /returns/{id}/cancel`, `GET /returns?source=...`.

## Purpose

Replace the parallel `sales_returns` and `pos_returns` modules with one writer that handles both flavors and posts a single, classifier-resolved JE. Existing read clients see compatibility views during the deprecation window.

## Inputs

- `POST /returns` body:
```
{
  "source": "sales" | "pos",
  "original_invoice_id": <int|null>,
  "original_pos_sale_id": <int|null>,
  "restock_warehouse_id": <int|null>,
  "lines": [{ "item_id": <int>, "qty": <Decimal>, "unit_price": <Decimal>, "tax_id": <int|null> }, ...],
  "reason": "..."
}
```

## Output

- `201` returns id (state `draft`).
- `200` on `/post`, `/cancel` with state and `je_id`.

## Behavior (post path)

1. Inside `transactional()`:
   1. Validate exactly one of `original_invoice_id` / `original_pos_sale_id` is set, consistent with `source`.
   2. Inventory pre-flight only when `restock_warehouse_id` is not null; full-line check (no short-circuit).
   3. Restock via `wac_per_warehouse.apply_inbound` (using the **original** sale's recorded WAC layer; if null, use current WAC and log a warning).
   4. Resolve accounts via `account_mapping.resolve(mapping_kind='sales_return', ...)`.
   5. `gl_service.post(source='sales_return' | 'pos_return', source_id=return_id, ...)`.
   6. Update state to `posted`, write audit.
2. Cancel path simply transitions `posted → cancelled` and reverses the JE.

## Errors

- `409 returns.already_posted` — state guard.
- `409 returns.shortage` — when `restock_warehouse_id` is set but a destination line cannot accept (e.g., warehouse closed, item blocked).
- `422 returns.line_qty_exceeds_original` — return qty > original qty minus prior returns.

## Concurrency

`(tenant_id, original_invoice_id)` and `(tenant_id, original_pos_sale_id)` are partial-unique on **state=draft** at a per-source-row level: only one open draft return allowed per source row at a time, to avoid duplicate-return races.

## Audit

- Activity types: `sales.return.created`, `sales.return.posted`, `sales.return.cancelled` (same set with `pos.` prefix when source=pos).
