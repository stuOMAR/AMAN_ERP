# برومت فحص نظام AMAN ERP

> **الاستخدام:** انسخ هذا الملف كاملاً وأرسله كأول رسالة في محادثة جديدة مع Claude Opus 4.7.
> **الهدف:** ينتج ملف `SYSTEM_MAP.md` يحتوي خريطة شاملة لكل مكونات النظام.

---

## التعليمات

أنت ستقوم بفحص شامل لمشروع AMAN ERP الموجود في `/home/omar/Desktop/aman`.

### ⚠️ قواعد صارمة - يجب الالتزام بها حرفياً

1. **لا تقرأ مجلد `docs/` أبداً** - الملفات هناك قديمة وغير محدثة. تجاهلها تماماً.

2. **لا تقرأ `node_modules/` أو `dist/` أو `uploads/` أو `__pycache__/` أو `.hypothesis/`** - مجلدات مولدة تلقائياً.

3. **الملفات الكبيرة جداً (>3000 سطر) لا تقرأ محتواها بالكامل** - اقرأ أول 100 سطر وآخر 50 سطر فقط، ثم اكتفِ بوصف وظيفتها.

4. **لا تعدل أي ملف** - أنت في وضع القراءة فقط.

5. **أنتج المخرجات بالعربية** - لأن النظام ERP عربي (سعودي) والمستخدمون عرب.

---

## خطوات الفحص (نفذها بهذا الترتيب بالضبط)

### المرحلة 1: الهيكل العام (10 دقائق)

```
اقرأ الملفات التالية كاملة:
- /home/omar/Desktop/aman/package.json
- /home/omar/Desktop/aman/docker-compose.yml
- /home/omar/Desktop/aman/docker-compose.prod.yml
- /home/omar/Desktop/aman/.env.example
- /home/omar/Desktop/aman/backend/config.py
- /home/omar/Desktop/aman/backend/requirements.txt
- /home/omar/Desktop/aman/backend/main.py (أول 200 سطر)
- /home/omar/Desktop/aman/frontend/package.json
- /home/omar/Desktop/aman/frontend/vite.config.js
- /home/omar/Desktop/aman/mobile/package.json
```

استنتج من هذه الملفات:
- إصدارات التكنولوجيات الرئيسية
- هيكل Docker (الخدمات، المنافذ، volumes)
- متغيرات البيئة الأساسية
- التبعيات الأساسية

---

### المرحلة 2: هيكل المجلدات التفصيلي (15 دقيقة)

```
نفذ أمر shell أو استخدم Glob لسرد الشجرة الكاملة:
1. ابدأ من الجذر: ls -la /home/omar/Desktop/aman/
2. لكل مجلد فرعي مهم، اسرد محتوياته:
   - backend/ (كل المجلدات الفرعية: routers/, services/, models/, schemas/, utils/, tests/, alembic/, db_ddl/, integrations/, scripts/, locales/, plugins/)
   - frontend/src/ (كل المجلدات الفرعية: pages/, components/, services/, hooks/, context/, config/, styles/, i18n/, locales/)
   - mobile/src/ (كل المجلدات الفرعية: screens/, services/, store/, utils/)
   - tests/ (Playwright E2E)
   - scripts/ (سكربتات الصيانة)
   - .github/workflows/ (CI/CD)
   - nginx/ (إعدادات nginx)
   - monitoring/ (مراقبة)
   - ops/ (عمليات)
```

أنتج شجرة مجلدات شاملة بصيغة متدرجة (indented tree).

---

### المرحلة 3: API Routes - كل المسارات (15 دقيقة)

```
نفذ الخطوات التالية:
1. ls /home/omar/Desktop/aman/backend/routers/ - لرؤية كل ملفات الراوتر
2. ls كل مجلد فرعي في routers/ (routers/auth/, routers/finance/, routers/sales/, إلخ)
3. لكل ملف router، اقرأه وابحث عن router = APIRouter(prefix=...) لاستخراج:
   - اسم الـ prefix
   - قائمة الـ endpoints (HTTP method + path + وصف مختصر)
4. اقرأ ملف main.py لترى كيف تُركب الراوترات (app.include_router)
5. صنف كل الراوترات حسب الوحدة (Finance, Sales, HR, Inventory, ...)
```

أنتج قائمة كاملة بكل الـ API routes مصنفة حسب الوحدة، كل Route بهذه الصيغة:
```
/path  [GET/POST/PUT/DELETE]  وصف مختصر
```

---

### المرحلة 4: نماذج قاعدة البيانات (10 دقائق)

```
1. اقرأ /home/omar/Desktop/aman/backend/models/__init__.py - كل النماذج المصدرة
2. اقرأ /home/omar/Desktop/aman/backend/database.py - آلية الـ multi-tenancy
3. اقرأ /home/omar/Desktop/aman/backend/db_ddl/tenant_schema.py (أول 200 سطر فقط)
4. اقرأ /home/omar/Desktop/aman/backend/alembic/env.py (أول 100 سطر)
5. اسرد /home/omar/Desktop/aman/backend/alembic/versions/ لعدد الـ migrations
6. اسرد /home/omar/Desktop/aman/backend/models/domain_models/ لكل ملفات النماذج
```

