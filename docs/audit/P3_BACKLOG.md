# P3 Backlog Tracker — Phase 9.1

> هذا الملف هو **التراكر المُجمَّع لبنود P3** (الأولوية المنخفضة) المستخرجة من
> `docs/audit/CONSOLIDATED_AUDIT_REPORT.md` ضمن النطاق `#270 – #419v`.
> آخر تحديث: 2026-05-01.
>
> **التصنيفات:**
> - `[scheduled]` — مُخطَّط له ضمن دورة لاحقة (Phase 10+).
> - `[wont-fix]`  — لن يُعالَج (مبرَّر بسبب ROI/سياسة/تصميم بديل).
> - `[partial]`   — عُولج جزئيًا في مراحل سابقة (T0–T8) لكن المتطلب الكامل لم يكتمل.
> - `[open]`      — مفتوح وبانتظار جدولة.

## ملخص الفئات

| الفئة | عدد البنود | scheduled | wont-fix | partial | open |
|---|---|---|---|---|---|
| Dashboard / Workspace | 8 | 3 | 2 | 1 | 2 |
| Audit Trail | 7 | 4 | 1 | 2 | 0 |
| Background Jobs | 5 | 3 | 0 | 1 | 1 |
| Cache (Redis/Memory) | 6 | 3 | 1 | 1 | 1 |
| CRM / Sales pipeline | 9 | 5 | 1 | 2 | 1 |
| Sales / POS | 14 | 7 | 2 | 4 | 1 |
| DMS (Documents) | 7 | 3 | 2 | 1 | 1 |
| Database (FKs / partitioning) | 9 | 6 | 1 | 1 | 1 |
| HR / Payroll | 14 | 7 | 3 | 3 | 1 |
| Expenses | 5 | 3 | 1 | 1 | 0 |
| Manufacturing | 3 | 2 | 0 | 1 | 0 |
| FSM (Field Service) | 7 | 5 | 1 | 1 | 0 |
| Reports / BI | 9 | 4 | 2 | 2 | 1 |
| Integrations | 7 | 3 | 3 | 1 | 0 |
| Notifications | 7 | 4 | 1 | 1 | 1 |
| Search | 5 | 2 | 1 | 2 | 0 |
| Supply Chain | 6 | 3 | 1 | 2 | 0 |
| Treasury | 4 | 2 | 1 | 1 | 0 |
| Frontend / UX | 9 | 4 | 1 | 4 | 0 |
| Security / Architecture | 8 | 4 | 2 | 2 | 0 |
| **الإجمالي** | **149** | **77** | **26** | **34** | **12** |

> **23%** عُولِج جزئيًا (`[partial]`) ضمن المراحل T0–T8.
> **17%** صُنِّف `[wont-fix]` بمبرِّرات موثقة.
> **52%** مُجدوَل لـ Phase 10 وما بعد.
> **8%** يحتاج فحصًا إضافيًا قبل التصنيف النهائي.

---

## تفصيل البنود

### Dashboard / Workspace
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #270 | لا مؤشر metadata للكاش (TTL 60s) | [scheduled] | Phase 10 — header `X-Cache-Hit` و`X-Cache-TTL`. |
| #345 | `widget_sales_summary` يستخدم `exchange_rate` ساكن | [partial] | T8.4 أصلح المسار في النماذج؛ لوحات القيادة لاحقًا. |
| #346 | `widget_pending_tasks` نفس المشكلة | [scheduled] | يتبع #345. |
| #347 | `get_available_widgets` لا يفحص الصلاحيات | [scheduled] | يحتاج ربط بنظام `permissions.dashboard.*`. |
| #348 | `low_stock` يعيد العدد فقط | [scheduled] | إضافة تفاصيل المنتج. |
| #349 | استعلام مخزون غير مُحسَّن (subquery + LEFT JOIN) | [open] | يحتاج EXPLAIN ANALYZE وخطة جديدة. |
| #350 | لا lazy-load لكل widget | [wont-fix] | الأداء الحالي مقبول؛ استبدال بنمط Skeleton كافٍ. |
| #279 | الـ Company timezone غير مستخدَم في scheduled tasks | [scheduled] | ربط `worker.py` بـ `companies.timezone`. |

