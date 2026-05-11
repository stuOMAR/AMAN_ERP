# API Contracts: Inventory Costing and GL Integration Overhaul

**Feature**: 027-inventory-integrity-overhaul
**Date**: 2026-05-09

## Overview

This feature mostly modifies existing API endpoints and adds an explicit shipment dispatch endpoint. The contracts below document the **behavioral changes** to existing endpoints and the new dispatch transition.

## Changed Endpoints

### Sales Invoices

#### POST /api/sales/invoices

**Current Behavior**: Creates invoice even if inventory row missing; deducts `quantity` only; FIFO/LIFO failure silently falls back to `cost_price`.

**New Behavior**:
1. Rejects if no `inventory` row exists for product+warehouse
2. Rejects if `quantity - COALESCE(reserved_quantity, 0) < requested_qty` (authoritative available check)
3. Uses an atomic `UPDATE ... WHERE quantity - COALESCE(reserved_quantity, 0) >= :qty RETURNING id` — fails if no row returned
4. `CostingService.consume_layers` failure raises error — no fallback to `cost_price`

**Error Responses**:
- `400 INSUFFICIENT_STOCK`: Product {product_id} has insufficient available stock ({available} available, {requested} requested)
- `400 NO_INVENTORY_ROW`: No inventory record found for product {product_id} in warehouse {warehouse_id}
- `400 COST_LAYER_EXHAUSTED`: Insufficient cost layers for product {product_id} — FIFO/LIFO layer deficit

#### POST /api/sales/invoices/{id}/cancel

**Current Behavior**: Adds quantity back to inventory; reverses GL; does NOT reverse cost layers.

**New Behavior**:
1. Calls `CostingService.handle_return(db, product_id, warehouse_id, quantity, unit_cost=<original line unit_cost>, source_document_type='sales_cancellation', source_document_id=<cancellation_or_invoice_id>, original_source_document_type='sales_invoice', original_source_document_id=invoice_id)` to restore consumed layers
2. Adds quantity back to inventory (existing behavior)
3. Registers reverse `inventory_transactions` with `reference_type='sales_cancellation'`
4. Reverses GL entries (existing behavior)

---

### POS Orders

#### POST /api/pos/orders

**Current Behavior**: FIFO/LIFO failure silently falls back to `cost_price`.

**New Behavior**: Same as sales invoices — `consume_layers` failure raises error.

#### POST /api/pos/orders/{id}/return

**Current Behavior**: Adds quantity back; uses `cost_price` for COGS reversal; does NOT reverse cost layers.

**New Behavior**:
1. Calls `CostingService.handle_return(db, product_id, warehouse_id, quantity, unit_cost=<original line unit_cost>, source_document_type='pos_return', source_document_id=return_id, original_source_document_type='pos_order', original_source_document_id=order_id)` to restore consumed layers
2. Uses `restored_unit_cost`/`restored_total_cost` from `handle_return` for COGS reversal (not `cost_price`)
3. Registers reverse `inventory_transactions` with `reference_type='pos_return'`

---

### Purchase Orders

#### POST /api/purchases/orders/{id}/receive

**Current Behavior**: Adds quantity to inventory; logs `purchase_in`; posts accrual GL; does NOT create cost layer or update WAC.

**New Behavior**:
1. Adds quantity to inventory (existing behavior)
2. Creates a **provisional cost layer** with `source_document_type='po_receipt'` at the PO unit price
3. For WAC products: calls `CostingService.update_cost` at the PO price
4. Posts accrual GL (existing behavior)
5. Logs `purchase_in` transaction (existing behavior)

#### POST /api/purchases/invoices

**Current Behavior**: Creates cost layer at invoice price (even for already-received quantities); logs full `purchase` transaction.

**New Behavior**:
1. Splits each line into already received quantity and quantity that still needs inventory receipt
2. For already received quantity: calculates price variance = (invoice_price - receipt_price) × received_qty
3. Posts variance JE through the GRNI/variance flow without creating a second quantity movement
4. Does not mutate the unit cost of already consumed provisional layer quantities; only remaining unconsumed quantity may be adjusted or linked to a variance adjustment
5. For quantity not already received: existing direct-receipt behavior (inventory quantity, WAC/layer creation, and `inventory_transactions`)
6. No duplicate `inventory_transactions` for already-received quantities

---

### Inventory Adjustments

#### POST /api/inventory/adjustments

**Current Behavior**: Updates inventory; posts GL; no validation of account mappings.

**New Behavior**:
1. Validates that `acc_map_inventory` and `acc_map_inventory_adjustment` account mappings exist when explicit accounts are not supplied — rejects with `400 MISSING_ACCOUNT_MAPPING` if not
2. All other behavior unchanged

#### POST /api/inventory/stock-movements

**Current Behavior**: Separate code path from `/adjustments`.

**New Behavior**: Routes through the same shared function as `/adjustments` — validates account mappings, posts GL, records movement.

---

### Transfers

#### POST /api/inventory/transfers (single item)

**Current Behavior**: Accepts any quantity including negative.

