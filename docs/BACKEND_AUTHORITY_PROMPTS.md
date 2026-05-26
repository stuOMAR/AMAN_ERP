# Backend-Authoritative Calculation Prompts

هذه البرومتات جاهزة للنسخ والتنفيذ على وحدات AMAN ERP. الهدف واحد في كل الوحدات:
الـ Frontend يجمع raw inputs فقط ويعرض نتائج السيرفر، والـ Backend هو المصدر الوحيد لأي حساب مالي أو تشغيلي مؤثر.

> ملاحظة مهمة: ليست كل الوحدات تحتاج `submitted_grand_total`. هذا النمط يستخدم فقط عندما تكون الواجهة تحفظ مستنداً له إجمالي مالي نهائي يمكن للمستخدم رؤيته قبل الحفظ، مثل فاتورة، أمر بيع، قسيمة راتب فردية، إقرار ضريبي، أو فاتورة مشروع. أما وحدات مثل المخزون، التصنيع، التقارير، الموافقات، والتكاملات فتستخدم Preview/Idempotency/Guards بدون فرض `submitted_grand_total` إلا إذا نشأ مستند مالي بإجمالي نهائي.

---

## حالة التطبيق العامة (Implementation Status)

### الفحص الإلزامي قبل البدء بأي وحدة:

```bash
# فحص الوحدات المدعومة حالياً في السكربت تلقائياً
python scripts/check_backend_authority.py

# فحص وحدة محددة
python scripts/check_backend_authority.py --module sales
python scripts/check_backend_authority.py --module purchases
python scripts/check_backend_authority.py --module finance
python scripts/check_backend_authority.py --module pos
python scripts/check_backend_authority.py --module inventory
python scripts/check_backend_authority.py --module manufacturing
python scripts/check_backend_authority.py --module hr
python scripts/check_backend_authority.py --module taxes

# الوحدات غير الموجودة بعد في check_backend_authority.py تُفحص بأوامر rg
# الموجودة داخل كل قسم إلى أن يتم توسيع السكربت لها.
```

---

## القواعد العامة (Non-Negotiable Rules)

1. **لا يعتبر أي ملف أو حساب محذوفاً من الواجهة حتى يتم التأكد بنسبة 100% أن الخلفية (Backend) تقوم بإرجاع نفس النتيجة بالضبط** ومجربة تحت كافة ظروف الحالات الخاصة والحدية (edge cases).
2. **عزل التعديلات**: أي تعديل على ملف يحتوي على أكثر من حساب Critical يتطلب تخطيطاً منفصلاً وتطبيق المرحلة B بشكل مستقل تماماً لكل حساب على حدة لتفادي التشابك والتداخل البرمجي.
3. **سلامة الاختبارات**: اختبارات الـ tests القديمة لا تُحذف أو تُلغى نهائياً، بل يتم تحديثها ومواءمتها مع التغييرات الجديدة أو إضافة فحص assertions إضافية صارمة للتحقق من السلوك الجديد.
4. لا يعتبر أي دمج أو تعديل مكتمل حتى:
   - لا توجد حسابات مؤثرة في React أو frontend services.
   - لا توجد payload totals محسوبة من الواجهة إلا كعرض مؤقت display-only، ولا تُرسل كحقيقة نهائية إلا إذا كانت قيمة backend preview.
   - كل money/rate/qty المهمة ترجع من backend كنصوص Decimal عادية.
   - يستخدم backend `Decimal` ولا يستخدم `float` أو JS `Number` للمحاور المالية.
   - mutations الحساسة لديها `Idempotency-Key`.
   - توجد guards مناسبة: tenant, permission, branch, warehouse, cost-center, fiscal period, budget, approval.
   - أي transaction مالي يستخدم GL service ولا يضيف journal entries مباشرة.
   - list endpoints paginated: default 25، cap 100.
   - scan لا يبقي إلا Low UI-only.
   - يتم تشغيل targeted tests و/أو build، وتوثيق أي اختبار لم يعمل.
   - **إلزامي: يتم تقديم تقرير إغلاق النطاق (Final Response Checklist) متوافق تماماً مع قواعد `AGENTS.md` (يحتوي على: Files Changed, Tests Run, Constitution-Sensitive Areas) كآخر رد بعد الانتهاء من كل وحدة.**

---

## الأنماط المستخدمة حسب الوحدة

### 1. submitted_grand_total / submitted_total (Hybrid Standard)

يستخدم فقط في المستندات ذات الإجمالي النهائي القابل للحفظ، مثل:
- Sales/Purchases/POS invoices and orders.
- Payslip single generation في HR.
- Project/customer billing.
- Tax returns عند اعتماد صافي الضريبة المستحقة.
- Contract billing documents، وليس بالضرورة سجل العقد نفسه.

### كيف يعمل:

```
المستخدم يكتب/يغيّر
       ↓
Frontend يعرض تقديراً محلياً فقط عند الحاجة باستخدام Decimal/fixed-point ← display-only
       ↓
يعرض النتيجة بلون باهت + "تقريبي" badge
       ↓
بعد 600ms → يُرسل للسيرفر (debounced)
       ↓
السيرفر يحسب بالـ Decimal + tax engine
       ↓
يُرجع النتيجة النهائية ← تُVERRIDE العرض المحلي
       ↓
المستخدم يضغط "حفظ"
       ↓
Frontend يُرسل submitted_grand_total (من السيرفر)
       ↓
السيرفر يتحقق: submitted == recalculated?
       ↓
إذا متطابق (فرق ≤ 0.01) → يقبل ويحفظ
إذا مختلف (فرق > 0.01) → يرفض 422
```

---

### 2. Preview بدون حفظ

يستخدم في أي عملية يمكن أن تعرض أثراً مالياً أو تشغيلياً قبل الالتزام:
- قيد يومية، فاتورة، payslip، إهلاك، تسوية مخزون، فاتورة مشروع، إقرار ضريبي.
- يجب أن يكون preview read-only أو داخل transaction لا يتم commit لها.

### 3. Idempotency-Key

إجباري على كل mutation قد يكرر أثراً مالياً أو تشغيلياً:
- إنشاء مستند مالي، ترحيل، اعتماد، صرف، استلام مخزون، مزامنة POS offline، إرسال تكامل خارجي، workflow action حساس.

### 4. Display-only Frontend

يجوز للواجهة عرض تنسيقات، subtotals توضيحية أو ترتيب/فلترة UI-only، بشرط ألا تكون مصدراً للحفظ أو الترحيل وألا تستخدم JS `Number` للمبالغ المالية.

---

# أدلة وبرومتات الفحص والتنفيذ التفصيلية للوحدات (16 وحدة)

---

## 1. Accounting / GL / Budgets / Financial Reports

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> هذا نظام مالي قائم وقيد التشغيل والاختبار. لا تقم بتعديل أكثر من ملف واحد في نفس الوقت دون إجراء الاختبارات الكاملة والتحقق المستقل بعد كل تعديل.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/accounting.py`
- `backend/schemas/budgets.py`
- `backend/routers/finance/accounting/journal.py`
- `backend/routers/finance/accounting/fiscal.py`
- `backend/routers/finance/accounting/recurring.py`
- `backend/routers/finance/budgets.py`

رسالة الالتزام المقترحة (Commit Message):
`feat(finance): enforce backend authority, idempotency keys, and decimal calculations for journal entries and budgets`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
عند حدوث أي مشكلة أو فشل في الاختبارات، تراجع فوراً باستخدام:
```bash
git checkout -- backend/routers/finance/accounting/journal.py backend/routers/finance/budgets.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وFinancial Controls Specialist متخصّص في المحاسبة العامة ودفتر الأستاذ العام (General Ledger) والموازنات التقديرية (Budgets).

المهمة:
مراجعة وتأمين وحدة "المحاسبة العامة والموازنات" (Accounting/GL/Budgets) لضمان أن السيرفر (Backend) هو المرجع الوحيد لجميع العمليات الحسابية والقيود والتسويات، وخلو الواجهة تماماً من أي حسابات مالية مؤثرة.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. دقة الحسابات المالية:
   - يجب استخدام Decimal حصراً لجميع حسابات الحركات والقيود والموازنات والنسب الضريبية. يمنع استخدام float نهائياً.
2. قيود اليومية (Journal Entries):
   - التحقق من توازن القيد (Debits == Credits) بالـ Decimal قبل الحفظ.
   - تفعيل Idempotency-Key على POST /journal-entries لمنع تكرار القيد.
3. الموازنات التقديرية (Budgets):
   - التحقق من عدم تجاوز الموازنة عند ترحيل القيود أو الحركات المرتبطة بمراكز التكلفة والحسابات الخاضعة للرقابة.
4. المعاينة (Preview):
   - إتاحة /journal-entries/preview لمعاينة أثر القيود والتحقق من التوازن دون حفظها في قاعدة البيانات.
5. استخدام الـ GL Service:
   - جميع حركات القيود والتسويات يجب أن تتم عبر GL Service حصراً.

