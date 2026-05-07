# تحليل وحدات البيانات الرئيسية - نظام AMAN ERP

> **السيناريو الأساسي:** شركة "الخليج القابضة" الدولية - 3 فروع (الرياض SAR، القاهرة EGP، دبي AED)
>
> **عملة التقارير الموحدة:** SAR (عملة الفرع الرئيسي)
>
> **تم الاستخراج من:** `backend/models/domain_models/*.py` (91+ ORM Model) + `routers/roles.py` (23 دور + صلاحيات)

---

## 1. قائمة وحدات البيانات الرئيسية (48+ وحدة)

### 1.1 الهيكل التنظيمي والجغرافي

| # | الجدول | الملف | الحقول الإلزامية | الحقول الاختيارية الرئيسية | العلاقات | تعدد العملات/الفروع |
|---|--------|------|-----------------|--------------------------|---------|-------------------|
| 1 | **branches** (الفروع) | `core_accounting.py:24` | `branch_name` | `branch_code`(unique), `branch_name_en`, `branch_type`, `address`, `city`, `country`, `country_code`, `default_currency`(3), `phone`, `email`, `manager_id→company_users`, `is_default`, `is_active` | Departments, Employees, Warehouses, Invoices, Expenses, JournalEntries, Budgets, Assets | كل فرع له `default_currency`. الفرع `is_default=True` هو المرجع للتقارير الموحدة |
| 2 | **departments** (الأقسام) | `hr_core_payroll.py:18` | `department_name` | `department_code`(unique), `name_en`, `parent_id→departments`(شجرة), `branch_id→branches`, `manager_id`, `description`, `is_active` | CostCenters, Employees, Budgets, Positions | شجرة هرمية داخل الفرع |
| 3 | **employee_positions** (المسميات) | `hr_core_payroll.py:32` | `position_name` | `position_code`(unique), `name_en`, `department_id→departments`, `level`, `description`, `is_active` | Employees | - |
| 4 | **warehouses** (المستودعات) | `core_business.py:90` | `warehouse_name` | `warehouse_code`(unique), `name_en`, `location`, `address`, `city`, `country`, `branch_id→branches`, `manager_id→company_users`, `is_default`, `is_active` | Inventory, DeliveryOrders | تابع لفرع |
| 5 | **cost_centers** (مراكز تكلفة) | `finance_costing.py:7` | `center_name` | `center_code`(unique), `name_en`, `department_id→departments`, `manager_id→employees`, `budget`, `currency`(3), `is_active` | JournalLines, Budgets, CostCenterBudgets | له عملة خاصة |
| 6 | **user_branches** (ربط مستخدم-فرع) | `core_business.py:8` | - | `user_id→company_users`, `branch_id→branches` | الآلية الأساسية لتقييد الصلاحيات بالفروع | Many-to-Many |
| 7 | **entity_groups** (مجموعات كيانات) | `intercompany.py:11` | `name`, `company_id`, `group_currency`, `consolidation_level` | `parent_id→entity_groups` | IntercompanyTransactions | للتوحيد والإقصاءات |

### 1.2 الموارد البشرية

| # | الجدول | الملف | الحقول الإلزامية | الحقول الاختيارية الرئيسية | العلاقات |
|---|--------|------|-----------------|--------------------------|---------|
| 8 | **employees** (الموظفون) | `hr_core_payroll.py:45` | `first_name`, `last_name` | `employee_code`(unique), `name_en`, `email`, `phone`, `mobile`, `gender`, `birth_date`, `hire_date`, `termination_date`, `department_id`, `position_id`, `branch_id`, `manager_id→employees`(ذاتي), `employment_type`, `status`, `salary`(18,4), `housing_allowance`, `transport_allowance`, `other_allowances`, `hourly_cost`, `currency`(3), `user_id→company_users`, `account_id→accounts`, `bank_account_id→treasury_accounts`, `tax_id`, `social_security`, `address`, `emergency_contact`, `nationality`, `is_saudi`, `eos_eligible`, `eos_amount`, `iqama_number`, `iqama_expiry`, `passport_number`, `sponsor`, `version` |
| 9 | **company_users** (مستخدمو النظام) | `core_accounting.py:8` | `username`(unique), `password` | `email`(unique), `full_name`, `role`(50), `permissions`(JSONB), `is_active`, `last_login` | Employee(1:1), UserBranches, JournalEntries, Approvals |
| 10 | **roles** (الأدوار) | `security_reporting.py:8` | `role_name`(unique) | `role_name_ar`, `description`, `permissions`(JSONB), `is_system_role` | CompanyUser.role → Role.role_name |
| 11 | **user_2fa_settings** | `security_reporting.py:68` | `user_id`(unique) | `secret_key`, `is_enabled`, `backup_codes`, `verified_at` | - |
| 12 | **user_sessions** | `security_reporting.py:82` | `user_id` | `token_hash`, `ip_address`, `user_agent`, `login_time`, `last_activity`, `is_active` | - |
| 13 | **attendance** | `hr_core_payroll.py:92` | `date` | `employee_id`, `check_in`, `check_out`, `status`, `notes` | - |
| 14 | **leave_requests** | `hr_core_payroll.py:120` | `leave_type`, `start_date`, `end_date` | `employee_id`, `reason`, `status`, `approved_by→company_users`, `attachment_url` | - |
| 15 | **employee_loans** | `hr_core_payroll.py:104` | `amount`, `monthly_installment` | `employee_id`, `total_installments`, `paid_amount`, `start_date`, `status`, `approved_by→company_users`, `branch_id` | - |
| 16 | **salary_structures** | `hr_core_payroll.py:134` | `name` | `name_en`, `base_type`, `is_active` | SalaryComponents |
| 17 | **salary_components** | `hr_core_payroll.py:145` | `name`, `component_type`, `calculation_type` | `name_en`, `percentage_of`, `percentage_value`, `formula`, `is_taxable`, `is_gosi_applicable`, `is_active`, `sort_order`, `structure_id` | EmployeeSalaryComponents |
| 18 | **employee_salary_components** | `hr_core_payroll.py:163` | - | `employee_id`, `component_id`, `amount`, `is_active`, `effective_date` | - |
| 19 | **payroll_periods** | `hr_core_payroll.py:7` | `name`, `start_date`, `end_date` | `payment_date`, `status` | PayrollEntries |
| 20 | **payroll_entries** | `hr_core_payroll.py:174` | - | `period_id`, `employee_id`, `basic_salary`, `housing/transport/other_allowances`, `overtime_amount`, `gosi_employee/employer_share`, `loan_deduction`, `deductions`, `net_salary`, `currency`, `exchange_rate`, `net_salary_base`, `status` | - |

### 1.3 الشؤون المالية والمحاسبية