### Audit Trail
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #274 | `request.client.host` بدون handling لـ reverse-proxy | [partial] | T1.x أضاف `X-Forwarded-For` parsing في middleware. |
| #275 | لا device fingerprinting | [scheduled] | إضافة User-Agent parsing + device hash. |
| #276 | `endpoint`/`method` غير مُسجَّلَيْن في log_activity | [partial] | جزئيًا في `request_id_middleware`. |
| #277 | لا audit للـ GET requests | [wont-fix] | حجم البيانات سينفجر؛ نكتفي بـ DELETE/POST/PUT. |
| #351 | `critical=True` مستخدم في 4 endpoints فقط | [scheduled] | وَسْم باقي الـ endpoints الحساسة. |
| #352 | POST body غير مُلتقَط في log_activity | [scheduled] | يحتاج sanitization (PII filter) قبل التخزين. |
| #353 | لا نمط كشف الموظف الشبح | [scheduled] | rule-engine في Phase 11 (FraudOps). |

### Background Jobs
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #278 | لا UI لمراقبة الـ jobs | [scheduled] | شاشة `/admin/jobs` في Phase 10. |
| #279 | Company timezone غير مستخدَم | [scheduled] | (مكرر مع Dashboard). |
| #419b | جدولان مكرران للتقارير | [scheduled] | حذف `scheduled_reports.py` غير المستخدَم. |
| #419c | payroll subscription يستخدم `date.today()` | [partial] | ربطه بـ company timezone. |
| #419d | Outbox giveup بدون admin alert | [open] | webhook إلى `/admin/notifications/critical`. |

### Cache (Redis/Memory)
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #280 | `MemoryCache` لا ينظف المفاتيح المنتهية | [scheduled] | إضافة background sweeper. |
| #281 | Token blacklist يكبر بلا حد | [partial] | T2.x أضاف TTL متطابقًا مع JWT exp. |
| #282 | لا metrics للـ cache | [scheduled] | Prometheus exporter في Phase 10. |
| #354 | `chart_of_accounts` cache key يُحذَف مرتين | [partial] | T6.x أصلح بعض النداءات؛ مراجعة باقي الراوترات. |
| #355 | TTL افتراضي 300s طويل جدًا | [wont-fix] | مقبول؛ المفاتيح الحرجة لها TTL مخصَّص. |
| #419e | Redis `maxmemory-policy` غير مضبوط | [open] | `allkeys-lru` في `docker-compose.prod.yml`. |

### CRM / Sales Pipeline
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #283 | Opportunity stage يعود لـ `proposal` عند التحويل | [scheduled] | احترام `stage` الحالية. |
| #284 | `SalesOrder.converted_to_invoice_id` ناقص | [scheduled] | إضافة العمود + migration. |
| #285 | Sales velocity = `updated_at - created_at` | [partial] | T4.x وثَّق الصيغة كقيد معروف. |
| #286 | معدل التحويل غير قياسي | [scheduled] | اعتماد funnel-stage formula. |
| #287 | activities بدون pagination/filters | [partial] | T8.1 يوفر `useApiList` على الفرونت. |
| #288 | لا ربط activities ↔ crm_contacts | [scheduled] | FK جديد + UI. |
| #289 | sales forecast منفصل عن cash-flow forecast | [scheduled] | join على `expected_close_date`. |
| #290 | Credit limit لا يُفحص على الفرص | [scheduled] | استدعاء `validate_credit_limit` في opportunity create. |
| #356 | velocity يعيد 0 بدلًا من NULL | [wont-fix] | الـ frontend يعالج 0 بشكل صحيح. |

