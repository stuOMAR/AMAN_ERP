"""
AMAN ERP - Main Application
نظام أمان لإدارة الموارد المؤسسية
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
import os
from contextlib import asynccontextmanager
from sqlalchemy import text
from datetime import datetime, timezone
import logging

from config import settings
from database import engine

# ── Observability ──────────────────────────────────────────────────────────────
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.environ.get("APP_ENV", "production"),
            release="aman-erp@2.0.0",
        )
        logging.getLogger(__name__).info("✅ Sentry initialized")
    except ImportError:
        pass  # sentry-sdk not installed — skip silently

# ── Core & Auth ────────────────────────────────────────────────────────────────
from routers import auth, companies, roles, branches, settings as company_settings
from routers import audit, notifications, approvals, security, data_import

# ── Accounting & Finance (routers/finance/) ─────────────────────────────────────
from routers import finance

# ── Sales, Purchases & Inventory ───────────────────────────────────────────────
from routers import sales, purchases, inventory, parties

# ── HR (routers/hr/) & Manufacturing (routers/manufacturing/) ───────────────────
from routers import hr, manufacturing

# ── Projects & Reports ─────────────────────────────────────────────────────────
from routers import projects, reports, scheduled_reports, dashboard

# ── Commerce & External ────────────────────────────────────────────────────────
from routers import pos, contracts, crm, external, services
from routers import calculator as calculator_router

# ── Role-Based KPI Dashboards ──────────────────────────────────────────────────
from routers import role_dashboards

# ── System Completion (Phase 100%) ─────────────────────────────────────────────
from routers import delivery_orders, landed_costs, hr_wps_compliance
from routers import system_completion
from routers import sso, matching, mobile
from routers import sms as sms_router  # SMS gateways
from routers import shipping as shipping_router  # carriers
from routers import governance as governance_router
from routers import search as search_router  # T7.2 unified search

# ── Feature 022: Audit, Security, Finance Integrity ────────────────────────────
from routers import credentials as credentials_router
from routers import account_classifications as account_classifications_router
from routers import recurring_review as recurring_review_router

# OPS-001: Structured logging — JSON in production, human-readable in dev
from utils.logging_config import setup_logging, RequestIDMiddleware
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة التطبيق"""
    logger.info("🚀 Starting AMAN ERP System...")
    
    # SEC-004: Warn if SECRET_KEY is weak/default
    if len(settings.SECRET_KEY) < 32 or settings.SECRET_KEY.startswith("your-"):
        logger.critical("🔴 SECURITY WARNING: SECRET_KEY is weak or default! Change it in .env immediately!")
        logger.critical("   Generate a strong key: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        # DB-015: Create central user index table for O(1) login lookup
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_user_index (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                company_id VARCHAR(100) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, company_id)
            );
            CREATE INDEX IF NOT EXISTS idx_system_user_index_username 
                ON system_user_index(username);
        """))
        
        # Create system_companies table for company registry
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_companies (
                id VARCHAR(100) PRIMARY KEY,
                company_name VARCHAR(255) NOT NULL,
                company_name_en VARCHAR(255),
                commercial_registry VARCHAR(100),
                tax_number VARCHAR(100),
                phone VARCHAR(50),
                email VARCHAR(255),
                address TEXT,
                city VARCHAR(100),
                country VARCHAR(100) DEFAULT 'SA',
                logo_url VARCHAR(255),
                database_name VARCHAR(255),
                database_user VARCHAR(255),
                currency VARCHAR(10) DEFAULT 'SAR',
                timezone VARCHAR(50) DEFAULT 'Asia/Riyadh',
                status VARCHAR(20) DEFAULT 'active',
                plan_type VARCHAR(50) DEFAULT 'basic',
                max_users INTEGER DEFAULT 10,
                subscription_end DATE,
                template_id INTEGER,
                enabled_modules JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activated_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_system_companies_status
                ON system_companies(status);
        """))

        # Industry Templates Table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS industry_templates (
                id SERIAL PRIMARY KEY,
                key VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                name_ar VARCHAR(100) NOT NULL,
                description TEXT,
                description_ar TEXT,
                icon VARCHAR(10),
                enabled_modules JSONB NOT NULL,
                default_settings JSONB
            );

        """))
        
        # Seed Industry Templates (12 types)
        conn.execute(text("""
            INSERT INTO industry_templates (key, name, name_ar, description, description_ar, icon, enabled_modules)
            VALUES 
            ('retail', 'Retail', 'تجارة التجزئة', 'Grocery, clothing, electronics, gifts', 'بقالات، ملابس، إلكترونيات، عطور، هدايا', '🛍️', '["dashboard","kpi","accounting","assets","treasury","sales","pos","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","subscriptions","matching","forecast"]'),
            ('wholesale', 'Wholesale & Distribution', 'الجملة والتوزيع', 'Distributors, wholesale warehouses, agents, importers', 'موزعين، مستودعات جملة، وكلاء بيع، مستوردين', '📦', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","matching","intercompany","forecast"]'),
            ('restaurant', 'Food & Beverage', 'المطاعم والمقاهي', 'Restaurants, cafes, cloud kitchens, food trucks, bakeries', 'مطاعم، كافيهات، مطابخ سحابية، فود ترك، مخابز', '🍽️', '["dashboard","kpi","accounting","assets","treasury","sales","pos","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","subscriptions","forecast"]'),
            ('manufacturing', 'Manufacturing', 'التصنيع والإنتاج', 'Factories, production workshops, packaging', 'مصانع، ورش إنتاج، تعبئة وتغليف', '🏭', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","manufacturing","projects","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","matching","intercompany","forecast","shop_floor","cpq","subscriptions"]'),
            ('construction', 'Construction', 'المقاولات والمشاريع', 'General contracting, finishing, plumbing, electrical', 'مقاولات عامة، تشطيب، سباكة، كهرباء، طرق', '🏗️', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","projects","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","matching","intercompany"]'),
            ('services', 'Professional Services', 'الخدمات المهنية', 'Accounting, law, consulting, training, marketing', 'محاسبة، محاماة، استشارات، تدريب، تسويق', '💼', '["dashboard","kpi","accounting","assets","treasury","sales","buying","projects","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","subscriptions","intercompany","cpq"]'),
            ('pharmacy', 'Pharmacy & Medical', 'الصيدليات والمستلزمات الطبية', 'Pharmacies, medical supplies, labs, small clinics', 'صيدليات، مستلزمات طبية، مختبرات، عيادات', '💊', '["dashboard","kpi","accounting","assets","treasury","sales","pos","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","matching","forecast","subscriptions"]'),
            ('workshop', 'Workshops & Repair', 'الورش والصيانة', 'Auto mechanics, electrical repair, device repair', 'ميكانيك، كهرباء سيارات، صيانة أجهزة', '🔧', '["dashboard","kpi","accounting","assets","treasury","sales","pos","buying","stock","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow"]'),
            ('ecommerce', 'E-Commerce', 'التجارة الإلكترونية', 'Online stores, social media selling, marketplaces', 'متاجر أونلاين، بيع عبر منصات التواصل', '🛒', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","subscriptions","cpq","forecast"]'),
            ('logistics', 'Logistics & Transport', 'النقل والخدمات اللوجستية', 'Freight, delivery, warehousing, cargo transport', 'شحن، توصيل، مستودعات، نقل بضائع', '🚛', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","matching","intercompany","forecast"]'),
            ('agriculture', 'Agriculture', 'الزراعة والتجارة الزراعية', 'Farms, crop traders, feed, poultry', 'مزارع، تجار محاصيل، أعلاف، دواجن', '🌾', '["dashboard","kpi","accounting","assets","treasury","sales","buying","stock","crm","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","forecast"]'),
            ('general', 'Multi-Activity', 'نشاط عام', 'Comprehensive system with all modules', 'نظام شامل لجميع الأنشطة', '🌐', '["dashboard","kpi","accounting","assets","treasury","sales","pos","buying","stock","manufacturing","projects","crm","services","expenses","taxes","approvals","reports","hr","audit","roles","settings","data_import","sso","analytics","performance","cashflow","campaigns","matching","intercompany","subscriptions","cpq","forecast","shop_floor"]')
            ON CONFLICT (key) DO UPDATE SET 
                name = EXCLUDED.name,
                name_ar = EXCLUDED.name_ar,
                description = EXCLUDED.description,
                description_ar = EXCLUDED.description_ar,
                icon = EXCLUDED.icon,
                enabled_modules = EXCLUDED.enabled_modules;
        """))


        # Create system_activity_log table for global audit trail

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_activity_log (
                id SERIAL PRIMARY KEY,
                company_id VARCHAR(100),
                action_type VARCHAR(100) NOT NULL,
                action_description TEXT,
                performed_by VARCHAR(255),
                ip_address VARCHAR(50),
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_system_activity_log_action 
                ON system_activity_log(action_type);
            CREATE INDEX IF NOT EXISTS idx_system_activity_log_date 
                ON system_activity_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_system_activity_log_company 
                ON system_activity_log(company_id);
        """))

        # SEC-08: DB-backed system-admin 2FA (replaces env-only ADMIN_TOTP_SECRET)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_admin_2fa (
                id SERIAL PRIMARY KEY,
                admin_username VARCHAR(100) UNIQUE NOT NULL,
                secret_key VARCHAR(255) NOT NULL,
                is_enabled BOOLEAN DEFAULT TRUE,
                backup_codes TEXT,
                verified_at TIMESTAMP,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_system_admin_2fa_username
                ON system_admin_2fa(admin_username);
        """))

        conn.commit()
    logger.info("✅ Database connected")

    # T4.2 — supervised coroutine runner with exponential backoff ──────────────
    async def run_supervised(coro_fn, *, name: str, base_delay: float = 1.0, max_delay: float = 60.0):
        """Re-launch *coro_fn()* after failures with exponential back-off.
        *coro_fn* must be a **callable** that returns a fresh coroutine each call."""
        import asyncio as _asyncio
        attempt = 0
        while True:
            try:
                await coro_fn()
            except Exception:
                delay = min(base_delay * (2 ** attempt), max_delay)
                attempt += 1
                logger.exception("Background task '%s' failed (attempt %d) — retrying in %.1fs", name, attempt, delay)
                await _asyncio.sleep(delay)
                continue
            # Coroutine returned normally — reset back-off
            attempt = 0

    # Start Background Stats Worker
    from routers.dashboard import update_system_stats_task
    import asyncio
    asyncio.create_task(run_supervised(update_system_stats_task, name="system_stats"))
    logger.info("📡 System Stats Background Worker Started")

    # SEC-201: Start token blacklist cleanup task
    async def _blacklist_cleanup_loop():
        from routers.auth import cleanup_expired_blacklist
        while True:
            try:
                cleanup_expired_blacklist()
            except Exception:
                pass
            await asyncio.sleep(3600)  # Every hour
    asyncio.create_task(run_supervised(_blacklist_cleanup_loop, name="blacklist_cleanup"))
    logger.info("🧹 Token Blacklist Cleanup Worker Started")

    
    # Start Report Scheduler
    # TASK-028: web process only starts the in-process scheduler when mode is
    # `in_process`. For production multi-replica deployments, set
    # SCHEDULER_MODE=dedicated and run backend/worker.py as a separate service
    # so jobs fire exactly once regardless of web replica count.
    scheduler_mode = (getattr(settings, "SCHEDULER_MODE", "in_process") or "in_process").lower()
    if scheduler_mode == "in_process":
        from services.scheduler import start_scheduler
        start_scheduler()
        logger.info("⏰ Report Scheduler Started (in-process)")
    else:
        logger.info("⏰ Report Scheduler NOT started in web process (SCHEDULER_MODE=%s)", scheduler_mode)

    # TASK-041: discover and register plugins (drop packages into backend/plugins/).
    try:
        from utils.plugin_registry import load_plugins
        loaded = load_plugins(app)
        if loaded:
            logger.info("🔌 Plugins registered: %s", ", ".join(loaded))
    except Exception:
        logger.exception("Plugin loading failed (non-fatal)")

    # Phase 6: optional Redis Streams bridge for the domain event bus.
    # Enabled by setting REDIS_EVENT_BUS=1 in the environment.
    try:
        from utils.redis_event_bus import install as _install_redis_bus, is_enabled as _bus_enabled
        if _bus_enabled():
            if _install_redis_bus():
                logger.info("📡 Redis event-bus bridge installed")
    except Exception:
        logger.exception("Redis event bus install failed (non-fatal)")

    # Phase 6 ext: transactional-outbox relay worker.
    # Enabled by setting OUTBOX_RELAY=1 in the environment.
    try:
        if os.getenv("OUTBOX_RELAY", "0") in ("1", "true", "yes"):
            from utils.outbox_relay import start_worker as _start_outbox
            from database import get_db_connection as _tenant_db
            # Relay uses the system/default tenant connection (company_id="system"
            # resolves to the default DB in get_db_connection). Per-tenant fan-out
            # is not needed because event_outbox lives in the shared schema.
            _start_outbox(lambda: _tenant_db("system"),
                          interval_seconds=int(os.getenv("OUTBOX_INTERVAL_SECONDS", "30")))
    except Exception:
        logger.exception("Outbox relay start failed (non-fatal)")
    
    # Sync schema for all existing company databases via Alembic migrations
    try:
        import subprocess
        import sys as _sys
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_ini = os.path.join(backend_dir, "alembic.ini")
        alembic_cmd = [
            _sys.executable, "-m", "alembic",
            "-c", alembic_ini,
            "-x", "company=all",
            "upgrade", "head",
        ]
        result = subprocess.run(
            alembic_cmd, cwd=backend_dir,
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            logger.info("🔄 Alembic migrations applied for all company databases")
        else:
            logger.warning(f"⚠️ Alembic migration warnings: {result.stderr or result.stdout}")
    except Exception as e:
        logger.warning(f"⚠️ Schema sync skipped: {e}")

    # Feature 022: Sensitive permission startup discovery
    try:
        from services.permissions.sensitive import discover_sensitive_routes
        discover_sensitive_routes(app, strict=False)
    except ImportError:
        logger.debug("sensitive permission discovery not available")

    # Feature 022: Audit outbox worker startup banner
    try:
        from services.audit_outbox_worker import start_worker as _audit_banner
        _audit_banner()
    except ImportError:
        pass

    yield
    
    logger.info("⏹️ Stopping AMAN ERP System...")
    engine.dispose()


app = FastAPI(
    title="AMAN ERP System",
    description="""
# نظام أمان لإدارة الموارد المؤسسية (AMAN ERP)

نظام ERP متكامل متعدد الشركات (Multi-Tenant) مبني بـ **FastAPI** و **PostgreSQL**.

## الوحدات الرئيسية

| الوحدة | الوصف |
|--------|-------|
| 📊 المحاسبة | دليل حسابات، قيود يومية، ميزان مراجعة، قوائم مالية |
| 💰 المبيعات | فواتير، أوامر بيع، عروض أسعار، مرتجعات |
| 🛒 المشتريات | أوامر شراء، موردين، RFQ، اتفاقيات |
| 📦 المخزون | منتجات، مستودعات، تحويلات، تتبع دفعات وأرقام تسلسلية |
| 🏦 الخزينة | حسابات بنكية، تسويات، شيكات، سندات |
| 👥 الموارد البشرية | موظفين، رواتب، حضور، إجازات، تقييم أداء |
| 🏭 التصنيع | قوائم مواد (BOM)، أوامر إنتاج، مراكز عمل |
| 🏪 نقاط البيع | واجهة POS، عروض، برامج ولاء |
| 📐 المشاريع | إدارة مشاريع، مهام، موارد، Gantt |
| 📈 التقارير | تقارير مالية وتشغيلية، تقارير مجدولة |

## المصادقة

يستخدم النظام **JWT Bearer Token** — أرسل التوكن في header:
```
Authorization: Bearer <token>
```
""",
    version="2.0.0",
    lifespan=lifespan,
    # SEC-T2.9: hide interactive API docs in production. They leak the full
    # endpoint surface + payload schemas, which is a recon goldmine. Set
    # APP_ENV=production (or EXPOSE_API_DOCS=false) to disable.
    docs_url=("/api/docs" if (settings.APP_ENV != "production" and getattr(settings, "EXPOSE_API_DOCS", True)) else None),
    redoc_url=("/api/redoc" if (settings.APP_ENV != "production" and getattr(settings, "EXPOSE_API_DOCS", True)) else None),
    openapi_url=("/api/openapi.json" if (settings.APP_ENV != "production" and getattr(settings, "EXPOSE_API_DOCS", True)) else None),
    openapi_tags=[
        # ── Core & Auth ──
        {"name": "المصادقة", "description": "تسجيل الدخول، JWT tokens، المصادقة الثنائية (2FA)، إدارة الجلسات"},
        {"name": "إدارة الشركات", "description": "إنشاء وإدارة الشركات (Multi-Tenant)، تهيئة قاعدة البيانات لكل شركة"},
        {"name": "إدارة الأدوار", "description": "أدوار المستخدمين والصلاحيات التفصيلية (RBAC)"},
        {"name": "branches", "description": "إدارة فروع الشركة وربط المستخدمين بالفروع"},
        {"name": "إعدادات الشركة", "description": "إعدادات عامة للشركة: عملة افتراضية، سنة مالية، شعار، إلخ"},
        {"name": "سجلات المراقبة", "description": "سجل المراجعة (Audit Log) — تتبع جميع العمليات والتعديلات"},
        {"name": "الإشعارات", "description": "إشعارات فورية عبر WebSocket وHTTP — إنشاء، قراءة، حذف"},
        {"name": "الاعتمادات", "description": "نظام الموافقات متعدد المستويات — سير عمل قابل للتخصيص"},
        {"name": "الأمان", "description": "إدارة مفاتيح API، Webhooks، سجل الأحداث الأمنية"},
        {"name": "استيراد/تصدير البيانات", "description": "استيراد بيانات من Excel/CSV — حسابات، منتجات، عملاء، موظفين"},

        # ── Accounting & Finance ──
        {"name": "المحاسبة", "description": "دليل الحسابات، القيود اليومية، الأرصدة الافتتاحية، قيود الإقفال، القيود المتكررة"},
        {"name": "accounting", "description": "العملات وأسعار الصرف — تحديث يومي وسجل تاريخي"},
        {"name": "مراكز التكلفة", "description": "إنشاء وإدارة مراكز التكلفة وتوزيع المصاريف"},
        {"name": "Budgets", "description": "إعداد الميزانيات التقديرية ومقارنتها بالفعلي — تنبيهات التجاوز"},
        {"name": "تسوية البنك", "description": "التسوية البنكية — استيراد كشف حساب، مطابقة تلقائية، تأكيد"},
        {"name": "الخزينة والمصروفات", "description": "حسابات بنكية ونقدية، مصروفات، تحويلات بين الحسابات، تقرير تدفقات نقدية"},
        {"name": "الضرائب", "description": "إعداد معدلات الضريبة، الإقرارات الضريبية، ضريبة الاستقطاع (WHT)"},
        {"name": "Costing Policies", "description": "سياسات تكلفة المخزون — FIFO, LIFO, متوسط مرجح، تكلفة معيارية"},
        {"name": "checks", "description": "شيكات القبض والدفع — إصدار، تحصيل، رفض، تحويل"},
        {"name": "أوراق القبض والدفع", "description": "سندات القبض والصرف — إنشاء، تأكيد، طباعة"},
        {"name": "الأصول الثابتة", "description": "إدارة الأصول — إهلاك، إعادة تقييم، صيانة، تأمين"},
        {"name": "المصاريف", "description": "مطالبات المصروفات — تقديم، موافقة، صرف، تقارير"},

        # ── Sales & Purchases ──
        {"name": "المبيعات", "description": "فواتير المبيعات، أوامر البيع، عروض الأسعار، المرتجعات، إيصالات القبض، إشعارات دائنة/مدينة"},
        {"name": "المشتريات", "description": "أوامر الشراء، فواتير المشتريات، المرتجعات، طلبات عروض أسعار (RFQ)، تقييم الموردين"},
        {"name": "المخزون", "description": "المنتجات، المستودعات، التحويلات، التسويات، حركات المخزون، الشحنات"},
        {"name": "Advanced Inventory Phase 2", "description": "تتبع الدفعات والأرقام التسلسلية، فحص الجودة، الجرد الدوري"},
        {"name": "الجهات (العملاء والموردين)", "description": "إدارة موحدة للعملاء والموردين — بيانات، كشوف حساب، أرصدة"},

        # ── HR ──
        {"name": "HR & Employees", "description": "الموظفين، الأقسام، المناصب، الرواتب، الحضور، الإجازات، القروض"},
        {"name": "HR Advanced - الموارد البشرية المتقدمة", "description": "تقييم الأداء، التدريب، المخالفات، العهد، التوظيف، العمل الإضافي"},

        # ── Manufacturing ──
        {"name": "Manufacturing (Phase 5)", "description": "مراكز العمل، خطوط الإنتاج، قوائم المواد (BOM)، أوامر الإنتاج، بطاقات العمل، MRP"},

        # ── Projects & Reports ──
        {"name": "المشاريع", "description": "إدارة المشاريع — مهام، موارد، ميزانيات، Gantt chart، تقارير تقدم"},
        {"name": "التقارير", "description": "ميزان المراجعة، قائمة الدخل، الميزانية العمومية، كشف حساب، تقارير المبيعات والمشتريات"},
        {"name": "Scheduled Reports", "description": "تقارير مجدولة — إعداد تقارير تلقائية تُرسل بالبريد الإلكتروني"},
        {"name": "لوحة التحكم", "description": "لوحة قيادة شاملة — إحصائيات مالية، رسوم بيانية، مؤشرات أداء"},

        # ── Commerce & External ──
        {"name": "Point of Sale", "description": "نقطة البيع — واجهة بيع، جلسات، عروض ترويجية، برامج ولاء، طاولات مطعم"},
        {"name": "Contracts", "description": "إدارة العقود — إنشاء، تجديد، إنهاء، تنبيهات الانتهاء"},
        {"name": "إدارة العلاقات CRM", "description": "فرص البيع (Pipeline)، تذاكر الدعم الفني، إدارة العملاء المحتملين"},
        {"name": "التكامل الخارجي", "description": "مفاتيح API، Webhooks، تكامل مع أنظمة خارجية"},
    ]
)

# CORS — قائمة بيضاء دقيقة للـ origins
def _build_origins() -> list[str]:
    """Build allowed origins from settings — supports comma-separated ALLOWED_ORIGINS env var"""
    if settings.ALLOWED_ORIGINS:
        return [o.strip() for o in settings.ALLOWED_ORIGINS.split(',') if o.strip()]
    origins = [settings.FRONTEND_URL]
    if settings.FRONTEND_URL_PRODUCTION:
        origins.append(settings.FRONTEND_URL_PRODUCTION)
    return origins

origins = _build_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)

# API-001: Rate Limiting — مشترك عبر shared limiter
from utils.limiter import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# OPS-001: Request-ID middleware — adds X-Request-ID to every request/response
app.add_middleware(RequestIDMiddleware)

# T9.4: Accept-Language middleware — stash the negotiated UI language onto
# `request.state.lang` so backend `utils/i18n.http_error()` can return the
# correct locale without every router parsing the header. Frontend's
# `services/apiClient.js` injects this header automatically.
from starlette.middleware.base import BaseHTTPMiddleware


class AcceptLanguageMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        raw = request.headers.get("Accept-Language", "")
        # Take the first language tag, drop quality parameters, normalize ar-SA → ar.
        primary = (raw.split(",")[0].split(";")[0].strip() or "en").split("-")[0].lower()
        if primary not in {"ar", "en"}:
            primary = "en"
        try:
            request.state.lang = primary
        except Exception:
            pass
        return await call_next(request)


app.add_middleware(AcceptLanguageMiddleware)

# T10.2 #171 — Server-wide request body size cap. Protects against DoS via
# huge multipart uploads even before the per-endpoint size checks in
# ``utils/sql_safety.py`` (50 MB document, 10 MB import) run. The default
# is 100 MB which is double the largest per-endpoint cap; tune via env.
_MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(100 * 1024 * 1024)))


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > _MAX_REQUEST_BODY_BYTES:
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "حجم الطلب يتجاوز الحد الأقصى المسموح به على مستوى الخادم"},
                    )
            except (TypeError, ValueError):
                pass
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)

# SEC-203: HTTPS Enforcement + Security Headers
# SEC-204: Input Sanitization (XSS/SQLi detection)
from utils.security_middleware import HTTPSRedirectMiddleware, InputSanitizationMiddleware
# FORCE_HTTPS must be explicitly enabled (e.g. after SSL cert is installed).
# When running on plain HTTP (IP-only, no domain/cert) keep it off to prevent
# the 301→HTTPS loop that causes ERR_CONNECTION_REFUSED in the browser.
if os.getenv("FORCE_HTTPS", "false").lower() == "true":
    app.add_middleware(HTTPSRedirectMiddleware)
else:
    # Still register the middleware for security headers only (no redirect)
    from utils.security_middleware import SecurityHeadersOnlyMiddleware
    app.add_middleware(SecurityHeadersOnlyMiddleware)
app.add_middleware(InputSanitizationMiddleware)

# SEC / TASK-030: CSRF double-submit-cookie protection. Enforcement mode is
# controlled via settings.CSRF_ENFORCEMENT (off | permissive | strict).
from utils.csrf_middleware import CSRFMiddleware
app.add_middleware(CSRFMiddleware)

# Optional N+1 query observer (disabled unless ENABLE_QUERY_COUNTER=1).
from utils.query_counter import QueryCounterMiddleware, install_engine_listener
app.add_middleware(QueryCounterMiddleware)

# Feature 022: Audit body capture — sanitise request bodies on sensitive routes
try:
    from utils.audit_body_capture import AuditBodyCaptureMiddleware
    app.add_middleware(AuditBodyCaptureMiddleware)
except ImportError:
    pass
try:
    from database import engine as _system_engine
    install_engine_listener(_system_engine)
except Exception:
    pass

# ── Prometheus Metrics ─────────────────────────────────────────────────────────
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/metrics", "/api/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("✅ Prometheus metrics exposed at /metrics")
except ImportError:
    logger.warning("⚠️ prometheus-fastapi-instrumentator not installed — metrics disabled")

# Static Files (Logos, attachments)
# T2.6 (audit #54, #167): the previous setup mounted /uploads and /api/uploads
# as wide-open StaticFiles, exposing every tenant's documents to anyone who
# guessed a filename. Now:
#   • /uploads/logos/<file>   → public branding (intentional)
#   • /uploads/<other>        → requires HMAC-signed query (?exp=…&sig=…)
#                                issued by the API after a permission check.
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
try:
    os.makedirs(os.path.join(uploads_dir, "logos"), exist_ok=True)
except PermissionError as e:
    logger.warning(f"⚠️  Cannot create uploads/logos: {e} — entrypoint should handle this")

# Public branding subdirectory only.
app.mount(
    "/uploads/logos",
    StaticFiles(directory=os.path.join(uploads_dir, "logos")),
    name="uploads_logos",
)


@app.get("/uploads/{file_path:path}", include_in_schema=False)
async def _serve_signed_upload(file_path: str, request: Request):
    """Guarded fallback for non-logo uploads — requires signed URL."""
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    from utils.signed_urls import verify_signature, is_public_path

    full_path = f"/uploads/{file_path}"
    # Logos handled by the public mount above; this route only fires for
    # paths that did not match it.
    if is_public_path(full_path):
        # Should never reach here in practice — defensive 404.
        raise HTTPException(status_code=404)

    exp = request.query_params.get("exp")
    sig = request.query_params.get("sig")
    ok, reason = verify_signature(full_path, exp, sig)
    if not ok:
        raise HTTPException(status_code=401, detail=f"unauthorized: {reason}")

    # Path-traversal hardening: resolve and ensure it stays inside uploads_dir.
    target = os.path.abspath(os.path.join(uploads_dir, file_path))
    if not target.startswith(os.path.abspath(uploads_dir) + os.sep):
        raise HTTPException(**http_error(400, "invalid_path", request))
    if not os.path.isfile(target):
        raise HTTPException(status_code=404)
    return FileResponse(target)


# Mirror under /api/uploads so the same signed URL works whether the caller
# uses the API prefix or hits the bare path.
@app.get("/api/uploads/{file_path:path}", include_in_schema=False)
async def _serve_signed_upload_api(file_path: str, request: Request):
    return await _serve_signed_upload(file_path, request)



# Global exception handler: sanitize 500 error messages to prevent info leakage
@app.exception_handler(FastAPIHTTPException)
async def sanitize_http_exception(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == 500:
        # Log the real error for debugging
        logger.error(f"Internal error on {request.method} {request.url.path}: {exc.detail}")
        return JSONResponse(
            status_code=500,
            content={"detail": "حدث خطأ داخلي في الخادم. يرجى المحاولة لاحقاً."}
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# Global unhandled exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    import traceback
    tb = traceback.format_exc()
    logger.error(tb)
    return JSONResponse(
        status_code=500,
        content={"detail": "حدث خطأ داخلي في الخادم. يرجى المحاولة لاحقاً."}
    )



# ── Core & Auth ─────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(roles.router, prefix="/api")
app.include_router(branches.router, prefix="/api")
app.include_router(company_settings.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(approvals.router, prefix="/api")
app.include_router(security.router, prefix="/api")
app.include_router(data_import.router, prefix="/api")

# ── Accounting & Finance (12 sub-routers from routers/finance/) ──
app.include_router(finance.router, prefix="/api")

# ── Sales, Purchases & Inventory ────────────────────────────────
app.include_router(sales.router, prefix="/api")
app.include_router(purchases.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(parties.router, prefix="/api")
from routers.party_balances import router as party_balances_router
app.include_router(party_balances_router, prefix="/api")
from routers.party_sites import router as party_sites_router
app.include_router(party_sites_router, prefix="/api")
from routers.price_lists import router as price_lists_router
app.include_router(price_lists_router, prefix="/api")
from routers.price_sync import router as price_sync_router
app.include_router(price_sync_router, prefix="/api")

# ── HR (2 sub-routers) & Manufacturing ────────────────────────────
app.include_router(hr.router, prefix="/api")
app.include_router(manufacturing.router, prefix="/api")

# ── Projects & Reports ───────────────────────────────────────────
app.include_router(projects.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(scheduled_reports.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")

# T7.2: unified search endpoint (parties / products / invoices / SOs / POs).
app.include_router(search_router.router, prefix="/api")

# ── Commerce & External ──────────────────────────────────────────
app.include_router(pos.router, prefix="/api")
app.include_router(contracts.router, prefix="/api")
app.include_router(crm.router, prefix="/api")
app.include_router(external.router, prefix="/api")
app.include_router(services.router, prefix="/api")
app.include_router(calculator_router.router, prefix="/api")
# ── Role-Based KPI Dashboards ────────────────────────────────────────────
app.include_router(role_dashboards.router, prefix="/api")
# ── System Completion (New modules) ──────────────────────────────
app.include_router(delivery_orders.router, prefix="/api")
app.include_router(landed_costs.router, prefix="/api")
app.include_router(hr_wps_compliance.router, prefix="/api")

# Feature 022: Employee receipt settlement endpoints
from routers.hr.employee_receipts import router as employee_receipts_router
app.include_router(employee_receipts_router, prefix="/api")
app.include_router(system_completion.router, prefix="/api")
app.include_router(sso.router, prefix="/api")
app.include_router(matching.router, prefix="/api")
app.include_router(mobile.router, prefix="/api")
app.include_router(sms_router.router, prefix="/api")
app.include_router(shipping_router.router, prefix="/api")
app.include_router(governance_router.router, prefix="/api")

# ── Feature 022: Audit, Security, Finance Integrity ────────────────────────────
app.include_router(credentials_router.router, prefix="/api")
app.include_router(account_classifications_router.router, prefix="/api")
app.include_router(recurring_review_router.router, prefix="/api")

# T4.3 — Smart Alerts router
try:
    from routers import smart_alerts as smart_alerts_router
    app.include_router(smart_alerts_router.router, prefix="/api")
    from routers import email_templates as email_templates_router
    app.include_router(email_templates_router.router, prefix="/api")
    # T5.3 — Integration keys + circuit breakers admin
    from routers import integrations_admin as integrations_admin_router
    app.include_router(integrations_admin_router.router, prefix="/api")
except ImportError:
    pass

# ── Feature 023: Sales/POS/CRM/ZATCA + Inventory/Manufacturing ──────
try:
    from routers.sales.order_to_invoice import router as order_to_invoice_router
    from routers.sales.cancellation import router as sales_cancellation_router
    from routers.returns_unified import router as returns_unified_router
    from routers.pos.offline import router as pos_offline_router
    from routers.pos.cancellation import router as pos_cancellation_router
    from routers.crm.velocity import router as crm_velocity_router
    from routers.crm.funnel import router as crm_funnel_router
    from routers.crm.cashflow import router as crm_cashflow_router
    from routers.einvoicing.outbox_admin import router as outbox_admin_router
    from routers.manufacturing.mrp import router as mrp_router
    from routers.manufacturing.mrp_recommendations import router as mrp_recommendations_router
    from routers.manufacturing.production import router as production_router
    from routers.manufacturing.production_approval import router as production_approval_router
    from routers.manufacturing.qc import router as qc_router
    from routers.inventory.archival_admin import router as archival_admin_router
    from routers.inventory.transfer_deprecated import router as transfer_deprecated_router

    app.include_router(order_to_invoice_router, prefix="/api")
    app.include_router(sales_cancellation_router, prefix="/api")
    app.include_router(returns_unified_router, prefix="/api")
    app.include_router(pos_offline_router, prefix="/api")
    app.include_router(pos_cancellation_router, prefix="/api")
    app.include_router(crm_velocity_router, prefix="/api")
    app.include_router(crm_funnel_router, prefix="/api")
    app.include_router(crm_cashflow_router, prefix="/api")
    app.include_router(outbox_admin_router, prefix="/api")
    app.include_router(mrp_router, prefix="/api")
    app.include_router(mrp_recommendations_router, prefix="/api")
    app.include_router(production_router, prefix="/api")
    app.include_router(production_approval_router, prefix="/api")
    app.include_router(qc_router, prefix="/api")
    app.include_router(archival_admin_router, prefix="/api")
    app.include_router(transfer_deprecated_router, prefix="/api")
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Feature 023 routers not fully loaded: {e}")

# ── Feature 024: HR/PII + Payroll + FSM + DMS + Notifications ────────
try:
    from routers.hr.pii_admin import router as pii_admin_router
    from routers.hr.salary_increments import router as salary_increments_router
    from routers.payroll.reversal import router as payroll_reversal_router
    from routers.fsm.pricelists_admin import router as pricelists_admin_router
    from routers.fsm.technicians_admin import router as technicians_admin_router
    from routers.fsm.contracts_renewal import router as contracts_renewal_router
    from routers.dms.quotas_admin import router as dms_quotas_admin_router

    app.include_router(pii_admin_router, prefix="/api")
    app.include_router(salary_increments_router, prefix="/api")
    app.include_router(payroll_reversal_router, prefix="/api")
    app.include_router(pricelists_admin_router, prefix="/api")
    app.include_router(technicians_admin_router, prefix="/api")
    app.include_router(contracts_renewal_router, prefix="/api")
    app.include_router(dms_quotas_admin_router, prefix="/api")
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Feature 024 routers not fully loaded: {e}")

# ── Feature 025: Reports/KPI/Search/Health/Scheduler/Restore routers ──────
try:
    from routers.reports import router as reports_router
    from routers.kpi import router as kpi_router
    from routers.health import router as health_detailed_router
    from routers.search import router as search_registry_router
    from routers.ops_scheduler import router as ops_scheduler_router
    from routers.ops_restore import router as ops_restore_router
    from routers.locale import router as locale_router

    app.include_router(reports_router, prefix="/api")
    app.include_router(kpi_router, prefix="/api")
    app.include_router(health_detailed_router)
    app.include_router(search_registry_router, prefix="/api")
    app.include_router(ops_scheduler_router, prefix="/api")
    app.include_router(ops_restore_router, prefix="/api")
    app.include_router(locale_router, prefix="/api")
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Feature 025 routers not fully loaded: {e}")


@app.get("/")
def root():
    return {
        "system": "AMAN ERP",
        "version": "2.0.0",
        "status": "running",
        "features": {
            "auto_company_id": True,
            "multi_tenant": True,
            "total_tables": 178
        },
        "docs": "/api/docs"
    }


@app.get("/api/health", tags=["Health"], summary="Health Check", include_in_schema=True)
def health_check():
    """
    فحص صحة النظام — يتحقق من:
    - اتصال قاعدة البيانات الرئيسية
    - عدد الشركات المسجلة
    - اتصال Redis (اختياري)
    - وقت الاستجابة
    """
    import time
    start = time.monotonic()
    
    checks: dict = {}
    overall = "healthy"

    # ── Database check ──
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM system_companies"))
            company_count = result.scalar()
        checks["database"] = {"status": "ok", "companies": company_count}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)[:120]}
        overall = "degraded"

    # ── Redis check (optional) ──
    try:
        if settings.REDIS_URL:
            import redis as redis_lib
            r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            r.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "not_configured"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)[:80]}
        # Redis is optional — don't degrade overall health

    elapsed_ms = round((time.monotonic() - start) * 1000, 2)

    return {
        "status": overall,
        "version": "2.0.0",
        "environment": os.environ.get("APP_ENV", "development"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "response_time_ms": elapsed_ms,
        "checks": checks,
    }


@app.get("/health", include_in_schema=False)
def health_check_root():
    """Alias for /api/health — used by Docker/load balancer health probes"""
    return health_check()


# T7.4 — cache hit-rate metrics for ops dashboards.
@app.get("/api/health/cache", tags=["Health"], summary="Cache Stats", include_in_schema=True)
def cache_health_endpoint():
    """\u0639\u062f\u0651\u0627\u062f hit/miss \u0644\u0644\u0643\u0627\u0634 \u0627\u0644\u0645\u0648\u062d\u062f \u0648\u0646\u0633\u0628\u0629 \u0627\u0644\u0625\u0635\u0627\u0628\u0629 (DoD: hit-rate > 60%)."""
    from utils.cache import cache_stats
    return cache_stats()


# T4.1 — Scheduler health endpoint
@app.get("/api/health/scheduler", tags=["Health"], summary="Scheduler Health", include_in_schema=True)
def scheduler_health():
    """فحص حالة المجدول — آخر تشغيل لكل وظيفة مع حالتها"""
    from services.scheduler import scheduler, _job_execution_log, _SCHEDULER_TZ
    running = scheduler.running
    jobs = []
    for job in scheduler.get_jobs():
        log = _job_execution_log.get(job.id, {})
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run": log.get("last_run"),
            "last_status": log.get("status"),
            "last_error": log.get("error"),
        })
    return {
        "scheduler_running": running,
        "timezone": _SCHEDULER_TZ,
        "job_count": len(jobs),
        "jobs": jobs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
