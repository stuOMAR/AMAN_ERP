# Research: Purchase Lifecycle Integrity Overhaul

**Date**: 2026-05-10
**Feature**: 028-purchase-lifecycle-integrity

## R1: Decimal Precision Strategy

**Decision**: Use `Decimal(18,4)` for all quantity, cost, and monetary arithmetic. Eliminate `float` from financial and inventory calculations.

**Rationale**: The database columns are `DECIMAL(18,4)` / `NUMERIC(18,4)`. The codebase already has a `_dec()` helper in every router that converts to Decimal. However, `float()` is used at boundaries (function returns, API serialization, `party_balance.py` parameters). Mixing float and Decimal causes precision loss in atomic comparisons — critical for concurrent safety.

**Alternatives considered**:
- **Decimal for costs only, float for quantities**: Rejected — quantity comparisons in concurrent checks must also be precise.
- **Keep mixed approach with documented risks**: Rejected — the concurrent safety guarantees (FR-001/002/007) require exact arithmetic.

**Action items**:
- Centralize `_dec()` into `backend/utils/decimal_helper.py` (currently duplicated in 8+ files)
- Change `party_balance.py` to accept `Decimal` instead of `float`
- Change `CostingService` return types from `float` to `Decimal`
- Remove all `float()` casts at GL/balance boundaries

## R2: Concurrent PO Receiving Strategy

**Decision**: Use `SELECT ... FOR UPDATE` on `purchase_order_lines` rows before reading `received_quantity`. Validate `received_quantity + new_qty <= quantity` atomically within the same transaction.

**Rationale**: The codebase already uses `FOR UPDATE` extensively (124 occurrences). The `transactional()` context manager in `tx.py` holds locks until commit. This is the established pattern for preventing lost updates.

**Alternatives considered**:
- **Optimistic locking (version column)**: Rejected — requires schema change and retry logic; pessimistic locking is the established pattern.
- **Advisory locks**: Rejected — less transparent than row-level locks; harder to debug.
- **Application-level mutex**: Rejected — doesn't work across multiple application instances.

**Action items**:
- Add `FOR UPDATE` to the PO line read in `receive_purchase_order()`
- Add `FOR UPDATE` to the PO header read (to prevent PO-level status races)
- Add `received_quantity + :qty <= quantity` check in the WHERE clause

## R3: GRNI Journal Entry Uniqueness

**Decision**: Use `source="purchase_order_receipt"` with `source_id=<receipt_id>` (not `po_id`) for GRNI journal entries. Generate receipt IDs before GL posting.

**Rationale**: The GL duplicate guard checks `(source, source_id, entry_date)`. Using `po_id` as `source_id` means all partial receipts on the same day get merged into one JE. Using a unique receipt ID ensures each receipt gets its own JE.

**Alternatives considered**:
- **Use `idempotency_key` instead**: Viable but requires generating unique keys per receipt. The `source_id` approach is simpler and already supported.
- **Remove the date from the duplicate check**: Rejected — the date guard prevents accidental double-posting of the same document on different days.

**Action items**:
- Generate a receipt record ID before GL posting
- Use `source="purchase_order_receipt"`, `source_id=receipt_id` in `gl_create_journal_entry`
- Update the GL duplicate guard to NOT merge when `source_id` differs (already the behavior)

## R4: PO-Line-to-Invoice-Line Linkage

**Decision**: Add `po_line_id INTEGER REFERENCES purchase_order_lines(id)` column to `invoice_lines` table. Match invoice lines to PO lines by this FK instead of by `product_id`.

**Rationale**: The current matching service matches by `product_id`, which fails when a PO has the same product on multiple lines at different prices. The `three_way_match_lines` table already has `po_line_id` — the invoice_lines table is the missing link.

**Alternatives considered**:
- **Composite key (product_id + line_number)**: Rejected — fragile if PO lines are reordered.
- **Application-level mapping only (no FK)**: Rejected — no referential integrity; matching can drift.

