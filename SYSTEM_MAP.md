# خريطة نظام AMAN ERP - الشاملة

> **آخر تحديث:** 2026-05-08  
> **الإصدار:** 2.0.0  
> **نوع النظام:** ERP متعدد المستأجرين (Multi-Tenant)  
> **النطاق:** محاسبة، مبيعات، مشتريات، مخزون، موارد بشرية، تصنيع، نقاط بيع، CRM، مشاريع، أصول، خزينة، ضرائب، ZATCA، خدمات ميدانية، اشتراكات، إدارة مستندات، تكاملات

ملاحظات الفحص: تم تجاهل `docs/` بالكامل، وكذلك `node_modules/` و`dist/` و`uploads/` و`__pycache__/` و`.hypothesis/`. ملف `backend/db_ddl/tenant_schema.py` طويل جداً، لذلك تم فحص بدايته واستخراج ملخص دلالي منه عبر أسماء الدوال والجداول دون قراءة الملف كاملاً يدوياً.

---

## 1. الهيكل العام للمشروع

```text
aman/
├── AGENTS.md
├── SYSTEM_SCAN_PROMPT.md
├── package.json
├── package-lock.json
├── docker-compose.yml
├── docker-compose.prod.yml
├── playwright.config.ts
├── deploy.sh
├── deploy_server.py
├── safe-start.sh
├── safe-stop.sh
├── start-local.sh
├── stop-local.sh
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── playwright.yml
│       └── security-scan.yml
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── worker.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── Dockerfile
│   ├── adapters/
│   │   └── health.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/              # 77 migration
│   ├── db_ddl/
│   │   ├── tenant_schema.py        # مصدر DDL الرئيسي لكل مستأجر
│   │   ├── reports_mvs.py
│   │   ├── reports_indexes.py
│   │   ├── tenant_runner.py
│   │   └── break_glass_audit_log.py
│   ├── integrations/
│   │   ├── payments/
│   │   ├── bank_feeds/
│   │   ├── sms/
│   │   ├── shipping/
│   │   └── einvoicing/
│   ├── locales/
│   │   ├── errors.ar.json
│   │   └── errors.en.json
│   ├── middleware/
│   │   └── cache_observability.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── domain_models/          # 55 ملف نماذج مجال
│   ├── plugins/
│   │   └── gl_posting_metrics/
│   ├── repositories/
│   │   ├── invoice_repo.py
│   │   ├── product_repo.py
│   │   └── employee_repo.py
│   ├── routers/                    # 234 ملف راوتر Python
│   │   ├── auth/
│   │   ├── finance/
│   │   ├── sales/
│   │   ├── purchases/
│   │   ├── inventory/
│   │   ├── hr/
│   │   ├── manufacturing/
│   │   ├── pos/
│   │   ├── crm/
│   │   ├── projects/
│   │   ├── reports/
│   │   ├── notifications/
│   │   ├── einvoicing/
│   │   ├── dms/
│   │   ├── fsm/
│   │   ├── payroll/
│   │   └── system_completion/
│   ├── schemas/                    # 53 ملف Pydantic schema
│   ├── scripts/
│   ├── services/                   # 150 ملف خدمة Python
│   ├── tests/                      # 74 ملف pytest أساسي
│   └── utils/                      # 42 أداة مساعدة
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── vitest.config.js
│   └── src/
│       ├── App.jsx                 # 974 سطر، التوجيه الرئيسي
│       ├── i18n.js
│       ├── components/
│       ├── config/
│       ├── context/
│       ├── hooks/
│       ├── i18n/
│       ├── locales/
│       ├── pages/                  # 366 صفحة/ملف JSX تقريباً
│       ├── router/
│       ├── services/               # 41 عميل API
│       ├── styles/
│       ├── tests/
│       └── utils/
├── mobile/
│   ├── package.json
│   ├── App.jsx
│   └── src/
│       ├── screens/
│       ├── services/
│       ├── store/
│       └── utils/
├── tests/
│   ├── fixtures/
│   ├── seed/
│   └── specs/                      # Playwright API E2E
├── nginx/
│   ├── production.conf
│   └── production.conf.template
├── monitoring/
│   ├── prometheus.yml
│   ├── alertmanager.yml
│   ├── alerts/
│   └── grafana/
├── ops/
│   ├── k8s/
│   └── systemd/
└── scripts/
```

ملاحظة Speckit: ملف `.specify/feature.json` يشير إلى `specs/001-system-basic-info-setup`، لكن هذا المجلد غير موجود حالياً داخل `specs/`.

---

## 2. التكنولوجيات المستخدمة

### 2.1 الواجهة الخلفية (Backend)

| التقنية | الإصدار/المصدر | الغرض |
|---|---|---|
| Python | 3.12 في CI | تشغيل FastAPI والخدمات |
| FastAPI | من `requirements.txt` | API framework |
| Uvicorn/Gunicorn | من `requirements.txt` و`docker-compose.prod.yml` | تشغيل ASGI في التطوير والإنتاج |
| SQLAlchemy | من `requirements.txt` | ORM واتصالات PostgreSQL |
| Alembic | من `requirements.txt` | migrations متعددة المستأجرين |
| PostgreSQL | 15 في Docker dev، 16 في CI | قاعدة البيانات النظامية وقواعد المستأجرين |
| Redis | 7-alpine | كاش، rate limiting، queues، event bus |
| Pydantic Settings | من `requirements.txt` | إعدادات `.env` والتحقق |
| python-jose/passlib/bcrypt | من `requirements.txt` | JWT وكلمات المرور |
| SlowAPI | من `requirements.txt` | rate limiting |
| APScheduler | من `requirements.txt` | مهام مجدولة |
| Sentry SDK | من `requirements.txt` | تتبع أخطاء ومراقبة |
| prometheus-fastapi-instrumentator | من `requirements.txt` | metrics |
| signxml/lxml/qrcode | من `requirements.txt` | ZATCA/UBL/QR |
| python3-saml/python-ldap | من `requirements.txt` | SSO وLDAP |
| firebase-admin | من `requirements.txt` | Push notifications |
| clamd/python-magic | من `requirements.txt` | فحص ملفات DMS |

### 2.2 الواجهة الأمامية (Frontend)

