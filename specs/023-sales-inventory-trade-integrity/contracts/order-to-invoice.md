# Contract: Order → Invoice

**Module**: `services/sales/order_to_invoice.py`
**Endpoint**: `POST /sales/orders/{order_id}/invoice`
**Permission**: `sales.invoice.create` (sensitive — wrapped by 022's `require_sensitive_permission`).

## Purpose

Convert a confirmed `SalesOrder` into a posted `Invoice` exactly once, even under concurrent retries. This is the single supported conversion path. Direct `Invoice` creation from arbitrary callers is removed.

## Inputs

- Path: `order_id: int`.
- Header: `Idempotency-Key: <≤64 chars>` — required.
- Body: `{ "posting_date": "YYYY-MM-DD" | null, "memo": "..." | null }`.

## Output

- `200 OK` — body is the full invoice payload (id, state=`posted`, lines, totals, gl_je_id, zatca_outbox_id, ...).
- `409 conflict.idempotency_replay` — same `Idempotency-Key` already mapped to a different order or different body hash.
- `409 sales_order.already_converted` — order already has `converted_to_invoice_id`.
- `409 sales_order.invalid_state` — order is not `confirmed`.
- `422 invoice.tax_resolution_failed` — tax id missing or mapping unresolved.
- `423 fiscal.period_locked` — posting date falls in a closed period without `fiscal.allow_drafts_in_closed_period`.

## Behavior

1. Acquire connection via `get_db_connection(company_id)`.
2. Inside `transactional()`:
   1. `SELECT ... FOR UPDATE` on `sales_orders`.
   2. Check idempotency: `SELECT * FROM invoices WHERE tenant_id=? AND sales_order_id=? AND idempotency_key=?` — if found, return it.
   3. Validate `order.state = 'confirmed'` and `order.converted_to_invoice_id IS NULL`.
   4. Snapshot lines into `invoice_lines` (qty, unit_price, tax_id, tax_rate at posting_date, discount).
   5. Insert `invoices` row in state `draft` with `idempotency_key`.
   6. Call `invoice_state.transition(invoice, 'posted', actor=ctx.user, reason=None)` which posts GL via `gl_service` (source=`SALES_INVOICE`, source_id=invoice.id) and inserts the `zatca_outbox` row when ZATCA is enabled.
   7. `UPDATE sales_orders SET converted_to_invoice_id=?` (unique partial index ensures exactly-one).
   8. Audit-write via `audit_writer.log_activity` with sanitized payload.
3. Return invoice payload.

## Errors

All errors are translated through 022's `audit_sanitizer` before being logged. Stack traces never leak to the client.

## Concurrency

The two safeguards combined make the conversion exactly-once:
- `(tenant_id, sales_order_id, idempotency_key)` unique → second client retry finds the existing row.
- `converted_to_invoice_id` unique partial index → race-losing transaction raises a `UniqueViolation` that the service catches and translates to a 409.

## Audit

- Activity type: `sales.invoice.created_from_order`.
- Audited fields: `order_id`, `invoice_id`, `idempotency_key`, `total_amount`, `posting_date`. Body sanitized.
