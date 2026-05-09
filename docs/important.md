# قواعد وسياسات النظام - AMAN ERP

## 1. فلترة الفروع (Branch Filtering) - القاعدة الأساسية

كل صفحات النظام تخضع لفلترة الفروع **عدا** الصفحات التي تحتوي بيانات مشتركة مثل:
- العملات (Currencies)
- أسعار صرف العملات (Exchange Rates)
- الإعدادات العامة على مستوى الشركة

### 1.1 آلية فلترة الفروع (Branch Scope)

**الملف الأساسي:** `backend/utils/permissions.py`

```python
# دالة حل نطاق الفروع - تحدد الفروع المسموح بها للمستخدم
resolve_branch_scope(current_user, requested_branch_id)
# ترجع: {"branch_id": int | None, "branch_ids": list | None}

# دالة بناء فلتر SQL من نطاق الفروع
branch_scope_filter_from_scope(scope, alias="t")
# ترجع: "AND t.branch_id = :branch_id" أو "AND t.branch_id = ANY(:branch_ids)"

# دالة مجمعة
branch_scope_filter(current_user, requested_branch_id, alias="t")
# ترجع: (scope_dict, sql_fragment, params)
```

### 1.2 مستويات الفلترة حسب الدور

| الدور | سلوك الفلترة |
|-------|-------------|
| **مستخدم عادي** | يرى بيانات فرع واحد فقط (فرعه) |
| **مدير / مشرف** | يرى كل الفروع المخصصة له، أو يختار فلترة بفرع محدد |
| **مدير النظام (system_admin)** | يرى كل الفروع بدون قيود |

### 1.3 سلوك "كل الفروع"

عندما يختار المستخدم "كل الفروع":
- **البيانات الكمية**: يتم جمع (SUM/COUNT) البيانات من كل الفروع
- **العملات**: تظهر البيانات بعملة موحدة مع مراعاة صرف العملات وصحة الأرصدة
- **يجب أن يكون الرصيد صحيحاً** بعد توحيد العملات

### 1.4 الصفحات التي تطبق فلترة الفروع

**تقارير:**
- لوحة التحكم (Dashboard): `routers/dashboard.py` - فلترة على `branch_id` في الفواتير، نقاط البيع، القيود، المستودعات
- تحليل المحاسبة: `routers/reports/accounting_analysis.py` - دالة `_scoped_branch_filter()`
- كشوفات المحاسبة: `routers/reports/accounting_statements.py` - دالة `_scoped_branch_filter()`
- مقارنة وتصدير المحاسبة: `routers/reports/accounting_compare_export.py`
- تقارير المبيعات: `routers/reports/sales.py`
- تقارير المشتريات: `routers/reports/purchases.py`
- تقارير الموارد البشرية: `routers/reports/hr.py`
- تقارير المخزون: `routers/inventory/reports.py`

**المبيعات:**
- الفواتير: `routers/sales/invoices.py`
- إشعارات الدائن: `routers/sales/credit_notes.py`
- عروض الأسعار: `routers/sales/quotations.py`
- الطلبات: `routers/sales/orders.py`
- العملاء: `routers/sales/customers.py`
- السندات: `routers/sales/vouchers.py`
- المرتجعات: `routers/sales/returns.py`

**المشتريات:**
- المدفوعات: `routers/purchases/payments.py`
- الطلبات الشاملة: `routers/purchases/blanket.py`
- الطلبات: `routers/purchases/orders.py`
- الموردين: `routers/purchases/suppliers.py`
- المرتجعات: `routers/purchases/returns.py`

**المخزون:**
- المنتجات: `routers/inventory/products.py` + `repositories/product_repo.py`
- قوائم الأسعار: `routers/inventory/price_lists.py`
- المستودعات: `routers/inventory/warehouses.py`
- الشحنات: `routers/inventory/shipments.py`
- تقارير التقييم: `routers/inventory/reports.py`