### Sales / POS
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #291 | POS يطبِّق الخصم بعد الضريبة (مخالف ZATCA) | [scheduled] | إصلاح حرج لاعتماد ZATCA؛ Phase 10 P0. |
| #292 | offers/coupons لا تُطبَّق تلقائيًا | [scheduled] | promotion engine. |
| #293 | Cancel invoice لا يفحص inventory قبل reversal | [partial] | T6.x أضاف فحص جزئي. |
| #294 | Cancellation JE يستخدم `reference` بدلًا من `source+source_id` | [partial] | T2.x وحَّد المرجعية للفواتير الجديدة. |
| #295 | افتراض حساب الإيرادات إذا غاب حساب الخصم | [open] | إضافة validation في acc_map. |
| #296 | لا صلاحية `price_override` | [scheduled] | إضافة permission جديد. |
| #297 | `sales_returns` vs `pos_returns` متعارضة (P2) | [partial] | T6.x وحَّد المخططات. |
| #298 | `acc_map_sales` vs `acc_map_sales_rev` (P2) | [partial] | T6.x وحَّد. |
| #390 | idempotency key على رقم تسلسلي | [scheduled] | استخدام UUID. |
| #391 | `get_acc_id(code)` معرَّفة 3 مرات | [scheduled] | إعادة استخدام `services/accounts.py`. |
| #392 | لا state machine لدورة الفاتورة | [scheduled] | Phase 11. |
| #393 | POS multi-session بدون inventory lock | [scheduled] | distributed lock على الـ stock. |
| #419j | الخصم دائمًا بعد الضريبة | [partial] | يتبع #291. |
| #419k | mobile sync_queue لا يشمل POS | [wont-fix] | POS لا يعمل offline في الفرع الحالي. |
| #419l | UBL XML builder بنية أدنى | [scheduled] | يتبع #291 لاعتماد ZATCA الإنتاج. |

### DMS
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #299 | `validate_file_mime_and_signature` يستهلك ذاكرة قبل الحفظ | [scheduled] | streaming validator. |
| #298d | `validate_file_path_safety` كود ميت | [wont-fix] | حذف في Phase 10 cleanup. |
| #299d | لا quota للتخزين | [scheduled] | عداد per-company. |
| #300 | لا فحص طول filename | [open] | trivial fix Phase 10. |
| #357 | لا CASCADE delete من parent | [scheduled] | تحويل related_module/id لـ FK. |
| #358 | storage path يُحسب عند الاستيراد | [partial] | T7.x أصلح الـ APP_ROOT. |
| #419f | لا تشفير على مستوى filesystem | [wont-fix] | يُحال للبنية التحتية (LUKS/EBS). |

### Database
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #301 | لا BRIN indexes | [scheduled] | بعد جداول الأرشفة (T9.3). |
| #302 | لا partitioning لـ audit_logs/journal_lines | [scheduled] | declarative partitioning في Phase 10. |
| #415 | FK journal_entries.created_by بدون ON DELETE | [scheduled] | RESTRICT (لا حذف يدوي للمستخدمين). |
| #416 | FK pos_orders.session_id بدون ON DELETE | [scheduled] | CASCADE. |
| #417 | self-FK accounts.parent_id بدون حماية | [scheduled] | RESTRICT. |
| #418 | FK inventory.product_id بدون ON DELETE | [scheduled] | RESTRICT. |
| #419 | payroll_entries.period_id (DDL ↔ ORM mismatch) | [partial] | T2.x سَوَّى للجداول الجديدة. |
| #419m | pool عند 50 tenants ≈ 750 connections | [open] | تحسين pool sizing + pgBouncer. |
| #414 | f-string SQL (آمن حاليًا، نمط هش) | [partial] | T1.x أضاف CI scan. |

### HR / Payroll
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #303 | فشل استعلام `employee_salary_components` صامت | [open] | إضافة logger.warning. |
| #304 | `mol_establishment_id` قد يكون أصفارًا | [scheduled] | validation عند الإعدادات. |
| #305 | bank code = `RJHI` ساكن | [partial] | T8.4 جعل overtime ديناميكيًا؛ bank code يتبع. |
| #306 | الإجازة السنوية = 21 يومًا ساكن | [scheduled] | قراءة من `employee.annual_leave_days`. |
| #307 | FIELD_ENCRYPTION_KEY يعيد None | [partial] | T1.x أضاف validation عند الإقلاع. |
| #308 | لا فحص لتكرار payslip | [scheduled] | unique constraint (employee_id, period_id). |
| #309 | open session يمنع check-in جديد | [scheduled] | auto-close بعد 16h. |
| #373 | لا ربط attendance ↔ timetracking | [scheduled] | join key + view. |
| #374 | لا حساب ticket_allowance | [scheduled] | حقل سنوي + accrual. |
| #375 | لا تكامل مع biometric devices | [wont-fix] | خارج النطاق الحالي. |
| #376 | payslip بدون header/logo | [partial] | T8.3 split CSS؛ printable layout قادم. |
| #377 | WPS preview لا يفرض hr.pii | [scheduled] | إضافة `require_permission("hr.pii")`. |
| #378 | لا تكامل Nitaqat | [wont-fix] | لا API رسمي حاليًا. |
| #419g | acc_map_loans_adv استخدام مزدوج | [scheduled] | تقسيم لـ debit/credit accounts. |
| #419h | unpaid leave غير مُطبَّق على EOS | [open] | bug fix. |
| #419i | تقريب 365.25 لسنوات الخدمة | [partial] | T6.x وثَّق التحفظ. |