| # | الجدول | الملف | الحقول الإلزامية | الحقول الاختيارية الرئيسية | العلاقات |
|---|--------|------|-----------------|--------------------------|---------|
| 21 | **accounts** (دليل الحسابات) | `core_accounting.py:45` | `account_number`(unique), `name`, `account_type` | `account_code`, `name_en`, `parent_id→accounts`(شجرة 5 مستويات), `is_header`, `balance`(18,4), `balance_currency`(18,4), `currency`(3), `is_active` | JournalLines, GL Mappings, TreasuryAccounts |
| 22 | **currencies** (العملات) | `finance_currency_bank.py:7` | `code`(3, unique), `name` | `name_en`, `symbol`(10), `is_base`, `current_rate`(18,6), `is_active` | ExchangeRates, Branches, Employees, Parties, Invoices |
| 23 | **exchange_rates** (أسعار الصرف) | `finance_currency_bank.py:22` | `rate_date`, `rate`(18,6) | `currency_id→currencies`, `source`, `created_by` | - |
| 24 | **tax_rates** (نسب الضرائب) | `finance_treasury_tax.py:61` | `tax_name` | `tax_code`(unique), `name_en`, `rate_type`, `rate_value`(10,4), `country_code`(5), `jurisdiction_code`(2), `description`, `effective_from/to`, `is_active` | TaxGroups, BranchTaxSettings, Invoices |
| 25 | **tax_regimes** (الأنظمة الضريبية) | `finance_treasury_tax.py:131` | `country_code`(2), `tax_type`, `name_ar`, `name_en` | `default_rate`(10,4), `is_required`, `applies_to`, `filing_frequency`, `is_active` | BranchTaxSettings |
| 26 | **tax_groups** (المجموعات الضريبية) | `finance_treasury_tax.py:80` | `group_name` | `group_code`(unique), `name_en`, `description`, `tax_ids`(JSONB), `is_active` | - |
| 27 | **branch_tax_settings** | `finance_treasury_tax.py:147` | `branch_id`, `tax_regime_id` | `is_registered`, `registration_number`, `custom_rate`(10,4), `is_exempt`, `exemption_reason`, `exemption_certificate`, `exemption_expiry`, `is_active` | - |
| 28 | **company_tax_settings** | `finance_treasury_tax.py:165` | `country_code`(2) | `is_vat_registered`, `vat_number`, `zakat_number`, `tax_registration_number`, `commercial_registry`, `fiscal_year_start`, `default_filing_frequency`, `zatca_phase`, `is_active` | - |
| 29 | **treasury_accounts** (خزينة/بنوك) | `core_business.py:70` | `name`, `account_type` | `name_en`, `currency`(3), `current_balance`(20,4), `gl_account_id→accounts`, `branch_id→branches`, `bank_name`, `account_number`, `iban`, `allow_overdraft`, `is_active` | TreasuryTransactions, BankReconciliations, Payments |
| 30 | **fiscal_years** (السنوات المالية) | `finance_fiscal_zakat.py:8` | `year`(unique), `start_date`, `end_date` | `status`, `retained_earnings_account_id→accounts`, `closing_entry_id→journal_entries` | FiscalPeriodLocks |
| 31 | **fiscal_period_locks** | `finance_fiscal_zakat.py:25` | `period_name`, `period_start`, `period_end` | `is_locked`, `locked_by→company_users`, `reason` | - |
| 32 | **zakat_calculations** | `finance_fiscal_zakat.py:41` | `fiscal_year`(unique) | `method`, `zakat_base`, `zakat_rate`(default=2.5), `zakat_amount`, `details`(JSONB), `status`, `journal_entry_id`, `notes` | - |
| 33 | **budgets** (الموازنات) | `finance_budgets.py:7` | `name` | `budget_code`(unique), `fiscal_year`, `branch_id→branches`, `department_id`, `cost_center_id`, `budget_type`, `status`, `total_budget`(18,4), `used_budget`, `remaining_budget`, `start/end_date`, `version` | BudgetItems, BudgetLines |
| 34 | **costing_policies** | `finance_costing.py:34` | `policy_name`, `policy_type` | `description`, `is_active`, `created_by/updated_by` | CostingPolicyDetails |
| 35 | **company_settings** | `core_business.py:157` | `setting_key`(100, unique) | `setting_value`(Text) | Key-value store: `default_currency`, `invoice_prefix`, `acc_map_*` GL mappings, `decimal_places`, `timezone` |
| 36 | **recurring_journal_templates** | `finance_cashflow.py:97` | `name`, `frequency`, `start_date`, `next_run_date` | `reference`, `end_date`, `is_active`, `auto_post`, `branch_id`, `currency`, `exchange_rate`, `run_count`, `max_runs` | RecurringJournalLines |
| 37 | **intercompany_transactions_v2** | `intercompany.py:24` | `source_entity_id`, `target_entity_id`, `transaction_type`, `source_amount`, `source_currency`, `target_amount`, `target_currency`, `exchange_rate`, `elimination_status` | `source/target_journal_entry_id`, `elimination_journal_entry_id` | IntercompanyAccountMappings, EntityGroups |
| 38 | **intercompany_account_mappings** | `intercompany.py:54` | `source_entity_id`, `target_entity_id`, `source_account_id`, `target_account_id` | - | EntityGroups |
| 39 | **payment_vouchers** | `finance_cashflow.py:7` | `voucher_number`, `voucher_type`, `voucher_date`, `party_type`, `party_id`, `amount`, `payment_method` | `branch_id`, `bank_account_id`, `treasury_account_id`, `check_number`, `reference`, `notes`, `currency`, `exchange_rate`, `status` | Payments, PaymentAllocations |
| 40 | **payments** | `finance_cashflow.py:33` | `payment_type`, `payment_date`, `amount` | `customer_id`, `supplier_id`, `currency`, `exchange_rate`, `payment_method`, `bank_account_id`, `reference`, `check_number`, `status` | PaymentAllocations |

### 1.4 العمليات التجارية

| # | الجدول | الملف | الحقول الإلزامية | الحقول الاختيارية الرئيسية | العلاقات |
|---|--------|------|-----------------|--------------------------|---------|
| 41 | **parties** (أطراف التعامل) | `core_business.py:34` | `name` | `party_type`, `party_code`(unique), `name_en`, `email`, `phone`, `mobile`, `fax`, `website`, `address`, `city`, `country`, `tax_number`, `commercial_register`, `tax_exempt`, `currency`(3), `is_customer`, `is_supplier`, `party_group_id→party_groups`, `branch_id→branches`, `payment_terms`, `credit_limit`(18,4), `current_balance`(18,4), `status`, `version` | Invoices, Contracts, Projects |
| 42 | **party_groups** | `core_business.py:17` | `group_name` | `group_code`(unique), `name_en`, `branch_id`, `discount_percentage`(5,2), `effect_type`, `payment_days`, `description`, `status` | Parties |
| 43 | **customers** (العملاء) | `sales_customers_delivery.py:7` | `customer_name` | `customer_code`(unique), `name_en`, `customer_type`, `tax_number`, `commercial_register`, `email`, `phone`, `mobile`, `address`, `city`, `country`, `customer_group_id→customer_groups`, `branch_id`, `payment_terms`, `credit_limit`, `current_balance`, `currency`, `price_list_id→customer_price_lists`, `tax_exempt`, `status`, `notes` | Contacts, BankAccounts, PriceLists, Transactions, Receipts, Balance |
| 44 | **suppliers** (الموردون) | `procurement_suppliers.py:136` | `supplier_name` | `supplier_code`(unique), `name_en`, `tax_number`, `commercial_register`, `email`, `phone`, `mobile`, `address`, `city`, `country`, `supplier_group_id`, `branch_id`, `payment_terms`, `credit_limit`, `current_balance`, `currency`, `tax_exempt`, `status`, `notes` | Contacts, BankAccounts, Payments, Transactions, Balance, Ratings |
| 45 | **projects** (المشاريع) | `projects_core.py:8` | `project_name` | `project_code`(unique), `name_en`, `description`, `customer_id`, `party_id→parties`, `project_type`, `status`, `start/end_date`, `planned_budget`(18,4), `actual_cost`(18,4), `progress_percentage`(5,2), `manager_id→employees`, `branch_id`, `contract_type`, `retainer_amount`(18,4), `billing_cycle`, `version` | Tasks, Budgets, Expenses, Revenues, Documents, ChangeOrders |
| 46 | **contracts** (العقود) | `projects_contracts_expenses.py:8` | `contract_number`(unique), `start_date` | `party_id→parties`, `contract_type`, `status`, `end_date`, `billing_interval`, `next_billing_date`, `total_amount`(18,4), `currency`(3), `notes`, `version` | ContractItems |
| 47 | **assets** (الأصول) | `assets_core.py:21` | `name` | `code`(unique), `type`, `purchase_date`, `cost`(18,4), `residual_value`(18,4), `life_years`, `currency`(3), `depreciation_method`, `status`, `branch_id`(FK), `version` | AssetCategory, DepreciationSchedule, Disposal, Impairment, Insurance, Maintenance, Revaluation |
| 48 | **asset_categories** | `assets_core.py:7` | `category_name` | `category_code`(unique), `name_en`, `description`, `depreciation_rate`(5,2), `useful_life`, `parent_id→asset_categories` | Assets |

### 1.5 المنتجات والمخزون

| # | الجدول | الملف | الحقول الإلزامية | الحقول الاختيارية الرئيسية |
|---|--------|------|-----------------|--------------------------|
| 49 | **product_categories** | `inventory_core.py:7` | `category_name` | `category_code`(unique), `name_en`, `parent_id→product_categories`(شجرة), `branch_id` |
| 50 | **product_units** | `inventory_core.py:26` | `unit_name` | `unit_code`(unique), `name_en`, `abbreviation`, `base_unit_id→product_units`, `conversion_factor`(10,6) |
| 51 | **products** | `inventory_core.py:40` | `product_name` | `product_code`(unique), `name_en`, `product_type`, `category_id`, `unit_id`, `barcode`, `cost_price`(18,4), `selling_price`(18,4), `tax_rate`(default=15), `is_taxable`, `sku`(unique), `reorder_level`, `reorder_quantity`, `has_batch/serial/expiry_tracking`, `has_variants`, `is_kit`, `version` |
| 52 | **inventory** | `inventory_core.py:85` | - | `product_id`, `warehouse_id`, `quantity`(18,4), `reserved_quantity`, `available_quantity`, `average_cost`(18,4) |

### 1.6 الأمن والاعتمادات والسجلات

| # | الجدول | الملف | الحقول الإلزامية |
|---|--------|------|-----------------|
| 53 | **approval_workflows** | `security_approvals.py:8` | `name`, `document_type` |
| 54 | **approval_requests** | `security_approvals.py:23` | `document_type`, `document_id` |
| 55 | **approval_actions** | `security_approvals.py:46` | `step`, `action` |
| 56 | **audit_log** | `security_admin_reporting.py` | `table_name`, `record_id`, `action` |
| 57 | **security_events** | `security_reporting.py:41` | `event_type` |
| 58 | **login_attempt** | `security_comms.py` | - |
| 59 | **password_history** | `security_comms.py` | - |
| 60 | **webhooks** | `security_reporting.py:110` | `name`, `url`, `events` |
| 61 | **scheduled_reports** | `security_reporting.py:21` | `report_type`, `frequency`, `recipients` |

---