**المالية:**
- قيود اليومية: `routers/finance/accounting/journal.py`
- الشيكات: `routers/finance/checks.py`
- الأوراق المالية: `routers/finance/notes.py`
- التدفقات النقدية: `routers/finance/cashflow.py`
- الميزانيات: `routers/finance/budgets.py`
- العهدة النثرية: `routers/finance/petty_cash.py`
- التسويات البنكية: `routers/finance/reconciliation.py`
- الخزينة: `routers/finance/treasury.py`
- العمليات البينية: `routers/finance/intercompany_v2.py`
- الاشتراكات: `routers/finance/subscriptions.py`
- الاعتراف بالإيراد: `routers/finance/revenue_recognition.py`
- الامتثال الضريبي: `routers/finance/tax_compliance.py`

**نقاط البيع:**
- الطلبات: `routers/pos/orders.py`

**المشاريع:**
- المشاريع: `routers/projects/core.py`

**إدارة علاقات العملاء:**
- الحملات: `routers/crm/campaigns.py`
- الفرص: `routers/crm/opportunities.py`

**أخرى:**
- العقود: `routers/contracts.py`
- أوامر التسليم: `routers/delivery_orders.py`
- التكاليف الأرضية: `routers/landed_costs.py`
- التدقيق: `routers/audit.py`
- التقارير المجدولة: `routers/scheduled_reports.py`
- المطابقات: `routers/matching.py`

---

## 2. سياسة عرض العملات وأسعار الصرف

عند عرض بيانات متعددة الفروع:
1. يجب عرض العملة الأساسية للفرع مع كل بيان
2. عند اختيار "كل الفروع"، يتم توحيد المبالغ بعملة واحدة مع الحفاظ على صحة الرصيد
3. كل فرع له عملته الافتراضية (`default_currency`)
4. تعرض العملة في الكروت والجداول بشكل واضح

**آلية حساب أسعار الصرف الموحدة:**
- في التقارير المالية المجمعة: تحويل كل مبلغ من عملة الفرع إلى العملة الموحدة
- في قوائم الأسعار: كل قائمة أسعار مرتبطة بعملة وفرع محدد (`price_lists` → `currency`, `branch_id`)

---

## 3. سياسات التصفية حسب النوع والحالة (Status / Type Filtering)

### 3.1 الحالات القياسية (Standard Status Values)

تستخدم معظم الكيانات قيم موحدة للحالة:
- `active` / `inactive` - نشط / متوقف
- `draft` / `posted` / `void` - مسودة / مرحل / ملغي
- `pending` / `confirmed` / `completed` / `cancelled` - معلق / مؤكد / مكتمل / ملغي

### 3.2 تصفية حسب النوع (Type Filtering)

| الصفحة | أنواع التصفية |
|--------|-------------|
| المنتجات | `goods` (سلع) / `service` (خدمات) |
| حسابات الخزينة | أنواع الحسابات (بنك، صندوق، استثمار...) |
| التسويات | تصفية حسب الحالة |
| الفواتير | `invoice` / `bill` / `pos_receipt` |
| الإشعارات | `state`: pending/sending/sent/failed/dlq + `channel`: email/sms/push/in_app/webhook |

### 3.3 تصفية حسب التاريخ

معظم القوائم تدعم:
- `date_from` / `date_to`
- `period`: today/wtd/mtd/qtd/ytd/last_month/last_quarter (في KPIs)
- دالة `resolve_period()` في `services/kpi_service/common.py`

---

## 4. سياسات الوحدات (Module & Industry-Based Filtering)

### 4.1 آلية تفعيل الوحدات

**الواجهة:** `frontend/src/config/industryModules.js`
**الخادم:** `backend/utils/permissions.py` → `require_module()`

### 4.2 الوحدات الدائمة (Always Enabled - 23 وحدة)
`dashboard`, `kpi`, `accounting`, `assets`, `treasury`, `sales`, `buying`, `crm`, `expenses`, `taxes`, `approvals`, `reports`, `hr`, `audit`, `roles`, `settings`, `data_import`, `sso`, `analytics`, `performance`, `cashflow`, `campaigns`, `subscriptions`

