#!/usr/bin/env python3
"""
AMAN ERP - Comprehensive Seed Script for Company dc4eaa49
==========================================================
يعمل مباشرة على قاعدة البيانات (بدون API) لضمان الدقة.
يُنشئ كل البيانات: عملات، فروع، حسابات، خزائن، إدارات، مستودعات، منتجات، عملاء، موردين، موظفين.
ويُنشئ journal entries لأرصدة افتتاحية صحيحة.

الاستخدام:
    python scripts/seed-dc4eaa49.py
    python scripts/seed-dc4eaa49.py --clean   # حذف البيانات أولاً
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

COMPANY_CODE = "1a134155"
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "aman")
DB_PASS = os.environ.get("DB_PASSWORD", "YourPassword123!@#")
DB_NAME = f"aman_{COMPANY_CODE}"

ADMIN_USER = "omar"
ADMIN_PASS = "As123321"

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

class DBHelper:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASS, dbname=DB_NAME
        )
        self.conn.autocommit = False
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        self.refs = {}
        self.admin_id = None

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def get_admin_id(self):
        self.cur.execute("SELECT id FROM company_users WHERE username = %s", (ADMIN_USER,))
        row = self.cur.fetchone()
        self.admin_id = row["id"] if row else 1
        return self.admin_id

    def fix_sequence(self, table, column="id"):
        """إصلاح sequence لأي جدول"""
        try:
            self.cur.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table}', '{column}'),
                    COALESCE((SELECT MAX({column}) FROM {table}), 0) + 1, false)
            """)
        except Exception:
            self.conn.rollback()

    def get_or_create(self, table, match_col, match_val, insert_data, ref_key=None):
        """جلب أو إنشاء سجل"""
        self.cur.execute(f"SELECT id FROM {table} WHERE {match_col} = %s", (match_val,))
        row = self.cur.fetchone()
        if row:
            if ref_key:
                self.refs[ref_key] = row["id"]
            return row["id"]

        cols = list(insert_data.keys())
        vals = list(insert_data.values())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        self.cur.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) RETURNING id",
            vals
        )
        new_id = self.cur.fetchone()["id"]
        if ref_key:
            self.refs[ref_key] = new_id
        return new_id


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ═══════════════════════════════════════════════════════════════
# Seed Functions
# ═══════════════════════════════════════════════════════════════

def seed_currencies(db: DBHelper):
    """إنشاء العملات"""
    print("\n═══ 1. إنشاء العملات ═══")
    currencies = [
        {"code": "SAR", "name": "ريال سعودي", "name_en": "Saudi Riyal", "symbol": "ر.س", "is_base": True, "current_rate": 1.0},
        {"code": "EGP", "name": "جنيه مصري", "name_en": "Egyptian Pound", "symbol": "ج.م", "is_base": False, "current_rate": 0.076},
        {"code": "AED", "name": "درهم إماراتي", "name_en": "UAE Dirham", "symbol": "د.إ", "is_base": False, "current_rate": 1.021},
        {"code": "USD", "name": "دولار أمريكي", "name_en": "US Dollar", "symbol": "$", "is_base": False, "current_rate": 3.75},
        {"code": "GBP", "name": "جنيه إنجليزي", "name_en": "British Pound", "symbol": "£", "is_base": False, "current_rate": 4.70},
    ]
    for cur in currencies:
        db.fix_sequence("currencies")
        cid = db.get_or_create("currencies", "code", cur["code"], {
            "code": cur["code"], "name": cur["name"], "name_en": cur["name_en"],
            "symbol": cur["symbol"], "is_base": cur["is_base"],
            "current_rate": cur["current_rate"], "is_active": True,
        }, ref_key=f"currency:{cur['code']}")
        print(f"  ✓ {cur['code']} - {cur['name']} (rate={cur['current_rate']}, base={cur['is_base']})")
    db.commit()


def seed_exchange_rates(db: DBHelper):
    """إنشاء أسعار الصرف"""
    print("\n═══ 2. إنشاء أسعار الصرف ═══")
    today = date.today()
    rates = [
        {"code": "EGP", "rate": 0.076},
        {"code": "AED", "rate": 1.021},
        {"code": "USD", "rate": 3.75},
        {"code": "GBP", "rate": 4.70},
    ]
    for r in rates:
        cur_id = db.refs.get(f"currency:{r['code']}")
        if not cur_id:
            continue
        try:
            db.cur.execute("""
                INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by)
                VALUES (%s, %s, %s, 'manual', %s)
                ON CONFLICT (currency_id, rate_date) DO UPDATE SET rate = EXCLUDED.rate
            """, (cur_id, today, r["rate"], db.admin_id))
            print(f"  ✓ {r['code']} → {r['rate']}")
        except Exception as e:
            print(f"  ⚠ {r['code']}: {e}")
            db.conn.rollback()
    db.commit()


