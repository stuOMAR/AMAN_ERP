# Requirements Document

## Introduction

هذا التوصيف يحدد متطلبات تنفيذ **مهمة تدقيق Read-Only لنظام AMAN ERP** تغطي وحدات المبيعات (Sales)، المشتريات (Purchases)، والمخازن (Inventory) في كل من Backend (FastAPI/SQLAlchemy) و Frontend (React).

> **هام جداً:** هذه ليست مهمة تطوير ميزة. الناتج الوحيد المسموح به هو **تقرير تدقيق منظم** يُكتب في ملف Markdown داخل مجلد المواصفة. **لا يُسمح للوكيل المنفذ بتعديل أي ملف Source Code، ولا تعديل الاختبارات، ولا تنفيذ migrations، ولا تشغيل أي أمر يغيّر حالة قاعدة البيانات أو أي سلوك Runtime للنظام أثناء تنفيذ مهام هذا التوصيف.** الإصلاحات المقترحة تُسجّل نصياً داخل التقرير فقط.

التدقيق ينطلق من خط أساس Baseline معروف: المستخدم أغلق سابقاً 40 ملاحظة، وثبّت الإصلاحَين F-30 (Cross-currency transfers) و F-31 (Per-warehouse GL inventory accounts)، مع نجاح 26 اختبار انحدار في `backend/tests/test_inventory_sales_purchase_integrity_regressions.py`. مهمة هذا التوصيف هي اكتشاف **مخاطر جديدة أو متبقية** خارج نطاق ما تم إغلاقه.

النطاق Scope:

- **Backend:** `backend/routers/sales/*`, `backend/routers/purchases/*`, `backend/routers/inventory/*`, `backend/services/gl_service.py`, `backend/services/costing_service.py`, `backend/services/matching_service.py`, `backend/utils/party_balance.py`, `backend/schemas/sales.py`, `backend/schemas/purchases.py`.
- **Frontend:** `frontend/src/services/sales.js`, `frontend/src/services/purchases.js`, `frontend/src/services/inventory.js`, `frontend/src/pages/Sales/*`, `frontend/src/pages/Buying/*`, `frontend/src/pages/Stock/*`, `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`.

الدورات الكاملة المطلوب فحصها:

1. **Sales Cycle:** Customer → Quotation → Sales Order → Delivery Order → Invoice → Receipt → Return/Credit Note → Cancellation.
2. **Purchases Cycle:** Supplier → Purchase Request → Approval → Goods Receipt → Purchase Invoice → 3-way Match → Payment → Return/Credit Note/Debit Note → Landed Costs.
3. **Inventory Cycle:** Products → Warehouses → Transfers → Shipments → Adjustments → Movements → Batches/Serials → Cycle Counts → Valuation.

## Glossary

