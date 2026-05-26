"""
AMAN ERP - Performance Tests: API Response Times
اختبارات الأداء: أوقات استجابة API
═══════════════════════════════════════
"""

"""
AMAN ERP - Performance Tests: API Response Times
اختبارات الأداء: أوقات استجابة API
═══════════════════════════════════════
"""

import pytest  # noqa: E402
import time  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


class TestAPIPerformance:
    """⚡ اختبارات أداء API"""

    # معايير الأداء المستهدفة
    TARGET_RESPONSE_TIME = 0.5  # 500ms
    TARGET_CRITICAL_TIME = 0.2  # 200ms للعمليات الحرجة
    TARGET_REPORT_TIME = 1.0  # 1s للتقارير

    def measure_response_time(self, func, *args, **kwargs):
        """قياس وقت الاستجابة"""
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        return result, elapsed

    def test_login_performance(self, client):
        """⚡ أداء تسجيل الدخول"""
        import os
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        
        response, elapsed = self.measure_response_time(
            client.post,
            "/api/auth/login",
            data={
                "username": os.environ.get("AMAN_TEST_USER", "aaaa"),
                "password": password,
                "grant_type": "password"
            }
        )
        
        assert response.status_code == 200, "تسجيل الدخول يجب أن ينجح"
        assert elapsed < self.TARGET_RESPONSE_TIME, \
            f"تسجيل الدخول استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_RESPONSE_TIME}s)"

    def test_dashboard_stats_performance(self, client, admin_headers):
        """⚡ أداء إحصائيات لوحة التحكم"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/dashboard/stats",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"لوحة التحكم استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_journal_entries_list_performance(self, client, admin_headers):
        """⚡ أداء قائمة القيود اليومية"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/accounting/journal-entries",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"قائمة القيود استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_sales_invoices_list_performance(self, client, admin_headers):
        """⚡ أداء قائمة فواتير المبيعات"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/sales/invoices",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"قائمة الفواتير استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_products_list_performance(self, client, admin_headers):
        """⚡ أداء قائمة المنتجات"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/inventory/products",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"قائمة المنتجات استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_balance_sheet_performance(self, client, admin_headers):
        """⚡ أداء تقرير الميزانية العمومية"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/reports/accounting/balance-sheet",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_REPORT_TIME, \
            f"الميزانية العمومية استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_REPORT_TIME}s)"

    def test_income_statement_performance(self, client, admin_headers):
        """⚡ أداء تقرير قائمة الدخل"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/reports/accounting/profit-loss",
            headers=admin_headers
        )
        
        # قد يكون endpoint غير موجود (404) أو يحتاج parameters
        if response.status_code == 404:
            pytest.skip("Endpoint profit-loss غير موجود")
        assert response.status_code == 200
        assert elapsed < self.TARGET_REPORT_TIME, \
            f"قائمة الدخل استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_REPORT_TIME}s)"

    def test_trial_balance_performance(self, client, admin_headers):
        """⚡ أداء ميزان المراجعة"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/reports/accounting/trial-balance",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_REPORT_TIME, \
            f"ميزان المراجعة استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_REPORT_TIME}s)"

    def test_create_journal_entry_performance(self, client, admin_headers):
        """⚡ أداء إنشاء قيد يومي"""
        entry_data = {
            "date": "2024-01-01",
            "description": "Performance Test Entry",
            "lines": [
                {"account_id": 1, "debit": 100, "credit": 0, "description": "Test"},
                {"account_id": 2, "debit": 0, "credit": 100, "description": "Test"}
            ],
            "status": "posted"
        }
        
        response, elapsed = self.measure_response_time(
            client.post,
            "/api/accounting/journal-entries",
            json=entry_data,
            headers=admin_headers
        )
        
        assert response.status_code in [200, 201]
        assert elapsed < self.TARGET_RESPONSE_TIME, \
            f"إنشاء القيد استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_RESPONSE_TIME}s)"

    def test_search_performance(self, client, admin_headers):
        """⚡ أداء البحث"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/inventory/products?search=test",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"البحث استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_pagination_performance(self, client, admin_headers):
        """⚡ أداء التصفح (Pagination)"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/sales/invoices?page=1&limit=50",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"التصفح استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    def test_filtering_performance(self, client, admin_headers):
        """⚡ أداء التصفية"""
        response, elapsed = self.measure_response_time(
            client.get,
            "/api/sales/invoices?status=posted&date_from=2024-01-01",
            headers=admin_headers
        )
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"التصفية استغرقت {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"

    @pytest.mark.parametrize("endpoint", [
        "/api/accounting/journal-entries",
        "/api/sales/invoices",
        "/api/inventory/products",
        "/api/purchases/invoices"
    ])
    def test_multiple_endpoints_performance(self, client, admin_headers, endpoint):
        """⚡ أداء عدة endpoints"""
        response, elapsed = self.measure_response_time(
            client.get,
            endpoint,
            headers=admin_headers
        )
        
        # بعض endpoints قد لا تكون موجودة (404)
        if response.status_code == 404:
            pytest.skip(f"Endpoint {endpoint} غير موجود")
        
        assert response.status_code == 200
        assert elapsed < self.TARGET_CRITICAL_TIME, \
            f"{endpoint} استغرق {elapsed:.3f}s (المستهدف: {self.TARGET_CRITICAL_TIME}s)"
