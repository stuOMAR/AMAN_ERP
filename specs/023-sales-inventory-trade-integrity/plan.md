# Implementation Plan: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing Remediation (R3 + R4)

**Branch**: `023-sales-inventory-trade-integrity` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/023-sales-inventory-trade-integrity/spec.md`

## Summary

Deliver R3 (Sales / POS / CRM / ZATCA) and R4 (Inventory / Costing / Manufacturing) from `docs/audit/REMAINING_REMEDIATION_PLAN.md` as one coordinated change set built on top of feature 022's primitives (audit outbox, PII sanitizer, sensitive-permission gate, account classification, secret vault, JE source enum, fiscal-period policy, treasury balance trigger).

The plan introduces:

- a single **Order → Invoice** service + endpoint with idempotency, line snapshotting, GL via `gl_service`, ZATCA outbox enqueue, and back-link `SalesOrder.converted_to_invoice_id`;
- a **canonical invoice state machine** (the only writer of `invoice.state`) used by sales, returns, ZATCA, and cancellation;
- **cancel/return hardening**: full-line inventory pre-flight, `(source, source_id)` linkage on reversal JEs, and consolidation of `sales_returns` + `pos_returns` into `returns_unified` (plus consolidation of `acc_map_sales` / `acc_map_sales_rev`);
- **POS multi-session safety**: per-warehouse Redis stock lock with row-lock fallback, complete (all-line) inventory check, bulk INSERT sweep;
- **POS offline reconcile**: client-UUID-keyed `pos_offline_batches` queue with a reconcile worker that re-validates against current stock and routes failures to `manual_review`;
- **CRM coherence**: opportunity stage history powering deterministic sales-velocity / funnel-conversion formulas, paginated activity feeds, opportunity assignment events, and a sales-forecast → cash-flow forecast feed;
- **ZATCA outbox + inline UBL/signing**: `zatca_outbox` with retry / backoff / dead-letter, inline UBL builder (standard + simplified), inline XML signing using vault credentials;
- **WAC per warehouse** as the single costing path across inventory, transfers, sales-issue, purchase-receipt, manufacturing consumption, and completion;
- **Decimal sweep** at every monetary/quantity boundary in the modules in scope, guarded by a CI lint;
- **Auto-reorder + MRP**: per-item-per-warehouse settings, scheduler producing recommendations, optional auto-PO creation, multi-level BOM net requirements with cycle detection;
- **Production completion overhaul**: BOM snapshot at start, partial completion with per-batch JEs at actual cost, by-product allocation, scrap as a first-class movement, optional QC gate, missing-mapping diagnostics, optional routing operations, deterministic `existing_qty`, large-MO approval, per-workstation overhead, shop-floor↔attendance link;
- **Cleanup**: 410 Gone on the deprecated transfer endpoint, `inventory_transactions` archival/retention, scoped `inventory.low_stock` webhook with debounce.

The technical approach favors small, sequenced migrations + additive contracts so existing modules continue to compile while we sweep callsites onto the new helpers, mirroring the discipline used in feature 022.

## Technical Context

**Language/Version**: Python 3.12 (FastAPI), JavaScript (React 18 / Vite) for the small surfaces this feature requires.
**Primary Dependencies**: FastAPI, SQLAlchemy + raw SQL, Pydantic at API boundary, APScheduler / existing worker, Redis (POS lock + low-stock debounce + outbox advisory locks), PostgreSQL `pgcrypto` (signing-key envelope reuse from 022 vault), `lxml`/`signxml` (or equivalent vetted lib already vendored) for UBL signing, existing `transactional()`, `gl_service`, `account_classifier` (from 022), `require_sensitive_permission` (from 022), `audit_writer` (from 022), `sanitize_for_audit` (from 022).
**Storage**: PostgreSQL 15, one DB per tenant. New tables: `zatca_outbox`, `mrp_recommendations`, `bom_snapshots`, `production_completions`, `pos_offline_batches`, `opportunity_stage_history`, `scrap_movements`, `item_warehouse_settings` (if missing), `inventory_transactions_archive`. Extensions to existing tables: `sales_orders` (`converted_to_invoice_id`, `responsible_user_id`), `invoices` (state machine columns, idempotency key), `manufacturing_orders` (`bom_snapshot_id`, `remaining_qty`, `qc_required`, extended state enum), `workstations` (`overhead_rate`, `effective_from`, `effective_to`). Compatibility views: `sales_returns`, `pos_returns`, `acc_map_sales_rev`.
**Testing**: Tests are not required by this plan; the user explicitly asked for an exhaustive spec/plan but did not request tests. CI gates here are static / discovery-based:
- `scripts/check_no_float_money.py` — forbid `float` in cost/qty arithmetic in inventory, costing, manufacturing modules;
- `scripts/check_invoice_state_writers.py` — forbid `UPDATE invoices SET state` outside the state machine module;
- `scripts/check_je_source_id.py` — forbid free-text `reference_number` use as the linkage key for reversals;
- `scripts/check_pos_lock_usage.py` — forbid POS commit paths without the Redis lock helper;
- `scripts/check_get_acc_id_callsites.py` — forbid scattered `get_acc_id(code)` outside the central resolver.
Tests may be added by the implementer when risk warrants (e.g., the deterministic sales-velocity fixtures).
**Target Platform**: Linux server backend; browser frontend; existing mobile POS surface for offline reconcile.
**Project Type**: AMAN ERP web application (backend + frontend; small mobile POS adjustments for offline batches).
**Performance Goals**: Order→Invoice end-to-end ≤ 800ms p95 for typical 10-line orders; POS commit p95 within +20% under ≥10 concurrent commits per warehouse; ZATCA outbox flush 99% within 5 minutes under normal load; MRP run for 10 000 items completes ≤ 5 minutes; auto-reorder scan ≤ 30s for 5 000 (item, warehouse) pairs; low-stock webhook decision ≤ 5ms (Redis dedupe).
**Constraints**: Decimal/NUMERIC for all money and quantity; tenant isolation via `get_db_connection(company_id)`; GL postings only via `gl_service` with `JESource` enum; every new endpoint declares `require_permission()` and (for sensitive surfaces) `require_sensitive_permission()`; every schema change ships an Alembic migration **and** updates `backend/db_ddl/tenant_schema.py` + `backend/database.py`; every credential read goes through 022's vault; every audit write goes through 022's outbox writer.
**Scale/Scope**: Multi-tenant; ~10 new tables, ~5 modified tables, ~2 new workers (ZATCA outbox flusher, POS offline reconciler) plus extended scheduler jobs (auto-reorder, MRP, archiver), ~12 service modules touched (sales, invoices, returns, pos, pos_offline, crm, einvoicing, inventory, costing, manufacturing, scheduler, webhooks). Frontend changes limited to ~5 surfaces (Order→Invoice action, ZATCA outbox monitor, MRP recommendations, production partial-completion, POS reconnect status).

## Constitution Check

*Initial pass — pre-research. Re-evaluated after Phase 1 design (see end of section).*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | All monetary and quantity fields declared `NUMERIC(18,4)` (qty `NUMERIC(18,6)` where finer precision is required); all arithmetic in `Decimal` with ROUND_HALF_UP; `float` banned by lint in modules in scope | PASS |
| Tenant isolation | All new tables carry `tenant_id`; all access via `get_db_connection(company_id)`; ZATCA + reconcile workers scoped per tenant; Redis keys namespaced `<tenant_id>:` | PASS |
| GL integrity | Order→Invoice posts via `gl_service`; cancellation reversal JE uses `(source, source_id)`; production completion / scrap / by-product all post via `gl_service`; balance JE epsilon and source enum honored | PASS |
| Security boundary | New sensitive endpoints (Order→Invoice, ZATCA outbox monitor, MRP recommendations, production approval, account-mapping admin, returns admin) wrapped with `require_sensitive_permission`; startup discovery from 022 enforces coverage | PASS |
| Regulatory settings | ZATCA UBL profile / signing algorithm / cert source come from secret vault + tenant settings; reorder thresholds, MRP horizons, QC tolerances, large-MO thresholds all in `company_settings` | PASS |
| Calculation centralization | Single `account_mapping_resolver` (consumes 022 classifier); single `wac_service` per-warehouse; single `byproduct_allocator`; single `invoice_state_machine`; single `pos_stock_lock` helper | PASS |
| Report consistency | New movement types (scrap, by-product) and partial completions reflected in inventory valuation reports through the same classifier-backed paths | PASS |
| Concurrency | POS commit + return: per-warehouse Redis lock with row-level `SELECT FOR UPDATE` fallback; purchase return: bulk `SELECT ... FOR UPDATE`; ZATCA outbox: `FOR UPDATE SKIP LOCKED`; MRP run: advisory lock per tenant; pos_offline reconcile: per-batch idempotent | PASS |
| Query discipline | Bulk INSERT for POS / inventory movements; bounded batch sizes for outbox flushers; partial indices on outbox + offline batch state; MRP explosion bounded by depth + cycle detection; auto-reorder paginated | PASS |
| UI consistency | New admin / monitor screens reuse DataTable, inline error, i18n, destructive-confirm patterns | PASS |
| Schema sync | Every new/changed table ships an Alembic migration **and** updates `backend/db_ddl/tenant_schema.py` + `backend/database.py` in the same task | PASS |
| Artifact boundaries | `data-model.md` lists tables and critical fields only — no full DDL | PASS |
| Spec format | Spec uses requirements + acceptance criteria + edge cases; no user stories | PASS |

**Initial Constitution Check: PASS — proceed to Phase 0.**

## Design Artifact Rules

`data-model.md` lists table names, critical fields, relationships, validation rules and state transitions only. No full DDL is generated; the actual DDL is produced by Alembic migrations and the canonical `tenant_schema.py` / `database.py` updates during implementation.

## Project Structure

### Documentation (this feature)

```text
specs/023-sales-inventory-trade-integrity/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── order-to-invoice.md
│   ├── invoice-state-machine.md
│   ├── sales-cancellation.md
│   ├── returns-unified.md
│   ├── account-mapping-resolver.md
│   ├── pos-stock-lock.md
│   ├── pos-offline-reconcile.md
│   ├── crm-velocity-funnel.md
│   ├── crm-cashflow-feed.md
│   ├── zatca-outbox.md
│   ├── ubl-signing.md
│   ├── wac-per-warehouse.md
│   ├── auto-reorder.md
│   ├── mrp-net-requirements.md
│   ├── production-completion.md
│   ├── byproduct-allocation.md
│   ├── qc-gate.md
│   ├── workstation-overhead.md
│   ├── inventory-archival.md
│   ├── inventory-low-stock-webhook.md
│   └── http-endpoints.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 023a_invoice_state_and_idempotency.py
│   ├── 023b_sales_order_invoice_link.py
│   ├── 023c_returns_unified_table.py
│   ├── 023d_acc_map_sales_consolidation.py
│   ├── 023e_zatca_outbox.py
│   ├── 023f_opportunity_stage_history.py
│   ├── 023g_pos_offline_batches.py
│   ├── 023h_item_warehouse_settings.py
│   ├── 023i_mrp_recommendations.py
│   ├── 023j_bom_snapshots_and_mo_extensions.py
│   ├── 023k_production_completions_and_scrap.py
│   ├── 023l_workstation_overhead.py
│   └── 023m_inventory_transactions_archive.py
├── db_ddl/
│   └── tenant_schema.py            # extended with all new tables/columns/views
├── database.py                     # synced with the tenant_schema additions
├── models/
│   └── domain_models/
│       ├── zatca_outbox.py
│       ├── mrp_recommendation.py
│       ├── bom_snapshot.py
│       ├── production_completion.py
│       ├── pos_offline_batch.py
│       ├── opportunity_stage_history.py
│       ├── scrap_movement.py
│       └── item_warehouse_settings.py
├── services/
│   ├── sales/
│   │   ├── order_to_invoice.py     # NEW
│   │   ├── invoice_state.py        # NEW: the only invoice.state writer
│   │   ├── sales_cancellation.py   # NEW: full-line preflight + reversal
│   │   └── account_mapping.py      # NEW: central account-mapping resolver
│   ├── returns_unified_service.py  # NEW: writes to consolidated table
│   ├── pos/
│   │   ├── stock_lock.py           # NEW: Redis lock + DB fallback
│   │   ├── pos_commit.py           # extended: bulk INSERT, full pre-flight
│   │   └── pos_offline_reconcile.py # NEW: worker
│   ├── crm/
│   │   ├── velocity.py             # NEW: deterministic formula
│   │   ├── funnel.py               # NEW
│   │   ├── activity_feed.py        # extended: pagination/filters
│   │   └── cashflow_feed.py        # NEW
│   ├── einvoicing/
│   │   ├── outbox.py               # NEW: zatca_outbox writer + worker
│   │   ├── ubl_builder.py          # extended: standard + simplified
│   │   └── ubl_signer.py           # NEW: inline signing using vault
│   ├── inventory/
│   │   ├── wac_per_warehouse.py    # NEW: canonical WAC service
│   │   ├── auto_reorder.py         # NEW
│   │   ├── archival.py             # NEW
│   │   └── low_stock_webhook.py    # NEW
│   ├── manufacturing/
│   │   ├── mrp.py                  # NEW: net req + multi-level BOM
│   │   ├── production_complete.py  # extended: partial + actual cost
│   │   ├── byproduct_allocator.py  # NEW
│   │   ├── qc_gate.py              # NEW
│   │   ├── scrap.py                # NEW: scrap_movements writer
│   │   └── workstation_overhead.py # NEW
│   └── webhooks/                   # extended dispatcher hook for low_stock
├── routers/
│   ├── sales/
│   │   └── order_to_invoice.py     # NEW endpoint
│   ├── einvoicing/
│   │   └── outbox_admin.py         # NEW monitor endpoints
│   ├── manufacturing/
│   │   ├── mrp_recommendations.py  # NEW
│   │   └── production_approval.py  # NEW
│   ├── inventory/
│   │   ├── transfers.py            # canonical /transfers (deprecated /transfer → 410)
│   │   └── archival_admin.py       # NEW
│   ├── pos/
│   │   └── offline.py              # NEW: offline batch ingest + status
│   └── (existing routers updated to use require_sensitive_permission)
├── scripts/
│   ├── check_no_float_money.py
│   ├── check_invoice_state_writers.py
│   ├── check_je_source_id.py
│   ├── check_pos_lock_usage.py
│   └── check_get_acc_id_callsites.py
└── locales/                        # i18n keys for new errors

