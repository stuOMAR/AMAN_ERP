"""
Shared fixtures and helpers for all accounting tests.
Uses the seeded database (aman_7b4e2b6b) from reset_and_reseed.py.
"""
import pytest
import sys
import os
import psycopg2
from decimal import Decimal

# إضافة مسار backend لكي يتمكن pytest من استيراد الوحدات
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# إضافة مسار tests لكي يتمكن من استيراد helpers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════
# 🔐 PLAT-TEST-02: توليد ADMIN_PASSWORD_HASH ديناميكياً قبل تحميل التطبيق
# يضمن أن تكون كلمة مرور الأدمن في الاختبارات متطابقة مع الـ hash المستخدم
# في auth.py، بغض النظر عن حالة .env.
# ═══════════════════════════════════════════════════════════════
_TEST_ADMIN_PW = os.environ.get("AMAN_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("AMAN_ADMIN_PASSWORD", _TEST_ADMIN_PW)
try:
    import bcrypt as _bcrypt
    os.environ["ADMIN_PASSWORD_HASH"] = _bcrypt.hashpw(
        _TEST_ADMIN_PW.encode("utf-8"), _bcrypt.gensalt(rounds=4)
    ).decode("utf-8")
except Exception:  # pragma: no cover - bcrypt always available in test env
    pass

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from database import get_db_connection  # noqa: E402

DB_URL = os.environ.get(
    "AMAN_TEST_DB_URL",
    "postgresql://aman:YourPassword123%21%40%23@localhost:5432/aman_d24b1b1c",
)

TOLERANCE = Decimal("0.01")

# ═══════════════════════════════════════════════════════════════
# 🔧 إعدادات الاختبار
# ═══════════════════════════════════════════════════════════════

# System admin credentials
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = _TEST_ADMIN_PW

# Company user credentials (for API tests that need company_id)
TEST_COMPANY_USERNAME = os.environ.get("AMAN_TEST_USER", "bbbb")
TEST_COMPANY_PASSWORD = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
TEST_COMPANY_ID = "d24b1b1c"


# ═══════════════════════════════════════════════════════════════
# 📦 Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def client():
    """TestClient للتطبيق - يُستخدم طوال الجلسة"""
    # نستخدم localhost لتجنب اعادة التوجيه من HTTPSRedirectMiddleware
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    """توكن مستخدم الشركة (superuser) - لتنفيذ جميع العمليات"""
    # نحاول أولاً تسجيل الدخول كمستخدم شركة (superuser)
    response = client.post(
        "/api/auth/login",
        data={
            "username": TEST_COMPANY_USERNAME,
            "password": TEST_COMPANY_PASSWORD,
            "grant_type": "password",
            "company_code": TEST_COMPANY_ID
        }
    )
    if response.status_code == 200:
        data = response.json()
        if data.get("company_id"):
            return data["access_token"]

    # إذا فشل، نحاول بمستخدم admin النظام
    response = client.post(
        "/api/auth/login",
        data={
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
            "grant_type": "password"
        }
    )
    if response.status_code != 200:
        pytest.skip(f"لا يمكن تسجيل الدخول: {response.status_code} - {response.text}")

    data = response.json()
    return data["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """Headers مع توكن المدير"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def company_info(client, admin_headers):
    """معلومات الشركة الحالية"""
    response = client.get("/api/auth/me", headers=admin_headers)
    if response.status_code != 200:
        pytest.skip("لا يمكن الحصول على معلومات المستخدم")
    return response.json()


@pytest.fixture(scope="session")
def company_id(company_info):
    """معرف الشركة"""
    cid = company_info.get("company_id")
    if not cid:
        pytest.skip("لا يوجد company_id")
    return cid


@pytest.fixture(scope="session")
def base_currency(client, admin_headers):
    """العملة الأساسية للشركة - يتم جلبها ديناميكياً من API"""
    response = client.get("/api/auth/me", headers=admin_headers)
    if response.status_code == 200:
        data = response.json()
        return data.get("currency", "SYP")
    return "SYP"


@pytest.fixture(scope="session")
def company_user_token(client):
    """
    توكن مستخدم شركة عادي (ليس system admin).
    """
    response = client.post(
        "/api/auth/login",
        data={
            "username": TEST_COMPANY_USERNAME,
            "password": TEST_COMPANY_PASSWORD,
            "grant_type": "password"
        }
    )
    if response.status_code != 200:
        pytest.skip("لا يمكن تسجيل دخول مستخدم الشركة")
    data = response.json()
    if not data.get("company_id"):
        pytest.skip("المستخدم ليس مرتبط بشركة")
    return data["access_token"]


@pytest.fixture(scope="session")
def company_headers(company_user_token):
    """Headers مع توكن مستخدم الشركة"""
    return {"Authorization": f"Bearer {company_user_token}"}


@pytest.fixture
def db_connection(company_id):
    """اتصال بقاعدة بيانات الشركة للتحقق المباشر"""
    conn = get_db_connection(company_id)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def db_conn():
    """Single DB connection for the entire test session (read-only tests)."""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def db(db_conn):
    """Per-test fixture that rolls back after each test."""
    cur = db_conn.cursor()
    yield cur
    db_conn.rollback()


@pytest.fixture(scope="session")
def rw_db():
    """Read-write connection that commits. Use for mutation tests only."""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# 🛠 Helper Functions
# ═══════════════════════════════════════════════════════════════

def get_account_id(cur, code):
    """Get account ID by account_code."""
    cur.execute("SELECT id FROM accounts WHERE account_code = %s", (code,))
    row = cur.fetchone()
    return row[0] if row else None


def get_account_balance(cur, code):
    """Get account balance by code."""
    cur.execute("SELECT COALESCE(balance, 0) FROM accounts WHERE account_code = %s", (code,))
    row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal("0")


def get_gl_balance(cur, account_code):
    """Calculate account balance from journal_lines (ground truth)."""
    cur.execute("""
        SELECT COALESCE(SUM(jl.debit), 0) as total_debit,
               COALESCE(SUM(jl.credit), 0) as total_credit
        FROM journal_lines jl
        JOIN accounts a ON a.id = jl.account_id
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        WHERE a.account_code = %s AND je.status = 'posted'
    """, (account_code,))
    row = cur.fetchone()
    total_debit = Decimal(str(row[0]))
    total_credit = Decimal(str(row[1]))

    cur.execute("SELECT account_type FROM accounts WHERE account_code = %s", (account_code,))
    acc_type = cur.fetchone()[0]

    if acc_type in ('asset', 'expense'):
        return total_debit - total_credit
    else:
        return total_credit - total_debit


def get_trial_balance(cur):
    """Get total debits and credits from all posted journal entries."""
    cur.execute("""
        SELECT COALESCE(SUM(jl.debit), 0), COALESCE(SUM(jl.credit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        WHERE je.status = 'posted'
    """)
    row = cur.fetchone()
    return Decimal(str(row[0])), Decimal(str(row[1]))


def get_treasury_balance(cur, treasury_id):
    """Get treasury account current balance."""
    cur.execute("SELECT COALESCE(current_balance, 0) FROM treasury_accounts WHERE id = %s", (treasury_id,))
    row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal("0")


def count_rows(cur, table, condition="1=1", params=None):
    """Count rows in a table with optional condition."""
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition}", params or ())
    return cur.fetchone()[0]


def get_invoice(cur, invoice_number, invoice_type='sales'):
    """Get invoice by number and type."""
    cur.execute("""
        SELECT * FROM invoices WHERE invoice_number = %s AND invoice_type = %s
    """, (invoice_number, invoice_type))
    row = cur.fetchone()
    if not row:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def get_je_by_reference(cur, reference):
    """Get journal entry and its lines by reference."""
    cur.execute("""
        SELECT je.id, je.entry_number, je.description, je.status
        FROM journal_entries je
        WHERE je.reference = %s AND je.status = 'posted'
    """, (reference,))
    je_row = cur.fetchone()
    if not je_row:
        return None, []
    je_id = je_row[0]
    cur.execute("""
        SELECT jl.account_id, a.account_code, a.name, jl.debit, jl.credit, jl.description
        FROM journal_lines jl
        JOIN accounts a ON a.id = jl.account_id
        WHERE jl.journal_entry_id = %s
        ORDER BY jl.id
    """, (je_id,))
    lines = []
    for r in cur.fetchall():
        lines.append({
            "account_id": r[0], "account_code": r[1], "account_name": r[2],
            "debit": Decimal(str(r[3])), "credit": Decimal(str(r[4])), "description": r[5]
        })
    return {
        "id": je_id, "entry_number": je_row[1],
        "description": je_row[2], "status": je_row[3]
    }, lines