- **AMAN_ERP**: نظام تخطيط موارد المؤسسة قيد التدقيق، يتألف من Backend (FastAPI + SQLAlchemy + PostgreSQL) و Frontend (React).
- **Auditor_Agent**: الوكيل البرمجي الذي ينفذ مهام هذا التوصيف، ويعمل بصلاحيات Read-Only فقط فيما يخص Source Code و Database و Runtime.
- **Audit_Report**: ملف Markdown النهائي `report.md` داخل مجلد المواصفة، يحتوي على نتائج التدقيق بالشكل المحدد في Requirement 8.
- **Finding**: ملاحظة موثقة عن خلل وظيفي أو أمني أو مالي تم اكتشافها أثناء التدقيق.
- **Severity**: درجة خطورة الـ Finding، من المجموعة `{Critical, High, Medium, Low, Info}`.
- **Baseline**: الـ 40 finding المُغلقة سابقاً والإصلاحان F-30 و F-31 المُلتزمان، إضافة إلى 26 اختبار الانحدار الناجحة في `backend/tests/test_inventory_sales_purchase_integrity_regressions.py`.
- **Sales_Cycle**: السلسلة الكاملة Customer → Quotation → Sales Order → Delivery Order → Invoice → Receipt → Return/Credit Note → Cancellation.
- **Purchases_Cycle**: السلسلة الكاملة Supplier → Purchase Request → Approval → Goods Receipt → Purchase Invoice → 3-way Match → Payment → Return/Credit Note/Debit Note → Landed Costs.
- **Inventory_Cycle**: السلسلة الكاملة Products → Warehouses → Transfers → Shipments → Adjustments → Movements → Batches/Serials → Cycle Counts → Valuation.
- **GL_Entry**: قيد محاسبي في دفتر الأستاذ العام، ناتج عن عملية مالية، يجب أن يكون متوازناً (مجموع المدين = مجموع الدائن) أو موثقاً صراحة بأنه لا يحتاج قيداً.
- **Tenant_Isolation**: عزل بيانات الشركات المختلفة عبر `company_id` و `get_db_connection`، بحيث لا يستطيع مستخدم شركة الوصول لبيانات شركة أخرى.
- **Three_Way_Match**: المطابقة الثلاثية بين Purchase Order و Goods Receipt و Purchase Invoice على مستوى الكميات والأسعار.
- **Idempotency**: الخاصية التي تضمن أن إعادة إرسال نفس الطلب الحساس (إنشاء فاتورة، تسجيل دفعة، تأكيد استلام) لا يُنتج تكراراً للمستند أو للقيد.
- **Row_Level_Lock**: قفل على مستوى الصف عبر `SELECT ... FOR UPDATE` أو ما يكافئه، يمنع تعديلات متزامنة لنفس السجل.
- **Atomic_Transaction**: وحدة عمل قاعدة بيانات تُنفَّذ بالكامل أو تُتراجع بالكامل (Commit/Rollback) دون حالة وسيطة منشورة.
- **Costing_Layer**: طبقة تكلفة تمثل دخول كمية من صنف بسعر معين في تاريخ معين، تُستخدم لحساب التكلفة بطريقة WAC أو FIFO.
- **PrivateRoute**: مكون React يحمي مسارات الواجهة عبر التحقق من الجلسة والصلاحيات.
- **require_permission**: Backend dependency يُحقق صلاحية المستخدم قبل تنفيذ Endpoint.
- **Branch_Scope**: تقييد نطاق العمليات على فروع محددة وفقاً لصلاحية المستخدم.
- **Endpoint_Drift**: حالة عدم تطابق بين مسار يستدعيه Frontend و Endpoint المُعرَّف فعلياً في Backend (مسار خاطئ، Verb خاطئ، أو Endpoint غير موجود).
- **Schema_Drift**: حالة عدم تطابق بين Payload المُرسَل/المُستقبَل من Frontend و Pydantic Schema في Backend (حقول ناقصة، أنواع مختلفة، أو أسماء مختلفة).
- **Permission_Drift**: حالة عدم تطابق بين الصلاحية المطلوبة في `PrivateRoute` (Frontend) والصلاحية المُتحقَّق منها في `require_permission` (Backend) لنفس العملية.

## Requirements

### Requirement 1: Read-Only Execution Constraint

**User Story:** بصفتي مالك النظام، أريد أن يكون التدقيق Read-Only تماماً، حتى أضمن عدم تأثير عملية التدقيق على Source Code أو حالة قاعدة البيانات أو سلوك النظام.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL NOT modify any file under `backend/`, `frontend/`, `migrations/`, `db_ddl/`, أو أي ملف مصدري آخر في المستودع باستثناء الملفات الواقعة داخل `.kiro/specs/audit-sales-purchases-inventory/`.
2. THE Auditor_Agent SHALL NOT execute any command that mutates database state (e.g. `alembic upgrade`, `alembic downgrade`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `DROP`).
3. THE Auditor_Agent SHALL NOT start, stop, or restart any runtime service (Backend, Frontend, Worker, Database).
4. THE Auditor_Agent SHALL produce exactly one primary deliverable located at `.kiro/specs/audit-sales-purchases-inventory/report.md`.
5. WHERE supporting artifacts are needed (e.g. endpoint maps, payload diffs), THE Auditor_Agent SHALL place them under `.kiro/specs/audit-sales-purchases-inventory/` and reference them from `report.md`.
6. IF a proposed fix requires code changes, THEN THE Auditor_Agent SHALL describe the fix textually inside the Finding row and SHALL NOT apply the change to source files.
7. WHERE running existing tests in read-only mode (e.g. `pytest --collect-only` or executing `backend/tests/test_inventory_sales_purchase_integrity_regressions.py` to confirm baseline) is needed, THE Auditor_Agent SHALL run them only, SHALL NOT modify them, and SHALL document the command used in the report.

