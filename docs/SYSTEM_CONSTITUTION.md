# AMAN ERP System Constitution

Version: 1.1.2
Last amended: 2026-05-21

This constitution defines the engineering contract for AMAN ERP. Rules marked
`[CRITICAL]` are non-negotiable. Violating one is a critical defect.

Amendment rationale for v1.1.2: made backend-authoritative calculation and
decimal display rules explicit across frontend/backend boundaries.

## 1. Financial Precision [CRITICAL]

`float`, `double`, and JavaScript `Number` are forbidden for monetary values.

| Rule | Requirement |
| --- | --- |
| SQL type | `NUMERIC(18,4)` or narrower for money columns. |
| Python | `decimal.Decimal` with `ROUND_HALF_UP`. |
| JavaScript | String-based amounts or a fixed-point library. `Number`, `parseFloat`, `toFixed`, and `toLocaleString` are forbidden for money, tax, FX, allocation, and cost values. |
| Comparison tolerance | `Decimal("0.01")`. |
| Exchange rate | Locked at transaction date; revaluation must not alter the original rate. |
| Budget | Enforced at journal-entry posting; overrun blocks or requires approval. |
| Payment allocation | One payment can allocate to many invoices, with remainder tracking. |
| Deferred revenue | Follows configured method: over-time or at-point-in-time. |
| API decimal display | Monetary and rate responses must not expose scientific notation such as `0E+6`; serialize display values as normal decimal strings. |

## 2. Multi-Tenant Isolation [CRITICAL]

AMAN uses one PostgreSQL database per company: `aman_{company_id}`. Cross-tenant
data leakage is a critical defect.

| Rule | Requirement |
| --- | --- |
| DB routing | Tenant operations must use the company-specific connection path, usually `get_db_connection(company_id)`. |
| DDL safety | Validate identifiers before DDL, including `validate_aman_identifier()` where applicable. |
| DDL engine | Tenant DDL must use the intended autocommit-safe path. |
| System data | System users, company registry, and system-level audit data belong only in the system database. |
| Engine cache | Tenant engine cache must be LRU-bounded to prevent connection exhaustion. |
| Migrations | Run Alembic per tenant: `alembic -x company=<id> upgrade head`. |
| New company | New companies must be created at schema HEAD. |

## 3. Double-Entry Integrity [CRITICAL]

Every financial transaction must produce balanced journal entries. Debit total
must equal credit total. No temporary exceptions are allowed at commit time.

| Rule | Requirement |
| --- | --- |
| Entry creation | Business transactions create journal entries through `services/gl_service.py`. Direct journal inserts are forbidden. |
| DB constraint | `trg_journal_balance` must validate journal balance, preferably `DEFERRABLE INITIALLY DEFERRED`. |
| App validation | `validate_je_lines()` must run before persisting transaction journal lines. |
| Fiscal period | `check_fiscal_period_open()` gates transaction creation. |
| Recurring JEs | Auto-post only into open periods; skipped periods are flagged for review. |

## 4. Security And Access Control [CRITICAL]

| Area | Rule |
| --- | --- |
| Tokens | Current auth contract: JWT access and refresh tokens are returned in the login body; Axios adds the Bearer header. |
| New secrets | Do not add new secrets to `localStorage` without explicit architectural justification. |
| Token payload | Must include `user_id`, `company_id`, `role`, `permissions`, `enabled_modules`, `allowed_branches`, and `type`. |
| 2FA | TOTP via `pyotp` is required where the auth flow mandates it. |
| Endpoints | Protected router endpoints require `require_permission("module.action")` or the existing module-specific equivalent. |
| Public exceptions | Login, refresh, health, and development docs are explicit exceptions. |
| Permission levels | Role-level, field-level, cost-center-level, and warehouse-level rules must be preserved. |
| Rate limits | Login, forgot-password, user API, and API-key limits must remain enforced. |
| Sessions | 401 should refresh when possible; logout blacklists tokens in DB/cache; concurrent sessions are validated. |
| Logs | Secrets, tokens, credentials, and private keys must never appear in logs or API responses. |
| SQL | Use parameterized SQL. String interpolation with untrusted input is forbidden. |
| XSS | Nginx CSP headers are required in deployed environments. |
| Error sanitization | `raise HTTPException(detail=str(e))` is forbidden. Log the exception and return a generic/i18n message. |
| Branch filtering | Branch-scoped endpoints must validate branch access. |
| Bypass rules | Superusers/admins may bypass; empty `allowed_branches` means unrestricted. |
| Warehouse routing | Warehouse-scoped logic must resolve the warehouse branch before access checks. |