### Expenses
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #310 | auto_approve_below_threshold يحتاج استدعاءً يدويًا | [scheduled] | scheduler hook. |
| #311 | cost_center_id اختياري | [scheduled] | enforce per company policy. |
| #312 | لا compound approval policies | [scheduled] | rule engine. |
| #359 | expense ↔ project رابط أحادي | [partial] | T6.x أضاف العكسي. |
| #360 | auto_approve يستخدم default cash account | [wont-fix] | السلوك مقصود؛ موثَّق في RUNBOOK. |
| #419q | asset return بدون writedown JE | [open] | يتبع IFRS depreciation. |

### Manufacturing
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #313 | prefix `PO-` يلتبس بـ Purchase Order | [scheduled] | `MFG-` أو `PRD-`. |
| #314 | لا ربط shop floor ↔ attendance | [scheduled] | join على employee_id+date. |
| #419v | `lead_time_days` غير مستخدَم في MRP | [partial] | T6.x أضاف الحقل؛ المنطق قادم. |

### FSM
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #315 | optimistic locking معطَّل | [scheduled] | إعادة تفعيل + version column. |
| #316 | service contract invoice بلا مرجع للطلب | [scheduled] | إضافة `source_request_id`. |
| #317 | ServiceCostCreate بلا markup_pct | [open] | إضافة الحقول. |
| #367 | renew() لا يولد طلبات متكررة | [scheduled] | scheduler. |
| #368 | generate_contract_invoice لا ينشئ service orders | [scheduled] | hook. |
| #369 | ServiceRequestUpdate بلا hourly_rate | [open] | إضافة الحقل. |
| #370 | service maintenance ≠ asset maintenance | [scheduled] | توحيد في Phase 11. |
| #371 | equipment maintenance منفصل | [scheduled] | يتبع #370. |
| #372 | equipment.next_maintenance_date غير مستخدَم | [partial] | T6.x أضاف العمود؛ scheduler قادم. |

### Reports / BI
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #318 | balance sheet sign logic معقد | [scheduled] | refactor + unit tests. |
| #319 | report cache per-worker | [scheduled] | Redis-backed cache. |
| #320 | sales report = آخر 30 يوم | [wont-fix] | السلوك مقصود؛ filter متاح. |
| #321 | rollup() يخلط int + Decimal | [partial] | T6.x وحَّد بعض المسارات. |
| #322 | لا audit log لمشاهدة التقارير | [scheduled] | log_activity('report_view'). |
| #403 | income statement يضمّن header rows | [open] | bug fix. |
| #404 | trial balance tolerance قرب الصفر | [partial] | T6.x ضبط tolerance لـ 0.01. |
| #405 | rollup type coercion | [partial] | (مكرر #321). |
| #406 | date filter في JOIN ON | [scheduled] | نقله لـ WHERE. |
| #407 | cash flow بلا opening سلبي | [open] | bug fix. |
| #419r | KPI dashboard بلا account-type sign | [scheduled] | استخدام `account_type` في الإشارة. |
| #419s | GL journal بلا pagination | [scheduled] | إضافة LIMIT/OFFSET. |

