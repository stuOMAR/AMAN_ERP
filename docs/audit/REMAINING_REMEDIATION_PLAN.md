# AMAN ERP — Remaining Remediation Plan

> تاريخ الإنشاء: 2026-05-02  
> الغرض: ملف واحد يجمع البنود غير المنجزة فقط بعد B41، ويحوّلها إلى خطة إصلاح متكاملة بدل التشتت بين `TODO.md` و`P3_BACKLOG.md` والتقارير الفردية.  
> قيد العمل الحالي: لا تشغيل ولا قراءة لملفات test إلا بتوجيه صريح من المستخدم.

---

## لماذا هذا الملف؟

العمل السابق كان مناسبًا أثناء مرحلة التدقيق والإغلاق السريع: كل دفعة كانت تثبت ما أُصلح، وما كان false-positive، وما يجب تأجيله. لكن بعد B41 صار لدينا تاريخ طويل ومفيد، وليس خطة تشغيل يومية واضحة.

لذلك هذا الملف يصبح **مصدر الحقيقة العملي للبنود المتبقية**. أما الملفات القديمة فتبقى مؤقتًا كأدلة تدقيق إلى أن يتم اعتماد هذا الملف، ثم يمكن أرشفتها أو حذفها حسب سياسة التنظيف في آخر الملف.

---

## تعريف الحالة

| الحالة | المعنى العملي |
|---|---|
| TODO | بند لم يبدأ بعد ويجب تنفيذه أو التحقق منه. |
| PARTIAL | جزء منه موجود، لكن لا يجوز اعتباره مغلقًا قبل إكمال المتطلب. |
| ARCHITECTURAL | تغيير واسع يحتاج تصميم/مخطط/ترحيل/مراجعة أثر. |
| OPS | يعتمد على التشغيل أو البنية التحتية وليس الكود فقط. |
| CLEANUP | تنظيف ملفات/توثيق/إزالة ازدواج بعد اعتماد الخطة. |

لا تُنقل البنود `FIXED` أو `INVALID` أو `wont-fix` إلى خطة التنفيذ إلا إذا ظهر دليل جديد.

---

## ملخص التنفيذ المقترح

| المسار | الأولوية | الهدف | بنود رئيسية |
|---|---|---|---|
| R1 — Audit & Security | عالية | إغلاق مخاطر التدقيق والصلاحيات والأسرار | audit atomicity, sensitive permissions, secret vault sweep |
| R2 — Finance Integrity | عالية | منع أخطاء مالية/GL/reconciliation | fiscal behavior, account mappings, reconciliation GL validation |
| R3 — Sales/POS/ZATCA | عالية | ضبط دورة البيع وPOS وZATCA offline | order-to-invoice, invoice state machine, UBL/signing/outbox |
| R4 — Inventory/Manufacturing Costing | عالية | توحيد التكلفة والمخزون والتصنيع | WAC per warehouse, MRP, partial production, by-product costing |
| R5 — HR/Payroll/PII | عالية | حماية PII واستكمال payroll workflows | payroll overlap, salary/IBAN visibility, GOSI/hazard, reversals |
| R6 — FSM/DMS/Notifications | متوسطة | إكمال الخدمة والمستندات والتنبيهات | service pricing, preventive maintenance, quotas, notification queues |
| R7 — Reports/Search/Dashboard | متوسطة | أداء وتقارير وتجربة بحث موحدة | report MVs, account classification, GlobalSearch UI, dashboard MVs |
| R8 — Frontend/Architecture/Ops | متوسطة | تقليل الدين التقني وتحسين النضج | useApi sweep, navigation, CSS splitting, repo pattern, backup automation |

---

## R1 — Audit & Security