def seed_branches(db: DBHelper):
    """إنشاء الفروع"""
    print("\n═══ 3. إنشاء الفروع ═══")
    branches = [
        {"code": "RUH-HQ", "name": "الفرع الرئيسي - الرياض", "name_en": "Riyadh HQ", "city": "الرياض", "country": "Saudi Arabia", "country_code": "SA", "currency": "SAR", "phone": "+966112220000", "email": "riyadh@aman.example", "is_default": True},
        {"code": "CAI", "name": "مصر - فرع القاهرة", "name_en": "Egypt - Cairo", "city": "القاهرة", "country": "Egypt", "country_code": "EG", "currency": "EGP", "phone": "+2022220000", "email": "cairo@aman.example"},
        {"code": "DXB", "name": "الإمارات - فرع دبي", "name_en": "UAE - Dubai", "city": "دبي", "country": "UAE", "country_code": "AE", "currency": "AED", "phone": "+97142220000", "email": "dubai@aman.example"},
        {"code": "LON", "name": "لندن - فرع بريطانيا", "name_en": "UK - London", "city": "لندن", "country": "UK", "country_code": "GB", "currency": "GBP", "phone": "+44201234000", "email": "london@aman.example"},
    ]
    # حذف الفرع الافتراضي الموجود مسبقاً
    db.cur.execute("DELETE FROM branches WHERE branch_code = 'BR001'")
    db.cur.execute("DELETE FROM user_branches WHERE branch_id NOT IN (SELECT id FROM branches)")

    for b in branches:
        db.fix_sequence("branches")
        bid = db.get_or_create("branches", "branch_code", b["code"], {
            "branch_code": b["code"], "branch_name": b["name"], "branch_name_en": b["name_en"],
            "city": b["city"], "country": b["country"], "country_code": b["country_code"],
            "default_currency": b["currency"], "phone": b["phone"], "email": b["email"],
            "is_default": b.get("is_default", False), "is_active": True,
        }, ref_key=f"branch:{b['code']}")
        # ربط المستخدم بالفرع
        try:
            db.cur.execute("""
                INSERT INTO user_branches (user_id, branch_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
            """, (db.admin_id, bid))
        except Exception:
            db.conn.rollback()
        print(f"  ✓ {b['code']} - {b['name']} ({b['currency']})")
    db.commit()


def seed_company_settings(db: DBHelper):
    """تحديث إعدادات الشركة"""
    print("\n═══ 4. تحديث إعدادات الشركة ═══")
    settings = {
        "default_currency": "SAR",
        "reporting_currency": "SAR",
        "invoice_prefix": "INV-",
        "journal_prefix": "JE-",
        "timezone": "Asia/Riyadh",
        "company_country": "SA",
    }
    for key, val in settings.items():
        try:
            db.cur.execute("""
                INSERT INTO company_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
            """, (key, val))
            print(f"  ✓ {key} = {val}")
        except Exception as e:
            print(f"  ⚠ {key}: {e}")
            db.conn.rollback()
    db.commit()


def seed_capital_accounts(db: DBHelper):
    """إنشاء حسابات رأس المال لكل عملة"""
    print("\n═══ 5. إنشاء حسابات رأس المال ═══")

    # التأكد من وجود الحساب الأب (31 - رأس المال)
    db.cur.execute("SELECT id FROM accounts WHERE account_number = '31'")
    parent = db.cur.fetchone()
    if not parent:
        # إنشاء حساب الأب
        db.cur.execute("SELECT id FROM accounts WHERE account_number = '3'")
        equity_root = db.cur.fetchone()
        equity_id = equity_root["id"] if equity_root else None
        db.fix_sequence("accounts")
        db.cur.execute("""
            INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, is_header, currency)
            VALUES ('31', 'CAP', 'رأس المال', 'Capital', 'equity', %s, TRUE, 'SAR')
            RETURNING id
        """, (equity_id,))
        parent = db.cur.fetchone()
    parent_id = parent["id"]

    capital_accounts = [
        {"number": "3101", "name": "رأس المال - ريال سعودي", "name_en": "Capital - SAR", "currency": "SAR"},
        {"number": "3102", "name": "رأس المال - جنيه مصري", "name_en": "Capital - EGP", "currency": "EGP"},
        {"number": "3103", "name": "رأس المال - درهم إماراتي", "name_en": "Capital - AED", "currency": "AED"},
        {"number": "3104", "name": "رأس المال - دولار أمريكي", "name_en": "Capital - USD", "currency": "USD"},
        {"number": "3105", "name": "رأس المال - جنيه إنجليزي", "name_en": "Capital - GBP", "currency": "GBP"},
    ]

    for acc in capital_accounts:
        db.fix_sequence("accounts")
        aid = db.get_or_create("accounts", "account_number", acc["number"], {
            "account_number": acc["number"], "account_code": "CAP",
            "name": acc["name"], "name_en": acc["name_en"],
            "account_type": "equity", "parent_id": parent_id,
            "is_header": False, "currency": acc["currency"], "is_active": True,
        }, ref_key=f"account:capital_{acc['currency'].lower()}")
        print(f"  ✓ {acc['number']} - {acc['name']}")
    db.commit()