frontend/
└── src/
    └── pages/
        ├── sales/
        │   └── OrderToInvoiceAction.jsx
        ├── einvoicing/
        │   └── ZatcaOutboxMonitor.jsx
        ├── manufacturing/
        │   ├── MrpRecommendations.jsx
        │   └── ProductionPartialCompletion.jsx
        └── pos/
            └── ReconnectStatus.jsx

mobile/
└── src/
    └── pos/
        └── offline_queue.js        # extended: client UUID + reconcile push
```

**Structure Decision**: Web application (backend + frontend) with a small mobile POS adjustment for offline batches. Backend changes dominate. Migrations live under `backend/alembic/versions/` and are mirrored in `backend/db_ddl/tenant_schema.py` and `backend/database.py` per Principle XXVIII (Schema Sync).

## Dependency on Feature 022

This plan **strictly consumes** the following primitives delivered by feature 022. They MUST exist (or ship concurrently) before this feature can be merged:

- `services/audit_writer.py::log_activity` (outbox-backed; safe inside `transactional()`).
- `services/audit_sanitizer.py::sanitize_for_audit` (used on every audited request body & error).
- `services/permissions/sensitive.py::require_sensitive_permission` (with startup discovery hook).
- `services/credentials_vault.py` (ZATCA cert + signing key live here; no other store may be introduced).
- `services/account_classifier.py` (used by the new central account-mapping resolver).
- `JESource` enum + `gl.je_epsilon` + `fiscal.allow_drafts_in_closed_period` semantics in `gl_service`.
- `tg_treasury_balance_authority` trigger and `aman.gl_context` GUC (treasury writes from this feature respect the trigger automatically because they go through `gl_service`).

Every new audited write, every new sensitive endpoint, every new credential, and every new posted JE in this feature MUST route through those primitives. No parallel implementation is permitted.

## Post-Design Constitution Check

*Re-evaluated after Phase 1 artifacts (`data-model.md`, `contracts/`, `quickstart.md`) were written.*

| Gate | Status After Design |
|------|---------------------|
| Financial precision | PASS — all monetary fields confirmed `NUMERIC(18,4)`, quantities `NUMERIC(18,6)` where needed; lint forbids `float` in cost/qty arithmetic; epsilons and tolerances pulled from `company_settings`. |
| Tenant isolation | PASS — every new table has `tenant_id`; all workers acquire connections via `get_db_connection(company_id)`; Redis keys namespaced. |
| GL integrity | PASS — Order→Invoice, cancellation, completion, scrap, by-product, WIP→FG all post via `gl_service` with `JESource` enum and `(source, source_id)` linkage. |
| Security boundary | PASS — new sensitive endpoints wrapped via 022's decorator; ZATCA + signing credentials read only from 022's vault; offline POS ingest requires device authentication and per-tenant rate limit. |
| Regulatory settings | PASS — ZATCA, reorder, MRP, QC, large-MO thresholds all configured. |
| Calculation centralization | PASS — single state machine, single account-mapping resolver, single WAC service, single by-product allocator, single POS lock helper. |
| Report consistency | PASS — new movements (scrap, by-product, partial completion, archival) flow through classifier-backed reporting paths. |
| Concurrency | PASS — POS Redis lock + DB fallback, bulk `FOR UPDATE` in purchase return, `FOR UPDATE SKIP LOCKED` in outbox + offline reconciler, advisory lock for MRP. |
| Query discipline | PASS — bulk INSERT, bounded batches, partial indices, paginated CRM activity, MRP cycle detection. |
| UI consistency | PASS — new screens follow the standard primitives. |
| Schema sync | PASS — every migration paired with `tenant_schema.py` + `database.py` updates. |
| Artifact boundaries | PASS — no DDL in `data-model.md`. |
| Spec format | PASS — requirements + acceptance + edge cases; no user stories. |

**Post-Design Constitution Check: PASS — proceed to Phase 2 (`/speckit.tasks`).**

## Complexity Tracking

No principle is violated; nothing to justify here.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
