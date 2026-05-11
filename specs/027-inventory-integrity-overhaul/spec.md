# Feature Specification: Inventory Costing and GL Integration Overhaul

**Feature Branch**: `027-inventory-integrity-overhaul`  
**Created**: 2026-05-09  
**Status**: Draft  
**Input**: User description: "نتائج مراجعة كود المخزون والتكاملات في Backend — 13 مشكلة (10 عالية، 3 متوسطة) تغطي صرف المبيعات، FIFO/LIFO، المرتجعات، الاستلام، التسويات، التحويلات، الشحنات، AVCO/WAC، التصنيع، Schema، الجرد، التقارير، والـ Validation."

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

The current inventory subsystem has **13 integrity defects** across sales, purchases, manufacturing, transfers, and reporting. These defects cause: inventory quantities diverging from GL balances, COGS miscalculation when FIFO/LIFO layers are not consumed, overselling due to missing available-quantity checks, duplicate or missing inventory transactions between PO receipt and purchase invoice, and schema mismatches that break runtime paths. The goal is to eliminate all high-risk defects and unify inventory movement, costing, and GL posting into a single auditable service.

### In Scope

- Sales invoice issuance: enforce inventory row existence and available-quantity (`quantity - reserved_quantity`) check before allowing sale
- FIFO/LIFO cost layer consumption: fail the operation (or create a formal adjustment) when layers are insufficient — never silently fall back to `cost_price`
- Sales cancellation and returns: reverse cost layer consumptions and register reverse inventory movements linked to the original document
- PO receipt vs. purchase invoice: receipt creates a temporary/provisional cost layer; invoice handles price variance only — no double-counting of inbound inventory
- Inventory adjustments: both legacy `/adjustments` and new paths must route through a single mandatory GL-posting service; reject if account mappings are missing
- Transfer and shipment quantities: enforce `gt=0` validation; prevent empty item lists; aggregate duplicate products before execution
- In-transit inventory: dispatch posts `Dr In-Transit / Cr Inventory`; receipt posts `Dr Destination Inventory / Cr In-Transit`
- AVCO/WAC calculation: lock the product/inventory row (`FOR UPDATE`) or use an atomic upsert to prevent concurrent corruption
- Manufacturing orders: lock production order `FOR UPDATE`, use unified costing service for material consumption and finished-good receipt, create a cost layer for the finished good
- Schema alignment: resolve `inventory_transactions` column mismatches (`transaction_date`, `tenant_id`, `item_id` vs. `created_at`, `product_id`) via a real migration or service-level adaptation
- Cycle count auto-adjust: fix column references (`reserved_quantity`, `available_quantity`, `product_name`)
- Inventory valuation reports: use `CostingService.calculate_inventory_valuation()` instead of `products.cost_price`; enforce `validate_branch_access` on warehouse-scoped routes
- Input validation: enforce `Field(gt=0)` / `Field(ge=0)` on all quantity, price, discount, and expiry-date fields

### Out of Scope

- UI/frontend changes
- New feature development beyond fixing the identified 13 defects
- Performance optimization of reporting queries (beyond correctness fixes)
- Migration of historical data (existing transactions are not re-processed)

### Functional Flow Summary

- **Flow-001 (Sales Invoice Issuance)**: User creates a sales invoice → system verifies each line item has an inventory row with sufficient available quantity (`quantity - reserved_quantity >= requested_qty`) using an atomic `UPDATE ... WHERE ... RETURNING id` → if any item fails, the entire invoice is rejected → on success, FIFO/LIFO layers are consumed and GL entries are posted.
- **Flow-002 (Cost Layer Consumption)**: During any outbound movement (sale, transfer-out, manufacturing consumption), the system calls the unified costing service to consume layers in FIFO/LIFO order → if layers are insufficient, the operation fails with a clear error (no silent fallback to `cost_price`).
- **Flow-003 (Sales Cancellation / Return)**: User cancels an invoice or creates a return → system calls `CostingService.handle_return()` with the original invoice reference → consumed layers are restored → a reverse inventory movement is registered linked to the cancellation/return document.
- **Flow-004 (PO Receipt → Purchase Invoice)**: Goods receipt creates a provisional cost layer and updates AVCO → when the purchase invoice arrives, only the price variance (invoice price vs. receipt price) is processed — no duplicate inbound inventory transaction is created.
- **Flow-005 (Inventory Adjustment)**: Any adjustment (physical count, cycle count, manual) routes through a single mandatory service that: (a) validates account mappings exist, (b) posts GL entries, (c) records the movement — both legacy and new API paths use this service.
- **Flow-006 (Transfer & Shipment)**: Transfer/shipment creation validates quantities > 0 and non-empty items → dispatch moves inventory to in-transit with GL posting → receipt moves from in-transit to destination with GL posting.
- **Flow-007 (Manufacturing)**: Production start locks the order `FOR UPDATE` → material consumption uses the costing service to consume layers → production completion creates a finished-good cost layer and updates `inventory.average_cost` — duplicate completion is prevented by the lock.
- **Flow-008 (WAC Calculation)**: On any inbound movement, the system locks the product/inventory row before reading quantity and cost → calculates new WAC → updates the row atomically.

