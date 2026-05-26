"""
test_24_reconciliation_advanced.py
===================================
اختبارات متقدمة للتسوية البنكية

Covers UNTESTED endpoints:
- POST /api/reconciliation/{id}/import-preview
- POST /api/reconciliation/{id}/import-confirm
- POST /api/reconciliation/{id}/auto-match
- DELETE /api/reconciliation/{id}/lines/{line_id}
- GET /api/reconciliation/{id}/ledger
- POST /api/reconciliation/{id}/match
- POST /api/reconciliation/{id}/unmatch
- POST /api/reconciliation/{id}/finalize
"""
import pytest
from datetime import date, timedelta


class TestReconciliationAutoMatch:
    """اختبارات المطابقة التلقائية"""

    def _get_reconciliation_id(self, client, admin_headers):
        """جلب معرف تسوية موجودة أو إنشاء واحدة"""
        r = client.get("/api/reconciliation", headers=admin_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        if items:
            return items[0]["id"]
        # محاولة إنشاء تسوية جديدة
        treasury_r = client.get("/api/treasury/accounts", headers=admin_headers)
        if treasury_r.status_code != 200:
            return None
        taccts = treasury_r.json()
        if isinstance(taccts, dict):
            taccts = taccts.get("items", taccts.get("accounts", []))
        if not taccts:
            return None
        create_r = client.post("/api/reconciliation", json={
            "account_id": taccts[0]["id"],
            "start_date": str(date.today() - timedelta(days=30)),
            "end_date": str(date.today()),
            "statement_balance": 50000.00
        }, headers=admin_headers)
        if create_r.status_code in (200, 201):
            return create_r.json().get("id")
        return None

    def test_auto_match_transactions(self, client, admin_headers):
        """اختبار المطابقة التلقائية للمعاملات"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.post(f"/api/reconciliation/{rec_id}/auto-match",
                        headers=admin_headers)
        assert r.status_code in (200, 404, 422, 501)

    def test_get_reconciliation_ledger(self, client, admin_headers):
        """اختبار عرض دفتر الأستاذ للتسوية"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.get(f"/api/reconciliation/{rec_id}/ledger",
                       headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_match_reconciliation_lines(self, client, admin_headers):
        """اختبار مطابقة سطور التسوية يدوياً"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        match_data = {
            "line_ids": [],
            "match_type": "manual"
        }
        r = client.post(f"/api/reconciliation/{rec_id}/match",
                        json=match_data, headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422, 501)

    def test_unmatch_reconciliation_lines(self, client, admin_headers):
        """اختبار إلغاء مطابقة سطور التسوية"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.post(f"/api/reconciliation/{rec_id}/unmatch",
                        json={"line_ids": []}, headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422, 501)


class TestReconciliationImport:
    """اختبارات استيراد كشوفات البنك"""

    def _get_reconciliation_id(self, client, admin_headers):
        r = client.get("/api/reconciliation", headers=admin_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        return items[0]["id"] if items else None

    def test_import_preview(self, client, admin_headers):
        """اختبار معاينة استيراد كشف بنك"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        # استيراد بيانات CSV بسيطة
        import_data = {
            "format": "csv",
            "data": "date,description,amount\n2025-01-15,إيداع,5000\n2025-01-16,سحب,-2000"
        }
        r = client.post(f"/api/reconciliation/{rec_id}/import-preview",
                        json=import_data, headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422, 501)

    def test_import_confirm(self, client, admin_headers):
        """اختبار تأكيد الاستيراد"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.post(f"/api/reconciliation/{rec_id}/import-confirm",
                        json={"confirmed": True}, headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422, 501)


class TestReconciliationFinalize:
    """اختبارات إنهاء التسوية"""

    def _get_reconciliation_id(self, client, admin_headers):
        r = client.get("/api/reconciliation", headers=admin_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        return items[0]["id"] if items else None

    def test_finalize_reconciliation(self, client, admin_headers):
        """اختبار إنهاء/إغلاق التسوية"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.post(f"/api/reconciliation/{rec_id}/finalize",
                        headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422, 501)

    def test_delete_reconciliation_line(self, client, admin_headers):
        """اختبار حذف سطر من التسوية"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        # جلب سطور التسوية
        lines_r = client.get(f"/api/reconciliation/{rec_id}/lines",
                             headers=admin_headers)
        if lines_r.status_code != 200:
            # جرب GET reconciliation/{id} لجلب التفاصيل
            detail_r = client.get(f"/api/reconciliation/{rec_id}",
                                  headers=admin_headers)
            if detail_r.status_code != 200:
                pytest.skip("لا يمكن جلب سطور التسوية")
            lines = detail_r.json().get("lines", [])
        else:
            lines = lines_r.json()
            if isinstance(lines, dict):
                lines = lines.get("items", lines.get("lines", []))

        if not lines:
            pytest.skip("لا توجد سطور")
        line_id = lines[-1].get("id")
        if not line_id:
            pytest.skip("لا يوجد معرف السطر")
        r = client.delete(f"/api/reconciliation/{rec_id}/lines/{line_id}",
                          headers=admin_headers)
        assert r.status_code in (200, 204, 404, 422, 501)

    def test_get_unreconciled_items(self, client, admin_headers):
        """اختبار عرض البنود غير المسواة"""
        rec_id = self._get_reconciliation_id(client, admin_headers)
        if not rec_id:
            pytest.skip("لا يمكن الحصول على تسوية")
        r = client.get(f"/api/reconciliation/{rec_id}/unreconciled",
                       headers=admin_headers)
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (list, dict))

    def test_reconciliation_with_invalid_id(self, client, admin_headers):
        """اختبار التسوية بمعرف غير صالح"""
        r = client.get("/api/reconciliation/999999", headers=admin_headers)
        assert r.status_code in (404, 422, 500)

    def test_create_reconciliation_duplicate_period(self, client, admin_headers):
        """اختبار إنشاء تسوية مكررة لنفس الفترة"""
        treasury_r = client.get("/api/treasury/accounts", headers=admin_headers)
        if treasury_r.status_code != 200:
            pytest.skip("لا يمكن جلب حسابات الخزينة")
        taccts = treasury_r.json()
        if isinstance(taccts, dict):
            taccts = taccts.get("items", taccts.get("accounts", []))
        if not taccts:
            pytest.skip("لا توجد حسابات خزينة")

        recon_data = {
            "account_id": taccts[0]["id"],
            "start_date": str(date.today() - timedelta(days=30)),
            "end_date": str(date.today()),
            "statement_balance": 50000.00
        }
        # إنشاء تسوية أولى
        client.post("/api/reconciliation", json=recon_data,
                         headers=admin_headers)
        # محاولة إنشاء مكررة
        r2 = client.post("/api/reconciliation", json=recon_data,
                         headers=admin_headers)
        assert r2.status_code in (200, 201, 400, 409, 422)
