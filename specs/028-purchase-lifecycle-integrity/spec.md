# Feature Specification: Purchase Lifecycle Integrity Overhaul

**Feature Branch**: `028-purchase-lifecycle-integrity`
**Created**: 2026-05-10
**Status**: Draft
**Input**: User description: "Fix 16 critical and medium severity integrity issues across the entire purchase lifecycle — PO receiving, invoicing, returns, payments, GL posting, landed costs, supplier balances, and reporting."

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

The purchase lifecycle in Aman ERP has 16 integrity issues (10 high, 6 medium) that span Purchases, Inventory, Accounting, Payments, Reports, and Frontend modules. These issues allow duplicate PO receiving, duplicate/cumulative invoicing without guardrails, incorrect GRNI (Goods Received Not Invoiced) accruals, broken cost layer linkage for returns, inconsistent supplier balance signs, non-functional landed cost integration, broken supplier payments and refunds, incomplete AP/VAT reports, and frontend-backend schema mismatches. The goal is to restore data integrity so that every purchase document (PO, receipt, invoice, return, payment, landed cost, credit/debit note) is atomic, idempotent, correctly linked, and produces balanced GL entries that reconcile with inventory valuation and supplier subledger.

### In Scope

- **PO Receiving**: Prevent concurrent duplicate receiving of the same PO line; ensure each receipt posts a unique GRNI journal entry
- **PO Invoicing**: Prevent duplicate and over-invoicing of PO lines; store PO-line-to-invoice-line linkage; cumulative quantity validation
- **Invoice–PO–Receipt Matching**: Match by PO line (not just product); track cumulative received vs invoiced per line
- **Purchase Returns & Cost Layers**: Link returns to the correct cost layer source (receipt layer, not invoice layer); ensure FIFO/LIFO ordering is correct per costing method
- **Supplier Balance Consistency**: Unify sign convention across invoices, returns, credit notes, debit notes, payments, and refunds; handle foreign-currency amounts correctly
- **Return GL Valuation**: Post inventory at actual cost layer cost (not invoice price); route price differences to variance accounts
- **Landed Cost Integration**: Align frontend and backend schemas; allocate landed costs to received lines only; update costs through the costing service (not direct product/inventory update); post balanced AP/clearing entries
- **Supplier Payments & Refunds**: Fix locking strategy; support refund allocations to purchase returns and credit notes; align frontend and backend document type handling
- **AP & VAT Reports**: Include all supplier document types (returns, credit/debit notes, refunds, landed costs) in aging, statement, and VAT reports; build a unified supplier subledger view
- **Stock Movement Reports**: Include all purchase-related transaction types in stock movement filters
- **Frontend Guards**: Disable "Convert to Invoice" when no uninvoiced received quantity remains; show remaining-to-invoice per PO line
- **Error Handling**: Replace broad exception swallowing with domain error messages; preserve stack traces; add correlation IDs
- **Schema Consistency**: Reconcile tenant schema with migrations; ensure all columns referenced in code exist

### Out of Scope

- New feature development (e.g., new document types, new reports)
- Performance optimization beyond concurrency correctness
- UI redesign or workflow changes beyond integrity guards
- Migration of historical data (existing corrupt data is not repaired by this feature; a separate data-fix script may follow)
- Repair of existing party_site_balances with incorrect signs (a separate one-time repair script recalculates balances from source documents before enabling reconciliation checks)

### Functional Flow Summary

- **Flow-001 (Receive PO)**: User approves a PO and receives goods. The system locks the PO lines, validates remaining quantity, creates inventory records and cost layers, and posts a unique GRNI journal entry per receipt. Concurrent receive attempts for the same PO line are rejected.
- **Flow-002 (Invoice PO)**: User creates a purchase invoice linked to a PO. The system validates that cumulative invoiced quantity does not exceed cumulative received quantity per PO line, stores the PO-line linkage, and posts the invoice accrual with GRNI reversal per receipt.
- **Flow-003 (Direct Purchase Invoice)**: User creates a purchase invoice without a PO. The system records inventory transactions with a consistent transaction type that appears in stock movement reports.
- **Flow-004 (Purchase Return)**: User creates a return linked to an original invoice. The system finds the correct cost layers (by receipt source, not invoice source), reverses them in FIFO/LIFO order, posts inventory at actual cost, and routes price differences to variance. Supplier balance is updated with the correct sign.
- **Flow-005 (Landed Cost)**: User allocates freight, customs, insurance, and handling costs to received PO lines. The system updates cost layers through the costing service, posts balanced GL entries, and records AP obligations for vendor-issued landed costs.
- **Flow-006 (Supplier Payment & Refund)**: User pays a supplier or processes a refund. The system locks individual balance rows (not aggregates), supports allocations to all valid document types, and posts balanced GL entries.
- **Flow-007 (Reports)**: User runs AP aging, supplier statement, or VAT report. The report includes all document types (invoices, returns, credit/debit notes, refunds, landed costs) and reconciles with GL and party balances.
- **Flow-008 (Concurrent Safety)**: Two users attempt the same operation simultaneously (receive same PO line, invoice same PO, pay same supplier). The system allows exactly one operation to succeed and returns a clear error to the other.

