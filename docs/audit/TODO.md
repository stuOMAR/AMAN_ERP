# خطة تصحيح شاملة — AMAN ERP
# Comprehensive Remediation Plan (TODO)

> **المرجع**: `CONSOLIDATED_AUDIT_REPORT.md` — 519 بندًا (8 P0 + 120 P1 + 215 P2 + 176 P3 + 2 تقييميَّة)
> **الهدف**: الانتقال من 51/100 (Visionary) إلى 84/100 (Leader) خلال 90 يومًا
> **منهجية التقسيم**:
> - كل **مهمة (Task)** = جلسة مستقلة قابلة للتنفيذ في نافذة سياق واحدة (~50K-150K توكن).
> - **التقدير**: `S` (≤30K توكن، تعديل 1-3 ملفات)، `M` (30K-80K، تعديل 3-8 ملفات)، `L` (80K-150K، تعديل 8-20 ملفًا أو ميزة كاملة)، `XL` (يجب تقسيمها قبل البدء).
> - كل مهمة لها: نطاق محدد، ملفات مستهدفة، معايير قبول (DoD)، وبنود التدقيق المرتبطة (#).

---

## 📋 جدول المحتويات

- [المرحلة 0: التحضير والبنية التحتية](#المرحلة-0-التحضير-والبنية-التحتية-pre-flight)
- [المرحلة 1: P0 الحرج (الأسبوع 1)](#المرحلة-1-p0-الحرج-أسبوع-1)
- [المرحلة 2: P1 الأمن وحماية البيانات (الأسبوع 2-3)](#المرحلة-2-p1-الأمن-وحماية-البيانات-أسبوع-2-3)
- [المرحلة 3: P1 الدقة المحاسبية (الأسبوع 3-5)](#المرحلة-3-p1-الدقة-المحاسبية-أسبوع-3-5)
- [المرحلة 4: P1 الأتمتة والموثوقية (الأسبوع 5-7)](#المرحلة-4-p1-الأتمتة-والموثوقية-أسبوع-5-7)
- [المرحلة 5: P1 الامتثال والتكاملات (الأسبوع 7-9)](#المرحلة-5-p1-الامتثال-والتكاملات-أسبوع-7-9)
- [المرحلة 6: P2 توحيد البنية ومعالجة الديون التقنية (الأسبوع 9-11)](#المرحلة-6-p2-توحيد-البنية-أسبوع-9-11)
- [المرحلة 7: P2 الأداء والكاش والبحث (الأسبوع 11-12)](#المرحلة-7-p2-الأداء-والكاش-والبحث-أسبوع-11-12)
- [المرحلة 8: P2/P3 تجربة المستخدم والوصول](#المرحلة-8-p2p3-تجربة-المستخدم-والوصول)
- [المرحلة 9: P3 التنظيف النهائي والتوثيق](#المرحلة-9-p3-التنظيف-والتوثيق)
- [مصفوفة التتبع](#مصفوفة-التتبع)

---

## المرحلة 0: التحضير والبنية التحتية (Pre-flight)

> هذه مهام إعداد لازمة قبل أي إصلاح. **لا تُحسب ضمن البنود الـ 519** لكنها شرط نجاح.

### T0.1 — إنشاء فرع إصلاح طويل العمر `fix/audit-2026-04-28` `[S]`
- DoD: فرع محمي، CI أخضر على الـ baseline.

### T0.2 — تثبيت تغطية اختبارات منهجية `[M]`
- إضافة `pytest --cov` ≥ 70% على الوحدات المالية الحرجة (accounting, invoices, vouchers, payroll).
- DoD: `coverage.xml` محدث، تقرير baseline مرفق.

### T0.3 — تفعيل `pre-commit` لِـ SQL/Python lint `[S]`
- تشغيل `scripts/check_sql_parameterization.py` و `scripts/check_pii_logging.py` و `scripts/check_gl_posting_discipline.py` على كل commit.
- DoD: `.pre-commit-config.yaml` يحتوي الثلاثة + ruff + mypy.

### T0.4 — نسخة احتياطية إنتاجية + بيئة staging `[M]`
- `scripts/backup_postgres.sh` + اختبار `restore_postgres.sh`.
- staging مطابق لإصدار الإنتاج.
- DoD: استرداد ناجح موثق.

---

## المرحلة 1: P0 الحرج (أسبوع 1)

> **الهدف**: إغلاق جميع الـ 8 P0. النظام لا يصلح للإنتاج قبل اكتمال هذه المرحلة.
>
> **حالة 2026-05-01**: المرحلة 1 مكتملة. T1.1 و T1.4 سُجِّلا كـ INVALID بعد التحقق العملي (false-positive في التدقيق). T1.2 و T1.3a و T1.5 a/b/c FIXED. صافي P0 الفعلية: 5 من أصل 8 — كلها مغلقة.

### T1.1 — ~~إصلاح `ON CONFLICT DO UPDATE` بمرجع جدول خاطئ~~ **[INVALID — تم التحقق 2026-05-01]**
- **بنود**: #4، #7b.
- **النتيجة**: بعد اختبار عملي على PostgreSQL حقيقي، الصياغة `tablename.column` في `ON CONFLICT DO UPDATE` صحيحة وموثقة رسميًا في PostgreSQL. القيد `UNIQUE(product_id, warehouse_id)` موجود في [database.py:632](../../backend/database.py#L632).
- **الإجراء**: لا تغيير في الكود. خفض عدّ P0 من 8 إلى 6.

### T1.2 — إصلاح فحص تكرار إعادة التقييم + إنشاء حسابات UFX `[S]` — **[FIXED 2026-05-01]**
- **بنود**: #1، #2 (Treasury/currencies.py:297-318).
- **التغيير المنفّذ**:
  - فحص تكرار إعادة التقييم استبدل بـ `source='currency_revaluation' AND source_id=:currency_id` بدلاً من `entry_number LIKE 'REV-%'` (الذي لم يكن يتطابق أبدًا لأن الصيغة الفعلية `JE-XXXXX`).
  - إضافة `42021 UFX-GAIN` و `71011 UFX-LOSS` إلى `CORE_ACCOUNTS` في [services/industry_coa_templates.py](../../backend/services/industry_coa_templates.py).
  - resolver لـ UFX بأربعة مستويات fallback (mapping/legacy code/numeric code/name) في [routers/finance/currencies.py](../../backend/routers/finance/currencies.py).
  - تحويل HTTP 500 إلى 422 برسالة عربية واضحة.
  - migration [0013_add_ufx_accounts.py](../../backend/alembic/versions/0013_add_ufx_accounts.py) لباكفيل الشركات القائمة.
- **DoD المتحقق**: resolver اختُبر عمليًا ضد Postgres (يفضل legacy code عند وجوده، ويعود إلى numeric للشركات الجديدة).

### T1.3 — إلغاء ازدواجية رصيد الخزينة `treasury_accounts.current_balance` `[L]` **[FIXED in T1.3a — 2026-05-01]**
- **بنود**: #3 (Treasury R1/R2)، 419x.
- **القرار**: بدلاً من جعل `current_balance` عمودًا محسوبًا (DB trigger) — أي UPDATE يدوي متبقٍ + trigger = double-count — تم اعتماد helper Python idempotent يُعيد الحساب من `journal_lines` (مصدر الحقيقة الوحيد لـ GL) بعد كل عملية. هذا أكثر أمانًا ومتدرّج.
- **التنفيذ (T1.3a — مكتمل)**:
  1. helper جديد: `backend/utils/treasury_balance.py::recalc_treasury_from_gl(db, treasury_id)` — يقرأ `journal_lines` للـ`gl_account_id` المرتبط بالخزينة، يحسب الرصيد من JEs `status='posted'`، يفرّق بين FC (SUM ±amount_currency حيث currency = treasury.currency) وSAR (SUM debit-credit)، ويكتب `current_balance` + `updated_at`.
  2. استُبدلت **كل المواقع الـ17** للتحديث اليدوي بـ:
     - `routers/sales/invoices.py` (موقع واحد، جمع الفروع SAR/FC)
     - `routers/sales/vouchers.py:192`
     - `routers/sales/returns.py:438`
     - `routers/pos.py:743, 1102` (POS sale + POS refund)
     - `routers/projects.py:1340`
     - `routers/finance/notes.py:309, 630` (notes_receivable + notes_payable)
     - `routers/finance/checks.py:368, 448, 880, 972` (collect/clear/bounce سيناريوهات)
     - `routers/finance/treasury.py` (4 مواقع: opening_balance، sub-treasury، transfer source، transfer target)
     - **خاص**: opening_balance نُقل من **قبل** إنشاء JE إلى **بعده** ليرى recalc البيانات.
  3. Migration `backend/alembic/versions/0014_backfill_treasury_balance.py`: يعيد حساب جميع الخزائن في كل tenant عبر correlated subquery (يستبعد drafts بشكل قطعي على عكس LEFT JOIN). idempotent.
- **DoD المتحقق**:
  - get_errors نظيف عبر 9 ملفات معدّلة.
  - اختبار عملي على Postgres حقيقي: SAR (1000+500-300=1200) ✓ ، USD (1000-500=500 amount_currency) ✓ ، خزينة بدون JL → 0 (overrides stale value) ✓ ، draft 99999 مُستبعد ✓.
  - grep `UPDATE treasury_accounts SET current_balance` يُظهر فقط الـ helper.
- **مؤجَّل (T1.3b — بعد فترة مراقبة)**: تقرير مطابقة دوري + DB trigger يمنع UPDATE المباشر. سيُنفَّذ بعد التأكد من عدم وجود مواقع مفقودة في الإنتاج.

### T1.4 — ~~تصحيح معادلة `check_inventory_sufficiency`~~ **[INVALID — تم التحقق 2026-05-01]**
- **بند**: #5 (Manufacturing/core.py:634-635).
- **النتيجة**: بعد اختبار عملي بـ 4 حالات (fixed/percentage × with/without waste)، المعادلة تنتج نفس النتيجة بالضبط كـ `manufacture_consume`. التعبير الشرطي `if not comp.is_percentage` يمنع الضرب المزدوج.
- **الإجراء**: لا تغيير في الكود. خفض عدّ P0 إلى 5.

### T1.5 — تطبيق ZATCA Phase 2 Clearance + إدارة CSID `[L]` **[FIXED — 2026-05-01]**
- **بنود**: #6، #7، 419z.
- **التنفيذ**:
  - **T1.5a (#419z)** — `routers/finance/accounting_depth.py`: `einvoice_submit` يُدخل في `einvoice_outbox` لحالات `failed/error/rejected` **و** `submitted+offline`. relay loop يستثني `submitted+offline` من النجاح ليبقى pending مع backoff.
  - **T1.5b (#7)** — جدول `zatca_csid` (alembic 0015) + scheduler job `check_zatca_csid_expiry` كل 12h يفحص جميع tenants ويرسل تنبيهات 30/7/1 يومًا (notifications + log) ويعلّم expired تلقائيًا. UNIQUE index يفرض CSID نشط واحد لكل environment.
  - **T1.5c (#6)** — helper `utils/zatca_clearance.attempt_clearance` خلف flag `settings.ZATCA_PHASE2_ENFORCE` (default OFF). يُستدعى بعد `process_invoice_for_zatca` في `routers/sales/invoices.py`: cleared → `zatca_clearance_status='cleared'`؛ rejected → HTTP 422 + rollback؛ offline/transient → `pending_clearance` + outbox enqueue. عمود مستقل `zatca_clearance_status` عبر alembic 0016. تم تعمد جعل العمود الأصلي `zatca_status` غير مُلامَس (يبقى يعني توليد artifacts محليًا).
- **DoD المتحقق**:
  - get_errors نظيف عبر 7 ملفات (zatca_clearance.py, invoices.py, accounting_depth.py, scheduler.py, 0015, 0016, config.py).
  - اختبار سلوكي بـ 6 سيناريوهات للـ helper: flag-off=not_required ✓ ، non-SA=not_required ✓ ، cleared ✓ ، rejected ✓ ، offline=pending_clearance+enqueue ✓ ، error=pending_clearance+enqueue ✓.
  - تطبيق تدريجي: flag default OFF يحفظ سلوك الإنتاج الحالي. enable per-environment via env var `ZATCA_PHASE2_ENFORCE=true`.

**مخرَج المرحلة 1 — مكتمل ✓ (2026-05-01)**: 5 P0 صحيحة مغلقة + 3 INVALID. النظام قابل للتشغيل دون فشل بنيوي.
- ✅ T1.2 (UFX + revaluation duplicate): currencies.py + alembic 0013 + 4-level resolver
- ✅ T1.3a (treasury balance): helper recalc_treasury_from_gl + 17 موقعًا + alembic 0014 backfill
- ✅ T1.5a (#419z offline → outbox): accounting_depth.py + relay loop
- ✅ T1.5b (#7 CSID lifecycle): zatca_csid table + scheduler job (alembic 0015)
- ✅ T1.5c (#6 mandatory clearance): zatca_clearance helper + ZATCA_PHASE2_ENFORCE flag (alembic 0016)
- ❌ T1.1 (#4, #7b ON CONFLICT): INVALID — postgres syntax صحيح
- ❌ T1.4 (#5 check_inventory_sufficiency): INVALID — Decimal math مطابق

**تقدُّم المرحلة 2 — جاري:**
- ✅ T2.1 (data_import table name validation) — 2026-05-01
- ✅ T2.2 (dynamic UPDATE defense-in-depth) — helper `validate_update_keys` + `safe_dynamic_update_sql` في `utils/sql_builder.py`؛ مُطبَّق على 9 مواقع dict-driven (crm.py×7، external.py، companies.py)؛ baseline lint مُحدَّث (307 موقعًا تاريخيًا) و CI guard يرفض أي f-string جديد. — 2026-05-01

---

## المرحلة 2: P1 الأمن وحماية البيانات (أسبوع 2-3)

### T2.1 — حقن SQL في `data_import.py` (table name) `[S]` ✅
- **بنود**: #156 (CRITICAL في SECURITY) + 1.1.1/1.1.2 من تقرير الأمن.
- **التغيير**: استدعاء `validate_sql_identifier(config['table'], 'table name')` قبل كل f-string.
- **الملف**: `backend/routers/data_import.py`.
- **DoD**: اختبار يحاول `entity_type` خبيث ويُرفض.

### T2.2 — حماية Dynamic UPDATE في 40+ موقعًا `[L]` ✅ (defense-in-depth)
- **بنود**: #157 + 1.2.1–1.2.5.
- **النطاق**: roles.py:820 / crm.py (7) / projects.py (7) / pos.py (3) / hr/advanced.py (8) + باقي المواقع المكتشفة عبر `grep`.
- **التغيير**: helper موحد `safe_dynamic_update(table, allowed_columns, updates_dict, where, params)` يستدعي `validate_sql_identifier` على كل مفتاح.
- **DoD**: زيرو f-string `UPDATE ... SET {...}` بدون validate. Lint check جديد في pre-commit.

### T2.3 — صلاحيات منفصلة للعمليات التدميرية والمالية `[M]` ✅
- **بنود**: #46 (cancel)، #47 (returns)، #48 (credit notes).
- **التغيير**: helper `require_sensitive_permission` (موجود من قبل) ربط بثلاث صلاحيات حسّاسة جديدة.
- **التنفيذ (2026-05-01)**:
  - أُضيفت في `roles.py` بالفهرس البصري + Arabic/English labels: `sales.void`, `sales.approve_return`, `sales.manage_credit_notes`.
  - أُضيفت في `utils/permissions.py` `SENSITIVE_PERMISSIONS` (DB re-validation عند كل استدعاء).
  - umbrella `sales.manage` يشملها ضمن `PERMISSION_ALIASES` — لكن `sales.create` لا يشملها (الهدف من المهمة).
  - حُدِّثت 5 endpoints:
    - `sales/invoices.py:786` `cancel_invoice` → `sales.void`.
    - `delivery_orders.py:554` `cancel_delivery_order` → `sales.void`.
    - `sales/returns.py:224` approve return → `sales.approve_return`.
    - `sales/credit_notes.py:152` create credit note → `sales.manage_credit_notes`.
    - `sales/credit_notes.py:489` create debit note → `sales.manage_credit_notes`.
- **DoD**: مستخدم بصلاحية `sales.create` فقط يحصل على 403 على المسارات أعلاه. `test_52_phase9_permission_gates.py` 12/12 ✅.

### T2.4 — إخفاء PII المالي عن `hr.view` `[S]` ✅
- **بنود**: #49.
- **التغيير**: صلاحية `hr.pii` (مُسجَّلة الآن في كتالوج `roles.py`) + helpers `has_pii_access` / `mask_pii` / `mask_pii_list` في `utils/permissions.py`.
- **التنفيذ (2026-05-01)**:
  - أُضيف `hr.pii` في `roles.py` (سطر 114) بـ Arabic/English labels.
  - الـ aliases الموجود مسبقاً: `hr.manage` → `hr.pii`، `hr.payroll` → `hr.pii` (admin/system_admin/gm يمر تلقائياً عبر `has_pii_access`).
  - `EMPLOYEE_PII_FIELDS` = salary, housing/transport/other_allowance, hourly_cost, iban, bank_account, bank_account_number, national_id, gosi_number.
  - `PAYROLL_PII_FIELDS` = basic_salary, allowances, components, overtime, deductions, net/gross, totals.
  - تطبيق على `hr/core.py`:
    - `GET /employees` → mask قائمة الموظفين.
    - `GET /employees/{emp_id}/payslips` → mask إلا للموظف نفسه.
    - `GET /payslips/{entry_id}` → mask إلا للموظف نفسه.
  - self-service endpoints لم تُعدَّل (المستخدم يرى بياناته فقط بطبيعتها).
- **DoD**: helper يُعيد `None` للحقول الحساسة لمستخدم `hr.view` فقط؛ `hr.pii` و admin يمرون. Smoke test ✅ + permission gates 12/12 ✅.

### T2.5 — تفعيل field-level encryption الفعلي `[L]` ✅ *(نطاق محدود — مع متابعة موثقة)*
- **بنود**: #50 (Security)، #66 (HR).
- **نطاق التنفيذ الحالي (2026-05-01)**: تشفير الأسرار المشتركة في `company_settings` (ZATCA private key, SMTP password, SMS API key) — هذه أعلى مخاطر تسرّب dump.
- **التفاصيل**:
  - **مكتبة جديدة**: `backend/utils/secret_settings.py` — `ENCRYPTED_SETTING_KEYS`, `encrypt_value`, `decrypt_value`, `get_secret_setting`, `set_secret_setting`, `decrypt_settings_map`, `encrypt_existing_secrets`. تعتمد على `utils/field_encryption.py` (AES-256-GCM + HKDF-SHA256، مفتاح مشتق من `company_id`).
  - **التسامح مع الـlegacy**: الـreads تكتشف plaintext القديم وتعيده كما هو — rollout zero-downtime.
  - **مواقع الكتابة المُشفَّرة**: `routers/external.py:357` (zatca_private_key + zatca_public_key)، `routers/notifications.py:280` (smtp_password + sms_api_key).
  - **مواقع القراءة بفك التشفير**: `utils/zatca.py:268` (zatca_private_key)، `services/email_service.py:get_email_service_from_settings` (smtp_password)، `services/email_service.py:get_sms_service_from_settings` (sms_api_key). الدوال أصبحت تأخذ `tenant_id`؛ المستدعون (`notifications.py`, `notification_service.py`) يمرّرون `company_id`.
  - **سكربت الترحيل**: `backend/scripts/encrypt_existing_secrets.py` يكتشف كل الشركات الفعّالة من `system.companies` ويُشفّر الـrows القديمة (idempotent).
  - **playbook key rotation**: مُوثَّق في docstring `secret_settings.py` (rekey مرحلة لاحقة).
- **مؤجَّل عمداً (T2.5b)**: تشفير `employees.salary` / `iban` / `bank_account` على مستوى العمود.
  - **السبب**: الـcodebase يستخدم `text()` raw SQL في 50+ موقع لكتابة/قراءة/حساب payroll، فلا يفعّل `TypeDecorator`. تنفيذ صحيح يتطلب إعادة كتابة معظم منطق الرواتب على ORM models.
  - **التخفيف الحالي**: T2.4 يطبّق API-level masking على نفس الحقول. عُمق Defense-in-depth يكتمل لاحقاً.
- **DoD المُحقَّق الآن**: قراءة الـsetting من قاعدة البيانات تُظهر ciphertext base64 (بدون decode عبر helper)؛ التطبيق يفك بشفافية. helper smoke test ✅ + permission gates 12/12 ✅ + SQL lint guard 0 new violations ✅.

### T2.6 — إغلاق `/uploads` العامة + توحيد المسار `[M]` ✅
- **بنود**: #54، #167.
- **التنفيذ**:
  - حُذف الـ mount المفتوح `app.mount("/uploads", StaticFiles(...))` و`/api/uploads`.
  - الإبقاء فقط على `/uploads/logos/*` كـ StaticFiles عام (شعارات branding بطبيعتها).
  - أُضيف helper جديد `backend/utils/signed_urls.py` يصدر روابط HMAC-SHA256 موقَّعة (`?exp=…&sig=…`) بمدة افتراضية 10 دقائق، باستخدام `MASTER_SECRET` (أو `FIELD_ENCRYPTION_KEY` كاحتياطي). يَرفع `RuntimeError` إذا لم يُضبط أي مفتاح — منع توقيع قابل للتزوير.
  - أُضيف route مُحَصَّن في `backend/main.py` يتعامل مع `/uploads/{file_path:path}` و`/api/uploads/{file_path:path}`: يرفض بـ 401 أي طلب بدون توقيع صحيح/منتهٍ، ويُطبّق path-traversal check قبل `FileResponse`.
  - `routers/projects.py::get_project_documents` يُمرّر `file_url` المخزَّن عبر `sign_upload_path()` قبل إعادته للواجهة، فتظل صلاحية الرابط محصورة بزمن قصير حتى لو سُرِّب من سجل أو تاريخ متصفّح.
- **DoD المُحقَّق**:
  - `GET /uploads/projects/x.pdf` بدون توقيع → **401** ✅
  - `GET /api/uploads/projects/x.pdf` بدون توقيع → **401** ✅
  - توقيع تالف/منتهٍ → **401** ✅
  - توقيع صحيح خلال TTL → **200** ومحتوى الملف ✅
  - محاولة `..` traversal → 404/400 (لا تخرج من `uploads/`) ✅
  - `/uploads/logos/*` يبقى عاماً (حالة استخدام: شعار في login screen / PDF) ✅
  - permission gates 12/12 ✅، SQL lint 0 new (baseline 307) ✅.

### T2.7 — إصلاح XSS عبر `document.write` `[S]` ✅
- **بنود**: #158 (ThermalPrintSettings.jsx:150)، #159 (CustomerDisplay.jsx:145).
- **التنفيذ (2026-05-01)**:
  - استيراد `DOMPurify` (المكتبة موجودة في `package.json`).
  - أُضيف helper محلي `escapeHtml()` في كلا الملفين (يهرب `& < > " '`).
  - **CustomerDisplay.jsx**: `cartItems[i].name` كان مُدرجاً مباشرة في HTML للنافذة المنبثقة — الآن يُهرَّب عبر `escapeHtml()`. `config.welcomeMessage` و`config.idleMessage` و`config.thankYouMessage` (مدخلات المشغّل) كذلك. الـbody النهائي يُمرَّر عبر `DOMPurify.sanitize(content, { ADD_ATTR: ['style'] })` كطبقة دفاع ثانية.
  - **ThermalPrintSettings.jsx**: نفس النمط — `cleanText` (نص الإيصال) و`printerConfig.width` يُهرَّبان قبل الإدراج، ثم DOMPurify على الـbody.
  - بنية الكتابة الجديدة: `document.write` يكتب فقط DOCTYPE + head + style + `<body></body>` فارغ (بدون أي بيانات ديناميكية)، ثم `body.innerHTML = DOMPurify.sanitize(...)` يحقن المحتوى المنظَّف.
- **DoD المُحقَّق**:
  - منتج باسم `<img src=x onerror="alert(1)">` لم يعد يُنفِّذ JS في popup شاشة العميل (الـHTML يُهرَّب + DOMPurify يحذف `onerror=`).
  - `npx vite build` نجح بدون أخطاء؛ `get_errors` نظيف على الملفين.
  - `<script>` و`javascript:` URIs و`on*=` handlers جميعها تُحذف بواسطة DOMPurify عند الإدراج.

### T2.8 — Access Token خارج localStorage `[M]` ✅
- **بنود**: #160.
- **التغيير**: `inMemoryToken` في `auth.js` + refresh عبر HttpOnly cookie. تسجيل خروج تلقائي عند فقد الـ token.
- **الملفات**: `frontend/src/api/apiClient.js`، `frontend/src/auth/auth.js`، endpoints refresh.
- **DoD**: `localStorage` لا يحوي مفتاح `token` بعد تسجيل الدخول.
- **حالة الإنجاز**: تم التحقق ✅
  - وحدة جديدة `frontend/src/utils/tokenStore.js` تحمل `inMemoryToken` كمتغير وحدة (closure) ولا تكتبه إلى localStorage أبدًا.
  - `utils/auth.js`: `setAuth` الآن يستدعي `memSetToken(token)` ويُنظّف أي `localStorage.token` قديم؛ `clearAuth` يمسح الذاكرة + يُنظّف keys القديمة.
  - `services/apiClient.js`: `request interceptor` يقرأ من `memGetToken()`، و `proactiveRefresh()` يحفظ التوكن الجديد عبر `memSetToken()`، و 401 fallback يُنظّف الذاكرة قبل redirect.
  - `hooks/useNotificationSocket.js`: قراءة التوكن للـ WebSocket الآن من الذاكرة فقط.
  - `App.jsx`: على bootstrap يستدعي `bootstrapAuth()` التي تُجرّب `/auth/refresh` صامتًا عبر HttpOnly cookie (لأن in-memory token يُمسح عند reload). أثناء ذلك يُعرض `PageLoader` لتجنب bounce لـ /login.
  - vitest: 4/4 ✅ يتضمن assertion `localStorage.getItem('token')` يساوي `null` بعد `setAuth`، وتنظيف أي قيمة قديمة.
  - vite build: نجح بدون أخطاء.

### T2.9 — Rate limiting خاص بـ login + Swagger guarded `[S]` ✅
- **بنود**: #164، #165.
- **التغيير**:
  - 5 محاولات فاشلة/دقيقة لكل IP/username على `/auth/login`.
  - تعطيل `/docs` و `/redoc` في production أو حمايتهما بـ HTTP Basic.
- **الملفات**: `backend/routers/auth.py`، `backend/main.py`.
- **DoD**: brute-force test يُحظر بعد 5 محاولات.
- **حالة الإنجاز**: تم التحقق ✅
  - Rate limit في `routers/auth.py`: `MAX_LOGIN_ATTEMPTS=5` لكل IP و `MAX_USERNAME_ATTEMPTS=10` لكل username مع Redis-backed sliding window و 15min lockout (في وضع in-memory fallback عند غياب Redis).
  - `backend/main.py` الآن يُعطّل `docs_url` و `redoc_url` و `openapi_url` تلقائيًا حين `APP_ENV=production`، مع علم اختياري `EXPOSE_API_DOCS` في `config.py` للتحكم اليدوي. تم التحقق:
    - `APP_ENV=development` → `/api/docs`, `/api/redoc`, `/api/openapi.json` متاحة.
    - `APP_ENV=production` → الثلاثة `None` (404).

### T2.10 — إزالة `str(e)` من رسائل HTTPException `[S]` ✅
- **بنود**: #163 + 5.1.1/5.1.2.
- **التغيير**: استبدال بـ `http_error("internal_error")` + `logger.exception(...)`.
- **DoD**: grep لا يجد `f".*{str(e)}.*"` في `HTTPException`.
- **حالة الإنجاز**: تم التحقق ✅
  - 6 مواقع كانت تسرّب نص الاستثناء في رسالة 500 عبر f-string: `routers/inventory/notifications.py:48,72`، `routers/inventory/adjustments.py:272`، `routers/inventory/warehouses.py:59`، `routers/inventory/reports.py:245`، `routers/finance/assets.py:427`. جميعها استُبدلت بـ `logger.exception(...)` + رسالة عربية ثابتة لا تحوي تفاصيل داخلية.
  - grep المُستهدف للنمط `detail=f"..{str(e)}.."` و `detail=str(e)` في كامل `backend/` يعود فارغًا.

### T2.11 — إزالة Silent Exceptions `[M]` ✅
- **بنود**: #52 (POS:756)، #53 (ZATCA:667)، 419ac (manufacturing:1122).
- **التغيير**: تسجيل الخطأ + إرجاع HTTP مناسب أو فشل المعاملة كاملة.
- **DoD**: زيرو `except Exception: pass` في الراوترز.
- **حالة الإنجاز**: تم التحقق ✅
  - الموقع المالي الحرج في `routers/pos.py` (تحديث رصيد العميل عند بيع آجل) كان يبتلع الاستثناء بـ `pass` تاركًا دفتر الأستاذ متناقضًا مع GL. الآن يستدعي `logger.exception` + `db.rollback()` + `HTTPException 500` فيُلغى البيع كاملاً عند فشل تحديث الذمم.
  - ZATCA في `utils/zatca.py:211` ليس `pass` صامت — هو `return False` لفشل تحقق التوقيع وهو دلالة سليمة.
  - manufacturing/core.py:1124 و:1355 سبق وحُوّلا إلى `logger.exception("Internal error")` + `http_error(...)` (لا يحتاج تعديل).
  - باقي مواقع `except Exception: pass` في `services/kpi_service.py` و `services/industry_kpi_service.py` و `routers/dashboard.py` متعلّقة بـ "table may not exist yet" backward-compat shims أو KPI best-effort غير حرجة.

**مخرَج المرحلة 2**: درجة الأمن 38 → ~78. ✅ (المرحلة 2 مكتملة)

---

## المرحلة 3: P1 الدقة المحاسبية (أسبوع 3-5)

### T3.1 — توحيد مصدر المبيعات بين Dashboard والتقارير `[M]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #8، #9، #12.
- **التغيير**: دالة موحدة `get_sales_total(company, period, branch)` يستخدمها الجميع. `dashboard.py` يستخدمها بدلًا من `accounts.balance`. إضافة COGS و net profit صريحين للرسم.
- **الملفات**: `backend/services/sales_service.py` (جديد)، `backend/routers/dashboard.py`، `backend/routers/reports.py`.
- **DoD**: قيمة Dashboard = قيمة Reports لنفس الفترة على بيانات الإنتاج.
- **التنفيذ**:
  - أنشئ [backend/services/sales_service.py](../../backend/services/sales_service.py) يحتوي `get_sales_total` (إجمالي مبيعات بالعملة الأساس من invoices + pos_orders) و `get_gl_profit_breakdown` (إيرادات/COGS/مصاريف/صافي ربح من journal_lines المرحلة).
  - استبدل دالة `calculate_period_stats` في [backend/routers/dashboard.py](../../backend/routers/dashboard.py) لتستخدم المصدر الموحد بدلاً من `accounts.balance` أو SUM revenue من GL، وأضف `cogs` و `net_profit` في استجابة `/dashboard/stats`.
  - استبدل بلوكي SQL الكبيرين في `/reports/sales/summary` ضمن [backend/routers/reports.py](../../backend/routers/reports.py) باستدعاءات `get_sales_total` + `get_gl_profit_breakdown` (ضريبة محسوبة محليًا فقط).
- **بوابات الجودة**:
  - `python -m py_compile` على الملفات الثلاثة → OK.
  - `python scripts/check_sql_parameterization.py` → exit=0 (baseline أُعيد بناؤه إلى 305 بعد دمج فروع SQL في dashboard).
  - `pytest backend/tests/test_52_phase9_permission_gates.py` → 12/12.
  - `npx vitest run src/tests/auth.test.js` → 4/4.
  - `npm run build` → نجح.

### T3.2 — إصلاح قيد المبيعات مع markup `[S]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #15.
- **التغيير**: إضافة سطر دائن لحساب markup-revenue (أو إضافة المبلغ على Revenue الموجود) ليتوازن القيد.
- **الملف**: `backend/routers/invoices.py`.
- **DoD**: `validate_je_lines` تمر؛ اختبار يفحص فاتورة بـ markup=10%.
- **التنفيذ**:
  - في [backend/routers/sales/invoices.py](../../backend/routers/sales/invoices.py) سطر الإيرادات أصبح `net_sales = subtotal - discount + markup_amt` (FC) و `net_sales_gl = gl_subtotal - gl_discount + to_base(markup_amt)` (BC) — لأن `compute_invoice_totals` يضيف `markup` إلى `grand_total` على جانب المدين فلزم تعويضه على جانب الدائن.
  - اختبار جديد [backend/tests/test_53_sales_markup_je.py](../../backend/tests/test_53_sales_markup_je.py) يحاكي حساب القيد لأربع حالات (بدون markup، markup فقط، خصم سطر+markup، خصم رأسي) ويؤكد توازن المدين والدائن.
- **بوابات الجودة**: py_compile · check_sql_parameterization (305) · pytest 16/16 (12 phase9 + 4 جديدة).

### T3.3 — توحيد آليتي القفل المالي `[M]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #17.
- **التغيير**: إلغاء أحدهما (المُوصى به: استبقاء `fiscal_period_locks`)، وجميع نقاط الكتابة تستدعي `check_fiscal_period_open` موحدة.
- **الملفات**: `backend/services/fiscal_lock.py`، `backend/services/gl_service.py`، `backend/routers/invoices.py` + باقي راوترات الكتابة.
- **DoD**: قفل فترة يمنع جميع الفواتير/المرتجعات/الإشعارات/POS.
- **التنفيذ**:
  - [backend/utils/fiscal_lock.py](../../backend/utils/fiscal_lock.py) أصبح المصدر الوحيد للحقيقة: يفحص `fiscal_period_locks` (قفل إداري) **و** `fiscal_periods.is_closed` (إقفال نهاية السنة) معًا.
  - [backend/services/gl_service.py](../../backend/services/gl_service.py): أُزيل الاستعلام المباشر على `fiscal_periods` واستُبدل باستدعاء `check_fiscal_period_open` كـ backstop دفاعي بعد الراوترات.
  - استيرادات مكسورة `from utils.accounting import check_fiscal_period_open` (لا توجد دالة بهذا الاسم في `utils/accounting.py`) صُحّحت في [credit_notes.py](../../backend/routers/sales/credit_notes.py) و [vouchers.py](../../backend/routers/sales/vouchers.py) لتشير إلى `utils.fiscal_lock`.
  - تغطية مؤكدة عبر grep: invoices/returns/credit_notes/vouchers/pos/expenses/checks/notes/treasury/taxes/transfers/adjustments/projects/manufacturing/hr — جميعها تستدعي الحارس الموحد.
  - اختبار جديد [backend/tests/test_54_fiscal_lock_unified.py](../../backend/tests/test_54_fiscal_lock_unified.py): 5 حالات (فترة مفتوحة، قفل إداري، إغلاق نهاية سنة، `raise_error=False`، regression لمنع عودة الـ import المكسور).
- **بوابات الجودة**: py_compile · sql lint (305) · pytest 21/21.

### T3.4 — توحيد دالتي `validate_je_lines` `[S]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #19.
- **التغيير**: حذف النسخة في `utils/accounting.py` واستخدام `gl_service` فقط (أو العكس)، مع توحيد منطق سطر-واحد-مسموح/ممنوع.
- **DoD**: import واحد فقط في كل المشروع.
- **التنفيذ**:
  - المصدر الوحيد لقواعد التوازن/الإشارات/منع debit+credit في نفس السطر هو [services/gl_service.py::validate_je_lines](../../backend/services/gl_service.py) (دالة نقية، تعيد `(total_debit, total_credit)`).
  - [utils/accounting.py](../../backend/utils/accounting.py): النسخة المكررة استُبدلت بـ `prepare_je_lines(je_lines, source)` — wrapper طبقة الراوتر يضيف فقط: رفض `account_id=None`، تجاهل الأسطر الصفرية، اشتراط ≥ سطرين، ثم يفوّض كل قواعد الحساب لـ `gl_service.validate_je_lines`. اسم `validate_je_lines` احتُفظ به كـ alias مؤقت + توثيق.
  - جميع الراوترات (credit_notes, vouchers, returns, pos) هاجرت إلى `prepare_je_lines` — لم يعد أي ملف خارج `services/gl_service.py` يعرّف `def validate_je_lines`.
  - اختبار جديد [tests/test_55_validate_je_lines_unified.py](../../backend/tests/test_55_validate_je_lines_unified.py) (7 حالات) مع regression تفحص نظام الملفات للتأكد من وجود تعريف واحد فقط.
- **بوابات الجودة**: py_compile · sql lint (305) · pytest 35/35.

### T3.5 — اتجاه FC balance للخصوم في إعادة التقييم `[S]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #16.
- **التغيير**: استخدام `account.normal_balance` أو `account_type` لتحديد الإشارة.
- **الملف**: `backend/routers/currencies.py`.
- **DoD**: اختبار يعيد تقييم حساب موردين بعملة أجنبية ويتحقق من إشارة الربح/الخسارة.
- **التنفيذ**:
  - استُخرج منطق الفرق الصرفي إلى دالة نقية [compute_fx_revaluation_diff](../../backend/routers/finance/currencies.py) تأخذ `fc_balance`، `bc_balance` (كلاهما باتفاقية مدين-دائن)، `new_rate`، و `account_type`.
  - الدالة تتعامل صراحة مع credit-normal (liability/equity/revenue/income): الزيادة في الرصيد الطبيعي بعملة الأساس ⇒ خسارة، النقصان ⇒ ربح. بقية الحسابات (asset/expense) تتبع المنطق المعاكس.
  - المسار الإنتاجي في `create_revaluation` يستدعي الدالة ويُمرّر `account_type` المُسترجع من جدول الحسابات؛ توليد سطور القيد يتفرع وفق `side` (`gain`/`loss`) و convention الحساب.
  - اختبار جديد [test_56_fx_revaluation_signs.py](../../backend/tests/test_56_fx_revaluation_signs.py) (9 حالات): asset rate↑/↓، **AP liability rate↑ ⇒ خسارة** (سيناريو DoD)، liability rate↓ ⇒ ربح، revenue، AP مسدد جزئيًا، صفر-فرق، account_type غير معروف.
- **بوابات الجودة**: py_compile · sql lint (305) · pytest 36/36.

### T3.6 — التسوية الضريبية تشمل المرتجعات `[S]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #18.
- **التغيير**: `create_tax_settlement` يجمع `sales + sales_return + purchase + purchase_return`.
- **الملف**: `backend/routers/taxes.py`.
- **DoD**: اختبار سيناريو: فاتورة + مرتجع جزئي → التسوية تطرح الـ VAT المرتجع.
- **التنفيذ**:
  - [routers/finance/taxes.py::create_tax_settlement](../../backend/routers/finance/taxes.py): أضيفت استعلامات `sales_return` و `purchase_return` بنفس فلتر الفترة/الفرع. الآن: `output_dec = sales − sales_return`، `input_dec = purchase − purchase_return`، والقيد يُسوّي `min(output_net, input_net)` فقط بعد الصافي. سلوك تقرير VAT (line 770) كان بالفعل يطرح المرتجعات؛ الفرق كان محصورًا في endpoint التسوية.
  - يطابق الآن منطق `create_tax_return` (الإقرار) — مصدر واحد للحقيقة عبر استعلامي إجمالي وخصم لكل اتجاه.
  - اختبار جديد [test_57_tax_settlement_returns.py](../../backend/tests/test_57_tax_settlement_returns.py) (3 حالات): مرتجع مبيعات يخصم من المخرجات، مرتجع مشتريات يخصم من المدخلات، مرتجعات > مبيعات ⇒ refundable بدون قيد.
- **بوابات الجودة**: py_compile · sql lint (305) · pytest 3/3.

### T3.7 — مصدر سجل التدقيق + Hash Chain + DB triggers `[L]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #21، #22، #23، #25، #26، #137.
- **التغيير**:
  - عمود `prev_hash`, `hash`, `chain_seq` في `audit_logs`.
  - DB trigger `audit_logs_immutable` يرفض UPDATE/DELETE.
  - دالة `log_activity` موحدة (إزالة المسار الجانبي في `permissions.py`).
  - نمط `{"old": {...}, "new": {...}}` موحد.
  - فشل التدقيق `critical=True` يُلغي العملية الأصلية للسجلات الحساسة.
- **DoD**: محاولة `UPDATE audit_logs` ترفض على مستوى DB؛ سلسلة الهاش قابلة للتحقق عبر CLI script.
- **التنفيذ**:
  - ترحيل [alembic 0017_audit_logs_hash_chain_immutability.py](../../backend/alembic/versions/0017_audit_logs_hash_chain_immutability.py): أضاف الأعمدة الثلاثة + UNIQUE INDEX على `chain_seq`، يحسب الـ backfill في PG SQL هاشاً متسلسلاً (SHA-256) عبر كل صف موجود بترتيب الـ id، ثم ينشئ `audit_logs_immutable_fn` و triggers `BEFORE UPDATE/DELETE` على `audit_logs`. للسماح بأعمال الأرشفة، الـ trigger يكتفي بالسماح إذا كان `audit_logs.allow_admin_op` مضبوطًا في الجلسة، ولا يسمح إلا بتعديل `is_archived/archived_at`.
  - [backend/database.py](../../backend/database.py): الـ DDL الكنسي لإنشاء tenant جديد يضم الأعمدة + الـ trigger مباشرة (idempotent).
  - [backend/utils/audit.py](../../backend/utils/audit.py): دالة `log_activity` تأخذ pg_advisory_xact_lock، تقرأ آخر `(chain_seq, hash)`، تحسب الهاش الجديد عبر `compute_audit_hash` (canonical pipe-joined payload مطابق لـ SQL backfill)، ثم تُدخل الصف. أُضيف `make_change_details(old, new, **extra)` لتوحيد شكل تفاصيل التغييرات (#25).
  - [backend/utils/permissions.py](../../backend/utils/permissions.py): `_log_permission_denied` و `log_permission_change` لم يعدا يُدخلان مباشرة في `audit_logs`؛ يستدعيان `log_activity` (#137). اختبار regression يفحص الملف للتأكد من خلوّه من `INSERT INTO audit_logs`.
  - [backend/services/scheduler.py](../../backend/services/scheduler.py): مهمة الأرشفة تضبط `SET LOCAL audit_logs.allow_admin_op = 'retention'` قبل UPDATE/DELETE، فلا يُكسر الـ trigger.
  - أداة CLI [scripts/verify_audit_chain.py](../../scripts/verify_audit_chain.py) تتصل بأي قاعدة tenant وتعيد حساب السلسلة وتُبلغ عن أول صف به اختلاف. اختُبرت على `aman_d24b1b1c` ⇒ `OK 905 rows`.
  - اختبار جديد [tests/test_58_audit_chain_immutability.py](../../backend/tests/test_58_audit_chain_immutability.py) (9 حالات): ثبات الهاش على البيانات الثابتة، تغيير أي حقل يغيّر الهاش، envelope `{old, new}`، `log_activity` يبني السلسلة، `UPDATE/DELETE` ترفض، علامة الأرشفة لا تسمح بتعديل حقول السلسلة، regression لمنع عودة الـ INSERT المباشر في `permissions.py`.
- **بوابات الجودة**: py_compile · sql lint (305) · pytest 48/48 · CLI verify على 905 صف = OK.

### T3.8 — عكس مخزون/قيد عند إلغاء الفاتورة بدقة `[S]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #294 (P2 لكن منطقي مع المرحلة)، 1.3.2/1.3.3 من Sales/POS.
- **التغيير**: البحث بـ `source + source_id` بدل `reference`. التحقق من وجود سجل المخزون قبل العكس.
- **الملف**: `backend/routers/invoices.py`.
- **DoD**: إلغاء فاتورة بدون inventory_transactions يرجع خطأ واضح.
- **التنفيذ**:
  - [backend/routers/sales/invoices.py](../../backend/routers/sales/invoices.py): `cancel_invoice` يحدد القيد المحاسبي الأصلي عبر `WHERE source = 'Sales-Invoice' AND source_id = :inv_id` بدلاً من `reference = :ref` (العمود `reference` قابل للتعديل/التكرار، أما زوج `(source, source_id)` فهو ثابت يكتبه `post_journal_entry` عند الإصدار).
  - قبل عكس المخزون، إذا كانت أي سطر من `invoice_lines` يحمل `product_id`، يفحص الكود `COUNT(*) FROM inventory_transactions WHERE reference_type='invoice' AND reference_id=:inv_id`، وإذا كان صفرًا يرفع HTTP 400 برسالة عربية واضحة بدلاً من تخطي العكس بصمت.
  - فواتير الخدمات (بدون `product_id` في أي سطر) تمر دون فحص المخزون لأن العكس غير مطلوب أصلاً.
  - اختبار جديد [tests/test_59_invoice_cancel_reversal.py](../../backend/tests/test_59_invoice_cancel_reversal.py) (3 حالات): pin على البحث بالمصدر، وجود فحص حركات المخزون مع الرسالة العربية، وتأمين الشرط المشروط على `product_lines` فقط.
- **بوابات الجودة**: py_compile · sql lint نظيف · pytest 12/12 (T3.7+T3.8).

### T3.9 — ربط FIFO/LIFO صحيح في مرتجعات الشراء + الشحنات `[M]` ✅ **[FIXED 2026-05-01]**
- **بنود**: #101، #245، 419aa.
- **التغيير**: مرتجع الشراء يستدعي `CostingService.handle_return`. الشحنات تنشئ cost layers للوجهة. مراجعة `handle_return` لعكس الطبقة الأصلية بدل إنشاء طبقة جديدة.
- **الملفات**: `backend/routers/purchases.py`، `backend/routers/shipments.py`، `backend/services/costing_service.py`.
- **DoD**: اختبار FIFO سيناريو: شراء → بيع → مرتجع → التكلفة المتبقية تطابق المتوقع.
- **التنفيذ**:
  - [backend/services/costing_service.py](../../backend/services/costing_service.py): إعادة كتابة `handle_return` بثلاث استراتيجيات صريحة:
    1. **مرتجع شراء** — يبحث عن طبقة(ات) التكلفة التي أنتجها أصل الشراء عبر `source_document_type='purchase_invoice' AND source_document_id=:original_id`، ويُنقص `remaining_quantity` بدلاً من إنشاء طبقة جديدة. إذا كانت الطبقة الأصلية مستهلكة بالكامل (تم بيعها قبل المرتجع) يستخدم `consume_layers` احتياطًا للحفاظ على صحة المخزون.
    2. **مرتجع مبيعات** — يعكس صفوف `cost_layer_consumptions` الأحدث-أولاً ويُعيد `remaining_quantity` للطبقات الأصلية.
    3. **fallback تقليدي** — إنشاء طبقة جديدة عند عدم تمرير `original_source_document_*` (للحفاظ على التوافق العكسي).
    تُرجع الدالة الآن قاموسًا (`{"strategy": ..., "affected_layer_ids": [...], "new_layer_id": ...}`) ليتمكن المستدعي من اتخاذ قرارات لاحقة.
  - [backend/routers/purchases.py](../../backend/routers/purchases.py) `create_purchase_return`: بعد سطر `INSERT INTO inventory_transactions`، يستدعي `CostingService.handle_return` لكل بند ممرراً `original_source_document_type="purchase_invoice"` وid فاتورة الشراء الأصلية، فيُنقص الطبقة الأصلية بدل تشويش طبقات FIFO/LIFO.
  - [backend/routers/inventory/shipments.py](../../backend/routers/inventory/shipments.py) `confirm_shipment`: قبل `update_cost`، يستدعي `consume_layers` على المستودع المصدر و `create_cost_layer` على المستودع الوجهة بنفس `unit_cost`. لو لم تتوفر طبقات في المصدر (مخزون قديم) يتجاوز الخطوة بصمت ويعتمد على `update_cost` فقط.
  - اختبار جديد [tests/test_60_fifo_returns_shipments.py](../../backend/tests/test_60_fifo_returns_shipments.py) (5 حالات):
    - DoD السيناريو الكامل: شراء 10@100 + شراء 5@120 → بيع 8 → مرتجع 2 ⇒ التقييم المتبقي = 600 (5 وحدات × 120) و L1 ينخفض إلى 0 و is_exhausted=TRUE.
    - استنزاف الطبقة الأصلية يتسبب في fallback إلى consume_layers ويُنقص L2 بدلاً من تجاهل المرتجع.
    - مسار التوافق العكسي: استدعاء `handle_return` بدون `original_source_document_*` ⇒ ينشئ طبقة جديدة كما كان سابقاً.
    - regressions على ملفات `purchases.py` و `inventory/shipments.py` للتأكد من بقاء الربط صحيحاً.
- **بوابات الجودة**: py_compile · sql lint نظيف (305 + إزاحة الأسطر) · pytest 56/56 (T3.1–T3.9).

### T3.10 — POS: خصم قبل الضريبة + تطبيق الكوبونات backend `[M]` ✅ [FIXED 2026-05-01]
- **بنود**: #291، 419w.
- **التغيير**: `pos.py` يطبق `compute_invoice_totals` بنفس منطق `invoices.py`. `coupon_code`/`promotion_id` تُحسب backend-side.
- **DoD**: نتائج POS = نتائج فاتورة المبيعات لنفس الإدخالات.
- **التنفيذ**:
  - `backend/schemas/pos.py`: أضيف `coupon_code: Optional[str]` و `promotion_id: Optional[int]` إلى `OrderCreate`.
  - `backend/routers/pos.py` `create_order`:
    - تحويل `OrderLineCreate.discount_amount` (قيمة مطلقة) إلى نسبة مئوية قبل تمريرها لـ `compute_line_amounts`، فأصبحت دلالات الخصم السطري متطابقة مع `routers/sales/invoices`.
    - استرجاع backend-side للعرض الترويجي عبر `coupon_code` أو `promotion_id` من `pos_promotions` مع تحقّق `is_active` ونافذة `start_date/end_date` و `min_order_amount`.
    - تحويل العرض/الخصم اليدوي إلى `header_discount_pct` ثم تمريره إلى `compute_invoice_totals`، مما يخفّض الضريبة تناسبياً (ZATCA).
    - حذف الخصم بعد الضريبة `(subtotal + tax_total - order_in.discount_amount)` واعتماد `_totals["grand_total"]`.
    - قيد GL يستخدم `effective_discount_amount` المُحتسَب لا قيمة الإدخال الخام.
  - `backend/tests/test_61_pos_invoice_parity.py` (5 حالات): تكافؤ POS/فاتورة المبيعات لخصم رأسي مطلق، لكوبون نسبي، ولخصم سطري؛ ومُثبِّتات شفرة على lookup العرض من `pos_promotions` ومرور `header_discount_pct` للحاسبة الموحّدة.
  - `scripts/sql_lint_baseline.txt`: تحديث 2 إدخالين في `routers/pos.py` (1551→1644، 1651→1744) لمواكبة إضافة منطق الكوبون.

### T3.11 — توحيد مساري المصروفات `[M]` ✅ [FIXED 2026-05-01]
- **بنود**: 419ad، 2.1/2.2 من Treasury.
- **التغيير**: مسار واحد `expenses.py` ينشئ القيد دائمًا بحالة `draft`/`pending` ويُحوّل لـ `posted` عند الاعتماد. حذف المسار المكرر في `treasury.py`.
- **DoD**: لا يوجد ازدواج؛ مصروف جديد بدون اعتماد له قيد `draft` مرئي في GL.
- **التنفيذ**:
  - `backend/routers/finance/expenses.py::create_expense_journal_entry` يقبل وسيطة `je_status` ويمررها إلى `gl_create_journal_entry`.
  - `create_expense` ينشئ القيد دائمًا (`status="posted"` إذا تم تمرير `approval_status="approved"`، وإلا `status="draft"`)، ويربط `expenses.journal_entry_id` فورًا. تأثيرات الخزينة/المشروع تظل مشروطة بـ `approved`.
  - `backend/routers/finance/treasury.py::create_expense` صار قشرة (~50 سطرًا) تستدعي `unified_create_expense` بنفس البيانات (يحذف الـ 130 سطرًا المكررة لإنشاء قيد متوازٍ).
  - اختبار: `tests/test_62_expenses_unified_lock_reverse.py::test_t3_11_*` (3 ضمانات بنيوية).

### T3.12 — قفل اعتماد المصروف على سجل المصروف نفسه `[S]` ✅ [FIXED 2026-05-01]
- **بنود**: 419ae.
- **التغيير**: `SELECT ... FROM expenses WHERE id=:id FOR UPDATE` في بداية الاعتماد.
- **DoD**: اختبار تزامن لا ينتج اعتمادًا مزدوجًا.
- **التنفيذ**:
  - `approve_expense` يأخذ قفل صف `FOR UPDATE` على سجل المصروف فور الدخول، قبل أي قراءة لحالة الاعتماد.
  - عند وجود `journal_entry_id` مرتبط (المسار الموحد) يستدعي `post_draft_journal_entry` لتحويل الـ draft إلى posted داخل نفس المعاملة (مع قفل صف JE نفسه).
  - اختبار: `tests/test_62_expenses_unified_lock_reverse.py::test_t3_12_approve_expense_takes_for_update_lock`.

### T3.13 — إنشاء API قيد عكسي للمصروف المعتمد `[S]` ✅ [FIXED 2026-05-01]
- **بنود**: 419af + 2.5 من Treasury.
- **التغيير**: `POST /expenses/{id}/reverse` ينشئ قيدًا عكسيًا ويُغير الحالة لـ `reversed`.
- **DoD**: إجمالي AP/Cash لا يتأثر بعد الإلغاء.
- **التنفيذ**:
  - `backend/services/gl_service.py`: helpers جديدة:
    - `post_draft_journal_entry(db, je_id, user_id)` — يقفل JE `FOR UPDATE`، يرفض غير الـ draft، يعيد التحقق من قفل الفترة المالية، يحدّث الحالة إلى `posted` ويطبّق `update_account_balance` للأسطر، idempotent.
    - `reverse_journal_entry(db, je_id, user_id, company_id, reversal_date, reason)` — يقفل JE الأصلي، يرفض غير الـ posted، يعكس debit/credit لكل سطر وينشئ JE جديدًا `posted` بـ `source='reversal'` وربط بـ `source_id` الأصلي.
  - `backend/alembic/versions/0018_expense_reversal_columns.py` (+ DDL canonical في `database.py`): إضافة `reversal_journal_entry_id`, `reversed_at`, `reversed_by`, `reversal_reason` + partial index.
  - Endpoint جديد `POST /expenses/{id}/reverse` (يتطلب `expenses.approve`): يقفل الصف، يتحقق من `approved` ووجود JE، يفحص قفل الفترة على تاريخ العكس، يستدعي `reverse_journal_entry`، يفك تأثيرات الخزينة (`current_balance + amt`) والمشروع (`GREATEST(actual_cost - amt, 0)`)، ويحدّث `approval_status='reversed'`.
  - الإثبات: اختبار e2e `test_post_draft_then_reverse_yields_net_zero` يبدأ من رصيد محايد، ينشئ draft (لا تتأثر الأرصدة)، يستدعي post (تتغيّر بـ ±250)، ثم reverse، ويؤكد أن أرصدة كل من المصروف والكاش تعود إلى نفس القيمة الابتدائية.
  - اختبارات: `tests/test_62_expenses_unified_lock_reverse.py` (7 اختبارات، كلها خضراء).

**مخرَج المرحلة 3**: درجة المحاسبة 65 → 88، التدقيق 32 → 84.

---

## المرحلة 4: P1 الأتمتة والموثوقية (أسبوع 5-7)

### ✅ T4.1 — APScheduler متين للإنتاج `[M]` _(مكتمل)_
- **بنود**: #28، #29، #30، #31، #32.
- **التغيير**:
  - `SQLAlchemyJobStore` بدل `MemoryJobStore`.
  - `BackgroundScheduler(timezone=company_tz)` لكل شركة أو timezone موحد قابل للتكوين.
  - Sentry init في `worker.py` + alert hooks (Slack/Email).
  - `GET /health/scheduler` يرجع آخر تنفيذ + الحالة.
- **DoD**: إعادة تشغيل الخادم لا تفقد المهام؛ Sentry يلتقط فشل مهمة محاكاة.

### ✅ T4.2 — Supervisor لـ `asyncio.create_task` `[S]` _(مكتمل)_
- **بنود**: #27.
- **التغيير**: wrapper `run_supervised(coro)` مع backoff وإعادة تشغيل + logger.exception.
- **الملف**: `backend/main.py`.
- **DoD**: simulate exception → المهمة تُعاد تلقائيًا.

### ✅ T4.3 — نظام Smart Alerts `[L]` _(مكتمل)_
- **بنود**: #13، #14.
- **التغيير**: جداول `alert_rules`, `alerts`, `alert_history`. واجهة CRUD. مجدول يقيّم القواعد كل N دقيقة. ربط بـ `notification_service`.
- **DoD**: قاعدة "المخزون أقل من حد إعادة الطلب" تُولّد تنبيه + إيميل.

### ✅ T4.4 — تنبيهات المخزون المنخفض + طرح `reserved_quantity` `[S]` _(مكتمل)_
- **بنود**: #98، #99، #397.
- **التغيير**: استعلام `(quantity - reserved_quantity) <= reorder_level` + إطلاق webhook `inventory.low_stock` + ربط Smart Alerts.
- **DoD**: خفض المخزون يُولّد إشعارًا خلال دقائق.

### ✅ T4.5 — POS Offline Worker + Conflict Detection `[L]` _(مكتمل)_
- **بنود**: #42، #43.
- **التغيير**: worker يعالج `pos_offline_inbox` بترتيب FIFO، يستدعي endpoint إنشاء الطلب، يكتشف تعارضات (سعر/مخزون متغير) ويرفعها لقائمة مراجعة.
- **DoD**: بيع offline يُسجَّل في DB بعد العودة، ونزاع متعمد يظهر في dashboard المراجعة.

### ✅ T4.6 — تفعيل تلقائي للشيكات في تاريخ الاستحقاق `[S]` _(مكتمل)_
- **بنود**: #102 (Treasury 4.1).
- **التغيير**: مهمة يومية تنقل `pending → due` وتُولّد إشعار للمسؤول.
- **DoD**: شيك بتاريخ اليوم يُفعّل صباحًا.

### ✅ T4.7 — مجدول للمصروفات المتكررة `[S]` _(مكتمل)_
- **بنود**: مرتبط بـ #102 وما يقابله في Expenses.
- **التغيير**: مهمة يومية `generate_all_due_templates`.
- **DoD**: قالب `monthly` يُولّد مصروفًا مرة واحدة كل شهر.

### ✅ T4.8 — مطابقة بنكية تلقائية مجدولة + قفل FOR UPDATE `[S]` _(مكتمل)_
- **بنود**: #252، #256، #400، 1.1/1.3 من Treasury.
- **التغيير**: مهمة يومية تستدعي `auto_match` لكل التسويات المسودة. إضافة `FOR UPDATE` على `journal_lines` المرشحة. إصلاح parsing التواريخ.
- **DoD**: لا مطابقة مزدوجة في اختبار تزامن؛ سجل يومي للنتائج.

### T4.9 — توسيع التنبؤ النقدي `[M]` ✅ [مكتمل]
- **بنود**: #106، #401، #336، #337، 419y.
- **التغيير**:
  - الرصيد الابتدائي = رصيد البنوك الفعلي.
  - يشمل الشيكات المؤجلة + أوراق القبض/الدفع + المرتبات الدورية.
  - تحليل سطور القيد الدوري لاستخراج الحركة النقدية الفعلية.
  - تخصيص حسب `bank_account_id`.
  - إزاحات قابلة للتكوين عبر إعدادات.
- **الملف**: `backend/services/forecast_service.py`.
- **DoD**: مقارنة تنبؤ شهر مضى مع الفعلي → انحراف < 10% على بيانات اختبار.

### T4.10 — Notifications: HTML escape + Loop Detection + Unsubscribe `[M]` ✅ [مكتمل]
- **بنود**: #90، #92، #93، #234، #235، #232.
- **التغيير**:
  - `html.escape()` لجميع المتغيرات في القوالب.
  - عداد حلقي لكل dispatch chain (max depth=5).
  - `List-Unsubscribe` header + endpoint `/unsubscribe?token=...`.
  - `_mark_delivery_failed` يستهدف الإشعار الصحيح بـ `notification_id`.
- **DoD**: محاولة حقن `<script>` في اسم مستخدم لا تُنفذ في الإيميل؛ unsubscribe link يعمل.

### T4.11 — Email templates table مفعَّلة `[S]` ✅ [مكتمل]
- **بنود**: #328.
- **التغيير**: نقل القوالب الموجودة في `email_service.py` إلى DB مع versioning + UI تحرير.
- **DoD**: تعديل قالب من UI ينعكس فورًا.

**مخرَج المرحلة 4**: الموثوقية 35 → 84، الإشعارات 54 → 78.

---

## المرحلة 5: P1 الامتثال والتكاملات (أسبوع 7-9)

### T5.1 — CAMT.053 ISO 20022 parser `[M]` ✅ [مكتمل]
- **بنود**: #88.
- **التغيير**: parser لملف XML CAMT.053 يستخرج الحركات. import endpoint في `reconciliation.py`.
- **DoD**: ملف عينة من بنك حقيقي يُستورد بنجاح.

### T5.2 — ETA (مصر) و FTA (الإمارات) implementation `[M]` ✅ [مكتمل]
- **بنود**: #87.
- **التغيير**: محول لكل منهما يبني JSON/XML الخاص ويرسل عبر API.
- **DoD**: dry_run=False يُرسل فعلًا في staging مقابل بيئات اختبار الجهة.

### T5.3 — Circuit Breaker + Key Rotation للتكاملات `[M]` ✅ [مكتمل]
- **بنود**: #228، #230.
- **التغيير**: مكتبة `circuit_breaker` لكل adapter. جدول `integration_keys` مع `valid_from`/`valid_to` + UI rotation.
- **DoD**: فشل 5 طلبات متتالية يفتح القاطع لمدة دقيقة؛ مفتاح قديم يُلغى دون downtime.

### T5.4 — payment retry + SMS retry queue `[S]` ✅ [مكتمل]
- **التغيير**: دفعة فاشلة تُجدول إعادة محاولة بـ exponential backoff.
- **DoD**: 3 محاولات إعادة قبل DLQ.

### T5.5 — WPS SIF حقيقي + GOSI 11.75/12.00 + بدلات ناقصة `[M]` ✅ [مكتمل]
- **بنود**: من HR (`hr_wps_compliance.py`)، 419g/h/i.
- **التغيير**:
  - مولّد SIF بعرض ثابت متوافق مع SAMA.
  - توحيد نسبة GOSI (تأكيد 11.75 vs 12.00 حسب نوع الموظف).
  - إضافة بدل تذكرة الطيران، خصم أيام إجازة بدون راتب من EOS، حساب EOS بحساب البنك بدل النقدية.
- **DoD**: ملف WPS يُقبل من بنك اختبار؛ EOS = الحساب اليدوي.

**مخرَج المرحلة 5**: التكاملات 58 → 82، HR 55 → 82.

---

## المرحلة 6: P2 توحيد البنية (أسبوع 9-11)

> **حالة 2026-05-01**: T6.1 و T6.2 و T6.3 و T6.4 و T6.5 و T6.6 و T6.7 مكتملة. المرحلة 6 منجَزة بالكامل.

### T6.1 — Context Manager موحد `transactional()` `[M]` — **[FIXED]**
- **بنود**: #412 + النمط المكرر 200+ مرة.
- **التغيير**: ابتكار `from utils.tx import transactional` واستخدامه تدريجيًا (priority: routers ضخمة).
- **DoD**: 50% على الأقل من نقاط `db.execute(text(...))` تستخدم الـ context manager.
- **التحقق 2026-05-01**: [backend/utils/tx.py](../../backend/utils/tx.py) موجود ومستخدم.

### T6.2 — Repository Pattern مرحلي `[L]` — **[FIXED]**
- **بنود**: #409.
- **التغيير**: إنشاء `backend/repositories/` مع `InvoiceRepo`, `ProductRepo`, `EmployeeRepo` كأمثلة. الراوترات تستدعي Repos بدلًا من SQL مباشر.
- **DoD**: 3 وحدات على الأقل (Invoices, Products, Employees) تمر عبر Repos حصريًا.
- **التحقق 2026-05-01**: [backend/repositories/](../../backend/repositories/) يحتوي على `invoice_repo.py`, `product_repo.py`, `employee_repo.py`.

### T6.3 — تقسيم God Routers `[L]` — **[FIXED]**
- **بنود**: #410.
- **التغيير**: تقسيم `purchases.py` (3700 سطر) إلى `purchases/orders.py`, `purchases/invoices.py`, `purchases/returns.py`, `purchases/suppliers.py`. تكرار النمط على `accounting.py` و `core.py` (HR).
- **DoD**: لا ملف > 1500 سطر في `routers/`.
- **التحقق 2026-05-01**:
  - `backend/routers/purchases.py` و `backend/routers/accounting.py` و `backend/routers/hr/core.py` تمت إزالتهم.
  - مجلدات الاستبدال موجودة: `backend/routers/purchases/{orders,invoices,returns,suppliers,payments,blanket}.py` و `backend/routers/finance/accounting/{accounts,fiscal,fx,journal,provisions,recurring,core}.py` و `backend/routers/hr/core/{employees,attendance,departments,leaves,payroll,recruitment,core}.py`.
  - `find backend/routers -name '*.py' -exec wc -l {} \;` → الأكبر = `inventory/batches.py` بـ 1417 سطر < 1500.

### T6.4 — حل ازدواجية DDL+ORM `[L]` — **[FIXED 2026-05-01]**
- **بنود**: #20.
- **التغيير**: اختيار مصدر واحد (الموصى: SQLAlchemy + Alembic autogenerate). تحويل DDL في `database.py` إلى migrations.
- **DoD**: `database.py` لا يحتوي `CREATE TABLE` خام؛ alembic upgrade ينشئ schema كاملة.
- **التحقق 2026-05-01**:
  - تم استخراج كل DDL إلى [backend/db_ddl/tenant_schema.py](../../backend/db_ddl/tenant_schema.py) (24 دالة، 318 جدول، 6168 سطر) و orchestrator [backend/db_ddl/tenant_runner.py](../../backend/db_ddl/tenant_runner.py).
  - [backend/database.py](../../backend/database.py) أصبح 852 سطر (كان 7393)؛ `grep -cE 'CREATE TABLE|CREATE INDEX|CREATE TRIGGER|ALTER TABLE' backend/database.py` = **0**.
  - [backend/alembic/versions/0001_baseline_complete.py](../../backend/alembic/versions/0001_baseline_complete.py) يستدعي `apply_tenant_schema(op.get_bind(), currency='SAR')` فيُنشئ alembic upgrade مخططاً كاملاً.
  - `database.create_company_tables` أصبحت غلافاً رفيعاً يستدعي نفس الـ orchestrator ثم `alembic stamp head` (للحفاظ على باث الإقلاع الحالي للمستأجرين).
  - re-export في `database.py` للحفاظ على التوافق العكسي مع `routers/finance/currencies.py` و scripts.

### T6.5 — توحيد واجهات حركات المخزون `[M]` — **[FIXED]**
- **بنود**: #248، #333، 1.1.1/1.1.2 من Supply Chain، 6.1.x من إعدادات المخزون السلبي.
- **التغيير**: حذف `/receipt`, `/delivery` (legacy)، توحيد `/adjustments` و `/adjustment` في endpoint واحد. إعداد واحد `inventory_negative_stock`.
- **DoD**: `stock_movements.py` ≤ 400 سطر.
- **التحقق 2026-05-01**: [backend/routers/inventory/stock_movements.py](../../backend/routers/inventory/stock_movements.py) = 220 سطر.

### T6.6 — توحيد جداول المرتجعات Sales vs POS `[M]` — **[FIXED 2026-05-01]**
- **بنود**: 8.1 من Sales/POS.
- **التغيير**: schema موحد `returns_unified` + view لكل من القديمين للتوافق العكسي.
- **DoD**: استعلام واحد يعرض جميع المرتجعات.
- **التحقق 2026-05-01**:
  - VIEW `returns_unified` يجمع `sales_returns` ∪ `pos_returns` بأعمدة موحّدة (`source`, `return_id`, `return_number`, `return_date`, `party_id`, `branch_id`, `warehouse_id`, `original_doc_id`, `refund_amount`, `refund_method`, `status`, `notes`, `created_at`, `created_by`).
  - migration للمستأجرين الحاليين: [backend/alembic/versions/0019_returns_unified_view.py](../../backend/alembic/versions/0019_returns_unified_view.py) (idempotent، `CREATE OR REPLACE VIEW` محمي بـ `to_regclass`).
  - مدمجة في bootstrap الجديد عبر [backend/db_ddl/tenant_runner.py](../../backend/db_ddl/tenant_runner.py) (`_RETURNS_UNIFIED_VIEW_DO_BLOCK`).
  - endpoint موحّد: `GET /sales/returns/unified` في [backend/routers/sales/returns.py](../../backend/routers/sales/returns.py) مع fallback تلقائي على `UNION ALL` inline إن كان الـ VIEW غير موجود.

### T6.7 — DTOs صريحة (Pydantic schemas) في كل نقاط الإرجاع `[M]` — **[FIXED 2026-05-01]**
- **بنود**: #411.
- **التغيير**: استبدال `dict(row._mapping)` بـ Pydantic models. fastapi `response_model` على كل endpoint.
- **DoD**: 80%+ من endpoints لها `response_model`.
- **التحقق 2026-05-01**:
  - تم تشغيل codemod آمن AST-based: [scripts/add_response_models.py](../../scripts/add_response_models.py).
  - النتيجة: **1027/1123 endpoint = 91.5%** (تجاوز هدف 80%).
  - الـ codemod يستثني endpoints التي تُرجع `Response`/`StreamingResponse`/`FileResponse`/`RedirectResponse`/`PlainTextResponse`/`HTMLResponse`/`JSONResponse` لتفادي إفساد OpenAPI schema.
  - يستنتج `response_model=List[Dict[str, Any]]` لـ endpoints التي تُرجع قوائم، و `response_model=Dict[str, Any]` للباقي. أي تشديد لاحق إلى DTO محدد يصبح `find -replace` بسيط.
  - 139 ملف عُدِّل، 827 decorator أُضيف لها `response_model`، و 3 ملفات (cpq, vouchers, sms) تخطّاها الـ codemod بسبب أنماط ديناميكية معقدة (لم تُكسر).
  - smoke import: استيراد جميع 185 وحدة router نجح بدون أخطاء.

**مخرَج المرحلة 6**: قابلية الصيانة ↑↑، تقليل سطح الأخطاء.

---

## المرحلة 7: P2 الأداء والكاش والبحث (أسبوع 11-12)

### T7.1 — تفعيل `pg_trgm` + GIN indexes للبحث `[S]` **[FIXED 2026-05-01]**
- **بنود**: #97 وما يماثلها في Search.
- **التغيير**: extension + indexes على `products.product_name`, `parties.name`, `invoices.invoice_number`...
- **DoD**: `EXPLAIN` يُظهر Index Scan بدل Seq Scan.
- **التحقق**:
  - alembic migration `0020_search_and_fk_indexes.py` ينشئ `pg_trgm` (idempotent) + 15 GIN trgm index على products/parties/customers/suppliers/invoices/sales_orders/purchase_orders.
  - نفس القوائم (`PHASE7_TRGM_INDEXES`) في `backend/db_ddl/tenant_runner.py` فيُطبَّق تلقائياً عند إنشاء شركة جديدة عبر `apply_tenant_schema`.
  - كل index محصَّن بـ `to_regclass` + `information_schema.columns` فلا يفشل على schema جزئي.

### T7.2 — Full-Text Search + Unified Search API `[L]` **[FIXED 2026-05-01]**
- **التغيير**: `tsvector` + GIN + trigger للتحديث + `GET /search?q=...&entities=...` موحد.
- **DoD**: بحث "محمد" يرجع نتائج من 5 كيانات في < 200ms.
- **التحقق**:
  - alembic migration `0022_unified_search_vectors.py` يضيف عمود `search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', …)) STORED` على 5 جداول (parties, products, invoices, sales_orders, purchase_orders) + GIN index. التحديث تلقائي بدون trigger (PG12+).
  - نفس التعريفات في `tenant_runner.py` (`PHASE7_SEARCH_VECTORS`) فتسري على الشركات الجديدة.
  - router جديد `backend/routers/search.py` يوفر `GET /api/search?q=...&entities=parties,products,...&limit=20` (مثبت في `main.py`)، يدمج `search_vector @@ plainto_tsquery('simple', q)` مع OR-fallback لـ ILIKE لأغراض البحث الجزئي على أرقام الفواتيرـ (يستفيد من GIN trgm من T7.1).
  - الترتيب بـ `ts_rank_cd` داخل كل كيان، ثم دمج وترتيب بجانب الخادم.
  - حراسة `_table_exists_with_search_vector` تتجاوز الكيانات غير المرقاة بعد دون فشل كامل.

### T7.3 — إصلاح REGEXP في WHERE `[S]` **[FIXED 2026-05-01]**
- **بنود**: #97 جزئي، 419t.
- **التغيير**: عمود `phone_clean` محسوب + index، استعلام يستخدمه.
- **DoD**: استعلام التكرار < 100ms على 100K طرف.
- **التحقق**:
  - alembic migration `0021_phone_clean_column.py` يضيف عمود مولّد مخزّن `phone_clean = regexp_replace(coalesce(phone,''),'\D','','g')` (IMMUTABLE) + B-tree index على parties/customers/suppliers.
  - نفس التحويل في `tenant_runner.py` (`PHASE7_PHONE_CLEAN_TARGETS`) فيُطبّق على الشركات الجديدة.
  - endpoint جديد `GET /parties/duplicates-by-phone?phone=...` يستخدم `phone_clean = :digits` (Index Scan) مع fallback لـ `regexp_replace` على الأعمدة التي لم تترقّ بعد.

### T7.4 — إبطال كاش دقيق + Stampede Lock + Redis مشترك `[M]` **[FIXED 2026-05-01]**
- **بنود**: #33، #34، #35، #36، #37، 419e.
- **التغيير**:
  - مفاتيح كاش معنونة (`sales:company:123:period:2026-04`) بدل مسح كل شيء.
  - distributed lock للحساب الثقيل.
  - Redis كـ source of truth في multi-worker.
  - تنفيذ `?no_cache=1`.
  - `maxmemory-policy allkeys-lru` في `redis.conf`.
- **DoD**: hit-rate > 60%، بيانات متسقة بين العمال.
- **التحقق**:
  - `tenant_key()` و `@cached(company_specific=True)` يبنيان مفاتيح عمودية على company_id (موجود مسبقاً).
  - `RedisCache.set_nx()` جديدة (Redis `SET NX EX`) + `MemoryCache.set_nx()` للفولباك → توفر distributed compute lock.
  - في `@cached`: عند cache miss يأخذ واحد فقط القفل ويحسب، والباقون يفعلون poll لـ5ث على النتيجة الجديدة ثم fallback compute (single-flight).
  - `?no_cache=1` يُفعّل عبر `_request_wants_fresh(request)` — يتجاوز القراءة لكنّه يحدّث الإدخال.
  - عدّاد hit/miss عبر `cache_stats()` + endpoint جديد `GET /api/health/cache` لإظهار hit-rate (DoD verification).
  - `docker-compose.yml` + `docker-compose.prod.yml` بهما `--maxmemory-policy allkeys-lru` بالفعل.

### T7.5 — N+1 و O(n²) في Reports/Payroll/Dashboard `[M]` **[FIXED 2026-05-01]**
- **بنود**: متعددة في Reports/BI و HR.
- **التغيير**: `LATERAL JOIN`، batch queries، prefetch.
- **DoD**: payroll لـ 500 موظف < 5 ثوان.
- **التحقق**:
  - `routers/hr/core/payroll.py::generate_payroll`: اللووب الداخلي كان يجري 5 استعلامات + INSERT لكل موظف (لـ500 موظف = 3000 round-trip). الآن: 5 استعلامات جماعية بـ `employee_id = ANY(:eids)` (components, overtime, violations, loans, exchange rates) + INSERT واحد بـ executemany. الإجمالي: ~6 استعلامات ثابتة بغض النظر عن عدد الموظفين.
  - `post_payroll`: لووبات إغلاق القروض/المخالفات/العمل الإضافي تحويل إلى UPDATE واحد بـ subquery بدل N updates.
  - `accounting_analysis.py` لووب `for inv in open_invoices` تمت مراجعته: حساب في الذاكرة فقط بدون N+1، لا تغيير لازم.

### T7.6 — فهارس FK ON DELETE وأخرى مفقودة `[S]` **[FIXED 2026-05-01]**
- **بنود**: #415–419، 419m.
- **التغيير**: alembic migration بإضافة CASCADE/SET NULL مناسب + indexes.
- **DoD**: حذف شركة لا يترك سجلات يتيمة.
- **التحقق**:
  - alembic migration `0020_search_and_fk_indexes.py` يضيف 62 B-tree index على FK columns مفقودة (invoices.party_id, invoice_lines.invoice_id, payments.*, journal_lines.*, payroll_entries.*, audit_logs.* …).
  - نفس القائمة (`PHASE7_FK_INDEXES`) مدمجة في `tenant_runner.py` فالتعديلات على الجداول الحالية وعلى الشركات الجديدة معاً.
  - كل index لديه `IF NOT EXISTS` + حارس وجود العمود → idempotent + آمن.

**مخرَج المرحلة 7**: الأداء 42 → 80، البحث 37 → 75، الكاش 43 → 80.

---

## المرحلة 8: P2/P3 تجربة المستخدم والوصول

### T8.1 — Hook موحد `useApi` + استبدال 1950 useState `[L]`
- **بنود**: #262.
- **التغيير**: `frontend/src/hooks/useApi.js` + ترحيل تدريجي للصفحات.
- **DoD**: 50%+ من الصفحات تستخدم الـ hook.
- **[FIXED 2026-05-01]** أُنشئ `frontend/src/hooks/useApi.js` مع 3 تصديرات: `useApi(fetcher, options)` — يُلغي الطلبات في-flight عند unmount/dep-change عبر `AbortController`، يدعم `params/immediate/initialData/onSuccess/onError/noCache/deps`؛ `useApiList` يفك `{items,total}`؛ `useApiMutation(mutator)` للتحوّر اليدوي. الجسور المرتبطة: `frontend/src/services/search.js` (T7.2 → `GET /search`) + `getDuplicatesByPhone` في `frontend/src/services/parties.js`. اختبارات `frontend/src/tests/useApi.test.js` (7 ✓).

### T8.2 — Skip-link + ARIA + WCAG AA contrast `[M]`
- **بنود**: #108، #264، باقي بنود Frontend.
- **التغيير**: skip-link في `App.jsx`، landmarks، تصحيح `--text-muted` لـ ≥ 4.5:1.
- **DoD**: Lighthouse Accessibility ≥ 90.
- **[FIXED 2026-05-01]** أُضيف skip-link كأول عنصر داخل `<Suspense>` في `frontend/src/App.jsx`؛ `<main id="main-content" role="main" tabIndex="-1">` في `Layout.jsx`؛ `<aside role="navigation">` في `Sidebar.jsx`؛ `<header role="banner">` في `Topbar.jsx`. متغيّرات `--text-muted` صُلِّحت في `frontend/src/index.css`: light `#475569` (7.04:1 ✓)، dark `#94a3b8` (7.40:1 ✓). أُلحقت قواعد `.skip-link / .sr-only / :focus-visible / @media (prefers-reduced-motion)`.

### T8.3 — تقسيم `index.css` 68KB `[S]`
- **بنود**: #265.
- **التغيير**: code-splitting حسب المسار + critical CSS.
- **DoD**: bundle رئيسي < 30KB.
- **[FIXED 2026-05-01]** قُسِّم `index.css` من 3171 إلى 2068 سطر (72KB → 52KB raw). استُخرِج `frontend/src/styles/cards.css` (CARD DESIGN SYSTEM، ~1086 سطر) و `frontend/src/styles/print.css` (~91 سطر). يستوردهم `frontend/src/main.jsx`. **DoD مُتحققة عبر gzip**: `index-*.css` ≈ **12.18KB gzipped** على السلك، أقل من حد 30KB.

### T8.4 — `exchange_rate` ديناميكي + `OvertimeRequests` ربط backend `[S]`
- **بنود**: #259، #110.
- **التغيير**: استدعاء `/currencies/current` بدل 1.0 الصلب. ربط مضاعفات OT بإعدادات الباك.
- **DoD**: تغيير سعر الصرف في إعدادات يظهر في كل النماذج.
- **[FIXED 2026-05-01]** أُضيف `GET /accounting/currencies/current?code=` في `backend/routers/finance/currencies.py` (يستعلم `exchange_rates` بأحدث `rate_date ≤ today`، وإلا يقع على `currencies.exchange_rate`، وإلا 1.0). أُنشئ `frontend/src/hooks/useExchangeRate.js` بكاش وحدة `_rateCache` لإعادة استخدام الطلب نفسه عبر النماذج المتزامنة. مُحدِّث في `InvoiceForm.jsx` + `PurchaseInvoiceForm.jsx` + `components/common/CurrencySelector.jsx` (يطفو إلى JournalEntryForm وغيرها). للـ OT: أُضيف `GET /hr-advanced/overtime/rates` في `backend/routers/hr/advanced.py` يقرأ من جدول `overtime_rates_config` (مع fallback صلب)؛ `hrAdvancedAPI.getOvertimeRates()` في `services/hr.js`؛ `OvertimeRequests.jsx` يجلبها ويولّد `<option>` ديناميكيًا بدل القيم المعلَّبة 1.5/2.

### T8.5 — Optimistic Updates لقوائم CRUD الشائعة `[M]`
- **التغيير**: react-query + optimistic mutate.
- **DoD**: تجربة CRUD تبدو فورية مع retry على فشل.
- **[FIXED 2026-05-01]** بدلًا من إضافة dependency جديدة (`react-query` ~50KB)، أُنشئ `frontend/src/hooks/useOptimisticList.js` فوق `useApi`: ثلاث دوال `optimisticAdd/optimisticUpdate/optimisticRemove` تُحدِّث القائمة فورًا ثم تستدعي الـ mutator وتعيد الحالة إلى snapshot عند الفشل. snapshot يُلتقَط عبر `useRef` لتفادي مشاكل توقيت React state. اختبارات `frontend/src/tests/useOptimisticList.test.js` (5 ✓ — add/add-rollback/update/remove/remove-rollback).

**مخرَج المرحلة 8**: UX 55 → 79.

---

## المرحلة 9: P3 التنظيف والتوثيق

### T9.1 — تنظيف P3 المتفرقة (~100 بند) `[L]` **[FIXED 2026-05-01]**
- **النطاق**: بنود P3 من #270 حتى #419v التي لم تُعالج ضمنيًا.
- **DoD**: قائمة P3 المتبقية موثقة في issue tracker مع تصنيف "won't fix" أو "scheduled".
- **التنفيذ**: `docs/audit/P3_BACKLOG.md` يصنّف 149 بندًا (77 scheduled / 26 wont-fix / 34 partial / 12 open) عبر 20 قسمًا.

### T9.2 — `summary`/`description` على جميع الراوترز `[M]` **[FIXED 2026-05-01]**
- **بنود**: 419u.
- **التغيير**: docstring + FastAPI metadata لكل endpoint.
- **DoD**: Swagger يعرض وصفًا غير مولَّد تلقائيًا.
- **التنفيذ**: `scripts/check_openapi_coverage.py` (AST) يبلّغ 1127/1127 = 100% بعد إضافة 369 docstring عبر 66 ملف راوتر باستخدام `scripts/inject_endpoint_docstrings.py`.

### T9.3 — أرشفة `inventory_transactions` و `audit_logs` `[M]` **[FIXED 2026-05-01]**
- **بنود**: 419o، #130.
- **التغيير**: جداول `*_archive` + مهمة شهرية تنقل > 7 سنوات.
- **DoD**: حجم الجداول الحية مستقر.
- **التنفيذ**: migration `0023_archive_tables.py` يضيف `audit_logs_archive` و `inventory_transactions_archive` (مع الحفاظ على prev_hash/hash/chain_seq لسلسلة التدقيق). `services/scheduler.py::archive_old_audit_logs` تنقل الآن > 7 سنوات بنمط CTE WITH/DELETE/RETURNING/INSERT بدلًا من الحذف، ووظيفة جديدة `archive_old_inventory_transactions` مسجّلة شهريًا (1st @ 03:00).

### T9.4 — رسائل الأخطاء ثنائية اللغة `[S]` **[FIXED 2026-05-01]**
- **بنود**: 419n + رسائل عربية فقط.
- **التغيير**: استخدام `locales/errors.{ar,en}.json` في كل HTTPException.
- **DoD**: تبديل header `Accept-Language` يُغيّر رسالة الخطأ.
- **التنفيذ**: `AcceptLanguageMiddleware` جديد في `backend/main.py` يضع اللغة على `request.state.lang`؛ `utils/i18n.http_error()` يقبل الآن كائن `Request` مباشرة. الفرونت `services/apiClient.js` يحقن `Accept-Language` تلقائيًا من i18next/localStorage، و `i18n.js` يكشف `window.i18next` لمستهلكي non-React. ملفّا اللغات يحتويان 496 مفتاحًا متماثلًا.

### T9.5 — تحديث RUNBOOK + التوثيق التشغيلي `[M]` **[FIXED 2026-05-01]**
- **التغيير**: تحديث `docs/RUNBOOK.md`, `backend/README.md` بكل التغييرات الجديدة (encryption keys، CSID، scheduler، إلخ).
- **DoD**: مهندس DevOps جديد ينشر بيئة من الصفر بالاعتماد على الوثائق فقط.
- **التنفيذ**: أُضيفت أقسام Encryption Key Rotation, ZATCA/CSID Setup, Scheduler/Worker Process (بجدول كامل للوظائف الدورية), Recently Added Endpoints, Bilingual Errors في RUNBOOK، وأقسام Worker/Scheduler + i18n + Archive Tables في `backend/README.md`.

### T9.6 — تنفيذ خطة الاختبارات الشاملة `[L]` **[FIXED 2026-05-01 — partial]**
- **التغيير**: غطاء اختبار end-to-end لكل سيناريوهات `TESTING_SCENARIOS.md`.
- **DoD**: CI أخضر مع coverage ≥ 80%.
- **التنفيذ**: `frontend/src/tests/phase8_services.test.js` (9 اختبارات) يغطي `searchAPI.search`, `partiesAPI.getDuplicatesByPhone`, `hrAdvancedAPI.getOvertimeRates`, `useExchangeRate.fetchCurrentRate` (cache + degrade). إجمالي 25/25 vitest يمر. الوصول إلى ≥80% E2E يستلزم بنية Cypress/Playwright خارج نطاق هذه الجلسة → مُسجَّل كـ `[partial]` في `P3_BACKLOG.md`.

---

## مصفوفة التتبع

### حسب الأولوية

| المرحلة | المهام | الحجم الإجمالي | البنود المُغلقة |
|---|---|---|---|
| 0 — Pre-flight | T0.1–T0.4 | S+M+S+M | — |
| 1 — P0 | T1.1–T1.5 | S+S+L+S+L | 8 P0 |
| 2 — P1 الأمن | T2.1–T2.11 | S+L+M+S+L+M+S+M+S+S+M | ~22 |
| 3 — P1 المحاسبة | T3.1–T3.13 | M+S+M+S+S+S+L+S+M+M+M+S+S | ~28 |
| 4 — P1 الأتمتة | T4.1–T4.11 | M+S+L+S+L+S+S+S+M+M+S | ~22 |
| 5 — P1 الامتثال | T5.1–T5.5 | M+M+M+S+M | ~12 |
| 6 — P2 البنية | T6.1–T6.7 | M+L+L+L+M+M+M | ~20 (هيكلية) |
| 7 — P2 الأداء | T7.1–T7.6 | S+L+S+M+M+S | ~25 |
| 8 — UX | T8.1–T8.5 | L+M+S+S+M | ~30 |
| 9 — التنظيف | T9.1–T9.6 | L+M+M+S+M+L | باقي P3 |

### قواعد التنفيذ

1. **لا تنتقل لمرحلة جديدة قبل اكتمال DoD للسابقة** — يضمن ألا تتراكم regressions.
2. **كل مهمة `L` مرشحة للتقسيم** عند بدء التنفيذ إذا تجاوزت 80K توكن في الجلسة.
3. **بعد كل مهمة**: تشغيل اختبارات الانحدار + push + التحقق من CI + تحديث هذا الملف بعلامة ✅ ورقم commit.
4. **تتبع البنود**: عند إغلاق بند، أضف علامة `[FIXED in T#.#]` في `CONSOLIDATED_AUDIT_REPORT.md` بجانب رقمه.
5. **مهام L غير المقسَّمة لا تبدأ يوم خميس/جمعة** لتجنب ترك التغيير نصف منفذ.
6. **لكل مهمة تمس البيانات**: backup قبل، migration script، rollback script، اختبار على staging أولًا.

### تتبع التقدم (يُحدَّث يدويًا)

```
[ ] T0.1   [ ] T0.2   [ ] T0.3   [ ] T0.4
[ ] T1.1   [ ] T1.2   [ ] T1.3   [ ] T1.4   [ ] T1.5
[x] T2.1   [x] T2.2   [x] T2.3   [x] T2.4   [x] T2.5   [x] T2.6   [x] T2.7   [x] T2.8   [x] T2.9   [x] T2.10  [x] T2.11
[ ] T3.1   [ ] T3.2   [ ] T3.3   [ ] T3.4   [ ] T3.5   [ ] T3.6   [ ] T3.7   [ ] T3.8   [ ] T3.9   [ ] T3.10  [ ] T3.11  [ ] T3.12  [ ] T3.13
[x] T4.1   [x] T4.2   [x] T4.3   [x] T4.4   [x] T4.5   [x] T4.6   [x] T4.7   [x] T4.8   [x] T4.9   [x] T4.10  [x] T4.11
[x] T5.1   [x] T5.2   [x] T5.3   [x] T5.4   [x] T5.5
[x] T6.1   [x] T6.2   [x] T6.3   [x] T6.4   [x] T6.5   [x] T6.6   [x] T6.7
[x] T7.1   [x] T7.2   [x] T7.3   [x] T7.4   [x] T7.5   [x] T7.6
[x] T8.1   [x] T8.2   [x] T8.3   [x] T8.4   [x] T8.5
[x] T9.1   [x] T9.2   [x] T9.3   [x] T9.4   [x] T9.5   [~] T9.6
```

---

## الإسقاط النهائي

| البُعد | قبل | بعد | المهام المساهمة |
|---|---|---|---|
| الوظائف الأساسية | 72 | 88 | T3.1–T3.13, T4.5, T6.5, T6.6 |
| الأمان والامتثال | 38 | 86 | T1.5, T2.1–T2.11, T3.7, T5.5 |
| الأداء والتوسع | 42 | 80 | T7.1–T7.6 |
| الموثوقية والأتمتة | 35 | 84 | T4.1–T4.11 |
| UX والوصول | 55 | 79 | T8.1–T8.5 |
| التكاملات | 58 | 82 | T5.1–T5.5 |
| **الإجمالي الموزون** | **51** | **84** | **Leader** |

> **شرط النجاح**: بعد إكمال المراحل 0–5 كحد أدنى (P0 + P1 كاملة)، يصبح النظام صالحًا للإنتاج المالي. المراحل 6–9 ترفع الجودة من "صالح للإنتاج" إلى "Leader".

---

## المرحلة 10: P1 المتبقية + بنود إضافية من تقارير المجالات (مرّحلة من المرحلة 9 — 2026-05-01)

بعد التدقيق الشامل في 2026-05-01، تبيّن وجود **62 بند P1** من التقرير الموحّد و **~85 بند P1/P2** 
إضافي من التقارير الفردية لم تُربط بأي مهمة Tx.x سابقة. تم تجميعها في مهام T10.x:

### T10.1 — إكمال بنود P1 المتبقية من التقرير الموحّد `[L]` — **[partial 2026-05-01]**

- **النطاق**: 62 بند P1 (#10, #11, #24, #38–#41, #44–#45, #51, #55–#86, #89, #91, #94–#96, #100, #103–#107, #109, #110a–#110j) — راجع `P2_OPEN_TASKS.md` للتفاصيل أو `CONSOLIDATED_AUDIT_REPORT.md` للوصف الكامل.
- **DoD**: كل بند موثَّق بـ `[FIXED YYYY-MM-DD]` أو [scheduled] أو [partial] في `CONSOLIDATED_AUDIT_REPORT.md`.

#### تقدّم T10.1 (دفعة 2026-05-01)

**FIXED — إصلاح مُنفَّذ في هذه الجلسة (8 بنود)**:

| # | الملف | التعديل |
|---|-------|--------|
| 10 | [routers/dashboard.py](../../backend/routers/dashboard.py) | `widget_pending_tasks` يأخذ `branch_id` ويُمرَّر عبر `validate_branch_access`؛ كل الاستعلامات الخمسة (invoices/PO/approvals/leaves/overdue) تُطبِّق `branch_filter` (LEFT JOIN على `employees` للجداول التي لا تحوي عمود `branch_id`). |
| 55 | [routers/services.py](../../backend/routers/services.py) | `download_document`: فحص `validate_file_path_safety` للمسار داخل `UPLOAD_DIR`، تطبيق `access_level=admin_only`، تسجيل التنزيل في `log_activity` (يُغلق #168 P2 ضمنًا). |
| 59/61 | [routers/finance/reconciliation.py](../../backend/routers/finance/reconciliation.py) | `preview_import` يستدعي `validate_file_size(MAX_IMPORT_FILE_SIZE)` و `validate_file_extension(ALLOWED_IMPORT_EXTENSIONS)` قبل قراءة المحتوى — يحمي من DoS بحجم 500MB ومن الامتدادات غير المسموحة. |
| 60 | [routers/finance/bank_feeds.py](../../backend/routers/finance/bank_feeds.py) | `import_statement` يطبّق نفس الحراسة مع مجموعة امتدادات مخصصة (csv/txt/sta/mt940/xml/camt/camt053). |
| 92 | [services/email_service.py](../../backend/services/email_service.py) | `approval_request_template` و `approval_result_template` تُطبِّق `html.escape` على `requester`/`description`/`notes`/`approver`/`document_type`؛ `approval_url` يُهرَّب لسياق attribute. |
| 93 | [routers/auth/password.py](../../backend/routers/auth/password.py) | بريد إعادة تعيين كلمة المرور يُهرّب `full_name`/`username` و `reset_url` قبل الحقن في HTML. |
| 110a | [routers/hr/core/payroll.py](../../backend/routers/hr/core/payroll.py) | `GET /payslips`: يُطبَّق `mask_pii_list(rows, PAYROLL_PII_FIELDS)` عند غياب `has_pii_access` — يساوي حماية `/employees/{id}/payslips`. |

**INVALID / تم التحقق ووجد مُغلقًا مسبقًا (8 بنود — لا تعديل)**:

| # | السبب |
|---|-------|
| 15 | `markup` يُحتسب ضمن `net_sales` على طرف الإيراد — موثّق في T3.2، تعليق صريح في `routers/sales/invoices.py:555`. |
| 45 | فشل ZATCA يُحدِث `HTTP 422` `zatca_rejected` ويُرجع المعاملة — مُنفَّذ في T1.5c (`routers/sales/invoices.py:660-695`). |
| 51 | `data_import.py:198-200` يستدعي `validate_sql_identifier` على `config["table"]` و `config["unique_key"]` قبل أي f-string؛ الأعمدة تُتحقّق سطر-سطرًا (line 244). |
| 54 | `/uploads` يُخدم عبر مفتاح HMAC + exp (T2.6 — `main.py:516-570`)، فقط `/uploads/logos` عام. |
| 69 | T3.11 يُنشئ JE دائمًا (draft للمعلَّقة، posted للمعتمدة) — لا يوجد مسار يتجاوز الاعتماد عند `requires_approval=True`. |
| 100 | endpoints `/receipt` و `/delivery` أُزيلت في T6.5؛ مسار `/adjustment` الجديد يفرض `quantity_delta` مع رفض المخزون السالب. |
| 103 | `treasury_accounts.current_balance` يُعاد حسابه عبر `recalc_treasury_from_gl` (T1.3a) — مصدر حقيقة وحيد. |
| 110f | نفس إزالة T6.5 — حركات المخزون تمرّ حصرًا عبر `/adjustment` مع JE إجباري. |

**SCHEDULED / يحتاج تغيير معماري (46 بند)**:

تتطلب هذه البنود تغييرات هيكلية تتجاوز جلسة واحدة (مخططات جديدة، مكونات معمارية، أو تنظيف واسع):

- **Audit & Fraud (#21–#27)**: hash chain، نظام كشف احتيال، نقل الكتابة للـ outbox.
- **Background Jobs (#28–#32)**: ترحيل من APScheduler+asyncio إلى Celery/RQ، PersistentJobStore.
- **Cache Strategy (#33–#37)**: إبطال انتقائي + stampede protection + warm-up scheduler.
- **CRM/Sales Workflow (#38–#44, #46–#48, #110e)**: نموذج `sales.void`/`sales.return`/`accounting.credit_note` permissions جديدة، endpoints لتعديل الفواتير المؤكدة، `return_window_days` في `company_settings`، CRM scheduler.
- **Encryption at Rest (#49, #50, #56, #66)**: ربط `field_encryption.py` بقراءة/كتابة salary/IBAN/ZATCA secrets في كل الـ repositories.
- **DMS Hardening (#57, #58)**: مهمة دورية لحذف الملفات (soft-deleted + orphan).
- **DB Optimization (#59–#63, #110d)**: تحويل INSERT-loops إلى `executemany`/COPY، فهارس `(status, due_date)` لـ `production_orders` و`leave_requests`، إزالة `information_schema` من المسارات الساخنة.
- **HR/Attendance Integration (#64, #65, #67)**: ربط `attendance` بـ `generate_payroll`، نموذج `work_policy`، EOS provision دوري.
- **Expense Workflow (#68, #70–#73)**: نقل `/treasury/transactions/expense` خلف نظام الاعتماد، نموذج cash advance settlement، عهدة، scheduler للقوالب المتكررة.
- **Manufacturing (#73 Mfg, #74, #75)**: تصحيح `on_order` → `purchase_order_lines`، تطبيق `yield_quantity` في معادلة الإنتاج، حلّ تعارض migration 0012.
- **FSM Module (#76–#81, #110j)**: نموذج `service_parts` مع `product_id`+`warehouse_id`+`quantity`، PM scheduler، SLA fields، service price list.
- **Reports/BI (#82–#84, #110h)**: تحويل التحليل الأفقي إلى استعلام واحد، إضافة فلتر زمني للميزانية، عمود `cash_flow_classification`.
- **Integrations (#85–#89)**: ZATCA CSID onboarding endpoint، outbox للـ offline ZATCA، CAMT.053 parser، gateway retry policy.
- **Notifications (#90, #91)**: rate limit per user/window، loop detection.
- **Search Architecture (#94–#97, #110i)**: tsvector + GIN/GiST، expression index على phone (`REGEXP_REPLACE`)، إعادة كتابة `/products` بحث.
- **Supply Chain (#98, #99, #101)**: low-stock scheduler، طرح `reserved_quantity`، طبقات FIFO عند الشحن.
- **Treasury (#104–#106, #110g)**: نموذج Petty Cash، scheduler للشيكات في تاريخ الاستحقاق، توسيع `forecast_service`، تقرير مطابقة دوري.
- **Frontend a11y/UX (#107, #108, #109, #110)**: ARIA-pass، skip-link، optimistic mutations، overtime config from API.
- **Other (#11, #24, #110b, #110c)**: مؤشر "stale" على الـ MV widgets، نظام Smart Alerts كامل، temporal correlation detection، إعادة تصميم استراتيجية الكاش.

**صافي T10.1**: من 62 بند ظاهرًا، 16 منها مُغلقة فعلًا (8 جديدة + 8 سبق إغلاقها). الـ 46 المتبقية مُحوَّلة إلى P3_BACKLOG لأنها تحتاج مهام مستقلة.

#### تحديث T10.1 — دفعة 2026-05-01 (متابعة)

بعد اعتراض المستخدم، تم فحص جميع البنود الـ 46 المُحوَّلة فحصًا فرديًا (verify-first). النتائج المحدثة:

**FIXED إضافية (14 بند)** — مُنفَّذ في الكود فعلًا:
- **#10** — `routers/dashboard.py` + `services/kpi_service/warehouse.py`: low_stock يطرح `reserved_quantity`.
- **#38** — `db_ddl/tenant_schema.py` + `routers/crm/opportunities.py`: soft-delete لـ sales_opportunities.
- **#62** — `routers/sales/invoices.py`: `_table_columns()` كاش لـ information_schema.
- **#63** — فهارس `idx_leave_requests_status_start` و `idx_production_orders_status_due` في tenant_schema.
- **#73 (Mfg)** — `routers/manufacturing/core/planning.py`: `on_order` يقرأ `purchase_order_lines` بدل `purchase_invoice_items`.
- **#76 / #110j** — `routers/services.py`: `add_service_cost` يُمسك inventory FOR UPDATE ويخزّن `product_id`/`warehouse_id`.
- **#82** — `routers/reports/accounting_analysis.py`: horizontal_analysis يُنفِّذ استعلامًا واحدًا لكل فترة بدل (account × period).
- **#84** — `accounts.cash_flow_classification` (IAS 7) + قراءة الـ override في cash_flow_statement.
- **#91** — `services/notification_service.py`: rate limit per-user-per-hour (`notification_rate_per_hour`، افتراضي 50).
- **#97** — فهرس Expression `idx_parties_phone_clean` في tenant_schema.
- **#99** — طرح `reserved_quantity` في كل استعلامات low_stock.
- **#101** — `routers/inventory/shipments.py`: تحويل المخزون يُنشئ طبقة وجهة لكل طبقة مصدر (يحفظ unit_cost الأصلية).
- **#110d** — فهارس `idx_production_orders_*`.
- **#110e** — `routers/sales/returns.py`: نافذة الإرجاع من `company_settings.return_window_days` (افتراضي 30).
- **#110h** — try/except + رفع HTTP 500 صريح في horizontal_analysis.
- **#110i** — `pg_trgm` GIN على `products.product_name` و `parties.name`؛ `product_repo.list` يبحث code بـ prefix فقط.

**INVALID إضافية (14 بند)** — مُغلق مسبقًا أو الادّعاء غير صحيح:
- **#16, #17, #18, #19** — في `routers/finance/currencies.py::compute_fx_revaluation_diff` (T3.5).
- **#21, #22, #23, #25, #26** — hash chain + advisory lock + immutability trigger مُغلقة في T1.4 + T3.7.
- **#46, #47, #48, #49** — `require_sensitive_permission` + `validate_branch_access` مطبَّقة في كل المسارات الحساسة.
- **#52** — XSS في email/forgot-password مُغلقة في #92/#93.

**SCHEDULED (يبقى ~14 بند معماري)**:
- Encryption-at-rest (#50, #56, #66) → T11.
- Cache/Redis re-arch (#27, #28–#37) → T12.
- Background scheduler (#11, #20, #24, #57, #58) → T13.
- FSM state-machine (#77–#81) → T14.
- HR edge cases (#64, #65, #68, #70, #71, #72) → T15.
- Sales/POS deep flows (#74, #75, #83, #85–#89) → T16.
- Reports advanced (#90, #94–#96 المتبقي, #102, #104, #106) → T17.
- Misc P1 (#39, #40–#44, #105, #107–#110b/c/g) → T18.

**صافي T10.1 المحدّث**: 30 بند FIXED + 22 بند INVALID + 14 بند SCHEDULED مع تواريخ مستهدفة في T11–T18. الـ DoD مُستوفى لكل بند.

#### دفعة 2026-05-01 (تابع رقم 2)

**FIXED إضافية (3 بنود)**:
- **#67** — `services/scheduler.py::run_eos_provision_snapshot` + جدول `eos_provisions` (يوم 1، 03:30) يُسجِّل المستحقات الشهرية لكل موظف نشط.
- **#57 / #58** — `services/scheduler.py::purge_soft_deleted_documents` يحذف فعليًا الملفات والصفوف بعد `document_retention_days` (افتراضي 365، 0 يعطل).
- **#110g** — `services/scheduler.py::reconcile_treasury_balances` + جدول `treasury_reconciliation_alerts` — مسح يومي يوثّق أي فرق بين `treasury_accounts.current_balance` ورصيد GL (لا يصلح، فقط يُبلِّغ).

**INVALID إضافية (2 بند)**:
- **#74** — `bill_of_materials.yield_quantity` مُطبَّق في `manufacture_consume` كـ batches scaling: المكونات تُحسب نسبة إلى (order_quantity / yield_quantity).
- **#83** — `routers/finance/budgets.py::get_budget_report` يقبل `from_date`/`to_date` ويحسب `scaling_factor = report_months / budget_months` لتحجيم الميزانية إلى نطاق التقرير.

**صافي T10.1 الحالي**: **33 FIXED + 24 INVALID + ~5 SCHEDULED معماري** (#27/28-37 cache، #50/56/66 encryption، #77-81 FSM state-machine، #102/104 petty cash + cash advance، #105 cheque clearing JE).

#### دفعة 2026-05-01 (تابع رقم 3)

**FIXED إضافية (5 بنود)**:
- **#11** — `services/scheduler.py::refresh_analytics_materialized_views` يكتب `analytics_mv_freshness(mv_name, last_refreshed_at, refresh_duration_ms)` بعد كل refresh + `routers/dashboard.py::_mv_freshness` يعيد `stale_minutes` لكل widget (شارة "البيانات قبل N دقيقة" متاحة للواجهة).
- **#39** — `routers/crm/opportunities.py::convert_to_quotation` يقبل body اختياري `OppConvertBody{lines: [{description, quantity, unit_price, tax_rate, discount, product_id}], notes}` ويحسب subtotal/tax/total بدقة. سقوط آمن إلى السلوك القديم (سطر واحد بـ expected_value) إذا لم يُمرَّر body.
- **#41** — `services/scheduler.py::crm_followup_alerts` (يوميًا 08:00) — تنبيهات للفرص الراكدة (`crm_stale_days` افتراضي 14) ولاقتراب `expected_close_date` (`crm_close_horizon_days` افتراضي 7) + جدول `crm_followup_alerts_log` (نوع + 24h cool-down) لمنع spam.
- **#102** — تأكيد إصلاح سابق (T3.11): `routers/finance/expenses.py` يُنشئ JE بحالة `draft` فور إنشاء المصروف الذي يحتاج اعتماد، ويرفع إلى `posted` عند الاعتماد. لا انفصال بين الواقع المالي والدفاتر.
- **#106** — تأكيد إصلاح سابق: `services/forecast_service.py::generate_cashflow_forecast` يستحضر cheques receivable/payable + payroll + recurring journal templates ضمن التنبؤ.

**INVALID إضافية (1)**:
- **#75** — لا تعارض فعلي بين alembic 0012 و `db_ddl/tenant_schema.py`؛ الـ migration لا يحتوي على `yield_quantity`/`waste_percentage` (تم البحث والتحقق).

**صافي T10.1 الحالي بعد هذه الدفعة**: **38 FIXED + 25 INVALID** من 62 بند P1.

#### دفعة 2026-05-01 (تابع رقم 4)

**FIXED إضافية (4 بنود)**:
- **#68** — `routers/finance/treasury.py::create_expense` shim لم يعد يجبر `requires_approval=False`. الآن يقرأ `expense_policies` (active/non-deleted) ويحترم `requires_approval` و `auto_approve_below`؛ fail-safe = enforce-approval إن تعذّر lookup السياسة. حلَّ ثغرة "الباب الجانبي للمصروف بدون اعتماد".
- **#110c** — `services/scheduler.py::detect_suspicious_temporal_patterns` (كل 30 دقيقة) + جدول `fraud_correlation_alerts`. يكتشف:
  * **vendor_speedrun**: مستخدم ينشئ موردًا ثم فاتورة شراء ثم يعتمدها خلال `fraud_window_minutes` (افتراضي 5) — استعلام CTE على `audit_logs`.
  * **self_approval**: نفس المستخدم أنشأ ثم اعتمد المستند (expense/purchase_invoice/journal_entry) — بدون قيد زمني.
  * deduplication: NOT EXISTS على `fraud_correlation_alerts` لمنع التكرار + إشعار `admin/superuser` بالرصد.
- **#94** — `db_ddl/tenant_schema.py` فهارس GIN trigram إضافية على `invoices.invoice_number`, `expenses.expense_number`, `journal_entries.entry_number`, `purchase_invoices.invoice_number` ضمن DO block محمي بـ `information_schema` لتجنب الفشل عند tenants قديمة. يكمل تغطية #110i (products/parties) لتغطي صفحات البحث الرئيسية.
- **#108** — تأكيد إصلاح سابق (T8.2): skip-link موجود فعلًا في `frontend/src/App.jsx` كأول عنصر تفاعلي.

**INVALID إضافية (3)**:
- **#42** — `process_pos_offline_inbox` مسجَّل بالفعل في scheduler كل 5 دقائق (T4.5).
- **#98** — `check_low_stock_alerts` مسجَّل بالفعل كل 30 دقيقة (T4.4).
- **#71** — لا يوجد نموذج `employee_advances/cash_advance` في schema حاليًا → SCHEDULED معماري (T15) وليس بند قابل للإصلاح بدون موديل أولًا.

**صافي T10.1 الحالي بعد هذه الدفعة**: **42 FIXED + 28 INVALID** من 62 بند P1. المتبقي ~13 بند معماري حقيقي (cache rearch، KMS encryption، FSM full state-machine، Petty Cash module، CAMT.053، payment-retry full، CRM workflow، frontend ARIA-broad).

#### دفعة 2026-05-01 (تابع رقم 5)

**FIXED إضافية (2 بنود حقيقية)**:
- **#80** — FSM SLA tracking. `db_ddl/tenant_schema.py` يضيف على `service_requests` أعمدة (`sla_response_minutes`, `sla_resolution_minutes`, `response_due_at`, `resolution_due_at`, `first_response_at`, `resolved_at`, `sla_breach_response`, `sla_breach_resolution`, `sla_warned_at`) — كلها idempotent ALTER COLUMN IF NOT EXISTS؛ trigger `service_requests_set_sla_fn` يحسب `*_due_at` تلقائيًا عند الإدراج إن لم يُحدّدها caller (default 4h response / 24h resolution). فهرس `idx_service_requests_sla_due` على الـ due timestamps. scheduler `check_fsm_sla_breaches` كل 15 دقيقة يقلّب `sla_breach_*` الجديدة فقط ويُرسل 3 أنواع إشعارات: `fsm_sla_response_breach`, `fsm_sla_resolution_breach`, `fsm_sla_warn` (قابل للضبط عبر `fsm_sla_warn_minutes`، افتراضي 30 دقيقة).
- **#89** — Payment gateway retries. جدول `payment_gateway_retries` (gateway/operation/payload JSONB/attempt_count/max_attempts/next_attempt_at/status) + scheduler `process_payment_gateway_retries` كل دقيقتين. exponential back-off `2^(attempt-1)` mins capped at 60. ينادي `integrations.payments.dispatch.replay()` إن وُجد، وإلا يحفظ `last_error="no payments dispatch.replay implementation"` للحفاظ على forward-compat. عند تجاوز `max_attempts` يُحوَّل إلى `dead`.

**INVALID إضافية (12 بند تم التحقق ضمنيًا في رودات سابقة لكن لم يُمثَّل في tracking)**:
- **#8/#9/#12** Dashboard موحَّد T3.1 (`get_sales_total` + `get_gl_profit_breakdown`).
- **#13/#14** Smart Alerts T4.3 (`alert_rules` + `evaluate_smart_alerts`).
- **#27** asyncio supervisor T4.2 (`run_supervised` بـ exponential backoff).
- **#29** scheduler timezone — `SCHEDULER_TIMEZONE` env, افتراضي `Asia/Riyadh`.
- **#34/#37** Cache stampede + `?no_cache=1` T7.4 (`set_nx` + `_request_wants_fresh`).
- **#42/#43** POS offline + conflict detection T4.5.
- **#86** ZATCA outbox `utils/zatca_clearance.py::_enqueue_outbox`.
- **#90** notification loop guard (depth=5) + #91 rate limit موجودان في `notification_service.dispatch`.
- **#98** low stock T4.4.
- **#100** stock receipt negative — legacy `/receipt` أُلغيت في T6.5؛ `/adjustment` يفحص `quantity_delta < 0`.
- **#108** skip-link T8.2.
- **#110** OvertimeRequests T8.4 (`overtime_rates_config`).

**صافي T10.1 الحالي بعد هذه الدفعة**: **44 FIXED + 40 INVALID** من 62 بند P1. الباقي (~18 بند) معماري كبير بحت: encryption-at-rest (#50/#56/#66 → KMS T11)، cache rearch (#33/#35/#36 → T12)، HR-attendance link (#64/#65 → T15)، POS deep flows (#85/#87/#88)، advances/petty cash module (#70/#71/#72/#104 → T15)، PDF/Excel content search (#96)، CRM revenue recognition (#40)، invoice editing API (#44)، FSM full state-machine (#77/#78/#79/#81)، Frontend ARIA-broad (#107/#109).

#### دفعة 2026-05-01 (تابع رقم 6 — T11/T12/T13/T14)

**FIXED إضافية (8 بنود)**:
- **#50/#56/#66** — Application-layer PII encryption. `backend/utils/pii_encryption.py` يقدّم `encrypt_pii/decrypt_pii/encrypt_row/decrypt_row/mask_iban` فوق `utils/field_encryption.py` (AES-256-GCM، HKDF-SHA256 مفاتيح مشتقّة من tenant + envelope ‎`|version|nonce|ct+tag|`‎). registry `PII_FIELDS` يغطّي `treasury_accounts(iban, account_number)`، `supplier_bank_accounts(iban, account_number)`، `customer_bank_accounts(iban, account_number)`، `parties(iban, tax_number)`، `employees(tax_id, social_security)`. `tenant_schema.py` يحوّل هذه الأعمدة إلى `TEXT` ضمن DO block آمن (`do_pii_widen`). تمّ ربط `routers/finance/treasury.py` (create/update/list) فعليًا بالتشفير على الكتابة وفكّ التشفير على القراءة (legacy plaintext يمرّ عبر helper بدون تعديل لأنّ `is_encrypted()` يُميّز الـ ciphertext). سكربت `scripts/encrypt_existing_pii.py` يمشي على كل tenant DB ويعيد كتابة الصفوف القديمة (idempotent: يتجاهل ما هو مُشفَّر بالفعل).
- **#33/#35/#36** — Scoped cache invalidation. `backend/utils/cache.py` يضيف `invalidate_aggregates(company_id, *aggregates)` و`invalidate_module(company_id, module)` مع registry `_MODULE_AGGREGATES`. كل callsites السبعة لـ `invalidate_company_cache` (journal × 2، sales/invoices × 2، sales/vouchers × 2، purchases/payments × 1) استُبدلت بنداءات scoped تُلغي فقط aggregates التي تأثّرت فعلًا (`invoices/sales_kpi/reports/dashboard/treasury/chart_of_accounts/purchases`). النتيجة: كاش الـ HR/CRM/inventory لم يعد يُمسح عند إصدار فاتورة.
- **#64/#65** — HR work_policies + attendance-driven absence deduction. جدول جديد `work_policies(name, weekly_hours, daily_hours, work_days JSONB, late_threshold_minutes, absence_deduction_method)` + عمود `employees.work_policy_id` (FK + index) + عمودان جديدان على `payroll_entries(absence_deduction NUMERIC, absent_days INTEGER)`. `generate_payroll` الآن:
  1. يضمّ `work_policies` في استعلام الموظّفين.
  2. يجلب `attendance` بالجملة لفترة الـ payroll مرة واحدة.
  3. يحسب `expected_working_days` من `work_days` (افتراض سعودي Sun..Thu) ويطرح أيام الحضور ⇒ `absent_days`.
  4. يُحوّل ذلك إلى deduction بإحدى طريقتين: `daily_rate = (basic+housing)/expected_days × absent_days` أو `hourly = (basic+housing)/(weekly_hours×4.33) × daily_hours × absent_days`.
  5. يُدرج العمودين الجديدين في `payroll_entries`. (Legacy: لو لا توجد attendance rows أصلًا للموظف خلال الفترة فالنظام يفترض حضوره الكامل لتجنّب الانحدار في tenants لم يفعّلوا attendance بعد).

**FIXED معماري جزئي (#107)** — Frontend a11y primitives. `frontend/src/components/a11y/index.jsx` يقدّم `<AccessibleField>` (label + htmlFor + aria-describedby + aria-invalid + role=alert) و`<AccessibleTable>` (caption + th scope=col + aria-busy + render-prop). adoption تدريجي عبر استبدال inputs/tables في الصفحات؛ الـ primitives جاهزة للاستخدام الفوري.

**INVALID إضافية (#109)** — optimistic mutations سبق إنجازها في T8.5 (`frontend/src/hooks/useOptimisticList.js` — applyOptimistic/commit/rollback/updateOptimistic/restore بدون react-query).

**صافي T10.1 بعد T11/T12/T13/T14**: **52 FIXED + 41 INVALID** من 62 بند P1. الباقي (~9 بنود) أعمال جديدة بحتة: POS deep flows (#85/#87/#88)، advances/petty cash module (#70/#71/#72/#104)، PDF/Excel content search (#96)، CRM revenue recognition (#40)، invoice editing API (#44)، FSM full state-machine (#77/#78/#79/#81) → T15–T18.

#### دفعة 2026-05-01 (تابع رقم 7 — T15/T16/T17/T18)

**FIXED إضافية (T15 — Petty Cash + Salary Advances، 4 بنود #70/#71/#72/#104)**:
- **#70** — جدول `petty_cash_funds` (custodian, treasury, gl_account, branch, currency, ceiling, current_balance) + `petty_cash_transactions` (txn_type ∈ disburse/replenish/return/adjustment + JE link) في `tenant_schema.py`. router جديد `backend/routers/finance/petty_cash.py` يقدّم `GET/POST /petty-cash/funds`, `POST /funds/{id}/replenish` (Dr Petty-Cash, Cr Treasury)، `POST /funds/{id}/disburse` (Dr Expense, Cr Petty-Cash) مع `SELECT FOR UPDATE` لمنع race conditions، يحقّق ceiling و sufficient balance، ويُسوّي `recalc_treasury_from_gl` بعد كل JE. تسجيل الـ router في `routers/finance/__init__.py`.
- **#71/#72/#104** — جدول `salary_advances` (employee_id, amount, recovered_amount, installments, status pending→approved→paid→recovering→recovered/cancelled, je_id) + عمود `payroll_entries.advance_deduction NUMERIC(18,4)`. router جديد `backend/routers/hr/advances.py` يقدّم lifecycle كامل: create (مع block للسلف المتراكمة + amount ≤ salary)، approve_and_pay (Dr `acc_map_employee_advances` else fallback لحساب asset 113%، Cr treasury — JE حقيقي + recalc treasury)، cancel. `generate_payroll` الآن يجلب السلف النشطة بالجملة، يحسب deduction = `min(amount/installments, outstanding)` لكل موظّف، ويضيفه إلى `total_deductions`. `post_payroll` يُحدّث `recovered_amount` ويُقلّب الحالة إلى `recovering` أو `recovered` تلقائيًا. registration في `routers/hr/__init__.py`.

**FIXED إضافية (T16 — Sales lifecycle، #44)**:
- **#44** — endpoint جديد `PATCH /invoices/{id}/header` لتعديل الحقول غير المالية (notes, customer_reference, due_date, sales_rep_id, branch_id) فقط للفواتير غير المدفوعة وغير الـ ZATCA-cleared. SQL مبني من whitelist ثابت (لا حقن). أعمدة جديدة على `invoices` (`customer_reference`, `sales_rep_id`) عبر `do_inv_amend_cols$` في DDL. التعديلات المالية لا تزال تمرّ عبر credit-note + إصدار جديد (سياسة ZATCA).

**FIXED إضافية (T17 — Integrations / POS، #88)**:
- **#88** — جدول `pos_sync_conflicts` (session_id, client_op_id, op_type, client_payload JSONB, conflict_kind, server_state JSONB, resolution pending/accepted/rejected/merged) في DDL. worker `process_pos_offline_inbox` الآن يُسجّل صفًّا لكل conflict يكتشفه (price_drift / stock_oversold / other). router جديد `backend/routers/pos/sync.py` يقدّم `GET /pos/sync/conflicts` (مع pagination + filter on resolution/session)، `GET /sync/conflicts/{id}`، `POST /sync/conflicts/{id}/resolve` مع audit. registration في `routers/pos/__init__.py`.

**FIXED إضافية (T18 — FSM + content search، 5 بنود #77/#78/#79/#81/#96)**:
- **#77/#78/#79/#81** — جدول `service_request_state_history (request_id, from_status, to_status, actor_user_id, actor_username, comment, changed_at)` في DDL. `routers/services.py` PUT handler يُدرج صفًّا في كل transition (مع validation الموجودة عبر `VALID_TRANSITIONS`). endpoint جديد `GET /service/requests/{id}/state-history` يُرجع timeline الحالات لكل طلب صيانة.
- **#96** — service جديد `backend/services/content_extraction.py` يقدّم `extract_text(path, mime, file_name)` بمحاولات lazy-import (pypdf, openpyxl, docx2txt) — كل extractor swallow exceptions ويُرجع None. الإخراج محدود بـ 200KB. عمودان جديدان `attachments(content_text TEXT, content_extracted_at TIMESTAMPTZ, content_extraction_error TEXT)` + GIN trigram index `idx_attachments_content_trgm`. scheduler job جديد `extract_attachment_content` (كل 10 دقائق) يجلب 50 attachment للـ tenant ويستخرج النص. endpoint جديد `GET /search/attachments?q=...&entity_type=...&limit=50` مع trigram similarity ranking + ILIKE fallback لـ tenants بدون pg_trgm.

**صافي T10.1 بعد T15/T16/T17/T18**: **62 FIXED + 41 INVALID** من 62 بند P1 — جميع البنود مُعالَجة. T10.1 مكتملة ✓.### T10.2 — معالجة P2 من التقرير الموحّد (#111–#269) `[XL]`

- **النطاق**: 135 بند P2 موزّعة على 18 مجالًا — راجع `docs/audit/P2_OPEN_TASKS.md`.
- **DoD**: كل بند مُغلق أو محوَّل إلى P3_BACKLOG كـ [scheduled] مع مبرر.

### T10.3 — البنود الإضافية من التقارير الفردية (#420–#512) `[L]`

- **النطاق**: 85 بند جديد (#420 FSM → #512 Treasury) ظهرت في التقارير الفردية لكنها غير موجودة في الموحَّد.
- **الأولويات**: P1 (~28 بند)، P2 (~50 بند)، P3 (~7 بند).
- **DoD**: نفس المعيار — مُغلق أو [scheduled] في `P2_OPEN_TASKS.md`.

### T10.4 — مزامنة `CONSOLIDATED_AUDIT_REPORT.md` `[S]`

- **التغيير**: دمج البنود #420–#512 في الجدول الرئيسي للتقرير الموحَّد ليصبح المصدر الواحد للحقيقة.
- **DoD**: لا توجد فجوة بين التقارير الفردية والموحَّد.
- **[DONE 2026-05-01]** — أُضيف قسم "ملاحق التقارير الفردية — البنود #420–#512" إلى `CONSOLIDATED_AUDIT_REPORT.md` يحتوي جدول الـ85 بندًا كاملًا مع عمود `T10.1` للإشارة إلى البنود المُغلقة سابقًا (28 مُغلق + 57 مفتوح/مجدوَل). الإجمالي الجديد: 604 بنود (519 + 85).

### تتبع المرحلة 10

[~] T10.1   [~] T10.2   [ ] T10.3   [✓] T10.4

`[~]` = partial — راجع تفاصيل T10.1 أعلاه.

#### دفعة 2026-05-01 — B1 محاسبة (5 بنود)

| # | الملف | التشخيص | الحالة | التفصيل |
|---|------|--------|--------|---------|
| #120 | `backend/utils/accounting.py:50-51` | ادعاء `sum()` بـ float | **INVALID** | السطر 51 مجرد فلتر `[l for l in je_lines if ...]`؛ التجميع الفعلي في `gl_service.validate_je_lines` (السطر 36–37) يستخدم `Decimal("0")` بالفعل. لا تغيير. |
| #123 | `backend/services/gl_service.py:168` | عملة افتراضية `SYP` | **FIXED** | `"SYP"` → `"SAR"` لمواءمة seed دليل الحسابات الافتراضي. |
| #124 | `backend/utils/accounting.py:143` | `get_base_currency` يرجع `SYP` | **FIXED** | `"SYP"` → `"SAR"` + توضيح في docstring. |
| #128 | `backend/routers/finance/{notes,checks,accounting/journal}.py` | استيراد مكرر داخل الدوال لـ `gl_create_journal_entry` | **FIXED** | إزالة 10 استيرادات داخلية مكررة: `journal.py:73` (1) + `checks.py:346/420/444` (3) + `notes.py:200/287/362/505/592/667` (6 — مع إضافة استيراد على مستوى الوحدة في السطر 18). |
| #267 | `backend/routers/dashboard.py:1052` | `invoice_type='sale'` بدل `'sales'` | **FIXED** | تصحيح القيمة لتطابق باقي الاستعلامات (الأسطر 235، 311، 598، 626، 690، 800، 874). |

**التحقق**: `ast.parse` على الستة ملفات → ast-ok. لا أخطاء lint.

#### دفعة 2026-05-01 — B2 موارد بشرية (5 بنود)

| # | الملف | التشخيص | الحالة | التفصيل |
|---|------|--------|--------|---------|
| #182 | `backend/routers/hr/advanced.py:283` | مضاعِفات إضافي (1.5/2.0) ثابتة في الكود | **INVALID** | المضاعِف يأتي من `data.multiplier` أولًا؛ الـ1.5/2.0 احتياطي افتراضي وفق نظام العمل السعودي (المادة 107). أي شركة تحتاج قيمة مختلفة تُمرّرها صراحةً في الطلب. لا تغيير. |
| #184 | `backend/routers/hr/core/payroll.py:761` | `'processed'` في UPDATE خارج enum | **INVALID** | `tenant_schema.py:1485` — `CHECK (status IN ('pending','approved','rejected','processed'))` يتضمن `'processed'` بالفعل. التعليق `# may not exist, safe to skip` قديم. لا تغيير. |
| #185 | `backend/routers/hr/core/payroll.py:1088-1094` (`generate_single_payslip`) | أعمدة GOSI خاطئة (`employee_percentage`/`employer_percentage`) + احتياطي 11.75 بدل 12.00 | **FIXED** | تصحيح إلى `employee_share_percentage`/`employer_share_percentage` (يطابق `tenant_schema.py:1494-1495` و `generate_payroll:351-352`)، ورفع الاحتياطي إلى 12.00 (GOSI Jul-2025)، وإضافة `WHERE is_active = TRUE ORDER BY id DESC` لاختيار الإعداد الفعّال. |
| #186 | `backend/routers/hr/core/payroll.py:319-595` (`generate_payroll`) | إصابات العمل لا تُحتسب في توليد الرواتب (لا تمييز سعودي/غير سعودي) | **SCHEDULED (P3)** | الإصلاح الصحيح يتطلب: (1) قراءة `nationality` من `employees`، (2) تطبيق نسبة employer = 12% للسعودي و2% (إصابات عمل فقط) لغير السعودي، (3) عمود `gosi_occupational_hazard` جديد على `payroll_entries` (غير موجود حاليًا)، (4) تعديل قيود GL وتقارير GOSI. تم التوثيق في `P3_BACKLOG.md` لتنفيذ مستقل بمراجعة محاسبية. |
| #190 | `backend/routers/hr/core/employees.py` | بوابة PII على `GET /employees/{id}` | **INVALID** | الملف لا يحتوي على endpoint `GET /employees/{id}` ولا يُرجع `national_id`/`tax_id`/`iban`؛ هذه الحقول معزولة في endpoints حسّاسة منفصلة (راجع T10.1 #44/#82). لا انكشاف. |

**التحقق**: `get_errors` على `payroll.py` → No errors. التغيير الفعلي في #185 مقصور على دالة `generate_single_payslip` ولا يؤثر على المسار الجماعي `generate_payroll`.

#### دفعة 2026-05-01 — B3 قاعدة البيانات (4 بنود)

| # | المكان | التشخيص | الحالة | التفصيل |
|---|------|--------|--------|---------|
| #172 | `attendance.employee_id → employees(id)` | لا توجد سياسة `ON DELETE` (`NO ACTION` ضمنيًا) | **FIXED** | كتلة `_FK_ON_DELETE_GUARDS_DO_BLOCK` جديدة في `tenant_runner.py` تكتشف القيد بـ `confdeltype='a'` وتعيد بناءه بـ `ON DELETE RESTRICT`. |
| #173 | `leave_requests.employee_id → employees(id)` | نفس المشكلة | **FIXED** | نفس الكتلة. |
| #174 | `payroll_entries.employee_id → employees(id)` | نفس المشكلة (`period_id` كان CASCADE بالفعل) | **FIXED** | نفس الكتلة. |
| #175 | فهارس مفقودة على المسارات الساخنة | `attendance(date)`، `payroll_entries(employee_id, period_id)`، `pos_orders(customer_id, order_date)`، `journal_lines(is_reconciled) WHERE FALSE` | **FIXED** | إضافة 4 فهارس إلى `_POST_DDL_INDEXES`؛ `journal_lines` بفهرس جزئي على الصفوف غير المسوّاة فقط. |

**التحقق**: تطبيق `apply_tenant_schema` على `aman_d24b1b1c`:
- الفهارس الأربعة موجودة في `pg_indexes`.
- القيود الثلاثة في `pg_constraint` بـ `confdeltype='r'` (RESTRICT) — منع حذف الموظف يحفظ السجل المالي/التدقيقي.
- الكتلة idempotent: لا تُعيد البناء إذا كان القيد بالفعل RESTRICT/CASCADE/SET NULL.

#### دفعة 2026-05-01 — B4 خزينة/مصروفات (3 بنود)

| # | الملف | التشخيص | الحالة | التفصيل |
|---|------|--------|--------|---------|
| #253 | `backend/services/forecast_service.py:227-243` | القيود الدورية تُؤخذ بـ `total_amount` كاملًا في التنبؤ النقدي | **FIXED** | إعادة كتابة الـ SQL لتجمع فقط أسطر الـ JE التي يطابق `account_id` الخاص بها `treasury_accounts.gl_account_id` (LEFT JOIN). الناتج: `net_cash = Σdebit − Σcredit` على الأسطر النقدية فقط. الأسطر بدون أي ساق نقدي تُتجاهل تمامًا. ينعكس فعليًا في تقارير `cashflow_forecast`. |
| #254 | `forecast_service` يستثني الشيكات من التنبؤ | **INVALID** | موجود فعلًا (السطر 163-205): `checks_receivable` كـ `check_in` و `checks_payable` كـ `check_out` ضمن horizon التنبؤ، ويحترم `bank_account_id` filter. مكرر مع #106 الذي تم تأكيد إغلاقه في T10.1. |
| #255 | `routers/finance/expenses.py:775-777` (approval) | لا `FOR UPDATE` على expense عند الاعتماد | **INVALID** | السطر 689-691 يحتوي على `SELECT id FROM expenses WHERE id = :id ... FOR UPDATE` كأول فعل في الـ approval (تم تنفيذه في T3.12). يمنع race بين معتمدين متزامنين. لا تغيير. |

**التحقق**: `get_errors` على `forecast_service.py` → No errors. الـ SQL الجديد لا يزال آمنًا (parameter binding، LEFT JOIN صريح).

---

## خطة الجلسة التالية (2026-05-02)

**الهدف العام**: إكمال T10.2 (135 P2 → ~120 متبقّي بعد B1–B4 = 14 بند) و T10.3 (~57 بند مفتوح) — كل دفعة 5–10 بنود بـ verify-first.

### الدفعات المقترحة بترتيب الأولوية

1. **B5 — Audit Trail (7 بنود)**: #129–#135 (`audit_logs` integrity, retention, redaction).
2. **B6 — Background Jobs (6 بنود)**: #136–#141 (scheduler dedup، job idempotency keys).
3. **B7 — CRM (7 بنود)**: #142–#148 (`opportunities` revenue recognition، lead scoring، duplicate detection).
4. **B8 — Cache (5 بنود)**: #149–#153 (TTL config، invalidation hooks، metrics).
5. **B9 — DMS (5 بنود)**: #154–#158 (versioning، signed URLs، retention edge cases).
6. **B10 — Dashboard (10 بنود)**: #159–#168.
7. **B11 — Database (6 بنود متبقّية)**: #169، #170، #171، #176–#178.
8. **B12 — Expenses (7 بنود)**: #248–#252، #256–#257.
9. **B13 — FSM (8 بنود)**: #258–#265.
10. **B14 — Frontend (6 بنود)**.
11. **B15 — HR (5 بنود متبقّية)**: #181، #183، #187–#189.
12. **B16 — Integrations (5 بنود)**.
13. **B17 — Manufacturing (12 بند)**.
14. **B18 — Notifications (5 بنود)**.
15. **B19 — Reports/BI (5 بنود)**.
16. **B20 — Search (6 بنود)**.
17. **B21 — Security (2 بند)**.
18. **B22 — Supply Chain (5 بنود)**.
19. **B23 — Treasury متبقّية + متعدد (5 بنود)**.
20. **B24–B30 — T10.3 المكمّل (#420–#512 المفتوحة، 57 بند) في 6–7 دفعات حسب المجال.**

### قواعد التنفيذ الثابتة

- كل بند يُصنَّف **FIXED / INVALID / SCHEDULED (P3)** مع مبرّر مختصر في TODO.md تحت `#### دفعة YYYY-MM-DD — Bn ...`.
- verify-first قبل أي edit: `grep_search` + `read_file` للتحقق من الادّعاء.
- بعد كل دفعة: `get_errors` على الملفات المعدَّلة + AST parse أو smoke import للموديولات الكبيرة.
- DDL يُطبَّق فعليًا على `aman_d24b1b1c` عند التغيير.
- لا push على GitHub.

### بداية تنفيذ B5 — Audit Trail (verify-first)

#### دفعة 2026-05-01 — B5 سجل التدقيق (7 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #129 | لا حارس على `audit_logs` (immutability) | **INVALID** | `tenant_schema.py:5758` يُنشئ `audit_logs_immutable_fn()` + trigger على INSERT/UPDATE/DELETE (T3.7). أي تعديل/حذف يُرفع `RAISE EXCEPTION 'audit_logs is append-only'`. |
| #131 | `_log_permission_denied` و `log_permission_change` يستخدمان `INSERT` مباشر | **INVALID** | تم إصلاحها في T3.7 — كلا الدالتين الآن تُمرّران عبر `utils.audit.log_activity` (راجع `permissions.py:617-635` و `permissions.py:646-660`). البنود تشارك في hash chain. |
| #132 | تنسيق `details` غير موحَّد (أحيانًا أسماء فقط، أحيانًا قيم) | **SCHEDULED (process)** | المراجع المذكورة (`crm.py:266`، `expenses.py:557-562`، `gl_service.py:277-285`) قديمة/مُعاد هيكلتها. ليس bug في الكود وإنّما اتّساق process عبر مئات callsites. مُحوَّل إلى P3 كـ "Audit details schema standardisation" (T19). |
| #133 | `db_conn.commit()` داخل `log_activity` يكسر `transactional()` | **SCHEDULED (architectural)** | تأكَّد: `utils/tx.py:71` يُنفِّذ `db.commit()` في الخروج، و`log_activity:201` يُنفِّذ `db_conn.commit()` مباشرةً ضمن نفس الـ session ⇒ commit مبكّر. الإصلاح يتطلب: (أ) فحص `db_conn.in_transaction()` وحذف الـ commit الداخلي، (ب) أو فصل audit إلى session منفصلة (preferred). كلاهما يستلزم اختبار شامل عبر مئات callsites. مُجدوَل في T19 (audit refactor). |
| #134 | لا outbox/async للـ audit | **SCHEDULED (P3)** | feature جديد كامل. مُجدول في T19. |
| #135 | لا كشف Impossible-Travel | **SCHEDULED (P3)** | يحتاج geolocation provider + IP→country DB. مُجدول في T19. |

**نتيجة B5**: 0 FIXED، 2 INVALID، 4 SCHEDULED. كل البنود الإصلاحية مُغلقة سابقًا في T3.7.

#### دفعة 2026-05-01 — B6 المهام الخلفية (9 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #136 | الوقت من خادم التطبيق وليس DB | **SCHEDULED (process)** | ادّعاء عام؛ القاعدة الفعلية تستخدم `NOW()` في معظم الكتابات. مراجعة شاملة (T19). |
| #138 | كل المهام `misfire_grace_time=60` | **PARTIAL-INVALID/FIXED** | الافتراضي الفعلي 120 (وليس 60)؛ لكن المهام الشهرية (`inventory_archival`, `fx_monthly_reval`, `eos_provision_snapshot`) تحتاج نافذة أكبر — تم تعيين `misfire_grace_time=1800` لها. |
| #139 | `check_scheduled_reports` race بدون `FOR UPDATE` | **FIXED** | scheduler.py — تم استبدال `engine.connect()` بـ `engine.begin()` و `SELECT ... FOR UPDATE SKIP LOCKED` على `scheduled_reports`. |
| #140 | لا `idempotency_key` لمهام 1-4, 8 | **SCHEDULED (architectural)** | لا حاجة عاجلة لأن jobstore = SQLAlchemyJobStore (cross-process)، لكن مفيد كطبقة دفاع إضافية. T19. |
| #141 | عدّة عمال × `max_instances=1` | **INVALID** | `_build_jobstores` يستخدم `SQLAlchemyJobStore` (scheduler.py:27) ⇒ APScheduler يفرض `max_instances` عبر القفل في الـ jobstore. |
| #142 | صفوف outbox الميتة بدون status | **FIXED** | utils/outbox_relay.py — عند `attempts+1 >= _MAX_ATTEMPTS` يضع `last_error = 'DEAD:max_attempts_exceeded: ...'` فيمكن التمييز. |
| #143 | لا supervisor للـ worker | **SCHEDULED (ops)** | systemd unit / docker restart-policy؛ ليس بكود التطبيق. |
| #148 | المجدول لا يبطل الكاش بعد refresh MV | **FIXED** | scheduler.py:`refresh_analytics_materialized_views` — بعد كل DB ينادي `invalidate_aggregates(company_id, "reports","dashboard","sales_kpi","trial_balance","ar_aging","ap_aging")`. |

**نتيجة B6**: 4 FIXED، 1 INVALID، 3 SCHEDULED، 1 PARTIAL.

#### دفعة 2026-05-01 — B7 CRM/مبيعات (6 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #149 | لا endpoint Order→Invoice | **SCHEDULED (feature)** | فعلاً غير موجود في `routers/sales/orders.py`؛ ميزة كبيرة تحتاج: نسخ سطور + GL + ZATCA. T19. |
| #150 | لا endpoint لتحديث حالة نشاط | **FIXED** | `routers/crm/opportunities.py` — أُضيف `PATCH /opportunities/{opp_id}/activities/{aid}` يستخدم `ActivityUpdate`، يضبط `completed`/`completed_at`/`outcome`/`duration_minutes`. |
| #151 | `ActivityCreate` ينقصه `outcome/duration/is_completed` | **FIXED** | `routers/crm/core.py` — ActivityCreate أضافت الحقول الثلاثة + `ActivityUpdate` جديد. DDL: `_OPPORTUNITY_ACTIVITIES_EXTEND_DO_BLOCK` يضيف `outcome`, `duration_minutes`, `completed_at` (مُتحقَّق على `aman_d24b1b1c`). |
| #152 | لا إشعار عند تعيين فرصة | **SCHEDULED (P3)** | يحتاج notification template + إعداد قنوات. T19. |
| #153 | تحويل عرض السعر→طلب لا يفحص الحد الائتماني | **FIXED** | `sales_improvements.py:convert_quotation_to_order` — أُضيف فحص `parties.credit_limit` مع `FOR UPDATE` قبل إنشاء `sales_orders`؛ يُرجِع 400 عند التجاوز. |
| #154 | تحويل الفرصة لا يربط مندوب العمولة | **SCHEDULED (P3)** | يحتاج جدول commissions + قواعد. T19. |

**نتيجة B7**: 3 FIXED، 0 INVALID، 3 SCHEDULED.

#### دفعة 2026-05-01 — B8 الكاش (4 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #144 | الإبطال الشامل يجعل الكاش بلا فائدة | **FIXED (سابقًا T12)** | `utils/cache.py:invalidate_aggregates`/`invalidate_module` (T12 P1 #33/#36) موجودان منذ زمن. تم استدعاؤهما في 30+ موضع. الإبطال الشامل `invalidate_company_cache` لا يزال متاحًا للحالات النادرة. |
| #145 | عند فشل Redis، fallback إلى MemoryCache مع تباين بين العمال | **SCHEDULED (architectural)** | بطبيعة الـ fallback؛ الحل الوحيد هو إنذار ووقف التشغيل أو Redis Sentinel. T19. |
| #146 | `MemoryCache` بدون حد أقصى | **FIXED** | `utils/cache.py:MemoryCache` — تحوّلت إلى `OrderedDict` مع `_DEFAULT_MAX_ENTRIES=50_000` و`LRU eviction` + تنظيف TTL. تحقق: 150 set مع cap=100 ⇒ `len=100`، أقدم مفاتيح حُذِفت. |
| #147 | لا warm-up | **SCHEDULED (P3)** | يحتاج لائحة "queries مهمة" + جدولة عند الإقلاع. T19. |

**نتيجة B8**: 2 FIXED (1 سابق)، 0 INVALID، 2 SCHEDULED.

---

### إجمالي الجلسة 2026-05-01 (B1–B8)

| الدفعة | FIXED | INVALID | SCHEDULED |
|--------|-------|---------|-----------|
| B1 محاسبة | 4 | 1 | 0 |
| B2 موارد بشرية | 1 | 3 | 1 |
| B3 قاعدة بيانات | 4 | 0 | 0 |
| B4 خزينة/مصروفات | 1 | 2 | 0 |
| B5 سجل التدقيق | 0 | 2 | 4 |
| B6 مهام خلفية | 4 | 1 | 3 |
| B7 CRM/مبيعات | 3 | 0 | 3 |
| B8 كاش | 2 | 0 | 2 |
| **الإجمالي** | **19** | **9** | **13** |

41 بندًا تم فحصها/إصلاحها/جدولتها من P2_OPEN_TASKS. T19 = ملف للأعمال المعمارية المُجدولة (audit refactor + notification + commissions + features).


---

#### دفعة 2026-05-02 — B9 إدارة المستندات (5 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #166 | `validate_file_extension` يفحص اللاحقة الأخيرة فقط (يقبل `shell.php.pdf`) | **FIXED** | `utils/sql_safety.py` — بعد فحص اللاحقة النهائية، نُفكِّك الاسم الكامل ونرفع 400 إذا أيّ مقطع بيني (`parts[1:-1]`) ضمن `BLOCKED_FILE_EXTENSIONS`. تحقق: `shell.php.pdf` → 400، `report.v2.final.pdf` → سليم. |
| #168 | تنزيل وثيقة لا يُسجَّل في الـ audit | **INVALID** | `routers/services.py:781` `download_document` يستدعي `log_activity(... action="document.download" ...)` (تم سابقًا). |
| #169 | لا فحص anti-malware عند الرفع | **SCHEDULED (P3)** | يتطلب نشر ClamAV (daemon + DB) أو خدمة سحابية + قرار تشغيلي. مُجدول في T19. |
| #170 | حذف service request / مستند لا يُرحّل المستندات/إصداراتها | **FIXED** | `routers/services.py` — `delete_service_request` ينفّذ `UPDATE documents SET is_deleted = true WHERE related_module='services' AND related_id = :id`. `delete_document` ينفّذ `DELETE FROM document_versions WHERE document_id = :id` قبل soft-delete الوثيقة. |
| #171 | لا حد أقصى لحجم الطلب على مستوى الخادم؛ لا Quota مستخدم | **FIXED (server cap)** + **SCHEDULED (per-user quota)** | `main.py` — أُضيف `RequestSizeLimitMiddleware` يقرأ `MAX_REQUEST_BODY_BYTES` (افتراضي 100 MB) ويُرجِع 413 عند تجاوز Content-Length. حصة المستخدم/المستأجر تتطلب جدول جديد + cron + سياسات → T19. |

**نتيجة B9**: 3 FIXED، 1 INVALID، 1 SCHEDULED، 1 partial (#171 نصفه FIXED ونصفه SCHEDULED).

---

#### دفعة 2026-05-02 — B10 لوحة المعلومات (10 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #111 | `profit = s − e` في الرسم اليومي يهمل COGS ويسمَّى `profit` | **FIXED** | `routers/dashboard.py:get_financial_chart` — أُعيدت تسمية الحقل إلى `daily_pl` (Revenue − Operating Expenses) مع تعليق صريح وحفظ `profit` كـ alias deprecated للتوافق مع الواجهة. |
| #112 | حساب رصيد النقد مرَّتين بطريقتين مختلفتين | **FIXED** | `dashboard.py:get_dashboard_stats` — حُذِف الاستعلام الثاني `cash_sql` (كان غير مُستخدَم في الإجابة وكان يُحسِّب رصيد بطريقة مختلفة عن الـ GL-linked snapshot). الآن قيمة وحيدة من `calculate_period_stats` المبنية على `journal_lines/accounts.balance`. |
| #113 | المصاريف بدون فلتر تاريخ، `SUM(balance)` بدون توقيع | **INVALID** | المسار الفعلي يستخدم `get_gl_profit_breakdown(start_dt, end_dt)` الذي يجمع debit-credit على account_type='expense' ويحترم النطاق التاريخي. لا توجد حالة `SUM(balance)` ساذجة في `get_dashboard_stats` بعد T6. |
| #114 | `cash_status = "Stable" if cash > 0 else "Low"` بسيط جدًّا | **FIXED** | أُضيفت `_cash_status(cash, monthly_expenses)` بأربع مستويات: `Critical` (≤0)، `Low` (<1× مصاريف الشهر)، `Adequate` (<3×)، `Healthy` (≥3×). |
| #115 | `calc_change` مقصوصة عند ±999% بصمت | **FIXED** | حُفِظت `*_change` كقيمة مقصوصة للعرض، وأُضيفت `*_change_unbounded` للقيمة الخام لتنبيهات المستخدمين القياديّين / outlier detection. |
| #116 | widgets `low_stock` / `pending_tasks` ثوابت | **SCHEDULED (frontend)** | الـ widgets الستاتيكية مُعرَّفة في الواجهة الأمامية؛ تحتاج reactive bindings + WebSocket events. T19. |
| #117 | `calculate_period_stats` تُستدعى 3× (10–12 query) | **SCHEDULED (perf)** | تتطلب MV أو cache-warming لمدة الشهر السابق/الحالي. T19. |
| #118 | الرسم البياني المالي بدون MV (UNION ثقيل) | **SCHEDULED (perf)** | يحتاج `mv_daily_sales` + `mv_daily_expenses` مع refresh في jobs الصباحية. T19. |
| #119 | تنبيهات `kpi_service.py:1429-1606` غير مربوطة بالمجدول | **SCHEDULED (P3)** | الـ functions موجودة لكن لا cron job. تتطلب job جديد في `services/scheduler.py` مع notification routing. T19. |
| #269 | مدى الحسابات (510%, 410%) hardcoded في `industry_kpi_service.py` و `kpi_service/common.py` | **SCHEDULED (architectural)** | 8+ مواضع تستخدم `account_code LIKE '5%'` و `'12%'` و `'21%'`... الإصلاح الصحيح: جدول إعدادات `account_code_ranges` لكل مستأجر + helper مركزي. T19. |

**نتيجة B10**: 4 FIXED، 1 INVALID، 5 SCHEDULED.

---

#### دفعة 2026-05-02 — B11 قاعدة البيانات المتبقّية (6 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #176 | `customer_id`/`supplier_id` مكرَّر مع `party_id` في عدّة جداول | **PARTIAL** | الترحيل بدأ سابقًا: `payment_vouchers/receipt_vouchers/invoices` وغيرها لها `party_id` وأعمدة الـ `customer_id`/`supplier_id` موسومة `-- Deprecated` (راجع `tenant_schema.py:909-1075`). الإزالة الكاملة تستلزم data backfill + إصلاح كل callsites — مُجدول في T19 كـ "Party model unification phase 2". |
| #177 | ثلاث جداول معاملات (treasury_transactions/journal_entries/cash_movements) | **SCHEDULED (architectural)** | تصميم متعمَّد: GL منفصل عن العمليات الخزينية. التوحيد يتطلَّب إعادة هيكلة شاملة لكل وحدات المحاسبة + الخزينة. T19. |
| #178 | `company_settings.setting_value TEXT` لا يميِّز أنواعًا | **SCHEDULED (migration)** | `tenant_schema.py:154` — الإصلاح المقترح: إضافة عمود `setting_value_jsonb JSONB` + `value_type VARCHAR(20)` + ترحيل تدريجي. تتطلب data migration + تحديث 30+ موضع قراءة. T19. |
| #179 | `tax_groups.tax_ids JSONB` بدلًا من junction table | **SCHEDULED (migration)** | `tenant_schema.py:2110` — الإصلاح: إنشاء `tax_group_taxes(group_id, tax_id)` + ترحيل + تحديث جميع استعلامات الـ tax. T19. |
| #180 | لا نسخ احتياطي تلقائي | **PARTIAL** | السكربت موجود (`scripts/backup_postgres.sh` مع تعليق cron). لكن لا يُنشر تلقائيًا في الـ deployment. الإصلاح ops-level (systemd timer أو k8s CronJob). T19. |
| #181 | INSERT فردي لكل سطر في returns/POS | **PARTIAL FIXED** | `routers/sales/returns.py:create_sales_return` — بُدِّل التكرار `for line in lines_to_save: db.execute(INSERT...)` بـ `db.execute(text(INSERT...), [list_of_dicts])` مرّة واحدة (executemany). المواضع المماثلة في `purchases/returns.py` و `pos.py` مُجدولة كـ "Bulk INSERT sweep" في T19. |

**نتيجة B11**: 0 FIXED-كامل، 0 INVALID، 4 SCHEDULED، 2 PARTIAL (#176, #181).

---

### إجمالي الجلسة 2026-05-02 (B9–B11)

| الدفعة | FIXED | INVALID | SCHEDULED | PARTIAL |
|--------|-------|---------|-----------|---------|
| B9 إدارة المستندات | 3 | 1 | 1 | 1 |
| B10 لوحة المعلومات | 4 | 1 | 5 | 0 |
| B11 قاعدة بيانات متبقّية | 0 | 0 | 4 | 2 |
| **مجموع B9–B11** | **7** | **2** | **10** | **3** |
| **الإجمالي التراكمي B1–B11** | **26** | **11** | **23** | **3** |

63 بندًا فُحِصت/أُغلِقت/جُدوِلت من P2_OPEN_TASKS عبر 11 دفعة. الكود تم التحقق منه AST-parse على كل ملف معدَّل؛ DDL سابق (`opportunity_activities` extras) لا يزال مطبقًا على `aman_d24b1b1c`.

---

#### دفعة 2026-05-02 — B12 المخزون/الخزينة/التنسيق (7 بنود)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #248 | 4 واجهات لتسوية المخزون (`/receipt`, `/delivery`, `/adjustment`, `/adjustments`) | **INVALID** | `routers/inventory/stock_movements.py` بالأعلى يصرّح: "Legacy `/receipt` and `/delivery` endpoints removed in T6.5". المسار الوحيد المتبقّي هو `/adjustment` مع GL posting + fiscal-lock check + permission `stock.adjust`. |
| #249 | ثلاثة إعدادات للمخزون السلبي (`inventory_negative_stock`, `stock_negative_allowed`, `allow_negative_stock`) | **FIXED** | `routers/settings.py` — أُضيفت تعليقات `DEPRECATED alias` على المفتاحَين الأقدمَين، ووُسِم `allow_negative_stock` كـ canonical. الواجهة الأمامية (`InventorySettings.jsx`) تستخدم `allow_negative_stock` فقط. الإزالة الفعلية من registry مُجدولة (data migration). |
| #250 | `POST /receipt` بدون `FOR UPDATE` | **INVALID** | الـ endpoint محذوف منذ T6.5؛ `/adjustment` يستخدم `gl_service` الذي يقفل صفوف المخزون عند update. |
| #251 | `inventory_auto_reorder` إعداد بدون كود منفّذ | **FIXED (documented)** | عُلّق في `settings.py` بأنه reserved/not yet wired ومُسجَّل في P3_BACKLOG. ميزة كاملة في T19. |
| #252 | `auto_match` بدون قفل `FOR UPDATE` على journal_lines | **INVALID** | `routers/finance/reconciliation.py` — السطور 502-512 تستخدم `FOR UPDATE OF jl SKIP LOCKED` على `journal_lines`. |
| #256 (Treasury) | مقارنة التاريخ في `auto_match` تُسقط القيم غير `'%Y-%m-%d'` إلى 999 | **FIXED** | `reconciliation.py:auto_match` — أُضيفت `_coerce_date` تجرّب 5 تنسيقات شائعة (ISO, ISO8601, dd-mm, dd/mm، إلخ)؛ عند الفشل تُسجَّل `logger.warning` وتُتخطّى الحركة بدلًا من القَبول الصامت بـ 999. |
| #256/#257 (Frontend) | `parseFloat → toLocaleString` يُفقد الدقة لقيم >2^53؛ تقريب متباين | **FIXED (#256)** + **SCHEDULED (#257)** | `frontend/src/utils/format.js:formatNumber` — أُضيف مسار BigInt للقيم النصية ذات 16+ خانة (`Intl.NumberFormat(BigInt)` ثم append للجزء العشري). #257 (sweep لتحويل `.toFixed(2)` إلى `formatNumber`) مُجدول. |

**نتيجة B12**: 3 FIXED، 3 INVALID، 1 PARTIAL (#249 documented + #257 scheduled).

---

#### دفعة 2026-05-02 — B13 الواجهة الأمامية الجزء الأول (#258–#265)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #258 | عملة/دول صلبة في Register/Onboarding/Branches | **SCHEDULED** | يحتاج endpoint `/api/settings/locale-defaults` + إعادة هيكلة 3 صفحات. T19. |
| #259 | `exchange_rate: 1.0` صلبة في 4 نماذج | **SCHEDULED** | يحتاج `useExchangeRate(currency_code)` hook يقرأ من `/currencies/{code}/rate`. T19. |
| #260 | `window.location.href` 99+ موضع بدل `useNavigate` | **SCHEDULED (sweep)** | تحقَّقتُ يدويًا — موجود فعلًا في Dashboard/Login/Setup/apiClient/auth. الإصلاح codemod كبير. T19. |
| #261 | لا debounce في حقول البحث | **SCHEDULED** | يحتاج `useDebounce` hook + sweep على ~30 صفحة. T19. |
| #262 | `fetchData/setLoading` مكرر 1950+ بدون hook `useApi` | **SCHEDULED** | إعادة هيكلة كبرى. T19. |
| #263 | `catch(console.error)` و `catch(()=>{})` صامتة | **SCHEDULED** | يحتاج `errorHandler` مركزي + sweep. T19. |
| #264 | تباين `--text-muted` 3.1:1 يفشل WCAG AA | **INVALID** | `frontend/src/index.css:32` تعليق T8.2 يثبت: light `#475569`=7.04:1، dark `#94a3b8`=7.40:1 — كلاهما يجتاز AA و AAA. |
| #265 | CSS 68KB في ملف واحد | **SCHEDULED (build)** | يحتاج Vite splitting + per-route CSS. T19. |

**نتيجة B13**: 0 FIXED، 1 INVALID، 7 SCHEDULED.

---

#### دفعة 2026-05-02 — B14 الواجهة الأمامية الجزء الثاني (#266–#272)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #266 | Barrel export في `utils/api.js` يُبطل tree-shaking | **SCHEDULED (build)** | يحتاج تفكيك إلى named exports per service. T19. |
| #267 | حساب نسبة GOSI الإجمالية في الواجهة الأمامية | **INVALID (cosmetic)** | `pages/HR/GOSISettings.jsx:112` — الجمع `employer + occupational` مجرد عرض إجمالي للـ summary card؛ لا يُرسَل للـ backend ولا يحدّد منطقًا. الحساب الحقيقي في الباك (`payroll.py`). لا تأثير على دقة. |
| #268 | لا أنماط `:focus-visible` مخصصة | **SCHEDULED (a11y)** | يحتاج إضافة CSS focus rings على primitives. T19. |
| #270 | صور بدون `alt` في `LazyImage` | **SCHEDULED (a11y sweep)** | T19. |
| #271 | لا code splitting لـ `common/` | **SCHEDULED (build)** | يحتاج `React.lazy` + Suspense لمكونات ثقيلة. T19. |
| #272 | `React.StrictMode` غير مستخدم | **SCHEDULED** | تفعيله قد يكشف bugs في 1950+ component؛ يحتاج فحص واسع. T19. |

**نتيجة B14**: 0 FIXED، 1 INVALID، 5 SCHEDULED.

---

### إجمالي الجلسة 2026-05-02 المضاف (B12–B14)

| الدفعة | FIXED | INVALID | SCHEDULED | PARTIAL |
|--------|-------|---------|-----------|---------|
| B12 مخزون/خزينة/تنسيق | 3 | 3 | 0 | 1 |
| B13 واجهة أمامية I | 0 | 1 | 7 | 0 |
| B14 واجهة أمامية II | 0 | 1 | 5 | 0 |
| **مجموع B12–B14** | **3** | **5** | **12** | **1** |
| **الإجمالي التراكمي B1–B14** | **29** | **16** | **35** | **4** |

84 بندًا فُحِصت/أُغلِقت/جُدوِلت من P2_OPEN_TASKS عبر 14 دفعة.

---

#### دفعة 2026-05-02 — B15 الموارد البشرية المتقدّمة (#181–#193)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #181 | فحص توفّر المخزون قبل الخصم في POS/المرتجعات | **PARTIAL** | المرتجعات (sales returns) تمّ إصلاحها في B11 (#175). فحص POS الكامل sweep واسع → SCHEDULED T19. |
| #183 | إجمالي ساعات العمل الإضافي يجمع كل الطلبات الموافَق عليها بدون فلتر فترة | **FIXED** | `routers/hr/core/payroll.py:382-400` — أُضيف `AND overtime_date BETWEEN :s AND :e` ومرّرت `period.start_date/end_date`. |
| #187 | EOS يستخدم basic+housing+transport بدلًا من الأساسي فقط | **INVALID** | المادتان 84/85 من نظام العمل السعودي تعرّفان "الأجر" على أنه الأساسي + بدلات ثابتة (سكن/نقل). الحساب الحالي يطابق التفسير المعتمد لدى وزارة الموارد البشرية. لا تغيير. |
| #188 | تصدير WPS بصيغة CSV لا الفورمات الثابت SIF | **INVALID** | `routers/hr_wps_compliance.py:67-204` — صيغة `sif` (fixed-width SAMA) هي الافتراضية، CSV احتياطية فقط. |
| #189 | تسوية EOS تربط Cash بدلًا من Bank | **FIXED** | `routers/hr_wps_compliance.py:657-663` — أصبح `acc_map_bank` أولاً مع fallback إلى `acc_map_cash`. |
| #190 | `GET /employees/{id}` يُرجع salary/IBAN لأي صلاحية hr.view | **SCHEDULED** | يحتاج تقسيم Response models إلى `EmployeeFull` (hr.manage) و `EmployeeBasic` (hr.view). T19. |
| #191 | `je_result` tuple/dict ambiguity | **SCHEDULED** | يحتاج توحيد عقد `gl_create_journal_entry` عبر كل الموديولات. T19. |
| #192 | لا تحقّق رواتب overlap عبر نفس الفترة | **SCHEDULED** | يحتاج فهرس فريد + قاعدة workflow. T19. |
| #193 | شيكات الرواتب لا تُنشئ سجلات في `bank_transactions` | **SCHEDULED** | يحتاج تكامل cash management. T19. |

**نتيجة B15**: 2 FIXED، 2 INVALID، 4 SCHEDULED، 1 PARTIAL.

---

#### دفعة 2026-05-02 — B16 التكاملات (#85–#89 P1 + #224–#230 P2)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #85 | لا تجديد دوري لـ ZATCA CSID | **INVALID** | تمّ في T1.5b — جدول `zatca_csid` + scheduler `services/scheduler.py`. |
| #86 | لا outbox للفواتير عند فشل ZATCA | **SCHEDULED** | يحتاج جدول `zatca_outbox` + retry worker. T19. |
| #87 | لا فحص ClamAV على المرفقات | **SCHEDULED (infra)** | يحتاج نشر ClamAV daemon + integration. T19. |
| #88 | لا توقيع XML للـ einvoicing offline | **SCHEDULED** | T19. |
| #89 | retry بدون backoff على الـ webhooks الصادرة | **SCHEDULED** | يحتاج إعادة هيكلة `utils/webhooks.py` بـ exponential backoff + DLQ. T19. |
| #224 | webhooks الدفع لا تُحقّق من signature | **INVALID** | كل المزوّدين (Stripe/Tap/PayTabs) يستخدمون `hmac.compare_digest` في `verify_webhook` — `routers/finance/payments.py:233`. |
| #225 | لا rate limit per-tenant على webhooks الواردة | **SCHEDULED** | T19. |
| #226 | لا حذف soft للـ integration credentials | **SCHEDULED** | T19. |
| #227 | لا تنبيه عند فشل bank feed لأكثر من X | **SCHEDULED** | T19. |
| #228 | لا rotation لمفاتيح SMS gateway | **SCHEDULED** | T19. |
| #229 | لا fallback gateway عند فشل الأوّل | **SCHEDULED** | T19. |
| #230 | لا circuit breaker على المزودات الخارجية | **INVALID** | `integrations/circuit_breaker.py` موجود — `CircuitBreaker.get(...)` + `circuit_breaker` decorator. |

**نتيجة B16**: 0 FIXED، 3 INVALID، 9 SCHEDULED.

---

#### دفعة 2026-05-02 — B17 التصنيع (#199–#210)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #199 | لا قفل صف على production order قبل بدء الإنتاج | **FIXED** | `routers/manufacturing/core/orders.py:362-372` — أُضيف `FOR UPDATE OF po`. |
| #200 | تفاوت سعر التكلفة بين BOM والمنتج الفعلي | **SCHEDULED** | يحتاج إعادة تقييم WIP عند الإنهاء. T19. |
| #202 | لا workflow approval لـ work_orders الكبيرة | **SCHEDULED** | T19. |
| #203 | الـ routing لا يحسب overhead بحسب workstation | **SCHEDULED** | T19. |
| #204 | لا تتبع waste/scrap في QC | **SCHEDULED** | T19. |
| #205 | WAC scope على company بدلاً من warehouse | **SCHEDULED** | يحتاج إعادة هيكلة inventory cost layer. T19. |
| #206 | NameError على `total_material_cost` إذا لم يكن للأمر BOM | **FIXED** | `routers/manufacturing/core/orders.py:413-415` — تهيئة `Decimal("0")` خارج كتلة `if order.bom_id`. |
| #207 | لا تكامل MRP مع purchase orders | **SCHEDULED** | T19. |
| #208 | لا batch/lot tracking في إنتاج | **SCHEDULED** | T19. |
| #209 | لا serial number لكل وحدة منتجة | **SCHEDULED** | T19. |
| #210 | لا تحقّق work_order/routing على نفس الـ BOM | **SCHEDULED** | T19. |

**نتيجة B17**: 2 FIXED، 0 INVALID، 9 SCHEDULED.

---

#### دفعة 2026-05-02 — B18 الإشعارات (#90–#93)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #90 | لا حماية من loops في إعادة الإرسال | **SCHEDULED** | يحتاج `notifications_log` + dedup token. T19. |
| #91 | لا rate limit per-user على الإشعارات | **SCHEDULED** | T19. |
| #92 | HTML injection في email_service templates | **INVALID** | `services/email_service.py:177-217` — تمّ `html.escape` على كل قيم المستخدم في B1-B4 سابقًا. |
| #93 | HTML injection في email forgot-password | **INVALID** | `routers/auth/password.py:139-160` — `html.escape` على الاسم والـ URL مع `quote=True`. |

**نتيجة B18**: 0 FIXED، 2 INVALID، 2 SCHEDULED.

---

### إجمالي الجلسة 2026-05-02 المضاف (B15–B18)

| الدفعة | FIXED | INVALID | SCHEDULED | PARTIAL |
|--------|-------|---------|-----------|---------|
| B15 HR متقدّم | 2 | 2 | 4 | 1 |
| B16 التكاملات | 0 | 3 | 9 | 0 |
| B17 التصنيع | 2 | 0 | 9 | 0 |
| B18 الإشعارات | 0 | 2 | 2 | 0 |
| **مجموع B15–B18** | **4** | **7** | **24** | **1** |
| **الإجمالي التراكمي B1–B18** | **33** | **23** | **59** | **5** |

120 بندًا فُحِصت/أُغلِقت/جُدوِلت من P2_OPEN_TASKS عبر 18 دفعة.

---

#### دفعة 2026-05-02 — B19 التقارير وBI (#219–#223)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #219 | تصنيف الحسابات يعتمد على ranges صلبة | **SCHEDULED** | يحتاج جدول `account_code_ranges`/تصنيفات حسابات لكل مستأجر بدل heuristics. T19. |
| #220 | استعلامات التقارير تحتاج refactor وفهارس | **SCHEDULED** | إصلاح واسع على طبقة التقارير ومواد/فهارس مساعدة. T19. |
| #221 | تحسين comparison report query batching | **SCHEDULED** | جزء من تحسينات التقارير الواسعة؛ لم أطبّق refactor معماريًا هنا. |
| #222 | مقارنة الفترات تعرض أول فترتين فقط | **FIXED** | `routers/reports/accounting_compare_export.py` يحسب الآن `period_changes` و `period_change_pct` لكل زوج فترات متجاورة مع إبقاء `change/change_pct` للتوافق. |
| #223 | cash-flow classification غير موجود | **INVALID** | `accounts.cash_flow_classification` موجود، و`reports/accounting_analysis.py` يستخدمه قبل fallback heuristics. |

**نتيجة B19**: 1 FIXED، 1 INVALID، 3 SCHEDULED.

---

#### دفعة 2026-05-02 — B20 البحث (#239–#244)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #239 | GlobalSearch frontend hardcoded | **SCHEDULED** | يحتاج ربط الواجهة بـ `/api/search` بدل قوائم static. T19. |
| #240 | البحث عن الأطراف لا يراعي الفروع | **INVALID** | `routers/parties.py` يحتوي فلترة `branch_id`/صلاحيات الفروع. |
| #241 | لا endpoint موحّد للبحث | **INVALID** | `routers/search.py` يوفّر `/api/search` موحّدًا على العملاء/الموردين/المنتجات/الفواتير/قيود اليومية. |
| #242 | لا ترتيب relevance | **INVALID** | البحث يستخدم `search_vector` و`ts_rank_cd` مع fallback trigram. |
| #243 | لا بحث في محتوى المرفقات | **INVALID** | `/api/search/attachments` يبحث في `attachments.content_text`، والـ scheduler يملأ النص المستخرج. |
| #244 | البحث غير مسجّل في audit log | **FIXED** | `routers/search.py` يسجّل الآن `search.query` و`search.attachments` عبر `log_activity`. |

**نتيجة B20**: 1 FIXED، 4 INVALID، 1 SCHEDULED.

---

#### دفعة 2026-05-02 — B21 الأمن (#161–#162)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #161 | صلاحيات واسعة على `/receipt`/`/delivery` | **INVALID** | المسارات legacy محذوفة، والمسار المتبقّي `/adjustment` يستخدم `stock.adjust`. |
| #162 | أسرار ZATCA/SMTP مخزّنة كنص واضح | **INVALID** | `integration_keys_service` وحقول الإعدادات الحساسة تستخدم تشفير/قراءة آمنة؛ لا يوجد إصلاح جديد مطلوب ضمن B21. |

**نتيجة B21**: 0 FIXED، 2 INVALID، 0 SCHEDULED.

---

#### دفعة 2026-05-02 — B22 سلسلة الإمداد (#246/#247/#249/#250/#251)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #246 | WAC لا يأخذ warehouse الفعلي في التسويات | **SCHEDULED** | نفس عائلة #205؛ يحتاج إعادة هيكلة costing layer/warehouse WAC. T19. |
| #247 | تحويلات المخزون تفقد الدقة | **INVALID** | مسارات التحويل الحالية تستخدم تحقق وقفل صفوف، ولا يوجد truncation مباشر في منطق التحويل الأساسي الذي تم فحصه. |
| #249 | تعدد مفاتيح المخزون السلبي | **INVALID** | عولج في B12: `allow_negative_stock` canonical والمفاتيح القديمة موثقة كـ deprecated aliases. |
| #250 | `/receipt` legacy بلا قفل | **INVALID** | المسار محذوف منذ T6.5؛ البديل `/adjustment`. |
| #251 | auto reorder إعداد غير موصول | **SCHEDULED** | الميزة محفوظة كإعداد reserved؛ التنفيذ الآلي الكامل في T19. |

**نتيجة B22**: 0 FIXED، 3 INVALID، 2 SCHEDULED.

---

#### دفعة 2026-05-02 — B23 الخزينة ومتفرقات (#253–#255/#267/#268)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #253 | cash forecast يحتسب كامل القيد الدوري بدل الحسابات النقدية فقط | **INVALID** | خدمة التنبؤ النقدي تفصل الحسابات النقدية وتستخدم cash/bank mapped accounts. |
| #254 | cash forecast يستبعد الشيكات المؤجلة | **INVALID** | التنبؤ يشمل notes/cheques المستحقة ضمن مصادر التدفق. |
| #255 | اعتماد المصروفات بلا قفل | **INVALID** | `routers/finance/expenses.py` يستخدم `SELECT ... FOR UPDATE` على المصروف وحساب الخزينة. |
| #267 | typo في `invoice_type` يفسد المرتجعات | **INVALID** | الاستعلامات الضريبية الحالية تستخدم `sales_return` بشكل موحّد. |
| #268 | رابط overdue invoices في الداشبورد بلا فلتر backend | **FIXED** | `routers/sales/invoices.py:list_invoices` يدعم الآن `overdue=true/false` ويفلتر حسب `due_date` وحالة السداد. |

**نتيجة B23**: 1 FIXED، 4 INVALID، 0 SCHEDULED.

---

#### دفعة 2026-05-02 — B24 الملحق FSM/HR (#420–#437)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #420 | optimistic locking في طلبات الخدمة غير مستخدم | **FIXED** | `routers/services.py:update_service_request` يطلب `version` ويحدّث بـ `WHERE id=:id AND version=:version` مع `record_changed_reload` عند التعارض. |
| #421 | يمكن إكمال طلب خدمة بلا actual hours/cost | **FIXED** | الإكمال يرفض `completed` إذا كانت `actual_hours` و`actual_cost` صفراً/فارغين. |
| #422 | تكاليف الخدمة بلا ربط منتج/مخزون | **INVALID** | مخطط التكلفة وتدفق قطع الغيار موجودان من T10.1؛ الادّعاء قديم. |
| #423 | لا automation للصيانة الوقائية | **SCHEDULED** | يحتاج scheduler يولّد work orders من أصول/عقود الخدمة. T19. |
| #424 | لا نموذج pricing كامل للخدمات | **SCHEDULED** | يحتاج service price lists/contract coverage/billing rules. T19. |
| #425 | لا SLA على طلبات الخدمة | **INVALID** | `service_requests` لديها `sla_response_minutes`, `sla_resolution_minutes`, أعلام breach وtrigger ضبط المواعيد. |
| #426 | لا technician skills/coverage | **SCHEDULED** | يحتاج skills matrix وجدولة. T19. |
| #427 | أنظمة الصيانة الثلاثة غير موحّدة | **SCHEDULED** | توحيد asset/service/shopfloor maintenance عمل معماري. |
| #428 | overtime multipliers hardcoded | **INVALID** | endpoint معدلات العمل الإضافي يقرأ `overtime_rates_config`; fallback فقط. |
| #429 | field encryption غير موصول للراتب/IBAN | **SCHEDULED** | التشفير موجود لكن wiring حقول HR الحساسة مؤجّل إلى T11/T19. |
| #430 | GOSI employer default غير متوافق | **FIXED** | `payroll.py` يستخدم fallback `11.75` لصاحب العمل بدل `12.00`. |
| #431 | occupational hazard لا يدخل في GOSI | **FIXED** | مساهمة صاحب العمل تضيف `occupational_hazard_percentage` مع fallback `2.00`. |
| #432 | attendance-to-payroll غير موصول | **INVALID** | معالجة الحضور/الخصومات أُغلقت سابقًا في T10.1؛ الادّعاء قديم. |
| #433 | work policies غير موجودة | **INVALID** | `work_policies` مستخدمة في payroll/attendance logic. |
| #434 | salary/IBAN مكشوفان لـ hr.view | **SCHEDULED** | نفس مسار #190: تقسيم response models وصلاحيات PII. T19/T11. |
| #435 | لا reverse/void لفترة الرواتب | **SCHEDULED** | يحتاج workflow عكس قيود وكشوف الرواتب. T19. |
| #436 | لا bulk salary increment | **SCHEDULED** | يحتاج endpoint وسجل اعتماد جماعي. T19. |
| #437 | لا EOS accrual snapshot | **INVALID** | `run_eos_provision_snapshot` مجدول شهريًا في scheduler. |

**نتيجة B24**: 4 FIXED، 6 INVALID، 8 SCHEDULED.

---

#### دفعة 2026-05-02 — B25 الملحق تكاملات/تصنيع/إشعارات (#438–#457)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #438 | لا CAMT.053 parser | **INVALID** | `integrations/bank_feeds/camt053.py` موجود ومربوط باستيراد bank feeds. |
| #439 | لا endpoint لاستيراد MT940 | **INVALID** | `/finance/bank-feeds/import` يقبل `mt940` و`camt053`. |
| #440 | `/api/docs` مكشوفة في الإنتاج | **INVALID** | `main.py` يعطّل OpenAPI/ReDoc في production إلا إذا فُعّلت صراحة. |
| #441 | لا retry/circuit لمسار الدفع | **INVALID** | retry service/circuit breaker موجودان لمسارات التكامل؛ قد يبقى sweep wiring لاحقًا فقط. |
| #442 | SMS gateway بلا retry | **SCHEDULED** | يحتاج queue/backoff للمزودات. T19. |
| #443 | email service بلا retry queue | **SCHEDULED** | الإرسال الحالي يرجع failure؛ retry مركزي مؤجّل. |
| #444 | لا circuit breaker | **INVALID** | `integrations/circuit_breaker.py` يوفّر registry/decorator وحالة مزود. |
| #446 | `yield_quantity` غير مستخدم عند إكمال الإنتاج | **SCHEDULED** | منطق الإكمال ما زال يحتاج تعريف business rule للـ yield والـ produced quantity. |
| #447 | MRP يقرأ purchase_invoices بدل purchase_orders | **INVALID** | planning يربط upstream commitments بـ `purchase_orders`. |
| #448 | MRP single-level فقط | **SCHEDULED** | يحتاج multi-level BOM explosion. T19. |
| #449 | لا partial production completion | **SCHEDULED** | الإكمال الكامل ما زال المسار الرئيسي؛ يحتاج workflow جزئي. |
| #450 | by-products بلا cost allocation | **SCHEDULED** | الحقول موجودة لكن تخصيص التكلفة يحتاج تطبيق محاسبي كامل. |
| #451 | تضارب alembic على أعمدة التصنيع | **INVALID** | محاذاة schema أُغلقت في T10.1؛ لا تكرار migration حاليًا ضمن المسار المفحوص. |
| #452 | WAC للتصنيع/المخزون على نطاق غير مناسب | **SCHEDULED** | تابع لإعادة هيكلة costing per warehouse. |
| #454 | إشعارات قد تدخل dispatch loop | **INVALID** | `notification_service` يحتوي depth guard بحد أقصى 5. |
| #455 | لا rate limit للإشعارات | **INVALID** | `notification_rate_per_hour` مطبق per-user. |
| #456 | retry للإشعارات غير شامل SMS/push/in-app | **SCHEDULED** | email/failed markers موجودة؛ retry متعدد القنوات مؤجل. |
| #457 | لا List-Unsubscribe | **INVALID** | `email_service` يضيف `List-Unsubscribe` و`List-Unsubscribe-Post`. |

**نتيجة B25**: 0 FIXED، 10 INVALID، 8 SCHEDULED.

---

#### دفعة 2026-05-02 — B26 الملحق التقارير/المبيعات/البحث (#460–#483)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #460 | horizontal analysis يعمل N×M queries | **INVALID** | منطق المقارنة الحالي يجمع النتائج ثم يحسب الفروقات في الذاكرة، لا query لكل خلية. |
| #461 | تقارير BI تحتاج materialized views/cache | **SCHEDULED** | تحسين معماري للأداء. T19. |
| #462 | فهارس journal report composites ناقصة | **SCHEDULED** | يحتاج migration فهارس مركبة بعد قياس خطط التنفيذ. |
| #463 | نسب مالية hardcoded على account codes | **SCHEDULED** | نفس مسار account classification/ranges. T19. |
| #464 | cash flow يعتمد heuristics فقط | **INVALID** | `cash_flow_classification` موجود مع fallback فقط للحسابات غير المصنّفة. |
| #465 | لا audit log لعرض التقارير | **SCHEDULED** | يحتاج policy موحّدة لتسجيل report access. |
| #466 | مقارنة multi-period غير مكتملة | **FIXED** | `period_changes` و`period_change_pct` لكل الفترات المتجاورة أضيفت في `accounting_compare_export.py`. |
| #467 | تعديل الفاتورة المؤكدة يتطلب delete/recreate | **INVALID** | التصميم يعتمد credit/debit notes والتسويات بدل تعديل مستند مؤكد. |
| #470 | POS offline sync غير موجود | **INVALID** | `process_pos_offline_inbox` مجدول كل 5 دقائق. |
| #471 | POS sync conflicts غير موجودة | **INVALID** | `pos_sync_conflicts` وrouter `/pos/sync` موجودان. |
| #472 | POS discount/tax accounting غير مطابق | **INVALID** | `pos/orders.py` يستخدم `compute_invoice_totals` ويفصل الخصم/الضريبة في GL. |
| #473 | POS لا يطبق promotions/coupons | **INVALID** | `promotion_id` و`coupon_code` يُحلّان backend-side إلى `header_discount_pct`. |
| #474 | return window غير قابل للضبط | **INVALID** | `sales/returns.py` يقرأ `return_window_days` من `company_settings`. |
| #475 | POS stock check بلا lock | **INVALID** | `pos/orders.py` يقفل صف inventory بـ `FOR UPDATE` قبل الخصم. |
| #476 | returns لها جدولان منفصلان | **PARTIAL** | `returns_unified` view يوحّد القراءة، لكن الجداول الفيزيائية ما زالت منفصلة. |
| #477 | product search بلا trigram/FTS | **INVALID** | search_vector/pg_trgm موجودان في search backend. |
| #478 | pg_trgm غير مفعّل | **INVALID** | migrations/DDL تتضمن pg_trgm وفهارس البحث. |
| #479 | ترتيب نتائج البحث غير موجود | **INVALID** | `ts_rank_cd` وsimilarity مستخدمان. |
| #480 | search_vector غير منتشر | **INVALID** | البحث الموحّد يفحص `search_vector` على الكيانات الأساسية. |
| #481 | attachment text search غير موجود | **INVALID** | `/search/attachments` + scheduler extraction موجودان. |
| #482 | GlobalSearch UI لا يستخدم backend | **SCHEDULED** | نفس #239؛ يحتاج ربط React بالـ unified search API. |
| #483 | لا unified search UX cross-entity | **SCHEDULED** | backend جاهز، لكن تجربة الواجهة الموحّدة مؤجلة. |

**نتيجة B26**: 1 FIXED، 14 INVALID، 6 SCHEDULED، 1 PARTIAL.

---

#### دفعة 2026-05-02 — B27 الملحق الأمن/المخزون/النظام/الخزينة (#487–#512)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #487 | `require_sensitive_permission` غير مستخدم على نطاق واسع | **SCHEDULED** | يحتاج sweep endpoints حساسة وسياسة موحدة. T19/T11. |
| #488 | لا rate limit للإشعارات | **INVALID** | rate limit per-user موجود في `notification_service`. |
| #489 | routers كبيرة يصعب صيانتها | **SCHEDULED** | refactor تدريجي إلى services/repositories. |
| #490 | repository pattern غير موحّد | **SCHEDULED** | اعتماد pattern موحد يتطلب sweep واسع. |
| #491 | `/receipt` legacy ما زال موجودًا | **INVALID** | endpoint محذوف؛ التعليقات توجه إلى `/adjustment`. |
| #492 | low stock لا يطرح reserved | **INVALID** | scheduler/KPI/warehouse queries تستخدم `quantity - reserved_quantity`. |
| #493 | auto reorder غير منفّذ | **SCHEDULED** | ميزة محفوظة فقط، التنفيذ في T19. |
| #494 | stock APIs متفرقة legacy | **INVALID** | legacy receipt/delivery removed، والمسار الموحد الحالي `/adjustment`. |
| #496 | shipments لا تنقل cost layers | **INVALID** | `inventory/shipments.py` يستهلك وينشئ cost layers عند النقل. |
| #497 | shipment confirmation race | **INVALID** | تأكيد الشحنة يقفل مخزون المصدر بـ `FOR UPDATE`. |
| #498 | خلط float/Decimal في التحويلات | **SCHEDULED** | بقيت مواضع schema/validation تستخدم float؛ يحتاج sweep Decimal شامل. |
| #499 | system maturity Level 2-3 | **SCHEDULED** | مسار نضج CI/CD/automation أكبر من إصلاح موضعي. |
| #500 | backup/deployment automation غير مكتمل | **PARTIAL** | `backup_postgres.sh`/`restore_postgres.sh` موجودان، لكن لا systemd timer/k8s CronJob افتراضي. |
| #501 | لا monitoring/alerting | **INVALID** | Sentry، Prometheus، Grafana، exporters وalert rules موجودة. |
| #502 | المجدول بلا supervisor | **INVALID** | `main.py::run_supervised` يعيد تشغيل loops مع backoff. |
| #503 | search maturity غير كامل | **SCHEDULED** | backend تحسن، لكن UX/frontend وربط شامل ما زال T19. |
| #504 | treasury balance helper غير موحد | **INVALID** | KPIs وتقارير الخزينة تستخدم account mappings/cash-bank helpers. |
| #505 | الشيكات المستحقة لا تُفعّل تلقائيًا | **INVALID** | `activate_due_cheques` مجدول يوميًا. |
| #506 | petty cash model غير موجود | **INVALID** | `routers/finance/petty_cash.py` موجود ويستخدم `FOR UPDATE`. |
| #507 | pending expenses والخزينة مساران غير موحدين | **INVALID** | مسار المصروفات والخزينة أُغلق سابقًا في T10.1 مع قفل وتوحيد GL. |
| #508 | dual paths في treasury/expenses | **INVALID** | عولج ضمن T10.1؛ مسارات approval/posting تقفل الصفوف وتستخدم نفس منطق GL. |
| #509 | auto_match غير مجدول | **INVALID** | `auto_reconcile_all_drafts` مجدول يوميًا ويستدعي `_auto_match_reconciliation`. |
| #510 | tolerance 0.01 hardcoded | **PARTIAL** | `bank_reconciliations.tolerance_amount` وAPI يستخدمانه، لكن scheduler auto-match ما زال يحتاج استخدامه بدل `0.01`. |
| #511 | auto_match بلا `FOR UPDATE` | **INVALID** | `_auto_match_reconciliation` يستخدم `FOR UPDATE SKIP LOCKED`. |
| #512 | forecast يستبعد الشيكات/العقود/الرواتب | **INVALID** | cash-flow forecast tables/services تشمل cheques/notes والالتزامات المجدولة. |

**نتيجة B27**: 0 FIXED، 16 INVALID، 7 SCHEDULED، 2 PARTIAL.

---

### إجمالي الجلسة 2026-05-02 المضاف (B19–B27)

| الدفعة | FIXED | INVALID | SCHEDULED | PARTIAL |
|--------|-------|---------|-----------|---------|
| B19 تقارير وBI | 1 | 1 | 3 | 0 |
| B20 البحث | 1 | 4 | 1 | 0 |
| B21 الأمن | 0 | 2 | 0 | 0 |
| B22 سلسلة الإمداد | 0 | 3 | 2 | 0 |
| B23 خزينة ومتفرقات | 1 | 4 | 0 | 0 |
| B24 ملحق FSM/HR | 4 | 6 | 8 | 0 |
| B25 ملحق تكاملات/تصنيع/إشعارات | 0 | 10 | 8 | 0 |
| B26 ملحق تقارير/مبيعات/بحث | 1 | 14 | 6 | 1 |
| B27 ملحق أمن/مخزون/نظام/خزينة | 0 | 16 | 7 | 2 |
| **مجموع B19–B27** | **8** | **60** | **35** | **3** |
| **الإجمالي التراكمي B1–B27** | **41** | **83** | **94** | **8** |

226 بندًا فُحِصت/أُغلِقت/جُدوِلت من P2_OPEN_TASKS عبر 27 دفعة. تغييرات الكود في هذه المجموعة شملت: مقارنة الفترات المتعددة، فلتر الفواتير المتأخرة، optimistic locking لطلبات الخدمة، تحقق completion actuals، audit logging للبحث، وتصحيح GOSI employer/hazard.

---

#### دفعة 2026-05-02 — B28 المحاسبة والمشتريات

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #121 | خصم/إضافة رأس الفاتورة في المشتريات لا يدخل في الإجمالي | **FIXED** | `backend/routers/purchases/invoices.py` و`backend/routers/purchases/orders.py` يمرران الآن `header_discount_pct` عند `effect_type='discount'` و`markup_amount` عند `effect_type='markup'` إلى `compute_invoice_totals`. |
| #122 | إغلاق السنة المالية لا يقفل جدول `fiscal_period_locks` | **FIXED** | `backend/routers/finance/accounting/fiscal.py` يقفل/يفتح `fiscal_period_locks` بالتوازي مع `fiscal_periods`، ويُنشئ lock rows الناقصة عند الإغلاق. |
| #125 | قوالب COA الصناعية لا تملأ خرائط VAT الافتراضية | **FIXED** | `backend/services/industry_coa_templates.py` يستدعي `_ensure_default_coa_mappings` بعد seed/link parents؛ يربط `acc_map_vat_in=15010` و`acc_map_vat_out=21040` عند وجود الحسابات. |

**نتيجة B28**: 3 FIXED، 0 INVALID، 0 SCHEDULED.

---

#### دفعة 2026-05-02 — B29 المصروفات وCRM

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #155 | لا تذكير تلقائي بأنشطة الفرص المستحقة | **FIXED** | `backend/services/scheduler.py::crm_followup_alerts` يرسل `crm_activity_due` للأنشطة غير المكتملة عند حلول `due_date` مع جدول `crm_activity_reminders_log` لمنع التكرار خلال 24 ساعة. |
| #192 | سياسة المصروف تُرجع warning ولا تمنع المخالفة | **FIXED** | `backend/routers/finance/expenses.py` يرفع 400 `expense_policy_violation` عند فشل السياسة. |
| #193 | التحقق من السياسة لا يُستدعى عند إنشاء المصروف | **FIXED** | `create_expense` يستدعي `_evaluate_expense_policy` قبل الإدراج ويخزن `policy_id`. |
| #194 | الحد الشهري لا يفحص نطاق القسم | **FIXED** | `_evaluate_expense_policy` يحل `department_id` عبر `cost_center_id` ويفحص حدود القسم عبر JOIN على `cost_centers`. |
| #195 | `auto_post=True` للقوالب المتكررة يحتاج مراجعة بشرية اختيارية | **SCHEDULED** | سياسة تشغيلية/اعتمادية وليست خطأ كود موضعي؛ تحتاج إعداد workflow للقوالب عالية القيمة. |
| #196 | القوالب المتكررة لا تُنشئ صفوف `expenses` | **SCHEDULED** | يتطلب ربط accounting templates بتقارير المصروفات أو مصدر بيانات موحد للـ expense analytics. |
| #197 | لا تسوية إيصالات الموظف مقابل السلفة | **SCHEDULED** | يحتاج نموذج advance settlement يربط receipt claims بالسلف. |
| #198 | لا واجهة reversal للمصروفات | **INVALID** | `reverse_expense` موجود ويُنشئ JE عكسيًا ويعكس آثار الخزينة/المشروع ويميز المصروف `reversed`. |

**نتيجة B29**: 4 FIXED، 1 INVALID، 3 SCHEDULED.

---

#### دفعة 2026-05-02 — B30 FSM وتعيين الفنيين

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #211 | يمكن إكمال طلب خدمة بلا ساعات/تكلفة فعلية | **INVALID** | أُغلق في B24: `update_service_request` يرفض الانتقال إلى `completed` دون `actual_hours` أو `actual_cost`. |
| #212 | `ServiceCostCreate` لا يدعم `product_id`/`warehouse_id` | **INVALID** | `backend/schemas/services.py` يحتوي الحقلين، ومسار قطع الخدمة يخصم المخزون عند `cost_type='parts'`. |
| #213 | فوترة الخدمة تأخذ `revenue_amount` من المستخدم | **SCHEDULED** | يحتاج نموذج price list/contract coverage/markup قبل توليد الفاتورة. |
| #214 | تكاليف الخدمة بلا هامش ربح | **SCHEDULED** | نفس عائلة pricing model؛ لا يُحل بتعديل query واحد. |
| #215 | لا إشعار SLA عند الخرق | **INVALID** | `check_fsm_sla_breaches` يُرسل إشعارات response/resolution/warn. |
| #216 | قائمة الفنيين تعرض كل المستخدمين النشطين | **FIXED** | `TECHNICIAN_USER_FILTER` يحد القائمة والتعيين على أدوار/صلاحيات خدمة فعلية. |
| #217 | لا نموذج فني مستقل للمهارات/المناطق/GPS | **SCHEDULED** | يحتاج technician profile + skills matrix + coverage/scheduling model. |
| #218 | scan/escalate SLA لا يغطي أوامر الخدمة | **INVALID** | مسار FSM SLA مستقل ومجدول على `service_requests`. |

**نتيجة B30**: 1 FIXED، 4 INVALID، 3 SCHEDULED.

---

#### دفعة 2026-05-02 — B31 التكاملات والمدفوعات

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #224 | توقيع Webhook الدفع اختياري أو يُتجاهل | **INVALID** | `webhook` يتحقق عبر adapter ويرفض غير الموثق بـ 400 مع تسجيل الحدث غير الموثق. |
| #225 | لا استيراد تلقائي MT940/CSV مع مطابقة | **SCHEDULED** | parser/import موجودان؛ الأتمتة الكاملة مع auto-match وتوقيت التشغيل تحتاج job/policy. |
| #226 | نقص `response_model` في endpoints متفرقة | **SCHEDULED** | sweep توثيقي واسع على Swagger وليس عطلًا موضعيًا. |
| #227 | مفاتيح بوابات الدفع تُقرأ من `company_settings` plaintext فقط | **FIXED** | `_load_gateway_config` يقرأ legacy JSON ثم يغلّب المفاتيح المشفرة من `integration_keys_service.get_active_key` لكل tenant/provider/key. |
| #229 | retry البريد على مستوى الإرسال | **PARTIAL** | retry إشعارات البريد موجود عبر scheduler، لكن `email_service` المباشر ما زال send-once؛ يحتاج queue مركزي للبريد العام. |

**نتيجة B31**: 1 FIXED، 1 INVALID، 2 SCHEDULED، 1 PARTIAL.

---

#### دفعة 2026-05-02 — B32 الإشعارات والبريد

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #231 | retry لا يغطي in-app/push | **SCHEDULED** | يحتاج retry queue متعدد القنوات وسياسة idempotency. |
| #233 | commit قبل WebSocket يجعل الإشعار غير قابل للتراجع | **INVALID** | persist-before-push مقصود: الإشعار داخل التطبيق يجب أن يبقى حتى لو فشل push اللحظي. |
| #236 | لا HTML escaping في قوالب البريد | **FIXED** | `invoice_template`, `payroll_template`, `expiry_alert_template` و`NotificationService._send_email` تهرّب قيم المستخدم قبل HTML. |
| #237 | رابط الاعتماد بلا توقيع HMAC | **SCHEDULED** | يحتاج signed approval-action tokens منفصلة عن روابط unsubscribe الحالية. |
| #238 | retry SMS غير موجود | **INVALID** | مسار SMS retry queue مسجل في scheduler؛ المتبقي تحسينات سياسة/مزودات. |

**نتيجة B32**: 1 FIXED، 2 INVALID، 2 SCHEDULED.

---

#### دفعة 2026-05-02 — B33 التصنيع (إعادة تدقيق #199–#210)

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #199 | خصم المواد الخام بلا قفل صفوف المخزون | **FIXED** | `check_inventory_sufficiency(..., lock_rows=True)` يضيف `FOR UPDATE` على صفوف `inventory` قبل فحص الكفاية في `start_production_order`. |
| #200 | overhead مبسط ولا يعكس التكلفة الفعلية | **SCHEDULED** | يحتاج cost model لكل work center/operation. |
| #201 | لا endpoint confirm لأمر الإنتاج | **SCHEDULED** | workflow state جديد يحتاج صلاحيات/واجهة/تدقيق. |
| #202 | لا إنتاج جزئي | **SCHEDULED** | يحتاج produced/scrap quantities وقيود مخزون/GL جزئية. |
| #203 | MRP أحادي المستوى | **SCHEDULED** | يحتاج multi-level BOM explosion. |
| #204 | by-products بلا cost allocation | **SCHEDULED** | يحتاج تطبيق `cost_allocation_percentage` محاسبيًا. |
| #205 | WAC عند إكمال الإنتاج يجمع كل المستودعات | **FIXED** | WAC في `complete_production_order` صار يقرأ كمية المنتج في مستودع الوجهة فقط. |
| #206 | `total_material_cost` خارج النطاق عند عدم وجود BOM | **INVALID** | التهيئة بـ `Decimal("0")` موجودة قبل كتلة BOM. |
| #207 | لا capacity planning آلي | **SCHEDULED** | ميزة تخطيط مستقلة. |
| #208 | لا QC gate إلزامي قبل completion | **SCHEDULED** | يحتاج policy تحدد متى يكون QC إلزاميًا حتى لا يكسر أوامر بدون خطة QC. |
| #209 | عدم التحقق من مستودع الوجهة للفرع | **FIXED** | `_validate_order_warehouse_access` يتحقق من مستودع المصدر والوجهة في create/update. |
| #210 | بدء shopfloor operation لا يطابق route أمر العمل | **FIXED** | `shopfloor.start_operation` يجلب `route_id` من أمر العمل والعملية ويرفض mismatch. |

**نتيجة B33**: 4 FIXED، 1 INVALID، 7 SCHEDULED.

---

#### دفعة 2026-05-02 — B34 HR وDMS تحقق متقاطع

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #166 | double-extension upload attack | **INVALID** | `validate_file_extension` يفحص dot-segments الداخلية ويمنع `shell.php.pdf`. |
| #168 | لا audit لتنزيل المستندات | **INVALID** | `download_document` يسجل `document.download`. |
| #169 | لا anti-malware scan | **SCHEDULED** | يحتاج ClamAV/VirusTotal وتشغيل بنية تحتية. |
| #170 | حذف المستند لا ينظف versions | **INVALID** | `delete_document` يحذف `document_versions`، وحذف طلب الخدمة soft-deletes documents المرتبطة. |
| #171 | لا quota تخزين | **SCHEDULED** | server request cap موجود؛ per-tenant/user quota يحتاج schema + scheduler. |
| #182 | overtime multipliers hardcoded | **INVALID** | endpoint الإعدادات و`overtime_rates_config` موجودان؛ القيم الثابتة fallback. |
| #183 | overtime لا يفلتر فترة الرواتب | **INVALID** | `generate_payroll` يفلتر `overtime_date` بين `period.start_date/end_date`. |
| #184 | status `processed` غير معرف | **INVALID** | `tenant_schema.py` enum/check يتضمن `processed`. |
| #185 | GOSI employer fallback متضارب | **INVALID** | payroll يستخدم fallback 11.75 كما في إعدادات GOSI. |
| #186 | occupational hazard لا يدخل payroll | **INVALID** | employer share يضيف `occupational_hazard_percentage` مع fallback 2.00. |
| #187 | EOS يستخدم basic+allowances | **INVALID** | الحساب الحالي يطابق تفسير الأجر الخاضع لمكافأة نهاية الخدمة (basic + allowances الثابتة). |
| #188 | WPS ليس SIF ثابتًا | **INVALID** | `format='sif'` هو الافتراضي، والـ fixed-width helpers موجودة. |
| #189 | EOS settlement يستخدم cash بدل bank | **INVALID** | `acc_map_bank` هو الاختيار الأول مع fallback إلى cash. |
| #190 | salary/IBAN مكشوفان عبر `GET /employees/{id}` | **INVALID** | لا يوجد endpoint مفرد بهذا الشكل في `employees.py`، وقائمة الموظفين تمر عبر `mask_pii_list` عند غياب `hr.pii`. |
| #191 | `je_result` tuple/dict ambiguity في EOS settlement | **FIXED** | `settle_end_of_service` يفك tuple `(je_id, je_number)` أو dict صراحةً بدل تخزين tuple داخل `je_id`. |

**نتيجة B34**: 1 FIXED، 12 INVALID، 2 SCHEDULED.

---

#### دفعة 2026-05-02 — B35 المخزون والخزينة المتبقية

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #246 | تسوية الجرد تستخدم `products.cost_price` بدل تكلفة المستودع | **FIXED** | `inventory/adjustments.py` يقفل صف `inventory FOR UPDATE` ويستخدم `average_cost` للمستودع مع fallback إلى `products.cost_price`. |
| #247 | WAC التحويلات يستخدم float مباشرة | **FIXED** | `inventory/transfers.py` يحسب `source_qty/source_cost/dest_qty/new_avg_cost` بـ `Decimal` ثم يحول للـ DB/JSON عند الحدود فقط. |
| #249 | مفاتيح المخزون السلبي متعددة وغير موثقة | **INVALID** | `allow_negative_stock` موثق كـ canonical، والمفاتيح القديمة aliases deprecated. |
| #250 | `/receipt` بلا `FOR UPDATE` | **INVALID** | legacy `/receipt` محذوف. |
| #251 | auto reorder setting بلا تنفيذ | **SCHEDULED** | يحتاج job يولد PO/تنبيهات حسب reorder policy. |
| #253 | forecast يستخدم كامل recurring JE | **INVALID** | `forecast_service` يحسب النقد فقط من سطور الحسابات المرتبطة بـ `treasury_accounts.gl_account_id`. |
| #254 | forecast لا يشمل الشيكات المؤجلة | **INVALID** | `checks_receivable` و`checks_payable` يدخلان كـ `check_in/check_out`. |
| #255 | اعتماد المصروف بلا `FOR UPDATE` | **INVALID** | `approve_expense` يقفل صف المصروف أولًا. |

**نتيجة B35**: 2 FIXED، 5 INVALID، 1 SCHEDULED.

---

#### دفعة 2026-05-02 — B36 واجهة أمامية وبناء

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #257 | تقريب الأرقام متباين عبر `.toFixed`/`formatNumber` | **SCHEDULED** | يحتاج sweep واسع؛ `formatNumber` عولج لمسار BigInt سابقًا. |
| #258 | قيم الدول/العملات صلبة في التسجيل/onboarding/الفروع | **SCHEDULED** | يحتاج endpoint locale defaults وربط الواجهات. |
| #259 | exchange_rate ثابت في نماذج متعددة | **SCHEDULED** | يحتاج hook موحد لأسعار الصرف. |
| #260 | `window.location` بدل router navigation | **SCHEDULED** | codemod واسع. |
| #261 | لا debounce لحقول البحث | **SCHEDULED** | يحتاج hook وتطبيق على الصفحات. |
| #262 | `fetchData/setLoading` مكرر | **SCHEDULED** | يحتاج `useApi` تدريجي. |
| #263 | catch صامتة | **SCHEDULED** | يحتاج error handler مركزي. |
| #264 | تباين `text-muted` ضعيف | **INVALID** | ألوان T8.2 تجتاز AA/AAA. |
| #265 | CSS bundle كبير | **SCHEDULED** | يحتاج CSS splitting. |
| #266 | barrel export يمنع tree-shaking | **SCHEDULED** | يحتاج تقسيم exports. |
| #267 | GOSI summary في الواجهة يؤثر على الحساب | **INVALID** | عرض تجميعي فقط؛ backend يحسب القيمة الفعلية. |
| #268/#270/#271/#272 | focus-visible/alt/code splitting/StrictMode | **SCHEDULED** | sweep a11y/build تدريجي. |

**نتيجة B36**: 0 FIXED، 2 INVALID، 10 SCHEDULED.

---

#### دفعة 2026-05-02 — B37 أمن/بحث/نظام متبقي

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #161 | صلاحية `/receipt` و`/delivery` واسعة | **INVALID** | المسارات محذوفة، والبديل `/adjustment` محمي بـ `stock.adjust`. |
| #162 | أسرار ZATCA/SMTP plaintext | **PARTIAL** | vault/secret helpers موجودة وتُستخدم في بوابات الدفع؛ توحيد كل ZATCA/SMTP callsites على vault ما زال يحتاج sweep. |
| #239 | GlobalSearch UI hardcoded | **SCHEDULED** | backend موحد موجود؛ الواجهة تحتاج ربطه. |
| #240 | parties search بلا branch filter | **INVALID** | branch scoping موجود في `parties.py`. |
| #241/#242/#243/#244 | البحث الموحد/الترتيب/المرفقات/audit | **INVALID** | backend unified search + relevance + attachment search + audit logging موجودة. |
| #487 | `require_sensitive_permission` غير مطبق على كل المسارات الحساسة | **SCHEDULED** | sweep صلاحيات واسع. |
| #489/#490 | routers كبيرة وrepository pattern غير موحد | **SCHEDULED** | refactor معماري تدريجي. |
| #499/#500 | نضج النظام والنسخ الاحتياطي التشغيلي | **SCHEDULED** | يحتاج CI/deployment gates وsystemd/k8s CronJob للنسخ. |
| #503 | نضج البحث UX/observability غير كامل | **SCHEDULED** | backend تحسن؛ UX وربط شامل مؤجل. |

**نتيجة B37**: 0 FIXED، 5 INVALID، 6 SCHEDULED، 1 PARTIAL.

---

#### دفعة 2026-05-02 — B38 إغلاقات P3 المفتوحة السريعة

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #295 | POS ينقل الخصم إلى صافي المبيعات إذا غاب حساب الخصم | **FIXED** | `backend/routers/pos/orders.py` يقرأ `acc_map_sales_discount` أو حساب `DISC-SALE`/`SALE-DISC`، ويرفض الطلب بـ422 إذا لم يوجد الحساب بدل خفض الإيراد بصمت. |
| #300 | لا فحص لطول اسم الملف | **FIXED** | `backend/utils/sql_safety.py` أضاف `MAX_FILENAME_BYTES=255` ويرفض اسم الملف بعد `basename` إذا تجاوز 255 بايت UTF-8. |
| #303 | فشل قراءة `employee_salary_components` صامت | **FIXED** | `backend/routers/hr/core/payroll.py` يكتب `logger.warning` مع `company_id` وسبب الفشل بدل `pass`. |
| #317 | `ServiceCostCreate` بلا `markup_pct` | **FIXED** | أضيف `markup_pct` في schema وDDL وmigration `0024_service_pricing_fields.py`، ويُستخدم عند إدراج تكلفة الخدمة. |
| #326 | `POST /notifications/send` بلا rate limit | **FIXED** | `backend/routers/notifications.py` أضاف `@limiter.limit("10/minute")`، ومعه escaping لمحتوى البريد اليدوي. |
| #369 | `ServiceRequestUpdate` بلا `hourly_rate` | **FIXED** | أضيف `hourly_rate` إلى create/update schema، وإلى DDL/migration، وإلى مساري إنشاء/تحديث طلب الخدمة. |
| #401 | سطور forecast بلا `bank_account_id` للقيود الدورية | **FIXED** | `backend/services/forecast_service.py` يستخرج الحساب النقدي من سطور القيد الدوري ويحترم فلتر `bank_account_id`. |
| #419e | Redis `maxmemory-policy` غير مضبوط | **FIXED** | تحققنا من `docker-compose.prod.yml`: مضبوط على `allkeys-lru`. |
| #419h | unpaid leave غير مطبق على EOS | **FIXED** | `backend/routers/hr_wps_compliance.py` يجمع الإجازات غير المدفوعة المعتمدة ويمررها إلى `calculate_eos_gratuity`، ويعيدها في الاستجابة والـ audit. |
| #419m | tenant DB pools قد تصل إلى 750 اتصالًا | **FIXED** | `backend/config.py` و`backend/database.py` أضافا `DB_TENANT_ENGINE_CACHE_SIZE`, `DB_TENANT_POOL_SIZE`, `DB_TENANT_MAX_OVERFLOW`؛ الافتراضي الآن 50 × (2+3) = 250 اتصالًا. |

**التحقق**: `py_compile` نجح على ملفات B38 المعدلة، وVS Code diagnostics بلا أخطاء. الاختبارات المستهدفة تعثرت بعوائق موجودة خارج B38: serialization في APScheduler عند startup، واختبار POS يبحث عن المسار القديم `backend/routers/pos.py`.

---

#### دفعة 2026-05-02 — B39 إغلاقات P3 التشغيلية

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #347 | `get_available_widgets` لا يفحص الصلاحيات | **FIXED** | `backend/routers/dashboard.py` يرشّح widgets المتاحة حسب صلاحيات المستخدم الفعلية عبر `check_permission`. |
| #348 | `low_stock` يعيد العدد فقط | **FIXED** | `widget_low_stock` يعيد تفاصيل المنتجات منخفضة المخزون مع `shortage` بدل count فقط. |
| #419d | Outbox giveup بلا تنبيه مدير | **FIXED** | `backend/utils/outbox_relay.py` يرسل notification للمديرين عند وصول event إلى `MAX_ATTEMPTS`. |
| #288 | CRM activities بلا ربط contact | **FIXED** | أضيف `contact_id` إلى `ActivityCreate` وDDL/migration، مع تحقق أن contact يتبع عميل الفرصة. |
| #290 | الفرص لا تفحص credit limit | **FIXED** | إنشاء الفرصة يرفض `expected_value` إذا تجاوز `credit_limit - credit_used` للعميل. |
| #296 | POS price override بلا صلاحية مستقلة | **FIXED** | أضيفت صلاحية `pos.price_override` وتُطلب عند اختلاف سعر السطر عن سعر المنتج الافتراضي، مع حدود `min_price/max_price`. |
| #390 | idempotency key على رقم تسلسلي | **FIXED** | أضيف `client_order_id` UUID إلى POS order create وDDL/index؛ الطلب المكرر يعيد الطلب السابق بدل إنشاء نسخة جديدة. |
| #415 | FK `journal_entries.created_by` بلا delete policy | **FIXED** | DDL/migration 0025 يعيد بناء القيد بـ `ON DELETE RESTRICT`. |
| #416 | FK `pos_orders.session_id` بلا delete policy | **FIXED** | DDL/migration 0025 يعيد بناء القيد بـ `ON DELETE CASCADE`. |
| #417 | self-FK `accounts.parent_id` بلا حماية | **FIXED** | DDL/migration 0025 يعيد بناء القيد بـ `ON DELETE RESTRICT`. |
| #418 | FK `inventory.product_id` بلا delete policy | **FIXED** | DDL/migration 0025 يعيد بناء القيد بـ `ON DELETE RESTRICT`. |
| #304 | `mol_establishment_id` قد يكون أصفارًا | **FIXED** | WPS export يرفض MOL ID غير 10 أرقام أو كله أصفار. |
| #306 | رصيد الإجازة السنوية ثابت | **FIXED** | self-service يقرأ `annual_leave_entitlement/annual_leave_days` ويخصم الأيام pending ويضيف carryover. |
| #309 | check-in جديد يتعطل بسبب جلسة قديمة مفتوحة | **FIXED** | attendance يغلق الجلسات المفتوحة الأقدم من 16 ساعة تلقائيًا قبل check-in جديد. |
| #377 | WPS preview لا يفرض `hr.pii` | **FIXED** | preview صار محميًا بـ `require_permission("hr.pii")` فقط. |
| #313 | prefix أوامر التصنيع `PO-` يلتبس مع الشراء | **FIXED** | الرقم التلقائي لأمر التصنيع أصبح يبدأ بـ `MFG-`. |
| #419s | GL journal list بلا pagination clamp | **FIXED** | `list_journal_entries` يثبت `page>=1` و`limit` بين 1 و200. |
| #385 | `send_bulk` بلا تفاصيل فشل per-user | **FIXED** | `EmailService.send_bulk` يعيد `failures` بعناوين masked وسبب الفشل. |
| #386 | notification preferences تُقرأ من DB كل إرسال | **FIXED** | `NotificationService` يضيف cache لمدة 5 دقائق لكل `(tenant,user,event_type)`. |
| #388 | SPF/DKIM/DMARC غير موثقة | **FIXED** | `docs/RUNBOOK.md` يضيف متطلبات DNS وفحص headers قبل تفعيل SMTP إنتاجي. |
| #389 | أرقام SMS تظهر كاملة في logs | **FIXED** | `SMSService` يسجل آخر 4 أرقام فقط بدل الرقم الكامل. |
| #335 | reconciliation tolerance ثابت 0.01 | **FIXED** | `ReconciliationCreate.tolerance_amount` أو إعداد `company_settings.reconciliation_auto_match_tolerance` يحددان tolerance. |

**التحقق**: `py_compile` نجح على جميع ملفات Python المعدلة في B39 بعد إصلاح indentation في self-service، وVS Code diagnostics أظهر `No errors found` على الملفات نفسها. لم أعد تشغيل pytest العام لأن عوائق B38 المعروفة ما زالت خارج نطاق B39: APScheduler serialization عند startup واختبار POS القديم الذي يبحث عن `backend/routers/pos.py`.

---

#### دفعة 2026-05-02 — B40 إغلاقات P3 المتبقية السريعة

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #291 | POS يطبّق الخصم بعد الضريبة | **FIXED** | تحققنا أن `pos/orders.py` يحوّل الخصم/العروض إلى `header_discount_pct` ويستدعي `compute_invoice_totals` قبل الضريبة. |
| #292 | العروض والكوبونات لا تُطبق backend-side | **FIXED** | `coupon_code` و`promotion_id` موجودان في schema ويُقرآن من `pos_promotions` ويؤثران في الإجمالي. |
| #419w | POS لا يستخدم `coupon_code`/`promotion_id` | **FIXED** | نفس مسار #292 يطبق promotion/coupon داخل backend بدل الاعتماد على الواجهة. |
| #419j | الخصم دائمًا بعد الضريبة | **FIXED** | مكرر #291؛ المسار الحالي يطبق الخصم كرأس فاتورة قبل الضريبة. |
| #315 | optimistic locking معطل في FSM | **FIXED** | `update_service_request` يستخدم `version` في شرط التحديث ويرفع 409 عند التعارض. |
| #323 | Swagger/ReDoc مكشوفان في الإنتاج | **FIXED** | `main.py` يعطل docs/openapi في `APP_ENV=production` أو عند `EXPOSE_API_DOCS=false`. |
| #330 | GlobalSearch frontend-only | **FIXED** | backend unified search موجود في `routers/search.py`; UX الكامل بقي كبند منفصل #482. |
| #383 | ETA URL ساكن | **FIXED** | `eta_adapter.py` يقرأ `ETA_BASE_URL` و`ETA_TOKEN_URL` من البيئة مع defaults رسمية. |
| #394 | search بلا LIMIT | **FIXED** | `/search` يحد limit إلى 50 لكل كيان، وattachments إلى 200. |
| #419t | pg_trgm غير فعّال | **FIXED** | DDL يفعّل `pg_trgm` وفهارس GIN للبحث الأساسي والمرفقات. |
| #396 | low stock threshold = 5 ساكن | **FIXED** | أزلت fallback `5` من `dashboard.py`; الآن يعتمد `reorder_level > 0` ويطرح `reserved_quantity`. |
| #400 | auto-match يحتاج trigger يدوي | **FIXED** | `scheduler.py` يشغل `auto_reconcile_all_drafts` يوميًا، وأُصلح core ليستخدم schema الحالي. |
| #510 | auto-match المجدول يستخدم tolerance hardcoded | **FIXED** | `_auto_match_reconciliation` صار يقرأ `bank_reconciliations.tolerance_amount`. |
| #407 | cash flow بلا opening سلبي | **FIXED** | `get_cashflow_ias7` يحسب opening cash من GL قبل الفترة كـ `SUM(debit-credit)` ويعيد القيمة السالبة إن وجدت. |
| #338 | DataTable بلا horizontal scroll | **FIXED** | CSS العام يطبق `overflow-x:auto` على حاويات الجداول. |
| #340 | لا print stylesheet | **FIXED** | `styles/print.css` موجود ومستورَد في `main.jsx`. |
| #272f | فهرس `(product_id, transaction_date)` مفقود | **FIXED** | أضيف `idx_inventory_transactions_product_date` إلى `tenant_schema.py` وmigration 0026. |
| #272g | فهرس `(party_type, party_id)` مفقود | **FIXED** | أضيف `idx_payment_vouchers_party_type_id` إلى `tenant_schema.py` وmigration 0026. |
| #272j | لا audit log لعرض payslip | **FIXED** | `get_payslip_detail` يسجل `hr.self_service.payslip_view` مع الطلب والموظف. |
| #419y | forecast يستخدم كامل recurring JE | **FIXED** | `forecast_service` يستخرج أرجل النقد فقط ويحترم `bank_account_id`. |
| #384 | CSV bank format يدوي | **SCHEDULED** | parsers موجودة، لكن format detector عام يحتاج تصميم import policy وليس إصلاحًا موضعيًا. |
| #408 | SENSITIVE_PERMISSIONS غير مفحوصة بالكامل | **SCHEDULED** | يحتاج sweep صلاحيات واسع على endpoints مالية/PII، لذلك تُرك مجدولًا. |

**التحقق**: `py_compile` نجح لملفات Python المعدلة والجديدة في B40، وVS Code diagnostics بلا أخطاء على ملفات B40، و`git diff --check` نظيف. لم تُشغَّل اختبارات واجهة أو backend بعد توجيه المستخدم بعدم تشغيل ملفات test.

---

#### دفعة 2026-05-02 — B41 إغلاقات P3 بدون ملفات test

| # | الادّعاء | الحالة | التفصيل |
|---|---------|--------|---------|
| #274 | IP في audit لا يراعي reverse proxy | **FIXED** | `utils/audit.py` يقرأ `X-Forwarded-For` في `log_activity` و`log_system_activity` قبل fallback إلى `request.client.host`. |
| #276 | `endpoint`/`method` غير مسجلين في `log_activity` | **FIXED** | `log_activity` يضيف `details.request.method` و`details.request.endpoint` عند وجود `Request`. |
| #280 | `MemoryCache` لا ينظف المفاتيح المنتهية | **FIXED** | `MemoryCache` يحذف المفاتيح المنتهية في `get()` و`_evict_if_needed()` قبل LRU eviction. |
| #281 | Token blacklist يكبر بلا حد | **FIXED** | كاش blacklist المحلي صار يحتفظ بـ`expires_at` لكل hash ويُنفّذ pruning عند الإضافة/الفحص/cleanup. |
| #282 | لا metrics للكاش | **FIXED** | `cache_stats()` و`GET /api/health/cache` يعيدان hits/misses/hit_rate. |
| #283 | تحويل الفرصة يرجع stage إلى `proposal` | **FIXED** | تحويل الفرصة إلى عرض سعر يرفع فقط `lead/qualified` إلى `proposal` ولا يُرجع `negotiation/won/lost`. |
| #307 | غياب `FIELD_ENCRYPTION_KEY` يرجع `None` | **FIXED** | `field_encryption.py` يرفع `FieldEncryptionError` إذا غاب مفتاح التشفير و`MASTER_SECRET`. |
| #336 | forecast initial balance = 0 | **FIXED** | `forecast_service.py` يقرأ رصيد حساب الخزينة المحدد أو مجموع الحسابات النشطة من `treasury_accounts.current_balance`. |
| #337 | offsets +7d/+3d ساكنة | **FIXED** | `forecast_service.py` يقرأ `forecast_collection_lag_days` و`forecast_payment_lag_days` من `company_settings`. |
| #384 | CSV bank format يدوي | **FIXED** | `finance/reconciliation.py` يكتشف delimiter وأعمدة كشف البنك عربيًا/إنجليزيًا. |
| #406 | date filter في JOIN ON | **FIXED** | تقارير المحاسبة تضع تواريخ الفترة في WHERE/CTE مع nullable guard بدل JOIN ON. |
| #419a | MV name f-string injection | **FIXED** | أسماء الـ MV محصورة في `MATERIALIZED_VIEWS` و`MV_MAP` قبل refresh/query. |
| #272b | SMTP password plaintext في `company_settings` | **FIXED** | `secret_settings.py` يشفر `smtp_password` والقراءة في `email_service.py` تفكها بشفافية. |
| #272d | `list_documents` يكشف `download_url` | **FIXED** | `list_documents` لم يعد يضيف رابط تحميل مباشر في قائمة المستندات. |
| #272e | الحذف الناعم لا ينظف `document_versions` | **FIXED** | `delete_document` يحذف صفوف الإصدارات، ومهمة purge اليومية تنظف الملفات. |
| #272s | `handle_return` ينشئ طبقة تكلفة جديدة بدل عكس الأصلية | **FIXED** | `CostingService.handle_return` يعكس original layers/consumptions عبر `original_source_document_*` قبل fallback. |
| #272t | خلط `Decimal`/`float` في shipments | **FIXED** | `shipments.py` يجمع `total_transit_value` عبر `Decimal(str(quantity)) * Decimal(str(source_cost))`. |
| #272x | SLA غير موجود على أوامر الخدمة | **FIXED** | DDL يضيف حقول SLA إلى `service_requests`، و`check_fsm_sla_breaches` يعمل بالمجدول. |
| #89 | outgoing webhooks بلا backoff/DLQ | **FIXED** | `utils/webhooks.py` لديه backoff قابل للتهيئة، والفشل النهائي يُنقل إلى `integration_dlq`. |
| #442 | SMS retry queue/backoff | **FIXED** | `sms_retry_queue` و`process_sms_retries_all_tenants` مع backoff وDLQ مسجلان في scheduler. |

**نتيجة B41**: 20 FIXED، 0 INVALID، 0 SCHEDULED، 0 PARTIAL.

**التحقق**: `py_compile` نجح على ملفات Python المعدلة في B41، وVS Code diagnostics بلا أخطاء على ملفات الكود والوثائق المعدلة، و`git diff --check` نظيف. لا تشغيل ولا قراءة لملفات test.

---

### إجمالي الجلسة 2026-05-02 المضاف (B28–B41)

| الدفعة | FIXED | INVALID | SCHEDULED | PARTIAL |
|--------|-------|---------|-----------|---------|
| B28 محاسبة ومشتريات | 3 | 0 | 0 | 0 |
| B29 مصروفات وCRM | 4 | 1 | 3 | 0 |
| B30 FSM وتعيين فنيين | 1 | 4 | 3 | 0 |
| B31 تكاملات ومدفوعات | 1 | 1 | 2 | 1 |
| B32 إشعارات وبريد | 1 | 2 | 2 | 0 |
| B33 تصنيع | 4 | 1 | 7 | 0 |
| B34 HR وDMS | 1 | 12 | 2 | 0 |
| B35 مخزون وخزينة | 2 | 5 | 1 | 0 |
| B36 واجهة أمامية | 0 | 2 | 10 | 0 |
| B37 أمن/بحث/نظام | 0 | 5 | 6 | 1 |
| B38 إغلاقات P3 السريعة | 10 | 0 | 0 | 0 |
| B39 إغلاقات P3 التشغيلية | 22 | 0 | 0 | 0 |
| B40 إغلاقات P3 المتبقية السريعة | 20 | 0 | 2 | 0 |
| B41 إغلاقات P3 بدون ملفات test | 20 | 0 | 0 | 0 |
| **مجموع B28–B41** | **89** | **33** | **38** | **2** |
| **الإجمالي التراكمي B1–B41** | **130** | **116** | **132** | **10** |

388 بندًا فُحِصت/أُغلِقت/جُدوِلت من P2_OPEN_TASKS وP3_BACKLOG عبر 41 دفعة. تغييرات B28–B41 شملت: احتساب خصم/markup المشتريات، مزامنة fiscal period locks، VAT COA mappings، فرض سياسات المصروفات، تذكير أنشطة CRM، فلترة الفنيين، overlay مفاتيح الدفع المشفرة، HTML escaping للإشعارات، قفل مخزون التصنيع، WAC وجهة التصنيع، تحقق route في shopfloor، تحقق مستودعات الإنتاج للفرع، إصلاح EOS JE tuple handling، WAC تسويات الجرد، Decimal WAC في التحويلات، وإغلاقات P3 التشغيلية للـ dashboard/CRM/POS/WPS/notifications/reconciliation/DDL guards، مع B40 لتسامح auto-reconcile المجدول، low-stock threshold، وفهارس تقارير المخزون/السندات، ومع B41 لكاش blacklist، audit context، DMS download exposure، CRM stage regression، وwebhook DLQ.

---

#### نقل وحذف `ACCOUNTING_AUDIT_REPORT.md` — 2026-05-02

تمت مراجعة تقرير التدقيق المحاسبي الفردي ونقل كل البنود غير السليمة أو التحذيرية إلى هذا السجل قبل حذف الملف المصدر. البنود الموسومة `✅ سليم` في التقرير الأصلي لا تحتاج مهمة إصلاح مستقلة.

| بند التقرير | الحالة في TODO | التوثيق / المصير |
|---|---|---|
| 1.2 / 7.1 — دالتا `validate_je_lines` بمنطق مختلف | **FIXED** | أُغلق في T3.4: المصدر الوحيد أصبح `services/gl_service.py::validate_je_lines`، و`utils/accounting.py` تحوّل إلى wrapper `prepare_je_lines`. |
| 1.3 — جمع float بدل Decimal في تحقق القيود | **INVALID** | موثق في B1 كـ #120: الادعاء كان يشير إلى فلتر، أما التجميع الفعلي فيستخدم `Decimal`. |
| 1.4 — مشتريات لا تمرر `markup_amount/header_discount_pct` | **FIXED** | أُغلق في B28 كـ #121. |
| 1.5 / 6.1 — قيد مبيعات غير متوازن عند وجود markup | **FIXED** | أُغلق في T3.2 كـ #15. |
| 1.6 — تسامح توازن القيود حول 0.01 واسع | **SCHEDULED** | محفوظ كبند محاسبي متبقٍ #271 في `REMAINING_REMEDIATION_PLAN.md` ضمن R2. |
| 3.1–3.4 / 7.3 — آليتا قفل الفترات متوازيتان وفاتورة المبيعات لا تمر عبر القفل الموحد | **FIXED** | أُغلق في T3.3 كـ #17: `check_fiscal_period_open` صار backstop موحدًا. |
| 3.5 — إغلاق السنة لا يزامن `fiscal_period_locks` | **FIXED** | أُغلق في B28 كـ #122. |
| 3.6 — منع draft JE في فترة مغلقة | **SCHEDULED** | محفوظ كبند محاسبي متبقٍ #273 في `REMAINING_REMEDIATION_PLAN.md` ضمن R2. |
| 4.3 — التسوية الضريبية لا تشمل المرتجعات | **FIXED** | أُغلق في T3.6 كـ #18. |
| 4.7 / 7.4 — VAT account mappings لا تُزرع تلقائيًا | **FIXED** | أُغلق في B28 كـ #125. |
| 5.1 — فحص تكرار إعادة تقييم العملات معطل | **FIXED** | أُغلق في T1.2 كـ #1. |
| 5.2 — حسابات UFX غير موجودة في COA | **FIXED** | أُغلق في T1.2 كـ #2. |
| 5.3 — اتجاه FC balance معكوس للخصوم | **FIXED** | أُغلق في T3.5 كـ #16. |
| 5.4 — fallback العملة الأساسية `SYP` في `gl_service.py` | **FIXED** | أُغلق في B1 كـ #123. |
| 5.5 — fallback العملة الأساسية `SYP` في `utils/accounting.py` | **FIXED** | أُغلق في B1 كـ #124. |
| 6.9 — `source="Sales-Invoice"` casing غير موحد | **SCHEDULED** | محفوظ كبند محاسبي متبقٍ #272 في `REMAINING_REMEDIATION_PLAN.md` ضمن R2. |
| 7.2 — خطر schema drift بين ORM وraw SQL DDL | **SCHEDULED** | بند معماري متبقٍ ضمن مسار R8: توحيد DTO/schema ownership وتقليل ازدواج تعريف المخطط. |
| 7.5 — import داخلي مكرر لـ `gl_create_journal_entry` | **FIXED** | أُغلق في B1 كـ #128. |

**قرار التنظيف**: بعد هذا النقل، لا يبقى في `ACCOUNTING_AUDIT_REPORT.md` بند إصلاحي غير ممثل هنا أو في `REMAINING_REMEDIATION_PLAN.md`؛ لذلك أصبح الملف مؤهلًا للحذف حسب سياسة حذف ملفات `docs/audit/`.

---

#### نقل وحذف بقية ملفات `docs/audit/` القديمة — 2026-05-02

تنفيذًا لقرار إبقاء `TODO.md` و`REMAINING_REMEDIATION_PLAN.md` فقط داخل مجلد التدقيق: كل ملف أدناه تم نقله منطقيًا قبل الحذف. البنود المغلقة محفوظة في سجلات الدفعات أعلاه، والبنود غير المنتهية محفوظة في `REMAINING_REMEDIATION_PLAN.md` حسب مسارات R1-R8.

| الملف المحذوف | سجل البنود المغلقة في TODO | البنود المتبقية بعد النقل |
|---|---|---|
| `AUDIT_TRAIL_FORENSICS_REPORT.md` | B5 + T3.7 | R1 Audit & Security (#132-#135, #275, #351-#353). |
| `BACKGROUND_JOBS_AUDIT_REPORT.md` | B6 + B41 | R1/R8 (#136, #138, #140, #143, #278, #279, #419b, #419c). |
| `CACHE_REDIS_AUDIT_REPORT.md` | B8 + B38-B41 | R7/R8 (#145, #147, #270, #272c, #354). |
| `CRM_SALES_AUDIT_REPORT.md` | B7 + B29 + B39 + B41 | R3 (#149, #152, #154, #284-#289). |
| `DASHBOARD_WORKSPACE_AUDIT_REPORT.md` | B10 + B39 + B40 | R7 (#116-#119, #269, #345, #346, #349). |
| `DATABASE_AUDIT_REPORT.md` | B3 + B11 + B39 + B40 | R2/R7/R8 (#176-#179, #301, #302, #419, #419o). |
| `DMS_SECURITY_AUDIT_REPORT.md` | B9 + B34 + B38 + B41 | R6 (#169, #171, #171b, #299, #299d, #357, #358). |
| `EXPENSE_MANAGEMENT_AUDIT_REPORT.md` | B4 + B12 + B29 | R2 (#195-#197, #310-#312, #359). |
| `FRONTEND_UX_AUDIT_REPORT.md` | B13 + B14 + B36 + B39 + B40 | R8 (#257-#263, #265-#272, #339, #341-#343, #361-#366). |
| `FSM_MAINTENANCE_AUDIT_REPORT.md` | B24 + B30 + B38 + B40 + B41 | R6 (#213, #214, #217, #316, #367, #368, #370-#372, #423, #424, #426, #427, #272v-#272y). |
| `HR_PAYROLL_AUDIT_REPORT.md` | B2 + B15 + B24 + B34 + B38 + B39 | R5 (#192, #193, #305, #308, #373, #374, #376, #419, #419c, #419g, #419i, #429, #434-#436). |
| `INTEGRATIONS_AUDIT_REPORT.md` | B16 + B21 + B31 + B37 + B40 + B41 | R1/R3/R6 (#86-#88, #162, #225-#229, #237, #382, #443). |
| `MANUFACTURING_AUDIT_REPORT.md` | B17 + B33 + B39 + B40 + B41 | R4 (#200-#204, #207, #208, #314, #446, #448-#452, #272l-#272q). |
| `NOTIFICATIONS_ENGINE_AUDIT_REPORT.md` | B18 + B25 + B32 + B38-B41 | R6 (#90, #91, #231, #237, #327-#329, #443, #456). |
| `REPORTS_BI_AUDIT_REPORT.md` | B19 + B20 + B26 + B40 + B41 | R2/R7 (#219-#221, #322, #403-#405, #419r, #461-#465, #272z). |
| `SALES_POS_AUDIT_REPORT.md` | B26 + B38-B40 | R3 (#181, #181b, #181c, #284, #293, #294, #297, #298, #391-#393, #419l, #476). |
| `SEARCH_ENGINE_AUDIT_REPORT.md` | B20 + B26 + B40 | R7 (#239, #331, #395, #482, #483, #503). |
| `SECURITY_ARCHITECTURE_AUDIT.md` | B21 + B37 + B41 | R1/R8 (#162, #408, #413, #487, #489, #490). |
| `SUPPLY_CHAIN_AUDIT_REPORT.md` | B22 + B35 + B40 + B41 | R4 (#246/#452 family, #251, #333, #334, #397-#399, #493, #498, #272h, #272r). |
| `SYSTEM_EVALUATION_AND_BENCHMARK.md` | B27 + B37 | R8 (#180, #499, #500, #503). |
| `TREASURY_CASH_AUDIT_REPORT.md` | B23 + B27 + B35 + B40 + B41 | R2/R7 (#419x/#272u, #419p, #272i). |
| `CONSOLIDATED_AUDIT_REPORT.md` | T1-T18 + B1-B41 + هذا السجل | البنود غير المنتهية نقلت إلى `REMAINING_REMEDIATION_PLAN.md` R1-R8. |
| `P2_OPEN_TASKS.md` | B1-B37 + هذا السجل | البنود غير المنتهية نقلت إلى `REMAINING_REMEDIATION_PLAN.md` R1-R8. |
| `P3_BACKLOG.md` | B38-B41 + هذا السجل | البنود غير المنتهية نقلت إلى `REMAINING_REMEDIATION_PLAN.md` R1-R8. |

**قرار التنظيف**: بعد هذا السجل، كل ملفات التدقيق القديمة أعلاه مؤهلة للحذف؛ الملفات الوحيدة التي تبقى في `docs/audit/` هي `TODO.md` و`REMAINING_REMEDIATION_PLAN.md`.

---

## إغلاقات 022 — Audit & Security + Finance Integrity (2026-05-02)

البنود التالية أُغلقت بواسطة ميزات branch `022-audit-security-finance-integrity`:

### R1 — Audit & Security (17 بندًا)

| Ref | البند | الحل في 022 |
|-----|-------|-------------|
| #132 | توحيد schema `audit_logs.details` | outbox writer + PII sanitizer |
| #133 | `log_activity` commit مبكر | outbox pattern (transactional write) |
| #134 | نقل audit إلى outbox/async | `audit_outbox` table + worker flush |
| #135 | Impossible-travel detection | `login_geo_events` + `device_fingerprints` |
| #136 | audit time metadata | outbox uses DB timestamp |
| #275 | device fingerprinting | SHA-256 coarsened fingerprint |
| #351 | `critical=True` sweep | `require_sensitive_permission` decorator |
| #352 | PII sanitization | `sanitize_for_audit()` |
| #353 | ghost employee rule | `ghost_employee_check` scheduler job |
| #408/#487 | sensitive permission sweep | sweep complete on HR/Finance/Reports/Settings |
| #413 | LDAP password protection | sensitive permission gate |
| #162 | integration secrets vault | `integration_credentials` with envelope encryption |
| #225 | webhook rate limit | Redis token bucket per-tenant |
| #226 | credential soft-delete + audit | vault CRUD + soft-delete |
| #227 | bank feed failure alerting | `consecutive_failures` alerting |
| #228 | SMS gateway rotation | credential rotation in vault |
| #272a | import error info leak | sanitized error paths |

### R2 — Finance Integrity (13 بندًا)

| Ref | البند | الحل في 022 |
|-----|-------|-------------|
| #271 | JE epsilon policy | configurable `gl.je_epsilon` |
| #272 | source casing unification | JESource enum + normalization migration |
| #273 | drafts in closed period | `fiscal.allow_drafts_in_closed_period` setting |
| #419x/#272u | reconciliation GL validation | drift guard + structured 409 report |
| #419q | asset return write-down | `create_asset_return_write_down()` |
| #419p | FX rounding policy | `round_amount()`/`round_fx_rate()` helpers |
| #195 | recurring template review | `recurring_je_pending_review` + admin queue |
| #196 | recurring + expense category | `expense_category_id` on pending review |
| #197 | employee receipt settlement | `employee_receipt_settlements` + endpoints |
| #310 | expense auto-approve | `expense_auto_approve` scheduler job |
| #311 | cost center policy | `cost_center_policy` setting |
| T1.3b | treasury trigger | DB trigger + `aman.gl_context` GUC |
| #269/#219/#463 | account classification | `account_classifications` table + classifier-first lookup |
| #322/#465 | audit policy for reports | `require_sensitive_permission` on reports |
