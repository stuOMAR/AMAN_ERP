# Tasks: Inventory Integrity, Costing, and GL Overhaul

**Input**: Design documents from `/specs/027-inventory-integrity-overhaul/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/api-contracts.md`, `quickstart.md`

**Tests**: Required. This feature touches stock balances, costing, COGS, and GL postings. Each behavioral phase must have fail-first coverage before or alongside implementation.

**Organization**: Tasks are grouped by accounting risk and dependency order. High-risk flows (sales, returns, PO receipt/invoice, shipment in-transit, manufacturing, valuation) must be verified with integration tests.

## Format: `[ID] [P?] [Area?] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on the current phase's sequential tasks.
- **[Area]**: Requirement/capability label, e.g. TEST, VALIDATION, WAC, SALES, PO, ADJ, SHIPMENT, MFG, REPORT.
- Every implementation task must preserve tenant isolation, fiscal-period checks before GL posting, Decimal/NUMERIC precision, and one-transaction atomicity for stock + cost + GL + audit.
- Do not silently fall back from FIFO/LIFO layer failure to `products.cost_price`. Either fail the operation with a clear 400/409 or create an explicitly posted adjustment where the requirement allows it.

---

## Phase 0: Regression Test Baseline

**Purpose**: Lock the expected behavior before changing high-risk accounting flows.

**Independent Validation**: Tests fail on the current defects and pass only after the implementation phases are complete.

- [x] T001 [TEST] Add `backend/tests/test_65_inventory_integrity_overhaul.py` with reusable fixtures for FIFO, LIFO, WAC products, two warehouses, open fiscal period, and required GL account mappings (`acc_map_inventory`, `acc_map_cogs`, `acc_map_inventory_adjustment`, `acc_map_in_transit`, `acc_map_unbilled_purchases`, WIP/FG mappings).
- [x] T002 [TEST] Add sales tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: missing inventory row rejects, insufficient available quantity rejects, and two concurrent invoices for the last unit result in exactly one success and no negative stock.
- [x] T003 [TEST] Add FIFO/LIFO outbound tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: sale of 12 units from layers 10@5 + 10@7 produces COGS 64, creates `cost_layer_consumptions`, and layer exhaustion raises a 400 without `cost_price` fallback.
- [x] T004 [TEST] Add cancellation/POS return tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: returned/cancelled FIFO quantities restore original consumed layers, inventory quantity increases, COGS reversal uses restored layer cost, and reverse `inventory_transactions` reference the return/cancellation.
- [x] T005 [TEST] Add PO receipt/invoice tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: PO receipt creates one provisional stock transaction/layer, invoice for already received quantity posts only price variance, no duplicate quantity transaction, and sold-before-invoice layers do not have their consumed cost mutated.
- [x] T006 [TEST] Add shipment in-transit tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: dispatch moves source `quantity` to source `in_transit_quantity`, receipt moves in-transit to destination quantity, duplicate dispatch/receipt is rejected, and GL entries are balanced.
- [x] T007 [TEST] Add manufacturing tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: material consumption uses actual costing service value, finished goods create cost layers, WAC is updated in the correct order, and parallel completions allow only one success.
- [x] T008 [TEST] Add report/schema tests in `backend/tests/test_65_inventory_integrity_overhaul.py`: valuation report matches layer/WAC valuation, branch-scoped valuation validates access, cycle-count auto-adjust compiles, and all inventory transaction DDL/indexes use existing columns.
- [x] T009 [TEST] Add validation tests in `backend/tests/test_43_pydantic_validation.py`: negative prices, zero/negative movement quantities, empty transfer/shipment item lists, invalid purchase lines, invalid PO receipt quantities, and invalid batch quantities.

**Checkpoint**: Critical tests exist and describe the accounting invariants. They may fail until implementation phases are complete.

---

## Phase 1: Validation, Schema, and DDL Alignment

**Purpose**: Remove invalid input paths and fix runtime column/index mismatches before behavioral changes.

**Independent Validation**: Pydantic validation rejects invalid input; DDL/index generation no longer references nonexistent `inventory_transactions` columns.

