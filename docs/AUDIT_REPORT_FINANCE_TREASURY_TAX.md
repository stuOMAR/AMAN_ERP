# AMAN ERP — تقرير تدقيق وحدات Accounting/GL، Treasury + Bank Reconciliation، Taxes + ZATCA + Compliance

> **نوع التقرير:** تدقيق مخاطر تشغيلية ومالية (Read-only، بدون تعديل كود)
> **النطاق:** Backend (FastAPI) + Frontend (React)
> **المرجع:** ARCHITECTURE.md + SYSTEM_CONSTITUTION.md + AGENTS.md
> **التاريخ:** مايو 2026
> **الحالة:** قيد التحديث (تقرير حي يعدَّل أثناء التدقيق)

---

## 1. ملخص تنفيذي
النظام يعرض انضباطًا جيدًا في عدة طبقات حساسة (Decimal everywhere، Idempotency على JE/Reversal/Transfer، Fiscal lock fail-closed، GL ↔ Treasury موحّد عبر recalc_treasury_from_gl، multi-book، per-row savepoints في outbox relay)، ولكن هناك مخاطر عالية ومتوسطة فعلية:

**مخاطر عالية:**
1. **ZATCA outbox الجديد (`zatca_outbox` table) معطّل تشغيليًا:** الـ enqueue يحدث من `services/sales/invoice_state.py::transition()` لكن لا أحد يستدعي هذا الـ state machine في مسار إنشاء الفاتورة الفعلي (`invoices.py`)، والـ `process_batch` غير مسجَّل في `scheduler.py`. النتيجة: أي فاتورة في tenant سعودي مع `ZATCA_PHASE2_ENFORCE=False` تذهب فقط لمسار `einvoice_outbox` (vs `zatca_outbox`)، ومع `ZATCA_PHASE2_ENFORCE=True` يعمل المسار المتزامن لكن جدول `zatca_outbox` يبقى معطّلًا فعليًا.
2. **VAT report لا يحتسب `sales_credit_note` و `sales_debit_note`:** في `routers/finance/taxes/reports.py::get_vat_report` تُجمَع credit/debit notes لـ purchase فقط، بينما sales credit/debit notes تُتجاهل من ضريبة المخرجات. هذا يؤدي لإقرار VAT مغلوط للمبيعات.
3. **`fiscal_period_locks` يستخدم `ON CONFLICT (period_start, period_end)` بدون unique constraint موجود:** لا في `tenant_schema.py` ولا في Alembic. القيد قائم على الكود فقط، وأي محاولة إقفال فترة عبر `toggle_fiscal_period` ستفشل بـ 500 لأن الـ `ON CONFLICT` يحتاج index/constraint فريد، أو ستحدث duplicates إذا تم تجاوز الـ `ON CONFLICT`.
4. **Inflow/Outflow في تقرير cashflow يستخدم `float(..)`:** في `treasury.py::get_treasury_cashflow_report` (السطور حول `total_in = sum(float(r.total)...)`) — هذا يخالف Constitution Decimal-only للنقد ويسبب فروقات تقريب.
5. **`recalc_treasury_from_gl` يستخدم `accounts.balance` بدلًا من إعادة بناء من `journal_lines`:** التعليق يقول "self-heals any prior drift" لكن الفعلي يقرأ `accounts.balance` (وهو الذي يُحدَّث عبر `update_account_balance`)، فإذا حدث drift في `accounts.balance` نفسه (وهذا ممكن لأن opening balance writes في تتعامل عبر JE فقط ولكن `update_account_balance` هي الكاتب الوحيد) لن يُعالَج. أيضًا قراءة `accounts.balance_currency` ثم fallback إلى تقسيم balance/rate بسعر صرف "آخر سعر" يُدخل مخاطر FX غير محسوبة لحظيًا.

