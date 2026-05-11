# Data Model: Inventory Costing and GL Integration Overhaul

**Feature**: 027-inventory-integrity-overhaul
**Date**: 2026-05-09

## Entities

### inventory

Per-product per-warehouse stock tracking.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| product_id | INTEGER | PK (composite), FK → products | |
| warehouse_id | INTEGER | PK (composite), FK → warehouses | |
| quantity | DECIMAL(18,4) | NOT NULL, DEFAULT 0 | On-hand quantity |
| reserved_quantity | DECIMAL(18,4) | NOT NULL, DEFAULT 0 | Reserved by open sales orders |
| available_quantity | DECIMAL(18,4) | GENERATED | = quantity - reserved_quantity |
| in_transit_quantity | DECIMAL(18,4) | NOT NULL, DEFAULT 0 | Shipped but not received |
| average_cost | DECIMAL(18,4) | NOT NULL, DEFAULT 0 | WAC per warehouse |
| policy_version | INTEGER | DEFAULT 1 | For optimistic locking |
| last_costing_update | TIMESTAMP | | Last WAC recalculation |

**Validation Rules**: quantity ≥ 0, reserved_quantity ≥ 0, in_transit_quantity ≥ 0
**State Transitions**: quantity changes via: sale (deduct), return (add), adjustment (set), transfer (deduct/add), manufacturing (deduct materials / add FG), shipment dispatch (deduct → in_transit), shipment receipt (in_transit → add dest)

**Changes Required**:
- No schema changes needed — `reserved_quantity`, `available_quantity`, `in_transit_quantity` columns already exist
- FR-008: Add `FOR UPDATE` when reading `quantity` + `average_cost` in `CostingService.update_cost`

---

### inventory_transactions

Audit trail for all inventory movements.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| product_id | INTEGER | NOT NULL, FK → products | |
| warehouse_id | INTEGER | NOT NULL, FK → warehouses | |
| transaction_type | VARCHAR(50) | NOT NULL | sale, purchase, purchase_in, return_in, adjustment_in, adjustment_out, transfer_in, transfer_out, shipment_in, shipment_out, production_in, production_out, batch_in |
| reference_type | VARCHAR(50) | | 'invoice', 'return', 'transfer', 'shipment', 'adjustment', 'production_order' |
| reference_id | INTEGER | | ID of the source document |
| reference_document | VARCHAR(100) | | Document number for display |
| quantity | DECIMAL(18,4) | NOT NULL | Positive for inbound, negative for outbound |
| balance_before | DECIMAL(18,4) | | Quantity before this transaction |
| balance_after | DECIMAL(18,4) | | Quantity after this transaction |
| unit_cost | DECIMAL(18,4) | | Cost per unit at time of transaction |
| total_cost | DECIMAL(18,4) | | = quantity × unit_cost |
| created_at | TIMESTAMP | DEFAULT NOW() | |

**Validation Rules**: quantity ≠ 0
**Changes Required**:
- FR-011: NO schema changes needed — `created_at` and `product_id` already exist
- Fix `wac_per_warehouse.py` to use `created_at` instead of `transaction_date`, `product_id` instead of `item_id`
- Add index: `CREATE INDEX IF NOT EXISTS idx_inventory_transactions_product_date ON inventory_transactions(product_id, created_at)` if not present

---

### cost_layers

FIFO/LIFO cost layers per product per warehouse.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| product_id | INTEGER | NOT NULL, FK → products | |
| warehouse_id | INTEGER | NOT NULL, FK → warehouses | |
| costing_method | VARCHAR(10) | NOT NULL | 'fifo', 'lifo', 'wac' |
| original_quantity | DECIMAL(18,4) | NOT NULL | Quantity at creation |
| remaining_quantity | DECIMAL(18,4) | NOT NULL, CHECK ≥ 0 | Decremented by consumptions |
| unit_cost | DECIMAL(18,4) | NOT NULL | Frozen cost per unit |
| source_document_type | VARCHAR(50) | | 'purchase', 'po_receipt', 'adjustment', 'production', 'return' |
| source_document_id | INTEGER | | ID of source document |
| is_exhausted | BOOLEAN | DEFAULT FALSE | TRUE when remaining_quantity = 0 |
| created_at | TIMESTAMP | DEFAULT NOW() | |

**Validation Rules**: remaining_quantity ≥ 0, unit_cost > 0, original_quantity > 0
**State Transitions**: Created on inbound (purchase, return, production) → remaining_quantity decremented on outbound (sale, transfer, production consumption) → is_exhausted = TRUE when fully consumed

**Changes Required**:
- FR-004: Add `'po_receipt'` as a valid `source_document_type` for PO receipt provisional layers