- [x] T010 [P] [VALIDATION] In `backend/routers/inventory/schemas.py`, import/use `Field` and change `ProductCreate.selling_price`, `buying_price`, and `last_buying_price` to `Field(default=0.0, ge=0)` so zero setup/free-sample prices remain allowed while negatives are rejected.
- [x] T011 [P] [VALIDATION] In `backend/routers/inventory/schemas.py`, set `StockTransferSingleCreate.quantity` and `StockTransferItem.quantity` to `Field(..., gt=0)`, and set `StockTransferCreate.items` and `StockMovementCreate.items` to `Field(..., min_length=1)`.
- [x] T012 [P] [VALIDATION] In `backend/routers/inventory/schemas.py`, set `ShipmentItemCreate.quantity` to `Field(..., gt=0)` and `ShipmentCreate.items` to `Field(..., min_length=1)`.
- [x] T013 [P] [VALIDATION] In `backend/routers/inventory/schemas.py`, set `StockAdjustmentCreate.new_quantity` to `Field(..., ge=0)`.
- [x] T014 [P] [VALIDATION] In `backend/schemas/purchases.py`, set purchase line `quantity` and `unit_price` to `Field(..., gt=0)`, `discount` to `Field(default=0, ge=0)`, and reject discounts greater than line gross if that validation does not already exist.
- [x] T015 [P] [VALIDATION] In `backend/schemas/purchases.py`, set `POReceiveRequest.received_quantity`/receipt item quantities to `Field(..., gt=0)`.
- [x] T016 [P] [VALIDATION] In `backend/routers/inventory/batches.py`, set `BatchCreate.quantity` to `Field(..., ge=0)` and ensure tracked products cannot create usable batch/serial stock without the required batch/serial reference.
- [x] T017 [SCHEMA] Fix `backend/services/inventory/wac_per_warehouse.py` to use existing `inventory_transactions` columns only: `product_id`, `warehouse_id`, `created_at`, `reference_type`, `reference_id`; remove any dependency on `tenant_id`, `item_id`, or `transaction_date`.
- [x] T018 [SCHEMA] Fix all DDL/index references to `inventory_transactions.transaction_date`, `tenant_id`, `item_id`, or `occurred_at` in `backend/db_ddl/tenant_schema.py`, `backend/db_ddl/tenant_runner.py`, and `backend/db_ddl/reports_indexes.py`; use `created_at`, `product_id`, `warehouse_id`, and `reference_id` instead.
- [x] T019 [SCHEMA] Fix inventory services that read `inventory_transactions` with nonexistent columns in `backend/services/inventory/transactions_reader.py`, `backend/services/inventory/archival.py`, `backend/services/inventory/auto_reorder.py`, and `backend/services/inventory/low_stock_webhook.py`; tenant isolation must come from the tenant schema/connection, not a missing `tenant_id` column.
- [x] T020 [SCHEMA] Fix cycle-count auto-adjust SQL in `backend/routers/inventory/batches.py`: replace `reserved` with `reserved_quantity`, `available` with `available_quantity` or the authoritative formula `quantity - COALESCE(reserved_quantity, 0)`, and `products.item_name` with the real product-name column.

**Checkpoint**: Validation is strict where movement quantities must be positive, prices are non-negative, and inventory transaction DDL/services compile against the actual schema.

---

## Phase 2: Costing Service Safety and WAC Concurrency

**Purpose**: Make the canonical costing service safe under concurrent inbound movements and capable of returning accurate reversal cost details.

**Independent Validation**: Concurrent inbound WAC movements produce one correct average cost; returns expose restored cost for GL reversal.

- [x] T021 [WAC] In `backend/services/costing_service.py::update_cost`, lock the product row with `SELECT ... FROM products WHERE id=:pid FOR UPDATE` before reading/updating `products.cost_price` in global WAC.
- [x] T022 [WAC] In `backend/services/costing_service.py::update_cost`, lock the warehouse inventory row with `FOR UPDATE` before reading `average_cost`/`quantity` in per-warehouse WAC; handle missing rows via safe insert/upsert under the same transaction.
- [x] T023 [WAC] In `backend/services/costing_service.py::update_cost`, when recomputing global product cost from all warehouses, read/update under the product lock and avoid a second unlocked existence check that can race.
- [x] T024 [RETURNS] In `backend/services/costing_service.py::handle_return`, extend the return dict to include `restored_unit_cost`, `restored_total_cost`, and the restored quantities per layer for the `reverse_consumption` path; keep existing keys for compatibility.
- [x] T025 [RETURNS] In `backend/services/costing_service.py::handle_return`, require new call sites to pass `unit_cost`, `source_document_type`, `source_document_id`, `original_source_document_type`, and `original_source_document_id`; legacy fallback may remain only for old data, not new sales/POS return flows.