استنتج:
- عدد النماذج التقريبي
- آلية الـ multi-tenancy
- المجالات الرئيسية (Accounting, HR, Sales, Inventory, ...)
- عدد الـ migrations

---

### المرحلة 5: الخدمات والمنطق التجاري (10 دقائق)

```
1. ls /home/omar/Desktop/aman/backend/services/
2. لكل ملف/مجلد في services/، اقرأه جزئياً (أول 80 سطر) لتعرف وظيفته
3. صنف الخدمات حسب المجال
```

---

### المرحلة 6: الأدوات المساعدة والـ Middleware (5 دقائق)

```
1. ls /home/omar/Desktop/aman/backend/utils/
2. اقرأ وصفاً مختصراً لكل ملف (أول 30 سطر)
3. ls /home/omar/Desktop/aman/backend/middleware/
4. اقرأ ملفات الـ middleware
```

---

### المرحلة 7: الواجهة الأمامية - الصفحات والمكونات (10 دقائق)

```
1. اقرأ /home/omar/Desktop/aman/frontend/src/App.jsx (أول 150 سطر) - التوجيه
2. ls /home/omar/Desktop/aman/frontend/src/pages/
3. لكل مجلد صفحة، اسرد ملفاته
4. ls /home/omar/Desktop/aman/frontend/src/components/
5. ls /home/omar/Desktop/aman/frontend/src/services/ - API clients
6. اقرأ /home/omar/Desktop/aman/frontend/src/services/apiClient.js
7. اقرأ /home/omar/Desktop/aman/frontend/src/i18n.js
```

---

### المرحلة 8: الاختبارات (5 دقائق)

```
1. اسرد /home/omar/Desktop/aman/backend/tests/ - اختبارات الباك إند
2. اسرد /home/omar/Desktop/aman/frontend/src/tests/ - اختبارات الفرونت إند
3. اسرد /home/omar/Desktop/aman/tests/specs/ - اختبارات Playwright E2E
4. اقرأ /home/omar/Desktop/aman/playwright.config.ts
5. اقرأ vitest.config.js للمشروعين
```

---

### المرحلة 9: CI/CD والـ Deployment (5 دقائق)

```
1. اقرأ /.github/workflows/ci.yml
2. اقرأ /.github/workflows/playwright.yml
3. اقرأ /.github/workflows/security-scan.yml
4. اقرأ /nginx/production.conf (أول 100 سطر)
5. اقرأ /monitoring/prometheus.yml
```

---

### المرحلة 10: كتابة الملف النهائي `SYSTEM_MAP.md`

بعد جمع كل المعلومات، اكتب ملف `SYSTEM_MAP.md` في `/home/omar/Desktop/aman/SYSTEM_MAP.md` بالهيكل التالي:

```markdown
# خريطة نظام AMAN ERP - الشاملة

> **آخر تحديث:** [DATE]
> **الإصدار:** 2.0.0
> **نوع النظام:** ERP متعدد المستأجرين (Multi-Tenant)
> **النطاق:** محاسبة، مبيعات، مشتريات، مخزون، موارد بشرية، تصنيع، نقاط بيع، CRM، مشاريع، أصول، خزينة، ضرائب، ZATCA

---

## 1. الهيكل العام للمشروع
[شجرة المجلدات الكاملة]

---

## 2. التكنولوجيات المستخدمة

### 2.1 الواجهة الخلفية (Backend)
| التقنية | الإصدار | الغرض |
|---|---|---|
| ... | ... | ... |

### 2.2 الواجهة الأمامية (Frontend)
| التقنية | الإصدار | الغرض |
|---|---|---|
| ... | ... | ... |

### 2.3 تطبيق الجوال (Mobile)
| التقنية | الإصدار | الغرض |
|---|---|---|
| ... | ... | ... |

---

## 3. هيكل قاعدة البيانات

### 3.1 آلية تعدد المستأجرين (Multi-Tenancy)
[شرح الآلية]

### 3.2 الجداول النظامية (System Tables)
[قائمة الجداول المشتركة]

### 3.3 مجالات قاعدة البيانات لكل مستأجر
[تصنيف الجداول حسب المجال + عدد تقريبي]

---

## 4. API Routes

### 4.1 المصادقة والصلاحيات
| المسار | الطريقة | الوصف |
|---|---|---|
| /api/auth/login | POST | ... |

[كرر لكل وحدة]

---

## 5. الواجهة الأمامية - الصفحات الرئيسية
[قائمة الصفحات مصنفة حسب الوحدة]

---

## 6. الخدمات الخلفية (Services)
[قائمة الخدمات مصنفة حسب المجال]

---

## 7. الأدوات المساعدة (Utils)
[قائمة الأدوات المساعدة مع وصف مختصر]

---

## 8. الاختبارات
[ملخص اختبارات الباك إند، الفرونت إند، E2E]

---

## 9. CI/CD والـ Deployment
[آلية النشر، خطوات CI، بيئة الإنتاج]

---

## 10. ملفات الدخول والإعدادات الرئيسية
| الملف | الوظيفة |
|---|---|
| backend/main.py | نقطة دخول FastAPI |
| ... | ... |
```

---

## ملاحظات مهمة