## 5. Saudi Regulatory Compliance [CRITICAL]

| Regulation | Requirements |
| --- | --- |
| ZATCA / VAT | 15% standard VAT rate, e-invoicing, gross-up logic, and proportional header-discount tax-base reduction per line. |
| WHT | Deduction at source through `WhtRate` and `WhtTransaction`; capital gains excluded from VAT. |
| Tax regimes | `TaxRegime` with jurisdiction codes; branch and company overrides apply. |
| GOSI / WPS | Runtime settings are authoritative. Hardcoded values are fallback only. WPS requires labor card, insurance number, and visa status where applicable. |
| Zakat | Follow `docs/ZAKAT_CALCULATION_METHODOLOGY.md`. |
| Configurability | Saudi rates and thresholds must be stored as settings. Hardcoding requires documented fallback reasoning. |
| Tests | ZATCA, GOSI, WHT, Zakat, and Saudization changes require tests. |

## 6. Concurrency Safety

| Scenario | Protection |
| --- | --- |
| Inventory transfers and treasury movements | Use `SELECT ... FOR UPDATE` row-level locks. |
| Low-lock entities | Use optimistic locking via version columns. |
| Balance-affecting operations | Execute atomically in a single DB transaction. |
| Credit limit | Validate `customer_balance + order_total <= credit_limit` atomically at sales-order posting. |
| BOM reservation | Component decrement/reservation must be atomic. |
| Three-way match | Validate PO quantity, GRN quantity, and invoice quantity before payment. |

## 7. Simplicity And Maintainability

| Rule | Detail |
| --- | --- |
| SQL-first | Prefer `db.execute(text(...))` with parameters for queries. Use Pydantic at API boundaries. |
| Abstractions | Add a new abstraction only after 3+ proven use cases or a clear local pattern. |
| Naming | Python uses `snake_case`; JavaScript/React uses `camelCase`. |
| Logging | Use structured logging. `print()` is forbidden in production code. |
| Large lists | Use `VirtualList` or equivalent for 1000+ rows. |
| Indexes | Add indexes for new high-cardinality filter columns. |
| Pagination | Default 25 rows, maximum 100, unless streaming/export behavior applies. |
| Frontend | Follow `docs/FRONTEND_STYLE_GUIDE.md`. |

## 8. Inventory Integrity

| Rule | Detail |
| --- | --- |
| UOM | Every movement quantity must be divisible by the product base unit. |
| Available quantity | Use `qty_on_hand - qty_reserved - qty_damaged`, never `qty_on_hand` alone. |
| Costing | FIFO through batch/serial movements; company policy can be FIFO/LIFO/weighted average. |
| Costing changes | Record policy history and inventory cost snapshots. |
| Adjustments | Generate variance journal entries through the GL service. |
| Transfers | Transit status must be tracked; source stock changes only at the correct workflow stage. |
| Cycle count | Variances create adjustment entries. |
| Bin management | Track inventory per warehouse, bin, and product. |
| Traceability | Batch/serial is enforced for flagged products. |
| Quality | Quality inspection gates receipt for configured categories. |

## 9. Procurement Discipline

| Rule | Detail |
| --- | --- |
| PO lines | Discounts and markups can exist at line and total levels. |
| Landed costs | Allocate by quantity or value. |
| Three-way match | PO, GRN, and supplier invoice must match before payment, within configured tolerance. |
| Blanket PO | Track consumed quantity against agreement limits. |
| Supplier rating | Quality, delivery, and price influence approval. |
| Payment terms | Due date is computed from invoice date plus payment days. |

## 10. Manufacturing Execution

| Rule | Detail |
| --- | --- |
| BOM consumption | Components reduce automatically at the configured manufacturing event. |
| Scrap | `output_qty = required_qty / (1 - scrap_rate%)`. |
| Routing | Step N is blocked until step N-1 is complete. |
| Capacity | Validate resource capacity before MO release. |
| Job cards | Track quantity produced, scrap, and downtime per operation. |
| MO state machine | `draft -> planned -> released -> in_progress -> completed`. |

