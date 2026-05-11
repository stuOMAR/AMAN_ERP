# Tasks: Purchase Lifecycle Integrity Overhaul

**Input**: Design documents from `/specs/028-purchase-lifecycle-integrity/`
**Prerequisites**: plan.md (required), spec.md (requirements and acceptance criteria required), research.md, data-model.md, contracts/

**Tests**: Not explicitly requested. Test tasks omitted.

**Organization**: Tasks are grouped by capability phase. Each phase maps to a functional area from the spec. Phases are ordered by dependency: foundational work first, then core purchase flows, then cross-cutting concerns.

## Format: `[ID] [P?] [Area?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Area]**: Optional capability label (e.g., RCPT, INV, RET, PAY, RPT, FE, ERR)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Schema migrations, Decimal precision, and transaction type constants that all capabilities depend on.

- [x] T001 Create centralized Decimal helper in backend/utils/decimal_helper.py with `_dec()`, `_D2`, `_D4`, `ROUND_HALF_UP` (extracted from duplicated pattern in 8+ files)
- [x] T002 [P] Create Alembic migration in backend/alembic/versions/ to add `po_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE SET NULL` and index on `invoice_lines`
- [x] T003 [P] Create Alembic migration in backend/alembic/versions/ to add `invoiced_quantity DECIMAL(18,4) DEFAULT 0` on `purchase_order_lines`
- [x] T004 [P] Update tenant_schema.py to add `po_line_id` column to invoice_lines DDL (around line 953) and `invoiced_quantity` to purchase_order_lines DDL (around line 1034)
- [x] T005 Create transaction type constants module in backend/utils/inventory_constants.py defining `TX_PURCHASE_RECEIPT`, `TX_PURCHASE_INVOICE`, `TX_PURCHASE_RETURN` (replacing inconsistent string literals across files)
- [x] T006 Create supplier_subledger database view in Alembic migration — UNION ALL of invoices, payment_vouchers, and party_transactions with correct sign convention per data-model.md

**Checkpoint**: Schema ready, Decimal helper available, constants defined, subledger view created.

---

## Phase 2: PO Receiving Integrity (FR-001 to FR-005)

**Goal**: Prevent concurrent duplicate PO receiving; ensure each receipt posts a unique GRNI journal entry.

**Independent Validation**: Create a PO, approve it, receive partial quantity, then attempt to receive more than remaining — second attempt fails with clear error.

- [x] T007 [RCPT] Add `FOR UPDATE` lock on purchase_order_lines in `receive_purchase_order()` in backend/routers/purchases/orders.py (around line 479) — lock PO lines before reading `received_quantity`
- [x] T008 [RCPT] Add `FOR UPDATE` lock on purchase_orders header in `receive_purchase_order()` in backend/routers/purchases/orders.py — prevent PO-level status races
- [x] T009 [RCPT] Add atomic quantity check in `receive_purchase_order()` in backend/routers/purchases/orders.py (around line 547) — `WHERE received_quantity + :qty <= quantity` in the UPDATE statement, raise HTTPException(409) if no rows updated
- [x] T010 [RCPT] Generate receipt record ID before GL posting in `receive_purchase_order()` in backend/routers/purchases/orders.py — insert receipt record, capture ID, then call `gl_create_journal_entry` with `source="purchase_order_receipt"`, `source_id=receipt_id`
- [x] T011 [RCPT] Update GL journal entry source_id from `po_id` to `receipt_id` in `receive_purchase_order()` in backend/routers/purchases/orders.py (around line 668) — ensures each partial receipt gets its own JE
- [x] T012 [RCPT] Replace `'purchase_in'` with `TX_PURCHASE_RECEIPT` constant in `receive_purchase_order()` in backend/routers/purchases/orders.py (around line 572) — standardize inventory_transactions.transaction_type

**Checkpoint**: PO receiving is concurrency-safe; each receipt has a unique GRNI journal entry.

---

## Phase 3: PO Invoicing Integrity (FR-006 to FR-010)

**Goal**: Prevent duplicate/over-invoicing of PO lines; store PO-line-to-invoice-line linkage; match by PO line.

**Independent Validation**: Create a PO, receive 10 units, invoice 10 units, attempt second invoice — rejected. PO with same product on 2 lines at different prices — partial invoice matches correct line.