## 2. مخطط العلاقات

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        COMPANY_SETTINGS                                      │
│       (default_currency, fiscal_year_start, GL account mappings)             │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────────────┐
│   CURRENCIES      │  │   FISCAL_YEARS   │  │  TAX_REGIMES → TAX_RATES         │
│ code, name, rate  │  │ year, start/end  │  │ country, tax_type, rate, filing  │
└──────┬───────────┘  └──────────────────┘  └──────────────┬──────────────────┘
       │                                                   │
       │            ┌──────────────────────────────────────┘
       │            │
       │   ┌────────▼──────────┐
       │   │  EXCHANGE_RATES    │
       │   │ currency, date, rate│
       │   └───────────────────┘
       │
       │   ┌═══════════════════════════════════════════════════════════════┐
       │   ║                    BRANCHES (الفروع)                          ║
       │   ║  id, branch_code, branch_name, country, default_currency,     ║
       │   ║  is_default (الفرع الرئيسي = عملة التقارير الموحدة)           ║
       │   ╚═══════╦═══════════╦═══════════╦═══════════╦═══════════════════╝
       │           │           │           │           │
       │   ┌───────▼──┐  ┌─────▼─────┐ ┌──▼────────┐ ┌▼──────────────┐
       │   │DEPARTMENTS│  │WAREHOUSES │ │  BUDGETS  │ │TREASURY_ACCTS │
       │   │(شجرة هرمية)│  │(مستودعات) │ │ (موازنات) │ │(خزينة وبنوك)  │
       │   └─────┬─────┘  └───────────┘ └───────────┘ └───────┬───────┘
       │         │                                             │
       │   ┌─────▼──────────┐                   ┌──────────────▼──────────┐
       │   │EMPLOYEE_POSITIONS│                  │ BANK_RECONCILIATIONS     │
       │   │(المسميات الوظيفية)│                  │ (تسويات بنكية)           │
       │   └────────────────┘                   └─────────────────────────┘
       │
       │   ┌═══════════════════════════════════════════════════════════════┐
       │   ║                  EMPLOYEES (الموظفون)                        ║
       │   ║ employee_code, first/last_name, email, phone, birth_date,    ║
       │   ║ hire_date, salary, currency, department_id, position_id,     ║
       │   ║ branch_id, manager_id→employees(Self-ref),                   ║
       │   ║ user_id→company_users, bank_account_id→treasury_accounts,    ║
       │   ║ social_security, tax_id, passport, iqama, nationality        ║
       │   ╚═══════╦═══════════════════════════════════════════════════════╝
       │           │
       │           │         user_id (1:1)
       │           ▼
       │   ┌═══════════════════════════════════════════════════════════════┐
       │   ║               COMPANY_USERS (المستخدمون)                      ║
       │   ║  username(unique), password(hashed), email, full_name,       ║
       │   ║  role → Role.role_name, permissions(JSONB), is_active        ║
       │   ╚═══════╦═══════════════╦═══════════════════════════════════════╝
       │           │               │
       │   ┌───────▼──────┐  ┌─────▼──────────┐
       │   │    ROLES     │  │  USER_BRANCHES  │
       │   │ role_name    │  │ user_id,        │
       │   │ permissions  │  │ branch_id       │
       │   │ (JSONB list) │  │ (Many-to-Many)  │
       │   └──────────────┘  └────────────────┘
       │
       │   🔗 السلسلة: Employee → CompanyUser → Role → Permissions → Branch Scope
       │
       │   ┌──────────────────────────────────────────────────────────────┐
       │   │              ACCOUNTS (دليل الحسابات - شجرة 5 مستويات)       │
       │   │  account_number(unique), name, account_type, parent_id,      │
       │   │  is_header, balance, currency                                │
       │   └──────┬───────────────────────────────────────┬───────────────┘
       │          │                                       │
       │   ┌──────▼────────┐                      ┌──────▼──────────┐
       │   │JOURNAL_ENTRIES │                      │  COST_CENTERS   │
       │   │entry_number,   │                      │ center_code,    │
       │   │date, status,   │                      │ name, budget,   │
       │   │currency, rate  │                      │ currency        │
       │   │branch_id       │                      └─────────────────┘
       │   └──────┬─────────┘
       │          │
       │   ┌──────▼─────────┐
       │   │ JOURNAL_LINES  │
       │   │account, debit, │
       │   │credit, ccy_amt │
       │   │cost_center_id  │
       │   └────────────────┘
       │
       └─── السلسلة الكاملة: ───────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                     PARTIES / CUSTOMERS / SUPPLIERS                      │
│                                                                          │
│  PARTIES (الطرف الموحد - يمكن أن يكون عميل ومورد معاً)                    │
│  ├── party_type, party_code, name, tax_number, currency                  │
│  ├── is_customer, is_supplier (Boolean flags)                            │
│  ├── credit_limit, current_balance, branch_id                            │
│  └── party_group_id → party_groups                                       │
│                                                                          │
│  CUSTOMERS (العملاء المستقلون)                                           │
│  └── Contacts, BankAccounts, PriceLists, Transactions, Receipts, Balance │
│                                                                          │
│  SUPPLIERS (الموردون المستقلون)                                          │
│  └── Contacts, BankAccounts, Payments, Transactions, Balance, Ratings    │
│                                                                          │
│  PROJECTS (المشاريع)                                                     │
│  └── Tasks, Budgets, Expenses, Revenues, Documents, ChangeOrders         │
│                                                                          │
│  CONTRACTS (العقود)                                                      │
│  └── ContractItems                                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. الأدوار والصلاحيات (23 دور)

### 3.1 قائمة الأدوار الكاملة مع الصلاحيات

| # | اسم الدور | المسمى العربي | الوصف | الصلاحيات الرئيسية |
|---|----------|-------------|------|-------------------|
| 1 | **superuser** | مدير النظام الأعلى | صلاحيات كاملة للنظام | `["*"]` - كل شيء |
| 2 | **admin** | مدير النظام | صلاحيات كاملة على جميع الوحدات | `["*"]` - كل شيء |
| 3 | **ceo** | رئيس الشركة | رؤية تنفيذية واعتمادات عليا | dashboard.*, approvals.approve, reports.financial, جميع *.view, audit.view, security.view |
| 4 | **manager** | مدير عام | إدارة جميع العمليات | sales.*, buying.*, products.*, stock.*, treasury.create, expenses.approve, contracts.*, projects.*, approvals.*, settings.view |
| 5 | **finance_manager** | مدير مالي | إشراف مالي شامل | accounting.manage, treasury.manage, reconciliation.*, taxes.manage, currencies.manage, cashflow.*, budgets.* |
| 6 | **chief_accountant** | رئيس الحسابات | قيود يومية + دليل حسابات + ضرائب | accounting.edit, accounting.create/post/void_journal_entry, taxes.manage, reconciliation.approve |
| 7 | **accountant** | محاسب | تنفيذ القيود دون إعدادات عليا | accounting.edit, create/post_journal_entry, treasury.create, expenses.create, taxes.manage |
| 8 | **branch_accountant** | محاسب فرع | محاسب مقيّد بفروع محددة | accounting.create/post_journal_entry, treasury.create, expenses.create (صلاحيات محدودة + تقييد فرعي) |
| 9 | **accounts_receivable** | محاسب ذمم مدينة | تحصيلات عملاء | sales.*, parties.manage, treasury.create |
| 10 | **accounts_payable** | محاسب ذمم دائنة | مدفوعات موردين | buying.*, parties.manage, expenses.create, matching.* |
| 11 | **treasury_officer** | أمين خزينة | خزينة + بنوك + تسويات | treasury.*, reconciliation.*, currencies.view |
| 12 | **tax_accountant** | محاسب ضرائب | إقرارات ودفعات ضريبية | taxes.manage, accounting.create/post_journal_entry |
| 13 | **cost_accountant** | محاسب تكاليف | تكلفة مخزون وتصنيع | cost_centers.*, costing.*, inventory.costing_*, manufacturing.view |
| 14 | **sales** | مسؤول مبيعات | مبيعات + عملاء + POS | sales.*, pos.*, contracts.create |
| 15 | **branch_manager** | مدير فرع | إدارة تشغيلية لفرع | sales.*, buying.create/receive, stock.transfer, treasury.create, expenses.approve, pos.*, approvals.* |
| 16 | **purchasing** | مسؤول مشتريات | مشتريات + موردين | buying.*, products.view, matching.* |
| 17 | **inventory** | أمين مستودع | مخزون + مستودعات | inventory.*, stock.*, products.* |
| 18 | **hr_manager** | مدير موارد بشرية | موظفين + رواتب + حضور | hr.*, hr.payroll.*, hr.self_service_approve |
| 19 | **employee** | موظف | خدمة ذاتية فقط | dashboard.view, hr.self_service |
| 20 | **cashier** | كاشير | نقطة بيع + صندوق | pos.*, sales.view/create, treasury.create |
| 21 | **manufacturing_user** | مسؤول تصنيع | أوامر إنتاج + BOM | manufacturing.*, products.view, stock.view |
| 22 | **project_manager** | مدير مشاريع | مشاريع + مهام + عقود | projects.*, contracts.*, expenses.create |
| 23 | **auditor** | مراجع/مدقق | عرض فقط + سجل المراقبة | كل شيء *.view + audit.view + security.view |

### 3.2 آلية تقييد الصلاحيات حسب الفرع

```
                    ┌──────────────────────┐
                    │    COMPANY_USER       │
                    │  username: mona.acct  │
                    │  role: branch_accountant│
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
    ┌───────▼──────┐   ┌───────▼──────┐   ┌───────▼──────┐
    │  USER_BRANCH │   │  USER_BRANCH │   │  USER_BRANCH │
    │  user: mona  │   │  user: admin │   │  user: tamer │
    │  branch: CAI │   │  branch: RUH │   │  branch: CAI │
    └──────────────┘   │  branch: CAI │   └──────────────┘
                       │  branch: DXB │
                       └──────────────┘

    منى (branch_accountant):
      ✓ يمكنها رؤية ومعالجة بيانات فرع القاهرة فقط (BR-CAI)
      ✗ لا يمكنها رؤية بيانات الرياض أو دبي

    admin (superuser):
      ✓ جميع الفروع - صلاحية مطلقة

    تامر (مدير فرع القاهرة - branch_manager):
      ✓ صلاحية إدارة تشغيلية كاملة على فرع القاهرة فقط
      ✓ اعتماد مصروفات، مبيعات، مشتريات، مخزون للقاهرة
      ✗ لا يرى بيانات الرياض أو دبي
```