- **لا تستخدم WebFetch أبداً** - كل شيء محلي في نظام الملفات.
- **استخدم Glob و Read و Bash بكثافة** - هذه المهمة تحتاج فحصاً شاملاً.
- **لا تتردد في تجاهل التفاصيل الدقيقة** - الهدف هو الصورة الكبيرة وليست التفاصيل الدقيقة لكل دالة.
- **إذا كان هناك ملف طويل جداً، اقرأ بدايته ونهايته فقط**.
- **الوقت المتوقع: 60-90 دقيقة من العمل المتواصل**.
- **أخرج النتيجة في ملف `SYSTEM_MAP.md` في جذر المشروع**.
















# خريطة نظام AMAN ERP - الشاملة

> **آخر تحديث:** 8 مايو 2026
> **الإصدار:** 2.0.0
> **مستودع GitHub:** github.com/AMANCAMSYS/AMAN_ERP
> **نوع النظام:** ERP متعدد المستأجرين (Multi-Tenant)
> **اللغة الأساسية:** Python 3.12 (Backend), React 18 (Frontend), React Native 0.76 (Mobile)
> **قاعدة البيانات:** PostgreSQL 15 + Redis 7
> **النطاق الوظيفي:** محاسبة، مبيعات، مشتريات، مخزون، موارد بشرية، تصنيع، نقاط بيع، CRM، مشاريع، أصول، خزينة، ضرائب، ZATCA، حقل خدمة (FSM)، اشتراكات، عقود، إدارة مستندات

---

## 1. الهيكل العام للمشروع

```
aman/
├── AGENTS.md                           # تعليمات المساعد
├── .env.example                        # قالب متغيرات البيئة الجذرية
├── package.json                        # تبعيات Playwright (E2E)
├── docker-compose.yml                  # بيئة التطوير (PostgreSQL + Redis + Backend + Frontend + Prometheus + Grafana)
├── docker-compose.prod.yml            # تجاوزات الإنتاج (العامل المخصص + إغلاق المنافذ)
├── deploy.sh / deploy_server.py        # سكربتات النشر
├── start-local.sh / stop-local.sh      # تشغيل/إيقاف محلي
├── safe-start.sh / safe-stop.sh        # تشغيل/إيقاف آمن
├── playwright.config.ts                # إعدادات Playwright للـ E2E
│
├── backend/                            # ════════ الواجهة الخلفية (FastAPI) ════════
│   ├── main.py                         #   نقطة الدخول (923 سطر) — FastAPI مع lifespan وكل الراوترات
│   ├── config.py                       #   إعدادات Pydantic (قاعدة بيانات، Redis، JWT، ZATCA)
│   ├── database.py                     #   محرك DB + تزويد المستأجرين + جداول النظام
│   ├── worker.py                       #   عامل مخصص لـ APScheduler (وضع الإنتاج)
│   ├── requirements.txt               #   تبعيات Python
│   ├── requirements-dev.txt            #   تبعيات التطوير
│   ├── Dockerfile                      #   صورة متعددة المراحل (builder → runtime)
│   ├── entrypoint.sh                   #   نقطة دخول الحاوية
│   ├── alembic.ini / alembic/          #   إدارة هجرة المخطط (multi-tenant)
│   ├── routers/   (61+ راوتر)          #   معالجات API — المصادقة، المالية، المبيعات، إلخ
│   ├── services/  (71+ خدمة)           #   طبقة المنطق التجاري
│   ├── schemas/   (54 ملف)             #   نماذج Pydantic للتحقق
│   ├── models/                         #   نماذج ORM (230+ نموذج)
│   │   ├── __init__.py                 #   تصدير مركزي لكل النماذج
│   │   ├── base.py                     #   ModelBase, AuditMixin, SoftDeleteMixin
│   │   └── domain_models/ (56 ملف)     #   نماذج مقسمة حسب المجال
│   ├── db_ddl/
│   │   └── tenant_schema.py (7396 سطر) #   تعريف DDL الكامل لكل مستأجر
│   ├── utils/     (43 ملف)             #   أدوات مساعدة (أمان، تدقيق، تشفير، i18n)
│   ├── middleware/                     #   وسيط المراقبة (cache observability)
│   ├── integrations/                   #   محولات خارجية (بنوك، مدفوعات، ZATCA، شحن، SMS)
│   ├── repositories/                   #   طبقة الوصول للبيانات
│   ├── plugins/                        #   نظام الإضافات
│   ├── locales/                        #   رسائل خطأ بالعربية والإنجليزية
│   ├── scripts/                        #   سكربتات الصيانة
│   └── tests/     (82 ملف اختبار)      #   pytest + hypothesis (خاصية)
│
├── frontend/                           # ════════ الواجهة الأمامية (React/Vite) ════════
│   ├── package.json                    #   React 18 + Vite 5 + جميع التبعيات
│   ├── vite.config.js                  #   إعدادات Vite
│   ├── nginx.conf                      #   إعدادات nginx للتطوير
│   ├── Dockerfile                      #   صورة متعددة المراحل (Node → Nginx)
│   ├── src/
│   │   ├── main.jsx                    #   نقطة دخول React
│   │   ├── App.jsx                     #   المكون الجذري + كل المسارات
│   │   ├── i18n.js                     #   إعداد i18next
│   │   ├── pages/      (57 مجلد)       #   صفحات التطبيق
│   │   ├── components/                 #   مكونات واجهة
│   │   ├── services/   (41 ملف)        #   طبقة API (Axios)
│   │   ├── hooks/      (8 خطافات)      #   خطافات React مخصصة
│   │   ├── context/                    #   سياقات React (فرع، سمة، إشعار)
│   │   ├── config/                     #   تمكين الوحدات حسب الصناعة
│   │   ├── styles/                     #   CSS (tokens, cards, navigation, print)
│   │   ├── locales/                    #   ترجمات عربي/إنجليزي
│   │   ├── router/                     #   مسارات الوضع الصارم
│   │   └── tests/      (5 ملفات)       #   Vitest + Testing Library
│   └── dist/                           #   مخرجات البناء
│
├── mobile/                             # ════════ تطبيق الجوال (React Native) ════════
│   ├── package.json                    #   React Native 0.76
│   ├── App.jsx                         #   المكون الجذري
│   ├── src/screens/    (13 مجلد)       #   شاشات (مصادقة، مبيعات، مخزون، مزامنة...)
│   ├── src/services/                   #   API + مزامنة + دفع + فض النزاعات
│   ├── src/store/                      #   تخزين SQLite غير متصل
│   └── src/utils/                      #   تنسيقات
│
├── tests/                              # ════════ اختبارات E2E (Playwright) ════════
│   ├── specs/          (8 ملفات)       #   مواصفات (مصادقة، فروع، مالية، HR...)
│   ├── fixtures/                       #   عميل API وسيناريوهات
│   └── seed/                           #   بيانات بذرة للاختبارات
│
├── nginx/
│   └── production.conf                 #   إعدادات nginx للإنتاج (SSL, security headers)
│
├── monitoring/                         #   المراقبة
│   ├── prometheus.yml                 #   أهداف Prometheus
│   ├── alerts/aman_alerts.yml         #   قواعد التنبيه
│   └── grafana/                        #   لوحات معلومات Grafana
│
├── ops/
│   ├── k8s/cronjob-backup.yaml        #   نسخ احتياطي K8s
│   └── systemd/                        #   خدمات systemd للنسخ الاحتياطي
│
├── scripts/          (17+ سكربت)       #   سكربتات فحص الجودة والصيانة
├── .github/workflows/                  #   CI/CD (3 ملفات)
├── specs/                              #   مواصفات الميزات
└── docs/                               #   ⚠️ وثائق قديمة — لا تعتمد عليها
```

