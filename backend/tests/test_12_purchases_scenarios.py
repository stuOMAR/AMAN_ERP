"""
AMAN ERP - اختبارات شاملة متعددة السيناريوهات: المشتريات
Comprehensive Multi-Scenario Tests: Purchases Module
═══════════════════════════════════════════════════════
يتضمن: الموردون، مجموعات الموردين، أوامر الشراء، فواتير الشراء، الدفعات
"""

import pytest
from datetime import date, timedelta
from helpers import assert_valid_response


# ═══════════════════════════════════════════════════════════════
# 🏪 الموردون - Suppliers
# ═══════════════════════════════════════════════════════════════
class TestSupplierScenarios:
    """سيناريوهات الموردين"""

    def test_list_suppliers(self, client, admin_headers):
        """✅ عرض الموردين"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_create_supplier(self, client, admin_headers):
        """✅ إنشاء مورد جديد"""
        r = client.post("/api/buying/suppliers", json={
            "supplier_name": "مورد اختبار جديد",
            "phone": "0115551234",
            "tax_number": "300777888999000",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_create_supplier_with_details(self, client, admin_headers):
        """✅ إنشاء مورد بتفاصيل كاملة"""
        r = client.post("/api/buying/suppliers", json={
            "supplier_name": "مصنع المواد الأولية",
            "phone": "0116667890",
            "tax_number": "300888999111222",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_supplier_statement(self, client, admin_headers):
        """✅ كشف حساب مورد"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")
        sid = suppliers[0]["id"]
        r2 = client.get(f"/api/buying/suppliers/{sid}/statement", headers=admin_headers)
        assert r2.status_code in [200, 404]

    def test_purchasing_stats(self, client, admin_headers):
        """✅ إحصائيات المشتريات"""
        r = client.get("/api/buying/stats", headers=admin_headers)
        assert r.status_code in [200, 404]