---

## 4. كود التعبئة (Seeding Scripts)

### 4.1 السيناريو 1: متجر تجزئة صغير (السعودية - SAR)

```python
# ملف: seeds/scenario_1_small_retail.py
# شركة: متجر النخبة للتجزئة
# الموقع: الرياض، السعودية
# الحجم: فرع واحد، 5 موظفين

import json

DATA = {
    "company": {
        "name": "متجر النخبة للتجزئة", "name_en": "Elite Retail Store",
        "country": "SA", "currency": "SAR", "timezone": "Asia/Riyadh"
    },
    "currencies": [
        {"code": "SAR", "name": "ريال سعودي", "symbol": "ر.س", "is_base": True, "current_rate": 1.0},
    ],
    "branches": [
        {"code": "BR-RUH", "name": "الرياض - الفرع الرئيسي", "name_en": "Riyadh Main",
         "country": "SA", "default_currency": "SAR", "is_default": True, "city": "الرياض"},
    ],
    "departments": [
        {"code": "MGMT", "name": "الإدارة"}, {"code": "SALES", "name": "المبيعات"},
        {"code": "ACC", "name": "المحاسبة"}, {"code": "WH", "name": "المستودع"},
    ],
    "positions": [
        {"code": "CEO", "name": "مدير عام", "level": 5},
        {"code": "ACCT", "name": "محاسب", "level": 3},
        {"code": "SALES", "name": "بائع", "level": 1},
        {"code": "STORE", "name": "أمين مستودع", "level": 1},
    ],
    "fiscal_years": [
        {"year": 2026, "start": "2026-01-01", "end": "2026-12-31", "status": "open"},
    ],
    "tax_regimes": [
        {"country": "SA", "type": "vat", "name": "VAT", "rate": 15.0, "filing": "quarterly"},
        {"country": "SA", "type": "zakat", "name": "Zakat", "rate": 2.5, "filing": "annual"},
    ],
    "tax_rates": [
        {"code": "VAT15", "name": "VAT 15%", "value": 15.0, "country": "SA"},
        {"code": "VAT0", "name": "Zero-Rated", "value": 0.0, "country": "SA"},
    ],
    "treasury_accounts": [
        {"name": "الصندوق الرئيسي", "type": "cash", "currency": "SAR", "branch": "BR-RUH"},
        {"name": "حساب الراجحي", "type": "bank", "currency": "SAR", "bank": "مصرف الراجحي",
         "iban": "SA0380000000123456789012", "branch": "BR-RUH"},
    ],
    "party_groups": [
        {"code": "VIP", "name": "عملاء مميزون", "discount": 10.0, "payment_days": 60},
        {"code": "STD", "name": "عاديون", "discount": 0, "payment_days": 30},
        {"code": "SUP", "name": "موردين", "discount": 5.0, "payment_days": 30},
    ],
    "parties": [
        {"code": "C-001", "name": "شركة الأفق للتجارة", "type": "company", "tax": "SA-3000000001",
         "currency": "SAR", "customer": True, "group": "VIP", "credit_limit": 100000, "branch": "BR-RUH"},
        {"code": "C-002", "name": "خالد عبدالرحمن", "type": "individual",
         "currency": "SAR", "customer": True, "group": "STD", "credit_limit": 25000, "branch": "BR-RUH"},
        {"code": "C-003", "name": "مؤسسة النور", "type": "company", "tax": "SA-3000000002",
         "currency": "SAR", "customer": True, "group": "STD", "credit_limit": 50000, "branch": "BR-RUH"},
        {"code": "S-001", "name": "شركة التوريدات المتحدة", "type": "company", "tax": "SA-3000000003",
         "currency": "SAR", "supplier": True, "group": "SUP", "branch": "BR-RUH"},
        {"code": "S-002", "name": "مصنع الألبان الطازجة", "type": "company", "tax": "SA-3000000004",
         "currency": "SAR", "supplier": True, "group": "SUP", "branch": "BR-RUH"},
    ],
    # ────────── USERS & EMPLOYEES ──────────
    "users": [
        {"username": "admin",    "password": "P@ssw0rd!", "email": "admin@elite.sa",  "full_name": "مدير النظام",  "role": "superuser",  "branches": ["BR-RUH"]},
        {"username": "ahmed",    "password": "P@ssw0rd!", "email": "ahmed@elite.sa",  "full_name": "أحمد محمد",    "role": "manager",     "branches": ["BR-RUH"]},
        {"username": "fatima",   "password": "P@ssw0rd!", "email": "fatima@elite.sa", "full_name": "فاطمة علي",    "role": "accountant",  "branches": ["BR-RUH"]},
        {"username": "hassan",   "password": "P@ssw0rd!", "email": "hassan@elite.sa", "full_name": "حسن محمود",    "role": "sales",       "branches": ["BR-RUH"]},
        {"username": "maha",     "password": "P@ssw0rd!", "email": "maha@elite.sa",   "full_name": "مها خالد",     "role": "inventory",   "branches": ["BR-RUH"]},
    ],
    "employees": [
        {"code": "EMP001", "first": "أحمد",  "last": "محمد",   "email": "ahmed@elite.sa",  "phone": "+966501234567",
         "gender": "male", "birth": "1985-03-15", "hire": "2020-01-01",
         "dept": "MGMT",  "pos": "CEO",   "branch": "BR-RUH", "manager": None,
         "salary": 25000, "housing": 5000, "transport": 2000, "ccy": "SAR",
         "username": "ahmed", "social": "1234567890", "nationality": "سعودي", "saudi": True,
         "eos": True},
        {"code": "EMP002", "first": "فاطمة", "last": "علي",    "email": "fatima@elite.sa", "phone": "+966502345678",
         "gender": "female", "birth": "1990-07-20", "hire": "2021-03-15",
         "dept": "ACC",   "pos": "ACCT",  "branch": "BR-RUH", "manager": "EMP001",
         "salary": 12000, "housing": 3000, "transport": 1500, "ccy": "SAR",
         "username": "fatima", "social": "2345678901", "nationality": "سعودية", "saudi": True},
        {"code": "EMP003", "first": "حسن",   "last": "محمود",  "email": "hassan@elite.sa", "phone": "+966503456789",
         "gender": "male", "birth": "1992-11-10", "hire": "2022-06-01",
         "dept": "SALES", "pos": "SALES", "branch": "BR-RUH", "manager": "EMP001",
         "salary": 10000, "housing": 2500, "transport": 1500, "ccy": "SAR",
         "username": "hassan", "social": "3456789012", "nationality": "سوداني", "saudi": False,
         "iqama": "IQ001234567", "passport": "P12345678"},
        {"code": "EMP004", "first": "عبدالله","last": "سعيد",   "email": "abdullah@elite.sa","phone": "+966504567890",
         "gender": "male", "birth": "1998-05-25", "hire": "2023-01-15",
         "dept": "SALES", "pos": "SALES", "branch": "BR-RUH", "manager": "EMP003",
         "salary": 5000, "ccy": "SAR", "social": "4567890123",
         "nationality": "سعودي", "saudi": True},
        {"code": "EMP005", "first": "مها",   "last": "خالد",   "email": "maha@elite.sa",   "phone": "+966505678901",
         "gender": "female", "birth": "1995-09-08", "hire": "2023-08-01",
         "dept": "WH",    "pos": "STORE", "branch": "BR-RUH", "manager": "EMP001",
         "salary": 6000, "ccy": "SAR",
         "username": "maha", "social": "5678901234", "nationality": "سعودية", "saudi": True},
    ],
    "products": [
        {"code": "P-001", "name": "أرز بسمتي 5ك", "cat": "FOOD", "cost": 35, "price": 49, "tax": 15},
        {"code": "P-002", "name": "زيت طبخ 2ل",   "cat": "FOOD", "cost": 20, "price": 28, "tax": 15},
        {"code": "P-003", "name": "عصير برتقال 1ل","cat": "BEV",  "cost": 5,  "price": 8,  "tax": 15},
        {"code": "P-004", "name": "حليب طازج 2ل",  "cat": "DAIRY","cost": 8,  "price": 12, "tax": 15},
        {"code": "P-005", "name": "منظف أرضيات 4ل","cat": "CLEAN","cost": 15, "price": 22, "tax": 15},
    ],
    "budgets": [
        {"code": "BUD-2026", "name": "موازنة 2026", "year": 2026, "total": 500000,
         "start": "2026-01-01", "end": "2026-12-31"},
    ],
}
```

### 4.2 السيناريو 2: الخليج القابضة (3 فروع، 3 عملات)

