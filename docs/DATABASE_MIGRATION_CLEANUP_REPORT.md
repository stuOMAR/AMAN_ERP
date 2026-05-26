# تقرير تنظيف ملفات قاعدة البيانات والـ Migrations

تاريخ التقرير: 2026-05-26

## الهدف

الهدف المطلوب هو تحويل قاعدة بيانات AMAN ERP إلى شكل نظيف يشبه "الإصدار الأول":

- مصدر schema رئيسي واحد وواضح.
- baseline migration واحد أو مجموعة صغيرة جداً بدل تاريخ طويل من ملفات التطوير.
- عدم وجود تكرار في تعريف الجداول أو الأعمدة أو الفهارس.
- حذف ملفات migrations القديمة فقط بعد التأكد أن الملفات الرئيسية تنشئ schema كاملة وصحيحة من الصفر.

لم يتم حذف أي ملف migration في هذه المرحلة. تم تنفيذ تنظيف أولي محدود في الملفات الرئيسية لإزالة تكرار واضح وآمن.

## مصادر الحقيقة الحالية

| الملف | الدور الحالي | التقييم |
|---|---|---|
| `backend/db_ddl/tenant_schema.py` | مصدر DDL الرئيسي لقواعد بيانات الشركات | هو أهم ملف قبل أي حذف |
| `backend/db_ddl/tenant_runner.py` | يشغل blocks الموجودة في `tenant_schema.py` مع post-DDL fix-ups | نقطة orchestration الصحيحة |
| `backend/database.py` | ينشئ قاعدة الشركة ثم يستدعي `apply_tenant_schema()` ويعمل Alembic stamp على head | تم تنظيف DDL tenant المتكرر منه في هذه الجولة |
| `backend/alembic/versions/0001_baseline_complete.py` | baseline يستدعي `apply_tenant_schema()` | مناسب ليكون أساس الإصدار الأول |
| `backend/alembic/env.py` | يشغل migrations على system DB أو tenant DB حسب `-x company=` | صالح، لكن سيحتاج مراجعة بعد squash |
| `backend/main.py` | ينشئ جداول system database عند startup | ليس tenant schema، لكنه DDL مركزي يجب توثيقه |

## أرقام الحالة الحالية

| البند | العدد / الحالة |
|---|---:|
| ملفات `backend/alembic/versions/*.py` | 109 ملفات |
| ملفات `backend/migrations/versions/*.py` | 4 ملفات legacy |
| Alembic heads | head واحد: `031i_permissions_audit_hardening` |
| `CREATE TABLE IF NOT EXISTS` داخل `tenant_schema.py` | 381 |
| `CREATE INDEX IF NOT EXISTS` داخل `tenant_schema.py` | 397 |
| `ADD COLUMN IF NOT EXISTS` داخل `tenant_schema.py` | 131 |
| SQL builder functions داخل `tenant_schema.py` | 29 |

## تحقق ما قبل الحذف

تمت إضافة فحصين قبل السماح بحذف ملفات migrations:

| الفحص | الملف | النتيجة |
|---|---|---|
| مقارنة ثابتة بين migrations والـ baseline | `backend/scripts/check_tenant_schema_completeness.py` | `missing_columns=0` |
| إنشاء قاعدة tenant مؤقتة وتطبيق `apply_tenant_schema()` فعلياً | `backend/scripts/check_tenant_schema_bootstrap.py` | `missing_columns=0` |

نتيجة الفحص الفعلي:

- تم إنشاء قاعدة مؤقتة باسم من نمط `aman_schema_check_<pid>`.
- تم تطبيق `db_ddl.tenant_runner.apply_tenant_schema()` عليها.
- تم استخراج الجداول والأعمدة من `information_schema`.
- تمت مقارنتها مع 113 ملف migration/version.
- النتيجة: `actual_tables=382`, `actual_columns=4943`, `missing_columns=0`.
- تم حذف القاعدة المؤقتة بعد انتهاء الفحص.

هذا يعني أن مسار إنشاء شركة جديدة يملك الآن الأعمدة والجداول التي أضافتها migrations التاريخية القابلة للجرد كـ schema نهائي.

## ملاحظات مهمة

### 1. التصميم قريب من baseline نظيف

النظام حالياً لا يعتمد على migrations القديمة لإنشاء شركة جديدة مباشرة. المسار الحالي:

1. `database.create_company_tables()`
2. `tenant_runner.apply_tenant_schema()`
3. `tenant_schema.py`
4. Alembic stamp على head

وكذلك migration `0001_baseline_complete.py` يستدعي نفس `apply_tenant_schema()`. هذا ممتاز كبداية لعمل squash وتنظيف التاريخ.

### 2. توجد شجرة migrations طويلة وليست مناسبة لشكل "أول إصدار"

