# Data Model: Purchase Lifecycle Integrity Overhaul

**Date**: 2026-05-10
**Feature**: 028-purchase-lifecycle-integrity

## Schema Changes

### Modified Tables

#### `invoice_lines` — Add PO Line Linkage

**New column**:
- `po_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE SET NULL` — Links each invoice line to the specific PO line it invoiced. Nullable for direct (non-PO) invoices.

**New index**:
- `idx_invoice_lines_po_line_id ON invoice_lines(po_line_id)`

**Validation**: When `po_line_id` is set, the invoice line's `product_id` must match the PO line's `product_id`. Cumulative invoiced quantity across all invoice lines referencing the same `po_line_id` must not exceed `purchase_order_lines.received_quantity`.

#### `inventory_transactions` — Standardize Transaction Types

**Change**: Standardize `transaction_type` values:
- PO receipt: `'purchase_receipt'` (was `'purchase_in'`)
- Direct purchase invoice: `'purchase_invoice'` (was `'purchase'`)
- Purchase return: `'purchase_return'` (unchanged)

**No DDL change** — the column is `VARCHAR(50)`. The change is in application code.

#### `purchase_order_lines` — Add Invoiced Quantity Tracking

**New column**:
- `invoiced_quantity DECIMAL(18,4) DEFAULT 0` — Tracks cumulative invoiced quantity per PO line. Updated atomically when invoice lines are created/voided.

**Validation**: `invoiced_quantity <= received_quantity` (enforced at application level with `FOR UPDATE` lock).

### New Database Objects

#### View: `supplier_subledger`

Unifies all supplier-facing document types for AP reporting. Each row represents a monetary movement affecting a supplier balance.

**Columns**:
- `party_id INTEGER` — Supplier party ID
- `branch_id INTEGER` — Branch ID
- `currency VARCHAR(10)` — Document currency
- `document_type VARCHAR(30)` — One of: `purchase_invoice`, `purchase_return`, `credit_note`, `debit_note`, `payment`, `refund`, `landed_cost`
- `document_id INTEGER` — Source document ID
- `document_number VARCHAR(50)` — Source document number
- `document_date DATE` — Source document date
- `debit DECIMAL(18,4)` — Amount increasing what we owe supplier (payments, returns, credit notes)
- `credit DECIMAL(18,4)` — Amount decreasing what we owe supplier (invoices)
- `base_debit DECIMAL(18,4)` — Debit in base currency
- `base_credit DECIMAL(18,4)` — Credit in base currency
- `exchange_rate DECIMAL(18,6)` — Exchange rate at document time

**Sources** (UNION ALL):
1. `invoices` WHERE `invoice_type = 'purchase'` → credit = total, debit = 0
2. `invoices` WHERE `invoice_type = 'purchase_return'` → credit = 0, debit = total
3. `invoices` WHERE `invoice_type IN ('credit_note', 'debit_note')` → per sign convention
4. `payment_vouchers` WHERE `voucher_type = 'payment'` → credit = 0, debit = amount
5. `payment_vouchers` WHERE `voucher_type = 'refund'` → credit = 0, debit = amount
6. Landed cost AP entries from `party_transactions` WHERE `reference_type = 'landed_cost'`

### Existing Tables (Reference)

These tables are NOT modified but are central to the feature:

#### `purchase_orders`
- **Status lifecycle**: `draft` → `approved` → `partial` → `received` (or `cancelled`)
- **Locking**: `FOR UPDATE` on header during receive to prevent status races

#### `purchase_order_lines`
- `received_quantity DECIMAL(18,4) DEFAULT 0` — Updated on each receipt
- `quantity DECIMAL(18,4)` — Ordered quantity
- **Constraint**: `received_quantity + new_receive <= quantity` (atomic check with `FOR UPDATE`)

#### `cost_layers`
- `source_document_type VARCHAR(30)` — Must be `'po_receipt'` for PO receipts (not `'purchase_invoice'`)
- `source_document_id INTEGER` — Must reference the receipt record ID (not PO ID)
- **Ordering**: FIFO = `purchase_date ASC, id ASC`; LIFO = `purchase_date DESC, id DESC`

#### `party_site_balances`
- `balance DECIMAL(18,4)` — Running balance per site/branch/currency/type
- **Sign convention**: Invoice = negative (we owe), payment/return/credit note = positive (reduces what we owe)
- **Locking**: `FOR UPDATE` on individual rows (not aggregate) during payment creation

#### `journal_entries`
- `source VARCHAR(100)` — Polymorphic: `'purchase_order_receipt'`, `'purchase_invoice'`, `'purchase_return'`, etc.
- `source_id INTEGER` — Polymorphic FK to the source document
- `idempotency_key VARCHAR(255)` — Optional unique key for deduplication
- **Duplicate guard**: `(source, source_id, entry_date)` triplet must be unique

#### `inventory_transactions`
- `transaction_type VARCHAR(50)` — Standardized enum: `purchase_receipt`, `purchase_invoice`, `purchase_return`, etc.
- `reference_type VARCHAR(50)` — Polymorphic: `'purchase_order'`, `'invoice'`, etc.
- `reference_id INTEGER` — Polymorphic FK

#### `three_way_match_lines`
- `po_line_id INTEGER` — Already exists; links to PO line
- `invoice_line_id INTEGER` — Now properly linked via `invoice_lines.po_line_id`

## Entity Relationships

```
purchase_orders 1──* purchase_order_lines
purchase_order_lines 1──* invoice_lines (via po_line_id, NEW)
purchase_order_lines 1──* cost_layers (via source_document_type='po_receipt')
purchase_orders 1──* inventory_transactions (via reference_type='purchase_order')
invoices 1──* invoice_lines
invoices 1──* journal_entries (via source='purchase_invoice', source_id=invoice.id)
invoices 1──* three_way_matches (via invoice_id)
three_way_matches 1──* three_way_match_lines
party_sites 1──* party_site_balances
party_site_balances *──1 branches (via company_branch_id)
```

## State Transitions

### Purchase Order Status
```
draft → approved → partial → received
draft → cancelled
approved → cancelled (if no receipts)
partial → cancelled (if all receipts reversed — edge case)
```

### Invoice Status
```
draft → posted → paid → cancelled
draft → cancelled
posted → cancelled (if no payments allocated)
```

### Cost Layer Lifecycle
```
Created (on PO receipt) → Partially consumed (on sale/return) → Exhausted (remaining_quantity = 0)
Created → Reversed (on purchase return, remaining_quantity reduced)
```

## Validation Rules Summary

| Entity | Rule | Enforcement |
|--------|------|-------------|
| PO receive | `received_quantity + new_qty <= quantity` | `FOR UPDATE` + atomic check |
| PO invoice | `SUM(invoiced_quantity) <= received_quantity` per PO line | `FOR UPDATE` + cumulative check |
| Return | `return_qty <= (invoiced_quantity - already_returned)` | `FOR UPDATE` + check |
| Cost layer | `remaining_quantity >= 0` | DB CHECK constraint |
| Supplier balance | Sign matches document type | Write-time validation |
| GL journal | `SUM(debit) = SUM(credit)` within 0.01 | Deferred constraint trigger |
| Fiscal period | Period not locked | `FOR UPDATE` on `fiscal_period_locks` |
