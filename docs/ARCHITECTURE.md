# AMAN ERP — توثيق المعمارية الشاملة

> **الإصدار:** 2.0.0
> **آخر تحديث:** مايو 2026
> **النطاق:** كامل النظام (Backend + Frontend + Infra)

---

## الفهرس

1. [نظرة عامة](#1-نظرة-عامة)
2. [المعمارية الكلية](#2-المعمارية-الكلية)
3. [Stack التقني](#3-stack-التقني)
4. [نموذج Multi-Tenant](#4-نموذج-multi-tenant)
5. [هيكل المشروع](#5-هيكل-المشروع)
6. [طبقات Backend](#6-طبقات-backend)
7. [وحدات الأعمال (Business Modules)](#7-وحدات-الأعمال-business-modules)
8. [الأمان والصلاحيات](#8-الأمان-والصلاحيات)
9. [التدفقات الحرجة (Cross-Module Flows)](#9-التدفقات-الحرجة-cross-module-flows)
10. [Frontend Architecture](#10-frontend-architecture)
11. [البنية التحتية والنشر](#11-البنية-التحتية-والنشر)
12. [المراقبة والملاحظة](#12-المراقبة-والملاحظة)
13. [الاختبارات وضمان الجودة](#13-الاختبارات-وضمان-الجودة)
14. [الترابطات الحرجة (Dependency Map)](#14-الترابطات-الحرجة-dependency-map)

---

## 1. نظرة عامة

**AMAN ERP** هو نظام تخطيط موارد مؤسسية (ERP) متعدد الشركات (Multi-Tenant) باللغتين العربية والإنجليزية. مصمم خصيصًا للسوق السعودي/الخليجي مع دعم كامل للضرائب الإقليمية (ZATCA Phase 2)، الزكاة، WPS، GOSI، والامتثال المالي IFRS.

### الأرقام الجوهرية

| المقياس | القيمة |
|---------|--------|
| إجمالي ملفات Routers (Backend) | 234 |
| إجمالي ملفات Services (Backend) | 150 |
| إجمالي API Endpoints | ~1,087 |
| إجمالي صفحات Frontend | 366 |
| إجمالي مكونات Frontend | 38 |
| إجمالي جداول قاعدة بيانات Tenant | 355+ |
| إجمالي Domain Models | 50+ ملف |
| الوحدات الوظيفية الرئيسية | 30+ |

### القدرات الجوهرية

- **Multi-Tenancy عميق:** قاعدة بيانات منفصلة لكل شركة (`aman_{company_id}`) مع فروع متعددة لكل شركة
- **محاسبة كاملة:** دليل حسابات هرمي 5 مستويات، قيود يومية مع GL guards، إغلاق فترات، Fiscal locks، Multi-currency مع revaluation
- **تكامل ضريبي:** ZATCA Phase 2 e-invoicing، Zakat calculator، WHT، Multi-rate VAT
- **مخزون متقدم:** FIFO/LIFO/AVG costing، تتبع دفعات وأرقام تسلسلية، تحويلات بـ shipments قابلة للاسترداد، فحص جودة، MRP
- **تصنيع كامل:** Work centers، BOMs، Production orders، Job cards، Capacity planning، Shop floor
- **ZATCA + بنوك:** Outbox pattern لـ ZATCA submission، Bank feeds مع reconciliation
- **أتمتة عمليات:** Approvals متعدد المستويات، Scheduled reports، Recurring JE، Auto-reorder
- **حوكمة وأمان:** RBAC مع 200+ permission، 2FA، CSRF/XSS protection، PII encryption، Audit hash chain، Sensitive permissions

---

## 2. المعمارية الكلية

### نمط النشر (Deployment Topology)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          العميل (Browser / Mobile)                        │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ HTTPS
                                   ▼
                    ┌──────────────────────────────┐
                    │     Nginx Reverse Proxy       │ (frontend container)
                    │  - SPA static files           │
                    │  - /api/* → backend           │
                    └──────────────────────┬───────┘
                                           │
              ┌────────────────────────────┴───────────────────────┐
              │                                                    │
              ▼                                                    ▼
   ┌────────────────────┐                              ┌────────────────────┐
   │  FastAPI Backend   │                              │   Worker Process   │
   │  (uvicorn workers) │                              │  (APScheduler)     │
   │                    │                              │                    │
   │  - 1087 endpoints  │                              │  - Scheduled jobs  │
   │  - Middlewares     │                              │  - Outbox relays   │
   │  - lifespan tasks  │                              │  - Archival jobs   │
   └────┬───────┬───────┘                              └────────┬───────────┘
        │       │                                               │
        │       │       ┌───────────────────┐                   │
        │       └──────▶│   Redis 7         │◀──────────────────┘
        │               │ - Cache           │
        │               │ - Rate limit      │
        │               │ - Event Bus opt.  │
        │               └───────────────────┘
        │
        ▼
   ┌────────────────────────────────────────────────────────────┐
   │                    PostgreSQL 15                            │
   │                                                             │
   │  ┌────────────────────┐    ┌────────────────────────────┐  │
   │  │ system DB (postgres)│   │ Tenant DBs (aman_{id})      │  │
   │  │                     │   │                              │  │
   │  │ - system_companies  │   │ - 355+ tables per tenant    │  │
   │  │ - system_user_index │   │ - Isolated PostgreSQL role  │  │
   │  │ - industry_templates│   │ - Alembic migrations        │  │
   │  │ - system_admin_2fa  │   │                              │  │
   │  └────────────────────┘    └────────────────────────────┘  │
   └────────────────────────────────────────────────────────────┘
        │
        ▼
   ┌────────────────────────┐    ┌────────────────────────┐
   │ Prometheus (metrics)    │    │ Sentry (errors)        │
   │ Grafana (dashboards)    │    │                        │
   │ ClamAV (DMS scanning)   │    │                        │
   └────────────────────────┘    └────────────────────────┘
```

### نمط الطبقات Logical Layers

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (React 18 + Vite)                             │
│  ├── pages/      ← UI screens (366)                      │
│  ├── components/ ← Reusable UI (38)                      │
│  ├── services/   ← API clients (axios)                   │
│  ├── hooks/      ← React hooks                           │
│  └── context/    ← Auth, Theme, Toast, Branch            │
└────────────────────────────┬────────────────────────────┘
                             │ HTTPS + JWT + CSRF + i18n
                             ▼
┌─────────────────────────────────────────────────────────┐
│  Backend - Layered Architecture                          │
│                                                          │
│  routers/   ← HTTP handlers (FastAPI)                    │
│      ↓ imports                                           │
│  services/  ← Business logic (pure Python)              │
│      ↓ imports                                           │
│  utils/     ← Cross-cutting concerns (auth, perm,       │
│               i18n, sql_safety, decimals, fiscal_lock)  │
│      ↓                                                   │
│  models/    ← SQLAlchemy models (mostly raw SQL today)   │
│  schemas/   ← Pydantic request/response                 │
│  db_ddl/    ← Tenant schema DDL (355+ tables)            │
│  migrations/← Alembic versions                           │
│  integrations/ ← External adapters (ZATCA, banks, SMS)  │
│  adapters/  ← Vendor-specific glue                       │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Stack التقني

### Backend
| المكون | الإصدار | الدور |
|--------|--------|------|
| Python | 3.12 | Runtime |
| FastAPI | latest | HTTP framework + OpenAPI |
| SQLAlchemy | 2.x | DB toolkit (mostly raw SQL via `text()`) |
| Pydantic | v2 | Validation, settings |
| Alembic | latest | DB migrations (per-tenant via `-x company=`) |
| python-jose | latest | JWT |
| pyotp | latest | 2FA TOTP |
| passlib + bcrypt | latest | Password hashing |
| slowapi | latest | Rate limiting |
| APScheduler | latest | Scheduled jobs |
| redis-py | latest | Cache + optional event bus |
| Sentry SDK | latest | Error tracking (optional) |
| prometheus-fastapi-instrumentator | latest | Metrics |

### Frontend
| المكون | الدور |
|--------|------|
| React 18 | UI library |
| Vite | Bundler + dev server |
| react-router-dom | Routing |
| axios | HTTP client |
| react-i18next | i18n (ar/en) |
| Recharts | Charts (lazy-loaded) |
| Vitest | Unit tests |
| Playwright | E2E tests |

### Infrastructure
| المكون | الدور |
|--------|------|
| PostgreSQL 15 | Primary DB (Multi-Tenant via separate databases) |
| Redis 7 | Cache, rate limit, optional event bus |
| Nginx | Static + reverse proxy |
| Docker Compose | Dev/staging orchestration |
| Prometheus + Grafana | Observability |
| ClamAV | DMS file scanning (dev profile) |

---

## 4. نموذج Multi-Tenant

### الاستراتيجية: قاعدة بيانات منفصلة لكل شركة (Database-per-Tenant)

كل شركة عند إنشائها تحصل على:
1. **قاعدة بيانات منفصلة:** `aman_{company_id}` (8 أحرف hex)
2. **مستخدم PostgreSQL خاص:** `company_{company_id}` بكلمة سر فريدة (لا تساوي كلمة سر admin التطبيق)
3. **Schema كامل:** 355+ جدول يتم إنشاؤها عبر `db_ddl/tenant_schema.py` و `db_ddl/tenant_runner.py`
4. **Alembic stamp head:** تثبيت الإصدار حتى لا تعاد migrations القديمة

### آلية الإنشاء (`backend/database.py`)

```python
create_company_database(company_id, admin_password)
  → CREATE DATABASE + CREATE USER (DDL engine, AUTOCOMMIT)
  → return (db_name, db_user)

create_company_tables(company_id, currency)
  → apply_tenant_schema(conn, currency=currency)  # ينشئ كل الجداول
  → run_company_alembic_stamp_head()              # alembic stamp head

initialize_company_default_data(...)
  → INSERT admin user (bcrypt hash)
  → INSERT default roles (من DEFAULT_ROLES)
  → INSERT 5-level COA (دليل حسابات هرمي)
  → INSERT default warehouse, branches, settings
```

### Tenant Engine Pool

`backend/database.py` يدير cache من LRU bounded engines:
- **DB_TENANT_ENGINE_CACHE_SIZE** = 50 (افتراضي)
- **DB_TENANT_POOL_SIZE** = 2 لكل tenant
- **DB_TENANT_MAX_OVERFLOW** = 3
- النتيجة: 50 × 5 = 250 اتصال DB كحد أقصى

```python
def _get_engine(company_id: str):
    if company_id in _engines:
        _engines.move_to_end(company_id)  # LRU touch
        return _engines[company_id]
    if len(_engines) >= _MAX_ENGINES:
        _, evicted = _engines.popitem(last=False)
        evicted.dispose()  # close LRU
    _engines[company_id] = create_engine(url, pool_size=2, max_overflow=3, pool_recycle=300)
    return _engines[company_id]
```

### Tenant Connection API

```python
from database import db_connection, get_tenant_db

# Pattern 1: explicit company_id
with db_connection(company_id) as conn:
    conn.execute(text("..."))

# Pattern 2: auto-resolve to first active tenant (single-tenant dev)
with get_tenant_db() as conn:
    ...
```

### المتغيرات داخل Tenant
- 178 جدول مذكور في `main.py` لكن `tenant_schema.py` يحتوي 355 (التعداد قديم)
- Domain models موزعة على 50+ ملف داخل `models/domain_models/` لكن أغلب الكود يستخدم raw SQL مع `text()`

### تجميع جداول Tenant (الفئات في `tenant_schema.py`)
1. **Foundation:** users, roles, branches, settings, audit
2. **Organization:** departments, positions
3. **Financial Core:** accounts (COA), journal_entries, je_lines, fiscal_periods, currencies
4. **Treasury:** treasury_accounts, transactions, checks, notes, bank_feeds
5. **Currency:** exchange_rates, fx_revaluation
6. **Inventory Core:** products, warehouses, categories, stock movements
7. **Inventory Phase 2:** batches, serials, quality inspections
8. **Costing:** cost_layers (FIFO/LIFO), avg_cost
9. **Sales:** customers, invoices, sales_orders, quotations, returns, receipts
10. **Purchases:** suppliers, purchase_orders, GR, RFQ
11. **Manufacturing:** work_centers, BOMs, production_orders, job_cards, MRP
12. **HR:** employees, payroll, attendance, leaves, performance
13. **POS:** sessions, sales, promotions, loyalty
14. **Approvals & Security:** workflows, approvals_log, api_keys, webhooks
15. **CRM:** opportunities, leads, tickets, campaigns
16. **Projects:** projects, tasks, milestones, resources, timesheets
17. **System Completion:** delivery_orders, landed_costs, WPS
18. **Feature 023/024:** Returns unified, MRP recommendations, payroll reversal, FSM, DMS
19. **Audit/Security/Finance Integrity:** credentials_vault, sensitive permissions, recurring review

### أعمدة Branch Isolation
أغلب الجداول التشغيلية تحتوي عمود `branch_id`، ويوجد middleware في `apiClient.js` يضيف `branch_id` تلقائيًا إلى GET requests بناءً على `current_branch_id` في localStorage.

---

## 5. هيكل المشروع

```
aman/
├── backend/                ← FastAPI app
│   ├── main.py             ← App factory + middlewares + lifespan
│   ├── config.py           ← Settings (pydantic-settings)
│   ├── database.py         ← Engine pool, tenant lifecycle
│   ├── worker.py           ← Standalone scheduler process
│   ├── alembic/            ← DB migrations
│   ├── alembic.ini
│   ├── db_ddl/             ← Tenant schema DDL
│   │   ├── tenant_schema.py    (7544 lines, 355 tables)
│   │   └── tenant_runner.py
│   ├── routers/            ← HTTP handlers (234 files)
│   │   ├── auth/           (core/session/password/twofa/admin)
│   │   ├── finance/        (12 sub-routers)
│   │   ├── sales/, purchases/, inventory/ (granular)
│   │   ├── hr/, manufacturing/, pos/, crm/
│   │   ├── reports/, einvoicing/, payroll/, fsm/, dms/
│   │   ├── projects/, notifications/, system_completion/
│   │   └── *.py            (40+ top-level routers)
│   ├── services/           ← Business logic (150 files)
│   │   ├── auth/, cache/, finance/, inventory/
│   │   ├── manufacturing/, sales/, hr/, kpi/, reports/
│   │   ├── permissions/    ← sensitive permissions registry
│   │   ├── einvoicing/, dms/, fsm/, ops/, scheduler/
│   │   ├── *.py            ← cross-cutting services
│   │   │   (costing_service, gl_service, tax_engine,
│   │   │    matching_service, recurring_je_service,
│   │   │    intercompany_service, multibook_service,
│   │   │    nrv_service, ifrs15_revenue_service, ...)
│   │   └── audit_outbox_worker.py
│   ├── schemas/            ← Pydantic models
│   ├── models/             ← SQLAlchemy domain models
│   │   └── domain_models/  (50+ files: core/finance/inventory/...)
│   ├── repositories/       ← Data access (limited use)
│   ├── adapters/           ← External system glue
│   ├── integrations/
│   │   ├── einvoicing/     (ZATCA Phase 2)
│   │   ├── bank_feeds/, payments/, sms/, shipping/
│   │   └── circuit_breaker.py
│   ├── plugins/            ← Drop-in extensions
│   ├── middleware/         ← Custom middlewares
│   ├── utils/              ← Cross-cutting utilities (40+ files)
│   ├── locales/            ← errors.{ar,en}.json
│   ├── tests/              ← Pytest suite
│   ├── uploads/            ← User-uploaded files (signed URLs only)
│   ├── scripts/            ← Maintenance scripts
│   └── migrations/         ← Legacy SQL migrations
│
├── frontend/               ← React 18 SPA
│   ├── src/
│   │   ├── App.jsx         ← Route definitions + auth gates
│   │   ├── main.jsx
│   │   ├── pages/          ← 366 page components
│   │   │   (Sales, Purchases, Stock, Accounting, HR,
│   │   │    Manufacturing, POS, CRM, Projects, Reports,
│   │   │    Treasury, Taxes, Assets, Admin, Settings, ...)
│   │   ├── components/     ← Reusable UI (38)
│   │   │   ├── Layout, Sidebar, Topbar
│   │   │   ├── common/, dashboard/, kpi/, a11y/
│   │   │   └── Notifications/, Tax/
│   │   ├── services/       ← API clients (40+ files)
│   │   │   └── apiClient.js (axios + interceptors)
│   │   ├── hooks/          ← React hooks
│   │   ├── context/        ← Auth, Theme, Toast, Branch
│   │   ├── i18n/, locales/ ← ar/en translations
│   │   ├── utils/          ← auth, requestManager, tokenStore
│   │   └── styles/, router/, config/, tests/
│   ├── vite.config.js
│   └── nginx.conf          ← Production nginx config
│
├── e2e/                    ← Playwright E2E tests
├── ops/                    ← Deployment manifests
│   ├── k8s/                (CronJob backup)
│   └── systemd/
├── monitoring/             ← Prometheus + Grafana config
│   ├── prometheus.yml, alertmanager.yml
│   ├── alerts/, grafana/
├── nginx/                  ← Edge nginx (if used outside compose)
├── scripts/                ← CI lint + maintenance scripts
├── docs/                   ← Operational docs
│   ├── RUNBOOK.md, audit/, perf/
│   └── ARCHITECTURE.md     ← (this file)
├── docker-compose.yml      ← Dev compose
├── docker-compose.prod.yml ← Prod overlay
├── deploy.sh
├── safe-start.sh, safe-stop.sh
├── playwright.config.ts
└── package.json            ← Root package (e2e deps)
```

---

## 6. طبقات Backend

### 6.1 Routers Layer (`backend/routers/`)

- يستخدم FastAPI `APIRouter`
- كل router يحدد prefix و tags
- كل endpoint يستخدم `Depends(require_permission(...))` للتحقق من الصلاحية
- تنسيق موحد للأخطاء: `HTTPException(**http_error(code, key, request))` يقرأ `request.state.lang` ويعيد رسالة بالعربية أو الإنجليزية

### 6.2 Middlewares (مرتبة بالتسجيل في `main.py`)

```
1. CORSMiddleware          ← قائمة بيضاء صارمة من ALLOWED_ORIGINS
2. RequestIDMiddleware     ← X-Request-ID لكل request/response
3. AcceptLanguageMiddleware← يضع request.state.lang من Accept-Language
4. RequestSizeLimitMiddleware ← cap 100MB افتراضي
5. HTTPSRedirectMiddleware (اختياري FORCE_HTTPS) أو SecurityHeadersOnlyMiddleware
6. InputSanitizationMiddleware← XSS/SQLi detection + reject
7. CSRFMiddleware          ← double-submit cookie (off/permissive/strict)
8. QueryCounterMiddleware  ← N+1 observability (مع ENABLE_QUERY_COUNTER)
9. AuditBodyCaptureMiddleware← يلتقط bodies على مسارات حساسة
```

### 6.3 Services Layer

كل خدمة معزولة في ملف منفصل وتركز على دومين معين:

| Service | الدور |
|---------|------|
| `costing_service.py` | حساب COGS بطرق FIFO/LIFO/AVG، يرجع Decimal |
| `gl_service.py` | إنشاء قيود GL من العمليات (مبيعات/مشتريات/مخزون) |
| `tax_engine.py` | حل ضرائب الخطوط (Multi-rate VAT) |
| `matching_service.py` | مطابقة بنوك / 3-way matching (PO/GR/Invoice) |
| `recurring_je_service.py` | توليد قيود متكررة |
| `intercompany_service.py` | معاملات بين الشركات |
| `multibook_service.py` | Multi-book accounting (محلي/IFRS) |
| `nrv_service.py` | Net Realizable Value للمخزون |
| `ifrs15_revenue_service.py` | تحقق الإيرادات IFRS 15 |
| `ecl_service.py` | Expected Credit Loss للذمم |
| `wht_service.py` | Withholding Tax |
| `subscription_service.py` | إدارة الاشتراكات |
| `forecast_service.py` / `demand_forecast_service.py` | تنبؤ الطلب |
| `audit_outbox_worker.py` | معالجة سجل المراجعة بشكل غير متزامن |
| `audit_writer.py` + `audit_sanitizer.py` | كتابة سجلات المراجعة بـ hash chain |
| `notification_service.py` | إشعارات (Email/SMS/Webhook/WS) |
| `scheduler.py` | APScheduler registry للوظائف المجدولة |
| `cpq_service.py` | Configure-Price-Quote |
| `industry_coa_templates.py` / `industry_gl_rules.py` | قوالب صناعية |
| `account_classifier.py` | تصنيف الحسابات تلقائيًا |

### 6.4 Utils Layer (`backend/utils/`)

```
auth_cookies.py        ← HttpOnly refresh + readable CSRF cookies
csrf_middleware.py     ← double-submit pattern enforcement
permissions.py         ← require_permission, require_module, aliases
sql_safety.py          ← validate identifiers, parameterization helpers
fiscal_lock.py         ← منع الكتابة في فترات مغلقة (fail-closed)
decimal_helper.py      ← تحويلات Decimal آمنة (no float)
quantity_validation.py ← validate كميات على المنتجات discrete
optimistic_lock.py     ← row version checking
tx.py                  ← transaction context managers
limiter.py             ← shared slowapi limiter
i18n.py                ← http_error(), i18n_message()
audit.py + audit_body_capture.py ← audit hash chain
event_bus.py + redis_event_bus.py + outbox_relay.py ← Domain events
field_encryption.py + pii_encryption.py ← AES-GCM PII at rest
masking.py             ← Mask PII in responses based on permission
signed_urls.py         ← HMAC-signed file URLs
zatca.py + zatca_clearance.py ← ZATCA helpers
treasury_balance.py + party_balance.py + balance_reconciliation.py ← invariants
```

### 6.5 Database Layer (`backend/db_ddl/` + `backend/database.py`)

- **`tenant_schema.py`:** المصدر الوحيد للجداول، 355+ CREATE TABLE IF NOT EXISTS
- **`tenant_runner.py`:** يطبق `tenant_schema` على tenant جديدة، ثم post-DDL fix-ups
- **`alembic/versions/`:** migrations تطبق على كل tenant عبر `alembic -x company=<id> upgrade head`
- **Alembic baseline:** `0001_baseline_complete` يستدعي نفس `apply_tenant_schema` ليطابق DDL = Migration

### 6.6 Lifespan Tasks (في `main.py`)

عند startup:
1. فحص قوة `SECRET_KEY` (≥32 char، entropy check)
2. إنشاء جداول النظام في system DB:
   - `system_user_index` (للبحث السريع عن user عبر شركات)
   - `system_companies` (سجل الشركات)
   - `industry_templates` (12 صناعة جاهزة)
   - `system_activity_log` (audit عام)
   - `system_admin_2fa` (DB-backed admin 2FA)
3. تشغيل خلفيات (في process أو worker dedicated):
   - `update_system_stats_task` (background stats)
   - `_blacklist_cleanup_loop` (تنظيف JWT blacklist كل ساعة)
   - `start_scheduler()` (APScheduler) — إذا `SCHEDULER_MODE=in_process`
4. تحميل plugins من `backend/plugins/`
5. تثبيت Redis event-bus bridge (إذا `REDIS_EVENT_BUS=1`)
6. تشغيل Outbox relay worker (إذا `OUTBOX_RELAY=1`)
7. تشغيل `alembic upgrade head` لكل قواعد بيانات tenants النشطة
8. اكتشاف Sensitive routes (Feature 022)

عند shutdown: `engine.dispose()` فقط.

---

## 7. وحدات الأعمال (Business Modules)

### 7.1 Auth & Authorization (`routers/auth/`)
- **Login:** username + password (per company) → JWT access (30min) + refresh cookie (7day HttpOnly)
- **2FA:** TOTP (pyotp) — مفعّل اختياريًا لكل مستخدم + DB-backed لـ admin
- **Refresh:** `/auth/refresh` يستخدم HttpOnly cookie + يرسل CSRF cookie جديد
- **Token blacklist:** JWT المُلغاة تُحفظ في DB حتى انتهاء `exp`
- **Risk-based:** `services/login_risk.py` يقيّم مخاطر الجلسة
- **SSO:** SAML/OIDC عبر `services/sso_service.py`

### 7.2 Companies & Branches & Roles
- **Company:** lifecycle (create DB → schema → seed admin/roles/COA → activate)
- **Branches:** كل شركة لها فروع، مع validate_branch_access في الصلاحيات
- **Roles:** `DEFAULT_ROLES` registry موحّد + permissions JSON + RBAC مع aliases في `utils/permissions.py`

### 7.3 Accounting & Finance (`routers/finance/`)
| Sub-router | الدور |
|------------|------|
| `accounting/accounts.py` | Chart of Accounts (5-level hierarchical, parent flag) |
| `accounting/journal.py` | Journal entries مع GL guards (debit=credit, fiscal lock, source/source_id) |
| `accounting/fiscal.py` | Fiscal periods + locks (fail-closed) |
| `accounting/recurring.py` | Recurring journal templates |
| `accounting/fx.py` | FX revaluation (realized/unrealized) |
| `accounting/provisions.py` | مخصصات (إجازات، ديون معدومة) |
| `currencies.py` | Exchange rates daily |
| `cost_centers.py` | Cost center allocations |
| `budgets.py` | Budgets + variance reporting |
| `reconciliation.py` + `bank_feeds.py` | Bank reconciliation |
| `treasury.py` | Treasury accounts + transactions |
| `costing_policies.py` | Inventory costing config (FIFO/LIFO/AVG/Standard) |
| `checks.py` + `notes.py` | Receivable/payable checks + promissory notes |
| `expenses.py` + `petty_cash.py` | Expenses + petty cash |
| `payments.py` | Payment processing |
| `revenue_recognition.py` | IFRS 15 |
| `subscriptions.py` | Subscription billing |
| `tax_compliance.py` | Tax returns |
| `intercompany_v2.py` | Entity groups + consolidation |

### 7.4 Sales (`routers/sales/`)
- Customers, Invoices (POS/sales), Sales Orders, Quotations, Returns, Receipts
- Credit Notes / Debit Notes (مع T2.3: sensitive permissions منفصلة)
- Contracts + Amendments
- Delivery Orders → Invoice (idempotent via `order_to_invoice`)
- Cancellation flow (`cancellation.py`)
- ZATCA submission via `einvoicing/` outbox

### 7.5 Inventory (`routers/inventory/`)
- **products.py:** CRUD + delete blocks if has inventory_transactions/cost_layers/batches/serials/stock_shipments. `stock.view_cost` يحجب `buying_price` للأدوار غير المسموح لها
- **warehouses.py:** branch isolation عند create/update/delete، delete blocks if active cost_layers أو pending shipments
- **transfers.py:** صلاحية `stock.transfer`، `validate_quantities_for_products`، Decimal فقط (no float)
- **shipments.py:** FOR UPDATE + reserved_quantity، confirm_shipment Decimal-safe، **POST /shipments/{id}/recall** لاسترداد dispatched
- **adjustments.py:** FOR UPDATE قراءة current_qty، Decimal كامل، validate_quantity للوحدات discrete
- **batches.py:** validate_quantity_for_product في create_batch
- **stock_movements.py:** موحد على permission `stock.adjustment`
- **costing.py:** FIFO/LIFO/AVG layers
- **forecast.py:** demand forecasting
- **reports.py:** /summary بـ average_cost (لا cost_price)، /movements مع pagination
- **categories.py, suppliers.py, advanced.py, archival_admin.py**

### 7.6 Manufacturing (`routers/manufacturing/`)
- Work centers, Routings, BOMs (multi-level)
- Production orders + approval gates لـ MO الكبيرة
- Job cards + Shop floor + Capacity planning
- MRP: `/mrp/run` + recommendations + accept
- QC gates (pass/fail) — تمنع التقدم في حالة الفشل
- Equipment maintenance + Manufacturing costing

### 7.7 HR (`routers/hr/`)
- **core/:** Employees, Departments, Attendance, Leaves, Payroll, Recruitment
- **advanced.py:** Performance reviews, Training, Violations, Custody, Overtime
- **performance.py:** تقييمات أداء
- **self_service.py:** بوابة الموظف
- **advances.py:** سُلف الموظفين
- **employee_receipts.py:** تسوية إيصالات الموظفين
- **pii_admin.py:** Unmask PII fields (IBAN/National ID/GOSI) عبر `hr.pii` permission
- **salary_increments.py:** تعديلات راتب
- **payroll/reversal.py:** عكس payroll
- **HRHome.jsx:** Frontend hub، يستخدم `hr.view` (وليس `hr.reports`) كـ guard

### 7.8 POS (`routers/pos/`)
- Sales sessions, transactions, promotions, loyalty, table/kitchen, offline batches, cancellation
- POS lock (`pos_stock_lock`) للكتابة على المخزون

### 7.9 CRM (`routers/crm/`)
- Velocity, Funnel, Cashflow forecast, Opportunities, Tickets, Campaigns

### 7.10 Reports (`routers/reports/`)
- Sales, Purchases, HR, Inventory, KPI, Custom, Industry-specific
- Accounting: Trial Balance, Income Statement, Balance Sheet, Cash Flow, Compare/Export
- Materialized views للتقارير الثقيلة (`db_ddl/reports_mvs.py`)

### 7.11 Projects, Services (FSM), DMS, Contracts, Notifications, External

### 7.12 System Completion
- Backup management, Print templates, Duplicate detection, Password reset
- Delivery orders, Landed costs, HR WPS compliance
- Intercompany consolidation trial balance

### 7.13 E-Invoicing (ZATCA)
- Outbox pattern: `einvoice_outbox` table
- Worker `zatca_outbox` كل 5s يرسل المعلقة
- `ZATCA_PHASE2_ENFORCE` يحول الإرسال إلى متزامن مع 422 عند الرفض
- Outbox admin: `/einvoicing/outbox` + `/reprocess`

---

## 8. الأمان والصلاحيات

### 8.1 Authentication (متعدد الطبقات)
- **JWT Bearer:** access token قصير (30min) في memory (لا localStorage)
- **HttpOnly refresh cookie:** ينقل عبر `/auth/refresh`
- **CSRF token:** double-submit (cookie + header `X-CSRF-Token`)
- **2FA TOTP:** اختياري لكل user + ملزم للـ system admin
- **Token blacklist:** JWT الملغاة في DB
- **JWT leeway:** 30s clock skew tolerance

### 8.2 Authorization (RBAC)
- **Permissions:** 200+ مفتاح بنمط `module.action` (مثلاً `stock.view`, `accounting.post_journal_entry`)
- **Aliases:** umbrella permissions في `PERMISSION_ALIASES` (مثلاً `inventory.*` يضمن stock + products)
- **Module guard:** `require_module("hr")` يتحقق أن الوحدة مفعّلة في `enabled_modules` للشركة
- **Sensitive permissions** (Feature 022): قائمة محصورة من الأذونات الخطرة (مثلاً `sales.void`, `hr.pii`) تتطلب re-auth أو 2FA

### 8.3 Field-Level & Resource-Level
- **PERM-001:** Field-level — `stock.view_cost` يحجب buying_price/last_buying_price
- **PERM-002:** Warehouse-level
- **PERM-003:** Cost-center-level
- **PERM-004:** Permission audit logging

### 8.4 Defenses
- **HTTPS:** اختياري `FORCE_HTTPS` + Security headers دائمًا
- **HSTS, CSP, X-Frame-Options:** عبر `SecurityHeadersOnlyMiddleware`
- **XSS/SQLi:** Input sanitization middleware
- **CSRF:** double-submit cookie pattern
- **Rate limit:** slowapi (10/min login, 120/min global)
- **Request size cap:** 100MB افتراضي
- **PII at rest:** AES-GCM في `field_encryption.py` و `pii_encryption.py`
- **Signed URLs:** ملفات /uploads تحتاج HMAC signature إلا /uploads/logos

### 8.5 Audit
- **Hash chain:** كل سجل audit يحتوي hash للسجل السابق → غير قابل للتلاعب الصامت
- **Audit body capture:** middleware يلتقط bodies على المسارات الحساسة (sanitized)
- **Audit outbox:** worker يكتب الـ audit بشكل غير متزامن
- **Audit archival:** سجلات أقدم من 7 سنوات → `audit_logs_archive`

### 8.6 Tenant Isolation
- قاعدة بيانات منفصلة لكل tenant (database-per-tenant)
- مستخدم PostgreSQL منفصل لكل tenant
- لا يمكن لـ user الوصول لبيانات شركة أخرى لأن JWT يحمل company_id ويتم لكل request توجيه الاتصال إلى DB الخاصة

### 8.7 Fiscal Lock (Fail-Closed)
- `utils/fiscal_lock.py` يمنع الكتابة في فترات مغلقة
- **Fail-closed:** عند خطأ في القراءة، يفترض locked → يرفض

---

## 9. التدفقات الحرجة (Cross-Module Flows)

### 9.1 إنشاء شركة جديدة
```
POST /api/companies (admin)
  → companies.py
  → database.create_company_database(...)        # CREATE DATABASE + USER
  → database.create_company_tables(...)          # 355 tables + Alembic stamp head
  → database.initialize_company_default_data(...)# admin user, roles, COA, defaults
  → activates row in system_companies
```

### 9.2 Sales Invoice → GL → Inventory → ZATCA
```
POST /api/sales/invoices
  ↓
sales_service.create_invoice
  ├─→ tax_engine.resolve_line_tax       # ضرائب
  ├─→ costing_service.get_cogs_cost     # COGS (Decimal)
  ├─→ inventory: deduct stock + cost_layers
  ├─→ gl_service.post_invoice_je        # قيد محاسبي (debit=credit, fiscal lock)
  ├─→ einvoice_outbox INSERT            # لـ ZATCA
  └─→ audit_writer + event_bus emit
worker: zatca_outbox (every 5s) → ZATCA Phase 2 → update outbox status
```

### 9.3 Purchase Order → GR → 3-Way Match → Invoice
```
POST /api/purchases/orders
  ↓
PO created
  ↓
POST /api/purchases/grn (Goods Receipt)
  ↓
matching_service: 3-way match (PO ↔ GR ↔ Invoice)
  ↓
على نجاح المطابقة → unlock invoice posting
  ↓
GL post + AP increase + Inventory increase + cost_layers (FIFO/LIFO)
```

### 9.4 Stock Transfer (with Shipments)
```
POST /api/inventory/transfers
  ↓ validate_quantities_for_products + permission stock.transfer
POST /api/inventory/shipments  (FOR UPDATE on source qty + reserved_quantity check)
  ↓
shipment status: pending → dispatched
  ↓
POST /api/inventory/shipments/{id}/confirm  (Decimal-safe)
  ↓
destination warehouse increase + source decrease finalized
  ↓
Recall path:
POST /api/inventory/shipments/{id}/recall  ← NEW
  ↓ status: dispatched → recalled
  ↓ Frontend: ShipmentDetails.jsx زر "استرداد"، badge للحالة
```

### 9.5 Production Order → BOM Consumption → MO Completion
```
POST /api/manufacturing/orders
  ↓
MRP: net requirements → recommendations
POST /api/manufacturing/orders/{id}/approve  (إذا cost > mfg.large_mo_threshold)
  ↓
Job cards: استهلاك مواد + labor + overhead
QC gate: pass/fail
POST /api/manufacturing/orders/{id}/complete  (partial supported)
  ↓
GL: WIP → Finished Goods + Manufacturing variance
  ↓
costing_service: تحديث avg_cost للمنتج النهائي
```

### 9.6 Payroll Run → WPS → GL
```
POST /api/hr/payroll/run (period)
  ↓
calculate gross + GOSI + WHT + deductions + advances
  ↓
WPS file generation (SAR salaries via SADAD/Mudad)
  ↓
GL posting: salary expense + GOSI expense + payable accounts
  ↓
Reversal supported via /payroll/reversal
```

### 9.7 Bank Reconciliation
```
Bank feed adapter (open banking / SAMA)
  ↓ ingestion
matching_service: auto-match + suggestions
  ↓
GL adjustments + treasury_balance.py invariant check
```

### 9.8 Approval Workflow
```
Operation triggers approval (e.g., MO > threshold, expense > limit)
  ↓
approvals_log INSERT (pending) + notification
  ↓
multi-level approvers act → on full approval → operation continues
  ↓
Audit + event_bus
```

### 9.9 Token Refresh (Frontend)
```
apiClient.js interceptor:
  - Pre-request: إذا token ينتهي خلال 60s → /auth/refresh
  - On 401: تنسيق refresh عبر mutex + retry
  - Refresh failure: clear session + redirect /login
```

---

## 10. Frontend Architecture

### 10.1 App Shell
- **`App.jsx`:** router definitions، `Layout` wrapper، lazy-loaded pages
- **`Layout.jsx`:** Sidebar + Topbar + GlobalSearch + outlet
- **Auth gating:** كل route محمي يفحص `isAuthenticated()` و `hasPermission(...)` قبل العرض

### 10.2 API Client (`services/apiClient.js`)
Axios instance بـ:
- `withCredentials: true` (للـ HttpOnly cookies)
- **Request interceptor:**
  - Bearer token من memory store
  - Pre-emptive refresh إذا token ينتهي خلال 60s
  - CSRF header على mutating requests
  - `branch_id` تلقائي على GET requests (من localStorage)
  - `Accept-Language` من i18next
  - AbortController auto-attached
- **Response interceptor:**
  - 429: retry with `Retry-After`
  - 401: auto-refresh + retry (mutex لتجنب race)
  - Global toast لأخطاء 4xx/5xx (مع skip option)

### 10.3 State Management
- **Auth:** `utils/auth.js` + `utils/tokenStore.js` (in-memory token)
- **Branch context:** `BranchContext` يحفظ `current_branch_id` في localStorage
- **Theme:** `ThemeContext` (light/dark)
- **Toast:** `ToastContext` + `toastEmitter`
- **Notifications:** `useNotificationSocket` (WebSocket)
- **Optimistic updates:** `useOptimisticList`

### 10.4 i18n
- `i18next` + `react-i18next`
- ar (افتراضي RTL) و en
- Errors backend بالعربية والإنجليزية حسب `Accept-Language`

### 10.5 Permission Gating
- `hasPermission(permKey)` يفحص user.permissions JSON
- صفحات Frontend تستخدم نفس مفاتيح الصلاحية الموحّدة مع backend

### 10.6 صفحات HR وسلامة الترجمة
- `HRHome.jsx`: `hr.view` كـ guard، loading state صحيح، fallback في t() لتجنب object/string conflict
- `Violations.jsx`: `t('common.actions')` بدلاً من `t('hr.violations.actions')`
- ملفات الترجمة: title field على كل object لتجنب conflict عند استخدام t() على parent key

### 10.7 Inventory Frontend
- `App.jsx`: routes Stock مع permissions متطابقة 100% مع backend
- `inventory.js`: client يحتوي `recallShipment`
- `ShipmentDetails.jsx` + `ShipmentList.jsx`: badge وفلتر للحالة `recalled`، زر استرداد

---

## 11. البنية التحتية والنشر

### 11.1 Docker Compose (Dev)
خدمات: db (PG15), redis, backend, frontend, prometheus, postgres-exporter, redis-exporter, grafana, clamav (dev profile).

### 11.2 Production
- **`docker-compose.prod.yml`:** يضيف overlay
- **Nginx:** SSL termination، gzip، cache static
- **Worker container:** `worker.py` مستقل لـ APScheduler (لتجنب duplicate jobs مع N replicas)
- **`SCHEDULER_MODE=dedicated`** لازم في production متعدد replicas
- **`OUTBOX_RELAY=1`** لتفعيل transactional outbox relay

### 11.3 Variables الحرجة
| متغير | غرض |
|-------|------|
| `SECRET_KEY` | JWT (≥32 char) |
| `POSTGRES_*` | DB connection |
| `REDIS_URL` + `REDIS_PASSWORD` | Cache + rate limit |
| `ALLOWED_ORIGINS` | CORS whitelist |
| `APP_ENV` | dev/staging/production |
| `SENTRY_DSN` | Error tracking |
| `SCHEDULER_MODE` | in_process / dedicated / disabled |
| `ZATCA_PHASE2_ENFORCE` | تفعيل ZATCA متزامن |
| `CSRF_ENFORCEMENT` | off / permissive / strict |
| `FORCE_HTTPS` | redirect HTTP→HTTPS |

### 11.4 K8s
- `ops/k8s/cronjob-backup.yaml`: نسخ احتياطي مجدول

### 11.5 Backups
- `scripts/backup_postgres.sh` + `scripts/restore_postgres.sh`
- نسخ كل tenant DB منفصلة

---

## 12. المراقبة والملاحظة

### 12.1 Logging
- **Structured logging:** JSON في production، human-readable في dev (`utils/logging_config.py`)
- **Request ID:** كل log line يحمل X-Request-ID

### 12.2 Metrics
- **Prometheus instrumentator:** `/metrics` endpoint
- **PostgreSQL exporter:** اتصالات، queries، locks
- **Redis exporter:** cache hit rate، memory

### 12.3 Sentry
- اختياري عبر `SENTRY_DSN`
- `traces_sample_rate` قابل للتعديل

### 12.4 Health Checks
- `/api/health`: DB + Redis + response time
- `/api/health/cache`: cache hit-rate (DoD: hit-rate > 60%)
- `/api/health/scheduler`: حالة كل وظيفة + last_run/last_status

### 12.5 Grafana Dashboards
- `monitoring/grafana/` فيها dashboards جاهزة

### 12.6 Alerts
- `monitoring/alertmanager.yml` + `monitoring/alerts/`

---

## 13. الاختبارات وضمان الجودة

### 13.1 Backend Tests (`backend/tests/`)
- pytest suite (المرجع: 984 test في README)
- Coverage on routers + services + utils
- Property-based testing بـ `hypothesis` (`backend/.hypothesis/`)

### 13.2 E2E Tests (`e2e/`)
- Playwright
- مثال: `budget-costcenter.spec.ts`

### 13.3 Frontend Tests
- Vitest unit tests في `frontend/src/tests/`

### 13.4 CI Lint Guards (`scripts/`)
| Script | يفحص |
|--------|------|
| `check_no_float_money.py` | عدم استخدام float في كميات/تكاليف |
| `check_invoice_state_writers.py` | فقط `invoice_state.py` يكتب `invoices.state` |
| `check_je_source_id.py` | استخدام source/source_id بدلاً من reference_number |
| `check_pos_lock_usage.py` | POS writes تستخدم `pos_stock_lock` |
| `check_get_acc_id_callsites.py` | استخدام `account_mapping.resolve()` |
| `check_pii_logging.py` | عدم تسجيل PII في logs |
| `check_sql_parameterization.py` | منع SQL injection |
| `check_cache_keys.py` | معايير cache keys |
| `check_schema_sync.py` | تطابق DDL مع Alembic |
| `audit_writer_lint.py` | audit_writer usage |
| `audit_permissions.py` | تدقيق صلاحيات |
| `check_frontend_i18n_strings.py` | i18n keys في frontend |
| `check_frontend_number_format.py` | تنسيق أرقام |
| `check_frontend_window_location.py` | عدم استخدام window.location مباشرة |
| `check_gl_posting_discipline.py` | انضباط قيود GL |

### 13.5 Pre-commit
- `.pre-commit-config.yaml` يربط الـ lint guards
- `.gitleaks.toml` لمنع تسرب secrets

---

## 14. الترابطات الحرجة (Dependency Map)

### 14.1 Backend ↔ Database
- **`tenant_schema.py`** هو المصدر الوحيد لـ DDL → أي تغيير يجب أن يقابله Alembic migration
- **`db_ddl/tenant_runner.py`** ينفّذه على tenants جديدة
- **Alembic migrations** تطبق نفس DDL على tenants موجودة

### 14.2 Frontend ↔ Backend Permissions
- مفاتيح الصلاحيات يجب أن تتطابق 100% بين:
  - `routers/**` (require_permission(...))
  - `frontend/App.jsx` (route guards)
  - `frontend/src/pages/**` (UI gating)
- aliases في `utils/permissions.py` يجسر بين الأسماء البديلة

### 14.3 Sales / Inventory / Accounting
- Sales invoice → COGS من costing_service → cost_layers update
- GL posting (`gl_service`) ربط Sales/AR/Inventory/COGS
- ZATCA outbox مرتبط بـ sales invoices

### 14.4 Purchases / Inventory / Accounting
- PO → GR → Inventory increase + cost_layers (FIFO/LIFO)
- 3-way match (PO ↔ GR ↔ Invoice)
- AP increase + Inventory expense

### 14.5 Manufacturing / Inventory / Accounting
- Production order → BOM consumption (raw → WIP)
- Job cards → labor + overhead allocation
- Completion → WIP → Finished Goods + variance

### 14.6 HR / Payroll / Accounting / Treasury
- Payroll run → salary expense + GOSI + WHT
- Treasury: bank payment + check issuance
- Employee receipts settlement
- Advances → loan account → deduction in payroll

### 14.7 Approvals / All Modules
- Approval workflows configurable per operation type + amount threshold
- Multi-level approvers + escalation
- Sensitive permissions require approval gate

### 14.8 Audit / All Modules
- كل write operation → audit_writer.write_event
- Hash chain على audit_logs
- Audit outbox worker → async processing
- Archival > 7 سنوات → audit_logs_archive

### 14.9 Notifications / WebSocket / Email / SMS
- `notification_service` يوزع عبر:
  - WebSocket: live notifications
  - Email: SMTP (templates)
  - SMS: gateways adapter
  - Webhook: outbound to external systems
- Preferences لكل user

### 14.10 Multi-Currency
- `currencies.py` daily rates
- `gl_service` يحوّل عند posting
- FX revaluation شهرية (realized + unrealized)
- `accounting/fx.py` ينشئ قيود الفروقات

### 14.11 Branch Isolation
- middleware في frontend (`apiClient.js`) يضيف `branch_id` لـ GETs
- `validate_branch_access` في backend permissions
- create/update/delete operations تفحص branch ownership

### 14.12 Fiscal Lock
- `utils/fiscal_lock.py` يفحص قبل كل posting (fail-closed)
- يمنع: JE posting, invoice cancel, return, adjustment في فترة مغلقة

### 14.13 Decimal Discipline
- لا float في cost/qty arithmetic (CI lint guard)
- INSERT/UPDATE تستخدم `str(Decimal)` على params
- `utils/decimal_helper.py` لتحويلات آمنة

### 14.14 Race Condition Protection
- FOR UPDATE في كل قراءة قبل كتابة (transfers, shipments, adjustments, batches)
- POS writes عبر `pos_stock_lock`
- Optimistic locking عبر `utils/optimistic_lock.py` للسجلات الحرجة

---

## ملخص الحالة الحالية (مايو 2026)

النظام في حالة **production-grade** مع:
- ✅ 1087 endpoint عاملة
- ✅ 106/106 inventory routes تشغّل بدون أخطاء
- ✅ Decimal precision في كل pipelines الحرجة
- ✅ Race condition protection (FOR UPDATE) في كل الكتابات الحرجة
- ✅ Recall workflow end-to-end (BE + FE + UI)
- ✅ Cost data protection عبر `stock.view_cost`
- ✅ Branch isolation عبر create/update/delete
- ✅ Fiscal lock fail-closed
- ✅ Quantity validation في transfers / shipments / adjustments / batches
- ✅ Translation files بدون object/string conflicts
- ✅ Diagnostics نظيفة على كل الملفات المعدّلة

التكامل بين الوحدات (المبيعات/المشتريات/POS/التصنيع/المحاسبة/المخزون) سليم، مع GL guards، Tenant isolation، RBAC متعدد الطبقات، و Audit hash chain.