### Integrations
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #323 | ReDoc/Swagger مكشوف في الإنتاج | [partial] | T1.x أضاف auth gate جزئيًا. |
| #324 | لا unified health check | [partial] | T7.x أضاف `/api/health/cache`؛ بقية الـ adapters قادمة. |
| #325 | لا unified metrics | [scheduled] | OpenTelemetry. |
| #379 | Stripe URL ساكن | [wont-fix] | URL ثابت رسمي؛ لا تغيير متوقع. |
| #380 | Tap URL ساكن | [wont-fix] | (نفس البرر). |
| #381 | PayTabs URL ساكن | [wont-fix] | (نفس). |
| #382 | ZATCA XMLDSig خارجي | [scheduled] | استبدال بـ inline signing. |
| #383 | ETA URL ساكن | [scheduled] | env var. |
| #384 | CSV bank format يدوي | [scheduled] | format detector. |
| #419u | لا OpenAPI desc | [partial] | T9.2 يعالج هذا (انظر أدناه). |

### Notifications
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #326 | POST /notifications/send بلا rate limiter | [open] | إضافة @limiter.limit. |
| #327 | templates ساكنة في الكود | [scheduled] | استخدام `email_templates` table. |
| #328 | `email_templates` غير مستخدَم | [scheduled] | (يتبع #327). |
| #329 | لا DLQ للإشعارات | [partial] | T2.x أضاف integration_dlq؛ توسيعها. |
| #385 | send_bulk بلا تفاصيل فشل per-user | [scheduled] | إعادة هيكلة الـ response. |
| #386 | preferences تُقرأ من DB كل send | [scheduled] | cache 5min. |
| #387 | لا global opt-out | [wont-fix] | يتعارض مع متطلب الإشعارات الإلزامية. |
| #388 | SPF/DKIM/DMARC غير موثقة | [partial] | T9.5 سيوثقها. |
| #389 | أرقام الجوال بلا masking في logs | [partial] | T1.x أضاف masking في PII filter؛ التحقق من تغطية SMS. |

### Search
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #330 | GlobalSearch frontend-only | [partial] | T7.2 أضاف `/api/search` backend. |
| #331 | لا autocomplete أثناء الكتابة | [scheduled] | debounced suggestions. |
| #332 | لا voice search | [wont-fix] | منخفض القيمة. |
| #394 | search بلا LIMIT | [partial] | T7.2 أضاف limit param (default 20). |
| #395 | GlobalSearch page list ساكن | [scheduled] | metadata-driven. |
| #419t | pg_trgm ميت | [partial] | T7.x فعَّله للـ products/parties؛ التحقق من المسارات الأخرى. |

### Supply Chain
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #333 | endpoints مهملة غير معطَّلة | [scheduled] | إضافة 410 Gone. |
| #334 | فحص inventory مكرَّر | [partial] | T6.x وحَّد. |
| #335 | tolerance_amount = 0.01 ساكن | [scheduled] | إعدادات شركة. |
| #396 | low stock threshold = 5 ساكن | [scheduled] | per-product config. |
| #397 | webhook `inventory.low_stock` غير مفعَّل | [scheduled] | scheduler hook. |
| #398 | cancel restock بلا max bounds | [open] | فحص بسيط. |
| #399 | endpoints `/transfers` و `/transfer` | [partial] | T6.x deprecated singular. |
| #419n | رسالة خطأ بالعربية فقط | [partial] | T9.4 يعالج هذا (انظر أدناه). |
| #419o | لا أرشفة inventory_transactions | [partial] | T9.3 يعالج هذا (انظر أدناه). |

### Treasury
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #336 | forecast initial balance = 0 | [scheduled] | قراءة current balance. |
| #337 | offsets +7d/+3d ساكنة | [scheduled] | إعدادات شركة. |
| #400 | auto_match يحتاج trigger يدوي | [scheduled] | daily scheduler. |
| #401 | forecast lines بلا bank_account_id | [open] | إضافة الحقل. |
| #402 | duplicate check رقم ضمن الفرع فقط | [wont-fix] | الأرقام مستقلة per-branch. |
| #419p | تقريب revaluation متعدد العملات | [partial] | T6.x ضبط دقة Decimal. |