**Action items**:
- Alembic migration: `ALTER TABLE invoice_lines ADD COLUMN po_line_id INTEGER REFERENCES purchase_order_lines(id)`
- Update `tenant_schema.py` DDL
- Update invoice creation to set `po_line_id` from request
- Update matching service to match by `po_line_id` instead of `product_id`
- Update GRNI reversal to use `po_line_id` for receipt cost lookup

## R5: Cost Layer Source for Returns

**Decision**: When processing a return linked to a PO invoice, trace back from the invoice to the original receipt's cost layers via `po_line_id`. Use `source_document_type='po_receipt'` and `source_document_id=<receipt_id>` to find the correct layers.

**Rationale**: Currently `handle_return()` searches for layers with `source_document_type='purchase_invoice'`, but PO receipts create layers with `source_document_type='po_receipt'`. This mismatch causes returns to miss the original layers and fall through to consuming arbitrary FIFO/LIFO layers.

**Alternatives considered**:
- **Store layer linkage on invoice posting**: More complex; requires an intermediate table.
- **Change receipt layer source to 'purchase_invoice'**: Rejected — conflates two different document types.

**Action items**:
- Pass `original_source_document_type="po_receipt"` and the receipt ID to `handle_return()`
- Update the receipt flow to store the receipt ID on the cost layer
- Update `handle_return()` to find layers by receipt source

## R6: FIFO Ordering in handle_return

**Decision**: Fix `handle_return()` to order layers by costing method: FIFO = `purchase_date ASC, id ASC`, LIFO = `purchase_date DESC, id DESC`.

**Rationale**: Currently `handle_return()` uses `ORDER BY purchase_date DESC, id DESC` for all methods, which is correct for LIFO but wrong for FIFO. The `consume_layers()` method already has correct ordering — `handle_return()` should mirror it.

**Alternatives considered**:
- **Delegate to consume_layers for all returns**: Rejected — `reduce_layer` strategy is semantically different (reverses original layers rather than consuming new ones).

**Action items**:
- Add costing_method-aware ordering to the layer query in `handle_return()`
- FIFO: `ORDER BY purchase_date ASC, id ASC`
- LIFO: `ORDER BY purchase_date DESC, id DESC`

## R7: Supplier Balance Sign Convention

**Decision**: Enforce at write time: purchase invoices = negative, payments/returns/credit notes = positive. Add sign validation in `update_party_site_balance()`.

**Rationale**: The current convention in `party_balance.py` docstring says invoice = negative, payment = positive. But returns and credit notes also pass negative values (same as invoices), which is inconsistent. The fix is to make returns/credit notes pass positive values and add a validation parameter.

**Alternatives considered**:
- **Keep current signs, fix reports**: Rejected — the sign convention is the root cause; fixing reports is treating symptoms.
- **Make party_balance type-aware**: More complex; the function would need to know document type. Simpler to enforce at call sites.

**Action items**:
- Add `document_type` parameter to `update_party_site_balance()` for sign validation
- Update all return/credit note call sites to pass positive amounts
- Update all payment/refund call sites to pass positive amounts (already correct)
- Keep invoice call sites passing negative amounts (already correct)

## R8: Return GL Valuation

**Decision**: Post return GL entries using actual cost from cost layers (not invoice unit price). Route the difference between invoice price and actual cost to a price variance account.

**Rationale**: The current code computes `return_total_cost` from the invoice's `unit_price`, but the costing service may compute a different cost (e.g., if landed costs changed the effective cost, or if FIFO layers have different costs). Using the actual cost ensures GL inventory matches cost layer valuation.

**Alternatives considered**:
- **Always use invoice price**: Rejected — causes GL/valuation mismatch when costs differ.
- **Use the higher of invoice/cost layer cost**: Rejected — no accounting basis for this.

**Action items**:
- After `handle_return()`, use `restored_unit_cost` (not `item.unit_price`) for GL posting
- Compute variance = `(invoice_price - actual_cost) * quantity`
- Post variance to a price variance account

## R9: Landed Cost Integration

**Decision**: Align frontend and backend DTOs. Allocate landed costs to received lines only. Update costs through `CostingService`. Post balanced GL entries.