**Checkpoint**: Cost calculations are concurrency-safe and returns provide an auditable cost basis.

---

## Phase 3: Sales and POS Outbound Integrity

**Purpose**: Prevent overselling and enforce FIFO/LIFO consumption without fallback.

**Independent Validation**: Sales/POS reject missing stock and insufficient available quantity; FIFO/LIFO COGS and consumptions match layers.

- [x] T026 [SALES] In `backend/routers/sales/invoices.py::create_sales_invoice`, replace the current separate stock check/deduct with an atomic statement using the authoritative available formula: `UPDATE inventory SET quantity = quantity - :qty, last_movement_date = NOW(), updated_at = NOW() WHERE product_id=:pid AND warehouse_id=:wh AND quantity - COALESCE(reserved_quantity,0) >= :qty RETURNING id, quantity`; if no row returns, distinguish missing row from insufficient stock.
- [x] T027 [SALES] In `backend/routers/sales/invoices.py::create_sales_invoice`, preserve sales-order reservation release but ensure `reserved_quantity` cannot go below zero and `available_quantity` is either recalculated consistently or treated as derived.
- [x] T028 [SALES] In `backend/routers/sales/invoices.py::create_sales_invoice`, remove the broad `except Exception` fallback around `CostingService.consume_layers`; convert `ValueError` from FIFO/LIFO exhaustion to HTTP 400 and let unexpected exceptions roll back.
- [x] T029 [SALES] In `backend/routers/sales/invoices.py::create_sales_invoice`, ensure `inventory_transactions` for outbound rows include `reference_type='sales_invoice'`, `reference_id=invoice_id`, `unit_cost`, and `total_cost` equal to the same COGS used in GL.
- [x] T030 [POS] In `backend/routers/pos/orders.py::create_order`, apply the same missing-row/available-quantity atomic deduction semantics as sales invoices.
- [x] T031 [POS] In `backend/routers/pos/orders.py::create_order`, remove the broad `except Exception` fallback around FIFO/LIFO consumption and ensure POS COGS uses the same cost returned by `CostingService.consume_layers`.

**Checkpoint**: Outbound sales flows cannot create negative stock and cannot hide broken FIFO/LIFO layers behind `cost_price`.

---

## Phase 4: Sales Cancellation and POS Returns

**Purpose**: Restore stock and cost layers using the original outbound document, and reverse COGS at the original layer cost.

**Independent Validation**: Cancellations/returns restore layer quantities and reverse inventory/COGS with the original cost basis.

- [x] T032 [SALES] In `backend/routers/sales/invoices.py::cancel_invoice`, lock the invoice row/status and make cancellation idempotent; reject already cancelled invoices before any stock, layer, or GL mutation.
- [x] T033 [SALES] In `backend/routers/sales/invoices.py::cancel_invoice`, after adding stock back, call `CostingService.handle_return(db, product_id, warehouse_id, quantity, unit_cost=<original line unit_cost>, source_document_type='sales_cancellation', source_document_id=<cancellation_or_invoice_id>, costing_method=<method>, original_source_document_type='sales_invoice', original_source_document_id=invoice_id)`.
- [x] T034 [SALES] In `backend/routers/sales/invoices.py::cancel_invoice`, use `handle_return.restored_total_cost`/`restored_unit_cost` for COGS reversal and reverse `inventory_transactions` with `reference_type='sales_cancellation'`, `reference_id=invoice_id`, and `total_cost` matching the GL reversal.
- [x] T035 [POS] In `backend/routers/pos/orders.py::create_return`, create/lock the return header before mutating inventory so each return has its own `return_id` and idempotency guard.
- [x] T036 [POS] In `backend/routers/pos/orders.py::create_return`, call `CostingService.handle_return(db, product_id, warehouse_id, quantity, unit_cost=<original line unit_cost>, source_document_type='pos_return', source_document_id=return_id, costing_method=<method>, original_source_document_type='pos_order', original_source_document_id=order_id)`.
- [x] T037 [POS] In `backend/routers/pos/orders.py::create_return`, use restored cost from `handle_return` for the return inventory transaction and COGS reversal instead of `products.cost_price`.

