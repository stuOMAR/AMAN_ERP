# Research: Inventory Costing and GL Integration Overhaul

**Feature**: 027-inventory-integrity-overhaul
**Date**: 2026-05-09
**Status**: Complete

## Research Questions

### RQ-001: Unified InventoryMovementService vs. Fix-in-Place

**Decision**: Fix-in-place approach (correct existing callers of `CostingService`).

**Rationale**:
- The existing `CostingService` already has all the required methods: `consume_layers`, `handle_return`, `update_cost`, `create_cost_layer`, `calculate_inventory_valuation`
- The defects are in the **callers** (sales, POS, manufacturing, purchases) not in the service itself
- Creating a new `InventoryMovementService` would require rewriting all 8+ calling modules simultaneously — high risk, large blast radius
- The spec says "Out of Scope: new feature development beyond fixing the 13 defects"
- The constitution principle VII (Simplicity and SQL-First) prefers direct service functions over new abstractions

**Alternatives considered**:
1. **New `InventoryMovementService`**: Wraps all movement types into one service. Rejected because: (a) the existing `CostingService` already does this for costing, (b) the callers have module-specific logic (GL accounts, document types) that would need to be parameterized, (c) higher risk of regression.
2. **Middleware/decorator approach**: Auto-intercept inventory mutations. Rejected because: inventory logic is not uniform across modules (sales has reservations, manufacturing has BOM, transfers have two warehouses).

**Recommendation**: Fix each caller to correctly use `CostingService` methods. This is the lowest-risk approach that addresses all 13 defects.

---

### RQ-002: Schema Alignment Strategy

**Decision**: Adapt services to use existing columns (`created_at` instead of `transaction_date`, `product_id` instead of `item_id`, schema-level tenant isolation instead of `tenant_id` column).

**Rationale**:
- `inventory_transactions` already has `product_id`, `warehouse_id`, `created_at` — these are the correct columns
- `wac_per_warehouse.py` (Feature 023) uses non-existent columns (`transaction_date`, `tenant_id`, `item_id`) — this is a bug in that service, not a missing schema feature
- Schema-per-tenant model means `tenant_id` is redundant at the row level
- Adding columns via migration requires updating all existing queries and indexes — unnecessary churn

**Alternatives considered**:
1. **Migration to add columns**: Add `transaction_date`, `tenant_id`, `item_id`. Rejected because: (a) `created_at` already serves the purpose of `transaction_date`, (b) `product_id` already serves the purpose of `item_id`, (c) tenant isolation is at schema level, (d) migration would require backfilling existing data.
2. **Hybrid**: Add `transaction_date` as alias view. Rejected because: adds complexity without value.

**Recommendation**: Fix `wac_per_warehouse.py` to use `created_at` and `product_id`. Add indexes on `inventory_transactions(product_id, created_at)` if not already present.

---

### RQ-003: WAC Locking Strategy

**Decision**: Use row locks in `CostingService.update_cost`: lock `products` before global WAC reads/updates, and lock the relevant `inventory` row before per-warehouse WAC reads/updates.

**Rationale**:
- `consume_layers` (line 241) already uses `FOR UPDATE` on `inventory` — this pattern works
- `update_cost` (line 45) currently reads `inventory.quantity` and `inventory.average_cost` without locking, then updates — race condition possible
- PostgreSQL `FOR UPDATE` is the standard pattern used throughout the codebase (constitution principle VI)
- Atomic upsert (`INSERT ... ON CONFLICT ... DO UPDATE SET quantity = quantity + :qty`) works for simple quantity changes but not for WAC recalculation which needs the current cost

**Alternatives considered**:
1. **Atomic upsert for WAC**: `UPDATE inventory SET average_cost = (quantity * average_cost + :new_qty * :new_cost) / (quantity + :new_qty), quantity = quantity + :new_qty`. Viable but: (a) doesn't handle the case where `quantity = 0` (division by zero), (b) doesn't create snapshots, (c) doesn't handle FIFO/LIFO layer creation.
2. **Optimistic locking**: Version column on inventory. Rejected because: (a) adds complexity, (b) retries would need full recalculation, (c) `FOR UPDATE` is already the established pattern.

**Recommendation**: Add the product/inventory `FOR UPDATE` locks in `update_cost` and remove unlocked existence checks that can race with concurrent inbound movements.

---

### RQ-004: In-Transit Inventory Lifecycle

**Decision**: Use the existing `confirm_shipment` pattern but add a `dispatch` step that moves inventory to in-transit immediately.

**Rationale**:
- Current flow: `create_shipment` (document only) → `confirm_shipment` (moves inventory directly from source to destination)
- Problem: Between creation and confirmation, inventory is still available for sale at source
- Fix: Add a `dispatch_shipment` endpoint that: (1) deducts from source, (2) adds to in-transit pseudo-warehouse or uses `in_transit_quantity` column on inventory, (3) posts GL `Dr In-Transit / Cr Source Inventory`
- The `inventory` table already has `in_transit_quantity` column (schema line 477) — use it

**Alternatives considered**:
1. **In-transit pseudo-warehouse**: Create a virtual warehouse for in-transit stock. Rejected because: (a) adds complexity, (b) the `in_transit_quantity` column already exists, (c) pseudo-warehouse would pollute warehouse-based reports.
2. **Reserve on create**: Reserve stock at shipment creation. Partially viable but: doesn't handle the GL posting requirement.

**Recommendation**: Use `in_transit_quantity` column. Dispatch deducts from `quantity`, adds to `in_transit_quantity`. Receipt deducts from `in_transit_quantity`, adds to destination `quantity`.

---