الملفات المستهدفة:
- backend/schemas/accounting.py
- backend/routers/finance/accounting/journal.py
- backend/routers/finance/budgets.py

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/finance/
rg --type py "float\(" backend/schemas/accounting.py
rg --type py "journal" backend/routers/finance/accounting/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ — قبل أي تعديل: فحص الأكواد وتحديد أي حقول تستخدم float أو أي حسابات توازن تتم في الواجهة.
المرحلة ب — التعديل بالترتيب: تعديل الـ Schemas لإدراج Decimal، ثم تعديل الـ Routers لتطبيق التحقق بالـ Decimal وتفعيل الـ Idempotency-Key.
المرحلة ج — التحقق النهائي: تشغيل اختبارات الوحدة وتشغيل check_backend_authority.py.
```

---

## 2. Treasury / Banks / Checks / Notes / Reconciliation

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> الحركات البنكية والخزينة حساسة للغاية وتؤثر مباشرة على السيولة النقدية. احذر التعديل العشوائي وتأكد من سلامة الحسابات والتسويات.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/payments.py`
- `backend/routers/finance/treasury.py`
- `backend/routers/finance/checks.py`
- `backend/routers/finance/notes.py`
- `backend/routers/finance/reconciliation.py`

رسالة الالتزام المقترحة (Commit Message):
`feat(treasury): secure treasury endpoints, enforce bank reconciliation logic in backend, and add idempotency protections`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/finance/treasury.py backend/routers/finance/reconciliation.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وTreasury & Cash Management Expert.

المهمة:
مراجعة وتأمين وحدة "الخزينة والبنوك والشيكات والتسويات" (Treasury & Cash Management) لضمان أن الـ Backend هو المصدر الحصري والنهائي لكافة عمليات المقاصة وصرف الشيكات والتسويات البنكية.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب الأرصدة وحركات الخزينة:
   - حساب الأرصدة البنكية وأرصدة الصناديق بالـ Decimal. يمنع استخدام float.
2. الشيكات وأوراق القبض/الدفع:
   - تفعيل Idempotency-Key بشكل صارم على عمليات تحصيل الشيكات (POST /checks/{id}/collect) وارتدادها (bounce) لمنع الازدواجية في ترحيل الحركات المالية.
3. التسويات البنكية (Bank Reconciliation):
   - الـ Backend يقوم بمطابقة كشوف الحسابات المرفوعة مع حركات GL بالـ Decimal بالكامل. لا يتم الاعتماد على أي مطابقة واجهة.
4. ترابط الـ GL:
   - جميع حركات الصرف والتحويل والتسوية البنكية يجب أن ترحل قيودها للأستاذ العام عبر GL Service حصراً.

الملفات المستهدفة:
- backend/routers/finance/treasury.py
- backend/routers/finance/checks.py
- backend/routers/finance/reconciliation.py

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/finance/treasury.py
rg --type py "reconciliation" backend/routers/finance/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: مسح وفحص ملفات الخزينة والتسويات للتأكد من استخدام Decimal.
المرحلة ب: تعديل Routers الشيكات والتسويات وتفعيل الـ Idempotency-Key في عمليات الصرف والتسوية.
المرحلة ج: تشغيل اختبارات الخزينة والتسويات وتشغيل check_backend_authority.py.
```

---

## 3. Sales / Invoices / Orders / Returns / Receipts

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> دورة المبيعات ترتبط مباشرة بضرائب القيمة المضافة ZATCA والعملاء والأستاذ العام. تأكد من دقة submitted_grand_total لتفادي فروقات الهللات.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/sales/schemas.py`
- `backend/schemas/sales_credit_notes.py`
- `backend/routers/sales/invoices.py`
- `backend/routers/sales/orders.py`
- `backend/routers/sales/returns.py`
- `frontend/src/pages/Sales/InvoiceForm.jsx`

رسالة الالتزام المقترحة (Commit Message):
`feat(sales): enforce submitted_grand_total validation and preview endpoints across sales invoices and orders`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/sales/invoices.py frontend/src/pages/Sales/InvoiceForm.jsx
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وSales & Billing Controls Specialist.

المهمة:
مراجعة وتأمين دورة "المبيعات والفوترة" (Sales & Billing) بالكامل لضمان الامتثال التام لنمط submitted_grand_total والـ Preview والـ Idempotency-Key.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. الـ Backend هو المصدر الوحيد لحساب الضرائب والخصومات وصافي الفاتورة (Decimal).
2. حماية الفاتورة وأوامر البيع (submitted_grand_total):
   - يجب أن تحتوي الـ Schemas الخاصة بالفواتير وأوامر البيع على حقل submitted_grand_total: Optional[Decimal] = None.
   - في الـ Router، يجب مقارنة المبلغ الإجمالي المحسوب مع المرسل من الواجهة والرفض بـ 422 إذا كان الفرق > 0.01.
3. المعاينة (Preview):
   - توفير /invoices/preview و /orders/preview لمعاينة أثر الفواتير ومسودة القيود المحاسبية بالـ Transaction Rollback.
4. منع تكرار الطلبات (Idempotency):
   - تفعيل Idempotency-Key على جميع عمليات الإنشاء والتعديل.

الملفات المستهدفة:
- backend/routers/sales/invoices.py
- backend/routers/sales/orders.py
- backend/routers/sales/schemas.py
- frontend/src/pages/Sales/InvoiceForm.jsx

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "submitted_grand_total" backend/routers/sales/
rg --type js "submitted_grand_total" frontend/src/pages/Sales/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص schemas الفواتير والمبيعات والتأكد من إرسال submitted_grand_total من الفرونت.
المرحلة ب: تطبيق مقارنة submitted_grand_total في الـ Routers والرفض بـ 422 عند عدم التطابق.
المرحلة ج: التحقق من نجاح الاختبارات لسيناريوهات الفروقات المحاسبية وعمليات الـ Rollback في المعاينة.
```

---

## 4. Purchases / Procurement / Supplier Invoices / Landed Costs / Matching

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> دورة المشتريات تؤثر على تكلفة المخزون ومتوسط التكلفة المتحرك للأصناف. تأكد من دقة حساب مصاريف الشحن والتخليص (Landed Costs).

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/purchases.py`
- `backend/routers/purchases/invoices.py`
- `backend/routers/purchases/orders.py`
- `backend/routers/purchases/returns.py`
- `frontend/src/pages/Buying/PurchaseInvoiceForm.jsx`

رسالة الالتزام المقترحة (Commit Message):
`feat(purchases): enforce backend calculations for supplier invoices, landed costs, and enable purchases preview`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/purchases/invoices.py frontend/src/pages/Buying/PurchaseInvoiceForm.jsx
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وProcurement & Inventory Costing Expert.

المهمة:
مراجعة وتأمين دورة "المشتريات والاعتمادات وتكاليف الشحن" (Purchases & Procurement) لضمان أن الـ Backend هو المرجع الحصري لحساب تكلفة المشتريات ومصاريف الشراء الملحقة (Landed Costs) وتوزيعها على الأصناف.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب التكاليف والإهلاك بالـ Decimal:
   - الـ Backend يحسب صافي قيمة الفاتورة وقيمة الضريبة ومصاريف الشحن الموزعة (Landed Costs) بالـ Decimal.
2. حماية فواتير المشتريات (submitted_grand_total):
   - إجبار وجود submitted_grand_total في الـ Schema للفاتورة وأوامر الشراء.
   - التحقق في الـ Router من تطابق القيمة والرفض بـ 422 عند الاختلاف.
3. المعاينة (Preview):
   - دعم /invoices/preview لمعاينة أثر الفاتورة وتوزيع التكاليف وقيود الاستحقاق قبل الترحيل الفعلي.
4. منع تكرار الطلبات (Idempotency):
   - تفعيل Idempotency-Key إجبارياً على جميع عمليات الإنشاء في المشتريات.

الملفات المستهدفة:
- backend/schemas/purchases.py
- backend/routers/purchases/invoices.py
- frontend/src/pages/Buying/PurchaseInvoiceForm.jsx

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "submitted_grand_total" backend/routers/purchases/
rg --type js "submitted_grand_total" frontend/src/pages/Buying/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص ملفات المشتريات والتأكد من عدم وجود حسابات ضرائب أو Landed Costs في الواجهة.
المرحلة ب: تعديل Routers المشتريات لمطابقة الفواتير مع الـ submitted_grand_total وتفعيل الـ Preview.
المرحلة ج: تشغيل اختبارات المشتريات وفحص تكاليف المخزون المتأثرة.
```

---

## 5. Inventory / Stock / Costing / Warehouses

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> التعديل على حركة المخزون (صادر/وارد/تسويات) يؤثر على تقييم المخزون المالي والأرباح والخسائر. التراجع السريع عند الخطأ حتمي.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/inventory/batches.py`
- `backend/routers/inventory/shipments.py`
- `backend/routers/inventory/transfers.py`
- `backend/routers/inventory/adjustments.py`

رسالة الالتزام المقترحة (Commit Message):
`feat(inventory): secure inventory shipments and adjustments, enable decimal calculations for valuations`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/inventory/shipments.py backend/routers/inventory/adjustments.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وInventory Valuation & Costing Specialist (FIFO/Moving Average).

المهمة:
مراجعة وتأمين وحدة "المخازن وحركات الأصناف والتقييم" (Inventory & Valuation) لضمان أن الـ Backend هو المسؤول الحصري والنهائي لحساب تكلفة حركات المخزون وتسوية الفروقات.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب تكلفة المخزون (Costing Engine):
   - الـ Backend يحسب قيمة الوارد وتكلفة المنصرف ومتوسط التكلفة بالـ Decimal حصراً. يمنع استخدام float.
2. حماية تسويات المخزن (Adjustments):
   - تفعيل Idempotency-Key إجبارياً على حركات الصرف والاستلام والتسويات (POST /adjustments) لمنع تكرار الحركة وتشويه الأرصدة.
