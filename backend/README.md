# Backend — AMAN ERP

FastAPI-based backend for the AMAN ERP system.

## التقنيات

- **Framework:** FastAPI (Python 3.12)
- **ORM:** SQLAlchemy (raw SQL + connection pooling)
- **Database:** PostgreSQL (Multi-Tenant: `aman_{company_id}`)
- **Auth:** JWT (python-jose) + 2FA (pyotp)
- **Server:** Uvicorn with `websockets` support
- **Rate Limiting:** slowapi (10/min login, 120/min global)

## 📁 

```
backend/
├── main.py                  ← FastAPI app, middleware, router registration
├── database.py              ← SQLAlchemy engine, 178+ table definitions
├── config.py                ← Settings from .env (pydantic-settings)
├── requirements.txt         ← Python dependencies
├── start.sh / stop.sh       ← Server management scripts
│
├── routers/                 ← API endpoint handlers
│   ├── auth.py              ← Login, JWT, 2FA, session management
│   ├── companies.py         ← Company CRUD, DB initialization
│   ├── roles.py             ← RBAC roles & permissions
│   ├── branches.py          ← Branch management
│   ├── settings.py          ← Company settings
│   ├── notifications.py     ← HTTP + WebSocket notifications
│   ├── approvals.py         ← Multi-level approval workflows
│   ├── audit.py             ← Audit log
│   ├── security.py          ← API keys, Webhooks
│   ├── data_import.py       ← Excel/CSV import
│   ├── dashboard.py         ← Dashboard stats & charts
│   ├── reports.py           ← Financial reports
│   ├── scheduled_reports.py ← Automated report scheduling
│   ├── purchases.py         ← Purchase orders, supplier payments
│   ├── parties.py           ← Unified customers/suppliers
│   ├── projects.py          ← Project management
│   ├── pos.py               ← Point of Sale
│   ├── contracts.py         ← Contract management
│   ├── crm.py               ← CRM - opportunities & tickets
│   ├── external.py          ← External integrations
│   │
│   ├── finance/             ← 12 financial routers
│   │   ├── accounting.py    ← Chart of accounts, journal entries
│   │   ├── currencies.py    ← Exchange rates
│   │   ├── cost_centers.py  ← Cost center management
│   │   ├── budgets.py       ← Budget planning & tracking
│   │   ├── reconciliation.py ← Bank reconciliation
│   │   ├── treasury.py      ← Treasury accounts & transactions
│   │   ├── taxes.py         ← Tax rates & returns
│   │   ├── costing_policies.py ← Inventory costing (FIFO/LIFO/AVG)
│   │   ├── checks.py        ← Receivable/payable checks
│   │   ├── notes.py         ← Promissory notes
│   │   ├── assets.py        ← Fixed assets & depreciation
│   │   └── expenses.py      ← Expense claims
│   │
│   ├── hr/                  ← Human Resources
│   │   ├── core.py          ← Employees, payroll, attendance, leaves
│   │   └── advanced.py      ← Performance, training, recruitment
│   │
│   ├── manufacturing/       ← Production
│   │   └── core.py          ← Work centers, BOMs, production orders
│   │
│   ├── inventory/           ← 14 inventory routers
│   │   ├── products.py, categories.py, warehouses.py, ...
│   │   └── advanced.py      ← Batches, serials, quality
│   │
│   └── sales/               ← 9 sales routers
│       ├── customers.py, invoices.py, orders.py, quotations.py, ...
│       └── credit_notes.py
│
├── schemas/                 ← Pydantic request/response models
├── services/                ← Business logic layer
├── utils/                   ← Shared utilities
│   ├── limiter.py           ← Rate limiter (slowapi shared instance)
│   ├── permissions.py       ← Permission decorators
│   └── security_middleware.py ← CSP, HSTS, input sanitization
├── migrations/              ← Database migration scripts
└── tests/                   ← 984 pytest tests
```

## التشغيل

```bash
# بيئة التطوير
bash start.sh

# أو يدوياً
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# الاختبارات
python3 -m pytest tests/ -q

# إيقاف
bash stop.sh
```

## Environment Variables

| المتغير | الوصف | القيمة الافتراضية |
|---------|-------|------------------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` |
| `SECRET_KEY` | JWT signing key (32+ chars) | مطلوب |
| `FRONTEND_URL` | Frontend URL for CORS | `http://localhost:5173` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | فارغ (يستخدم FRONTEND_URL) |

## API Documentation

- **Swagger UI:** http://localhost:8000/api/docs
- **ReDoc:** http://localhost:8000/api/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

## Worker / Scheduler (T9.5)

A dedicated worker process runs APScheduler jobs (audit/inventory archival,
ZATCA reporting, recurring invoices, bank feed sync). It must NOT run inside
uvicorn workers (would cause duplicate job execution).

```bash
# In production (docker compose)
docker compose -f docker-compose.prod.yml up -d worker

# Locally
SCHEDULER_MODE=dedicated python -m worker
```

Job registry: `backend/services/scheduler.py::start_scheduler`. See
`docs/RUNBOOK.md` → "Scheduler / Worker Process" for the full job schedule.

## Internationalization (T9.4)

Backend errors are bilingual (Arabic / English) via
`backend/locales/errors.{ar,en}.json`. Routers use:

```python
from utils.i18n import http_error
raise HTTPException(**http_error(404, "record_not_found", lang=request.state.lang))
```

`AcceptLanguageMiddleware` (in `main.py`) reads the `Accept-Language` header
that the frontend's `apiClient.js` sets automatically.

## Recently Added Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/search` | Unified search (products/customers/suppliers/invoices) |
| `GET /api/currencies/current` | Today's FX rate |
| `POST /api/hr/overtime-rates-config` | Configure overtime multipliers |
| `GET /api/parties/duplicates-by-phone` | Duplicate detection |

## Archive Tables (T9.3)

* `audit_logs_archive` — entries older than 7 years moved here monthly.
* `inventory_transactions_archive` — same retention policy.

Both preserve original IDs and (for audit) the hash-chain columns so
forensic verification can still walk the chain.
