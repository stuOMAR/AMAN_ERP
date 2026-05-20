# AMAN ERP Procurement & Purchases Full Cycle - Comprehensive Audit Report

## 1. Executive Summary
This report presents the findings of a rigorous architecture and code-level audit conducted on the **Procurement and Purchases Full Cycle** of the AMAN ERP system. The audit focused on compliance with `SYSTEM_CONSTITUTION.md` and `ARCHITECTURE.md`, specifically evaluating financial precision, transaction atomicity, multi-tenant isolation, idempotency, and cross-module integrations (Accounting, Inventory, Costing, Tax, and Treasury).

**Overall Assessment:** The backend architecture demonstrates a high level of maturity. Core systems such as the `gl_service.py` (General Ledger), `costing_service.py` (Inventory Valuation), and `wht_service.py` (Withholding Tax) adhere strictly to the established architectural tenets. However, critical violations regarding the usage of `float` instead of `Decimal` were discovered in the application layer (routers) and the Frontend, which pose an immediate risk to financial precision.

## 2. Core Architectural Compliance & Findings

### 2.1 Financial Precision (`float` vs `Decimal`)
**Standard:** Use `Decimal` in Python and string/fixed-point handling in JavaScript for monetary values. `float` and `double` are strictly forbidden.

**Findings (CRITICAL RISK):**
Despite the core services (`gl_service`, `costing_service`) strictly enforcing `Decimal` arithmetic, several API routers cast values to `float` before passing them to the services or database.

*   **`backend/routers/purchases/returns.py`:**
    *   Line 497: `unit_cost=float(return_unit_cost)`
    *   Line 536: `{"qty": float(return_qty)}`
    *   Lines 558-560: `qty: -float(...)`, `unit_cost: float(...)`, `total_cost: float(...)`
*   **`backend/routers/purchases/orders.py`:**
    *   Line 615: `new_qty=float(item_qty)` passed into `CostingService.update_cost`
*   **`backend/routers/purchases/invoices.py`:**
    *   Line 149: `total_base": float(_dec(r["total"]) * ...)`
    *   Line 1219: `unit_cost=float(unit_cost)`

**Frontend Findings (HIGH RISK):**
The React Frontend extensively relies on native JavaScript `Number()` for monetary aggregations and displays (e.g., in `PaymentForm.jsx`, `PurchaseInvoiceForm.jsx`, `PurchaseDebitNotes.jsx`). JavaScript numbers are double-precision 64-bit floats, which inevitably lead to rounding discrepancies (e.g., `0.1 + 0.2 = 0.30000000000000004`). 
*   Recommendation: The Frontend must migrate to a library like `decimal.js` or `big.js` for all monetary calculations to mirror backend precision.

### 2.2 Transactional Integrity and Concurrency
**Standard:** Journal entries must stay balanced. Concurrent operations must not corrupt inventory or financial ledgers.

**Findings (PASS):**
*   **Inventory Receipts (`orders.py`):** Uses strict `SELECT ... FOR UPDATE` locks on PO lines and inventory tables to prevent race conditions during concurrent receiving.
*   **Costing Updates (`costing_service.py`):** Correctly acquires nested transactions and row-level locks on `products` and `inventory` tables before executing WAC (Weighted Average Cost) calculations.
*   **Ledger Postings (`gl_service.py`):** Safely encapsulates debit and credit validation. Ensures balancing to zero before committing the Journal Entry (JE). 

### 2.3 Idempotency
**Standard:** API endpoints resulting in financial or inventory mutations must be idempotent to handle network retries safely.

**Findings (PASS):**
*   **Purchases API:** `invoices.py` explicitly captures the `Idempotency-Key` header and validates it against the `invoices` table (`ON CONFLICT (idempotency_key) ...`).
*   **GL Service:** `gl_service.create_journal_entry` requires an `idempotency_key` parameter for critical automated entries (like WHT).

### 2.4 Cross-Module Integrations
**Findings (PASS):**
*   **3-Way Matching (`matching_service.py`):** Robustly implemented. Compares invoice quantities/prices against PO terms and GRN receipts. Supports customizable tolerance configurations globally and per-supplier.
*   **Landed Costs (`costing_service.py`):** `apply_landed_cost_adjustment` correctly increases the valuation of specific inventory and FIFO/LIFO cost layers without manipulating the physical quantity on hand.
*   **Withholding Tax / WHT (`wht_service.py`):** Perfectly abstracts tax deduction. It parses gross payments, computes the withheld amount based on country/payment rules, deducts it from the bank credit, and correctly books the withheld portion to a "WHT Payable" liability account in a single atomic JE.
*   **Fiscal Period Locking:** Properly invoked (`check_fiscal_period_open`) across purchasing, invoicing, and payment modules, providing a hard wall against backdating transactions into closed accounting periods.

## 3. Remediation Roadmap

The following actions are required to bring the Procurement cycle into 100% compliance with the System Constitution.

### Phase 1: Backend Precision Overhaul (High Priority)
1.  **Refactor `returns.py`**: Replace all `float()` casting with `Decimal(str(...))` or the `_dec()` utility.
2.  **Refactor `orders.py`**: Fix line 615; `CostingService.update_cost` accepts strings/Decimals safely. Pass `str(item_qty)` instead of `float(item_qty)`.
3.  **Refactor `invoices.py`**: Remove `float()` wrapping from `total_base` calculations and unit costs.

### Phase 2: Frontend Calculation Refactor (Medium Priority)
1.  Introduce `decimal.js` (or similar) into the Vite/React frontend.
2.  Refactor forms (`PurchaseInvoiceForm.jsx`, `PaymentForm.jsx`, `PurchaseDebitNotes.jsx`) to use Decimal objects for all multiplication (exchange rates, taxes, discounts) and addition (subtotals, totals).
3.  Remove all `Number()` aggregations in JSX rendering logic.

### Phase 3: Tenant Schema Verification (Low Priority / Routine)
1.  Audit `backend/db_ddl/tenant_schema.py` to ensure all columns related to `wht_rules`, `three_way_matches`, and `match_tolerances` are present and strictly typed as `NUMERIC(18, 4)` or equivalent, rather than `REAL` or `DOUBLE PRECISION`.

---
**Auditor:** Antigravity (Senior ERP Auditor)
**Date:** May 20, 2026