## 11. HR And Payroll Compliance

| Rule | Detail |
| --- | --- |
| Salary formula | `basic_salary + allowances - deductions = net_salary`; FX rate locks at period end for multi-currency payroll. |
| Payroll status | `draft -> calculated -> locked`; no edits after lock. |
| Leave | Decrement on approval; reset at fiscal year end per leave type. |
| Termination | Close pending leaves and generate end-of-service calculation. |
| WPS | Labor card number, insurance number, and visa status are mandatory where required. |
| GOSI | Rates come from configured tables. |
| Documents | Expiry dates drive compliance alerts. |
| Custody | Company assets are tracked and reconciled at termination. |
| Recruitment | `JobOpening -> JobApplication` follows the hiring workflow. |

## 12. Asset Lifecycle Management

| Rule | Detail |
| --- | --- |
| Depreciation | `monthly = (cost - salvage_value) / (useful_life_years * 12)`. |
| Schedules | Depreciation schedules are generated at creation when applicable. |
| Disposal | Derecognition journal entry goes through GL service. |
| Revaluation | Adjusts carrying value and equity/surplus/deficit correctly. |
| Impairment | Writes down to fair value and creates a journal entry. |
| Transfers | Logged as asset transfer events. |
| Insurance | Policy numbers and expiry dates are tracked. |
| Maintenance | Costs are recorded per asset. |

## 13. Sales And CRM Workflow

| Rule | Detail |
| --- | --- |
| State machine | `Quotation -> SO -> Delivery -> Invoice -> Receipt`; no invalid skipping. |
| Credit limit | `customer_balance + order_total > credit_limit` blocks SO posting. |
| Commissions | Calculated per invoice and paid after collection only. |
| Pricing | Customer price list overrides standard pricing when configured. |
| Party | A party can be both customer and supplier. |
| CRM pipeline | `lead -> proposal -> negotiation -> won/lost`, with probability and expected close date. |
| Lead scoring | Calculated by rule. |
| Targets | Tracked per salesperson. |

## 14. Approval Workflow Governance

| Rule | Detail |
| --- | --- |
| Levels | Number of approvers is configurable by document type. |
| Sequence | Level N cannot approve after level N-1 rejected. |
| Logging | Approval actions store timestamp, approver, action, and comments. |
| Rejection | Rejection loops back to preparer. |
| Status | `pending -> approved / rejected`. |

## 15. Project And Contract Management

| Rule | Detail |
| --- | --- |
| Budget | Planned-vs-actual variance is tracked and surfaced. |
| Progress | Task percent complete rolls up to project level. |
| Dependencies | Task dependencies prevent out-of-order execution. |
| Contract types | Support fixed-price and time-and-materials billing. |
| Expenses | Receipt references and cost type links are required. |
| Milestones | Planned and actual dates are tracked. |

## 16. POS Operations

| Rule | Detail |
| --- | --- |
| Sessions | Opening and closing balances per shift, user, and warehouse. |
| Payments | Multi-tender payments through `PosOrderPayment`. |
| Returns | Validate quantity and UOM against original order. |
| Loyalty | Points accumulation and redemption are tracked. |
| F&B / tables | Kitchen flow: `pending -> preparing -> ready`. |
| Promotions | Applied at order time and reflected in journal entries. |
| Closure | Actual cash reconciles against system balance. |

## 17. Observability And Audit Trail

| Rule | Detail |
| --- | --- |
| Audit fields | Business entities must track created/updated timestamps and users. |
| Soft delete | Business entities use soft-delete unless a documented exception applies. |
| Exceptions | Pure junction tables and append-only logs/events may be exempt. |
| Audit log | State-changing APIs record user, action, resource, and JSON diff where feasible. |
| Notifications | In-app, WebSocket, webhook, and email channels are supported. |
| Reports | Custom reports must remain user-definable without code changes. |

## 18. Session Contract And API Consistency

`POST /api/auth/login` must return these token fields:

| Field |
| --- |
| `access_token` |
| `refresh_token` |
| `token_type` |

The user object must include:

| Field |
| --- |
| `id` |
| `username` |
| `full_name` |
| `email` |
| `role` |
| `company_id` |
| `permissions` |
| `enabled_modules` |
| `allowed_branches` |
| `industry_type` |
| `currency` |
| `decimal_places` |
| `timezone` |

- `GET /api/auth/me` must return the same user shape.
- Removing or renaming existing fields is a major breaking change.
- `AuthContext` stores the full user object.
- `BranchContext` derives from `user.allowed_branches`.
- `useIndustryType()` derives from `user.industry_type`.
- Route visibility is gated by `user.enabled_modules`, not hardcoded role or
  industry checks.
- Login and `/me` must be updated together when the payload changes.

## 19. Calculation Centralization [CRITICAL]

Duplicate calculation logic across routers, services, or frontend is a critical
defect.

| Calculation | Rule |
| --- | --- |
| Tax | VAT, WHT, and gross-up logic use one shared utility. Routers must not inline tax math. |
| Discounts / markups | Use a centralized calculator. |
| Account balance | Use one canonical method; derived stores are reconciled caches. |
| Invoice totals | Use the canonical invoice-total function for sales, purchase, POS, credit notes, and debit notes. |
| Frontend | No monetary calculations. Backend returns calculated values; frontend formats only. |
| Raw input contract | Frontend sends raw user inputs only. It must not send frontend-computed subtotal, total, tax, discount, remaining, allocation, FX, valuation, COGS, or cost amounts. |
| Backend authority | Backend preview, detail, and create/post services are the only authority for money, tax, discount, FX, remaining balance, allocation, inventory cost, valuation, and COGS calculations. |
| No local fallback | Frontend must not fallback to local formulas or default FX values such as `exchange_rate = 1` for non-base currency when the backend has not resolved the rate. |
| Preview/detail contract | If a UI needs a calculated field, add it to the appropriate backend preview/detail response instead of recomputing it in React. |
| Display only | Frontend formatting helpers may pad, group, or normalize decimal strings; they must not change monetary meaning or perform business calculations. |
| Bug fixes | Fix the centralized logic so all callers inherit the correction. |

## 20. Report Consistency And Reconciliation [CRITICAL]

| Rule | Detail |
| --- | --- |
| Trial balance | Must equal `SUM(debit) - SUM(credit)` from `journal_lines` per fiscal period. |
| Subledgers | AR aging reconciles to GL receivables; AP aging to GL payables; inventory valuation to GL inventory. |
| Query source | Financial reports query `journal_lines` directly unless a timestamped cache with recalculation exists. |
| Same params | API, page, and Excel export use the same query function for the same filters. |
| Period boundaries | Use fiscal period dates, not `created_at`, for period reporting. |
| Multi-currency | Functional and foreign amounts are separated; do not mix them in one total column. |

## 21. Cross-Module Data Consistency

| Entity | Rule |
| --- | --- |
| Party | Read from `parties`; no shadow copies. |
| Product catalog | Name, UOM, tax category, and costing come from `products`. |
| GL account refs | Store `account_id` FK; resolve code/name/type by join. |
| Exchange rates | All modules read from the same `exchange_rates` source with the same date lookup. |
| Calculated responses | Preview/detail endpoints expose all UI-needed calculated values so clients do not duplicate financial logic. |
| Config cascade | Company default, then branch override, consistently across modules. |

## 22. Transaction Validation Pipeline

Every financial mutation follows this sequence:

| Step | Stage | Detail |
| --- | --- | --- |
| 1 | Schema | Pydantic validation. |
| 2 | Permission | Permission and module checks. |
| 3 | Fiscal period | `check_fiscal_period_open()`. |
| 4 | Business rules | Credit limit, stock, budget, approval status. |
| 5 | Calculation | Totals balance, tax correctness, line/header match. |
| 6 | Persist | Database write. |
| 7 | Post-persist | GL entry, notifications, side effects. |

- Fail fast at the earliest stage.
- Accumulate all errors within a stage where practical.
- The same pipeline applies to API, POS, and bulk import.
- Draft records skip stages 4 and 5 but still require stages 1 and 2.
- Draft-to-posted transitions run the full pipeline.

## 23. Idempotency And Duplicate Prevention [CRITICAL]

Duplicate payments, invoices, or orders caused by double-submit are critical
defects.

