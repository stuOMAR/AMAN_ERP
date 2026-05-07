# ملخص جلسة العمل - AMAN ERP

## 1. إنشاء ملفات Playwright للاختبارات E2E

**الملفات المُنشأة:**
- `tests/playwright.config.ts` — إعدادات Playwright
- `tests/fixtures/api-client.ts` — أدوات API مساعدة
- `tests/fixtures/scenarios.ts` — بيانات السيناريوهات
- `tests/seed/seed.spec.ts` — اختبار تعبئة البيانات
- `tests/specs/auth.spec.ts` — اختبارات المصادقة
- `tests/specs/branches.spec.ts` — اختبارات الفروع
- `tests/specs/currencies.spec.ts` — اختبارات العملات
- `tests/specs/permissions.spec.ts` — اختبارات الصلاحيات
- `tests/specs/financial.spec.ts` — اختبارات مالية
- `tests/specs/inventory.spec.ts` — اختبارات المخزون
- `tests/specs/hr.spec.ts` — اختبارات الموارد البشرية
- `tests/specs/isolation.spec.ts` — اختبارات عزل الفروع

---

## 2. خطة اختبارات شاملة

**المُنشأ:** `docs/test-plan.md`

تغطي 8 مراحل:
1. Seed (تعبئة البيانات)
2. Auth & Security (المصادقة)
3. Branches & Currencies (الفروع والعملات)
4. Permissions (الصلاحيات)
5. Financial Transactions (المعاملات المالية)
6. Inventory (المخزون)
7. HR (الموارد البشرية)
8. Cross-Branch Isolation (عزل الفروع)

---

## 3. سكريبتات تعبئة البيانات

**المُنشأة:**
- `scripts/seed.py` — تعبئة البيانات الرئيسية (فروع، عملات، حسابات، موظفين، منتجات، عملاء)
- `scripts/seed-transactions.py` — تعبئة المعاملات (مشتريات، مبيعات، مخزون، مالية، HR، تصنيع، POS، مشاريع)
- `scripts/cleanup.py` — تنظيف البيانات (يحذف المعاملات ويُصفّر أرصدة الحسابات)

---

## 4. إصلاحات Backend جذرية

### تحويل العملات
| الملف | الإصلاح |
|-------|---------|
| `routers/finance/accounting/accounts.py` | SQL query يُحوّل balance باستخدام exchange_rate |
| `routers/finance/treasury.py` | لا يُطبق سعر الصرف مرتين |
| `routers/reports/accounting_statements.py` | trial balance يُحوّل العملات صحيحاً |
| `utils/accounting.py` | `compute_line_amounts` يدعم fixed و percentage discount |

### إنشاء حسابات رأس المال تلقائياً
| الملف | الإصلاح |
|-------|---------|
| `routers/finance/currencies.py` | يُنشئ حساب رأس المال عند إنشاء عملة جديدة |
| `routers/finance/treasury.py` | يُنشئ حساب رأس المال عند إنشاء خزينة بعملة جديدة |

### إصلاحات الخزائن
| المشكلة | الإصلاح |
|---------|---------|
| sequence متعارض | يُعيّن max(id)+1 |
| حساب مكرر | يتخطى إذا كان موجوداً |
| كود مكرر | يتحقق من عدم التكرار قبل الإنشاء |

### إصلاحات الموظفين
| المشكلة | الإصلاح |
|---------|---------|
| sequence متعارض | يُصلح قبل الإنشاء |
| username مكرر | يتحقق من الوجود أولاً |

---

## 5. إصلاحات Frontend

### Hook جديد
**المُنشأ:** `frontend/src/hooks/useInvoiceCalc.js`

يُرسل البيانات للـ backend ويُرجع النتائج المحسوبة.

### Endpoint عام للحسابات
**المُنشأ:** `backend/routers/calculator.py`

- `POST /api/calculate/invoice-totals` — حساب إجماليات أي فاتورة
- `POST /api/calculate/contract-totals` — حساب إجماليات العقود

### Preview Endpoints
| Endpoint | الوصف |
|----------|-------|
| `POST /api/sales/invoices/preview` | حساب إجماليات فاتورة مبيعات |
| `POST /api/buying/invoices/preview` | حساب إجماليات فاتورة مشتريات |