**Checkpoint**: Sales/POS reversals restore both quantity and valuation history.

---

## Phase 5: Purchase Order Receipt and Purchase Invoice Integrity

**Purpose**: Avoid duplicate stock/cost recognition when a purchase invoice is created after PO receipt, and post price variance without rewriting historical COGS.

**Independent Validation**: PO receipt + invoice produce one physical stock receipt, correct provisional/variance accounting, and no retroactive mutation of consumed layer cost.

- [x] T038 [PO] In `backend/routers/purchases/orders.py::receive_purchase_order`, after fiscal-period/account validation and before quantity update, call `CostingService.update_cost` for WAC products with the PO receipt price and quantity using the correct "called before inventory update" order.
- [x] T039 [PO] In `backend/routers/purchases/orders.py::receive_purchase_order`, for FIFO/LIFO products, create a provisional cost layer with `source_document_type='po_receipt'`, `source_document_id=<receipt_or_po_id>`, `unit_cost=<po_unit_price>`, and remaining quantity equal to the received quantity.
- [x] T040 [PO] In `backend/routers/purchases/orders.py::receive_purchase_order`, ensure the receipt creates exactly one `inventory_transactions` row for the received quantity with `reference_type='po_receipt'`, `reference_id=<receipt_or_po_id>`, and receipt unit/total cost.
- [x] T041 [PO] In `backend/routers/purchases/invoices.py::create_purchase_invoice`, split each line into `qty_already_received` and `qty_to_add`; call `CostingService.update_cost`, create cost layers, and insert `inventory_transactions` only for `qty_to_add`.
- [x] T042 [PO] In `backend/routers/purchases/invoices.py::create_purchase_invoice`, when invoicing already received quantity, calculate price variance as `(invoice_unit_cost - receipt_unit_cost) * qty_already_received` and post it to the configured variance/GRNI flow without creating another quantity movement.
- [x] T043 [PO] In `backend/routers/purchases/invoices.py::create_purchase_invoice`, do not overwrite `unit_cost` for consumed portions of provisional layers. For remaining unconsumed quantity, either adjust the remaining layer value explicitly or create a cost adjustment layer/variance record linked to the invoice; consumed COGS must remain historical.
- [x] T044 [PO] In `backend/routers/purchases/invoices.py::create_purchase_invoice`, update provisional layer metadata to link the invoice (`invoice_reference_id` if available, or notes/reference fields that exist) without changing the cost of already consumed quantities.
- [x] T045 [PO] In `backend/routers/purchases/invoices.py::create_purchase_invoice`, ensure GRNI/unbilled purchases reversal, inventory debit/credit, and price variance JE are balanced and idempotent for repeated invoice submission attempts.

**Checkpoint**: Receipt and invoice no longer double-count stock or mutate historical valuation.

---

## Phase 6: Inventory Adjustments and Stock Movement Unification

**Purpose**: Route adjustment-style movements through one atomic implementation with mandatory GL mapping validation.

**Independent Validation**: `/adjustments` and `/stock-movements/adjustment` produce the same inventory/GL effects and reject missing mappings.

- [x] T046 [ADJ] In `backend/routers/inventory/adjustments.py`, extract shared adjustment posting into `post_inventory_adjustment(db, *, items, adjustment_account_id=None, inventory_account_id=None, reference, notes, txn_date, user_id, username, company_id, request)` that handles row locks, quantity changes, inventory transaction rows, GL posting, fiscal lock, and audit within the caller transaction.
- [x] T047 [ADJ] In the shared adjustment helper, validate `acc_map_inventory` and `acc_map_inventory_adjustment` when explicit account IDs are not supplied; do not use the nonexistent/incorrect key `acc_map_adjustment`.
- [x] T048 [ADJ] In the shared adjustment helper, reject stock decreases that would make quantity negative using `SELECT ... FOR UPDATE`, and use Decimal cost from `inventory.average_cost` with fallback to `products.cost_price`.
- [x] T049 [ADJ] Refactor `backend/routers/inventory/adjustments.py::create_adjustment` to call the shared helper and keep its current response contract.
- [x] T050 [ADJ] Refactor `backend/routers/inventory/stock_movements.py::create_stock_adjustment` to call the shared helper while preserving support for explicit `adjustment_account_id` and multi-item adjustments.