### Acceptance Criteria

1. **Given** a product with no inventory row in the target warehouse, **When** a user creates a sales invoice for that product, **Then** the system rejects the invoice and does not create any Invoice or Journal Entry records.
2. **Given** the last available unit of a product, **When** two concurrent sales invoices attempt to sell it, **Then** only one invoice succeeds and the other is rejected.
3. **Given** a FIFO costing policy with layers 10@5 and 10@7, **When** 12 units are sold, **Then** COGS = 64 and the remaining layer is 8@7.
4. **Given** a completed FIFO sale of 12 units, **When** the invoice is cancelled, **Then** the consumed layers are restored and the inventory quantity increases by 12 with a reverse movement linked to the cancellation.
5. **Given** a PO receipt of 10 units, **When** a purchase invoice for the same 10 units is posted, **Then** no duplicate `inventory_transactions` row is created for the quantity — only a price-variance entry is posted.
6. **Given** a shipment dispatched between two warehouses, **When** the shipment is in-transit (not yet confirmed), **Then** the inventory appears as in-transit (not available for sale) and GL reflects `Dr In-Transit / Cr Source Inventory`.
7. **Given** a manufacturing order, **When** two parallel requests attempt to complete it, **Then** only one succeeds.
8. **Given** a cycle count with reserved stock, **When** auto-adjust runs, **Then** the system references `reserved_quantity` and `available_quantity` columns without errors.

### Edge Cases

- What happens when a sales invoice contains multiple lines for the same product but different warehouses? Each warehouse's inventory is checked and consumed independently.
- How does the system handle a return when the original invoice's cost layers have already been partially consumed by a subsequent sale? The return creates a new inbound layer at the original cost.
- What happens when a PO receipt quantity differs from the purchase invoice quantity? The invoice processes the variance for the difference only.
- How does the system handle an adjustment when the GL account mapping is missing? The operation is rejected with a clear error message.
- What happens when a transfer is created with `items=[]`? Validation rejects it before execution.
- How does the system handle concurrent WAC recalculations for the same product? The row lock ensures sequential processing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST reject a sales invoice line item if no inventory row exists for the product in the target warehouse or if available quantity (`quantity - reserved_quantity`) is less than the requested quantity.
- **FR-002**: System MUST consume cost layers in FIFO/LIFO order during any outbound movement and MUST NOT fall back silently to `product.cost_price` when layers are insufficient.
- **FR-003**: System MUST restore consumed cost layers and register a reverse inventory movement when a sales invoice is cancelled or a return is created, with the movement linked to the original document.
- **FR-004**: System MUST create a provisional cost layer on PO receipt and process only the price variance on the associated purchase invoice — no duplicate inbound inventory transaction.
- **FR-005**: System MUST route all inventory adjustments (legacy and new) through a single service that enforces GL account mapping existence and posts journal entries.
- **FR-006**: System MUST validate that all transfer and shipment item quantities are greater than zero and that the item list is non-empty.
- **FR-007**: System MUST move inventory to in-transit status on dispatch with GL posting (`Dr In-Transit / Cr Inventory`) and move to destination on receipt with GL posting (`Dr Destination / Cr In-Transit`).
- **FR-008**: System MUST lock the product/inventory row before reading quantity and cost for WAC recalculation to prevent concurrent corruption.
- **FR-009**: System MUST lock a production order `FOR UPDATE` before completing it to prevent duplicate completion.
- **FR-010**: System MUST use the unified costing service for both material consumption and finished-good receipt in manufacturing.
- **FR-011**: System MUST align `inventory_transactions` schema — either add missing columns (`transaction_date`, `tenant_id`, `item_id`) via a real migration or adapt all services and indexes to use existing columns (`created_at`, `product_id`).
- **FR-012**: System MUST reference correct column names (`reserved_quantity`, `available_quantity`, `product_name`) in cycle count auto-adjust logic.
- **FR-013**: System MUST use `CostingService.calculate_inventory_valuation()` for inventory valuation reports and enforce `validate_branch_access` on warehouse-scoped report routes.
- **FR-014**: System MUST enforce `Field(gt=0)` or `Field(ge=0)` on all quantity, price, discount, and expiry-date fields in Pydantic schemas for inventory, purchases, and batches.