---

## 2. التكنولوجيات المستخدمة

### 2.1 الواجهة الخلفية (Python 3.12)

| التقنية | الغرض |
|---|---|
| **FastAPI** | إطار الويب الأساسي |
| **Gunicorn + Uvicorn** | خادم WSGI/ASGI الإنتاجي |
| **SQLAlchemy** | ORM |
| **PostgreSQL 15** | قاعدة البيانات الأساسية |
| **Alembic** | هجرة المخطط (multi-tenant) |
| **Pydantic v2 + pydantic-settings** | التحقق من البيانات وإدارة الإعدادات |
| **APScheduler** | جدولة المهام (in_process / dedicated worker) |
| **Redis 7** | تخزين مؤقت + rate limiting + ناقل أحداث |
| **python-jose[cryptography]** | مصادقة JWT |
| **passlib[bcrypt]** | تجزئة كلمات المرور |
| **slowapi** | تقييد المعدل (rate limiting) |
| **Sentry** | تتبع الأخطاء |
| **Prometheus** | مقاييس عبر prometheus-fastapi-instrumentator |
| **pyotp** | مصادقة ثنائية (TOTP) |
| **python3-saml** | الدخول الموحد SSO |
| **python-ldap** | مصادقة LDAP |
| **firebase-admin** | إشعارات الدفع |
| **signxml + lxml** | توقيع ZATCA UBL XML الرقمي |
| **pandas + openpyxl + pypdf** | استيراد/تصدير البيانات |
| **reportlab + arabic-reshaper + python-bidi** | PDF مع دعم العربية |
| **python-magic + clamd** | فحص ملفات DMS |
| **Jinja2** | قوالب البريد الإلكتروني |
| **hypothesis** | اختبار قائم على الخصائص |
| **celery** | غير مفعل حالياً (APScheduler يحل محله) |

### 2.2 الواجهة الأمامية (React 18)

| التقنية | الغرض |
|---|---|
| **React 18** | إطار واجهة المستخدم |
| **Vite 5** | بناء وتطوير سريع |
| **React Router 6** | توجيه العميل |
| **Axios** | HTTP client |
| **i18next + react-i18next** | الترجمة (عربي/إنجليزي) |
| **Recharts + ECharts** | الرسوم البيانية والتقارير |
| **react-hook-form** | إدارة النماذج |
| **react-hot-toast** | الإشعارات |
| **DOMpurify** | حماية XSS |
| **react-grid-layout** | تخطيط ودجات لوحة التحكم |
| **react-window** | قوائم افتراضية |
| **lucide-react + react-icons** | الأيقونات |
| **dayjs** | معالجة التواريخ |
| **Vitest + Testing Library** | اختبارات الوحدة والتكامل |
| **Nginx** | خادم ويب إنتاجي |

### 2.3 تطبيق الجوال (React Native)