### الهدف
تقليل المخاطر التي قد تكسر سلامة التدقيق أو تكشف بيانات حساسة.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #132 | FIXED | توحيد schema لحقل `audit_logs.details` بين callsites المختلفة. _(022: outbox writer + PII sanitizer)_ |
| #133 | FIXED | إصلاح `log_activity` حتى لا يعمل `commit` مبكرًا داخل `transactional()`. _(022: outbox pattern)_ |
| #134 | FIXED | نقل audit logging إلى outbox/async أو session مستقلة آمنة. _(022: `audit_outbox` table + worker flush)_ |
| #135 | FIXED | Impossible-travel detection عبر IP geolocation provider. _(022: `login_geo_events` + `device_fingerprints`)_ |
| #136 | FIXED | مراجعة مواضع audit/time metadata التي تعتمد على ساعة التطبيق وتوحيد السياسة مع `NOW()`/DB timestamp عند الحاجة. _(022: outbox uses DB timestamp)_ |
| #275 | FIXED | إضافة device fingerprinting آمن لتتبع الأجهزة دون تخزين PII خام. _(022: SHA-256 coarsened fingerprint)_ |
| #351 | FIXED | توسيع وسم `critical=True` على endpoints الحساسة. _(022: `require_sensitive_permission` decorator)_ |
| #352 | FIXED | تسجيل body آمن بعد PII sanitization. _(022: `sanitize_for_audit()`)_ |
| #353 | FIXED | rule لكشف نمط الموظف الشبح. _(022: `ghost_employee_check` scheduler job)_ |
| #408 / #487 | FIXED | sweep لتطبيق `require_sensitive_permission` على endpoints مالية/PII. _(022: sweep complete)_ |
| #413 | FIXED | حماية LDAP password POST بسياق HTTPS/production policy. _(022: sensitive permission gate)_ |
| #162 | FIXED | توحيد كل أسرار ZATCA/SMTP والتكاملات على encrypted key vault. _(022: `integration_credentials` vault)_ |
| #225 | FIXED | rate limit per-tenant للـ inbound webhooks. _(022: Redis token bucket)_ |
| #226 | FIXED | soft delete + audit للـ integration credentials. _(022: vault CRUD + soft-delete)_ |
| #227 | FIXED | تنبيه عند فشل bank feed لأكثر من X محاولات. _(022: `consecutive_failures` alerting)_ |
| #228 | FIXED | rotation لمفاتيح SMS gateway. _(022: credential rotation in vault)_ |
| #272a | FIXED | تقليل تسريب معلومات هيكلية في أخطاء import. _(022: sanitized error paths)_ |

