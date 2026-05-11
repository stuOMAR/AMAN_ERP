# Quickstart: Purchase Lifecycle Integrity Overhaul

**Date**: 2026-05-10
**Feature**: 028-purchase-lifecycle-integrity

## Prerequisites

- PostgreSQL 15+ with tenant schema support
- Python 3.12 with `decimal` module
- Alembic installed and configured (`backend/alembic.ini`)
- Node.js 18+ for frontend

## Setup Steps

### 1. Run Database Migration

```bash
cd backend
alembic -x company=all upgrade head
```

This adds the `po_line_id` column to `invoice_lines` and `invoiced_quantity` to `purchase_order_lines`.

### 2. Create Supplier Subledger View

The migration also creates the `supplier_subledger` database view. Verify:

```sql
SELECT * FROM supplier_subledger WHERE party_id = 1 LIMIT 10;
```

### 3. Verify Decimal Precision

All `_dec()` helpers should import from `backend/utils/decimal_helper.py`. Run the linter:

```bash
cd backend
ruff check --select F401 routers/purchases/ services/
```

### 4. Verify Frontend Schema Alignment

Check that `LandedCosts.jsx` sends `purchase_order_id` (not `reference_type`):

```bash
cd frontend
npm run build
```

## Verification Checklist

- [ ] Create a PO with 2 lines (same product, different prices), receive both, invoice partially → matching uses correct PO line
- [ ] Two concurrent receive attempts on same PO line → exactly one succeeds
- [ ] Purchase return after partial sale → correct cost layer reversed (FIFO order)
- [ ] Supplier payment with refund allocation to purchase return → accepted
- [ ] AP aging report includes returns, credit notes, and landed costs
- [ ] VAT report includes credit notes
- [ ] Stock movement report shows purchase_receipt and purchase_invoice transactions
- [ ] "Convert to Invoice" button disabled when no uninvoiced quantity remains
- [ ] New tenant can complete full PO → Receive → Invoice → Return → Payment → Reports flow

## Key Files to Review

| File | Change Summary |
|------|---------------|
| `backend/routers/purchases/orders.py` | Add `FOR UPDATE` on PO lines, unique receipt source_id for GRNI |
| `backend/routers/purchases/invoices.py` | Store `po_line_id`, cumulative invoiced check, Decimal precision |
| `backend/routers/purchases/returns.py` | Fix cost layer source, actual cost GL posting, positive sign for balance |
| `backend/routers/purchases/payments.py` | Fix locking granularity, support refund to returns |
| `backend/services/costing_service.py` | Fix FIFO ordering in `handle_return()` |
| `backend/services/matching_service.py` | Match by `po_line_id` instead of `product_id` |
| `backend/utils/party_balance.py` | Accept Decimal, add sign validation |
| `backend/db_ddl/tenant_schema.py` | Add `po_line_id` to `invoice_lines`, `invoiced_quantity` to PO lines |
| `backend/alembic/versions/` | New migration for schema changes |
| `frontend/src/pages/Buying/LandedCosts.jsx` | Align DTO with backend |
| `frontend/src/pages/Buying/BuyingOrderDetails.jsx` | Disable convert-to-invoice when no uninvoiced qty |