المجلد `backend/alembic/versions/` يحتوي 109 ملفات، بينها merge revisions وتاريخ تطوير طويل. وجود head واحد يعني أن graph صالح حالياً، لكنه ليس نظيفاً كإصدار أول.

الحذف الآمن يتطلب إما:

- إبقاء ملف baseline واحد فقط إذا كان المشروع سيبدأ من قواعد بيانات جديدة أو يمكن إعادة stamp لكل tenants.
- أو الاحتفاظ بمسار ترقية انتقالي إذا كانت هناك شركات إنتاجية موجودة تحتاج upgrade بدون إسقاط البيانات.

### 3. يوجد مجلد migrations legacy منفصل

المجلد `backend/migrations/versions/` يحتوي 4 ملفات revision منفصلة:

- `migrate_recipients_to_jsonb.py`
- `fix_approval_reports_schema.py`
- `fix_sub_svc_exp_schema.py`
- `add_scheduled_report_results.py`

هذه الملفات ليست ضمن شجرة Alembic الرئيسية في `backend/alembic/versions/`، وبعضها يبدأ بـ `down_revision = None`. هذا يجعلها مرشحاً قوياً للحذف بعد التأكد أن تغييراتهم مدمجة في `tenant_schema.py` أو في baseline الجديد.

### 4. تكرار جدول `inventory_transactions_archive` تم تنظيفه

كان يوجد تعريفان لنفس الجدول داخل `tenant_schema.py`:

- تعريف صريح بالأعمدة عند `backend/db_ddl/tenant_schema.py:6147`
- تعريف آخر باستخدام `LIKE inventory_transactions` ضمن block Feature 023

كما توجد migrations تاريخية مرتبطة بنفس الجدول:

- `backend/alembic/versions/0023_archive_tables.py`
- `backend/alembic/versions/023m_inventory_transactions_archive.py`

تمت إزالة تعريف `LIKE inventory_transactions` المتكرر، مع إبقاء الفهارس المرتبطة بالأرشيف. التعريف المتبقي هو التعريف الصريح الكامل، وهو الأنسب لـ baseline قابل للفهم والمراجعة.

### 5. لم يظهر تكرار مباشر في الأعمدة أو أسماء الفهارس بالمسح السريع

المسح النصي لم يظهر تكراراً مباشراً من نوع:

- نفس `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` أكثر من مرة.
- نفس اسم `CREATE INDEX IF NOT EXISTS ...` أكثر من مرة.

لكن وجود 131 أمر `ADD COLUMN IF NOT EXISTS` داخل `tenant_schema.py` يعني أن الملف ما زال يحمل آثار migrations تاريخية. في baseline نظيف، الأعمدة النهائية يجب أن تكون داخل تعريف `CREATE TABLE` الأساسي قدر الإمكان، وتبقى `ALTER TABLE` فقط للحالات التي تتطلب ترتيب dependencies أو constraints لاحقة.

### 6. يوجد DDL خارج `tenant_schema.py`

في `backend/main.py` توجد جداول system database مثل:

- `system_user_index`
- `system_companies`
- `industry_templates`
- `system_activity_log`
- `system_admin_2fa`

هذه ليست tenant tables، ولا يجب دمجها عشوائياً في `tenant_schema.py`. لكنها تحتاج baseline واضح خاص بالـ system DB إذا كان الهدف تنظيف كامل لملفات قاعدة البيانات.

في `backend/database.py` كان يوجد DDL tenant خارج مصدر الحقيقة:

- `party_sites`
- `party_site_balances`
- auto-heal لأعمدة ZATCA داخل جدول `invoices`

هذه التعريفات موجودة أيضاً في `tenant_schema.py` و/أو migrations. تم حذف هذا التكرار من `database.py` لأن مسار إنشاء الشركة يستدعي `create_company_tables()` قبل `initialize_company_default_data()`، و`create_company_tables()` يستدعي `apply_tenant_schema()`. أي إصلاح schema لاحق يجب أن يبقى في `tenant_schema.py` وملفات Alembic، لا في مسار فتح الاتصال.

### 7. حذف migrations سيكسر بعض الاختبارات الحالية ما لم تُحدث

بعض الاختبارات والـ scripts تقرأ ملفات migration محددة مباشرة، مثل:

- `backend/tests/test_reports_backend_authority.py`
- `backend/tests/test_contracts_backend_authority.py`
- `backend/tests/test_crm_backend_authority.py`
- `backend/tests/test_hr_payroll_backend_authority.py`
- `backend/tests/test_security_admin_backend_authority.py`
- `backend/tests/test_audit_pr10_ddl_sync.py`
- `backend/scripts/check_approval_tokens.py`
- `backend/scripts/check_maintenance_writers.py`
- `backend/scripts/check_payroll_period_writers.py`
- `backend/scripts/check_hardcoded_bank_codes.py`