### 4.3 الوحدات المتغيرة (Variable Modules - 10 وحدات)
`pos`, `stock`, `manufacturing`, `projects`, `services`, `matching`, `intercompany`, `cpq`, `forecast`, `shop_floor`

### 4.4 الأنشطة التجارية المدعومة (12 نشاط)

| الرمز | النشاط | الوحدات الإضافية |
|-------|--------|-----------------|
| RT | تجارة التجزئة | pos |
| WS | الجملة والتوزيع | matching, intercompany |
| FB | المطاعم والمقاهي | pos |
| MF | التصنيع | pos, manufacturing, projects, services, shop_floor, cpq |
| CN | المقاولات | projects, services, matching, intercompany |
| SV | الخدمات | services, projects |
| PH | الصيدليات | pos |
| WK | الورش والصيانة | pos, services |
| EC | التجارة الإلكترونية | cpq |
| LG | النقل واللوجستيات | services, matching, intercompany |
| AG | الزراعة | (الأساسية فقط) |
| GN | نشاط عام | الكل |

### 4.5 أولويات تحديد الوحدات المفعلة
1. **الأولوية الأولى**: `enabled_modules` من الباك إند (قائمة مخصصة)
2. **الأولوية الثانية**: مصفوفة النشاط التجاري (الافتراضي لكل نشاط)
3. **الأولوية الثالثة**: إذا لم يُحدد شيء → إظهار كل الوحدات

---

## 5. سياسات الصلاحيات المتقدمة (Advanced Permission Policies)

### 5.1 PERM-001: تنقية الحقول (Field Filtering)

**الموقع:** `backend/utils/permissions.py` → `filter_fields()`

يتم إخفاء الحقول الحساسة حسب الدور:
- **أدوار مقيدة**: إخفاء `cost`, `price`, `salary`, `margin`, `profit`
- **الحقول المخفية افتراضياً لكل نوع مورد:**

| نوع المورد | الحقول المخفية للأدوار المقيدة |
|-----------|------------------------------|
| `product` | `cost`, `supplier_price`, `margin`, `markup` |
| `invoice` | `cost_total`, `profit`, `margin` |
| `employee` | `salary`, `basic_salary`, `housing_allowance`, `transportation_allowance` |
| `project` | `budget`, `actual_cost`, `profit` |
| `journal` | `debit`, `credit` (في بعض الحالات) |

### 5.2 PERM-002: فلترة المستودعات (Warehouse Filtering)

**الموقع:** `backend/utils/permissions.py` → `build_warehouse_filter()`

المستخدمين المقيدين بمستودعات محددة يرون فقط:
- المخزون في المستودعات المسموح بها
- الحركات المخزنية المرتبطة بتلك المستودعات

### 5.3 PERM-003: فلترة مراكز التكلفة (Cost Center Filtering)

**الموقع:** `backend/utils/permissions.py` → `build_cost_center_filter()`

المستخدمين المقيدين بمراكز تكلفة محددة يرون فقط:
- المعاملات المرتبطة بمراكز التكلفة المسموح بها

### 5.4 أسماء مستعارة للصلاحيات (Permission Aliases)

**الموقع:** `backend/utils/permissions.py` → `PERMISSION_ALIASES`

```python
PERMISSION_ALIASES = {
    "products.view": ["products.view", "stock.view"],
    "products.create": ["products.create", "stock.manage"],
    "products.edit": ["products.edit", "stock.manage"],
    "products.delete": ["products.delete", "stock.manage"],
    "pos.view": ["pos.view", "pos.manage"],
    "sales.view": ["sales.view", "sales.manage", "crm.view"],
}
```

### 5.5 صلاحيات البدل (Wildcards)