**مخاطر متوسطة:**
6. تقرير VAT والتقارير الضريبية تعتمد على `invoices.tax_amount` و `invoices.subtotal/discount` كمصدر حقيقة، وليس على `journal_lines`. هذا يخالف مبدأ "GL هو مصدر الحقيقة" وقد ينحرف عن GL إذا حصل reversal/void بدون تحديث `invoices` (مثلًا void يحدث reversal JE لكن لا يلمس `invoices.tax_amount`).
7. `auto_match` و `match_transaction` في bank reconciliation يقفلان `journal_lines` بـ `FOR UPDATE OF jl SKIP LOCKED` لكنهما لا يقفلان `bank_statement_lines` للمطابقة بنفس المستوى، مما يفتح race بين عدة workers على نفس bank line.
8. Treasury transfer ينشئ JE عبر `gl_create_journal_entry` بـ `idempotency_key`، لكن إذا تكرّر الطلب بعد crash قبل INSERT في `treasury_transactions`، السلوك التالي يعيد JE من gl_service ولكن يُصدر INSERT جديد على `treasury_transactions` (الفحص الأولي مرّ لأنه قائم على Idempotency-Key وليس على حقيقة وجود JE). جيد لأن المفتاح موحد، لكن إذا سقطت الـ key يمكن إنشاء حركتي خزينة لـ JE واحدة.
9. `attempt_clearance` في `zatca_clearance.py` يضع الفاتورة `pending_clearance` ويُنشئ صف `einvoice_outbox`، لكن tax/VAT reports لا تستثني الفواتير `rejected`/`pending_clearance` من إجمالي ضريبة المخرجات (تستثني فقط draft/cancelled). فاتورة sale في حالة `pending_clearance` ستُحتسب في VAT return قبل أن تَعتمدها ZATCA، مما يخالف الواقع التشغيلي.
10. WHT service و `external.py::create_wht_transaction` متناقضان: الـ service موجود (`post_payment_with_wht`) لكنه لا يُستدعى من أي مسار حقيقي، والـ endpoint في `external.py` ينشئ JE WHT منفصل عن سند الدفع، أي لا يحدث reduce حقيقي في AP/Bank — يُسجَّل WHT debit AP / credit WHT Payable فقط، بدون ربطه بسند الدفع الذي يفترض أن يخصم WHT من المبلغ الصافي. النتيجة: ازدواج في تخفيض AP إذا أُنشئ سند دفع لاحقًا بنفس القيمة الإجمالية.

**مخاطر منخفضة-متوسطة:**
11. `fiscal_lock.create_fiscal_lock_table()` وُسِم deprecated، ولكن الـ canonical في `database.create_all_tables()` لا يوجد به DDL لـ `fiscal_period_locks` المذكور في التعليق — الـ DDL في `tenant_schema.py` فقط. قد يقع tenant جديد بدون الجدول إذا لم يمر عبر tenant_schema.
12. Treasury delete account يفحص `current_balance` بمقارنة `abs(...) > 0.01` مع float — يجب Decimal.
13. `routers/finance/treasury.py::create_transfer` يقفل الحسابين الخزينيين بترتيب id لتجنب deadlock (جيد) لكنه يقفل الـ ledger account المرتبط (`accounts`) لا. JE post على نفس account من thread آخر قد يتداخل.
14. `validate_period` في `gl_service.py` يقرأ `company_settings.fiscal.allow_drafts_in_closed_period` بدون cache، مع كل JE — حمل بسيط لكنه يتراكم.

---

## 2. جدول Findings (مرتب حسب الخطورة)

