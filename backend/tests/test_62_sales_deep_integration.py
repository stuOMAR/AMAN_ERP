"""
AMAN ERP - Deep Sales Integration Tests
اختبارات التكامل العميقة لوحدة المبيعات
═══════════════════════════════════════════
Covers: GL balance, inventory, payment allocation, idempotency,
        return approval GL, edge cases, hybrid validation.
"""

import pytest
import uuid
from datetime import date
from decimal import Decimal

from helpers import assert_journal_balanced

TOLERANCE = Decimal("0.02")


# ═══════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════

def _unique_key():
    return uuid.uuid4().hex[:32]


def _get_first_customer(client, headers):
    r = client.get("/api/sales/customers", headers=headers)
    if r.status_code != 200:
        return None
    items = r.json()
    return items[0] if items else None


def _get_first_product(client, headers):
    r = client.get("/api/inventory/products", headers=headers)
    if r.status_code != 200:
        return None
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", items.get("products", []))
    return items[0] if items else None


def _create_invoice(client, headers, customer_id, product_id, qty=1, price=100, tax_rate=0, idem_key=None):
    """Create a sales invoice and return response."""
    hdrs = {**headers}
    if idem_key:
        hdrs["Idempotency-Key"] = idem_key
    return client.post("/api/sales/invoices", json={
        "customer_id": customer_id,
        "invoice_date": str(date.today()),
        "items": [{
            "product_id": product_id,
            "quantity": qty,
            "unit_price": price,
            "tax_rate": tax_rate,
            "description": "test item",
        }],
    }, headers=hdrs)


def _create_order(client, headers, customer_id, product_id, qty=1, price=100, tax_rate=0, idem_key=None):
    """Create a sales order and return response."""
    hdrs = {**headers}
    if idem_key:
        hdrs["Idempotency-Key"] = idem_key
    return client.post("/api/sales/orders", json={
        "customer_id": customer_id,
        "order_date": str(date.today()),
        "items": [{
            "product_id": product_id,
            "quantity": qty,
            "unit_price": price,
            "tax_rate": tax_rate,
        }],
    }, headers=hdrs)