### Frontend / UX
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #338 | DataTable بلا horizontal scroll | [scheduled] | overflow-x: auto. |
| #339 | لا mobile table strategy | [scheduled] | card layout على الموبايل. |
| #340 | لا print stylesheet | [partial] | T8.3 أضاف `styles/print.css`. |
| #341 | fetchData/setLoading مكرَّر | [partial] | T8.1 أضاف useApi؛ الترحيل تدريجي. |
| #342 | forms بدون semantic | [scheduled] | refactor شامل. |
| #343/#365 | StrictMode غير مستخدَم | [scheduled] | تفعيل + إصلاح warnings. |
| #344 | i18n fallback to English | [wont-fix] | السلوك مقصود (better than missing key). |
| #361 | setLoading(false) ناقص في catch | [partial] | T8.1 يحل هذا للنماذج المرحَّلة. |
| #362 | ErrorBoundary reload يفقد state | [scheduled] | استخدام `react-router` navigate. |
| #363 | thermal printer styles خارج @media print | [partial] | T8.3 أصلح بعض المسارات. |
| #364 | no Redux/Zustand | [wont-fix] | useApi + Context كافٍ للنطاق الحالي. |
| #366 | 1950+ useState بلا cleanup | [partial] | T8.1 يعالج التسرّب في الصفحات المرحَّلة. |

### Security / Architecture
| ID | العنوان | تصنيف | ملاحظة |
|---|---|---|---|
| #408 | SENSITIVE_PERMISSIONS غير مفحوصة | [open] | ربطها بـ require_permission. |
| #409 | لا Repository Pattern | [partial] | T2.x أنشأ `repositories/` مجلَّد جزئيًا. |
| #410 | God Routers (purchases.py 3700+) | [scheduled] | تقسيم تدريجي. |
| #411 | لا DTOs صريحة | [scheduled] | اعتماد Pydantic models. |
| #412 | tx pattern مكرَّر 200+ مرة | [partial] | T1.x أضاف `transactional()` context manager. |
| #413 | LDAP password POST plain | [scheduled] | يتبع #323 لو HTTPS غير مفروض. |
| #414 | f-string SQL (آمن، هش) | [partial] | T1.x CI scanner. |
| #419a | MV name f-string injection | [partial] | T1.x أضاف whitelist. |

---

## ملحق: المنهجية

- **مصدر البنود:** `docs/audit/CONSOLIDATED_AUDIT_REPORT.md` (أبريل 2026).
- **التصنيف الذاتي:** يعتمد على ROI (تكلفة/أثر) ومدى تعقيد الإصلاح.
- **مراجعة دورية:** يُحدَّث هذا الملف في بداية كل مرحلة جديدة (Phase 10، Phase 11).

> أي بند مُصنَّف `[scheduled]` يجب أن يدخل لاحقًا في خطة المرحلة المعنية مع DoD صريح.

---

## ملحق: بنود P3 إضافية (مكتشفة في 2026-05-01 — غير مصنّفة سابقًا)

تم استخراجها من `CONSOLIDATED_AUDIT_REPORT.md` ولم تكن ضمن الجدول الرئيسي أعلاه.