### Requirement 2: Baseline Acknowledgement

**User Story:** بصفتي مالك النظام، أريد أن يُعامل التدقيق الإصلاحات السابقة كخط أساس Known-Good، حتى لا يُعاد فتح ملاحظات مغلقة ويتركز الجهد على المخاطر الجديدة أو المتبقية.

#### Acceptance Criteria

1. THE Audit_Report SHALL contain a section titled "Baseline" that explicitly references the 40 previously closed findings, fixes F-30 (cross-currency transfers) و F-31 (per-warehouse GL inventory accounts), و 26 الاختبار في `backend/tests/test_inventory_sales_purchase_integrity_regressions.py`.
2. WHEN evaluating an issue that is already covered by Baseline, THE Auditor_Agent SHALL NOT list it as a new Finding unless evidence shows the fix is incomplete or has regressed; in that case THE Auditor_Agent SHALL annotate the Finding with `Regression_Of: <baseline reference>`.
3. THE Auditor_Agent SHALL run `backend/tests/test_inventory_sales_purchase_integrity_regressions.py` once in read-only mode to confirm the 26 tests still pass, and SHALL record the result (pass/fail counts and runtime) in the Baseline section.
4. IF any of the 26 baseline regression tests fails, THEN THE Auditor_Agent SHALL log a Critical Finding describing the regression with the failing test name, the failing assertion, and the Suggested Fix textually.

### Requirement 3: Sales Cycle Audit Coverage

**User Story:** بصفتي مدقّق ERP، أريد فحص دورة المبيعات الكاملة، حتى أتأكد من سلامة خصم المخزون والقيود المحاسبية والضرائب وأرصدة العملاء والصلاحيات وضوابط الفروع ومنع التكرار.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL trace the full Sales_Cycle (Customer → Quotation → Sales Order → Delivery Order → Invoice → Receipt → Return/Credit Note → Cancellation) across `backend/routers/sales/*`, `backend/services/gl_service.py`, `backend/services/costing_service.py`, `backend/utils/party_balance.py`, `backend/schemas/sales.py`, `frontend/src/services/sales.js`, و `frontend/src/pages/Sales/*`.
2. THE Auditor_Agent SHALL verify that delivery and invoice posting decreases on-hand inventory using a Costing_Layer-aware path and SHALL log a Finding for any divergence.
3. THE Auditor_Agent SHALL verify that every revenue-recognizing operation (Invoice posting, Credit Note posting, Receipt posting, Cancellation reversal) creates a balanced GL_Entry, و SHALL log a Finding for any operation that posts no GL_Entry without explicit documentation.
4. THE Auditor_Agent SHALL verify VAT/Tax computation paths match between `frontend/src/pages/Sales/InvoiceForm.jsx` and `backend/schemas/sales.py` / `backend/routers/sales/invoices.py`, و SHALL log a Schema_Drift Finding for any mismatch.
5. THE Auditor_Agent SHALL verify that Customer balance updates (via `backend/utils/party_balance.py`) are invoked atomically with the corresponding GL_Entry, و SHALL log a Finding if the balance update is outside the Atomic_Transaction.
6. THE Auditor_Agent SHALL verify Branch_Scope enforcement on every Sales endpoint (orders, deliveries, invoices, receipts, returns, cancellations) و SHALL log a Finding for any endpoint that does not filter by branch when the user is branch-scoped.
7. IF a sensitive Sales document operation (Invoice posting, Receipt posting, Cancellation) lacks Idempotency protection (idempotency key, unique constraint, or document-state guard), THEN THE Auditor_Agent SHALL log a Finding with reproduction steps for the double-submit risk.
8. WHEN auditing Cancellation flow in `backend/routers/sales/cancellation.py`, THE Auditor_Agent SHALL verify that cancellation reverses both inventory movement and GL_Entry, و SHALL log a Finding for any one-sided reversal.