- `*` - صلاحية كاملة (مدير، مشرف عام، مدير نظام)
- `products.*` - كل صلاحيات المنتجات
- `sales.*` - كل صلاحيات المبيعات

---

## 6. سياسات المصروفات (Expense Policies)

**الموقع:** `backend/routers/finance/expenses.py` + `backend/services/finance/cost_center_policy.py`

### 6.1 أنواع المصروفات (12 نوع)

`travel` (سفر)، `meals` (وجبات)، `supplies` (لوازم)، `transportation` (نقل)، `entertainment` (ترفيه)، `materials` (مواد)، `labor` (عمالة)، `services` (خدمات)، `rent` (إيجار)، `utilities` (مرافق)، `salaries` (رواتب)، `other` (أخرى)

### 6.2 محددات السياسة لكل نوع مصروف

- `daily_limit` - الحد اليومي
- `monthly_limit` - الحد الشهري
- `annual_limit` - الحد السنوي
- `requires_receipt` - يتطلب إيصال
- `cost_center_policy`: `required` (إجباري) / `optional` (اختياري) / `disabled` (معطل)

### 6.3 سياسة مركز التكلفة (Cost Center Policy)

**الموقع:** `backend/services/finance/cost_center_policy.py`

| الإعداد | السلوك |
|---------|--------|
| `off` | لا يتم التحقق من مركز التكلفة |
| `warn` | تحذير فقط بدون منع |
| `required` | منع الحفظ بدون مركز تكلفة |

---

## 7. إعدادات السياسات العامة (Policy Settings)

**الموقع:** `frontend/src/pages/Admin/PolicySettings.jsx` + `PUT /api/settings`

| المفتاح | النوع | الوصف |
|---------|------|-------|
| `reconciliation_tolerance` | رقم | هامش التسامح في التسويات البنكية |
| `gl.je_epsilon` | رقم | أدنى قيمة للقيود المحاسبية |
| `fiscal.allow_drafts_in_closed_period` | منطقي | السماح بالمسودات في فترة مقفلة |
| `expenses.auto_approve_threshold` | رقم | حد الموافقة التلقائية للمصروفات |
| `expenses.cost_center_policy` | اختيار | سياسة مركز التكلفة: required/optional/disabled |
| `webhook.rate_limit_rpm` | رقم | حد المعدل للـ webhooks (طلب/دقيقة) |
| `audit.sla_hours` | رقم | ساعات SLA للتدقيق |
| `recurring.review_threshold_default` | رقم | حد المراجعة الافتراضي للعمليات الدورية |

---

## 8. سياسة تقييم التكلفة (Costing Policy)

**الموقع:** `frontend/src/pages/Settings/CostingPolicy.jsx` + `backend/services/costing_service.py`

### 8.1 السياسات المتاحة

| السياسة | الوصف | التوصية |
|---------|------|---------|
| `global_wac` | متوسط التكلفة المرجح عالمي | فرع واحد أو أقل |
| `per_warehouse_wac` | متوسط التكلفة المرجح لكل مستودع | 3 فروع أو أقل |
| `hybrid` | هجين (حسب المنتج) | أكثر من 3 فروع |
| `smart` | ذكي (يختار تلقائياً) | - |

### 8.2 آلية التوصية التلقائية
- `<= 1` فرع → `global_wac`
- `<= 3` فروع → `per_warehouse_wac`
- `> 3` فروع → `hybrid`

---

## 9. قواعد القيود المحاسبية التلقائية (Industry GL Rules)

**الموقع:** `backend/services/industry_gl_rules.py`

### 9.1 القواعد الافتراضية (14 قاعدة)