| التقنية | الغرض |
|---|---|
| **React Native 0.76** | إطار الجوال |
| **React Navigation 6** | التنقل |
| **AsyncStorage** | تخزين محلي |
| **react-native-sqlite-storage** | SQLite غير متصل |
| **Firebase Messaging** | إشعارات الدفع |
| **Jest** | اختبارات |

---

## 3. هيكل قاعدة البيانات (Multi-Tenant)

### 3.1 آلية تعدد المستأجرين

كل شركة تحصل على قاعدة بيانات مستقلة `aman_{company_id}`. النظام يدير:
- **قاعدة مشتركة (`postgres`):** جداول نظامية (شركات، مستخدمين، تدقيق)
- **قواعد مستأجرين:** قاعدة لكل شركة (~290+ جدول + 8+ عروض مادية)
- **LRU cache:** 50 اتصال نشط كحد أقصى (قابل للتكوين عبر `DB_TENANT_ENGINE_CACHE_SIZE`)
- **Alembic multi-tenant:** الهجرة تطبق على كل قواعد المستأجرين دفعة واحدة (`alembic -x company=all upgrade head`)

### 3.2 المجالات الرئيسية (لكل مستأجر)

| المجال | الجداول الرئيسية |
|---|---|
| **أساسي** | `accounts`, `branches`, `company_users`, `warehouses`, `parties`, `party_site_balances` |
| **محاسبة** | `journal_entries`, `journal_lines`, `fiscal_years`, `fiscal_period_locks`, `currencies`, `exchange_rates` |
| **خزينة** | `treasury_accounts`, `treasury_transactions`, `bank_reconciliations`, `checks_*`, `notes_*` |
| **مبيعات** | `customers`, `sales_quotations`, `sales_orders`, `invoices`, `sales_returns`, `customer_receipts`, `delivery_orders`, `contracts` |
| **مشتريات** | `suppliers`, `purchase_orders`, `purchase_invoices`, `purchase_returns`, `rfq_*`, `blanket_purchase_orders` |
| **مخزون** | `products`, `product_categories`, `inventory`, `inventory_transactions`, `stock_adjustments`, `product_batches`, `product_serials` |
| **موارد بشرية** | `employees`, `departments`, `positions`, `salary_structures`, `payroll_*`, `attendance`, `leave_requests`, `employee_loans`, `performance_reviews` |
| **تصنيع** | `work_centers`, `bills_of_material`, `production_orders`, `manufacturing_routes`, `job_cards`, `mrp_*`, `quality_inspections` |
| **POS** | `pos_sessions`, `pos_orders`, `pos_payments`, `pos_promotions`, `pos_loyalty_*`, `pos_tables`, `pos_kitchen_orders` |
| **CRM** | `sales_opportunities`, `support_tickets`, `marketing_campaigns`, `leads` |
| **ضرائب** | `tax_rates`, `tax_groups`, `tax_returns`, `tax_payments`, `wht_rates`, `company_tax_settings` |
| **مشاريع** | `projects`, `project_tasks`, `project_budgets`, `project_resources` |
| **أصول** | `assets`, `asset_categories`, `asset_depreciation_schedules` |
| **مالية** | `budgets`, `cost_centers`, `costing_policies`, `cash_flow_forecasts`, `zakat_calculations` |
| **أمان** | `roles`, `api_keys`, `webhooks`, `audit_log`, `security_events`, `user_sessions` |
| **اشتراكات** | `subscription_plans`, `subscription_enrollments`, `subscription_invoices` |

---

## 4. API Routes (تحت `/api/`)

### 4.1 الأساسية والمصادقة
| المسار | الوصف |
|---|---|
| `/api/auth/*` | تسجيل الدخول/الخروج، التحديث، 2FA، إعادة كلمة المرور، الجلسات |
| `/api/companies/*` | إدارة الشركات (CRUD) |
| `/api/roles/*` | إدارة الصلاحيات (RBAC) |
| `/api/branches/*` | إدارة الفروع |
| `/api/settings/*` | إعدادات الشركة |
| `/api/audit/*` | سجلات التدقيق |
| `/api/notifications/*` | الإشعارات |
| `/api/approvals/*` | سير الموافقات |
| `/api/security/*` | مفاتيح API، webhooks، أحداث أمنية |
| `/api/data-import/*` | استيراد Excel/CSV |
| `/api/search/*` | بحث موحد (أطراف، منتجات، فواتير...) |

### 4.2 المحاسبة والمالية
| المسار | الوصف |
|---|---|
| `/api/accounting/*` | دليل الحسابات، اليومية، ميزان المراجعة |
| `/api/accounting/depth/*` | هرمية الحسابات |
| `/api/accounting/advanced/*` | محاسبة متقدمة |
| `/api/cost-centers/*` | مراكز التكلفة |
| `/api/budgets/*` | الموازنات |
| `/api/reconciliation/*` | التسويات البنكية |
| `/api/currencies/*` | العملات وأسعار الصرف |
| `/api/costing-policies/*` | سياسات تكلفة المخزون |
| `/api/treasury/*` | معاملات الخزينة |
| `/api/checks/*` | شيكات مستحقة القبض/الدفع |
| `/api/notes/*` | أوراق قبض/دفع |
| `/api/payments/*` | سندات الدفع |
| `/api/expenses/*` | مطالبات المصروفات |
| `/api/forecast/*` | التنبؤات المالية |
| `/api/intercompany/*` | معاملات بين الشركات |
| `/api/taxes/*` | إدارة الضرائب |
| `/api/tax-compliance/*` | الامتثال الضريبي |
| `/api/bank-feeds/*` | تغذية بنكية |
| `/api/petty-cash/*` | العهدة النثرية |
| `/api/cashflow/*` | التدفق النقدي |

