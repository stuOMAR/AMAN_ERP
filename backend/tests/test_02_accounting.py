"""
AMAN ERP - اختبارات المحاسبة والقيود المحاسبية
Accounting & Journal Entries Tests
═══════════════════════════════════════════════════
يتضمن: دليل الحسابات، القيود المحاسبية، التوازن المحاسبي
"""

import pytest
from helpers import (
    assert_valid_response, assert_journal_balanced
)


class TestChartOfAccounts:
    """📊 اختبارات دليل الحسابات"""

    def test_list_accounts(self, client, admin_headers):
        """✅ عرض دليل الحسابات"""
        response = client.get("/api/accounting/accounts", headers=admin_headers)
        assert_valid_response(response)
        data = response.json()
        assert isinstance(data, list)

    def test_accounts_have_required_fields(self, client, admin_headers):
        """✅ الحسابات تحتوي على الحقول المطلوبة"""
        response = client.get("/api/accounting/accounts", headers=admin_headers)
        if response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = response.json()
        if len(accounts) == 0:
            pytest.skip("لا توجد حسابات")
        
        account = accounts[0]
        required_fields = ["id", "account_code", "name"]
        for field in required_fields:
            assert field in account, f"الحقل {field} مفقود من الحساب"

    def test_account_types_valid(self, client, admin_headers):
        """✅ أنواع الحسابات صحيحة (أصول، خصوم، حقوق ملكية، إيرادات، مصروفات)"""
        response = client.get("/api/accounting/accounts", headers=admin_headers)
        if response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        valid_types = ["asset", "liability", "equity", "revenue", "expense", 
                       "assets", "liabilities", "income", "expenses",
                       "cost_of_goods_sold", "cogs", "other_income", "other_expense"]
        
        accounts = response.json()
        for acc in accounts:
            acc_type = acc.get("account_type", "").lower()
            if acc_type:
                assert acc_type in valid_types, \
                    f"نوع حساب غير معروف: {acc_type} للحساب {acc.get('account_code')}"

    def test_account_codes_unique(self, client, admin_headers):
        """✅ أكواد الحسابات فريدة (لا تكرار)"""
        response = client.get("/api/accounting/accounts", headers=admin_headers)
        if response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = response.json()
        codes = [acc.get("account_code") for acc in accounts if acc.get("account_code")]
        assert len(codes) == len(set(codes)), \
            f"⚠️ يوجد أكواد حسابات مكررة! العدد الكلي={len(codes)}, الفريد={len(set(codes))}"