**Checkpoint**: Adjustment paths are consistent, atomic, and GL-backed.

---

## Phase 7: Transfers, Shipments, and In-Transit Inventory

**Purpose**: Make warehouse shipment movement explicit: dispatch moves stock to in-transit, receipt moves it from in-transit to destination.

**Independent Validation**: Invalid quantities are rejected, duplicate status transitions are rejected, and GL/inventory move through dispatch then receipt.

- [x] T051 [TRANSFER] In `backend/routers/inventory/transfers.py`, aggregate duplicate products in multi-item transfer requests before stock checks and updates, then validate one combined quantity per product.
- [x] T052 [SHIPMENT] In `backend/routers/inventory/shipments.py`, add/verify permission-gated `dispatch_shipment` endpoint and lock the shipment row `FOR UPDATE`; allow dispatch only from a pending/approved state and reject already dispatched/received/cancelled shipments.
- [x] T053 [SHIPMENT] In `dispatch_shipment`, validate `acc_map_inventory` and `acc_map_in_transit`, check fiscal period open, atomically deduct source `quantity` and increase source `in_transit_quantity` using `quantity - COALESCE(reserved_quantity,0) >= :qty`, and create `shipment_dispatch` inventory transactions with source layer cost.
- [x] T054 [SHIPMENT] In `dispatch_shipment`, consume FIFO/LIFO source layers with `sale_document_type='shipment_dispatch'` and store enough detail to recreate destination layers at the original layer costs on receipt; if layers are insufficient, fail instead of falling back silently.
- [x] T055 [SHIPMENT] In `confirm_shipment`/`receive_shipment`, lock the shipment row `FOR UPDATE`, allow receipt only from `dispatched`, deduct source `in_transit_quantity`, add destination `quantity`, create destination cost layers from dispatch consumption details, and update destination WAC in the correct order.
- [x] T056 [SHIPMENT] In `confirm_shipment`/`receive_shipment`, post GL `Dr Destination Inventory / Cr In-Transit Inventory`, create receipt inventory transactions with `reference_type='shipment_receive'`, and make repeated receipt attempts idempotently reject.
- [x] T057 [SHIPMENT] In `backend/routers/inventory/shipments.py`, update list/detail responses if needed so status and in-transit quantities are visible to reports and tests.

**Checkpoint**: Shipment accounting shows an auditable in-transit balance until receipt.

---

## Phase 8: Manufacturing Costing Integration

**Purpose**: Use actual material costing for WIP and create finished-good layers/costs on completion.

**Independent Validation**: Materials consumed at actual FIFO/LIFO/WAC cost; finished goods receive cost layers; duplicate completion is prevented.

- [x] T058 [MFG] In `backend/routers/manufacturing/core/orders.py::start_production_order`, replace raw material `ON CONFLICT DO UPDATE SET quantity = inventory.quantity - :qty` with costing-service-backed consumption: FIFO/LIFO via `CostingService.consume_layers`, WAC via locked inventory average/product cost.
- [x] T059 [MFG] In `start_production_order`, write `production_out` inventory transactions using the actual unit/total cost returned by the costing flow, and make the WIP GL debit equal the same total material cost.
- [x] T060 [MFG] In `backend/routers/manufacturing/core/orders.py::complete_production_order`, lock the production order with `SELECT ... FOR UPDATE` and constrain the row to `status='in_progress'` before any stock/GL mutation; reject if no row returns.
- [x] T061 [MFG] In `complete_production_order`, compute finished-good unit cost from the posted WIP/material/labor/overhead basis, call `CostingService.update_cost` before adding finished-good quantity, then add inventory quantity.
- [x] T062 [MFG] In `complete_production_order`, create finished-good and by-product cost layers for FIFO/LIFO products with `source_document_type='production_order'`, and write `production_in` inventory transactions with matching unit/total cost.
- [x] T063 [MFG] In `complete_production_order`, ensure WIP/FG GL entries are balanced, fiscal-period checked, idempotent by production order, and equal to the inventory transaction valuation.

**Checkpoint**: Manufacturing inventory and GL use the same actual cost basis.

---

## Phase 9: Reports, Valuation, and Branch Access

**Purpose**: Make inventory reports reflect actual costing policy and prevent branch data leakage.