```python
# ملف: seeds/scenario_2_gulf_holding.py
# شركة: الخليج القابضة
# 3 فروع: الرياض (SAR) + القاهرة (EGP) + دبي (AED)
# 12 موظف، 3 عملات، عملاء وموردين لكل فرع

DATA = {
    "company": {
        "name": "الخليج القابضة", "name_en": "Al-Khaleej Holding Group",
        "country": "SA", "reporting_currency": "SAR", "timezone": "Asia/Riyadh"
    },
    # ── عملات الفروع + عملات التجارة الخارجية ──
    "currencies": [
        {"code": "SAR", "name": "ريال سعودي", "symbol": "ر.س", "is_base": True,  "rate": 1.0},
        {"code": "EGP", "name": "جنيه مصري",  "symbol": "ج.م", "is_base": False, "rate": 0.077},
        {"code": "AED", "name": "درهم إماراتي","symbol": "د.إ", "is_base": False, "rate": 1.02},
        {"code": "USD", "name": "دولار أمريكي","symbol": "$",   "is_base": False, "rate": 3.75},
        {"code": "EUR", "name": "يورو",        "symbol": "€",   "is_base": False, "rate": 4.12},
    ],
    "exchange_rates": [
        {"from": "EGP", "date": "2026-01-01", "rate": 0.077},
        {"from": "AED", "date": "2026-01-01", "rate": 1.02},
        {"from": "USD", "date": "2026-01-01", "rate": 3.75},
        {"from": "EUR", "date": "2026-01-01", "rate": 4.12},
    ],
    # ── 3 فروع ──
    "branches": [
        {"code": "BR-RUH", "name": "الرياض - المركز الرئيسي", "name_en": "Riyadh HQ",
         "country": "SA", "ccy": "SAR", "is_default": True,  "city": "الرياض",
         "phone": "+966112340001", "email": "riyadh@khaleej-holding.com"},
        {"code": "BR-CAI", "name": "القاهرة - فرع مصر", "name_en": "Cairo Branch",
         "country": "EG", "ccy": "EGP", "is_default": False, "city": "القاهرة",
         "phone": "+20225556001", "email": "cairo@khaleej-holding.com"},
        {"code": "BR-DXB", "name": "دبي - فرع الإمارات", "name_en": "Dubai Branch",
         "country": "AE", "ccy": "AED", "is_default": False, "city": "دبي",
         "phone": "+97143456001", "email": "dubai@khaleej-holding.com"},
    ],
    # ── 9 أقسام (هيكل مركزي + أقسام فرعية) ──
    "departments": [
        {"code": "CEO",      "name": "مكتب الرئيس التنفيذي", "branch": "BR-RUH"},
        {"code": "FINANCE",  "name": "الإدارة المالية",      "branch": "BR-RUH"},
        {"code": "SALES-SA", "name": "المبيعات - السعودية",  "branch": "BR-RUH"},
        {"code": "SALES-EG", "name": "المبيعات - مصر",       "branch": "BR-CAI"},
        {"code": "SALES-AE", "name": "المبيعات - الإمارات",  "branch": "BR-DXB"},
        {"code": "PROC",     "name": "المشتريات",            "branch": "BR-RUH"},
        {"code": "IT",       "name": "تقنية المعلومات",      "branch": "BR-RUH"},
        {"code": "AUDIT",    "name": "المراجعة الداخلية",    "branch": "BR-RUH"},
        {"code": "HR",       "name": "الموارد البشرية",      "branch": "BR-RUH"},
    ],
    "positions": [
        {"code": "CEO",       "name": "رئيس تنفيذي",       "name_en": "CEO",            "level": 7},
        {"code": "CFO",       "name": "مدير مالي",         "name_en": "CFO",            "level": 6},
        {"code": "CHIEF-ACCT","name": "رئيس حسابات",       "name_en": "Chief Accountant","level": 5},
        {"code": "BR-MGR",    "name": "مدير فرع",          "name_en": "Branch Manager",  "level": 5},
        {"code": "SALES-MGR", "name": "مدير مبيعات",       "name_en": "Sales Manager",   "level": 4},
        {"code": "ACCT",      "name": "محاسب",             "name_en": "Accountant",      "level": 3},
        {"code": "BR-ACCT",   "name": "محاسب فرع",         "name_en": "Branch Accountant","level": 2},
        {"code": "AUDITOR",   "name": "مراجع داخلي",       "name_en": "Internal Auditor","level": 4},
        {"code": "TREASURY",  "name": "أمين خزينة",        "name_en": "Treasury Officer","level": 3},
        {"code": "IT-SPEC",   "name": "أخصائي تقنية",      "name_en": "IT Specialist",   "level": 2},
    ],
    "cost_centers": [
        {"code": "CC-ADMIN",   "name": "تكاليف إدارية",      "ccy": "SAR", "dept": "CEO"},
        {"code": "CC-SALES-SA","name": "تكاليف مبيعات السعودية","ccy": "SAR","dept": "SALES-SA"},
        {"code": "CC-SALES-EG","name": "تكاليف مبيعات مصر",   "ccy": "EGP","dept": "SALES-EG"},
        {"code": "CC-SALES-AE","name": "تكاليف مبيعات الإمارات","ccy": "AED","dept": "SALES-AE"},
    ],
    "fiscal_years": [
        {"year": 2026, "start": "2026-01-01", "end": "2026-12-31", "status": "open"},
    ],
    # ── أنظمة ضريبية حسب الدولة ──
    "tax_regimes": [
        {"country": "SA", "type": "vat",        "name": "VAT",        "rate": 15.0, "filing": "quarterly"},
        {"country": "SA", "type": "zakat",      "name": "Zakat",      "rate": 2.5,  "filing": "annual"},
        {"country": "SA", "type": "withholding","name": "WHT",        "rate": 5.0,  "filing": "monthly"},
        {"country": "EG", "type": "vat",        "name": "VAT",        "rate": 14.0, "filing": "monthly"},
        {"country": "EG", "type": "income_tax", "name": "Income Tax", "rate": 22.5, "filing": "annual"},
        {"country": "AE", "type": "vat",        "name": "VAT",        "rate": 5.0,  "filing": "quarterly"},
        {"country": "AE", "type": "corp_tax",   "name": "Corporate",  "rate": 9.0,  "filing": "annual"},
    ],
    "tax_rates": [
        {"code": "SA-VAT15","name": "VAT 15%","value": 15.0,"country": "SA"},
        {"code": "SA-VAT0", "name": "VAT 0%", "value": 0.0, "country": "SA"},
        {"code": "EG-VAT14","name": "VAT 14%","value": 14.0,"country": "EG"},
        {"code": "AE-VAT5", "name": "VAT 5%", "value": 5.0, "country": "AE"},
        {"code": "SA-WHT5", "name": "WHT 5%", "value": 5.0, "country": "SA"},
    ],
    "treasury_accounts": [
        {"name": "صندوق الرياض",    "type": "cash", "ccy": "SAR", "branch": "BR-RUH"},
        {"name": "الراجحي - الرياض","type": "bank", "ccy": "SAR", "branch": "BR-RUH", "bank": "مصرف الراجحي", "iban": "SA03800000001122334455"},
        {"name": "الأهلي - الرياض",  "type": "bank", "ccy": "SAR", "branch": "BR-RUH", "bank": "البنك الأهلي",   "iban": "SA03600000009988776655"},
        {"name": "صندوق القاهرة",   "type": "cash", "ccy": "EGP", "branch": "BR-CAI"},
        {"name": "بنك مصر - القاهرة","type": "bank", "ccy": "EGP", "branch": "BR-CAI", "bank": "بنك مصر"},
        {"name": "صندوق دبي",       "type": "cash", "ccy": "AED", "branch": "BR-DXB"},
        {"name": "دبي الإسلامي",    "type": "bank", "ccy": "AED", "branch": "BR-DXB", "bank": "بنك دبي الإسلامي"},
    ],
    "party_groups": [
        {"code": "VIP",     "name": "عملاء مميزون",    "discount": 15.0, "days": 60},
        {"code": "CORP",    "name": "عملاء شركات",      "discount": 5.0,  "days": 45},
        {"code": "RETAIL",  "name": "عملاء تجزئة",      "discount": 2.0,  "days": 30},
        {"code": "SUP-KSA", "name": "موردين السعودية",  "discount": 3.0,  "days": 30},
        {"code": "SUP-EG",  "name": "موردين مصر",       "discount": 0,    "days": 45},
        {"code": "SUP-INTL","name": "موردين دوليين",    "discount": 0,    "days": 60},
    ],
    "parties": [
        # عملاء السعودية
        {"code": "C-SA-1","name":"شركة الأفق للتجارة","ccy":"SAR","customer":True,"group":"CORP",  "limit":200000,"branch":"BR-RUH","tax":"SA-3000000101"},
        {"code": "C-SA-2","name":"مؤسسة النور",        "ccy":"SAR","customer":True,"group":"RETAIL","limit":75000, "branch":"BR-RUH","tax":"SA-3000000102"},
        {"code": "C-SA-3","name":"فارس محمد",          "ccy":"SAR","customer":True,"group":"RETAIL","limit":25000, "branch":"BR-RUH"},
        # عملاء مصر
        {"code": "C-EG-1","name":"الشركة المصرية للتوزيع","ccy":"EGP","customer":True,"group":"CORP",  "limit":500000,"branch":"BR-CAI","tax":"EG-4000000101"},
        {"code": "C-EG-2","name":"مكتب الهندسة المتطورة",  "ccy":"EGP","customer":True,"group":"RETAIL","limit":200000,"branch":"BR-CAI","tax":"EG-4000000102"},
        # عملاء الإمارات
        {"code": "C-AE-1","name":"شركة الخليج للمقاولات","ccy":"AED","customer":True,"group":"VIP",   "limit":350000,"branch":"BR-DXB","tax":"AE-5000000101"},
        {"code": "C-AE-2","name":"مؤسسة النجاح",          "ccy":"AED","customer":True,"group":"RETAIL","limit":150000,"branch":"BR-DXB","tax":"AE-5000000102"},
        # موردين
        {"code": "S-SA-1","name":"شركة التوريدات المتحدة",  "ccy":"SAR","supplier":True,"group":"SUP-KSA","branch":"BR-RUH","tax":"SA-3000000201"},
        {"code": "S-SA-2","name":"مصنع المنتجات البلاستيكية","ccy":"SAR","supplier":True,"group":"SUP-KSA","branch":"BR-RUH","tax":"SA-3000000202"},
        {"code": "S-EG-1","name":"الشركة العربية للتصنيع",  "ccy":"EGP","supplier":True,"group":"SUP-EG", "branch":"BR-CAI","tax":"EG-4000000201"},
        {"code": "S-INT-1","name":"TechGlobal Industries Ltd.","ccy":"USD","supplier":True,"group":"SUP-INTL","branch":"BR-RUH","tax":"GB-123456789"},
    ],
    # ═══════════════════════════════════════════════════════════════════════
    #  المستخدمون والموظفون - 12 موظف موزعين على 3 فروع
    #  آلية الصلاحيات:
    #    Employee → user_id → CompanyUser → role → Role.permissions
    #    CompanyUser ← user_branches → Branch (تقييد الفرع)
    # ═══════════════════════════════════════════════════════════════════════
    "users": [
        # 0 - مدير النظام (جميع الفروع - superuser)
        {"username":"admin",        "pass":"Admin@2026!", "email":"admin@khaleej-holding.com",
         "full_name":"مدير النظام",     "role":"superuser",        "branches":["BR-RUH","BR-CAI","BR-DXB"]},
        # 1 - الرئيس التنفيذي (جميع الفروع - CEO: رؤية تنفيذية + اعتمادات)
        {"username":"khaled.ceo",   "pass":"Ceo@2026!",  "email":"khaled@khaleej-holding.com",
         "full_name":"خالد عبدالعزيز",  "role":"ceo",              "branches":["BR-RUH","BR-CAI","BR-DXB"]},
        # 2 - المدير المالي (جميع الفروع - صلاحية مالية عليا)
        {"username":"nasser.cfo",   "pass":"Cfo@2026!",  "email":"nasser@khaleej-holding.com",
         "full_name":"ناصر القحطاني",   "role":"finance_manager",  "branches":["BR-RUH","BR-CAI","BR-DXB"]},
        # 3 - رئيس حسابات (الرياض فقط)
        {"username":"sara.chief",   "pass":"Chief@2026!","email":"sara@khaleej-holding.com",
         "full_name":"سارة الحربي",     "role":"chief_accountant", "branches":["BR-RUH"]},
        # 4 - مدير فرع القاهرة (القاهرة فقط - branch_manager)
        {"username":"tamer.branch",  "pass":"Branch@2026!","email":"tamer@khaleej-holding.com",
         "full_name":"تامر حسن",       "role":"branch_manager",   "branches":["BR-CAI"]},
        # 5 - مدير فرع دبي (دبي فقط - branch_manager)
        {"username":"omar.branch",   "pass":"Branch@2026!","email":"omar@khaleej-holding.com",
         "full_name":"عمر البلوشي",    "role":"branch_manager",   "branches":["BR-DXB"]},
        # 6 - محاسب الرياض (الرياض فقط)
        {"username":"ali.acct",     "pass":"Acct@2026!", "email":"ali@khaleej-holding.com",
         "full_name":"علي المطيري",     "role":"accountant",       "branches":["BR-RUH"]},
        # 7 - محاسب فرع القاهرة (القاهرة فقط - صلاحية branch_accountant المحدودة)
        {"username":"mona.acct",    "pass":"Acct@2026!", "email":"mona@khaleej-holding.com",
         "full_name":"منى عبدالله",     "role":"branch_accountant","branches":["BR-CAI"]},
        # 8 - محاسب فرع دبي (دبي فقط - صلاحية محدودة)
        {"username":"rashid.acct",  "pass":"Acct@2026!", "email":"rashid@khaleej-holding.com",
         "full_name":"راشد الكتبي",     "role":"branch_accountant","branches":["BR-DXB"]},
        # 9 - مراجع داخلي (جميع الفروع - صلاحية auditor: عرض فقط)
        {"username":"noura.audit",  "pass":"Audit@2026!","email":"noura@khaleej-holding.com",
         "full_name":"نورة السبيعي",    "role":"auditor",          "branches":["BR-RUH","BR-CAI","BR-DXB"]},
        # 10 - مدير مبيعات الرياض (الرياض فقط)
        {"username":"fahad.sales",  "pass":"Sales@2026!","email":"fahad@khaleej-holding.com",
         "full_name":"فهد الشمري",      "role":"sales",            "branches":["BR-RUH"]},
        # 11 - أمين خزينة (جميع الفروع - treasury_officer)
        {"username":"lamia.treasury","pass":"Treasury@2026!","email":"lamia@khaleej-holding.com",
         "full_name":"لمياء الزهراني",  "role":"treasury_officer", "branches":["BR-RUH","BR-CAI","BR-DXB"]},
    ],
    "employees": [
        # ─── الرياض (8 موظفين - رواتب SAR) ───
        {"code":"KH-001","first":"خالد",  "last":"عبدالعزيز","email":"khaled@khaleej-holding.com",
         "phone":"+966501001001","gender":"male","birth":"1975-06-10","hire":"2018-01-01",
         "dept":"CEO","pos":"CEO","branch":"BR-RUH","manager":None,
         "salary":75000,"housing":15000,"transport":5000,"allowances":5000,"ccy":"SAR",
         "username":"khaled.ceo","social":"1000000001","nationality":"سعودي","saudi":True,"passport":"A12345678"},
        {"code":"KH-002","first":"ناصر",  "last":"القحطاني","email":"nasser@khaleej-holding.com",
         "phone":"+966502002002","gender":"male","birth":"1978-09-22","hire":"2019-03-01",
         "dept":"FINANCE","pos":"CFO","branch":"BR-RUH","manager":"KH-001",
         "salary":55000,"housing":12000,"transport":4000,"ccy":"SAR",
         "username":"nasser.cfo","social":"1000000002","nationality":"سعودي","saudi":True,"passport":"A12345679"},
        {"code":"KH-003","first":"سارة",  "last":"الحربي","email":"sara@khaleej-holding.com",
         "phone":"+966503003003","gender":"female","birth":"1985-12-05","hire":"2020-06-01",
         "dept":"FINANCE","pos":"CHIEF-ACCT","branch":"BR-RUH","manager":"KH-002",
         "salary":28000,"housing":6000,"transport":2500,"ccy":"SAR",
         "username":"sara.chief","social":"1000000003","nationality":"سعودية","saudi":True,"passport":"B87654321"},
        {"code":"KH-004","first":"علي",   "last":"المطيري","email":"ali@khaleej-holding.com",
         "phone":"+966504004004","gender":"male","birth":"1992-04-18","hire":"2022-01-01",
         "dept":"FINANCE","pos":"ACCT","branch":"BR-RUH","manager":"KH-003",
         "salary":15000,"housing":3000,"transport":1500,"ccy":"SAR",
         "username":"ali.acct","social":"1000000004","nationality":"سعودي","saudi":True,"passport":"C11223344"},
        {"code":"KH-010","first":"فهد",   "last":"الشمري","email":"fahad@khaleej-holding.com",
         "phone":"+966506006006","gender":"male","birth":"1990-01-15","hire":"2021-08-01",
         "dept":"SALES-SA","pos":"SALES-MGR","branch":"BR-RUH","manager":"KH-002",
         "salary":20000,"housing":5000,"transport":3000,"ccy":"SAR",
         "username":"fahad.sales","social":"1000000006","nationality":"سعودي","saudi":True,"passport":"E66778899"},
        {"code":"KH-009","first":"نورة",  "last":"السبيعي","email":"noura@khaleej-holding.com",
         "phone":"+966505005005","gender":"female","birth":"1988-03-25","hire":"2021-01-01",
         "dept":"AUDIT","pos":"AUDITOR","branch":"BR-RUH","manager":"KH-001",
         "salary":22000,"housing":5000,"transport":2000,"ccy":"SAR",
         "username":"noura.audit","social":"1000000005","nationality":"سعودية","saudi":True,"passport":"D55443322"},
        {"code":"KH-011","first":"لمياء", "last":"الزهراني","email":"lamia@khaleej-holding.com",
         "phone":"+966507007007","gender":"female","birth":"1992-09-30","hire":"2023-01-01",
         "dept":"FINANCE","pos":"TREASURY","branch":"BR-RUH","manager":"KH-003",
         "salary":13000,"housing":3000,"transport":1500,"ccy":"SAR",
         "username":"lamia.treasury","social":"1000000007","nationality":"سعودية","saudi":True,"passport":"F00112233"},
        {"code":"KH-012","first":"محمد",  "last":"العتيبي","email":"mohammed@khaleej-holding.com",
         "phone":"+966508008008","gender":"male","birth":"1987-06-28","hire":"2019-06-01",
         "dept":"IT","pos":"IT-SPEC","branch":"BR-RUH","manager":"KH-001",
         "salary":16000,"housing":3500,"transport":2000,"ccy":"SAR",
         "username":None,"social":"1000000008","nationality":"سعودي","saudi":True,"passport":"G44556677"},
        # ─── القاهرة (2 موظفين - رواتب EGP) ───
        {"code":"KH-005","first":"تامر",  "last":"حسن","email":"tamer@khaleej-holding.com",
         "phone":"+201001234567","gender":"male","birth":"1982-08-14","hire":"2020-09-01",
         "dept":"SALES-EG","pos":"BR-MGR","branch":"BR-CAI","manager":"KH-001",
         "salary":120000,"housing":15000,"transport":5000,"ccy":"EGP",
         "username":"tamer.branch","social":"EG-123456789","nationality":"مصري","saudi":False,"passport":"EGP98765432"},
        {"code":"KH-006","first":"منى",   "last":"عبدالله","email":"mona@khaleej-holding.com",
         "phone":"+201001234568","gender":"female","birth":"1993-02-20","hire":"2022-03-01",
         "dept":"SALES-EG","pos":"BR-ACCT","branch":"BR-CAI","manager":"KH-005",
         "salary":45000,"housing":5000,"transport":2000,"ccy":"EGP",
         "username":"mona.acct","social":"EG-987654321","nationality":"مصرية","saudi":False,"passport":"EGP12345678"},
        # ─── دبي (2 موظفين - رواتب AED) ───
        {"code":"KH-007","first":"عمر",   "last":"البلوشي","email":"omar@khaleej-holding.com",
         "phone":"+971501234567","gender":"male","birth":"1980-11-03","hire":"2020-06-01",
         "dept":"SALES-AE","pos":"BR-MGR","branch":"BR-DXB","manager":"KH-001",
         "salary":35000,"housing":10000,"transport":3000,"ccy":"AED",
         "username":"omar.branch","social":"AE-111222333","nationality":"إماراتي","saudi":False,"passport":"AE123456789"},
        {"code":"KH-008","first":"راشد",  "last":"الكتبي","email":"rashid@khaleej-holding.com",
         "phone":"+971501234568","gender":"male","birth":"1990-07-12","hire":"2022-01-01",
         "dept":"SALES-AE","pos":"BR-ACCT","branch":"BR-DXB","manager":"KH-007",
         "salary":15000,"housing":4000,"transport":2000,"ccy":"AED",
         "username":"rashid.acct","social":"AE-444555666","nationality":"إماراتي","saudi":False,"passport":"AE987654321"},
    ],
    "budgets": [
        {"code":"BUD-RUH-2026","name":"موازنة الرياض 2026","year":2026,"branch":"BR-RUH","total":5000000,"start":"2026-01-01","end":"2026-12-31"},
        {"code":"BUD-CAI-2026","name":"موازنة القاهرة 2026","year":2026,"branch":"BR-CAI","total":15000000,"start":"2026-01-01","end":"2026-12-31"},
        {"code":"BUD-DXB-2026","name":"موازنة دبي 2026","year":2026,"branch":"BR-DXB","total":2500000,"start":"2026-01-01","end":"2026-12-31"},
    ],
    "entity_groups": [
        {"name":"الرياض","name_en":"Riyadh","ccy":"SAR","consolidation":0},
        {"name":"القاهرة","name_en":"Cairo","ccy":"EGP","consolidation":0},
        {"name":"دبي","name_en":"Dubai","ccy":"AED","consolidation":0},
    ],
}
```

