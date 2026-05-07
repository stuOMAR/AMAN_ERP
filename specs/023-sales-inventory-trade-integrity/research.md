# Phase 0 Research: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing Remediation

**Feature**: 023-sales-inventory-trade-integrity
**Date**: 2026-05-02

The spec contained no `[NEEDS CLARIFICATION]` markers — informed defaults were chosen during specification. This document records the decisions, the alternatives that were considered, and the rationale, so that downstream tasks have a single point of reference.

All decisions assume feature 022's primitives exist and MUST NOT be re-implemented.

---

## R3.1 — Order → Invoice endpoint and idempotency

**Decision**: Single endpoint `POST /sales/orders/{order_id}/invoice` with header `Idempotency-Key`. The service:

1. Loads the `SalesOrder` with `SELECT ... FOR UPDATE` and verifies it is in `confirmed` (not already converted, not cancelled).
2. Looks up `(idempotency_key, sales_order_id)` in `invoices`; if found, returns it (idempotent short-circuit).
3. Snapshots lines (qty, unit price, tax id, tax rate at posting date, discount amount), creates an `Invoice` in `draft`.
4. Calls the **invoice state machine** to transition `draft → posted`. The transition function posts the GL via `gl_service` and on success enqueues the ZATCA outbox row.
5. Sets `SalesOrder.converted_to_invoice_id = invoice.id` (unique-when-set constraint guarantees a second concurrent caller hits a conflict and falls back to read).
6. Returns the invoice payload.

**Rationale**: One endpoint, one transactional boundary, one state-machine call site. The unique constraint on `(idempotency_key, sales_order_id)` plus `converted_to_invoice_id UNIQUE WHERE NOT NULL` guarantees exactly-one even under N concurrent calls.

**Alternatives considered**:
- *Two-step API (create draft, then post)* — rejected: doubles the surface area without solving the idempotency problem; encourages partial state in production.
- *Background-job conversion* — rejected: caller cannot synchronously assert the invoice is posted before clearing the order.

---

## R3.2 — Invoice state machine

**Decision**: A pure module `services/sales/invoice_state.py` exposes one function `transition(invoice, target_state, *, actor, reason)` that:

- consults a static `LEGAL_TRANSITIONS` map: `draft→posted, posted→submitted, submitted→cleared, submitted→reported, posted→reversed, posted→cancelled, draft→cancelled, cleared→reversed, reported→reversed`;
- raises `InvalidInvoiceTransition` on any other request;
- writes the `state` column with a `CASE WHEN current_state = expected_current_state` UPDATE so race-losing callers raise `StaleInvoiceState`;
- emits a domain event (`invoice.state_changed`) and an audit row via 022's writer;
- is the **only** code path that writes `invoices.state` (a CI lint enforces this).

**Rationale**: Existing code mutates state from many places. A single function plus a static lint produces the strongest contract for the smallest implementation cost.

**Alternatives considered**:
- *Database CHECK + state-transition trigger* — rejected: less debuggable, harder to attach side effects (audit, events) cleanly.
- *Saga / workflow engine* — rejected: scope creep.

---

## R3.3 — Sales/POS cancel + return reversal

**Decision**:
- Cancellation runs a single `inventory_preflight(invoice)` that returns the **complete** list of short lines (no first-line short-circuit). If any short line exists, the cancellation aborts before any mutation.
- Cancellation JE is requested from `gl_service.reverse(source_je_id, source='sales_invoice_cancel', source_id=invoice.id)`. Free-text `reference_number` is no longer the linkage column.
- The `returns_unified` table becomes the only writer target. `sales_returns` and `pos_returns` become backward-compatible views over `returns_unified` (filtered by the `source` column). All readers stay on the views during the migration window; writers are switched atomically per service in 023c migration.

**Rationale**: Each piece is small, additive, and removes a specific class of defect (partial reversal, free-text linkage drift, divergent returns paths).

---

## R3.4 — Account-mapping resolver

**Decision**: A new `services/sales/account_mapping.py` exposes a single resolver:

```
resolve(*, mapping_kind, account_code=None, classification=None, company_id) -> account_id
```

