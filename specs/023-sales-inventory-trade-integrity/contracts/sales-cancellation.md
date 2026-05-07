# Contract: Sales / POS Cancellation

**Module**: `services/sales/sales_cancellation.py`
**Endpoints**: `POST /sales/invoices/{id}/cancel`, `POST /pos/sales/{id}/cancel`.
**Permission**: `sales.invoice.cancel`, `pos.sale.cancel` (sensitive).

## Purpose

Cancel a posted sales invoice or POS sale **only** when the full set of issued items can be returned to stock without violating warehouse policy. Reverse the GL via `(source, source_id)`. Restore stock atomically.

## Inputs

- Path id, body `{ "reason": "...", "restock_warehouse_id": <int|null> }`.
- `restock_warehouse_id=null` ⇒ scrap-on-cancel; otherwise the named warehouse must accept the line.

## Output

- `200 OK` with reversal JE id and updated invoice/sale.
- `409 inventory.preflight_failed` — body lists ALL short lines (no first-line short-circuit). Format:

```
{
  "code": "inventory.preflight_failed",
  "shortages": [
    {"item_id": 1, "warehouse_id": 5, "required": 10, "available": 4},
    ...
  ]
}
```

- `409 cancel.cap_exceeded` — restock would exceed `inventory.cancel_restock_cap_pct` over original sale qty.
- `423 fiscal.period_locked` if the original posting period is closed and the policy forbids reversal there.

## Behavior

1. Inside `transactional()`:
   1. Acquire per-warehouse Redis lock (POS) / row lock (Sales) on affected stock keys.
   2. Run `inventory_preflight(lines)` collecting **all** shortages; abort on any.
   3. Restore stock via `wac_per_warehouse.apply_inbound(...)` per line at the layer's recorded WAC (recorded at original sale).
   4. Call `invoice_state.transition(invoice, 'cancelled', ...)`. The state machine performs `gl_service.reverse(source_je_id, source='sales_invoice_cancel', source_id=invoice.id)`.
   5. Audit-write.
2. Returns reversal JE id.

## Errors

All shortages reported in one response. The cap is read from `company_settings`.

## Concurrency

Cancellation acquires the same locks the original commit used. POS Redis lock is required (lint enforced) for POS path.

## Audit

- Activity type: `sales.invoice.cancelled` / `pos.sale.cancelled`.
- Audited fields: `invoice_id`, `reason`, `restock_warehouse_id`, `reversal_je_id`, `lines_restocked`.