### Requirement 4: Purchases Cycle Audit Coverage

**User Story:** بصفتي مدقّق ERP، أريد فحص دورة المشتريات الكاملة، حتى أتأكد من سلامة زيادة المخزون وتكلفة البضاعة وأرصدة الموردين والقيود وضرائب AP والمطابقة الثلاثية ومنع الاستلام أو الفوترة الزائدة.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL trace the full Purchases_Cycle (Supplier → Purchase Request → Approval → Goods Receipt → Purchase Invoice → 3-way Match → Payment → Return/Credit Note/Debit Note → Landed Costs) across `backend/routers/purchases/*`, `backend/services/matching_service.py`, `backend/services/gl_service.py`, `backend/services/costing_service.py`, `backend/utils/party_balance.py`, `backend/schemas/purchases.py`, `frontend/src/services/purchases.js`, و `frontend/src/pages/Buying/*`.
2. THE Auditor_Agent SHALL verify that Goods Receipt increases on-hand inventory and creates a Costing_Layer at the correct unit cost (including landed cost allocation when applicable), و SHALL log a Finding for any divergence.
3. THE Auditor_Agent SHALL verify Three_Way_Match logic in `backend/services/matching_service.py` enforces line-level linkage between PO lines, GR lines, and Invoice lines on quantity AND price, و SHALL log a Finding for any link enforced only on header level.
4. THE Auditor_Agent SHALL verify that the system prevents over-receipt against PO and over-invoicing against GR (i.e. cumulative received ≤ ordered, cumulative invoiced ≤ received), و SHALL log a Finding when a tolerance bypass exists without an authorization control.
5. THE Auditor_Agent SHALL verify VAT/AP posting on Purchase Invoice creates a balanced GL_Entry (Inventory/Expense Dr, VAT Dr, AP Cr) و SHALL log a Finding for any unbalanced or missing entry.
6. THE Auditor_Agent SHALL verify Supplier balance updates are inside the same Atomic_Transaction as the Invoice/Payment GL_Entry, و SHALL log a Finding for any balance update committed outside the transaction.
7. THE Auditor_Agent SHALL verify that Return / Credit Note / Debit Note flows reverse both inventory and GL consistently and update Supplier balance correctly, و SHALL log a Finding for any one-sided reversal.
8. THE Auditor_Agent SHALL verify Landed Cost allocation in `backend/routers/purchases/*` و `backend/services/costing_service.py` distributes costs proportionally to received lines and updates Costing_Layers, و SHALL log a Finding when the allocation diverges or skips a line.
9. IF Goods Receipt, Purchase Invoice posting, or Payment lacks Idempotency protection, THEN THE Auditor_Agent SHALL log a Finding with reproduction steps for the double-submit risk.

### Requirement 5: Inventory Cycle Audit Coverage

