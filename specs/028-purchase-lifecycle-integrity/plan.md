# Implementation Plan: Purchase Lifecycle Integrity Overhaul

**Branch**: `028-purchase-lifecycle-integrity` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/028-purchase-lifecycle-integrity/spec.md`

## Summary

Fix 16 critical integrity issues across the purchase lifecycle (PO receiving, invoicing, returns, payments, GL posting, landed costs, supplier balances, reporting). The core problems are: missing row-level locks allowing concurrent duplicate operations, product-only matching instead of PO-line-level matching, broken cost layer linkage for returns, inconsistent supplier balance signs, non-functional landed cost integration, and incomplete AP/VAT reports. The fix requires adding `po_line_id` to `invoice_lines`, creating a `supplier_subledger` database view, unifying transaction type enums, enforcing Decimal(18,4) precision, and adding atomic quantity checks with `FOR UPDATE` locks throughout.

## Technical Context

**Language/Version**: Python 3.12 backend; React 18/Vite frontend
**Primary Dependencies**: FastAPI, SQLAlchemy/raw SQL via `text()`, Pydantic at API boundary, React, i18next, PostgreSQL 15
**Storage**: PostgreSQL 15, one database per tenant (multi-tenant schema via `tenant_schema.py`), Redis cache
**Testing**: pytest for backend, Playwright for E2E; tests planned only when explicitly requested
**Target Platform**: Linux server backend, browser frontend
**Project Type**: AMAN ERP web application — backend (`backend/`) + frontend (`frontend/`)
**Performance Goals**: No N+1 queries; no unbounded result sets; queries above 2s require optimization
**Constraints**: Decimal/NUMERIC(18,4) financial precision, tenant isolation via `get_db_connection(company_id)`, GL-backed reports, permission-gated endpoints, Alembic migrations + `tenant_schema.py` sync
**Scale/Scope**: Multi-tenant ERP; 16 integrity fixes across ~15 backend files and ~5 frontend files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No project constitution file found at `.specify/memory/constitution.md`. Applying AMAN ERP standard gates based on codebase conventions:

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | All quantity/cost arithmetic uses Decimal(18,4); `_dec()` helper pattern; `ROUND_HALF_UP` for money | PASS — FR-041 mandates Decimal everywhere |
| Tenant isolation | All DB access via `get_db_connection(company_id)` inside `transactional()` context | PASS — existing pattern preserved |
| GL integrity | All accounting mutations post through `gl_create_journal_entry()` with balanced JE lines | PASS — FR-004/005 fix source_id uniqueness |
| Security boundary | Every endpoint uses `require_permission()`; sensitive output masked | PASS — existing pattern preserved |
| Regulatory settings | ZATCA, tax rates from settings/tables, not hardcoded | N/A — no regulatory changes |
| Calculation centralization | Cost calculations via `CostingService`, balance via `update_party_site_balance` | PASS — FR-021 enforces costing service |
| Report consistency | Reports derive from GL-backed views; supplier subledger view created | PASS — FR-027/028/030 |
| Concurrency | `FOR UPDATE` on PO lines, inventory rows, balance rows, invoice rows | PASS — FR-001/002/024 |
| Query discipline | No N+1; supplier subledger view avoids repeated joins | PASS |
| UI consistency | DataTable, inline errors, i18n, destructive confirmation | N/A — minimal UI changes |
| Schema sync | Alembic migration + `tenant_schema.py` update for `po_line_id` column | PASS — FR-037/038 |
| Artifact boundaries | Data model lists tables and critical fields only | PASS |
| Spec format | Requirements and acceptance criteria; no user stories | PASS |

## Design Artifact Rules

`data-model.md` MUST list entity/table names, critical fields, relationships, validation rules, and state transitions only. Do not generate full DDL unless the user explicitly asks for DDL.

## Project Structure

### Documentation (this feature)

```text
specs/028-purchase-lifecycle-integrity/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
backend/
├── routers/
│   ├── purchases/
│   │   ├── orders.py          # PO receiving (FR-001 to FR-005), RFQ (FR-039/040)
│   │   ├── invoices.py        # PO invoicing (FR-006 to FR-010), direct invoice (FR-031)
│   │   ├── returns.py         # Purchase returns (FR-011 to FR-015, FR-016/018)
│   │   └── payments.py        # Supplier payments (FR-024 to FR-026)
│   ├── landed_costs.py        # Landed costs (FR-019 to FR-023)
│   ├── reports/
│   │   └── purchases.py       # AP reports (FR-027, FR-028, FR-030)
│   ├── inventory/
│   │   └── reports.py         # Stock movement (FR-031)
│   └── finance/
│       └── taxes/reports.py   # VAT reports (FR-029)
├── services/
│   ├── gl_service.py          # GL journal entries (FR-004/005)
│   ├── matching_service.py    # 3-way matching (FR-009)
│   └── costing_service.py     # Cost layers (FR-011 to FR-015)
├── utils/
│   ├── party_balance.py       # Supplier balance (FR-016 to FR-018)
│   └── tx.py                  # Transaction management
├── db_ddl/
│   └── tenant_schema.py       # Schema DDL (FR-037)
└── alembic/versions/          # Migration for po_line_id column

frontend/
└── src/
    └── pages/
        └── Buying/
            ├── BuyingOrderDetails.jsx    # Convert-to-invoice guard (FR-032)
            ├── PurchaseInvoiceForm.jsx   # Pre-fill fix (FR-033)
            ├── LandedCosts.jsx           # Schema alignment (FR-019)
            └── RFQList.jsx               # RFQ flow (FR-039/040)
```

**Structure Decision**: Web application (Option 2) — backend + frontend as established in the AMAN ERP codebase.