### 4.3 السيناريو 3: شركة خدمات احترافية (الإمارات - AED)

```python
# ملف: seeds/scenario_3_professional_services.py
# شركة: الدار للاستشارات الهندسية
# فرعين: دبي + أبوظبي، 8 موظفين، تركيز على المشاريع والعقود والأصول

DATA = {
    "company": {
        "name": "الدار للاستشارات الهندسية", "name_en": "Al-Dar Engineering Consultancy",
        "country": "AE", "currency": "AED", "timezone": "Asia/Dubai"
    },
    "currencies": [
        {"code": "AED", "name": "درهم إماراتي", "symbol": "د.إ", "is_base": True, "rate": 1.0},
        {"code": "USD", "name": "دولار أمريكي", "symbol": "$",   "is_base": False, "rate": 3.673},
        {"code": "EUR", "name": "يورو",          "symbol": "€",  "is_base": False, "rate": 4.02},
    ],
    "branches": [
        {"code": "BR-DXB", "name": "دبي - المكتب الرئيسي", "name_en": "Dubai HQ",      "city": "دبي",    "ccy": "AED", "is_default": True},
        {"code": "BR-AUH", "name": "أبوظبي - المكتب الفرعي","name_en": "Abu Dhabi Office","city": "أبوظبي","ccy": "AED", "is_default": False},
    ],
    "departments": [
        {"code": "MGMT",  "name": "الإدارة العليا", "branch": "BR-DXB"},
        {"code": "FIN",   "name": "المالية",         "branch": "BR-DXB"},
        {"code": "ENG",   "name": "الهندسة",         "branch": "BR-DXB"},
        {"code": "PMO",   "name": "إدارة المشاريع",  "branch": "BR-DXB"},
        {"code": "BD",    "name": "تطوير الأعمال",    "branch": "BR-DXB"},
        {"code": "ENG-AUH","name":"الهندسة - أبوظبي", "branch": "BR-AUH"},
    ],
    "positions": [
        {"code": "MD",       "name": "شريك إداري",        "name_en": "Managing Director",  "level": 7},
        {"code": "FIN-MGR",  "name": "مدير مالي",         "name_en": "Finance Manager",    "level": 5},
        {"code": "SR-ENG",   "name": "مهندس استشاري أول", "name_en": "Senior Engineer",    "level": 5},
        {"code": "PM",       "name": "مدير مشاريع",       "name_en": "Project Manager",    "level": 4},
        {"code": "ENG",      "name": "مهندس",             "name_en": "Engineer",           "level": 3},
        {"code": "ARCH",     "name": "مهندس معماري",      "name_en": "Architect",          "level": 3},
        {"code": "QS",       "name": "مساح كميات",        "name_en": "Quantity Surveyor",  "level": 2},
        {"code": "ACCT",     "name": "محاسب",             "name_en": "Accountant",         "level": 2},
    ],
    "tax_regimes": [
        {"country": "AE", "type": "vat",      "name": "VAT", "rate": 5.0, "filing": "quarterly"},
        {"country": "AE", "type": "corp_tax", "name": "Corporate Tax", "rate": 9.0, "filing": "annual"},
    ],
    "users": [
        {"username":"admin",     "pass":"Admin@2026!","email":"admin@aldar.ae",  "full_name":"مدير النظام",       "role":"superuser",       "branches":["BR-DXB","BR-AUH"]},
        {"username":"rashid.md", "pass":"Md@2026!",   "email":"rashid@aldar.ae", "full_name":"راشد المنصوري",    "role":"ceo",             "branches":["BR-DXB","BR-AUH"]},
        {"username":"leila.fin", "pass":"Fin@2026!",  "email":"leila@aldar.ae",  "full_name":"ليلى عبدالكريم",   "role":"finance_manager", "branches":["BR-DXB","BR-AUH"]},
        {"username":"hani.pm",   "pass":"Pm@2026!",   "email":"hani@aldar.ae",   "full_name":"هاني خليل",        "role":"project_manager", "branches":["BR-DXB"]},
        {"username":"dana.eng",  "pass":"Eng@2026!",  "email":"dana@aldar.ae",   "full_name":"دانة الشامسي",     "role":"project_manager", "branches":["BR-AUH"]},
        {"username":"bilal.aud", "pass":"Audit@2026!","email":"bilal@aldar.ae",  "full_name":"بلال أحمد",        "role":"auditor",         "branches":["BR-DXB","BR-AUH"]},
        {"username":"karim.eng", "pass":"Eng@2026!",  "email":"karim@aldar.ae",  "full_name":"كريم نور الدين",   "role":"employee",        "branches":["BR-DXB"]},
        {"username":"salma.acct","pass":"Acct@2026!","email":"salma@aldar.ae",  "full_name":"سلمى جابر",        "role":"accountant",      "branches":["BR-DXB"]},
    ],
    "employees": [
        {"code":"AD-001","first":"راشد", "last":"المنصوري",  "email":"rashid@aldar.ae", "phone":"+971501112233",
         "gender":"male","birth":"1972-04-12","hire":"2015-01-01",
         "dept":"MGMT","pos":"MD","branch":"BR-DXB","manager":None,
         "salary":80000,"housing":20000,"transport":5000,"ccy":"AED",
         "username":"rashid.md","social":"AE-1001","nationality":"إماراتي","saudi":False,"passport":"AE0101"},
        {"code":"AD-002","first":"ليلى", "last":"عبدالكريم",  "email":"leila@aldar.ae",  "phone":"+971502223344",
         "gender":"female","birth":"1980-08-20","hire":"2018-06-01",
         "dept":"FIN","pos":"FIN-MGR","branch":"BR-DXB","manager":"AD-001",
         "salary":45000,"housing":10000,"transport":3000,"ccy":"AED",
         "username":"leila.fin","social":"AE-1002","nationality":"إماراتية","saudi":False,"passport":"AE0202"},
        {"code":"AD-003","first":"هاني", "last":"خليل",       "email":"hani@aldar.ae",    "phone":"+971503334455",
         "gender":"male","birth":"1983-11-30","hire":"2019-01-01",
         "dept":"PMO","pos":"PM","branch":"BR-DXB","manager":"AD-001",
         "salary":35000,"housing":8000,"transport":2500,"ccy":"AED",
         "username":"hani.pm","social":"AE-1003","nationality":"أردني","saudi":False,"passport":"JO123456"},
        {"code":"AD-004","first":"بلال", "last":"أحمد",       "email":"bilal@aldar.ae",   "phone":"+971504445566",
         "gender":"male","birth":"1985-05-15","hire":"2020-03-01",
         "dept":"FIN","pos":"AUDITOR","branch":"BR-DXB","manager":"AD-002",
         "salary":28000,"housing":6000,"transport":2000,"ccy":"AED",
         "username":"bilal.aud","social":"AE-1004","nationality":"هندي","saudi":False,"passport":"IN789012"},
        {"code":"AD-005","first":"كريم", "last":"نور الدين",   "email":"karim@aldar.ae",   "phone":"+971505556677",
         "gender":"male","birth":"1990-08-08","hire":"2021-06-01",
         "dept":"ENG","pos":"ENG","branch":"BR-DXB","manager":"AD-003",
         "salary":22000,"housing":5000,"transport":2000,"ccy":"AED",
         "username":"karim.eng","social":"AE-1005","nationality":"مصري","saudi":False,"passport":"EGP55555"},
        {"code":"AD-006","first":"دانة", "last":"الشامسي",     "email":"dana@aldar.ae",    "phone":"+971506667788",
         "gender":"female","birth":"1988-02-14","hire":"2022-01-01",
         "dept":"ENG-AUH","pos":"SR-ENG","branch":"BR-AUH","manager":"AD-001",
         "salary":32000,"housing":8000,"transport":2500,"ccy":"AED",
         "username":"dana.eng","social":"AE-1006","nationality":"إماراتية","saudi":False,"passport":"AE0303"},
        {"code":"AD-007","first":"سلمى", "last":"جابر",        "email":"salma@aldar.ae",   "phone":"+971507778899",
         "gender":"female","birth":"1993-07-22","hire":"2023-01-01",
         "dept":"FIN","pos":"ACCT","branch":"BR-DXB","manager":"AD-002",
         "salary":18000,"housing":4000,"transport":1500,"ccy":"AED",
         "username":"salma.acct","social":"AE-1007","nationality":"لبنانية","saudi":False,"passport":"LB11111"},
        {"code":"AD-008","first":"وائل", "last":"فوزي",        "email":"wael@aldar.ae",    "phone":"+971508889900",
         "gender":"male","birth":"1995-01-10","hire":"2024-02-01",
         "dept":"ENG","pos":"ARCH","branch":"BR-DXB","manager":"AD-003",
         "salary":20000,"housing":4000,"transport":2000,"ccy":"AED",
         "username":None,"social":"AE-1008","nationality":"فلسطيني","saudi":False,"passport":"PS22222"},
    ],
    # ── مشاريع (خاص بقطاع الخدمات) ──
    "projects": [
        {"code":"PRJ-001","name":"برج النخلة - دبي","name_en":"Palm Tower","type":"construction",
         "customer":"شركة النخلة العقارية","client":"C-AE-1","party":"P-AE-1",
         "manager":"AD-003","branch":"BR-DXB","status":"in_progress",
         "budget":5000000,"actual_cost":2100000,"progress":42.0,
         "contract_type":"fixed_price","retainer":500000,"billing":"monthly",
         "start":"2025-06-01","end":"2027-12-31"},
        {"code":"PRJ-002","name":"مستشفى الظفرة - أبوظبي","name_en":"Al Dhafra Hospital","type":"infrastructure",
         "customer":"هيئة الصحة - أبوظبي","client":"C-AE-2","party":"P-AE-2",
         "manager":"AD-006","branch":"BR-AUH","status":"planning",
         "budget":12000000,"actual_cost":0,"progress":5.0,
         "contract_type":"cost_plus","retainer":0,"billing":"quarterly",
         "start":"2026-03-01","end":"2029-06-30"},
        {"code":"PRJ-003","name":"مجمع سكني - دبي","name_en":"Residential Complex","type":"residential",
         "customer":"شركة دبي للتطوير","client":"C-AE-3","party":"P-AE-3",
         "manager":"AD-003","branch":"BR-DXB","status":"in_progress",
         "budget":8000000,"actual_cost":4600000,"progress":60.0,
         "contract_type":"fixed_price","retainer":800000,"billing":"monthly",
         "start":"2025-01-01","end":"2027-06-30"},
    ],
    # ── عقود (خاص بقطاع الخدمات) ──
    "contracts": [
        {"number":"CTR-001","party":"P-AE-1","type":"service","status":"active",
         "start":"2025-06-01","end":"2027-12-31","billing":"monthly","total":5000000,"ccy":"AED"},
        {"number":"CTR-002","party":"P-AE-2","type":"consultancy","status":"draft",
         "start":"2026-03-01","end":"2029-06-30","billing":"quarterly","total":12000000,"ccy":"AED"},
        {"number":"CTR-003","party":"P-AE-3","type":"service","status":"active",
         "start":"2025-01-01","end":"2027-06-30","billing":"monthly","total":8000000,"ccy":"AED"},
    ],
    # ── أصول ──
    "assets": [
        {"code":"AST-001","name":"مبنى المكتب الرئيسي - دبي","type":"building","cost":2500000,"residual":250000,
         "life":25,"method":"straight_line","branch":"BR-DXB","ccy":"AED","purchase":"2020-01-01"},
        {"code":"AST-002","name":"أجهزة حاسوب ومعدات مكتبية","type":"equipment","cost":350000,"residual":35000,
         "life":5,"method":"straight_line","branch":"BR-DXB","ccy":"AED","purchase":"2024-01-01"},
        {"code":"AST-003","name":"سيارات الشركة (3 مركبات)","type":"vehicles","cost":450000,"residual":45000,
         "life":7,"method":"reducing_balance","branch":"BR-DXB","ccy":"AED","purchase":"2023-01-01"},
        {"code":"AST-004","name":"برامج هندسية (تراخيص)","type":"software","cost":180000,"residual":0,
         "life":3,"method":"straight_line","branch":"BR-DXB","ccy":"AED","purchase":"2025-06-01"},
    ],
    "budgets": [
        {"code":"BUD-CORP-2026","name":"الموازنة الشاملة 2026","year":2026,"branch":"BR-DXB","total":20000000,"start":"2026-01-01","end":"2026-12-31"},
        {"code":"BUD-AUH-2026","name":"موازنة أبوظبي 2026","year":2026,"branch":"BR-AUH","total":5000000,"start":"2026-01-01","end":"2026-12-31"},
    ],
}
```

