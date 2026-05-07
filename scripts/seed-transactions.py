#!/usr/bin/env python3
"""
AMAN ERP - Transactions Seed Script (v2)
==========================================
يُدخل بيانات المعاملات لجميع الوحدات عبر API.

الاستخدام:
    python scripts/seed-transactions.py --company-code 9d08756c
    python scripts/seed-transactions.py --company-code 9d08756c --batch purchases
"""

import argparse
import sys
from datetime import date, timedelta

import requests

DEFAULT_URL = "http://localhost:8000"
COMPANY_CODE = "9d08756c"
COMPANY_USER = "omar"
COMPANY_PASS = "As123321"


class AmanClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token = None
        self.refs = {}

    def _h(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def login(self, username, password, company_code):
        res = self.session.post(
            f"{self.base_url}/api/auth/login",
            data={"username": username, "password": password, "grant_type": "password", "company_code": company_code},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        res.raise_for_status()
        self.token = res.json()["access_token"]

    def get(self, path):
        r = self.session.get(f"{self.base_url}{path}", headers=self._h())
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = self.session.post(f"{self.base_url}{path}", json=body, headers=self._h())
        if not r.ok:
            print(f"  ✗ POST {path} → {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
        return r.json()

    def put(self, path, body):
        r = self.session.put(f"{self.base_url}{path}", json=body, headers=self._h())
        if not r.ok:
            print(f"  ✗ PUT {path} → {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
        return r.json()


def load_refs(client):
    import json, os
    refs_path = "tests/.seed-refs.json"
    if os.path.exists(refs_path):
        with open(refs_path) as f:
            data = json.load(f)
            client.refs = data.get("refs", {})
        print(f"  ✓ تم تحميل {len(client.refs)} مرجع")


def get_list(data):
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


# ═══════════════════════════════════════════════════════════════
# الدفعة 1: المشتريات
# ═══════════════════════════════════════════════════════════════

def seed_purchases(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 1: المشتريات 🛒                     ║")
    print("╚══════════════════════════════════════════════════════════╝")

    prods = get_list(client.get("/api/inventory/products"))
    tablet = next((p for p in prods if p.get("item_code") == "GH-TAB-10"), None)
    scanner = next((p for p in prods if p.get("item_code") == "GH-SCN-01"), None)

    supps = get_list(client.get("/api/parties/suppliers"))
    supplier = supps[0] if supps else None

    whs = get_list(client.get("/api/inventory/warehouses"))
    wh_ruh = next((w for w in whs if w.get("code") == "WH-RUH"), None)

    if not tablet or not scanner or not supplier or not wh_ruh:
        print("  ✗ بيانات ناقصة")
        return

    # سيناريو 1: أمر شراء + اعتماد + استلام
    print("\n── سيناريو 1: أمر شراء + اعتماد + استلام ──")
    try:
        po = client.post("/api/buying/orders", {
            "supplier_id": supplier["id"],
            "order_date": str(date.today()),
            "expected_date": str(date.today() + timedelta(days=7)),
            "branch_id": client.refs.get("branch:riyadh"),
            "currency": "SAR",
            "items": [
                {"product_id": tablet["id"], "description": tablet["item_name"], "quantity": 100, "unit_price": 800, "tax_rate": 15},
            ],
        })
        po_id = po.get("id")
        print(f"  ✓ أمر شراء #{po_id}")

        # اعتماد أمر الشراء
        client.post(f"/api/buying/orders/{po_id}/approve", {})
        print(f"  ✓ اعتماد أمر شراء #{po_id}")

        # استلام
        po_detail = client.get(f"/api/buying/orders/{po_id}")
        lines = po_detail.get("items", po_detail.get("lines", []))
        if lines:
            receive_items = [{"line_id": line["id"], "received_quantity": line["quantity"]} for line in lines]
            client.post(f"/api/buying/orders/{po_id}/receive", {
                "items": receive_items,
                "warehouse_id": wh_ruh["id"],
            })
            print(f"  ✓ استلام كامل في مستودع الرياض")
    except Exception as e:
        print(f"  ✗ {e}")

    # سيناريو 2: أمر شراء متعدد الأسطر
    print("\n── سيناريو 2: أمر شراء متعدد الأسطر ──")
    try:
        po = client.post("/api/buying/orders", {
            "supplier_id": supplier["id"],
            "order_date": str(date.today()),
            "branch_id": client.refs.get("branch:riyadh"),
            "currency": "SAR",
            "items": [
                {"product_id": tablet["id"], "description": tablet["item_name"], "quantity": 50, "unit_price": 800, "tax_rate": 15},
                {"product_id": scanner["id"], "description": scanner["item_name"], "quantity": 30, "unit_price": 280, "tax_rate": 15},
            ],
        })
        print(f"  ✓ أمر شراء #{po.get('id')} (50 tablet + 30 scanner)")
    except Exception as e:
        print(f"  ✗ {e}")

    # سيناريو 3: فاتورة مشتريات
    print("\n── سيناريو 3: فاتورة مشتريات ──")
    try:
        inv = client.post("/api/buying/invoices", {
            "supplier_id": supplier["id"],
            "invoice_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "branch_id": client.refs.get("branch:riyadh"),
            "currency": "SAR",
            "items": [
                {"product_id": tablet["id"], "description": "شراء مباشر", "quantity": 20, "unit_price": 800, "tax_rate": 15},
            ],
        })
        print(f"  ✓ فاتورة مشتريات #{inv.get('id')}")
    except Exception as e:
        print(f"  ✗ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 2: المبيعات
# ═══════════════════════════════════════════════════════════════

def seed_sales(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 2: المبيعات 💰                      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    prods = get_list(client.get("/api/inventory/products"))
    tablet = next((p for p in prods if p.get("item_code") == "GH-TAB-10"), None)
    scanner = next((p for p in prods if p.get("item_code") == "GH-SCN-01"), None)

    custs = get_list(client.get("/api/parties/customers"))
    riyadh_cust = next((c for c in custs if "نجد" in c.get("name", "")), None)
    cairo_cust = next((c for c in custs if "دلتا" in c.get("name", "")), None)

    if not tablet or not riyadh_cust:
        print("  ✗ بيانات ناقصة")
        return

    # سيناريو 1: فاتورة مبيعات SAR
    print("\n── سيناريو 1: فاتورة مبيعات بالـ SAR ──")
    try:
        inv = client.post("/api/sales/invoices", {
            "customer_id": riyadh_cust["id"],
            "invoice_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "branch_id": client.refs.get("branch:riyadh"),
            "warehouse_id": client.refs.get("wh:riyadh"),
            "currency": "SAR",
            "items": [
                {"product_id": tablet["id"], "description": tablet["item_name"], "quantity": 10, "unit_price": 1200, "tax_rate": 15},
                {"product_id": scanner["id"], "description": scanner["item_name"], "quantity": 5, "unit_price": 450, "tax_rate": 15},
            ],
        })
        total = inv.get("total", inv.get("grand_total", "N/A"))
        print(f"  ✓ فاتورة #{inv.get('id')} = {total} SAR")
    except Exception as e:
        print(f"  ✗ {e}")

    # سيناريو 2: فاتورة مبيعات EGP
    print("\n── سيناريو 2: فاتورة مبيعات بالـ EGP ──")
    if cairo_cust:
        try:
            inv = client.post("/api/sales/invoices", {
                "customer_id": cairo_cust["id"],
                "invoice_date": str(date.today()),
                "branch_id": client.refs.get("branch:cairo"),
                "warehouse_id": client.refs.get("wh:cairo"),
                "currency": "EGP",
                "items": [
                    {"product_id": tablet["id"], "description": tablet["item_name"], "quantity": 20, "unit_price": 16000, "tax_rate": 14},
                ],
            })
            print(f"  ✓ فاتورة #{inv.get('id')} بالـ EGP")
        except Exception as e:
            print(f"  ✗ {e}")

    # سيناريو 3: فاتورة مع سداد
    print("\n── سيناريو 3: فاتورة مع سداد جزئي ──")
    try:
        treasuries = get_list(client.get("/api/treasury/accounts"))
        riyadh_bank = next((t for t in treasuries if "الرياض" in t.get("name", "")), None)
        inv = client.post("/api/sales/invoices", {
            "customer_id": riyadh_cust["id"],
            "invoice_date": str(date.today()),
            "branch_id": client.refs.get("branch:riyadh"),
            "currency": "SAR",
            "payment_method": "bank",
            "paid_amount": 5000,
            "treasury_id": riyadh_bank["id"] if riyadh_bank else None,
            "items": [
                {"product_id": scanner["id"], "description": scanner["item_name"], "quantity": 20, "unit_price": 450, "tax_rate": 15},
            ],
        })
        print(f"  ✓ فاتورة #{inv.get('id')} مع سداد 5000 SAR")
    except Exception as e:
        print(f"  ✗ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 3: المخزون
# ═══════════════════════════════════════════════════════════════

def seed_inventory(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 3: المخزون 📦                       ║")
    print("╚══════════════════════════════════════════════════════════╝")

    prods = get_list(client.get("/api/inventory/products"))
    tablet = next((p for p in prods if p.get("item_code") == "GH-TAB-10"), None)
    scanner = next((p for p in prods if p.get("item_code") == "GH-SCN-01"), None)

    whs = get_list(client.get("/api/inventory/warehouses"))
    wh_ruh = next((w for w in whs if w.get("code") == "WH-RUH"), None)
    wh_cai = next((w for w in whs if w.get("code") == "WH-CAI"), None)

    if not tablet or not wh_ruh:
        print("  ✗ بيانات ناقصة")
        return

    # سيناريو 1: رصيد افتتاحي (تسوية مخزون)
    print("\n── سيناريو 1: رصيد افتتاحي ──")
    for prod in [tablet, scanner]:
        try:
            client.post("/api/inventory/adjustments", {
                "product_id": prod["id"],
                "warehouse_id": wh_ruh["id"],
                "quantity": 200 if prod == tablet else 100,
                "adjustment_type": "add",
                "reason": "رصيد افتتاحي",
                "adjustment_date": str(date.today()),
            })
            print(f"  ✓ {prod['item_name']}: +{'200' if prod == tablet else '100'} وحدة")
        except Exception as e:
            print(f"  ✗ {prod['item_name']}: {e}")

    # سيناريو 2: تحويل بين مستودعات
    print("\n── سيناريو 2: تحويل بين مستودعات ──")
    if wh_cai:
        try:
            client.post("/api/inventory/transfers", {
                "product_id": tablet["id"],
                "source_warehouse_id": wh_ruh["id"],
                "destination_warehouse_id": wh_cai["id"],
                "quantity": 50,
                "transfer_date": str(date.today()),
                "notes": "تحويل اختباري",
            })
            print(f"  ✓ تحويل 50 tablet من الرياض → القاهرة")
        except Exception as e:
            print(f"  ✗ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 4: المالية
# ═══════════════════════════════════════════════════════════════

def seed_finance(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 4: المالية 📊                       ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # سيناريو 1: سنة مالية
    print("\n── سيناريو 1: سنة مالية 2026 ──")
    try:
        client.post("/api/accounting/fiscal-years", {
            "year": 2026,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        })
        print(f"  ✓ سنة مالية 2026")
    except Exception as e:
        print(f"  ⚠ {e}")

    # سيناريو 2: قيد يدوي
    print("\n── سيناريو 2: قيد يدوي ──")
    try:
        accs = get_list(client.get("/api/accounting/accounts"))
        cash = next((a for a in accs if a.get("account_number") == "1110"), None)
        sales = next((a for a in accs if a.get("account_number") == "4100"), None)
        if cash and sales:
            je = client.post("/api/accounting/journal-entries", {
                "entry_date": str(date.today()),
                "description": "قيد تسوية - إيرادات متنوعة",
                "branch_id": client.refs.get("branch:riyadh"),
                "lines": [
                    {"account_id": cash["id"], "debit": 5000, "credit": 0},
                    {"account_id": sales["id"], "debit": 0, "credit": 5000},
                ],
            })
            print(f"  ✓ قيد #{je.get('id', 'N/A')}: 5000 SAR")
    except Exception as e:
        print(f"  ✗ {e}")

    # سيناريو 3: مراكز تكلفة
    print("\n── سيناريو 3: مراكز تكلفة ──")
    try:
        client.post("/api/cost-centers/", {"center_name": "مركز تكلفة الرياض", "center_code": "CC-RUH", "currency": "SAR"})
        client.post("/api/cost-centers/", {"center_name": "مركز تكلفة القاهرة", "center_code": "CC-CAI", "currency": "EGP"})
        client.post("/api/cost-centers/", {"center_name": "مركز تكلفة دبي", "center_code": "CC-DXB", "currency": "AED"})
        print(f"  ✓ 3 مراكز تكلفة")
    except Exception as e:
        print(f"  ⚠ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 5: الموارد البشرية
# ═══════════════════════════════════════════════════════════════

def seed_hr(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 5: الموارد البشرية 👥               ║")
    print("╚══════════════════════════════════════════════════════════╝")

    emps = get_list(client.get("/api/hr/employees/"))
    if not emps:
        print("  ✗ لا يوجد موظفين")
        return

    # سيناريو 1: طلب إجازة
    print("\n── سيناريو 1: طلبات إجازة ──")
    for emp in emps[:3]:
        try:
            client.post("/api/hr/leaves", {
                "employee_id": emp["id"],
                "leave_type": "annual",
                "start_date": str(date.today() + timedelta(days=10)),
                "end_date": str(date.today() + timedelta(days=12)),
                "reason": "إجازة سنوية",
            })
            print(f"  ✓ إجازة: {emp.get('first_name', '')} {emp.get('last_name', '')}")
        except Exception as e:
            print(f"  ⚠ {emp.get('first_name', '')}: {e}")

    # سيناريو 2: سلفة
    print("\n── سيناريو 2: سلفة موظف ──")
    if len(emps) > 1:
        try:
            client.post("/api/hr/advances", {
                "employee_id": emps[1]["id"],
                "amount": 5000,
                "total_installments": 5,
                "start_date": str(date.today()),
                "reason": "سلفة طارئة",
            })
            print(f"  ✓ سلفة 5000 لـ {emps[1].get('first_name', '')}")
        except Exception as e:
            print(f"  ⚠ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 6: التصنيع
# ═══════════════════════════════════════════════════════════════

def seed_manufacturing(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 6: التصنيع 🏭                       ║")
    print("╚══════════════════════════════════════════════════════════╝")

    prods = get_list(client.get("/api/inventory/products"))
    tablet = next((p for p in prods if p.get("item_code") == "GH-TAB-10"), None)
    scanner = next((p for p in prods if p.get("item_code") == "GH-SCN-01"), None)

    # سيناريو 1: مركز عمل
    print("\n── سيناريو 1: مراكز عمل ──")
    try:
        client.post("/api/manufacturing/work-centers", {
            "name": "خط تجميع الرياض",
            "code": "WC-RUH-01",
            "capacity_per_day": 50,
            "cost_per_hour": 150,
        })
        print(f"  ✓ مركز عمل: خط تجميع الرياض")
    except Exception as e:
        print(f"  ⚠ {e}")

    # سيناريو 2: BOM
    print("\n── سيناريو 2: قائمة مواد BOM ──")
    if tablet and scanner:
        try:
            client.post("/api/manufacturing/boms", {
                "name": "BOM - جهاز لوحي",
                "product_id": tablet["id"],
                "quantity": 1,
                "components": [
                    {"component_product_id": scanner["id"], "quantity": 1},
                ],
            })
            print(f"  ✓ BOM: جهاز لوحي ← قارئ باركود")
        except Exception as e:
            print(f"  ⚠ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 7: POS
# ═══════════════════════════════════════════════════════════════

def seed_pos(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 7: POS 🏪                           ║")
    print("╚══════════════════════════════════════════════════════════╝")

    prods = get_list(client.get("/api/inventory/products"))
    tablet = next((p for p in prods if p.get("item_code") == "GH-TAB-10"), None)

    emps = get_list(client.get("/api/hr/employees/"))
    cashier = next((e for e in emps if e.get("role") == "cashier"), None)

    whs = get_list(client.get("/api/inventory/warehouses"))
    wh_dxb = next((w for w in whs if w.get("code") == "WH-DXB"), None)

    if not cashier or not wh_dxb:
        print("  ✗ بيانات ناقصة (cashier/warehouse)")
        return

    # فتح جلسة
    print("\n── سيناريو 1: فتح جلسة POS ──")
    try:
        session = client.post("/api/pos/sessions/open", {
            "branch_id": client.refs.get("branch:dubai"),
            "warehouse_id": wh_dxb["id"],
            "opening_balance": 1000,
        })
        session_id = session.get("id")
        print(f"  ✓ جلسة POS #{session_id}")

        # طلب
        if tablet:
            try:
                client.post("/api/pos/orders", {
                    "session_id": session_id,
                    "items": [{"product_id": tablet["id"], "quantity": 2, "unit_price": 1175}],
                    "payments": [{"method": "cash", "amount": 2350}],
                })
                print(f"  ✓ طلب POS: 2 × tablet = 2350 AED")
            except Exception as e:
                print(f"  ⚠ {e}")

        # إغلاق
        client.post(f"/api/pos/sessions/{session_id}/close", {"closing_balance": 3350})
        print(f"  ✓ إغلاق جلسة POS")
    except Exception as e:
        print(f"  ⚠ {e}")


# ═══════════════════════════════════════════════════════════════
# الدفعة 8: المشاريع والعقود
# ═══════════════════════════════════════════════════════════════

def seed_projects(client):
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║              الدفعة 8: المشاريع والعقود 📋              ║")
    print("╚══════════════════════════════════════════════════════════╝")

    custs = get_list(client.get("/api/parties/customers"))
    riyadh_cust = next((c for c in custs if "نجد" in c.get("name", "")), None)

    prods = get_list(client.get("/api/inventory/products"))
    impl = next((p for p in prods if p.get("item_code") == "GH-SRV-IMPL"), None)

    emps = get_list(client.get("/api/hr/employees/"))
    ceo = next((e for e in emps if e.get("role") == "ceo"), None)

    # مشروع
    print("\n── سيناريو 1: مشروع ──")
    try:
        project = client.post("/api/projects/", {
            "project_name": "تطبيق نظام ERP",
            "project_code": "PRJ-2026-001",
            "customer_id": riyadh_cust["id"] if riyadh_cust else None,
            "manager_id": ceo["id"] if ceo else None,
            "branch_id": client.refs.get("branch:riyadh"),
            "planned_budget": 500000,
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=180)),
            "status": "active",
        })
        pid = project.get("id")
        print(f"  ✓ مشروع #{pid}: تطبيق نظام ERP")

        for task_name in ["تحليل المتطلبات", "تصميم قاعدة البيانات", "تطوير الواجهات", "اختبار النظام", "التدريب"]:
            try:
                client.post(f"/api/projects/{pid}/tasks", {"task_name": task_name})
            except Exception:
                pass
        print(f"  ✓ 5 مهام")
    except Exception as e:
        print(f"  ✗ {e}")

    # عقد
    print("\n── سيناريو 2: عقد ──")
    if riyadh_cust and impl:
        try:
            client.post("/api/contracts/", {
                "contract_number": "GH-C-2026-001",
                "party_id": riyadh_cust["id"],
                "contract_type": "subscription",
                "start_date": str(date.today()),
                "end_date": str(date.today() + timedelta(days=365)),
                "currency": "SAR",
                "total_amount": 240000,
                "billing_interval": "monthly",
                "items": [
                    {"product_id": impl["id"], "description": "دعم وصيانة", "quantity": 12, "unit_price": 20000, "tax_rate": 15},
                ],
            })
            print(f"  ✓ عقد: دعم وصيانة (240,000 SAR/سنة)")
        except Exception as e:
            print(f"  ⚠ {e}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

BATCHES = {
    "purchases": seed_purchases,
    "sales": seed_sales,
    "inventory": seed_inventory,
    "finance": seed_finance,
    "hr": seed_hr,
    "manufacturing": seed_manufacturing,
    "pos": seed_pos,
    "projects": seed_projects,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--company-code", default=COMPANY_CODE)
    parser.add_argument("--batch", choices=list(BATCHES.keys()) + ["all"], default="all")
    args = parser.parse_args()

    client = AmanClient(args.url)

    print("╔══════════════════════════════════════════════════════════╗")
    print("║        AMAN ERP - تعبئة المعاملات (v2)                  ║")
    print("╚══════════════════════════════════════════════════════════╝")

    client.login(COMPANY_USER, COMPANY_PASS, args.company_code)
    print(f"  ✓ تسجيل الدخول")
    load_refs(client)

    if args.batch == "all":
        for name, func in BATCHES.items():
            func(client)
    else:
        BATCHES[args.batch](client)

    print("\n" + "═" * 60)
    print("  ✅ انتهت التعبئة!")
    print("═" * 60)


if __name__ == "__main__":
    main()