**Independent Validation**: Report totals match cost layers/WAC and branch-scoped users cannot view unauthorized warehouse valuation.

- [x] T064 [REPORT] In `backend/routers/inventory/reports.py`, replace valuation logic based on `products.cost_price * quantity` with `CostingService.calculate_inventory_valuation(db, warehouse_id=..., branch_id/branch_ids=..., as_of_date=...)`.
- [x] T065 [REPORT] In `backend/routers/inventory/reports.py`, adapt the endpoint response to the existing Pydantic/report contract: correct `as_of_date` type, item fields, `warehouse_id`, and grand total naming.
- [x] T066 [REPORT] In `backend/routers/inventory/reports.py`, call `validate_branch_access` for explicit `warehouse_id` filters and restrict unfiltered reports to the user's allowed branch IDs.
- [x] T067 [REPORT] In `backend/routers/reports/inventory.py`, replace summary/valuation calculations that use `products.cost_price` with costing-service valuation or documented WAC fields, and add branch access filtering.
- [x] T068 [REPORT] In `backend/services/kpi_service/warehouse.py`, review any inventory value KPI using `products.cost_price`; either switch to costing-service valuation or document why it is an approximate KPI and exclude it from financial valuation reports.

**Checkpoint**: Financial inventory valuation comes from the same costing source as movements.

---

## Phase 10: Batch/Serial Tracking and End-of-Period Guards

**Purpose**: Close inventory integrity gaps that affect batch sequencing, traceability, and closing controls.

**Independent Validation**: Tracked products cannot move without required tracking references; closed periods cannot receive new stock/GL mutations.

- [x] T069 [BATCH] In sales/POS outbound, shipments, transfers, adjustments, and manufacturing consumption paths, enforce that products with `has_batch_tracking`/`has_serial_tracking` provide valid available batch/serial selections before stock is deducted.
- [x] T070 [BATCH] In the same movement paths, update batch/serial quantities/status atomically with inventory quantity and cost layer changes, and reject reuse of consumed serial numbers.
- [x] T071 [BATCH] In receiving flows (PO receipt, purchase invoice direct receipt, manufacturing FG, returns), create/update batch quantities only after validating expiry/manufacturing dates and product tracking rules.
- [x] T072 [CLOSING] Verify every new or modified GL-posting path calls `check_fiscal_period_open` before stock/cost/GL mutations for sales cancellation, POS return, PO variance, dispatch, receipt, adjustment, and manufacturing.
- [x] T073 [CLOSING] Verify month-end valuation is reproducible from cost layers, inventory quantities, and inventory transactions as of the closing date; add a regression test if the current reporting API supports `as_of_date`.

**Checkpoint**: Batch/serial traceability and fiscal closing controls cover all modified movements.

---

## Phase 11: Cross-Cutting Audit, Authorization, and Performance

**Purpose**: Finish operational hardening after behavioral fixes.

- [x] T074 [AUTH] Verify every new/modified endpoint uses the existing permission model: sales invoice/cancel, POS order/return, PO receive/invoice, adjustment, shipment dispatch/receive, manufacturing start/complete, valuation reports.
- [x] T075 [AUDIT] Move or add `log_activity` calls so sensitive inventory operations are auditable without being lost after commit/connection close; include product, warehouse, quantity, document reference, and GL reference where available.
- [x] T076 [TXN] Verify each modified operation commits once after all stock, cost, GL, transaction log, and audit work succeeds; rollback must leave no partial inventory or GL mutation.
- [x] T077 [PRECISION] Verify all new cost calculations use `Decimal` and quantize consistently with existing `_D2`, `_D4`, `_D6`, and `ROUND_HALF_UP`; do not introduce float math in valuation/GL amounts.
- [x] T078 [PERF] Review indexes for large inventory transaction tables after schema fixes: product+warehouse+created_at, reference_type+reference_id, warehouse+created_at, and cost layer product+warehouse+is_exhausted+purchase_date.
- [x] T079 [QUICKSTART] Re-verify `specs/027-inventory-integrity-overhaul/quickstart.md` after implementation so it still matches the corrected behavior, especially `handle_return` arguments, PO variance without historical cost mutation, and shipment dispatch/receive status transitions.
- [x] T080 [CONTRACT] Re-verify `specs/027-inventory-integrity-overhaul/contracts/api-contracts.md` after implementation so endpoint contracts still match the corrected plan and do not reintroduce the obsolete `handle_return(document_type, document_id)` call.