| # | Severity | Module | File:Line | Problem | Business Impact | Reproduction | Suggested Fix | Test Needed |
|---|----------|--------|-----------|---------|-----------------|--------------|---------------|-------------|
| F-01 | Critical | ZATCA / Sales | `invoice_state.py` 135-155, `outbox.py` 44, `scheduler.py` | الـ `invoice_state.transition()` هو الموضع الوحيد الذي يستدعي `services.einvoicing.outbox.enqueue` لإضافة صفوف إلى `zatca_outbox`، لكنه يُستدعى فقط من `sales_cancellation.py` و `order_to_invoice.py` — وليس من المسار الفعلي لإنشاء الفاتورة في `routers/sales/invoices.py::create_invoice`. | فواتير ZATCA Phase 2 لا تُرسَل عبر مسار `zatca_outbox` إطلاقًا عند الإنشاء المباشر. الاعتماد فقط على `einvoice_outbox`. | إنشاء فاتورة sales عبر POST `/sales/invoices` على tenant SA. فحص جدول `zatca_outbox` — تجده فارغاً. | إما إزالة `outbox.py` وتوحيد على `einvoice_outbox`، أو ربط `enqueue` من `invoices.py` وتسجيل `process_batch` في scheduler. | E2E: invoice → outbox row → worker processes → submitted. |
| F-02 | Critical | Taxes / VAT | `reports.py` 78-94 | في `get_vat_report` تُحسب `sales_credit_note` و `sales_debit_note` كصفر، بينما الـ purchase تُحسب. الـ `sales_return` تُطرح لكن الـ  notes لا. | إقرار VAT الخاص بالمخرجات (Output VAT) مبالَغ فيه عند وجود إشعارات دائنة sales. دفع زيادة لـ ZATCA. | إنشاء فاتورة بـ 1000+150 VAT، ثم credit note بـ 200+30 VAT. الـ VAT Output يبقى 150. | إضافة `output_credit_notes` و `output_debit_notes` ودمجهم في `net_output_vat` بنفس منطق المدخلات. | pytest: VAT report property على إشعارات sales+purchase. |
| F-03 | Critical | Accounting | `fiscal.py` 656-661, `tenant_schema.py` 4776-4789 | `INSERT ... ON CONFLICT (period_start, period_end)` على `fiscal_period_locks`، لكن الـ DDL لا يحوي `UNIQUE` أو أي index فريد على هذين العمودين. | فشل runtime بـ 500 على إقفال فترة. أو created duplicate locks لنفس الفترة إذا أُزيل القيد. | إقفال فترة مالية يدويًا من Frontend → backend يُصدر الخطأ. | إضافة migration و DDL بـ `CREATE UNIQUE INDEX IF NOT EXISTS uq_fiscal_period_locks_period`. | pytest: إقفال نفس الفترة مرتين بدون 500/duplicate. |
| F-04 | High | Treasury Reports | `treasury.py` | استخدام `float()` للنقد في تقرير cashflow (`total_in`, `total_out`, `daily_trend`). | فروقات تقريب على أرقام كبيرة، ولا يطابق GL بدقة. | تقرير cashflow على حركات بأرقام عشرية صغيرة → الفرق التراكمي ≠ 0. | استبدال `float()` بـ `Decimal` و `_dec()` و quantize نهائي. | pytest: total_in/out == sum of jl. |
| F-05 | High | Treasury / GL | `treasury_balance.py` 55-93 | `recalc_treasury_from_gl` يقرأ `accounts.balance` و `accounts.balance_currency` ولا يُعيد البناء من `journal_lines` للـ healing الفعلي. | لن يعالج drift موجود بـ `accounts.balance`. مخاطر FX من استخدام أحدث سعر صرف. | إنشاء حساب أجنبي، استلام/دفع، ثم recalc → الرصيد المعروض ينقلب بسبب سعر الصرف. | إعادة البناء من `journal_lines` وتثبيت `rate` للحركة. | property test: recalc x N. |
| F-06 | High | Taxes / VAT | `reports.py` 60-89 | تقارير VAT تعتمد على `invoices.tax_amount`، وليس على `journal_lines` لحسابات VAT. | إذا حدث reversal لـ JE بدون تعديل invoice، يخالف GL وينحرف التقرير. | إنشاء JE تسوية يدوية ضد حساب VAT → التقرير لا يظهرها. | جمع التقرير من `journal_lines` لـ VAT أو تقاطع المصدرين. | reconciliation test. |
| F-07 | High | ZATCA / Tax | `zatca_clearance.py` 81-167 | VAT report يفلتر على status بدون استثناء `rejected` أو `pending_clearance` من ZATCA. | فاتورة مرفوضة تُحسب في ضريبة المخرجات كأنها صالحة. | إصدار فاتورة → رفض ZATCA → invoice status='posted' → تدخل VAT report. | فلترة الـ invoices بناءً على `zatca_clearance_status`. | E2E snippet reject. |
| F-08 | High | WHT | `external.py`, `wht_service.py` | API ينشئ WHT JE منفصل عن سند الدفع ولا يستدعي `post_payment_with_wht`. | تخفيض AP مضاعف وانحراف الأرصدة. | دفع 100 وتطبيق WHT 5% عبر endpoint → AP ينقص 105. | ربط WHT بسند الدفع دائمًا ومنع JE المنفصل غير المرتبط. | pytest: AP delta == gross. |
| F-09 | High | Bank Rec | `reconciliation.py` | `auto_match` يقفل journal lines لكنه لا يقفل `bank_statement_lines`. | race condition و duplicate matching للبنك لنفس الخط البنكي. | تشغيل auto_match متزامن مرتين. | `FOR UPDATE` على `bank_statement_lines` أيضًا. | concurrency test. |
| F-10 | Medium | Treasury Idem | `treasury.py` | Idempotency بـ `treasury_transactions` فقط. إذا نجح الـ JE وأخفق INSERT، الـ  retry سيكرر الـ treasury entry. | حركتا خزينة لنفس قيد الـ GL. | crash بعد JE، وقبل INSERT treasury، ثم اعادة الطلب. | إضافة UNIQUE على `idempotency_key` بالخزينة. | retry test. |
| F-11 | Medium | Tax/Compliance | `tax_engine.py` | default fall-through بالضريبة إذا ضريبة المنتج منتهية. | تطبيق ضريبة افتراضية خاطئة بصمت. | منتج ضريبته منتهية الصلاحية → يمر ضريبة فرع افتراضية. | Raising exception/warning. | unit test. |
| F-12 | Medium | GL / Currency | `gl_service.py` | `update_account_balance` يلوّث `accounts.balance_currency` إذا اختلف القيد عن عملة الحساب. | `balance_currency` يصبح لا معنى له بخليط العملات. | AR SAR وعملة القيد USD. | تقييد عملات متطابقة. | property test. |
| F-13 | Medium | Sales / Cancel | `invoices.py` | UPDATE `status`='cancelled' بدون `state` machine. | divergence بين state و status. | إلغاء فاتورة → stat = posted, status = cancelled. | استخدام state_machine للتحديث معاً. | regression. |
| F-14 | Medium | Reconciliation| `reconciliation.py` | `tolerance` رقم ثابت لا يحترم قيم العملات المختلفة. | تسامح بفوق الحد لعملات ذات قيمة أعلى. | حساب USD والـ tolerance 1.0 (وهي SAR أصلاً). | اعتبار العملة بـ tolerance. | unit test. |
| F-15 | Medium | Treasury | `treasury.py` | `abs(...) > 0.01` للمقارنة بـ float`. | Decimal drift. | حساب بـ 0.005 يُحذف. | استخدام Decimal. | - |
| F-16 | Medium | ZATCA/Outbox | `accounting_depth.py` | لا يوجد Idempotency-Key per row بـ `einvoice_outbox_relay`. | submission مرتين لـ ZATCA بـ UUIDs مختلفة للـ retry. | شبكة بطيئة وretry من الـ worker. | إضافة `idempotency_key` للـ request ZATCA. | mock adapter. |
| F-17 | Medium | Permissions | `treasury.py` (FE) | Frontend لا يمرر `treasury.manage` للـ UI. | 403 غير وديUX. | النقر على تحويل والخادم يرفضه متأخراً. | FE guards + withPermission. | - |
| F-18 | Medium | Reports | `accounting_statements.py` | Net income يجمع `posted` ولا يستثني الـ manual reversals بدون tag. | مبالغ معروضة مرتين (ربح/خسارة) للreversal اليدوي. | JE + Reversal → postedx2. | حجب `source='reversal'` + Original ID. | test. |
| F-19 | Medium | Recurring JE | `recurring_je_service.py`| `_compute_amount` يجمع debit+credit. | - | - | توثيق. | - |
| F-20 | Medium | Frontend Prms | `treasury.js` | لا يفحص الصلاحية بـ UI (createExpense). | - | - | تحديث frontend guards. | - |
| F-21 | Low | Multibook | `multibook_service.py`| لا يعمل rollback إذا فشل ledger من الـ ledgers الإضافية. | عدم اتساق الـ multibooks. | transaction تنجح بـ L1 وتفشل بـ L2. | all-or-nothing rollback. | concurrency. |
| F-22 | Low | Frontend Sales | `App.jsx` | UI يرسل status='posted' عوضاً عن draft في مسار الـ  JE. | UX سيئ. | - | تعديل القيمة الافتراضية. | - |
| F-23 | Low | i18n | Multiple | استخدام `i18n_message` بدون تمرير `request`. | رسائل بالإنكليزية. | - | - | - |
| F-24 | Low | Decimal hygiene | `treasury.py` | `float()` للـ opening balance (create account). | خطر precision. | - | استخدام `Decimal`. | - |

---

### 6.4 GL ↔ Reports
(سيتم التحديث لاحقاً)

### 6.5 Treasury ↔ Bank Reconciliation
(سيتم التحديث لاحقاً)

### 6.6 Tax Returns ↔ Invoices/Credit Notes/Returns
(سيتم التحديث لاحقاً)

---

## 7. اختبارات مقترحة

(سيتم التحديث لاحقاً بناءً على تقدم التقرير)

## 3. Endpoints مفقودة أو غير مستخدمة

### 3.1 Endpoints موثَّقة في ARCHITECTURE.md لكن غير مشغَّلة فعليًا
| Endpoint / Component | الحالة | تفاصيل |
|----------------------|--------|---------|
| `zatca_outbox` worker (كل 5 ثوانٍ) | غير مشغَّل | `services/einvoicing/outbox.py::start_worker()` مجرد banner يطبع log line. `process_batch` غير مسجَّل في `scheduler.py`. |
| `outbox.enqueue` | غير مرتبط بمسار الإنتاج | يُستدعى فقط من `invoice_state.transition` و `sales_cancellation/order_to_invoice`. مسار `invoices.py::create_invoice` يكتب invoices مباشرة. |
| `wht_service.post_payment_with_wht` | مكتوب وغير مستدعى | لا أحد يستدعيه؛ المنطق الفعلي للـ WHT يحدث في `external.py::create_wht_transaction` بمنطق مختلف ومخالف (F-08). |

### 3.2 Endpoints موجودة لكن بدون UI/Frontend client
| Endpoint Backend | Frontend client؟ | تأثير |
|------------------|------------------|-------|
| `POST /api/finance/accounting-depth/einvoice/outbox/relay` | ❌ لا يوجد | وثَّقه ARCHITECTURE كـ "operations API"؛ يحتاج curl للتشغيل. |
| `GET /api/finance/accounting-depth/einvoice/outbox` | ❌ لا يوجد | لا توجد صفحة عرض للـ outbox status في Frontend. |
| `POST /api/finance/accounting-depth/ecl/compute` | ❌ لا يوجد | تشغيل ECL provision via API فقط. |
| `POST /api/finance/accounting-depth/nrv/run` | ❌ لا يوجد | - |
| `POST /api/finance/accounting-depth/cgu` | ❌ لا يوجد | - |
| `POST /api/finance/accounting-depth/ifrs15/contracts/recognise`| ⚠ جزئي | `accounting.js` يستدعي `/accounting/revenue-recognition/...` (مسار مختلف). |
| `POST /api/petty-cash/funds/replenish/disburse` | ❌ غير ظاهر | مذكور في ARCHITECTURE لكن `treasury.js` لا يحوي endpoints `petty-cash`. |
| `POST /api/finance/bank-feeds/import` (MT940/CAMT) | ❌ لا يوجد | Frontend يستخدم `/treasury/bank-import` (مسار CSV قديم). |
| `POST /api/finance/subscriptions/dunning/scan/...` | ❌ لا يوجد | dunning operations بدون UI. |
| `POST /api/reports/cache/refresh` | ❌ لا يوجد | refresh من ops/curl فقط. |
| `GET /api/reports/period_stats` | ❌ لا يوجد | period stats لا تظهر في dashboard. |

### 3.3 Endpoints من Frontend لكنها لم تُسجَّل على Backend
* `POST /treasury/bank-import`: ✅ موجود في `treasury.py` (legacy).
* `POST /accounting/zakat/calculate`: يحتاج تأكيد وجوده — لم يظهر في الفحص الأولي.
* `POST /accounting/fx-revaluation`: يحتاج تأكيد — `fx.py` فيه FX endpoints مع prefix مختلف.
* `POST /accounting/provisions/bad-debt` / `leave`: يحتاج تأكيد.

### 3.4 Endpoints معطَّلة أو متضاربة
* `POST /api/treasury/transactions/expense`: تحوّل إلى shim يفوّض `expenses.py::create_expense` لكنه لا يفحص `treasury.manage` بعد التحويل سياسة الموافقة قد تختلف.
* مسارات Reconciliation: `/reconciliation/{id}/auto-match` تتطلب `reconciliation.create`، بينما `finalize` يتطلب `finance.reconciliation.finalize`.

---

## 4. Frontend services/pages تستدعي API غير مطابق

| Frontend Caller | API Path المرسَل | المسار الفعلي على Backend | حالة المطابقة | ملاحظة |
|-----------------|------------------|---------------------------|---------------|--------|
| `treasury.js::importBankStatement` | `POST /treasury/bank-import` | `treasury.py` | ✅ مطابق (لكن legacy) | لا يستفيد من CAMT.053 |
| `accounting.js::list` | `GET /accounting/accounts` | `accounts.py` | ✅ مطابق | - |
| `accounting.js::voidJournalEntry` | `POST /journal-entries/{id}/void`| `journal.py` | ✅ مطابق | يتطلب sensitive auth، و Frontend لا يفحص. |
| `taxes.js::getVATReport` | `GET /taxes/vat-report` | `reports.py` | ✅ مطابق | ناقص منطقياً (F-02) |
| `taxes.js::createPayment` | `POST /taxes/payments` | `payments.py` | ✅ مطابق | - |
| `accounting.js::recognizeRevenue` | `POST /.../recognize` | `revenue_recognition.py` | ⚠ يحتاج تأكيد | تعارض مع `ifrs15`. |
| `external.js::generateZatcaQR` | `POST /external/zatca/generate-qr`| `external.py /qr` | ⚠ اختلاف بسيط | فحص schema name. |
| `external.js::createWhtTransaction`| `POST /external/wht/transactions`| `external.py` | ✅ مطابق | مكسور منطقياً (F-08) |

### 4.1 صفحات Frontend بدون مكوّن backend ضمن النطاق
* `ZakatCalculator.jsx`: /accounting/zakat (لم يُفحص).
* `IntercompanyTransactions.jsx`: /accounting/intercompany/... (موجود في `intercompany_v2.py`).
* `FXGainLossReport.jsx`: /reports/accounting/fx-gain-loss (يحتاج تأكيد).

---

## 5. صلاحيات غير متطابقة بين Frontend وBackend

| Function | Frontend Permission Check | Backend Permission | حالة |
|----------|---------------------------|--------------------|------|
| Treasury transfer | لا فحص محلي | `treasury.manage` | ❌ FE لا يحرس |
| Treasury expense | لا فحص محلي | `treasury.manage` | ❌ FE لا يحرس |
| Account list | لا فحص محلي | `treasury.view` | ✅ مقبول |
| Reconciliation match | لا فحص محلي | `reconciliation.create` | ❌ FE لا يحرس |
| Reconciliation finalize | لا فحص محلي | `finance.reconciliation.finalize` (critical)| ❌ FE لا يحرس + تباين اسم |
| Journal entry create | route guard `accounting.edit` | `accounting.edit` (critical)| ⚠ لا يستدعي 2FA |
| Fiscal close | لا فحص محلي | `accounting.manage` | ❌ FE لا يحرس |

**Sensitive Permissions غير محصَّلة في الـ UI:** `accounting.edit` وغيرها حساسة، تتطلب 2FA/re-auth. الـ Frontend يرفض الخطأ `403` فقط دون إظهار flow المصادقة.

---

## 6. مخاطر ترابط البيانات (Data Dependency Risks)

### 6.1 GL ↔ Treasury
* **`current_balance` drift**: يعتمد على `accounts.balance` وليس المجموع الفعلي لحركات اليومية (F-05).
* **Missing unique link**: `gl_account_id` في `treasury_accounts` لا يُفحص كـ  `UNIQUE` (قد يربط أكثر من حساب خزينة لنفس الـ GL).
* **Inactive account reconnect**: حذف حساب خزينة يلغي تنشيط `accounts` لكن لا يفصل المعرف؛ إعادة الإنشاء قد ترتبط بحساب غير نشط.
* **Internal transfer FX**: استخدام "آخر سعر صرف" في التحويل الداخلي بين عملتين مختلفتين بدل cross-rate اللحظي.

### 6.2 GL ↔ Tax
* **VAT report detachment**: قراءة من `invoices` بدل `journal_lines` (F-06).
* **Payment exceeding balance**: دفعات الضريبة لا تفحص سقف المستحق بدقة صارمة (`tax_return_id` links).
* **WHT AP Detachment**: قيد الخصم منفصل عن الدفع (F-08).
* **Tax rate gap**: إغلاق إصدار ضريبة قد يترك فترة يوم بدون ضريبة افتراضية.

### 6.3 GL ↔ ZATCA
* فاتورة rejected من ZATCA تترك القيد (JE) كما هو `posted` (لا يُعكس).
* `attempt_clearance` يحدّث الفاتورة فقط ولا يتدخل بالحسابات.

---

## 7. اختبارات مقترحة
(يُستكمل بالتفصيل لاحقاً بناءً على الأولويات)