لذلك حذف ملفات `versions` يجب أن يتبعه تحديث الاختبارات لتفحص baseline/schema النهائي بدلاً من تفحص migration تاريخية.

## قرار معماري مطلوب قبل الحذف

هناك مساران فقط:

### المسار A: إصدار أول نظيف بالكامل

مناسب إذا:

- لا توجد قواعد بيانات شركات production يجب ترقيتها.
- أو يمكن إسقاط قواعد الشركات وإعادة إنشائها.
- أو يمكن عمل `alembic stamp head` لكل tenant بعد مطابقة schema.

الإجراء:

1. تنظيف `tenant_schema.py`.
2. تنظيف DDL المتكرر في `database.py`.
3. إنشاء baseline migration واحد.
4. حذف ملفات `backend/alembic/versions/*.py` القديمة مع إبقاء baseline الجديد.
5. حذف `backend/migrations/versions/`.
6. تحديث الاختبارات والوثائق.

### المسار B: تنظيف مع دعم tenants موجودة

مناسب إذا:

- توجد قواعد بيانات شركات حالية لا يمكن إسقاطها.
- يجب الحفاظ على مسار upgrade تاريخي.

الإجراء:

1. إنشاء baseline جديد للنسخ الجديدة.
2. إبقاء migrations القديمة أو أرشفتها لفترة انتقالية.
3. توفير script للتحقق من schema ثم `stamp`.
4. حذف التاريخ القديم فقط بعد ترحيل كل tenants وتوثيق ذلك.

## خطة التنفيذ المقترحة

### المرحلة 1: تنظيف مصدر الحقيقة

- إزالة تكرار `inventory_transactions_archive`. **تم**
- دمج أعمدة `ADD COLUMN IF NOT EXISTS` الواضحة داخل `CREATE TABLE` الأصلي عندما يكون ذلك آمناً.
- إزالة إنشاء `party_sites` و `party_site_balances` من `database.py` إذا ثبت أنها مضمونة من `tenant_schema.py`. **تم**
- إزالة auto-heal لأعمدة ZATCA من `database.py` لأن الأعمدة موجودة في `tenant_schema.py` وAlembic. **تم**
- تصنيف DDL الموجود في `main.py` كـ system schema وليس tenant schema.

### المرحلة 2: baseline جديد

- إنشاء migration واحد باسم واضح مثل `0001_initial_clean_schema.py`.
- جعله يستدعي `apply_tenant_schema()` أو يحتوي snapshot واضح حسب القرار النهائي.
- ضبط `revision` و `down_revision = None`.
- التأكد أن `alembic heads` يرجع head واحد فقط.

### المرحلة 3: الاختبار من الصفر

- إنشاء قاعدة tenant فارغة مؤقتة.
- تشغيل `alembic -x company=<test_company> upgrade head`.
- تشغيل bootstrap إنشاء شركة جديدة.
- التحقق من عدم وجود جداول أو أعمدة مكررة.
- تشغيل اختبارات backend المتعلقة بالـ schema والـ authority.

### المرحلة 4: حذف التاريخ القديم

بعد نجاح المراحل السابقة فقط:

- حذف ملفات `backend/alembic/versions/` القديمة باستثناء baseline الجديد.
- حذف `backend/migrations/versions/`.
- تحديث docs والاختبارات التي تشير إلى ملفات migration القديمة.

## توصية نهائية

لا أنصح بحذف ملفات migrations مباشرة الآن. الترتيب الصحيح هو:

1. إصلاح التكرار المؤكد في `tenant_schema.py`.
2. جعل `tenant_schema.py` و `tenant_runner.py` قادرين على إنشاء schema كاملة ونظيفة من الصفر.
3. تحديث الاختبارات لتفحص schema النهائي.
4. بعدها فقط يتم حذف التاريخ القديم أو استبداله بملف baseline واحد.

الحالة الحالية جيدة كبنية انتقالية، لكنها ليست بعد "أول إصدار نظيف" بسبب:

- وجود 109 migration في الشجرة الرئيسية.
- وجود 4 migrations legacy منفصلة.
- وجود 131 أمر `ADD COLUMN IF NOT EXISTS` داخل baseline schema، وهي آثار تاريخية يجب دمجها تدريجياً في تعريفات الجداول.
- اعتماد اختبارات على ملفات migration محددة.

بعد فحص ما قبل الحذف، لم يعد سبب التأجيل هو نقص أعمدة أو جداول في baseline، بل قرار التشغيل: هل سيتم اعتماد مسار إصدار أول نظيف فقط، أم يجب دعم tenants موجودة بمسار انتقالي.