### RQ-005: PO Receipt vs. Purchase Invoice Deduplication

**Decision**: PO receipt creates a provisional cost layer; invoice handles price variance only.

**Rationale**:
- Current flow: PO receipt adds quantity + logs `purchase_in` transaction + posts accrual GL. Invoice adds quantity AGAIN + logs `purchase` transaction + posts GL — double-counts inventory.
- Fix: PO receipt creates a provisional cost layer at the PO price. Invoice compares invoice price to receipt price, posts variance only, and upgrades the provisional layer to final.
- The `cost_layers` table has `source_document_type` — can use `'po_receipt'` vs. `'purchase_invoice'`

**Alternatives considered**:
1. **Invoice-only costing**: Don't update inventory at receipt, only at invoice. Rejected because: (a) goods are physically present and should be available for sale, (b) GRNI (Goods Received Not Invoiced) accounting requires receipt-time accrual.
2. **Full quantity at invoice**: Keep current behavior but skip the receipt transaction. Rejected because: (a) goods may be received weeks before invoice, (b) inventory accuracy requires real-time quantity tracking.

**Recommendation**: Receipt creates quantity + provisional layer + accrual JE. Invoice creates price-variance JE + upgrades layer. No duplicate `inventory_transactions`.

---

### RQ-006: Manufacturing Costing Integration

**Decision**: Use `CostingService.consume_layers` for material consumption and `CostingService.create_cost_layer` for finished goods.

**Rationale**:
- Current `start_production_order` uses raw `ON CONFLICT DO UPDATE SET quantity = inventory.quantity - :qty` — no layer consumption, no FIFO/LIFO
- Current `complete_production_order` manually calculates WAC and updates `products.cost_price` — doesn't create cost layer, doesn't update `inventory.average_cost`
- Fix: (1) Material consumption calls `consume_layers` per BOM line, (2) FG receipt calls `create_cost_layer` + `update_cost`, (3) Lock production order `FOR UPDATE` at completion to prevent duplicate

**Alternatives considered**:
1. **Keep raw SQL for performance**: Rejected because: (a) correctness > performance for costing, (b) the overhead of `CostingService` is minimal (single row lock + iteration), (c) constitution principle XIX requires centralized calculation.
2. **Separate manufacturing costing service**: Rejected because: (a) `CostingService` already handles all costing methods, (b) adds unnecessary abstraction.

**Recommendation**: Replace raw SQL in manufacturing with `CostingService` calls. Add `FOR UPDATE` lock on production order at completion.

---

### RQ-007: Adjustment Path Unification

**Decision**: Route both `/adjustments` (legacy) and `/stock_movements` through a single adjustment service function.

**Rationale**:
- Two paths exist: `adjustments.py` (line 67) and `stock_movements.py` (line 55)
- Both update inventory and log transactions, but may have different GL posting logic
- Constitution principle XIX (Calculation Centralization) requires one canonical service
- Fix: Create a shared `post_adjustment(db, ...)` function that both routes call, which: (1) validates account mappings, (2) posts GL, (3) records movement

**Alternatives considered**:
1. **Deprecate one path**: Remove `/stock_movements` endpoint. Rejected because: (a) may be used by integrations, (b) breaking change.
2. **Keep both, add GL check to both**: Viable but: risks future divergence.

**Recommendation**: Extract shared logic into a helper function. Both routes call it.

---

### RQ-008: Cycle Count Column References

**Decision**: Replace `reserved`, `available`, `products.item_name` with `reserved_quantity`, `available_quantity`, `product_name`.

**Rationale**:
- `inventory` table has `reserved_quantity` and `available_quantity` columns (schema line 477)
- `products` table has `product_name` column (standard)
- `batches.py` line 1300 uses incorrect column names — simple rename
- No schema change needed, just code fix

**Recommendation**: Direct column name replacement in the affected query.

---

### RQ-009: Validation Schema Fixes

**Decision**: Add `Field(gt=0)` to movement quantities and purchase unit prices, `Field(ge=0)` to product setup prices and discounts.

**Rationale**:
- Pydantic v2 supports `Field(gt=0)` for strict positive validation and `Field(ge=0)` where zero is valid
- Constitution principle XXII (Validation Pipeline Order) requires schema validation as the first step
- Fields needing validation: movement `quantity`, purchase `unit_price`, non-negative `selling_price`/`buying_price`, `discount`, and `expiry_date`

**Recommendation**: Add `Field(gt=0)` to movement quantities and purchase unit prices, and `Field(ge=0)` to product prices, discounts, and initial batch quantities across `inventory/schemas.py`, `schemas/purchases.py`, and `inventory/batches.py`.

---

## Summary of Decisions

| Research Question | Decision | Risk Level |
|-------------------|----------|------------|
| RQ-001: Service architecture | Fix-in-place (correct callers) | Low |
| RQ-002: Schema alignment | Adapt services to existing columns | Low |
| RQ-003: WAC locking | Add `FOR UPDATE` to `update_cost` | Low |
| RQ-004: In-transit lifecycle | Use `in_transit_quantity` column + dispatch step | Medium |
| RQ-005: PO receipt/invoice dedup | Provisional layer at receipt, variance at invoice | Medium |
| RQ-006: Manufacturing costing | Use `CostingService` methods | Medium |
| RQ-007: Adjustment unification | Shared helper function | Low |
| RQ-008: Cycle count columns | Direct rename | Low |
| RQ-009: Validation schemas | Add `Field(gt=0)` | Low |

**Overall Risk**: Low-Medium. Most changes are caller fixes to an existing well-tested service. The medium-risk items (RQ-004, RQ-005, RQ-006) require careful transaction design but follow established patterns.