3. ترابط الـ GL:
   - حركات المخزون المؤثرة مالياً (تسويات، بضاعة بالطريق، فروقات جرد) يجب أن ترحل قيودها للأستاذ العام عبر GL Service حصراً.

الملفات المستهدفة:
- backend/routers/inventory/adjustments.py
- backend/routers/inventory/shipments.py
- backend/routers/inventory/transfers.py

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/inventory/
rg --type py "moving_average" backend/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: التحقق من استخدام Decimal في حساب التكاليف بالمستودعات.
المرحلة ب: تفعيل Idempotency-Key في Routers المخازن والتأكد من مطابقة حركات القيمة لـ GL.
المرحلة ج: تشغيل اختبارات المخازن والتأكد من عدم وجود أخطاء في الكميات أو الأرصدة السالبة.
```

---

## 6. Manufacturing / MRP / BOM / Shop Floor

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> أوامر التصنيع وقوائم المواد (BOM) تؤثر على استهلاك المواد الخام وتكلفة المنتج النهائي. أي خطأ يسبب خللاً في انضباط تكاليف المنتجات التامة.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/manufacturing/core/orders.py`
- `backend/routers/manufacturing/core/boms.py`

رسالة الالتزام المقترحة (Commit Message):
`feat(mrp): secure manufacturing BOM allocations and orders, enforce backend authority for production costing`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/manufacturing/core/orders.py backend/routers/manufacturing/core/boms.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وManufacturing & Cost Accounting Specialist.

المهمة:
مراجعة وتأمين وحدة "التصنيع وقوائم المواد" (Manufacturing & MRP) لضمان أن الـ Backend هو المسؤول الحصري والنهائي لحساب توزيع تكاليف المواد والأجور المباشرة وغير المباشرة على المنتجات النهائية.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب تكلفة قائمة المواد (BOM Costing):
   - الـ Backend يحسب تكلفة الـ BOM بالـ Decimal بضرب كميات المواد الخام في تكاليفها الفعلية المحدثة، وإضافة المصاريف التشغيلية. يمنع الحساب في الواجهة.
2. حماية أوامر الإنتاج:
   - تفعيل Idempotency-Key إجبارياً على POST /orders (إنشاء أمر إنتاج) و POST /orders/{id}/consume (صرف المواد الخام) لمنع تكرار صرف المواد.
3. ترابط الـ GL:
   - ترحيل تكلفة الإنتاج تحت التشغيل (WIP) وتكلفة البضاعة التامة الصنع للأستاذ العام عبر GL Service حصراً.

الملفات المستهدفة:
- backend/routers/manufacturing/core/orders.py
- backend/routers/manufacturing/core/boms.py

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/manufacturing/
rg --type py "wip" backend/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: التحقق من دقة حسابات الـ BOM والتأكد من استخدام Decimal بالكامل في المواد التشغيلية.
المرحلة ب: تعديل Routers التصنيع وتأمين عمليات الإنتاج والصرف التلقائي بـ Idempotency-Key.
المرحلة ج: تشغيل الفحص والاختبارات للتأكد من توازن قيود التصنيع وصحة الأرصدة المستهلكة.
```

---

## 7. HR / Payroll / Attendance / Leave / WPS / GOSI

### الحالة الحالية: ✅ مطبق للسيناريوهات الأساسية / يحتاج توسيع اختبارات Integration عند توفر بيانات tenant كاملة

تم تنفيذ وتثبيت المسارات التالية:
- `POST /hr/payslips/preview` يحسب صافي الراتب بالـ Backend دون حفظ.
- `POST /hr/payslips/generate` يستخدم نفس محرك الحساب، ويتحقق من `submitted_grand_total`.
- mismatch يرجع `422` و`detail == "submitted_grand_total_mismatch"`.
- نفس `Idempotency-Key` يعيد نفس payslip ولا ينشئ قسيمة ثانية.
- تم إضافة idempotency لحفظ قسيمة راتب، إنشاء سلفة، وإنشاء طلب إجازة.
- تم تقليل حسابات الرواتب في الواجهة إلى display-only باستخدام Decimal.js حيث يلزم.

اختبارات مثبتة:
- `test_submitted_grand_total_mismatch_returns_422`
- `test_idempotency_key_prevents_duplicate_payslip`
- `test_preview_does_not_commit_to_db`
- `test_preview_and_save_return_same_net_salary`

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> مسيرات الرواتب تؤثر مباشرة على التزامات الموظفين والـ GL والامتثال لنظام حماية الأجور (WPS). احذر التغييرات غير المجربة في محرك حساب التأمينات (GOSI).

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/hr.py` و `backend/schemas/hr_advanced.py`
- `backend/routers/hr/core/payroll.py` (محرك مسيرات الرواتب الرئيسي)
- `backend/routers/hr/advances.py` و `backend/routers/hr/core/leaves.py`
- `frontend/src/pages/HR/` و `frontend/src/pages/payroll/`

رسالة الالتزام المقترحة (Commit Message):
`feat(hr): enforce backend payroll engine, submitted_grand_total for payslips, and add idempotency protections`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/hr/core/payroll.py backend/routers/hr/advances.py backend/schemas/hr.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وFinancial Controls Engineer متخصّص في أنظمة الموارد البشرية والرواتب (HR/Payroll) والامتثال المالي ومحرك الرواتب وحماية الأجور (WPS).

المهمة:
مراجعة وتعديل وحماية وحدة "الموارد البشرية والرواتب" (HR & Payroll) لضمان أن الـ Backend هو المصدر الوحيد والنهائي لجميع العمليات الحسابية والمالية الحساسة، والتأكد من عدم وجود أي حسابات مالية للرواتب أو الاستحقاقات أو الخصومات في الـ Frontend.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. الرواتب ومحرك الرواتب:
   - يجب استخدام Decimal في جميع حسابات الرواتب، البدلات، الحوافز، والخصومات (التأمين الاجتماعي GOSI، الغيابات، التأخير، الضرائب). يمنع استخدام float نهائيًا.
   - محرك حساب مسيرات الرواتب (Payroll Engine) يجب أن يكون بالكامل في الـ Backend.
2. submitted_grand_total للرواتب (Payslips):
   - يجب أن تحتوي Schema إنشاء قسيمة الراتب الفردية على حقل submitted_grand_total: Optional[Decimal] = None.
   - الواجهة لا تحسب صافي الراتب؛ تستدعي `/payslips/preview` ثم ترسل قيمة `net_salary` الراجعة من السيرفر كـ `submitted_grand_total`.
   - في الـ Router، عند حفظ قسيمة الراتب، يجب التحقق من أن صافي الراتب المرسل من الواجهة يتطابق مع الحساب الفعلي للـ Backend:
     abs(net_salary - data.submitted_grand_total) <= Decimal("0.01")
     إذا اختلف، يتم الرفض فوراً برمز استجابة 422 و detail يساوي `submitted_grand_total_mismatch`.
3. المعاينة (Preview):
   - يجب دعم endpoint للمعاينة `/payslips/preview` لحساب صافي الراتب ومسودة قيد الاستحقاق المقترح قبل حفظه الفعلي في قاعدة البيانات.
   - preview يجب ألا ينشئ payroll_entries أو payroll_periods جديدة.
4. منع تكرار الصرف (Idempotency):
   - تفعيل Idempotency-Key إجبارياً على جميع عمليات: إنشاء قسيمة راتب (`POST /payslips/generate`)، صرف/طلب السلف (`POST /advances`)، وتسجيل الإجازات (`POST /leaves`).
   - تكرار نفس المفتاح يجب أن يعيد نفس نتيجة العملية المحفوظة، وليس رسالة عامة فقط.
5. ترابط الـ GL (دفتر اليومية):
   - عند ترحيل payroll period، يجب إثبات قيد الاستحقاق (رواتب مستحقة، مصاريف رواتب، استقطاعات، GOSI) في الأستاذ العام عبر GL Service حصراً. يُمنع كتابة قيود اليومية مباشرة.
   - قسيمة الراتب الفردية يمكن أن تعرض draft_journal_lines في preview، لكن لا تنشئ JE إلا عند workflow/period posting المعتمد.
6. الامتثال لنظام حماية الأجور (WPS):
   - التأكد من مطابقة مخرجات مسيرات الرواتب مع هيكل ملف WPS الرسمي (البنك المركزي/وزارة الموارد البشرية) بالهللة.

