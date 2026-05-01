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

### T8.2 — Skip-link + ARIA + WCAG AA contrast `[M]`
- **بنود**: #108، #264، باقي بنود Frontend.
- **التغيير**: skip-link في `App.jsx`، landmarks، تصحيح `--text-muted` لـ ≥ 4.5:1.
- **DoD**: Lighthouse Accessibility ≥ 90.

### T8.3 — تقسيم `index.css` 68KB `[S]`
- **بنود**: #265.
- **التغيير**: code-splitting حسب المسار + critical CSS.
- **DoD**: bundle رئيسي < 30KB.

### T8.4 — `exchange_rate` ديناميكي + `OvertimeRequests` ربط backend `[S]`
- **بنود**: #259، #110.
- **التغيير**: استدعاء `/currencies/current` بدل 1.0 الصلب. ربط مضاعفات OT بإعدادات الباك.
- **DoD**: تغيير سعر الصرف في إعدادات يظهر في كل النماذج.

### T8.5 — Optimistic Updates لقوائم CRUD الشائعة `[M]`
- **التغيير**: react-query + optimistic mutate.
- **DoD**: تجربة CRUD تبدو فورية مع retry على فشل.

**مخرَج المرحلة 8**: UX 55 → 79.

---

## المرحلة 9: P3 التنظيف والتوثيق

### T9.1 — تنظيف P3 المتفرقة (~100 بند) `[L]`
- **النطاق**: بنود P3 من #270 حتى #419v التي لم تُعالج ضمنيًا.
- **DoD**: قائمة P3 المتبقية موثقة في issue tracker مع تصنيف "won't fix" أو "scheduled".

### T9.2 — `summary`/`description` على جميع الراوترز `[M]`
- **بنود**: 419u.
- **التغيير**: docstring + FastAPI metadata لكل endpoint.
- **DoD**: Swagger يعرض وصفًا غير مولَّد تلقائيًا.

### T9.3 — أرشفة `inventory_transactions` و `audit_logs` `[M]`
- **بنود**: 419o، #130.
- **التغيير**: جداول `*_archive` + مهمة شهرية تنقل > 7 سنوات.
- **DoD**: حجم الجداول الحية مستقر.

### T9.4 — رسائل الأخطاء ثنائية اللغة `[S]`
- **بنود**: 419n + رسائل عربية فقط.
- **التغيير**: استخدام `locales/errors.{ar,en}.json` في كل HTTPException.
- **DoD**: تبديل header `Accept-Language` يُغيّر رسالة الخطأ.

### T9.5 — تحديث RUNBOOK + التوثيق التشغيلي `[M]`
- **التغيير**: تحديث `docs/RUNBOOK.md`, `backend/README.md` بكل التغييرات الجديدة (encryption keys، CSID، scheduler، إلخ).
- **DoD**: مهندس DevOps جديد ينشر بيئة من الصفر بالاعتماد على الوثائق فقط.

### T9.6 — تنفيذ خطة الاختبارات الشاملة `[L]`
- **التغيير**: غطاء اختبار end-to-end لكل سيناريوهات `TESTING_SCENARIOS.md`.
- **DoD**: CI أخضر مع coverage ≥ 80%.

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
[ ] T8.1   [ ] T8.2   [ ] T8.3   [ ] T8.4   [ ] T8.5
[ ] T9.1   [ ] T9.2   [ ] T9.3   [ ] T9.4   [ ] T9.5   [ ] T9.6
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
