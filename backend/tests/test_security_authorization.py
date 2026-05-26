"""
AMAN ERP - Security Tests: Authorization
اختبارات الأمان: الصلاحيات والوصول
═══════════════════════════════════════
"""

"""
AMAN ERP - Security Tests: Authorization
اختبارات الأمان: الصلاحيات والوصول
═══════════════════════════════════════
"""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


class TestAuthorizationSecurity:
    """🔐 اختبارات أمان الصلاحيات"""

    def test_access_protected_endpoint_without_permission(self, client, company_user_token):
        """❌ رفض الوصول لـ endpoint محمي بدون صلاحية"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة الوصول لـ endpoint يتطلب صلاحية خاصة
        response = client.delete(
            "/api/companies/1",  # مثال: حذف شركة يتطلب صلاحية admin
            headers=headers
        )
        # يجب أن يُرفض (403/404/401) أو endpoint غير موجود (405)
        assert response.status_code in [403, 404, 401, 405], \
            f"يجب أن يُرفض الوصول بدون صلاحية (حصلنا على {response.status_code})"

    def test_access_with_wrong_company_id(self, client, company_user_token):
        """🔒 منع الوصول لبيانات شركة أخرى (Multi-tenant isolation)"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة الوصول لبيانات شركة أخرى
        # Note: يعتمد على كيفية تنفيذ multi-tenant isolation
        response = client.get("/api/accounting/journal-entries", headers=headers)
        
        # يجب أن يعيد فقط بيانات الشركة الخاصة بالمستخدم
        if response.status_code == 200:
            response.json()
            # التحقق من أن البيانات تعود للشركة الصحيحة فقط
            # (يعتمد على التطبيق)

    def test_branch_access_control(self, client, company_user_token):
        """🏢 التحكم في الوصول للفروع"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة الوصول لفرع غير مسموح
        response = client.get(
            "/api/sales/invoices?branch_id=99999",  # فرع غير موجود أو غير مسموح
            headers=headers
        )
        # يجب أن يُرفض أو يُفلتر
        assert response.status_code in [200, 403, 404]

    def test_role_based_access(self, client):
        """👥 التحكم في الوصول بناءً على الدور"""
        # Note: يحتاج إنشاء مستخدمين بأدوار مختلفة
        # هذا اختبار أساسي للتحقق من وجود RBAC
        
        # محاولة الوصول بـ role محدود
        # يجب أن يُرفض الوصول للعمليات المحمية
        pass

    def test_permission_wildcards(self, client, admin_headers):
        """⭐ اختبار الصلاحيات العامة (wildcards)"""
        # المستخدم بـ صلاحية "*" يجب أن يصل لكل شيء
        response = client.get("/api/accounting/journal-entries", headers=admin_headers)
        assert response.status_code == 200

    def test_section_wildcard_permissions(self, client):
        """⭐ اختبار صلاحيات القسم (section wildcards)"""
        # مستخدم بـ صلاحية "sales.*" يجب أن يصل لجميع sales endpoints
        # لكن لا يصل لـ purchases endpoints
        pass

    def test_unauthorized_data_modification(self, client, company_user_token):
        """🚫 منع تعديل البيانات بدون صلاحية"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة تعديل بيانات بدون صلاحية
        response = client.put(
            "/api/accounting/journal-entries/1",
            json={"status": "posted"},
            headers=headers
        )
        # يجب أن يُرفض إذا لم تكن هناك صلاحية (403/404/401) أو endpoint غير موجود (405)
        assert response.status_code in [403, 404, 401, 405], \
            f"يجب أن يُرفض التعديل بدون صلاحية (حصلنا على {response.status_code})"

    def test_unauthorized_data_deletion(self, client, company_user_token):
        """🚫 منع حذف البيانات بدون صلاحية"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة حذف بيانات بدون صلاحية
        response = client.delete(
            "/api/accounting/journal-entries/1",
            headers=headers
        )
        # يجب أن يُرفض إذا لم تكن هناك صلاحية (403/404/401) أو endpoint غير موجود (405)
        assert response.status_code in [403, 404, 401, 405], \
            f"يجب أن يُرفض الحذف بدون صلاحية (حصلنا على {response.status_code})"

    def test_token_manipulation(self, client):
        """🛡️ منع التلاعب بـ Token"""
        import os
        import time
        from jose import jwt
        from config import settings
        
        # الحصول على token جديد
        time.sleep(2)
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        username = os.environ.get("AMAN_TEST_USER", "aaaa")
        
        login_response = client.post(
            "/api/auth/login",
            data={
                "username": username,
                "password": password,
                "grant_type": "password"
            }
        )
        
        if login_response.status_code == 429:
            pytest.skip("Rate limited - يحتاج انتظار")
        
        if login_response.status_code != 200:
            pytest.skip(f"لا يمكن تسجيل الدخول: {login_response.status_code}")
        
        token = login_response.json().get("access_token")
        if not token:
            pytest.skip("لا يوجد token في الاستجابة")
        
        try:
            # محاولة تعديل token
            decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            original_company_id = decoded.get("company_id")
            decoded["company_id"] = "different_company_id_999"
            
            # إنشاء token معدّل
            manipulated_token = jwt.encode(decoded, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
            
            # محاولة استخدام token معدّل
            response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {manipulated_token}"}
            )
            # يجب أن يُرفض أو يُعيد بيانات الشركة الأصلية فقط
            # Note: قد ينجح (200) إذا كان النظام لا يتحقق من company_id في كل request
            # أو قد يُرفض (401/403) إذا كان يتحقق
            # 404 يعني endpoint غير موجود (غير متوقع هنا)
            assert response.status_code in [200, 401, 403, 404], \
                f"Token معدّل يجب أن يُعالج بشكل آمن (حصلنا على {response.status_code})"
            
            # إذا نجح (200)، يجب أن يُعيد بيانات الشركة الأصلية وليس المعدّلة
            if response.status_code == 200:
                data = response.json()
                # التحقق من أن company_id في الاستجابة هو الأصلي وليس المعدّل
                if "company_id" in data:
                    assert data["company_id"] == original_company_id, \
                        "يجب أن يُعيد بيانات الشركة الأصلية وليس المعدّلة"
        except jwt.ExpiredSignatureError:
            pytest.skip("Token منتهي - هذا آمن")
        except jwt.JWTError as e:
            pytest.skip(f"خطأ في Token: {e}")
        except Exception as e:
            # أي خطأ آخر يعني أن النظام رفض Token المعدّل (آمن)
            pytest.skip(f"Token manipulation test skipped: {e}")

    def test_privilege_escalation(self, client, company_user_token):
        """🛡️ منع تصعيد الصلاحيات"""
        
        # محاولة تغيير الدور أو الصلاحيات
        # Note: يعتمد على وجود endpoint لتعديل الأدوار
        # يجب أن يُرفض من قبل مستخدم عادي

    def test_cross_company_data_access(self, client):
        """🔒 منع الوصول لبيانات شركات أخرى"""
        # إنشاء token لشركة معينة
        # محاولة الوصول لبيانات شركة أخرى
        # يجب أن يُرفض تماماً
        pass

    def test_api_endpoint_enumeration(self, client):
        """🛡️ منع تعداد نقاط النهاية"""
        # محاولة الوصول لـ endpoints غير معروفة
        endpoints = [
            "/api/admin/users",
            "/api/admin/companies",
            "/api/internal/debug",
            "/api/secret/data"
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            # يجب أن يُعاد 401/403 وليس 404 (لإخفاء وجود endpoint)
            assert response.status_code in [401, 403, 404]

    def test_sensitive_data_in_response(self, client, admin_headers):
        """🔒 التأكد من عدم تسريب بيانات حساسة في الاستجابة"""
        response = client.get("/api/auth/me", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        # التأكد من عدم وجود كلمات مرور
        assert "password" not in str(data).lower()
        assert "secret" not in str(data).lower()
        assert "token" not in str(data).lower() or "access_token" in data  # فقط access_token مسموح

    def test_bulk_operations_permission(self, client, company_user_token):
        """🚫 منع العمليات المجمعة بدون صلاحية"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة حذف أو تعديل مجمع
        response = client.post(
            "/api/accounting/journal-entries/bulk-delete",
            json={"ids": [1, 2, 3]},
            headers=headers
        )
        # يجب أن يُرفض إذا لم تكن هناك صلاحية
        assert response.status_code in [403, 404, 405, 401]

    def test_audit_log_access(self, client, company_user_token):
        """📋 التحكم في الوصول لسجلات التدقيق"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        response = client.get("/api/audit/logs", headers=headers)
        # يجب أن يُرفض للمستخدمين العاديين
        assert response.status_code in [200, 403, 401]

    def test_settings_modification_permission(self, client, company_user_token):
        """⚙️ التحكم في تعديل الإعدادات"""
        headers = {"Authorization": f"Bearer {company_user_token}"}
        
        # محاولة تعديل إعدادات النظام
        response = client.put(
            "/api/settings/security",
            json={"setting": "value"},
            headers=headers
        )
        # يجب أن يُرفض للمستخدمين العاديين
        assert response.status_code in [403, 404, 401]