### الصفحات المُحدّثة (12 صفحة)
| الصفحة | التغيير |
|--------|---------|
| `SalesInvoiceForm.jsx` | استبدال `getTotals()` بـ hook |
| `SalesQuotationForm.jsx` | استبدال `calculateTotals()` بـ hook |
| `SalesOrderForm.jsx` | استبدال `calculateTotals()` بـ hook |
| `SalesReturnForm.jsx` | إضافة hook |
| `SalesCreditNotes.jsx` | إضافة hook |
| `SalesDebitNotes.jsx` | إضافة hook |
| `ContractForm.jsx` | استبدال `getTotals()` بـ hook |
| `PurchaseInvoiceForm.jsx` | استبدال `calculateTotals()` بـ hook |
| `BuyingOrderForm.jsx` | استبدال `calculateTotals()` بـ hook |
| `BuyingReturnForm.jsx` | إضافة hook |
| `PurchaseCreditNotes.jsx` | إضافة hook |
| `PurchaseDebitNotes.jsx` | إضافة hook |

---

## 6. إصلاحات قاعدة البيانات

| المشكلة | الإصلاح |
|---------|---------|
| `audit_outbox` sequence | يُصلح قبل كل عملية |
| `company_users` sequence | يُعيّن max(id)+1 |
| `journal_entries` sequence | يُصلح |
| `accounts` sequence | يُعيّن max(id)+1 (لا يُحذف) |
| `fiscal_years` | يُنشأ تلقائياً |
| `fiscal_periods` | يُنشأ 12 فترة تلقائياً |

---

## 7. شجرة الحسابات الجديدة

```
حقوق الملكية (3000) 📂
└── رأس المال (31) 📂
    ├── رأس المال - ريال سعودي (3101) 📄 SAR
    ├── رأس المال - جنيه مصري (3102) 📄 EGP
    ├── رأس المال - درهم إماراتي (3103) 📄 AED
    ├── رأس المال - دولار أمريكي (3104) 📄 USD
    └── رأس المال - جنيه إنجليزي (3105) 📄 GBP
```

---

## 8. القاعدة الذهبية

```
debit/credit = المبلغ بالعملة الأصلية
exchange_rate = سعر التحويل لعملة التقارير
debit_base = debit × exchange_rate (يُخزن في DB)
amount_currency = المبلغ بالعملة الأصلية (يُخزن في DB)
currency = رمز العملة الأصلية (يُخزن في DB)
```

---

## 9. القيم المالية الصحيحة

```
الحساب                    | العملة | SAR        | الأصلية
─────────────────────────────────────────────────────────
صندوق الرياض              | SAR    |    25,000  |    25,000
بنك القاهرة               | EGP    |    22,800  |   300,000
بنك دبي                   | AED    |   224,620  |   220,000
صندوق القاهرة             | EGP    |     3,800  |    50,000
رأس المال - ريال سعودي    | SAR    |    25,000  |    25,000
رأس المال - جنيه مصري     | EGP    |    26,600  |   350,000
رأس المال - درهم إماراتي  | AED    |   224,620  |   220,000
─────────────────────────────────────────────────────────
المجموع                   |        |   276,220  |   276,220 ✓
```

---

## 10. الأوامر المفيدة

```bash
# تنظيف البيانات (يحافظ على الحسابات)
python scripts/cleanup.py --company-code 9d08756c --confirm

# تعبئة البيانات الرئيسية
python scripts/seed.py --company-code 9d08756c

# تعبئة المعاملات
python scripts/seed-transactions.py --company-code 9d08756c

# تشغيل اختبارات Playwright
cd tests && npx playwright test
```

---

## 11. الـ Endpoints التي تعمل

| Endpoint | Method | الحالة |
|----------|--------|--------|
| `/api/accounting/currencies/` | GET/POST | ✓ |
| `/api/branches/` | GET/POST | ✓ |
| `/api/accounting/accounts` | GET/POST | ✓ |
| `/api/treasury/accounts` | GET/POST | ✓ |
| `/api/hr/departments` | GET/POST | ✓ |
| `/api/inventory/warehouses` | GET/POST | ✓ |
| `/api/inventory/products` | GET/POST | ✓ |
| `/api/sales/customers` | POST | ✓ |
| `/api/parties/customers` | GET | ✓ |
| `/api/inventory/suppliers` | POST | ✓ |
| `/api/parties/suppliers` | GET | ✓ |
| `/api/hr/employees` | GET/POST | ✓ |
| `/api/calculate/invoice-totals` | POST | ✓ |
| `/api/sales/invoices/preview` | POST | ✓ |
| `/api/buying/invoices/preview` | POST | ✓ |

---

## 12. الحالة النهائية للبيانات

```
البيانات          | العدد
───────────────────────────
الحسابات          |    27
الخزائن            |     4
الموظفين          |    11
المنتجات          |     3
الفروع            |     4
العملات            |     5
```
