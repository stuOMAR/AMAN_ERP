# Phase 0 Research: Audit & Security + Finance Integrity Remediation

**Feature**: 022-audit-security-finance-integrity
**Date**: 2026-05-02

The spec contained no `[NEEDS CLARIFICATION]` markers — informed defaults were chosen during specification. This document records the decisions, the alternatives that were considered, and the rationale, so that downstream tasks have a single point of reference.

## R1.1 — Audit logging atomicity

**Decision**: Use a transactional outbox pattern. `log_activity()` writes to `audit_outbox` on the **same** SQLAlchemy session as the business transaction; a background worker flushes committed rows from `audit_outbox` to `audit_logs` in a separate session, in batches, with `FOR UPDATE SKIP LOCKED`.

**Rationale**:
- Eliminates the current premature `commit` inside `log_activity` that breaks `transactional()`.
- Guarantees audit row persists iff the business operation persists.
- Batch flush keeps audit hot path cheap; SLA monitoring is straightforward (`enqueued_at` vs. `flushed_at`).

**Alternatives considered**:
- *Synchronous direct insert in caller's session* — what we have today. Rejected because callsites that wrap `log_activity` in their own transaction would still see double-commits and exception-masking issues; also doesn't help when audit writes themselves fail.
- *Fire-and-forget background task (asyncio)* — rejected because if the process crashes between business commit and audit task scheduling, the audit row is lost.
- *Logical replication / WAL-based audit* — rejected as out of proportion for the remediation; also doesn't carry the structured `details` payload we need.

## R1.2 — Audit details schema unification

**Decision**: Define a single Pydantic model `AuditDetails` (action-specific subclasses) that the writer accepts; legacy callsites that pass arbitrary dicts are normalized at the writer boundary into `{"legacy": <dict>}` and flagged for cleanup.

**Rationale**: Avoids breaking changes to ~hundreds of callsites while still landing on a stable schema for new code and analytics.

**Alternatives considered**: Flat JSON with no schema (rejected — analytics impossible); aggressive rewrite of all callsites (rejected — too risky for one feature batch).

## R1.3 — PII sanitizer

**Decision**: Single helper `sanitize_for_audit(payload, *, context)` that walks dicts/lists, applies path-based rules + key-name regex (configurable per company), and returns a redacted copy. Used by:
- the audit writer,
- the request-body capture middleware,
- the import-error formatter.

Rules are seeded with: `salary`, `iban`, `national_id`, `password`, `secret`, `token`, `api_key`, `credit_card`, plus structural-hint patterns (`column "..."`, `relation "..."`).

**Rationale**: Single boundary makes audit, log capture and error responses uniformly safe; allow-list is auditable; configurable per tenant.

**Alternatives considered**:
- *Per-callsite redaction* — rejected: causes drift and missed sites (the original problem).
- *Database trigger sanitization* — rejected: too late and can't see request body.

## R1.4 — Sensitive-permission decorator + discovery

**Decision**: A new `require_sensitive_permission(scope, *, critical=False, audit_view=True)` decorator that:
1. Calls existing `require_permission(scope)`.
2. Optionally enforces step-up auth (TOTP/recent reauth) per company policy.
3. Tags the audit log with `critical=True/False`.
4. Registers itself in a startup-time registry. A startup hook compares the registry against a curated list of sensitive route patterns; missing wraps raise `SystemExit(1)` in production and a CI-grade error in dev.

The curated list is encoded in `services/permissions/sensitive_routes.yaml` (path glob → required scope).

**Rationale**: Single point of enforcement, single CI gate, works for both Flask-style decorators and FastAPI dependencies (we use FastAPI; the hook is implemented as a `Depends()`).

**Alternatives considered**:
- *Route-by-route ad-hoc decorators* — what we have today, the source of the gap.
- *Pure middleware* — rejected: middleware can't easily know the resource semantics needed for `critical=True` and step-up.