الملفات المستهدفة للفحص والتعديل:
- الـ Schemas: backend/schemas/hr.py أو backend/schemas/payroll.py
- الـ Routers: backend/routers/hr/* و backend/routers/payroll/*
- الـ Services: backend/services/payroll/*
- الـ Frontend: frontend/src/pages/HR/* و frontend/src/pages/payroll/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/hr/ backend/services/payroll/
rg --type py "submitted_grand_total|payslips/preview|Idempotency-Key|idempotency_key" backend/routers/hr/
rg --type js "toNumber\(|parseFloat|toFixed\(|Number\(" frontend/src/pages/HR/ frontend/src/pages/payroll/ frontend/src/services/hr.js
rg --type js "submitted_grand_total|payslips/preview|Idempotency-Key" frontend/src/pages/HR/ frontend/src/services/hr.js

خطوات التنفيذ المطلوبة:
أولاً: فحص الملفات المذكورة للبحث عن أي حسابات مالية للرواتب أو التأمينات في الـ Frontend ووصفها.
ثانياً: ضمان أن preview/save يستخدمان نفس دالة الحساب في Backend، وأن الحفظ يرفض mismatch ويعيد نفس نتيجة idempotency replay.
ثالثاً: تشغيل الاختبارات السلوكية الأربعة أعلاه، ثم `npm --prefix frontend run build`.
```

---

## 8. Assets / Leases / Depreciation / Impairment

### الحالة الحالية: 🔲 قيد التنفيذ / لم يبدأ بعد

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> عمليات الإهلاك وحساب جداول الالتزامات الإيجارية (IFRS 16) تؤثر على الأصول المعروضة بالميزانية والـ GL. الأخطاء البرمجية هنا قد تسبب فروقات وتعديلات محاسبية لاحقة.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/assets.py`
- `backend/routers/finance/assets/core.py` (محرك الأصول الثابتة)
- `frontend/src/pages/Assets/`

رسالة الالتزام المقترحة (Commit Message):
`feat(assets): secure fixed assets and lease accounting, add depreciation preview, and enforce IFRS 16 compliance`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/finance/assets/core.py backend/schemas/assets.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وFixed Assets & Lease Accounting Expert (IFRS 16).

المهمة:
مراجعة وتعديل وحماية وحدة "الأصول الثابتة والإيجارات" (Assets & Leases) لضمان أن الـ Backend هو المصدر الوحيد والنهائي لحسابات الإهلاك (Depreciation)، إعادة التقييم (Revaluation)، الاستبعاد والتخريد (Disposal)، وجداول التزامات الإيجار وحق الاستخدام (IFRS 16).

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حسابات الإهلاك (Depreciation Engine):
   - الـ Backend هو المسؤول الحصري عن حساب الإهلاك (قسط ثابت، متناقص، إلخ) بناءً على العمر الإنتاجي وتاريخ الاستحواذ والقيمة التخريدية للأصل بالـ Decimal. يمنع استخدام float.
2. حماية عمليات الاستبعاد والتخريد:
   - لا يستخدم `submitted_grand_total` على سجل الأصل نفسه.
   - عند بيع أصل، إن كان الـ endpoint ينشئ مستند بيع أو سند قبض بقيمة نهائية، يجب استخدام حقل مثل `submitted_disposal_proceeds` أو `submitted_grand_total` حسب schema المحلي لتمثيل مبلغ البيع/التحصيل الراجع من preview.
   - الـ Backend يحسب صافي القيمة الدفترية، مجمع الإهلاك، وربح/خسارة الاستبعاد بالـ Decimal ولا يقبل أرقام frontend كحقيقة محاسبية.
3. المعاينة (Preview):
   - إتاحة /assets/depreciate/preview لمعاينة قيود الإهلاك المقترحة للشهر قبل ترحيلها الفعلي للـ GL.
   - إتاحة /assets/disposal/preview لمعاينة أثر استبعاد الأصل وقيود إثبات الخسائر أو الأرباح الرأسمالية.
4. منع التكرار (Idempotency):
   - تفعيل Idempotency-Key إجبارياً على POST /assets/depreciate لمنع تشغيل الإهلاك الدوري لنفس الشهر أكثر من مرة.
5. ترابط الـ GL:
   - جميع عمليات الإهلاك والتخريد يجب أن ترحل قيودها للأستاذ العام عبر GL Service حصراً.

الملفات المستهدفة:
- الـ Schemas: backend/schemas/assets.py
- الـ Routers: backend/routers/finance/assets/*
- الـ Services: backend/services/impairment_service.py
- الـ Frontend: frontend/src/pages/Assets/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/finance/assets/ backend/services/impairment_service.py
rg --type py "IFRS|depreciation|disposal|impairment|revaluation" backend/routers/finance/assets/ backend/services/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: تحديد طرق الإهلاك المحتسبة في الواجهة وتهيئة Schemas للأصول الثابتة.
المرحلة ب: تعديل Routers الأصول لدعم الإهلاك بالـ Decimal ومعاينة القيود وتأمينها بـ Idempotency-Key.
المرحلة ج: تشغيل اختبارات الأصول ومطابقة قيود إهلاك الأصول في الـ GL.
```

---

## 9. POS / Sessions / Offline / Promotions / Loyalty

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> نقطة البيع (POS) تعمل في وضع متصل ومنفصل (Offline). احذر تغيير منطق الفوترة دون فحص دقيق لآلية المزامنة التلقائية للفواتير من الـ LocalStorage.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/pos.py`
- `backend/routers/pos/orders.py`
- `frontend/src/pages/POS/POSInterface.jsx`

رسالة الالتزام المقترحة (Commit Message):
`feat(pos): secure POS orders submission, enforce submitted_grand_total matching and sync safety`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/pos/orders.py frontend/src/pages/POS/POSInterface.jsx
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وPOS & Retail Operations Specialist.

المهمة:
مراجعة وتأمين وحدة "نقاط البيع والمزامنة" (POS & Offline Sync) لضمان صحة احتساب الفواتير والعروض والولاء بالـ Decimal وحمايتها من الثغرات البرمجية في وضع عدم الاتصال.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب الفواتير بالـ Decimal:
   - الـ Backend هو المصدر النهائي والوحيد لتطبيق الخصومات الترويجية، الضرائب، واحتساب نقاط الولاء بالـ Decimal.
2. حماية عمليات الحفظ (submitted_grand_total):
   - الـ Schema تحتوي على submitted_grand_total: Optional[Decimal] = None.
   - في الـ Router، يتم التحقق من صحة الإجمالي والرفض بـ 422 عند أي تلاعب أو خطأ حسابي بالواجهة.
3. المزامنة والـ Idempotency:
   - إجبارية الـ Idempotency-Key على جميع الفواتير المزامنة بعد العودة للاتصال بالإنترنت لمنع تكرار ترحيل الفاتورة في قاعدة البيانات.
4. المعاينة (Preview):
   - دعم معاينة الحسابات ونقاط الولاء قبل الحفظ النهائي للفاتورة.

الملفات المستهدفة:
- backend/schemas/pos.py
- backend/routers/pos/orders.py
- frontend/src/pages/POS/POSInterface.jsx

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "submitted_grand_total" backend/routers/pos/
rg --type js "submitted_grand_total" frontend/src/pages/POS/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص آلية إرسال الفواتير في الواجهة والتأكد من إرسال submitted_grand_total.
المرحلة ب: تعديل Routers نقاط البيع لمقارنة المبالغ وتفعيل الـ Idempotency-Key الصارم للطلبات المزامنة.
المرحلة ج: تشغيل اختبارات الفوترة لنقاط البيع والتأكد من المزامنة الناجحة بلا تكرار.
```

---

## 10. Projects / TimeTracking / Expenses / Resources

### الحالة الحالية: 🔲 قيد التنفيذ / لم يبدأ بعد

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> حساب ساعات عمل المشاريع والفوترة بناءً على نسب الإنجاز يؤثر مباشرة على حساب أجور المشاريع تحت التشغيل (WIP) وإثبات الإيرادات.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/projects.py` و `backend/schemas/timetracking.py`
- `backend/routers/projects/` (تشمل: core.py, finance.py, timetracking.py)
- `frontend/src/pages/Projects/`

رسالة الالتزام المقترحة (Commit Message):
`feat(projects): enforce backend calculation of timesheet billing, project WIP cost, and add billing preview`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/projects/finance.py backend/routers/projects/timetracking.py backend/schemas/projects.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وProject Costing & WIP Specialist.

المهمة:
مراجعة وتأمين وحدة "المشاريع وساعات العمل" (Projects & Timesheets) لضمان دقة احتساب أجور المشاريع تحت التشغيل (WIP) وتكلفة ساعات العمل والفوترة بناءً على نسب الإنجاز أو الساعات المستنفذة.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. دقة حساب تكلفة ساعات العمل:
   - الـ Backend يحسب تكلفة جدول العمل (Timesheet) بضرب الساعات الفعلية في معدل تكلفة الموظف بالـ Decimal وليس الـ Frontend.
2. حماية الفوترة (submitted_grand_total):
   - يستخدم `submitted_grand_total` فقط عند إصدار فاتورة عميل فعلية للمشروع أو إنشاء مستند مالي نهائي.
   - Timesheets وResource allocations لا تستخدم `submitted_grand_total`; حمايتها تكون بالـ Idempotency-Key وقيود عدم التكرار الطبيعية (employee/date/project/task).
   - في Router الفوترة، يتم إعادة احتساب القيمة بناءً على الساعات المعتمدة أو نسب الإنجاز أو milestones المعتمدة ومقارنتها بالمرسل والرفض بـ 422 في حال عدم التطابق.
3. المعاينة (Preview):
   - إتاحة /projects/billing/preview لمعاينة مسودة فاتورة المشروع وقيود إثبات الإيرادات وتكلفة المشروع قبل الحفظ الفعلي.
4. منع التكرار (Idempotency):
   - تفعيل الـ Idempotency-Key على POST /timesheets لمنع تكرار إرسال ساعات العمل لنفس اليوم/الموظف، وعلى project expense/revenue/billing mutations لمنع تكرار الأثر المالي.

الملفات المستهدفة:
- الـ Schemas: backend/schemas/timetracking.py و backend/schemas/resource.py عند وجودها
- الـ Routers: backend/routers/projects/* و backend/routers/projects/timetracking.py
- الـ Frontend: frontend/src/pages/Projects/* و frontend/src/pages/TimeTracking/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/projects/ backend/schemas/timetracking.py backend/schemas/resource.py
rg --type py "wip|timesheet|billable|idempotency_key" backend/routers/projects/
rg --type js "toNumber\(|parseFloat|toFixed\(|reduce\(" frontend/src/pages/Projects/ frontend/src/pages/TimeTracking/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: تحديد الحسابات المالية وساعات العمل وتكلفة الساعات بالواجهة.
المرحلة ب: صياغة Routers المشاريع لضمان احتساب التكلفة في Backend، وتفعيل الـ Preview لعمليات الفوترة.
المرحلة ج: تشغيل اختبارات الفوترة وساعات العمل للمشاريع والتحقق من GL.
```

---

## 11. Taxes / ZATCA / WHT / Zakat / E-Invoicing

### الحالة الحالية: ✅ مطبق بالكامل (الحالة في check_backend_authority.py: PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> الضرائب والفوترة الإلكترونية (ZATCA) بالغة الحساسية. أي فرق هللة، إرسال مكرر، إلغاء فاتورة مخلوصة، أو حساب ضريبي من الواجهة قد يسبب مخالفة نظامية وغرامات وتبايناً بين الإقرار والـ GL. الـ Backend هو المصدر الوحيد للحساب، والـ Frontend يعرض نتائج السيرفر فقط.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/taxes.py`
- `backend/routers/finance/taxes/` كاملًا: `returns_.py`, `payments.py`, `core.py`, `groups.py`, `calendar.py`, `reports.py`
- `backend/routers/finance/tax_compliance.py`
- `backend/routers/einvoicing/outbox_admin.py`
- `backend/integrations/einvoicing/zatca_adapter.py`
- `backend/services/einvoicing/`, خصوصًا `outbox.py`, `ubl_builder.py`, `ubl_signer.py`
- `backend/routers/external.py` لمسارات WHT و ZATCA QR/signing القديمة
- `backend/routers/system_completion/accounting.py` و `backend/routers/system_completion/core.py` للزكاة
- `backend/routers/governance.py` لإعدادات عناصر وعاء الزكاة
- `backend/routers/sales/invoices.py` و `backend/services/sales/invoice_state.py` عند لمس أثر ZATCA على الفواتير
- `backend/locales/errors.en.json` و `backend/locales/errors.ar.json`
- `frontend/src/pages/Taxes/` و `frontend/src/pages/einvoicing/`
- `frontend/src/pages/Accounting/ZakatCalculator.jsx`
- `frontend/src/services/taxes.js` و أي service يستخدم WHT أو ZATCA

رسالة الالتزام المقترحة (Commit Message):
`feat(taxes): enforce backend authority for VAT, ZATCA, WHT, Zakat, and e-invoicing`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/schemas/taxes.py backend/routers/finance/taxes backend/routers/finance/tax_compliance.py backend/routers/einvoicing/outbox_admin.py backend/integrations/einvoicing/zatca_adapter.py backend/locales/errors.en.json backend/locales/errors.ar.json frontend/src/pages/Taxes frontend/src/pages/einvoicing frontend/src/services/taxes.js
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وZATCA Integration & Tax Compliance Specialist (الزكاة والضريبة والجمارك بالمملكة العربية السعودية).

المهمة:
تأمين وحدة "Taxes / ZATCA / WHT / Zakat / E-Invoicing" end-to-end بحيث تكون كل الحسابات، الإقرارات، الاستقطاعات، الزكاة، الفوترة الإلكترونية، الإرسال للهيئة، والقيود المحاسبية صادرة من الـ Backend فقط، ومتطابقة مع الأستاذ العام، ومعزولة حسب الشركة/الفرع، ومحمية من التكرار.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. Decimal فقط:
   - يمنع `float`, `double`, JS `Number`, `parseFloat`, `toFixed`, و `toLocaleString` لأي مبلغ ضريبي أو زكوي أو WHT أو FX أو إجمالي فاتورة.
   - Python يستخدم `Decimal` و `ROUND_HALF_UP`.
   - API يعيد المبالغ كنصوص Decimal عادية، بلا scientific notation مثل `0E+6`.
   - يسمح للواجهة فقط بتنسيق نصوص Decimal، لا حسابها.

2. VAT / Tax Returns:
   - `POST /api/taxes/returns/preview` هو المرجع الوحيد لصافي الضريبة المستحقة أو المستردة.
   - إنشاء الإقرار `POST /api/taxes/returns` لا يقبل مبلغاً محسوباً من الواجهة. يجب أن ترسل الواجهة `submitted_tax_due` أو `submitted_grand_total` الراجع من preview.
   - الـ Backend يعيد الحساب من قيود `journal_lines` المنشورة خلال الفترة، مع فلترة الفرع، ويقارن بالهللة. أي اختلاف يرفض بـ 422.
   - تقديم الإقرار `PUT /api/taxes/returns/{return_id}/file` يعيد الحساب مرة أخرى ويرفض المسودة القديمة إذا تغيرت القيود بعد إنشائها.
   - لا يجوز أن يعتمد الإقرار على فواتير غير مرحلة أو قيود غير منشورة.

3. الربط مع GL:
   - كل تسوية أو دفع ضريبي أو زكاة أو WHT ينتج أثراً محاسبياً يجب أن يمر عبر GL service أو helper محلي معتمد يضمن توازن القيود.
   - يمنع إدخال journal entries مباشرة من Router ضريبي جديد.
   - يجب احترام `check_fiscal_period_open()` في أي عملية ترحيل ضريبية أو زكوية أو WHT.
   - تقارير VAT/WHT/Zakat يجب أن تتطابق مع `journal_lines` أو جدول مصدر رسمي مرتبط بقيد GL.

4. ZATCA / E-Invoicing:
   - الفواتير المخلوصة أو المقبولة من ZATCA لا تلغى ولا تعدل مباشرة. المسار الصحيح هو credit note/debit note حسب الحالة ثم إرسال المستند التصحيحي.
   - الإرسال أو إعادة الإرسال إلى ZATCA يجب أن يكون عبر outbox/idempotent workflow. لا يسمح بإرسال مباشر قابل للتكرار من واجهة أو Router.
   - `POST /api/einvoicing/outbox/{outbox_id}/reprocess` يتطلب `Idempotency-Key` إجباري ولا يستخدم fallback.
   - الـ QR/UBL/signing/clearance/reporting يجب أن تستخدم Decimal strings وحدود تحويل JSON واضحة، ولا تسرب مفاتيح أو شهادات أو raw exception.
   - أخطاء ZATCA تعرض برسائل i18n عامة، وتُسجل التفاصيل داخلياً بدون أسرار.

5. WHT:
   - WHT يحسب في Backend فقط من `WhtRate`/`WhtTransaction` أو الخدمة المعتمدة.
   - إنشاء WHT transaction يتطلب `payment_id` صالحاً عند ارتباطه بدفع مورد، ولا ترسل الواجهة `payment_id: null`.
   - يجب أن يرتبط WHT بالدفع/المورد/الفرع وأن يحترم branch access.
   - الـ Idempotency-Key إجباري لإنشاء WHT transaction حتى لا يتكرر قيد الاستقطاع.
   - WHT payable/reclassification يجب أن يكون متوازناً ومتصالحاً مع AP/Cash/GL.

6. Zakat:
   - الزكاة تتبع `docs/ZAKAT_CALCULATION_METHODOLOGY.md` وطريقة Net Equity الافتراضية حيث تطبق.
   - حساب الزكاة `POST /api/accounting/zakat/calculate` يعرض preview فقط.
   - ترحيل الزكاة `POST /api/accounting/zakat/{fiscal_year}/post` يحتاج صلاحية إدارة، فترة مفتوحة، mapping حسابات زكاة، و idempotency/duplicate guard مناسب.
   - إعدادات وعاء الزكاة من `governance/zakat/base-items` و tax regimes/company settings هي المصدر، لا أرقام hardcoded في الواجهة.

7. الصلاحيات والعزل:
   - كل endpoint محمي بـ `require_module("taxes")` أو permission مناسب مثل `taxes.view`, `taxes.manage`, `accounting.view`, `accounting.manage`, `einvoicing.manage`.
   - كل عمليات tenant تستخدم `transactional(current_user.company_id)` أو مسار tenant DB المعتمد.
   - أي فلتر فرع يستخدم `validate_branch_access` أو `resolve_branch_scope`.
   - لا توجد SQL interpolated من مدخلات المستخدم؛ كل SQL parameterized.

8. Frontend contract:
   - صفحات `frontend/src/pages/Taxes/*`, `frontend/src/pages/einvoicing/*`, و `ZakatCalculator.jsx` تجمع raw inputs فقط.
   - لا توجد حسابات VAT/WHT/Zakat/return totals في React باستخدام JS Number.
   - create/file tax return يستخدم preview من backend ثم يرسل submitted value نفسها.
   - ZATCA outbox reprocess و WHT transaction و tax return create/payment mutations ترسل `Idempotency-Key`.
   - أي نص جديد يضاف إلى `frontend/src/locales/en.json` و `frontend/src/locales/ar.json`.

9. الترابطات الإلزامية:
   - Sales/POS/Purchases invoices → VAT totals → GL journal_lines → Tax returns.
   - Sales invoices → UBL/QR/signing → ZATCA outbox → immutable cleared status.
   - Supplier payments → WHT calculation/transaction → WHT payable GL → WHT reports/certificates.
   - Accounting balances/settings/tax regimes → Zakat calculation → Zakat posting.
   - Branch/company settings → tax jurisdiction/rate selection → reports and returns.
   - Treasury tax payments → tax_return remaining amount → GL cash/bank impact.

الملفات المستهدفة:
- الـ Schemas: `backend/schemas/taxes.py`
- Routers الضرائب: `backend/routers/finance/taxes/*`
- Tax compliance: `backend/routers/finance/tax_compliance.py`
- WHT/ZATCA legacy integration: `backend/routers/external.py`
- ZATCA outbox/admin: `backend/routers/einvoicing/outbox_admin.py`
- ZATCA adapter/services: `backend/integrations/einvoicing/*`, `backend/services/einvoicing/*`
- Zakat: `backend/routers/system_completion/accounting.py`, `backend/routers/system_completion/core.py`, `backend/routers/governance.py`
- Sales invoice state linkage: `backend/routers/sales/invoices.py`, `backend/services/sales/invoice_state.py`
- Frontend: `frontend/src/pages/Taxes/*`, `frontend/src/pages/einvoicing/*`, `frontend/src/pages/Accounting/ZakatCalculator.jsx`, `frontend/src/services/taxes.js`
- Locales/tests/checker: `backend/locales/errors.*.json`, `frontend/src/locales/*.json`, `backend/tests/*tax*`, `scripts/check_backend_authority.py`

مسح الأكواد ومطابقة الأنماط (rg scan commands):
python scripts/check_backend_authority.py --module taxes
rg --type py "float\(|round\(|str\(.*Exception|HTTPException\(.*str\(e\)" backend/routers/finance/taxes backend/routers/finance/tax_compliance.py backend/routers/einvoicing backend/integrations/einvoicing backend/services/einvoicing
rg --type py "zatca|clearance|reporting|outbox|idempotency|last_idempotency_key" backend/routers backend/services/einvoicing backend/integrations/einvoicing
rg --type py "wht|withholding|WHT|payment_id|gl_create_journal_entry|create_journal_entry" backend/routers/external.py backend/services
rg --type py "zakat|زكاة|base-items|ZakatCalculateRequest" backend/routers/system_completion backend/routers/governance.py backend/services
rg --type js "\bNumber\(|parseFloat\(|toFixed\(|toLocaleString\(|Math\.abs" frontend/src/pages/Taxes frontend/src/pages/einvoicing frontend/src/pages/Accounting/ZakatCalculator.jsx frontend/src/services/taxes.js
rg --type js "submitted_tax_due|submitted_grand_total|previewReturn|Idempotency-Key|createWhtTransaction|reprocess" frontend/src/pages/Taxes frontend/src/pages/einvoicing frontend/src/services

خطة التنفيذ (خمس مراحل):
المرحلة أ: رسم خريطة endpoints والواجهات وربطها بالمصدر المحاسبي: VAT returns, tax payments, WHT, Zakat, ZATCA outbox.
المرحلة ب: إزالة أي حساب مالي من الواجهة واستبداله بـ preview/detail backend responses، مع Decimal/fixed-point display فقط.
المرحلة ج: تأمين backend mutations: submitted values للـ returns، idempotency للـ create/post/reprocess/payment/WHT، branch/tenant/permission/fiscal guards، ورسائل i18n.
المرحلة د: فحص الترابطات العابرة: Sales/POS/Purchases → VAT → GL → returns، Supplier payments → WHT → GL، Zakat settings → posting، Sales invoice state → ZATCA outbox.
المرحلة هـ: تشغيل الاختبارات والبناء والفحص الآلي، وتوثيق أي استثناء.

اختبارات الإغلاق الإلزامية:
python scripts/check_backend_authority.py --module taxes
POSTGRES_PASSWORD=TestPassword123 SECRET_KEY=abcdefghijklmnopqrstuvwxyz1234567890 python -m pytest backend/tests/test_63_tax_constitution_hardening.py backend/tests/test_64_tax_module_integrations.py backend/tests/test_zatca_adapter_decimal_money.py backend/tests/test_audit_f024_eta_rounding.py -q
npm --prefix frontend run build

معايير القبول:
- check_backend_authority taxes = ALL CHECKS PASSED.
- لا توجد حسابات مالية في frontend scan إلا حالات non-money موثقة.
- tax return create/file يعيد الحساب ويرفض mismatch بـ 422.
- ZATCA reprocess لا يعمل بدون Idempotency-Key.
- WHT transaction لا يرسل payment_id فارغاً ولا ينشئ قيداً مكرراً.
- Zakat calculate/post مسجلان ومربوطان بالصلاحيات وGL.
- كل الرسائل الجديدة مترجمة عربي/إنجليزي.
- التقرير النهائي يذكر الملفات، الاختبارات، والمناطق الدستورية الحساسة.
```

---

## 12. CRM / Campaigns / Forecasts / Lead Scoring

### الحالة الحالية: 🔲 قيد التنفيذ / لم يبدأ بعد

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> التوقعات المالية وحساب قيمة الفرص البيعية (Forecasts) يجب ألا يتم حسابها في الواجهة لتلافي تضارب التقارير المالية والخطط التسويقية المعروضة للإدارة.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/campaign.py` و `backend/schemas/forecast.py`
- `backend/routers/crm/` (تشمل: opportunities.py, campaigns.py, core.py)
- `frontend/src/pages/CRM/`

رسالة الالتزام المقترحة (Commit Message):
`feat(crm): enforce backend calculation of sales pipeline forecasts and lead scoring, add idempotency to lead creation`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/crm/opportunities.py backend/schemas/campaign.py backend/schemas/forecast.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وCRM & Financial Forecasting Expert.

المهمة:
مراجعة وتأمين وحدة "إدارة علاقات العملاء والتوقعات المالية" (CRM & Sales Pipeline) لضمان صحة حساب قيمة الفرص البيعية والتوقعات بالـ Decimal والـ Backend حصراً.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب التوقعات والتقييم بالـ Decimal:
   - الـ Backend يحسب قيم الفرص التقديرية مضروبة بنسب النجاح الاحتمالية بالـ Decimal. يُمنع الحساب في الواجهة.
2. حماية المدخلات والـ Idempotency:
   - تفعيل Idempotency-Key على POST /leads و POST /opportunities لمنع تكرار إنشاء العملاء المحتملين وتشويه التحليلات.
3. التقييم الذكي (Lead Scoring):
   - محرك التقييم وتحديد النقاط للعميل المحتمل يتم بالكامل بالـ Backend بناءً على معايير مرجحة ومثبتة بالـ Database.

الملفات المستهدفة:
- الـ Schemas: backend/schemas/crm.py
- الـ Routers: backend/routers/crm/*
- الـ Frontend: frontend/src/pages/CRM/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/crm/
rg --type py "probability" backend/routers/crm/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص آلية حساب التوقعات والفرص في الواجهة وإزالتها.
المرحلة ب: تعديل Routers الـ CRM لضمان استخدام الـ Decimal بالكامل، وتفعيل الـ Idempotency-Key على Mutations.
المرحلة ج: تشغيل اختبارات الـ CRM والتأكد من اتساق الأرقام التقديرية مع لوحة القيادة.
```

---

## 13. Contracts / Subscriptions / Services / FSM

### الحالة الحالية: ✅ مطبق (الحالة في `check_backend_authority.py --module contracts`: 14/14 PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> العقود الدورية والاشتراكات تؤثر على الاعتراف بالإيرادات المؤجلة والمستحقة. حساب جداول الفوترة الدورية بالفرونت يسبب تباين القيود المحاسبية.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/schemas/contracts.py`
- `backend/routers/contracts.py` (ملف فردي)
- `backend/routers/fsm/contracts_renewal.py`
- `frontend/src/pages/Contracts/`

رسالة الالتزام المقترحة (Commit Message):
`feat(contracts): secure contract subscription billing cycles, enforce submitted_grand_total, and enable revenue recognition preview`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/contracts.py backend/routers/fsm/contracts_renewal.py backend/schemas/contracts.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وContract Billing & Deferred Revenue Specialist (IFRS 15).

المهمة:
مراجعة وتأمين وحدة "العقود والاشتراكات والفوترة الدورية" (Contracts & Subscriptions) لضمان أن الـ Backend هو المسؤول الحصري عن إصدار فواتير الاشتراكات وجداول الاعتراف بالإيرادات الدورية (IFRS 15).

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. حساب دورة الفوترة بالـ Decimal:
   - الـ Backend يحسب قيم الفواتير الدورية، الضرائب، والخصومات بالـ Decimal ويمنع حساب جداول الفوترة بالفرونت.
2. حماية العقود (submitted_grand_total):
   - لا يستخدم `submitted_grand_total` على سجل العقد الرئيسي إلا إذا كان الحفظ ينشئ مستنداً مالياً فورياً.
   - يستخدم `submitted_grand_total` في عمليات إنشاء فاتورة عقد/اشتراك أو تشغيل billing cycle عندما يكون هناك إجمالي نهائي راجع من preview.
   - الـ Backend يحسب دورات الفوترة، الضرائب، الخصومات، الإيراد المؤجل، وجدول الاعتراف بالإيراد بالـ Decimal.
3. المعاينة (Preview):
   - دعم /contracts/preview و /contracts/billing-cycle/preview لمعاينة الفواتير التي سيتم إصدارها وجداول الاعتراف بالإيرادات المؤجلة شهرياً بالـ Transaction Rollback.
4. منع التكرار (Idempotency):
   - تفعيل Idempotency-Key إجبارياً على عمليات تفعيل الفوترة الدورية وتجديد العقود ومنع تكرار إصدار الفاتورة الشهرية للعميل.

الملفات المستهدفة:
- الـ Schemas: backend/schemas/contracts.py عند وجودها
- الـ Routers: backend/routers/contracts.py و backend/routers/fsm/contracts_renewal.py
- الـ Frontend: frontend/src/pages/Contracts/* و frontend/src/pages/Services/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "float\(" backend/routers/contracts.py backend/routers/fsm/
rg --type py "deferred_revenue|revenue_recognition|billing_cycle|idempotency" backend/routers/contracts.py backend/routers/fsm/ backend/services/
rg --type js "toNumber\(|parseFloat|toFixed\(|billing|contract_total" frontend/src/pages/Contracts/ frontend/src/pages/Services/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: تحديد كيفية حساب الفوترة الدورية بالفرونت وتهيئة Schemas للعقود.
المرحلة ب: تعديل Routers العقود لإثبات جداول الفوترة الدورية وتفعيل الـ Preview بالـ Rollback.
المرحلة ج: تشغيل اختبارات دورة الفوترة والتحقق من صحة إيرادات الاشتراكات بالـ GL.
```

---

## 14. Reports / KPI / Dashboards / Analytics

### الحالة الحالية: ✅ مطبق (الحالة في `check_backend_authority.py --module reports`: 53/53 PASSED)

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> التقارير المالية والتحليلية هي مرآة الشركة للملاك والجهات الضريبية. يجب ألا تجري الواجهة أي عملية جمع أو فلترة حسابية، ويجب أن تعرض البيانات المستلمة من الـ Backend كما هي.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/reports/accounting_statements.py` و `backend/routers/reports/kpi.py`
- `frontend/src/pages/Reports/` و `frontend/src/pages/Analytics/`

رسالة الالتزام المقترحة (Commit Message):
`feat(reports): secure financial report endpoints, ensure zero calculation on frontend, enforce read-only pagination`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/reports/accounting_statements.py backend/routers/reports/kpi.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وFinancial Reporting & Analytics Specialist.

المهمة:
مراجعة وتأمين وحدة "التقارير المالية واللوحات التحليلية" (Reports & KPI) لضمان أن الـ Backend هو المصدر الحصري والمعادلات الحسابية بالـ Decimal تتم فقط داخل قاعدة البيانات والـ Backend، ولا يتم حساب أي إجمالي أو فروقات في الواجهة.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. عدم احتساب أي إجماليات في الواجهة (Zero Frontend Calculation):
   - الـ Frontend يستقبل المجاميع والبيانات جاهزة من السيرفر كـ Decimal ويعرضها كما هي (display-only).
   - يُمنع تماماً قيام الواجهة بجمع الأعمدة أو حساب نسب الربحية أو احتساب إجمالي الضرائب محلياً.
2. سرعة وموثوقية التقارير:
   - التقارير المالية الكبرى (قائمة الدخل، الميزانية العمومية، ميزان المراجعة) يجب أن تعتمد على حركات الـ GL الفعلية بالـ Decimal، وتدعم الفلترة السريعة بالفترات المالية والمراكز التكليفية المعتمدة بالـ Backend.
3. معايير الصفحات (Pagination):
   - دعم الترقيم والصفحات للتقارير ذات الحركات الضخمة (default 25 rows, capped at 100).
4. أمن البيانات والقراءة الآمنة:
   - الـ Endpoints للتقارير يجب أن تكون للقراءة فقط (Safe GET)، ومحمية بصلاحيات الموديول والشركة المناسبة.

الملفات المستهدفة:
- الـ Routers: backend/routers/reports/*
- الـ Frontend: frontend/src/pages/Reports/* و frontend/src/pages/Analytics/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "financial_statements" backend/routers/
rg --type js "reduce\(" frontend/src/pages/Reports/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: مراجعة صفحات التقارير في الواجهة والبحث عن أي عمليات جمع أو احتساب نسب محلياً ووصفها.
المرحلة ب: تعديل الـ Endpoints في الـ Backend لإرجاع كافة الإجماليات والمجاميع محسوبة وجاهزة بالـ Decimal.
المرحلة ج: إزالة عمليات الحساب والجمع من الواجهة وتشغيل الفحص التلقائي check_backend_authority.py.

نتيجة التنفيذ:
- تم تثبيت ملخصات Widgets التحليلية في الـ Backend (`summary`, `value_keys`, `pie_data`) وإزالة حسابات `reduce/Number/toFixed/toLocaleString` من شاشة Analytics Dashboard.
- تم تفعيل pagination لدفتر الأستاذ العام والـ Analytics widgets بقيمة افتراضية 25 وحد أقصى 100.
- تم إصلاح تكامل الـ Analytics materialized views لتطابق أعمدة الـ widgets وتدعم فلترة الفروع مع migration مخصص.
- تم سد فجوة تكامل دفتر الأستاذ العام: الواجهة ترسل `skip/limit` وتعرض أدوات pagination، والتصدير يستخدم helper الـ Backend بدون تقييد صفحات العرض.
- تم سد فجوة تحديث الكاش: refresh للتقارير صار مربوطاً بالـ tenant الحالي ويشمل Analytics MVs مع تحديث freshness metadata.
- تم توسيع `scripts/check_backend_authority.py` بوحدة `reports` وإضافة اختبار ثابت `test_reports_backend_authority.py`.
```

---

## 15. Approvals / Workflow / Audit / Security / Admin

### الحالة الحالية: ✅ مطبق (الحالة في `check_backend_authority.py --module security_admin`: 49/49 PASSED)

تم تنفيذ وتثبيت المسارات التالية:
- `POST /approvals/requests/{id}/action` يقبل `Idempotency-Key` إلزامياً، ويحفظ المفتاح على `approval_actions` مع فهرس unique جزئي.
- قرار الموافقة/الرفض/الإرجاع أصبح action-only من الواجهة، مع replay آمن لنفس idempotency key بدلاً من تكرار القرار.
- الـ Backend يتحقق أن المستخدم الحالي هو الموافق المحدد للخطوة الحالية، وتعرض قائمة pending فقط الطلبات التي يملك المستخدم حق اعتمادها.
- تم إصلاح مسار audit في الموافقات بحيث لا يظلّل كائن `Request` ولا يستدعي `log_activity` بوسيط خاطئ، وتعمل mutations الحساسة بـ `critical=True`.
- `POST /workflow/auto-approve` يتطلب `Idempotency-Key`، وعمليات تعديل SLA/conditions والتصعيد/الموافقة التلقائية تسجل audit event رسمي.
- `/workflow/analytics` يرجع الآن القيم top-level التي تعرضها صفحة الموافقات، بما فيها `approval_rate` المحسوبة في الـ Backend.
- عرض تفاصيل طلب الاعتماد في الواجهة يستخدم modal داخلياً بدلاً من route غير مسجل.
- تم توحيد aliases بين `approvals.action` و`approvals.approve` في الـ Backend والـ Frontend، و`approvals.manage` أصبح يغطي edit/action/approve.
- مسار governance القديم `POST /governance/approvals/sla/escalate` يكتب audit event رسمي ويفشل مغلقاً عند فشل audit enqueue.
- `GET /audit/logs` وواجهات security list الحساسة أصبحت بسقف pagination `le=100`.
- `audit_writer` و`audit_outbox_worker` لم يعودا يسجلان raw exception details، وoutbox worker يقرأ `company_settings` حسب schema الفعلي.
- تم إضافة فحص pre-flight للوحدة باسم `security_admin` واختبار static backend-authority مخصص.

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> الموافقات، الصلاحيات، وسجلات التدقيق هي طبقة التحكم فوق كل الوحدات. أي bypass هنا قد يسمح بترحيل مستندات مالية أو كشف PII أو تغيير إعدادات حساسة دون أثر تدقيقي.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/approvals.py`
- `backend/routers/audit.py`
- `backend/routers/security.py`
- `backend/schemas/approvals.py`
- `backend/services/audit_writer.py` و `backend/services/audit_sanitizer.py`
- `backend/services/audit_outbox_worker.py`
- `frontend/src/pages/Approvals/`
- `frontend/src/pages/Admin/` و `frontend/src/pages/Settings/`

رسالة الالتزام المقترحة (Commit Message):
`feat(security): enforce approval workflow integrity, audit hash chain, and admin guardrails`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/approvals.py backend/routers/audit.py backend/routers/security.py backend/services/audit_writer.py
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وSecurity/Audit Governance Engineer.

المهمة:
مراجعة وتأمين وحدة "الموافقات، سير العمل، التدقيق، الأمن، والإدارة" لضمان أن جميع قرارات الموافقة والصلاحيات وسجلات التدقيق تحكمها الـ Backend فقط، وأن الواجهة لا تستطيع تجاوز workflow أو توليد حالة موافقة محلياً.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. سير الموافقات:
   - الـ Backend يحدد المستويات، التسلسل، صلاحية الموافق، حالة المستند، وسبب الرفض.
   - لا يجوز للواجهة إرسال status نهائي مثل approved/posted كحقيقة، بل ترسل action فقط مثل approve/reject مع السبب.
   - Level N لا يوافق قبل Level N-1، والرفض يقفل/يرجع workflow حسب الإعدادات.
2. الصلاحيات والأمن:
   - كل endpoint محمي يحتاج `require_permission` أو guard مكافئ، مع branch/cost-center/sensitive permission حيث يلزم.
   - إعدادات security، API keys، roles، policies، وPII لا تُعرض أو تُعدل دون صلاحيات دقيقة.
3. التدقيق Audit:
   - كل mutation حساسة تكتب audit event عبر `audit_writer` أو helper رسمي.
   - لا تسجل أسرار، tokens، كلمات مرور، raw exceptions، أو private keys.
   - Hash chain وaudit_outbox لا يتم كسرهما أو تجاوزهما.
4. Idempotency:
   - إجراءات approve/reject/post/finalize الحساسة يجب أن تقبل Idempotency-Key أو تعتمد natural idempotency مثبتة، حتى لا يكرر المستخدم نفس القرار أو الترحيل.

الملفات المستهدفة:
- backend/routers/approvals.py
- backend/routers/audit.py
- backend/routers/security.py
- backend/services/audit_writer.py
- backend/services/audit_sanitizer.py
- backend/services/audit_outbox_worker.py
- frontend/src/pages/Approvals/*
- frontend/src/pages/Admin/*
- frontend/src/pages/Settings/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "raise HTTPException\\(detail=str\\(|print\\(|password|secret|token" backend/routers/approvals.py backend/routers/audit.py backend/routers/security.py backend/services/
rg --type py "require_permission|require_sensitive_permission|audit_writer|log_activity|idempotency" backend/routers/approvals.py backend/routers/security.py backend/routers/audit.py
rg --type js "approved|rejected|posted|permission|role|api_key|secret" frontend/src/pages/Approvals/ frontend/src/pages/Admin/ frontend/src/pages/Settings/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص workflow والـ guards والتأكد من عدم وجود public mutation غير مقصودة.
المرحلة ب: تثبيت backend-only approval decisions وaudit events وidempotency للقرارات الحساسة.
المرحلة ج: تشغيل اختبارات الصلاحيات، الموافقات، audit hash chain، وfrontend build.
```

---

## 16. Integrations / DMS / Notifications / Imports

### الحالة الحالية: 🔲 قيد التنفيذ / يحتاج فحص مستقل

> [!WARNING]
> **تحذير هام جدًا للنظام القائم:**
> التكاملات الخارجية، DMS، الإشعارات، والاستيراد قد تتعامل مع ملفات، أسرار، webhooks، وبيانات ضخمة. أي خطأ قد يؤدي إلى تسريب بيانات أو تكرار إرسال أو إدخال بيانات غير صالحة.

### متطلبات البدء والـ Git Commit
الملفات المطلوب تتبعها وتأكيد حفظها قبل أي تعديل:
- `backend/routers/integrations_admin.py`
- `backend/routers/data_import.py`
- `backend/routers/dms/`
- `backend/routers/notifications/`
- `backend/services/integration_keys_service.py`
- `backend/services/integration_retry_service.py`
- `backend/services/webhooks/dispatch.py`
- `backend/services/dms/`
- `backend/services/notifications/`
- `frontend/src/pages/dms/`
- `frontend/src/pages/notifications/`
- `frontend/src/pages/DataImport/`
- `frontend/src/pages/Settings/tabs/IntegrationKeysVault.jsx`
- `frontend/src/pages/Settings/IntegrationDLQ.jsx`

رسالة الالتزام المقترحة (Commit Message):
`feat(integrations): secure imports, DMS, notifications, webhooks, and integration retries`

### تعليمات الـ Rollback (التراجع عند حدوث أخطاء)
```bash
git checkout -- backend/routers/integrations_admin.py backend/routers/data_import.py backend/routers/notifications backend/routers/dms
git clean -fd
```

---

```text
أنت Senior ERP Software Architect وIntegration Reliability/Security Engineer.

المهمة:
مراجعة وتأمين وحدة "التكاملات، إدارة المستندات، الإشعارات، والاستيراد" لضمان أن الـ Backend يملك التحقق، التعقيم، deduplication، rate limiting، retry policy، وحماية الأسرار بالكامل.

قواعد غير قابلة للتفاوض (Non-Negotiable Guardrails):
1. التكاملات والأسرار:
   - مفاتيح التكاملات تحفظ مشفرة/مخفية ولا تعاد للواجهة كنص صريح.
   - webhooks توقع أو تتحقق من التوقيع حيث يلزم، ولا تسجل payloads تحتوي أسراراً أو PII دون sanitization.
2. Idempotency والتكرار:
   - إرسال webhooks، retry queues، import confirmations، notification sends، وأي external delivery يجب أن يستخدم idempotency أو dedupe key.
   - retry لا يكرر الأثر الخارجي إذا كان provider أكد النجاح سابقاً.
3. DMS والملفات:
   - التحقق من MIME/extension/size، فحص antimalware إن كان مفعلاً، وحماية path traversal.
   - التحميلات والروابط الموقعة لا تكشف مسارات محلية أو أسماء ملفات حساسة.
4. الاستيراد:
   - الـ Backend يتحقق من schema، ينفذ validation، ويرجع errors معقمة.
   - لا يتم إدخال batch جزئي بدون سياسة واضحة: all-or-nothing أو staging/review.
   - Import preview/staging يجب ألا يكتب إلى جداول الأعمال قبل confirm.
5. الإشعارات:
   - الـ Backend يحدد القنوات، القوالب، rate limits، unsubscribe، وحالة الإرسال.
   - الواجهة لا تحدد success/failure ولا تعيد إرسال الرسالة كحقيقة.

الملفات المستهدفة:
- backend/routers/integrations_admin.py
- backend/routers/data_import.py
- backend/routers/dms/*
- backend/routers/notifications/*
- backend/services/integration_keys_service.py
- backend/services/integration_retry_service.py
- backend/services/webhooks/dispatch.py
- backend/services/dms/*
- backend/services/notifications/*
- frontend/src/pages/dms/*
- frontend/src/pages/notifications/*
- frontend/src/pages/DataImport/*
- frontend/src/pages/Settings/*

مسح الأكواد ومطابقة الأنماط (rg scan commands):
rg --type py "secret|api_key|token|password|private_key|raise HTTPException\\(detail=str\\(|print\\(" backend/routers/integrations_admin.py backend/routers/data_import.py backend/routers/dms/ backend/routers/notifications/ backend/services/
rg --type py "idempotency|dedupe|retry|webhook|antimalware|sanitize|path traversal|UploadFile" backend/routers/ backend/services/
rg --type js "api_key|secret|token|localStorage|innerHTML|dangerouslySetInnerHTML|retry|import" frontend/src/pages/dms/ frontend/src/pages/notifications/ frontend/src/pages/DataImport/ frontend/src/pages/Settings/

خطة التنفيذ (ثلاث مراحل):
المرحلة أ: فحص الأسرار والملفات والاستيراد والإرسال الخارجي وتحديد نقاط التكرار أو التسريب.
المرحلة ب: تثبيت idempotency/dedupe، تعقيم الأخطاء، حماية الملفات، وتشفير/إخفاء مفاتيح التكامل.
المرحلة ج: تشغيل اختبارات imports/DMS/notifications/integrations وتشغيل frontend build.
```

---

## معايير الاكتمال العامة (Definition of Done)

لكل وحدة من الوحدات السابقة (سواء المكتملة أو قيد التنفيذ):

1. **التحقق التقني (check_backend_authority):**
   - للوحدات المدعومة في السكربت: تشغيل `python scripts/check_backend_authority.py --module <module_name>` يمر بنجاح تام (ALL CHECKS PASSED).
   - للوحدات غير المدعومة بعد: تشغيل أوامر `rg` الموجودة في قسم الوحدة وتوثيق النتائج، أو توسيع `scripts/check_backend_authority.py` قبل اعتبارها مكتملة.
2. **عزل الحسابات في الفرونت:**
   - إزالة أي حسابات مالية مؤثرة في الواجهة ووسم الحسابات التوضيحية البسيطة فقط بـ `// display-only`.
3. **الدقة المحاسبية (Decimal):**
   - استخدام الـ `Decimal` في كافة الحسابات والـ Schemas والـ Routers، ومنع استخدام الـ `float` نهائياً للمبالغ والنسب.
4. **حماية التكرار (Idempotency):**
   - تفعيل الـ `Idempotency-Key` بشكل إلزامي على جميع الـ Mutation Endpoints التي قد تكرر ترحيلاً مالياً أو أثراً تشغيلياً أو إرسالاً خارجياً حساساً.
5. **سلامة الأستاذ العام (GL Posting):**
   - أي مستند مالي يولد أثراً محاسبياً يجب أن يرحل حركته عبر `backend/services/gl_service.py` حصراً، ويُمنع كتابة القيود مباشرة في قواعد البيانات.
6. **سلامة الاختبارات وبناء المشروع:**
   - تشغيل targeted backend tests المتصلة بالوحدة، مع توثيق أي متغيرات بيئة لازمة مثل `POSTGRES_PASSWORD` و`SECRET_KEY`.
   - عند توفر بيئة كاملة ومستقرة: `cd backend && python -m pytest tests/ -q`
   - بناء مشروع Frontend يتم بلا أي أخطاء: `cd frontend && npm run build` أو `npm --prefix frontend run build`
