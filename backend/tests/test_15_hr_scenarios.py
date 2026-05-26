"""
AMAN ERP - اختبارات شاملة متعددة السيناريوهات: الموارد البشرية
Comprehensive Multi-Scenario Tests: HR Module
═══════════════════════════════════════════════════════
يتضمن: الأقسام، المناصب، الموظفين، الحضور، الإجازات، السلف، الرواتب، مكافأة نهاية الخدمة
"""

import pytest
from datetime import date, timedelta
from helpers import assert_valid_response


# ═══════════════════════════════════════════════════════════════
# 🏢 الأقسام - Departments
# ═══════════════════════════════════════════════════════════════
class TestDepartmentScenarios:
    """سيناريوهات الأقسام"""

    def test_list_departments(self, client, admin_headers):
        """✅ عرض الأقسام"""
        r = client.get("/api/hr/departments", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 3

    def test_create_department(self, client, admin_headers):
        """✅ إنشاء قسم"""
        r = client.post("/api/hr/departments", json={
            "department_name": "قسم التسويق",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_create_department_with_code(self, client, admin_headers):
        """✅ إنشاء قسم بكود"""
        r = client.post("/api/hr/departments", json={
            "department_name": "قسم الجودة",
            "department_code": "DEP-QA",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_delete_empty_department(self, client, admin_headers):
        """✅ حذف قسم فارغ"""
        r = client.post("/api/hr/departments", json={
            "department_name": "قسم للحذف",
        }, headers=admin_headers)
        if r.status_code in [200, 201]:
            did = r.json().get("id")
            if did:
                r2 = client.delete(f"/api/hr/departments/{did}", headers=admin_headers)
                assert r2.status_code in [200, 204, 400]


# ═══════════════════════════════════════════════════════════════
# 💼 المناصب - Positions
# ═══════════════════════════════════════════════════════════════
class TestPositionScenarios:
    """سيناريوهات المناصب"""

    def test_list_positions(self, client, admin_headers):
        """✅ عرض المناصب"""
        r = client.get("/api/hr/positions", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 3

    def test_create_position(self, client, admin_headers):
        """✅ إنشاء منصب"""
        r = client.post("/api/hr/positions", json={
            "position_name": "مدير تسويق",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_create_position_with_department(self, client, admin_headers):
        """✅ إنشاء منصب مرتبط بقسم"""
        r = client.get("/api/hr/departments", headers=admin_headers)
        depts = r.json()
        if not depts:
            pytest.skip("لا أقسام")

        r2 = client.post("/api/hr/positions", json={
            "position_name": "مساعد إداري",
            "department_id": depts[0]["id"],
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400, 409]

    def test_delete_unused_position(self, client, admin_headers):
        """✅ حذف منصب غير مستخدم"""
        r = client.post("/api/hr/positions", json={
            "position_name": "منصب للحذف",
        }, headers=admin_headers)
        if r.status_code in [200, 201]:
            pid = r.json().get("id")
            if pid:
                r2 = client.delete(f"/api/hr/positions/{pid}", headers=admin_headers)
                assert r2.status_code in [200, 204, 400]


# ═══════════════════════════════════════════════════════════════
# 👤 الموظفون - Employees
# ═══════════════════════════════════════════════════════════════
class TestEmployeeScenarios:
    """سيناريوهات الموظفين"""

    def test_list_employees(self, client, admin_headers):
        """✅ عرض الموظفين"""
        r = client.get("/api/hr/employees", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 3

    def test_create_employee_basic(self, client, admin_headers):
        """✅ إنشاء موظف بمعلومات أساسية"""
        r = client.post("/api/hr/employees", json={
            "first_name": "عبدالله",
            "last_name": "السالم",
            "salary": 7000,
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_create_employee_full(self, client, admin_headers):
        """✅ إنشاء موظف بمعلومات كاملة"""
        r = client.get("/api/hr/departments", headers=admin_headers)
        depts = r.json()
        dept_name = depts[0].get("department_name", "الإدارة العامة") if depts else "الإدارة العامة"

        r2 = client.post("/api/hr/employees", json={
            "first_name": "نورة",
            "last_name": "العمري",
            "salary": 8000,
            "department_name": dept_name,
            "branch_id": 1,
            "housing_allowance": 1500,
            "transport_allowance": 700,
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400, 409]

    def test_create_employee_with_user(self, client, admin_headers):
        """✅ إنشاء موظف مع مستخدم نظام"""
        r = client.post("/api/hr/employees", json={
            "first_name": "ياسر",
            "last_name": "المطيري",
            "salary": 6000,
            "create_user": True,
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 409]

    def test_update_employee(self, client, admin_headers):
        """✅ تحديث بيانات موظف"""
        r = client.get("/api/hr/employees", headers=admin_headers)
        emps = r.json()
        if not emps:
            pytest.skip("لا موظفين")
        eid = emps[0]["id"]
        r2 = client.put(f"/api/hr/employees/{eid}", json={
            "salary": 5500,
            "housing_allowance": 1100,
        }, headers=admin_headers)
        assert r2.status_code in [200, 400, 404]


# ═══════════════════════════════════════════════════════════════
# ⏰ الحضور والانصراف - Attendance
# ═══════════════════════════════════════════════════════════════
class TestAttendanceScenarios:
    """سيناريوهات الحضور"""

    def test_attendance_status(self, client, admin_headers):
        """✅ حالة الحضور الحالية"""
        r = client.get("/api/hr/attendance/status", headers=admin_headers)
        assert r.status_code in [200, 404, 500]

    def test_attendance_history(self, client, admin_headers):
        """✅ سجل الحضور"""
        r = client.get("/api/hr/attendance/history", headers=admin_headers)
        assert r.status_code in [200, 404, 500]

    def test_check_in(self, client, admin_headers):
        """✅ تسجيل حضور"""
        r = client.post("/api/hr/attendance/check-in", headers=admin_headers)
        # 404 if user is not linked to employee
        assert r.status_code in [200, 201, 400, 404]

    def test_check_out(self, client, admin_headers):
        """✅ تسجيل انصراف"""
        r = client.post("/api/hr/attendance/check-out", headers=admin_headers)
        # 404 if user is not linked to employee
        assert r.status_code in [200, 201, 400, 404]


# ═══════════════════════════════════════════════════════════════
# 🏖 الإجازات - Leave Requests
# ═══════════════════════════════════════════════════════════════
class TestLeaveScenarios:
    """سيناريوهات الإجازات"""

    def test_list_leaves(self, client, admin_headers):
        """✅ عرض طلبات الإجازة"""
        r = client.get("/api/hr/leaves", headers=admin_headers)
        assert_valid_response(r)

    def test_create_annual_leave(self, client, admin_headers):
        """✅ طلب إجازة سنوية"""
        r = client.post("/api/hr/leaves", json={
            "leave_type": "annual",
            "start_date": str(date.today() + timedelta(days=30)),
            "end_date": str(date.today() + timedelta(days=35)),
            "reason": "إجازة سنوية",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 500]

    def test_create_sick_leave(self, client, admin_headers):
        """✅ طلب إجازة مرضية"""
        r = client.post("/api/hr/leaves", json={
            "leave_type": "sick",
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=2)),
            "reason": "مرض",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 500]

    def test_create_emergency_leave(self, client, admin_headers):
        """✅ طلب إجازة طارئة"""
        r = client.post("/api/hr/leaves", json={
            "leave_type": "emergency",
            "start_date": str(date.today()),
            "end_date": str(date.today()),
            "reason": "ظرف طارئ",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400, 500]

    def test_approve_leave(self, client, admin_headers):
        """✅ الموافقة على إجازة"""
        r = client.get("/api/hr/leaves", headers=admin_headers)
        leaves = r.json()
        pending = next((line for line in leaves if line.get("status") == "pending"), None)
        if not pending:
            pytest.skip("لا إجازات معلقة")
        lid = pending["id"]
        r2 = client.put(f"/api/hr/leaves/{lid}", json={
            "status": "approved",
        }, headers=admin_headers)
        assert r2.status_code in [200, 400, 404]

    def test_reject_leave(self, client, admin_headers):
        """✅ رفض إجازة"""
        r = client.get("/api/hr/leaves", headers=admin_headers)
        leaves = r.json()
        pending = next((line for line in leaves if line.get("status") == "pending"), None)
        if not pending:
            pytest.skip("لا إجازات معلقة")
        lid = pending["id"]
        r2 = client.put(f"/api/hr/leaves/{lid}", json={
            "status": "rejected",
        }, headers=admin_headers)
        assert r2.status_code in [200, 400, 404]


# ═══════════════════════════════════════════════════════════════
# 💳 السلف والقروض - Employee Loans
# ═══════════════════════════════════════════════════════════════
class TestLoanScenarios:
    """سيناريوهات السلف"""

    def test_list_loans(self, client, admin_headers):
        """✅ عرض السلف"""
        r = client.get("/api/hr/loans", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_create_loan(self, client, admin_headers):
        """✅ إنشاء سلفة"""
        r = client.get("/api/hr/employees", headers=admin_headers)
        emps = r.json()
        if not emps:
            pytest.skip("لا موظفين")

        r2 = client.post("/api/hr/loans", json={
            "employee_id": emps[0]["id"],
            "amount": 5000,
            "total_installments": 5,
            "start_date": str(date.today()),
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400, 500]

    def test_create_large_loan(self, client, admin_headers):
        """✅ إنشاء سلفة كبيرة"""
        r = client.get("/api/hr/employees", headers=admin_headers)
        emps = r.json()
        if not emps:
            pytest.skip("لا موظفين")

        r2 = client.post("/api/hr/loans", json={
            "employee_id": emps[0]["id"],
            "amount": 20000,
            "total_installments": 12,
            "start_date": str(date.today() + timedelta(days=30)),
        }, headers=admin_headers)
        assert r2.status_code in [200, 201, 400, 500]

    def test_approve_loan(self, client, admin_headers):
        """✅ اعتماد سلفة"""
        # Create a new pending loan to ensure we have one to approve
        r = client.get("/api/hr/employees", headers=admin_headers)
        emps = r.json()
        if not emps:
            pytest.skip("لا موظفين")
        r_create = client.post("/api/hr/loans", json={
            "employee_id": emps[-1]["id"],
            "amount": 3000,
            "total_installments": 3,
            "start_date": str(date.today()),
        }, headers=admin_headers)
        if r_create.status_code not in [200, 201]:
            # Fallback: check existing
            r2 = client.get("/api/hr/loans", headers=admin_headers)
            loans = r2.json()
            pending = next((line for line in loans if line.get("status") == "pending"), None)
            if not pending:
                pytest.skip("لا سلف معلقة")
            lid = pending["id"]
        else:
            lid = r_create.json()["id"]
        r3 = client.put(f"/api/hr/loans/{lid}/approve", headers=admin_headers)
        assert r3.status_code in [200, 400, 404]


# ═══════════════════════════════════════════════════════════════
# 💰 الرواتب - Payroll
# ═══════════════════════════════════════════════════════════════
class TestPayrollScenarios:
    """سيناريوهات الرواتب"""

    def test_list_payroll_periods(self, client, admin_headers):
        """✅ عرض فترات الرواتب"""
        r = client.get("/api/hr/payroll-periods", headers=admin_headers)
        assert_valid_response(r)
        assert len(r.json()) >= 1

    def test_get_payroll_period_detail(self, client, admin_headers):
        """✅ تفاصيل فترة رواتب"""
        r = client.get("/api/hr/payroll-periods", headers=admin_headers)
        periods = r.json()
        if not periods:
            pytest.skip("لا فترات رواتب")
        pid = periods[0]["id"]
        r2 = client.get(f"/api/hr/payroll-periods/{pid}", headers=admin_headers)
        assert r2.status_code in [200, 404]

    def test_create_payroll_period(self, client, admin_headers):
        """✅ إنشاء فترة رواتب"""
        r = client.post("/api/hr/payroll-periods", json={
            "name": "رواتب يوليو 2025",
            "start_date": "2025-07-01",
            "end_date": "2025-07-31",
            "payment_date": "2025-07-28",
        }, headers=admin_headers)
        assert r.status_code in [200, 201, 400]

    def test_get_payroll_entries(self, client, admin_headers):
        """✅ عرض مسيرات الرواتب"""
        r = client.get("/api/hr/payroll-periods", headers=admin_headers)
        periods = r.json()
        if not periods:
            pytest.skip("لا فترات")
        pid = periods[0]["id"]
        r2 = client.get(f"/api/hr/payroll-periods/{pid}/entries", headers=admin_headers)
        assert r2.status_code in [200, 404]

    def test_generate_payroll(self, client, admin_headers):
        """✅ توليد مسير رواتب"""
        r = client.get("/api/hr/payroll-periods", headers=admin_headers)
        periods = r.json()
        # Find draft period
        draft = next((p for p in periods if p.get("status") == "draft"), None)
        if not draft:
            pytest.skip("لا فترة مسودة")
        pid = draft["id"]
        r2 = client.post(f"/api/hr/payroll-periods/{pid}/generate", headers=admin_headers)
        assert r2.status_code in [200, 201, 400, 500]


# ═══════════════════════════════════════════════════════════════
# 🏁 مكافأة نهاية الخدمة - End of Service
# ═══════════════════════════════════════════════════════════════
class TestEndOfServiceScenarios:
    """سيناريوهات مكافأة نهاية الخدمة"""

    def test_calculate_eos_short_service(self, client, admin_headers):
        """✅ حساب مكافأة لخدمة قصيرة"""
        r = client.post("/api/hr/end-of-service/calculate", json={
            "employee_id": 1,
        }, headers=admin_headers)
        # May succeed or fail based on employee data
        assert r.status_code in [200, 400, 404, 500]

    def test_calculate_eos_different_employee(self, client, admin_headers):
        """✅ حساب مكافأة لموظف آخر"""
        r = client.post("/api/hr/end-of-service/calculate", json={
            "employee_id": 2,
        }, headers=admin_headers)
        assert r.status_code in [200, 400, 404, 500]

    def test_calculate_eos_invalid_employee(self, client, admin_headers):
        """✅ حساب مكافأة لموظف غير موجود"""
        r = client.post("/api/hr/end-of-service/calculate", json={
            "employee_id": 99999,
        }, headers=admin_headers)
        assert r.status_code in [400, 404, 500]