def seed_treasury_accounts(db: DBHelper):
    """إنشاء الخزائن والبنوك - كل خزينة بحساب GL منفصل"""
    print("\n═══ 6. إنشاء الخزائن والبنوك ═══")

    # جلب الحساب الأب للبنوك والصناديق
    db.cur.execute("SELECT id FROM accounts WHERE account_number = '1101'")
    cash_parent = db.cur.fetchone()
    parent_id = cash_parent["id"] if cash_parent else None

    treasuries = [
        {"ref": "treasury:riyadh_bank", "name": "بنك الرياض الرئيسي", "name_en": "Riyad Bank Main", "type": "bank", "currency": "SAR", "branch_code": "RUH-HQ", "bank_name": "Riyad Bank", "acc_number": "100200300", "opening": 500000, "gl_number": "11010201", "gl_name": "بنك الرياض - SAR"},
        {"ref": "treasury:riyadh_cash", "name": "صندوق الرياض", "name_en": "Riyad Cash Box", "type": "cash", "currency": "SAR", "branch_code": "RUH-HQ", "opening": 25000, "gl_number": "11010101", "gl_name": "صندوق الرياض - SAR"},
        {"ref": "treasury:cairo_bank", "name": "بنك القاهرة", "name_en": "CIB Cairo", "type": "bank", "currency": "EGP", "branch_code": "CAI", "bank_name": "CIB", "acc_number": "EG100200", "opening": 300000, "gl_number": "11010202", "gl_name": "بنك القاهرة - EGP"},
        {"ref": "treasury:dubai_bank", "name": "بنك دبي", "name_en": "Emirates NBD", "type": "bank", "currency": "AED", "branch_code": "DXB", "bank_name": "Emirates NBD", "acc_number": "AE100200", "opening": 220000, "gl_number": "11010203", "gl_name": "بنك دبي - AED"},
        {"ref": "treasury:cairo_cash", "name": "صندوق القاهرة", "name_en": "Cairo Cash Box", "type": "cash", "currency": "EGP", "branch_code": "CAI", "opening": 50000, "gl_number": "11010102", "gl_name": "صندوق القاهرة - EGP"},
    ]

    for t in treasuries:
        branch_id = db.refs.get(f"branch:{t['branch_code']}")

        # إنشاء حساب GL منفصل لكل خزينة
        db.fix_sequence("accounts")
        gl_id = db.get_or_create("accounts", "account_number", t["gl_number"], {
            "account_number": t["gl_number"],
            "account_code": t["type"].upper()[:3],
            "name": t["gl_name"],
            "name_en": t.get("name_en", ""),
            "account_type": "asset",
            "parent_id": parent_id,
            "is_header": False,
            "currency": t["currency"],
            "is_active": True,
        })

        # إنشاء الخزينة مع ربطها بالحساب GL المنفصل
        db.fix_sequence("treasury_accounts")
        tid = db.get_or_create("treasury_accounts", "name", t["name"], {
            "name": t["name"], "name_en": t["name_en"],
            "account_type": t["type"], "currency": t["currency"],
            "branch_id": branch_id, "bank_name": t.get("bank_name", ""),
            "account_number": t.get("acc_number", ""),
            "current_balance": t["opening"],
            "allow_overdraft": False, "is_active": True,
            "gl_account_id": gl_id,
        }, ref_key=t["ref"])
        db.refs[f"gl:{t['ref']}"] = gl_id
        print(f"  ✓ {t['name']} ({t['currency']}, {t['type']}, opening={t['opening']}, GL={t['gl_number']})")
    db.commit()


def seed_departments(db: DBHelper):
    """إنشاء الإدارات"""
    print("\n═══ 7. إنشاء الإدارات ═══")
    departments = [
        {"ref": "dept:executive", "name": "الإدارة التنفيذية", "branch_code": "RUH-HQ"},
        {"ref": "dept:finance", "name": "المالية", "branch_code": "RUH-HQ"},
        {"ref": "dept:sales", "name": "المبيعات", "branch_code": "RUH-HQ"},
        {"ref": "dept:hr", "name": "الموارد البشرية", "branch_code": "RUH-HQ"},
        {"ref": "dept:warehouse", "name": "المستودعات", "branch_code": "DXB"},
        {"ref": "dept:projects", "name": "المشاريع", "branch_code": "RUH-HQ"},
    ]
    for d in departments:
        branch_id = db.refs.get(f"branch:{d['branch_code']}")
        db.fix_sequence("departments")
        did = db.get_or_create("departments", "department_name", d["name"], {
            "department_name": d["name"], "branch_id": branch_id, "is_active": True,
        }, ref_key=d["ref"])
        print(f"  ✓ {d['name']}")
    db.commit()


def seed_warehouses(db: DBHelper):
    """إنشاء المستودعات"""
    print("\n═══ 8. إنشاء المستودعات ═══")

    # حذف المستودع الافتراضي
    db.cur.execute("DELETE FROM warehouses WHERE warehouse_code = 'WH001'")

    warehouses = [
        {"ref": "wh:riyadh", "code": "WH-RUH", "name": "مستودع الرياض الرئيسي", "name_en": "Riyadh Main Warehouse", "branch_code": "RUH-HQ", "location": "الرياض - السلي", "is_default": True},
        {"ref": "wh:cairo", "code": "WH-CAI", "name": "مستودع القاهرة", "name_en": "Cairo Warehouse", "branch_code": "CAI", "location": "القاهرة - مدينة نصر"},
        {"ref": "wh:dubai", "code": "WH-DXB", "name": "مستودع دبي", "name_en": "Dubai Warehouse", "branch_code": "DXB", "location": "دبي - جبل علي"},
    ]
    for w in warehouses:
        branch_id = db.refs.get(f"branch:{w['branch_code']}")
        db.fix_sequence("warehouses")
        wid = db.get_or_create("warehouses", "warehouse_code", w["code"], {
            "warehouse_code": w["code"], "warehouse_name": w["name"],
            "warehouse_name_en": w.get("name_en", ""), "branch_id": branch_id,
            "location": w.get("location", ""), "is_default": w.get("is_default", False),
            "is_active": True,
        }, ref_key=w["ref"])
        print(f"  ✓ {w['code']} - {w['name']}")
    db.commit()