**New Behavior**:
1. Validates `quantity > 0` via `Field(gt=0)` — rejects with `422 VALIDATION_ERROR` if ≤ 0
2. All other behavior unchanged

#### POST /api/inventory/transfers/multi (multi-item)

**Current Behavior**: Accepts empty items list and negative quantities.

**New Behavior**:
1. Validates `items` is non-empty — rejects with `422 VALIDATION_ERROR` if empty
2. Validates each item `quantity > 0`
3. Aggregates duplicate products (same product_id in multiple items) before execution

---

### Shipments

#### POST /api/inventory/shipments

**Current Behavior**: Creates document only; no inventory movement.

**New Behavior**:
1. Validates each item `quantity > 0` via `Field(gt=0)`
2. Validates `items` is non-empty

#### POST /api/inventory/shipments/{id}/dispatch (NEW)

**New Endpoint**:
- Locks the shipment row and allows dispatch only from the pending/approved state
- Deducts from source warehouse `quantity`, adds to source warehouse `in_transit_quantity`
- Posts GL: Dr In-Transit Inventory / Cr Source Inventory
- Updates shipment status to `dispatched`

**Error Responses**:
- `400 INSUFFICIENT_STOCK`: Source warehouse has insufficient stock for dispatch
- `400 ALREADY_DISPATCHED`: Shipment already dispatched
- `400 MISSING_ACCOUNT_MAPPING`: In-transit or inventory account mapping is missing

#### POST /api/inventory/shipments/{id}/receive

**Current Behavior**: Moves inventory directly from source to destination.

**New Behavior**:
1. Locks the shipment row and allows receipt only from `dispatched`
2. Deducts from `in_transit_quantity` on source warehouse
3. Adds to destination warehouse quantity
4. Creates destination cost layers at the costs consumed during dispatch
5. Posts GL: Dr Destination Inventory / Cr In-Transit Inventory
6. Updates shipment status to `received`

---

### Manufacturing

#### POST /api/manufacturing/orders/{id}/start

**Current Behavior**: Uses raw SQL for material consumption; no layer consumption.

**New Behavior**:
1. For each BOM material line: calls `CostingService.consume_layers` (if FIFO/LIFO) or deducts at WAC
2. Posts GL: Dr WIP / Cr Raw Materials (existing behavior)
3. All other behavior unchanged

#### POST /api/manufacturing/orders/{id}/complete

**Current Behavior**: Manually calculates WAC; updates `products.cost_price` only; no cost layer for FG.

**New Behavior**:
1. Locks production order `FOR UPDATE` — rejects if status ≠ 'in_progress'
2. Computes finished-good unit cost from posted WIP/material/labor/overhead basis
3. Calls `CostingService.update_cost` before adding finished-good inventory quantity
4. Creates cost layer for finished good via `CostingService.create_cost_layer`
5. Sets production order status to `completed`
6. Posts GL: Dr FG Inventory / Cr WIP (existing behavior)

**Error Responses**:
- `400 ORDER_NOT_IN_PROGRESS`: Production order must be in 'in_progress' status
- `409 CONCURRENT_COMPLETION`: Production order is locked by another transaction

---

### Reports

#### GET /api/inventory/reports/valuation-report

**Current Behavior**: Uses `products.cost_price` for valuation.

**New Behavior**:
1. Calls `CostingService.calculate_inventory_valuation()` which uses cost layers (FIFO/LIFO) or `inventory.average_cost` (WAC)
2. Validates `warehouse_id` access via `validate_branch_access` if warehouse filter is provided

---

### Cycle Counts

#### POST /api/inventory/batches/{id}/auto-adjust

**Current Behavior**: References non-existent columns `reserved`, `available`, `products.item_name`.

**New Behavior**: References correct columns `reserved_quantity`, `available_quantity`, `product_name`.

---

## New Validation Rules (Schema Changes)

### inventory/schemas.py

| Schema | Field | Current | New |
|--------|-------|---------|-----|
| ProductCreate | selling_price | optional | `Field(ge=0)` |
| ProductCreate | buying_price | optional | `Field(ge=0)` |
| ProductCreate | last_buying_price | optional | `Field(ge=0)` |
| StockTransferSingleCreate | quantity | optional | `Field(gt=0)` |
| StockTransferCreate | items | optional | `min_length=1` |
| ShipmentCreate | items | optional | `min_length=1` |
| ShipmentItemCreate | quantity | optional | `Field(gt=0)` |
| StockAdjustmentCreate | new_quantity | optional | `Field(ge=0)` |

### schemas/purchases.py

| Schema | Field | Current | New |
|--------|-------|---------|-----|
| PurchaseLineItem | quantity | optional | `Field(gt=0)` |
| PurchaseLineItem | unit_price | optional | `Field(gt=0)` |
| PurchaseLineItem | discount | optional | `Field(ge=0)` |
| POReceiveItem | received_quantity | optional | `Field(gt=0)` |

### inventory/batches.py

| Schema | Field | Current | New |
|--------|-------|---------|-----|
| BatchCreate | quantity | optional | `Field(ge=0)` |