| Rule | Detail |
| --- | --- |
| Idempotency keys | Payment, invoice, and order endpoints accept optional `Idempotency-Key`; same key returns original response; TTL at least 24h. |
| Financial documents | Any endpoint that creates vouchers, invoices, credit/debit notes, payments, receipts, inventory value movements, or GL-affecting documents must provide idempotency or an equivalent replay guard. |
| Duplicate detection | Check `(party_id, amount, date, reference)` within a configurable window; prompt instead of silently creating. |
| Sequence numbers | Generate atomically with row lock. Gaps are acceptable; duplicates are not. |
| Frontend guard | Mutation buttons disable after first click until server response, preferably through shared client/form behavior. |
| Bulk import | Detect natural-key duplicates and report created/skipped/failed counts. |

## 24. Data Lifecycle Governance

| Rule | Detail |
| --- | --- |
| Retention | Audit logs kept at least 7 years; soft-deleted records retained at least 1 fiscal year before archival. |
| Archival | Configurable archive period; archived data remains queryable for compliance and excluded from operational queries by default. |
| Restore | Soft-delete restore is logged and revalidates current business rules. |
| Cleanup | Sessions, OTPs, idempotency keys, and stale cache are purged by scheduler with configurable frequency. |
| Attachments | Track size and MIME type; monitor company quota; flag orphaned attachments instead of auto-deleting. |

## 25. Performance And Query Discipline

| Rule | Detail |
| --- | --- |
| N+1 prevention | Lists with related data use JOINs or batch queries. Loop plus `db.execute()` is forbidden for list rows. |
| Query reuse | Same data shape uses a shared query function; avoid copy-paste SQL. |
| Pagination | Every list endpoint enforces `LIMIT`; unbounded queries on large tables are forbidden. |
| Exports | Exports may bypass pagination but must stream or chunk. |
| Heavy aggregation | Queries taking more than 2s on representative data need optimization, index, materialized view, or pre-aggregation. |
| Connections | Request-scoped DB dependencies close sessions/connections. |

## 26. Calculation Traceability

| Domain | Must store |
| --- | --- |
| Tax per line | `tax_rate`, `taxable_base`, `tax_amount`, tax regime reference, and override flag. |
| Discounts | Source, original amount, discount amount, and net amount. |
| Exchange rates | Source currency, target currency, rate used, rate date, and rate source. |
| Payroll run | Basic salary, allowances, deductions, employee/employer GOSI shares, and net salary per employee. |
| Inventory costing | Previous cost, new cost, affected quantity, and trigger event. |

## 27. UI/UX Behavioral Consistency [CRITICAL]

| Component | Required behavior |
| --- | --- |
| `DataTable` | Server-side pagination, default 25 rows, column sort for dates/amounts, primary text search. |
| Table export | Excel/CSV exports the full filtered dataset and uses the same query function as the list endpoint. |
| Form validation | Inline field errors on submit; clear on change after failure. No `alert()` or toast-only validation. |
| Error messages | Use translated i18n keys. Raw backend strings are forbidden. |
| Loading states | Use `PageLoading`, `DataTable` skeleton, or action-button spinner as appropriate. |
| Confirmation | Use shared `ConfirmDialog` for destructive actions. |
| Filter persistence | Filters, sort, and page restore on back-navigation. |
| Layout rhythm | Workspace header, filters/actions, content, then pagination. |

## 28. Schema Definition Synchronization [CRITICAL]

Schema drift is a critical defect.

Every tenant schema change must update both:

1. `backend/alembic/versions/` for existing companies.
2. `backend/db_ddl/tenant_schema.py` for the tenant baseline used for new
   company creation.

Also update `backend/database.py` when the changed table/index/constraint is
bootstrapped there for system-level or compatibility initialization.

| Change type | Requirement |
| --- | --- |
| Column add | Same type, default, and nullability in migration and tenant baseline. |
| Column remove | Remove from tenant baseline and drop through migration. |
| Index changes | Match index expressions and `WHERE` clauses in migration and baseline. |
| Table add/remove | Add/remove in baseline and migration. |
| Verification | A freshly created company DB should match an existing company after all migrations. |

## 29. Technology Stack