### 4.3 المبيعات والمشتريات والمخزون
| المسار | الوصف |
|---|---|
| `/api/sales/*` | العملاء، الفواتير، عروض الأسعار، أوامر البيع، المرتجعات |
| `/api/purchases/*` | الموردين، أوامر الشراء، فواتير الشراء، المرتجعات |
| `/api/inventory/*` | المنتجات، المخازن، الحركات، التحويلات، الباتشات، الجودة |
| `/api/delivery-orders/*` | أوامر التسليم |
| `/api/landed-costs/*` | تكاليف الشحن والرسوم |
| `/api/matching/*` | المطابقة الثلاثية (PO-استلام-فاتورة) |
| `/api/contracts/*` | العقود |
| `/api/credentials/*` | خزنة الاعتمادات |
| `/api/shipping/*` | شركات الشحن |
| `/api/sms/*` | بوابات SMS |

### 4.4 الموارد البشرية والرواتب
| المسار | الوصف |
|---|---|
| `/api/hr/*` | الموظفون، الأقسام، الرواتب، الحضور، الإجازات، السلف |
| `/api/hr/advanced/*` | تقييم الأداء، التدريب، المخالفات |
| `/api/hr/self-service/*` | الخدمة الذاتية للموظفين |
| `/api/hr/pii/*` | إدارة البيانات الحساسة |
| `/api/payroll/*` | عكس الرواتب |
| `/api/wps-compliance/*` | نظام حماية الأجور والتوطين |

### 4.5 التصنيع
| المسار | الوصف |
|---|---|
| `/api/manufacturing/*` | مراكز العمل، BOM، أوامر الإنتاج، التوجيه، MRP، الجودة |

### 4.6 نقاط البيع (POS)
| المسار | الوصف |
|---|---|
| `/api/pos/*` | الجلسات، الطلبات، المدفوعات، العروض، الولاء، المطبخ |

### 4.7 إدارة علاقات العملاء (CRM)
| المسار | الوصف |
|---|---|
| `/api/crm/*` | الفرص، التذاكر، الحملات، التحليلات، التوقعات |

### 4.8 المشاريع
| المسار | الوصف |
|---|---|
| `/api/projects/*` | المشاريع، المهام، الميزانيات، الموارد، المخاطر |

### 4.9 التقارير ولوحات القيادة
| المسار | الوصف |
|---|---|
| `/api/reports/*` | ميزان المراجعة، الدخل، الميزانية العمومية، تقارير مخصصة |
| `/api/dashboard/*` | ودجات وإحصائيات النظام |
| `/api/role-dashboards/*` | لوحات KPI حسب الدور |
| `/api/kpi/*` | إدارة مؤشرات الأداء |
| `/api/scheduled-reports/*` | التقارير المجدولة |

### 4.10 خدمات التكامل والنظام
| المسار | الوصف |
|---|---|
| `/api/einvoicing/*` | فواتير ZATCA الإلكترونية (السعودية) |
| `/api/dms/*` | إدارة المستندات (حصص التخزين) |
| `/api/fsm/*` | إدارة الخدمات الميدانية |
| `/api/sso/*` | إعدادات الدخول الموحد |
| `/api/mobile/*` | مزامنة تطبيق الجوال |
| `/api/smart-alerts/*` | التنبيهات الذكية |
| `/api/email-templates/*` | قوالب البريد |
| `/api/integrations-admin/*` | طوابير إعادة المحاولة و DLQ |
| `/api/governance/*` | الحوكمة |
| `/api/account-classifications/*` | تصنيفات الحسابات |
| `/api/recurring-review/*` | مراجعة القيود المتكررة |
| `/api/ops/*` | عمليات (جدولة، استعادة) |
| `/api/sse/*` | Server-Sent Events |
| `/api/websocket/*` | WebSocket |
| `/api/locale/*` | موارد الترجمة |
| `/health` | فحص الصحة |
| `/metrics` | مقاييس Prometheus |

---

## 5. الخدمات الخلفية (Business Logic)

| المجال | الخدمات |
|---|---|
| **مالية** | سياسات مركز التكلفة |
| **موارد بشرية** | الحضور، PII، الرواتب الجماعية، سنوات الخدمة |
| **تصنيع** | BOM، MRP، الإنتاج، الجودة، الخردة |
| **مخزون** | أرشفة، إعادة طلب، WAC، إنذارات المخزون المنخفض |
| **POS** | تسوية غير متصل، قفل المخزون |
| **CRM** | تغذية التدفق النقدي، مسار التحويل |
| **خدمات ميدانية** | العقود، قوائم الأسعار، الفنيين |
| **مستندات** | مكافحة الفيروسات، الحصص، المرفقات |
| **فواتير إلكترونية** | ZATCA صندوق الصادر، بناء UBL، التوقيع |
| **رواتب** | عكس الفترة، حركات البنك |
| **إشعارات** | مرسل، طابور، قوالب (Push/Email/SMS/WebSocket) |
| **مؤشرات أداء** | 14 ملف نطاق + تقييم وإرسال |
| **تقارير** | إنشاء القوائم المالية |
| **صلاحيات** | RBAC + اكتشاف المسارات الحساسة |
| **بحث** | سجل البحث وتسجيله |
| **Webhooks** | إرسال الـ webhooks |
| **ذاكرة مؤقتة** | عميل Redis، إبطال، إحماء |
| **جدولة** | APScheduler (عدم تكرار، مراقبة) |
| **عمليات** | تقسيم التدقيق، استعادة |