| التقنية | الإصدار | الغرض |
|---|---|---|
| React | ^18.2.0 | تطبيق SPA |
| Vite | ^5.0.0 | build/dev server |
| React Router | ^6.20.0 | التوجيه |
| Axios | ^1.6.0 | API client |
| i18next/react-i18next | ^25.7.4 / ^16.5.3 | الترجمة عربي/إنجليزي |
| lucide-react/react-icons | ^0.562.0 / ^5.5.0 | الأيقونات |
| Recharts/ECharts | ^3.6.0 / ^6.0.0 | الرسوم البيانية |
| react-hook-form | ^7.71.1 | النماذج |
| react-window | ^2.2.7 | القوائم الكبيرة |
| Vitest/jsdom/Testing Library | ^1.4.0 / ^24.0.0 | اختبارات الوحدة |

### 2.3 تطبيق الجوال (Mobile)

| التقنية | الإصدار | الغرض |
|---|---|---|
| React Native | 0.76.9 | تطبيق جوال |
| React | 18.2.0 | واجهة التطبيق |
| React Navigation | ^6.x | التنقل |
| Async Storage | ^2.1.2 | تخزين جلسة محلي |
| NetInfo | ^12.0.1 | مراقبة الاتصال |
| Firebase Messaging | ^21.12.1 | إشعارات دفع |
| SQLite Storage | ^6.0.1 | تخزين غير متصل |
| Jest | ^29.7.0 | اختبارات |

### 2.4 التشغيل والمراقبة

| التقنية | الإصدار/المصدر | الغرض |
|---|---|---|
| Docker Compose | `docker-compose.yml` | تشغيل dev/staging |
| Nginx | `nginx/production.conf` | reverse proxy وSSL وsecurity headers |
| Prometheus | v2.51.0 | metrics |
| Grafana | 10.4.2 | dashboards |
| postgres-exporter | v0.15.0 | metrics PostgreSQL |
| redis_exporter | v1.58.0 | metrics Redis |
| ClamAV | latest ضمن profile dev | فحص ملفات DMS |

---

## 3. هيكل قاعدة البيانات

### 3.1 آلية تعدد المستأجرين (Multi-Tenancy)

النظام يستخدم قاعدة نظامية مركزية وقاعدة بيانات مستقلة لكل شركة. اسم قاعدة المستأجر يبنى من `aman_{company_id}` عبر `settings.get_company_database_url(company_id)`.

الطبقة المركزية في `backend/database.py` تحتوي:

| العنصر | الوصف |
|---|---|
| `engine` | اتصال قاعدة النظام المركزية |
| `_ddl_engine` | اتصال AUTOCOMMIT لإنشاء قواعد البيانات |
| `system_companies` | سجل الشركات والمستأجرين |
| `system_user_index` | فهرس مركزي لتسريع تسجيل الدخول حسب المستخدم والشركة |
| `_get_engine(company_id)` | LRU cache لمحركات قواعد المستأجرين |
| `get_tenant_db(company_id)` | context manager لاتصال مستأجر |
| `create_company_database()` | إنشاء قاعدة مستأجر |
| `create_company_tables()` | إنشاء مخطط المستأجر وتهيئته |

إعدادات كاش محركات المستأجرين من `backend/config.py`:

| المتغير | القيمة الافتراضية | المعنى |
|---|---:|---|
| `DB_TENANT_ENGINE_CACHE_SIZE` | 50 | عدد محركات المستأجرين المحفوظة |
| `DB_TENANT_POOL_SIZE` | 2 | حجم pool لكل مستأجر |
| `DB_TENANT_MAX_OVERFLOW` | 3 | الاتصالات الزائدة لكل مستأجر |

### 3.2 الجداول النظامية (System Tables)

تنشأ في `backend/main.py` أثناء lifespan إذا لم تكن موجودة:

| الجدول | الغرض |
|---|---|
| `system_user_index` | فهرسة المستخدمين عبر الشركات لتسجيل الدخول السريع |
| `system_companies` | بيانات الشركات، الاشتراك، العملة، timezone، الوحدات |
| `industry_templates` | قوالب صناعية وتفعيل وحدات حسب النشاط |
| `system_activity_log` | سجل نشاط مركزي على مستوى النظام |

### 3.3 مجالات قاعدة البيانات لكل مستأجر

ملف `backend/db_ddl/tenant_schema.py` هو المصدر الرئيسي لمخطط المستأجر. تم استخراج 351 عبارة `CREATE TABLE IF NOT EXISTS` تقريباً و277 عبارة `CREATE INDEX IF NOT EXISTS` تقريباً، إضافة إلى materialized views.

| مجموعة DDL | عدد جداول تقريبي | أمثلة |
|---|---:|---|
| Foundation | 13 | users, branches, accounts, treasury_accounts, suppliers |
| Additional Base | 28 | customers, products, warehouses, inventory, RFQ |
| Core Dependent | 6 | journal_lines, parties, invoices, invoice_lines |
| Sales/Purchases dependent | 14 | purchase_orders, sales_orders, returns, vouchers |
| Organization/HR | 27 | payroll_periods, employees, attendance, leave_requests |
| Financial | 48 | balances, receipts, budgets, assets, tax, projects |
| Treasury dependent | 6 | checks, notes, expense_policies, expenses |
| Currency | 3 | currencies, exchange_rates, currency_transactions |
| Contracts | 3 | contracts, contract_items, contract_milestones |
| Costing policy | 4 | costing policies and snapshots |
| Advanced inventory | 15 | batches, serials, QC, variants, bins, kits |
| Manufacturing | 19 | work centers, routing, BOM, production, MRP, service requests |
| POS | 14 | sessions, orders, payments, returns, loyalty, tables, kitchen |
| Approvals | 3 | workflows, requests, actions |
| Security/CRM/External | 24 | sessions, API keys, webhooks, WHT, CRM, tickets |
| Cashflow forecast | 2 | forecasts and lines |
| Phase features | 12 | matching, SSO, cost layers, intercompany, notification prefs |
| System completion | 20 | delivery, landed cost, print templates, backups, security |
| Extended features | 36 | subscriptions, dunning, einvoice outbox, documents, alerts |
| Performance/archive | 8 | audit archive, inventory archive, petty cash, salary advances |
| GL/IFRS/ZATCA/Outbox | 18 | ledgers, ECL, NRV, impairment, revenue contracts, ZATCA |
| Integration layer | 5 | integration keys, circuit state, retry queues, DLQ |
| Audit/security finance | 7 | audit_outbox, credentials, classifications, device fingerprints |
| Feature 023 | 13 | unified returns, ZATCA outbox, POS offline, MRP recommendations |
| Feature 024 | 1 | scheduled_job_runs |

Materialized views:

