"""
AMAN ERP - اختبارات نظام الإشعارات المتقدمة والحديثة
Notifications: List, WS Ticket, Settings, Queue, Unsubscribe, Alphanumeric Tenancy
═══════════════════════════════════════════════════════════════
"""

import pytest
from jose import jwt
from config import settings as app_settings
from database import get_db_connection, get_system_db
from sqlalchemy import text
from helpers import assert_valid_response
from routers.auth.core import create_access_token


def _get_dynamic_test_context():
    """Dynamically find a seeded company database with users, and generate a valid token."""
    db = get_system_db()
    try:
        companies = db.execute(text("SELECT id FROM system_companies")).fetchall()
        for row in companies:
            company_id = row[0]
            try:
                with get_db_connection(company_id) as conn:
                    user = conn.execute(text("SELECT id, username FROM company_users LIMIT 1")).fetchone()
                    if user:
                        user_id = user[0]
                        username = user[1]
                        
                        token = create_access_token({
                            "sub": username,
                            "user_id": user_id,
                            "company_id": company_id,
                            "permissions": ["*"]
                        })
                        return {"Authorization": f"Bearer {token}"}, company_id
            except Exception:
                continue
        
        pytest.skip("No seeded company databases with active users found")
    finally:
        db.close()


class TestNotificationsHardened:
    """سيناريوهات اختبار الإشعارات المحصنة والمطورة"""

    def test_list_notifications_strict(self, client):
        """✅ جلب الإشعارات والتحقق من الهيكل"""
        headers, _ = _get_dynamic_test_context()
        r = client.get("/api/notifications", headers=headers)
        assert_valid_response(r)
        data = r.json()
        assert isinstance(data, list)
        if len(data) > 0:
            item = data[0]
            assert "id" in item
            assert "title" in item
            assert "is_read" in item

    def test_ws_ticket_generation(self, client):
        """✅ توليد تذكرة WebSocket قصيرة الأجل والتحقق من صحتها وفك تشفيرها"""
        headers, _ = _get_dynamic_test_context()
        r = client.post("/api/notifications/ws-ticket", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "ticket" in data
        
        ticket = data["ticket"]
        # Verify it can be decoded using our secret key
        payload = jwt.decode(ticket, app_settings.SECRET_KEY, algorithms=[app_settings.ALGORITHM])
        assert payload.get("token_use") == "ws_ticket"
        assert "company_id" in payload
        assert "user_id" in payload
        
        # Verify it has extremely short expiry (around 20s from now)
        import time
        assert payload["exp"] <= int(time.time()) + 25

    def test_smtp_settings_validation_failure(self, client):
        """✅ التحقق من أن إدخال منفذ SMTP غير صالح يرجع 400 وليس 500"""
        headers, _ = _get_dynamic_test_context()
        # Invalid port > 65535
        r = client.put("/api/notifications/settings", json={
            "smtp_port": 99999,
            "smtp_host": "smtp.gmail.com"
        }, headers=headers)
        assert r.status_code == 400
        assert "detail" in r.json()

        # Invalid port negative
        r = client.put("/api/notifications/settings", json={
            "smtp_port": -1,
        }, headers=headers)
        assert r.status_code == 400

        # Invalid host empty
        r = client.put("/api/notifications/settings", json={
            "smtp_host": "   ",
        }, headers=headers)
        assert r.status_code == 400

    def test_deduplication_in_queue_window(self, client):
        """✅ التحقق من عدم تكرار الإشعار في نافذة الإلغاء (Dedupe Window)"""
        from services.notifications.dispatcher import dispatch_user_notification
        
        _, company_id = _get_dynamic_test_context()
        
        conn = get_db_connection(company_id)
        try:
            # First dispatch
            res1 = dispatch_user_notification(
                conn,
                tenant_id=company_id,
                recipient_id=1,
                event_type="test_dedupe_event",
                channel="email",
                title="Dedupe Test",
                body="Testing deduplication window",
                commit=True
            )
            assert res1["dispatched"] is True
            
            # Second dispatch (immediate duplicate)
            res2 = dispatch_user_notification(
                conn,
                tenant_id=company_id,
                recipient_id=1,
                event_type="test_dedupe_event",
                channel="email",
                title="Dedupe Test",
                body="Testing deduplication window",
                commit=True
            )
            assert res2["dispatched"] is False
            assert res2["reason"] == "notifications.duplicate_in_window"
        finally:
            conn.close()

    def test_unsubscribe_link_verification(self, client):
        """✅ التحقق من صحة فك تشفير رابط إلغاء الاشتراك (Unsubscribe Token)"""
        from services.email_service import generate_unsubscribe_token
        
        _, company_id = _get_dynamic_test_context()
        
        token = generate_unsubscribe_token(user_id=1, event_type="leave_approved")
        
        # Test unsubscribe confirmation route
        r = client.get(f"/api/notifications/unsubscribe?token={token}&company_id={company_id}")
        assert r.status_code == 200
        assert "إلغاء اشتراكك" in r.text or "unsubscribe" in r.text.lower()
        
        # Test with invalid token
        r_invalid = client.get(f"/api/notifications/unsubscribe?token=invalid_token_here&company_id={company_id}")
        assert r_invalid.status_code == 400

    def test_alphanumeric_company_id_support(self, client):
        """✅ التحقق من أن المعرفات الأبجدية الرقمية (Alphanumeric) مدعومة بالكامل ولا تسبب أخطاء"""
        from services.notifications.dispatcher import dispatch
        
        _, company_id = _get_dynamic_test_context()
        
        conn = get_db_connection(company_id)
        try:
            # Should not raise ValueError/TypeError when using alphanumeric tenant_id
            alphanumeric_id = "company_abc_123"
            res = dispatch(
                conn,
                tenant_id=alphanumeric_id,
                event_type="alphanumeric_test",
                channel="email",
                recipient="test@example.com",
                payload={"test": True},
                commit=False  # Do not commit to avoid database pollution
            )
            assert "dispatched" in res
        finally:
            conn.close()

    def test_mark_read_404_invalid_id(self, client):
        """✅ التحقق من أن تحديد إشعار غير موجود يرجع 404 بدلاً من 200"""
        headers, _ = _get_dynamic_test_context()
        r = client.put("/api/notifications/999999/read", headers=headers)
        assert r.status_code == 404