## R1.5 — Unified credential vault

**Decision**: One table `integration_credentials` with envelope encryption: `secret_ciphertext` is encrypted with a per-tenant data key derived from the existing key derivation (KDF over master + tenant_id). `key_version` stores which master version was used so rotation is possible. Status enum supports `active | rotating | soft_deleted`. Rotation creates a new row and ages out the old one after a configurable grace.

**Rationale**: One schema for all integrations (ZATCA / SMTP / SMS / payments / shipping / bank / LDAP). Rotation overlap supports long-running jobs that already captured the old credential. Soft-delete + audit retain history for compliance.

**Alternatives considered**: External KMS (Vault, AWS KMS) — rejected as scope creep; existing tenant-aware key derivation is acceptable for this batch and the contract leaves room to swap implementations later.

## R1.6 — Webhook rate limiting

**Decision**: Per-tenant token bucket in Redis (`webhook:ratelimit:<tenant>:<integration>`) using `INCR` + `EXPIRE` with a Lua script for atomicity. Threshold and window come from `company_settings`. Exceeded requests return HTTP 429 and write an audit row.

**Rationale**: Existing Redis is already in use; token bucket fits "burst then steady" webhook traffic; per-tenant scoping prevents one tenant's misbehaving partner from affecting another.

**Alternatives considered**: NGINX-level rate limit (rejected: cannot be tenant-aware easily and bypasses our audit layer); per-process counters (rejected: not coherent across workers).

## R1.7 — Bank-feed failure alerting

**Decision**: Add a `consecutive_failures` counter on `integration_credentials` (or a small companion table) updated by the bank-feed adapter via the circuit-breaker hook. When the counter passes the configured N, a notification is dispatched via the existing notification queue and the counter is reset on first success.

**Rationale**: Reuses the existing `integrations/circuit_breaker.py` and notification queue.

## R1.8 — Device fingerprint + impossible-travel seam

**Decision**: Ship two narrow tables (`device_fingerprints`, `login_geo_events`) with no provider integration. The login flow writes a hashed fingerprint and a coarse geo placeholder; a hook point `evaluate_login_risk()` returns `"ok"` by default. This unblocks future detection rules without binding to a provider.

**Rationale**: Spec explicitly out-of-scope on provider selection; data model and seam are in scope.

## R1.9 — Ghost-employee rule

**Decision**: A scheduled job runs against the latest payroll snapshot per tenant, joining `employees`, `bank_accounts`, `attendance` and `payroll_entries`, flagging employees with: zero attendance + paid salary, IBAN matching another employee, terminated status with active payroll, missing manager. Findings written to `audit_logs` (critical) and surfaced in an HR review queue.

**Rationale**: Heuristics-only, no PII leak. Deterministic and auditable.

## R2.1 — Reconciliation finalize GL drift guard

**Decision**: `reconciliation_service.finalize(rec_id)` recomputes the GL balance for the linked account at the cut-off date via `gl_service.get_balance(account_id, as_of)` and compares to the reconciled bank/treasury total. If `abs(gl_total - bank_total) > tolerance`, finalize returns a structured drift report and rejects. Tolerance comes from `company_settings.reconciliation.drift_tolerance` (default 0.01).

**Rationale**: Single place to enforce GL truth; tolerance configurable per tenant; drift report (`gl_total`, `bank_total`, `difference`, `tolerance`, `unmatched_lines`) gives operators actionable info.

## R2.2 — Account classification (replaces hard-coded code ranges)

**Decision**: New table `account_classifications(tenant_id, account_id, statement_category, sign, aggregation_hint, is_active, valid_from, valid_to)` with one active row per `(tenant_id, account_id)`. `account_classifier.classify(account_id)` reads via per-request cache and is the only source for statement category/sign in Balance Sheet, P&L, Trial Balance and KPI.

**Defaults**: A migration seeds rows from current code-range heuristics so day-one behavior is unchanged.