**User Story:** بصفتي مدقّق ERP، أريد فحص دورة المخازن الكاملة، حتى أتأكد من منع المخزون السالب وصحة قفل الصفوف وعزل الفروع وطبقات التكلفة وطرق التقييم وتطابق الحركة مع الرصيد.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL trace the full Inventory_Cycle (Products → Warehouses → Transfers → Shipments → Adjustments → Movements → Batches/Serials → Cycle Counts → Valuation) across `backend/routers/inventory/*`, `backend/services/costing_service.py`, `frontend/src/services/inventory.js`, و `frontend/src/pages/Stock/*`.
2. THE Auditor_Agent SHALL verify that every outbound stock operation (delivery, transfer-out, shipment, negative adjustment) prevents on-hand from going negative without explicit policy override, و SHALL log a Finding for any operation that allows negative stock silently.
3. THE Auditor_Agent SHALL verify that receiving, transfer, invoicing, return, and payment operations acquire Row_Level_Locks (`SELECT ... FOR UPDATE` or equivalent) on the relevant stock and party rows, و SHALL log a Finding for any operation missing the lock.
4. THE Auditor_Agent SHALL verify Branch_Scope and warehouse-level scoping on inventory queries and mutations, و SHALL log a Finding for any endpoint that returns stock from warehouses outside the user's scope.
5. THE Auditor_Agent SHALL verify Costing_Layer correctness for both WAC and FIFO methods (layer creation on receipt, layer consumption on issue, no negative layers, no orphan layers), و SHALL log a Finding for any divergence.
6. THE Auditor_Agent SHALL verify that stock movement totals (sum of `qty_in - qty_out` per item per warehouse) reconcile with current `on_hand` values and with valuation reports, و SHALL log a Finding for any reconciliation gap exceeding rounding tolerance.
7. THE Auditor_Agent SHALL verify that batches/serials are uniquely tracked, cannot be issued twice, and reconcile with item-level balances, و SHALL log a Finding for any duplicate or orphan batch/serial.
8. WHEN auditing transfer flow, THE Auditor_Agent SHALL confirm that transfers are atomic (out-of-source AND in-to-destination committed together) and respect cross-currency revaluation per F-30 baseline, و SHALL log a Regression Finding if F-30 behavior is no longer correct.
9. WHEN auditing GL inventory accounts, THE Auditor_Agent SHALL confirm per-warehouse posting per F-31 baseline, و SHALL log a Regression Finding if posting reverts to a single inventory account.

### Requirement 6: Cross-Stack Consistency Audit

**User Story:** بصفتي مدقّق Full-Stack، أريد فحص التطابق بين Frontend و Backend (المسارات، الصلاحيات، الـ Payloads)، حتى أكتشف أي Endpoint Drift أو Permission Drift أو Schema Drift يسبب أعطالاً.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL build a mapping of every API call in `frontend/src/services/sales.js`, `frontend/src/services/purchases.js`, و `frontend/src/services/inventory.js` to its corresponding Backend endpoint in `backend/routers/sales/*`, `backend/routers/purchases/*`, و `backend/routers/inventory/*`.
2. THE Auditor_Agent SHALL list every Endpoint_Drift case (Frontend calls a path/verb that has no Backend match) under a section titled "Frontend Pages Calling Mismatched APIs".
3. THE Auditor_Agent SHALL list every Backend endpoint in the audited routers that has no Frontend caller and no documented external consumer, under a section titled "Missing or Unused Endpoints".
4. THE Auditor_Agent SHALL compare each `PrivateRoute` permission in `frontend/src/App.jsx` و `frontend/src/components/Sidebar.jsx` against the corresponding `require_permission` in the Backend endpoint, و SHALL log a Permission_Drift Finding for any mismatch (different permission name, missing on either side, weaker on Backend).
5. THE Auditor_Agent SHALL compare every Frontend form Payload against the corresponding Pydantic schema in `backend/schemas/sales.py` و `backend/schemas/purchases.py` (and inline schemas under `backend/routers/inventory/*`), و SHALL log a Schema_Drift Finding for missing fields, type mismatches, or naming mismatches that would cause request rejection or silent data loss.

### Requirement 7: Cross-Cutting Correctness Audit

**User Story:** بصفتي مدقّق Senior، أريد فحص الضوابط الشاملة (Tenant Isolation، Decimal usage، Atomic Transactions، Locks، GL Balance، Party balances، Idempotency، Error Codes، Reports)، حتى أكتشف عيوباً جوهرية لا تنتمي لدورة بعينها.

#### Acceptance Criteria