---

## 5. ملاحظات ختامية

### تعدد الفروع والعملات - آلية العمل

| السيناريو | كيف يعمل | مثال |
|----------|---------|------|
| **موظف بفرع محدد** | `employee.branch_id` + `employee.currency` = راتبه بالعملة المحلية | تامر في القاهرة: راتب 120,000 EGP |
| **مستخدم مقيد بفروع** | `user_branches` = يحدد أي الفروع يراها | `mona.acct` ترى BR-CAI فقط |
| **معاملة بعملة غير محلية** | `invoice.currency` + `invoice.exchange_rate` | مورد دولي يفوتر بـ USD، يتحول لـ SAR |
| **تقارير موحدة** | `is_base=True` للعملة (SAR)، `is_default=True` للفرع الرئيسي | كل الأرباح تحول لـ SAR |
| **توحيد القوائم المالية** | `entity_groups` + `intercompany_transactions_v2` + `elimination_status` | معاملات بين الرياض والقاهرة تُقصى تلقائياً |
| **الضرائب المتعددة** | `tax_regimes` + `branch_tax_settings` لكل دولة | الرياض VAT 15%، القاهرة VAT 14%، دبي VAT 5% |
| **GL Account Mappings** | `company_settings` مفتاح-قيمة: `acc_map_*` | `acc_map_ar` = id حساب المدينون |
| **موازنات لكل فرع** | `budgets.branch_id` | موازنة الرياض 5M SAR، القاهرة 15M EGP |