| القاعدة | الوصف |
|---------|------|
| `cash_sale` | بيع نقدي |
| `credit_sale` | بيع آجل |
| `customer_payment` | تحصيل عميل |
| `cash_purchase` | شراء نقدي |
| `credit_purchase` | شراء آجل |
| `supplier_payment` | دفع مورد |
| `salary_accrual` | استحقاق رواتب |
| `salary_payment` | صرف رواتب |
| `vat_sale` | ضريبة مبيعات |
| `vat_purchase` | ضريبة مشتريات |
| `depreciation` | إهلاك |
| `rent_expense` | مصروف إيجار |
| `gosi_expense` | مصروف التأمينات |
| `eos_provision` | مخصص مكافأة نهاية الخدمة |

### 9.2 التجاوزات حسب النشاط

لكل نشاط تجاري تجاوزات خاصة للحسابات الافتراضية في القواعد أعلاه.

---

## 10. قواعد كشف الموظفين الوهميين (Ghost Employee Detection)

**الموقع:** `backend/services/ghost_employee_rule.py`

### 10.1 القواعد الأربع

| القاعدة | الوصف |
|---------|------|
| 1. حضور صفري + راتب | موظف بدون بصمة حضور ويتقاضى راتب |
| 2. IBAN مكرر | أكثر من موظف نشط يتشاركون نفس رقم الآيبان |
| 3. منتهي الخدمة + راتب نشط | موظف منتهي الخدمة وما زال في كشوف الرواتب |
| 4. بدون مدير | موظف نشط بدون مدير مباشر |

---

## 11. قواعد الإشارات المحاسبية (Sign Rules)

**الموقع:** `backend/services/reports/sign_rules.py`

تحدد إشارة (موجب/سالب) الحسابات في التقارير المالية بناءً على:
- الطبيعة العادية للحساب (`debit` / `credit`) من جدول `account_classifications`
- فئة الحساب: `revenue`, `expense`, `asset`, `liability`, `equity`
- نوع التقرير: ميزانية (`balance`) أو دخل (`income`)

---

## 12. آلية التخزين المؤقت للفلاتر (Client-Side)

### 12.1 BranchContext (حالة الفرع المختار)

**الموقع:** `frontend/src/context/BranchContext.jsx`

- يخزن الفرع الحالي في `localStorage.setItem('current_branch_id', value)`
- يبث حدث `branch:changed` عند تغيير الفرع
- يمرر `currentBranch` و `branches` و `displayCurrency` لكل المكونات

### 12.2 API Interceptor (اعتراض الطلبات)

**الموقع:** `frontend/src/services/apiClient.js`

- كل طلبات GET تحصل تلقائياً على `branch_id` من localStorage
- يمكن تعطيل هذا السلوك عبر `skipBranchScope: true`

### 12.3 مكون SearchFilter الموحد

**الموقع:** `frontend/src/components/common/SearchFilter.jsx`

مكون موحد لإضافة:
- مربع بحث نصي
- قوائم منسدلة للفلاتر الإضافية
- يرجع `filters` كمصفوفة من `{ key, label, options }`

### 12.4 فلترة المنتجات (Repository Pattern)

**الموقع:** `backend/repositories/product_repo.py` → `list()`

- بحث محسن: `product_code ILIKE 'prefix%'` (B-tree) + `product_name ILIKE '%substring%'` (trigram GIN)
- فلترة: `category_id`, `is_active`, `branch_id`, `branch_ids`

---

## ملخص هرمية الفلترة

```
1. صلاحية الدخول (Authentication / Authorization)
   └─ require_permission() / hasPermission()
   
2. صلاحية الوحدة (Module Gate)
   └─ require_module() / isModuleEnabled()
   
3. نطاق الفروع (Branch Scope)
   └─ resolve_branch_scope() → branch_scope_filter_from_scope()
   
4. فلترة المستودعات (Warehouse Scope) [PERM-002]
   └─ build_warehouse_filter()
   
5. فلترة مراكز التكلفة (Cost Center Scope) [PERM-003]
   └─ build_cost_center_filter()
   
6. تنقية الحقول (Field Filtering) [PERM-001]
   └─ filter_fields()
   
7. فلترة المستخدم (User Filters)
   └─ status, type, date, search (اختياري)
```