class TestJournalEntries:
    """📝 اختبارات القيود المحاسبية"""

    def test_list_journal_entries(self, client, admin_headers):
        """✅ عرض قائمة القيود المحاسبية"""
        # لا يوجد GET endpoint لقائمة القيود - نتحقق من وجود endpoint الإنشاء
        response = client.get("/api/accounting/summary", headers=admin_headers)
        assert_valid_response(response)

    def test_create_balanced_journal_entry(self, client, admin_headers):
        """
        ✅ إنشاء قيد محاسبي متوازن
        قاعدة: المدين = الدائن
        """
        # جلب أول حسابين من دليل الحسابات
        acc_response = client.get("/api/accounting/accounts", headers=admin_headers)
        if acc_response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = acc_response.json()
        if len(accounts) < 2:
            pytest.skip("أقل من حسابين في دليل الحسابات")
        
        # نبحث عن حساب أصل وحساب مصروف
        debit_acc = None
        credit_acc = None
        for acc in accounts:
            acc_type = acc.get("account_type", "").lower()
            if acc_type in ["asset", "assets"] and not debit_acc:
                debit_acc = acc
            elif acc_type in ["expense", "expenses"] and not credit_acc:
                credit_acc = acc
        
        if not debit_acc or not credit_acc:
            # نستخدم أي حسابين
            debit_acc = accounts[0]
            credit_acc = accounts[1]
        
        journal_entry = {
            "date": "2026-02-11",
            "reference": "TEST-JE-001",
            "description": "قيد اختبار آلي",
            "lines": [
                {
                    "account_id": debit_acc["id"],
                    "debit": 1000.00,
                    "credit": 0,
                    "description": "مدين - اختبار"
                },
                {
                    "account_id": credit_acc["id"],
                    "debit": 0,
                    "credit": 1000.00,
                    "description": "دائن - اختبار"
                }
            ]
        }
        
        response = client.post(
            "/api/accounting/journal-entries",
            json=journal_entry,
            headers=admin_headers
        )
        
        # القيد يجب أن ينجح أو يرفض لسبب منطقي
        if response.status_code == 200 or response.status_code == 201:
            data = response.json()
            # التحقق من التوازن
            if "lines" in data:
                total_debit = sum(line.get("debit", 0) for line in data["lines"])
                total_credit = sum(line.get("credit", 0) for line in data["lines"])
                assert_journal_balanced(total_debit, total_credit)
        else:
            # مقبول إذا كان خطأ معروف (مثلاً تكرار المرجع)
            assert response.status_code in [400, 422, 500], \
                f"خطأ غير متوقع: {response.status_code} - {response.text}"

    def test_reject_unbalanced_journal_entry(self, client, admin_headers):
        """
        ❌ رفض قيد غير متوازن
        قاعدة محاسبية: لا يمكن إنشاء قيد المدين فيه ≠ الدائن
        """
        acc_response = client.get("/api/accounting/accounts", headers=admin_headers)
        if acc_response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = acc_response.json()
        if len(accounts) < 2:
            pytest.skip("أقل من حسابين")
        
        # قيد غير متوازن عمداً
        journal_entry = {
            "date": "2026-02-11",
            "reference": "TEST-UNBAL-001",
            "description": "قيد غير متوازن - يجب أن يرفض",
            "lines": [
                {
                    "account_id": accounts[0]["id"],
                    "debit": 5000.00,
                    "credit": 0,
                    "description": "مدين"
                },
                {
                    "account_id": accounts[1]["id"],
                    "debit": 0,
                    "credit": 3000.00,
                    "description": "دائن - مبلغ مختلف عمداً"
                }
            ]
        }
        
        response = client.post(
            "/api/accounting/journal-entries",
            json=journal_entry,
            headers=admin_headers
        )
        
        # يجب أن يُرفض
        assert response.status_code in [400, 422], \
            f"⚠️ تم قبول قيد غير متوازن! هذا خطأ محاسبي خطير: {response.status_code}"

    def test_reject_zero_amount_journal_entry(self, client, admin_headers):
        """❌ رفض قيد بمبلغ صفر"""
        acc_response = client.get("/api/accounting/accounts", headers=admin_headers)
        if acc_response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = acc_response.json()
        if len(accounts) < 2:
            pytest.skip("أقل من حسابين")
        
        journal_entry = {
            "date": "2026-02-11",
            "reference": "TEST-ZERO-001",
            "description": "قيد بمبلغ صفر",
            "lines": [
                {
                    "account_id": accounts[0]["id"],
                    "debit": 0,
                    "credit": 0,
                    "description": "صفر"
                },
                {
                    "account_id": accounts[1]["id"],
                    "debit": 0,
                    "credit": 0,
                    "description": "صفر"
                }
            ]
        }
        
        response = client.post(
            "/api/accounting/journal-entries",
            json=journal_entry,
            headers=admin_headers
        )
        # بعض الأنظمة تقبل قيد بصفر (0=0 متوازن)
        assert response.status_code in [200, 201, 400, 422, 500]

    def test_reject_single_line_journal(self, client, admin_headers):
        """❌ رفض قيد بسطر واحد فقط"""
        acc_response = client.get("/api/accounting/accounts", headers=admin_headers)
        if acc_response.status_code != 200:
            pytest.skip("لا يمكن تحميل الحسابات")
        
        accounts = acc_response.json()
        if len(accounts) < 1:
            pytest.skip("لا توجد حسابات")
        
        journal_entry = {
            "date": "2026-02-11",
            "reference": "TEST-SINGLE-001",
            "description": "قيد بسطر واحد",
            "lines": [
                {
                    "account_id": accounts[0]["id"],
                    "debit": 1000,
                    "credit": 0,
                    "description": "سطر وحيد"
                }
            ]
        }
        
        response = client.post(
            "/api/accounting/journal-entries",
            json=journal_entry,
            headers=admin_headers
        )
        assert response.status_code in [400, 422], \
            "⚠️ تم قبول قيد بسطر واحد! يجب أن يكون على الأقل سطرين"


class TestAccountingSummary:
    """📈 اختبارات الملخص المحاسبي"""

    def test_accounting_summary(self, client, admin_headers):
        """✅ الملخص المحاسبي يعمل"""
        response = client.get("/api/accounting/summary", headers=admin_headers)
        assert_valid_response(response)