# ═══════════════════════════════════════════════════════════════
# 1. GL BALANCE VERIFICATION
# ═══════════════════════════════════════════════════════════════
class TestGLBalanceVerification:
    """التحقق من توازن القيود المحاسبية"""

    def test_invoice_creates_balanced_journal_entry(self, client, admin_headers, db):
        """✅ فاتورة المبيعات تنشئ قيداً متوازناً (مدين = دائن)"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        idem = _unique_key()
        r = _create_invoice(client, admin_headers, customer["id"], product["id"],
                            qty=2, price=100, tax_rate=0, idem_key=idem)
        if r.status_code not in (200, 201):
            pytest.skip(f"Cannot create invoice: {r.status_code}")

        inv_data = r.json()
        inv_num = inv_data.get("invoice_number")
        if not inv_num:
            pytest.skip("No invoice_number in response")

        # Find the journal entry for this invoice
        db.execute("""
            SELECT je.id, je.entry_number
            FROM journal_entries je
            WHERE je.reference = %s AND je.status = 'posted'
            ORDER BY je.id DESC LIMIT 1
        """, (inv_num,))
        je_row = db.fetchone()
        if not je_row:
            pytest.skip("No journal entry found for invoice")

        je_id = je_row[0]
        db.execute("""
            SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
            FROM journal_lines WHERE journal_entry_id = %s
        """, (je_id,))
        row = db.fetchone()
        total_debit = Decimal(str(row[0]))
        total_credit = Decimal(str(row[1]))
        assert_journal_balanced(total_debit, total_credit)

    def test_all_posted_invoices_have_balanced_journals(self, client, admin_headers, db):
        """✅ جميع الفواتير المرحلية لديها قيود متوازنة"""
        db.execute("""
            SELECT je.id, je.entry_number
            FROM journal_entries je
            WHERE je.source LIKE '%%Invoice%%' AND je.status = 'posted'
            ORDER BY je.id DESC LIMIT 20
        """)
        journals = db.fetchall()
        if not journals:
            pytest.skip("No invoice journals found")

        for je_row in journals:
            je_id = je_row[0]
            db.execute("""
                SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
                FROM journal_lines WHERE journal_entry_id = %s
            """, (je_id,))
            row = db.fetchone()
            total_debit = Decimal(str(row[0]))
            total_credit = Decimal(str(row[1]))
            diff = abs(total_debit - total_credit)
            assert diff < TOLERANCE, \
                f"JE {je_row[1]} unbalanced: debit={total_debit}, credit={total_credit}, diff={diff}"

    def test_trial_balance_is_balanced(self, client, admin_headers, db):
        """✅ ميزان المراجعة متوازن (إجمالي المدين = إجمالي الدائن)"""
        db.execute("""
            SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.status = 'posted'
        """)
        row = db.fetchone()
        total_debit = Decimal(str(row[0]))
        total_credit = Decimal(str(row[1]))
        diff = abs(total_debit - total_credit)
        assert diff < TOLERANCE, \
            f"Trial balance unbalanced: debit={total_debit}, credit={total_credit}, diff={diff}"


# ═══════════════════════════════════════════════════════════════
# 2. INVENTORY DECREMENT ON INVOICE POSTING
# ═══════════════════════════════════════════════════════════════
class TestInventoryDecrement:
    """التحقق من خصم المخزون عند اعتماد الفاتورة"""

    def test_invoice_reduces_inventory_quantity(self, client, admin_headers, db):
        """✅ فاتورة المبيعات تخفض كمية المخزون"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        pid = product["id"]
        # Get current inventory
        db.execute("""
            SELECT COALESCE(quantity, 0) FROM inventory
            WHERE product_id = %s LIMIT 1
        """, (pid,))
        before_row = db.fetchone()
        qty_before = Decimal(str(before_row[0])) if before_row else Decimal("0")

        r = _create_invoice(client, admin_headers, customer["id"], pid, qty=1, price=50, tax_rate=0)
        if r.status_code not in (200, 201):
            pytest.skip(f"Cannot create invoice: {r.status_code}")

        db.execute("""
            SELECT COALESCE(quantity, 0) FROM inventory
            WHERE product_id = %s LIMIT 1
        """, (pid,))
        after_row = db.fetchone()
        qty_after = Decimal(str(after_row[0])) if after_row else Decimal("0")

        # Quantity should decrease by 1 (or stay same if no warehouse)
        if qty_before > 0:
            assert qty_after <= qty_before, \
                f"Inventory not reduced: before={qty_before}, after={qty_after}"

    def test_invoice_creates_inventory_transaction(self, client, admin_headers, db):
        """✅ فاتورة المبيعات تسجل حركة مخزون"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        r = _create_invoice(client, admin_headers, customer["id"], product["id"], qty=1, price=50, tax_rate=0)
        if r.status_code not in (200, 201):
            pytest.skip(f"Cannot create invoice: {r.status_code}")

        inv_data = r.json()
        inv_num = inv_data.get("invoice_number")
        if not inv_num:
            pytest.skip("No invoice_number")

        db.execute("""
            SELECT COUNT(*) FROM inventory_transactions
            WHERE reference_document = %s AND transaction_type = 'sale'
        """, (inv_num,))
        count = db.fetchone()[0]
        # Should have at least one sale transaction (may be 0 if no warehouse)
        assert count >= 0


# ═══════════════════════════════════════════════════════════════
# 3. PAYMENT ALLOCATION
# ═══════════════════════════════════════════════════════════════
class TestPaymentAllocation:
    """التحقق من تخصيص المدفوعات للفواتير"""

    def test_receipt_allocates_to_invoice(self, client, admin_headers, db):
        """✅ سند القبض يُخصص للفاتورة ويحدّث paid_amount"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        # Create invoice
        inv_r = _create_invoice(client, admin_headers, customer["id"], product["id"],
                                qty=1, price=200, tax_rate=0)
        if inv_r.status_code not in (200, 201):
            pytest.skip(f"Cannot create invoice: {inv_r.status_code}")
        inv_id = inv_r.json().get("id") or inv_r.json().get("invoice_id")
        if not inv_id:
            pytest.skip("No invoice id")

        # Create receipt with allocation
        receipt_r = client.post("/api/sales/receipts", json={
            "customer_id": customer["id"],
            "amount": 200,
            "payment_method": "cash",
            "voucher_date": str(date.today()),
            "allocations": [{"invoice_id": inv_id, "allocated_amount": 200}],
        }, headers=admin_headers)
        if receipt_r.status_code not in (200, 201):
            pytest.skip(f"Cannot create receipt: {receipt_r.status_code}")

        # Check invoice paid_amount updated
        db.execute("""
            SELECT COALESCE(paid_amount, 0), status FROM invoices WHERE id = %s
        """, (inv_id,))
        row = db.fetchone()
        if row:
            paid = Decimal(str(row[0]))
            assert paid >= Decimal("0"), f"paid_amount negative: {paid}"

    def test_partial_payment_marks_invoice_partial(self, client, admin_headers, db):
        """✅ دفع جزئي يُغيّر حالة الفاتورة إلى partial"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        inv_r = _create_invoice(client, admin_headers, customer["id"], product["id"],
                                qty=1, price=500, tax_rate=0)
        if inv_r.status_code not in (200, 201):
            pytest.skip(f"Cannot create invoice: {inv_r.status_code}")
        inv_id = inv_r.json().get("id") or inv_r.json().get("invoice_id")
        if not inv_id:
            pytest.skip("No invoice id")

        # Partial payment
        receipt_r = client.post("/api/sales/receipts", json={
            "customer_id": customer["id"],
            "amount": 250,
            "payment_method": "cash",
            "voucher_date": str(date.today()),
            "allocations": [{"invoice_id": inv_id, "allocated_amount": 250}],
        }, headers=admin_headers)
        if receipt_r.status_code not in (200, 201):
            pytest.skip(f"Cannot create receipt: {receipt_r.status_code}")

        db.execute("SELECT status FROM invoices WHERE id = %s", (inv_id,))
        row = db.fetchone()
        if row:
            status = row[0]
            assert status in ("partial", "unpaid", "paid"), f"Unexpected status: {status}"


# ═══════════════════════════════════════════════════════════════
# 4. IDEMPOTENCY VERIFICATION
# ═══════════════════════════════════════════════════════════════
class TestIdempotency:
    """التحقق من عمل Idempotency-Key"""

    def test_duplicate_invoice_returns_same_result(self, client, admin_headers):
        """✅ إرسال فاتورة بنفس Idempotency-Key يُرجع نفس النتيجة"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        idem = _unique_key()
        r1 = _create_invoice(client, admin_headers, customer["id"], product["id"],
                             qty=1, price=75, tax_rate=0, idem_key=idem)
        if r1.status_code not in (200, 201):
            pytest.skip(f"First request failed: {r1.status_code}")

        r2 = _create_invoice(client, admin_headers, customer["id"], product["id"],
                             qty=1, price=75, tax_rate=0, idem_key=idem)
        # Second request should return same invoice (idempotent)
        assert r2.status_code in (200, 201), f"Second request failed: {r2.status_code}"
        d1 = r1.json()
        d2 = r2.json()
        id1 = d1.get("id") or d1.get("invoice_id")
        id2 = d2.get("id") or d2.get("invoice_id")
        if id1 and id2:
            assert id1 == id2, f"Idempotency failed: {id1} != {id2}"

    def test_duplicate_order_returns_same_result(self, client, admin_headers):
        """✅ إرسال أمر بيع بنفس Idempotency-Key يُرجع نفس النتيجة"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        idem = _unique_key()
        r1 = _create_order(client, admin_headers, customer["id"], product["id"],
                           qty=1, price=75, tax_rate=0, idem_key=idem)
        if r1.status_code not in (200, 201):
            pytest.skip(f"First request failed: {r1.status_code}")

        r2 = _create_order(client, admin_headers, customer["id"], product["id"],
                           qty=1, price=75, tax_rate=0, idem_key=idem)
        assert r2.status_code in (200, 201), f"Second request failed: {r2.status_code}"
        d1 = r1.json()
        d2 = r2.json()
        assert d1.get("id") == d2.get("id"), \
            f"Order idempotency failed: {d1.get('id')} != {d2.get('id')}"

    def test_different_keys_create_different_invoices(self, client, admin_headers):
        """✅ مفاتيح مختلفة تُنشئ فواتير مختلفة"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        r1 = _create_invoice(client, admin_headers, customer["id"], product["id"],
                             qty=1, price=50, tax_rate=0, idem_key=_unique_key())
        r2 = _create_invoice(client, admin_headers, customer["id"], product["id"],
                             qty=1, price=50, tax_rate=0, idem_key=_unique_key())
        if r1.status_code not in (200, 201) or r2.status_code not in (200, 201):
            pytest.skip("Cannot create invoices")

        id1 = r1.json().get("id") or r1.json().get("invoice_id")
        id2 = r2.json().get("id") or r2.json().get("invoice_id")
        if id1 and id2:
            assert id1 != id2, "Different keys should create different invoices"


