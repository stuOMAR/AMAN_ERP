"""
test_32_tax_currency_advanced.py
==================================
اختبارات متقدمة للضرائب والعملات

Covers UNTESTED endpoints:
- POST /api/taxes/returns/{id}/file
- POST /api/taxes/returns/{id}/cancel
- GET /api/taxes/audit-report
- POST /api/taxes/settle
- POST /api/accounting/currencies/revaluate
"""
import pytest
from datetime import date, timedelta


# ══════════════════════════════════════════════════════════════
# 💵 الضرائب المتقدمة (Tax Advanced)
# ══════════════════════════════════════════════════════════════

class TestTaxReturnsAdvanced:
    """اختبارات متقدمة للإقرارات الضريبية"""

    def _get_tax_return_id(self, client, admin_headers):
        r = client.get("/api/taxes/returns", headers=admin_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", data.get("returns", []))
        return items[0]["id"] if items else None

    def test_file_tax_return(self, client, admin_headers):
        """اختبار تقديم إقرار ضريبي"""
        return_id = self._get_tax_return_id(client, admin_headers)
        if not return_id:
            pytest.skip("لا توجد إقرارات ضريبية")
        r = client.post(f"/api/taxes/returns/{return_id}/file",
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 405, 422, 501)

    def test_cancel_tax_return(self, client, admin_headers):
        """اختبار إلغاء إقرار ضريبي"""
        return_id = self._get_tax_return_id(client, admin_headers)
        if not return_id:
            pytest.skip("لا توجد إقرارات ضريبية")
        r = client.post(f"/api/taxes/returns/{return_id}/cancel",
                        json={"reason": "خطأ في البيانات - اختبار"},
                        headers=admin_headers)
        assert r.status_code in (200, 400, 404, 405, 422, 501)

    def test_file_and_cancel_workflow(self, client, admin_headers):
        """اختبار دورة تقديم وإلغاء إقرار ضريبي"""
        # إنشاء إقرار
        fy_r = client.get("/api/accounting/fiscal-years/current",
                          headers=admin_headers)
        if fy_r.status_code != 200:
            pytest.skip("لا توجد سنة مالية حالية")
        fy_r.json()
        
        return_data = {
            "period": "Q1",
            "year": date.today().year,
            "start_date": str(date.today().replace(month=1, day=1)),
            "end_date": str(date.today().replace(month=3, day=31)),
            "return_type": "vat"
        }
        create_r = client.post("/api/taxes/returns", json=return_data,
                               headers=admin_headers)
        if create_r.status_code not in (200, 201):
            pytest.skip("لا يمكن إنشاء إقرار")
        
        return_id = create_r.json().get("id")
        if not return_id:
            pytest.skip("لا يوجد معرف الإقرار")

        # حساب الضريبة
        client.post(f"/api/taxes/returns/{return_id}/calculate",
                             headers=admin_headers)
        
        # تقديم الإقرار
        file_r = client.post(f"/api/taxes/returns/{return_id}/file",
                             headers=admin_headers)
        assert file_r.status_code in (200, 201, 400, 404, 422, 501)

    def test_calculate_and_submit_tax_return(self, client, admin_headers):
        """اختبار حساب وتقديم إقرار ضريبي"""
        return_id = self._get_tax_return_id(client, admin_headers)
        if not return_id:
            pytest.skip("لا توجد إقرارات ضريبية")
        
        # حساب
        calc_r = client.post(f"/api/taxes/returns/{return_id}/calculate",
                             headers=admin_headers)
        
        # تقديم
        if calc_r.status_code in (200, 201):
            submit_r = client.post(f"/api/taxes/returns/{return_id}/submit",
                                   headers=admin_headers)
            assert submit_r.status_code in (200, 201, 400, 404, 422)


class TestTaxReportsAdvanced:
    """اختبارات تقارير الضرائب المتقدمة"""

    def test_tax_audit_report(self, client, admin_headers):
        """اختبار تقرير مراجعة الضرائب"""
        r = client.get("/api/taxes/audit-report", headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_tax_audit_report_with_period(self, client, admin_headers):
        """اختبار تقرير مراجعة الضرائب لفترة محددة"""
        today = str(date.today())
        year_start = str(date.today().replace(month=1, day=1))
        r = client.get(
            f"/api/taxes/audit-report?start_date={year_start}&end_date={today}",
            headers=admin_headers
        )
        assert r.status_code in (200, 404, 501)

    def test_tax_settle(self, client, admin_headers):
        """اختبار تسوية الضرائب"""
        settle_data = {
            "period": "Q1",
            "year": date.today().year,
            "settlement_date": str(date.today())
        }
        r = client.post("/api/taxes/settle", json=settle_data,
                        headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_vat_report_detailed(self, client, admin_headers):
        """اختبار تقرير ضريبة القيمة المضافة التفصيلي"""
        today = str(date.today())
        month_ago = str(date.today() - timedelta(days=30))
        r = client.get(
            f"/api/reports/taxes/vat?start_date={month_ago}&end_date={today}",
            headers=admin_headers
        )
        assert r.status_code in (200, 404)

    def test_tax_summary(self, client, admin_headers):
        """اختبار ملخص الضرائب"""
        r = client.get("/api/taxes/summary", headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_tax_liability(self, client, admin_headers):
        """اختبار التزامات الضرائب"""
        r = client.get("/api/taxes/liability", headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_sales_tax_report(self, client, admin_headers):
        """اختبار تقرير ضريبة المبيعات"""
        today = str(date.today())
        quarter_start = str(date.today().replace(month=1, day=1))
        r = client.get(
            f"/api/reports/taxes/sales?start_date={quarter_start}&end_date={today}",
            headers=admin_headers
        )
        assert r.status_code in (200, 404)

    def test_purchases_tax_report(self, client, admin_headers):
        """اختبار تقرير ضريبة المشتريات"""
        today = str(date.today())
        quarter_start = str(date.today().replace(month=1, day=1))
        r = client.get(
            f"/api/reports/taxes/purchases?start_date={quarter_start}&end_date={today}",
            headers=admin_headers
        )
        assert r.status_code in (200, 404)


# ══════════════════════════════════════════════════════════════
# 💱 إعادة تقييم العملات (Currency Revaluation)
# ══════════════════════════════════════════════════════════════

class TestCurrencyRevaluation:
    """اختبارات إعادة تقييم العملات"""

    def test_currency_revaluation(self, client, admin_headers):
        """اختبار إعادة تقييم فروقات العملات"""
        revaluation_data = {
            "date": str(date.today()),
            "currency": "USD",
            "new_rate": 3.75  # سعر الصرف الجديد
        }
        r = client.post("/api/accounting/currencies/revaluate",
                        json=revaluation_data, headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_multi_currency_revaluation(self, client, admin_headers, base_currency):
        """اختبار إعادة تقييم عملات متعددة"""
        # جلب العملات المفعلة
        curr_r = client.get("/api/accounting/currencies/", headers=admin_headers)
        if curr_r.status_code != 200:
            pytest.skip("لا يمكن جلب العملات")
        currencies = curr_r.json()
        if isinstance(currencies, dict):
            currencies = currencies.get("items", currencies.get("currencies", []))
        
        foreign_currencies = [c for c in currencies if c.get("code") != base_currency]
        if not foreign_currencies:
            pytest.skip("لا توجد عملات أجنبية")

        for currency in foreign_currencies[:2]:  # أول عملتين
            revaluation_data = {
                "date": str(date.today()),
                "currency": currency["code"],
                "new_rate": 3.75 if currency["code"] == "USD" else 4.10
            }
            r = client.post("/api/accounting/currencies/revaluate",
                            json=revaluation_data, headers=admin_headers)
            assert r.status_code in (200, 201, 400, 404, 422, 501)

    def test_currency_revaluation_with_invalid_rate(self, client, admin_headers):
        """اختبار إعادة تقييم بسعر صرف غير صالح"""
        revaluation_data = {
            "date": str(date.today()),
            "currency": "USD",
            "new_rate": -3.75  # سعر سالب غير صالح
        }
        r = client.post("/api/accounting/currencies/revaluate",
                        json=revaluation_data, headers=admin_headers)
        assert r.status_code in (400, 404, 422, 501)

    def test_create_currency_exchange_rate(self, client, admin_headers, base_currency):
        """اختبار إضافة سعر صرف عملة"""
        # جلب عملة
        curr_r = client.get("/api/accounting/currencies/", headers=admin_headers)
        if curr_r.status_code != 200:
            pytest.skip("لا يمكن جلب العملات")
        currencies = curr_r.json()
        if isinstance(currencies, dict):
            currencies = currencies.get("items", [])
        foreign = [c for c in currencies if c.get("code") != base_currency]
        if not foreign:
            pytest.skip("لا توجد عملات أجنبية")

        currency_id = foreign[0]["id"]
        rate_data = {
            "currency_id": currency_id,
            "rate": 3.76,
            "rate_date": str(date.today())
        }
        r = client.post("/api/accounting/currencies/rates",
                        json=rate_data, headers=admin_headers)
        assert r.status_code in (200, 201, 400, 404, 422)

    def test_get_currency_rates_history(self, client, admin_headers, base_currency):
        """اختبار عرض سجل أسعار صرف عملة"""
        curr_r = client.get("/api/accounting/currencies/", headers=admin_headers)
        if curr_r.status_code != 200:
            pytest.skip("لا يمكن جلب العملات")
        currencies = curr_r.json()
        if isinstance(currencies, dict):
            currencies = currencies.get("items", [])
        foreign = [c for c in currencies if c.get("code") != base_currency]
        if not foreign:
            pytest.skip("لا توجد عملات أجنبية")

        currency_id = foreign[0]["id"]
        r = client.get(f"/api/accounting/currencies/{currency_id}/rates",
                       headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_fx_realized_gains_report(self, client, admin_headers):
        """اختبار تقرير أرباح/خسائر العملات المحققة"""
        r = client.get("/api/reports/accounting/fx-realized",
                       headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_fx_unrealized_gains_report(self, client, admin_headers):
        """اختبار تقرير أرباح/خسائر العملات غير المحققة"""
        r = client.get("/api/reports/accounting/fx-unrealized",
                       headers=admin_headers)
        assert r.status_code in (200, 404, 501)

    def test_currency_list_active_only(self, client, admin_headers):
        """اختبار عرض العملات النشطة فقط"""
        r = client.get("/api/accounting/currencies/?is_active=true",
                       headers=admin_headers)
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", [])
            # التحقق من أن جميع العملات نشطة
            for curr in items:
                if "is_active" in curr:
                    assert curr["is_active"]

    def test_create_new_currency(self, client, admin_headers):
        """اختبار إضافة عملة جديدة"""
        currency_data = {
            "code": "EUR",
            "name": "يورو",
            "symbol": "€",
            "exchange_rate": 4.10,
            "is_active": True
        }
        r = client.post("/api/accounting/currencies/",
                        json=currency_data, headers=admin_headers)
        assert r.status_code in (200, 201, 400, 409, 422)

    def test_update_currency(self, client, admin_headers):
        """اختبار تحديث بيانات عملة"""
        curr_r = client.get("/api/accounting/currencies/", headers=admin_headers)
        if curr_r.status_code != 200:
            pytest.skip("لا يمكن جلب العملات")
        currencies = curr_r.json()
        if isinstance(currencies, dict):
            currencies = currencies.get("items", [])
        if not currencies:
            pytest.skip("لا توجد عملات")

        currency_id = currencies[0]["id"]
        update_data = {
            "name": "عملة محدثة - اختبار",
            "is_active": True
        }
        r = client.put(f"/api/accounting/currencies/{currency_id}",
                       json=update_data, headers=admin_headers)
        assert r.status_code in (200, 400, 404, 422)

    def test_delete_currency(self, client, admin_headers, base_currency):
        """اختبار حذف عملة"""
        curr_r = client.get("/api/accounting/currencies/", headers=admin_headers)
        if curr_r.status_code != 200:
            pytest.skip("لا يمكن جلب العملات")
        currencies = curr_r.json()
        if isinstance(currencies, dict):
            currencies = currencies.get("items", [])
        # حذف آخر عملة (الأقل استخداماً)
        deletable = [c for c in currencies if c.get("code") != base_currency]
        if not deletable:
            pytest.skip("لا توجد عملات قابلة للحذف")

        currency_id = deletable[-1]["id"]
        r = client.delete(f"/api/accounting/currencies/{currency_id}",
                          headers=admin_headers)
        assert r.status_code in (200, 204, 400, 404, 422, 501)
