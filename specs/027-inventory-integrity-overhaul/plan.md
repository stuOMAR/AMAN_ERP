# Implementation Plan: Inventory Costing and GL Integration Overhaul

**Branch**: `027-inventory-integrity-overhaul` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/027-inventory-integrity-overhaul/spec.md`

## Summary

The inventory subsystem has 13 integrity defects (10 high, 3 medium) spanning sales issuance, FIFO/LIFO layer consumption, returns/cancellation, PO receipt vs. invoice, adjustments, transfers, shipments, WAC concurrency, manufacturing costing, schema mismatches, cycle counts, valuation reports, and input validation. The fix strategy is: (1) enforce available-quantity checks with atomic `UPDATE ... WHERE ... RETURNING id`, (2) eliminate silent fallback from FIFO/LIFO to `cost_price`, (3) reuse the existing `CostingService` as the costing authority while unifying duplicate adjustment logic in place, and (4) resolve schema mismatches by adapting services and indexes to the existing `inventory_transactions` columns.

## Technical Context

**Language/Version**: Python 3.12 backend
**Primary Dependencies**: FastAPI, raw SQL via psycopg2/asyncpg, Pydantic v2 at API boundaries
**Storage**: PostgreSQL 15, one database per tenant
**Testing**: Integration tests for critical flows (concurrent sales, FIFO consumption, cancellation reversal)
**Target Platform**: Linux server backend
**Project Type**: AMAN ERP web application — backend only (no frontend changes in this feature)
**Performance Goals**: No N+1 queries; WAC/FIFO row locks held briefly; no unbounded result sets
**Constraints**: Decimal/NUMERIC financial precision (ROUND_HALF_UP), tenant isolation via schema-per-tenant, GL-backed postings via `gl_service.py`, permission-gated endpoints, migration + schema sync required
**Scale/Scope**: Multi-tenant ERP — inventory module affecting sales, purchases, manufacturing, POS, transfers, shipments, reports

### Current Architecture (from codebase exploration)

**CostingService** (`backend/services/costing_service.py`, 694 lines):
- Static methods: `update_cost`, `consume_layers`, `handle_return`, `create_cost_layer`, `get_cogs_cost`, `calculate_inventory_valuation`
- WAC is default; FIFO/LIFO is opt-in per product via `cost_layers` table
- `consume_layers` (line 241) already uses `FOR UPDATE` on both `inventory` and `cost_layers`
- `handle_return` (line 320) exists but is NOT called by cancellation or POS returns
- Precision: `Decimal` with `_D4 = Decimal('0.0001')` and `ROUND_HALF_UP`

**Sales Invoices** (`backend/routers/sales/invoices.py`):
- `create_sales_invoice` (line 252): locks inventory `FOR UPDATE` (line 503), validates quantity (line 511), deducts (line 519), consumes layers for FIFO/LIFO (line 534), posts GL (line 654)
- `cancel_invoice` (line 930): adds quantity back (line 970), reverses GL (line 1005), but does NOT reverse cost layers

**POS Orders** (`backend/routers/pos/orders.py`):
- `create_order` (line 37): locks inventory (line 312), consumes layers (line 323), deducts (line 345), posts GL (line 401)
- `create_return` (line 672): adds quantity back (line 746), reverses GL (line 820), but does NOT reverse cost layers

**Purchases**:
- `receive_purchase_order` (`purchases/orders.py`, line 468): locks inventory (line 556), adds quantity (line 562), logs transaction (line 573), posts accrual GL (line 627) — but does NOT call `CostingService.update_cost` or `create_cost_layer`
- `create_purchase_invoice` (`purchases/invoices.py`, line 246): calls `update_cost` (line 481) and `create_cost_layer` for FIFO/LIFO (line 497), logs transaction (line 547), posts GL (line 619) — processes FULL quantity even if already received

**Inventory Adjustments** (`backend/routers/inventory/adjustments.py`):
- `create_adjustment` (line 67): locks inventory (line 92), validates (line 101), upserts inventory (line 145), logs transaction (line 161), posts GL (line 180)
- Separate path from `stock_movements.py` — two competing adjustment routes

**Transfers** (`backend/routers/inventory/transfers.py`):
- `create_stock_transfer` (line 24): locks source+dest (lines 68, 85), deducts source (line 94), calculates WAC on dest (line 100), logs (line 132), posts GL (line 174)
- No `gt=0` validation on quantity field

**Shipments** (`backend/routers/inventory/shipments.py`):
- `create_shipment` (line 26): creates document only, no inventory movement
- `confirm_shipment` (line 269): locks source (line 316), deducts (line 328), consumes layers (line 334), creates layers at dest (line 365), logs (line 435), posts GL with in-transit bridge (line 487)
- No `gt=0` validation on quantity

**Manufacturing** (`backend/routers/manufacturing/core/orders.py`):
- `start_production_order` (line 361): locks order (line 370), checks inventory (line 388), consumes materials via raw `ON CONFLICT` (line 428) — does NOT use `CostingService.consume_layers`
- `complete_production_order` (line 523): adds FG (line 563), logs (line 605), posts GL (line 605), manually calculates WAC (line 701) — does NOT create cost layer for FG, does NOT lock order for completion

**Schema** (`backend/db_ddl/tenant_schema.py`):
- `inventory_transactions` (line 494): has `product_id`, `warehouse_id`, `transaction_type`, `quantity`, `unit_cost`, `created_at` — does NOT have `transaction_date`, `tenant_id`, `item_id`
- `wac_per_warehouse.py` (line 130) inserts with `tenant_id` — will fail at runtime

**Schemas/Validation**:
- `inventory/schemas.py` line 12: `ProductCreate` has no `gt=0` on `selling_price`, `buying_price`
- `schemas/purchases.py` line 8: `PurchaseLineItem` has no `gt=0` on `quantity`, `unit_price`
- `inventory/schemas.py` line 100: `StockTransferSingleCreate` has no `gt=0` on `quantity`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | All costing uses `Decimal` with `ROUND_HALF_UP`; `CostingService` already enforces `_D4` precision; new code must maintain this | PASS |
| Tenant isolation | All DB access goes through `get_db_connection(company_id)` — no cross-tenant reads; schema-per-tenant model | PASS |
| GL integrity | All inventory mutations post through `gl_service.py` with balanced JEs; `check_fiscal_period_open` enforced; adjustments route must enforce GL posting | PASS |
| Security boundary | All endpoints use `require_permission()`; no sensitive data in logs; rate limiting on high-risk routes | PASS |
| Regulatory settings | No ZATCA/GOSI/WPS changes in this feature; VAT handling unchanged | N/A |
| Calculation centralization | `CostingService` is the canonical costing service; `wac_per_warehouse.py` is a separate service that must be reconciled or deprecated | PASS |
| Report consistency | Valuation reports will use `CostingService.calculate_inventory_valuation()` instead of `products.cost_price` | PASS |
| Concurrency | `FOR UPDATE` locks are already used in sales, POS, transfers, shipments, PO receipt; WAC calculation in `update_cost` needs `FOR UPDATE` added; manufacturing completion needs order lock | PASS |
| Query discipline | No new heavy queries; existing patterns maintained | PASS |
| UI consistency | No frontend changes in this feature | N/A |
| Schema sync | Schema alignment requires migration + `tenant_schema.py` update for any column additions; service adaptation alternative documented | PASS |
| Artifact boundaries | Data model lists tables and critical fields only; no full DDL | PASS |
| Spec format | No user stories; uses requirements, acceptance criteria, edge cases | PASS |

**Gates**: All applicable gates PASS. No violations to justify.

### Post-Design Re-Evaluation

Re-evaluated after Phase 1 design artifacts (data-model.md, contracts/api-contracts.md, quickstart.md):

| Gate | Post-Design Evidence | Status |
|------|---------------------|--------|
| Financial precision | All cost calculations use `Decimal` with `ROUND_HALF_UP` via `CostingService`; no new float usage introduced | PASS |
| Tenant isolation | No changes to tenant isolation model; all DB access remains schema-scoped | PASS |
| GL integrity | New GL postings (in-transit, provisional receipt, price variance) all route through `gl_service.py` with balanced JEs; account mapping validation added for adjustments | PASS |
| Security boundary | No new endpoints without permission checks; new `dispatch` endpoint requires same permissions as `confirm` | PASS |
| Calculation centralization | All costing flows use `CostingService` methods; manufacturing switches from raw SQL to `CostingService`; adjustment paths unified | PASS |
| Report consistency | Valuation report uses `CostingService.calculate_inventory_valuation()` — consistent with costing policy | PASS |
| Concurrency | `FOR UPDATE` added to WAC calculation; production order locked at completion; all existing locks maintained | PASS |
| Schema sync | No new business columns needed; services and DDL/index definitions must be adapted to existing `inventory_transactions` columns (`created_at`, `product_id`, `warehouse_id`, references) | PASS |

**Post-Design Gates**: All applicable gates PASS. Design artifacts are constitution-compliant.

## Design Artifact Rules

`data-model.md` MUST list entity/table names, critical fields, relationships, validation rules, and state transitions only. Do not generate full DDL unless the user explicitly asks for DDL.

## Project Structure

### Documentation (this feature)

```text
specs/027-inventory-integrity-overhaul/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
backend/
├── routers/
│   ├── sales/
│   │   ├── invoices.py          # Fix: FR-001, FR-002, FR-003
│   │   └── returns.py           # Fix: FR-003
│   ├── purchases/
│   │   ├── orders.py            # Fix: FR-004
│   │   └── invoices.py          # Fix: FR-004
│   ├── inventory/
│   │   ├── __init__.py          # Fix: FR-005
│   │   ├── adjustments.py       # Fix: FR-005
│   │   ├── transfers.py         # Fix: FR-006
│   │   ├── shipments.py         # Fix: FR-006, FR-007
│   │   ├── batches.py           # Fix: FR-012
│   │   ├── stock_movements.py   # Fix: FR-005
│   │   ├── reports.py           # Fix: FR-013
│   │   └── schemas.py           # Fix: FR-014
│   ├── manufacturing/
│   │   └── core/orders.py       # Fix: FR-009, FR-010
│   └── pos/
│       └── orders.py            # Fix: FR-002, FR-003
├── services/
│   ├── costing_service.py       # Fix: FR-008 (WAC locking)
│   └── inventory/
│       └── wac_per_warehouse.py # Fix: FR-011 (schema alignment)
├── schemas/
│   └── purchases.py             # Fix: FR-014
├── db_ddl/
│   ├── tenant_schema.py         # Fix: FR-011
│   └── tenant_runner.py         # Fix: FR-011
└── reports/
    └── inventory.py             # Fix: FR-013
```

**Structure Decision**: Backend-only changes across existing module structure. No broad new movement service is planned. Fixes are in-place corrections to existing files, with only small shared helpers where duplicate logic already exists (for example inventory adjustments).

## Complexity Tracking

> **No Constitution violations to justify.** All changes align with existing principles.