### Key Entities

- **inventory**: Stores per-product per-warehouse quantity, reserved_quantity, and average_cost. Critical fields: `product_id`, `warehouse_id`, `quantity`, `reserved_quantity`, `average_cost`.
- **inventory_transactions**: Records all inventory movements (inbound, outbound, transfer, adjustment). Critical fields: `product_id`, `warehouse_id`, `transaction_type`, `quantity`, `unit_cost`, `created_at`.
- **cost_layers**: Stores FIFO/LIFO cost layers per product. Critical fields: `product_id`, `warehouse_id`, `quantity`, `unit_cost`, `layer_date`, `source_document_type`, `source_document_id`.
- **cost_layer_consumptions**: Records which layers were consumed by outbound movements. Critical fields: `layer_id`, `consumed_quantity`, `document_type`, `document_id`.
- **products**: Master product data. Critical fields: `id`, `product_name`, `cost_policy` (FIFO/LIFO/WAC).
- **journal_entries / journal_entry_lines**: GL postings linked to inventory movements. Critical fields: `document_type`, `document_id`, `account_id`, `debit`, `credit`.
- **account_mappings**: Maps inventory events to GL accounts. Critical fields: `event_type` (e.g., `inventory_asset`, `cogs`, `adjustment`, `in_transit`), `account_id`.
- **production_orders**: Manufacturing orders. Critical fields: `id`, `status`, `product_id`, `quantity`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero instances of sales invoices created without a corresponding inventory deduction (no "phantom sales").
- **SC-002**: 100% of outbound movements have a matching `cost_layer_consumptions` record — no silent fallback to `cost_price`.
- **SC-003**: After cancellation or return, the inventory balance and cost layers match the pre-sale state (quantity and layer integrity restored).
- **SC-004**: PO receipt followed by purchase invoice for the same goods produces exactly one set of `inventory_transactions` rows (no duplicates).
- **SC-005**: In-transit shipments are reflected in GL and inventory reports as in-transit (not available) between dispatch and receipt.
- **SC-006**: Concurrent WAC recalculations for the same product produce a single correct average cost — no lost updates.
- **SC-007**: Concurrent manufacturing order completions: only one succeeds; the second is rejected.
- **SC-008**: Cycle count auto-adjust executes without column-reference errors.
- **SC-009**: All inventory valuation reports use the configured costing method (FIFO/LIFO/WAC) via the costing service — not `products.cost_price`.
- **SC-010**: All quantity, price, and discount fields reject zero and negative values at the API boundary.

## Assumptions

- The existing `CostingService` is capable of handling FIFO, LIFO, and WAC calculations once its callers are corrected — no rewrite of the core algorithm is assumed.
- PostgreSQL is the database engine, supporting `FOR UPDATE` row locking and `RETURNING` clauses.
- The system uses a single-tenant or schema-per-tenant model where `tenant_id` on `inventory_transactions` may be handled at the schema level rather than the row level.
- Historical data migration (re-processing existing transactions) is out of scope; fixes apply to new transactions only.
- The existing GL posting mechanism (journal entries) is functional once the correct account mappings are enforced.
- The codebase uses Pydantic v2 for request validation schemas.
- The `reserved_quantity` column already exists on the `inventory` table (it is used in some code paths but not all).