---

### cost_layer_consumptions

Records which layers were consumed by outbound movements.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| cost_layer_id | INTEGER | NOT NULL, FK → cost_layers | |
| quantity_consumed | DECIMAL(18,4) | NOT NULL, CHECK > 0 | |
| sale_document_type | VARCHAR(50) | | 'invoice', 'pos_order', 'shipment', 'production' |
| sale_document_id | INTEGER | | ID of consuming document |
| created_at | TIMESTAMP | DEFAULT NOW() | |

**Validation Rules**: quantity_consumed > 0
**Changes Required**:
- FR-003: Add `'cancellation'` and `'return'` as valid `sale_document_type` values for reversal records

---

### products

Master product data.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| product_name | VARCHAR(255) | NOT NULL | |
| cost_price | DECIMAL(18,4) | | Global cost price (used as fallback for WAC) |
| selling_price | DECIMAL(18,4) | | |
| cost_policy | VARCHAR(20) | DEFAULT 'wac' | 'fifo', 'lifo', 'wac' |

**Changes Required**:
- FR-012: Ensure `product_name` is the correct column name (not `item_name`)

---

### production_orders

Manufacturing orders.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| product_id | INTEGER | NOT NULL, FK → products | |
| quantity | DECIMAL(18,4) | NOT NULL | Target quantity |
| status | VARCHAR(20) | NOT NULL | 'draft', 'in_progress', 'completed', 'cancelled' |
| warehouse_id | INTEGER | FK → warehouses | Source warehouse for materials |
| finished_goods_warehouse_id | INTEGER | FK → warehouses | Destination for FG |

**State Transitions**: draft → in_progress (start) → completed (complete). Parallel completion must be prevented by `FOR UPDATE` lock.

**Changes Required**:
- FR-009: Add `FOR UPDATE` lock on production order at completion time
- FR-010: Use `CostingService.consume_layers` for material consumption, `create_cost_layer` + `update_cost` for FG receipt

---

### stock_adjustments

Adjustment records.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | SERIAL | PK | |
| product_id | INTEGER | NOT NULL, FK → products | |
| warehouse_id | INTEGER | NOT NULL, FK → warehouses | |
| old_quantity | DECIMAL(18,4) | NOT NULL | |
| new_quantity | DECIMAL(18,4) | NOT NULL, CHECK ≥ 0 | |
| difference | DECIMAL(18,4) | NOT NULL | = new_quantity - old_quantity |
| reason | TEXT | | |
| status | VARCHAR(20) | DEFAULT 'approved' | |
| created_at | TIMESTAMP | DEFAULT NOW() | |

**Changes Required**:
- FR-005: Both `/adjustments` and `/stock_movements` must call a shared function that validates GL account mappings and posts journal entries

---

### stock_shipments + stock_shipment_items

Shipment lifecycle documents.

| Table | Key Fields |
|-------|------------|
| stock_shipments | id, source_warehouse_id, destination_warehouse_id, status (pending/dispatched/received/cancelled), created_at |
| stock_shipment_items | id, shipment_id, product_id, quantity, unit_cost |

**Changes Required**:
- FR-006: Add `Field(gt=0)` validation on `quantity` in `stock_shipment_items`
- FR-007: Add `dispatch` step that moves inventory to `in_transit_quantity` and posts GL `Dr In-Transit / Cr Inventory`

---

### journal_entries + journal_entry_lines

GL postings linked to inventory movements.

| Table | Key Fields |
|-------|------------|
| journal_entries | id, source (e.g., 'Sales-Invoice'), source_id, status (posted/void), created_at |
| journal_entry_lines | id, journal_entry_id, account_id, debit, credit |

**Changes Required**: None — existing structure supports all required GL postings.

---

### account_mappings / company_settings

Maps inventory events to GL accounts.

| Key | Purpose |
|-----|---------|
| acc_map_inventory | Inventory Asset account |
| acc_map_cogs | Cost of Goods Sold account |
| acc_map_inventory_adjustment | Inventory Adjustment account |
| acc_map_in_transit | In-Transit Inventory account (may need to be added) |
| acc_map_unbilled_purchases | GRNI accrual account |

**Changes Required**:
- FR-005: Validate that required account mappings exist before posting adjustments
- FR-007: Ensure `acc_map_in_transit` mapping exists for in-transit GL postings

## Relationships

```
products 1──N inventory (per warehouse)
products 1──N cost_layers (per warehouse)
cost_layers 1──N cost_layer_consumptions
inventory 1──N inventory_transactions
products 1──N production_orders
products 1──N stock_adjustments
stock_shipments 1──N stock_shipment_items
journal_entries 1──N journal_entry_lines
```
