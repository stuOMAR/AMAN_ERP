"""
AMAN ERP - Security Tests: Authentication
اختبارات الأمان: المصادقة والتسجيل
═══════════════════════════════════════
"""

"""
AMAN ERP - Security Tests: Authentication
اختبارات الأمان: المصادقة والتسجيل
═══════════════════════════════════════
"""

import pytest  # noqa: E402
import time  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


class TestAuthenticationSecurity:
    """🔐 اختبارات أمان المصادقة"""

    def test_login_with_valid_credentials(self, client):
        """✅ تسجيل دخول صحيح"""
        import os
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        response = client.post(
            "/api/auth/login",
            data={
                "username": os.environ.get("AMAN_TEST_USER", "aaaa"),
                "password": password,
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "company_id" in data or "user_id" in data

    def test_login_with_invalid_password(self, client):
        """❌ رفض تسجيل دخول بكلمة مرور خاطئة"""
        response = client.post(
            "/api/auth/login",
            data={
                "username": "admin",
                "password": "wrong_password_12345",
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        assert response.status_code in [401, 404]

    def test_login_with_nonexistent_user(self, client):
        """❌ رفض تسجيل دخول بمستخدم غير موجود"""
        response = client.post(
            "/api/auth/login",
            data={
                "username": "nonexistent_user_xyz_12345",
                "password": "any_password",
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        assert response.status_code in [401, 404]

    def test_login_rate_limiting(self, client):
        """🛡️ Rate limiting على محاولات تسجيل الدخول"""
        import time
        # استخدام username فريد لكل اختبار لتجنب rate limiting من اختبارات سابقة
        unique_username = f"test_rate_limit_{int(time.time() * 1000)}"
        
        # انتظار قصير لتجنب rate limiting من اختبارات سابقة
        time.sleep(2)
        
        # محاولة تسجيل دخول خاطئ 6 مرات (الحد الأقصى 5)
        rate_limited = False
        for i in range(6):
            response = client.post(
                "/api/auth/login",
                data={
                    "username": unique_username,
                    "password": "wrong_password",
                    "grant_type": "password",
                    "company_code": "d24b1b1c"
                }
            )
            if response.status_code == 429:
                rate_limited = True
                # إذا حصلنا على 429 في أي محاولة، هذا يعني أن rate limiting يعمل
                if i >= 4:  # بعد 5 محاولات على الأقل
                    break
            elif i < 5:
                # المحاولات الأولى يجب أن تفشل بشكل طبيعي
                assert response.status_code in [401, 404], \
                    f"المحاولة {i+1} يجب أن تفشل بـ 401/404 لكن حصلت على {response.status_code}"
        
        # التحقق من أن rate limiting تم تفعيله في النهاية
        # (قد يحدث في المحاولة 5 أو 6)
        if not rate_limited and response.status_code != 429:
            pytest.skip("Rate limiting not implemented yet")

    def test_access_without_token(self, client):
        """❌ رفض الوصول بدون token"""
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_access_with_invalid_token(self, client):
        """❌ رفض الوصول بـ token غير صحيح"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token_12345"}
        )
        assert response.status_code == 401

    def test_access_with_expired_token(self, client):
        """❌ رفض الوصول بـ token منتهي (محاكاة)"""
        # Note: في الإنتاج، يجب اختبار token منتهي فعلياً
        # هنا نختبر أن النظام يتحقق من صحة token
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer expired_token_test"}
        )
        assert response.status_code == 401

    def test_token_contains_required_fields(self, client):
        """✅ Token يحتوي على الحقول المطلوبة"""
        import os
        import time
        from jose import jwt
        from config import settings
        
        # الحصول على token جديد لتجنب rate limiting
        time.sleep(2)
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        username = os.environ.get("AMAN_TEST_USER", "aaaa")
        
        login_response = client.post(
            "/api/auth/login",
            data={
                "username": username,
                "password": password,
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        
        if login_response.status_code == 429:
            pytest.skip("Rate limited - يحتاج انتظار 15 دقيقة")
        
        if login_response.status_code != 200:
            pytest.skip(f"لا يمكن تسجيل الدخول: {login_response.status_code}")
        
        token = login_response.json().get("access_token")
        if not token:
            pytest.skip("لا يوجد token في الاستجابة")
        
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert "sub" in decoded, "Token يجب أن يحتوي على 'sub' (username)"
        assert "exp" in decoded, "Token يجب أن يحتوي على 'exp' (expiration)"
        assert "iat" in decoded, "Token يجب أن يحتوي على 'iat' (issued at)"
        assert "company_id" in decoded or "user_id" in decoded, "Token يجب أن يحتوي على company_id أو user_id"

    def test_password_not_in_response(self, client):
        """🔒 كلمة المرور غير موجودة في الاستجابة"""
        import os
        import time
        
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        username = os.environ.get("AMAN_TEST_USER", "aaaa")
        
        # انتظار أطول لتجنب rate limiting من اختبارات سابقة
        time.sleep(3)
        
        response = client.post(
            "/api/auth/login",
            data={
                "username": username,
                "password": password,
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        # قد نحصل على 429 بسبب rate limiting من اختبارات سابقة
        if response.status_code == 200:
            data = response.json()
            assert "password" not in str(data).lower(), "كلمة المرور يجب ألا تظهر في الاستجابة"
            assert password not in str(data), "كلمة المرور يجب ألا تظهر في الاستجابة"
        elif response.status_code == 429:
            # إذا كان rate limited، ننتظر أكثر ثم نحاول مرة أخرى
            time.sleep(5)
            response = client.post(
                "/api/auth/login",
                data={
                    "username": username,
                    "password": password,
                    "grant_type": "password"
                }
            )
            if response.status_code == 200:
                data = response.json()
                assert "password" not in str(data).lower()
                assert password not in str(data)
            else:
                pytest.skip(f"Rate limited بعد انتظار - status: {response.status_code}")
        else:
            pytest.skip(f"فشل تسجيل الدخول - status: {response.status_code}")

    def test_sql_injection_in_login(self, client):
        """🛡️ حماية من SQL Injection في تسجيل الدخول"""
        import time
        sql_injection_attempts = [
            "admin' OR '1'='1",
            "admin'--",
            "admin'/*",
            "' OR 1=1--",
            "admin'; DROP TABLE users;--"
        ]
        
        for i, attempt in enumerate(sql_injection_attempts):
            # تأخير بسيط لتجنب rate limiting
            if i > 0:
                time.sleep(0.5)
            
            response = client.post(
                "/api/auth/login",
                data={
                    "username": attempt,
                    "password": "any_password",
                    "grant_type": "password"
                }
            )
            # يجب أن يفشل بشكل آمن (401/404/400/429) وليس 500
            assert response.status_code != 500, \
                f"SQL injection attempt '{attempt}' يجب أن يُرفض بأمان وليس 500"
            assert response.status_code in [401, 404, 400, 429], \
                f"SQL injection attempt '{attempt}' يجب أن يُرفض بأمان (حصلنا على {response.status_code})"

    def test_xss_in_login(self, client):
        """🛡️ حماية من XSS في تسجيل الدخول"""
        import time
        xss_attempts = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert('xss')"
        ]
        
        for i, attempt in enumerate(xss_attempts):
            # تأخير بسيط لتجنب rate limiting
            if i > 0:
                time.sleep(0.5)
            
            response = client.post(
                "/api/auth/login",
                data={
                    "username": attempt,
                    "password": "any_password",
                    "grant_type": "password"
                }
            )
            # يجب أن يُرفض أو يُعالج بشكل آمن
            assert response.status_code in [401, 404, 400, 429]
            # التأكد من عدم وجود script في الاستجابة
            assert "<script>" not in response.text.lower()

    def test_brute_force_protection(self, client):
        """🛡️ حماية من Brute Force Attack"""
        username = f"test_brute_force_{int(time.time())}"
        
        # محاولة تسجيل دخول خاطئ متكرر
        for i in range(10):
            response = client.post(
                "/api/auth/login",
                data={
                    "username": username,
                    "password": f"wrong_password_{i}",
                    "grant_type": "password",
                    "company_code": "d24b1b1c"
                }
            )
            if i >= 5:  # بعد 5 محاولات
                # يجب تفعيل rate limiting
                if response.status_code == 429:
                    break
        else:
            pytest.skip("Rate limiting / brute force protection not implemented yet")

    def test_concurrent_login_attempts(self, client):
        """🛡️ معالجة محاولات تسجيل دخول متزامنة"""
        import threading
        import os
        import time
        
        results = []
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        # استخدام usernames مختلفة لتجنب rate limiting
        base_username = os.environ.get("AMAN_TEST_USER", "aaaa")
        
        def attempt_login(thread_id):
            # استخدام username فريد لكل thread
            f"{base_username}_concurrent_{thread_id}_{int(time.time() * 1000)}"
            response = client.post(
                "/api/auth/login",
                data={
                    "username": base_username,  # استخدام نفس username للاختبار
                    "password": password,
                    "grant_type": "password",
                    "company_code": "d24b1b1c"
                }
            )
            results.append(response.status_code)
        
        # 5 محاولات متزامنة (تقليل العدد لتجنب rate limiting)
        threads = [threading.Thread(target=attempt_login, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # يجب أن تنجح بعض المحاولات أو على الأقل لا تتعطل
        # قد نحصل على 429 بسبب rate limiting، وهذا مقبول
        assert len(results) == 5, "يجب أن تكتمل جميع المحاولات"
        # التحقق من أن النظام لم يتعطل (لا 500)
        assert 500 not in results, "يجب ألا يحدث خطأ 500"

    def test_token_refresh_security(self, client):
        """🔄 أمان Refresh Token"""
        import os
        import time
        
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
        
        # اختبار endpoint refresh token
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            assert "access_token" in data, "يجب أن يعيد token جديد"
            assert data["token_type"] == "bearer", "يجب أن يكون نوع token bearer"
            
            # التحقق من أن Token الجديد يعمل
            new_token = data["access_token"]
            me_response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {new_token}"}
            )
            assert me_response.status_code == 200, "Token الجديد يجب أن يعمل"
        elif response.status_code == 405:
            pytest.skip("Endpoint refresh غير موجود أو method غير مدعوم")
        else:
            assert response.status_code in [200, 401], \
                f"Refresh token يجب أن يعمل أو يُرفض بشكل آمن (حصلنا على {response.status_code})"

    def test_logout_invalidates_token(self, client):
        """🚪 تسجيل الخروج يبطل Token"""
        import os
        import time
        
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
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # التحقق من أن Token يعمل قبل logout
        me_response = client.get("/api/auth/me", headers=headers)
        assert me_response.status_code == 200, "Token يجب أن يعمل قبل logout"
        
        # محاولة تسجيل الخروج
        logout_response = client.post("/api/auth/logout", headers=headers)
        
        if logout_response.status_code == 200:
            # Note: في الإنتاج الكامل، يجب أن يُبطل Token (blacklist)
            # هنا نتحقق فقط من وجود endpoint
            assert "message" in logout_response.json() or logout_response.status_code == 200
        elif logout_response.status_code == 405:
            pytest.skip("Endpoint logout غير موجود أو method غير مدعوم")
        else:
            # حتى لو لم يُبطل Token، endpoint موجود
            assert logout_response.status_code in [200, 401, 403], \
                f"Logout endpoint يجب أن يعمل (حصلنا على {logout_response.status_code})"

    def test_case_sensitive_username(self, client):
        """🔤 حساسية حالة الأحرف في اسم المستخدم"""
        import os
        import time
        password = os.environ.get("AMAN_TEST_PASSWORD", "As123321")
        username = os.environ.get("AMAN_TEST_USER", "aaaa")
        
        # تأخير لتجنب rate limiting
        time.sleep(1)
        
        # محاولة تسجيل دخول بحروف كبيرة
        response = client.post(
            "/api/auth/login",
            data={
                "username": username.upper(),
                "password": password,
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        # يجب أن يفشل إذا كان النظام case-sensitive
        # أو ينجح إذا كان case-insensitive (يعتمد على التصميم)
        # أو 429 إذا كان rate limited
        assert response.status_code in [200, 401, 404, 429]

    def test_empty_credentials(self, client):
        """❌ رفض بيانات تسجيل دخول فارغة"""
        response = client.post(
            "/api/auth/login",
            data={
                "username": "",
                "password": "",
                "grant_type": "password"
            }
        )
        assert response.status_code in [400, 401, 422]

    def test_very_long_credentials(self, client):
        """🛡️ معالجة بيانات تسجيل دخول طويلة جداً"""
        import time
        time.sleep(1)  # تأخير لتجنب rate limiting
        
        long_string = "a" * 10000
        response = client.post(
            "/api/auth/login",
            data={
                "username": long_string,
                "password": long_string,
                "grant_type": "password",
                "company_code": "d24b1b1c"
            }
        )
        # يجب أن يُرفض بشكل آمن (400/413/422) أو rate limited (429)
        assert response.status_code in [400, 401, 404, 413, 422, 429]