**Rationale**: The frontend sends `reference_type`/`reference_id` but the backend expects `purchase_order_id`/`grn_id`. The backend directly updates `products.cost_price` and `inventory.average_cost`, bypassing `CostingService`. This breaks FIFO/LIFO layer consistency.

**Alternatives considered**:
- **Keep direct updates, add layer sync**: Rejected — maintaining two cost update paths is error-prone.

**Action items**:
- Unify DTO: frontend sends `purchase_order_id` and `cost_items` (matching backend schema)
- Replace direct `products.cost_price` / `inventory.average_cost` updates with `CostingService.update_cost()`
- Post GL: Dr Inventory, Cr AP (for vendor items) or Cr Expense (for non-vendor)
- Update `party_site_balances` for vendor-issued landed costs

## R10: Supplier Payment Locking

**Decision**: Lock individual `party_site_balances` rows instead of joining through `party_sites`. Support refund allocations to `purchase_return` and `credit_note` invoice types.

**Rationale**: The current query joins `party_sites` → `party_site_balances` with `FOR UPDATE`, which locks all balance rows for the supplier. This is overly broad and causes contention. The frontend sends `purchase_return` as invoice_type for refunds, but the backend rejects non-`purchase` types.

**Alternatives considered**:
- **Keep aggregate lock, add retry**: Rejected — doesn't solve the fundamental locking granularity issue.

**Action items**:
- Lock `party_site_balances` rows directly by `party_site_id` + `currency` + `account_type`
- Update allocation validation to accept `purchase_return` and `credit_note` types for refunds
- Align frontend filter with backend validation

## R11: Supplier Subledger View

**Decision**: Create a database view `supplier_subledger` that unions invoices, payments, returns, credit notes, debit notes, refunds, and landed cost AP entries.

**Rationale**: The AP aging report and supplier statement currently query only invoices and payments. Adding all document types via a view ensures consistency and avoids data duplication. The view is always up-to-date since it reads from source tables.

**Alternatives considered**:
- **Materialized table**: Rejected — requires sync logic on every document create/void; risk of stale data.
- **Application-level aggregation**: Rejected — slower, harder to maintain, duplicates SQL logic.

**Action items**:
- Create `supplier_subledger` view with columns: `party_id, branch_id, currency, document_type, document_id, document_number, document_date, debit, credit, running_balance`
- Union all supplier document types with correct signs
- Update AP aging report to query from the view
- Update supplier statement to query from the view

## R12: Transaction Type Unification

**Decision**: Standardize `inventory_transactions.transaction_type` to use `purchase_receipt`, `purchase_invoice`, `purchase_return` (not `purchase_in`, `purchase`).

**Rationale**: PO receipt uses `'purchase_in'`, invoice uses `'purchase'`, returns use `'purchase_return'`. Stock movement reports filter for `'purchase_in'` only, missing invoice and return transactions.

**Alternatives considered**:
- **Update report filter to include all types**: Viable but leaves the inconsistency. Better to standardize at the source.

**Action items**:
- Update `orders.py` receipt: `'purchase_in'` → `'purchase_receipt'`
- Update `invoices.py` direct invoice: `'purchase'` → `'purchase_invoice'`
- Update stock movement report filter to include all three types
- Create an enum or constant for transaction types

## R13: Error Handling Pattern

**Decision**: Remove `pass` before `raise`/`logger.error`. Use `logger.exception()` instead of `logger.error()`. Re-raise `HTTPException` without wrapping.

**Rationale**: Multiple endpoints catch `Exception` broadly, use `pass` (dead code), and `logger.error()` (loses stack trace). The `pass` statements are artifacts of earlier refactoring.

**Alternatives considered**:
- **Custom exception hierarchy**: More structured but larger scope. This fix is about removing anti-patterns, not adding new architecture.

**Action items**:
- Remove all `pass` before `raise`/`logger.error`
- Replace `logger.error()` with `logger.exception()` in exception handlers
- Re-raise `HTTPException` without catching it in the outer `except Exception`
