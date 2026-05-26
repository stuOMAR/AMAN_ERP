"""
AMAN ERP - Load Tests: Concurrent Users
اختبارات التحميل: المستخدمون المتزامنون
═══════════════════════════════════════
"""

"""
AMAN ERP - Load Tests: Concurrent Users
اختبارات التحميل: المستخدمون المتزامنون
═══════════════════════════════════════
"""

import threading  # noqa: E402
import time  # noqa: E402
import os  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


class TestConcurrentLoad:
    """⚡ اختبارات التحميل المتزامن"""

    def test_concurrent_login(self, client):
        """⚡ تسجيل دخول متزامن"""
        num_threads = 20
        results = []
        errors = []
        
        def login_attempt():
            try:
                password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
                username = os.environ.get("AMAN_TEST_USER", "aaaa")
                response = client.post(
                    "/api/auth/login",
                    data={
                        "username": username,
                        "password": password,
                        "grant_type": "password"
                    }
                )
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=login_attempt) for _ in range(num_threads)]
        start_time = time.time()
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        elapsed = time.time() - start_time
        
        # يجب أن تنجح معظم المحاولات
        success_count = results.count(200)
        success_rate = success_count / num_threads
        
        assert success_rate >= 0.8, \
            f"معدل النجاح {success_rate*100:.1f}% (المستهدف: 80%+)"
        assert len(errors) == 0, f"حدثت أخطاء: {errors[:5]}"
        assert elapsed < 10, f"الوقت المستغرق {elapsed:.2f}s (المستهدف: <10s)"

    def test_concurrent_api_calls(self, client, admin_headers):
        """⚡ استدعاءات API متزامنة"""
        num_threads = 50
        results = []
        errors = []
        endpoints = [
            "/api/dashboard/stats",
            "/api/accounting/journal-entries",
            "/api/sales/invoices",
            "/api/inventory/products"
        ]
        
        def api_call(endpoint):
            try:
                response = client.get(endpoint, headers=admin_headers)
                results.append((endpoint, response.status_code, time.time()))
            except Exception as e:
                errors.append((endpoint, str(e)))
        
        threads = []
        for endpoint in endpoints:
            for _ in range(num_threads // len(endpoints)):
                t = threading.Thread(target=api_call, args=(endpoint,))
                threads.append(t)
        
        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        elapsed = time.time() - start_time
        
        # يجب أن تنجح جميع الاستدعاءات
        success_count = sum(1 for _, status, _ in results if status == 200)
        success_rate = success_count / len(results) if results else 0
        
        assert success_rate >= 0.95, \
            f"معدل النجاح {success_rate*100:.1f}% (المستهدف: 95%+)"
        assert len(errors) == 0, f"حدثت أخطاء: {errors[:5]}"
        assert elapsed < 30, f"الوقت المستغرق {elapsed:.2f}s (المستهدف: <30s)"

    def test_concurrent_data_creation(self, client, admin_headers):
        """⚡ إنشاء بيانات متزامن"""
        num_threads = 10
        results = []
        errors = []
        
        def create_entry(thread_id):
            try:
                entry_data = {
                    "date": "2024-01-01",
                    "description": f"Concurrent Test Entry {thread_id}",
                    "lines": [
                        {"account_id": 1, "debit": 100, "credit": 0, "description": "Test"},
                        {"account_id": 2, "debit": 0, "credit": 100, "description": "Test"}
                    ],
                    "status": "draft"  # draft لتجنب التأثير على البيانات
                }
                response = client.post(
                    "/api/accounting/journal-entries",
                    json=entry_data,
                    headers=admin_headers
                )
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=create_entry, args=(i,)) for i in range(num_threads)]
        start_time = time.time()
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        elapsed = time.time() - start_time
        
        success_count = results.count(200) + results.count(201)
        success_rate = success_count / num_threads
        
        assert success_rate >= 0.8, \
            f"معدل النجاح {success_rate*100:.1f}% (المستهدف: 80%+)"
        assert elapsed < 15, f"الوقت المستغرق {elapsed:.2f}s (المستهدف: <15s)"

    def test_database_connection_pool(self, client, admin_headers):
        """⚡ اختبار Connection Pool"""
        num_requests = 100
        results = []
        
        start_time = time.time()
        for i in range(num_requests):
            response = client.get("/api/dashboard/stats", headers=admin_headers)
            results.append((response.status_code, time.time() - start_time))
        
        elapsed = time.time() - start_time
        
        success_count = sum(1 for status, _ in results if status == 200)
        avg_time = elapsed / num_requests
        
        assert success_count == num_requests, "يجب أن تنجح جميع الطلبات"
        assert avg_time < 0.5, f"متوسط الوقت {avg_time:.3f}s (المستهدف: <0.5s)"
        assert elapsed < 50, f"إجمالي الوقت {elapsed:.2f}s (المستهدف: <50s)"

    def test_mixed_workload(self, client, admin_headers):
        """⚡ حمل مختلط (قراءة وكتابة)"""
        num_reads = 30
        num_writes = 10
        results = []
        
        def read_operation():
            response = client.get("/api/accounting/journal-entries", headers=admin_headers)
            results.append(("read", response.status_code))
        
        def write_operation(thread_id):
            entry_data = {
                "date": "2024-01-01",
                "description": f"Mixed Workload Test {thread_id}",
                "lines": [
                    {"account_id": 1, "debit": 50, "credit": 0, "description": "Test"},
                    {"account_id": 2, "debit": 0, "credit": 50, "description": "Test"}
                ],
                "status": "draft"
            }
            response = client.post(
                "/api/accounting/journal-entries",
                json=entry_data,
                headers=admin_headers
            )
            results.append(("write", response.status_code))
        
        threads = []
        for i in range(num_reads):
            t = threading.Thread(target=read_operation)
            threads.append(t)
        for i in range(num_writes):
            t = threading.Thread(target=write_operation, args=(i,))
            threads.append(t)
        
        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        elapsed = time.time() - start_time
        
        read_success = sum(1 for op, status in results if op == "read" and status == 200)
        write_success = sum(1 for op, status in results if op == "write" and status in [200, 201])
        
        assert read_success == num_reads, f"يجب أن تنجح جميع عمليات القراءة ({read_success}/{num_reads})"
        assert write_success >= num_writes * 0.8, \
            f"يجب أن تنجح 80%+ من عمليات الكتابة ({write_success}/{num_writes})"
        assert elapsed < 20, f"الوقت المستغرق {elapsed:.2f}s (المستهدف: <20s)"
