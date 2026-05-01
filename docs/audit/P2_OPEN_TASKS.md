# P2 Open Tasks — Uncovered Audit Items

> **Generated**: 2026-05-01 — extracted from `CONSOLIDATED_AUDIT_REPORT.md`
> **Scope**: P2 (medium-priority) audit items not explicitly mapped to a TODO Tx.x task
> and not classified in P3_BACKLOG.md. These are scheduled for **Phase 10** remediation.

**Total**: 135 P2 items + supplementary findings from individual reports (#420–#512).

---

## Accounting (9 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 120 | ``utils/accounting.py`` | 50-51 | استخدام جمع `float` مباشر `sum(l.get("debit", 0))` بدل `Decimal` — يُعرّض لخطأ الفاصلة العائمة | [open] |
| 121 | ``purchases.py`` | 1276-1284 | استدعاء `compute_invoice_totals` بدون تمرير `markup_amount` و `header_discount_pct` — خصم رأسي أو هامش ربح في فاتورة مشتريات لن يُحتسب | [open] |
| 122 | ``accounting.py`` | 1426-1431 | `close_fiscal_year` يغلق `fiscal_periods.is_closed` لكنه لا يُحدِّث `fiscal_period_locks.is_locked` — تناقض بين الجدولين | [open] |
| 123 | ``gl_service.py`` | 168 | العملة الأساسية الافتراضية `SYP` عند فقدان الإعدادات — غير متسقة مع الزرع الافتراضي SAR | [open] |
| 124 | ``utils/accounting.py`` | 131 | نفس السقوط إلى `SYP` في `get_base_currency` | [open] |
| 125 | ``industry_coa_templates.py`` | 60, 77 | مفاتيح ربط VAT (`acc_map_vat_in`, `acc_map_vat_out`) لا تُسجل تلقائيًا في `company_settings` عند زراعة COA | [open] |
| 126 | ``invoices.py`` | 520-602 | فاتورة مبيعات → قيد تلقائي. الخلل الوحيد: markup غير متوازن (انظر P1 #15) | [open] |
| 127 | ``fiscal_lock.py` + `gl_service.py`` | - | نظاما قفل متوازيان لنفس الغرض دون تنسيق | [open] |
| 128 | ``accounting.py`` | 598 | استيراد مكرر لـ `gl_create_journal_entry` داخل الدالة مع وجود استيراد على مستوى الموديول | [open] |

## Audit Trail (7 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 129 | ``database.py`` | 6713-6741 | القيود المحاسبية محمية بـ `trg_je_immutable` لكن سجلات التدقيق غير محمية. الحارس ليس لديه حارس | [open] |
| 131 | ``permissions.py`` | 612-621 | `log_permission_denied` و `log_permission_change` ينفذان `INSERT INTO audit_logs` مباشرة بدون `log_activity` | [open] |
| 132 | ``crm.py:266`, `expenses.py:557-562`, `gl_service.py:277-285`` | - | تفاصيل التغيير عشوائية: أحيانًا أسماء الحقول فقط، أحيانًا القيم الجديدة فقط. لا نمط موحد old/new | [open] |
| 133 | ``audit.py`` | 77 | كل `log_activity` ينفذ `commit()` مستقل — خطر تناقض معاملاتي | [open] |
| 134 | `-` | - | لا كتابة غير متزامنة للتدقيق: لا `@background`، لا message queue، لا outbox pattern لسجلات التدقيق | [open] |
| 135 | `-` | - | **لا يوجد كشف لتسجيل الدخول من موقع جغرافي مختلف** (Impossible Travel) | [open] |
| 136 | `-` | - | **التوقيت من خادم التطبيق** وليس `CURRENT_TIMESTAMP` من قاعدة البيانات — قابل للتلاعب بساعة الخادم | [open] |

## Background Jobs (6 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 138 | ``scheduler.py`` | 493-504 | جميع المهام تستخدم `misfire_grace_time=60`. مهمة شهرية لها 300 ثانية فقط من السماح — إذا كان الخادم مشغولاً 5 دقائق، الدورة الشهرية تفوّت | [open] |
| 139 | ``scheduler.py`` | 108-115 | `check_scheduled_reports` — سباق عند تحديث `next_run_at` بدون `FOR UPDATE` | [open] |
| 140 | `-` | - | المهام 1-4, 8 ليس لديها `idempotency_key`. `max_instances=1` يحمي داخل نفس العملية فقط، وليس عبر العمال | [open] |
| 141 | `-` | - | تعدد العمال × `max_instances=1`: 4 عمال = 4 مثيلات من نفس المهمة تعمل في نفس الوقت في وضع `in_process` | [open] |
| 142 | ``outbox_relay.py`` | 85-97 | بعد `MAX_ATTEMPTS=10`، صفوف outbox تُترك بدون `delivered_at` ولا status خاص. لا يمكن التمييز بين "سينعالج" و"مهمل" | [open] |
| 143 | `-` | - | لا supervisor للـ worker المخصص: إذا مات (OOM, segfault) لا أحد يعرف | [open] |

## CRM (7 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 149 | ``invoices.py`` | - | **لا يوجد رابط تلقائي من طلب البيع إلى الفاتورة**: لا `Order → Invoice Conversion` endpoint | [open] |
| 150 | ``crm.py`` | - | **لا يوجد endpoint لتحديث حالة نشاط** (تسجيل الاكتمال). الأنشطة تُنشأ فقط ولا تُحدَّث | [open] |
| 151 | ``crm.py`` | 55-59 | نموذج `ActivityCreate` ينقصه حقول: `outcome`, `duration`, `is_completed` | [open] |
| 152 | `-` | - | **لا يوجد إشعار عند تعيين فرصة لمندوب جديد**. بينما يوجد إشعار عند تعيين تذكرة دعم | [open] |
| 153 | ``sales_improvements.py`` | 37-80 | تحويل عرض السعر → طلب لا يتحقق من الحد الائتماني قبل التحويل | [open] |
| 154 | ``sales_rfq.py`` | 47-63 | تحويل الفرصة لا يُسجِّل المندوب تلقائيًا في العمولة. يجب ربط `assigned_to` بحقل `salesperson_id` في العمولة | [open] |
| 155 | `-` | - | التذكيرات (Reminders) غير مفعلة: `due_date` موجود في الأنشطة لكن لا يُستخدم تشغيليًا | [open] |

## Cache (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 144 | `جميع التقارير + الداشبورد` | - | الإبطال الشامل يجعل الكاش عديم الفائدة في البيئات النشطة: 90% من طلبات التقارير cache miss | [open] |
| 145 | ``cache.py`` | 116-119 | إذا فشل Redis، النظام يقع على `MemoryCache`. في الإنتاج، كل عامل لديه حالة كاش مختلفة تمامًا | [open] |
| 146 | ``cache.py`` | 27-61 | `MemoryCache` قواميس Python بدون حد أقصى. في وضع fallback، سينمو بلا حدود حتى Out of Memory | [open] |
| 147 | `-` | - | لا توجد تدفئة (Warm-up): عند بدء التشغيل، أول مستخدم يتحمل كامل وقت الحساب | [open] |
| 148 | ``scheduler.py`` | 492-505 | المجدول يحدث `mv_*` كل 15 دقيقة لكنه لا يُبطل أي كاش API. بيانات قديمة إضافية فوق الـ 15 دقيقة | [open] |

## DMS (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 166 | ``sql_safety.py`` | 173-201 | **هجوم الامتداد المزدوج (Double Extension) غير مكشوف**: `os.path.splitext("file.php.pdf")` يُرجع `.pdf`. المهاجم يمكنه رفع `shell.php.pdf` | [open] |
| 168 | `-` | - | **لا يوجد سجل تدقيق لتحميل الملفات (Download Audit Log)**: لا يُسجل من حمّل أي مستند ومتى | [open] |
| 169 | `-` | - | **لا يوجد فحص فيروسات (Anti-Malware Scan)**: لا ClamAV ولا VirusTotal | [open] |
| 170 | ``services.py`` | 287-306, 739-760 | حذف طلب الخدمة لا يمس المستندات المرتبطة. حذف المستند (soft delete) لا ينظف الإصدارات | [open] |
| 171 | `-` | - | لا يوجد حد أقصى لحجم الطلب على مستوى الخادم. لا Quota تخزين للمستخدمين | [open] |

## Dashboard (10 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 111 | ``dashboard.py`` | 309-311 | الرسم البياني المالي: `profit = s - e` لا يشمل COGS. تسمية "أرباح" مضللة (يجب تسميتها `gross_profit`) | [open] |
| 112 | ``dashboard.py`` | 180-188 | الرصيد النقدي يُحسب مرتين مختلفتين: من `accounts.balance` ومن `treasury_accounts JOIN accounts`. الرقمان قد يختلفان | [open] |
| 113 | ``dashboard.py`` | 134-141 | عند عدم تحديد تاريخ، المصروفات = `SUM(balance)` بدون إشارة سالبة. إذا كان هناك مصروفات بإشارات مختلفة، النتيجة خاطئة | [open] |
| 114 | ``dashboard.py`` | 229 | `cash_status = "Stable"` ما دام الرصيد > 0. حتى لو الرصيد 1 ريال والمصروفات الشهرية 100,000 | [open] |
| 115 | ``dashboard.py`` | 170-178 | `calc_change` مقصوص عند ±999%. المدير لا يرى قفزات كبيرة | [open] |
| 116 | ``dashboard.py`` | 740-790, 793-877 | `widget_low_stock` و `widget_pending_tasks` قوائم ساكنة — لا إشعارات نشطة | [open] |
| 117 | ``dashboard.py`` | 80-163 | دالة `calculate_period_stats` تُستدعى 3 مرات، كل استدعاء 3-4 استعلامات. المجموع ≈ 10-12 استعلامًا | [open] |
| 118 | ``dashboard.py`` | 259-298 | الرسم البياني المالي: استعلامان ثقيلان (UNION + treasury_transactions). لا تجميع مسبق أو MV | [open] |
| 119 | ``kpi_service.py`` | 1429-1606 | `_build_executive_alerts()` و `_build_financial_alerts()` قادرة على كشف المشاكل لكنها غير مربوطة بأي مجدول أو إشعار | [open] |
| 269 | ``dashboard.py`` | 1008-1016 | النسب المالية مرتبطة بترقيم صلب (`510%`, `410%`) — إذا استخدم العميل ترقيمًا مختلفًا النسبة = 0 | [open] |

## Database (10 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 172 | ``attendance`` | - | FK `employee_id -> employees(id)` بدون ON DELETE RESTRICT صريح | [open] |
| 173 | ``leave_requests`` | - | FK `employee_id -> employees(id)` بدون ON DELETE | [open] |
| 174 | ``payroll_entries`` | - | FK `employee_id -> employees(id)` بدون ON DELETE | [open] |
| 175 | `فهارس مفقودة` | - | `payroll_entries(employee_id, period_id)`, `attendance(date)` مستقل, `pos_orders(customer_id)` + `(order_date, status)`, `journal_lines(is_reconciled)` | [open] |
| 176 | `متعدد` | - | **أعمدة قديمة مكررة**: `customer_id` + `supplier_id` بجانب `party_id` في جداول invoices/quotations/orders | [open] |
| 177 | `متعدد` | - | **3 جداول لنفس الغرض**: `customer_transactions` + `supplier_transactions` + `party_transactions` | [open] |
| 178 | ``company_settings`` | - | `setting_value TEXT` — تخزين المفاتيح الرقمية (account IDs) كنصوص، مما يمنع FK والتحقق | [open] |
| 179 | ``tax_groups`` | - | `tax_ids JSONB DEFAULT '[]'` — مصفوفة JSON بدل جدول وسيط (many-to-many). لا FK أو INDEX على العناصر الفردية | [open] |
| 180 | `-` | - | **لا يوجد نسخ احتياطي تلقائي** — لا scheduler، لا cron job. لا سياسة استبقاء للملفات | [open] |
| 181 | ``returns.py:187-198`, `pos.py:491-525`` | - | INSERT فردي لكل سطر مرتجع ولكل سطر POS | [open] |

## Expenses (7 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 192 | ``expenses.py`` | 432-460 | فحص السياسات يُرجع `policy_warning` فقط — لا يمنع المصروف المخالف | [open] |
| 193 | ``expenses.py`` | 328-363 | `validate_expense_against_policy` لا تُستدعى تلقائيًا عند إنشاء المصروف | [open] |
| 194 | ``expenses.py`` | 445-460 | التحقق من الحد الشهري يفحص مجموع مصروفات الموظف فقط — لا يفحص الحد الشهري للقسم | [open] |
| 195 | ``accounting.py`` | 1978 | قالب متكرر بـ `auto_post=True` يُنشئ قيودًا مرحَّلة تلقائيًا بدون مراجعة بشرية | [open] |
| 196 | ``accounting.py`` | 1720-1973 | القوالب المتكررة تُنشئ قيودًا مباشرة لكنها لا تُنشئ سجلاً في جدول `expenses` — تقارير المصروفات لا تشملها | [open] |
| 197 | `-` | - | **لا يوجد ربط بين السلفة والمصروفات**: لا يمكن للموظف تقديم إيصالات لتسوية جزء من السلفة | [open] |
| 198 | ``expenses.py`` | 835-874 | لا واجهة للقيد العكسي (reversal) للمصروفات المعتمدة التي تحتاج تراجع | [open] |

## FSM (8 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 211 | ``services.py`` | 255-261 | الانتقال إلى `completed` لا يشترط وجود تكاليف مسجلة أو ساعات فعلية | [open] |
| 212 | ``schemas/services.py`` | 46-50 | نموذج `ServiceCostCreate` لا يحتوي على `product_id` أو `inventory_item_id` | [open] |
| 213 | ``governance.py`` | 987-1014 | فوترة الخدمة: `revenue_amount` من المستخدم مباشرة، لا تحتسب من التكاليف + هامش ربح | [open] |
| 214 | ``services.py`` | 360-406 | التكاليف تُحسب كـ `qty × unit_cost` — لا يوجد هامش ربح (markup) | [open] |
| 215 | `-` | - | **لا يوجد إشعار تلقائي عند خرق SLA**: فقط علامة `sla_breached` في الاستجابة بدون إشعار | [open] |
| 216 | ``services.py`` | 763-773 | قائمة الفنيين تُرجع كل المستخدمين النشطين بدون فلترة — لا دور "فني" متخصص | [open] |
| 217 | `-` | - | **لا يوجد نموذج "فني" مستقل**: لا مهارات، لا مناطق تغطية، لا جدول مواعيد، لا تتبع موقع GPS | [open] |
| 218 | ``governance.py`` | 234-277 | `scan_and_escalate_sla` يفحص طلبات الاعتماد فقط — ليس لأوامر الخدمة | [open] |

## Frontend (6 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 257 | `عدة صفحات` | - | استخدم متباين للتقريب: بعض الصفحات `formatNumber()` وأخرى `.toFixed(2)` مباشرة | [open] |
| 258 | `عدة صفحات` | - | قيم عملة ودول صلبة في 3+ أماكن (Register, Onboarding, Branches) بدل API الإعدادات | [open] |
| 260 | `99+ استخدام` | - | ملاحة `window.location` بدل `useNavigate()` — يفقد حالة التطبيق | [open] |
| 261 | `عدة صفحات` | - | عدم Debounce في حقول البحث — طلب API مع كل ضغطة مفتاح | [open] |
| 263 | `عدة صفحات` | - | `catch(console.error)` و `catch(() => {})` الصامت في عشرات الصفحات | [open] |
| 266 | ``utils/api.js`` | - | Barrel export يُبطل tree-shaking ويُحمّل كل الخدمات معًا | [open] |

## HR (10 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 182 | ``advanced.py`` | 269 | المضاعفات `1.5` و `2.0` صلبة رغم وجود جدول `overtime_rates_config` غير المستخدم | [open] |
| 183 | ``core.py`` | 841-850 | تجميع العمل الإضافي لا يتحقق من أن الطلب يقع ضمن فترة الرواتب — أي طلب معتمد من أي تاريخ يُضاف | [open] |
| 184 | ``core.py`` | 994-999 | حالة `'processed'` للعمل الإضافي غير مُعرّفة في قيم status enum | [open] |
| 185 | ``advanced.py`` | 323 | تناقض: GOSI صاحب العمل `11.75%` في الواجهة و `12.00%` في الحساب الفعلي | [open] |
| 186 | ``advanced.py`` | 385 | المخاطر المهنية (`occupational_hazard_percentage`) غير مُضمّنة في `generate_payroll` | [open] |
| 187 | ``core.py`` | 1820 | أجر أساس نهاية الخدمة يشمل `basic + housing + transport` بينما القانون ينص على الأجر الأساسي فقط | [open] |
| 188 | ``wps_compliance.py`` | 68-216 | صيغة WPS ملف CSV وليس SIF حقيقي (fixed-width). البنوك السعودية قد ترفضه | [open] |
| 189 | ``wps_compliance.py`` | 589 | حساب التسوية البنكي يستخدم `acc_map_cash` بدل `acc_map_bank` | [open] |
| 190 | ``core.py` (HR)` | 214-223 | `GET /employees/{id}` يعيد salary, IBAN لأي مستخدم `hr.view` بدون فلترة | [open] |
| 191 | ``wps_compliance.py`` | 563-594 | EOS settlement: `je_result` معامل كـ dict أو tuple — خطأ محتمل في unpacking | [open] |

## Integrations (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 224 | ``payments.py`` | - | توقيع webhook المدفوعات اختياري — إذا فشل `verify_webhook`، يتم تجاهل الحدث بصمت | [open] |
| 225 | `-` | - | لا يوجد استيراد تلقائي لـ MT940/CSV مع مطابقة المعاملات | [open] |
| 226 | `Swagger` | - | نقص `response_model` في بعض الـ endpoints — لا يظهر شكل response في Swagger | [open] |
| 227 | `جميع المحولات` | - | اعتماد API Keys/Secrets من `company_settings` مباشرة — إذا تسربت قاعدة البيانات تتسرب جميع المفاتيح | [open] |
| 229 | ``email_service.py`` | - | البريد الإلكتروني: لا retry على مستوى الإرسال | [open] |

## Manufacturing (12 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 199 | ``core.py`` | 1047 | خصم المخزون بدون قفل `FOR UPDATE` — سباق بيانات بين أمرين إنتاج | [open] |
| 200 | ``core.py`` | 598 | التكاليف العامة (overhead) مبسطة: 30% ثابت من العمالة — لا تعكس التكلفة الحقيقية | [open] |
| 201 | `-` | - | لا يوجد endpoint للاعتماد (`POST /orders/{id}/confirm`) للانتقال من draft إلى confirmed | [open] |
| 202 | ``core.py`` | 1164 | لا يوجد إنتاج جزئي — `produced_quantity = quantity` دائمًا | [open] |
| 203 | ``core.py`` | 1765 | MRP لمستوى واحد فقط — لا يتحقق من المكونات الفرعية (sub-assemblies) | [open] |
| 204 | ``core.py`` | 1189-1210 | المنتجات الثانوية (by-products) لا تُكلَّف — تُضاف للمخزون بدون تكلفة | [open] |
| 205 | ``core.py`` | 1312-1316 | WAC يحسب من جميع المستودعات وليس مستودع الوجهة فقط | [open] |
| 206 | ``core.py`` | 1106 | `total_material_cost` خارج النطاق في `log_activity` — سيسبب `NameError` إذا لم يوجد BOM | [open] |
| 207 | `-` | - | لا يوجد تخطيط سعة (capacity planning) آلي | [open] |
| 208 | `-` | - | لا يوجد فحص جودة إلزامي قبل إكمال الإنتاج | [open] |
| 209 | `-` | - | إنشاء أمر إنتاج بدون التحقق من صلاحية المستودع المصدر/الوجهة للفرع | [open] |
| 210 | ``shopfloor.py`` | 147 | بدء العملية لا يتحقق من صحة `work_order_id` مقابل `routing_operation_id` | [open] |

## Notifications (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 231 | ``scheduler.py`` | 348-361 | retry للبريد فقط — إشعارات in-app و push الفاشلة لا تُعاد محاولتها | [open] |
| 233 | ``notification_service.py`` | 186 | `_send_in_app` ينفذ `commit()` قبل WebSocket — إذا فشل الإرسال بعد الـ commit لا يمكن استرجاع الإشعار | [open] |
| 236 | `-` | - | **لا يوجد HTML Escaping** في أي قالب إيميل. كل المتغيرات تُحقن مباشرة | [open] |
| 237 | ``email_service.py`` | 165 | رابط الاعتماد `{approval_url}` بدون توقيع رقمي — لا HMAC للتحقق من عدم التلاعب | [open] |
| 238 | `-` | - | إعادة محاولة SMS الفاشلة غير موجودة — retry يغطي البريد فقط | [open] |

## Reports/BI (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 219 | ``reports.py`` | 2535-2629 | النسب المالية تعتمد على `account_number LIKE '11%'` لتحديد الأصول المتداولة. إذا لم يلتزم دليل الحسابات بهذا الترقيم، النسب خاطئة | [open] |
| 220 | ``reports.py`` | 1140-1144 | قائمة الدخل والميزانية تستخدمان `LEFT JOIN ... (je.id IS NULL OR ...)`. هذا يجبر مسحًا كاملًا للجدول | [open] |
| 221 | ``reports.py`` | 1968-2008 | مقارنة قائمة الدخل: استعلام منفصل لكل فترة. مع 5 فترات = 5 استعلامات كاملة | [open] |
| 222 | ``reports.py`` | 2328-2355 | `_build_comparison_table` تحتسب التغير لأول فترتين فقط — لا تشمل الفترات الإضافية | [open] |
| 223 | ``reports.py`` | 1550-1554 | تصنيف IAS 7: كل أصل لا يحتوي على كلمات محددة يُصنف "تشغيلي" — قد يشمل استثمارات طويلة الأجل | [open] |

## Search (6 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 239 | ``GlobalSearch.jsx`` | 20-276 | البحث الشامل (Ctrl+K) يعتمد على قائمة صفحات ثابتة في الكود. الصفحات الجديدة لا تظهر حتى recompile | [open] |
| 240 | ``parties.py`` | - | البحث في العملاء لا يحتوي على فلتر `branch_id` — قد يشمل عملاء من فروع أخرى | [open] |
| 241 | `-` | - | لا بحث موحد عبر الكيانات (Unified Search): لا يمكن البحث في العملاء + الموردين + الفواتير دفعة واحدة | [open] |
| 242 | `-` | - | لا ترتيب حسب الصلة (Relevance Ranking): نتائج ILIKE غير مرتبة حسب الأهمية | [open] |
| 243 | `-` | - | لا بحث في محتوى المستندات المرفوعة (PDF, Word, Excel) | [open] |
| 244 | `-` | - | البحث لا يُسجل في سجل التدقيق | [open] |

## Security (2 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 161 | ``stock_movements.py`` | 29 | صلاحية `stock.manage` واسعة جدًا للـ `/receipt` و `/delivery` — تسمح بالتلاعب بالمخزون دون قيد محاسبي | [open] |
| 162 | ``settings.py` / `company_settings`` | - | ZATCA private key + certificate + SMTP password مخزنة كنص واضح | [open] |

## Supply Chain (5 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 246 | ``adjustments.py`` | 193 | قيمة تسوية الجرد تستخدم `cost_price` من `products` وليس WAC المستودع الفعلي | [open] |
| 247 | ``transfers.py`` | 103 | حساب WAC في التحويلات يستخدم `float` مباشرة بدل `Decimal` | [open] |
| 249 | ``settings.py`` | 74, 77, 130 | **ثلاثة إعدادات مختلفة** للمخزون السلبي (`inventory_negative_stock`, `stock_negative_allowed`, `allow_negative_stock`) لا يقرأها أحد فعليًا | [open] |
| 250 | ``stock_movements.py`` | 87-90 | `POST /receipt` بدون `FOR UPDATE` — سباق بيانات محتمل عند استلام وشحن نفس المنتج | [open] |
| 251 | ``settings.py`` | 75 | `inventory_auto_reorder` إعداد بدون كود منفذ فعليًا | [open] |

## Treasury (3 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 253 | ``forecast_service.py`` | 118-133 | القيود الدورية تُؤخذ بقيمتها الكلية `total_amount` — لا تحلل سطور القيد لاستخراج الحسابات النقدية فقط | [open] |
| 254 | ``forecast_service.py`` | 72-93 | التنبؤ لا يشمل الشيكات المؤجلة في توقعات السيولة | [open] |
| 255 | ``expenses.py`` | 775-777 | اعتماد المصروف: لا `FOR UPDATE` على سجل المصروف نفسه — اعتماد مزدوج نظري | [open] |

## متعدد (2 items)

| # | الملف | السطر | التفصيل | الحالة |
|---|-------|-------|----------|--------|
| 267 | `-` | - | `invoice_type='sale'` خطأ إملائي في `dashboard.py:1046` — النتيجة دائمًا 0 (الصحيح `sales`) | [open] |
| 268 | `-` | - | الرابط `overdue=true` في dashboard معطل — لا يوجد فلتر `overdue` في صفحة الفواتير | [open] |

---

## Supplementary findings from individual report files (#420–#512)

These were discovered while scanning per-domain audit reports against the consolidated report.
Items already represented (e.g. duplicates of #182, #6, #7, #21 etc.) have been pruned.

| # | Source | File | Line | التفصيل | Status | Priority |
|---|--------|------|------|---------|--------|----------|
| 420 | FSM | service_requests | - | Optimistic lock disabled — `version` field exists but unused on update | [open] | P2
| 421 | FSM | service_requests | - | Service order completion accepted with zero costs/hours | [open] | P2
| 422 | FSM | service_request_costs | - | Parts not linked to inventory (no product_id) — no stock/GL impact | [open] | P1
| 423 | FSM | - | - | No preventive maintenance automation (no pm_schedules table or scheduler) | [open] | P1
| 424 | FSM | - | - | Service billing without pricing model (no service price list / hourly rate) | [open] | P1
| 425 | FSM | service_requests | - | No SLA enforcement — service requests have no response/resolution time targets | [open] | P1
| 426 | FSM | services/technicians | - | Technician profile missing skills/coverage areas — no specialist assignment | [open] | P2
| 427 | FSM | - | - | 3 disjoint maintenance systems (service/asset/manufacturing) — no unified interface | [open] | P2
| 428 | HR | OvertimeRequests.jsx | - | Hardcoded overtime multipliers (1.5/2.0) in frontend — requires redeploy to change | [open] | P1
| 429 | HR | field_encryption.py | - | AES-256-GCM defined but never called — salary/IBAN stored plaintext | [open] | P1
| 430 | HR | gosi calc | - | GOSI employer share discrepancy 11.75% (settings) vs 12.00% (payroll gen) | [open] | P2
| 431 | HR | payroll | - | Occupational hazard insurance not included in payroll generation | [open] | P2
| 432 | HR | payroll | - | No attendance-to-payroll integration — absences/lateness not deducted | [open] | P1
| 433 | HR | - | - | No work_policies table — cannot differentiate paid/unpaid leave or OT eligibility | [open] | P1
| 434 | HR | GET /employees/{id} | - | Salary/IBAN/bank_account exposed to hr.view without PII gate | [open] | P1
| 435 | HR | payroll | - | Payroll period reversal/undo not supported — committed errors require manual GL reversal | [open] | P2
| 436 | HR | - | - | No bulk salary increment API — annual raises = manual per-employee | [open] | P2
| 437 | HR | EOS | - | EOS provision not accrued periodically — only computed at separation | [open] | P2
| 438 | Integrations | bank_feeds | - | CAMT.053 (ISO 20022) parser missing — only legacy MT940 + CSV | [open] | P1
| 439 | Integrations | bank_feeds | - | MT940 parser exists but no auto-import + auto-match endpoint | [open] | P2
| 440 | Integrations | /api/docs | - | Docs unprotected in production — exposes full API schema | [open] | P2
| 441 | Integrations | payments | - | No retry on Stripe/Tap/PayTabs adapters — fail immediately | [open] | P2
| 442 | Integrations | sms | - | SMS gateway failures not retried — transient losses | [open] | P2
| 443 | Integrations | email | - | Email service has no retry — SMTP transient failures discard messages | [open] | P2
| 444 | Integrations | - | - | No circuit breaker for failing integrations — calls failed APIs indefinitely | [open] | P2
| 446 | Manufacturing | bom_outputs | - | yield_quantity field exists but never applied — assumes 100% yield | [open] | P1
| 447 | Manufacturing | core.py:1804-1809 | - | MRP "on order" reads purchase_invoices instead of purchase_orders | [open] | P1
| 448 | Manufacturing | mrp | - | MRP single-level — no sub-assembly BOM expansion | [open] | P2
| 449 | Manufacturing | production | - | No partial production completion — produced_qty always = order qty | [open] | P2
| 450 | Manufacturing | bom_outputs | - | By-products receive no cost allocation despite cost_allocation_percentage field | [open] | P2
| 451 | Manufacturing | alembic 0012 | - | Column naming conflict — adds columns already in database.py | [open] | P1
| 452 | Manufacturing | core.py:1312-1316 | - | WAC recalc sums all warehouses, not destination only | [open] | P2
| 454 | Notifications | - | - | No detection of infinite notification loops — recursive dispatch can spam | [open] | P1
| 455 | Notifications | - | - | No per-user notification rate limit — spam vulnerability | [open] | P1
| 456 | Notifications | _mark_delivery_failed | - | Retry only for email — SMS/push/in-app fail permanently | [open] | P2
| 457 | Notifications | email | - | Missing List-Unsubscribe header — CAN-SPAM/GDPR violation | [open] | P2
| 458 | Notifications | - | - | No SPF/DKIM/DMARC documentation — deliverability risk | [scheduled] | P3
| 459 | Notifications | - | - | No notification deduplication — duplicate sends on rapid events | [scheduled] | P3
| 460 | Reports/BI | horizontal analysis | - | O(n²) — 200 accounts × 3 periods = 600 separate queries | [open] | P1
| 461 | Reports/BI | balance sheet | - | LEFT JOIN journal_lines without date filter — full table scan | [open] | P1
| 462 | Reports/BI | - | - | Missing journal_lines(account_id, entry_date) index — all reports full scan | [open] | P2
| 463 | Reports/BI | financial ratios | - | Account numbers hardcoded (LIKE '11%') — silent breakage on COA changes | [open] | P2
| 464 | Reports/BI | cash flow | - | IAS 7 classification by name keywords — fragile, not configurable | [open] | P1
| 465 | Reports/BI | reports | - | No audit log for report access — SOC 2 / ISO 27001 gap | [scheduled] | P3
| 466 | Reports/BI | comparison | - | Multi-period comparison limited to 2 periods (change[0]-change[1]) | [open] | P2
| 467 | Sales/POS | invoices | - | No edit API for confirmed invoices — must delete+recreate | [open] | P1
| 470 | Sales/POS | pos_offline_inbox | - | Queued but no worker dequeues — orders stuck indefinitely | [open] | P1
| 471 | Sales/POS | offline mode | - | No conflict detection — prices/stock may change during offline window | [open] | P1
| 472 | Sales/POS | pos | - | Discount applied AFTER tax — violates ZATCA & IFRS rules | [open] | P2
| 473 | Sales/POS | promotions | - | Coupons not auto-applied — frontend must compute manually | [open] | P2
| 474 | Sales/POS | returns | - | No return policy window — returns accepted from invoices years old | [open] | P1
| 475 | Sales/POS | pos sessions | - | No optimistic locking on inventory across concurrent sessions | [open] | P2
| 476 | Sales/POS | sales_returns / pos_returns | - | Duplicate tables for returns — different schemas, logic duplication | [open] | P2
| 477 | Search | products | - | ILIKE %query% on 50K+ rows = sequential scan every time | [open] | P1
| 478 | Search | - | - | pg_trgm not enabled despite docs mention — no GIN indexes | [open] | P1
| 479 | Search | - | - | No fuzzy search or ranking — exact matches not prioritized | [open] | P1
| 480 | Search | - | - | No FTS — cannot search across multiple fields simultaneously | [open] | P1
| 481 | Search | DMS | - | Document content (PDFs/Word) not indexed — only title/tags | [open] | P2
| 482 | Search | UI | - | Browser search menu hardcoded ~270 pages — new pages need recompile | [open] | P2
| 483 | Search | - | - | No cross-entity unified search frontend — only per-module results | [open] | P2
| 487 | Security | - | - | require_sensitive_permission decorator defined but unused | [open] | P2
| 488 | Security | /notifications/send | - | No rate limit — users can spam notifications | [scheduled] | P3
| 489 | Security | core.py / purchases.py / accounting.py | - | God routers (3000+ lines) violate SRP | [open] | P2
| 490 | Security | architecture | - | No Repository Pattern — SQL access in routers, no test isolation | [open] | P2
| 491 | Supply | POST /receipt | - | No qty>0 validation — can accidentally decrease inventory | [open] | P1
| 492 | Supply | low stock alert | - | Doesn't subtract reserved_quantity — false low-stock alerts | [open] | P1
| 493 | Supply | inventory_auto_reorder | - | Setting exists but no PO-creation logic | [open] | P2
| 494 | Supply | stock APIs | - | /receipt /delivery /adjustment /adjustments — different logic & GL impact | [open] | P2
| 496 | Supply | shipment | - | FIFO/LIFO products arrive without cost layers — WAC fails | [open] | P2
| 497 | Supply | receipt | - | Missing FOR UPDATE lock — race condition with shipment | [open] | P2
| 498 | Supply | transfer WAC | - | Float arithmetic instead of Decimal — rounding errors | [open] | P2
| 499 | System Eval | - | - | System maturity Level 2-3 — lacks automation/monitoring/CI | [scheduled] | P2
| 500 | System Eval | - | - | No automated backup system — manual snapshots only | [open] | P2
| 501 | System Eval | - | - | No monitoring/alerting (no Sentry/APM/uptime) | [open] | P2
| 502 | System Eval | - | - | Scheduler has no supervisor — silent death on loop crash | [open] | P2
| 503 | System Eval | search | - | Search engine maturity 37/100 — breaks at 10K+ products | [open] | P1
| 504 | Treasury | treasury_accounts | - | current_balance dual-source with accounts.balance — divergence risk | [open] | P1
| 505 | Treasury | cheques | - | No auto-activation of post-dated cheques on maturity | [open] | P1
| 506 | Treasury | - | - | Petty cash fund model missing — no fund/replenishment/custodian | [open] | P1
| 507 | Treasury | expenses | - | Pending expenses delay GL — cash spent but books not updated | [open] | P1
| 508 | Treasury | treasury.py + expenses.py | - | Dual paths — different GL timing, inconsistent treatment | [open] | P2
| 509 | Treasury | reconciliation | - | auto_match not scheduled — must be manually triggered | [scheduled] | P3
| 510 | Treasury | reconciliation | - | Tolerance 0.01 hardcoded — no API/setting | [scheduled] | P3
| 511 | Treasury | reconciliation | - | auto_match missing FOR UPDATE locks — concurrent matches duplicate | [open] | P2
| 512 | Treasury | cash flow forecast | - | Excludes cheques, NR/NP, payroll obligations, contracts | [open] | P2
