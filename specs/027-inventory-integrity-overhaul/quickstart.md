# Quickstart: Inventory Costing and GL Integration Overhaul

**Feature**: 027-inventory-integrity-overhaul
**Date**: 2026-05-09

## Prerequisites

- PostgreSQL 15 database with tenant schema
- Python 3.12 with FastAPI, Pydantic v2
- Access to `CostingService` (`backend/services/costing_service.py`)
- Access to `gl_service` (`backend/services/gl_service.py`)

## Quick Verification

After implementation, verify these critical flows:

### 1. Sales Invoice Rejects Without Inventory

```bash
# Create a sales invoice for a product with no inventory row
curl -X POST /api/sales/invoices -d '{
  "items": [{"product_id": 999, "quantity": 1, "unit_price": 100}]
}'
# Expected: 400 with "No inventory record found"
# Verify: No invoice or JE created in database
```

### 2. Concurrent Sales — Only One Succeeds

```bash
# Terminal 1 & 2 simultaneously:
curl -X POST /api/sales/invoices -d '{
  "items": [{"product_id": 1, "quantity": 1, "unit_price": 100}]
}'
# Expected: One succeeds (200), one fails (400 insufficient stock)
# Verify: inventory.quantity = 0, exactly 1 invoice created
```

### 3. FIFO Layer Consumption

```bash
# Setup: Purchase 10@5 and 10@7 for FIFO product
# Sell 12 units
# Verify: COGS = (10×5) + (2×7) = 64
# Verify: Remaining layer = 8@7
# Verify: cost_layer_consumptions has 2 records
```

### 4. Cancellation Restores Layers

```bash
# Complete a FIFO sale, then cancel the invoice
# Verify: cost_layers.remaining_quantity restored
# Verify: inventory.quantity increased
# Verify: reverse inventory_transactions with reference_type='sales_cancellation'
# Verify: GL has voided reversal entries
```

### 5. PO Receipt + Invoice — No Duplicate Transactions

```bash
# Receive PO for 10 units
# Verify: inventory_transactions has 1 'purchase_in' row
# Create purchase invoice for same PO
# Verify: inventory_transactions does NOT have a second 'purchase' row for quantity
# Verify: Only price-variance/GRNI JE posted for already-received quantity
# Verify: Any layer quantity already consumed before invoice kept its original cost
```

### 6. Shipment In-Transit

```bash
# Create and dispatch a shipment
# Verify: source inventory.quantity decreased
# Verify: source inventory.in_transit_quantity increased
# Verify: GL has Dr In-Transit / Cr Source Inventory
# Receive the shipment
# Verify: in_transit_quantity decreased
# Verify: destination quantity increased
# Verify: GL has Dr Destination / Cr In-Transit
```

### 7. Manufacturing — Concurrent Completion

```bash
# Start a production order, then attempt 2 parallel completions
# Expected: One succeeds (200), one fails (409 locked)
# Verify: FG cost layer created
# Verify: inventory.average_cost updated
```

### 8. Cycle Count Auto-Adjust

```bash
# Run cycle count auto-adjust on a product with reserved stock
# Verify: No SQL column-reference errors
# Verify: Adjustment uses reserved_quantity and available_quantity columns
```

## Key Files to Modify

| File | Changes | FR |
|------|---------|-----|
| `backend/routers/sales/invoices.py` | Available-quantity check, layer reversal on cancellation | FR-001, FR-002, FR-003 |
| `backend/routers/pos/orders.py` | Remove silent fallback, add layer reversal on return | FR-002, FR-003 |
| `backend/routers/purchases/orders.py` | Create provisional cost layer on receipt | FR-004 |
| `backend/routers/purchases/invoices.py` | Handle price variance only, no duplicate quantity | FR-004 |
| `backend/routers/inventory/adjustments.py` | Validate account mappings | FR-005 |
| `backend/routers/inventory/stock_movements.py` | Route through shared adjustment function | FR-005 |
| `backend/routers/inventory/schemas.py` | Add movement `Field(gt=0)` and price `Field(ge=0)` validations | FR-006, FR-014 |
| `backend/routers/inventory/transfers.py` | Quantity validation | FR-006 |
| `backend/routers/inventory/shipments.py` | Dispatch step, in-transit GL | FR-006, FR-007 |
| `backend/routers/inventory/batches.py` | Fix column references | FR-012 |
| `backend/routers/inventory/reports.py` | Use CostingService for valuation | FR-013 |
| `backend/routers/manufacturing/core/orders.py` | Use CostingService, lock order | FR-009, FR-010 |
| `backend/services/costing_service.py` | Add WAC locks and return restored cost details | FR-003, FR-008 |
| `backend/services/inventory/wac_per_warehouse.py` | Fix column references | FR-011 |
| `backend/schemas/purchases.py` | Add `Field(gt=0)` validations | FR-014 |
| `backend/routers/reports/inventory.py` | Use CostingService, validate branch access | FR-013 |