1. THE Auditor_Agent SHALL verify Tenant_Isolation on every audited endpoint by confirming use of `company_id` and `get_db_connection` consistently, و SHALL log a Critical Finding for any endpoint that can leak data across tenants.
2. THE Auditor_Agent SHALL grep for `float(`, `: float`, و `Float(` usage in money/quantity fields across audited Backend modules, و SHALL log a Finding for every monetary or quantity field that uses `float` instead of `Decimal`.
3. THE Auditor_Agent SHALL verify that every financial و inventory mutation operation runs inside an Atomic_Transaction (single `with conn.transaction()` / `db.begin()` block), و SHALL log a Finding for any multi-step mutation that commits intermediate state.
4. THE Auditor_Agent SHALL verify Row_Level_Lock usage as defined in Requirement 5.3, summarized in this section as well.
5. THE Auditor_Agent SHALL verify GL_Entry balance (sum debit = sum credit) for every financial operation by inspecting `backend/services/gl_service.py` call sites, و SHALL log a Critical Finding for any unbalanced posting path.
6. THE Auditor_Agent SHALL verify customer/supplier balance update correctness via `backend/utils/party_balance.py`, و SHALL log a Finding when an operation that affects party balance does not invoke the utility or invokes it with wrong sign.
7. THE Auditor_Agent SHALL verify Idempotency on sensitive document operations (Invoice posting, Receipt posting, Payment posting, Goods Receipt, Cancellation) و SHALL log a Finding for each operation lacking Idempotency.
8. THE Auditor_Agent SHALL verify that validation errors return HTTP 400/403/409 with structured error messages, و SHALL log a Finding for any audited endpoint that returns HTTP 500 due to a recoverable validation issue.
9. THE Auditor_Agent SHALL verify that aging, statement, valuation, و stock-movement reports reconcile with their accounting/inventory source, و SHALL log a Finding for any report whose totals disagree with the source-of-truth tables.

### Requirement 8: Audit Report Format

**User Story:** بصفتي قارئ التقرير، أريد بنية موحدة لتقرير التدقيق، حتى أستطيع فرز الملاحظات حسب الخطورة وتتبعها وتحويلها إلى مهام إصلاح لاحقاً.

#### Acceptance Criteria

1. THE Audit_Report SHALL be written to `.kiro/specs/audit-sales-purchases-inventory/report.md` as the single primary deliverable.
2. THE Audit_Report SHALL contain, in order, the following top-level sections: `Executive Summary`, `Baseline`, `Findings`, `Missing or Unused Endpoints`, `Frontend Pages Calling Mismatched APIs`, `Suggested Tests`, `Methodology`.
3. THE `Executive Summary` SHALL be no longer than 25 lines and SHALL state: scope audited, count of findings per Severity, top three risks, و overall risk posture in one sentence.
4. THE `Findings` section SHALL render every Finding as a row in a Markdown table with exactly these columns in this order: `Severity | Module | File:Line | Problem | Business Impact | Reproduction Scenario | Suggested Fix | Test Needed`.
5. THE `Findings` table SHALL be sorted by Severity descending using the order `Critical > High > Medium > Low > Info`.
6. WHERE a Finding references a code location, THE `File:Line` cell SHALL use the exact relative path from the workspace root and a line number or line range (e.g. `backend/routers/sales/invoices.py:142` or `:142-167`).
7. THE `Missing or Unused Endpoints` section SHALL list every Backend endpoint in the audited routers that has no Frontend caller, in a Markdown table with columns `Method | Path | Router File | Notes`.
8. THE `Frontend Pages Calling Mismatched APIs` section SHALL list every Frontend → Backend call mismatch, in a Markdown table with columns `Frontend File | Call (Method + Path) | Expected Backend | Mismatch Type | Impact`.
9. THE `Suggested Tests` section SHALL contain two subsections, `Backend pytest` و `Frontend / E2E Playwright`, each listing test ideas that target unresolved Findings, with one bullet per test idea referencing the Finding ID it covers.
10. THE `Methodology` section SHALL document: tools/commands used (read-only only), files inspected, and any limitation encountered (e.g. unreadable file, blocked test).
11. THE Audit_Report SHALL NOT include cosmetic or style-only issues unless they cause a functional, security, or financial defect, in which case the Finding SHALL state the concrete defect caused.
12. THE Auditor_Agent SHALL assign each Finding a unique ID in the form `F-NEW-001`, `F-NEW-002`, ... incrementing across the report, و SHALL reference these IDs in the `Suggested Tests` section.
