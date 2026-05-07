/**
 * Master data scenarios from docs/master-data-playwright-scenarios.md
 * Transformed into TypeScript for Playwright tests.
 */

export interface SeedRow {
  ref: string;
  [key: string]: any;
}

export interface Scenario {
  key: string;
  company: SeedRow;
  currencies: SeedRow[];
  exchangeRates: SeedRow[];
  branches: SeedRow[];
  companySettings: SeedRow[];
  taxRegimes: SeedRow[];
  taxRates: SeedRow[];
  taxGroups: SeedRow[];
  branchTaxSettings: SeedRow[];
  accounts: SeedRow[];
  treasuryAccounts: SeedRow[];
  departments: SeedRow[];
  positions: SeedRow[];
  costCenters: SeedRow[];
  warehouses: SeedRow[];
  binLocations: SeedRow[];
  workPolicies: SeedRow[];
  salaryStructures: SeedRow[];
  salaryComponents: SeedRow[];
  employees: SeedRow[];
  users: SeedRow[];
  partyGroups: SeedRow[];
  parties: SeedRow[];
  productCategories: SeedRow[];
  productUnits: SeedRow[];
  products: SeedRow[];
  priceLists: SeedRow[];
  projects: SeedRow[];
  contracts: SeedRow[];
  expensePolicies: SeedRow[];
  approvalWorkflows: SeedRow[];
  posSettings: Record<string, any>;
}

export const COMPANY_CODE = "34773f13";
export const COMPANY_USER = "omar";
export const COMPANY_PASS = "As123321";
export const EMPLOYEE_PASSWORD = "P@ssw0rd!2026";

