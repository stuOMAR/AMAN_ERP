
import logging
import os
import re
import subprocess
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from typing import Generator, Tuple
from contextlib import contextmanager
from passlib.context import CryptContext
import uuid

from config import settings

# T6.4: DDL extracted to backend/db_ddl/tenant_schema.py.
# Re-export here so any caller `from database import get_*_tables_sql`
# continues to work. db_ddl is the single source of truth.
from db_ddl.tenant_schema import (  # noqa: E402,F401
    get_foundation_tables_sql,
    get_additional_base_tables_sql,
    get_treasury_base_tables_sql,
    get_core_dependent_tables_sql,
    get_additional_dependent_tables_sql,
    get_organization_tables_sql,
    get_financial_tables_sql,
    get_treasury_dependent_tables_sql,
    get_currency_tables_sql,
    get_contract_tables_sql,
    get_costing_policy_tables_sql,
    get_advanced_inventory_tables_sql,
    get_advanced_inventory_phase2_tables_sql,
    get_manufacturing_tables_sql,
    get_pos_tables_sql,
    get_approval_tables_sql,
    get_security_tables_sql,
    get_cashflow_forecast_tables_sql,
    get_phase_features_tables_sql,
    get_system_completion_tables_sql,
    get_extended_features_tables_sql,
    get_performance_indexes_sql,
    get_gl_integrity_guards_sql,
    get_phase5_integration_tables_sql,
    get_audit_security_finance_tables_sql,
    get_feature023_tables_sql,
    get_feature024_tables_sql,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SEC-007: Separate DDL engine (AUTOCOMMIT, for CREATE DATABASE / CREATE USER)
# from the regular system engine used for SELECT/INSERT/UPDATE/DELETE.
_ddl_engine = create_engine(
    settings.DATABASE_URL,
    isolation_level="AUTOCOMMIT",
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Regular system engine — no AUTOCOMMIT so transactions are properly managed.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from collections import OrderedDict

# PERF-FIX: Bounded LRU engine cache — prevents connection exhaustion in
# environments with many companies.
# Defaults: 50 engines × (2 pool + 3 overflow) = 250 connections max.
_MAX_ENGINES = max(1, int(getattr(settings, "DB_TENANT_ENGINE_CACHE_SIZE", 50)))
_TENANT_POOL_SIZE = max(1, int(getattr(settings, "DB_TENANT_POOL_SIZE", 2)))
_TENANT_MAX_OVERFLOW = max(0, int(getattr(settings, "DB_TENANT_MAX_OVERFLOW", 3)))
_engines: OrderedDict = OrderedDict()

def _get_engine(company_id: str):
    """Internal helper to get or create a cached engine (LRU eviction)."""
    if not company_id:
        raise ValueError("company_id is required")
    if company_id in _engines:
        # Move to end to mark as recently used
        _engines.move_to_end(company_id)
        return _engines[company_id]
    # Evict least-recently-used engine when cap is exceeded
    if len(_engines) >= _MAX_ENGINES:
        _lru_id, _lru_engine = _engines.popitem(last=False)
        try:
            _lru_engine.dispose()
            logger.info(f"🔌 Engine evicted (LRU): company {_lru_id}")
        except Exception:
            pass
    db_url = settings.get_company_database_url(company_id)
    _engines[company_id] = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=_TENANT_POOL_SIZE,
        max_overflow=_TENANT_MAX_OVERFLOW
    )
    try:
        from utils.query_counter import install_engine_listener
        install_engine_listener(_engines[company_id])
    except Exception:
        pass
    return _engines[company_id]

def get_db_connection(company_id: str):
    """Returns a connection to the company specific database with engine caching
    
    Note: Caller is responsible for closing the connection with db.close()
    For safer usage, use db_connection() context manager instead.
    """
    return _get_engine(company_id).connect()


def _get_all_company_db_names() -> list:
    """Return list of database_names for all active companies (e.g. 'aman_abc123')."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT database_name FROM system_companies "
                "WHERE status = 'active' AND database_name IS NOT NULL"
            )).fetchall()
            return [r[0] for r in rows if r[0]]
    except Exception:
        logger.exception("_get_all_company_db_names failed")
        return []


@contextmanager
def db_connection(company_id: str):
    """Context manager for safe database connection handling
    
    Usage:
        with db_connection(company_id) as db:
            result = db.execute(...)
            # connection automatically closed
    """
    conn = _get_engine(company_id).connect()
    try:
        yield conn
    finally:
        if not conn.closed:
            conn.close()


@contextmanager
def get_tenant_db(company_id: str | None = None):
    """Return a tenant DB connection, defaulting to the sole active tenant.

    New operational/reporting routers call this helper from request handlers.
    When a company id is not supplied, use the first active company so local
    single-tenant development endpoints remain reachable.
    """
    tenant_id = str(company_id or "").strip()
    if not tenant_id:
        with engine.connect() as system_conn:
            tenant_id = str(
                system_conn.execute(
                    text(
                        "SELECT id FROM system_companies "
                        "WHERE status = 'active' "
                        "ORDER BY created_at NULLS LAST, id "
                        "LIMIT 1"
                    )
                ).scalar()
                or ""
            )
    if not tenant_id:
        raise RuntimeError("No active tenant database is available")

    with db_connection(tenant_id) as conn:
        yield conn

def get_company_db(company_id: str) -> Generator[Session, None, None]:
    """Returns a session to the company specific database using cached engine"""
    engine = _get_engine(company_id)
    CompanySession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = CompanySession()
    try:
        yield db
    finally:
        db.close()


def get_system_db() -> Session:
    return SessionLocal()


def generate_company_id() -> str:
    length = settings.COMPANY_ID_LENGTH
    return str(uuid.uuid4()).replace('-', '')[:length]


def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except Exception:
        # Fallback for bcrypt 5.x compatibility
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        import bcrypt
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_company_database(company_id: str, admin_password: str) -> Tuple[bool, str, str, str]:
    db_name = f"aman_{company_id}"
    db_user = f"company_{company_id}"
    
    # SEC-FIX-025: Validate identifiers to prevent SQL injection in DDL
    from utils.sql_safety import validate_aman_identifier
    validate_aman_identifier(db_name, "database name")
    validate_aman_identifier(db_user, "database user")

    # SEC-C3: The per-tenant PostgreSQL role password MUST NOT equal the
    # tenant admin's application password. Generate a fresh high-entropy
    # secret; it is only used by superusers for direct DB access.
    import secrets as _secrets
    db_role_password = _secrets.token_urlsafe(32)

    # SEC-007: Use _ddl_engine (AUTOCOMMIT) — DDL cannot run inside a transaction.
    try:
        with _ddl_engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": db_name}
            ).fetchone()
            
            if result:
                return False, "قاعدة البيانات موجودة", "", ""
            
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            conn.execute(text(f"CREATE USER {db_user} WITH PASSWORD :password"), {"password": db_role_password})
            conn.execute(text(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO {db_user}'))
            conn.execute(text(f'ALTER DATABASE "{db_name}" OWNER TO {db_user}'))
        
        logger.info(f"✅ Created database: {db_name}")
        return True, "تم إنشاء قاعدة البيانات", db_name, db_user
        
    except Exception:
        logger.exception("Failed to create company database")
        return False, "حدث خطأ أثناء إنشاء قاعدة البيانات", "", ""


    # NOTE: sync_essential_columns has been removed.
    # Existing tenant schema changes are handled by Alembic migrations.
    # New tenant DBs get the full schema via db_ddl.tenant_runner.apply_tenant_schema().

def create_company_tables(company_id: str, currency: str = "SAR") -> Tuple[bool, str]:
    """Create tenant schema, then stamp Alembic head.

    T6.4: All raw DDL has moved to ``backend/db_ddl/tenant_schema.py`` (the
    ``get_*_tables_sql()`` string builders) and
    ``backend/db_ddl/tenant_runner.py`` (orchestrator + post-DDL fix-ups).
    This function is now a thin wrapper: open an AUTOCOMMIT connection to
    the freshly-provisioned tenant DB, call
    :func:`db_ddl.tenant_runner.apply_tenant_schema`, then stamp Alembic
    at ``head`` so subsequent ``alembic upgrade`` runs are no-ops.

    The Alembic baseline migration ``0001_baseline_complete`` invokes the
    same :func:`apply_tenant_schema`, so ``alembic upgrade head`` against
    an empty tenant DB produces an identical schema — satisfying the T6.4
    DoD "alembic upgrade ينشئ schema كاملة".
    """
    from db_ddl.tenant_runner import apply_tenant_schema

    db_name = f"aman_{company_id}"
    connection_url = settings.get_company_database_url(company_id)

    def run_company_alembic_stamp_head() -> Tuple[bool, str]:
        """Stamp Alembic head for a freshly created company database.

        Tries the in-process Alembic Python API first (most reliable, no
        PATH dependency); falls back to subprocess invocations if needed.
        """
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_ini = os.path.join(backend_dir, "alembic.ini")

        try:
            from alembic.config import Config as _AlembicConfig
            from alembic import command as _alembic_command

            cfg = _AlembicConfig(alembic_ini)
            cfg.cmd_opts = type(
                "X", (), {"autogenerate": False, "x": [f"company={company_id}"]}
            )()
            try:
                cfg.attributes["x"] = [f"company={company_id}"]
            except Exception:
                pass
            _alembic_command.stamp(cfg, "head")
            logger.info(f"✅ Alembic head stamped (api) for {db_name}")
            return True, "ok"
        except Exception as api_exc:
            api_error = f"alembic api: {api_exc}"
            logger.warning(
                f"Alembic API stamp failed for {db_name}: {api_exc}; "
                "trying subprocess fallback"
            )

        alembic_args = [
            "-c", alembic_ini,
            "-x", f"company={company_id}",
            "stamp", "head",
        ]
        candidate_commands = [
            [sys.executable, "-m", "alembic.config", *alembic_args],
            ["alembic", *alembic_args],
        ]
        errors = [api_error]
        for alembic_cmd in candidate_commands:
            try:
                result = subprocess.run(
                    alembic_cmd,
                    cwd=backend_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                errors.append(f"Command not found: {' '.join(alembic_cmd)}")
                continue
            except Exception as exc:
                errors.append(f"Execution failed for {' '.join(alembic_cmd)}: {exc}")
                continue
            if result.returncode == 0:
                logger.info(f"✅ Alembic head stamped (subprocess) for {db_name}")
                return True, "ok"
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            details = stderr or stdout or "Unknown Alembic error"
            errors.append(f"{' '.join(alembic_cmd)} -> {details}")

        combined_error = " | ".join(errors)
        logger.error(f"❌ Alembic stamp failed for {db_name}: {combined_error}")
        return False, combined_error

    company_engine = None
    try:
        company_engine = create_engine(connection_url, isolation_level="AUTOCOMMIT")
        with company_engine.connect() as conn:
            apply_tenant_schema(conn, currency=currency)

        migration_ok, migration_msg = run_company_alembic_stamp_head()
        if not migration_ok:
            return False, f"فشل ترحيل Alembic: {migration_msg}"

        logger.info(f"✅ Created all tables and stamped Alembic head for {db_name}")
        return True, "تم إنشاء جميع الجداول وتثبيت Alembic head بنجاح"

    except Exception as e:
        logger.error(f"❌ Error creating tables: {str(e)}")
        return False, str(e)
    finally:
        if company_engine is not None:
            company_engine.dispose()



# Country → official currency mapping
COUNTRY_CURRENCY_MAP = {
    "SA": "SAR",
    "SY": "SYP",
    "AE": "AED",
    "EG": "EGP",
    "KW": "KWD",
    "TR": "TRY",
    "JO": "JOD",
    "IQ": "IQD",
    "LB": "LBP",
    "OM": "OMR",
    "BH": "BHD",
    "QA": "QAR",
}

def initialize_company_default_data(company_id: str, admin_username: str, 
                                    admin_email: str, admin_password: str, 
                                    admin_full_name: str, timezone: str = "Asia/Damascus",
                                    currency: str = "SYP", country: str = "SY") -> Tuple[bool, str]:
    """Initialize default data for company"""
    db_name = f"aman_{company_id}"
    connection_url = settings.get_company_database_url(company_id)
    
    try:
        company_engine = create_engine(connection_url)
        hashed_password = hash_password(admin_password)
        
        with company_engine.connect() as conn:
            # Create admin user
            conn.execute(text("""
                INSERT INTO company_users (username, password, email, full_name, role, permissions)
                VALUES (:username, :password, :email, :full_name, 'superuser', :permissions)
            """), {
                "username": admin_username,
                "password": hashed_password,
                "email": admin_email,
                "full_name": admin_full_name,
                "permissions": '{"all": true}'
            })
            
            # Default roles come from the canonical registry used by /api/roles/init-defaults.
            import json
            from routers.roles import DEFAULT_ROLES
            for role_name, role_data in DEFAULT_ROLES.items():
                conn.execute(text("""
                    INSERT INTO roles (role_name, role_name_ar, description, permissions, is_system_role)
                    VALUES (:name, :name_ar, :description, CAST(:permissions AS JSONB), TRUE)
                    ON CONFLICT (role_name) DO UPDATE SET
                        role_name_ar = EXCLUDED.role_name_ar,
                        description = EXCLUDED.description,
                        permissions = EXCLUDED.permissions,
                        is_system_role = TRUE
                """), {
                    "name": role_name,
                    "name_ar": role_data.get("name_ar", role_name),
                    "description": role_data.get("description", ""),
                    "permissions": json.dumps(role_data.get("permissions", [])),
                })
            
            # Default accounts hierarchical structure
            # (account_number, account_code, name, name_en, account_type, parent_index_in_this_list)
            # Level 1
            root_accounts = [
                ("1", "ASSET", "الأصول", "Assets", "asset", None),
                ("2", "LIAB", "الخصوم", "Liabilities", "liability", None),
                ("3", "EQTY", "حقوق الملكية", "Equity", "equity", None),
                ("4", "REV", "الإيرادات", "Revenue", "revenue", None),
                ("5", "EXP", "المصروفات", "Expenses", "expense", None),
            ]
            
            inserted_ids = {}
            for acc in root_accounts:
                result = conn.execute(text("""
                    INSERT INTO accounts (account_number, account_code, name, name_en, account_type, currency)
                    VALUES (:number, :code, :name, :name_en, :type, :currency) RETURNING id
                """), {"number": acc[0], "code": acc[1], "name": acc[2], "name_en": acc[3], "type": acc[4], "currency": currency})
                inserted_ids[acc[0]] = result.fetchone()[0]

            # Level 2 & 3 - Comprehensive "Global" Chart of Accounts
            sub_accounts = [
                # 1. Assets
                ("11", "C-ASSET", "أصول متداولة", "Current Assets", "asset", "1"),
                ("1101", "CASH", "النقد وما في حكمه", "Cash & Equivalents", "asset", "11"),
                ("110101", "BOX", "الصندوق الرئيسي", "Main Box", "asset", "1101"),
                ("110102", "BNK", "البنك", "Bank", "asset", "1101"),
                ("1102", "AR", "العملاء والذمم المدينة", "Accounts Receivable", "asset", "11"),
                ("1103", "INV", "المخزون", "Inventory", "asset", "11"),
                ("110301", "RM-INV", "مخزون المواد الأولية", "Raw Materials Inventory", "asset", "1103"),
                ("110302", "FG-INV", "مخزون الإنتاج التام", "Finished Goods Inventory", "asset", "1103"),
                ("1110", "WIP", "أعمال تحت التشغيل", "Work In Progress", "asset", "11"),
                ("1111", "INT-CO", "حسابات بين الفروع", "Intercompany Accounts", "asset", "11"),
                ("1112", "INV-TRN", "مخزون في الطريق", "Inventory In Transit", "asset", "11"),
                ("1104", "ADV", "سلف وقروض الموظفين", "Employee Loans", "asset", "11"),
                ("1105", "PRE", "مصروفات مدفوعة مقدماً", "Prepaid Expenses", "asset", "11"),
                
                ("12", "F-ASSET", "أصول ثابتة", "Fixed Assets", "asset", "1"),
                ("1201", "MAC", "الآلات والمعدات", "Machinery & Equipment", "asset", "12"),
                ("1202", "VEH", "السيارات ووسائل النقل", "Vehicles", "asset", "12"),
                ("1203", "FUR", "الأثاث والمفروشات", "Furniture", "asset", "12"),
                ("1204", "BLD", "المباني والإنشاءات", "Buildings", "asset", "12"),
                ("1205", "LND", "الأراضي", "Lands", "asset", "12"),
                ("1206", "CMP", "أجهزة حاسوب وأنظمة", "Computers & Systems", "asset", "12"),
                ("1207", "ACC-DEP", "الإهلاك المتراكم", "Accumulated Depreciation", "asset", "12"),

                # Prepayments & Special Current Assets
                ("1106", "PRE-SUP", "مدفوعات مقدمة للموردين", "Prepayments to Suppliers", "asset", "11"),
                ("1107", "VAT-IN-AST", "ضريبة المدخلات", "Input VAT (Receivable)", "asset", "11"),
                ("1108", "CHK-RCV", "شيكات تحت التحصيل", "Checks Under Collection", "asset", "11"),
                ("1109", "NR", "أوراق قبض", "Notes Receivable", "asset", "11"),

                # 2. Liabilities
                ("21", "C-LIAB", "خصوم متداولة", "Current Liabilities", "liability", "2"),
                ("2101", "AP", "الموردين والذمم الدائنة", "Accounts Payable", "liability", "21"),
                ("2102", "ACC", "مصاريف مستحقة", "Accrued Expenses", "liability", "21"),
                ("2104", "UNB-PUR", "مشتريات مستلمة غير مفوترة", "Unbilled Received Purchases", "liability", "2102"),
                ("2103", "VAT", "ضريبة القيمة المضافة", "VAT Payable", "liability", "21"),
                ("210301", "VAT-OUT", "ضريبة المخرجات", "Output VAT", "liability", "2103"),
                ("2105", "CHK-PAY", "شيكات تحت الدفع", "Checks Payable", "liability", "21"),
                ("2106", "GOSI-PAY", "التأمينات الاجتماعية المستحقة", "GOSI Payable", "liability", "21"),
                ("2107", "CUST-DEP", "عربون / دفعات مقدمة من العملاء", "Customer Deposits", "liability", "21"),
                ("2110", "NP", "أوراق دفع", "Notes Payable", "liability", "21"),
                
                ("22", "L-LIAB", "خصوم غير متداولة", "Non-Current Liabilities", "liability", "2"),
                ("2201", "L-LOAN", "قروض طويلة الأجل", "Long Term Loans", "liability", "22"),
                ("2202", "EOS", "مخصص نهاية الخدمة", "End of Service Provision", "liability", "22"),

                # 3. Equity
                ("31", "CAP", "رأس المال", "Capital", "equity", "3"),
                ("32", "RET", "الأرباح المبقاة", "Retained Earnings", "equity", "3"),
                ("33", "CUR", "أرباح العام الحالي", "Current Year Earnings", "equity", "3"),
                ("34", "DRW", "الجارى والمسحوبات", "Owner Withdrawals", "equity", "3"),

                # 4. Revenue
                ("41", "SALE", "إيرادات التشغيل", "Operating Revenue", "revenue", "4"),
                ("4101", "SALE-G", "مبيعات البضائع", "Sales of Goods", "revenue", "41"),
                ("4102", "SALE-S", "إيرادات الخدمات", "Service Revenue", "revenue", "41"),
                ("4103", "SALE-R", "مردودات المبيعات", "Sales Returns", "revenue", "41"),
                ("4104", "SALE-DISC", "خصم مبيعات", "Sales Discount", "revenue", "41"),
                ("42", "O-REV", "إيرادات أخرى", "Other Revenue", "revenue", "4"),
                ("4201", "FX-GAIN", "أرباح فروقات عملة (محققة)", "Realized FX Gain", "revenue", "42"),
                ("4202", "UFX-GAIN", "أرباح فروقات عملة (غير محققة)", "Unrealized FX Gain", "revenue", "42"),

                # 5. Expenses
                ("51", "CGS", "تكلفة البضاعة المباعة", "Cost of Goods Sold", "expense", "5"),
                ("5101", "CGS-G", "تكلفة مبيعات البضائع", "COGS - Goods", "expense", "51"),
                ("5102", "CGS-MFG", "تكلفة التصنيع", "Manufacturing Cost", "expense", "51"),
                ("5103", "LABOR", "تكلفة العمالة المباشرة", "Direct Labor Cost", "expense", "51"),
                ("5104", "MFG-OH", "المصاريف الصناعية العامة", "Manufacturing Overhead", "expense", "51"),
                ("52", "OP-EXP", "المصروفات التشغيلية والإدارية", "Operating Expenses", "expense", "5"),
                ("5201", "SAL", "الرواتب والأجور", "Salaries", "expense", "52"),
                ("5202", "RNT", "مصروف الإيجار", "Rent Expense", "expense", "52"),
                ("5203", "UTL", "الكهرباء والمياه", "Utilities", "expense", "52"),
                ("5204", "COM", "الاتصالات والإنترنت", "Communication", "expense", "52"),
                ("5205", "MNT", "الصيانة", "Maintenance", "expense", "52"),
                ("5206", "GOV", "الرسوم الحكومية", "Government Fees", "expense", "52"),
                ("5207", "MKT", "التسويق والإعلان", "Marketing", "expense", "52"),
                ("5208", "TRV", "مصاريف السفر والتنقل", "Travel Expenses", "expense", "52"),
                ("5209", "GEN-EXP", "مصروفات عمومية", "General Expenses", "expense", "52"),
                ("5210", "GOSI-EXP", "مصروف التأمينات الاجتماعية", "GOSI Expense", "expense", "52"),
                ("5211", "INS", "مصروف التأمين", "Insurance Expense", "expense", "52"),
                ("5212", "CLEAN", "مصروف النظافة", "Cleaning Expense", "expense", "52"),
                ("5213", "STATIONERY", "مصروف القرطاسية", "Stationery Expense", "expense", "52"),
                ("5214", "HOSP", "مصروف الضيافة", "Hospitality Expense", "expense", "52"),
                ("53", "DEP", "الإهلاك", "Depreciation", "expense", "5"),
                ("54", "FIN", "المصروفات المالية والبنكية", "Financial Charges", "expense", "5"),
                ("5401", "BANK-F", "الرسوم البنكية", "Bank Fees", "expense", "54"),
                ("5402", "FX-LOSS", "خسائر فروقات عملة (محققة)", "Realized FX Loss", "expense", "54"),
                ("5403", "UFX-LOSS", "خسائر فروقات عملة (غير محققة)", "Unrealized FX Loss", "expense", "54"),
                ("55", "O-EXP", "مصروفات أخرى", "Other Expenses", "expense", "5"),
                ("5501", "AST-LOSS", "خسائر استبعاد الأصول", "Asset Disposal Loss", "expense", "55"),
                ("5502", "CASH-OS", "فروقات صندوق (زيادة/نقصان)", "Cash Over/Short", "expense", "55"),
                ("5503", "INV-ADJ", "فروقات تسوية المخزون", "Inventory Adjustment", "expense", "55"),

                # ── COA-001: Intangible Assets ──
                ("13", "INTANG", "أصول غير ملموسة", "Intangible Assets", "asset", "1"),
                ("1301", "GOODWILL", "شهرة", "Goodwill", "asset", "13"),
                ("1302", "PATENT", "براءات اختراع وعلامات تجارية", "Patents & Trademarks", "asset", "13"),
                ("1303", "COPYR", "حقوق التأليف والنشر", "Copyrights", "asset", "13"),
                ("1304", "ACC-AMORT", "الإطفاء المتراكم", "Accumulated Amortization", "asset", "13"),
                ("1305", "ROU", "أصل حق الاستخدام", "Right of Use Asset", "asset", "13"),

                # ── COA-002: Tax accounts ──
                ("2108", "WHT-PAY", "ضريبة الاستقطاع", "Withholding Tax Payable", "liability", "21"),
                ("2109", "INC-TAX", "ضريبة الدخل المستحقة", "Income Tax Payable", "liability", "21"),
                ("2111", "ZAKAT", "الزكاة المستحقة", "Zakat Payable", "liability", "21"),
                ("2112", "VAT-SETT", "تسوية ضريبة القيمة المضافة", "VAT Settlement", "liability", "21"),

                # ── COA-003/004: Additional Expenses ──
                ("5215", "LEGAL", "مصروفات قانونية", "Legal Expenses", "expense", "52"),
                ("5216", "AUDIT", "مصروف التدقيق والمراجعة", "Audit Fees", "expense", "52"),
                ("5217", "COMM", "عمولات المبيعات", "Sales Commissions", "expense", "52"),
                ("5218", "PR", "علاقات عامة", "Public Relations", "expense", "52"),

                # ── COA-005: Other Revenue ──
                ("4203", "INT-INC", "فوائد محصلة", "Interest Income", "revenue", "42"),
                ("4204", "DIV-INC", "توزيعات أرباح", "Dividend Income", "revenue", "42"),
                ("4205", "AST-GAIN", "ربح بيع أصول", "Gain on Asset Disposal", "revenue", "42"),
                ("4206", "PUR-DISC", "خصومات مكتسبة", "Purchase Discounts", "revenue", "42"),

                # ── COA-006: HR, Provisions, Prepaid sub-accounts ──
                ("5219", "ALLOW", "بدلات الموظفين", "Employee Allowances", "expense", "52"),
                ("5220", "OVT", "العمل الإضافي", "Overtime Expense", "expense", "52"),
                ("5221", "TERM-EXP", "مكافآت نهاية الخدمة (مصروف)", "Termination Benefits Expense", "expense", "52"),
                ("5222", "LV-EXP", "مصروف الإجازات", "Leave Expense", "expense", "52"),
                ("5223", "BD-EXP", "مصروف ديون معدومة", "Bad Debt Expense", "expense", "52"),
                ("2203", "LV-PROV", "مخصص الإجازات", "Leave Provision", "liability", "22"),
                ("2204", "BD-PROV", "مخصص الديون المعدومة", "Allowance for Doubtful Debts", "liability", "22"),
                ("110501", "PRE-RENT", "إيجار مدفوع مقدماً", "Prepaid Rent", "asset", "1105"),
                ("110502", "PRE-INS", "تأمين مدفوع مقدماً", "Prepaid Insurance", "asset", "1105"),

                # ── Equity: Revaluation Reserve (for GL-007) ──
                ("35", "REVAL", "احتياطي إعادة التقييم", "Revaluation Reserve", "equity", "3"),
            ]

            for acc in sub_accounts:
                parent_id = inserted_ids.get(acc[5])
                result = conn.execute(text("""
                    INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, currency)
                    VALUES (:number, :code, :name, :name_en, :type, :parent_id, :currency) RETURNING id
                """), {"number": acc[0], "code": acc[1], "name": acc[2], "name_en": acc[3], "type": acc[4], "parent_id": parent_id, "currency": currency})
                inserted_ids[acc[0]] = result.fetchone()[0]

            # Flag all parents as header accounts so postings are only allowed
            # on leaf nodes. A parent is any account that appears as
            # parent_id for another row.
            conn.execute(text("""
                UPDATE accounts
                SET is_header = TRUE
                WHERE id IN (SELECT DISTINCT parent_id FROM accounts WHERE parent_id IS NOT NULL)
            """))
            
            # Default settings
            default_currency = currency

            # Default Mappings (GL Account Mapping)
            # We map system roles (keys) to account IDs from the inserted_ids
            # inserted_ids maps account_number (e.g. '1103') to its database ID
            mapping_seeds = [
                # Assets
                ("acc_map_inventory", inserted_ids.get("1103")),  # INV
                ("acc_map_vat_in", inserted_ids.get("1107")),      # VAT-IN (Asset)
                ("acc_map_ar", inserted_ids.get("1102")),         # AR
                ("acc_map_cash_main", inserted_ids.get("110101")), # BOX
                ("acc_map_bank", inserted_ids.get("110102")),      # BNK
                ("acc_map_loans_adv", inserted_ids.get("1104")),   # ADV (Loans)
                ("acc_map_prepaid_exp", inserted_ids.get("1105")), # PRE (Prepaid)
                ("acc_map_prepayment_supplier", inserted_ids.get("1106")), # PRE-SUP
                ("acc_map_checks_receivable", inserted_ids.get("1108")),   # CHK-RCV
                ("acc_map_notes_receivable", inserted_ids.get("1109")),    # NR
                ("acc_map_wip", inserted_ids.get("1110")),           # WIP
                ("acc_map_raw_materials", inserted_ids.get("110301")), # RM-INV
                ("acc_map_finished_goods", inserted_ids.get("110302")),# FG-INV
                ("acc_map_fixed_assets", inserted_ids.get("12")),  # F-ASSET
                ("acc_map_acc_depr", inserted_ids.get("1207")),    # Accumulated Depreciation

                # Liabilities
                ("acc_map_ap", inserted_ids.get("2101")),         # AP
                ("acc_map_vat_out", inserted_ids.get("210301")),   # VAT-OUT
                ("acc_map_accrued_salaries", inserted_ids.get("2102")), # ACC (Accrued)
                ("acc_map_unbilled_purchases", inserted_ids.get("2104")), # UNB-PUR
                ("acc_map_checks_payable", inserted_ids.get("2105")),     # CHK-PAY
                ("acc_map_gosi_payable", inserted_ids.get("2106")),       # GOSI Payable
                ("acc_map_customer_deposits", inserted_ids.get("2107")),  # Customer Deposits
                ("acc_map_notes_payable", inserted_ids.get("2110")),      # NP
                ("acc_map_eos_provision", inserted_ids.get("2202")),      # EOS

                # Revenue
                ("acc_map_sales_rev", inserted_ids.get("4101")),   # SALE-G
                ("acc_map_service_rev", inserted_ids.get("4102")), # SALE-S
                ("acc_map_asset_gain", inserted_ids.get("42")),    # O-REV

                # Cost of Sales / Manufacturing
                ("acc_map_cogs", inserted_ids.get("5101")),          # CGS-G
                ("acc_map_mfg_cogs", inserted_ids.get("5102")),      # CGS-MFG
                ("acc_map_labor_cost", inserted_ids.get("5103")),    # Direct Labor
                ("acc_map_mfg_overhead", inserted_ids.get("5104")),  # Manufacturing Overhead

                # Operating Expenses
                ("acc_map_salaries_exp", inserted_ids.get("5201")),# SAL
                ("acc_map_salaries", inserted_ids.get("5201")),    # Alias for expenses module
                ("acc_map_rent_expense", inserted_ids.get("5202")),     # RNT
                ("acc_map_utilities_expense", inserted_ids.get("5203")), # UTL
                ("acc_map_travel_expense", inserted_ids.get("5208")),    # TRV
                ("acc_map_general_expense", inserted_ids.get("5209")),   # GEN-EXP
                ("acc_map_gosi_expense", inserted_ids.get("5210")),      # GOSI Expense
                ("acc_map_insurance_expense", inserted_ids.get("5211")), # INS

                # Depreciation & Financial
                ("acc_map_depr_exp", inserted_ids.get("53")),      # DEP
                ("acc_map_asset_loss", inserted_ids.get("5501")),  # Asset Disposal Loss
                ("acc_map_cash_over_short", inserted_ids.get("5502")), # POS Cash Over/Short
                ("acc_map_expense_other", inserted_ids.get("55")), # Other Expenses (fallback)

                # Inventory & Intercompany
                ("acc_map_inventory_adjustment", inserted_ids.get("5503")), # Inventory Adjustment
                ("acc_map_intercompany", inserted_ids.get("1111")),         # Intercompany Accounts
                ("acc_map_in_transit", inserted_ids.get("1112")),           # TASK-026: Inventory In Transit
                ("acc_map_fx_difference", inserted_ids.get("5402")),        # FX Difference (Realized Loss)

                # ── COA-001: Intangible Assets ──
                ("acc_map_intangible_assets", inserted_ids.get("13")),
                ("acc_map_acc_amortization", inserted_ids.get("1304")),

                # ── COA-002: Tax accounts ──
                ("acc_map_withholding_tax", inserted_ids.get("2108")),
                ("acc_map_income_tax", inserted_ids.get("2109")),
                ("acc_map_zakat", inserted_ids.get("2111")),
                ("acc_map_vat_settlements", inserted_ids.get("2112")),

                # ── COA-005: Other Revenue ──
                ("acc_map_sales_returns", inserted_ids.get("4103")),
                ("acc_map_sales_discount", inserted_ids.get("4104")),
                ("acc_map_interest_income", inserted_ids.get("4203")),
                ("acc_map_asset_disposal_gain", inserted_ids.get("4205")),
                ("acc_map_purchase_discount", inserted_ids.get("4206")),

                # ── COA-003/004: Additional Expenses ──
                ("acc_map_legal_expense", inserted_ids.get("5215")),
                ("acc_map_audit_expense", inserted_ids.get("5216")),
                ("acc_map_sales_commission", inserted_ids.get("5217")),

                # ── COA-006: HR Provisions & Prepaid ──
                ("acc_map_allowances", inserted_ids.get("5219")),
                ("acc_map_overtime", inserted_ids.get("5220")),
                ("acc_map_termination_benefits", inserted_ids.get("5221")),
                ("acc_map_leave_expense", inserted_ids.get("5222")),
                ("acc_map_bad_debt_expense", inserted_ids.get("5223")),
                ("acc_map_provision_holiday", inserted_ids.get("2203")),
                ("acc_map_provision_doubtful", inserted_ids.get("2204")),
                ("acc_map_prepaid_rent", inserted_ids.get("110501")),
                ("acc_map_prepaid_insurance", inserted_ids.get("110502")),
                ("acc_map_accrued_expenses", inserted_ids.get("2102")),

                # ── GL-007: Revaluation Reserve ──
                ("acc_map_revaluation_reserve", inserted_ids.get("35")),
            ]

            curr_names = {
                "SAR": ("ريال سعودي", "Saudi Riyal", "ر.س"),
                "SYP": ("ليرة سورية", "Syrian Pound", "ل.س"),
                "USD": ("دولار أمريكي", "US Dollar", "$"),
                "EUR": ("يورو", "Euro", "€"),
                "GBP": ("جنيه إسترليني", "British Pound", "£"),
                "AED": ("درهم إماراتي", "UAE Dirham", "د.إ"),
                "KWD": ("دينار كويتي", "Kuwaiti Dinar", "د.ك"),
                "EGP": ("جنيه مصري", "Egyptian Pound", "ج.م"),
                "TRY": ("ليرة تركية", "Turkish Lira", "₺"),
            }
            c_name, c_name_en, c_symbol = curr_names.get(currency, (currency, currency, currency))
            
            conn.execute(text("""
                INSERT INTO currencies (code, name, name_en, symbol, is_base, current_rate)
                VALUES (:code, :name, :name_en, :symbol, TRUE, 1.0)
                ON CONFLICT (code) DO UPDATE SET is_base = TRUE
            """), {"code": currency, "name": c_name, "name_en": c_name_en, "symbol": c_symbol})


            settings_data = [
                ("default_currency", default_currency),
                ("company_country", country),
                ("fiscal_year_start", "01-01"),
                ("invoice_prefix", "INV-"),
                ("journal_prefix", "JE-"),
                ("decimal_places", "2"),
                ("date_format", "YYYY-MM-DD"),
                ("timezone", timezone),
                ("tax.zakat.gregorian_rate", "2.57764"),
            ]
            
            for key, value in settings_data:
                conn.execute(text("""
                    INSERT INTO company_settings (setting_key, setting_value) VALUES (:key, :value)
                """), {"key": key, "value": value})
            
            # Insert Mappings
            for key, val_id in mapping_seeds:
                if val_id:
                    conn.execute(text("""
                        INSERT INTO company_settings (setting_key, setting_value) VALUES (:key, :value)
                        ON CONFLICT (setting_key) DO UPDATE SET setting_value = :value
                    """), {"key": key, "value": str(val_id)})

            # Default branch
            # Map country code to country name and timezone
            country_names = {
                "SA": ("المملكة العربية السعودية", "Saudi Arabia"),
                "SY": ("سوريا", "Syria"),
                "AE": ("الإمارات", "United Arab Emirates"),
                "EG": ("مصر", "Egypt"),
                "KW": ("الكويت", "Kuwait"),
                "TR": ("تركيا", "Turkey"),
            }
            country_ar, country_en = country_names.get(country, (country, country))
            branch_result = conn.execute(text("""
                INSERT INTO branches (branch_code, branch_name, branch_name_en, country, country_code, default_currency, is_default, is_active)
                VALUES ('BR001', 'الفرع الرئيسي', 'Main Branch', :country_name, :country_code, :currency, TRUE, TRUE)
                RETURNING id
            """), {"country_name": country_ar, "country_code": country, "currency": currency}).fetchone()
            branch_id = branch_result[0]

            # Link admin user to branch
            user_id_result = conn.execute(text("SELECT id FROM company_users WHERE username = :u"), {"u": admin_username}).fetchone()
            if user_id_result:
                conn.execute(text("""
                    INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid)
                """), {"uid": user_id_result[0], "bid": branch_id})

            # Create default party_sites and party_site_balances tables
            # (These are created by the schema, but we ensure they exist)
            # Note: party_sites are created dynamically when parties are created
            # The default party (admin user) gets a site automatically
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS party_sites (
                    id SERIAL PRIMARY KEY,
                    party_id INTEGER NOT NULL REFERENCES parties(id),
                    site_name VARCHAR(255) NOT NULL,
                    site_name_en VARCHAR(255),
                    country VARCHAR(100),
                    country_code VARCHAR(5),
                    currency VARCHAR(10) NOT NULL,
                    contact_name VARCHAR(255),
                    phone VARCHAR(50),
                    email VARCHAR(255),
                    address TEXT,
                    city VARCHAR(100),
                    tax_number VARCHAR(50),
                    bank_account VARCHAR(100),
                    payment_terms INTEGER DEFAULT 30,
                    is_default BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS party_site_balances (
                    id SERIAL PRIMARY KEY,
                    company_branch_id INTEGER NOT NULL REFERENCES branches(id),
                    party_site_id INTEGER NOT NULL REFERENCES party_sites(id),
                    account_type VARCHAR(20) NOT NULL CHECK (account_type IN ('payable', 'receivable')),
                    currency VARCHAR(10) NOT NULL,
                    balance DECIMAL(18,4) DEFAULT 0,
                    gl_account_id INTEGER REFERENCES accounts(id),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company_branch_id, party_site_id, account_type, currency)
                )
            """))

            # Default warehouse
            conn.execute(text("""
                INSERT INTO warehouses (warehouse_code, warehouse_name, warehouse_name_en, branch_id, is_default, is_active)
                VALUES ('WH001', 'المستودع الرئيسي', 'Main Warehouse', :bid, TRUE, TRUE)
            """), {"bid": branch_id})

            
            # Default product units
            units = [
                ("PC", "قطعة", "Piece", "pcs"),
                ("KG", "كيلوغرام", "Kilogram", "kg"),
                ("LT", "لتر", "Liter", "lt"),
                ("M", "متر", "Meter", "m"),
                ("BOX", "صندوق", "Box", "box"),
            ]
            for unit in units:
                conn.execute(text("""
                    INSERT INTO product_units (unit_code, unit_name, unit_name_en, abbreviation)
                    VALUES (:code, :name, :name_en, :abbr)
                """), {"code": unit[0], "name": unit[1], "name_en": unit[2], "abbr": unit[3]})
            
            # Tax rates are entered manually by the user — no auto-seed.

            # ── Tax Compliance: Seed tax_regimes for the company's country ───
            _tax_regimes = {
                "SA": [
                    ("vat", "ضريبة القيمة المضافة", "Value Added Tax (VAT)", 15.00, True, "all", "quarterly"),
                    ("zakat", "الزكاة", "Zakat", 2.50, True, "saudi_owned", "annual"),
                    ("income_tax", "ضريبة الدخل", "Corporate Income Tax", 20.00, True, "foreign_owned", "annual"),
                    ("withholding", "ضريبة الاستقطاع", "Withholding Tax", 5.00, False, "cross_border", "monthly"),
                ],
                "SY": [
                    ("income_tax", "ضريبة الدخل", "Income Tax", 22.00, True, "all", "annual"),
                    ("salary_tax", "ضريبة الرواتب والأجور", "Salary Tax", 0.00, True, "all", "monthly"),
                    ("stamp_duty", "رسوم الطوابع", "Stamp Duty", 0.60, False, "contracts", "per_transaction"),
                ],
                "AE": [
                    ("vat", "ضريبة القيمة المضافة", "Value Added Tax (VAT)", 5.00, True, "all", "quarterly"),
                    ("corporate_tax", "ضريبة الشركات", "Corporate Tax", 9.00, True, "all", "annual"),
                ],
                "EG": [
                    ("vat", "ضريبة القيمة المضافة", "Value Added Tax (VAT)", 14.00, True, "all", "monthly"),
                    ("income_tax", "ضريبة الدخل", "Corporate Income Tax", 22.50, True, "all", "annual"),
                ],
                "JO": [
                    ("sales_tax", "ضريبة المبيعات", "General Sales Tax", 16.00, True, "all", "monthly"),
                    ("income_tax", "ضريبة الدخل", "Corporate Income Tax", 20.00, True, "all", "annual"),
                ],
                "KW": [
                    ("income_tax", "ضريبة الدخل", "Corporate Income Tax", 15.00, True, "foreign_owned", "annual"),
                    ("zakat", "الزكاة", "Zakat (NLST)", 1.00, True, "all", "annual"),
                ],
                "OM": [
                    ("vat", "ضريبة القيمة المضافة", "Value Added Tax (VAT)", 5.00, True, "all", "quarterly"),
                ],
                "TR": [
                    ("kdv", "ضريبة القيمة المضافة (KDV)", "Value Added Tax (KDV)", 20.00, True, "all", "monthly"),
                ],
                "IQ": [
                    ("sales_tax", "ضريبة المبيعات", "Sales Tax", 15.00, True, "all", "monthly"),
                ],
                "LB": [
                    ("vat", "ضريبة القيمة المضافة", "Value Added Tax (VAT)", 11.00, True, "all", "monthly"),
                ],
                "YE": [
                    ("exempt", "معفاة", "Exempt (War Economy)", 0.00, False, "all", "annual"),
                ],
            }
            country_regimes = _tax_regimes.get(country, _tax_regimes.get("SA", []))
            for reg in country_regimes:
                conn.execute(text("""
                    INSERT INTO tax_regimes (country_code, tax_type, name_ar, name_en, default_rate, is_required, applies_to, filing_frequency)
                    VALUES (:cc, :type, :ar, :en, :rate, :req, :applies, :freq)
                    ON CONFLICT (country_code, tax_type) DO NOTHING
                """), {"cc": country, "type": reg[0], "ar": reg[1], "en": reg[2], "rate": reg[3], "req": reg[4], "applies": reg[5], "freq": reg[6]})

            # Company tax settings for the main country
            conn.execute(text("""
                INSERT INTO company_tax_settings (country_code) VALUES (:cc)
                ON CONFLICT (country_code) DO NOTHING
            """), {"cc": country})

            # Tax rates are entered manually by the user via the UI.
            # No auto-seed for tax_rates.

            # ── WHT Rules: Country-specific withholding tax rules ──────────
            _wht_rules_seed = [
                # (country_code, payment_type, rate, description)
                # Turkey
                ("TR", "services", 0.2000, "Turkey WHT on services"),
                ("TR", "rent", 0.2000, "Turkey WHT on rent"),
                ("TR", "dividends", 0.1500, "Turkey WHT on dividends"),
                # Egypt (verify/complete existing)
                ("EG", "services_resident", 0.0050, "Egypt WHT on resident services"),
                ("EG", "services_non_resident", 0.2000, "Egypt WHT on non-resident services"),
                ("EG", "rent", 0.1000, "Egypt WHT on rent"),
                # Jordan
                ("JO", "services", 0.0500, "Jordan WHT on services"),
                ("JO", "rent", 0.0500, "Jordan WHT on rent"),
                ("JO", "dividends", 0.1000, "Jordan WHT on dividends"),
            ]
            for wr in _wht_rules_seed:
                conn.execute(text("""
                    INSERT INTO wht_rules (country_code, payment_type, rate, description, is_active)
                    VALUES (:cc, :pt, :rate, :desc, TRUE)
                    ON CONFLICT DO NOTHING
                """), {"cc": wr[0], "pt": wr[1], "rate": wr[2], "desc": wr[3]})

            # ── Tax Classifications: Product-type-based tax mapping ────────
            _classifications_seed = [
                # (code, name_ar, name_en, description)
                ("STANDARD",      "بضاعة عادية",              "Standard Goods",      "General goods subject to standard tax rate"),
                ("MEDICINE",      "أدوية ومستلزمات طبية",     "Medicine & Medical",  "Pharmaceutical products and medical supplies"),
                ("BASIC_FOOD",    "مواد غذائية أساسية",        "Basic Food",          "Unprocessed basic food staples"),
                ("PROCESSED_FOOD","مواد غذائية مصنعة",        "Processed Food",      "Manufactured and processed food products"),
                ("TOBACCO",       "منتجات التبغ",              "Tobacco Products",    "Cigarettes, tobacco, and related products"),
                ("SERVICES",      "خدمات",                     "Services",            "Professional and general services"),
                ("DIGITAL",       "خدمات رقمية",              "Digital Services",    "Software, SaaS, and digital services"),
                ("EXEMPT",        "معفى",                      "Exempt",              "Products exempt from all taxes"),
                ("ZERO_RATED",    "صفري",                      "Zero Rated",          "Products taxed at 0% rate"),
            ]
            for cl in _classifications_seed:
                conn.execute(text("""
                    INSERT INTO tax_classifications (code, name_ar, name_en, description)
                    VALUES (:code, :ar, :en, :desc)
                    ON CONFLICT (code) DO NOTHING
                """), {"code": cl[0], "ar": cl[1], "en": cl[2], "desc": cl[3]})

            # Tax classification rates are linked manually by the user via the UI.
            # No auto-seed for classification-to-country rate links.

            # Default Costing Policy
            conn.execute(text("""
                INSERT INTO costing_policies (policy_name, policy_type, description, is_active, created_by)
                VALUES ('Default Global WAC', 'global_wac', 'Standard unified cost across all branches', TRUE, 1)
            """))
            
            conn.commit()

        # DB-015: Populate central user index for fast login lookup
        try:
            system_url = settings.DATABASE_URL
            system_engine = create_engine(system_url)
            with system_engine.connect() as sys_conn:
                sys_conn.execute(text("""
                    INSERT INTO system_user_index (username, company_id, is_active)
                    VALUES (:username, :company_id, true)
                    ON CONFLICT (username, company_id) DO UPDATE SET is_active = true, updated_at = CURRENT_TIMESTAMP
                """), {"username": admin_username, "company_id": company_id})
                sys_conn.commit()
            system_engine.dispose()
        except Exception as idx_err:
            logger.warning(f"⚠️ Could not populate user index: {idx_err}")

        logger.info(f"✅ Initialized default data for {db_name}")
        return True, "تم تهيئة البيانات الافتراضية"
        
    except Exception as e:
        logger.error(f"❌ Error initializing data: {str(e)}")
        return False, str(e)
    finally:
        company_engine.dispose()
