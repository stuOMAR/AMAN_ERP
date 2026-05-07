# Feature Specification: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing Remediation (R3 + R4)

**Feature Branch**: `023-sales-inventory-trade-integrity`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "do R3 — Sales, POS, CRM, ZATCA and R4 — Inventory, Costing, Manufacturing on one speckit; the coder is cheaper than you, so spec everything well"

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

Two adjacent operational tracks in AMAN ERP — the **trade lane** (R3: Sales, POS, CRM, ZATCA) and the **physical/cost lane** (R4: Inventory, Costing, Manufacturing) — still have several open or partial items after batch B41. They are coupled at multiple points (sales reservation ↔ stock; invoice posting ↔ inventory cost; production completion ↔ WIP/COGS; ZATCA outbox ↔ invoice lifecycle), so shipping them as one coordinated change set avoids contract drift between modules.

The outcome must:

- Close the **order-to-invoice** lifecycle end-to-end with an explicit invoice state machine, GL/ZATCA propagation, and a back-link from sales orders to issued invoices.
- Make **POS** safe under multi-session and offline conditions (stock locks, complete inventory checks, offline guard).
- Make **ZATCA** offline-resilient with a durable outbox, retry worker, inline UBL XML signing, and clearance/reporting hand-off.
- Make **CRM ↔ sales velocity ↔ commissions ↔ cash-flow forecast** coherent rather than ad-hoc estimates.
- Establish **Weighted Average Cost (WAC) per warehouse** as the canonical inventory costing unit, with Decimal-clean math at all module boundaries.
- Fix sales/purchase **return reversal** flows (inventory check, GL reference unification, table consolidation).
- Deliver **MRP** with safety stock + lead time, multi-level BOM net-requirements, and PO generation from recommendations.
- Deliver **production completion** with partial completion, by-product cost allocation, scrap/QC gates, real WIP revaluation at finish, and clear missing-mapping diagnostics.
- Resolve duplicate / deprecated transfer endpoints and inventory archival/retention.

This feature consumes contracts shipped by feature 022 (sensitive-permission gate, account classification table, JE source casing, fiscal-period policy, audit outbox, secret vault). It MUST NOT re-implement those contracts; it MUST consume them.

### In Scope

**R3 — Sales, POS, CRM, ZATCA**