- [x] T013 [INV] Store `po_line_id` on invoice lines in `create_purchase_invoice()` in backend/routers/purchases/invoices.py (around line 408) — read `po_line_id` from request, INSERT into invoice_lines
- [x] T014 [INV] Add cumulative invoiced quantity validation in `create_purchase_invoice()` in backend/routers/purchases/invoices.py — before insert, `SELECT SUM(quantity) FROM invoice_lines WHERE po_line_id = :pid` and validate `sum + new_qty <= received_quantity`
- [x] T015 [INV] Update `invoiced_quantity` on purchase_order_lines in `create_purchase_invoice()` in backend/routers/purchases/invoices.py — after invoice line insert, `UPDATE purchase_order_lines SET invoiced_quantity = invoiced_quantity + :qty WHERE id = :po_line_id`
- [x] T016 [INV] Update matching_service.py to match by `po_line_id` instead of `product_id` in `perform_match()` (around line 136) — change `inv_map` key from `product_id` to `po_line_id`
- [x] T017 [INV] Update GRNI reversal in `create_purchase_invoice()` in backend/routers/purchases/invoices.py (around line 488) — use `po_line_id` to find receipt cost instead of `product_id` only
- [x] T018 [INV] Add `remaining_to_invoice` field to PO details API response in backend/routers/purchases/orders.py — compute `received_quantity - invoiced_quantity` per line
- [x] T019 [INV] Replace `'purchase'` with `TX_PURCHASE_INVOICE` constant in `create_purchase_invoice()` in backend/routers/purchases/invoices.py (around line 566) — standardize inventory_transactions.transaction_type for direct invoices
- [x] T020 [INV] Update Pydantic schema `PurchaseCreate` in backend/routers/purchases/invoices.py to accept `po_line_id` field on line items

**Checkpoint**: PO invoicing validates cumulative quantities; invoice lines linked to PO lines; matching uses PO line.

---

## Phase 4: Purchase Returns & Cost Layers (FR-011 to FR-015)

**Goal**: Fix cost layer source for returns; ensure FIFO/LIFO ordering; post GL at actual cost.

**Independent Validation**: FIFO product received via PO, part sold, then return created — return reverses original receipt layer (not arbitrary FIFO layer). GL inventory matches cost layer valuation.

- [x] T021 [RET] Fix cost layer source lookup in `create_purchase_return()` in backend/routers/purchases/returns.py (around line 419) — pass `original_source_document_type="po_receipt"` and receipt ID to `CostingService.handle_return()`
- [x] T022 [RET] Trace invoice to receipt via `po_line_id` in `create_purchase_return()` in backend/routers/purchases/returns.py — query `invoice_lines.po_line_id` → `purchase_order_lines` → find receipt cost layer source
- [x] T023 [RET] Fix FIFO ordering in `handle_return()` in backend/services/costing_service.py (around line 404) — add costing_method-aware ordering: FIFO = `ORDER BY purchase_date ASC, id ASC`, LIFO = `ORDER BY purchase_date DESC, id DESC`
- [x] T024 [RET] Use actual cost from cost layers for GL posting in `create_purchase_return()` in backend/routers/purchases/returns.py (around line 469) — use `restored_unit_cost` from `handle_return()` result instead of `item.unit_price`
- [x] T025 [RET] Post price variance to variance account in `create_purchase_return()` in backend/routers/purchases/returns.py (around line 511) — compute `variance = (invoice_price - actual_cost) * quantity`, post to variance GL account
- [x] T026 [RET] Fix supplier balance sign for returns in `create_purchase_return()` in backend/routers/purchases/returns.py (around line 577) — change from `-float(gl_paid)` to `+float(gl_paid)` (positive = reduces what we owe)
- [x] T027 [RET] Update `update_party_site_balance()` in backend/utils/party_balance.py — change parameter type from `float` to `Decimal`, add optional `document_type` parameter for sign validation

**Checkpoint**: Returns reverse correct cost layers; GL uses actual cost; supplier balance sign correct.

---

## Phase 5: Supplier Payments & Refunds (FR-024 to FR-026)

**Goal**: Fix payment locking; support refund allocations to returns/credit notes.

**Independent Validation**: Create a payment, allocate to purchase invoice — works. Create refund, allocate to purchase return — works. Two concurrent payments — one succeeds, one fails.

- [x] T028 [PAY] Fix locking granularity in `create_supplier_payment()` in backend/routers/purchases/payments.py (around line 57) — lock `party_site_balances` rows directly by `party_site_id + currency + account_type` instead of joining through `party_sites`
- [x] T029 [PAY] Support refund allocations to purchase returns in `create_supplier_payment()` in backend/routers/purchases/payments.py (around line 118) — update validation to accept `invoice_type IN ('purchase', 'purchase_return', 'credit_note', 'debit_note')` for refund vouchers
- [x] T030 [PAY] Fix frontend refund filter in frontend/src/pages/Purchases/PaymentForm.jsx (around line 451) — ensure filter matches backend validation (already filters by `purchase_return` for refunds, verify alignment)

**Checkpoint**: Payments lock individual rows; refunds can allocate to returns/credit notes.

---

## Phase 6: Landed Cost Integration (FR-019 to FR-023)

**Goal**: Align frontend/backend schemas; update costs through CostingService; post balanced GL entries.