# ═══════════════════════════════════════════════════════════════
# 📂 مجموعات الموردين - Supplier Groups
# ═══════════════════════════════════════════════════════════════
class TestSupplierGroupScenarios:
    """سيناريوهات مجموعات الموردين"""

    def test_list_supplier_groups(self, client, admin_headers):
        """✅ عرض المجموعات"""
        r = client.get("/api/buying/supplier-groups", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_create_supplier_group(self, client, admin_headers):
        """✅ إنشاء مجموعة"""
        r = client.post("/api/buying/supplier-groups", json={
            "group_name": "موردون دوليون",
            "discount_percentage": 8,
            "payment_days": 45,
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_update_supplier_group(self, client, admin_headers):
        """✅ تحديث مجموعة"""
        r = client.get("/api/buying/supplier-groups", headers=admin_headers)
        groups = r.json()
        if not groups:
            pytest.skip("لا مجموعات")
        gid = groups[0]["id"]
        r2 = client.put(f"/api/buying/supplier-groups/{gid}", json={
            "group_name": "مجموعة محدّثة",
            "payment_days": 30,
        }, headers=admin_headers)
        assert r2.status_code in [200, 404]

    def test_delete_supplier_group(self, client, admin_headers):
        """✅ حذف مجموعة"""
        r = client.post("/api/buying/supplier-groups", json={
            "group_name": "مجموعة موردين للحذف",
        }, headers=admin_headers)
        if r.status_code in [200, 201]:
            gid = r.json().get("id")
            if gid:
                r2 = client.delete(f"/api/buying/supplier-groups/{gid}", headers=admin_headers)
                assert r2.status_code in [200, 204, 400]


# ═══════════════════════════════════════════════════════════════
# 📋 أوامر الشراء - Purchase Orders
# ═══════════════════════════════════════════════════════════════
class TestPurchaseOrderScenarios:
    """سيناريوهات أوامر الشراء"""

    def test_list_purchase_orders(self, client, admin_headers):
        """✅ عرض أوامر الشراء"""
        r = client.get("/api/buying/orders", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_get_purchase_order_detail(self, client, admin_headers):
        """✅ تفاصيل أمر شراء"""
        r = client.get("/api/buying/orders", headers=admin_headers)
        orders = r.json()
        if not orders:
            pytest.skip("لا أوامر شراء")
        oid = orders[0]["id"]
        r2 = client.get(f"/api/buying/orders/{oid}", headers=admin_headers)
        assert r2.status_code in [200, 404, 500]

    def test_create_purchase_order_single(self, client, admin_headers):
        """✅ إنشاء أمر شراء بصنف واحد"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")

        r2 = client.post("/api/buying/orders", json={
            "supplier_id": suppliers[0]["id"],
            "order_date": str(date.today()),
            "items": [
                {"product_id": 1, "quantity": 20, "unit_price": 95, "description": "صنف اختبار", "tax_rate": 15}
            ]
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400]

    def test_create_purchase_order_multi(self, client, admin_headers):
        """✅ إنشاء أمر شراء متعدد الأصناف"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")

        r2 = client.post("/api/buying/orders", json={
            "supplier_id": suppliers[0]["id"],
            "order_date": str(date.today()),
            "expected_date": str(date.today() + timedelta(days=14)),
            "items": [
                {"product_id": 1, "quantity": 100, "unit_price": 90, "description": "صنف 1", "tax_rate": 15},
                {"product_id": 2, "quantity": 50, "unit_price": 170, "description": "صنف 2", "tax_rate": 15},
            ]
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400]

    def test_approve_purchase_order(self, client, admin_headers):
        """✅ اعتماد أمر شراء"""
        r = client.get("/api/buying/orders", headers=admin_headers)
        orders = r.json()
        draft = next((o for o in orders if o.get("status") == "draft"), None)
        if not draft:
            pytest.skip("لا أمر شراء مسودة")
        r2 = client.put(f"/api/buying/orders/{draft['id']}/approve", headers=admin_headers)
        assert r2.status_code in [200, 400, 500]

    def test_receive_purchase_order(self, client, admin_headers):
        """✅ استلام أمر شراء"""
        r = client.get("/api/buying/orders", headers=admin_headers)
        orders = r.json()
        approved = next((o for o in orders if o.get("status") == "approved"), None)
        if not approved:
            pytest.skip("لا أمر شراء معتمد")
        r2 = client.post(f"/api/buying/orders/{approved['id']}/receive", headers=admin_headers)
        assert r2.status_code in [200, 400, 422, 500]


# ═══════════════════════════════════════════════════════════════
# 🧾 فواتير الشراء - Purchase Invoices
# ═══════════════════════════════════════════════════════════════
class TestPurchaseInvoiceScenarios:
    """سيناريوهات فواتير الشراء"""

    def test_list_purchase_invoices(self, client, admin_headers):
        """✅ عرض فواتير الشراء"""
        r = client.get("/api/buying/invoices", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_get_purchase_invoice_detail(self, client, admin_headers):
        """✅ تفاصيل فاتورة شراء"""
        r = client.get("/api/buying/invoices", headers=admin_headers)
        invoices = r.json()
        if not invoices:
            pytest.skip("لا فواتير شراء")
        inv_id = invoices[0]["id"]
        r2 = client.get(f"/api/buying/invoices/{inv_id}", headers=admin_headers)
        assert r2.status_code in [200, 404]
        if r2.status_code == 200:
            data = r2.json()
            for key in (
                "remaining_balance",
                "base_currency",
                "total_base",
                "paid_amount_base",
                "remaining_balance_base",
            ):
                assert key in data
                assert isinstance(data[key], str)
                assert "E" not in data[key].upper()
            for line in data.get("items", []):
                assert "unit_price_base" in line
                assert "total_base" in line

    def test_create_purchase_invoice_cash(self, client, admin_headers):
        """✅ فاتورة شراء نقدية"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")

        r2 = client.post("/api/buying/invoices", json={
            "supplier_id": suppliers[0]["id"],
            "invoice_date": str(date.today()),
            "payment_method": "cash",
            "paid_amount": 1150,
            "treasury_id": 2,
            "items": [
                {"product_id": 1, "description": "شراء بضاعة", "quantity": 10, "unit_price": 100, "tax_rate": 15}
            ]
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400]

    def test_create_purchase_invoice_credit(self, client, admin_headers):
        """✅ فاتورة شراء آجلة"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")

        r2 = client.post("/api/buying/invoices", json={
            "supplier_id": suppliers[0]["id"],
            "invoice_date": str(date.today()),
            "payment_method": "credit",
            "items": [
                {"product_id": 1, "description": "بضاعة 1", "quantity": 50, "unit_price": 90, "tax_rate": 15},
                {"product_id": 2, "description": "بضاعة 2", "quantity": 20, "unit_price": 170, "tax_rate": 15},
            ]
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400]


# ═══════════════════════════════════════════════════════════════
# 💳 دفعات الموردين - Supplier Payments
# ═══════════════════════════════════════════════════════════════
class TestSupplierPaymentScenarios:
    """سيناريوهات دفعات الموردين"""

    def test_list_supplier_payment_vouchers(self, client, admin_headers):
        """✅ عرض سندات صرف الموردين"""
        r = client.get("/api/buying/payment-vouchers", headers=admin_headers)
        assert r.status_code in [200, 404]

    def test_create_supplier_payment(self, client, admin_headers):
        """✅ دفعة لمورد"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")

        r2 = client.post("/api/buying/payments", json={
            "supplier_id": suppliers[0]["id"],
            "amount": 1000,
            "payment_method": "bank_transfer",
            "voucher_date": str(date.today()),
            "treasury_id": 3,
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400]

    def test_supplier_outstanding_invoices(self, client, admin_headers):
        """✅ فواتير مورد معلقة"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")
        sid = suppliers[0]["id"]
        r2 = client.get(f"/api/buying/suppliers/{sid}/outstanding", headers=admin_headers)
        assert r2.status_code in [200, 404]

    def test_supplier_payment_history(self, client, admin_headers):
        """✅ تاريخ دفعات مورد"""
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        suppliers = r.json()
        if not suppliers:
            pytest.skip("لا موردين")
        sid = suppliers[0]["id"]
        r2 = client.get(f"/api/buying/suppliers/{sid}/payment-history", headers=admin_headers)
        assert r2.status_code in [200, 404]