### Acceptance Criteria

1. **Given** an approved PO with a line of quantity 10, **When** two users simultaneously receive quantity 5 on the same line, **Then** exactly one succeeds and the other receives an error indicating the line is already fully or partially received.
2. **Given** a PO with 10 units received, **When** a user invoices 10 units, **Then** a second attempt to invoice the same PO line is rejected because cumulative invoiced quantity equals received quantity.
3. **Given** a PO with the same product on two lines at different prices, **When** a partial invoice is created, **Then** the matching and GRNI reversal use the correct PO line (not just product).
4. **Given** a FIFO product received via PO, **When** part is sold and then a purchase return is created, **Then** the return reverses the original receipt layer (not a random FIFO layer).
5. **Given** a purchase invoice in USD, **When** a partial return is created, **Then** the supplier balance reflects the return with the correct sign and currency, and the GL matches the AP ledger.
6. **Given** a PO receipt at one cost and a landed cost allocation changing the effective cost, **When** a return is processed, **Then** the GL inventory valuation matches the cost layer valuation.
7. **Given** a landed cost allocated to PO lines, **When** the allocation is posted, **Then** GL entries are balanced (debit = credit), AP is correctly recorded, and product costs are updated through the costing service.
8. **Given** a refund payment linked to a purchase return, **When** the payment is created, **Then** the backend accepts the allocation and the supplier balance is correctly adjusted.
9. **Given** a set of invoices, returns, credit notes, and payments, **When** the AP aging report is run, **Then** the report total matches the supplier subledger and the GL AP account balance.
10. **Given** a purchase invoice with tax, **When** a credit note is issued, **Then** the VAT report correctly nets the input VAT.

### Edge Cases

- What happens when a PO line is partially received and then the PO is amended (quantity changed)? The system must validate that the new quantity is not less than already-received quantity.
- How does the system handle a return when the original cost layer has already been fully consumed by sales? The return should consume the next available FIFO/LIFO layer at the current cost.
- What happens when a supplier payment is created with an allocation to a fully-paid invoice? The system must reject the allocation with a clear error.
- How does the system handle a foreign-currency invoice where the exchange rate changes between receipt and invoicing? The GRNI reversal must use the receipt-date rate, not the invoice-date rate.
- What happens when two users try to allocate the same landed cost simultaneously? The system must serialize the allocation operation.
- How does the system handle a purchase return when inventory quantity is insufficient (reserved by sales orders)? The system must reject the return with a clear error.
- What happens when a period is closed and a user tries to post a return dated in that period? The system must reject with a fiscal-period error.

## Requirements *(mandatory)*

### Functional Requirements