---

## 6. الأدوات المساعدة (Utils) — 43 ملف

| الأداة | الوظيفة |
|---|---|
| `security_middleware.py` | إعادة توجيه HTTPS، تعقيم المدخلات |
| `csrf_middleware.py` | CSRF double-submit cookie |
| `limiter.py` | تقييد المعدل (rate limiting) |
| `permissions.py` | مساعدات RBAC |
| `tenant_isolation.py` | عزل المستأجرين |
| `field_encryption.py` | تشفير الحقول |
| `pii_encryption.py` | تشفير البيانات الحساسة |
| `signed_urls.py` | روابط ملفات موقعة بـ HMAC |
| `event_bus.py` | ناقل أحداث النطاق |
| `redis_event_bus.py` | جسر Redis للأحداث |
| `outbox_relay.py` | مرحل صندوق الصادر (transactional outbox) |
| `ws_manager.py` | إدارة WebSocket |
| `webhooks.py` | مساعدات Webhook |
| `audit.py` | سجل التدقيق |
| `auth_cookies.py` | مصادقة HttpOnly cookie |
| `logging_config.py` | سجلات JSON منظمة |
| `query_counter.py` | كشف استعلامات N+1 |
| `optimistic_lock.py` | قفل متفائل |
| `fiscal_lock.py` | قفل الفترة المالية |
| `i18n.py` | ترجمة الخلفية |
| `exports.py` | تصدير PDF/Excel |
| `sql_builder.py` | بناء SQL ديناميكي |
| `sql_safety.py` | منع حقن SQL |
| `treasury_balance.py` | أرصدة الخزينة |
| `balance_reconciliation.py` | التسويات |
| `zatca.py / zatca_clearance.py` | مساعدات ZATCA |
| `plugin_registry.py` | نظام الإضافات |
| `masking.py` | إخفاء البيانات |
| `currency_display.py` | تنسيق العملات |
| `duplicate_detection.py` | كشف التكرار |

---

## 7. الواجهة الأمامية — الصفحات الرئيسية

| الوحدة | الصفحات |
|---|---|
| **أساسي** | تسجيل الدخول، لوحة التحكم، الإعدادات، البحث |
| **محاسبة** | دليل الحسابات، اليومية، الأستاذ العام، ميزان المراجعة |
| **مبيعات** | العملاء، الفواتير، عروض الأسعار، أوامر البيع، CPQ |
| **مشتريات** | الموردين، أوامر الشراء، الفواتير، العقود الشاملة |
| **مخزون** | المنتجات، المخازن، التحويلات، التعديلات، الباتشات |
| **خزينة** | الحسابات البنكية، التسويات، الشيكات، الأوراق التجارية |
| **موارد بشرية** | موظفون، أقسام، رواتب، حضور، إجازات، تقييم أداء |
| **تصنيع** | مراكز عمل، BOM، أوامر إنتاج، توجيه، MRP، أرضية المصنع |
| **POS** | واجهة البيع، العروض، الولاء، المطبخ |
| **CRM** | الفرص، التذاكر، الحملات، التحليلات |
| **مشاريع** | مشاريع، مهام، ميزانيات، موارد |
| **تقارير** | قوائم مالية، KPIs، تقارير مخصصة |
| **أصول** | الأصول الثابتة، الإهلاك |
| **مصاريف** | مطالبات المصروفات |
| **ضرائب** | إقرارات، استقطاع، امتثال |
| **اشتراكات** | خطط وفواتير الاشتراكات |
| **إدارة** | شركات، صلاحيات، تدقيق، مهام مجدولة |
| **آخر** | تدفق نقدي، تنبؤات، تحليلات، خدمة ذاتية، SSO |

---

## 8. الاختبارات

### 8.1 اختبارات الباك إند (82 ملف)
- **الإطار:** pytest + pytest-asyncio + pytest-cov + pytest-xdist
- **الاختبارات القائمة على الخصائص:** hypothesis
- **التصنيف:** مصادقة، محاسبة، مبيعات، مشتريات، مخزون، خزينة، HR، تقارير، تكامل، أصول/مشاريع، تصنيع/POS، شيكات/أوراق، ضرائب/مالية، CRM، موافقات، إشعارات، صلاحيات، أمان (مصادقة، صلاحيات، حقن)، أداء، حمل متزامن

### 8.2 اختبارات الفرونت إند (5 ملفات)
- **الإطار:** Vitest + @testing-library/react + jsdom
- **الملفات:** auth, useApi, useOptimisticList, phase8_services

### 8.3 اختبارات E2E (Playwright)
- **8 مواصفات:** مصادقة، فروع، عملات، مالية، HR، مخزون، عزل، صلاحيات
- **+ ميزانية ومراكز تكلفة**