**Validation**: On save, validate uniqueness, that every account has at most one active classification, and (optionally) that key reports do not break (config preview).

**Alternatives considered**: Inline classification on `accounts` table (rejected — couples report config with master data); pure code (rejected — the problem we're fixing).

## R2.3 — JE epsilon, source casing, fiscal-period gate

**Decision**:
- Epsilon: `Decimal("0.005")` default, configurable; enforced inside `gl_service.post_journal_entry`.
- Source: enum `JESource = {sales, purchase, payroll, treasury, manufacturing, manual, recurring, asset, system}`; legacy values mapped via migration; new code MUST use the enum.
- Period gate: enforced in `gl_service.validate_period(date)`; draft policy from `company_settings.fiscal.allow_drafts_in_closed_period` (default `false`).

## R2.4 — Asset-return write-down JE

**Decision**: When an asset return is recorded with remaining NBV, asset_service requests a write-down JE from `gl_service` using the configured loss-on-return account (from settings). The JE is linked to the asset via `journal_entries.source = asset` and `source_id = asset_id`.

## R2.5 — Multi-currency revaluation rounding policy

**Decision**: `Decimal` with `ROUND_HALF_UP`; FX rates stored at `NUMERIC(18,6)`; revaluation amounts at `NUMERIC(18,4)`. Document that intermediate calculations stay at full precision and only round at JE persistence boundary.

## R2.6 — Treasury balance authority

**Decision**: PostgreSQL row-level trigger on `treasury_accounts` that raises if `current_balance` is being updated and the session has not set `local "aman.gl_context" = 'on'`. The official `treasury_service.update_balance()` sets that GUC inside its `transactional()` block. Migrations may set it explicitly with audit.

**Rationale**: Mirrors the existing pattern used in other guarded tables; avoids application-only enforcement.

## R2.7 — Recurring template safety + categories

**Decision**:
- Add `review_threshold NUMERIC(18,4)`, `auto_approve BOOLEAN`, `expense_category_id BIGINT NOT NULL` (after backfill) to `recurring_je_templates`.
- Scheduler calls `recurring_je_service.run(template)` which posts directly if `auto_approve AND amount < review_threshold`, else creates a `pending_review` record routed to approvers.
- Generated JE inherits `expense_category_id` (propagated via `journal_lines.expense_category_id` or equivalent column) for reporting.

## R2.8 — Employee-receipt-vs-advance reconciliation

**Decision**: New table `employee_receipt_settlements(employee_id, advance_id, receipt_id, amount, status, approved_by, je_id)` wires receipts to advances with approval and GL link.

## R2.9 — Auto-approve scheduler & cost-center policy

**Decision**:
- Auto-approve scheduler: a job that scans pending expense approvals and auto-approves those below `company_settings.expenses.auto_approve_threshold`, recording reason in audit.
- Cost-center policy: enum in settings `{off, warn, required}`. JE/posting validators consult this and either pass, log warning, or reject.

## R2.10 — Uniform report-view audit policy

**Decision**: Decorator `audit_report_view(report_key)` applied to every financial-report endpoint, writing a uniform audit row `{report_key, filters, period, generated_at}`. Combined with `require_sensitive_permission(..., audit_view=True)` for permission + audit.

## CI gates introduced

- `scripts/audit_writer_lint.py` — fails on any `INSERT INTO audit_logs` outside `services/audit_writer.py`, and on any `COMMIT`/`ROLLBACK` inside `log_activity` and its dependencies (AST scan).
- Sensitive-permission discovery — startup hook in dev/CI; `pytest`-free, runs as part of `python -m backend.scripts.permissions_discover`.
- Code-range scan — fails on remaining hard-coded account-code-range checks in `backend/services/reports/**` and `backend/routers/reports*`.

## Open questions remaining

None. All decisions above are commitments for Phase 1 / Phase 2.