**PO Receiving (Issues #1, #2)**

- **FR-041**: System MUST use Decimal(18,4) for all quantity, cost, and monetary arithmetic; float MUST NOT be used for financial or inventory calculations.
- **FR-001**: System MUST lock PO lines before reading received quantities during a receive operation.
- **FR-002**: System MUST validate that the sum of already-received plus new-receive quantity does not exceed the ordered quantity, as an atomic check.
- **FR-003**: System MUST reject a concurrent receive attempt on the same PO line with a clear error message.
- **FR-004**: System MUST generate a unique journal entry per receipt (not per PO) for GRNI accrual.
- **FR-005**: System MUST use a receipt-level identifier (not PO ID) as the source reference for GRNI journal entries to prevent the GL duplicate guard from merging separate partial receipts.

**PO Invoicing (Issues #3, #4)**

- **FR-006**: System MUST store the PO-line-to-invoice-line linkage on each invoice line.
- **FR-007**: System MUST validate that cumulative invoiced quantity across all invoices for a PO line does not exceed cumulative received quantity for that line.
- **FR-008**: System MUST prevent duplicate invoicing of the same PO line when the remaining-to-invoice quantity is zero.
- **FR-009**: System MUST match invoice lines to PO lines (not just product) when performing 3-way matching and GRNI reversal.
- **FR-010**: System MUST return remaining-to-invoice quantity per PO line in the PO details API response.

**Purchase Returns & Cost Layers (Issues #5, #7)**

- **FR-011**: System MUST locate cost layers by the original receipt source (not invoice source) when processing a return linked to a PO invoice.
- **FR-012**: System MUST reverse cost layers in the correct order per costing method (FIFO: oldest first, LIFO: newest first).
- **FR-013**: When the original receipt layer is fully consumed, the system MUST consume the next available layer at the current cost and record the cost difference as a variance.
- **FR-014**: System MUST post return GL entries using the actual cost from cost layers (not the invoice unit price).
- **FR-015**: System MUST route the difference between invoice price and actual cost to a price variance account.

**Supplier Balance (Issue #6)**

- **FR-016**: System MUST use a consistent sign convention: purchase invoices decrease supplier balance (negative), payments/returns/credit notes increase supplier balance (positive).
- **FR-017**: System MUST store the foreign-currency amount in the currency bucket and the base-currency amount separately when exchange rates differ.
- **FR-018**: System MUST validate at write time that supplier balance updates match the expected sign for the document type (invoice: negative; payment/return/credit note: positive).

**Landed Costs (Issue #8)**

- **FR-019**: System MUST use a unified data contract between frontend and backend for landed cost creation (matching field names and types).
- **FR-020**: System MUST allocate landed costs only to received lines (not ordered-only lines).
- **FR-021**: System MUST update product costs and inventory costs through the costing service (not direct column updates).
- **FR-022**: System MUST post balanced GL entries for landed costs (debit inventory, credit AP or expense).
- **FR-023**: System MUST record AP obligations for vendor-issued landed costs in the supplier subledger.

**Supplier Payments & Refunds (Issue #9)**

- **FR-024**: System MUST lock individual supplier balance rows (not aggregate queries) during payment creation.
- **FR-025**: System MUST support refund allocations to purchase returns and credit notes (not just purchase invoices).
- **FR-026**: System MUST align frontend and backend document type handling for refund flows.

**AP & VAT Reports (Issues #11, #13)**

- **FR-027**: AP aging report MUST include purchase returns, credit notes, debit notes, refunds, and landed cost AP obligations.
- **FR-028**: Supplier statement MUST include all supplier document types in the running balance calculation.
- **FR-029**: VAT report MUST include purchase credit notes and debit notes with correct signs.
- **FR-030**: Reports MUST reconcile with party balances and GL account balances.

**Stock Movement Reports (Issue #12)**

- **FR-031**: Stock movement report filter MUST include all purchase-related transaction types (purchase receipt, purchase invoice, purchase return).

**Frontend Guards (Issue #10)**

- **FR-032**: "Convert to Invoice" button MUST be disabled when no uninvoiced received quantity remains on any PO line.
- **FR-033**: Invoice form pre-fill from PO MUST use remaining-to-invoice quantity (not total received or ordered quantity).

**Error Handling (Issue #15)**

- **FR-034**: System MUST NOT catch and swallow broad exceptions on critical operations (receiving, invoicing, returns, payments).
- **FR-035**: System MUST return domain-specific error messages (not generic 500 errors) for validation failures.
- **FR-036**: System MUST log exceptions with full stack traces (not just error messages).

**Schema Consistency (Issue #14)**

- **FR-037**: All columns referenced in application code MUST exist in the tenant schema (either in the base DDL or in migrations).
- **FR-038**: New tenants MUST be able to complete a full purchase lifecycle (PO → Receive → Invoice → Return → Payment → Reports) without schema errors.

**RFQ (Issue #16 — Medium)**

- **FR-039**: RFQ creation MUST accept and store supplier invitations (not just header and lines).
- **FR-040**: Converting an RFQ response to a PO MUST create an actual purchase order (not just return a comparison).

### Key Entities

- **Purchase Orders**: Header with supplier, currency, status; Lines with product, quantity, unit price, received_quantity, invoiced_quantity
- **Purchase Order Receipts**: Per-line receipt record linking PO line to received quantity, warehouse, cost layer, and GRNI journal entry
- **Purchase Invoices**: Header with supplier, currency, status; Lines with product, quantity, unit price, PO-line linkage
- **Invoice Lines**: Each line linked to a PO line (nullable for direct invoices), with cumulative invoiced tracking
- **Cost Layers**: Per-unit-cost inventory layer with source_document_type, source_document_id, remaining_quantity, and costing method (FIFO/LIFO/WAC)
- **Inventory Transactions**: Movement log with consistent transaction_type enum (purchase_receipt, purchase_invoice, purchase_return, etc.)
- **Journal Entries**: GL entries with source and source_id; each receipt/invoice/return/payment/landed cost produces a unique entry
- **Party Site Balances**: Per-site, per-branch, per-currency balance with consistent sign convention
- **Supplier Subledger**: Database view (not materialized table) unifying all supplier movements (invoices, returns, credit/debit notes, payments, refunds, landed costs) from existing tables for reporting
- **Three-Way Match Records**: Match header and line-level variance records linking PO lines, receipt quantities, and invoice lines
- **Landed Cost Allocations**: Per-line allocation of freight, customs, insurance, and handling costs with allocation method

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero duplicate PO receipts: concurrent receive attempts on the same PO line always produce exactly one success and one rejection.
- **SC-002**: Zero over-invoicing: cumulative invoiced quantity per PO line never exceeds cumulative received quantity.
- **SC-003**: GRNI reconciliation: sum of all GRNI journal entries equals sum of all inventory receipt values minus sum of all invoice accrual reversals, with zero residual.
- **SC-004**: Cost layer integrity: every purchase return consumes the correct cost layer source (receipt, not invoice) and in the correct order (FIFO: oldest, LIFO: newest).
- **SC-005**: Supplier balance reconciliation: party_site_balances total matches GL AP account balance for every supplier, in every currency, at every month-end.
- **SC-006**: Landed cost GL balance: every landed cost posting has debit = credit (zero imbalance).
- **SC-007**: Report reconciliation: AP aging report total matches supplier subledger total, which matches GL AP balance.
- **SC-008**: VAT report completeness: net VAT input includes all purchase invoices, credit notes, and debit notes with correct signs.
- **SC-009**: Error clarity: 100% of validation failures return domain-specific messages (not generic 500 errors).
- **SC-010**: New tenant smoke test: a new tenant can complete PO → Receive → Invoice → Return → Payment → Reports without any schema or integrity errors.

## Clarifications

### Session 2026-05-10

- Q: Should quantity and cost fields use Decimal(18,4) everywhere to match DB column types, or keep the current mixed float/Decimal approach? → A: Decimal(18,4) everywhere — align with DB column type, use Python Decimal for all quantity/cost arithmetic.
- Q: How should the unified supplier subledger be built for AP reports — materialized table, database view, or application-level aggregation? → A: Database view over existing tables — no data duplication, always consistent, query-time join over invoices/payments/returns/credit notes.
- Q: Should supplier balance sign validation fix historical data or enforce correct signs going forward only? → A: Enforce correct signs going forward only — add sign validation at write time; historical data repaired by a separate one-time script.

## Assumptions

- The existing database is PostgreSQL with row-level locking support.
- The application uses a single-database, multi-tenant architecture with tenant schemas.
- Costing methods (FIFO, LIFO, WAC) are configured per-product and respected by the costing service.
- Exchange rates are stored as "base per foreign currency" (e.g., 1 USD = 3.75 SAR).
- The fiscal period lock mechanism already exists and is functional; this feature relies on it for date validation.
- Existing historical data with integrity issues is not repaired by this feature; a separate data migration/cleanup effort may follow.
- The GL service's duplicate guard (source + source_id + date) is the correct behavior for preventing double-posting; the fix is to ensure each receipt gets a unique source_id.
- The party_balance sign convention (invoice = negative for suppliers, payment = positive) is the intended design; the fix is to ensure all callers follow it.
- Arabic and English error messages are both acceptable; the system should return the user's preferred language when available.
- All quantity and cost arithmetic uses Decimal(18,4) to match database column types; float is not used for any financial or inventory calculations.
