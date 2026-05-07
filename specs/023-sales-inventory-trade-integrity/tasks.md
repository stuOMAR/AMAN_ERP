# Tasks: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing Remediation (R3 + R4)

**Input**: Design documents from `/specs/023-sales-inventory-trade-integrity/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: Not requested. Verification via static CI gates (no-float-money, invoice-state-writers, je-source-id, pos-lock-usage, get-acc-id-callsites) and the smoke checks in [quickstart.md](quickstart.md). Implementer may add tests where risk warrants — particularly for CRM velocity/funnel formulas, by-product allocation, and MRP cycle detection.

**Organization**: Tasks are grouped by capability/requirement (no user stories). Capability labels reference R3.x / R4.x in `docs/audit/REMAINING_REMEDIATION_PLAN.md`.

**Dependency on feature 022**: Phase 2 of feature 022 (sanitizer + audit outbox writer + sensitive-permission decorator + discovery + secret vault + account classifier + JESource enum + treasury trigger) MUST be live before any task here begins. Do not re-implement these primitives.

## Format

`- [ ] [TaskID] [P?] [Area?] Description with file path`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks).
- **[Area]**: capability label (e.g., `[R3.1]`, `[R4.4]`); omitted on Setup, Foundational and Polish phases.

---

## Phase 1: Setup

**Purpose**: Branch hygiene, scaffolding for new modules, CI lints, i18n keys.

- [x] T001 Create directory scaffolding: `backend/services/sales/`, `backend/services/pos/`, `backend/services/crm/`, `backend/services/einvoicing/`, `backend/services/inventory/`, `backend/services/manufacturing/`, `backend/services/webhooks/`, `backend/routers/sales/`, `backend/routers/pos/`, `backend/routers/einvoicing/`, `backend/routers/manufacturing/`, `backend/routers/inventory/`, `backend/routers/crm/`, `frontend/src/pages/sales/`, `frontend/src/pages/einvoicing/`, `frontend/src/pages/manufacturing/`, `frontend/src/pages/pos/`. Add `__init__.py` where needed. No code yet.
- [x] T002 [P] Add empty CI lint scaffolds at [scripts/check_no_float_money.py](scripts/check_no_float_money.py), [scripts/check_invoice_state_writers.py](scripts/check_invoice_state_writers.py), [scripts/check_je_source_id.py](scripts/check_je_source_id.py), [scripts/check_pos_lock_usage.py](scripts/check_pos_lock_usage.py), [scripts/check_get_acc_id_callsites.py](scripts/check_get_acc_id_callsites.py). Each exits 0 with a banner. Wire all five into the runner used by `scripts/full_code_scanner.py` and the existing CI command list.
- [x] T003 [P] Add new i18n keys placeholder section in [backend/locales/errors.en.json](backend/locales/errors.en.json) and [backend/locales/errors.ar.json](backend/locales/errors.ar.json) for: `sales.invoice.state_invalid_transition`, `sales.invoice.stale_state`, `sales.invoice.already_converted`, `sales.invoice.tax_resolution_failed`, `inventory.preflight_failed`, `cancel.cap_exceeded`, `pos.stock_lock_conflict`, `pos.stock_lock_timeout`, `pos.offline.duplicate`, `pos.offline.stale_batch`, `returns.already_posted`, `returns.shortage`, `returns.line_qty_exceeds_original`, `account_mapping.missing`, `account_mapping.classification_ambiguous`, `einvoicing.outbox.already_terminal`, `einvoicing.outbox.signing_unavailable`, `einvoicing.signer.failed`, `einvoicing.ubl.validation_failed`, `mfg.completion.qty_exceeds_remaining`, `mfg.completion.yield_tolerance_exceeded`, `mfg.qc.no_pending_completions`, `mfg.qc.invalid_disposition`, `mfg.missing_account_mapping`, `mfg.bom.cycle_detected`, `mfg.byproduct.fallback_to_qty`, `mfg.byproduct.cost_exceeds_total`, `inventory.negative_balance_forbidden`, `inventory.archival.batch_failed`, `crm.cashflow.window_too_long`, `endpoint_gone`.
- [x] T004 [P] Confirm dependency `signxml` (or in-house equivalent) is declared in [backend/requirements.txt](backend/requirements.txt) and pinned. If missing, add it. Document the choice in [specs/023-sales-inventory-trade-integrity/research.md](specs/023-sales-inventory-trade-integrity/research.md) (R3.8) without changing existing decisions.

**Checkpoint**: Scaffolding lands without behavior change; CI green; lint scripts present and registered.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Apply all 13 migrations, sync `tenant_schema.py` + `database.py`, seed settings keys, and stand up the new workers' skeletons. Until this phase is complete, no capability phase may begin.

**CRITICAL**: Every migration is paired with a `tenant_schema.py` + `database.py` update in the **same task** (Principle XXVIII). All numeric columns use `NUMERIC(18,4)` (or `(18,6)` where marked `[fine]` in [data-model.md](data-model.md)). No `DOUBLE PRECISION`.

### F.1 — Migrations

- [x] T005 Migration [backend/alembic/versions/023a_invoice_state_and_idempotency.py](backend/alembic/versions/023a_invoice_state_and_idempotency.py): add `invoices.state VARCHAR(32) NOT NULL DEFAULT 'draft'` (CHECK in `{draft,posted,submitted,cleared,reported,reversed,cancelled}`), `invoices.idempotency_key VARCHAR(64) NULL`, `invoices.posted_at TIMESTAMPTZ NULL`, `invoices.posted_by BIGINT NULL`, `invoices.state_reason TEXT NULL`; partial unique `(tenant_id, sales_order_id, idempotency_key) WHERE idempotency_key IS NOT NULL`. Backfill `state` from existing posted/cancelled flags. Reversible. Sync [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [x] T006 Migration [backend/alembic/versions/023b_sales_order_invoice_link.py](backend/alembic/versions/023b_sales_order_invoice_link.py): add `sales_orders.converted_to_invoice_id BIGINT NULL` FK → `invoices.id`, `sales_orders.responsible_user_id BIGINT NULL` FK → `users.id`; partial unique `(tenant_id, converted_to_invoice_id) WHERE converted_to_invoice_id IS NOT NULL`. Sync schema files.
- [x] T007 Migration [backend/alembic/versions/023c_returns_unified_table.py](backend/alembic/versions/023c_returns_unified_table.py): create `returns_unified` and `returns_unified_lines` per [data-model.md §returns_unified](data-model.md#returns_unified); migrate existing `sales_returns` and `pos_returns` rows into `returns_unified` with `source` set; replace `sales_returns` and `pos_returns` with updatable views over `returns_unified`. Partial unique `(tenant_id, original_invoice_id) WHERE state='draft'` and `(tenant_id, original_pos_sale_id) WHERE state='draft'`. Sync schema files.
- [x] T008 Migration [backend/alembic/versions/023d_acc_map_sales_consolidation.py](backend/alembic/versions/023d_acc_map_sales_consolidation.py): add `acc_map_sales.direction VARCHAR(16) NOT NULL DEFAULT 'forward'` (CHECK in `{forward,reversal}`); copy rows from `acc_map_sales_rev` with `direction='reversal'`; replace `acc_map_sales_rev` with a view filtering `direction='reversal'`. Sync schema files.
- [x] T009 [P] Migration [backend/alembic/versions/023e_zatca_outbox.py](backend/alembic/versions/023e_zatca_outbox.py): create `zatca_outbox` per [data-model.md §zatca_outbox](data-model.md#zatca_outbox); unique `(tenant_id, invoice_id)`; partial index `(tenant_id, state, next_attempt_at) WHERE state IN ('pending','failed')`. Sync schema files.
- [x] T010 [P] Migration [backend/alembic/versions/023f_opportunity_stage_history.py](backend/alembic/versions/023f_opportunity_stage_history.py): create `opportunity_stage_history` per [data-model.md §opportunity_stage_history](data-model.md#opportunity_stage_history); seed initial rows from current `opportunities.stage` so velocity/funnel have history. Sync schema files.
- [x] T011 [P] Migration [backend/alembic/versions/023g_pos_offline_batches.py](backend/alembic/versions/023g_pos_offline_batches.py): create `pos_offline_batches` per [data-model.md §pos_offline_batches](data-model.md#pos_offline_batches); unique `(tenant_id, device_id, client_uuid)`. Sync schema files.
- [x] T012 [P] Migration [backend/alembic/versions/023h_item_warehouse_settings.py](backend/alembic/versions/023h_item_warehouse_settings.py): create `item_warehouse_settings` (or extend if partial); PK `(tenant_id, item_id, warehouse_id)`; backfill from existing item-level reorder fields where present. Sync schema files.
- [x] T013 [P] Migration [backend/alembic/versions/023i_mrp_recommendations.py](backend/alembic/versions/023i_mrp_recommendations.py): create `mrp_recommendations` per [data-model.md §mrp_recommendations](data-model.md#mrp_recommendations); index `(tenant_id, state, run_id)`. Sync schema files.
- [x] T014 [P] Migration [backend/alembic/versions/023j_bom_snapshots_and_mo_extensions.py](backend/alembic/versions/023j_bom_snapshots_and_mo_extensions.py): create `bom_snapshots`; extend `manufacturing_orders` with `bom_snapshot_id BIGINT NULL` FK, `remaining_qty NUMERIC(18,4)`, `qc_required BOOLEAN DEFAULT FALSE`, `requires_approval BOOLEAN DEFAULT FALSE`, `approved_by BIGINT NULL` FK, `approved_at TIMESTAMPTZ NULL`; extend `manufacturing_orders.state` CHECK to include `pending_approval, qc_pending`; backfill `remaining_qty = original_qty - completed_qty`. Sync schema files.
- [x] T015 [P] Migration [backend/alembic/versions/023k_production_completions_and_scrap.py](backend/alembic/versions/023k_production_completions_and_scrap.py): create `production_completions` and `scrap_movements`; index `production_completions (tenant_id, mo_id, completed_at)` and `scrap_movements (tenant_id, item_id, occurred_at)`. Sync schema files.
- [x] T016 [P] Migration [backend/alembic/versions/023l_workstation_overhead.py](backend/alembic/versions/023l_workstation_overhead.py): add `workstations.overhead_rate NUMERIC(18,4) NULL`, `effective_from DATE NULL`, `effective_to DATE NULL`; add EXCLUSION constraint on `(workstation_id WITH =, daterange(effective_from, effective_to, '[]') WITH &&)` to forbid overlap. Sync schema files.
- [x] T017 [P] Migration [backend/alembic/versions/023m_inventory_transactions_archive.py](backend/alembic/versions/023m_inventory_transactions_archive.py): create `inventory_transactions_archive` mirroring `inventory_transactions` schema and primary indexes (`(tenant_id, item_id, warehouse_id, occurred_at)`, `(tenant_id, occurred_at)`). Sync schema files.

### F.2 — Settings keys

- [x] T018 Seed default values for the new keys in [backend/services/settings_service.py](backend/services/settings_service.py) bootstrap per [data-model.md §Settings keys](data-model.md#3-settings-keys-added-to-company_settings); idempotent on re-run; per-tenant rollout via existing tenant-bootstrap path. Verify with `SELECT key, value FROM company_settings WHERE key LIKE 'pos.%' OR key LIKE 'zatca.%' OR key LIKE 'mrp.%' OR key LIKE 'manufacturing.%' OR key LIKE 'inventory.%' OR key LIKE 'crm.%';`.

### F.3 — Worker skeletons

- [x] T019 [P] Skeleton [backend/services/einvoicing/outbox.py](backend/services/einvoicing/outbox.py) with stub `enqueue()` and worker loop that selects 0 rows; wire into [backend/worker.py](backend/worker.py) with startup banner `worker.zatca_outbox started (interval=5s, batch=25)`.
- [x] T020 [P] Skeleton [backend/services/pos/pos_offline_reconcile.py](backend/services/pos/pos_offline_reconcile.py) with worker loop that selects 0 rows; wire into [backend/worker.py](backend/worker.py) with banner `worker.pos_offline_reconciler started (interval=10s, batch=50)`.
- [x] T021 [P] Schedule [backend/services/inventory/auto_reorder.py](backend/services/inventory/auto_reorder.py) (no-op stub) every 60m; banner `worker.auto_reorder scheduled (every 60m)`.
- [x] T022 [P] Schedule [backend/services/inventory/archival.py](backend/services/inventory/archival.py) (no-op stub) daily 03:00 UTC; banner `worker.inventory_archiver scheduled (daily 03:00 UTC)`.
- [x] T023 [P] Schedule [backend/services/manufacturing/mrp.py](backend/services/manufacturing/mrp.py) (no-op stub) per `mfg.mrp_interval_minutes`; banner `worker.mrp scheduled (every Nm)`.

**Checkpoint — Foundation Ready**: All migrations applied; tenant_schema.py + database.py in sync; settings seeded; workers booting with banners. Capability phases can now run with the dependency rules stated below.

---

## Phase 3: R3.2 — Invoice State Machine (foundational for sales)

**Goal**: A single module is the only writer of `invoices.state`; legal transitions enforced; concurrency guarded by conditional UPDATE; side effects (GL post, ZATCA enqueue, audit event) attached.

**Independent Validation**: Lint T028 fails any other writer; smoke check in [quickstart.md §4 Order→Invoice](quickstart.md#order--invoice-idempotent) shows `invoices.state='posted'` after one call; concurrent retries hit `StaleInvoiceState`.

**Dependency**: Phase 2 (specifically T005 — `state`/`idempotency_key` columns must exist).

- [x] T024 [R3.2] Implement [backend/services/sales/invoice_state.py](backend/services/sales/invoice_state.py) per [contracts/invoice-state-machine.md](contracts/invoice-state-machine.md): `LEGAL_TRANSITIONS` dict, `transition(invoice, target_state, *, actor, reason=None)`, conditional UPDATE with `WHERE state = $expected`, `InvalidInvoiceTransition` and `StaleInvoiceState` exceptions, side-effect dispatch (GL post on `draft→posted`, GL reverse on any `→reversed/cancelled` from posted+, ZATCA outbox enqueue when ZATCA enabled), `invoice.state_changed` domain event, `audit_writer.log_activity('sales.invoice.state_changed', ...)`.
- [x] T025 [R3.2] Sweep direct `UPDATE invoices SET state` callsites: locate via `grep -rn "UPDATE invoices SET state\|invoices.state\s*=\s*" backend/`; replace each with `invoice_state.transition(...)`. Files likely: [backend/services/sales_service.py](backend/services/sales_service.py), [backend/services/pos_service.py](backend/services/pos_service.py), [backend/services/einvoicing/](backend/services/einvoicing/) modules, any returns code. Preserve existing audit lines that piggybacked on the update — the state machine emits its own.
- [x] T026 [R3.2] Map all current GL JE postings for sales invoices to use `JESource.SALES_INVOICE` (and `SALES_INVOICE_REVERSE`/`SALES_INVOICE_CANCEL` for reversal/cancel) with `source_id=invoice.id` (Principle: free-text `reference_number` is no longer linkage). Update [backend/services/gl_service.py](backend/services/gl_service.py) or callers as needed; do not change `gl_service` semantics.
- [x] T027 [R3.2] Add domain-event hook `invoice.state_changed` to the existing event bus (search for the event dispatcher used in feature 022); CRM forecast and ZATCA outbox subscribe.
- [x] T028 [P] [R3.2] CI lint [scripts/check_invoice_state_writers.py](scripts/check_invoice_state_writers.py): AST/regex scan that fails on any `UPDATE invoices SET state` outside `services/sales/invoice_state.py`; fails on direct assignment to `invoice.state` outside the same module's tests. Wire into CI runner.
- [x] T029 [P] [R3.2] CI lint [scripts/check_je_source_id.py](scripts/check_je_source_id.py): fails on `gl_service.reverse(...)` or `gl_service.post(...)` calls that pass `reference_number=` instead of `source=` and `source_id=`; documents allowlist for non-sales modules.

**Checkpoint**: Lint T028 enforced; T026 sweep completed; legal transitions exercised in smoke.

---

## Phase 4: R3.4 — Account-Mapping Resolver

**Goal**: One central resolver for sales/POS/manufacturing GL mappings; `get_acc_id(code)` removed from all callers; `acc_map_sales_rev` reads use `direction='reversal'`.

**Independent Validation**: Lint T032 reports zero offenders; smoke `POST /sales/invoices/.../cancel` resolves reversal accounts via consolidated table.

**Dependency**: Phase 2 (T008).

- [x] T030 [R3.4] Implement [backend/services/sales/account_mapping.py](backend/services/sales/account_mapping.py) per [contracts/account-mapping-resolver.md](contracts/account-mapping-resolver.md): `resolve(*, mapping_kind, account_code=None, classification=None, company_id)`. Delegate to 022's `services/account_classifier.py` for class lookups. Apply `manufacturing.missing_mapping_policy` and a parallel `sales.missing_mapping_policy` (default `block` for sales, `warn` for manufacturing).
- [x] T031 [R3.4] Sweep `get_acc_id(` and `acc_map_sales_rev` direct reads: replace with `account_mapping.resolve(...)`. Files via `grep -rn "get_acc_id\|acc_map_sales_rev" backend/`. Likely: [backend/services/sales_service.py](backend/services/sales_service.py), [backend/services/pos_service.py](backend/services/pos_service.py), [backend/services/manufacturing/](backend/services/manufacturing/), [backend/services/returns_service.py](backend/services/returns_service.py).
- [x] T032 [P] [R3.4] CI lint [scripts/check_get_acc_id_callsites.py](scripts/check_get_acc_id_callsites.py): fails on any `import` of `get_acc_id` outside `services/sales/account_mapping.py`. Wire into CI runner.

**Checkpoint**: Lint passes; cancellation/return smoke resolves through the new resolver.

---

## Phase 5: R3.1 — Order → Invoice

**Goal**: A single endpoint converts a confirmed `SalesOrder` into a posted `Invoice` exactly once with idempotency.

**Independent Validation**: Smoke check in [quickstart.md §4 Order→Invoice](quickstart.md#order--invoice-idempotent) — two retries with the same Idempotency-Key return identical invoice; `converted_to_invoice_id` set; `zatca_outbox` row exists when ZATCA enabled.

**Dependencies**: Phase 3 (T024 state machine), Phase 4 (T030 resolver), Phase 2 (T005, T006).

- [x] T033 [R3.1] Implement service [backend/services/sales/order_to_invoice.py](backend/services/sales/order_to_invoice.py) per [contracts/order-to-invoice.md](contracts/order-to-invoice.md): `SELECT FOR UPDATE` on order, idempotency lookup, line snapshot (qty, unit_price, tax_id, tax_rate at posting_date, discount), `invoices` insert in `draft`, call `invoice_state.transition('posted')`, set `converted_to_invoice_id`, audit-write.
- [x] T034 [R3.1] Schema [backend/schemas/sales.py](backend/schemas/sales.py): `OrderToInvoiceRequest`, `OrderToInvoiceResponse` (full invoice payload + `gl_je_id`, `zatca_outbox_id`).
- [x] T035 [R3.1] Router [backend/routers/sales/order_to_invoice.py](backend/routers/sales/order_to_invoice.py): `POST /sales/orders/{order_id}/invoice`, `Idempotency-Key` header required (≤64 chars), `require_sensitive_permission('sales.invoice.create')`, error envelope per [contracts/http-endpoints.md](contracts/http-endpoints.md).
- [x] T036 [R3.1] Register router in [backend/main.py](backend/main.py); update curated sensitive routes registry from feature 022 to include this path.
- [x] T037 [R3.1] Frontend [frontend/src/pages/sales/OrderToInvoiceAction.jsx](frontend/src/pages/sales/OrderToInvoiceAction.jsx): button on confirmed orders, generates client-side UUID for `Idempotency-Key`, displays invoice id + state, error inline. Reuse standard primitives.

**Checkpoint**: Idempotent POST returns identical responses across retries; concurrent calls produce one invoice; smoke passes.

---

## Phase 6: R3.3 — Sales/POS Cancellation + Returns Unified

**Goal**: Full-line inventory pre-flight; cancellation and return reversal via `gl_service.reverse(source, source_id)`; `sales_returns` + `pos_returns` consolidated under `returns_unified`.

**Independent Validation**: Smoke: cancellation with one short line returns `409` listing **all** short lines; `returns_unified` row visible through `sales_returns` view; reversal JE has correct `source`/`source_id`.

**Dependencies**: Phase 3 (state machine), Phase 4 (resolver), Phase 2 (T007).

### R3.3a — Cancellation hardening

- [x] T038 [R3.3] Implement [backend/services/sales/sales_cancellation.py](backend/services/sales/sales_cancellation.py) per [contracts/sales-cancellation.md](contracts/sales-cancellation.md): full-line `inventory_preflight(lines)` returning **all** shortages; `wac_per_warehouse.apply_inbound` per line at recorded WAC; call `invoice_state.transition('cancelled', reason=...)`; respect `inventory.cancel_restock_cap_pct`.
- [x] T039 [R3.3] Routers: [backend/routers/sales/cancellation.py](backend/routers/sales/cancellation.py) (`POST /sales/invoices/{id}/cancel`) and [backend/routers/pos/cancellation.py](backend/routers/pos/cancellation.py) (`POST /pos/sales/{id}/cancel`); `require_sensitive_permission`. Replace any existing partial-cancel logic.
- [x] T040 [P] [R3.3] Schema [backend/schemas/sales.py](backend/schemas/sales.py): `CancellationRequest` and `CancellationResponse` with `shortages: list[Shortage]` payload format from contract.

### R3.3b — Returns unified

- [x] T041 [R3.3] Implement [backend/services/returns_unified_service.py](backend/services/returns_unified_service.py) per [contracts/returns-unified.md](contracts/returns-unified.md): create draft, post (with full-line pre-flight when restock_warehouse_id set, `account_mapping.resolve('sales_return*')`, `gl_service.post(source='sales_return'|'pos_return', source_id=return_id)`), cancel.
- [x] T042 [R3.3] Router [backend/routers/returns_unified.py](backend/routers/returns_unified.py): all 4 endpoints from [contracts/http-endpoints.md](contracts/http-endpoints.md); sensitive on writes.
- [x] T043 [R3.3] Switch existing `sales_returns` and `pos_returns` writer call-sites to `returns_unified_service`. Locate via `grep -rn "INSERT INTO sales_returns\|INSERT INTO pos_returns\|sales_returns_service\|pos_returns_service" backend/`. Read paths keep using the compatibility views (no change needed).
- [x] T044 [P] [R3.3] Schema [backend/schemas/returns.py](backend/schemas/returns.py): `ReturnCreate`, `ReturnPost`, `ReturnView`.

**Checkpoint**: Both cancellation and return paths produce a single reversal JE per row with `(source, source_id)`; consolidated table visible; views still serve legacy readers.

---

## Phase 7: R3.5 — POS Stock Lock + Bulk Commit

**Goal**: Per-warehouse Redis lock with DB-advisory fallback wraps every POS commit/return; full-line stock pre-flight; bulk INSERT.

**Independent Validation**: Smoke: 5 concurrent POS commits to same warehouse — at most stock-available succeed, others 409; lint T048 passes.

**Dependencies**: Phase 2 (Redis available), Phase 6 (cancellation uses the same lock).

- [x] T045 [R3.5] Implement [backend/services/pos/stock_lock.py](backend/services/pos/stock_lock.py) per [contracts/pos-stock-lock.md](contracts/pos-stock-lock.md): context manager `pos_stock_lock(tenant_id, warehouse_id, *, ttl=None)`; Redis `SET NX PX`; Lua-based safe release; `pg_advisory_xact_lock(hash(tenant_id, warehouse_id))` fallback when Redis unavailable; one short retry; `PosLockTimeout` after 5s.
- [x] T046 [R3.5] Refactor [backend/services/pos/pos_commit.py](backend/services/pos/pos_commit.py) (extract from existing pos_service if monolithic): single bulk `SELECT` for stock check (returns ALL short lines), single bulk INSERT into `inventory_transactions`, GL via `gl_service`, lock-wrapped end-to-end.
- [x] T047 [R3.5] Sweep all POS write paths (`grep -rn "inventory_transactions" backend/services/pos`) to ensure each is inside the lock context manager.
- [x] T048 [P] [R3.5] CI lint [scripts/check_pos_lock_usage.py](scripts/check_pos_lock_usage.py): AST scan over `backend/services/pos/` — any function that writes to `inventory_transactions`, `pos_sales`, `pos_sale_lines`, or returns the canonical `commit_pos_sale` must contain a `pos_stock_lock(` call (or be a helper called only inside one). Wire into CI runner.

**Checkpoint**: Lint enforced; smoke contention test passes deterministically.

---

## Phase 8: R3.6 — POS Offline Reconcile

**Goal**: Idempotent ingest of offline batches keyed by `(device_id, client_uuid)`; reconciler replays through online commit; failures land in `manual_review` with structured reason; clients can poll outcomes.

**Independent Validation**: Smoke push two batches with same `client_uuid` → `queued=1, duplicates=1`; reconciler completes with `committed` and `pos_sale_id` set.

**Dependencies**: Phase 7 (stock lock + commit), Phase 2 (T011, T020).

- [x] T049 [R3.6] Replace stub T020 with full [backend/services/pos/pos_offline_reconcile.py](backend/services/pos/pos_offline_reconcile.py) per [contracts/pos-offline-reconcile.md](contracts/pos-offline-reconcile.md): worker loop with `FOR UPDATE SKIP LOCKED`, state transitions, structured `failure_reason_code` (`out_of_stock`, `closed_period`, `state_machine_violation`, `pricing_mismatch`, `stale_batch`).
- [x] T050 [R3.6] Router [backend/routers/pos/offline.py](backend/routers/pos/offline.py): `POST /pos/offline/batches` (device-scoped, idempotent ON CONFLICT DO NOTHING), `GET /pos/offline/batches?device_id=...`, `POST /pos/offline/batches/{id}/retry` (sensitive admin).
- [x] T051 [P] [R3.6] Schema [backend/schemas/pos_offline.py](backend/schemas/pos_offline.py): `OfflineBatchSubmit`, `OfflineBatchView` (includes `failure_reason_code`, `failure_detail`, `pos_sale_id`).
- [x] T052 [P] [R3.6] Mobile extension [mobile/src/pos/offline_queue.js](mobile/src/pos/offline_queue.js): generate `client_uuid` per batch (UUIDv4); persist queue locally; on reconnect push to `/pos/offline/batches`; poll `GET` on backoff; surface `manual_review` rows in a UI alert.
- [x] T053 [P] [R3.6] Frontend [frontend/src/pages/pos/ReconnectStatus.jsx](frontend/src/pages/pos/ReconnectStatus.jsx): cashier-facing list of batches with reasons; supports retry button gated on `pos.offline.admin`.

**Checkpoint**: Idempotency and replay round-trip verified.

---

## Phase 9: R3.7 — CRM (stage history, velocity, funnel, cashflow)

**Goal**: Replace heuristic CRM metrics with deterministic formulas backed by `opportunity_stage_history`; expose cash-flow forecast feed; paginate the activity feed; emit opportunity-assignment event.

**Independent Validation**: Fixtures-driven check: `velocity` and `funnel` outputs match expected values to within $10^{-4}$ given a fixed history.

**Dependencies**: Phase 2 (T010).

- [x] T054 [R3.7] Hook into opportunity stage updates: every `UPDATE opportunities SET stage` (or service equivalent) inserts a corresponding `opportunity_stage_history` row in the same transaction. Locate via `grep -rn "opportunities.stage\|update_opportunity_stage" backend/`.
- [x] T055 [R3.7] Implement [backend/services/crm/velocity.py](backend/services/crm/velocity.py) per [contracts/crm-velocity-funnel.md](contracts/crm-velocity-funnel.md): pure function over history; returns `confidence='insufficient_data'` when denominators=0.
- [x] T056 [R3.7] Implement [backend/services/crm/funnel.py](backend/services/crm/funnel.py) per same contract; pagination on output; bounded by `crm.funnel_window_days`.
- [x] T057 [R3.7] Implement [backend/services/crm/cashflow_feed.py](backend/services/crm/cashflow_feed.py) per [contracts/crm-cashflow-feed.md](contracts/crm-cashflow-feed.md): probability-weighted bucketed feed; bounded by `crm.cashflow_horizon_days`; FX via existing canonical FX service.
- [x] T058 [R3.7] Extend [backend/services/crm/activity_feed.py](backend/services/crm/activity_feed.py) (locate or create) to support pagination (`cursor` or `offset/limit`) and filters (`actor_id`, `entity_type`, `event_type`, `since`, `until`).
- [x] T059 [P] [R3.7] Routers: [backend/routers/crm/velocity.py](backend/routers/crm/velocity.py) (`GET /crm/velocity`), [backend/routers/crm/funnel.py](backend/routers/crm/funnel.py) (`GET /crm/funnel`), [backend/routers/crm/cashflow.py](backend/routers/crm/cashflow.py) (`GET /crm/cashflow-forecast`); standard `require_permission('crm.read')`.
- [x] T060 [P] [R3.7] Emit `opportunity.assigned` domain event whenever `responsible_user_id` changes on an opportunity; subscribers (notifications) are owned by R6 — this feature only emits.

**Checkpoint**: Three GET endpoints return deterministic numbers; activity feed paginates; assignment event fires.

---

## Phase 10: R3.8 — ZATCA Outbox + UBL/Signing (inline)

**Goal**: Decouple invoice posting from ZATCA round-trip via `zatca_outbox`; inline UBL build (standard + simplified) and inline signing using vault credentials; manual reprocess; bounded retries with backoff and dead-letter; remove external signer dependency.

**Independent Validation**: Smoke: outbox row created on invoice post; worker submits within seconds; reprocess endpoint resets failed→pending; no external signer URL in code.

**Dependencies**: Phase 3 (state machine enqueues), Phase 2 (T009, T019), feature 022's vault.

- [x] T061 [R3.8] Replace stub T019 with full [backend/services/einvoicing/outbox.py](backend/services/einvoicing/outbox.py) per [contracts/zatca-outbox.md](contracts/zatca-outbox.md): `enqueue(invoice, idempotency_key=invoice.id)` (ON CONFLICT DO NOTHING); worker `FOR UPDATE SKIP LOCKED`; state transitions per data-model diagram; exponential backoff with jitter.
- [x] T062 [R3.8] Implement [backend/services/einvoicing/ubl_builder.py](backend/services/einvoicing/ubl_builder.py) per [contracts/ubl-signing.md](contracts/ubl-signing.md): build UBL 2.1 for `standard` and `simplified` profiles; XSD-validate output; raise `UblValidationError` (sanitized).
- [x] T063 [R3.8] Implement [backend/services/einvoicing/ubl_signer.py](backend/services/einvoicing/ubl_signer.py): load `(cert_pem, private_key_pem)` from `credentials_vault.get(tenant_id, integration='zatca')`; XAdES-BES sign per ZATCA; embed prior-hash chain reference; raise `SignerCredentialsMissing`/`SignerCryptoError` (sanitized).
- [x] T064 [R3.8] Wire `outbox.submit()` to use the inline builder + signer + ZATCA HTTP client (existing or new minimal client); cache `signed_xml` on success.
- [x] T065 [R3.8] Remove the legacy external signer dependency: delete or deprecate the old client module; CI grep guard added in T072 below. Settings keys for the external signer URL/credentials are removed from defaults.
- [x] T066 [R3.8] Routers [backend/routers/einvoicing/outbox_admin.py](backend/routers/einvoicing/outbox_admin.py): `GET /einvoicing/outbox?state=...` and `POST /einvoicing/outbox/{id}/reprocess` per [contracts/http-endpoints.md](contracts/http-endpoints.md); both sensitive.
- [x] T067 [P] [R3.8] Frontend [frontend/src/pages/einvoicing/ZatcaOutboxMonitor.jsx](frontend/src/pages/einvoicing/ZatcaOutboxMonitor.jsx): list with state, attempts, last_error (already sanitized), reprocess button on `dead_letter` rows.
- [x] T068 [P] [R3.8] Schema [backend/schemas/einvoicing.py](backend/schemas/einvoicing.py): `OutboxRowView`, `ReprocessResponse`.

**Checkpoint**: Posting an invoice creates exactly one outbox row; worker progresses to `submitted`/`cleared`/`reported`; signing happens in-process; reprocess works.

---

## Phase 11: R4.1 + R4.2 — WAC per Warehouse + Decimal sweep

**Goal**: Single canonical `wac_per_warehouse` service used by all cost-affecting movements; `float` banned in inventory/manufacturing/costing arithmetic; column types `NUMERIC(18,4)`/`(18,6)` enforced.

**Independent Validation**: Lint T072 passes; sales-issue, purchase-receipt, transfer, manufacturing-consume, manufacturing-complete, return-restock all funnel through the new service.

**Dependencies**: Phase 2 done. Phases 5-10 of this feature do **not** block this phase but should land before to avoid double-sweep.

- [x] T069 [R4.1] Implement [backend/services/inventory/wac_per_warehouse.py](backend/services/inventory/wac_per_warehouse.py) per [contracts/wac-per-warehouse.md](contracts/wac-per-warehouse.md): `apply_inbound`, `apply_outbound`, `apply_transfer`, `read_wac` — all `Decimal` only; respect `inventory.allow_negative_balance` policy; raise `NegativeBalanceForbidden` on block.
- [x] T070 [R4.1] Sweep callers: `grep -rn "wac\|moving_average\|stock_layer" backend/services/`. Replace global-WAC code paths in [backend/services/costing_service.py](backend/services/costing_service.py), [backend/services/purchase_service.py](backend/services/purchase_service.py) (receipts), [backend/services/sales_service.py](backend/services/sales_service.py) (issues), [backend/services/pos_service.py](backend/services/pos_service.py) (commit/return), [backend/services/inventory/transfer_service.py](backend/services/inventory/transfer_service.py), and [backend/services/manufacturing/](backend/services/manufacturing/) (consume + complete) with the new service.
- [x] T071 [R4.2] Decimal sweep: ensure all monetary/quantity columns in inventory and manufacturing tables are `NUMERIC(18,4)` (or `(18,6)` per data-model). If migrations 023j/023k/023l/023m don't already cover existing columns, add a small migration `023n_decimal_sweep_existing.py` to `ALTER COLUMN ... TYPE NUMERIC(18,4)` for any `DOUBLE PRECISION` left in scope. Sync schema files.
- [x] T072 [P] [R4.2] CI lint [scripts/check_no_float_money.py](scripts/check_no_float_money.py): AST scan of `backend/services/inventory/`, `backend/services/manufacturing/`, `backend/services/costing_service.py`, plus all callers updated in T070; fails on `float(`, division producing float without `Decimal` cast, arithmetic with `float` literals on cost/qty paths. Allow `int` for indexing but flag float results. Also greps for the legacy external signer URL pattern (per T065).

**Checkpoint**: Lints pass; valuation reports compute identically per warehouse; no float in scope.

---

## Phase 12: R4.3a — Auto-Reorder

**Goal**: `(item, warehouse)` settings drive a paginated scheduler that writes recommendations and (optionally) creates draft POs grouped by supplier.

**Independent Validation**: Smoke: insert a setting with `reorder_point=100`, drop on-hand to 50, run scheduler — recommendation created with computed qty.

**Dependencies**: Phase 2 (T012, T013, T021).

- [x] T073 [R4.3] Replace stub T021 with full [backend/services/inventory/auto_reorder.py](backend/services/inventory/auto_reorder.py) per [contracts/auto-reorder.md](contracts/auto-reorder.md): per-tenant advisory lock, paginated scan (1000 rows), `recommended_qty = max(reorder_quantity, safety_stock + forecasted_demand_during_lead_time − available)`, optional draft-PO creation when `inventory.auto_reorder_enabled=true`.
- [x] T074 [R4.3] Use `account_mapping.resolve` for any AP/inventory account references on draft POs created here.
- [x] T075 [P] [R4.3] Audit events `inventory.reorder_run_completed`, `inventory.reorder_recommended`, `inventory.reorder_po_drafted` via `audit_writer.log_activity`.

**Checkpoint**: Below-reorder-point pairs always produce a recommendation per run; no double-PO on consecutive runs (recommendation state filter).

---

## Phase 13: R4.3b — MRP Net Requirements + Multi-Level BOM

**Goal**: Multi-level BOM net-requirements with cycle detection; consolidated recommendations per `(item, warehouse)`; optional draft POs.

**Independent Validation**: BOM cycle returns `BomCycleError` with the path; 10k-item run completes in ≤5min; recommendations consolidated.

**Dependencies**: Phase 12 (shares table), Phase 2 (T013, T023).

- [x] T076 [R4.3] Replace stub T023 with full [backend/services/manufacturing/mrp.py](backend/services/manufacturing/mrp.py) per [contracts/mrp-net-requirements.md](contracts/mrp-net-requirements.md): Tarjan SCC cycle detect, top-down explosion with yield/scrap %, aggregate per `(item, warehouse)`, persist with shared `run_id`.
- [x] T077 [R4.3] Router [backend/routers/manufacturing/mrp.py](backend/routers/manufacturing/mrp.py): `POST /manufacturing/mrp/run` (sensitive); [backend/routers/manufacturing/mrp_recommendations.py](backend/routers/manufacturing/mrp_recommendations.py): `GET /manufacturing/mrp/recommendations` and `POST /manufacturing/mrp/recommendations/{id}/accept` (sensitive on accept).
- [x] T078 [P] [R4.3] Frontend [frontend/src/pages/manufacturing/MrpRecommendations.jsx](frontend/src/pages/manufacturing/MrpRecommendations.jsx): listing with `run_id` filter, accept-to-PO action.
- [x] T079 [P] [R4.3] Schema [backend/schemas/mrp.py](backend/schemas/mrp.py): `MrpRunRequest`, `MrpRunResponse`, `RecommendationView`, `AcceptResponse`, `BomCycleErrorBody { cycle_path: list[item_id] }`.

**Checkpoint**: Cycle detection deterministic; performance budget met; accept-to-PO records `po_id` on the recommendation.

---

## Phase 14: R4.4 — Production Completion (Partial, Actual Cost) + BOM Snapshot + Scrap + By-product

**Goal**: BOM snapshot at MO start; partial completions write actual-cost JEs; scrap and by-product as first-class movements; large-MO approval; deterministic `existing_qty`; missing-mapping policy.

**Independent Validation**: Smoke: partial completion 50/100 → MO `remaining_qty=50`, JE balanced at actual cost, `production_completions` row inserted; large MO requires approval.

**Dependencies**: Phase 11 (WAC), Phase 4 (mapping), Phase 2 (T014, T015).

- [x] T080 [R4.4] BOM snapshot at MO release: extend [backend/services/manufacturing/manufacturing_orders.py](backend/services/manufacturing/manufacturing_orders.py) (or canonical writer) — on `release` transition, capture BOM into `bom_snapshots`; set `mo.bom_snapshot_id`. Subsequent BOM edits do not affect the snapshot.
- [x] T081 [R4.4] Implement [backend/services/manufacturing/production_complete.py](backend/services/manufacturing/production_complete.py) per [contracts/production-completion.md](contracts/production-completion.md): row-lock on MO, qty/yield validation, consume materials via `wac_per_warehouse.apply_outbound`, compute actual labor (attendance link when enabled, fallback to planned ratio) and overhead (per-workstation rate, fallback to global), allocate by-products via `byproduct_allocator`, write scrap rows, FG inbound at allocated cost, `gl_service.post(source='mfg_completion', source_id=mo.id)`, insert `production_completions`, decrement `remaining_qty`, set `qc_pending` or `completed`.
- [x] T082 [R4.4] Implement [backend/services/manufacturing/byproduct_allocator.py](backend/services/manufacturing/byproduct_allocator.py) per [contracts/byproduct-allocation.md](contracts/byproduct-allocation.md): three methods + sales-value→quantity fallback with audit warning.
- [x] T083 [R4.4] Implement [backend/services/manufacturing/scrap.py](backend/services/manufacturing/scrap.py): writer for `scrap_movements` + JE post. Used by completion and by QC fail (Phase 15).
- [x] T084 [R4.4] Large-MO approval gate: in MO planning service, when `planned_cost ≥ manufacturing.large_mo_threshold`, set `state='pending_approval'` and `requires_approval=true`. Router [backend/routers/manufacturing/production_approval.py](backend/routers/manufacturing/production_approval.py): `POST /manufacturing/orders/{id}/approve` (sensitive); transitions `pending_approval → released`, sets `approved_by`/`approved_at`.
- [x] T085 [R4.4] Deterministic `existing_qty`: replace any heuristic source with `read_inventory_transactions(item, warehouse, until=cutoff)` aggregation (Phase 16 helper). Locate via `grep -rn "existing_qty" backend/services/manufacturing`.
- [x] T086 [R4.4] Missing-mapping policy: `account_mapping.resolve` already supports `block`/`warn`. Wire `manufacturing.missing_mapping_policy` setting to its calls in completion/scrap paths.
- [x] T087 [R4.4] Optional routing operations: add `routing_operations.optional BOOLEAN DEFAULT FALSE` (small migration `023o_routing_optional.py` or fold into 023j depending on order) and skip `optional=true` operations in the completion progress without raising. Sync schema files.
- [x] T088 [R4.4] Shop-floor↔attendance link: when `mfg.shopfloor_attendance_link_enabled=true`, completion's labor minutes pulled from attendance records (existing module). Otherwise fallback documented above.
- [x] T089 [P] [R4.4] Router [backend/routers/manufacturing/production.py](backend/routers/manufacturing/production.py): `POST /manufacturing/orders/{id}/complete` (sensitive); error envelope per contract.
- [x] T090 [P] [R4.4] Schema [backend/schemas/manufacturing.py](backend/schemas/manufacturing.py): `CompletionRequest`, `CompletionResponse`, `ApprovalResponse`, `ScrapLine`, `ByproductLine`.
- [x] T091 [P] [R4.4] Frontend [frontend/src/pages/manufacturing/ProductionPartialCompletion.jsx](frontend/src/pages/manufacturing/ProductionPartialCompletion.jsx): qty input ≤ remaining, scrap and by-product line builders, submit shows `wip_to_fg_je_id` and updated `remaining_qty`.

**Checkpoint**: Partial completion math matches contract; large-MO approval blocks completion until approved; scrap and by-product visible in inventory valuation.

---

## Phase 15: R4.5 — QC Gate

**Goal**: When `qc_required=true`, completed qty stays in virtual `qc_pending` until pass; failure routes to scrap or rework with documented JE.

**Independent Validation**: Smoke: complete 100 with `qc_required` → state `qc_pending`; pass → state `completed`, FG inventory increments; fail-scrap → `scrap_movements` row.

**Dependencies**: Phase 14.

- [x] T092 [R4.5] Implement [backend/services/manufacturing/qc_gate.py](backend/services/manufacturing/qc_gate.py) per [contracts/qc-gate.md](contracts/qc-gate.md): `pass(completion_ids)`, `fail(completion_ids, disposition, reason)`; integrate with [backend/services/manufacturing/scrap.py](backend/services/manufacturing/scrap.py) for scrap disposition.
- [x] T093 [R4.5] Router [backend/routers/manufacturing/qc.py](backend/routers/manufacturing/qc.py): `POST /manufacturing/orders/{id}/qc/pass`, `POST /manufacturing/orders/{id}/qc/fail`; both sensitive.
- [x] T094 [P] [R4.5] Schema [backend/schemas/manufacturing.py](backend/schemas/manufacturing.py): extend with `QcPassRequest`, `QcFailRequest` (`disposition: 'scrap'|'rework'`).

**Checkpoint**: QC gate enforced; rework returns units to WIP and resumes; scrap has its JE.

---

## Phase 16: R4.6 — Workstation Overhead

**Goal**: Per-workstation overhead rate with effective-dating and global fallback.

**Independent Validation**: Two completions with different `as_of` use different rates from the workstation's effective ranges.

**Dependencies**: Phase 2 (T016).

- [x] T095 [R4.6] Implement [backend/services/manufacturing/workstation_overhead.py](backend/services/manufacturing/workstation_overhead.py) per [contracts/workstation-overhead.md](contracts/workstation-overhead.md): `get_rate(workstation_id, *, as_of)`; consult workstation row, fallback to `manufacturing.global_overhead_rate`.
- [x] T096 [R4.6] Wire into [backend/services/manufacturing/production_complete.py](backend/services/manufacturing/production_complete.py) overhead computation.
- [x] T097 [P] [R4.6] Audit `mfg.workstation.overhead_updated` on edits (existing or new admin path).

**Checkpoint**: Overlap exclusion constraint surfaces `ConflictingOverheadRanges`.

---

## Phase 17: R4.7 — Inventory Archival + Read Helper

**Goal**: Daily archiver moves rows older than `inventory.retention_days` to `inventory_transactions_archive`; balance reads UNION ALL across both.

**Independent Validation**: Force `retention_days=1`, run archiver, confirm rows moved; valuation report still correct.

**Dependencies**: Phase 2 (T017, T022).

- [x] T098 [R4.7] Replace stub T022 with full [backend/services/inventory/archival.py](backend/services/inventory/archival.py) per [contracts/inventory-archival.md](contracts/inventory-archival.md): per-tenant advisory lock, batched `WITH moved AS (DELETE ... RETURNING *) INSERT INTO archive`, retry with backoff, audit summary.
- [x] T099 [R4.7] Implement read helper `read_inventory_transactions(...)` in [backend/services/inventory/transactions_reader.py](backend/services/inventory/transactions_reader.py) (or extend existing reader): UNION ALL across live and archive with index hints. Sweep historical-balance callers via `grep -rn "FROM inventory_transactions" backend/services` to use this helper when their range may span the cutoff.
- [x] T100 [P] [R4.7] Router [backend/routers/inventory/archival_admin.py](backend/routers/inventory/archival_admin.py): `GET /inventory/archival/status`, `POST /inventory/archival/run` (sensitive).

**Checkpoint**: Hot table size bounded; valuation/historical reports unaffected.

---

## Phase 18: R4.8 — Inventory `low_stock` Webhook

**Goal**: Day-bucket debounced emission via Redis SET-NX; payload delivered through unified dispatcher (R6).

**Independent Validation**: Two crossings same day → one webhook delivered.

**Dependencies**: Phase 2 (Redis).

- [x] T101 [R4.8] Implement [backend/services/inventory/low_stock_webhook.py](backend/services/inventory/low_stock_webhook.py) per [contracts/inventory-low-stock-webhook.md](contracts/inventory-low-stock-webhook.md): hook into the inventory-write path (after every decrement of `(item, warehouse)`); compute `available`; if below `reorder_point`, `SET NX EX <inventory.low_stock_debounce_hours × 3600>` and call `webhooks.dispatch('inventory.low_stock', payload)`.
- [x] T102 [R4.8] Wire the inventory-write path: locate via `grep -rn "INSERT INTO inventory_transactions" backend/services`. Each decrementing path calls the new helper after the DB write but before the surrounding `transactional()` returns. Idempotent under concurrent calls (Redis NX).

**Checkpoint**: Smoke webhook debounce passes.

---

## Phase 19: Cleanup + Cross-Cutting (`/transfer` 410, sensitive endpoint registration, audit verbs)

**Purpose**: Final consolidation: deprecate `/transfer`, ensure every new sensitive endpoint is in the discovery registry from feature 022, ensure every new audited write uses 022's writer, locales finalized.

- [x] T103 Replace [backend/routers/inventory/transfers.py](backend/routers/inventory/transfers.py) (canonical) routes are present; add a stub router [backend/routers/inventory/transfer_deprecated.py](backend/routers/inventory/transfer_deprecated.py) responding `410 Gone` with `{"code":"endpoint_gone","moved_to":"/inventory/transfers"}` for any method on `/inventory/transfer` (singular). Register in [backend/main.py](backend/main.py).
- [x] T104 Update curated sensitive routes registry from feature 022 ([backend/services/permissions/sensitive_routes.yaml](backend/services/permissions/sensitive_routes.yaml)) to include all sensitive endpoints from [contracts/http-endpoints.md](contracts/http-endpoints.md). Run startup discovery in dev to confirm `permissions.discover: OK (N sensitive endpoints wrapped)`.
- [x] T105 Sweep new audit verbs: ensure every service in this feature uses `audit_writer.log_activity` (no direct `INSERT INTO audit_logs`). Grep `INSERT INTO audit_logs|insert.*audit_logs` against new files. Lint from feature 022 (`scripts/audit_writer_lint.py`) must pass.
- [x] T106 Finalize i18n keys T003 placeholders with English + Arabic strings. Re-run i18n-coverage check if present.
- [x] T107 Update OpenAPI coverage check ([scripts/check_openapi_coverage.py](scripts/check_openapi_coverage.py)) so the new endpoints in [contracts/http-endpoints.md](contracts/http-endpoints.md) are present in the served OpenAPI spec.

---

## Phase 20: Polish & Documentation

- [x] T108 [P] Update [backend/README.md](backend/README.md) with a section: "Feature 023 surfaces" listing the new endpoints, workers, settings keys, and lint scripts.
- [x] T109 [P] Update [docs/RUNBOOK.md](docs/RUNBOOK.md): operational notes for the new workers (zatca_outbox, pos_offline_reconciler, auto_reorder, mrp, inventory_archiver) — health metrics, expected lag, dead-letter triage.
- [x] T110 [P] Update [docs/PROJECT_DESIGN_REQUIREMENTS.md](docs/PROJECT_DESIGN_REQUIREMENTS.md): add summary entries for the new modules.
- [x] T111 Run smoke checks from [quickstart.md §4](quickstart.md#4-smoke-checks); record outputs/screenshots in PR.
- [x] T112 Confirm all five lints (T002 list) report zero offenders on `main`.

---

## Dependencies (Capability Order)

```
Phase 1 (Setup)
  ↓
Phase 2 (Foundational migrations + worker stubs + settings)
  ↓
Phase 3  R3.2 Invoice State Machine ──┐
                                       ├─→ Phase 5  R3.1 Order→Invoice
Phase 4  R3.4 Account Mapping Resolver ┤
                                       ├─→ Phase 6  R3.3 Cancellation + Returns Unified
                                       │
                                       ├─→ Phase 7  R3.5 POS Lock + Bulk Commit
                                       │      ↓
                                       │   Phase 8  R3.6 POS Offline Reconcile
                                       │
                                       ├─→ Phase 9  R3.7 CRM (independent)
                                       │
                                       └─→ Phase 10 R3.8 ZATCA Outbox + UBL/Signing

Phase 11  R4.1 + R4.2 WAC per warehouse + Decimal sweep
  ↓
Phase 12  R4.3a Auto-Reorder
  ↓
Phase 13  R4.3b MRP
  ↓
Phase 14  R4.4 Production Completion + BOM snapshot + Scrap + By-product
  ↓
Phase 15  R4.5 QC Gate
  ↓
Phase 16  R4.6 Workstation Overhead (parallel with 14/15 OK)

Phase 17  R4.7 Inventory Archival       (parallel with R3 phases after Phase 2)
Phase 18  R4.8 Low-Stock Webhook         (parallel with R3 phases after Phase 2)

Phase 19  Cleanup + Cross-Cutting        (after all capability phases)
Phase 20  Polish + Documentation         (after Phase 19)
```

**Critical path**: Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6 → Phase 7 → Phase 8 → Phase 19 → Phase 20.
**R4 critical path**: Phase 2 → Phase 11 → Phase 14 → Phase 15 → Phase 19.

## Parallel Execution Opportunities

- Phase 2: T009–T017 migrations are all `[P]` once T005–T008 run in order; T019–T023 worker stubs are all `[P]`.
- Phase 3: T028 + T029 lints `[P]`; T024 must precede the sweep T025.
- Phase 5: T034, T036, T037 `[P]` after T033.
- Phase 6: T040, T044 `[P]`; routers T039 depend on T038; returns service T041 independent of cancellation.
- Phase 7: T048 `[P]`; T046 depends on T045.
- Phase 8: T051, T052, T053 `[P]` after T049/T050.
- Phase 9: All five sub-tasks (T055, T056, T057, T058, T060) can run after T054 in parallel.
- Phase 10: T067, T068 `[P]` after T061–T066.
- Phase 11: T072 `[P]`; T070 depends on T069.
- Phase 13: T078, T079 `[P]` after T076–T077.
- Phase 14: T089, T090, T091 `[P]` after T081.
- Phase 15: T094 `[P]`.
- Phase 17: T100 `[P]`.
- Phase 20: T108, T109, T110 `[P]`.

## Suggested MVP Scope

The minimum-viable subset that closes the highest-risk integrity gaps:

1. Phase 1 + Phase 2 (everything).
2. Phase 3 (Invoice State Machine).
3. Phase 4 (Account Mapping Resolver).
4. Phase 5 (Order → Invoice).
5. Phase 6 (Cancellation + Returns Unified).
6. Phase 7 (POS Stock Lock).
7. Phase 11 (WAC per warehouse + Decimal sweep).
8. Phase 19 (Cleanup) + Phase 20 (Polish).

This MVP delivers the entire **trade integrity** core (consistent invoice lifecycle, safe cancellation, no stock over-decrement, deterministic costing). ZATCA outbox (Phase 10), POS offline (Phase 8), CRM analytics (Phase 9), MRP (Phase 13), production-completion overhaul (Phase 14), QC (Phase 15), workstation overhead (Phase 16), archival (Phase 17), low-stock webhook (Phase 18) ship in subsequent increments.

## Format Validation

All tasks above strictly follow `- [ ] [TaskID] [P?] [Area?] Description with file path`. Setup, Foundational, Cleanup, and Polish tasks omit `[Area]`. Capability tasks carry `[R3.x]`/`[R4.x]` labels matching the audit plan.
