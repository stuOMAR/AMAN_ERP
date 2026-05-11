# API Contracts: Purchase Lifecycle Integrity Overhaul

**Date**: 2026-05-10
**Feature**: 028-purchase-lifecycle-integrity

## Changed Endpoints

### POST `/api/v1/purchases/orders/{id}/receive`

**Changes**: Add `FOR UPDATE` lock on PO lines. Validate remaining quantity atomically. Use receipt-level `source_id` for GRNI journal entries.

**Request** (unchanged):
```json
{
  "warehouse_id": 1,
  "items": [
    { "line_id": 10, "quantity": 5 },
    { "line_id": 11, "quantity": 3 }
  ]
}
```

**New error responses**:
- `409 Conflict`: `"تم استلام الكمية المطلوبة بالفعل لهذا السطر"` — PO line already fully received
- `409 Conflict`: `"الكمية المطلوبة تتجاوز المتبقي للاستلام"` — Requested quantity exceeds remaining

**Success response** (unchanged):
```json
{
  "success": true,
  "message": "تم استلام أمر الشراء بنجاح",
  "receipt_id": 12345,
  "data": { ... }
}
```

### POST `/api/v1/purchases/invoices`

**Changes**: Store `po_line_id` on invoice lines. Validate cumulative invoiced quantity.

**Request** — new field on each line item:
```json
{
  "supplier_id": 1,
  "invoice_date": "2026-05-10",
  "original_invoice_id": 100,
  "items": [
    {
      "product_id": 10,
      "po_line_id": 501,
      "quantity": 5,
      "unit_price": 100.00
    }
  ]
}
```

**New error responses**:
- `400 Bad Request`: `"تم فوترة الكمية المستلمة بالفعل لهذا السطر"` — PO line already fully invoiced
- `400 Bad Request`: `"الكمية المفوترة تتجاوز الكمية المستلمة"` — Invoiced qty exceeds received qty

### POST `/api/v1/purchases/returns`

**Changes**: Use actual cost from cost layers for GL posting. Update supplier balance with positive sign.

**Request** (unchanged):
```json
{
  "supplier_id": 1,
  "original_invoice_id": 200,
  "items": [
    { "product_id": 10, "quantity": 2, "unit_price": 100.00 }
  ]
}
```

**Behavioral changes** (no schema change):
- GL inventory credit uses cost layer cost (not invoice price)
- Price difference posted to variance account
- Supplier balance updated with positive amount (was negative)

### POST `/api/v1/purchases/payments`

**Changes**: Lock individual balance rows. Support refund allocations to purchase returns.

**Request** — allocation to purchase return now works:
```json
{
  "supplier_id": 1,
  "amount": 500.00,
  "voucher_type": "refund",
  "allocations": [
    { "invoice_id": 300, "amount": 500.00 }
  ]
}
```

**New error responses**:
- `400 Bad Request`: `"الفاتورة مدفوعة بالكامل"` — Invoice already fully paid

### GET `/api/v1/purchases/orders/{id}`

**Changes**: Response includes `remaining_to_invoice` per line.

**New field in response**:
```json
{
  "lines": [
    {
      "id": 501,
      "product_id": 10,
      "quantity": 10,
      "received_quantity": 8,
      "invoiced_quantity": 5,
      "remaining_to_invoice": 3
    }
  ]
}
```

### POST `/api/v1/landed-costs`

**Changes**: Aligned DTO. Frontend sends `purchase_order_id` instead of `reference_type`/`reference_id`.

**Request**:
```json
{
  "purchase_order_id": 100,
  "lc_date": "2026-05-10",
  "allocation_method": "by_value",
  "cost_items": [
    { "cost_type": "freight", "amount": 500.00, "vendor_id": 5 }
  ]
}
```

## New Database View

### `supplier_subledger`

Queryable view for AP reports. No API endpoint change — reports query the view directly.

```sql
SELECT document_type, document_number, document_date, debit, credit, currency
FROM supplier_subledger
WHERE party_id = 1 AND branch_id = 1
ORDER BY document_date;
```

## Stock Movement Report Filter

**Change**: Filter now accepts additional types:
- `'purchase_receipt'` (was `'purchase_in'`)
- `'purchase_invoice'` (new)
- `'purchase_return'` (existing but not in filter map)

**No API schema change** — the filter parameter values are expanded.
