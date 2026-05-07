# Contract: Inventory Archival

**Module**: `services/inventory/archival.py`.
**Job**: scheduled daily.

## Purpose

Keep `inventory_transactions` small while preserving full history for valuation and audit.

## Behavior

1. Acquire per-tenant advisory lock.
2. `cutoff = now − inventory.retention_days`.
3. Loop in batches of 5000:
   - `WITH moved AS (DELETE FROM inventory_transactions WHERE tenant_id=? AND occurred_at < cutoff RETURNING *) INSERT INTO inventory_transactions_archive SELECT * FROM moved`.
   - Sleep briefly between batches to keep WAL/IO calm.
4. Vacuum suggestion only — do not run VACUUM here (ops job).

## Read helper

```
read_inventory_transactions(tenant_id, item_id=None, warehouse_id=None, *, since=None, until=None) -> Iterator[Row]
```

UNION ALL across the live and archive tables, with index hints; used by valuation and historical balance reports.

## Errors

Per-batch failures retry with exponential backoff up to 3 times, then alert.

## Audit

`inventory.archival.run_completed { moved, batches }`.