### صلاحيات الموظفين حسب الفروع (السيناريو 2)

| الموظف | الفرع | الدور | الصلاحية | نطاق الفروع |
|--------|-------|------|---------|------------|
| خالد (CEO) | الرياض | CEO | رؤية تنفيذية - لا تنفيذ قيود | جميع الفروع |
| ناصر (CFO) | الرياض | Finance Manager | إشراف مالي شامل | جميع الفروع |
| سارة | الرياض | Chief Accountant | قيود + ضرائب + حسابات | الرياض فقط |
| علي | الرياض | Accountant | قيود + مصروفات | الرياض فقط |
| لمياء | الرياض | Treasury Officer | خزينة + بنوك | جميع الفروع |
| فهد | الرياض | Sales | مبيعات + عملاء + POS | الرياض فقط |
| محمد | الرياض | IT Specialist | لا صلاحيات نظام (لا يملك user_id) | - |
| نورة | الرياض | Auditor | عرض فقط + سجل المراقبة | جميع الفروع |
| تامر | القاهرة | Branch Manager | إدارة تشغيلية كاملة | القاهرة فقط |
| منى | القاهرة | Branch Accountant | قيود + مصروفات (محدودة) | القاهرة فقط |
| عمر | دبي | Branch Manager | إدارة تشغيلية كاملة | دبي فقط |
| راشد | دبي | Branch Accountant | قيود + مصروفات (محدودة) | دبي فقط |