def seed_product_categories(db: DBHelper):
    """إنشاء تصنيفات المنتجات"""
    print("\n═══ 9. إنشاء تصنيفات المنتجات ═══")
    categories = [
        {"ref": "cat:electronics", "name": "إلكترونيات", "code": "ELEC"},
        {"ref": "cat:services", "name": "خدمات", "code": "SERV"},
    ]
    for c in categories:
        db.fix_sequence("product_categories")
        cid = db.get_or_create("product_categories", "category_name", c["name"], {
            "category_name": c["name"], "category_code": c["code"], "is_active": True,
        }, ref_key=c["ref"])
        print(f"  ✓ {c['code']} - {c['name']}")
    db.commit()


def seed_products(db: DBHelper):
    """إنشاء المنتجات"""
    print("\n═══ 10. إنشاء المنتجات ═══")
    products = [
        {"ref": "prod:tablet", "code": "GH-TAB-10", "name": "جهاز لوحي 10 بوصة", "type": "product", "unit": "قطعة", "sell": 1200, "buy": 800, "tax": 15, "cat": "cat:electronics"},
        {"ref": "prod:scanner", "code": "GH-SCN-01", "name": "قارئ باركود", "type": "product", "unit": "قطعة", "sell": 450, "buy": 280, "tax": 15, "cat": "cat:electronics"},
        {"ref": "prod:implementation", "code": "GH-SRV-IMPL", "name": "خدمة تطبيق نظام", "type": "service", "unit": "ساعة", "sell": 350, "buy": 0, "tax": 15, "cat": "cat:services"},
    ]
    for p in products:
        cat_id = db.refs.get(p["cat"])
        db.fix_sequence("products")
        pid = db.get_or_create("products", "product_code", p["code"], {
            "product_code": p["code"], "product_name": p["name"], "product_type": p["type"],
            "selling_price": p["sell"], "cost_price": p["buy"],
            "tax_rate": p["tax"], "category_id": cat_id,
            "is_track_inventory": p["type"] == "product", "is_active": True,
        }, ref_key=p["ref"])
        print(f"  ✓ {p['code']} - {p['name']} (sell={p['sell']}, buy={p['buy']})")
    db.commit()


def seed_customers(db: DBHelper):
    """إنشاء العملاء"""
    print("\n═══ 11. إنشاء العملاء ═══")
    customers = [
        {"ref": "party:riyadh_customer", "name": "شركة نجد للتجزئة", "name_en": "Najd Retail Co.", "branch_code": "RUH-HQ", "currency": "SAR", "tax_number": "300111111100003", "credit_limit": 250000, "payment_terms": 45, "phone": "+966112000001"},
        {"ref": "party:cairo_customer", "name": "دلتا ماركت", "name_en": "Delta Market", "branch_code": "CAI", "currency": "EGP", "tax_number": "123456789", "credit_limit": 500000, "payment_terms": 30, "phone": "+20222000001"},
        {"ref": "party:dubai_customer", "name": "Dubai Retail LLC", "name_en": "Dubai Retail LLC", "branch_code": "DXB", "currency": "AED", "tax_number": "1234567890", "credit_limit": 300000, "payment_terms": 30, "phone": "+97142000001"},
    ]
    for c in customers:
        branch_id = db.refs.get(f"branch:{c['branch_code']}")
        db.fix_sequence("customers")
        db.cur.execute("""
            INSERT INTO customers (customer_code, customer_name, customer_name_en,
                branch_id, currency, tax_number, credit_limit, payment_terms, phone, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            RETURNING id
        """, (f"CUST-{c['ref'].split(':')[1].upper()}", c["name"], c.get("name_en", ""),
              branch_id, c["currency"], c.get("tax_number", ""),
              c.get("credit_limit", 0), c.get("payment_terms", 30), c.get("phone", "")))
        cid = db.cur.fetchone()["id"]
        db.refs[c["ref"]] = cid
        print(f"  ✓ {c['name']} ({c['currency']})")
    db.commit()