**Independent Validation**: Create PO, receive, allocate landed cost — GL entries balanced (Dr = Cr), product costs updated via CostingService, AP recorded.

- [x] T031 [LC] Align frontend DTO in frontend/src/pages/Buying/LandedCosts.jsx (around line 19) — change form state to send `purchase_order_id` instead of `reference_type`/`reference_id`
- [x] T032 [LC] Replace direct product/inventory cost updates in `allocate_landed_cost()` in backend/routers/landed_costs.py (around line 379) — replace `UPDATE products SET cost_price` and `UPDATE inventory SET average_cost` with `CostingService.update_cost()` calls
- [x] T033 [LC] Fix inventory cost update scope in backend/routers/landed_costs.py (around line 387) — add `warehouse_id` filter to inventory UPDATE (currently updates ALL warehouses)
- [x] T034 [LC] Update party_site_balances for vendor-issued landed costs in backend/routers/landed_costs.py (around line 423) — replace direct `party_transactions` INSERT with `update_party_site_balance()` call

**Checkpoint**: Landed costs aligned with backend; costs updated via CostingService; AP balanced.

---

## Phase 7: Reports (FR-027 to FR-031)

**Goal**: Include all supplier document types in AP/VAT reports; fix stock movement filter.

**Independent Validation**: Create invoice + return + credit note + payment — AP aging total matches GL AP balance. VAT report nets correctly. Stock movement shows all purchase types.

- [x] T035 [RPT] Update AP aging report in backend/routers/reports/purchases.py (around line 150) — query from `supplier_subledger` view instead of `invoices` table only
- [x] T036 [RPT] Update supplier statement in backend/routers/reports/purchases.py (around line 223) — query from `supplier_subledger` view to include returns, credit notes, refunds, landed costs
- [x] T037 [RPT] Update VAT report in backend/routers/finance/taxes/reports.py (around line 78) — add `purchase_credit_note` and `purchase_debit_note` types with correct signs
- [x] T038 [RPT] Update stock movement report filter in backend/routers/inventory/reports.py (around line 194) — add `purchase_receipt`, `purchase_invoice`, `purchase_return` to the filter map (replacing `purchase_in`)

**Checkpoint**: All reports include all document types; report totals reconcile with GL.

---

## Phase 8: Frontend Guards (FR-032, FR-033)

**Goal**: Disable convert-to-invoice when no uninvoiced qty remains; pre-fill with remaining quantity.

**Independent Validation**: PO with partial receipt and full invoice — convert-to-invoice button disabled. PO with partial receipt and no invoice — pre-fill with received quantity.

- [x] T039 [FE] Disable convert-to-invoice button in frontend/src/pages/Buying/BuyingOrderDetails.jsx (around line 56) — check `remaining_to_invoice > 0` on any line before enabling button
- [x] T040 [FE] Fix invoice form pre-fill in frontend/src/pages/Buying/PurchaseInvoiceForm.jsx (around line 78) — use `remaining_to_invoiced` (received - invoiced) instead of `received_quantity` or `quantity`

**Checkpoint**: Frontend prevents duplicate invoicing at UI level.

---

## Phase 9: Error Handling & Cleanup (FR-034 to FR-036)

**Goal**: Remove exception swallowing anti-patterns; improve error clarity.

**Independent Validation**: Trigger a validation error — response contains domain-specific message, not generic 500. Server logs contain full stack trace.

- [x] T041 [P] [ERR] Remove dead `pass` statements and fix logging in backend/routers/purchases/orders.py (around lines 464, 712, 832) — remove `pass` before `raise`, use `logger.exception()` instead of `logger.error()`
- [x] T042 [P] [ERR] Remove dead `pass` statements and fix logging in backend/routers/purchases/returns.py (around lines 623, 626) — remove `pass`, use `logger.exception()`
- [x] T043 [P] [ERR] Remove dead `pass` statements and fix logging in backend/routers/purchases/payments.py (around line 316) — remove `pass`, use `logger.exception()`
- [x] T044 [ERR] Re-raise HTTPException without wrapping in backend/routers/purchases/orders.py (around line 711) — `except HTTPException: raise` before `except Exception`

**Checkpoint**: All purchase endpoints have clean error handling with stack traces.

---

## Phase 10: RFQ Completion (FR-039, FR-040)

**Goal**: Store supplier invitations; convert RFQ response to actual PO.

**Independent Validation**: Create RFQ with suppliers, record quotation, convert winning quote to PO — PO created with correct lines and prices.

- [x] T045 [RFQ] Create RFQ supplier invitations table in Alembic migration — `rfq_suppliers(rfq_id, party_id, status, invited_at, responded_at)`
- [x] T046 [RFQ] Update RFQ creation in backend/routers/purchases/orders.py (around line 801) — accept `supplier_ids` from request, insert into `rfq_suppliers`
- [x] T047 [RFQ] Create quotation-to-PO conversion endpoint in backend/routers/purchases/orders.py (around line 875) — `POST /rfq/{rfq_id}/convert` creates a purchase_order from the winning quotation's lines

