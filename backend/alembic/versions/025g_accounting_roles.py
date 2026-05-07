"""025g: Add accounting separation-of-duties role templates.

Revision: 025g_accounting_roles
Revises: 025f_treasury_branch_repair
Create Date: 2026-05-04
"""
import json

import sqlalchemy as sa
from alembic import op


revision = "025g_accounting_roles"
down_revision = "025f_treasury_branch_repair"
branch_labels = None
depends_on = None


ROLE_TEMPLATES = {
    "superuser": {
        "name_ar": "مدير النظام الأعلى",
        "description": "صلاحيات كاملة للنظام والشركة",
        "permissions": ["*"],
    },
    "admin": {
        "name_ar": "مدير النظام",
        "description": "صلاحيات كاملة على جميع وحدات النظام",
        "permissions": ["*"],
    },
    "ceo": {
        "name_ar": "رئيس الشركة",
        "description": "رؤية تنفيذية واعتمادات عليا دون تنفيذ قيود أو عمليات نقدية يومية",
        "permissions": [
            "dashboard.view", "dashboard.executive", "dashboard.financial",
            "sales.view", "buying.view", "products.view", "stock.view", "inventory.view",
            "accounting.view", "treasury.view", "reconciliation.view",
            "taxes.view", "currencies.view", "reports.view", "reports.financial", "reports.create",
            "hr.view", "hr.reports", "hr.payroll.view",
            "assets.view", "expenses.view", "contracts.view", "projects.view", "pos.view",
            "manufacturing.view", "approvals.view", "approvals.approve",
            "notifications.view", "audit.view", "security.view", "branches.view",
            "finance.cashflow_view", "dashboard.analytics_view",
        ],
    },
    "manager": {
        "name_ar": "مدير عام",
        "description": "إدارة جميع العمليات مع صلاحيات اعتماد وتقارير",
        "permissions": [
            "dashboard.view", "dashboard.executive", "sales.*", "buying.*",
            "products.*", "stock.*", "inventory.*",
            "accounting.view", "accounting.budgets.view", "accounting.cost_centers.view",
            "treasury.view", "treasury.create", "reconciliation.view",
            "taxes.view", "currencies.view", "reports.view", "reports.financial", "reports.create",
            "hr.view", "hr.reports", "hr.payroll.view", "assets.view", "assets.create",
            "expenses.view", "expenses.approve", "contracts.*", "projects.*",
            "pos.view", "pos.manage", "manufacturing.view", "manufacturing.create", "manufacturing.reports",
            "approvals.view", "approvals.create", "approvals.approve", "notifications.view",
            "security.view", "audit.view", "data_import.view", "branches.view", "settings.view",
            "hr.self_service", "hr.self_service_approve", "matching.view", "matching.approve",
            "intercompany.view", "costing.view", "finance.cashflow_view", "finance.cashflow_generate", "sso.view",
        ],
    },
    "finance_manager": {
        "name_ar": "مدير مالي",
        "description": "إشراف مالي شامل: إعدادات محاسبية، تقارير، اعتمادات، خزينة وتسويات",
        "permissions": [
            "dashboard.view", "dashboard.financial", "dashboard.analytics_view",
            "accounting.view", "accounting.manage", "accounting.budgets.view", "accounting.budgets.manage",
            "accounting.cost_centers.view", "accounting.cost_centers.manage",
            "treasury.view", "treasury.manage", "reconciliation.view", "reconciliation.create", "reconciliation.approve",
            "finance.reconciliation_view", "finance.reconciliation_manage",
            "taxes.view", "taxes.manage", "currencies.view", "currencies.manage",
            "reports.view", "reports.financial", "reports.create", "reports.edit",
            "expenses.view", "expenses.approve", "assets.view", "assets.manage",
            "sales.view", "buying.view", "contracts.view", "projects.view",
            "hr.payroll.view", "approvals.view", "approvals.approve",
            "audit.view", "security.view", "branches.view", "notifications.view",
            "finance.cashflow_view", "finance.cashflow_generate", "finance.cashflow_manage",
            "finance.accounting_view", "finance.accounting_read", "finance.accounting_post",
        ],
    },
    "chief_accountant": {
        "name_ar": "رئيس الحسابات",
        "description": "إدارة القيود اليومية، دليل الحسابات، الضرائب، التسويات والتقارير المالية",
        "permissions": [
            "dashboard.view", "dashboard.financial",
            "accounting.view", "accounting.edit", "accounting.manage",
            "accounting.create_journal_entry", "accounting.post_journal_entry", "accounting.void_journal_entry",
            "treasury.view", "treasury.create", "treasury.edit",
            "reconciliation.view", "reconciliation.create", "reconciliation.approve",
            "finance.reconciliation_view", "finance.accounting_view", "finance.accounting_read", "finance.accounting_post",
            "taxes.view", "taxes.manage", "currencies.view", "currencies.manage",
            "reports.view", "reports.financial", "reports.create",
            "expenses.view", "expenses.approve", "assets.view", "assets.manage",
            "sales.view", "buying.view", "contracts.view", "branches.view", "notifications.view", "audit.view",
        ],
    },
    "accountant": {
        "name_ar": "محاسب",
        "description": "تنفيذ القيود اليومية والضرائب والمدفوعات دون صلاحيات إعدادات مالية عليا أو حذف",
        "permissions": [
            "dashboard.view", "dashboard.financial",
            "accounting.view", "accounting.edit", "accounting.create_journal_entry", "accounting.post_journal_entry",
            "treasury.view", "treasury.create", "reconciliation.view", "reconciliation.create",
            "finance.accounting_view", "finance.accounting_read", "finance.accounting_post",
            "taxes.view", "taxes.manage", "currencies.view",
            "reports.view", "reports.financial", "reports.create",
            "sales.view", "buying.view",
            "expenses.view", "expenses.create", "expenses.approve",
            "assets.view", "assets.create", "contracts.view", "hr.payroll.view",
            "branches.view", "notifications.view", "intercompany.view", "costing.view", "finance.cashflow_view",
            "finance.cashflow_generate", "matching.view",
        ],
    },
    "branch_accountant": {
        "name_ar": "محاسب فرع",
        "description": "محاسب تشغيلي مقيّد بالفروع المسموحة له: قيود، قبض/صرف، مصاريف وتقارير فرعية",
        "permissions": [
            "dashboard.view", "dashboard.financial",
            "accounting.view", "accounting.create_journal_entry", "accounting.post_journal_entry",
            "treasury.view", "treasury.create", "reconciliation.view", "reconciliation.create",
            "sales.view", "buying.view", "expenses.view", "expenses.create",
            "taxes.view", "currencies.view", "reports.view", "reports.financial",
            "branches.view", "notifications.view", "finance.accounting_view", "finance.accounting_read",
        ],
    },
    "accounts_receivable": {
        "name_ar": "محاسب ذمم مدينة",
        "description": "تحصيلات العملاء وسندات القبض والشيكات تحت التحصيل دون صلاحيات الموردين أو إعدادات الحسابات",
        "permissions": [
            "dashboard.view", "dashboard.sales", "sales.view", "sales.create", "sales.reports",
            "parties.view", "parties.manage", "treasury.view", "treasury.create", "reconciliation.view",
            "accounting.view", "reports.view", "branches.view", "notifications.view", "finance.accounting_read",
        ],
    },
    "accounts_payable": {
        "name_ar": "محاسب ذمم دائنة",
        "description": "فواتير الموردين والمدفوعات وأوراق الدفع والمصاريف دون صلاحيات العملاء أو إعدادات الحسابات",
        "permissions": [
            "dashboard.view", "dashboard.procurement", "buying.view", "buying.create", "buying.reports",
            "parties.view", "parties.manage", "expenses.view", "expenses.create", "matching.view", "matching.approve",
            "treasury.view", "treasury.create", "accounting.view", "reports.view",
            "branches.view", "notifications.view", "finance.accounting_read",
        ],
    },
    "treasury_officer": {
        "name_ar": "أمين خزينة / مسؤول بنوك",
        "description": "إدارة القبض والصرف والتحويلات والتسويات البنكية دون إدارة دليل الحسابات",
        "permissions": [
            "dashboard.view", "dashboard.financial", "treasury.view", "treasury.create", "treasury.edit",
            "reconciliation.view", "reconciliation.create", "finance.reconciliation_view", "finance.reconciliation_manage",
            "accounting.view", "reports.view", "currencies.view", "branches.view", "notifications.view",
        ],
    },
    "tax_accountant": {
        "name_ar": "محاسب ضرائب",
        "description": "إعداد الإقرارات والدفعات الضريبية ومراجعة حسابات الضريبة",
        "permissions": [
            "dashboard.view", "dashboard.financial", "taxes.view", "taxes.manage", "accounting.view",
            "accounting.create_journal_entry", "accounting.post_journal_entry", "treasury.view", "treasury.create",
            "reports.view", "reports.financial", "currencies.view", "sales.view", "buying.view",
            "branches.view", "notifications.view", "finance.accounting_read",
        ],
    },
    "cost_accountant": {
        "name_ar": "محاسب تكاليف",
        "description": "تكلفة المخزون والتصنيع ومراكز التكلفة دون صلاحيات خزينة يومية",
        "permissions": [
            "dashboard.view", "dashboard.financial", "dashboard.warehouse", "dashboard.manufacturing",
            "accounting.view", "accounting.cost_centers.view", "accounting.cost_centers.manage",
            "stock.view", "stock.view_cost", "inventory.view", "inventory.costing_view", "inventory.costing_manage",
            "costing.view", "costing.manage", "manufacturing.view", "reports.view", "reports.financial",
            "branches.view", "notifications.view",
        ],
    },
    "branch_manager": {
        "name_ar": "مدير فرع",
        "description": "إدارة تشغيلية لفرع محدد: مبيعات، مشتريات، مخزون، مصاريف واعتمادات تشغيلية",
        "permissions": [
            "dashboard.view", "dashboard.sales", "dashboard.procurement", "dashboard.warehouse", "dashboard.pos",
            "sales.view", "sales.create", "sales.edit", "buying.view", "buying.create", "buying.receive",
            "products.view", "stock.view", "stock.transfer", "inventory.view",
            "treasury.view", "treasury.create", "expenses.view", "expenses.create", "expenses.approve",
            "reports.view", "projects.view", "pos.view", "pos.create", "pos.sessions", "pos.returns",
            "approvals.view", "approvals.create", "approvals.approve", "branches.view", "notifications.view",
        ],
    },
    "cashier": {
        "name_ar": "كاشير / أمين صندوق",
        "description": "تشغيل نقطة البيع وعمليات الصندوق",
        "permissions": [
            "dashboard.view", "pos.view", "pos.create", "pos.sessions", "pos.returns",
            "sales.view", "sales.create", "products.view", "stock.view",
            "treasury.view", "treasury.create", "notifications.view",
        ],
    },
    "auditor": {
        "name_ar": "مراجع / مدقق",
        "description": "صلاحيات قراءة ومراجعة فقط على السجلات المالية والتشغيلية وسجل المراقبة",
        "permissions": [
            "dashboard.view", "dashboard.financial", "dashboard.analytics_view",
            "accounting.view", "treasury.view", "reconciliation.view", "taxes.view", "currencies.view",
            "reports.view", "reports.financial", "sales.view", "buying.view", "products.view", "stock.view",
            "inventory.view", "expenses.view", "contracts.view", "projects.view", "assets.view",
            "hr.view", "manufacturing.view", "audit.view", "security.view", "branches.view", "notifications.view",
        ],
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    roles_exists = bind.execute(sa.text("SELECT to_regclass('public.roles')")).scalar()
    if not roles_exists:
        return

    for role_name, role_data in ROLE_TEMPLATES.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO roles (role_name, role_name_ar, description, permissions, is_system_role)
                VALUES (:name, :name_ar, :description, CAST(:permissions AS JSONB), TRUE)
                ON CONFLICT (role_name) DO UPDATE SET
                    role_name_ar = EXCLUDED.role_name_ar,
                    description = EXCLUDED.description,
                    permissions = EXCLUDED.permissions,
                    is_system_role = TRUE
                """
            ),
            {
                "name": role_name,
                "name_ar": role_data["name_ar"],
                "description": role_data["description"],
                "permissions": json.dumps(role_data["permissions"]),
            },
        )


def downgrade() -> None:
    # Non-destructive: roles may already be assigned to users, so do not delete
    # or overwrite user-managed role data on downgrade.
    pass