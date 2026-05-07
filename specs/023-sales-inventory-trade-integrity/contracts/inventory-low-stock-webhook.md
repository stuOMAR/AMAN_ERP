# Contract: Inventory `low_stock` Webhook

**Module**: `services/inventory/low_stock_webhook.py`.

## Purpose

Emit `inventory.low_stock` once per `(item_id, warehouse_id, calendar_day)` whenever on-hand falls below the reorder point. Delegate delivery to the unified webhook dispatcher (owned by R6).

## Behavior

1. After every inventory_transactions write that decrements `(item, warehouse)`, compute new available.
2. If `available < reorder_point`:
   - Compute Redis key `lowstock:<tenant>:<item>:<warehouse>:<yyyymmdd>`.
   - `SET NX EX <inventory.low_stock_debounce_hours × 3600>`.
   - If set succeeded → call `webhooks.dispatch('inventory.low_stock', payload)`.

## Payload

```
{
  "tenant_id": ...,
  "item_id": ...,
  "warehouse_id": ...,
  "available": <Decimal>,
  "reorder_point": <Decimal>,
  "preferred_supplier_id": <int|null>,
  "occurred_at": "..."
}
```

## Errors

Webhook dispatcher errors are absorbed; the inventory transaction is not rolled back.

## Audit

Audit on debounce miss is suppressed; audit on dispatch is delegated to the dispatcher.