| المصدر | views |
|---|---|
| `tenant_schema.py` | `mv_revenue_summary`, `mv_expense_summary`, `mv_cash_position`, `mv_top_customers`, `mv_ar_aging`, `mv_ap_aging`, `mv_inventory_turnover`, `mv_sales_pipeline` |
| `reports_mvs.py` | `mv_daily_financial_chart`, `mv_period_stats` |

### 3.4 نماذج ORM

| العنصر | العدد التقريبي |
|---|---:|
| ملفات `backend/models/domain_models` | 55 |
| classes مستخرجة من النماذج | 288 تقريباً |
| migrations في `backend/alembic/versions` | 77 |

المجالات الرئيسية في النماذج: core accounting، core business، HR payroll، inventory، procurement، finance treasury/tax، projects، operations، approvals/security، assets، costing، currency، fiscal/zakat، CRM، POS، CPQ، intercompany، matching، SSO، subscriptions، demand forecast، mobile sync.

---

## 4. API Routes

تم استخراج المسارات من ملفات `backend/routers/**/*.py` ومن تركيب `app.include_router` في `backend/main.py`. عدد المسارات الفعلية بعد الدمج وإزالة التكرار: **1178 route**.

ملاحظة مهمة: بعض الراوترات الاختيارية تعرف `prefix` يبدأ بـ `/api` ثم تركب في `main.py` أيضاً تحت `prefix="/api"`، لذلك يظهر حسب الكود مسار من نوع `/api/api/...` لبعض FSM/DMS/Payroll/HR admin routes.

### 4.1 توزيع المسارات حسب الوحدة

| الوحدة | عدد routes |
|---|---:|
| المالية والمحاسبة | 293 |
| التقارير ولوحات التحكم | 121 |
| الموارد البشرية والرواتب | 112 |
| الإدارة والأمان والإعدادات | 96 |
| المبيعات والعقود | 90 |
| المخزون | 89 |
| المشتريات والأطراف | 65 |
| التصنيع | 63 |
| المشاريع | 59 |
| CRM | 52 |
| التكاملات والخدمات | 49 |
| نقاط البيع | 37 |
| المصادقة والصلاحيات | 28 |
| أخرى | 19 |
| صحة النظام | 5 |