export const gulfHoldingScenario: Scenario = {
  key: "gulf_holding_multibranch",
  company: {
    ref: "company:gulf_holding",
    company_name: "الخليج القابضة",
    company_name_en: "Gulf Holding",
    email: "info@gulf-holding.example",
    country: "SA",
    currency: "SAR",
    timezone: "Asia/Riyadh",
    commercial_registry: "1010999988",
    tax_number: "300000000000003",
    admin_username: "gulf.admin",
    admin_email: "admin@gulf-holding.example",
    admin_full_name: "مدير نظام الخليج القابضة",
    admin_password_hash: PASSWORD_HASH,
  },
  currencies: [
    { ref: "currency:SAR", code: "SAR", name: "ريال سعودي", name_en: "Saudi Riyal", symbol: "ر.س", is_base: true, current_rate: 1 },
    { ref: "currency:EGP", code: "EGP", name: "جنيه مصري", name_en: "Egyptian Pound", symbol: "ج.م", is_base: false, current_rate: 0.076 },
    { ref: "currency:AED", code: "AED", name: "درهم إماراتي", name_en: "UAE Dirham", symbol: "د.إ", is_base: false, current_rate: 1.021 },
    { ref: "currency:USD", code: "USD", name: "دولار أمريكي", name_en: "US Dollar", symbol: "$", is_base: false, current_rate: 3.75 },
  ],
  exchangeRates: [
    { currency_ref: "currency:EGP", rate: 0.076, rate_date: "2026-05-04", source: "manual" },
    { currency_ref: "currency:AED", rate: 1.021, rate_date: "2026-05-04", source: "manual" },
    { currency_ref: "currency:USD", rate: 3.75, rate_date: "2026-05-04", source: "manual" },
  ],
  branches: [
    { ref: "branch:riyadh", branch_code: "RUH-HQ", branch_name: "السعودية - الفرع الرئيسي الرياض", branch_name_en: "Saudi Arabia - Riyadh HQ", city: "الرياض", country: "Saudi Arabia", country_code: "SA", default_currency: "SAR", phone: "+966112220000", email: "riyadh@gulf-holding.example", is_default: true },
    { ref: "branch:cairo", branch_code: "CAI", branch_name: "مصر - فرع القاهرة", branch_name_en: "Egypt - Cairo Branch", city: "القاهرة", country: "Egypt", country_code: "EG", default_currency: "EGP", phone: "+2022220000", email: "cairo@gulf-holding.example" },
    { ref: "branch:dubai", branch_code: "DXB", branch_name: "الإمارات - فرع دبي", branch_name_en: "UAE - Dubai Branch", city: "دبي", country: "United Arab Emirates", country_code: "AE", default_currency: "AED", phone: "+97142220000", email: "dubai@gulf-holding.example" },
  ],
  companySettings: [
    { setting_key: "default_currency", setting_value: "SAR" },
    { setting_key: "reporting_currency", setting_value: "SAR" },
    { setting_key: "invoice_prefix", setting_value: "GH-SINV" },
    { setting_key: "journal_prefix", setting_value: "GH-JE" },
    { setting_key: "timezone", setting_value: "Asia/Riyadh" },
  ],
  taxRegimes: [
    { ref: "taxRegime:sa_vat", country_code: "SA", tax_type: "vat", name_ar: "ضريبة القيمة المضافة السعودية", name_en: "Saudi VAT", default_rate: 15, is_required: true, filing_frequency: "monthly" },
    { ref: "taxRegime:eg_vat", country_code: "EG", tax_type: "vat", name_ar: "ضريبة القيمة المضافة المصرية", name_en: "Egypt VAT", default_rate: 14, is_required: true, filing_frequency: "monthly" },
    { ref: "taxRegime:ae_vat", country_code: "AE", tax_type: "vat", name_ar: "ضريبة القيمة المضافة الإماراتية", name_en: "UAE VAT", default_rate: 5, is_required: true, filing_frequency: "quarterly" },
  ],
  taxRates: [
    { ref: "tax:sa_vat_15", tax_code: "SA-VAT-15", tax_name: "ضريبة القيمة المضافة 15%", rate_value: 15, country_code: "SA", effective_from: "2026-01-01" },
    { ref: "tax:eg_vat_14", tax_code: "EG-VAT-14", tax_name: "ضريبة القيمة المضافة 14%", rate_value: 14, country_code: "EG", effective_from: "2026-01-01" },
    { ref: "tax:ae_vat_5", tax_code: "AE-VAT-5", tax_name: "ضريبة القيمة المضافة 5%", rate_value: 5, country_code: "AE", effective_from: "2026-01-01" },
  ],
  taxGroups: [
    { ref: "taxGroup:gcc_standard", group_code: "GCC-STD", group_name: "ضرائب الخليج القياسية", tax_refs: ["tax:sa_vat_15", "tax:ae_vat_5"] },
    { ref: "taxGroup:egypt_standard", group_code: "EG-STD", group_name: "ضرائب مصر القياسية", tax_refs: ["tax:eg_vat_14"] },
  ],
  branchTaxSettings: [
    { branch_ref: "branch:riyadh", tax_regime_ref: "taxRegime:sa_vat", is_registered: true, registration_number: "300000000000003" },
    { branch_ref: "branch:cairo", tax_regime_ref: "taxRegime:eg_vat", is_registered: true, registration_number: "EG-VAT-998877" },
    { branch_ref: "branch:dubai", tax_regime_ref: "taxRegime:ae_vat", is_registered: true, registration_number: "AE-VAT-556677" },
  ],
  accounts: [
    { ref: "account:assets", account_number: "1000", name: "الأصول", account_type: "asset", is_header: true, currency: "SAR" },
    { ref: "account:cash", account_number: "1110", name: "الصندوق", account_type: "asset", parent_ref: "account:assets", currency: "SAR" },
    { ref: "account:banks", account_number: "1120", name: "البنوك", account_type: "asset", parent_ref: "account:assets", currency: "SAR" },
    { ref: "account:ar", account_number: "1210", name: "ذمم العملاء", account_type: "asset", parent_ref: "account:assets", currency: "SAR" },
    { ref: "account:inventory", account_number: "1310", name: "المخزون", account_type: "asset", parent_ref: "account:assets", currency: "SAR" },
    { ref: "account:liabilities", account_number: "2000", name: "الالتزامات", account_type: "liability", is_header: true },
    { ref: "account:ap", account_number: "2110", name: "ذمم الموردين", account_type: "liability", parent_ref: "account:liabilities" },
    { ref: "account:vat_payable", account_number: "2310", name: "ضريبة مستحقة", account_type: "liability", parent_ref: "account:liabilities" },
    { ref: "account:revenue", account_number: "4000", name: "الإيرادات", account_type: "revenue", is_header: true },
    { ref: "account:sales", account_number: "4100", name: "مبيعات", account_type: "revenue", parent_ref: "account:revenue" },
    { ref: "account:expenses", account_number: "5000", name: "المصروفات", account_type: "expense", is_header: true },
    { ref: "account:salary_exp", account_number: "5110", name: "مصروف رواتب", account_type: "expense", parent_ref: "account:expenses" },
  ],
  treasuryAccounts: [
    { ref: "treasury:riyadh_bank", name: "بنك الرياض الرئيسي", account_type: "bank", currency: "SAR", branch_ref: "branch:riyadh", gl_account_ref: "account:banks", bank_name: "Riyad Bank", account_number: "100200300", iban: "SA0380000000608010167519", opening_balance: 500000, allow_overdraft: false },
    { ref: "treasury:riyadh_cash", name: "صندوق الرياض", account_type: "cash", currency: "SAR", branch_ref: "branch:riyadh", gl_account_ref: "account:cash", opening_balance: 25000 },
    { ref: "treasury:cairo_bank", name: "بنك القاهرة", account_type: "bank", currency: "EGP", branch_ref: "branch:cairo", gl_account_ref: "account:banks", bank_name: "CIB", account_number: "EG100200", opening_balance: 300000 },
    { ref: "treasury:dubai_bank", name: "بنك دبي", account_type: "bank", currency: "AED", branch_ref: "branch:dubai", gl_account_ref: "account:banks", bank_name: "Emirates NBD", account_number: "AE100200", opening_balance: 220000 },
  ],
  departments: [
    { ref: "dept:executive", department_name: "الإدارة التنفيذية", branch_ref: "branch:riyadh" },
    { ref: "dept:finance", department_name: "المالية", branch_ref: "branch:riyadh" },
    { ref: "dept:sales", department_name: "المبيعات", branch_ref: "branch:riyadh" },
    { ref: "dept:hr", department_name: "الموارد البشرية", branch_ref: "branch:riyadh" },
    { ref: "dept:warehouse", department_name: "المستودعات", branch_ref: "branch:dubai" },
    { ref: "dept:projects", department_name: "المشاريع", branch_ref: "branch:riyadh" },
  ],
  positions: [
    { ref: "pos:ceo", position_name: "مدير تنفيذي", department_ref: "dept:executive" },
    { ref: "pos:branch_manager", position_name: "مدير فرع", department_ref: "dept:executive" },
    { ref: "pos:finance_manager", position_name: "مدير مالي", department_ref: "dept:finance" },
    { ref: "pos:chief_accountant", position_name: "رئيس حسابات", department_ref: "dept:finance" },
    { ref: "pos:accountant", position_name: "محاسب", department_ref: "dept:finance" },
    { ref: "pos:sales_supervisor", position_name: "مشرف مبيعات", department_ref: "dept:sales" },
    { ref: "pos:cashier", position_name: "كاشير", department_ref: "dept:sales" },
    { ref: "pos:hr_manager", position_name: "مدير موارد بشرية", department_ref: "dept:hr" },
    { ref: "pos:warehouse_keeper", position_name: "أمين مستودع", department_ref: "dept:warehouse" },
    { ref: "pos:auditor", position_name: "مراجع داخلي", department_ref: "dept:finance" },
  ],
  costCenters: [
    { ref: "cc:ruh_admin", center_code: "CC-RUH-ADMIN", center_name: "إدارة الرياض", department_ref: "dept:executive", currency: "SAR" },
    { ref: "cc:ruh_fin", center_code: "CC-RUH-FIN", center_name: "مالية الرياض", department_ref: "dept:finance", currency: "SAR" },
    { ref: "cc:cai_sales", center_code: "CC-CAI-SALES", center_name: "مبيعات القاهرة", department_ref: "dept:sales", currency: "EGP" },
    { ref: "cc:dxb_ops", center_code: "CC-DXB-OPS", center_name: "عمليات دبي", department_ref: "dept:warehouse", currency: "AED" },
  ],
  warehouses: [
    { ref: "wh:riyadh", code: "WH-RUH", name: "مستودع الرياض الرئيسي", branch_ref: "branch:riyadh", location: "الرياض - السلي", is_default: true },
    { ref: "wh:cairo", code: "WH-CAI", name: "مستودع القاهرة", branch_ref: "branch:cairo", location: "القاهرة - مدينة نصر" },
    { ref: "wh:dubai", code: "WH-DXB", name: "مستودع دبي", branch_ref: "branch:dubai", location: "دبي - جبل علي" },
  ],
  binLocations: [],
  workPolicies: [
    { ref: "workPolicy:gcc", name: "دوام الخليج", weekly_hours: 40, daily_hours: 8, work_days: [7, 1, 2, 3, 4] },
    { ref: "workPolicy:egypt", name: "دوام مصر", weekly_hours: 45, daily_hours: 9, work_days: [7, 1, 2, 3, 4] },
  ],
  salaryStructures: [
    { ref: "salary:monthly", name: "راتب شهري", base_type: "monthly" },
  ],
  salaryComponents: [
    { ref: "salComp:housing", name: "بدل سكن", component_type: "earning", calculation_type: "percentage", percentage_of: "salary", percentage_value: 25, is_gosi_applicable: false },
    { ref: "salComp:transport", name: "بدل نقل", component_type: "earning", calculation_type: "fixed", percentage_value: 0, is_gosi_applicable: false },
    { ref: "salComp:gosi", name: "استقطاع تأمينات", component_type: "deduction", calculation_type: "percentage", percentage_of: "salary", percentage_value: 9.75, is_gosi_applicable: true },
  ],
  employees: [
    { ref: "emp:ceo", first_name: "سالم", last_name: "الغامدي", email: "salem.g@gulf-holding.example", phone: "+966500000001", hire_date: "2021-01-01", salary: 65000, currency: "SAR", branch_ref: "branch:riyadh", department_name: "الإدارة التنفيذية", position_name: "مدير تنفيذي", create_user: true, username: "salem.ceo", password: "P@ssw0rd!2026", role: "ceo", allowed_branch_refs: ["branch:riyadh", "branch:cairo", "branch:dubai"] },
    { ref: "emp:finance_manager", first_name: "نورة", last_name: "القحطاني", email: "noura.q@gulf-holding.example", phone: "+966500000002", hire_date: "2021-03-01", salary: 42000, currency: "SAR", branch_ref: "branch:riyadh", department_name: "المالية", position_name: "مدير مالي", create_user: true, username: "noura.finance", password: "P@ssw0rd!2026", role: "finance_manager", allowed_branch_refs: ["branch:riyadh", "branch:cairo", "branch:dubai"] },
    { ref: "emp:cairo_manager", first_name: "أحمد", last_name: "حسن", email: "ahmed.h@gulf-holding.example", phone: "+201000000001", hire_date: "2022-06-15", salary: 85000, currency: "EGP", branch_ref: "branch:cairo", department_name: "المبيعات", position_name: "مدير فرع", create_user: true, username: "ahmed.cairo", password: "P@ssw0rd!2026", role: "branch_manager", allowed_branch_refs: ["branch:cairo"] },
    { ref: "emp:dubai_manager", first_name: "خالد", last_name: "المنصوري", email: "khaled.m@gulf-holding.example", phone: "+971500000001", hire_date: "2022-08-01", salary: 38000, currency: "AED", branch_ref: "branch:dubai", department_name: "المستودعات", position_name: "مدير فرع", create_user: true, username: "khaled.dubai", password: "P@ssw0rd!2026", role: "branch_manager", allowed_branch_refs: ["branch:dubai"] },
    { ref: "emp:dubai_cashier", first_name: "ريم", last_name: "النعيمي", email: "reem.n@gulf-holding.example", phone: "+971500000002", hire_date: "2024-01-05", salary: 12500, currency: "AED", branch_ref: "branch:dubai", department_name: "المبيعات", position_name: "كاشير", create_user: true, username: "reem.cashier", password: "P@ssw0rd!2026", role: "cashier", allowed_branch_refs: ["branch:dubai"] },
    { ref: "emp:auditor", first_name: "طارق", last_name: "الأنصاري", email: "tariq.a@gulf-holding.example", phone: "+966500000010", hire_date: "2022-10-01", salary: 26000, currency: "SAR", branch_ref: "branch:riyadh", department_name: "المالية", position_name: "مراجع داخلي", create_user: true, username: "tariq.audit", password: "P@ssw0rd!2026", role: "auditor", allowed_branch_refs: ["branch:riyadh", "branch:cairo", "branch:dubai"] },
  ],
  users: [],
  partyGroups: [
    { ref: "partyGroup:key_accounts", group_code: "VIP", group_name: "عملاء استراتيجيون", payment_days: 45, discount_percentage: 5 },
    { ref: "partyGroup:suppliers", group_code: "SUP", group_name: "موردون معتمدون", payment_days: 30 },
  ],
  parties: [
    { ref: "party:riyadh_customer", name: "شركة نجد للتجزئة", is_customer: true, branch_ref: "branch:riyadh", currency: "SAR", tax_number: "300111111100003", credit_limit: 250000, group_ref: "partyGroup:key_accounts" },
    { ref: "party:cairo_customer", name: "دلتا ماركت", is_customer: true, branch_ref: "branch:cairo", currency: "EGP", tax_number: "EG998877", credit_limit: 500000, group_ref: "partyGroup:key_accounts" },
    { ref: "party:dubai_customer", name: "Dubai Retail LLC", is_customer: true, branch_ref: "branch:dubai", currency: "AED", tax_number: "AE556677", credit_limit: 300000, group_ref: "partyGroup:key_accounts" },
    { ref: "party:global_supplier", name: "Gulf Supply FZCO", is_supplier: true, branch_ref: "branch:dubai", currency: "AED", tax_number: "AE-SUP-1122", group_ref: "partyGroup:suppliers" },
  ],
  productCategories: [
    { ref: "cat:electronics", category_code: "ELEC", category_name: "إلكترونيات" },
    { ref: "cat:services", category_code: "SERV", category_name: "خدمات" },
  ],
  productUnits: [
    { ref: "unit:piece", unit_code: "PCS", unit_name: "قطعة", abbreviation: "pcs" },
    { ref: "unit:hour", unit_code: "HOUR", unit_name: "ساعة", abbreviation: "hr" },
  ],
  products: [
    { ref: "prod:tablet", item_code: "GH-TAB-10", item_name: "جهاز لوحي 10 بوصة", item_type: "product", unit_ref: "unit:piece", category_ref: "cat:electronics", selling_price: 1200, buying_price: 800, tax_rate: 15, has_serial_tracking: true },
    { ref: "prod:scanner", item_code: "GH-SCN-01", item_name: "قارئ باركود", item_type: "product", unit_ref: "unit:piece", category_ref: "cat:electronics", selling_price: 450, buying_price: 280, tax_rate: 15 },
    { ref: "prod:implementation", item_code: "GH-SRV-IMPL", item_name: "خدمة تطبيق نظام", item_type: "service", unit_ref: "unit:hour", category_ref: "cat:services", selling_price: 350, buying_price: 0, tax_rate: 15 },
  ],
  priceLists: [
    { ref: "price:sar", name: "أسعار السعودية", currency: "SAR", is_default: true, items: [{ product_ref: "prod:tablet", price: 1200 }, { product_ref: "prod:scanner", price: 450 }] },
    { ref: "price:egp", name: "أسعار مصر", currency: "EGP", items: [{ product_ref: "prod:tablet", price: 16000 }, { product_ref: "prod:scanner", price: 6000 }] },
    { ref: "price:aed", name: "أسعار الإمارات", currency: "AED", items: [{ product_ref: "prod:tablet", price: 1175 }, { product_ref: "prod:scanner", price: 440 }] },
  ],
  projects: [
    { ref: "project:erp_rollout", project_code: "PRJ-GH-001", project_name: "تطبيق نظام موحد للفروع", customer_ref: "party:riyadh_customer", manager_ref: "emp:ceo", branch_ref: "branch:riyadh", planned_budget: 750000, contract_type: "fixed_price", status: "planning" },
  ],
  contracts: [
    { ref: "contract:riyadh_support", contract_number: "GH-C-2026-001", party_ref: "party:riyadh_customer", contract_type: "subscription", start_date: "2026-05-01", end_date: "2027-04-30", billing_interval: "monthly", currency: "SAR", total_amount: 240000, items: [{ product_ref: "prod:implementation", description: "دعم وتشغيل شهري", quantity: 12, unit_price: 20000, tax_rate: 15 }] },
  ],
  expensePolicies: [
    { ref: "expensePolicy:travel", name: "سفر وتنقل", expense_type: "travel", daily_limit: 1500, monthly_limit: 15000, requires_receipt: true, requires_approval: true, auto_approve_below: 300 },
  ],
  approvalWorkflows: [
    { ref: "approval:expense", name: "اعتماد المصاريف", document_type: "expense", conditions: { amount_gte: 300 }, steps: [{ role: "branch_manager" }, { role: "finance_manager" }], sla_hours: 24 },
  ],
  posSettings: {
    tables: [{ ref: "posTable:dubai_01", table_number: "D01", table_name: "طاولة دبي 1", floor: "main", capacity: 4, branch_ref: "branch:dubai" }],
    promotions: [{ ref: "promo:opening", name: "عرض الافتتاح", promotion_type: "percentage", value: 10, coupon_code: "GULF10", min_order_amount: 500, branch_ref: "branch:riyadh", start_date: "2026-05-01", end_date: "2026-06-30" }],
    loyaltyPrograms: [{ ref: "loyalty:gulf", name: "نقاط الخليج", points_per_unit: 1, currency_per_point: 0.05, min_points_redeem: 200, branch_ref: "branch:riyadh" }],
  },
};