**Checkpoint**: The implementation is auditable, permission-gated, performant, and documented.

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 0 (Tests)**: Start first. Tests can be added in parallel with Phase 1 but must exist before marking any behavioral phase done.
- **Phase 1 (Validation/Schema)**: No implementation dependency; required before report/schema tests can pass.
- **Phase 2 (Costing Service)**: Required before Sales, Returns, PO, Shipment, Manufacturing, and Reports.
- **Phase 3 (Sales/POS Outbound)**: Depends on Phase 1 and Phase 2.
- **Phase 4 (Cancellations/Returns)**: Depends on Phase 2 and Phase 3.
- **Phase 5 (PO Receipt/Invoice)**: Depends on Phase 1 and Phase 2.
- **Phase 6 (Adjustments)**: Depends on Phase 1.
- **Phase 7 (Transfers/Shipments)**: Depends on Phase 1 and Phase 2.
- **Phase 8 (Manufacturing)**: Depends on Phase 1 and Phase 2.
- **Phase 9 (Reports)**: Depends on Phase 1 and Phase 2.
- **Phase 10 (Batch/Serial/Closing)**: Depends on Phases 3-8.
- **Phase 11 (Cross-Cutting)**: Runs after each phase and finalizes after all previous phases.

### Within-Phase Dependencies

- Phase 0: T001 before T002-T009.
- Phase 1: T010-T016 parallel; T017-T020 parallel after confirming real schema columns.
- Phase 2: T021 -> T022 -> T023; T024 -> T025.
- Phase 3: T026 -> T027 -> T028 -> T029; T030 -> T031 can run in parallel with sales after T026 semantics are agreed.
- Phase 4: T032 -> T033 -> T034; T035 -> T036 -> T037. Sales and POS return work can run in parallel.
- Phase 5: T038 -> T039 -> T040; T041 -> T042 -> T043 -> T044 -> T045.
- Phase 6: T046 -> T047 -> T048 -> T049/T050.
- Phase 7: T051 is independent; T052 -> T053 -> T054 -> T055 -> T056 -> T057.
- Phase 8: T058 -> T059; T060 -> T061 -> T062 -> T063.
- Phase 9: T064 -> T065 -> T066; T067 and T068 can run in parallel after T064 design is clear.
- Phase 10: T069 -> T070 -> T071; T072 and T073 can run in parallel.
- Phase 11: T074-T078 run as review tasks after relevant files change; T079-T080 run at the end.

### Parallel Opportunities

```bash
# Foundation in parallel:
T001-T009 tests
T010-T020 validation/schema
T021-T025 costing service

# After foundation:
T026-T031 sales/POS
T038-T045 purchases
T046-T050 adjustments
T051-T057 shipments/transfers
T058-T063 manufacturing
T064-T068 reports
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 0 tests for sales, costing, and WAC.
2. Complete Phase 1 schema/validation fixes.
3. Complete Phase 2 WAC lock and return-cost details.
4. Complete Phase 3 sales/POS outbound integrity.
5. Stop and validate: no overselling, no silent FIFO/LIFO fallback, correct COGS, concurrent sales safety.

### Incremental Delivery

1. Foundation: Phase 0 + Phase 1 + Phase 2.
2. Sales integrity: Phase 3.
3. Reversal integrity: Phase 4.
4. Purchase integrity: Phase 5.
5. Adjustment and transfer/shipment integrity: Phase 6 + Phase 7.
6. Manufacturing integrity: Phase 8.
7. Reporting and closing integrity: Phase 9 + Phase 10.
8. Operational hardening: Phase 11.

### Critical Path

```text
Phase 0 Tests + Phase 1 Schema
              + Phase 2 Costing
                    |
                    +--> Phase 3 Sales/POS --> Phase 4 Returns
                    +--> Phase 5 Purchases
                    +--> Phase 6 Adjustments
                    +--> Phase 7 Shipments
                    +--> Phase 8 Manufacturing
                    +--> Phase 9 Reports
                              |
                              v
                    Phase 10 Closing/Tracking
                              |
                              v
                    Phase 11 Audit/Auth/Performance
```