### 4.2 المصادقة والصلاحيات

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/auth/*` | GET/POST/PUT/DELETE | تسجيل دخول، refresh/logout، إدارة الجلسات، reset password |
| `/api/security/2fa/*` | GET/POST | إعداد وتفعيل وتعطيل 2FA |
| `/api/auth/sso/*` | GET/POST/PUT/DELETE | SAML/LDAP config، mappings، metadata، ACS، exchange |
| `/api/security/sessions*` | GET/DELETE | الجلسات النشطة وإنهاؤها |
| `/api/roles/*` | GET/POST/PUT/DELETE | الأدوار والصلاحيات الافتراضية |

أمثلة مباشرة:

| المسار | الطريقة | الوصف |
|---|---|---|
| `/api/auth/login` | POST | تسجيل الدخول |
| `/api/auth/refresh` | POST | تدوير access token عبر refresh cookie |
| `/api/auth/logout` | POST | إنهاء الجلسة |
| `/api/security/2fa/setup` | POST | إنشاء سر 2FA وQR |
| `/api/security/2fa/verify` | POST | تفعيل 2FA |
| `/api/auth/sso/providers` | GET | مزودي SSO النشطين |
| `/api/auth/sso/saml/metadata` | GET | SAML SP metadata |

### 4.3 المالية والمحاسبة

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/accounting/*` | GET/POST/PUT/DELETE | الحسابات، القيود، السنوات والفترات، القيود المتكررة، FX، opening/closing |
| `/api/accounting/budgets/*` | GET/POST/PUT/DELETE | الموازنات والبنود والتقارير |
| `/api/accounting/intercompany/*` | GET/POST/PUT/DELETE | intercompany v2، mapping، consolidation |
| `/api/finance/*` | GET/POST/PUT/DELETE | bank feeds، payments، accounting-depth، subscriptions، cashflow |
| `/api/treasury/*` | GET/POST/PUT/DELETE | حسابات خزينة، تحويلات، مصاريف، تسوية |
| `/api/reconciliation/*` | GET/POST/PUT | bank reconciliation |
| `/api/checks/*` | GET/POST/PUT | شيكات واردة وصادرة، تحصيل، صرف، ارتداد |
| `/api/notes/*` | GET/POST/PUT | أوراق قبض ودفع |
| `/api/assets/*` | GET/POST/PUT/DELETE | أصول، نقل، إهلاك، صيانة، تأمين، إعادة تقييم، impairment، QR |
| `/api/taxes/*` | GET/POST/PUT/DELETE | VAT/WHT/Zakat، معدلات، مجموعات، إقرارات، دفع، تقويم |
| `/api/tax-compliance/*` | GET/POST/PUT | الأنظمة الضريبية وإعدادات الفروع |
| `/api/expenses/*` | GET/POST/PUT/DELETE | مصاريف، سياسات، اعتماد، عكس |
| `/api/cost-centers/*` | GET/POST/PUT/DELETE | مراكز التكلفة |
| `/api/costing-policies/*` | GET/POST/PUT | سياسات التكلفة |
| `/api/matching/*` و`/api/buying/matches/*` | GET/POST/PUT | three-way matching |
| `/api/party-balances/*` | GET | أرصدة العملاء والموردين حسب الفرع/الموقع |

### 4.4 المبيعات والعقود

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/sales/customers*` | GET/POST/PUT/DELETE | العملاء، المجموعات، المعاملات، حدود الائتمان |
| `/api/sales/invoices*` | GET/POST/PATCH | فواتير البيع، preview، cancellation، payment history |
| `/api/sales/orders*` | GET/POST/PUT | أوامر البيع والتحويل إلى فاتورة |
| `/api/sales/quotations*` | GET/POST | عروض الأسعار، إرسال بريد، تحويل |
| `/api/sales/returns*` | GET/POST | مرتجعات البيع |
| `/api/sales/credit-notes*` | GET/POST | إشعارات دائنة |
| `/api/sales/debit-notes*` | GET/POST | إشعارات مدينة |
| `/api/sales/receipts*` | GET/POST | سندات قبض |
| `/api/sales/payments*` | GET/POST | سندات دفع/مدفوعات ضمن المبيعات |
| `/api/sales/delivery-orders*` | GET/POST/PUT | أوامر التسليم |
| `/api/sales/cpq/*` | GET/POST | منتجات قابلة للتكوين، تسعير، quotes، PDF، convert |
| `/api/contracts*` | GET/POST/PUT | عقود، milestones، renew، cancel، generate invoice |
| `/api/price-lists*` | GET/POST | قوائم أسعار واستيراد Excel |

### 4.5 المشتريات والأطراف

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/buying/suppliers*` | GET/POST/PUT/DELETE | الموردون، المجموعات، تفاصيل، statement |
| `/api/buying/orders*` | GET/POST/PUT | أوامر الشراء والاستلام |
| `/api/buying/invoices*` | GET/POST/PUT | فواتير الشراء |
| `/api/buying/returns*` | GET/POST | مرتجعات الشراء |
| `/api/buying/payments*` | GET/POST | مدفوعات الموردين |
| `/api/buying/blanket*` | GET/POST/PUT | Blanket purchase orders |
| `/api/purchases/landed-costs*` | GET/POST | التكاليف الإضافية والتوزيع والترحيل |
| `/api/parties*` | GET/POST/PUT | الأطراف الموحدة، العملاء/الموردون، كشف التكرارات |
| `/api/party-sites*` | GET/POST/PUT | مواقع الأطراف وأرصدة المواقع |

### 4.6 المخزون

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/inventory/products*` | GET/POST/PUT/DELETE | المنتجات، وحدات، SKU، باركود |
| `/api/inventory/categories*` | GET/POST/PUT/DELETE | تصنيفات المنتجات |
| `/api/inventory/warehouses*` | GET/POST/PUT/DELETE | المستودعات والتفاصيل |
| `/api/inventory/transfers*` | GET/POST/PUT | التحويلات المخزنية |
| `/api/inventory/adjustments*` | GET/POST | التسويات |
| `/api/inventory/stock-movements*` | GET | حركة المخزون |
| `/api/inventory/shipments*` | GET/POST/PUT | الشحنات |
| `/api/inventory/reports*` | GET | التقارير المخزنية |
| `/api/inventory/batches*` | GET/POST/PUT | batches/serials |
| `/api/inventory/advanced/*` | GET/POST/PUT | variants، bins، kits، ledger |
| `/api/inventory/costing/*` | GET/POST | costing layers/valuation |
| `/api/inventory/forecast/*` | GET/POST | demand forecast |
| `/api/inventory/archival/*` | GET/POST | أرشفة الحركات |

### 4.7 الموارد البشرية والرواتب

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/hr/employees*` | GET/POST/PUT | الموظفون وPII والزيادات |
| `/api/hr/departments*` | GET/POST/PUT | الأقسام |
| `/api/hr/positions*` | GET/POST/PUT | المناصب |
| `/api/hr/payroll-periods*` | GET/POST | فترات الرواتب، توليد، ترحيل، reverse |
| `/api/hr/payslips*` | GET/POST | قسائم الرواتب |
| `/api/hr/attendance*` | GET/POST | الحضور |
| `/api/hr/leaves*` | GET/POST/PUT | الإجازات |
| `/api/hr/loans*` | GET/POST/PUT | السلف والقروض |
| `/api/hr-advanced/*` | GET/POST/PUT | تدريب، مخالفات، عهد، توظيف، performance |
| `/api/hr/self-service*` | GET/POST/PUT | بوابة الموظف الذاتية |
| `/api/hr/wps/*` | GET/POST | WPS preview/export |
| `/api/hr/saudization/*` | GET | السعودة ونطاقات |
| `/api/hr/employee-receipts*` | GET/POST | تسويات قبض الموظفين |

### 4.8 التصنيع

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/manufacturing/work-centers*` | GET/POST/PUT/DELETE | مراكز العمل |
| `/api/manufacturing/routes*` | GET/POST/PUT/DELETE | routings |
| `/api/manufacturing/boms*` | GET/POST/PUT/DELETE | BOMs ومكونات |
| `/api/manufacturing/orders*` | GET/POST/PUT | production orders، approval، QC، completion |
| `/api/manufacturing/mrp*` | GET/POST | MRP plans/recommendations |
| `/api/manufacturing/equipment*` | GET/POST/PUT | معدات وصيانة |
| `/api/manufacturing/reports*` | GET | تقارير التصنيع |
| `/api/manufacturing/shopfloor*` | GET/POST | shop floor logs وoperations |
| `/api/manufacturing/routing*` | GET/POST/PUT | إدارة routing المتقدمة |

### 4.9 نقاط البيع

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/pos/sessions*` | GET/POST/PUT | جلسات POS |
| `/api/pos/orders*` | GET/POST/PUT | أوامر POS والمدفوعات |
| `/api/pos/promotions*` | GET/POST/PUT/DELETE | العروض |
| `/api/pos/loyalty*` | GET/POST/PUT | الولاء والنقاط |
| `/api/pos/tables*` | GET/POST/PUT | الطاولات |
| `/api/pos/kitchen*` | GET/POST/PUT | شاشة المطبخ |
| `/api/pos/offline*` | GET/POST | batches ومزامنة offline |
| `/api/pos/sync*` | GET/POST | حل التعارضات |
| `/api/pos/cancellation*` | POST | إلغاء عمليات POS |

### 4.10 CRM

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/crm/opportunities*` | GET/POST/PUT/DELETE | الفرص والمراحل |
| `/api/crm/tickets*` | GET/POST/PUT | تذاكر الدعم |
| `/api/crm/campaigns*` | GET/POST/PUT | الحملات |
| `/api/crm/knowledge-base*` | GET/POST/PUT | قاعدة المعرفة |
| `/api/crm/segments*` | GET/POST/PUT | شرائح العملاء |
| `/api/crm/contacts*` | GET/POST/PUT | جهات الاتصال |
| `/api/crm/analytics*` | GET | تحليلات pipeline |
| `/api/crm/velocity*` | GET | سرعة التحويل |
| `/api/crm/funnel*` | GET | funnel conversion |
| `/api/crm/cashflow*` | GET | feed للتدفق النقدي |

### 4.11 المشاريع

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/projects*` | GET/POST/PUT/DELETE | المشاريع الأساسية |
| `/api/projects/tasks*` | GET/POST/PUT | مهام المشروع |
| `/api/projects/timetracking*` | GET/POST/PUT | timesheets |
| `/api/projects/resources*` | GET/POST/PUT | الموارد والتخصيص |
| `/api/projects/finance*` | GET | مالية المشروع |
| `/api/projects/monitoring*` | GET | مراقبة المشروع |
| `/api/projects/change-orders*` | GET/POST/PUT | أوامر تغيير |
| `/api/projects/risks*` | GET/POST/PUT | المخاطر |

### 4.12 التقارير ولوحات التحكم

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/dashboard/*` | GET/POST/PUT/DELETE | KPIs، widgets، layouts، analytics dashboards |
| `/api/dashboard/role/*` | GET | لوحات حسب الدور: executive, financial, sales, HR, manufacturing, projects |
| `/api/reports/*` | GET/POST/PUT/DELETE | مركز التقارير، scheduled/shared/custom/cache |
| `/api/reports/accounting/*` | GET | trial balance، P&L، balance sheet، GL |
| `/api/reports/sales/*` | GET | مبيعات، aging، statement |
| `/api/reports/purchases/*` | GET | مشتريات، aging، supplier statement |
| `/api/reports/inventory/*` | GET | inventory analytics |
| `/api/kpi/*` | GET/POST | إدارة تعريفات KPI وتقييماتها |
| `/api/search*` | GET | بحث موحد وسجل البحث |
| `/api/calculate/*` | POST | حساب إجماليات الفواتير والعقود بدون حفظ |

### 4.13 الإدارة والإعدادات والتكاملات

| عائلة المسار | الطرق | الوصف |
|---|---|---|
| `/api/companies/*` | GET/POST/PUT | تسجيل الشركات، الوحدات، templates، logo |
| `/api/branches*` | GET/POST/PUT/DELETE | الفروع |
| `/api/settings/*` | GET/POST | إعدادات الشركة، CSID، SMTP |
| `/api/audit/*` | GET | سجل التدقيق |
| `/api/security/*` | GET/POST/PUT/DELETE | سياسة كلمات المرور، أحداث أمنية، جلسات |
| `/api/data-import/*` | GET/POST | preview، execute، history، export، templates |
| `/api/governance/*` | GET/POST/PUT | حوكمة مالية/ضريبية/HR/أصول/POS/خدمات |
| `/api/admin/credentials*` | GET/POST | vault credentials |
| `/api/admin/account-classifications*` | GET/POST | تصنيف الحسابات للتقارير |
| `/api/admin/recurring/*` | GET/POST | مراجعة القيود المتكررة |
| `/api/alerts/*` | GET/POST/PUT | smart alerts |
| `/api/email-templates/*` | GET/POST/PUT | قوالب البريد |
| `/api/integrations/*` | GET/POST/PUT | مفاتيح التكامل وDLQ/circuit breaker |
| `/api/external/*` | GET/POST/PUT/DELETE | API keys، webhooks، WHT، ZATCA helpers |
| `/api/services/*` | GET/POST/PUT/DELETE | طلبات خدمة ومستندات |
| `/api/notifications/*` | GET/POST/PUT | إشعارات وقوالب وطابور |
| `/api/mobile/*` | GET/POST | sync ودashboard وتسجيل جهاز |
| `/api/sms/*` | GET/POST | مزودي SMS، إرسال، logs |
| `/api/shipping/*` | GET/POST | carriers/shipments/tracking |
| `/api/einvoicing/outbox*` | GET/POST | ZATCA outbox وإعادة المعالجة |
| `/api/ops/*` | GET/POST | scheduler/restore |
| `/api/locale/*` | GET | اللغة والترجمة |

### 4.14 صحة النظام

| المسار | الطريقة | الوصف |
|---|---|---|
| `/` | GET | معلومات النظام والإصدار |
| `/health` | GET | alias للصحة يستخدمه Docker/load balancer |
| `/api/health` | GET | صحة DB/cache/scheduler تقريباً |
| `/api/health/cache` | GET | hit/miss للكاش |
| `/api/health/scheduler` | GET | حالة jobs المجدولة |

---

## 5. الواجهة الأمامية - الصفحات الرئيسية

`frontend/src/App.jsx` يستخدم lazy loading مع `PrivateRoute` وصلاحيات دقيقة. المسارات الرئيسية تتوزع كالتالي:

| الوحدة | صفحات/مسارات رئيسية |
|---|---|
| عام | login، register، forgot/reset password، dashboard، profile، 404 |
| Setup | industry setup، module customization، onboarding wizard |
| Accounting | COA، journal entries، fiscal years، recurring templates، opening/closing balances، budgets، VAT، tax audit، cashflow، GL، trial balance، P&L، balance sheet، currencies، zakat، fiscal locks، intercompany، revenue recognition |
| Sales | customers، invoices، orders، quotations، returns، receipts/payments، price lists، reports، contracts، credit/debit notes، commissions، delivery orders، CPQ |
| Buying/Purchases | suppliers، RFQ، purchase orders، invoices، returns، payments، landed cost، supplier statements، blanket PO |
| Stock | products، categories، warehouses، transfers، adjustments، shipments، batches، serials، QC، price lists، valuation، profitability، movements |
| Treasury | accounts، transfers، reconciliation، checks، notes، bank import، balances/cashflow reports |
| HR | employees، departments، positions، payroll، loans، leaves، attendance، reports، salary structures، overtime، GOSI، documents، performance، training، violations، custody، WPS، saudization، EOS، self-service |
| Manufacturing | work centers، routings، BOMs، production orders، job cards، MRP، equipment، schedule، reports، costing، capacity، shop floor |
| Projects | list/details/form، resources، risks، financial/resource reports، Gantt، timesheets، timetracking |
| POS | home، interface، promotions، loyalty، tables، kitchen، offline، thermal، customer display |
| CRM | opportunities، tickets، campaigns، knowledge base، lead scoring، segments، analytics، contacts، forecasts |
| Reports/KPI/Analytics | report center، builder، scheduled/shared، consolidation، KPI dashboard/admin، FX gain/loss، IAS7، industry reports، custom dashboards |
| Admin/Settings | companies، audit logs، roles، backups، security events، scheduler، health، company profile، branches، costing policy، API keys، webhooks، print templates، smart alerts، email templates، SSO |
| Services/DMS/Notifications | service requests، document management، quotas، quarantine alerts، notification queue، email template editor |
| Finance extras | subscriptions، cashflow forecasts، matching، costing، tax compliance، WHT |

مكونات الواجهة الرئيسية:

| المجلد/الملف | الوظيفة |
|---|---|
| `components/Layout.jsx` | الهيكل العام |
| `components/Sidebar.jsx` و`Topbar.jsx` | التنقل |
| `components/common/*` | جداول، بطاقات، pagination، modal، loading states، date inputs |
| `components/dashboard/*` | widgets للوحة التحكم |
| `components/kpi/*` | KPI cards/charts/gauge |
| `components/Notifications/NotificationCenter.jsx` | مركز الإشعارات |
| `components/GlobalSearch.jsx` | البحث العام |
| `context/*` | Theme، Toast، Branch |

طبقة API في الفرونت تعتمد على `frontend/src/services/apiClient.js`:

| الخاصية | الوصف |
|---|---|
| `baseURL` | `VITE_API_URL` أو `/api` |
| `withCredentials` | يرسل refresh cookie |
| CSRF | يقرأ `csrf_token` ويضيف `X-CSRF-Token` للطلبات المتغيرة |
| token refresh | mutex يمنع refresh متزامن متعدد |
| branch scope | يضيف `branch_id` تلقائياً لطلبات GET |
| i18n | يضيف `Accept-Language` |
| error handling | toast عالمي للأخطاء مع رسائل عربية/إنجليزية |

---

## 6. الخدمات الخلفية (Services)

### 6.1 خدمات مالية ومحاسبية

| الخدمة | الوظيفة |
|---|---|
| `gl_service.py` | تحقق وترحيل القيود مع Decimal وضبط الاتزان |
| `tax_engine.py` | محرك ضريبة متعدد البلدان والفروع |
| `reconciliation_service.py` | إنهاء التسويات البنكية مع drift guard |
| `ifrs15_revenue_service.py` | عقود IFRS 15 وتوزيع transaction price |
| `ecl_service.py` | IFRS 9 ECL للذمم |
| `nrv_service.py` | اختبار NRV للمخزون |
| `impairment_service.py` | اختبارات impairment |
| `forecast_service.py` | توليد توقعات cashflow |
| `multibook_service.py` | ترحيل قيود multi-book |
| `recurring_je_service.py` | القيود اليومية المتكررة والمراجعة |
| `account_classifier.py` | تصنيف الحسابات للتقارير |
| `finance/cost_center_policy.py` | سياسات إلزام/تحذير مركز التكلفة |

### 6.2 خدمات المبيعات والمخزون والتصنيع

| الخدمة | الوظيفة |
|---|---|
| `sales/invoice_state.py` | transitions لحالة الفاتورة |
| `sales/account_mapping.py` | حل حسابات المبيعات |
| `sales/order_to_invoice.py` | تحويل أمر بيع إلى فاتورة |
| `sales/sales_cancellation.py` | إلغاء الفاتورة مع preflight للمخزون |
| `returns_unified_service.py` | كتابة المرتجعات الموحدة |
| `cpq_service.py` | تحقق وتحديد سعر التكوين |
| `inventory/wac_per_warehouse.py` | WAC لكل مستودع |
| `inventory/auto_reorder.py` | إعادة الطلب التلقائي |
| `inventory/archival.py` | أرشفة حركات المخزون |
| `inventory/transactions_reader.py` | قراءة live + archive |
| `inventory/low_stock_webhook.py` | Webhook عند انخفاض المخزون |
| `manufacturing/mrp.py` | MRP متعدد المستويات |
| `manufacturing/production_complete.py` | إكمال الإنتاج الجزئي والفعلية |
| `manufacturing/qc_gate.py` | بوابة QC |
| `manufacturing/scrap.py` | تسجيل scrap |
| `manufacturing/byproduct_allocator.py` | توزيع by-products |
| `manufacturing/workstation_overhead.py` | معدلات overhead |

### 6.3 HR وFSM وDMS

| الخدمة | الوظيفة |
|---|---|
| `hr/pii.py` | تشفير/فك/إخفاء PII للموارد البشرية |
| `hr/bulk_salary_increment.py` | زيادات الرواتب الجماعية |
| `hr/attendance_timetracking.py` | ربط الحضور بتتبع الوقت |
| `hr/service_years.py` | حساب سنوات الخدمة |
| `hr/ticket_allowance.py` | استحقاق بدل التذاكر |
| `ghost_employee_rule.py` | كشف ghost employees |
| `payroll/period_writer.py` | إنشاء فترة رواتب |
| `payroll/period_reversal.py` | عكس فترة الرواتب |
| `payroll/bank_movements.py` | حركات البنك للرواتب |
| `wps/bank_codes.py` | رموز بنوك WPS |
| `fsm/pricelists.py` | حل أسعار خدمات FSM |
| `fsm/coverage.py` | تغطية العقد |
| `fsm/contract_renew.py` | تجديد العقود |
| `fsm/zero_revenue_gate.py` | اعتماد أوامر خدمة بدون إيراد |
| `fsm/maintenance/*` | إنشاء وجدولة صيانة وقائية |
| `dms/storage_paths.py` | مسارات التخزين |
| `dms/streaming_mime.py` | تحقق MIME |
| `dms/antimalware.py` | فحص ClamAV |
| `dms/quotas.py` | حصص التخزين |
| `dms/attachment_links.py` | ربط المستندات بالكيانات |

### 6.4 التكاملات، الإشعارات، التقارير، التشغيل

| الخدمة | الوظيفة |
|---|---|
| `sso_service.py` | SAML/LDAP وتعيين المجموعات للأدوار |
| `credentials_vault.py` | تشفير أسرار التكامل |
| `integration_keys_service.py` | إدارة مفاتيح التكامل |
| `integration_retry_service.py` | retry queues وDLQ |
| `webhooks/dispatch.py` | إرسال webhooks |
| `webhook_rate_limit.py` | rate limiting للـ webhooks |
| `einvoicing/ubl_builder.py` | بناء UBL 2.1 |
| `einvoicing/ubl_signer.py` | توقيع XML |
| `einvoicing/outbox.py` | ZATCA outbox worker |
| `notifications/dispatcher.py` | إرسال إشعارات مع idempotency |
| `notifications/templates.py` | rendering عبر Jinja2 |
| `notifications/queue_worker.py` | معالجة طابور الإشعارات |
| `search/registry.py` | سجل كيانات البحث |
| `search/logging.py` | سجل استعلامات البحث |
| `reports/*` | trial balance، income statement، balance sheet، rollup، MV refresh |
| `kpi_service/*` | KPIs حسب الدور والمجال |
| `scheduler.py` و`scheduler/*` | APScheduler، idempotency، timezone، monitoring |
| `ops/restore.py` | restore dry-run/execute |
| `ops/audit_partitions.py` | صيانة partitions |
| `cache/*` | Redis cache client، invalidation، warmup، keys |

---

## 7. الأدوات المساعدة (Utils)

| الملف | الوظيفة |
|---|---|
| `utils/permissions.py` | صلاحيات RBAC وحراس الوحدات |
| `utils/security_middleware.py` | HTTPS redirect وinput sanitization |
| `utils/csrf_middleware.py` | CSRF double-submit cookie |
| `utils/auth_cookies.py` | refresh cookie وCSRF helpers |
| `utils/limiter.py` | SlowAPI rate limiter مع Redis |
| `utils/field_encryption.py` | AES-GCM للحقول الحساسة |
| `utils/pii_encryption.py` | تشفير PII |
| `utils/masking.py` | إخفاء PII |
| `utils/signed_urls.py` | روابط ملفات موقعة HMAC |
| `utils/sql_safety.py` | تحقق identifiers وحماية SQL |
| `utils/sql_builder.py` | بناء SQL مساعد |
| `utils/audit.py` | تسجيل تدقيق |
| `utils/audit_body_capture.py` | التقاط جسم الطلب للتدقيق |
| `utils/logging_config.py` | structured logging وRequest ID |
| `utils/query_counter.py` | عداد استعلامات SQL لكل طلب |
| `utils/cache.py` | كاش عام |
| `utils/redis_event_bus.py` | Redis Streams للأحداث |
| `utils/event_bus.py` | event bus داخل العملية |
| `utils/outbox_relay.py` | transactional outbox relay |
| `utils/plugin_registry.py` | سجل الإضافات |
| `utils/ws_manager.py` | WebSocket manager |
| `utils/i18n.py` | رسائل أخطاء مترجمة |
| `utils/email.py` | بريد |
| `utils/exports.py` | تصدير وتقارير مع خط عربي |
| `utils/fiscal_lock.py` | قفل الفترة المحاسبية |
| `utils/optimistic_lock.py` | optimistic locking |
| `utils/tenant_isolation.py` | عزل المستأجر |
| `utils/quantity_validation.py` | تحقق كميات |
| `utils/duplicate_detection.py` | كشف التكرار |
| `utils/balance_reconciliation.py` | مطابقة الأرصدة |
| `utils/treasury_balance.py` | أرصدة الخزينة |
| `utils/treasury_gl.py` | قيود الخزينة |
| `utils/zatca.py` و`zatca_clearance.py` | ZATCA QR/clearance |
| `middleware/cache_observability.py` | headers/decorator لمراقبة الكاش |

---

## 8. الاختبارات

### 8.1 اختبارات Backend

| النوع | الموقع | الملخص |
|---|---|---|
| pytest | `backend/tests/` | 74 ملف اختبار يغطي auth، accounting، sales، purchases، inventory، HR، treasury، reports، approvals، security، ZATCA، fiscal locks، POS parity، GL integrity |
| property-based | `hypothesis` في requirements | يستخدم لبعض اختبارات صحة القيود |
| performance/security scripts | `backend/tests/run_*` | تشغيل اختبارات أمان وأداء |

أمثلة ملفات مهمة: `test_01_auth.py`, `test_10_accounting_scenarios.py`, `test_38_security_2fa.py`, `test_46_gl_balance_property.py`, `test_58_audit_chain_immutability.py`, `test_61_pos_invoice_parity.py`.

### 8.2 اختبارات Frontend

| الملف | الغرض |
|---|---|
| `frontend/src/tests/auth.test.js` | تدفق المصادقة |
| `frontend/src/tests/useApi.test.js` | hook/API usage |
| `frontend/src/tests/useOptimisticList.test.js` | optimistic UI |
| `frontend/src/tests/phase8_services.test.js` | اختبارات خدمات |
| `frontend/src/tests/setup.js` | إعداد Testing Library |

`frontend/vitest.config.js` يستخدم `jsdom`, `globals`, وcoverage عبر `v8`.

### 8.3 اختبارات Playwright

| الموقع | الوصف |
|---|---|
| `playwright.config.ts` | E2E UI داخل `./e2e` على Chromium، reporter HTML |
| `tests/playwright.config.ts` | API E2E داخل `tests/specs` مع setup seed واعتماديات |
| `tests/specs/auth.spec.ts` | المصادقة |
| `tests/specs/branches.spec.ts` | الفروع |
| `tests/specs/currencies.spec.ts` | العملات |
| `tests/specs/permissions.spec.ts` | الصلاحيات |
| `tests/specs/financial.spec.ts` | المالية |
| `tests/specs/inventory.spec.ts` | المخزون |
| `tests/specs/hr.spec.ts` | HR |
| `tests/specs/isolation.spec.ts` | عزل المستأجر |

---

## 9. CI/CD والـ Deployment

### 9.1 Docker

| الخدمة | الصورة/البناء | المنفذ | التخزين |
|---|---|---:|---|
| `db` | `postgres:15-alpine` | `127.0.0.1:5432` | `db_data` |
| `redis` | `redis:7-alpine` | `127.0.0.1:6379` | `redis_data` |
| `backend` | `./backend/Dockerfile` | `8000` | `uploads` |
| `frontend` | `./frontend/Dockerfile` | `80:8080` | لا يوجد |
| `prometheus` | `prom/prometheus:v2.51.0` | `9090` | `prometheus_data` |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | داخلي | لا يوجد |
| `redis-exporter` | `oliver006/redis_exporter:v1.58.0` | داخلي | لا يوجد |
| `grafana` | `grafana/grafana:10.4.2` | `3000` | `grafana_data` |
| `clamav` | `clamav/clamav:latest` | `127.0.0.1:3310` | `clamav_data` |

إنتاجياً `docker-compose.prod.yml` يغلق منافذ DB/Redis/Backend/Prometheus/Grafana خارجياً، ويشغل backend عبر Gunicorn، ويضيف خدمة `worker` مخصصة للمجدول `python -m worker` مع replica واحدة.

### 9.2 متغيرات البيئة الأساسية

| المتغير | الغرض |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_SERVER`, `POSTGRES_PORT` | اتصال PostgreSQL |
| `REDIS_URL`, `REDIS_PASSWORD` | اتصال Redis |
| `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | JWT |
| `JWT_LEEWAY_SECONDS` | سماحية clock skew |
| `ADMIN_PASSWORD_HASH` | كلمة مرور admin مهيأة |
| `FRONTEND_URL`, `FRONTEND_URL_PRODUCTION`, `ALLOWED_ORIGINS` | CORS |
| `APP_ENV` | development/staging/production |
| `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` | Sentry |
| `EXPOSE_API_DOCS` | فتح أو إغلاق API docs |
| `CSRF_ENFORCEMENT`, `CSRF_COOKIE_NAME`, `CSRF_HEADER_NAME` | CSRF |
| `REFRESH_COOKIE_NAME`, `COOKIE_SAMESITE` | cookies |
| `SCHEDULER_MODE` | in_process/disabled/dedicated |
| `ZATCA_PHASE2_ENFORCE` | فرض clearance وقت إنشاء الفاتورة |
| `GRAFANA_USER`, `GRAFANA_PASSWORD` | Grafana |

### 9.3 GitHub Actions

| workflow | الوظيفة |
|---|---|
| `.github/workflows/ci.yml` | Backend lint/import smoke، guards، tenant bootstrap E2E، Alembic roundtrip، coverage، Frontend build/Vitest، dependency audit، deploy |
| `.github/workflows/playwright.yml` | تثبيت Playwright وتشغيل Chromium tests ورفع التقرير |
| `.github/workflows/security-scan.yml` | Gitleaks secret scanning |

وظائف CI الرئيسية:

| job | الوصف |
|---|---|
| `backend-static` | Python 3.12، تثبيت dependencies، Ruff syntax، import smoke لكل routers |
| `backend-guards` | SQL parameterization، GL discipline، PII logging، money float، invoice state، cache keys، schema sync |
| `frontend-guards` | number formatting، window.location، i18n strings |
| `tenant-bootstrap-e2e` | إنشاء مستأجر جديد والتأكد من >=290 جدول و>=8 MV |
| `alembic-roundtrip` | downgrade -1 ثم upgrade head على مستأجر bootstrapped |
| `backend-coverage` | pytest + coverage advisory |
| `frontend` | npm install، Vite build، Vitest |
| `dependency-audit` | pip-audit وnpm audit advisory |
| `deploy` | SSH إلى `/opt/aman` ثم pull/build/restart مع health checks |

### 9.4 Nginx وMonitoring وOps

| الملف | الوظيفة |
|---|---|
| `nginx/production.conf` | SSL/TLS، HTTP to HTTPS، rate limiting، security headers، CSP، gzip، frontend static، proxy للـ API |
| `monitoring/prometheus.yml` | scrape backend `/metrics`, postgres exporter, redis exporter, prometheus |
| `monitoring/alerts/aman_alerts.yml` | قواعد تنبيه |
| `monitoring/alertmanager.yml` | Alertmanager |
| `monitoring/grafana/dashboards/aman_backend.json` | لوحة Grafana |
| `ops/k8s/cronjob-backup.yaml` | نسخ احتياطي على Kubernetes |
| `ops/systemd/aman-backup.service` و`.timer` | نسخ احتياطي عبر systemd |

---

## 10. ملفات الدخول والإعدادات الرئيسية

| الملف | الوظيفة |
|---|---|
| `backend/main.py` | نقطة دخول FastAPI، middleware، CORS، metrics، mount uploads، تركيب كل الراوترات |
| `backend/config.py` | إعدادات Pydantic، DB، Redis، JWT، CSRF، Sentry، ZATCA، scheduler |
| `backend/database.py` | اتصال النظام والمستأجرين، إنشاء DB، تهيئة الجداول والبذور |
| `backend/worker.py` | عامل APScheduler المخصص للإنتاج |
| `backend/db_ddl/tenant_schema.py` | DDL الأساسي للمستأجر |
| `backend/db_ddl/reports_mvs.py` | materialized views للتقارير |
| `backend/alembic/env.py` | Alembic متعدد المستأجرين عبر `-x company=...` |
| `backend/models/__init__.py` | تصدير كل نماذج ORM |
| `backend/routers/__init__.py` | سطح حزمة الراوترات |
| `backend/services/scheduler.py` | تعريف وجدولة jobs |
| `frontend/src/App.jsx` | توجيه React والصفحات المحمية |
| `frontend/src/services/apiClient.js` | Axios instance وJWT/CSRF/branch/i18n interceptors |
| `frontend/src/i18n.js` | i18next عربي/إنجليزي |
| `frontend/vite.config.js` | Vite build، proxy `/api` و`/uploads` |
| `frontend/vitest.config.js` | Vitest/jsdom/coverage |
| `mobile/App.jsx` | دخول React Native، AuthContext، NetworkContext، navigation |
| `mobile/src/services/api.js` | عميل API للجوال |
| `mobile/src/services/syncService.js` | مزامنة offline |
| `mobile/src/store/offlineStore.js` | تخزين SQLite/محلي |
| `docker-compose.yml` | بيئة dev/staging |
| `docker-compose.prod.yml` | overrides للإنتاج وworker |
| `.env.example` | متغيرات Docker root |
| `playwright.config.ts` | E2E UI |
| `tests/playwright.config.ts` | E2E API |
| `.github/workflows/ci.yml` | CI/CD الرئيسي |
| `nginx/production.conf` | Nginx الإنتاجي |
| `monitoring/prometheus.yml` | Prometheus scrape config |

---

## 11. ملاحظات معمارية مختصرة

1. النظام multi-tenant على مستوى قاعدة البيانات، وليس schema فقط: كل شركة لها قاعدة مستقلة `aman_{company_id}`.
2. قاعدة النظام المركزية تحتفظ بالشركات وفهرس المستخدمين وقوالب الصناعة والسجل العام.
3. Backend منظم حسب طبقات: Routers -> Schemas -> Services -> Repositories/Utils -> Models/DDL -> PostgreSQL.
4. معظم الوحدات لها حضور كامل في Backend وFrontend: router + service + schema + pages + tests.
5. الأمان متعدد الطبقات: JWT، refresh cookie HttpOnly، CSRF double-submit، RBAC، 2FA، PII encryption/masking، signed URLs، SQL safety، rate limiting، audit chain.
6. الإنتاج يفصل المجدول في `worker` مستقل لتجنب تكرار jobs عند تعدد نسخ web.
7. تقارير الأداء تعتمد على materialized views وكاش Redis ومراقبة Prometheus/Grafana.
8. الامتثال السعودي حاضر عبر ZATCA UBL signing/outbox وWPS وSaudization/Zakat.
9. الجوال مصمم للعمل غير المتصل عبر تخزين محلي ومزامنة وحل تعارضات.
10. CI يتضمن حراس جودة مخصصة تعكس مخاطر النظام: SQL، GL، PII، cache keys، schema sync، invoice state، POS locks.