---

## 9. CI/CD والـ Deployment

### بيئة التطوير (Docker Compose)
8 خدمات: PostgreSQL (5432)، Redis (6379)، Backend (8000)، Frontend (80/8080)، Prometheus (9090)، PostgreSQL Exporter، Redis Exporter، Grafana (3000)، ClamAV (اختياري)

### بيئة الإنتاج (docker-compose.prod.yml)
- إضافة `worker` (نسخة واحدة، APScheduler مخصص)
- إغلاق منافذ DB و Redis خارجياً
- `SCHEDULER_MODE=dedicated`
- Gunicorn + UvicornWorker على الـ backend

### خطوات CI (`.github/workflows/ci.yml`)
1. **backend-static:** Ruff lint (أخطاء نحوية) + اختبار استيراد كل الراوترات
2. **backend-guards:** فحص parameterization SQL، انضباط GL، PII، أموال float، حالة الفواتير، مصدر JE، POS lock، cache keys، مزامنة المخطط
3. **frontend-guards:** تنسيق الأرقام، window.location، i18n strings
4. **tenant-bootstrap-e2e:** إنشاء مستأجر جديد + تأكيد ≥ 290 جدول + ≥ 8 عروض مادية
5. **alembic-roundtrip:** downgrade -1 → upgrade head
6. **backend-coverage:** pytest --cov (استشاري، PRs فقط)
7. **frontend:** Vite build + Vitest
8. **dependency-audit:** pip-audit + npm audit
9. **deploy:** نشر تلقائي للإنتاج عند push إلى main (SSH + إعادة بناء انتقائية + فحص صحة)

---

## 10. ملفات الدخول والإعدادات الرئيسية

| الملف | الوظيفة |
|---|---|
| `backend/main.py` (923 سطر) | نقطة دخول FastAPI — lifespan، كل الـ middleware، كل الراوترات |
| `backend/config.py` (179 سطر) | إعدادات Pydantic — DB، Redis، JWT، CSRF، ZATCA، المجدول |
| `backend/database.py` | محرك DB + إنشاء المستأجر + جداول النظام (`system_companies`, `system_user_index`) |
| `backend/worker.py` | عامل المجدول المخصص (للوضع `dedicated`) |
| `backend/alembic/env.py` | بيئة Alembic متعددة المستأجرين |
| `backend/db_ddl/tenant_schema.py` (7396 سطر) | كل DDL المخطط لكل مستأجر |
| `frontend/src/App.jsx` | المكون الجذري + كل المسارات |
| `frontend/src/services/apiClient.js` | عميل Axios + interceptors |
| `frontend/vite.config.js` | إعدادات بناء Vite |
| `frontend/nginx.conf` | Nginx للـ frontend |
| `docker-compose.yml` (212 سطر) | بيئة التطوير |
| `nginx/production.conf` | Nginx إنتاجي (SSL، rate limiting، security headers) |
| `monitoring/prometheus.yml` | أهداف Prometheus |
| `.github/workflows/ci.yml` (611 سطر) | خط أنابيب CI/CD الكامل |

---

## 11. أنماط المعمارية المتبعة

1. **Multi-Tenant:** كل شركة قاعدة بيانات مستقلة `aman_{company_id}`. ذاكرة LRU تخزن حتى 50 اتصال.

2. **طبقات Backend:** Routers (API) → Schemas (تحقق) → Services (منطق تجاري) → Repositories (وصول بيانات) → Models (ORM) → PostgreSQL

3. **30+ وحدة أعمال مستقلة:** محاسبة، مبيعات، مشتريات، مخزون، HR، تصنيع، POS، CRM، مشاريع، أصول، خزينة، ضرائب، مصاريف، اشتراكات... لكل منها routers + services + schemas + frontend pages

4. **12 قالب صناعة:** تجزئة، جملة، مطاعم، تصنيع، مقاولات، خدمات، صيدليات، ورش، تجارة إلكترونية، لوجستيات، زراعة، عام

5. **أمان متعدد الطبقات:**
   - JWT (HttpOnly refresh cookie + CSRF double-submit)
   - تشفير كلمات المرور bcrypt
   - مصادقة ثنائية TOTP
   - صلاحيات RBAC
   - منع حقن SQL (parameterized queries)
   - حماية XSS (DOMPurify + InputSanitizationMiddleware)
   - تقييد المعدل (تسجيل الدخول: 5/دقيقة، API: 30/ثانية)
   - روابط ملفات موقعة بـ HMAC
   - تشفير البيانات الحساسة (PII)
   - سجل تدقيق كامل

6. **فصل المجدول:** في التطوير `in_process`، في الإنتاج `dedicated` (عامل منفصل لضمان عدم تكرار المهام عند وجود عدة نسخ ويب).

7. **مراقبة:** Prometheus + Grafana + Sentry + سجلات JSON منظمة

8. **ترجمة كاملة:** عربي/إنجليزي (i18next للفرونت، JSON للخطأ في الباك، دعم RTL)

9. **امتثال ZATCA (السعودية):** فواتير إلكترونية UBL XML + توقيع رقمي + صندوق صادر للموافقة

10. **جوال غير متصل:** React Native + SQLite للتخزين المحلي + مزامنة + فض نزاعات
