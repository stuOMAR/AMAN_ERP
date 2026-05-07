# Contract: WAC per Warehouse

**Module**: `services/inventory/wac_per_warehouse.py`.

## Purpose

Be the canonical service for moving-weighted-average cost computations at the `(item_id, warehouse_id)` grain. Every cost-affecting movement in the system funnels through here.

## Public functions

```
apply_inbound(item_id, warehouse_id, qty, unit_cost, *, source) -> InboundResult
apply_outbound(item_id, warehouse_id, qty, *, source) -> OutboundResult
apply_transfer(item_id, src_warehouse_id, dst_warehouse_id, qty, *, source) -> TransferResult
read_wac(item_id, warehouse_id, as_of=None) -> Decimal
```

`source` is a free-form caller tag like `purchase_receipt`, `mfg_receive`, `pos_commit`, `sales_invoice`, `transfer`, `return_restock`, etc., used in audit/diagnostics.

## Inbound formula

```
new_qty   = old_qty + qty
new_cost  = ((old_qty × old_wac) + (qty × unit_cost)) / new_qty   if new_qty > 0
```

Negative resulting qty is **never** allowed — see negative-balance policy below.

## Outbound formula

Returns the unit cost used (current WAC). Qty decrements; WAC is unchanged.

## Negative balance policy

Configurable per warehouse: `inventory.allow_negative_balance` ∈ `{block, warn}` from `company_settings`. Default `block`. `warn` writes a structured warning into `inventory_warnings` and proceeds; `block` raises `NegativeBalanceForbidden`.

## Transfer

Outbound at src WAC, inbound at dst with the layer's cost (the qty's cost from src). Two GL postings (DR src in-transit / CR src inv; DR dst inv / CR src in-transit) issued by the caller via `gl_service`.

## Concurrency

The service expects the caller to hold the appropriate row-level or per-warehouse lock (Redis for POS, `SELECT FOR UPDATE` for ledger paths). The service does not acquire its own locks beyond what the underlying SQL implies.

## Errors

- `NegativeBalanceForbidden` (when policy=block and outbound would push qty below 0).
- `NoStockLayer` (when inbound qty=0 or unit_cost negative).
- `InvalidUnitCost` (when float passed — also caught by lint).

## Lint

`scripts/check_no_float_money.py` enforces Decimal in callers; this module accepts only `Decimal` typed parameters.

## Audit

Movements are written to `inventory_transactions` by the caller; this service does not audit independently.