| Layer | Technology and constraint |
| --- | --- |
| Backend | Python 3.12, FastAPI, routers for all endpoints. |
| Frontend | React 18, Vite, JSX, i18next AR/EN, RTL support. |
| Mobile | React Native, React Navigation, Firebase, AsyncStorage. |
| Database | PostgreSQL 15, one DB per tenant plus system DB. |
| ORM | SQLAlchemy 2.0; SQL-first query style. |
| Cache | Redis for rate limiting, sessions, token blacklist, and caches. |
| Auth | JWT Bearer and TOTP via `pyotp`. |
| Container | Docker and Nginx with Compose orchestration and TLS in production. |
| Production | Gunicorn with Uvicorn workers behind Nginx. |
| Monitoring | Prometheus and Grafana; `/metrics` is internal-only. |
| Validation | Pydantic request/response bodies; 422 on validation failure. |

- Backend and frontend are independently deployable.
- New Python dependencies go in `backend/requirements.txt`.
- Schema changes go through Alembic; manual production DDL is forbidden.
- New endpoints need a Pydantic `response_model` unless an existing module
  pattern documents a different response contract.

## 30. Data Integrity Constraints

### Database Level

| Constraint | Rule |
| --- | --- |
| Indexes | Required for high-cardinality, frequently filtered columns. |
| FK constraints | Explicit `CASCADE`, `SET NULL`, or `RESTRICT`. |
| Check constraints | Include checks such as debit/credit non-negative, start date before end date, and quantity non-negative. |
| Unique constraints | Business numbers such as account, party, invoice, PO, SO, RFQ, and journal numbers are unique per tenant DB. |
| Balance trigger | Journal balance trigger validates debit equals credit at commit. |

### Model And Schema Integrity

| Rule | Requirement |
| --- | --- |
| Model registration | New SQLAlchemy models are imported through the model package where applicable. |
| DDL/ORM parity | Column, type, length, default, and constraints match between ORM and DDL. |
| FK `ondelete` parity | `ForeignKey(ondelete=...)` matches DDL `ON DELETE`. |
| Relationships | FKs should have relationships where the ORM is used for that entity. |
| Migration coverage | Every tenant DDL addition has Alembic coverage. |
| Audit columns | Audit/soft-delete fields exist in DDL for business entities unless documented as exceptions. |

## 31. Quality Gates

| Gate | Requirement |
| --- | --- |
| Testing | New transactional endpoints test auth, permissions, fiscal enforcement, journal balance, and UOM/stock behavior where relevant. |
| Migrations | Tenant migrations are idempotent and work across active company DBs. |
| Review focus | GL service, permission decorators, tenant routing, approval workflows, and compliance logic. |
| i18n | New user-facing strings go in English and Arabic locale files. |
| Frontend tests | New pages handling auth, permissions, branch filtering, or i18n get Vitest/RTL coverage. |

## 32. Legacy Code Policy

If existing code violates this constitution:

- Do not expand the violation.
- Fix it when touching the area if the fix is low risk and well scoped.
- If fixing it is not safe in the current task, keep the new behavior compliant
  and document the remaining debt in the relevant task, PR, or audit note.
- Add regression tests around the new compliant behavior when practical.

## 33. Document Precedence

When guidance conflicts, use this order:

1. `AGENTS.md`.
2. `docs/SYSTEM_CONSTITUTION.md`.
3. Module-specific documentation.
4. Existing code patterns.

Critical safety rules still override local patterns that are known legacy
violations.

## 34. Agent Completion Contract

Every completed coding task should report:

- Files changed.
- Tests/builds run.
- Constitution-sensitive areas touched.
- Tests not run and why.

## 35. PR Merge Gate Checklist

| Item | Status |
| --- | --- |
| No `float` for money | unchecked |
| No `detail=str(e)` error leakage | unchecked |
| Branch access validated on branch-scoped endpoints | unchecked |
| Audit and soft-delete fields on new business entities | unchecked |
| FK `ondelete` explicit | unchecked |
| New strings in English and Arabic locale files | unchecked |
| Compliance logic has test coverage | unchecked |
| Login and `/me` updated together if payload changed | unchecked |
| Response shape matches module pattern | unchecked |
| Alembic migration included for schema changes | unchecked |
| Tenant baseline updated for schema changes | unchecked |
| No duplicated calculation logic | unchecked |
| Idempotency key on payment, invoice, and order mutations | unchecked |
| Tax, discount, and FX breakdown stored where applicable | unchecked |