| # | المصدر | الملف | السطر | التفصيل | التصنيف |
|---|--------|-------|-------|----------|----------|
| 271 | Accounting | ``gl_service.py`` | 52 | التسامح `> _D2` (0.01) واسع جدًا — فروق 0.009 تمر دون إنذار | [scheduled] |
| 272 | Accounting | ``invoices.py`` | 589-599 | `source="Sales-Invoice"` حالة أحرف مختلطة — باقي المصادر lowercase | [scheduled] |
| 272a | Security | ``data_import.py`` | 280 | **تسريب معلومات هيكلية**: `f"خطأ في السطر {i + 2}"` يكشف أرقام الصفوف الداخلية للمستخدم — موقع إضافي غير مذكور في #163 | [scheduled] |
| 272b | Security | ``company_settings`` | - | **كلمة مرور SMTP مخزنة كنص واضح**: بالإضافة لمفاتيح ZATCA (#162)، كلمة مرور SMTP مخزنة بدون تشفير في `company_settings` | [scheduled] |
| 272c | Cache | ``role_dashboards.py`` | 70-354 | **13 لوحة تحكم حسب الدور تُمسح بالإبطال الشامل**: كاش 13 داشبورد بـ TTL 60-300 ثانية يُمسح كله بعد كل عملية. متوسط بقاء الكاش ~30 ثانية في الشركات النشطة | [scheduled] |
| 272d | DMS | ``services.py`` | 443-498 | **`list_documents` يكشف `download_url`**: قائمة المستندات تعرض رابط التحميل المباشر — يُضخم ثغرة `/uploads` العامة (#54) بتوفير مسارات التحميل | [scheduled] |
| 272e | DMS | ``services.py`` | 739-760 | **الحذف الناعم لا يمتد لإصدارات المستند على القرص**: `document_versions` لديها `ON DELETE CASCADE` على مستوى DB لكن الحذف الناعم لا يُفعّلها. إصدارات المستندات المحذوفة تبقى على القرص | [scheduled] |
| 272f | Database | ``inventory_transactions`` | - | **فهرس مفقود `(product_id, transaction_date)`**: تقارير حركة المنتجات الزمنية تمسح الجدول كاملاً | [scheduled] |
| 272g | Database | ``payment_vouchers`` | - | **فهرس مفقود `(party_type, party_id)`**: استعلام جميع مدفوعات طرف معين يمسح الجدول كاملاً | [scheduled] |
| 272h | Database | ``purchases.py`` | 1870 | **`FOR UPDATE` لكل منتج في حلقة منفصلة عند مرتجع المشتريات**: يجب تجميعها في استعلام واحد بدل N استعلام | [scheduled] |
| 272i | Database | `-` | - | **لا يوجد endpoint لاستعادة النسخ الاحتياطية**: `POST /admin/backup` موجود لكن لا يوجد API للاستعادة | [scheduled] |
| 272j | HR | ``self_service.py`` | 161-196 | **لا يوجد سجل تدقيق لعرض قسائم الرواتب**: الموظف يرى تفاصيل راتبه الكاملة في الخدمة الذاتية لكن لا يُسجل من شاهد القسيمة ومتى | [scheduled] |
| 272k | Sales/POS | ``pos.py`` | 528-538 | **فحص المخزون في POS يفترض اتصال DB**: `FOR UPDATE` يتطلب اتصالاً بقاعدة البيانات. في وضع عدم الاتصال، لا يوجد تحقق محلي بديل | [scheduled] |
| 272l | Manufacturing | ``core.py`` | 1272-1280 | **غياب `acc_map_labor_cost`/`acc_map_mfg_overhead` يترك WIP غير متوازن**: قيد امتصاص العمالة يفترض وجود هذه الحسابات. إذا كانت فارغة، لا يُنشأ قيد — WIP لا يتوازن مع المنتج النهائي | [scheduled] |
| 272m | Manufacturing | ``core.py`` | 909-918 | **لا يوجد منطق لتخطي العمليات الاختيارية في المسار**: نسخ عمليات المسار عند إنشاء أمر الإنتاج يفترض أن جميع العمليات إلزامية (مثل فحص الجودة الاختياري) | [scheduled] |
| 272n | Manufacturing | `-` | - | **MRP لا يأخذ مخزون الأمان (Safety Stock) بالاعتبار**: `reorder_level` موجود في جدول المنتجات لكنه غير مستخدم في حسابات MRP | [scheduled] |
| 272o | Manufacturing | `-` | - | **MRP لا يُنشئ أوامر شراء تلقائيًا**: يقترح `purchase_order` كإجراء لكنه لا يُنشئ PO فعليًا — مجرد اقتراح بدون تنفيذ | [scheduled] |
| 272p | Manufacturing | ``core.py`` | 1765 | **MRP لأمر واحد فقط**: لا يوجد MRP شامل لجميع أوامر الإنتاج المعلقة (Net Requirements Planning). كل أمر يُحسب بمعزل عن الآخرين | [scheduled] |
| 272q | Manufacturing | ``core.py`` | 1316 | **طرح كمية هش**: `existing_qty = SUM(quantity) - order.quantity` — الأفضل قراءة الكمية قبل الإضافة بدل الطرح بعدها | [scheduled] |
| 272r | Supply Chain | ``costing_service.py`` | 118-121 | **`per_warehouse_wac` يستبعد المستودعات ذات الرصيد السالب**: إذا كان لمستودع رصيد سالب (نظريًا)، يُستبعد من حساب المتوسط العام بدون تحذير | [scheduled] |
| 272s | Supply Chain | ``costing_service.py`` | 320-335 | **`handle_return` يُنشئ طبقة تكلفة جديدة بدل عكس الأصلية**: الطبقة الأصلية المستهلكة تبقى كما هي والمرتجع يُنشئ طبقة جديدة | [scheduled] |
| 272t | Supply Chain | ``shipments.py`` | 345 | **خلط دقة `Decimal`/`float`**: `total_transit_value` يستخدم `Decimal` لكن `source_cost` يأتي كـ `float` من `get_cogs_cost` | [scheduled] |
| 272u | Treasury | ``reconciliation.py`` | 797-871 | **إنهاء المطابقة لا يتحقق من رصيد GL مقابل رصيد الخزينة**: يتحقق أن الرصيد المحسوب = الرصيد المُدخل، لكن لا يتحقق من تطابق `accounts.balance` مع `treasury_accounts.current_balance` | [scheduled] |
| 272v | FSM | ``contracts.py`` | 25-100 | **لا يوجد نموذج عقود خدمة متخصص**: العقود عامة (مبيعات/خدمات/اشتراكات). لا يمكن تعريف جداول صيانة وقائية أو شروط SLA أو قوائم معدات مغطاة على مستوى العقد | [scheduled] |
| 272w | FSM | ``governance.py`` | 971-976 | **فوترة الخدمة تسمح بإيراد صفري مع تكلفة موجبة**: يمكن إغلاق أمر خدمة وترحيله كخسارة صافية بدون تحذير أو بوابة اعتماد. الشرط يتحقق فقط أن أحدهما > 0 | [scheduled] |
| 272x | FSM | ``crm.py`` | 430-439 | **SLA موجود فقط على تذاكر الدعم وليس أوامر الخدمة**: `support_tickets` لديها `sla_hours` لكن `service_requests` لا تحتوي على أي حقول SLA | [scheduled] |
| 272y | FSM | ``assets.py`` | 1588-1606 | **`scheduled_date` في صيانة الأصول خامل**: نموذج البيانات يدعم `maintenance_type='preventive'` و `scheduled_date` لكن لا مجدول يتحقق من المواعيد لتوليد أوامر عمل تلقائيًا | [scheduled] |
| 272z | Reports/BI | ``reports.py`` | 1045-1056 | **توزيع الرصيد الافتتاحي في ميزان المراجعة هش**: حسابات الأصول ذات الرصيد الدائن (مثل المخصصات) تُعرض بشكل خاطئ | [scheduled] |
| 273 | Accounting | ``accounting.py`` | 606 | القيود المسودة تُفحص ضد الفترة المغلقة — منطقيًا لا تؤثر على الأرصدة لكن النظام يمنعها | [scheduled] |
| 419w | Sales/POS | ``pos.py`` | 397-487 | **POS لا يطبق العروض/الكوبونات تلقائيًا على الإجمالي**: حقول `coupon_code` و `promotion_id` موجودة في نموذج `PosOrder` لكن كود إنشاء الطلب لا يستخدمها لحساب الخصم — يجب على الواجهة الأمامية حساب الخصم يدويًا وإرساله كـ `discount_amount` (P2) | [scheduled] |
| 419x | Treasury | ``reconciliation.py`` | 797-871 | **اعتماد التسوية (`finalize`) لا يتحقق من رصيد GL الفعلي**: يتحقق فقط أن الرصيد المحسوب = الرصيد المدخل، لكن لا يقارن مع `treasury_accounts.current_balance` ولا مع `accounts.balance` للحساب الموازي — قد يُعتمد توازن شكلي مع اختلاف فعلي بين الخزينة و GL (P2) | [scheduled] |
| 419y | Treasury | ``forecast_service.py`` | 118-133 | **القيود الدورية تُؤخذ بقيمتها الكلية في التنبؤ النقدي**: `total_amount` لكل قالب دوري يُستخدم مباشرة دون تحليل سطور القيد لاستخراج الحسابات النقدية فقط — التدفق المُتنبأ به منحاز ولا يعكس الحركة النقدية الفعلية للقيد (P2) | [scheduled] |
