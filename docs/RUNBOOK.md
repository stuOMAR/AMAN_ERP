# 📋 AMAN ERP — دليل الطوارئ التشغيلي (Runbook)

> **الإصدار:** 1.0  
> **آخر تحديث:** 2025  
> **المسؤول:** فريق DevOps / مدير النظام

---

## الفهرس

1. [معلومات الاتصال والتصعيد](#1-معلومات-الاتصال-والتصعيد)
2. [الوصول للبنية التحتية](#2-الوصول-للبنية-التحتية)
3. [إجراءات الطوارئ السريعة](#3-إجراءات-الطوارئ-السريعة)
4. [استكشاف الأخطاء — Backend](#4-استكشاف-الأخطاء--backend)
5. [استكشاف الأخطاء — Database](#5-استكشاف-الأخطاء--database)
6. [استكشاف الأخطاء — Redis](#6-استكشاف-الأخطاء--redis)
7. [النسخ الاحتياطي والاستعادة](#7-النسخ-الاحتياطي-والاستعادة)
8. [النشر والترقيات](#8-النشر-والترقيات)
9. [الأمان — الاستجابة للحوادث](#9-الأمان--الاستجابة-للحوادث)
10. [الصيانة الدورية](#10-الصيانة-الدورية)
11. [تدوير الأسرار + Smoke Regression](#11-تدوير-الأسرار--smoke-regression)

---

## 1. معلومات الاتصال والتصعيد

| المستوى | المسؤول | طريقة التواصل | وقت الاستجابة |
|---------|---------|---------------|---------------|
| L1 | مهندس DevOps | Slack #ops-alerts | 15 دقيقة |
| L2 | مدير التقنية (CTO) | هاتف + Slack | 30 دقيقة |
| L3 | مطور رئيسي | هاتف | 1 ساعة |

### تصنيف الحوادث

| الخطورة | الوصف | مثال | وقت الحل المستهدف |
|---------|-------|------|-------------------|
| **P1 — حرج** | النظام متوقف بالكامل | DB down, no backend | 30 دقيقة |
| **P2 — عالي** | وظيفة رئيسية معطلة | لا يمكن إنشاء فواتير | 2 ساعة |
| **P3 — متوسط** | تدهور أداء | بطء ملحوظ | 4 ساعات |
| **P4 — منخفض** | مشكلة تجميلية | خطأ في ترجمة | يوم عمل |

---

## 2. الوصول للبنية التحتية

### الخوادم

```bash
# الإنتاج
ssh deploy@erp.yourdomain.com

# المسارات الهامة
/opt/aman/                     # مجلد التطبيق
/opt/aman/backend/.env         # متغيرات البيئة
/opt/aman/backups/             # النسخ الاحتياطية
/var/log/aman/                 # السجلات
```

### Docker

```bash
# حالة الخدمات
docker compose ps

# سجلات الخدمة
docker compose logs -f backend --tail=100
docker compose logs -f db --tail=50

# الدخول لحاوية
docker compose exec backend bash
docker compose exec db psql -U aman -d postgres
```

### قواعد البيانات

```bash
# الاتصال بقاعدة البيانات الرئيسية
psql -h localhost -U aman -d postgres

# الاتصال بقاعدة شركة محددة
psql -h localhost -U aman -d aman_<company_id>

# قائمة قواعد بيانات الشركات
psql -U aman -d postgres -c "SELECT id, company_name, database_name, status FROM system_companies;"
```

---

## 3. إجراءات الطوارئ السريعة

### 🔴 النظام متوقف بالكامل

```bash
# 1. تحقق من حالة Docker
docker compose ps

# 2. أعد تشغيل جميع الخدمات
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 3. تحقق من الصحة
curl -s http://localhost:8000/health | python3 -m json.tool

# 4. راقب السجلات
docker compose logs -f --tail=50
```

### 🔴 قاعدة البيانات لا تستجيب

```bash
# 1. تحقق من حالة PostgreSQL
docker compose exec db pg_isready -U aman

# 2. تحقق من المساحة
docker compose exec db df -h /var/lib/postgresql/data

# 3. أعد تشغيل PostgreSQL فقط
docker compose restart db

# 4. انتظر حتى يصبح جاهزاً ثم أعد تشغيل Backend
sleep 10
docker compose restart backend

# 5. تحقق من الاتصالات المعلقة
docker compose exec db psql -U aman -c "SELECT count(*) FROM pg_stat_activity;"
```

### 🔴 ذاكرة الخادم ممتلئة

```bash
# 1. تحقق من الاستخدام
free -h
docker stats --no-stream

# 2. أوقف الخدمات غير الحرجة مؤقتاً
docker compose stop grafana prometheus

# 3. امسح ذاكرة Redis
docker compose exec redis redis-cli FLUSHDB

# 4. أعد تشغيل Backend (يحرر الذاكرة)
docker compose restart backend
```

### 🟡 بطء شديد في الاستجابة

```bash
# 1. تحقق من P95 latency
curl -s http://localhost:8000/metrics | grep http_request_duration

# 2. تحقق من استعلامات بطيئة
docker compose exec db psql -U aman -c "
  SELECT pid, now()-query_start AS duration, query 
  FROM pg_stat_activity 
  WHERE state = 'active' AND now()-query_start > interval '5 seconds'
  ORDER BY duration DESC LIMIT 10;"

# 3. ألغِ الاستعلامات المعلقة (> 5 دقائق)
docker compose exec db psql -U aman -c "
  SELECT pg_terminate_backend(pid) 
  FROM pg_stat_activity 
  WHERE state = 'active' AND now()-query_start > interval '5 minutes'
  AND pid <> pg_backend_pid();"

# 4. VACUUM للجداول الكبيرة
docker compose exec db psql -U aman -d aman_<company_id> -c "VACUUM ANALYZE;"
```

---

## 4. استكشاف الأخطاء — Backend

### Backend لا يبدأ

```bash
# 1. تحقق من السجلات
docker compose logs backend --tail=100

# 2. تحقق من متغيرات البيئة
docker compose exec backend env | grep -E "(POSTGRES|REDIS|SECRET)"

# 3. تحقق من صحة الكود
docker compose exec backend python -c "import ast; ast.parse(open('main.py').read()); print('OK')"

# 4. تشغيل يدوي للتشخيص
docker compose exec backend python -c "from config import settings; print(settings.DATABASE_URL)"
```

### أخطاء 500 متكررة

```bash
# 1. ابحث في سجلات JSON
docker compose logs backend --since=10m | grep '"level": "ERROR"'

# 2. تحقق من request_id محدد
docker compose logs backend | grep '<request_id>'

# 3. تحقق من اتصال DB
docker compose exec backend python -c "
from database import engine
from sqlalchemy import text
with engine.connect() as c:
    print(c.execute(text('SELECT 1')).scalar())
"
```

### ارتفاع استخدام CPU

```bash
# 1. حدد العمليات الثقيلة
docker compose top backend

# 2. قلل عدد Workers مؤقتاً
docker compose exec backend kill -HUP 1  # Gunicorn graceful reload

# 3. أو أعد التشغيل بعمال أقل
GUNICORN_WORKERS=2 docker compose up -d backend
```

---

## 5. استكشاف الأخطاء — Database

### مساحة القرص ممتلئة

```bash
# 1. تحقق من حجم كل قاعدة بيانات
docker compose exec db psql -U aman -c "
  SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size 
  FROM pg_database ORDER BY pg_database_size(datname) DESC;"

# 2. حدد أكبر الجداول
docker compose exec db psql -U aman -d aman_<company_id> -c "
  SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS size
  FROM pg_catalog.pg_statio_user_tables 
  ORDER BY pg_total_relation_size(relid) DESC LIMIT 20;"

# 3. نظف سجلات المراجعة القديمة (> 6 أشهر)
docker compose exec db psql -U aman -d aman_<company_id> -c "
  DELETE FROM audit_log WHERE created_at < NOW() - INTERVAL '6 months';"

# 4. VACUUM FULL (⚠️ يقفل الجدول)
docker compose exec db psql -U aman -d aman_<company_id> -c "VACUUM FULL ANALYZE;"
```

### Deadlocks

```bash
# 1. تحقق من deadlocks
docker compose exec db psql -U aman -c "
  SELECT datname, deadlocks FROM pg_stat_database WHERE deadlocks > 0;"

# 2. تحقق من الأقفال الحالية
docker compose exec db psql -U aman -c "
  SELECT blocked.pid AS blocked_pid,
         blocking.pid AS blocking_pid,
         blocked.query AS blocked_query
  FROM pg_stat_activity blocked
  JOIN pg_locks bl ON bl.pid = blocked.pid
  JOIN pg_locks bk ON bk.locktype = bl.locktype 
       AND bk.database IS NOT DISTINCT FROM bl.database
       AND bk.relation IS NOT DISTINCT FROM bl.relation
  JOIN pg_stat_activity blocking ON bk.pid = blocking.pid
  WHERE NOT bl.granted AND bl.pid <> bk.pid;"
```

### استعادة من اتصال مقطوع

```bash
# أعد تعيين الاتصالات المعلقة
docker compose exec db psql -U aman -c "
  SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
  WHERE state = 'idle in transaction' AND now()-state_change > interval '10 minutes';"
```

---

## 6. استكشاف الأخطاء — Redis

```bash
# حالة Redis
docker compose exec redis redis-cli INFO server | head -20

# الذاكرة
docker compose exec redis redis-cli INFO memory

# عدد المفاتيح
docker compose exec redis redis-cli DBSIZE

# مسح ذاكرة التخزين المؤقت (آمن — البيانات تُعاد بنائها)
docker compose exec redis redis-cli FLUSHDB

# مسح rate limiter فقط
docker compose exec redis redis-cli --scan --pattern 'rl:*' | xargs -r redis-cli DEL
```

---

## 7. النسخ الاحتياطي والاستعادة

### تشغيل نسخة احتياطية يدوية

```bash
./scripts/backup.sh
```

### استعادة من نسخة احتياطية

```bash
# 1. أوقف Backend أولاً
docker compose stop backend

# 2. استعد قاعدة البيانات الرئيسية
gunzip -c backups/20250101_020000_system.sql.gz | \
  psql -h localhost -U aman -d postgres

# 3. استعد قاعدة شركة
gunzip -c backups/20250101_020000_aman_be67ce39.sql.gz | \
  psql -h localhost -U aman -d aman_be67ce39

# 4. أعد تشغيل Backend
docker compose start backend

# 5. تحقق
curl -s http://localhost:8000/health | python3 -m json.tool
```

### Point-in-Time Recovery (PITR)

```bash
# يتطلب تفعيل WAL archiving في postgresql.conf:
# wal_level = replica
# archive_mode = on
# archive_command = 'cp %p /var/lib/postgresql/wal_archive/%f'

# للاستعادة إلى نقطة زمنية:
# 1. أوقف PostgreSQL
# 2. أنشئ recovery.conf:
echo "restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p'
recovery_target_time = '2025-01-15 14:30:00'" > recovery.conf

# 3. أعد تشغيل PostgreSQL
```

---

## 8. النشر والترقيات

### ⚠️ تحذير مهم جداً — منع فقدان البيانات

```
❌ لا تستخدم هذه الأوامر أبداً (تحذف قاعدة البيانات كاملاً):
   docker compose down -v
   docker volume rm aman_db_data
   docker system prune -a --volumes

✅ استخدم دائماً:
   docker compose stop        # يوقف الحاويات ويحفظ البيانات
   docker compose start       # يعيد تشغيل الخدمات المتوقفة
   docker compose up -d       # يشغّل الخدمات مع إنشاء أي غير موجودة
```

### إيقاف السيرفر بأمان (قبل Power Off من DigitalOcean)

```bash
# الطريقة الآمنة — تأخذ نسخة احتياطية قبل الإيقاف
bash /opt/aman/safe-stop.sh

# أو يدوياً:
bash /opt/aman/scripts/backup.sh          # نسخة احتياطية أولاً
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop   # إيقاف آمن
```

### إعادة تشغيل السيرفر بعد Power On

```bash
# بعد إعادة التشغيل من DigitalOcean، Docker يبدأ الحاويات تلقائياً
# إذا لم تبدأ تلقائياً:
bash /opt/aman/safe-start.sh

# أو يدوياً:
cd /opt/aman && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
sleep 30
curl -s http://localhost:8000/health | python3 -m json.tool
```

### النسخ الاحتياطي اليدوي

```bash
bash /opt/aman/scripts/backup.sh
# النسخ تُحفظ في: /opt/aman/backups/
# النسخ التلقائية: كل يوم الساعة 02:00 صباحاً
# لعرض آخر النسخ:
ls -lh /opt/aman/backups/ | tail -10
```

### النشر العادي (Zero-downtime)

```bash
# 1. اسحب آخر الكود
cd /opt/aman && git pull origin main

# 2. أنشئ الحاويات الجديدة
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 3. شغّل الهجرات (System + جميع قواعد الشركات)
docker compose exec backend alembic -x company=all upgrade head

# 4. أعد النشر (rolling update)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend

# 5. تحقق من الصحة
sleep 10
curl -s http://localhost:8000/health | python3 -m json.tool

# 6. راقب الأخطاء (5 دقائق)
docker compose logs -f backend --since=5m | grep -i error
```

### التراجع (Rollback)

```bash
# 1. ارجع للإصدار السابق
git checkout HEAD~1

# 2. أعد البناء والنشر
docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend

# 3. تراجع عن آخر هجرة (إن لزم) على جميع الشركات
docker compose exec backend alembic -x company=all downgrade -1
```

### تحديث Frontend فقط

```bash
docker compose build frontend
docker compose up -d --no-deps frontend
```

---

## 9. الأمان — الاستجابة للحوادث

### 🔴 اشتباه اختراق حساب

```bash
# 1. عطّل المستخدم فوراً
psql -U aman -d aman_<company_id> -c "
  UPDATE company_users SET is_active = false WHERE username = '<username>';"

# 2. أبطل جميع التوكنات (أضف للقائمة السوداء)
# من خلال واجهة الإدارة أو API:
curl -X POST http://localhost:8000/api/auth/force-logout/<user_id> \
  -H "Authorization: Bearer <admin_token>"

# 3. راجع سجل المراجعة
psql -U aman -d aman_<company_id> -c "
  SELECT * FROM audit_log 
  WHERE performed_by = '<username>' 
  ORDER BY created_at DESC LIMIT 50;"

# 4. تحقق من IPs المشبوهة
psql -U aman -d postgres -c "
  SELECT * FROM system_activity_log 
  WHERE performed_by = '<username>'
  ORDER BY created_at DESC LIMIT 20;"
```

### 🔴 تسريب SECRET_KEY

```bash
# 1. أنشئ مفتاح جديد فوراً
python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. حدّث .env
nano /opt/aman/backend/.env  # غيّر SECRET_KEY

# 3. أعد تشغيل Backend (يُبطل جميع التوكنات)
docker compose restart backend

# ⚠️ جميع المستخدمين سيحتاجون لإعادة تسجيل الدخول
```

### 🔴 هجوم Brute Force

```bash
# 1. تحقق من محاولات الدخول الفاشلة
docker compose logs backend --since=1h | grep "failed_login\|rate_limit\|429"

# 2. احجب IP على مستوى Nginx
echo "deny <IP_ADDRESS>;" >> /etc/nginx/conf.d/blocked_ips.conf
nginx -t && nginx -s reload

# 3. أو احجب على مستوى الجدار الناري
ufw deny from <IP_ADDRESS>
```

---

## 10. الصيانة الدورية

### يومياً (تلقائي عبر cron)
- ✅ النسخ الاحتياطي: `0 2 * * * /opt/aman/scripts/backup.sh`
- ✅ تنظيف التوكنات المنتهية: تلقائي في التطبيق (كل ساعة)

### أسبوعياً
```bash
# 1. تحقق من مساحة القرص
df -h
docker system df

# 2. نظف حاويات Docker القديمة
docker system prune -f

# 3. تحقق من سجلات الأخطاء
docker compose logs backend --since=7d | grep -c '"level": "ERROR"'

# 4. حدّث الأمان
apt-get update && apt-get upgrade -y --security-only
```

### شهرياً
```bash
# 1. VACUUM ANALYZE لجميع قواعد البيانات
for db in $(psql -U aman -t -A -c "SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"); do
  echo "VACUUM ANALYZE on $db..."
  psql -U aman -d "$db" -c "VACUUM ANALYZE;"
done

# 2. تحقق من حجم النسخ الاحتياطية
du -sh /opt/aman/backups/

# 3. اختبر الاستعادة على بيئة اختبار
# (استعد آخر نسخة على خادم اختبار وتحقق)

# 4. حدّث شهادات SSL (إن لزم)
certbot renew --dry-run

# 5. راجع التنبيهات والمقاييس في Grafana
```

### ربع سنوي
```bash
# 1. حدّث packages Python
pip list --outdated
# حدّث بحذر وافحص

# 2. حدّث Docker images
docker compose pull
docker compose up -d

# 3. مراجعة أمنية
# - راجع الصلاحيات والأدوار
# - راجع مفاتيح API النشطة
# - حدّث كلمات المرور الداخلية
```

---

## 11. تدوير الأسرار + Smoke Regression

### 11.1 تدوير الأسرار (تشغيلي)

استخدم سكربت المساعدة التالي للتحقق من الجاهزية وطباعة القيم المقترحة:

```bash
cd /opt/aman
./scripts/ops/rotate_secrets_checklist.sh
```

مخرجات السكربت:
1. يتحقق من المفاتيح الأساسية في `backend/.env`.
2. يتحقق من وجود `SECRET_KEY` ضعيف/افتراضي.
3. يطبع قيم قوية مقترحة لتدوير `SECRET_KEY` وكلمات المرور.
4. يوضح أهداف التدوير (GitHub Secrets + server env + providers).
5. يطبع أوامر تحقق ما بعد التدوير.

### 11.2 Smoke Regression لمسارات `O2C/P2P`

بعد التدوير أو أي تعديل حساس، نفذ:

```bash
cd /opt/aman
export AMAN_BASE_URL=http://localhost:8000
export AMAN_TOKEN=<fresh_bearer_token>
export AMAN_CUSTOMER_ID=1
export AMAN_SUPPLIER_ID=1
export AMAN_PRODUCT_ID=1
/home/omar/Desktop/aman/.venv/bin/python backend/scripts/smoke_o2c_p2p.py
```

نتيجة النجاح المتوقعة:
1. نجاح `auth/me`.
2. نجاح إنشاء order + sales invoice في `O2C`.
3. نجاح إنشاء purchase invoice في `P2P`.
4. رفض محاولة overpayment في `P2P` (كود `400/422`).

### 11.3 قرار الاستعداد

لا يتم اعتماد الجاهزية النهائية إلا بعد:
1. تنفيذ تدوير الأسرار فعليا.
2. نجاح smoke regression بدون أعطال حرجة.
3. تثبيت أن CI يمر عبر secret-scan gate.

### 11.4 إعدادات DNS للبريد الصادر

قبل تفعيل SMTP إنتاجي لأي نطاق مرسل، يجب توثيق وتأكيد سجلات DNS التالية مع مزود البريد:

| السجل | القيمة المطلوبة |
|-------|-----------------|
| SPF | سجل TXT على النطاق المرسل يصرح بخوادم SMTP الفعلية، مثل `v=spf1 include:<provider> -all`. |
| DKIM | مفتاح DKIM عام لكل selector مستخدم، مع تدوير عند تغيير مزود البريد أو مفتاح التوقيع. |
| DMARC | سجل TXT يبدأ بسياسة مراقبة `p=none` ثم ينتقل إلى `quarantine` أو `reject` بعد مراجعة التقارير. |

تحقق التشغيل: أرسل رسالة اختبار إلى صندوق خارجي، ثم راجع headers للتأكد من `spf=pass`, `dkim=pass`, `dmarc=pass`. عند فشل أي سجل، أوقف إرسال الحملات bulk حتى يتم تصحيح DNS.

## 12. Audit Outbox Worker Recovery (022)

The audit outbox pattern writes audit events to `audit_outbox` within the
same transaction as the business operation. A dedicated worker flushes
rows to `audit_logs` asynchronously.

### If the worker stops

```bash
# 1. Check worker process
docker compose ps worker

# 2. Check outbox lag
psql -U aman -d aman_<company_id> -c "
  SELECT COUNT(*) AS pending, 
         EXTRACT(EPOCH FROM NOW() - MIN(created_at))::int AS oldest_age_sec
  FROM audit_outbox WHERE flushed_at IS NULL;"

# 3. Restart worker
docker compose restart worker

# 4. If backlog is large (>10k rows), increase batch size temporarily
# Set AUDIT_OUTBOX_BATCH=500 in worker env, restart, then reset to default.
```

### If outbox table grows unbounded

```bash
# Check table size
psql -U aman -d aman_<company_id> -c "
  SELECT pg_size_pretty(pg_total_relation_size('audit_outbox'));"

# Purge flushed rows older than 7 days
psql -U aman -d aman_<company_id> -c "
  DELETE FROM audit_outbox WHERE flushed_at < NOW() - INTERVAL '7 days';"
```

---

## 13. Reconciliation Drift Report Interpretation (022)

When `POST /reconciliation/{id}/finalize` returns **HTTP 409**, the response
body contains a structured drift report:

```json
{
  "error": "reconciliation_drift",
  "gl_total": 150000.00,
  "bank_total": 149500.00,
  "difference": 500.00,
  "tolerance": 1.00,
  "unmatched_lines": [
    {"id": 42, "description": "Wire transfer", "amount": 500.00}
  ]
}
```

### Interpretation

| Field | Meaning |
|-------|---------|
| `gl_total` | Sum of reconciled lines (credits - debits) + opening balance |
| `bank_total` | The end balance entered from the bank statement |
| `difference` | `abs(gl_total - bank_total)` |
| `tolerance` | Max allowed difference from `company_settings.reconciliation_tolerance` |
| `unmatched_lines` | Statement lines not yet matched to GL entries |

### Resolution steps

1. **Difference > tolerance**: Check `unmatched_lines` — likely a missing match.
2. **Difference within tolerance but still 409**: Tolerance setting may be too tight.
   Update via `PUT /api/settings` with key `reconciliation_tolerance`.
3. **Force finalize**: If management approves, use the force-override button in the
   admin UI (requires `finance.reconciliation.finalize` sensitive permission).

---

## 14. Credential Rotation Playbook (022)

Integration credentials are stored in `integration_credentials` with envelope
encryption. Rotation is triggered via admin UI or API.

### Rotate a credential

```bash
# Via API
curl -X POST http://localhost:8000/api/admin/credentials/{id}/rotate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_secret": "new-value-here"}'
```

### Check credential health

```bash
psql -U aman -d aman_<company_id> -c "
  SELECT id, integration, name, status, consecutive_failures, 
         last_rotated_at, expires_at
  FROM integration_credentials 
  WHERE status != 'soft_deleted'
  ORDER BY consecutive_failures DESC;"
```

### Alert on failures

Credentials with `consecutive_failures >= 3` trigger a notification.
Check `notifications` table for `credential_failure` type alerts.

### Soft-delete vs hard-delete

- **Soft-delete**: Sets `status='soft_deleted'`, preserves encrypted secret for audit.
- **Restore**: `POST /api/admin/credentials/{id}/restore` reactivates.
- **Hard-delete**: Only via direct DB after compliance review. Not exposed in API.

---

## 15. Treasury Trigger Bypass for Migrations (022)

A DB trigger on `treasury_accounts` blocks direct `UPDATE current_balance`
unless the session has `aman.gl_context = 'on'` GUC set.

### Legitimate bypass paths

- `gl_service.create_journal_entry()` — sets GUC automatically
- `utils/treasury_balance.py` — sets GUC before UPDATE
- `scripts/reconcile_balances.py` — sets GUC in fix path

### If a migration needs to update balances

```sql
-- Set the GUC before your UPDATE
SELECT set_config('aman.gl_context', 'on', true);

UPDATE treasury_accounts SET current_balance = :new_balance WHERE id = :id;
```

### If the trigger blocks a legitimate operation

Check if the caller sets the GUC:
```bash
grep -rn "aman.gl_context" backend/
```

If missing, add `db.execute(text("SELECT set_config('aman.gl_context', 'on', true)"))`
before the UPDATE statement.

---

## 16. Sensitive Permission Discovery (022)

The `require_sensitive_permission` decorator enforces critical permissions on
finance/PII endpoints. A discovery script audits coverage.

### Run discovery

```bash
cd /home/omar/Desktop/aman/backend
python -m scripts.permissions_discover --strict
```

### Output interpretation

- **OK**: All routes with `require_sensitive_permission` have matching permission
  definitions in the role system.
- **FAIL**: Some routes reference permissions not in the role definitions. 
  Add the missing permissions to `backend/data/default_roles.json` or the
  permission seed migration.

### Adding a new sensitive endpoint

```python
from services.permissions.sensitive import require_sensitive_permission

@router.post("/my-endpoint", dependencies=[
    Depends(require_sensitive_permission("module.action", critical=True))
])
```

The `critical=True` flag ensures the action is logged even if the outbox
worker is delayed.

---

## ملحق: أوامر مفيدة

```bash
# عدد المستخدمين النشطين
psql -U aman -d aman_<company_id> -c "SELECT count(*) FROM company_users WHERE is_active = true;"

# آخر عمليات تسجيل دخول
psql -U aman -d postgres -c "SELECT * FROM system_activity_log WHERE action_type = 'login' ORDER BY created_at DESC LIMIT 10;"

# إحصائيات API
curl -s http://localhost:8000/metrics | grep http_requests_total | head -20

# حجم الملفات المرفوعة
du -sh /opt/aman/backend/uploads/

# استهلاك الحاويات
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

## Webhook DLQ + e-invoice outbox relay

Both webhooks and the e-invoice outbox use the same retry pattern:

* On failure the row is left in the source table with `attempts++`.
* The retry worker (`backend/services/scheduler.py::retry_failed_notifications`
  for webhooks; the on-demand `/api/finance/accounting-depth/einvoice/outbox/relay`
  endpoint for invoices) waits an exponential backoff of `min(2^attempts, WEBHOOK_RETRY_BACKOFF_CAP_SEC)` seconds.
* After **6 attempts** the row is moved to the DLQ status (`webhook_dlq` table
  for webhooks, `einvoice_outbox.status='giveup'` for invoices) and stops being
  retried automatically.

### Manual replay

```bash
# Webhook DLQ replay (drain N rows back to pending)
psql -U aman -d aman_<company_id> -c \
  "UPDATE webhook_dlq SET status='pending', attempts=0 \
   WHERE id IN (SELECT id FROM webhook_dlq WHERE status='giveup' ORDER BY id LIMIT 50);"

# E-invoice outbox replay
psql -U aman -d aman_<company_id> -c \
  "UPDATE einvoice_outbox SET status='pending', attempts=0 \
   WHERE id IN (SELECT id FROM einvoice_outbox WHERE status='giveup' ORDER BY id LIMIT 50);"

# Trigger an immediate relay sweep
curl -sS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/finance/accounting-depth/einvoice/outbox/relay \
  -d '{"limit": 100}' -H 'Content-Type: application/json'
```

### Tunables

| Variable | Default | Notes |
|---|---|---|
| `WEBHOOK_RETRY_BACKOFF_CAP_SEC` | `300` | upper bound for exponential backoff |
| `WEBHOOK_RETRY_MAX_ATTEMPTS` | `6` | move to DLQ after this many tries |
| `EINVOICE_OUTBOX_BATCH` | `50` | rows processed per relay invocation |

### Monitoring

* Prometheus alert: `WebhookDLQGrowth` fires when `webhook_dlq` count grows by > 10 in 1h.
* Same alert pattern recommended for `einvoice_outbox` (status='giveup').
* Dashboard panel: "Outbox lag" — `MAX(EXTRACT(EPOCH FROM NOW() - created_at))` for `pending` rows.

## Hybrid Local Development (Postgres native + Redis Docker)

For day-to-day development we run the database on the host and only put Redis
in a container. This avoids the slow file-system overhead of bind-mounting the
entire repo into the backend container while still giving us a clean Redis.

### One-time setup

```bash
# 1. PostgreSQL (Debian/Ubuntu)
sudo apt-get install -y postgresql postgresql-contrib
sudo -u postgres createuser --superuser aman
sudo -u postgres createdb -O aman aman_main

# 2. Redis as a container
docker run -d --name aman_redis -p 127.0.0.1:6379:6379 redis:7-alpine
```

### Daily startup

```bash
# 1. Activate the venv
source .venv/bin/activate

# 2. Export env vars (or use .env)
export DATABASE_URL=postgresql://aman@localhost:5432/aman_main
export REDIS_URL=redis://localhost:6379/0
export ENABLE_QUERY_COUNTER=1            # optional N+1 observer

# 3. Apply migrations
cd backend && alembic upgrade head && cd ..

# 4. Run backend + frontend
./safe-start.sh                          # uses logs/*.pid
```

### Toggling between hybrid and full-Docker

* Hybrid: `docker compose up -d redis` then `./safe-start.sh`.
* Full stack: `docker compose up -d` (uses bundled Postgres + Redis).
* Stop hybrid: `./safe-stop.sh && docker stop aman_redis`.

## Backup & Restore Policy

Backups live under `/var/backups/aman/` on the production host and are
written by `scripts/backup_postgres.sh` (system DB + every tenant DB).

### Schedule (cron)

```
# /etc/cron.d/aman-backup
30 2 * * *   aman   /opt/aman/scripts/backup_postgres.sh daily
0  3 * * 0   aman   /opt/aman/scripts/backup_postgres.sh weekly
0  4 1 * *   aman   /opt/aman/scripts/backup_postgres.sh monthly
```

### Retention

| Tier    | Keep on disk | Off-site copy |
|---------|--------------|---------------|
| daily   | 14 days      | last 7 mirrored to S3 nightly |
| weekly  | 8 weeks      | mirrored to S3 weekly         |
| monthly | 12 months    | mirrored to S3 monthly        |

Pruning is part of `backup_postgres.sh` (uses `find -mtime`). S3 lifecycle
rules enforce the off-site retention as a second line of defence.

### Restore drill

```bash
# Restore the latest daily snapshot of company DB c_42
sudo -u postgres /opt/aman/scripts/restore_postgres.sh \
    --target c_42 --from /var/backups/aman/daily/$(ls -1 /var/backups/aman/daily | tail -1)
```

A full restore drill MUST be executed every quarter against staging and the
result logged in `docs/audit/` with the start/finish timestamps and the row
counts of the top 10 tables before/after restore (sanity check).

### Verification

* Each snapshot is followed by `pg_restore -l` to confirm the dump is readable.
* Nightly checksum (sha256) is appended to `/var/backups/aman/CHECKSUMS`.
* Prometheus alert `BackupOlderThan26h` fires when the newest daily file is
  more than 26 hours old.

---

## Encryption Key Rotation (T9.5)

`FIELD_ENCRYPTION_KEY` is used by `backend/utils/encryption.py` to encrypt
sensitive fields at rest (CSID secrets, payment tokens, PII columns flagged
in `models/`). Rotation procedure:

1. Generate a new key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Append the new key to `FIELD_ENCRYPTION_KEYS` (comma-separated list — old
   keys remain for decryption only). Set `FIELD_ENCRYPTION_KEY` (singular) to
   the new value so all NEW writes use it.
3. Restart backend + worker (`./safe-stop.sh && ./safe-start.sh`).
4. Run the re-encryption job (off-hours):
   ```bash
   docker exec aman_backend python -m scripts.rotate_field_encryption \
       --batch-size 500
   ```
5. Once all rows are re-encrypted, drop the old key from `FIELD_ENCRYPTION_KEYS`
   on the next deploy.

Rotation cadence: yearly OR immediately after a suspected key compromise.

## ZATCA Phase 2 / CSID Setup (T9.5)

CSIDs (Cryptographic Stamp Identifiers) are stored encrypted in
`zatca_csids` (per branch). To onboard a new branch:

1. Submit CSR via `POST /api/zatca/csids/request` (returns sandbox CSID).
2. Validate against ZATCA sandbox: `POST /api/zatca/invoices/validate`.
3. Promote to production: `POST /api/zatca/csids/{id}/promote-prod`.
4. Verify reporting works: tail `worker` logs for `zatca_report` job.

See `backend/integrations/einvoicing/` for the underlying client.

## Scheduler / Worker Process (T9.5)

The system runs a single dedicated APScheduler process to avoid duplicate
job execution across uvicorn workers. Configure via:

```bash
# In .env / docker-compose.prod.yml — exactly ONE process per cluster
SCHEDULER_MODE=dedicated
```

Start the worker:

```bash
python -m worker        # or: docker compose up worker
```

Key recurring jobs (see `backend/services/scheduler.py`):

| Job ID                  | Schedule                | Purpose |
|-------------------------|-------------------------|---------|
| `audit_archival`        | every 24h               | Soft-archive >1y, MOVE >7y to `audit_logs_archive` (T9.3) |
| `inventory_archival`    | monthly, 1st @ 03:00    | MOVE inventory_transactions >7y to archive table (T9.3) |
| `gl_close_period`       | monthly                 | Auto-close prior period if reconciled |
| `recurring_invoices`    | hourly                  | Generate scheduled invoices |
| `zatca_report`          | every 5 min             | Report queued invoices to ZATCA |
| `bank_feed_sync`        | every 30 min            | Pull bank statements via integrations |

If you need to disable scheduling temporarily, set `SCHEDULER_ENABLED=false`
on the worker process.

## Recently Added Endpoints (Phase 8 / 9)

* `GET /api/search` — unified full-text search across products / customers / suppliers / invoices.
* `GET /api/currencies/current` — convenience endpoint exposing today's exchange rate.
* `POST /api/hr/overtime-rates-config` — admin-only configuration of overtime multipliers.
* `GET /api/parties/duplicates-by-phone` — duplicate-detection helper.
* Archive tables: `audit_logs_archive`, `inventory_transactions_archive` (T9.3).

## Bilingual Error Responses (T9.4)

The frontend `apiClient.js` injects `Accept-Language: <lang>` on every
request. Backend `AcceptLanguageMiddleware` stores the value on
`request.state.lang`, and `utils/i18n.http_error()` resolves messages from
`backend/locales/errors.{ar,en}.json`. To add a new key:

1. Add to BOTH `errors.en.json` and `errors.ar.json`.
2. Use `raise HTTPException(**http_error(404, "my_key", lang=request.state.lang))`.

---

## Feature 023 — Worker Operations

### ZATCA Outbox Worker (`worker.zatca_outbox`)

- **Interval**: 5 seconds, batch size 25
- **Health**: Check `zatca_outbox` table for rows stuck in `processing` state > 5 minutes
- **Dead letter**: Rows with `state='dead_letter'` need manual reprocess via `POST /einvoicing/outbox/{id}/reprocess`
- **Expected lag**: < 30 seconds from invoice post to ZATCA submission
- **Alert**: > 100 rows in `pending` state for > 5 minutes

### POS Offline Reconciler (`worker.pos_offline_reconciler`)

- **Interval**: 10 seconds, batch size 50
- **Health**: Check `pos_offline_batches` for rows in `reconciling` state > 2 minutes
- **Manual review**: Rows with `state='manual_review'` need human triage
- **Failure codes**: `out_of_stock`, `closed_period`, `state_machine_violation`, `pricing_mismatch`, `stale_batch`

### Auto-Reorder (`worker.auto_reorder`)

- **Interval**: 60 minutes (configurable via `inventory.auto_reorder_interval_minutes`)
- **Health**: Check `mrp_recommendations` for `source='auto_reorder'` rows created in last run
- **Lock**: Per-tenant advisory lock prevents concurrent runs
- **Performance target**: 5000 pairs ≤ 30 seconds

### Inventory Archiver (`worker.inventory_archiver`)

- **Schedule**: Daily at 03:00 UTC
- **Health**: Check `inventory_transactions_archive` row count growth
- **Retention**: Configurable via `inventory.retention_days` (default 365)
- **Performance**: Batches of 5000, brief pause between batches
- **Alert**: If `inventory_transactions` grows beyond 10M rows

### MRP Scheduler (`worker.mrp`)

- **Interval**: Configurable via `mfg.mrp_interval_minutes` (default 60)
- **Health**: Check `mrp_recommendations` for recent `run_id`
- **Lock**: Per-tenant advisory lock prevents concurrent runs
- **Performance target**: 10000 items ≤ 5 minutes
- **Cycle detection**: BOM cycles raise `BomCycleError` with path

---

## Feature 023 — Troubleshooting

### Invoice State Machine

- **StaleInvoiceState**: Concurrent modification detected. Retry the operation.
- **InvalidInvoiceTransition**: State transition not allowed. Check `LEGAL_TRANSITIONS` in `invoice_state.py`.

### POS Stock Lock

- **PosLockTimeout**: Could not acquire lock within 5 seconds. Check Redis connectivity.
- **Fallback**: If Redis unavailable, falls back to `pg_advisory_xact_lock`.

### ZATCA Signing

- **SignerCredentialsMissing**: ZATCA credentials not configured in vault for this tenant.
- **SignerCryptoError**: Certificate/key mismatch or expiration. Check vault entries.

### MRP Cycles

- **BomCycleError**: BOM has circular dependency. Fix BOM structure before re-running MRP.