It first looks up the configured mapping in the consolidated `acc_map_sales` table (with the direction column distinguishing reversal mappings, replacing `acc_map_sales_rev`). If the mapping points to a class (e.g., "default revenue"), it asks 022's `account_classifier` for an account matching the classification. The free `get_acc_id(code)` helper is removed; a CI lint forbids importing it.

**Rationale**: One resolver collapses three current shortcuts (free `get_acc_id`, `acc_map_sales_rev` table, ad-hoc class-based fallbacks) into a single contract that consumes 022's classifier.

---

## R3.5 — POS multi-session stock lock

**Decision**: Per-warehouse Redis lock keyed `pos:lock:<tenant_id>:<warehouse_id>` with TTL = 5s (configurable). Acquisition is non-blocking with one short retry; on failure → HTTP 409 `pos.stock_lock_conflict`. Inside the lock the commit:

1. Re-reads stock for **all** lines (single bulk query).
2. If any line short, releases lock and returns 409 with the list of short lines.
3. Performs bulk INSERT into `inventory_transactions`.
4. Posts GL via `gl_service`.
5. Releases lock.

If Redis is unavailable, the lock helper falls back to a per-warehouse `pg_advisory_xact_lock(hash(tenant_id, warehouse_id))`. The fallback is slower but correct.

**Rationale**: Redis lock is fast for the hot path; advisory lock is a safe fallback that requires no schema change. TTL bounds the worst case if a process crashes mid-commit.

**Alternatives considered**:
- *Row-level `SELECT FOR UPDATE` on every line* — rejected for the hot POS path because it serializes commits even when warehouses differ; the per-warehouse lock is finer than per-tenant and coarser than per-line.
- *Optimistic concurrency on a `stock_version` column* — rejected: would require schema change on the hottest table and provides weaker guarantees against multi-line interleaving.

---

## R3.6 — POS offline reconcile

**Decision**: Mobile/desktop POS clients keep an offline queue keyed by client-generated UUIDs. On reconnect, the client pushes batches to `POST /pos/offline/batches`. The server inserts into `pos_offline_batches` (state `queued`) idempotently on `(device_id, client_uuid)` (unique index). A worker picks `queued` rows with `FOR UPDATE SKIP LOCKED`, re-runs the same online commit path under the per-warehouse lock, and updates state to `committed` or `manual_review` (with a structured reason: `out_of_stock`, `closed_period`, `state_machine_violation`, etc.). The client polls `GET /pos/offline/batches?device_id=...` to learn outcomes.

**Rationale**: Idempotency on `(device_id, client_uuid)` plus the same online commit code path keeps offline behavior consistent with online behavior.

---

## R3.7 — CRM velocity, funnel conversion, cash-flow feed

**Decision**:
- A new table `opportunity_stage_history` records every stage change. Existing `updated_at − created_at` formulas are replaced.
- **Sales velocity** (per pipeline, rolling window): `velocity = (won_value × win_rate) / avg_cycle_days` where `win_rate` and `avg_cycle_days` are computed from stage history over the configured window. Deterministic against fixed fixtures.
- **Funnel conversion** (per stage, rolling window): `conversion(stage_i → stage_j) = count(transitions stage_i→stage_j) / count(opportunities that entered stage_i)` over the same window.
- **Cash-flow forecast feed**: each open opportunity contributes `expected_value × probability` to the bucket keyed by `expected_close_date`. The forecast service exposes `forecast_by_date(window_start, window_end, currency)`.

**Rationale**: Pure functions of stage history; trivially unit-testable against fixtures; no module coupling beyond reading two tables.

---

## R3.8 — ZATCA outbox + inline UBL/signing

