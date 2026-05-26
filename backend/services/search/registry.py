"""T141: Search registry — data-driven entity list with permissions."""

from __future__ import annotations

from dataclasses import dataclass

from utils.permissions import check_permission


@dataclass(frozen=True)
class SearchEntity:
    entity_code: str
    label: str
    route_template: str
    icon: str
    permissions_required: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    module_key: str | None = None
    resource: str | None = None


# ── Registry ─────────────────────────────────────────────────────────────

SEARCH_REGISTRY: tuple[SearchEntity, ...] = (
    SearchEntity("customer", "Customers", "/sales/customers/{id}", "Users", ("sales.view",), ("name", "email", "phone"), "sales", "customers"),
    SearchEntity("customer_group", "Customer Groups", "/sales/customer-groups?group_id={id}", "UsersRound", ("sales.view",), ("group_name", "group_code"), "sales", "customer_groups"),
    SearchEntity("supplier", "Suppliers", "/buying/suppliers/{id}", "Truck", ("purchases.view", "buying.view"), ("name", "email"), "buying", "suppliers"),
    SearchEntity("supplier_group", "Supplier Groups", "/buying/supplier-groups?group_id={id}", "UsersRound", ("buying.view", "purchases.view"), ("group_name", "group_code"), "buying", "supplier_groups"),
    SearchEntity("invoice", "Invoices", "/sales/invoices/{id}", "FileText", ("sales.view",), ("invoice_number", "customer_name"), "sales", "invoices"),
    SearchEntity("sales_order", "Sales Orders", "/sales/orders/{id}", "ClipboardList", ("sales.view",), ("so_number", "customer_name"), "sales", "sales_orders"),
    SearchEntity("quotation", "Quotations", "/sales/quotations/{id}", "FileSignature", ("sales.view",), ("sq_number", "customer_name"), "sales", "sales_quotations"),
    SearchEntity("sales_return", "Sales Returns", "/sales/returns/{id}", "Undo2", ("sales.view",), ("return_number", "customer_name"), "sales", "sales_returns"),
    SearchEntity("sales_credit_note", "Sales Credit Notes", "/sales/credit-notes?note_id={id}", "BadgeMinus", ("sales.view",), ("invoice_number", "customer_name"), "sales", "invoices"),
    SearchEntity("sales_debit_note", "Sales Debit Notes", "/sales/debit-notes?note_id={id}", "BadgePlus", ("sales.view",), ("invoice_number", "customer_name"), "sales", "invoices"),
    SearchEntity("customer_receipt", "Customer Receipts", "/sales/receipts/{id}", "ReceiptText", ("sales.view",), ("voucher_number", "customer_name"), "sales", "payment_vouchers"),
    SearchEntity("delivery_order", "Delivery Orders", "/sales/delivery-orders/{id}", "Truck", ("sales.view",), ("delivery_number", "tracking_number"), "sales", "delivery_orders"),
    SearchEntity("contract", "Contracts", "/sales/contracts/{id}", "FileCheck", ("contracts.view",), ("contract_number", "party_name"), "contracts", "contracts"),
    SearchEntity("product", "Products", "/stock/products?product_id={id}", "Package", ("inventory.view", "products.view", "stock.view"), ("name", "sku", "barcode"), "stock", "products"),
    SearchEntity("warehouse", "Warehouses", "/stock/warehouses/{id}", "Warehouse", ("stock.view", "inventory.view"), ("warehouse_name", "warehouse_code"), "stock", "warehouses"),
    SearchEntity("product_category", "Product Categories", "/stock/categories?category_id={id}", "Tags", ("stock.view", "inventory.view"), ("category_name", "category_code"), "stock", "product_categories"),
    SearchEntity("product_unit", "Product Units", "/stock/products?unit_id={id}", "Ruler", ("stock.view", "inventory.view"), ("unit_name", "unit_code"), "stock", "product_units"),
    SearchEntity("price_list", "Price Lists", "/stock/price-lists/{id}", "BadgePercent", ("stock.view", "inventory.view"), ("price_list_name", "price_list_code"), "stock", "customer_price_lists"),
    SearchEntity("inventory_transaction", "Inventory Transactions", "/stock/reports/movements?transaction_id={id}", "ArrowRightLeft", ("stock.reports", "stock.view"), ("reference_document", "reference_type"), "stock", "inventory_transactions"),
    SearchEntity("stock_adjustment", "Stock Adjustments", "/stock/adjustments?adjustment_id={id}", "SlidersHorizontal", ("stock.view", "inventory.view"), ("adjustment_number", "reason"), "stock", "stock_adjustments"),
    SearchEntity("stock_shipment", "Stock Shipments", "/stock/shipments/{id}", "PackageCheck", ("stock.view", "inventory.view"), ("shipment_ref", "status"), "stock", "stock_shipments"),
    SearchEntity("product_batch", "Product Batches", "/stock/batches?batch_id={id}", "Boxes", ("stock.view", "inventory.view"), ("batch_number", "product_name"), "stock", "product_batches"),
    SearchEntity("product_serial", "Product Serials", "/stock/serials?serial_id={id}", "Hash", ("stock.view", "inventory.view"), ("serial_number", "product_name"), "stock", "product_serials"),
    SearchEntity("quality_inspection", "Quality Inspections", "/stock/quality?inspection_id={id}", "ClipboardCheck", ("stock.view", "inventory.view"), ("inspection_number", "product_name"), "stock", "quality_inspections"),
    SearchEntity("cycle_count", "Cycle Counts", "/stock/cycle-counts?count_id={id}", "ClipboardList", ("stock.view", "inventory.view"), ("count_number", "warehouse_name"), "stock", "cycle_counts"),
    SearchEntity("cost_layer", "Cost Layers", "/stock/cost-layers?layer_id={id}", "Layers", ("stock.view_cost",), ("product_name", "source_document_type"), "stock", "cost_layers"),
    SearchEntity("journal_entry", "Journal Entries", "/accounting/journal-entries?entry_id={id}", "BookOpen", ("accounting.view",), ("reference", "description"), "accounting", "journal_entries"),
    SearchEntity("account", "Accounts", "/accounting/coa?account_id={id}", "List", ("accounting.view",), ("code", "name"), "accounting", "accounts"),
    SearchEntity("cost_center", "Cost Centers", "/accounting/cost-centers?cost_center_id={id}", "Crosshair", ("accounting.view",), ("center_name", "center_code"), "accounting", "cost_centers"),
    SearchEntity("fiscal_year", "Fiscal Years", "/accounting/fiscal-years?year_id={id}", "CalendarRange", ("accounting.view",), ("year", "status"), "accounting", "fiscal_years"),
    SearchEntity("fiscal_period", "Fiscal Periods", "/accounting/fiscal-years?period_id={id}", "CalendarDays", ("accounting.view",), ("name", "fiscal_year"), "accounting", "fiscal_periods"),
    SearchEntity("recurring_journal_template", "Recurring Journal Templates", "/accounting/recurring-templates?template_id={id}", "Repeat", ("accounting.view",), ("name", "reference"), "accounting", "recurring_journal_templates"),
    SearchEntity("fiscal_period_lock", "Fiscal Period Locks", "/accounting/fiscal-locks?lock_id={id}", "LockKeyhole", ("accounting.manage",), ("period_name", "reason"), "accounting", "fiscal_period_locks"),
    SearchEntity("currency", "Currencies", "/accounting/currencies?currency_id={id}", "BadgeDollarSign", ("currencies.view",), ("code", "name"), "accounting", "currencies"),
    SearchEntity("exchange_rate", "Exchange Rates", "/accounting/currencies?rate_id={id}", "TrendingUp", ("currencies.view",), ("currency_code", "source"), "accounting", "exchange_rates"),
    SearchEntity("treasury_account", "Treasury Accounts", "/treasury/accounts?account_id={id}", "Landmark", ("treasury.view",), ("name", "account_number", "bank_name"), "treasury", "treasury_accounts"),
    SearchEntity("treasury_transaction", "Treasury Transactions", "/treasury?transaction_id={id}", "ArrowLeftRight", ("treasury.view",), ("transaction_number", "reference_number"), "treasury", "treasury_transactions"),
    SearchEntity("bank_reconciliation", "Bank Reconciliations", "/treasury/reconciliation/{id}", "ListChecks", ("reconciliation.view",), ("statement_date", "account_name"), "treasury", "bank_reconciliations"),
    SearchEntity("check_receivable", "Checks Receivable", "/treasury/checks-receivable?check_id={id}", "BadgeDollarSign", ("treasury.view",), ("check_number", "drawer_name", "bank_name"), "treasury", "checks_receivable"),
    SearchEntity("check_payable", "Checks Payable", "/treasury/checks-payable?check_id={id}", "BadgeDollarSign", ("treasury.view",), ("check_number", "beneficiary_name", "bank_name"), "treasury", "checks_payable"),
    SearchEntity("note_receivable", "Notes Receivable", "/treasury/notes-receivable?note_id={id}", "FileInput", ("treasury.view",), ("note_number", "drawer_name", "bank_name"), "treasury", "notes_receivable"),
    SearchEntity("note_payable", "Notes Payable", "/treasury/notes-payable?note_id={id}", "FileOutput", ("treasury.view",), ("note_number", "beneficiary_name", "bank_name"), "treasury", "notes_payable"),
    SearchEntity("expense", "Expenses", "/expenses/{id}", "Receipt", ("expenses.view",), ("expense_number", "vendor_name", "description"), "expenses", "expenses"),
    SearchEntity("budget", "Budgets", "/accounting/budgets/{id}/report", "CircleDollarSign", ("accounting.budgets.view",), ("budget_code", "budget_name"), "accounting", "budgets"),
    SearchEntity("report_template", "Report Templates", "/reports/builder?template_id={id}", "FileCog", ("reports.view",), ("template_name", "template_type"), "reports", "report_templates"),
    SearchEntity("custom_report", "Custom Reports", "/reports/builder?report_id={id}", "FileBarChart", ("reports.view",), ("report_name", "description"), "reports", "custom_reports"),
    SearchEntity("scheduled_report", "Scheduled Reports", "/reports/scheduled?report_id={id}", "CalendarClock", ("reports.view",), ("report_name", "report_type"), "reports", "scheduled_reports"),
    SearchEntity("analytics_dashboard", "Analytics Dashboards", "/analytics/{id}", "LayoutDashboard", ("dashboard.analytics_view",), ("name", "description"), "analytics", "analytics_dashboards"),
    SearchEntity("purchase_order", "Purchase Orders", "/buying/orders/{id}", "ShoppingCart", ("buying.view", "purchases.view"), ("po_number", "supplier_name"), "buying", "purchase_orders"),
    SearchEntity("purchase_invoice", "Purchase Invoices", "/buying/invoices/{id}", "FileText", ("buying.view", "purchases.view"), ("invoice_number", "supplier_name"), "buying", "invoices"),
    SearchEntity("purchase_return", "Purchase Returns", "/buying/returns/{id}", "Undo2", ("buying.view", "purchases.view"), ("invoice_number", "supplier_name"), "buying", "invoices"),
    SearchEntity("purchase_credit_note", "Purchase Credit Notes", "/buying/credit-notes?note_id={id}", "BadgeMinus", ("buying.view", "purchases.view"), ("invoice_number", "supplier_name"), "buying", "invoices"),
    SearchEntity("purchase_debit_note", "Purchase Debit Notes", "/buying/debit-notes?note_id={id}", "BadgePlus", ("buying.view", "purchases.view"), ("invoice_number", "supplier_name"), "buying", "invoices"),
    SearchEntity("supplier_payment", "Supplier Payments", "/buying/payments/{id}", "ReceiptText", ("buying.view", "purchases.view"), ("voucher_number", "supplier_name"), "buying", "payment_vouchers"),
    SearchEntity("blanket_po", "Blanket Purchase Orders", "/buying/blanket-po/{id}", "ScrollText", ("buying.blanket_view", "buying.view"), ("agreement_number", "supplier_name"), "buying", "blanket_purchase_orders"),
    SearchEntity("rfq", "Requests For Quotation", "/buying/rfq?rfq_id={id}", "ClipboardQuestion", ("buying.view", "purchases.view"), ("rfq_number", "title"), "buying", "request_for_quotations"),
    SearchEntity("supplier_rating", "Supplier Ratings", "/buying/supplier-ratings?rating_id={id}", "Star", ("buying.view", "purchases.view"), ("supplier_name", "comments"), "buying", "supplier_ratings"),
    SearchEntity("purchase_agreement", "Purchase Agreements", "/buying/agreements?agreement_id={id}", "Handshake", ("buying.view", "purchases.view"), ("agreement_number", "title"), "buying", "purchase_agreements"),
    SearchEntity("landed_cost", "Landed Costs", "/buying/landed-costs/{id}", "ShipWheel", ("buying.view", "purchases.view"), ("lc_number", "reference"), "buying", "landed_costs"),
    SearchEntity("employee", "Employees", "/hr/employees?employee_id={id}", "User", ("hr.view",), ("name", "employee_id"), "hr", "employees"),
    SearchEntity("department", "Departments", "/hr/departments?department_id={id}", "Building2", ("hr.view",), ("department_name", "department_code"), "hr", "departments"),
    SearchEntity("position", "Positions", "/hr/positions?position_id={id}", "BriefcaseBusiness", ("hr.view",), ("position_name", "position_code"), "hr", "employee_positions"),
    SearchEntity("leave_request", "Leave Requests", "/hr/leaves?leave_id={id}", "CalendarDays", ("hr.view", "hr.leaves.view"), ("employee_name", "leave_type"), "hr", "leave_requests"),
    SearchEntity("attendance_record", "Attendance Records", "/hr/attendance?attendance_id={id}", "Clock3", ("hr.view",), ("employee_name", "status"), "hr", "attendance"),
    SearchEntity("employee_loan", "Employee Loans", "/hr/loans?loan_id={id}", "HandCoins", ("hr.view",), ("employee_name", "reason"), "hr", "employee_loans"),
    SearchEntity("overtime_request", "Overtime Requests", "/hr/overtime?overtime_id={id}", "Timer", ("hr.view",), ("employee_name", "reason"), "hr", "overtime_requests"),
    SearchEntity("performance_review", "Performance Reviews", "/hr/performance?review_id={id}", "ChartNoAxesColumn", ("hr.performance_view", "hr.view"), ("employee_name", "review_period"), "hr", "performance_reviews"),
    SearchEntity("payroll_period", "Payroll Periods", "/hr/payroll/{id}", "WalletCards", ("hr.view", "hr.payroll"), ("name", "status"), "hr", "payroll_entries"),
    SearchEntity("payroll_entry", "Payroll Entries", "/hr/payroll?payslip_id={id}", "ReceiptText", ("hr.view", "hr.payroll.view"), ("employee_name", "period_name"), "hr", "payroll_entries"),
    SearchEntity("salary_structure", "Salary Structures", "/hr/salary-structures?structure_id={id}", "Layers2", ("hr.view",), ("name", "description"), "hr", "salary_structures"),
    SearchEntity("employee_document", "Employee Documents", "/hr/documents?document_id={id}", "IdCard", ("hr.view",), ("employee_name", "document_type", "document_number"), "hr", "employee_documents"),
    SearchEntity("review_cycle", "Review Cycles", "/hr/performance/cycles?cycle_id={id}", "RotateCcw", ("hr.performance_view", "hr.view"), ("name", "status"), "hr", "review_cycles"),
    SearchEntity("training_program", "Training Programs", "/hr/training?training_id={id}", "GraduationCap", ("hr.view",), ("name", "trainer"), "hr", "training_programs"),
    SearchEntity("employee_violation", "Employee Violations", "/hr/violations?violation_id={id}", "ShieldAlert", ("hr.view",), ("employee_name", "violation_type"), "hr", "employee_violations"),
    SearchEntity("employee_custody", "Employee Custody", "/hr/custody?custody_id={id}", "PackageCheck", ("hr.view",), ("employee_name", "item_name", "serial_number"), "hr", "employee_custody"),
    SearchEntity("job_opening", "Job Openings", "/hr/recruitment?opening_id={id}", "Briefcase", ("hr.view",), ("title", "department_name"), "hr", "job_openings"),
    SearchEntity("job_application", "Job Applications", "/hr/recruitment?application_id={id}", "FileUser", ("hr.view",), ("applicant_name", "opening_title"), "hr", "job_applications"),
    SearchEntity("leave_carryover", "Leave Carryover", "/hr/leave-carryover?carryover_id={id}", "CalendarPlus", ("hr.view",), ("employee_name", "leave_type"), "hr", "leave_carryover"),
    SearchEntity("project", "Projects", "/projects/{id}", "Folder", ("projects.view",), ("name", "code"), "projects", "projects"),
    SearchEntity("project_task", "Project Tasks", "/projects?task_id={id}", "ListTodo", ("projects.view",), ("task_name", "project_name"), "projects", "project_tasks"),
    SearchEntity("project_timesheet", "Project Timesheets", "/projects/timesheets?timesheet_id={id}", "CalendarClock", ("projects.view", "projects.time_view"), ("employee_name", "project_name"), "projects", "project_timesheets"),
    SearchEntity("project_risk", "Project Risks", "/projects/risks?risk_id={id}", "TriangleAlert", ("projects.view",), ("title", "project_name"), "projects", "project_risks"),
    SearchEntity("resource_allocation", "Resource Allocations", "/projects/resources?allocation_id={id}", "UsersRound", ("projects.view", "projects.resource_manage"), ("employee_name", "project_name", "role"), "projects", "resource_allocations"),
    SearchEntity("task_dependency", "Task Dependencies", "/projects/gantt?dependency_id={id}", "GitBranch", ("projects.view",), ("task_name", "depends_on_task_name"), "projects", "task_dependencies"),
    SearchEntity("production_order", "Production Orders", "/manufacturing/orders/{id}", "Factory", ("manufacturing.view",), ("order_number", "product_name"), "manufacturing", "production_orders"),
    SearchEntity("work_center", "Work Centers", "/manufacturing/work-centers?work_center_id={id}", "Cog", ("manufacturing.view",), ("name", "code"), "manufacturing", "work_centers"),
    SearchEntity("manufacturing_route", "Manufacturing Routes", "/manufacturing/routing/{id}", "Route", ("manufacturing.view",), ("name", "product_name"), "manufacturing", "manufacturing_routes"),
    SearchEntity("manufacturing_bom", "Bills of Materials", "/manufacturing/boms?bom_id={id}", "Layers3", ("manufacturing.view",), ("name", "code", "product_name"), "manufacturing", "bill_of_materials"),
    SearchEntity("manufacturing_equipment", "Manufacturing Equipment", "/manufacturing/equipment?equipment_id={id}", "Wrench", ("manufacturing.view",), ("name", "code"), "manufacturing", "manufacturing_equipment"),
    SearchEntity("mrp_plan", "MRP Plans", "/manufacturing/mrp/{id}", "Boxes", ("manufacturing.view",), ("plan_name", "status"), "manufacturing", "mrp_plans"),
    SearchEntity("capacity_plan", "Capacity Plans", "/manufacturing/capacity?plan_id={id}", "Gauge", ("manufacturing.view",), ("work_center_name", "plan_date"), "manufacturing", "capacity_plans"),
    SearchEntity("shop_floor_log", "Shop Floor Logs", "/manufacturing/shopfloor?log_id={id}", "ClipboardPenLine", ("manufacturing.view",), ("order_number", "operator_name"), "manufacturing", "shop_floor_logs"),
    SearchEntity("asset", "Assets", "/assets/{id}", "Archive", ("assets.view",), ("name", "code"), "assets", "assets"),
    SearchEntity("asset_category", "Asset Categories", "/assets/management?category_id={id}", "FolderTree", ("assets.view",), ("category_name", "category_code"), "assets", "asset_categories"),
    SearchEntity("asset_transfer", "Asset Transfers", "/assets/management?transfer_id={id}", "MoveRight", ("assets.view",), ("asset_name", "reason"), "assets", "asset_transfers"),
    SearchEntity("asset_disposal", "Asset Disposals", "/assets/management?disposal_id={id}", "ArchiveX", ("assets.view",), ("asset_name", "buyer_name"), "assets", "asset_disposals"),
    SearchEntity("asset_revaluation", "Asset Revaluations", "/assets/management?revaluation_id={id}", "TrendingUp", ("assets.view",), ("asset_name", "reason"), "assets", "asset_revaluations"),
    SearchEntity("asset_insurance", "Asset Insurance", "/assets/management?insurance_id={id}", "ShieldCheck", ("assets.view",), ("asset_name", "policy_number", "insurer"), "assets", "asset_insurance"),
    SearchEntity("asset_maintenance", "Asset Maintenance", "/assets/management?maintenance_id={id}", "Wrench", ("assets.view",), ("asset_name", "vendor"), "assets", "asset_maintenance"),
    SearchEntity("lease_contract", "Lease Contracts", "/assets/leases?lease_id={id}", "FileKey2", ("assets.view",), ("description", "lessor_name"), "assets", "lease_contracts"),
    SearchEntity("asset_impairment", "Asset Impairments", "/assets/impairment?impairment_id={id}", "TrendingDown", ("assets.view",), ("asset_name", "reason"), "assets", "asset_impairments"),
    SearchEntity("document", "Documents", "/services/documents?document_id={id}", "Files", ("services.view",), ("doc_number", "title", "file_name"), "services", "documents"),
    SearchEntity("service_request", "Service Requests", "/services/requests?request_id={id}", "Wrench", ("services.view",), ("title", "customer_name"), "services", "service_requests"),
    SearchEntity("pos_order", "POS Orders", "/pos?order_id={id}", "ShoppingBag", ("pos.view",), ("order_number", "customer_name"), "pos", "pos_orders"),
    SearchEntity("pos_session", "POS Sessions", "/pos?session_id={id}", "MonitorDot", ("pos.view",), ("session_code", "status"), "pos", "pos_sessions"),
    SearchEntity("pos_return", "POS Returns", "/pos?return_id={id}", "Undo2", ("pos.view", "pos.returns"), ("order_number", "refund_method"), "pos", "pos_returns"),
    SearchEntity("pos_promotion", "POS Promotions", "/pos/promotions?promotion_id={id}", "TicketPercent", ("pos.view",), ("name", "coupon_code"), "pos", "pos_promotions"),
    SearchEntity("pos_loyalty_program", "POS Loyalty Programs", "/pos/loyalty?program_id={id}", "BadgePercent", ("pos.view",), ("name",), "pos", "pos_loyalty_programs"),
    SearchEntity("pos_table", "POS Tables", "/pos/tables?table_id={id}", "Utensils", ("pos.view",), ("table_number", "table_name"), "pos", "pos_tables"),
    SearchEntity("pos_kitchen_order", "POS Kitchen Orders", "/pos/kitchen?kitchen_order_id={id}", "ChefHat", ("pos.view",), ("product_name", "station"), "pos", "pos_kitchen_orders"),
    SearchEntity("tax_return", "Tax Returns", "/taxes/returns/{id}", "Landmark", ("taxes.view",), ("return_number", "tax_period"), "taxes", "tax_returns"),
    SearchEntity("tax_calendar_event", "Tax Calendar", "/taxes/calendar?event_id={id}", "CalendarCheck", ("taxes.view",), ("title", "tax_type"), "taxes", "tax_calendar"),
    SearchEntity("tax_rate", "Tax Rates", "/taxes?tax_rate_id={id}", "Percent", ("taxes.view",), ("tax_name", "tax_code"), "taxes", "tax_rates"),
    SearchEntity("tax_group", "Tax Groups", "/taxes?tax_group_id={id}", "Landmark", ("taxes.view",), ("group_name", "group_code"), "taxes", "tax_groups"),
    SearchEntity("tax_classification", "Tax Classifications", "/taxes/classifications?classification_id={id}", "Landmark", ("taxes.manage", "taxes.view"), ("name_ar", "name_en", "code"), "taxes", "tax_classifications"),
    SearchEntity("tax_payment", "Tax Payments", "/taxes/compliance?payment_id={id}", "Receipt", ("taxes.view",), ("payment_number", "reference"), "taxes", "tax_payments"),
    SearchEntity("tax_regime", "Tax Regimes", "/taxes/compliance?regime_id={id}", "Scale", ("taxes.view",), ("regime_name", "country_code"), "taxes", "tax_regimes"),
    SearchEntity("wht_rate", "Withholding Tax Rates", "/taxes/wht?wht_rate_id={id}", "Percent", ("taxes.view",), ("name", "name_ar", "category"), "taxes", "wht_rates"),
    SearchEntity("wht_transaction", "Withholding Tax Transactions", "/taxes/wht?wht_transaction_id={id}", "ReceiptText", ("taxes.view",), ("certificate_number", "status"), "taxes", "wht_transactions"),
    SearchEntity("zakat_calculation", "Zakat Calculations", "/accounting/zakat?calculation_id={id}", "Calculator", ("accounting.view", "taxes.view"), ("fiscal_year", "status"), "accounting", "zakat_calculations"),
    SearchEntity("crm_opportunity", "CRM Opportunities", "/crm/opportunities?opportunity_id={id}", "Target", ("sales.view",), ("title", "customer_name"), "crm", "sales_opportunities"),
    SearchEntity("support_ticket", "Support Tickets", "/crm/tickets?ticket_id={id}", "LifeBuoy", ("sales.view",), ("ticket_number", "subject", "customer_name"), "crm", "support_tickets"),
    SearchEntity("marketing_campaign", "Marketing Campaigns", "/crm/campaigns/{id}", "Megaphone", ("crm.campaign_view", "sales.view"), ("name", "campaign_type"), "crm", "marketing_campaigns"),
    SearchEntity("crm_contact", "CRM Contacts", "/crm/contacts?contact_id={id}", "Contact", ("sales.view",), ("name", "customer_name"), "crm", "crm_contacts"),
    SearchEntity("crm_segment", "CRM Segments", "/crm/segments?segment_id={id}", "UsersRound", ("sales.view",), ("name", "description"), "crm", "crm_customer_segments"),
    SearchEntity("crm_knowledge_base", "CRM Knowledge Base", "/crm/knowledge-base?article_id={id}", "BookOpenText", ("sales.view",), ("title", "category", "tags"), "crm", "crm_knowledge_base"),
    SearchEntity("crm_sales_forecast", "CRM Sales Forecasts", "/crm/forecasts?forecast_id={id}", "ChartSpline", ("sales.view",), ("period", "forecast_type"), "crm", "crm_sales_forecasts"),
    SearchEntity("approval_workflow", "Approval Workflows", "/approvals/{id}/edit", "Workflow", ("settings.view", "approvals.view"), ("name", "document_type"), "approvals", "approval_workflows"),
    SearchEntity("approval_request", "Approval Requests", "/approvals?request_id={id}", "BadgeCheck", ("approvals.view",), ("document_type", "description"), "approvals", "approval_requests"),
    SearchEntity("cashflow_forecast", "Cash Flow Forecasts", "/finance/cashflow/{id}", "ChartArea", ("finance.cashflow_view",), ("name", "mode"), "finance", "cashflow_forecasts"),
    SearchEntity("subscription_plan", "Subscription Plans", "/finance/subscriptions/plans/{id}/edit", "PackagePlus", ("finance.subscription_view",), ("name", "description"), "finance", "subscription_plans"),
    SearchEntity("subscription_enrollment", "Subscription Enrollments", "/finance/subscriptions/enrollments/{id}", "RefreshCcwDot", ("finance.subscription_view",), ("customer_name", "plan_name"), "finance", "subscription_enrollments"),
    SearchEntity("revenue_schedule", "Revenue Recognition Schedules", "/accounting/revenue-recognition?schedule_id={id}", "CalendarCheck", ("accounting.view",), ("invoice_number", "contract_number"), "accounting", "revenue_recognition_schedules"),
    SearchEntity("intercompany_entity", "Intercompany Entities", "/accounting/intercompany/entities?entity_id={id}", "Building", ("accounting.view",), ("name", "company_id"), "accounting", "entity_groups"),
    SearchEntity("intercompany_transaction", "Intercompany Transactions", "/accounting/intercompany/transactions?transaction_id={id}", "ArrowLeftRight", ("accounting.view",), ("reference_document", "transaction_type"), "accounting", "intercompany_transactions_v2"),
    SearchEntity("branch", "Branches", "/settings/branches?branch_id={id}", "GitBranch", ("branches.view",), ("branch_name", "branch_code"), None, "branches"),
    SearchEntity("role", "Roles", "/admin/roles?role_id={id}", "Shield", ("admin.roles",), ("role_name", "role_name_ar"), None, "roles"),
    SearchEntity("audit_log", "Audit Logs", "/admin/audit-logs?log_id={id}", "ClipboardList", ("audit.view",), ("action", "resource_type", "username"), "audit", "audit_logs"),
    SearchEntity("security_event", "Security Events", "/admin/security-events?event_id={id}", "ShieldAlert", ("admin.security", "security.view"), ("event_type", "severity"), "audit", "security_events"),
    SearchEntity("email_template", "Email Templates", "/settings/email-templates?template_id={id}", "Mail", ("settings.view", "email_templates.admin"), ("template_name", "code", "subject"), None, "email_templates"),
    SearchEntity("print_template", "Print Templates", "/settings/print-templates?template_id={id}", "Printer", ("settings.view",), ("name", "template_type"), None, "print_templates"),
    SearchEntity("webhook", "Webhooks", "/settings/webhooks?webhook_id={id}", "Webhook", ("settings.view", "admin"), ("name", "events"), None, "webhooks"),
    SearchEntity("sso_configuration", "SSO Configurations", "/settings/sso/{id}", "KeyRound", ("settings.view",), ("display_name", "provider_type"), None, "sso_configurations"),
    SearchEntity("integration_key", "Integration Keys", "/settings/api-keys?integration_key_id={id}", "Key", ("admin", "settings.view"), ("integration_type", "provider", "key_name"), None, "integration_keys"),
    SearchEntity("integration_dlq", "Integration DLQ", "/settings/integration-dlq?item_id={id}", "ArchiveRestore", ("admin",), ("queue_type", "provider", "reason"), None, "integration_dlq"),
    SearchEntity("notification_queue_item", "Notification Queue", "/settings/notifications/queue?item_id={id}", "BellRing", ("notifications.admin",), ("event_type", "recipient", "template_code"), None, "notifications_queue"),
    SearchEntity("company_setting", "Company Settings", "/settings?setting_id={id}", "Settings", ("settings.view",), ("setting_key",), None, "company_settings"),
    SearchEntity("sales_commission", "Sales Commissions", "/sales/commissions?commission_id={id}", "Percent", ("sales.view",), ("salesperson_name", "invoice_number", "status"), "sales", "sales_commissions"),
    SearchEntity("cpq_quote", "CPQ Quotes", "/sales/cpq/quotes/{id}", "FileSignature", ("sales.view",), ("status",), "sales", "cpq_quotes"),
    SearchEntity("cpq_pricing_rule", "CPQ Pricing Rules", "/sales/cpq/products?rule_id={id}", "SlidersHorizontal", ("sales.view",), ("rule_type",), "sales", "cpq_pricing_rules"),
    SearchEntity("demand_forecast", "Demand Forecasts", "/inventory/forecast/{id}", "TrendingUp", ("inventory.forecast_view",), ("forecast_method",), "stock", "demand_forecasts"),
    SearchEntity("expense_policy", "Expense Policies", "/expenses/policies?policy_id={id}", "FileText", ("expenses.view",), ("name", "expense_type"), "expenses", "expense_policies"),
    SearchEntity("bank_import_batch", "Bank Import Batches", "/treasury/bank-import?batch_id={id}", "Upload", ("treasury.view",), ("file_name", "status"), "treasury", "bank_import_batches"),
    SearchEntity("match_tolerance", "Match Tolerances", "/buying/matching/tolerances?tolerance_id={id}", "Settings2", ("buying.edit",), ("name",), "buying", "match_tolerances"),
    SearchEntity("eos_provision", "End of Service Provisions", "/hr/end-of-service?provision_id={id}", "UserMinus", ("hr.view",), ("employee_name",), "hr", "eos_provisions"),
    SearchEntity("alert_rule", "Alert Rules", "/settings/smart-alerts?rule_id={id}", "BellRing", ("settings.view",), ("name", "rule_type"), None, "alert_rules"),
)

MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "stock": ("stock", "inventory"),
    "buying": ("buying", "purchases"),
}


def get_registry() -> list[dict]:
    """Return the full search registry as a list of dicts."""
    return [
        {
            "entity_code": e.entity_code,
            "label": e.label,
            "route_template": e.route_template,
            "icon": e.icon,
            "permissions_required": list(e.permissions_required),
            "search_fields": list(e.search_fields),
            "module_key": e.module_key,
            "resource": e.resource,
        }
        for e in SEARCH_REGISTRY
    ]


def module_is_enabled(module_key: str | None, enabled_modules) -> bool:
    """Return whether a module is enabled; empty modules means unrestricted."""
    if not module_key:
        return True

    modules = set(enabled_modules or [])
    if not modules:
        return True

    accepted = MODULE_ALIASES.get(module_key, (module_key,))
    return any(module in modules for module in accepted)


def get_registry_for_user(user_permissions: set[str], enabled_modules=None) -> list[dict]:
    """Return registry entries the user has permission to see."""
    entries = [
        entry for entry in get_registry()
        if module_is_enabled(entry.get("module_key"), enabled_modules)
    ]

    if "*" in user_permissions:
        return entries

    permissions = list(user_permissions)
    return [
        entry for entry in entries
        if not entry["permissions_required"] or
           any(check_permission(permissions, p) for p in entry["permissions_required"])
    ]