- **Order → Invoice** endpoint that copies order lines, applies pricing/tax/discount snapshots, posts GL via existing service, triggers ZATCA submission, and writes a back-link `SalesOrder.converted_to_invoice_id` (#149, #284).
- **Invoice lifecycle state machine** (`draft → posted → submitted → cleared/reported → reversed/cancelled`) used by sales, returns, ZATCA outbox, and cancellation flows. Illegal transitions raise a domain error (#392).
- **Cancel / reversal hardening**:
  - Pre-flight inventory check covers **all** lines (not first-line short-circuit) before reversing stock movements (#293).
  - Cancellation JE references unified to `(source, source_id)` instead of free-text `reference_number` (#294).
  - Scattered `get_acc_id(code)` callers replaced by one centralized account-mapping resolver consuming feature 022's account classification (#391).
- **Sales returns table consolidation**: physically unify `sales_returns` and `pos_returns` (currently behind a compatibility view from `returns_unified`); rewrite reads/writes to the consolidated table; keep a backward-compatible view only for downstream readers (#297, #476).
- **Account-mapping table consolidation**: finish unifying `acc_map_sales` and `acc_map_sales_rev` into one table (or one view + writer) and migrate callers (#298).
- **POS multi-session stock safety**: per-warehouse short-lived distributed stock lock (Redis-backed) when committing a POS sale or a POS return; block conflicting concurrent commits with a deterministic 409 response (#393).
- **POS offline / local stock guard**: when POS runs in offline mode, validate against the last known per-warehouse snapshot and queue commits to a server-side reconciliation worker that re-checks availability and either commits or routes to manual resolution (#181, #181b).
- **POS bulk INSERT sweep**: any remaining row-by-row INSERTs in POS commit / inventory movement paths converted to bulk operations (#181c, #272k).
- **CRM**:
  - Notify sales rep when an opportunity is assigned to them (via the unified notification queue from R6; this feature only emits the event) (#152).
  - Real sales velocity formula (replace `updated_at - created_at`) using stage-transition history (#285).
  - Standard funnel-stage conversion-rate formula (#286).
  - Pagination + filters for CRM activity feeds (#287).
  - Sales forecast feeds cash-flow forecast via expected close date and probability (#289).
- **ZATCA / E-invoicing**:
  - `zatca_outbox` table + worker with retry, exponential backoff, dead-letter, and idempotency key per invoice (#86).
  - Inline UBL XML builder finalised to ZATCA acceptance level for both standard and simplified invoices (#419l).
  - Inline XML signing inside the einvoicing module that replaces the external signer dependency, using credentials from the secret vault shipped in feature 022 (#88, #382).
- **Commissions hook**: when an opportunity converts to an order/invoice, record the responsible sales rep on the order/invoice for downstream commission rules. The commission engine itself is out of scope; only the link is in scope (#154).

**R4 — Inventory, Costing, Manufacturing**

- **WAC per warehouse** as the canonical costing unit across inventory transactions, transfers, sales-issue, purchase-receipt, manufacturing consumption, and manufacturing completion. Tighten any remaining global-WAC callsites to per-warehouse (#452).
- **Decimal sweep** at all module boundaries (transfers, shipments, schemas, Pydantic serializers, manufacturing math): all monetary and quantity math uses `Decimal` with explicit quantization; no `float` arithmetic on cost or quantity (#498).
- **Auto-reorder end-to-end** (#251, #493):
  - Per-item, per-warehouse reorder point + reorder quantity + supplier preference + lead-time fields.
  - Scheduler scans below-reorder items and emits PO recommendations.
  - Recommendations can be auto-converted to draft POs subject to policy.
- **Bulk `FOR UPDATE`** in purchase return: replace the per-line N-queries pattern with a single `SELECT ... FOR UPDATE` over the affected rows (#272h).
- **Negative-balance warehouse handling in WAC** (#272r): policy-driven (block / warn / allow with audit). Default = warn + audit; configurable per company.
- **Inventory webhook `inventory.low_stock`** wired into the unified webhook dispatcher with idempotency (#397).
- **Cancel-restock max bounds** to prevent restock greater than original issue (#398).
- **410 Gone** on the deprecated transfer endpoint(s); single canonical `/transfers` route; remove duplicate `/transfer` (#333, #399).
- **Inventory transactions archival/retention** policy + scheduled archiver, with reads transparently spanning live + archive when needed (#419o).
- **MRP** (#272n, #272o, #207, #272p, #203, #448, #419v):
  - Safety stock + lead time used in net requirements.
  - Multi-level BOM net-requirements planning (recursive explosion respecting yield and scrap %).
  - PO generation from MRP recommendations (draft POs, grouped by supplier).
- **Production completion** (#200, #449, #446):
  - WIP revaluation at completion based on **actual** material + labor + overhead consumption, not standard.
  - Partial production completion: a single MO can be completed in multiple batches, each posting its own JE and stock movement.
  - Validation rule for `yield_quantity` at completion (cannot exceed planned + tolerance; tolerance configurable).
- **By-product cost allocation** at completion using a configurable allocation method (by relative sales value, by physical quantity, or fixed cost) (#450).
- **Scrap / waste tracking** as a first-class movement type with quantity, reason, JE impact, and reporting (#204).
- **QC gate policy** at production completion: optional QC step that, if enabled per item or per workflow, holds the completed quantity in a `qc_pending` location until passed (#208).
- **Operations** (#272l, #272m, #272q):
  - Warn (or block, by policy) when labor/overhead account mappings are missing instead of silently posting to a default.
  - Support optional operations in routing (an operation can be flagged `optional` and skipped without failing the MO).
  - Replace the fragile `existing_qty` derivation with a deterministic source from inventory transactions.
- **Confirm/approval workflow for large MOs** (#201, #202): MOs above a configurable cost or quantity threshold enter `pending_approval`.
- **Per-workstation overhead rate** (#203 — overhead axis): allow workstations to carry their own overhead rate that overrides the global rate.
- **Shop-floor ↔ attendance link** (#314): operator clock-in/out on a workstation contributes to actual labor cost on the MO.

### Out of Scope

- Service contracts / FSM pricing / preventive-maintenance scheduler (R6 track).
- DMS quotas, anti-malware, MIME validation (R6 track).
- Notification queue, retry/dedup, email templates (R6 track) — this feature only **emits** events.
- Reports MVs, partitioning, BRIN indexes, dashboard widgets (R7 track) — beyond the small touches needed for low-stock and inventory webhooks.
- Frontend `useApi` migration, CSS splitting, format/debounce sweeps (R8 track) — frontend changes are limited to the new screens this feature requires (Order→Invoice action, ZATCA outbox monitor, MRP recommendations, production partial-completion form).
- New rule-engine for sales discount/approval policies — keep this feature additive; reuse existing approval primitives only.
- Replacing existing pricing engines (price lists, promotions). This feature consumes them; it does not redesign them.
- Commission calculation engine itself (only the responsible-rep link is in scope).
- Settings JSONB typed-model and tax-group junction (#178/#179) — explicitly deferred.

### Functional Flow Summary

- **Flow-001 (Order-to-Invoice)**: A confirmed `SalesOrder` is converted via a single endpoint. The service snapshots lines (qty, unit price, tax, discount), creates an `Invoice` in `draft`, posts GL through the existing service, transitions to `posted`, queues a ZATCA outbox row, sets `SalesOrder.converted_to_invoice_id`, and returns the new invoice. Re-invoking the endpoint on an already-converted order returns the existing invoice (idempotent).
- **Flow-002 (Invoice State Machine)**: Every transition (`draft → posted`, `posted → submitted`, `submitted → cleared|reported`, any → `reversed|cancelled`) goes through one `transition(invoice, target_state, actor, reason)` function that checks legality, writes audit, emits domain events, and is the only writer of `invoice.state`.
- **Flow-003 (Cancel / Reverse Sale)**: Cancellation runs (a) the full inventory pre-flight (all lines), (b) GL reversal with `(source='sales_invoice_cancel', source_id=invoice.id)`, (c) returns-unified write, (d) ZATCA reverse-outbox if applicable, all inside one `transactional()`.
- **Flow-004 (POS Sale Commit)**: POS commit acquires a per-warehouse Redis lock, validates stock for **every** line, performs bulk inventory movement INSERT, posts GL, releases lock. Conflicting concurrent commit returns 409 `pos.stock_lock_conflict`.
- **Flow-005 (POS Offline Reconcile)**: Offline POS commits are queued client-side with a client-generated UUID. On reconnect they are pushed to the reconcile worker, which re-validates stock against current server state and either commits or marks the queued record `manual_review`.
- **Flow-006 (ZATCA Outbox)**: Posting an invoice writes a row to `zatca_outbox` with state `pending`. The worker picks it up, builds UBL XML inline, signs inline using vault credentials, submits to ZATCA, and updates state (`submitted/cleared/reported/failed`). Failed rows retry with exponential backoff up to a max; after max, they go to `dead_letter` and raise an alert.
- **Flow-007 (Sales Velocity & Conversion)**: Sales velocity is computed from stage-transition history (`opportunity_stage_history`); funnel conversion is computed per stage on a rolling window. Both have unit tests against fixed fixtures so the formula is deterministic.
- **Flow-008 (Cash-Flow Forecast Feed)**: Each open opportunity contributes `expected_value × probability` to the forecast bucket whose key is its `expected_close_date`.
- **Flow-009 (WAC per Warehouse Update)**: Inbound stock at warehouse W with cost C and quantity Q updates `(qty_w, cost_w)` using moving WAC scoped to W. Outbound at W consumes at the per-W WAC. Transfers between warehouses move at sending WAC; receiving WAC re-averages with the inbound layer.
- **Flow-010 (MRP Run)**: Scheduler (or manual trigger) computes net requirements per item per warehouse: `net = max(0, demand + safety_stock − on_hand − on_order)`, then explodes BOMs multi-level, respects lead time (place-by date), and produces grouped PO recommendations.
- **Flow-011 (Production Completion — Partial)**: A user completes a partial quantity of an MO. The system consumes proportional materials, posts WIP→FG JE at actual cost for the completed quantity, allocates by-product cost using the configured method, and leaves the MO `in_progress` with reduced remaining qty. A final completion closes the MO.
- **Flow-012 (Production Completion — QC Gate)**: If QC is enabled, the completed quantity moves to a `qc_pending` virtual location. A QC pass moves it to FG; a QC fail routes it to scrap or rework with a documented JE.
- **Flow-013 (Auto-Reorder)**: Scheduler scans items below `reorder_point` per warehouse, generates PO recommendations grouped by preferred supplier, and (under policy) auto-creates draft POs for review.

### Acceptance Criteria

1. **Given** a confirmed sales order with N lines, **When** the Order→Invoice endpoint is called, **Then** an `Invoice` is created with N lines whose unit prices, taxes and discounts match the order snapshot, the invoice is in `posted` state with a balanced JE, a `zatca_outbox` row exists in `pending`, and `SalesOrder.converted_to_invoice_id` equals the new invoice id.
2. **Given** a sales order already converted, **When** the Order→Invoice endpoint is called again with the same order id and the same idempotency key, **Then** the existing invoice id is returned without creating a second invoice or a second JE.
3. **Given** an invoice in `cleared` state, **When** any caller attempts a `draft` transition, **Then** the state machine raises `InvalidInvoiceTransition` and no DB row is mutated.
4. **Given** a sales invoice cancellation, **When** the inventory pre-flight detects insufficient stock on **any** line, **Then** the entire cancellation is aborted with a structured error listing every short line, no stock movement is reversed, and no JE is written.
5. **Given** a cancellation that proceeds, **When** the reversal JE is written, **Then** its `(source, source_id)` is `('sales_invoice_cancel', invoice.id)` and there is no free-text `reference_number` in the JE header used as the linkage key.
6. **Given** a POS sale commit on warehouse W, **When** a second concurrent commit on the same warehouse contends for stock that is now insufficient, **Then** exactly one commit succeeds and the other returns HTTP 409 with code `pos.stock_lock_conflict`; no negative stock row is created.
7. **Given** a POS offline batch with K commits, **When** the device reconnects, **Then** every commit is processed exactly once (idempotent on its client UUID) and either materialised as a server-side sale or routed to `manual_review` with a structured reason.
8. **Given** an invoice transitions to `posted`, **When** the ZATCA worker picks the outbox row, **Then** it builds and signs UBL XML inline using vault credentials, submits to ZATCA, and the outbox row reflects the terminal status with the cleared/reported reference returned by ZATCA. After max retries on a permanent error, the row is `dead_letter` and an alert is emitted.
9. **Given** an opportunity with a stage history and a known close date, **When** sales velocity and funnel conversion are computed, **Then** results are deterministic against fixed fixtures (a unit test asserts exact numbers; no `updated_at − created_at` heuristic is used).
10. **Given** a stock receipt at warehouse W, **When** the WAC update runs, **Then** only `(qty_w, cost_w)` change; sibling warehouses' WAC values are unchanged; an automated test seeds two warehouses with different costs and asserts isolation.
11. **Given** a transfer from W1 to W2, **When** stock arrives at W2, **Then** W1 issues at W1's WAC, W2 receives at the inbound layer's cost, and the moving average at W2 reflects the new mix; both legs are written in one `transactional()`.
12. **Given** an item below reorder point at warehouse W, **When** MRP runs, **Then** a recommendation is produced with the correct net requirement, place-by date, and preferred supplier, and (if policy = auto) a draft PO appears with one line per item grouped by supplier.
13. **Given** an MO with a multi-level BOM, **When** MRP explodes net requirements, **Then** sub-assemblies' net demand is reduced by their on-hand and on-order quantities at each level (no double counting).
14. **Given** an MO in `in_progress`, **When** a partial completion of qty Q is posted, **Then** materials are consumed proportionally, the WIP→FG JE for that batch is at actual cost, by-product cost is allocated per the configured method, the MO remains `in_progress` with `remaining_qty -= Q`, and a final completion closes it with no residual WIP variance beyond the configured tolerance.
15. **Given** QC is enabled for an item, **When** completion runs, **Then** the completed qty lands in `qc_pending` and only a QC pass releases it to FG; a QC fail routes to scrap or rework with a documented JE.
16. **Given** an MO whose labor or overhead account mapping is missing, **When** completion runs under policy `block`, **Then** completion is rejected with a structured error naming the missing mapping; under policy `warn`, completion proceeds and an alert + audit row are written.
17. **Given** a deprecated transfer endpoint is called, **When** any client invokes it, **Then** the response is HTTP 410 Gone with a body pointing to the canonical `/transfers` route.
18. **Given** a purchase return with M lines, **When** stock is locked for reversal, **Then** exactly one `SELECT ... FOR UPDATE` is issued over the affected rows (verified by query log) instead of M separate locks.
19. **Given** an inventory transaction older than the configured retention horizon, **When** the archiver runs, **Then** the row moves to the archive partition/table; balance computation that needs to span the cut-off transparently reads both live and archive sources and produces the same answer as before archival.
20. **Given** any monetary or quantity computation in the modules in scope, **When** code is statically scanned, **Then** there is no `float` arithmetic on cost or quantity in production paths; values flow as `Decimal` with explicit quantization at boundaries.
21. **Given** an inventory event drops an item below the configured low-stock threshold, **When** the dispatcher runs, **Then** `inventory.low_stock` fires exactly once per (item, warehouse) per debounce window, with idempotency key `(item_id, warehouse_id, day)`.
22. **Given** the same opportunity is converted to an order, **When** the order is later converted to an invoice, **Then** the responsible sales rep id is recorded on both the order and the invoice for downstream commission processing.

### Edge Cases

- Order→Invoice called twice in parallel for the same order id → exactly one invoice; the other call observes the conflict and returns the same invoice id (idempotency key + unique constraint).
- ZATCA returns a transient error → outbox retries with backoff; permanent rejection → `dead_letter` and alert; manual reprocess endpoint provided for ops.
- Network split during a POS commit after stock lock acquired → lock TTL expires, no orphaned reservation; commit either fully completes or fully fails.
- Offline POS device clock skew → server uses server timestamp for `posted_at` and keeps client time as `client_posted_at` for traceability.
- Sales return on an invoice that is `reversed/cancelled` → rejected by the state machine.
- Partial completion of an MO whose BOM was edited mid-flight → the MO snapshots its BOM at start; subsequent BOM edits do not retroactively change consumption ratios for the open MO.
- Negative-balance warehouse encountered during WAC update → policy applies (block / warn+audit / allow); default `warn+audit` recovers gracefully.
- By-product allocation when the chosen method is "by sales value" but no sales price is configured → fall back to "by quantity" and emit a warning.
- MRP exploding a recursive BOM (cycle) → cycle detection raises a deterministic error naming the cycle path; no infinite expansion.
- A QC fail on a partial completion → scrap or rework JE applies only to the failing quantity, not to already-passed completions.
- Auto-reorder generating a PO whose preferred supplier is inactive → recommendation is produced but PO auto-creation is skipped; the recommendation is flagged for manual supplier choice.
- Returns-unified migration: in-flight returns at deploy time → readers fall back to the compatibility view until the migration window closes; writers are switched atomically per service.

## Requirements *(mandatory)*

### Functional Requirements

**R3 — Sales / POS / CRM / ZATCA**

- **FR-001**: System MUST expose a single Order→Invoice endpoint that snapshots order lines and creates a posted invoice with a balanced JE, propagates ZATCA, and persists `SalesOrder.converted_to_invoice_id`.
- **FR-002**: System MUST treat the Order→Invoice endpoint as idempotent on a client-supplied key plus order id; concurrent or repeat calls MUST NOT create duplicate invoices.
- **FR-003**: System MUST implement an invoice state machine as the **only** writer of `invoice.state`, with states `draft, posted, submitted, cleared, reported, reversed, cancelled` and explicitly enumerated legal transitions.
- **FR-004**: System MUST run a complete (all-line) inventory pre-flight before reversing any sales/purchase document and abort the whole reversal on any insufficiency.
- **FR-005**: System MUST link reversal/cancellation JEs to their source via `(source, source_id)` and MUST NOT rely on free-text `reference_number` for downstream lookups.
- **FR-006**: System MUST consolidate `sales_returns` and `pos_returns` into one physical table; old names remain only as backward-compatible views; all writers go to the consolidated table.
- **FR-007**: System MUST consolidate `acc_map_sales` and `acc_map_sales_rev` (single table or single writer + view) and migrate every caller.
- **FR-008**: System MUST replace scattered `get_acc_id(code)` calls with one centralized account-mapping resolver that consumes feature 022's account classification.
- **FR-009**: System MUST acquire a per-warehouse short-TTL distributed lock around POS commit and POS return, and return HTTP 409 `pos.stock_lock_conflict` on contention with insufficient stock.
- **FR-010**: System MUST validate stock availability for **every** POS line (not first-line short-circuit) before committing, both online and offline.
- **FR-011**: System MUST accept offline POS batches identified by client-generated UUIDs, process each commit exactly once, and route unresolvable commits to `manual_review` with a structured reason.
- **FR-012**: System MUST convert any remaining row-by-row INSERT in POS commit and inventory movement paths to bulk INSERT.
- **FR-013**: System MUST emit a sales-rep assignment event when an opportunity is assigned (consumed by the notification queue from R6).
- **FR-014**: System MUST compute sales velocity from `opportunity_stage_history` (not `updated_at − created_at`) and provide a deterministic, unit-tested formula.
- **FR-015**: System MUST compute funnel-stage conversion rate using a documented formula with a defined rolling window.
- **FR-016**: System MUST paginate and filter CRM activity feeds.
- **FR-017**: System MUST feed sales forecast into cash-flow forecast as `expected_value × probability` bucketed by `expected_close_date`.
- **FR-018**: System MUST persist a `zatca_outbox` row when an invoice transitions to `posted`, and a worker MUST process it with retry, exponential backoff, idempotency, and dead-lettering.
- **FR-019**: System MUST build UBL XML inline (no external service round-trip) for both standard and simplified ZATCA invoices, at the level required for ZATCA acceptance.
- **FR-020**: System MUST sign UBL XML inline using credentials from feature 022's secret vault, replacing any external signer dependency.
- **FR-021**: System MUST record the responsible sales rep on the order and invoice when an opportunity converts, to support downstream commission processing.

**R4 — Inventory / Costing / Manufacturing**

- **FR-050**: System MUST treat WAC as per-warehouse for all inbound, outbound, transfer, manufacturing-consume, and manufacturing-complete paths.
- **FR-051**: System MUST use `Decimal` (with explicit quantization) for all monetary and quantity arithmetic in inventory, costing and manufacturing modules; `float` arithmetic on cost/qty MUST be absent in production paths and MUST be guarded by a static check.
- **FR-052**: System MUST support per-item, per-warehouse `reorder_point`, `reorder_quantity`, `preferred_supplier_id`, and `lead_time_days`.
- **FR-053**: System MUST run a scheduler that detects below-reorder items and produces PO recommendations grouped by preferred supplier, with a policy toggle to auto-create draft POs.
- **FR-054**: System MUST acquire a single bulk `SELECT ... FOR UPDATE` over all affected rows in purchase return reversal.
- **FR-055**: System MUST handle negative-warehouse balances during WAC by a configurable policy (`block | warn | allow`), default `warn`, with audit on every occurrence.
- **FR-056**: System MUST emit `inventory.low_stock` once per `(item_id, warehouse_id, debounce_window)`.
- **FR-057**: System MUST cap cancel-restock at the original issued quantity and reject excess.
- **FR-058**: System MUST return HTTP 410 Gone on deprecated transfer endpoint(s) and expose a single canonical `/transfers` route.
- **FR-059**: System MUST archive `inventory_transactions` older than a configurable retention horizon and ensure balance reads spanning the cut-off remain correct.
- **FR-060**: MRP MUST compute `net = max(0, demand + safety_stock − on_hand − on_order)` per item per warehouse and explode multi-level BOMs without double-counting sub-assemblies' on-hand/on-order.
- **FR-061**: MRP MUST detect BOM cycles deterministically and raise a structured error naming the cycle path.
- **FR-062**: MRP MUST be able to convert recommendations into draft POs grouped by supplier under policy.
- **FR-063**: System MUST snapshot an MO's BOM at start; subsequent BOM edits MUST NOT retroactively change consumption for that MO.
- **FR-064**: System MUST support partial production completion: each batch consumes proportional materials, posts its own JE at actual cost, and reduces remaining qty on the MO.
- **FR-065**: System MUST validate `yield_quantity` at completion against `planned_qty × (1 ± tolerance)` with tolerance configurable per item or per workflow.
- **FR-066**: System MUST allocate by-product cost at completion using a configurable method (`by_sales_value | by_quantity | fixed`), with a documented fallback when the chosen method's inputs are missing.
- **FR-067**: System MUST track scrap/waste as a first-class movement type with quantity, reason, JE impact and reporting.
- **FR-068**: System MUST support an optional QC gate that holds completed qty in `qc_pending` until passed, with documented routing on fail (scrap or rework).
- **FR-069**: System MUST raise a structured error or warning (per policy) when labor/overhead account mappings are missing at completion, instead of silently posting to a default.
- **FR-070**: Routing MUST support optional operations that may be skipped without failing the MO.
- **FR-071**: System MUST replace the fragile `existing_qty` derivation with a deterministic source from `inventory_transactions`.
- **FR-072**: System MUST route MOs above a configurable cost or quantity threshold through a `pending_approval` workflow before they may start.
- **FR-073**: Workstations MUST be able to carry their own overhead rate that overrides the global rate.
- **FR-074**: Operator clock-in/out on a workstation MUST contribute to the MO's actual labor cost when the shop-floor↔attendance link is enabled.

**Cross-cutting**

- **FR-090**: All new audit-relevant writes (state transitions, cancellations, completions, MRP runs, ZATCA outbox transitions) MUST go through the audit-outbox pattern shipped in feature 022.
- **FR-091**: All new sensitive endpoints (Order→Invoice, ZATCA outbox monitor, MRP recommendations, production approval, account-mapping admin) MUST be gated by `require_sensitive_permission` from feature 022.
- **FR-092**: All new credentials (ZATCA cert, signing keys) MUST be stored in feature 022's secret vault; no new credential store may be introduced.
- **FR-093**: All new posted JEs MUST use the normalized `JESource` enum and respect the fiscal-period draft policy from feature 022.

### Key Entities

- **`SalesOrder`**: existing; add `converted_to_invoice_id` (FK, nullable, unique-when-set), `responsible_user_id` carried from the originating opportunity.
- **`Invoice`**: existing; ensure `state` is the single column written by the state machine; add `(idempotency_key, sales_order_id)` uniqueness for Order→Invoice idempotency.
- **`zatca_outbox`**: new. Critical fields: `id`, `tenant_id`, `invoice_id`, `state` (`pending|submitting|submitted|cleared|reported|failed|dead_letter`), `attempts`, `next_attempt_at`, `last_error`, `idempotency_key`, `cleared_reference`, `reported_reference`, timestamps. Indexes on `(state, next_attempt_at)`.
- **`returns_unified`** (renamed/promoted from compatibility view to physical table): consolidated rows from `sales_returns` + `pos_returns`. Critical fields: `id`, `tenant_id`, `source` (`sales|pos`), `original_invoice_id`, `lines`, `gl_reference`, timestamps. Old table names become backward-compatible views.
- **`opportunity_stage_history`**: new (or formalized). Critical fields: `opportunity_id`, `from_stage`, `to_stage`, `changed_at`, `changed_by`. Drives sales velocity and funnel conversion.
- **`item_warehouse_settings`**: existing or new; critical fields per `(item_id, warehouse_id)`: `reorder_point`, `reorder_quantity`, `preferred_supplier_id`, `lead_time_days`, `safety_stock`.
- **`mrp_recommendations`**: new. Critical fields: `id`, `tenant_id`, `item_id`, `warehouse_id`, `net_quantity`, `place_by_date`, `preferred_supplier_id`, `state` (`open|converted|dismissed`), `generated_at`.
- **`manufacturing_orders`**: existing; add `bom_snapshot_id` (FK to a snapshot table), `remaining_qty`, `state` extended to include `pending_approval` and `qc_pending`, `qc_required` flag.
- **`bom_snapshots`**: new. Captures the BOM as it stood when the MO started.
- **`production_completions`**: new (or formalized). One row per partial completion with `qty`, `wip_to_fg_je_id`, `byproduct_allocation_method`, `actual_material_cost`, `actual_labor_cost`, `actual_overhead_cost`, `qc_state`.
- **`workstation_overhead_rates`**: new (or column on `workstations`). `workstation_id`, `rate`, `effective_from`, `effective_to`.
- **`scrap_movements`**: first-class movement-type record. `item_id`, `warehouse_id`, `qty`, `reason`, `je_id`, `mo_id`, timestamps.
- **`pos_offline_batches`**: new. `id`, `device_id`, `client_uuid`, `payload`, `state` (`queued|reconciling|committed|manual_review|failed`), `server_committed_at`, `client_posted_at`.
- **Account-mapping consolidation**: `acc_map_sales` becomes the single writable table; `acc_map_sales_rev` becomes a derived view (or merged via column distinguishing reversal direction).

**Data Documentation Rule**: Mention table names and critical fields only. Do not include full DDL unless explicitly requested.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of confirmed sales orders that proceed to invoicing flow through the new Order→Invoice endpoint; a one-week post-deploy sample shows zero invoices created via the legacy ad-hoc path.
- **SC-002**: Zero duplicate invoices observed under load when the Order→Invoice endpoint receives 100 concurrent calls per order id with the same idempotency key (load test asserts exactly one invoice).
- **SC-003**: Zero illegal invoice state transitions in production logs over the first 30 days post-deploy.
- **SC-004**: Zero sales/purchase reversals that produce negative stock or partial reversal in production over the first 30 days; reversal-abort rate due to pre-flight failure is observable on a dashboard.
- **SC-005**: POS commit p95 latency under contention (≥10 concurrent commits per warehouse) stays within +20% of single-commit p95; zero observed negative stock rows.
- **SC-006**: 100% of offline POS commits queued during a planned 30-minute outage are processed exactly once after reconnect; manual_review rate is reported per device.
- **SC-007**: ZATCA outbox processes ≥99% of pending rows within 5 minutes under normal conditions; dead-letter rate alerts if it exceeds a configured threshold.
- **SC-008**: Sales velocity and funnel conversion are computed in deterministic unit tests against fixed fixtures with exact expected values; the legacy `updated_at − created_at` formula is removed from the codebase (static check).
- **SC-009**: Cash-flow forecast values match expected `Σ value × probability` per close-date bucket within rounding (verified by integration test).
- **SC-010**: WAC isolation per warehouse is verified by an automated test asserting that operations on warehouse W1 do not change `cost_w` for warehouse W2.
- **SC-011**: Static analysis reports zero `float`-on-cost or `float`-on-qty operations in inventory, costing, and manufacturing modules.
- **SC-012**: Auto-reorder produces correct recommendations for ≥99% of seeded below-reorder items in nightly tests; PO auto-creation produces zero PO with quantity ≤ 0.
- **SC-013**: Multi-level BOM net-requirements pass a fixture suite covering 2-level and 3-level BOMs with on-hand/on-order at each level; cycle detection produces deterministic error path strings.
- **SC-014**: Partial production completion test seeds an MO of 100 units, completes it in 3 batches (40/35/25), and asserts: total consumed materials = planned × actual yield; sum of three WIP→FG JEs balances; final WIP variance within configured tolerance.
- **SC-015**: QC gate test asserts that on QC fail the failing quantity does not appear in FG and is recorded in scrap or rework with a documented JE.
- **SC-016**: Deprecated transfer endpoints return HTTP 410 in production; observability dashboards show usage of the canonical endpoint replacing the deprecated one within 14 days.
- **SC-017**: Inventory transactions older than retention horizon are archived nightly; balance-as-of queries spanning the cut-off return values identical to pre-archival within rounding (verified by automated comparison job).
- **SC-018**: `inventory.low_stock` is delivered exactly once per `(item, warehouse, day)` in a debounce test; duplicate-rate metric stays at 0.
- **SC-019**: Account-mapping consolidation: zero readers of `acc_map_sales_rev` outside the compatibility layer (static check); zero writers outside the consolidated table.
- **SC-020**: Returns-unified consolidation: zero writers to legacy `sales_returns` or `pos_returns` tables outside the migration shim; data parity validated by a one-shot reconciliation script.
- **SC-021**: All new sensitive endpoints are tagged `critical=True` and gated by `require_sensitive_permission`; the existing OpenAPI / permission audit script reports 100% coverage for them.
- **SC-022**: All new ZATCA / signing credentials are read from the secret vault; no new credential is added to legacy stores (verified by the credential-callsite scanner).

## Assumptions

- Feature 022 (Audit & Security + Finance Integrity) ships before or concurrently with this feature and provides: audit outbox writer, PII sanitizer, `require_sensitive_permission` decorator, secret vault, account classification table, fiscal-period draft policy, JE source enum, and treasury balance trigger. This feature consumes those primitives and does not duplicate them.
- The notification queue, retry/dedup, email templates and webhook dispatcher infrastructure are owned by R6; this feature only **emits** the relevant events (sales-rep assigned, low-stock, ZATCA dead-letter alert, MRP recommendation generated). If R6 is not yet in place, emission goes through the existing minimal dispatcher with a TODO link to R6.
- Frontend changes are limited to the small surfaces this feature requires (Order→Invoice action button, ZATCA outbox monitor, MRP recommendations list, production partial-completion form, POS reconnect status). Frontend-wide sweeps are out of scope and live in R8.
- Existing pricing engines, tax computation, GL posting service, and approval primitives are reused as-is. Where a contract change is unavoidable (e.g., JE `(source, source_id)` linkage), it is documented and migrated in this feature.
- The Redis-backed POS lock uses the existing Redis cache infrastructure with a short TTL (default 5 seconds, configurable). Redis unavailability falls back to a row-level DB lock with a slower path; failure mode is documented.
- ZATCA technical requirements (UBL profile, signing algorithm, cert format) are taken from the current production integration; this feature finalises inline implementation but does not redefine ZATCA semantics.
- The "cheaper coder" implementing this spec is expected to follow existing module conventions (services + repositories + transactional boundaries, Pydantic schemas, Alembic migrations with backfill scripts, structured errors, audit on every state-changing endpoint) without inventing new architectural patterns.
- All migrations include reversible down-paths and backfill scripts; tables introduced as `_v2` are renamed to canonical names within the same release window.
- Tests are written but **not** executed by the implementer unless the user explicitly asks; verification relies on `py_compile`, static checks, EXPLAIN where relevant, and code review.