**Decision**:
- `zatca_outbox(invoice_id, state, attempts, next_attempt_at, last_error, idempotency_key, cleared_reference, reported_reference, ...)` with index on `(state, next_attempt_at)`.
- Worker uses `FOR UPDATE SKIP LOCKED` to claim rows; states progress `pending → submitting → submitted → cleared|reported` for success, or `→ failed → dead_letter` after max attempts.
- Backoff: exponential with jitter, base 30s, cap 30 minutes, max attempts 8 (configurable).
- UBL builder lives in `services/einvoicing/ubl_builder.py`, parameterized for **standard** vs. **simplified** profiles. The builder uses values from the invoice + tenant settings; no per-invoice toggling outside the configured profile.
- Signing happens inline via `services/einvoicing/ubl_signer.py`, which loads the cert + private key from 022's `integration_credentials` vault (integration = `zatca`). The external signer dependency is removed.
- Manual reprocess endpoint: `POST /einvoicing/outbox/{id}/reprocess` (sensitive, audited).

**Rationale**: Outbox pattern proven in 022 for audit; inline signing eliminates the external service round-trip and the credential leakage path; vault-backed credentials inherit 022's rotation/audit/soft-delete.

**Alternatives considered**:
- *Keep the external signer* — rejected: increases attack surface, complicates offline behavior, contradicts spec requirement #88/#382.
- *Synchronous ZATCA call inside the invoice posting transaction* — rejected: ZATCA latency would couple posting time to a third-party service; outbox decouples them.

**Signing library**: `signxml>=3.2.0` (with `lxml>=5.0.0` for UBL XML building). Chosen over raw `xmlsec1` bindings because signxml provides a pure-Python XAdES-BES implementation with better error messages and no C library version coupling. Both are pinned in `backend/requirements.txt`.

---

## R4.1 — WAC per warehouse

**Decision**: Canonical service `services/inventory/wac_per_warehouse.py` with one entry per direction:

- `apply_inbound(item_id, warehouse_id, qty, unit_cost, *, source)` — moving WAC update at warehouse W.
- `apply_outbound(item_id, warehouse_id, qty, *, source)` — consumes at W's current WAC; returns the cost used.
- `apply_transfer(item_id, src_warehouse_id, dst_warehouse_id, qty, *, source)` — outbound at src WAC, inbound at dst with the layer's cost.

All callers (purchase receipt, sales issue, POS commit, manufacturing consume, manufacturing complete, transfer, return restock) MUST go through this service. Existing global-WAC callsites are swept in 023.

**Rationale**: Per-warehouse WAC is the canonical accounting answer when warehouses have meaningfully different replenishment costs (a current source of report drift).

**Alternatives considered**: FIFO/LIFO per warehouse — rejected as scope; the constitution and current code are WAC-based; FIFO is a separate, heavier track.

---

## R4.2 — Decimal sweep

**Decision**: Add a CI lint (`scripts/check_no_float_money.py`) that AST-walks `backend/services/inventory/`, `backend/services/manufacturing/`, `backend/services/costing_service.py`, and forbids `float()` casts, division returning `float`, and arithmetic on `float` literals in code paths typed for cost/qty. Migrations include `ALTER COLUMN ... TYPE NUMERIC(18,4)` (or `(18,6)` for fine quantities) wherever a `DOUBLE PRECISION` column was found.

**Rationale**: A static check is cheap, deterministic, and satisfies the constitution's Financial Precision principle without runtime overhead.

---

## R4.3 — Auto-reorder + MRP

**Decision**:
- `item_warehouse_settings(item_id, warehouse_id, reorder_point, reorder_quantity, safety_stock, lead_time_days, preferred_supplier_id)` — one row per `(item, warehouse)`.
- Auto-reorder scheduler scans below-reorder pairs in chunks (paginated), computes recommended qty = `max(reorder_quantity, safety_stock + forecasted_demand_during_lead_time − on_hand − on_order)`, groups by preferred supplier, writes `mrp_recommendations` rows. Under policy `auto_create=true`, it additionally creates a draft PO per supplier.
- MRP performs multi-level BOM net-requirements: starting from external demand (sales orders + forecast), it computes net per item, explodes via BOM with yield + scrap %, and rolls up. Cycle detection uses Tarjan SCC; on a cycle it raises `BomCycleError(path=[...])`.

**Rationale**: Splits "below reorder point" (operational, fast scan) from "MRP run" (strategic, heavier). Both share the recommendation table.

---

## R4.4 — Production completion overhaul

