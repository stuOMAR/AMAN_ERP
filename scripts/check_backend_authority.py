#!/usr/bin/env python3
"""
Backend Authority Pre-Flight Check
═══════════════════════════════════
يشغّل قبل البدء بأي وحدة للتأكد من:
1. وجود submitted_grand_total في schemas
2. وجود preview endpoints في routers
3. إرسال submitted_grand_total من frontend
4. وجود Idempotency-Key على mutations
5. استخدام Decimal (لا float)

الاستخدام:
    python scripts/check_backend_authority.py                    # فحص جميع الوحدات
    python scripts/check_backend_authority.py --module sales     # فحص وحدة محددة
    python scripts/check_backend_authority.py --strict           # فحص صارم (exit 1 عند failure)
"""
import re
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

# ═══════════════════════════════════════════════════════════════
# Configuration: Module → Files mapping
# ═══════════════════════════════════════════════════════════════

MODULES = {
    "sales": {
        "label": "Sales / Invoices / Orders / Returns / Receipts",
        "schemas": [
            "backend/routers/sales/schemas.py",
            "backend/schemas/sales_credit_notes.py",
        ],
        "routers": [
            "backend/routers/sales/invoices.py",
            "backend/routers/sales/orders.py",
            "backend/routers/sales/returns.py",
            "backend/routers/sales/quotations.py",
            "backend/routers/sales/credit_notes.py",
            "backend/routers/sales/vouchers.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Sales/InvoiceForm.jsx",
            "frontend/src/pages/Sales/SalesOrderForm.jsx",
            "frontend/src/pages/Sales/SalesReturnForm.jsx",
            "frontend/src/pages/Sales/SalesQuotationForm.jsx",
            "frontend/src/pages/Sales/SalesCreditNotes.jsx",
            "frontend/src/pages/Sales/SalesDebitNotes.jsx",
        ],
        "create_endpoints": {
            "invoices.py":        {"path": "/invoices",        "method": "POST", "needs_total": True},
            "orders.py":          {"path": "/orders",          "method": "POST", "needs_total": True},
            "returns.py":         {"path": "/returns",         "method": "POST", "needs_total": True},
            "quotations.py":      {"path": "/quotations",      "method": "POST", "needs_total": True},
            "credit_notes.py":    {"path": "/credit-notes",    "method": "POST", "needs_total": True},
            "credit_notes.py_dn": {"path": "/debit-notes",     "method": "POST", "needs_total": True},
            "vouchers.py":        {"path": "/receipts",        "method": "POST", "needs_total": False},
            "vouchers.py_pay":    {"path": "/payments",        "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "invoices.py":     "/invoices/preview",
            "orders.py":       "/orders/preview",
            "returns.py":      "/returns/preview",
            "quotations.py":   "/quotations/preview",
            "credit_notes.py": "/credit-notes/preview",
            "credit_notes.py_dn": "/debit-notes/preview",
            "vouchers.py":     "/receipts/preview",
        },
    },
    "purchases": {
        "label": "Purchases / Procurement / Supplier Invoices",
        "schemas": [
            "backend/schemas/purchases.py",
        ],
        "routers": [
            "backend/routers/purchases/invoices.py",
            "backend/routers/purchases/orders.py",
            "backend/routers/purchases/returns.py",
            "backend/routers/purchases/payments.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Buying/PurchaseInvoiceForm.jsx",
            "frontend/src/pages/Buying/BuyingOrderForm.jsx",
            "frontend/src/pages/Buying/BuyingReturnForm.jsx",
        ],
        "create_endpoints": {
            "invoices.py":  {"path": "/invoices",  "method": "POST", "needs_total": True},
            "orders.py":    {"path": "/orders",    "method": "POST", "needs_total": True},
            "returns.py":   {"path": "/returns",   "method": "POST", "needs_total": True},
            "payments.py":  {"path": "/payments",  "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "invoices.py": "/invoices/preview",
            "payments.py": "/payments/preview",
        },
    },
    "finance": {
        "label": "Finance / Treasury / GL / Budgets",
        "schemas": [
            "backend/schemas/payments.py",
        ],
        "routers": [
            "backend/routers/finance/accounting/journal.py",
            "backend/routers/finance/treasury.py",
            "backend/routers/finance/expenses.py",
            "backend/routers/finance/checks.py",
            "backend/routers/finance/notes.py",
            "backend/routers/finance/reconciliation.py",
        ],
        "frontend_pages": [],
        "create_endpoints": {
            "journal.py":       {"path": "/journal-entries",  "method": "POST", "needs_total": False},
            "treasury.py":      {"path": "/accounts",         "method": "POST", "needs_total": False},
            "expenses.py":      {"path": "/expenses",         "method": "POST", "needs_total": False},
            "checks.py":        {"path": "/receivable",       "method": "POST", "needs_total": False},
            "notes.py":         {"path": "/receivable",       "method": "POST", "needs_total": False},
            "reconciliation.py": {"path": "/reconciliation",  "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "journal.py": "/journal-entries/preview",
        },
    },
    "pos": {
        "label": "POS / Point of Sale",
        "schemas": [
            "backend/schemas/pos.py",
        ],
        "routers": [
            "backend/routers/pos/orders.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/POS/POSInterface.jsx",
        ],
        "create_endpoints": {
            "orders.py": {"path": "/orders", "method": "POST", "needs_total": True},
        },
        "preview_endpoints": {
            "orders.py": "/orders/preview",
        },
    },
    "inventory": {
        "label": "Inventory / Stock / Warehouses",
        "schemas": [],
        "routers": [
            "backend/routers/inventory/batches.py",
            "backend/routers/inventory/shipments.py",
            "backend/routers/inventory/transfers.py",
            "backend/routers/inventory/adjustments.py",
        ],
        "frontend_pages": [],
        "create_endpoints": {
            "batches.py":     {"path": "/batches",     "method": "POST", "needs_total": False},
            "shipments.py":   {"path": "/shipments",   "method": "POST", "needs_total": False},
            "transfers.py":   {"path": "/transfers",   "method": "POST", "needs_total": False},
            "adjustments.py": {"path": "/adjustments",  "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {},
    },
    
    "hr": {
        "label": "HR / Payroll / Attendance / Leave / WPS / GOSI",
        "schemas": [
            "backend/routers/hr/core/core.py",
        ],
        "submitted_total_schemas": ["PayslipGenerateRequest"],
        "routers": [
            "backend/routers/hr/core/payroll.py",
            "backend/routers/hr/advances.py",
            "backend/routers/hr/employee_receipts.py",
            "backend/routers/hr/core/leaves.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/HR/Payslips.jsx",
        ],
        "create_endpoints": {
            "payroll.py": {"path": "/payslips/generate", "method": "POST", "needs_total": True},
            "advances.py": {"path": "/advances", "method": "POST", "needs_total": False},
            "leaves.py": {"path": "/leaves", "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "payroll.py": "/payslips/preview",
        },
    },
    "manufacturing": {
        "label": "Manufacturing / MRP / BOM",
        "schemas": [],
        "routers": [
            "backend/routers/manufacturing/core/orders.py",
            "backend/routers/manufacturing/core/boms.py",
        ],
        "frontend_pages": [],
        "create_endpoints": {
            "orders.py": {"path": "/orders", "method": "POST", "needs_total": False},
            "boms.py":   {"path": "/boms",   "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {},
    },
    "assets": {
        "label": "Assets / Leases / Depreciation / Impairment",
        "schemas": [
            "backend/schemas/assets.py",
        ],
        "routers": [
            "backend/routers/finance/assets/core.py",
            "backend/routers/finance/assets/depreciation.py",
            "backend/routers/finance/assets/leases.py",
            "backend/routers/finance/assets/transfers.py",
            "backend/routers/finance/assets/impairment.py",
            "backend/routers/finance/assets/revaluations.py",
            "backend/routers/finance/assets/insurance.py",
            "backend/routers/finance/assets/maintenance.py",
            "backend/routers/finance/assets/qr.py",
            "backend/routers/finance/assets/reports.py",
        ],
        "frontend_pages": [],
        "create_endpoints": {
            "core.py": {"path": "/{asset_id}/dispose", "method": "POST", "needs_total": True},
        },
        "preview_endpoints": {
            "depreciation.py": "/depreciate/preview",
            "leases.py": "/leases/preview",
        },
    },
    "projects": {
        "label": "Project Accounting & Invoicing",
        "schemas": [
            "backend/schemas/projects.py",
        ],
        "submitted_total_schemas": [
            "ProjectExpenseCreate",
            "ProjectRevenueCreate",
            "ProjectInvoiceCreate",
        ],
        "routers": [
            "backend/routers/projects/core.py",
            "backend/routers/projects/finance.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Projects/ProjectDetails.jsx",
        ],
        "create_endpoints": {
            "core.py": {"path": "/{project_id}/create-invoice", "method": "POST", "needs_total": True},
            "finance.py": {"path": "/{project_id}/expenses|/{project_id}/revenues", "method": "POST", "needs_total": True},
        },
        "preview_endpoints": {
            "core.py": "/{project_id}/create-invoice/preview",
        },
    },
    "taxes": {
        "label": "Taxes / ZATCA / WHT / Zakat / E-Invoicing",
        "schemas": [
            "backend/schemas/taxes.py",
        ],
        "submitted_total_schemas": ["TaxReturnCreate"],
        "submitted_total_fields": ["submitted_tax_due", "submitted_grand_total"],
        "routers": [
            "backend/routers/finance/taxes/returns_.py",
            "backend/routers/finance/taxes/core.py",
            "backend/routers/finance/taxes/payments.py",
            "backend/routers/einvoicing/outbox_admin.py",
            "backend/integrations/einvoicing/zatca_adapter.py",
            "backend/integrations/einvoicing/eta_adapter.py",
            "backend/integrations/einvoicing/uae_fta_adapter.py",
            "backend/services/einvoicing/outbox.py",
            "backend/services/einvoicing/ubl_builder.py",
            "backend/services/einvoicing/ubl_signer.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Taxes/TaxReturnForm.jsx",
            "frontend/src/pages/Taxes/TaxReturnDetails.jsx",
        ],
        "create_endpoints": {
            "returns_.py": {"path": "/returns", "method": "POST", "needs_total": True},
            "core.py": {"path": "/settle", "method": "POST", "needs_total": False},
            "payments.py": {"path": "/payments", "method": "POST", "needs_total": False},
            "outbox_admin.py": {"path": "/{outbox_id}/reprocess", "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "returns_.py": "/returns/preview",
        },
    },
    "contracts": {
        "label": "Contracts / Subscriptions / Services / FSM",
        "schemas": [
            "backend/schemas/contracts.py",
        ],
        "submitted_total_schemas": [
            "ContractInvoiceGenerateRequest",
        ],
        "routers": [
            "backend/routers/contracts.py",
            "backend/routers/finance/subscriptions.py",
            "backend/routers/fsm/contracts_renewal.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Sales/ContractDetails.jsx",
        ],
        "create_endpoints": {
            "contracts.py": {"path": "/{contract_id}/generate-invoice", "method": "POST", "needs_total": True},
            "subscriptions.py": {"path": "/enroll", "method": "POST", "needs_total": False},
            "contracts_renewal.py": {"path": "/{contract_id}/renew", "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "contracts.py": "/preview, /billing-cycle/preview",
        },
        "required_patterns": [
            {
                "file": "frontend/src/pages/Sales/ContractForm.jsx",
                "pattern": r"contractsAPI\.previewContract",
                "message": "Contract form must call /contracts/preview",
            },
            {
                "file": "frontend/src/App.jsx",
                "pattern": r'permission="contracts\.view"><ContractList',
                "message": "Contract list route must use contracts.view",
            },
            {
                "file": "frontend/src/App.jsx",
                "pattern": r'permission="contracts\.view"><ContractDetails',
                "message": "Contract details route must use contracts.view",
            },
            {
                "file": "backend/routers/fsm/contracts_renewal.py",
                "pattern": r'APIRouter\(prefix="/fsm/service-contracts"',
                "message": "FSM renewal router must not double-prefix /api",
            },
        ],
    },
    "reports": {
        "label": "Reports / KPI / Dashboards / Analytics",
        "schemas": [],
        "routers": [
            "backend/routers/reports/accounting_statements.py",
            "backend/routers/reports/accounting_compare_export.py",
            "backend/routers/reports/kpi.py",
            "backend/routers/dashboard.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Accounting/GeneralLedger.jsx",
            "frontend/src/pages/Reports/KPIDashboard.jsx",
            "frontend/src/pages/Reports/CashFlowIAS7.jsx",
            "frontend/src/pages/Reports/FXGainLossReport.jsx",
            "frontend/src/pages/Reports/DetailedProfitLoss.jsx",
            "frontend/src/pages/Analytics/DashboardView.jsx",
        ],
        "create_endpoints": {},
        "preview_endpoints": {},
        "idempotency_optional_routers": [
            "dashboard.py",
        ],
        "frontend_forbidden_patterns": [
            {
                "pattern": r"\.reduce\(",
                "message": "financial report totals must come from backend summary endpoints",
            },
            {
                "pattern": r"\bNumber\(",
                "message": "financial report values must stay backend-formatted Decimal strings",
            },
            {
                "pattern": r"parseFloat",
                "message": "financial report values must not be parsed as JavaScript floats",
            },
            {
                "pattern": r"toFixed\(",
                "message": "financial report rounding must come from backend Decimal logic",
            },
            {
                "pattern": r"toLocaleString\(",
                "message": "financial report numeric formatting must use Decimal-string helpers",
            },
        ],
        "required_patterns": [
            {
                "file": "backend/routers/reports/accounting_statements.py",
                "pattern": r"limit: int = Query\(25, ge=1, le=100\)",
                "message": "General ledger caps report pagination at 100",
            },
            {
                "file": "backend/routers/reports/accounting_statements.py",
                "pattern": r'"pagination": \{',
                "message": "General ledger returns pagination metadata",
            },
            {
                "file": "backend/routers/reports/accounting_compare_export.py",
                "pattern": r"_get_general_ledger_data\(",
                "message": "General ledger export uses the backend data helper",
            },
            {
                "file": "backend/routers/reports/accounting_compare_export.py",
                "pattern": r"limit=None",
                "message": "General ledger export bypasses UI pagination intentionally",
            },
            {
                "file": "backend/routers/dashboard.py",
                "pattern": r"def _widget_summary",
                "message": "Analytics widgets return backend-calculated summaries",
            },
            {
                "file": "backend/routers/dashboard.py",
                "pattern": r"branch_id = ANY\(:branch_ids\)",
                "message": "Analytics widgets apply backend branch filters against MV data",
            },
            {
                "file": "backend/routers/dashboard.py",
                "pattern": r'"summary": _widget_summary',
                "message": "Widget payload includes authoritative summary",
            },
            {
                "file": "backend/db_ddl/tenant_schema.py",
                "pattern": r"analytics_mv_freshness",
                "message": "Tenant schema includes analytics MV freshness tracking",
            },
            {
                "file": "backend/db_ddl/tenant_schema.py",
                "pattern": r"ux_mv_revenue_month ON mv_revenue_summary\(month, branch_id\)",
                "message": "Analytics materialized views are branch-aware",
            },
            {
                "file": "backend/alembic/versions/031e_reports_analytics_mvs.py",
                "pattern": r"DROP MATERIALIZED VIEW IF EXISTS mv_revenue_summary",
                "message": "Analytics MV migration recreates stale incompatible views",
            },
            {
                "file": "backend/routers/reports/__init__.py",
                "pattern": r"refresh_report_mvs\(tenant_id=tenant_id\)",
                "message": "Report cache refresh is scoped to the authenticated tenant",
            },
            {
                "file": "backend/services/reports/mv_refresh.py",
                "pattern": r"ANALYTICS_MVS = \{",
                "message": "On-demand report refresh includes analytics materialized views",
            },
            {
                "file": "backend/services/reports/mv_refresh.py",
                "pattern": r"analytics_mv_freshness",
                "message": "On-demand analytics refresh updates freshness metadata",
            },
            {
                "file": "backend/services/reports/mv_refresh.py",
                "pattern": r"pg_matviews",
                "message": "On-demand MV refresh checks view existence before refreshing",
            },
            {
                "file": "frontend/src/pages/Analytics/DashboardView.jsx",
                "pattern": r"widget\.summary",
                "message": "Analytics dashboard displays backend widget summary",
            },
            {
                "file": "frontend/src/pages/Analytics/DashboardView.jsx",
                "pattern": r"widget\.value_keys",
                "message": "Analytics charts use backend value keys",
            },
            {
                "file": "frontend/src/pages/Accounting/GeneralLedger.jsx",
                "pattern": r"skip: \(page - 1\) \* pageSize",
                "message": "General ledger frontend sends backend pagination offset",
            },
            {
                "file": "frontend/src/pages/Accounting/GeneralLedger.jsx",
                "pattern": r"<Pagination",
                "message": "General ledger frontend exposes backend pagination controls",
            },
            {
                "file": "frontend/src/services/dashboard.js",
                "pattern": r"getAnalyticsDashboard: \(id, config = \{\}\)",
                "message": "Analytics API forwards backend filters and pagination",
            },
        ],
    },
    "security_admin": {
        "label": "Approvals / Workflow / Audit / Security / Admin",
        "schemas": [],
        "routers": [
            "backend/routers/approvals.py",
            "backend/routers/finance/advanced_workflow.py",
            "backend/routers/audit.py",
            "backend/routers/security.py",
            "backend/routers/settings.py",
            "backend/routers/roles.py",
            "backend/utils/audit.py",
            "backend/services/audit_writer.py",
            "backend/services/audit_outbox_worker.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/Approvals/ApprovalsPage.jsx",
            "frontend/src/services/approvals.js",
            "frontend/src/utils/auth.js",
        ],
        "create_endpoints": {},
        "preview_endpoints": {},
        "idempotency_optional_routers": [
            "security.py",
            "settings.py",
            "roles.py",
        ],
        "decimal_optional_routers": [
            "settings.py",
        ],
        "frontend_forbidden_patterns": [
            {
                "pattern": r"status\s*:\s*actionType",
                "message": "approval UI must send action, not a final status field",
            },
            {
                "pattern": r"status\s*:\s*['\"](?:approved|rejected|posted|finalized)['\"]",
                "message": "approval UI must not submit final workflow states as facts",
            },
        ],
        "required_patterns": [
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"require_idempotency_key\(http_request, operation=\"approval action\"\)",
                "message": "Approval action endpoint requires Idempotency-Key",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"INSERT INTO approval_actions \(request_id, step, action, actioned_by, notes, idempotency_key\)",
                "message": "Approval actions persist the idempotency key",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"approval_request = db\.execute",
                "message": "Approval action handler does not shadow the FastAPI request object",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"def _user_can_approve_step",
                "message": "Backend validates the actor against the current approval step",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"APPROVER_ELIGIBILITY_SQL",
                "message": "Pending approvals are filtered to the current approver",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"WHERE role = :role AND is_active = TRUE",
                "message": "Approval notifications use the tenant user role model",
            },
            {
                "file": "backend/routers/approvals.py",
                "pattern": r"critical=True",
                "message": "Approval mutations fail closed when audit enqueue fails",
            },
            {
                "file": "backend/routers/finance/advanced_workflow.py",
                "pattern": r"require_idempotency_key\(request, operation=\"workflow auto approval\"\)",
                "message": "Bulk auto-approval requires Idempotency-Key",
            },
            {
                "file": "backend/routers/finance/advanced_workflow.py",
                "pattern": r"require_permission\(\"approvals\.edit\"\)",
                "message": "Workflow escalation mutation requires edit permission",
            },
            {
                "file": "backend/routers/finance/advanced_workflow.py",
                "pattern": r'"total_requests": total_requests',
                "message": "Workflow analytics returns frontend-compatible top-level totals",
            },
            {
                "file": "backend/routers/finance/advanced_workflow.py",
                "pattern": r'"approval_rate": str\(approval_rate\)',
                "message": "Workflow analytics returns backend-calculated approval rate",
            },
            {
                "file": "backend/routers/governance.py",
                "pattern": r"action=\"approvals\.sla_escalate\"",
                "message": "Governance approval SLA escalation writes an audit event",
            },
            {
                "file": "backend/routers/governance.py",
                "pattern": r"critical=True",
                "message": "Governance approval SLA escalation fails closed on audit enqueue errors",
            },
            {
                "file": "backend/utils/permissions.py",
                "pattern": r'"approvals\.action": \["approvals\.approve"\]',
                "message": "Backend permission aliases map approvals.action to approvals.approve",
            },
            {
                "file": "backend/utils/permissions.py",
                "pattern": r'"approvals\.view", "approvals\.create", "approvals\.edit"',
                "message": "Backend approvals.manage implies edit/action/approve permissions",
            },
            {
                "file": "backend/routers/audit.py",
                "pattern": r"from utils\.i18n import http_error",
                "message": "Audit router imports localized HTTP errors",
            },
            {
                "file": "backend/routers/audit.py",
                "pattern": r"limit: int = Query\(50, ge=1, le=100\)",
                "message": "Audit log list caps pagination at 100",
            },
            {
                "file": "backend/routers/audit.py",
                "pattern": r"resolve_target_company_id",
                "message": "Audit log access resolves the authorized tenant",
            },
            {
                "file": "backend/routers/security.py",
                "pattern": r"limit: int = Query\(50, ge=1, le=100\)",
                "message": "Security event lists cap pagination at 100",
            },
            {
                "file": "backend/routers/settings.py",
                "pattern": r"require_sensitive_permission\(\"settings\.manage\", critical=True\)",
                "message": "Sensitive settings mutations revalidate permission",
            },
            {
                "file": "backend/routers/roles.py",
                "pattern": r"require_permission\(\"admin\.roles\"\)",
                "message": "Role and permission administration is protected",
            },
            {
                "file": "backend/db_ddl/tenant_schema.py",
                "pattern": r"uq_approval_actions_idempotency",
                "message": "Tenant schema includes approval action idempotency index",
            },
            {
                "file": "backend/alembic/versions/031f_approvals_workflow_security_authority.py",
                "pattern": r"uq_approval_actions_idempotency",
                "message": "Approval action idempotency migration is present",
            },
            {
                "file": "backend/services/audit_writer.py",
                "pattern": r"raise AuditWriteError\(f\"Failed to enqueue audit row for \{action\}\"\)",
                "message": "Audit writer does not expose raw exception details",
            },
            {
                "file": "backend/services/audit_outbox_worker.py",
                "pattern": r"SELECT setting_value FROM company_settings WHERE setting_key = :k",
                "message": "Audit outbox worker reads company_settings using the tenant schema",
            },
            {
                "file": "backend/services/audit_outbox_worker.py",
                "pattern": r"\"flush_failed\"",
                "message": "Audit outbox worker stores sanitized failure markers",
            },
            {
                "file": "backend/main.py",
                "pattern": r"Unhandled exception on %s %s",
                "message": "Global exception handler does not log raw exception details",
            },
            {
                "file": "frontend/src/pages/Approvals/ApprovalsPage.jsx",
                "pattern": r"makeIdempotencyKey\('approval-action'\)",
                "message": "Approval page sends Idempotency-Key for action requests",
            },
            {
                "file": "frontend/src/pages/Approvals/ApprovalsPage.jsx",
                "pattern": r"openDetailsModal\(item\)",
                "message": "Approval request details use an in-page modal instead of an unregistered route",
            },
            {
                "file": "frontend/src/pages/Approvals/ApprovalsPage.jsx",
                "pattern": r"\{actionType && \(",
                "message": "Approval details modal only renders action controls for action flows",
            },
            {
                "file": "frontend/src/services/approvals.js",
                "pattern": r"'Idempotency-Key'",
                "message": "Approval API client sends Idempotency-Key for actions",
            },
            {
                "file": "frontend/src/utils/auth.js",
                "pattern": r"'approvals\.action': \['approvals\.approve'\]",
                "message": "Frontend permission aliases map approvals.action to approvals.approve",
            },
            {
                "file": "frontend/src/utils/auth.js",
                "pattern": r"'approvals\.manage': \['approvals\.view', 'approvals\.create', 'approvals\.edit', 'approvals\.action', 'approvals\.approve'\]",
                "message": "Frontend approvals.manage implies edit/action/approve permissions",
            },
        ],
    },
    "integrations": {
        "label": "Integrations / DMS / Notifications / Imports",
        "schemas": [],
        "routers": [
            "backend/routers/integrations_admin.py",
            "backend/routers/data_import.py",
            "backend/routers/dms/quotas_admin.py",
            "backend/routers/notifications/core.py",
            "backend/routers/notifications/queue_admin.py",
            "backend/routers/notifications/templates_admin.py",
            "backend/services/integration_keys_service.py",
            "backend/services/integration_retry_service.py",
            "backend/services/webhooks/dispatch.py",
            "backend/services/dms/storage_paths.py",
            "backend/services/dms/antimalware.py",
            "backend/services/dms/streaming_mime.py",
            "backend/services/notifications/dispatcher.py",
            "backend/services/notifications/queue_worker.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/DataImport/DataImportPage.jsx",
            "frontend/src/pages/Settings/IntegrationDLQ.jsx",
            "frontend/src/pages/Settings/tabs/IntegrationKeysVault.jsx",
            "frontend/src/pages/dms/QuarantineAlerts.jsx",
            "frontend/src/pages/dms/QuotaMeter.jsx",
            "frontend/src/pages/notifications/NotificationQueueMonitor.jsx",
            "frontend/src/pages/notifications/EmailTemplateEditor.jsx",
            "frontend/src/services/dataImport.js",
            "frontend/src/services/integrationQueues.js",
            "frontend/src/services/notifications.js",
        ],
        "create_endpoints": {
            "data_import.py": {"path": "/data-import/execute", "method": "POST", "needs_total": False},
            "core.py": {"path": "/notifications/send", "method": "POST", "needs_total": False},
            "queue_admin.py": {"path": "/notifications/queue/{id}/retry", "method": "POST", "needs_total": False},
            "integrations_admin.py": {"path": "/integrations/dlq/{id}/replay", "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {
            "data_import.py": "/data-import/preview",
        },
        "idempotency_optional_routers": [
            "templates_admin.py",
        ],
        "frontend_forbidden_patterns": [
            {
                "pattern": r"dangerouslySetInnerHTML",
                "message": "integration/DMS/notification pages must not render unsanitized HTML",
            },
            {
                "pattern": r"\.innerHTML",
                "message": "integration/DMS/notification pages must not write raw HTML",
            },
            {
                "pattern": r"localStorage\.(?:setItem|getItem)\([^)]*(?:token|secret|api_key)",
                "message": "integration/DMS pages must not store secrets in localStorage",
            },
        ],
        "required_patterns": [
            {
                "file": "backend/services/integration_keys_service.py",
                "pattern": r"encrypted_value",
                "message": "Integration keys are stored encrypted and not returned as plaintext",
            },
            {
                "file": "backend/routers/integrations_admin.py",
                "pattern": r"sanitize_for_audit",
                "message": "Integration DLQ payloads are sanitized before admin display",
            },
            {
                "file": "backend/routers/integrations_admin.py",
                "pattern": r"limit: int = Query\(25, ge=1, le=100\)",
                "message": "Integration retry/DLQ lists cap pagination at 100",
            },
            {
                "file": "backend/routers/integrations_admin.py",
                "pattern": r"require_idempotency_key\(request, operation=\"integration DLQ replay\"\)",
                "message": "Integration DLQ replay requires Idempotency-Key",
            },
            {
                "file": "backend/routers/data_import.py",
                "pattern": r"require_idempotency_key\(request, operation=\"data import execute\"\)",
                "message": "Data import execution requires Idempotency-Key",
            },
            {
                "file": "backend/routers/data_import.py",
                "pattern": r"validate_file_mime_and_signature",
                "message": "Data import validates MIME/signature in addition to extension and size",
            },
            {
                "file": "backend/routers/data_import.py",
                "pattern": r"skip_errors: bool = Query\(False\)",
                "message": "Data import defaults to all-or-nothing execution",
            },
            {
                "file": "backend/routers/data_import.py",
                "pattern": r"_find_completed_import_by_idempotency_key",
                "message": "Data import execution dedupes completed confirmations by idempotency key",
            },
            {
                "file": "backend/routers/dms/quotas_admin.py",
                "pattern": r'APIRouter\(prefix="/dms"',
                "message": "DMS admin router mounts once under /api/dms",
            },
            {
                "file": "backend/routers/dms/quotas_admin.py",
                "pattern": r"quarantine_ref",
                "message": "DMS quarantine list does not expose local quarantine paths",
            },
            {
                "file": "backend/services/dms/storage_paths.py",
                "pattern": r"dms\.path_traversal",
                "message": "DMS storage paths guard against path traversal",
            },
            {
                "file": "backend/services/dms/antimalware.py",
                "pattern": r'"clean": False, "engine": "clamav", "error": "scan_unavailable"',
                "message": "DMS antimalware fails closed when scanning is unavailable",
            },
            {
                "file": "backend/routers/notifications/core.py",
                "pattern": r"require_idempotency_key\(request, operation=\"notification send\"\)",
                "message": "Notification sends require Idempotency-Key",
            },
            {
                "file": "backend/routers/notifications/core.py",
                "pattern": r"feature_source = :source",
                "message": "Notification sends dedupe by backend-stored idempotency source",
            },
            {
                "file": "backend/routers/notifications/queue_admin.py",
                "pattern": r"require_idempotency_key\(request, operation=\"notification retry\"\)",
                "message": "Notification retry requires Idempotency-Key",
            },
            {
                "file": "backend/services/webhooks/dispatch.py",
                "pattern": r"sanitize_for_audit\(payload or \{\}, context=\"webhook_dispatch\"\)",
                "message": "Webhook outbox payloads are sanitized before persistence",
            },
            {
                "file": "backend/services/webhooks/dispatch.py",
                "pattern": r"WHERE NOT EXISTS",
                "message": "Webhook dispatch dedupes already queued/sent deliveries",
            },
            {
                "file": "backend/services/integration_retry_service.py",
                "pattern": r"_sanitize_external_payload",
                "message": "Integration retry DLQ payloads and gateway responses are sanitized",
            },
            {
                "file": "backend/services/notifications/queue_worker.py",
                "pattern": r"_safe_error",
                "message": "Notification queue worker stores sanitized error markers",
            },
            {
                "file": "frontend/src/services/dataImport.js",
                "pattern": r"'Idempotency-Key': idempotencyKey",
                "message": "Data import frontend sends Idempotency-Key on execute",
            },
            {
                "file": "frontend/src/pages/DataImport/DataImportPage.jsx",
                "pattern": r"previewData\.preview_rows",
                "message": "Data import page renders backend preview rows",
            },
            {
                "file": "frontend/src/pages/DataImport/DataImportPage.jsx",
                "pattern": r"dataImportAPI\.executeImport",
                "message": "Data import page confirms via backend execute endpoint",
            },
            {
                "file": "frontend/src/services/integrationQueues.js",
                "pattern": r"replayDLQ: \(id, idempotencyKey",
                "message": "Integration DLQ replay API accepts an idempotency key",
            },
            {
                "file": "frontend/src/services/notifications.js",
                "pattern": r"'Idempotency-Key': idempotencyKey",
                "message": "Notification send API forwards Idempotency-Key",
            },
            {
                "file": "frontend/src/pages/notifications/NotificationQueueMonitor.jsx",
                "pattern": r"makeIdempotencyKey\(`notification-retry:\$\{id\}`\)",
                "message": "Notification queue retry sends an idempotency key",
            },
        ],
    },
    "crm": {
        "label": "CRM / Campaigns / Forecasts / Lead Scoring",
        "schemas": [
            "backend/routers/crm/core.py",
            "backend/schemas/campaign.py",
            "backend/schemas/forecast.py",
        ],
        "routers": [
            "backend/routers/crm/opportunities.py",
            "backend/routers/crm/campaigns.py",
            "backend/routers/crm/segments.py",
            "backend/routers/crm/analytics.py",
            "backend/routers/crm/velocity.py",
            "backend/routers/crm/funnel.py",
            "backend/routers/crm/cashflow.py",
            "backend/services/crm/velocity.py",
            "backend/services/crm/funnel.py",
            "backend/services/crm/cashflow_feed.py",
            "backend/services/kpi_service/crm.py",
        ],
        "frontend_pages": [
            "frontend/src/pages/CRM/CRMHome.jsx",
            "frontend/src/pages/CRM/Opportunities.jsx",
            "frontend/src/pages/CRM/MarketingCampaigns.jsx",
            "frontend/src/pages/CRM/SalesForecasts.jsx",
            "frontend/src/pages/CRM/LeadScoring.jsx",
            "frontend/src/pages/CRM/PipelineAnalytics.jsx",
            "frontend/src/pages/Campaign/CampaignList.jsx",
            "frontend/src/pages/Campaign/CampaignReport.jsx",
            "frontend/src/pages/Campaign/CampaignForm.jsx",
        ],
        "create_endpoints": {
            "opportunities.py": {"path": "/opportunities", "method": "POST", "needs_total": False},
            "campaigns.py": {"path": "/campaigns", "method": "POST", "needs_total": False},
        },
        "preview_endpoints": {},
        "idempotency_optional_routers": [
            "segments.py",
        ],
        "frontend_forbidden_patterns": [
            {
                "pattern": r"expected_value\s*:\s*Number\(",
                "message": "expected_value must be submitted as a Decimal string",
            },
            {
                "pattern": r"budget\s*:\s*Number\(",
                "message": "campaign budget must be submitted as a Decimal string",
            },
            {
                "pattern": r"reduce\(.*budget",
                "message": "campaign budget totals must come from backend summary endpoints",
            },
            {
                "pattern": r"reduce\(.*total_(sent|opened|clicked|responded)",
                "message": "campaign engagement totals must come from backend summary endpoints",
            },
            {
                "pattern": r"toFixed\(",
                "message": "campaign/forecast rates must come formatted from backend",
            },
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# Check Functions
# ═══════════════════════════════════════════════════════════════

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    file: Optional[str] = None
    line: Optional[int] = None


def _read_file(path: str) -> str:
    full = ROOT / path
    if not full.exists():
        return ""
    return full.read_text(encoding="utf-8", errors="replace")


def _find_pattern(content: str, pattern: str) -> list[tuple[int, str]]:
    """Return [(line_number, line_text), ...] for matches."""
    results = []
    for i, line in enumerate(content.splitlines(), 1):
        if re.search(pattern, line):
            results.append((i, line.strip()))
    return results


def check_schema_has_submitted_grand_total(module_cfg: dict) -> list[CheckResult]:
    """Check that schemas define submitted_grand_total field."""
    results = []
    target_schema_classes = module_cfg.get("submitted_total_schemas")
    total_fields = module_cfg.get("submitted_total_fields", ["submitted_grand_total"])
    if target_schema_classes:
        found_classes = {cls_name: False for cls_name in target_schema_classes}
        for schema_path in module_cfg.get("schemas", []):
            content = _read_file(schema_path)
            if not content:
                results.append(CheckResult(
                    name=f"Schema exists: {schema_path}",
                    passed=False,
                    message=f"File not found: {schema_path}",
                    file=schema_path,
                ))
                continue

            for cls_name in target_schema_classes:
                cls_match = re.search(rf"class\s+{cls_name}\s*\(", content)
                if not cls_match:
                    continue
                found_classes[cls_name] = True
                cls_start = content[:cls_match.start()].count("\n") + 1
                next_cls = re.search(r"\nclass\s+\w+\s*\(", content[cls_match.end():])
                cls_end = cls_match.end() + next_cls.start() if next_cls else len(content)
                cls_block = content[cls_match.start():cls_end]
                present_fields = [field for field in total_fields if field in cls_block]
                if present_fields:
                    results.append(CheckResult(
                        name=f"Schema {cls_name} has submitted total field",
                        passed=True,
                        message=f"{schema_path}: {cls_name} ✓ ({', '.join(present_fields)})",
                        file=schema_path,
                    ))
                else:
                    results.append(CheckResult(
                        name=f"Schema {cls_name} missing submitted total field",
                        passed=False,
                        message=f"{schema_path}: {cls_name} ❌ — add one of: {', '.join(total_fields)}",
                        file=schema_path,
                        line=cls_start,
                    ))

        for cls_name, found in found_classes.items():
            if not found:
                results.append(CheckResult(
                    name=f"Schema {cls_name} exists",
                    passed=False,
                    message=f"{cls_name} ❌ — class not found in configured schema files",
                ))
        return results

    # Schemas that don't need submitted_grand_total (no line-item calculations)
    SKIP_SCHEMAS = {
        "CustomerGroupCreate", "CustomerCreate", "CustomerResponse",
        "SupplierGroupCreate", "SupplierCreate", "SupplierPaymentCreate",
        "PaymentAllocation", "PaymentAllocationSchema",
        "SalesPreviewLineInput", "SalesDocumentPreviewRequest",
        "SalesReceiptAllocationPreviewRequest", "SupplierPaymentPreviewRequest",
        "InvoiceLineItem", "InvoiceResponse", "SOLineItem", "QuotationLineItem",
        "SalesReturnLineItem", "PurchaseLineItem", "ReceiveItem", "POReceiveRequest",
        "OrderLineCreate", "OrderPaymentCreate", "OrderResponse",
        "SessionCreate", "ReturnItemCreate", "ReturnCreate",
        "SalesNoteLine", "Shortage", "CancellationRequest", "CancellationResponse",
        "OrderToInvoiceRequest", "OrderToInvoiceResponse",
        "AssetCreate", "AssetTransferCreate", "AssetRevaluationCreate", "LeaseContractCreate",
        "InsuranceCreate", "MaintenanceCreate", "LeasePaymentCreate",
    }
    for schema_path in module_cfg.get("schemas", []):
        content = _read_file(schema_path)
        if not content:
            results.append(CheckResult(
                name=f"Schema exists: {schema_path}",
                passed=False,
                message=f"File not found: {schema_path}",
                file=schema_path,
            ))
            continue

        # Find all *Create and *Disposal classes
        create_classes = re.findall(r"class\s+(\w*(?:Create|Disposal)\w*)\s*\(", content)
        for cls_name in create_classes:
            if cls_name in SKIP_SCHEMAS:
                continue
            # Check if this class has submitted_grand_total
            cls_match = re.search(rf"class\s+{cls_name}\s*\(", content)
            if cls_match:
                cls_start = content[:cls_match.start()].count("\n") + 1
                cls_block = content[cls_match.start():cls_match.start() + 2000]
                if any(field in cls_block for field in total_fields):
                    results.append(CheckResult(
                        name=f"Schema {cls_name} has submitted_grand_total",
                        passed=True,
                        message=f"{schema_path}: {cls_name} ✓",
                        file=schema_path,
                    ))
                else:
                    # Only flag as missing if the endpoint needs it
                    needs = any(
                        ep.get("needs_total", False)
                        for ep in module_cfg.get("create_endpoints", {}).values()
                    )
                    if needs:
                        results.append(CheckResult(
                            name=f"Schema {cls_name} missing submitted_grand_total",
                            passed=False,
                            message=f"{schema_path}: {cls_name} ❌ — add: submitted_grand_total: Optional[Decimal] = None",
                            file=schema_path,
                            line=cls_start,
                        ))
    return results


def check_router_has_verification(module_cfg: dict) -> list[CheckResult]:
    """Check that create endpoints verify submitted_grand_total."""
    results = []
    total_fields = module_cfg.get("submitted_total_fields", ["submitted_grand_total"])
    for router_path in module_cfg.get("routers", []):
        content = _read_file(router_path)
        if not content:
            continue

        filename = Path(router_path).name
        endpoints = module_cfg.get("create_endpoints", {})

        for ep_key, ep_cfg in endpoints.items():
            if not ep_cfg.get("needs_total", False):
                continue

            # Check if this router handles this endpoint
            ep_path = ep_cfg["path"]
            if ep_key.replace("_dn", "") != filename and ep_key != filename:
                continue

            if any(field in content for field in total_fields):
                results.append(CheckResult(
                    name=f"Router {filename} verifies submitted total",
                    passed=True,
                    message=f"{router_path}: {ep_path} ✓",
                    file=router_path,
                ))
            else:
                results.append(CheckResult(
                    name=f"Router {filename} missing submitted_grand_total verification",
                    passed=False,
                    message=f"{router_path}: {ep_path} ❌ — add verification after grand_total calculation",
                    file=router_path,
                ))
    return results


def check_preview_endpoints_exist(module_cfg: dict) -> list[CheckResult]:
    """Check that preview endpoints exist in routers."""
    results = []
    previews = module_cfg.get("preview_endpoints", {})

    for router_key, preview_path in previews.items():
        # Find the actual router file
        router_path = None
        for rp in module_cfg.get("routers", []):
            if Path(rp).name == router_key or router_key.replace("_dn", "") == Path(rp).name:
                router_path = rp
                break

        if not router_path:
            results.append(CheckResult(
                name=f"Preview endpoint {preview_path}",
                passed=False,
                message=f"Router file not found for {router_key}",
            ))
            continue

        content = _read_file(router_path)
        if "preview" in content.lower():
            results.append(CheckResult(
                name=f"Preview endpoint {preview_path}",
                passed=True,
                message=f"{router_path}: {preview_path} ✓",
                file=router_path,
            ))
        else:
            results.append(CheckResult(
                name=f"Preview endpoint {preview_path} missing",
                passed=False,
                message=f"{router_path}: {preview_path} ❌ — no preview endpoint found",
                file=router_path,
            ))
    return results


def check_idempotency_on_mutations(module_cfg: dict) -> list[CheckResult]:
    """Check that POST endpoints have Idempotency-Key support."""
    results = []
    optional_routers = set(module_cfg.get("idempotency_optional_routers", []))
    for router_path in module_cfg.get("routers", []):
        content = _read_file(router_path)
        if not content:
            continue

        filename = Path(router_path).name
        if router_path in optional_routers or filename in optional_routers:
            continue
        has_post = bool(re.search(r"@router\.post|@.*_router\.post", content))
        has_idempotency = "Idempotency-Key" in content or "idempotency_key" in content or "require_idempotency_key" in content

        if has_post:
            if has_idempotency:
                results.append(CheckResult(
                    name=f"Idempotency on {filename}",
                    passed=True,
                    message=f"{router_path}: Idempotency-Key ✓",
                    file=router_path,
                ))
            else:
                results.append(CheckResult(
                    name=f"Idempotency missing on {filename}",
                    passed=False,
                    message=f"{router_path}: ❌ — POST endpoint without Idempotency-Key",
                    file=router_path,
                ))
    return results


def check_decimal_usage(module_cfg: dict) -> list[CheckResult]:
    """Check that routers use Decimal, not float."""
    results = []
    optional_routers = set(module_cfg.get("decimal_optional_routers", []))
    for router_path in module_cfg.get("routers", []):
        content = _read_file(router_path)
        if not content:
            continue

        filename = Path(router_path).name
        if router_path in optional_routers or filename in optional_routers:
            continue
        float_matches = _find_pattern(content, r"\bfloat\(")

        if float_matches:
            results.append(CheckResult(
                name=f"Float usage in {filename}",
                passed=False,
                message=f"{router_path}: ❌ — {len(float_matches)} float() calls found (use Decimal)",
                file=router_path,
                line=float_matches[0][0],
            ))
        else:
            results.append(CheckResult(
                name=f"No float in {filename}",
                passed=True,
                message=f"{router_path}: Decimal ✓",
                file=router_path,
            ))
    return results


def check_frontend_sends_submitted_grand_total(module_cfg: dict) -> list[CheckResult]:
    """Check that frontend pages send submitted_grand_total."""
    results = []
    needs_total = bool(module_cfg.get("submitted_total_schemas")) or any(
        ep.get("needs_total", False)
        for ep in module_cfg.get("create_endpoints", {}).values()
    )
    if not needs_total:
        return results
    total_fields = module_cfg.get("submitted_total_fields", ["submitted_grand_total"])
    for page_path in module_cfg.get("frontend_pages", []):
        content = _read_file(page_path)
        if not content:
            results.append(CheckResult(
                name=f"Frontend page exists: {page_path}",
                passed=False,
                message=f"File not found: {page_path}",
                file=page_path,
            ))
            continue

        present_fields = [field for field in total_fields if field in content]
        if present_fields:
            results.append(CheckResult(
                name=f"Frontend sends submitted total: {Path(page_path).name}",
                passed=True,
                message=f"{page_path}: ✓ ({', '.join(present_fields)})",
                file=page_path,
            ))
        else:
            results.append(CheckResult(
                name=f"Frontend missing submitted_grand_total: {Path(page_path).name}",
                passed=False,
                message=f"{page_path}: ❌ — add submitted_grand_total to payload",
                file=page_path,
            ))
    return results


def check_frontend_forbidden_patterns(module_cfg: dict) -> list[CheckResult]:
    """Check module-specific frontend patterns that would reintroduce calculations."""
    results = []
    patterns = module_cfg.get("frontend_forbidden_patterns", [])
    if not patterns:
        return results

    for page_path in module_cfg.get("frontend_pages", []):
        content = _read_file(page_path)
        if not content:
            continue
        for item in patterns:
            matches = _find_pattern(content, item["pattern"])
            if matches:
                results.append(CheckResult(
                    name=f"Forbidden frontend pattern: {Path(page_path).name}",
                    passed=False,
                    message=f"{page_path}: ❌ — {item['message']}",
                    file=page_path,
                    line=matches[0][0],
                ))
            else:
                results.append(CheckResult(
                    name=f"Forbidden frontend pattern absent: {Path(page_path).name}",
                    passed=True,
                    message=f"{page_path}: frontend backend-authority pattern ✓",
                    file=page_path,
                ))
    return results


def check_required_patterns(module_cfg: dict) -> list[CheckResult]:
    """Check module-specific integration patterns that must stay wired."""
    results = []
    patterns = module_cfg.get("required_patterns", [])
    if not patterns:
        return results

    for item in patterns:
        file_path = item["file"]
        content = _read_file(file_path)
        if not content:
            results.append(CheckResult(
                name=f"Required integration pattern: {Path(file_path).name}",
                passed=False,
                message=f"{file_path}: ❌ — file not found",
                file=file_path,
            ))
            continue
        matches = _find_pattern(content, item["pattern"])
        if matches:
            results.append(CheckResult(
                name=f"Required integration pattern: {Path(file_path).name}",
                passed=True,
                message=f"{file_path}: {item['message']} ✓",
                file=file_path,
            ))
        else:
            results.append(CheckResult(
                name=f"Required integration pattern: {Path(file_path).name}",
                passed=False,
                message=f"{file_path}: ❌ — {item['message']}",
                file=file_path,
            ))
    return results


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def run_checks(module_name: Optional[str] = None, strict: bool = False) -> bool:
    """Run all checks. Returns True if all passed."""
    all_passed = True
    total_checks = 0
    passed_checks = 0

    modules_to_check = {module_name: MODULES[module_name]} if module_name else MODULES

    for mod_name, mod_cfg in modules_to_check.items():
        print(f"\n{'═' * 60}")
        print(f"  Module: {mod_cfg['label']}")
        print(f"{'═' * 60}")

        checks = []
        checks.extend(check_schema_has_submitted_grand_total(mod_cfg))
        checks.extend(check_router_has_verification(mod_cfg))
        checks.extend(check_preview_endpoints_exist(mod_cfg))
        checks.extend(check_idempotency_on_mutations(mod_cfg))
        checks.extend(check_decimal_usage(mod_cfg))
        checks.extend(check_frontend_sends_submitted_grand_total(mod_cfg))
        checks.extend(check_frontend_forbidden_patterns(mod_cfg))
        checks.extend(check_required_patterns(mod_cfg))

        for check in checks:
            total_checks += 1
            icon = "✅" if check.passed else "❌"
            if check.passed:
                passed_checks += 1
            else:
                all_passed = False
            print(f"  {icon} {check.message}")

    print(f"\n{'═' * 60}")
    print(f"  Summary: {passed_checks}/{total_checks} checks passed")
    if all_passed:
        print("  ✅ ALL CHECKS PASSED")
    else:
        print("  ❌ SOME CHECKS FAILED")
    print(f"{'═' * 60}\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Backend Authority Pre-Flight Check")
    parser.add_argument("--module", choices=list(MODULES.keys()), help="Check specific module only")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 on failure")
    args = parser.parse_args()

    passed = run_checks(module_name=args.module, strict=args.strict)

    if args.strict and not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