**Checkpoint**: RFQ lifecycle complete: invite suppliers → receive quotes → convert to PO.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Final consistency checks and validation.

- [x] T048 [P] Import centralized `_dec()` from backend/utils/decimal_helper.py in all files that currently define it locally: orders.py, invoices.py, returns.py, payments.py, gl_service.py, costing_service.py, party_balance.py
- [x] T049 [P] Remove `float()` casts at GL/balance boundaries in backend/routers/purchases/invoices.py, returns.py, payments.py — pass Decimal values directly to `gl_create_journal_entry` and `update_party_site_balance`
- [x] T050 Verify schema consistency: run `alembic upgrade head` on a test tenant and confirm full PO → Receive → Invoice → Return → Payment → Reports flow works without errors
- [x] T051 Run quickstart.md validation checklist — verify all 9 scenarios pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — can start immediately
- **Phase 2 (PO Receiving)**: Depends on Phase 1 (schema migration, constants, Decimal helper)
- **Phase 3 (PO Invoicing)**: Depends on Phase 2 (needs receiving to work first)
- **Phase 4 (Returns)**: Depends on Phase 3 (needs invoicing and po_line_id linkage)
- **Phase 5 (Payments)**: Depends on Phase 1 only (independent of PO flows)
- **Phase 6 (Landed Costs)**: Depends on Phase 1 only (independent of PO flows)
- **Phase 7 (Reports)**: Depends on Phase 1 (subledger view) and ideally Phases 2-5 (all document types)
- **Phase 8 (Frontend)**: Depends on Phase 3 (needs `remaining_to_invoice` API field)
- **Phase 9 (Error Handling)**: Depends on Phase 1 only (independent cleanup)
- **Phase 10 (RFQ)**: Depends on Phase 1 only (independent feature)
- **Phase 11 (Polish)**: Depends on all previous phases

### Within Each Phase

- Schema/migration tasks first (T002-T004, T006)
- Service layer before endpoint changes
- Backend before frontend
- Core logic before integration/wiring

### Parallel Opportunities

- Phase 1: T002, T003, T004, T005, T006 can all run in parallel (different files)
- Phase 5 and Phase 6 can run in parallel with Phases 2-4 (different files)
- Phase 9 can run in parallel with any other phase (different files, cleanup only)
- Phase 10 can run in parallel with Phases 2-9 (independent feature)
- T041, T042, T043 are parallel (different files)

---

## Parallel Example: Phase 1

```bash
# Launch all Phase 1 tasks in parallel:
Task: "Create centralized Decimal helper in backend/utils/decimal_helper.py"
Task: "Create Alembic migration for po_line_id on invoice_lines"
Task: "Create Alembic migration for invoiced_quantity on purchase_order_lines"
Task: "Update tenant_schema.py with new columns"
Task: "Create transaction type constants module"
Task: "Create supplier_subledger database view migration"
```

## Parallel Example: Phases 5+6 (independent of PO flows)

```bash
# These can run in parallel with Phases 2-4:
Task: "Fix payment locking in backend/routers/purchases/payments.py"
Task: "Align landed cost DTO in frontend/src/pages/Buying/LandedCosts.jsx"
Task: "Replace direct cost updates in backend/routers/landed_costs.py"
```

---

## Implementation Strategy

### MVP First (Phases 1-3)

1. Complete Phase 1: Schema migrations, Decimal helper, constants
2. Complete Phase 2: PO Receiving integrity (concurrency-safe receiving)
3. Complete Phase 3: PO Invoicing integrity (cumulative validation, po_line_id)
4. **STOP and VALIDATE**: PO → Receive → Invoice flow is integrity-safe
5. Deploy if ready

### Incremental Delivery

1. Phase 1 → Foundation ready
2. Phase 2+3 → PO Receive + Invoice integrity (MVP)
3. Phase 4 → Returns integrity (cost layers, GL valuation)
4. Phase 5+6 → Payments + Landed costs (independent)
5. Phase 7+8 → Reports + Frontend guards (visibility)
6. Phase 9+10 → Error handling + RFQ (cleanup + completion)
7. Phase 11 → Final validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Phase 1 together
2. Once Phase 1 is done:
   - Developer A: Phases 2→3→4 (core PO flow)
   - Developer B: Phase 5+6 (payments + landed costs)
   - Developer C: Phase 9+10 (error handling + RFQ)
3. After core flow done:
   - Developer A: Phase 7 (reports)
   - Developer B: Phase 8 (frontend)
4. Team: Phase 11 (polish + validation)