### خطة الإصلاح
1. إصلاح audit atomicity أولًا (#133)، لأنه يؤثر على صحة المعاملات.
2. إضافة sanitizer مركزي للـ audit details/body.
3. تنفيذ sensitive-permission sweep على HR/Finance/Reports/Settings.
4. نقل أسرار التكاملات الباقية إلى vault موحد.
5. إضافة قواعد fraud/security التي تحتاج providers بعد تحديد مزود IP geo.

---

## R2 — Finance Integrity

### الهدف
إغلاق الثغرات التي قد تخلق فروقًا مالية أو اعتمادًا شكليًا دون تطابق فعلي.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #271 | FIXED | تضييق تسامح توازن القيود حول 0.01 وفق سياسة واضحة. _(022: configurable `gl.je_epsilon`)_ |
| #272 | FIXED | توحيد `source` في الفواتير إلى casing موحد. _(022: JESource enum + normalization migration)_ |
| #273 | FIXED | السماح بالمسودات في فترات مغلقة أو ضبط policy واضح لها. _(022: `fiscal.allow_drafts_in_closed_period` setting)_ |
| #419x / #272u | FIXED | `finalize` في reconciliation يجب أن يقارن GL مع treasury/account balance. _(022: drift guard + structured 409 report)_ |
| #419q | FIXED | asset return يحتاج writedown JE حسب IFRS/depreciation. _(022: `create_asset_return_write_down()`)_ |
| #419p | FIXED | استكمال سياسة تقريب revaluation متعدد العملات وتوثيق حدود الدقة. _(022: `round_amount()`/`round_fx_rate()` helpers)_ |
| #195 | FIXED | workflow مراجعة بشرية اختيارية للقوالب المتكررة عالية القيمة قبل auto-post. _(022: `recurring_je_pending_review` + admin queue)_ |
| #196 | FIXED | ربط القوالب المحاسبية المتكررة بسجل/تصنيف مصروفات موحد للتقارير. _(022: `expense_category_id` on pending review)_ |
| #197 | FIXED | نموذج تسوية إيصالات الموظف مقابل السلف وربطه بالاعتمادات وGL. _(022: `employee_receipt_settlements` + endpoints)_ |
| #310 | FIXED | تفعيل auto-approve-below-threshold عبر scheduler/hook واضح. _(022: `expense_auto_approve` scheduler job)_ |
| #311 | FIXED | فرض `cost_center_id` حسب سياسة الشركة بدل بقائه اختياريًا دائمًا. _(022: `cost_center_policy` setting)_ |
| #312 | ARCHITECTURAL | rule engine لسياسات موافقة مصروفات مركبة. |
| #359 | PARTIAL | إكمال الربط العكسي بين المصروف والمشروع في التقارير/workflows. |
| T1.3b | FIXED | DB trigger يمنع UPDATE المباشر على `treasury_accounts.current_balance` خارج المسار الرسمي (GL). _(022: trigger + `aman.gl_context` GUC)_ |
| #177 | ARCHITECTURAL | توحيد علاقة `treasury_transactions` و`journal_entries` و`cash_movements` أو توثيق حدودها بعقد واضح. |
| #178 | ARCHITECTURAL | تحويل `company_settings.setting_value` إلى typed/JSONB model تدريجي. |
| #179 | ARCHITECTURAL | استبدال `tax_groups.tax_ids JSONB` بجدول junction. |
| #269 / #219 / #463 | FIXED | استبدال account-code ranges الصلبة بتصنيف حسابات configurable. _(022: `account_classifications` table + classifier-first lookup)_ |
| #322 / #465 | FIXED | سياسة audit موحدة لمشاهدة التقارير المالية. _(022: `require_sensitive_permission` on reports)_ |

### خطة الإصلاح
1. إصلاح reconciliation finalize لأنه أعلى أثر مالي.
2. توحيد source/casing وعقد JE return في مسارات صغيرة قابلة للتحقق.
3. تصميم account classification table، ثم نقل التقارير المالية عليه تدريجيًا.
4. ترحيل settings/tax schema في migrations مستقلة مع backfill.

---

## R3 — Sales, POS, CRM, ZATCA

### الهدف
إكمال دورة البيع من الفرصة حتى الفاتورة، وتحسين POS/ZATCA offline دون كسر المسارات الحالية.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #149 | TODO | endpoint Order → Invoice مع نسخ السطور وGL/ZATCA. |
| #152 | TODO | إشعار عند تعيين فرصة. |
| #154 | ARCHITECTURAL | ربط تحويل الفرصة بمندوب العمولة وقواعد commissions. |
| #284 | TODO | `SalesOrder.converted_to_invoice_id` + migration. |
| #285 | PARTIAL | تحسين sales velocity بدل `updated_at-created_at`. |
| #286 | TODO | formula قياسية لمعدل التحويل funnel-stage. |
| #287 | PARTIAL | pagination/filters لأنشطة CRM. |
| #289 | TODO | ربط sales forecast بـ cash-flow forecast عبر expected close. |
| #293 | PARTIAL | فحص inventory كامل قبل cancel reversal. |
| #294 | PARTIAL | توحيد cancellation JE reference إلى source/source_id. |
| #297 / #476 | PARTIAL | توحيد جداول sales_returns وpos_returns فعليًا بعد `returns_unified`. |
| #298 | PARTIAL | إنهاء توحيد `acc_map_sales` و`acc_map_sales_rev`. |
| #391 | TODO | إزالة تكرار `get_acc_id(code)` لصالح helper مركزي. |
| #392 | ARCHITECTURAL | state machine لدورة الفاتورة. |
| #393 | ARCHITECTURAL | POS multi-session inventory lock/distributed stock lock. |
| #419l | TODO | تحسين UBL XML builder لاعتماد ZATCA. |
| #86 | TODO | `zatca_outbox` + retry worker للفواتير offline. |
| #88 / #382 | TODO | XML signing لمسار einvoicing offline واستبدال signer الخارجي بـ inline signing موثوق. |
| #181 / #181b / #181c / #272k | TODO | POS offline/local stock guard، وفحص مخزون POS الكامل، وBulk INSERT sweep للمسارات المتبقية. |

### خطة الإصلاح
1. تنفيذ Order→Invoice وربط `converted_to_invoice_id`.
2. بناء invoice lifecycle state machine قبل توسيع الإلغاء/المرتجع.
3. تنفيذ ZATCA outbox + XML signing كمسار متكامل.
4. توحيد returns ماديًا بعد تثبيت compatibility view.

---

## R4 — Inventory, Costing, Manufacturing

### الهدف
جعل تكلفة المخزون والتصنيع متسقة على مستوى المستودع والمنتج وأمر الإنتاج.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #452 | ARCHITECTURAL | استكمال WAC/costing per warehouse في التصنيع والمخزون بعد الإغلاقات الموضعية. |
| #498 | PARTIAL | Decimal sweep في التحويلات/الشحنات/schemas. |
| #251 / #493 | TODO | تنفيذ auto-reorder end-to-end. |
| #272h | TODO | تجميع `FOR UPDATE` في مرتجع المشتريات بدل حلقة N queries. |
| #272r | TODO | تحذير/معالجة المستودعات ذات الرصيد السالب في WAC. |
| #397 | TODO | تفعيل webhook `inventory.low_stock`. |
| #398 | TODO | cancel restock max bounds. |
| #333 | TODO | تعطيل endpoints مهملة بـ 410 Gone. |
| #334 | PARTIAL | إزالة تكرار فحص inventory. |
| #399 | PARTIAL | إنهاء ازدواج `/transfers` و`/transfer`. |
| #419o | PARTIAL | استكمال أرشفة `inventory_transactions` وربطها بسياسة retention. |
| #419v / #272n | PARTIAL/TODO | إدخال lead time + safety stock في MRP. |
| #272o / #207 | TODO | تحويل توصيات MRP إلى purchase planning/PO. |
| #272p / #203 / #448 | ARCHITECTURAL | Multi-level BOM / Net Requirements Planning. |
| #200 | TODO | إعادة تقييم WIP عند الإنهاء بحسب التكلفة الفعلية. |
| #201 / #202 | TODO | confirm/approval workflow لأوامر الإنتاج الكبيرة. |
| #203 | TODO | overhead بحسب workstation. |
| #204 / #208 | TODO | waste/scrap tracking وQC gate policy. |
| #446 | TODO | business rule لـ `yield_quantity` عند completion. |
| #449 | TODO | partial production completion. |
| #450 | TODO | by-product cost allocation. |
| #272l | TODO | فرض/تحذير عند غياب labor/overhead mappings. |
| #272m | TODO | دعم operations اختيارية في routing. |
| #272q | TODO | إصلاح حساب `existing_qty` الهش. |
| #314 | TODO | ربط shop floor بالحضور. |

### خطة الإصلاح
1. تثبيت costing model: WAC per warehouse + Decimal boundary rules.
2. إصلاح المرتجعات/التحويلات منخفضة المخاطر.
3. توسيع MRP تدريجيًا: safety stock، multi-level BOM، ثم PO generation.
4. تنفيذ production completion الجزئي وQC/by-product بعد استقرار التكلفة.

---

## R5 — HR, Payroll, PII

### الهدف
إكمال سلامة الرواتب وحماية بيانات الموظفين.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #434 | TODO | التحقق النهائي من أن كل مسارات HR التي تعرض salary/IBAN تمر عبر `hr.pii` أو masking، بعد إغلاق false-positive #190. |
| #192 | TODO | منع payroll overlap بفهرس/قاعدة workflow. |
| #193 | TODO | تسجيل شيكات/تحويلات الرواتب في `bank_transactions`. |
| #429 | PARTIAL | توصيل field encryption فعليًا لحقول salary/IBAN الحساسة. |
| #435 | ARCHITECTURAL | workflow عكس/إبطال فترة رواتب مع عكس GL وWPS. |
| #436 | TODO | bulk salary increment API مع اعتماد وسجل تدقيق. |
| #419 | PARTIAL | إنهاء mismatch المتبقي حول `payroll_entries.period_id` بين DDL/ORM للجداول القديمة. |
| #419c | PARTIAL | ربط payroll subscription و`date.today()` بسياسة company timezone. |
| #305 | PARTIAL | bank code hardcoded في WPS/HR. |
| #308 | TODO | unique constraint لتكرار payslip. |
| #373 | TODO | ربط attendance ↔ timetracking. |
| #374 | TODO | حساب ticket allowance. |
| #376 | PARTIAL | تحسين payslip printable header/logo. |
| #419g | TODO | تقسيم `acc_map_loans_adv` إلى debit/credit mappings. |
| #419i | PARTIAL | سياسة أدق من تقريب 365.25 لسنوات الخدمة. |

### خطة الإصلاح
1. حماية PII في API responses والتشفير أولًا.
2. إغلاق GOSI/hazard وpayroll overlap قبل أي توسع رواتب.
3. تنفيذ payroll reversal بعد توحيد عقد JE.
4. تحسينات WPS/payslip والبدلات بعد سلامة الحسابات.

---

## R6 — FSM, DMS, Notifications

### الهدف
استكمال الخدمة الميدانية والمستندات والتنبيهات كمنظومة تشغيل لا مجرد endpoints.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #213 / #214 / #424 | ARCHITECTURAL | service pricing/contract coverage/margin model. |
| #217 / #426 | TODO | technician profile للمهارات والمناطق والتوفر. |
| #423 / #272y | TODO | preventive maintenance scheduler من assets/contracts. |
| #427 / #370 / #371 | ARCHITECTURAL | توحيد asset/service/shopfloor maintenance. |
| #316 | TODO | ربط فاتورة عقد الخدمة بطلب الخدمة. |
| #367 | TODO | renew() يولد طلبات متكررة. |
| #368 | TODO | generate_contract_invoice ينشئ service orders. |
| #372 | PARTIAL | استخدام `equipment.next_maintenance_date`. |
| #272v | TODO | نموذج عقود خدمة متخصص. |
| #272w | TODO | بوابة تحذير/اعتماد عند خدمة بإيراد صفري وتكلفة موجبة. |
| #169 / #87 | OPS | anti-malware scan عبر ClamAV أو خدمة سحابية. |
| #171 / #171b / #299d | TODO | storage quota per tenant/user + scheduler cleanup. |
| #299 | TODO | streaming MIME/signature validator. |
| #357 | ARCHITECTURAL | تحويل related_module/id إلى FK أو relation model. |
| #358 | PARTIAL | إنهاء storage path runtime/config cleanup. |
| #90 / #91 / #231 / #456 | TODO | notification retry/dedup/idempotency لجميع القنوات. |
| #327 / #328 | TODO | استخدام `email_templates` table بدل templates ثابتة. |
| #329 | PARTIAL | توسيع DLQ للإشعارات. |
| #443 / #229 | PARTIAL/TODO | queue مركزي للبريد المباشر بدل send-once. |
| #237 | TODO | signed approval-action tokens. |

### خطة الإصلاح
1. تصميم service pricing + contracts model لأن عدة بنود تعتمد عليه.
2. تنفيذ DMS quota/anti-malware كمسار مستقل قابل للتشغيل.
3. بناء notification queue موحد، ثم نقل email/SMS/push/in-app عليه.
4. preventive maintenance بعد توحيد models الأساسية.

---

## R7 — Reports, Search, Dashboard

### الهدف
تحويل التقارير والبحث من “تعمل” إلى “تعمل بسرعة وبشكل قابل للتوسع”.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #116 | TODO | ربط widgets static بـ reactive bindings وWS events. |
| #117 | TODO | تقليل استدعاءات `calculate_period_stats` عبر MV/cache warm-up. |
| #118 | TODO | MVs للرسم المالي اليومي. |
| #119 | TODO | ربط KPI alerts بالمجدول والتنبيهات. |
| #145 | ARCHITECTURAL | سياسة إنتاجية عند فشل Redis بدل fallback صامت إلى MemoryCache متباين بين العمال. |
| #147 | TODO | cache warm-up للـ queries المهمة عند الإقلاع أو بعد refresh. |
| #270 | TODO | metadata للكاش (`X-Cache-Hit`, `X-Cache-TTL`). |
| #345 / #346 | PARTIAL/TODO | إصلاح exchange-rate static في dashboard widgets. |
| #349 | OPEN | تحسين استعلام low_stock عبر EXPLAIN وخطة جديدة. |
| #354 | PARTIAL | مراجعة حذف cache key المتكرر في `chart_of_accounts` وباقي callsites. |
| #272c | TODO | scoped invalidation لكاش `role_dashboards` بدل mass-evict لكل اللوحات. |
| #318 | TODO | refactor balance-sheet sign logic. |
| #319 | TODO | Redis-backed report cache. |
| #321 / #405 | PARTIAL | إزالة type coercion في rollup. |
| #403 | OPEN | income statement لا يضم header rows. |
| #404 | PARTIAL | trial balance tolerance policy. |
| #419r | TODO | KPI dashboard يستخدم account_type sign. |
| #272z | TODO | إصلاح توزيع الرصيد الافتتاحي في ميزان المراجعة للحسابات ذات الرصيد العكسي. |
| #301 | TODO | BRIN indexes للجداول الزمنية الكبيرة بعد قياس EXPLAIN. |
| #302 | ARCHITECTURAL | partitioning لـ `audit_logs`/`journal_lines` ضمن خطة retention والأداء. |
| #461 / #220 | ARCHITECTURAL | report MVs/cache/indexing بعد قياس EXPLAIN. |
| #462 | TODO | فهارس مركبة لتقارير journal/account/date. |
| #221 | TODO | تحسين batching/cache لمسارات المقارنة. |
| #239 / #482 / #483 | TODO | ربط GlobalSearch UI بالـ backend unified search وتجربة cross-entity. |
| #331 | TODO | autocomplete أثناء الكتابة. |
| #395 | TODO | GlobalSearch page metadata بدل قائمة static. |
| #503 | PARTIAL | استكمال نضج البحث UX/observability وربط الشاشات. |
| #324 / #325 | PARTIAL/TODO | unified health/metrics لكل adapters. |
| #419u | PARTIAL | إكمال OpenAPI descriptions. |

### خطة الإصلاح
1. البدء بالتقارير عالية الكلفة: EXPLAIN + indexes/MV.
2. توحيد account classification لأن التقارير وKPI تعتمد عليه.
3. ربط GlobalSearch UI بالـ API الحالي.
4. تحسين observability والـ cache metadata.

---

## R8 — Frontend, Architecture, Ops Cleanup

### الهدف
تقليل الدين التقني الكبير، ثم تنظيف ملفات التدقيق القديمة بعد اعتماد المصدر الجديد.

### البنود المتبقية

| Ref | الحالة | المطلوب |
|---|---|---|
| #257 | TODO | sweep لتحويل `.toFixed(2)` و`parseFloat` إلى `formatNumber()`. |
| #258 | TODO | locale defaults endpoint وربط Register/Onboarding/Branches. |
| #259 | TODO | `useExchangeRate` hook بدل `exchange_rate: 1.0`. |
| #260 | TODO | استبدال `window.location` بـ router navigation. |
| #261 | TODO | `useDebounce` لحقول البحث. |
| #262 | ARCHITECTURAL | `useApi` hook migration بدل fetchData/setLoading المكرر. |
| #263 | TODO | error handler مركزي بدل catch صامت. |
| #265 | TODO | Vite/CSS splitting. |
| #266 | TODO | تفكيك barrel exports لاستعادة tree-shaking. |
| #268 | TODO | `:focus-visible` rings على primitives. |
| #270 | TODO | alt sweep للصور والأيقونات. |
| #271 | TODO | React.lazy/code splitting للمكونات الثقيلة. |
| #272 / #343/#365 | TODO | تفعيل StrictMode بعد إصلاح warnings. |
| #339 | TODO | mobile table strategy. |
| #341 / #361 / #366 | PARTIAL | استكمال ترحيل الصفحات إلى useApi/cleanup آمن. |
| #342 | TODO | semantic forms refactor. |
| #362 | TODO | ErrorBoundary يستخدم router navigation ويحافظ على state. |
| #363 | PARTIAL | thermal printer styles داخل print media. |
| #419n | PARTIAL | استكمال i18n للأخطاء التي ما زالت بالعربية فقط وربطها بنظام الترجمة. |
| #176 | PARTIAL | Party model unification phase 2. |
| #138 | PARTIAL | مراجعة `misfire_grace_time` لباقي المهام الطويلة بعد إغلاق المهام الشهرية. |
| #140 | ARCHITECTURAL | idempotency keys إضافية للمهام الحرجة كطبقة دفاع فوق SQLAlchemyJobStore. |
| #143 | OPS | supervisor/restart policy للـ worker خارج كود التطبيق. |
| #278 | TODO | UI/endpoint لمراقبة jobs وحالاتها. |
| #279 | TODO | استخدام company timezone في scheduled tasks حيث يلزم. |
| #419b | CLEANUP | إزالة/دمج جدول أو router التقارير المجدولة المكرر بعد تأكيد المسار المستخدم. |
| #272i | OPS | restore API/playbook آمن لاستعادة النسخ الاحتياطية مع صلاحيات وتدقيق. |
| #180 / #500 | OPS/PARTIAL | نشر backup automation via systemd timer/k8s CronJob. |
| #489 / #490 / #409 / #410 / #411 / #412 / #414 | ARCHITECTURAL | refactor routers إلى services/repositories/DTOs وتقليل f-string SQL pattern. |
| #499 | OPS | CI/CD/deployment gates/playbooks لرفع maturity. |

### خطة الإصلاح
1. تنفيذ frontend utility sweeps ذات المخاطر المنخفضة أولًا: format/debounce/navigation/error handler.
2. ترحيل useApi تدريجيًا حسب أكثر الصفحات استخدامًا.
3. refactor backend architecture تدريجيًا حسب routers الأعلى تغييرًا.
4. تنفيذ backup automation وCI gates بعد استقرار خطة الملفات.

---

## تحقق التغطية 2026-05-02

تمت مراجعة مصادر التدقيق التالية مقابل هذا الملف: `TODO.md`, `P3_BACKLOG.md`, `P2_OPEN_TASKS.md`, `CONSOLIDATED_AUDIT_REPORT.md`، والتقارير الفردية داخل `docs/audit` عبر البنود المرقمة التي دُمجت في #420–#512 وملحقات #272*.

القاعدة المعتمدة هنا: آخر حالة في `TODO.md` تتقدم على التقارير القديمة. لذلك لم تُنقل بنود ظهرت في التقارير الفردية أو `P3_BACKLOG.md` لكنها أُغلقت لاحقًا في B28–B41 مثل #121/#122/#125، #186، #190، #205/#209/#210/#246/#247، #256، #272b/#272d/#272e/#272f/#272g/#272j، و#438–#440 عندما ثبت أنها FIXED/INVALID أو صار الجزء المفتوح ممثلًا برقم آخر مثل #257.

البنود التي كانت ناقصة بعد أول إنشاء للخطة وأُضيفت في هذه المراجعة تشمل: #136، #275، #278/#279، #301/#302، #310–#312، #354، #419/#419b/#419c/#419n/#419o/#419p، #272c/#272i/#272z، #195–#197، #181/#181b، و#382، وT1.3b (DB trigger خزينة — أُضيف 2026-05-02 بعد التحقق من انتهاء فترة المراقبة ونجاح #110g).

---

## سياسة حذف ملفات `docs/audit/`

### المبدأ
يمكن حذف أي ملف من مجلد `docs/audit/`، ما عدا هذا الملف، بعد استيفاء الشرطين التاليين معًا، لا أحدهما فقط:

| الشرط | المعنى العملي |
|---|---|
| جميع البنود منتهية | كل بند في الملف حالته `FIXED` أو `INVALID` أو `wont-fix`، ولا يوجد أي بند `TODO` أو `PARTIAL` أو `scheduled` أو `open` ما زال يحتاج تنفيذًا. |
| البنود المنجزة منقولة | كل بند أُغلق تم توثيقه في `TODO.md`، وكل بند متبقٍ موجود في هذا الملف. |

لا يكفي أن تكون البنود منتهية إذا لم يُنقل سجلها، ولا يكفي أن تكون منقولة إذا بقيت بنود مفتوحة في الملف الأصلي.

### الملف الوحيد المستثنى من الحذف

| الملف | السياسة |
|---|---|
| `REMAINING_REMEDIATION_PLAN.md` | لا يُحذف. يبقى مصدر الحقيقة الدائم للبنود المتبقية وسياسات الإغلاق والتنظيف. |

### قاعدة ما بعد تنظيف الملفات

بعد نقل سجلات الملفات القديمة إلى `TODO.md` وحذف التقارير الفردية والتراكرات الوسيطة، لم يعد `CONSOLIDATED_AUDIT_REPORT.md` مصدرًا باقيًا داخل `docs/audit/`. مصدر الإغلاق هو `TODO.md`، ومصدر البنود المتبقية هو هذا الملف.

### طريقة تقييم أي ملف قبل الحذف

| خطوة | المطلوب |
|---|---|
| 1 | فحص الملف بحثًا عن أي حالة مفتوحة: `TODO`, `PARTIAL`, `scheduled`, `open`, أو صياغة تدل أن البند لم ينته. |
| 2 | مطابقة كل بند مغلق مع سجل إغلاق موجود في `TODO.md`. |
| 3 | إذا وُجد بند مفتوح، يُنقل إلى هذا الملف بدل حذف الملف المصدر. |
| 4 | إذا وُجد بند مغلق بلا سجل إغلاق، يُضاف سجل إغلاقه قبل الحذف. |
| 5 | بعد اكتمال الشرطين، يمكن حذف الملف أو أرشفته حسب قرار المستخدم. |

### تطبيق السياسة على الملفات الحالية

بعد تنفيذ تنظيف 2026-05-02، الملفات الوحيدة التي تبقى في `docs/audit/` هي `TODO.md` و`REMAINING_REMEDIATION_PLAN.md`. أي ملف تدقيق جديد يُنشأ لاحقًا يخضع للقاعدة نفسها: يغلق أو ينقل إلى `TODO.md`/هذه الخطة قبل الحذف.

---

## معيار إغلاق أي بند من الآن فصاعدًا

لكي نغلق بندًا من هذا الملف:

1. نتحقق من الادعاء في الكود الحالي.
2. إن كان مغلقًا سابقًا: نحذفه من هذا الملف ونضيفه في سجل موجز داخل `TODO.md` أو changelog جديد.
3. إن احتاج إصلاحًا: نطبق إصلاحًا محدودًا ونوثّق الملفات المتأثرة.
4. نستخدم فقط تحقق غير اختباري ما لم يطلب المستخدم تشغيل tests: diagnostics، `py_compile`، `git diff --check`، وفحوص syntax/build غير test عند الحاجة.
5. لا نعيد فتح ملفات audit الفردية إلا عند الحاجة لسياق تاريخي.

---

## الدفعة التالية المقترحة

أفضل بداية بعد التوحيد هي R1/R2 لأنها تقلل المخاطر العامة قبل الميزات:

1. R1-01: إصلاح `log_activity` atomicity (#133).
2. R1-02: PII sanitizer موحد للـ audit body/details (#352).
3. R2-01: تحقق GL الفعلي عند finalize reconciliation (#419x/#272u).
4. R2-02: توحيد JE return contract (#191) إن كان مطلوبًا لإصلاحات payroll/treasury.
5. R5-01: حجب salary/IBAN عن `hr.view` وربط `hr.pii` (#190/#434).

هذه بداية عملية لأنها تضرب مخاطر سلامة البيانات قبل تحسينات الأداء والواجهة.