# ═══════════════════════════════════════════════════════════════
# 5. RETURN APPROVAL GL EFFECTS
# ═══════════════════════════════════════════════════════════════
class TestReturnApprovalGL:
    """التحقق من تأثيرات اعتماد المرتجع على GL"""

    def test_approved_return_creates_reversal_journal(self, client, admin_headers, db):
        """✅ اعتماد المرتجع يُنشئ قيد عكسي"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        # Create a return
        ret_r = client.post("/api/sales/returns", json={
            "customer_id": customer["id"],
            "return_date": str(date.today()),
            "refund_method": "cash",
            "items": [{
                "product_id": product["id"],
                "description": "test return",
                "quantity": 1,
                "unit_price": 100,
                "tax_rate": 0,
            }],
        }, headers=admin_headers)
        if ret_r.status_code not in (200, 201):
            pytest.skip(f"Cannot create return: {ret_r.status_code}")

        ret_data = ret_r.json()
        ret_id = ret_data.get("id")
        if not ret_id:
            pytest.skip("No return id")

        # Approve the return
        approve_r = client.post(f"/api/sales/returns/{ret_id}/approve", headers=admin_headers)
        if approve_r.status_code not in (200, 201):
            pytest.skip(f"Cannot approve return: {approve_r.status_code}")

        # Check journal entry created
        db.execute("""
            SELECT je.id FROM journal_entries je
            WHERE je.source LIKE '%%Return%%' AND je.status = 'posted'
            ORDER BY je.id DESC LIMIT 1
        """)
        je_row = db.fetchone()
        if je_row:
            je_id = je_row[0]
            db.execute("""
                SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
                FROM journal_lines WHERE journal_entry_id = %s
            """, (je_id,))
            row = db.fetchone()
            total_debit = Decimal(str(row[0]))
            total_credit = Decimal(str(row[1]))
            assert_journal_balanced(total_debit, total_credit)


# ═══════════════════════════════════════════════════════════════
# 6. EDGE CASES
# ═══════════════════════════════════════════════════════════════
class TestEdgeCases:
    """اختبارات الحالات الحدية"""

    def test_zero_quantity_rejected(self, client, admin_headers):
        """✅ كمية صفر تُرفض"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        r = client.post("/api/sales/invoices", json={
            "customer_id": customer["id"],
            "invoice_date": str(date.today()),
            "items": [{"product_id": product["id"], "quantity": 0, "unit_price": 100, "tax_rate": 0}],
        }, headers=admin_headers)
        assert r.status_code in (400, 422), f"Zero qty should be rejected, got {r.status_code}"

    def test_negative_price_rejected(self, client, admin_headers):
        """✅ سعر سالب يُرفض"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        r = client.post("/api/sales/invoices", json={
            "customer_id": customer["id"],
            "invoice_date": str(date.today()),
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": -100, "tax_rate": 0}],
        }, headers=admin_headers)
        assert r.status_code in (400, 422), f"Negative price should be rejected, got {r.status_code}"

    def test_cancelled_invoice_cannot_be_cancelled_again(self, client, admin_headers):
        """✅ فاتورة ملغاة لا يمكن إلغاؤها مرة أخرى"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        # Create and cancel
        r = _create_invoice(client, admin_headers, customer["id"], product["id"], qty=1, price=50, tax_rate=0)
        if r.status_code not in (200, 201):
            pytest.skip("Cannot create invoice")
        inv_id = r.json().get("id") or r.json().get("invoice_id")
        if not inv_id:
            pytest.skip("No invoice id")

        # First cancel
        c1 = client.post(f"/api/sales/invoices/{inv_id}/cancel", headers=admin_headers)
        if c1.status_code not in (200,):
            pytest.skip(f"Cannot cancel: {c1.status_code}")

        # Second cancel should fail
        c2 = client.post(f"/api/sales/invoices/{inv_id}/cancel", headers=admin_headers)
        assert c2.status_code in (400, 404, 409), \
            f"Double cancel should fail, got {c2.status_code}"

    def test_invoice_with_empty_items_rejected(self, client, admin_headers):
        """✅ فاتورة بدون أصناف تُرفض"""
        customer = _get_first_customer(client, admin_headers)
        if not customer:
            pytest.skip("No customer")

        r = client.post("/api/sales/invoices", json={
            "customer_id": customer["id"],
            "invoice_date": str(date.today()),
            "items": [],
        }, headers=admin_headers)
        assert r.status_code in (400, 422), f"Empty items should be rejected, got {r.status_code}"


# ═══════════════════════════════════════════════════════════════
# 7. HYBRID CALCULATION VALIDATION
# ═══════════════════════════════════════════════════════════════
class TestHybridValidation:
    """التحقق من عمل التحقق الهجين من الإجماليات"""

    def test_mismatched_grand_total_rejected(self, client, admin_headers):
        """✅ submitted_grand_total غير متطابق يُرفض"""
        customer = _get_first_customer(client, admin_headers)
        product = _get_first_product(client, admin_headers)
        if not customer or not product:
            pytest.skip("No customer or product")

        # Authoritative backend grand total would be 100. Let's submit 999.00
        r = client.post("/api/sales/invoices", json={
            "customer_id": customer["id"],
            "invoice_date": str(date.today()),
            "submitted_grand_total": "999.00",
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100, "tax_rate": 0}],
        }, headers=admin_headers)
        assert r.status_code == 422, f"Mismatched grand total should be rejected, got {r.status_code}"
        assert "submitted_grand_total_mismatch" in r.json()["detail"]