**Decision**:
- At MO start, snapshot the BOM into `bom_snapshots` (FK from MO). Subsequent BOM edits do not affect the snapshot.
- Each completion (full or partial) writes a `production_completions` row with `qty`, `actual_material_cost`, `actual_labor_cost`, `actual_overhead_cost`, `byproduct_allocation_method`, and the `wip_to_fg_je_id` returned by `gl_service`.
- Materials are consumed proportionally to the completed qty against the snapshot.
- Labor cost = `Σ (operator_minutes × rate)` from the shop-floor↔attendance link (when enabled). Overhead cost = `Σ (workstation_minutes × workstation_overhead_rate)` falling back to the global rate.
- By-product allocation: configurable per item (`by_sales_value | by_quantity | fixed`); fallback to `by_quantity` with a warning when `by_sales_value` inputs are missing.
- QC gate: when `qc_required=true`, completed qty lands in a virtual `qc_pending` location; pass moves to FG; fail routes to scrap or rework with a documented JE.
- Yield validation: `yield_quantity ≤ planned_qty × (1 + tolerance)` with tolerance from `manufacturing.yield_tolerance` (default 5%).
- Missing-mapping policy: `block | warn` from `manufacturing.missing_mapping_policy` (default `warn`).
- Optional operations in routing: a `routing_operations.optional` flag allows skipping without failing the MO.
- `existing_qty` deterministic source: replace any heuristic derivation with `inventory_transactions` aggregation per `(item, warehouse)` at the cut-off timestamp.

**Rationale**: Each item solves a single defect; the snapshot table isolates configuration drift; the policies are explicit and configurable.

---

## R4.5 — Scrap as a first-class movement

**Decision**: New table `scrap_movements(item_id, warehouse_id, qty, reason, je_id, mo_id, occurred_at)`. Scrap posts a JE through `gl_service` (DR scrap-loss / CR inventory) at the warehouse's WAC. Inventory valuation reports include scrap as a recognized loss line.

**Rationale**: Aligns with the "single source of truth" principle: scrap had been a soft annotation on inventory transactions; promoting it makes reports and audits straightforward.

---

## R4.6 — Inventory archival/retention

**Decision**: Configurable retention horizon (`inventory.retention_days`, default 365) and a scheduled archiver that moves `inventory_transactions` rows older than the horizon to `inventory_transactions_archive` (same schema). Balance reads that need history older than the cut-off use a UNION ALL helper `read_inventory_transactions(...)`. Indices on archive mirror live for spanning queries.

**Rationale**: Keeps the hot table small without breaking historical balance computations.

---

## R4.7 — Inventory `low_stock` webhook

**Decision**: Dispatcher hook fires `inventory.low_stock` once per `(item_id, warehouse_id, day)`. Idempotency uses Redis SET with key `lowstock:<tenant>:<item>:<warehouse>:<yyyymmdd>` and 36-hour TTL. The event is delivered through the unified webhook dispatcher (R6 owns the dispatcher; this feature emits).

**Rationale**: Day-bucket debounce is the simplest correct policy for low-stock alerts; the Redis key collapses duplicates regardless of which worker observed the threshold cross.

---

## R4.8 — `/transfer` deprecation + transfer canonicalization

**Decision**: Keep `/transfers` as the canonical resource. `/transfer` (singular) responds with HTTP 410 Gone and a body `{ "code": "endpoint_gone", "moved_to": "/transfers" }`. Removed entirely after a deprecation window of 60 days (cleanup feature, not in this scope).

---

## Open questions / deferrals

- The commission **calculation** engine (#154 architectural part) remains deferred. This feature only writes `responsible_user_id` on order/invoice; no rule evaluation is included.
- Compound expense-approval rule engine (#312) — out of scope (deferred to its own track).
- `/treasury` ↔ `/cash_movements` ↔ `/journal_entries` contract reshape (#177) — out of scope; this feature does not change those contracts.
- IP geolocation provider for impossible-travel — owned by a future feature; 022 ships only the data seam.

---

## Decision summary

Every decision above resolves a specific spec requirement, follows the constitution, reuses 022's primitives, and minimizes surface area. No decision introduces a parallel store, a new credential path, or an alternative GL writer. Phase 1 artifacts are produced from these decisions.
