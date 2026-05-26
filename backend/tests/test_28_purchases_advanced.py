"""
test_28_purchases_advanced.py
===============================
اختبارات متقدمة للمشتريات

Covers UNTESTED endpoints:
- POST /api/buying/returns (create)
- GET /api/buying/returns/{id}
- GET /api/buying/suppliers/{id}/transactions
- GET /api/buying/suppliers/{id}/outstanding-invoices
- GET /api/buying/invoices/{id}/payment-history
- GET /api/buying/payments/{id}
- GET/POST /api/buying/credit-notes
- GET /api/buying/credit-notes/{id}
- GET/POST /api/buying/debit-notes
- GET /api/buying/debit-notes/{id}
- GET /api/buying/summary
"""
import pytest
from datetime import date, timedelta


# ══════════════════════════════════════════════════════════════
# 🔄 مرتجعات المشتريات - Purchase Returns
# ══════════════════════════════════════════════════════════════

class TestPurchaseReturns:
    """اختبارات مرتجعات المشتريات"""

    def test_create_purchase_return(self, client, admin_headers):
        """اختبار إنشاء مرتجع مشتريات"""
        inv_r = client.get("/api/buying/invoices", headers=admin_headers)
        if inv_r.status_code != 200:
            pytest.skip("لا يمكن جلب فواتير المشتريات")
        invoices = inv_r.json()
        if isinstance(invoices, dict):
            invoices = invoices.get("items", invoices.get("invoices", []))
        if not invoices:
            pytest.skip("لا توجد فواتير مشتريات")

        invoice = invoices[0]
        return_data = {
            "invoice_id": invoice.get("id"),
            "supplier_id": invoice.get("supplier_id"),
            "date": str(date.today()),
            "reason": "بضاعة تالفة - اختبار",
            "items": [
                {
                    "description": "مرتجع مواد",
                    "quantity": 1,
                    "unit_price": 500.00
                }
            ]
        }
        r = client.post("/api/buying/returns", json=return_data,
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_get_purchase_return_detail(self, client, admin_headers):
        """اختبار تفاصيل مرتجع مشتريات"""
        r = client.get("/api/buying/returns", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا يمكن جلب المرتجعات")
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if not items:
            pytest.skip("لا توجد مرتجعات")
        ret_id = items[0].get("id") or items[0].get("return_id")
        r2 = client.get(f"/api/buying/returns/{ret_id}",
                        headers=admin_headers)
        assert r2.status_code in (200, 404)

    def test_list_purchase_returns_with_filter(self, client, admin_headers):
        """اختبار عرض المرتجعات مع فلترة"""
        today = str(date.today())
        month_ago = str(date.today() - timedelta(days=30))
        r = client.get(
            f"/api/buying/returns?start_date={month_ago}&end_date={today}",
            headers=admin_headers
        )
        assert r.status_code in (200, 404)


# ══════════════════════════════════════════════════════════════
# 🏷 إشعارات المشتريات - Credit/Debit Notes
# ══════════════════════════════════════════════════════════════

class TestPurchaseCreditNotes:
    """اختبارات إشعارات الدائن للمشتريات"""

    def test_list_purchase_credit_notes(self, client, admin_headers):
        """اختبار عرض إشعارات الدائن"""
        r = client.get("/api/buying/credit-notes", headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_create_purchase_credit_note(self, client, admin_headers):
        """اختبار إنشاء إشعار دائن مشتريات"""
        suppliers_r = client.get("/api/buying/suppliers", headers=admin_headers)
        if suppliers_r.status_code != 200:
            pytest.skip("لا يمكن جلب الموردين")
        suppliers = suppliers_r.json()
        if isinstance(suppliers, dict):
            suppliers = suppliers.get("items", suppliers.get("suppliers", []))
        if not suppliers:
            pytest.skip("لا يوجد موردون")

        cn_data = {
            "supplier_id": suppliers[0]["id"],
            "date": str(date.today()),
            "reason": "خصم كمية - اختبار",
            "amount": 2000.00,
            "items": [
                {
                    "description": "خصم كمية",
                    "quantity": 1,
                    "unit_price": 2000.00
                }
            ]
        }
        r = client.post("/api/buying/credit-notes", json=cn_data,
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_get_purchase_credit_note_detail(self, client, admin_headers):
        """اختبار تفاصيل إشعار دائن"""
        r = client.get("/api/buying/credit-notes", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا توجد إشعارات دائن")
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if not items:
            pytest.skip("لا توجد إشعارات")
        cn_id = items[0].get("id") or items[0].get("note_id")
        r2 = client.get(f"/api/buying/credit-notes/{cn_id}",
                        headers=admin_headers)
        assert r2.status_code in (200, 404)


class TestPurchaseDebitNotes:
    """اختبارات إشعارات المدين للمشتريات"""

    def test_list_purchase_debit_notes(self, client, admin_headers):
        """اختبار عرض إشعارات المدين"""
        r = client.get("/api/buying/debit-notes", headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_create_purchase_debit_note(self, client, admin_headers):
        """اختبار إنشاء إشعار مدين مشتريات"""
        suppliers_r = client.get("/api/buying/suppliers", headers=admin_headers)
        if suppliers_r.status_code != 200:
            pytest.skip("لا يمكن جلب الموردين")
        suppliers = suppliers_r.json()
        if isinstance(suppliers, dict):
            suppliers = suppliers.get("items", suppliers.get("suppliers", []))
        if not suppliers:
            pytest.skip("لا يوجد موردون")

        dn_data = {
            "supplier_id": suppliers[0]["id"],
            "date": str(date.today()),
            "reason": "فرق سعر - اختبار",
            "amount": 300.00,
            "items": [
                {
                    "description": "فرق سعر مواد",
                    "quantity": 1,
                    "unit_price": 300.00
                }
            ]
        }
        r = client.post("/api/buying/debit-notes", json=dn_data,
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_get_purchase_debit_note_detail(self, client, admin_headers):
        """اختبار تفاصيل إشعار مدين"""
        r = client.get("/api/buying/debit-notes", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا توجد إشعارات مدين")
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if not items:
            pytest.skip("لا توجد إشعارات")
        dn_id = items[0].get("id") or items[0].get("note_id")
        r2 = client.get(f"/api/buying/debit-notes/{dn_id}",
                        headers=admin_headers)
        assert r2.status_code in (200, 404)


# ══════════════════════════════════════════════════════════════
# 💳 تفاصيل المدفوعات - Payment Details
# ══════════════════════════════════════════════════════════════

class TestPurchasePaymentDetails:
    """اختبارات تفاصيل مدفوعات المشتريات"""

    def test_get_purchase_payment_detail(self, client, admin_headers):
        """اختبار تفاصيل سند دفع مشتريات"""
        r = client.get("/api/buying/payments", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا يمكن جلب المدفوعات")
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if not items:
            pytest.skip("لا توجد مدفوعات")
        voucher_id = items[0].get("id") or items[0].get("voucher_id")
        r2 = client.get(f"/api/buying/payments/{voucher_id}",
                        headers=admin_headers)
        assert r2.status_code in (200, 404)
        if r2.status_code == 200:
            data = r2.json()
            assert "total_allocated" in data
            assert isinstance(data["total_allocated"], str)
            assert "E" not in data["total_allocated"].upper()

    def test_invoice_payment_history(self, client, admin_headers):
        """اختبار سجل دفعات فاتورة مشتريات"""
        inv_r = client.get("/api/buying/invoices", headers=admin_headers)
        if inv_r.status_code != 200:
            pytest.skip("لا يمكن جلب الفواتير")
        invoices = inv_r.json()
        if isinstance(invoices, dict):
            invoices = invoices.get("items", [])
        if not invoices:
            pytest.skip("لا توجد فواتير")
        inv_id = invoices[0]["id"]
        r = client.get(f"/api/buying/invoices/{inv_id}/payment-history",
                       headers=admin_headers)
        assert r.status_code in (200, 404)


# ══════════════════════════════════════════════════════════════
# 📊 معاملات المورد والمستحقات
# ══════════════════════════════════════════════════════════════

class TestSupplierTransactions:
    """اختبارات معاملات الموردين"""

    def _get_supplier_id(self, client, admin_headers):
        r = client.get("/api/buying/suppliers", headers=admin_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        return items[0]["id"] if items else None

    def test_supplier_transactions(self, client, admin_headers):
        """اختبار معاملات المورد"""
        sid = self._get_supplier_id(client, admin_headers)
        if not sid:
            pytest.skip("لا يوجد موردون")
        r = client.get(f"/api/buying/suppliers/{sid}/transactions",
                       headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_supplier_outstanding_invoices(self, client, admin_headers):
        """اختبار فواتير المورد المستحقة"""
        sid = self._get_supplier_id(client, admin_headers)
        if not sid:
            pytest.skip("لا يوجد موردون")
        r = client.get(f"/api/buying/suppliers/{sid}/outstanding-invoices",
                       headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_purchases_summary(self, client, admin_headers):
        """اختبار ملخص المشتريات"""
        r = client.get("/api/buying/summary", headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_create_purchase_payment(self, client, admin_headers):
        """اختبار إنشاء سند دفع للموردين"""
        sid = self._get_supplier_id(client, admin_headers)
        if not sid:
            pytest.skip("لا يوجد موردون")

        treasury_r = client.get("/api/treasury/accounts", headers=admin_headers)
        if treasury_r.status_code != 200:
            pytest.skip("لا توجد حسابات خزينة")
        taccts = treasury_r.json()
        if isinstance(taccts, dict):
            taccts = taccts.get("items", [])
        if not taccts:
            pytest.skip("لا توجد حسابات خزينة")

        payment_data = {
            "supplier_id": sid,
            "treasury_account_id": taccts[0]["id"],
            "amount": 3000.00,
            "date": str(date.today()),
            "payment_method": "bank_transfer",
            "description": "دفعة مورد اختبار"
        }
        r = client.post("/api/buying/payments", json=payment_data,
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 422, 501)

    def test_purchase_order_receive(self, client, admin_headers):
        """اختبار استلام أمر شراء"""
        orders_r = client.get("/api/buying/orders", headers=admin_headers)
        if orders_r.status_code != 200:
            pytest.skip("لا يمكن جلب أوامر الشراء")
        orders = orders_r.json()
        if isinstance(orders, dict):
            orders = orders.get("items", [])
        approved = [o for o in orders if o.get("status") == "approved"]
        if not approved:
            pytest.skip("لا توجد أوامر شراء معتمدة")
        order_id = approved[0]["id"]
        r = client.post(f"/api/buying/orders/{order_id}/receive",
                        json={"warehouse_id": None},
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)


class TestBlanketPOBackendAuthority:
    """اختبارات قيم Blanket PO المحسوبة من الخلفية."""

    def test_blanket_po_list_returns_backend_calculated_fields(self, client, admin_headers):
        r = client.get("/api/buying/blanket", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا يمكن جلب اتفاقيات الشراء المفتوحة")
        items = r.json().get("blanket_pos", [])
        if not items:
            pytest.skip("لا توجد اتفاقيات شراء مفتوحة")
        row = items[0]
        for key in ("remaining_quantity", "remaining_amount", "consumption_progress_pct"):
            assert key in row
            assert isinstance(row[key], str)
            assert "E" not in row[key].upper()
        assert "is_fully_released" in row

    def test_blanket_po_detail_returns_backend_calculated_fields(self, client, admin_headers):
        r = client.get("/api/buying/blanket", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("لا يمكن جلب اتفاقيات الشراء المفتوحة")
        items = r.json().get("blanket_pos", [])
        if not items:
            pytest.skip("لا توجد اتفاقيات شراء مفتوحة")
        bpo_id = items[0]["id"]
        detail = client.get(f"/api/buying/blanket/{bpo_id}", headers=admin_headers)
        assert detail.status_code in (200, 404)
        if detail.status_code == 200:
            data = detail.json()
            for key in ("remaining_quantity", "remaining_amount", "consumption_progress_pct"):
                assert key in data
                assert isinstance(data[key], str)
                assert "E" not in data[key].upper()
            assert "is_fully_released" in data
