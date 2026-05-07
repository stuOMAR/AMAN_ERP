#!/usr/bin/env python3
"""
AMAN ERP - Master Data Seed Script
===================================
يُدخل جميع البيانات الرئيسية عبر API لكي يكون النظام جاهزاً للاستخدام.

الاستخدام:
    python scripts/seed.py                          # القيم الافتراضية
    python scripts/seed.py --url http://localhost:8000 --company-code XXXX

المتطلبات:
    pip install requests
"""

import argparse
import json
import sys
import time
from typing import Optional

import requests

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

DEFAULT_URL = "http://localhost:8000"
COMPANY_CODE = "9d08756c"
COMPANY_USER = "omar"
COMPANY_PASS = "As123321"
COMPANY_NAME = "الخليج القابضة"
COMPANY_EMAIL = "info@gulf-holding.example"

# ═══════════════════════════════════════════════════════════════
# API Client
# ═══════════════════════════════════════════════════════════════

class AmanClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.refs: dict[str, int] = {}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, username: str, password: str, company_code: str = "") -> str:
        data = {
            "username": username,
            "password": password,
            "grant_type": "password",
        }
        if company_code:
            data["company_code"] = company_code
        res = self.session.post(
            f"{self.base_url}/api/auth/login",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        res.raise_for_status()
        body = res.json()
        self.token = body["access_token"]
        return self.token

    def get(self, path: str) -> dict:
        res = self.session.get(f"{self.base_url}{path}", headers=self._headers())
        res.raise_for_status()
        return res.json()

    def post(self, path: str, body: dict) -> dict:
        res = self.session.post(
            f"{self.base_url}{path}", json=body, headers=self._headers()
        )
        if not res.ok:
            print(f"  ✗ POST {path} → {res.status_code}: {res.text[:300]}")
            res.raise_for_status()
        return res.json()

    def put(self, path: str, body: dict) -> dict:
        res = self.session.put(
            f"{self.base_url}{path}", json=body, headers=self._headers()
        )
        res.raise_for_status()
        return res.json()


# ═══════════════════════════════════════════════════════════════
# Seed Data
# ═══════════════════════════════════════════════════════════════

COMPANY_DATA = {
    "company_name": "الخليج القابضة",
    "company_name_en": "Gulf Holding",
    "email": "info@gulf-holding.example",
    "country": "SA",
    "currency": "SAR",
    "timezone": "Asia/Riyadh",
    "commercial_registry": "1010999988",
    "tax_number": "300000000000003",
    "admin_username": "gulf.admin",
    "admin_email": "admin@gulf-holding.example",
    "admin_full_name": "مدير نظام الخليج القابضة",
    "admin_password": "P@ssw0rd!2026",
}

CURRENCIES = [
    {"ref": "currency:SAR", "code": "SAR", "name": "ريال سعودي", "name_en": "Saudi Riyal", "symbol": "ر.س", "is_base": True, "current_rate": 1.0},
    {"ref": "currency:EGP", "code": "EGP", "name": "جنيه مصري", "name_en": "Egyptian Pound", "symbol": "ج.م", "is_base": False, "current_rate": 0.076},
    {"ref": "currency:AED", "code": "AED", "name": "درهم إماراتي", "name_en": "UAE Dirham", "symbol": "د.إ", "is_base": False, "current_rate": 1.021},
    {"ref": "currency:USD", "code": "USD", "name": "دولار أمريكي", "name_en": "US Dollar", "symbol": "$", "is_base": False, "current_rate": 3.75},
]

EXCHANGE_RATES = [
    {"currency_ref": "currency:EGP", "rate": 0.076, "rate_date": "2026-05-04", "source": "manual"},
    {"currency_ref": "currency:AED", "rate": 1.021, "rate_date": "2026-05-04", "source": "manual"},
    {"currency_ref": "currency:USD", "rate": 3.75, "rate_date": "2026-05-04", "source": "manual"},
]

BRANCHES = [
    {"ref": "branch:riyadh", "branch_code": "RUH-HQ", "branch_name": "السعودية - الفرع الرئيسي الرياض", "branch_name_en": "Saudi Arabia - Riyadh HQ", "city": "الرياض", "country": "Saudi Arabia", "country_code": "SA", "default_currency": "SAR", "phone": "+966112220000", "email": "riyadh@gulf-holding.example", "is_default": True},
    {"ref": "branch:cairo", "branch_code": "CAI", "branch_name": "مصر - فرع القاهرة", "branch_name_en": "Egypt - Cairo Branch", "city": "القاهرة", "country": "Egypt", "country_code": "EG", "default_currency": "EGP", "phone": "+2022220000", "email": "cairo@gulf-holding.example"},
    {"ref": "branch:dubai", "branch_code": "DXB", "branch_name": "الإمارات - فرع دبي", "branch_name_en": "UAE - Dubai Branch", "city": "دبي", "country": "United Arab Emirates", "country_code": "AE", "default_currency": "AED", "phone": "+97142220000", "email": "dubai@gulf-holding.example"},
]

COMPANY_SETTINGS = [
    {"setting_key": "default_currency", "setting_value": "SAR"},
    {"setting_key": "reporting_currency", "setting_value": "SAR"},
    {"setting_key": "invoice_prefix", "setting_value": "GH-SINV"},
    {"setting_key": "journal_prefix", "setting_value": "GH-JE"},
    {"setting_key": "timezone", "setting_value": "Asia/Riyadh"},
]

ACCOUNTS = [
    # الأصول
    {"ref": "account:assets", "account_number": "1000", "name": "الأصول", "account_type": "asset", "is_header": True, "currency": "SAR"},
    {"ref": "account:cash_equiv", "account_number": "1101", "name": "النقدية وما في حكمها", "account_type": "asset", "parent_ref": "account:assets", "is_header": True, "currency": "SAR"},
    {"ref": "account:cash", "account_number": "1110", "name": "الصندوق", "account_type": "asset", "parent_ref": "account:cash_equiv", "currency": "SAR"},
    {"ref": "account:banks", "account_number": "1120", "name": "البنوك", "account_type": "asset", "parent_ref": "account:cash_equiv", "currency": "SAR"},
    {"ref": "account:ar", "account_number": "1210", "name": "ذمم العملاء", "account_type": "asset", "parent_ref": "account:assets", "currency": "SAR"},
    {"ref": "account:inventory", "account_number": "1310", "name": "المخزون", "account_type": "asset", "parent_ref": "account:assets", "currency": "SAR"},
    # الالتزامات
    {"ref": "account:liabilities", "account_number": "2000", "name": "الالتزامات", "account_type": "liability", "is_header": True},
    {"ref": "account:ap", "account_number": "2110", "name": "ذمم الموردين", "account_type": "liability", "parent_ref": "account:liabilities"},
    {"ref": "account:vat_payable", "account_number": "2310", "name": "ضريبة مستحقة", "account_type": "liability", "parent_ref": "account:liabilities"},
    # حقوق الملكية
    {"ref": "account:equity", "account_number": "3000", "name": "حقوق الملكية", "account_type": "equity", "is_header": True},
    {"ref": "account:capital_parent", "account_number": "31", "name": "رأس المال", "account_type": "equity", "parent_ref": "account:equity", "is_header": True, "currency": "SAR"},
    {"ref": "account:capital_sar", "account_number": "3101", "name": "رأس المال - ريال سعودي", "account_type": "equity", "parent_ref": "account:capital_parent", "currency": "SAR"},
    {"ref": "account:capital_egp", "account_number": "3102", "name": "رأس المال - جنيه مصري", "account_type": "equity", "parent_ref": "account:capital_parent", "currency": "EGP"},
    {"ref": "account:capital_aed", "account_number": "3103", "name": "رأس المال - درهم إماراتي", "account_type": "equity", "parent_ref": "account:capital_parent", "currency": "AED"},
    # الإيرادات
    {"ref": "account:revenue", "account_number": "4000", "name": "الإيرادات", "account_type": "revenue", "is_header": True},
    {"ref": "account:sales", "account_number": "4100", "name": "مبيعات", "account_type": "revenue", "parent_ref": "account:revenue"},
    # المصروفات
    {"ref": "account:expenses", "account_number": "5000", "name": "المصروفات", "account_type": "expense", "is_header": True},
    {"ref": "account:salary_exp", "account_number": "5110", "name": "مصروف رواتب", "account_type": "expense", "parent_ref": "account:expenses"},
    {"ref": "account:cogs", "account_number": "5200", "name": "تكلفة بضاعة مباعة", "account_type": "expense", "parent_ref": "account:expenses"},
]

TREASURY_ACCOUNTS = [
    {"ref": "treasury:riyadh_bank", "name": "بنك الرياض الرئيسي", "name_en": "Riyad Bank Main", "account_type": "bank", "currency": "SAR", "branch_ref": "branch:riyadh", "bank_name": "Riyad Bank", "account_number": "100200300", "opening_balance": 500000, "allow_overdraft": False},
    {"ref": "treasury:riyadh_cash", "name": "صندوق الرياض", "name_en": "Riyad Cash Box", "account_type": "cash", "currency": "SAR", "branch_ref": "branch:riyadh", "opening_balance": 25000},
    {"ref": "treasury:cairo_bank", "name": "بنك القاهرة", "name_en": "CIB Cairo", "account_type": "bank", "currency": "EGP", "branch_ref": "branch:cairo", "bank_name": "CIB", "account_number": "EG100200", "opening_balance": 300000},
    {"ref": "treasury:dubai_bank", "name": "بنك دبي", "name_en": "Emirates NBD", "account_type": "bank", "currency": "AED", "branch_ref": "branch:dubai", "bank_name": "Emirates NBD", "account_number": "AE100200", "opening_balance": 220000},
]

DEPARTMENTS = [
    {"ref": "dept:executive", "department_name": "الإدارة التنفيذية", "branch_ref": "branch:riyadh"},
    {"ref": "dept:finance", "department_name": "المالية", "branch_ref": "branch:riyadh"},
    {"ref": "dept:sales", "department_name": "المبيعات", "branch_ref": "branch:riyadh"},
    {"ref": "dept:hr", "department_name": "الموارد البشرية", "branch_ref": "branch:riyadh"},
    {"ref": "dept:warehouse", "department_name": "المستودعات", "branch_ref": "branch:dubai"},
    {"ref": "dept:projects", "department_name": "المشاريع", "branch_ref": "branch:riyadh"},
]

POSITIONS = [
    {"ref": "pos:ceo", "position_name": "مدير تنفيذي", "position_title": "مدير تنفيذي"},
    {"ref": "pos:branch_manager", "position_name": "مدير فرع", "position_title": "مدير فرع"},
    {"ref": "pos:finance_manager", "position_name": "مدير مالي", "position_title": "مدير مالي"},
    {"ref": "pos:chief_accountant", "position_name": "رئيس حسابات", "position_title": "رئيس حسابات"},
    {"ref": "pos:accountant", "position_name": "محاسب", "position_title": "محاسب"},
    {"ref": "pos:sales_supervisor", "position_name": "مشرف مبيعات", "position_title": "مشرف مبيعات"},
    {"ref": "pos:cashier", "position_name": "كاشير", "position_title": "كاشير"},
    {"ref": "pos:hr_manager", "position_name": "مدير موارد بشرية", "position_title": "مدير موارد بشرية"},
    {"ref": "pos:warehouse_keeper", "position_name": "أمين مستودع", "position_title": "أمين مستودع"},
    {"ref": "pos:auditor", "position_name": "مراجع داخلي", "position_title": "مراجع داخلي"},
]

WAREHOUSES = [
    {"ref": "wh:riyadh", "code": "WH-RUH", "name": "مستودع الرياض الرئيسي", "branch_ref": "branch:riyadh", "location": "الرياض - السلي", "is_default": True},
    {"ref": "wh:cairo", "code": "WH-CAI", "name": "مستودع القاهرة", "branch_ref": "branch:cairo", "location": "القاهرة - مدينة نصر"},
    {"ref": "wh:dubai", "code": "WH-DXB", "name": "مستودع دبي", "branch_ref": "branch:dubai", "location": "دبي - جبل علي"},
]

PRODUCT_CATEGORIES = [
    {"ref": "cat:electronics", "name": "إلكترونيات", "code": "ELEC"},
    {"ref": "cat:services", "name": "خدمات", "code": "SERV"},
]

PRODUCTS = [
    {"ref": "prod:tablet", "item_code": "GH-TAB-10", "item_name": "جهاز لوحي 10 بوصة", "item_type": "product", "unit": "قطعة", "selling_price": 1200, "buying_price": 800, "tax_rate": 15, "has_serial_tracking": True, "category_ref": "cat:electronics"},
    {"ref": "prod:scanner", "item_code": "GH-SCN-01", "item_name": "قارئ باركود", "item_type": "product", "unit": "قطعة", "selling_price": 450, "buying_price": 280, "tax_rate": 15, "category_ref": "cat:electronics"},
    {"ref": "prod:implementation", "item_code": "GH-SRV-IMPL", "item_name": "خدمة تطبيق نظام", "item_type": "service", "unit": "ساعة", "selling_price": 350, "buying_price": 0, "tax_rate": 15, "category_ref": "cat:services"},
]

CUSTOMERS = [
    {"ref": "party:riyadh_customer", "name": "شركة نجد للتجزئة", "name_en": "Najd Retail Co.", "branch_ref": "branch:riyadh", "currency": "SAR", "tax_number": "300111111100003", "credit_limit": 250000, "payment_terms": 45, "phone": "+966112000001"},
    {"ref": "party:cairo_customer", "name": "دلتا ماركت", "name_en": "Delta Market", "branch_ref": "branch:cairo", "currency": "EGP", "tax_number": "123456789", "credit_limit": 500000, "payment_terms": 30, "phone": "+20222000001"},
    {"ref": "party:dubai_customer", "name": "Dubai Retail LLC", "name_en": "Dubai Retail LLC", "branch_ref": "branch:dubai", "currency": "AED", "tax_number": "1234567890", "credit_limit": 300000, "payment_terms": 30, "phone": "+97142000001"},
]

SUPPLIERS = [
    {"ref": "party:global_supplier", "name": "Gulf Supply FZCO", "name_en": "Gulf Supply FZCO", "branch_ref": "branch:dubai", "currency": "AED", "tax_number": "9876543210", "phone": "+97143000001"},
]

EMPLOYEES = [
    {
        "ref": "emp:ceo", "first_name": "سالم", "last_name": "الغامدي", "email": "salem.g@gulf-holding.example",
        "phone": "+966500000001", "hire_date": "2021-01-01", "salary": 65000, "currency": "SAR",
        "department_name": "الإدارة التنفيذية", "position_title": "مدير تنفيذي",
        "create_user": True, "username": "salem.ceo", "password": COMPANY_PASS, "role": "ceo",
        "allowed_branch_refs": ["branch:riyadh", "branch:cairo", "branch:dubai"],
    },
    {
        "ref": "emp:finance_manager", "first_name": "نورة", "last_name": "القحطاني", "email": "noura.q@gulf-holding.example",
        "phone": "+966500000002", "hire_date": "2021-03-01", "salary": 42000, "currency": "SAR",
        "department_name": "المالية", "position_title": "مدير مالي",
        "create_user": True, "username": "noura.finance", "password": COMPANY_PASS, "role": "finance_manager",
        "allowed_branch_refs": ["branch:riyadh", "branch:cairo", "branch:dubai"],
    },
    {
        "ref": "emp:chief_accountant", "first_name": "ماجد", "last_name": "الدوسري", "email": "majed.d@gulf-holding.example",
        "phone": "+966500000003", "hire_date": "2022-02-01", "salary": 30000, "currency": "SAR",
        "department_name": "المالية", "position_title": "رئيس حسابات",
        "create_user": True, "username": "majed.chief", "password": COMPANY_PASS, "role": "accountant",
        "allowed_branch_refs": ["branch:riyadh", "branch:cairo", "branch:dubai"],
    },
    {
        "ref": "emp:cairo_manager", "first_name": "أحمد", "last_name": "حسن", "email": "ahmed.h@gulf-holding.example",
        "phone": "+201000000001", "hire_date": "2022-06-15", "salary": 85000, "currency": "EGP",
        "department_name": "المبيعات", "position_title": "مدير فرع",
        "create_user": True, "username": "ahmed.cairo", "password": COMPANY_PASS, "role": "branch_manager",
        "allowed_branch_refs": ["branch:cairo"],
    },
    {
        "ref": "emp:cairo_accountant", "first_name": "منى", "last_name": "إبراهيم", "email": "mona.i@gulf-holding.example",
        "phone": "+201000000002", "hire_date": "2023-01-10", "salary": 45000, "currency": "EGP",
        "department_name": "المالية", "position_title": "محاسب",
        "create_user": True, "username": "mona.cairo.acc", "password": COMPANY_PASS, "role": "accountant",
        "allowed_branch_refs": ["branch:cairo"],
    },
    {
        "ref": "emp:dubai_manager", "first_name": "خالد", "last_name": "المنصوري", "email": "khaled.m@gulf-holding.example",
        "phone": "+971500000001", "hire_date": "2022-08-01", "salary": 38000, "currency": "AED",
        "department_name": "المستودعات", "position_title": "مدير فرع",
        "create_user": True, "username": "khaled.dubai", "password": COMPANY_PASS, "role": "branch_manager",
        "allowed_branch_refs": ["branch:dubai"],
    },
    {
        "ref": "emp:dubai_cashier", "first_name": "ريم", "last_name": "النعيمي", "email": "reem.n@gulf-holding.example",
        "phone": "+971500000002", "hire_date": "2024-01-05", "salary": 12500, "currency": "AED",
        "department_name": "المبيعات", "position_title": "كاشير",
        "create_user": True, "username": "reem.cashier", "password": COMPANY_PASS, "role": "cashier",
        "allowed_branch_refs": ["branch:dubai"],
    },
    {
        "ref": "emp:sales_supervisor", "first_name": "عبدالعزيز", "last_name": "الشهري", "email": "aziz.s@gulf-holding.example",
        "phone": "+966500000008", "hire_date": "2023-04-01", "salary": 22000, "currency": "SAR",
        "department_name": "المبيعات", "position_title": "مشرف مبيعات",
        "create_user": True, "username": "aziz.sales", "password": COMPANY_PASS, "role": "sales",
        "allowed_branch_refs": ["branch:riyadh"],
    },
    {
        "ref": "emp:hr_manager", "first_name": "هند", "last_name": "العتبي", "email": "hind.o@gulf-holding.example",
        "phone": "+966500000009", "hire_date": "2021-11-01", "salary": 28000, "currency": "SAR",
        "department_name": "الموارد البشرية", "position_title": "مدير موارد بشرية",
        "create_user": True, "username": "hind.hr", "password": COMPANY_PASS, "role": "hr_manager",
        "allowed_branch_refs": ["branch:riyadh", "branch:cairo", "branch:dubai"],
    },
    {
        "ref": "emp:auditor", "first_name": "طارق", "last_name": "الأنصاري", "email": "tariq.a@gulf-holding.example",
        "phone": "+966500000010", "hire_date": "2022-10-01", "salary": 26000, "currency": "SAR",
        "department_name": "المالية", "position_title": "مراجع داخلي",
        "create_user": True, "username": "tariq.audit", "password": COMPANY_PASS, "role": "auditor",
        "allowed_branch_refs": ["branch:riyadh", "branch:cairo", "branch:dubai"],
    },
]


# ═══════════════════════════════════════════════════════════════
# Seed Functions
# ═══════════════════════════════════════════════════════════════

def resolve_refs(row: dict, refs: dict) -> dict:
    """تحويل _ref إلى _id باستخدام جدول المراجع"""
    out = {}
    for key, value in row.items():
        if key.endswith("_ref") and isinstance(value, str) and value in refs:
            out[key.replace("_ref", "_id")] = refs[value]
        elif key.endswith("_refs") and isinstance(value, list):
            out[key.replace("_refs", "_ids")] = [refs[r] for r in value if r in refs]
        elif key not in ("ref",):
            out[key] = value
    return out


def seed_currencies(client: AmanClient):
    """إنشاء العملات"""
    print("\n═══ 2. إنشاء العملات ═══")
    for cur in CURRENCIES:
        body = {k: v for k, v in cur.items() if k != "ref"}
        try:
            created = client.post("/api/accounting/currencies/", body)
            client.refs[cur["ref"]] = created["id"]
            print(f"  ✓ {cur['code']} - {cur['name']} (rate={cur['current_rate']}, base={cur['is_base']})")
        except Exception:
            try:
                currencies = client.get("/api/accounting/currencies/")
                lst = currencies if isinstance(currencies, list) else currencies.get("data", [])
                existing = next((c for c in lst if c.get("code") == cur["code"]), None)
                if existing:
                    client.refs[cur["ref"]] = existing["id"]
                    print(f"  ⚠ {cur['code']} موجود مسبقاً (id={existing['id']})")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {cur['code']}")


def seed_exchange_rates(client: AmanClient):
    """إنشاء أسعار الصرف"""
    print("\n═══ 3. إنشاء أسعار الصرف ═══")
    for er in EXCHANGE_RATES:
        body = {
            "currency_id": client.refs[er["currency_ref"]],
            "rate": er["rate"],
            "rate_date": er["rate_date"],
            "source": er["source"],
        }
        try:
            client.post("/api/accounting/currencies/rates", body)
            print(f"  ✓ {er['currency_ref']} → {er['rate']}")
        except Exception:
            print(f"  ⚠ فشل إنشاء سعر الصرف لـ {er['currency_ref']}")


def seed_branches(client: AmanClient):
    """إنشاء الفروع"""
    print("\n═══ 4. إنشاء الفروع ═══")
    for branch in BRANCHES:
        body = {k: v for k, v in branch.items() if k != "ref"}
        try:
            created = client.post("/api/branches/", body)
            client.refs[branch["ref"]] = created["id"]
            print(f"  ✓ {branch['branch_code']} - {branch['branch_name']} ({branch['default_currency']})")
        except Exception:
            try:
                branches = client.get("/api/branches/")
                lst = branches if isinstance(branches, list) else branches.get("data", [])
                existing = next((b for b in lst if b.get("branch_code") == branch["branch_code"]), None)
                if existing:
                    client.refs[branch["ref"]] = existing["id"]
                    print(f"  ⚠ {branch['branch_code']} موجود مسبقاً (id={existing['id']})")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {branch['branch_code']}")


def seed_company_settings(client: AmanClient):
    """تحديث إعدادات الشركة"""
    print("\n═══ 5. تحديث إعدادات الشركة ═══")
    settings = {s["setting_key"]: s["setting_value"] for s in COMPANY_SETTINGS}
    try:
        client.post("/api/settings/bulk", {"settings": settings})
        for s in COMPANY_SETTINGS:
            print(f"  ✓ {s['setting_key']} = {s['setting_value']}")
    except Exception:
        print(f"  ⚠ فشل تحديث الإعدادات (غير حرج)")


def seed_accounts(client: AmanClient):
    """إنشاء دليل الحسابات"""
    print("\n═══ 6. إنشاء دليل الحسابات ═══")
    for acc in ACCOUNTS:
        body = resolve_refs(acc, client.refs)
        try:
            created = client.post("/api/accounting/accounts", body)
            client.refs[acc["ref"]] = created["id"]
            print(f"  ✓ {acc['account_number']} - {acc['name']} ({acc['account_type']})")
        except Exception:
            try:
                accounts = client.get("/api/accounting/accounts")
                lst = accounts if isinstance(accounts, list) else accounts.get("data", [])
                existing = next((a for a in lst if a.get("account_number") == acc["account_number"]), None)
                if existing:
                    client.refs[acc["ref"]] = existing["id"]
                    print(f"  ⚠ {acc['account_number']} موجود مسبقاً (id={existing['id']})")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {acc['account_number']}")


def seed_treasury_accounts(client: AmanClient):
    """إنشاء الخزائن والبنوك"""
    print("\n═══ 7. إنشاء الخزائن والبنوك ═══")
    for treasury in TREASURY_ACCOUNTS:
        body = resolve_refs(treasury, client.refs)
        try:
            created = client.post("/api/treasury/accounts", body)
            client.refs[treasury["ref"]] = created["id"]
            print(f"  ✓ {treasury['name']} ({treasury['currency']}, {treasury['account_type']})")
        except Exception:
            try:
                treasuries = client.get("/api/treasury/accounts")
                lst = treasuries if isinstance(treasuries, list) else treasuries.get("data", [])
                existing = next((t for t in lst if t.get("name") == treasury["name"]), None)
                if existing:
                    client.refs[treasury["ref"]] = existing["id"]
                    print(f"  ⚠ {treasury['name']} موجود مسبقاً (id={existing['id']})")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {treasury['name']}")


def seed_departments(client: AmanClient):
    """إنشاء الإدارات"""
    print("\n═══ 8. إنشاء الإدارات ═══")
    for dept in DEPARTMENTS:
        body = resolve_refs(dept, client.refs)
        try:
            created = client.post("/api/hr/departments", body)
            client.refs[dept["ref"]] = created["id"]
            print(f"  ✓ {dept['department_name']}")
        except Exception:
            try:
                departments = client.get("/api/hr/departments")
                lst = departments if isinstance(departments, list) else departments.get("data", [])
                existing = next((d for d in lst if d.get("department_name") == dept["department_name"]), None)
                if existing:
                    client.refs[dept["ref"]] = existing["id"]
                    print(f"  ⚠ {dept['department_name']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {dept['department_name']}")


def seed_warehouses(client: AmanClient):
    """إنشاء المستودعات"""
    print("\n═══ 9. إنشاء المستودعات ═══")
    for wh in WAREHOUSES:
        body = resolve_refs(wh, client.refs)
        try:
            created = client.post("/api/inventory/warehouses", body)
            client.refs[wh["ref"]] = created["id"]
            print(f"  ✓ {wh['code']} - {wh['name']}")
        except Exception:
            try:
                warehouses = client.get("/api/inventory/warehouses")
                lst = warehouses if isinstance(warehouses, list) else warehouses.get("data", [])
                existing = next((w for w in lst if w.get("code") == wh["code"]), None)
                if existing:
                    client.refs[wh["ref"]] = existing["id"]
                    print(f"  ⚠ {wh['code']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {wh['code']}")


def seed_product_categories(client: AmanClient):
    """إنشاء تصنيفات المنتجات"""
    print("\n═══ 10. إنشاء تصنيفات المنتجات ═══")
    for cat in PRODUCT_CATEGORIES:
        body = {k: v for k, v in cat.items() if k != "ref"}
        try:
            created = client.post("/api/inventory/categories", body)
            client.refs[cat["ref"]] = created["id"]
            print(f"  ✓ {cat['code']} - {cat['name']}")
        except Exception:
            try:
                categories = client.get("/api/inventory/categories")
                lst = categories if isinstance(categories, list) else categories.get("data", [])
                existing = next((c for c in lst if c.get("code") == cat["code"] or c.get("name") == cat["name"]), None)
                if existing:
                    client.refs[cat["ref"]] = existing["id"]
                    print(f"  ⚠ {cat['name']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {cat['name']}")


def seed_products(client: AmanClient):
    """إنشاء المنتجات"""
    print("\n═══ 11. إنشاء المنتجات ═══")
    for prod in PRODUCTS:
        body = resolve_refs(prod, client.refs)
        try:
            created = client.post("/api/inventory/products", body)
            client.refs[prod["ref"]] = created["id"]
            print(f"  ✓ {prod['item_code']} - {prod['item_name']} ({prod['selling_price']})")
        except Exception:
            try:
                products = client.get("/api/inventory/products")
                lst = products if isinstance(products, list) else products.get("data", [])
                existing = next((p for p in lst if p.get("item_code") == prod["item_code"]), None)
                if existing:
                    client.refs[prod["ref"]] = existing["id"]
                    print(f"  ⚠ {prod['item_code']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {prod['item_code']}")


def seed_customers(client: AmanClient):
    """إنشاء العملاء"""
    print("\n═══ 12. إنشاء العملاء ═══")
    for cust in CUSTOMERS:
        body = resolve_refs(cust, client.refs)
        try:
            created = client.post("/api/sales/customers", body)
            client.refs[cust["ref"]] = created["id"]
            print(f"  ✓ {cust['name']} ({cust['currency']})")
        except Exception:
            try:
                customers = client.get("/api/parties/customers")
                lst = customers.get("items", []) if isinstance(customers, dict) else customers
                existing = next((c for c in lst if c.get("name") == cust["name"]), None)
                if existing:
                    client.refs[cust["ref"]] = existing["id"]
                    print(f"  ⚠ {cust['name']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {cust['name']}")


def seed_suppliers(client: AmanClient):
    """إنشاء الموردين"""
    print("\n═══ 13. إنشاء الموردين ═══")
    for sup in SUPPLIERS:
        body = resolve_refs(sup, client.refs)
        try:
            created = client.post("/api/inventory/suppliers", body)
            client.refs[sup["ref"]] = created["id"]
            print(f"  ✓ {sup['name']} ({sup['currency']})")
        except Exception:
            try:
                suppliers = client.get("/api/parties/suppliers")
                lst = suppliers.get("items", []) if isinstance(suppliers, dict) else suppliers
                existing = next((s for s in lst if s.get("name") == sup["name"]), None)
                if existing:
                    client.refs[sup["ref"]] = existing["id"]
                    print(f"  ⚠ {sup['name']} موجود مسبقاً")
            except Exception:
                print(f"  ✗ فشل إنشاء/جلب {sup['name']}")


def seed_employees(client: AmanClient):
    """إنشاء الموظفين مع المستخدمين"""
    print("\n═══ 14. إنشاء الموظفين والمستخدمين ═══")
    for emp in EMPLOYEES:
        body = {
            "first_name": emp["first_name"],
            "last_name": emp["last_name"],
            "email": emp.get("email"),
            "phone": emp.get("phone"),
            "hire_date": emp.get("hire_date"),
            "salary": emp.get("salary", 0),
            "currency": emp.get("currency"),
            "department_name": emp.get("department_name"),
            "position_title": emp.get("position_title"),
            "create_user": emp.get("create_user", False),
            "username": emp.get("username"),
            "password": emp.get("password"),
            "role": emp.get("role"),
        }
        if emp.get("branch_ref") and emp["branch_ref"] in client.refs:
            body["branch_id"] = client.refs[emp["branch_ref"]]
        if emp.get("allowed_branch_refs"):
            body["allowed_branch_ids"] = [
                client.refs[r] for r in emp["allowed_branch_refs"] if r in client.refs
            ]
        try:
            created = client.post("/api/hr/employees", body)
            if "id" in created:
                client.refs[emp["ref"]] = created["id"]
            user_info = " + مستخدم" if emp.get("create_user") else ""
            print(f"  ✓ {emp['first_name']} {emp['last_name']} - {emp.get('position_title', '')} ({emp.get('currency', '')}){user_info}")
        except Exception as e:
            # Check if employee already exists by trying to get the list
            try:
                employees = client.get("/api/hr/employees/")
                lst = employees if isinstance(employees, list) else employees.get("data", [])
                existing = next(
                    (e2 for e2 in lst
                     if (e2.get("first_name") == emp["first_name"] and e2.get("last_name") == emp["last_name"])
                     or (emp.get("username") and e2.get("username") == emp["username"])
                    ), None
                )
                if existing:
                    client.refs[emp["ref"]] = existing["id"]
                    print(f"  ⚠ {emp['first_name']} {emp['last_name']} موجود مسبقاً (id={existing['id']})")
                else:
                    print(f"  ✗ فشل إنشاء {emp['first_name']} {emp['last_name']}: {e}")
            except Exception:
                print(f"  ✗ فشل إنشاء {emp['first_name']} {emp['last_name']}: {e}")


def verify_seed(client: AmanClient):
    """التحقق من اكتمال التعبئة"""
    print("\n═══ التحقق من اكتمال التعبئة ═══")

    checks = [
        ("branches", "/api/branches/", 3),
        ("currencies", "/api/accounting/currencies/", 4),
        ("accounts", "/api/accounting/accounts", 12),
        ("treasury", "/api/treasury/accounts", 4),
        ("departments", "/api/hr/departments", 6),
        ("warehouses", "/api/inventory/warehouses", 3),
        ("products", "/api/inventory/products", 3),
        ("employees", "/api/hr/employees/", 10),
    ]

    all_ok = True
    for name, endpoint, min_count in checks:
        try:
            data = client.get(endpoint)
            lst = data if isinstance(data, list) else data.get("data", data.get("items", []))
            count = len(lst) if isinstance(lst, list) else 0
            status = "✓" if count >= min_count else "✗"
            print(f"  {status} {name}: {count} (expected ≥{min_count})")
            if count < min_count:
                all_ok = False
        except Exception as e:
            print(f"  ✗ {name}: خطأ - {e}")
            all_ok = False

    return all_ok


def print_summary(client: AmanClient):
    """طباعة ملخص المستخدمين وكلمة المرور"""
    print("\n" + "═" * 60)
    print("  ملخص البيانات المُدخلة")
    print("═" * 60)
    print(f"\n  الشركة: {COMPANY_NAME}")
    print(f"  عدد الفروع: {len([r for r in client.refs if r.startswith('branch:')])}")
    print(f"  عدد العملات: {len([r for r in client.refs if r.startswith('currency:')])}")
    print(f"  عدد الموظفين: {len([r for r in client.refs if r.startswith('emp:')])}")
    print(f"  عدد المنتجات: {len([r for r in client.refs if r.startswith('prod:')])}")

    print("\n  المستخدمون وكلمة المرور: P@ssw0rd!2026")
    print("  ┌─────────────────────┬──────────────────┬─────────────────┐")
    print("  │ المستخدم            │ الدور            │ الفرع           │")
    print("  ├─────────────────────┼──────────────────┼─────────────────┤")
    users = [
        ("salem.ceo", "ceo", "كل الفروع"),
        ("noura.finance", "finance_manager", "كل الفروع"),
        ("majed.chief", "accountant", "كل الفروع"),
        ("ahmed.cairo", "branch_manager", "القاهرة"),
        ("mona.cairo.acc", "accountant", "القاهرة"),
        ("khaled.dubai", "branch_manager", "دبي"),
        ("reem.cashier", "cashier", "دبي"),
        ("aziz.sales", "sales", "الرياض"),
        ("hind.hr", "hr_manager", "كل الفروع"),
        ("tariq.audit", "auditor", "كل الفروع"),
    ]
    for username, role, branch in users:
        print(f"  │ {username:<19} │ {role:<16} │ {branch:<15} │")
    print("  └─────────────────────┴──────────────────┴─────────────────┘")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AMAN ERP - Seed Master Data")
    parser.add_argument("--url", default=DEFAULT_URL, help="Backend URL")
    parser.add_argument("--company-code", default="", help="Company code (if already exists)")
    args = parser.parse_args()

    client = AmanClient(args.url)

    print("╔══════════════════════════════════════════════════════════╗")
    print("║        AMAN ERP - تعبئة البيانات الرئيسية               ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"\n  الخادم: {args.url}")

    # Step 1: Company already exists — just login
    company_code = args.company_code or COMPANY_CODE
    print(f"\n═══ تسجيل الدخول (company_code={company_code}) ═══")
    try:
        client.login(COMPANY_USER, COMPANY_PASS, company_code)
        print(f"  ✓ تم تسجيل الدخول بنجاح")
    except Exception as e:
        print(f"  ✗ فشل تسجيل الدخول: {e}")
        sys.exit(1)

    # Step 3-14: Seed all data
    seed_currencies(client)
    seed_exchange_rates(client)
    seed_branches(client)
    seed_company_settings(client)
    seed_accounts(client)
    seed_treasury_accounts(client)
    seed_departments(client)
    seed_warehouses(client)
    seed_product_categories(client)
    seed_products(client)
    seed_customers(client)
    seed_suppliers(client)
    seed_employees(client)

    # Verify
    ok = verify_seed(client)

    # Summary
    print_summary(client)

    if ok:
        print("\n  ✅ تمت التعبئة بنجاح! النظام جاهز للاستخدام.")
    else:
        print("\n  ⚠️ تمت التعبئة مع بعض التحذيرات. راجع الرسائل أعلاه.")

    # Save refs for tests
    refs_path = "tests/.seed-refs.json"
    try:
        with open(refs_path, "w") as f:
            json.dump({"company_code": company_code, "refs": client.refs}, f, indent=2, ensure_ascii=False)
        print(f"\n  📁 حُفظت المراجع في: {refs_path}")
    except Exception:
        pass

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