def seed_suppliers(db: DBHelper):
    """إنشاء الموردين"""
    print("\n═══ 12. إنشاء الموردين ═══")
    suppliers = [
        {"ref": "party:global_supplier", "name": "Gulf Supply FZCO", "name_en": "Gulf Supply FZCO", "branch_code": "DXB", "currency": "AED", "tax_number": "9876543210", "phone": "+97143000001"},
    ]
    for s in suppliers:
        branch_id = db.refs.get(f"branch:{s['branch_code']}")
        db.fix_sequence("suppliers")
        db.cur.execute("""
            INSERT INTO suppliers (supplier_code, supplier_name, supplier_name_en,
                branch_id, currency, tax_number, phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (f"SUP-{s['ref'].split(':')[1].upper()}", s["name"], s.get("name_en", ""),
              branch_id, s["currency"], s.get("tax_number", ""), s.get("phone", "")))
        sid = db.cur.fetchone()["id"]
        db.refs[s["ref"]] = sid
        print(f"  ✓ {s['name']} ({s['currency']})")
    db.commit()


def seed_employees(db: DBHelper):
    """إنشاء الموظفين مع المستخدمين"""
    print("\n═══ 13. إنشاء الموظفين والمستخدمين ═══")

    # جلب الإدارات
    db.cur.execute("SELECT id, department_name FROM departments")
    dept_map = {r["department_name"]: r["id"] for r in db.cur.fetchall()}

    # إنشاء المواقع الوظيفية
    positions = [
        {"code": "POS-CEO", "name": "مدير تنفيذي", "dept": "الإدارة التنفيذية"},
        {"code": "POS-BM", "name": "مدير فرع", "dept": "المبيعات"},
        {"code": "POS-FM", "name": "مدير مالي", "dept": "المالية"},
        {"code": "POS-CA", "name": "رئيس حسابات", "dept": "المالية"},
        {"code": "POS-ACC", "name": "محاسب", "dept": "المالية"},
        {"code": "POS-SS", "name": "مشرف مبيعات", "dept": "المبيعات"},
        {"code": "POS-CAO", "name": "كاشير", "dept": "المبيعات"},
        {"code": "POS-HR", "name": "مدير موارد بشرية", "dept": "الموارد البشرية"},
        {"code": "POS-WH", "name": "أمين مستودع", "dept": "المستودعات"},
        {"code": "POS-AUD", "name": "مراجع داخلي", "dept": "المالية"},
    ]
    pos_map = {}
    for pos in positions:
        dept_id = dept_map.get(pos["dept"])
        db.fix_sequence("employee_positions")
        pid = db.get_or_create("employee_positions", "position_code", pos["code"], {
            "position_code": pos["code"], "position_name": pos["name"],
            "department_id": dept_id, "is_active": True,
        })
        pos_map[pos["name"]] = pid
    db.commit()

    employees = [
        {"ref": "emp:ceo", "first": "سالم", "last": "الغامدي", "email": "salem@aman.example", "phone": "+966500000001", "hire": "2021-01-01", "salary": 65000, "currency": "SAR", "dept": "الإدارة التنفيذية", "pos": "مدير تنفيذي", "user": "salem.ceo", "role": "ceo", "branches": ["RUH-HQ", "CAI", "DXB"]},
        {"ref": "emp:finance_manager", "first": "نورة", "last": "القحطاني", "email": "noura@aman.example", "phone": "+966500000002", "hire": "2021-03-01", "salary": 42000, "currency": "SAR", "dept": "المالية", "pos": "مدير مالي", "user": "noura.finance", "role": "finance_manager", "branches": ["RUH-HQ", "CAI", "DXB"]},
        {"ref": "emp:chief_accountant", "first": "ماجد", "last": "الدوسري", "email": "majed@aman.example", "phone": "+966500000003", "hire": "2022-02-01", "salary": 30000, "currency": "SAR", "dept": "المالية", "pos": "رئيس حسابات", "user": "majed.chief", "role": "accountant", "branches": ["RUH-HQ", "CAI", "DXB"]},
        {"ref": "emp:cairo_manager", "first": "أحمد", "last": "حسن", "email": "ahmed@aman.example", "phone": "+201000000001", "hire": "2022-06-15", "salary": 85000, "currency": "EGP", "dept": "المبيعات", "pos": "مدير فرع", "user": "ahmed.cairo", "role": "branch_manager", "branches": ["CAI"]},
        {"ref": "emp:cairo_accountant", "first": "منى", "last": "إبراهيم", "email": "mona@aman.example", "phone": "+201000000002", "hire": "2023-01-10", "salary": 45000, "currency": "EGP", "dept": "المالية", "pos": "محاسب", "user": "mona.cairo.acc", "role": "accountant", "branches": ["CAI"]},
        {"ref": "emp:dubai_manager", "first": "خالد", "last": "المنصوري", "email": "khaled@aman.example", "phone": "+971500000001", "hire": "2022-08-01", "salary": 38000, "currency": "AED", "dept": "المستودعات", "pos": "مدير فرع", "user": "khaled.dubai", "role": "branch_manager", "branches": ["DXB"]},
        {"ref": "emp:dubai_cashier", "first": "ريم", "last": "النعيمي", "email": "reem@aman.example", "phone": "+971500000002", "hire": "2024-01-05", "salary": 12500, "currency": "AED", "dept": "المبيعات", "pos": "كاشير", "user": "reem.cashier", "role": "cashier", "branches": ["DXB"]},
        {"ref": "emp:sales_supervisor", "first": "عبدالعزيز", "last": "الشهري", "email": "aziz@aman.example", "phone": "+966500000008", "hire": "2023-04-01", "salary": 22000, "currency": "SAR", "dept": "المبيعات", "pos": "مشرف مبيعات", "user": "aziz.sales", "role": "sales", "branches": ["RUH-HQ"]},
        {"ref": "emp:hr_manager", "first": "هند", "last": "العتبي", "email": "hind@aman.example", "phone": "+966500000009", "hire": "2021-11-01", "salary": 28000, "currency": "SAR", "dept": "الموارد البشرية", "pos": "مدير موارد بشرية", "user": "hind.hr", "role": "hr_manager", "branches": ["RUH-HQ", "CAI", "DXB"]},
        {"ref": "emp:auditor", "first": "طارق", "last": "الأنصاري", "email": "tariq@aman.example", "phone": "+966500000010", "hire": "2022-10-01", "salary": 26000, "currency": "SAR", "dept": "المالية", "pos": "مراجع داخلي", "user": "tariq.audit", "role": "auditor", "branches": ["RUH-HQ", "CAI", "DXB"]},
    ]

    for emp in employees:
        # إنشاء مستخدم - أولاً تحقق إذا موجود
        db.fix_sequence("company_users")
        db.cur.execute("SELECT id FROM company_users WHERE username = %s", (emp["user"],))
        existing_user = db.cur.fetchone()
        if existing_user:
            user_id = existing_user["id"]
        else:
            hashed = hash_password(ADMIN_PASS)
            db.cur.execute("""
                INSERT INTO company_users (username, password, email, full_name, role, permissions, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                RETURNING id
            """, (emp["user"], hashed, emp["email"], f"{emp['first']} {emp['last']}",
                  emp["role"], '{"all": true}' if emp["role"] == "ceo" else '{}'))
            user_id = db.cur.fetchone()["id"]

        # ربط المستخدم بالفروع
        for bc in emp.get("branches", []):
            bid = db.refs.get(f"branch:{bc}")
            if bid:
                try:
                    db.cur.execute("""
                        INSERT INTO user_branches (user_id, branch_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                    """, (user_id, bid))
                except Exception:
                    db.conn.rollback()

        # إنشاء موظف - تحقق أولاً
        dept_id = dept_map.get(emp["dept"])
        pos_id = pos_map.get(emp["pos"])
        emp_code = f"EMP-{emp['ref'].split(':')[1].upper()}"

        db.cur.execute("SELECT id FROM employees WHERE employee_code = %s", (emp_code,))
        existing_emp = db.cur.fetchone()
        if existing_emp:
            db.refs[emp["ref"]] = existing_emp["id"]
            print(f"  ⚠ {emp['first']} {emp['last']} موجود مسبقاً")
        else:
            db.fix_sequence("employees")
            db.cur.execute("""
                INSERT INTO employees (employee_code, first_name, last_name, email, phone,
                    hire_date, salary, currency, department_id, position_id, branch_id,
                    user_id, status, employment_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 'full_time')
                RETURNING id
            """, (emp_code, emp["first"], emp["last"],
                  emp["email"], emp["phone"], emp["hire"], emp["salary"], emp["currency"],
                  dept_id, pos_id, db.refs.get(f"branch:{emp['branches'][0]}"), user_id))
            eid = db.cur.fetchone()["id"]
            db.refs[emp["ref"]] = eid
            print(f"  ✓ {emp['first']} {emp['last']} - {emp['pos']} ({emp['currency']}) + مستخدم")

    db.commit()


def seed_fiscal_year(db: DBHelper):
    """إنشاء سنة مالية"""
    print("\n═══ 14. إنشاء سنة مالية ═══")
    try:
        db.fix_sequence("fiscal_years")
        db.cur.execute("""
            INSERT INTO fiscal_years (year, start_date, end_date, status)
            VALUES (2026, '2026-01-01', '2026-12-31', 'open')
            ON CONFLICT (year) DO NOTHING
            RETURNING id
        """)
        result = db.cur.fetchone()
        fy_id = result["id"] if result else None

        if fy_id:
            # إنشاء 12 فترة
            for m in range(1, 13):
                start = date(2026, m, 1)
                if m == 12:
                    end = date(2026, 12, 31)
                elif m == 2:
                    end = date(2026, 2, 28)
                else:
                    end = date(2026, m, 30)
                month_name = ["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"][m-1]
                db.fix_sequence("fiscal_periods")
                try:
                    db.cur.execute("""
                        INSERT INTO fiscal_periods (name, start_date, end_date, fiscal_year)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (f"{month_name} 2026", start, end, 2026))
                except Exception:
                    db.conn.rollback()
        print(f"  ✓ سنة مالية 2026 مع 12 فترة")
    except Exception as e:
        print(f"  ⚠ {e}")
        db.conn.rollback()
    db.commit()


def seed_opening_journal_entries(db: DBHelper):
    """إنشاء قيود افتتاحية بأرصدة صحيحة"""
    print("\n═══ 15. إنشاء قيود افتتاحية ═══")

    # القاعدة الذهبية:
    # debit/credit = المبلغ بالعملة الأصلية
    # exchange_rate = سعر التحويل لعملة التقارير (SAR)
    # debit_base = debit × exchange_rate

    today = date.today()
    branch_id = db.refs.get("branch:RUH-HQ")

    # جلب أسعار الصرف
    exchange_rates = {"SAR": 1.0, "EGP": 0.076, "AED": 1.021, "USD": 3.75, "GBP": 4.70}

    # جلب معرفات الحسابات
    account_ids = {}
    db.cur.execute("SELECT id, account_number, currency FROM accounts WHERE account_number IN ('110101','110102','1102','1103','2101','3101','3102','3103','3104','3105')")
    for r in db.cur.fetchall():
        account_ids[r["account_number"]] = {"id": r["id"], "currency": r["currency"]}

    # جلب معرفات الخزائن
    treasury_map = {}
    db.cur.execute("SELECT id, name, currency, account_type FROM treasury_accounts")
    for r in db.cur.fetchall():
        treasury_map[r["name"]] = r

    # ═══════════════════════════════════════════════════════
    # القيد الافتتاحي 1: أرصدة الخزائن
    # ═══════════════════════════════════════════════════════
    print("\n── القيد الافتتاحي 1: أرصدة الخزائن والبنوك ──")

    opening_balances = [
        # الخزائن ( debit الصندوق / البنك = credit رأس المال )
        {"treasury": "بنك الرياض الرئيسي", "amount": 500000, "currency": "SAR", "capital_acc": "3101"},
        {"treasury": "صندوق الرياض", "amount": 25000, "currency": "SAR", "capital_acc": "3101"},
        {"treasury": "بنك القاهرة", "amount": 300000, "currency": "EGP", "capital_acc": "3102"},
        {"treasury": "بنك دبي", "amount": 220000, "currency": "AED", "capital_acc": "3103"},
        {"treasury": "صندوق القاهرة", "amount": 50000, "currency": "EGP", "capital_acc": "3102"},
    ]

    # إنشاء قيد افتتاحي واحد
    db.fix_sequence("journal_entries")
    db.cur.execute("""
        INSERT INTO journal_entries (entry_number, entry_date, description, status,
            currency, exchange_rate, branch_id, source, created_by, posted_at)
        VALUES (%s, %s, %s, 'posted', 'SAR', 1.0, %s, 'manual', %s, %s)
        RETURNING id
    """, ("JE-OPE-001", today, "رصيد افتتاحي - الخزائن والبنوك", branch_id, db.admin_id, today))
    je_id = db.cur.fetchone()["id"]

    line_num = 0
    for ob in opening_balances:
        # جلب GL account_id من الخزينة في قاعدة البيانات
        db.cur.execute("SELECT gl_account_id, account_type FROM treasury_accounts WHERE name = %s", (ob["treasury"],))
        treasury = db.cur.fetchone()
        if not treasury or not treasury["gl_account_id"]:
            print(f"  ⚠ لا يوجد GL للخزينة: {ob['treasury']}")
            continue

        rate = exchange_rates.get(ob["currency"], 1.0)
        amount_base = round(ob["amount"] * rate, 4)

        # debit للخزينة
        gl_acc_id = treasury["gl_account_id"]
        db.fix_sequence("journal_lines")

        db.cur.execute("""
            INSERT INTO journal_lines (journal_entry_id, account_id,
                debit, credit, amount_currency, currency, description)
            VALUES (%s, %s, %s, 0, %s, %s, %s)
        """, (je_id, gl_acc_id, amount_base, ob["amount"], ob["currency"],
              f"رصيد افتتاحي - {ob['treasury']}"))

        # credit لرأس المال
        db.fix_sequence("journal_lines")
        capital_id = account_ids.get(ob["capital_acc"], {}).get("id")
        db.cur.execute("""
            INSERT INTO journal_lines (journal_entry_id, account_id,
                debit, credit, amount_currency, currency, description)
            VALUES (%s, %s, 0, %s, %s, %s, %s)
        """, (je_id, capital_id, amount_base, ob["amount"], ob["currency"],
              f"رأس المال - {ob['currency']}"))

        sar_equiv = ob["amount"] * rate
        print(f"  ✓ {ob['treasury']}: {ob['amount']:,.0f} {ob['currency']} = {sar_equiv:,.0f} SAR")

    # تحديث أرصدة الحسابات بناءً على القيود
    db.cur.execute("""
        SELECT account_id,
            SUM(debit) - SUM(credit) as net_balance
        FROM journal_lines
        WHERE journal_entry_id = %s
        GROUP BY account_id
    """, (je_id,))
    for r in db.cur.fetchall():
        db.cur.execute("""
            UPDATE accounts SET balance = %s, balance_currency = %s
            WHERE id = %s
        """, (r["net_balance"], r["net_balance"], r["account_id"]))

    db.commit()
    print(f"  ✓ قيد افتتاحي #{je_id}: {line_num} سطر")


def verify_data(db: DBHelper):
    """التحقق من اكتمال البيانات"""
    print("\n═══ التحقق من اكتمال البيانات ═══")

    checks = [
        ("currencies", 5),
        ("branches", 4),
        ("accounts", 120),
        ("treasury_accounts", 5),
        ("departments", 6),
        ("warehouses", 3),
        ("products", 3),
        ("customers", 3),
        ("suppliers", 1),
        ("employees", 10),
        ("company_users", 11),
    ]

    all_ok = True
    for table, min_count in checks:
        try:
            db.cur.execute(f"SELECT COUNT(*) as c FROM {table}")
            count = db.cur.fetchone()["c"]
            status = "✓" if count >= min_count else "✗"
            print(f"  {status} {table}: {count} (expected ≥{min_count})")
            if count < min_count:
                all_ok = False
        except Exception as e:
            print(f"  ✗ {table}: {e}")
            all_ok = False

    # التحقق من ترابط القيود
    print("\n── التحقق من ترابط القيود ──")
    db.cur.execute("""
        SELECT je.id, je.entry_number,
            SUM(jl.debit) as total_debit,
            SUM(jl.credit) as total_credit,
            ABS(SUM(jl.debit) - SUM(jl.credit)) as diff
        FROM journal_entries je
        JOIN journal_lines jl ON jl.journal_entry_id = je.id
        WHERE je.status = 'posted'
        GROUP BY je.id, je.entry_number
        HAVING ABS(SUM(jl.debit) - SUM(jl.credit)) > 0.01
    """)
    unbalanced = db.cur.fetchall()
    if unbalanced:
        print(f"  ✗ {len(unbalanced)} قيد غير متوازن!")
        for u in unbalanced:
            print(f"    - {u['entry_number']}: debit={u['total_debit']}, credit={u['total_credit']}, diff={u['diff']}")
        all_ok = False
    else:
        print(f"  ✓ جميع القيود المتداولة متوازنة")

    # التحقق من أرصدة الحسابات
    print("\n── التحقق من أرصدة الحسابات ──")
    db.cur.execute("""
        SELECT a.account_number, a.name, a.currency, a.balance, a.balance_currency
        FROM accounts a
        WHERE a.balance != 0 OR a.balance_currency != 0
        ORDER BY a.account_number
    """)
    for r in db.cur.fetchall():
        print(f"  {r['account_number']} - {r['name']}: balance={r['balance']:,.2f} {r.get('currency','SAR')}")

    return all_ok


def print_summary(db: DBHelper):
    """طباعة ملخص"""
    print("\n" + "═" * 60)
    print("  ملخص البيانات المُدخلة لشركة dc4eaa49")
    print("═" * 60)

    db.cur.execute("SELECT COUNT(*) as c FROM branches")
    print(f"\n  الفروع: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM currencies")
    print(f"  العملات: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM accounts")
    print(f"  الحسابات: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM treasury_accounts")
    print(f"  الخزائن: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM departments")
    print(f"  الإدارات: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM warehouses")
    print(f"  المستودعات: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM products")
    print(f"  المنتجات: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM customers")
    print(f"  العملاء: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM suppliers")
    print(f"  الموردين: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM employees")
    print(f"  الموظفين: {db.cur.fetchone()['c']}")
    db.cur.execute("SELECT COUNT(*) as c FROM company_users")
    print(f"  المستخدمين: {db.cur.fetchone()['c']}")

    print("\n  المستخدمون وكلمة المرور: As123321")
    print("  ┌─────────────────────┬──────────────────┬─────────────────┐")
    print("  │ المستخدم            │ الدور            │ الفروع          │")
    print("  ├─────────────────────┼──────────────────┼─────────────────┤")
    users = [
        ("omar", "superuser", "كل الفروع"),
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
    for username, role, branches in users:
        print(f"  │ {username:<19} │ {role:<16} │ {branches:<15} │")
    print("  └─────────────────────┴──────────────────┴─────────────────┘")


# ═══════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════

def clean_data(db: DBHelper):
    """حذف جميع البيانات (إلا المستخدم الرئيسي والحسابات)"""
    print("\n═══ تنظيف البيانات ═══")

    tables = [
        "journal_lines", "journal_entries", "invoice_lines", "invoices",
        "payment_vouchers", "payment_allocations", "supplier_transactions",
        "customer_transactions", "party_transactions", "treasury_transactions",
        "sales_quotation_lines", "sales_quotations", "sales_order_lines", "sales_orders",
        "sales_return_lines", "sales_returns", "purchase_order_lines", "purchase_orders",
        "inventory_transactions", "inventory", "stock_adjustments",
        "pos_order_lines", "pos_orders", "pos_sessions",
        "payroll_entries", "payroll_periods", "attendance", "leave_requests",
        "employee_loans", "employees", "parties", "party_groups",
        "products", "product_categories", "warehouses", "departments",
        "employee_positions", "cost_centers", "treasury_accounts",
        "exchange_rates", "currencies", "tax_rates", "branches",
        "company_settings",
    ]

    try:
        db.cur.execute("SET session_replication_role = 'replica'")
    except Exception:
        db.conn.rollback()

    for table in tables:
        try:
            db.cur.execute(f"SELECT COUNT(*) as c FROM {table}")
            count = db.cur.fetchone()["c"]
            if count > 0:
                db.cur.execute(f"TRUNCATE TABLE {table} CASCADE")
                print(f"  ✓ {table}: {count} صف محذوف")
        except Exception as e:
            db.conn.rollback()
            try:
                db.cur.execute(f"DELETE FROM {table}")
                print(f"  ✓ {table}: deleted")
            except Exception:
                db.conn.rollback()

    try:
        db.cur.execute("SET session_replication_role = 'origin'")
    except Exception:
        db.conn.rollback()

    # تصفير أرصدة الحسابات
    db.cur.execute("UPDATE accounts SET balance = 0, balance_currency = 0")
    print(f"  ✓ تصفير أرصدة {db.cur.rowcount} حساب")

    # إصلاح التسلسلات
    for table in tables:
        db.fix_sequence(table)
    db.fix_sequence("company_users")

    db.commit()
    print("  ✅ تم التنظيف")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AMAN ERP - Seed dc4eaa49")
    parser.add_argument("--clean", action="store_true", help="Clean data first")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║   AMAN ERP - تعبئة بيانات شركة dc4eaa49               ║")
    print("╚══════════════════════════════════════════════════════════╝")

    db = DBHelper()
    db.get_admin_id()

    if args.clean:
        clean_data(db)

    try:
        seed_currencies(db)
        seed_exchange_rates(db)
        seed_branches(db)
        seed_company_settings(db)
        seed_capital_accounts(db)
        seed_treasury_accounts(db)
        seed_departments(db)
        seed_warehouses(db)
        seed_product_categories(db)
        seed_products(db)
        seed_customers(db)
        seed_suppliers(db)
        seed_employees(db)
        seed_fiscal_year(db)
        seed_opening_journal_entries(db)

        ok = verify_data(db)
        print_summary(db)

        if ok:
            print("\n  ✅ تمت التعبئة بنجاح! النظام جاهز للاستخدام.")
        else:
            print("\n  ⚠️ تمت التعبئة مع بعض التحذيرات.")

        # حفظ المراجع
        refs_path = "tests/.seed-refs-dc4eaa49.json"
        with open(refs_path, "w") as f:
            json.dump({"company_code": COMPANY_CODE, "refs": db.refs}, f, indent=2, ensure_ascii=False)
        print(f"\n  📁 حُفظت المراجع في: {refs_path}")

    except Exception as e:
        print(f"\n  ✗ خطأ: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
