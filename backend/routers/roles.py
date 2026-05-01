"""
AMAN ERP - Roles Management Router
API endpoints for managing roles and permissions.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user, UserResponse
from utils.tx import transactional
from utils.permissions import require_permission
from utils.tenant_isolation import resolve_target_company_id
from schemas.roles import RoleCreate, RoleUpdate
from utils.audit import log_activity

router = APIRouter(prefix="/roles", tags=["Roles Management"])
logger = logging.getLogger(__name__)


# --- Available Permissions ---
# Complete permission registry for the entire AMAN ERP system
# Every permission that is checked by require_permission() must be listed here
# Grouped by module (section) for the frontend permission picker UI
AVAILABLE_PERMISSIONS = [
    # ═══════════════════════ Dashboard ═══════════════════════
    {"key": "dashboard.view", "section": "dashboard", "label_ar": "عرض لوحة المعلومات", "label_en": "View Dashboard"},
    {"key": "dashboard.executive", "section": "dashboard", "label_ar": "لوحة المدير التنفيذي", "label_en": "Executive Dashboard"},
    {"key": "dashboard.financial", "section": "dashboard", "label_ar": "لوحة المدير المالي", "label_en": "Financial Dashboard"},
    {"key": "dashboard.sales", "section": "dashboard", "label_ar": "لوحة المبيعات", "label_en": "Sales Dashboard"},
    {"key": "dashboard.procurement", "section": "dashboard", "label_ar": "لوحة المشتريات", "label_en": "Procurement Dashboard"},
    {"key": "dashboard.warehouse", "section": "dashboard", "label_ar": "لوحة المخازن", "label_en": "Warehouse Dashboard"},
    {"key": "dashboard.hr", "section": "dashboard", "label_ar": "لوحة الموارد البشرية", "label_en": "HR Dashboard"},
    {"key": "dashboard.manufacturing", "section": "dashboard", "label_ar": "لوحة التصنيع", "label_en": "Manufacturing Dashboard"},
    {"key": "dashboard.projects", "section": "dashboard", "label_ar": "لوحة المشاريع", "label_en": "Projects Dashboard"},
    {"key": "dashboard.pos", "section": "dashboard", "label_ar": "لوحة نقاط البيع", "label_en": "POS Dashboard"},
    {"key": "dashboard.crm", "section": "dashboard", "label_ar": "لوحة إدارة العلاقات", "label_en": "CRM Dashboard"},
    {"key": "dashboard.industry", "section": "dashboard", "label_ar": "مؤشرات القطاع", "label_en": "Industry KPIs"},

    # ═══════════════════════ Sales ═══════════════════════
    {"key": "sales.view", "section": "sales", "label_ar": "عرض المبيعات والفواتير", "label_en": "View Sales & Invoices"},
    {"key": "sales.create", "section": "sales", "label_ar": "إنشاء فواتير وطلبات بيع", "label_en": "Create Invoices & Sales Orders"},
    {"key": "sales.edit", "section": "sales", "label_ar": "تعديل الفواتير", "label_en": "Edit Invoices"},
    {"key": "sales.delete", "section": "sales", "label_ar": "حذف / إلغاء فواتير", "label_en": "Delete / Cancel Invoices"},
    {"key": "sales.void", "section": "sales", "label_ar": "إلغاء فاتورة معتمدة (Void)", "label_en": "Void Posted Invoice"},
    {"key": "sales.approve_return", "section": "sales", "label_ar": "اعتماد مرتجع المبيعات", "label_en": "Approve Sales Return"},
    {"key": "sales.manage_credit_notes", "section": "sales", "label_ar": "إصدار وإدارة الإشعارات الدائنة/المدينة", "label_en": "Issue & Manage Credit / Debit Notes"},
    {"key": "sales.reports", "section": "sales", "label_ar": "تقارير المبيعات", "label_en": "Sales Reports"},

    # ═══════════════════════ Purchases ═══════════════════════
    {"key": "buying.view", "section": "buying", "label_ar": "عرض المشتريات", "label_en": "View Purchases"},
    {"key": "buying.create", "section": "buying", "label_ar": "إنشاء فواتير وأوامر شراء", "label_en": "Create Purchase Invoices & Orders"},
    {"key": "buying.edit", "section": "buying", "label_ar": "تعديل فواتير الشراء", "label_en": "Edit Purchase Invoices"},
    {"key": "buying.delete", "section": "buying", "label_ar": "حذف فواتير الشراء", "label_en": "Delete Purchase Invoices"},
    {"key": "buying.approve", "section": "buying", "label_ar": "اعتماد أوامر الشراء", "label_en": "Approve Purchase Orders"},
    {"key": "buying.receive", "section": "buying", "label_ar": "استلام البضائع", "label_en": "Receive Goods"},
    {"key": "buying.reports", "section": "buying", "label_ar": "تقارير المشتريات", "label_en": "Purchase Reports"},

    # ═══════════════════════ Products & Inventory ═══════════════════════
    {"key": "products.view", "section": "products", "label_ar": "عرض المنتجات والأصناف", "label_en": "View Products & Items"},
    {"key": "products.create", "section": "products", "label_ar": "إنشاء منتج / صنف", "label_en": "Create Products"},
    {"key": "products.edit", "section": "products", "label_ar": "تعديل منتج / صنف", "label_en": "Edit Products"},
    {"key": "products.delete", "section": "products", "label_ar": "حذف منتج", "label_en": "Delete Products"},

    {"key": "stock.view", "section": "stock", "label_ar": "عرض المخزون والأرصدة", "label_en": "View Stock & Balances"},
    {"key": "stock.view_cost", "section": "stock", "label_ar": "عرض سعر التكلفة", "label_en": "View Cost Price"},
    {"key": "stock.adjustment", "section": "stock", "label_ar": "تسوية المخزون", "label_en": "Stock Adjustment"},
    {"key": "stock.transfer", "section": "stock", "label_ar": "نقل بين المستودعات", "label_en": "Stock Transfer"},
    {"key": "stock.manage", "section": "stock", "label_ar": "إدارة المستودعات", "label_en": "Manage Warehouses"},
    {"key": "stock.reports", "section": "stock", "label_ar": "تقارير المخزون", "label_en": "Stock Reports"},

    {"key": "inventory.view", "section": "inventory", "label_ar": "عرض الجرد", "label_en": "View Inventory"},
    {"key": "inventory.delete", "section": "inventory", "label_ar": "حذف عمليات الجرد", "label_en": "Delete Inventory Records"},

    # ═══════════════════════ Accounting ═══════════════════════
    {"key": "accounting.view", "section": "accounting", "label_ar": "عرض المحاسبة والقيود", "label_en": "View Accounting & Journal Entries"},
    {"key": "accounting.edit", "section": "accounting", "label_ar": "تعديل القيود المحاسبية", "label_en": "Edit Journal Entries"},
    {"key": "accounting.manage", "section": "accounting", "label_ar": "إدارة شجرة الحسابات والإعدادات", "label_en": "Manage Chart of Accounts & Settings"},
    {"key": "accounting.budgets.view", "section": "accounting", "label_ar": "عرض الموازنات", "label_en": "View Budgets"},
    {"key": "accounting.budgets.manage", "section": "accounting", "label_ar": "إدارة الموازنات", "label_en": "Manage Budgets"},
    {"key": "accounting.cost_centers.view", "section": "accounting", "label_ar": "عرض مراكز التكلفة", "label_en": "View Cost Centers"},
    {"key": "accounting.cost_centers.manage", "section": "accounting", "label_ar": "إدارة مراكز التكلفة", "label_en": "Manage Cost Centers"},

    # ═══════════════════════ Treasury & Banks ═══════════════════════
    {"key": "treasury.view", "section": "treasury", "label_ar": "عرض الخزينة والبنوك", "label_en": "View Treasury & Banks"},
    {"key": "treasury.create", "section": "treasury", "label_ar": "إنشاء عمليات (قبض / صرف)", "label_en": "Create Receipts & Payments"},
    {"key": "treasury.edit", "section": "treasury", "label_ar": "تعديل عمليات الخزينة", "label_en": "Edit Treasury Transactions"},
    {"key": "treasury.delete", "section": "treasury", "label_ar": "حذف عمليات الخزينة", "label_en": "Delete Treasury Transactions"},
    {"key": "treasury.manage", "section": "treasury", "label_ar": "إدارة الحسابات البنكية والخزائن", "label_en": "Manage Bank Accounts & Safes"},

    {"key": "reconciliation.view", "section": "treasury", "label_ar": "عرض تسوية البنك", "label_en": "View Bank Reconciliation"},
    {"key": "reconciliation.create", "section": "treasury", "label_ar": "إنشاء تسوية بنكية", "label_en": "Create Bank Reconciliation"},
    {"key": "reconciliation.approve", "section": "treasury", "label_ar": "اعتماد التسوية البنكية", "label_en": "Approve Reconciliation"},

    # ═══════════════════════ Taxes ═══════════════════════
    {"key": "taxes.view", "section": "taxes", "label_ar": "عرض الضرائب والإقرارات", "label_en": "View Taxes & Returns"},
    {"key": "taxes.manage", "section": "taxes", "label_ar": "إدارة أنواع الضرائب والإقرارات", "label_en": "Manage Tax Types & Returns"},

    # ═══════════════════════ Currencies ═══════════════════════
    {"key": "currencies.view", "section": "currencies", "label_ar": "عرض العملات وأسعار الصرف", "label_en": "View Currencies & Exchange Rates"},
    {"key": "currencies.manage", "section": "currencies", "label_ar": "إدارة العملات وأسعار الصرف", "label_en": "Manage Currencies & Exchange Rates"},

    # ═══════════════════════ Reports ═══════════════════════
    {"key": "reports.view", "section": "reports", "label_ar": "عرض التقارير", "label_en": "View Reports"},
    {"key": "reports.financial", "section": "reports", "label_ar": "التقارير المالية (ميزانية، أرباح وخسائر)", "label_en": "Financial Reports (Balance Sheet, P&L)"},
    {"key": "reports.create", "section": "reports", "label_ar": "إنشاء تقارير مجدولة", "label_en": "Create Scheduled Reports"},
    {"key": "reports.edit", "section": "reports", "label_ar": "تعديل التقارير المجدولة", "label_en": "Edit Scheduled Reports"},
    {"key": "reports.delete", "section": "reports", "label_ar": "حذف التقارير", "label_en": "Delete Reports"},

    # ═══════════════════════ HR & Payroll ═══════════════════════
    {"key": "hr.view", "section": "hr", "label_ar": "عرض بيانات الموظفين", "label_en": "View Employee Data"},
    {"key": "hr.pii", "section": "hr", "label_ar": "عرض البيانات المالية والشخصية الحساسة (الرواتب، IBAN)", "label_en": "View Sensitive PII (Salary, IBAN, Bank)"},
    {"key": "hr.manage", "section": "hr", "label_ar": "إدارة الموظفين (إضافة، تعديل، حذف)", "label_en": "Manage Employees (Add, Edit, Delete)"},
    {"key": "hr.reports", "section": "hr", "label_ar": "تقارير الموارد البشرية", "label_en": "HR Reports"},
    {"key": "hr.attendance.view", "section": "hr", "label_ar": "عرض الحضور والانصراف", "label_en": "View Attendance"},
    {"key": "hr.attendance.manage", "section": "hr", "label_ar": "إدارة الحضور والانصراف", "label_en": "Manage Attendance"},
    {"key": "hr.leaves.manage", "section": "hr", "label_ar": "إدارة الإجازات والأرصدة", "label_en": "Manage Leaves & Balances"},
    {"key": "hr.loans.view", "section": "hr", "label_ar": "عرض القروض والسلف", "label_en": "View Loans & Advances"},
    {"key": "hr.loans.manage", "section": "hr", "label_ar": "إدارة القروض والسلف", "label_en": "Manage Loans & Advances"},
    {"key": "hr.payroll.view", "section": "hr", "label_ar": "عرض كشوف الرواتب", "label_en": "View Payroll"},
    {"key": "hr.payroll.manage", "section": "hr", "label_ar": "إدارة الرواتب ومعالجتها", "label_en": "Manage & Process Payroll"},
    {"key": "hr.self_service", "section": "hr", "label_ar": "الخدمة الذاتية للموظف", "label_en": "Employee Self-Service"},
    {"key": "hr.self_service_approve", "section": "hr", "label_ar": "اعتماد طلبات الخدمة الذاتية", "label_en": "Approve Self-Service Requests"},

    # ═══════════════════════ SSO ═══════════════════════
    {"key": "sso.view", "section": "sso", "label_ar": "عرض إعدادات الدخول الموحد", "label_en": "View SSO Configuration"},
    {"key": "sso.manage", "section": "sso", "label_ar": "إدارة إعدادات الدخول الموحد", "label_en": "Manage SSO Configuration"},

    # ═══════════════════════ 3-Way Matching ═══════════════════════
    {"key": "matching.view", "section": "matching", "label_ar": "عرض المطابقة الثلاثية", "label_en": "View 3-Way Matching"},
    {"key": "matching.approve", "section": "matching", "label_ar": "اعتماد المطابقات", "label_en": "Approve Matches"},
    {"key": "matching.manage", "section": "matching", "label_ar": "إدارة حدود التفاوت", "label_en": "Manage Tolerances"},

    # ═══════════════════════ Intercompany ═══════════════════════
    {"key": "intercompany.view", "section": "intercompany", "label_ar": "عرض المعاملات بين الشركات", "label_en": "View Intercompany Transactions"},
    {"key": "intercompany.manage", "section": "intercompany", "label_ar": "إدارة المعاملات بين الشركات", "label_en": "Manage Intercompany Transactions"},

    # ═══════════════════════ Inventory Costing ═══════════════════════
    {"key": "costing.view", "section": "costing", "label_ar": "عرض تكاليف المخزون", "label_en": "View Inventory Costing"},
    {"key": "costing.manage", "section": "costing", "label_ar": "إدارة طرق التكلفة", "label_en": "Manage Costing Methods"},

    # ═══════════════════════ Cash Flow Forecast ═══════════════════════
    {"key": "finance.cashflow_view", "section": "finance", "label_ar": "عرض توقعات التدفق النقدي", "label_en": "View Cash Flow Forecasts"},
    {"key": "finance.cashflow_generate", "section": "finance", "label_ar": "إنشاء توقعات التدفق النقدي", "label_en": "Generate Cash Flow Forecasts"},

    # ═══════════════════════ Fixed Assets ═══════════════════════
    {"key": "assets.view", "section": "assets", "label_ar": "عرض الأصول الثابتة", "label_en": "View Fixed Assets"},
    {"key": "assets.create", "section": "assets", "label_ar": "إضافة أصل ثابت", "label_en": "Add Fixed Asset"},
    {"key": "assets.manage", "section": "assets", "label_ar": "إدارة الأصول (إهلاك، استبعاد)", "label_en": "Manage Assets (Depreciation, Disposal)"},

    # ═══════════════════════ Expenses ═══════════════════════
    {"key": "expenses.view", "section": "expenses", "label_ar": "عرض المصاريف", "label_en": "View Expenses"},
    {"key": "expenses.create", "section": "expenses", "label_ar": "إنشاء طلب مصاريف", "label_en": "Create Expense Request"},
    {"key": "expenses.edit", "section": "expenses", "label_ar": "تعديل المصاريف", "label_en": "Edit Expenses"},
    {"key": "expenses.delete", "section": "expenses", "label_ar": "حذف المصاريف", "label_en": "Delete Expenses"},
    {"key": "expenses.approve", "section": "expenses", "label_ar": "اعتماد المصاريف", "label_en": "Approve Expenses"},

    # ═══════════════════════ Contracts ═══════════════════════
    {"key": "contracts.view", "section": "contracts", "label_ar": "عرض العقود", "label_en": "View Contracts"},
    {"key": "contracts.create", "section": "contracts", "label_ar": "إنشاء عقد", "label_en": "Create Contract"},
    {"key": "contracts.edit", "section": "contracts", "label_ar": "تعديل العقود", "label_en": "Edit Contracts"},
    {"key": "contracts.manage", "section": "contracts", "label_ar": "إدارة وتجديد العقود", "label_en": "Manage & Renew Contracts"},

    # ═══════════════════════ Projects ═══════════════════════
    {"key": "projects.view", "section": "projects", "label_ar": "عرض المشاريع", "label_en": "View Projects"},
    {"key": "projects.create", "section": "projects", "label_ar": "إنشاء مشروع", "label_en": "Create Project"},
    {"key": "projects.edit", "section": "projects", "label_ar": "تعديل المشاريع", "label_en": "Edit Projects"},
    {"key": "projects.delete", "section": "projects", "label_ar": "حذف المشاريع", "label_en": "Delete Projects"},
    {"key": "projects.manage", "section": "projects", "label_ar": "إدارة المشاريع والمهام", "label_en": "Manage Projects & Tasks"},

    # ═══════════════════════ POS ═══════════════════════
    {"key": "pos.view", "section": "pos", "label_ar": "عرض نقطة البيع", "label_en": "View POS"},
    {"key": "pos.create", "section": "pos", "label_ar": "إنشاء طلبات نقطة البيع", "label_en": "Create POS Orders"},
    {"key": "pos.manage", "section": "pos", "label_ar": "إدارة نقطة البيع", "label_en": "Manage POS Settings"},
    {"key": "pos.sessions", "section": "pos", "label_ar": "إدارة جلسات نقطة البيع", "label_en": "Manage POS Sessions"},
    {"key": "pos.returns", "section": "pos", "label_ar": "مرتجعات نقطة البيع", "label_en": "POS Returns"},

    # ═══════════════════════ Manufacturing ═══════════════════════
    {"key": "manufacturing.view", "section": "manufacturing", "label_ar": "عرض التصنيع وأوامر الإنتاج", "label_en": "View Manufacturing & Production Orders"},
    {"key": "manufacturing.create", "section": "manufacturing", "label_ar": "إنشاء أوامر تصنيع و BOM", "label_en": "Create Production Orders & BOMs"},
    {"key": "manufacturing.manage", "section": "manufacturing", "label_ar": "إدارة التصنيع ومراكز العمل", "label_en": "Manage Manufacturing & Work Centers"},
    {"key": "manufacturing.delete", "section": "manufacturing", "label_ar": "حذف بيانات التصنيع", "label_en": "Delete Manufacturing Data"},
    {"key": "manufacturing.reports", "section": "manufacturing", "label_ar": "تقارير الإنتاج والتصنيع", "label_en": "Manufacturing Reports"},

    # ═══════════════════════ Approvals ═══════════════════════
    {"key": "approvals.view", "section": "approvals", "label_ar": "عرض طلبات الاعتماد", "label_en": "View Approval Requests"},
    {"key": "approvals.create", "section": "approvals", "label_ar": "إنشاء طلبات اعتماد", "label_en": "Create Approval Requests"},
    {"key": "approvals.edit", "section": "approvals", "label_ar": "تعديل سلاسل الاعتماد", "label_en": "Edit Approval Workflows"},
    {"key": "approvals.approve", "section": "approvals", "label_ar": "اعتماد / رفض الطلبات", "label_en": "Approve / Reject Requests"},
    {"key": "approvals.manage", "section": "approvals", "label_ar": "إدارة سلاسل الاعتماد", "label_en": "Manage Approval Workflows"},

    # ═══════════════════════ Notifications ═══════════════════════
    {"key": "notifications.view", "section": "notifications", "label_ar": "عرض التنبيهات", "label_en": "View Notifications"},
    {"key": "notifications.send", "section": "notifications", "label_ar": "إرسال تنبيهات للمستخدمين", "label_en": "Send Notifications to Users"},

    # ═══════════════════════ Audit ═══════════════════════
    {"key": "audit.view", "section": "audit", "label_ar": "عرض سجلات المراقبة", "label_en": "View Audit Logs"},
    {"key": "audit.manage", "section": "audit", "label_ar": "إدارة سجلات المراقبة", "label_en": "Manage Audit Logs"},

    # ═══════════════════════ Security ═══════════════════════
    {"key": "security.view", "section": "security", "label_ar": "عرض إعدادات الأمان", "label_en": "View Security Settings"},
    {"key": "security.manage", "section": "security", "label_ar": "إدارة السياسات الأمنية", "label_en": "Manage Security Policies"},

    # ═══════════════════════ Data Import ═══════════════════════
    {"key": "data_import.view", "section": "data_import", "label_ar": "عرض صفحة استيراد البيانات", "label_en": "View Data Import"},
    {"key": "data_import.create", "section": "data_import", "label_ar": "رفع وتنفيذ عمليات الاستيراد", "label_en": "Upload & Execute Imports"},
    {"key": "data_import.manage", "section": "data_import", "label_ar": "إدارة قوالب الاستيراد", "label_en": "Manage Import Templates"},

    # ═══════════════════════ Admin & Settings ═══════════════════════
    {"key": "admin", "section": "admin", "label_ar": "صلاحية إدارة النظام الكاملة", "label_en": "Full System Admin Access"},
    {"key": "admin.users", "section": "admin", "label_ar": "إدارة المستخدمين", "label_en": "Manage Users"},
    {"key": "admin.roles", "section": "admin", "label_ar": "إدارة الأدوار والصلاحيات", "label_en": "Manage Roles & Permissions"},
    {"key": "admin.companies", "section": "admin", "label_ar": "إدارة الشركات (SaaS)", "label_en": "Manage Companies (SaaS)"},
    {"key": "admin.branches", "section": "admin", "label_ar": "إدارة الفروع", "label_en": "Manage Branches"},

    {"key": "branches.view", "section": "branches", "label_ar": "عرض الفروع", "label_en": "View Branches"},
    {"key": "branches.manage", "section": "branches", "label_ar": "تعديل وحذف الفروع", "label_en": "Edit & Delete Branches"},

    {"key": "settings.view", "section": "settings", "label_ar": "عرض الإعدادات", "label_en": "View Settings"},
    {"key": "settings.edit", "section": "settings", "label_ar": "تعديل الإعدادات", "label_en": "Edit Settings"},
    {"key": "settings.manage", "section": "settings", "label_ar": "إدارة الإعدادات العامة", "label_en": "Manage General Settings"},
    {"key": "settings.create", "section": "settings", "label_ar": "إضافة إعدادات", "label_en": "Create Settings"},
    {"key": "settings.delete", "section": "settings", "label_ar": "حذف إعدادات", "label_en": "Delete Settings"},

    # ═══════════════════════ Services & Documents ═══════════════════════
    {"key": "services.view", "section": "services", "label_ar": "عرض طلبات الخدمة والمستندات", "label_en": "View Service Requests & Documents"},
    {"key": "services.create", "section": "services", "label_ar": "إنشاء طلبات خدمة ومستندات", "label_en": "Create Service Requests & Documents"},
    {"key": "services.edit", "section": "services", "label_ar": "تعديل طلبات الخدمة", "label_en": "Edit Service Requests"},
    {"key": "services.delete", "section": "services", "label_ar": "حذف طلبات الخدمة", "label_en": "Delete Service Requests"},

    # ═══════════════════════ Parties ═══════════════════════
    {"key": "parties.view", "section": "parties", "label_ar": "عرض الأطراف (عملاء/موردين)", "label_en": "View Parties (Customers/Suppliers)"},
    {"key": "parties.manage", "section": "parties", "label_ar": "إدارة الأطراف", "label_en": "Manage Parties"},

    # ═══════════════════════ Purchases (Landed Costs aliases) ═══════════════════════
    {"key": "purchases.view", "section": "buying", "label_ar": "عرض التكاليف المحملة", "label_en": "View Landed Costs"},
    {"key": "purchases.create", "section": "buying", "label_ar": "إنشاء تكاليف محملة", "label_en": "Create Landed Costs"},

    # ═══════════════════════ Logistics & Shipments ═══════════════════════
    {"key": "inventory.shipments_view", "section": "logistics", "label_ar": "عرض الشحنات", "label_en": "View Shipments"},
    {"key": "inventory.shipments_create", "section": "logistics", "label_ar": "إنشاء وتسجيل شحنات", "label_en": "Create & Record Shipments"},

    # ═══════════════════════ Inventory Costing (router-level) ═══════════════════════
    {"key": "inventory.costing_view", "section": "costing", "label_ar": "عرض تكاليف المخزون (المتقدم)", "label_en": "View Inventory Costing (Advanced)"},
    {"key": "inventory.costing_manage", "section": "costing", "label_ar": "إدارة طرق تكلفة المخزون", "label_en": "Manage Inventory Costing Methods"},

    # ═══════════════════════ Demand Forecasting ═══════════════════════
    {"key": "inventory.forecast_view", "section": "forecast", "label_ar": "عرض توقعات الطلب", "label_en": "View Demand Forecasts"},
    {"key": "inventory.forecast_generate", "section": "forecast", "label_ar": "إنشاء توقعات الطلب", "label_en": "Generate Demand Forecasts"},
    {"key": "inventory.forecast_manage", "section": "forecast", "label_ar": "إدارة إعدادات التوقع", "label_en": "Manage Forecast Settings"},

    # ═══════════════════════ Manufacturing – Shop Floor ═══════════════════════
    {"key": "manufacturing.shopfloor_view", "section": "manufacturing", "label_ar": "عرض شاشة الإنتاج الميداني", "label_en": "View Shop Floor"},
    {"key": "manufacturing.shopfloor_operate", "section": "manufacturing", "label_ar": "تشغيل عمليات الإنتاج الميداني", "label_en": "Operate Shop Floor"},
    {"key": "manufacturing.routing_view", "section": "manufacturing", "label_ar": "عرض مسارات التصنيع (Routing)", "label_en": "View Manufacturing Routings"},
    {"key": "manufacturing.routing_manage", "section": "manufacturing", "label_ar": "إدارة مسارات التصنيع", "label_en": "Manage Manufacturing Routings"},

    # ═══════════════════════ CRM – Campaigns & Marketing ═══════════════════════
    {"key": "crm.campaign_view", "section": "crm", "label_ar": "عرض الحملات التسويقية", "label_en": "View Marketing Campaigns"},
    {"key": "crm.campaign_manage", "section": "crm", "label_ar": "إدارة الحملات التسويقية", "label_en": "Manage Marketing Campaigns"},
    {"key": "crm.campaign_execute", "section": "crm", "label_ar": "تنفيذ وإطلاق الحملات", "label_en": "Execute / Launch Campaigns"},

    # ═══════════════════════ Sales – CPQ (Configure Price Quote) ═══════════════════════
    {"key": "sales.cpq_view", "section": "sales", "label_ar": "عرض تسعير وتهيئة المنتجات (CPQ)", "label_en": "View CPQ Pricing"},
    {"key": "sales.cpq_create", "section": "sales", "label_ar": "إنشاء عروض أسعار (CPQ)", "label_en": "Create CPQ Quotes"},

    # ═══════════════════════ Projects – Time & Resources (granular) ═══════════════════════
    {"key": "projects.time_view", "section": "projects", "label_ar": "عرض الأوقات والحضور على المشاريع", "label_en": "View Project Timesheets"},
    {"key": "projects.time_log", "section": "projects", "label_ar": "تسجيل الوقت على المشاريع", "label_en": "Log Time on Projects"},
    {"key": "projects.time_approve", "section": "projects", "label_ar": "اعتماد سجلات الأوقات", "label_en": "Approve Project Timesheets"},
    {"key": "projects.resource_view", "section": "projects", "label_ar": "عرض تخصيص الموارد", "label_en": "View Resource Allocation"},
    {"key": "projects.resource_manage", "section": "projects", "label_ar": "إدارة تخصيص الموارد", "label_en": "Manage Resource Allocation"},

    # ═══════════════════════ HR – Performance Management ═══════════════════════
    {"key": "hr.performance_view", "section": "hr", "label_ar": "عرض تقييمات الأداء", "label_en": "View Performance Reviews"},
    {"key": "hr.performance_manage", "section": "hr", "label_ar": "إدارة دورات تقييم الأداء", "label_en": "Manage Performance Cycles"},
    {"key": "hr.performance_review", "section": "hr", "label_ar": "تنفيذ تقييم الموظفين", "label_en": "Conduct Employee Reviews"},
    {"key": "hr.performance_self", "section": "hr", "label_ar": "التقييم الذاتي للموظف", "label_en": "Employee Self-Assessment"},

    # ═══════════════════════ HR – Leaves & PII ═══════════════════════
    {"key": "hr.leaves.view", "section": "hr", "label_ar": "عرض الإجازات والأرصدة", "label_en": "View Leaves & Balances"},
    {"key": "hr.pii", "section": "hr", "label_ar": "الوصول لبيانات الموظف الحساسة (رقم هوية، إيبان)", "label_en": "Access Employee PII (Nat. ID, IBAN)"},

    # ═══════════════════════ Finance – Cash Flow & Subscriptions ═══════════════════════
    {"key": "finance.cashflow_manage", "section": "finance", "label_ar": "إدارة توقعات التدفق النقدي", "label_en": "Manage Cash Flow Forecasts"},
    {"key": "finance.subscription_view", "section": "finance", "label_ar": "عرض الاشتراكات والفوترة المتكررة", "label_en": "View Subscriptions & Recurring Billing"},
    {"key": "finance.subscription_manage", "section": "finance", "label_ar": "إدارة الاشتراكات والفوترة المتكررة", "label_en": "Manage Subscriptions & Recurring Billing"},

    # ═══════════════════════ Dashboard – BI & Analytics ═══════════════════════
    {"key": "dashboard.analytics_view", "section": "dashboard", "label_ar": "عرض لوحات التحليلات (BI)", "label_en": "View BI Dashboards"},
    {"key": "dashboard.analytics_manage", "section": "dashboard", "label_ar": "إدارة لوحات التحليلات (BI)", "label_en": "Manage BI Dashboards"},

    # ═══════════════════════ Accounting – Journal Entry (granular) ═══════════════════════
    {"key": "accounting.create_journal_entry", "section": "accounting", "label_ar": "إنشاء قيود يومية", "label_en": "Create Journal Entries"},
    {"key": "accounting.post_journal_entry", "section": "accounting", "label_ar": "ترحيل قيود يومية", "label_en": "Post Journal Entries"},
    {"key": "accounting.void_journal_entry", "section": "accounting", "label_ar": "إلغاء قيود يومية", "label_en": "Void Journal Entries"},

    # ═══════════════════════ Approvals – Granular actions ═══════════════════════
    {"key": "approvals.delete", "section": "approvals", "label_ar": "حذف طلبات الاعتماد", "label_en": "Delete Approval Requests"},

    # ═══════════════════════ Blanket Purchase Orders ═══════════════════════
    {"key": "buying.blanket_view", "section": "buying", "label_ar": "عرض أوامر الشراء الشاملة", "label_en": "View Blanket Purchase Orders"},
    {"key": "buying.blanket_manage", "section": "buying", "label_ar": "إدارة أوامر الشراء الشاملة", "label_en": "Manage Blanket Purchase Orders"},
    {"key": "buying.blanket_release", "section": "buying", "label_ar": "إصدار طلبات من أوامر الشراء الشاملة", "label_en": "Release Blanket PO Calls"},

    # ═══════════════════════ Expenses (Policies) ═══════════════════════
    {"key": "expenses.manage", "section": "expenses", "label_ar": "إدارة سياسات المصاريف", "label_en": "Manage Expense Policies"},

    # ═══════════════════════ Finance – Accounting Depth & Postings ═══════════════════════
    {"key": "finance.accounting_view", "section": "finance", "label_ar": "عرض محاسبة المدفوعات (متقدم)", "label_en": "View Payment Accounting (Advanced)"},
    {"key": "finance.accounting_read", "section": "finance", "label_ar": "قراءة قيود المدفوعات", "label_en": "Read Payment Postings"},
    {"key": "finance.accounting_post", "section": "finance", "label_ar": "ترحيل قيود المدفوعات محاسبياً", "label_en": "Post Payment Journal Entries"},

    # ═══════════════════════ Finance – Bank Feeds & Auto-Reconciliation ═══════════════════════
    {"key": "finance.reconciliation_view", "section": "finance", "label_ar": "عرض التسوية البنكية الآلية", "label_en": "View Bank Feed Reconciliation"},
    {"key": "finance.reconciliation_manage", "section": "finance", "label_ar": "إدارة التسوية البنكية الآلية", "label_en": "Manage Bank Feed Reconciliation"},

    # ═══════════════════════ Admin – Security Events ═══════════════════════
    {"key": "admin.security", "section": "admin", "label_ar": "إدارة أحداث الأمان والمراقبة", "label_en": "Manage Security Events & Monitoring"},

    # ═══════════════════════ Mobile App Access ═══════════════════════
    {"key": "mobile.sync", "section": "mobile", "label_ar": "مزامنة بيانات تطبيق الموبايل", "label_en": "Mobile App Data Sync"},
    {"key": "mobile.dashboard", "section": "mobile", "label_ar": "عرض لوحة الموبايل", "label_en": "View Mobile Dashboard"},

    # ═══════════════════════ Umbrella / legacy-alias perms (registered so UI & frontend can reference them) ═══════════════════════
    # These are expanded through PERMISSION_ALIASES in utils/permissions.py:
    #   sales.manage → sales.view + sales.create + sales.edit + sales.delete
    #   buying.manage → buying.view + buying.create + buying.edit + buying.delete
    #   approvals.action ↔ approvals.approve (same semantic; different legacy name)
    #   data_import.execute ↔ data_import.create
    #   stock.create_product / stock.delete_product ↔ products.create / products.delete
    {"key": "sales.manage", "section": "sales", "label_ar": "إدارة المبيعات (عرض/إنشاء/تعديل/حذف)", "label_en": "Manage Sales (View/Create/Edit/Delete)"},
    {"key": "buying.manage", "section": "buying", "label_ar": "إدارة المشتريات (عرض/إنشاء/تعديل/حذف)", "label_en": "Manage Purchases (View/Create/Edit/Delete)"},
    {"key": "approvals.action", "section": "approvals", "label_ar": "تنفيذ إجراء اعتماد (اسم بديل لـ approvals.approve)", "label_en": "Perform Approval Action (alias for approvals.approve)"},
    {"key": "data_import.execute", "section": "data_import", "label_ar": "تنفيذ عمليات الاستيراد (اسم بديل لـ data_import.create)", "label_en": "Execute Import Jobs (alias for data_import.create)"},
    {"key": "stock.create_product", "section": "stock", "label_ar": "إنشاء منتج من شاشة المخزون", "label_en": "Create Product from Stock UI"},
    {"key": "stock.delete_product", "section": "stock", "label_ar": "حذف منتج من شاشة المخزون", "label_en": "Delete Product from Stock UI"},
]

# Section labels for the frontend permission picker UI
PERMISSION_SECTIONS = {
    "dashboard": {"label_ar": "لوحة المعلومات", "label_en": "Dashboard", "icon": "LayoutDashboard"},
    "sales": {"label_ar": "المبيعات", "label_en": "Sales", "icon": "ShoppingCart"},
    "buying": {"label_ar": "المشتريات", "label_en": "Purchases", "icon": "ShoppingBag"},
    "products": {"label_ar": "المنتجات", "label_en": "Products", "icon": "Package"},
    "stock": {"label_ar": "المخزون", "label_en": "Stock", "icon": "Warehouse"},
    "inventory": {"label_ar": "الجرد", "label_en": "Inventory", "icon": "ClipboardList"},
    "accounting": {"label_ar": "المحاسبة", "label_en": "Accounting", "icon": "Calculator"},
    "treasury": {"label_ar": "الخزينة والبنوك", "label_en": "Treasury & Banks", "icon": "Landmark"},
    "taxes": {"label_ar": "الضرائب", "label_en": "Taxes", "icon": "Receipt"},
    "currencies": {"label_ar": "العملات", "label_en": "Currencies", "icon": "DollarSign"},
    "reports": {"label_ar": "التقارير", "label_en": "Reports", "icon": "BarChart3"},
    "hr": {"label_ar": "الموارد البشرية", "label_en": "HR & Payroll", "icon": "Users"},
    "assets": {"label_ar": "الأصول الثابتة", "label_en": "Fixed Assets", "icon": "Building"},
    "expenses": {"label_ar": "المصاريف", "label_en": "Expenses", "icon": "CreditCard"},
    "contracts": {"label_ar": "العقود", "label_en": "Contracts", "icon": "FileSignature"},
    "projects": {"label_ar": "المشاريع", "label_en": "Projects", "icon": "FolderKanban"},
    "pos": {"label_ar": "نقطة البيع", "label_en": "POS", "icon": "Monitor"},
    "manufacturing": {"label_ar": "التصنيع", "label_en": "Manufacturing", "icon": "Factory"},
    "approvals": {"label_ar": "الاعتمادات", "label_en": "Approvals", "icon": "CheckSquare"},
    "notifications": {"label_ar": "التنبيهات", "label_en": "Notifications", "icon": "Bell"},
    "audit": {"label_ar": "المراقبة", "label_en": "Audit", "icon": "Eye"},
    "security": {"label_ar": "الأمان", "label_en": "Security", "icon": "Shield"},
    "data_import": {"label_ar": "استيراد البيانات", "label_en": "Data Import", "icon": "Upload"},
    "services": {"label_ar": "الخدمات والمستندات", "label_en": "Services & Documents", "icon": "Wrench"},
    "parties": {"label_ar": "الأطراف", "label_en": "Parties", "icon": "Users2"},
    "admin": {"label_ar": "الإدارة", "label_en": "Admin", "icon": "Settings"},
    "branches": {"label_ar": "الفروع", "label_en": "Branches", "icon": "GitBranch"},
    "settings": {"label_ar": "إعدادات النظام", "label_en": "System Settings", "icon": "Cog"},
    "sso": {"label_ar": "الدخول الموحد", "label_en": "SSO", "icon": "KeyRound"},
    "matching": {"label_ar": "المطابقة الثلاثية", "label_en": "3-Way Matching", "icon": "CheckCheck"},
    "intercompany": {"label_ar": "بين الشركات", "label_en": "Intercompany", "icon": "Building2"},
    "costing": {"label_ar": "تكاليف المخزون", "label_en": "Inventory Costing", "icon": "Layers"},
    "finance": {"label_ar": "التمويل", "label_en": "Finance", "icon": "TrendingUp"},
    "crm": {"label_ar": "إدارة العلاقات والتسويق", "label_en": "CRM & Marketing", "icon": "Megaphone"},
    "logistics": {"label_ar": "الشحن واللوجستيات", "label_en": "Logistics & Shipments", "icon": "Truck"},
    "forecast": {"label_ar": "توقعات الطلب", "label_en": "Demand Forecasting", "icon": "LineChart"},
    "mobile": {"label_ar": "تطبيق الموبايل", "label_en": "Mobile App", "icon": "Smartphone"},
}


# --- Default Roles ---
# Comprehensive role definitions following proper accounting separation of duties
DEFAULT_ROLES = {
    "admin": {
        "name_ar": "مدير النظام",
        "description": "صلاحيات كاملة على جميع وحدات النظام",
        "permissions": ["*"]
    },
    "manager": {
        "name_ar": "مدير عام",
        "description": "إدارة جميع العمليات مع صلاحيات اعتماد وتقارير",
        "permissions": [
            "dashboard.view",
            "sales.*", "buying.*",
            "products.*", "stock.*", "inventory.*",
            "accounting.view", "accounting.edit", "accounting.budgets.view", "accounting.cost_centers.view",
            "treasury.view", "treasury.create", "treasury.edit",
            "reconciliation.view",
            "taxes.view", "currencies.view",
            "reports.view", "reports.financial", "reports.create",
            "hr.view", "hr.reports", "hr.payroll.view",
            "assets.view", "assets.create",
            "expenses.view", "expenses.approve",
            "contracts.*",
            "projects.*",
            "pos.view", "pos.manage",
            "manufacturing.view", "manufacturing.create", "manufacturing.reports",
            "approvals.view", "approvals.create", "approvals.approve",
            "notifications.view",
            "security.view", "audit.view",
            "data_import.view",
            "branches.view",
            "settings.view",
            "hr.self_service", "hr.self_service_approve",
            "matching.view", "matching.approve",
            "intercompany.view",
            "costing.view",
            "finance.cashflow_view", "finance.cashflow_generate",
            "sso.view",
        ]
    },
    "accountant": {
        "name_ar": "محاسب",
        "description": "إدارة كاملة للمحاسبة والضرائب والخزينة والتقارير المالية",
        "permissions": [
            "dashboard.view",
            "accounting.*",
            "treasury.*", "reconciliation.*",
            "taxes.*", "currencies.*",
            "reports.view", "reports.financial", "reports.create",
            "sales.view", "buying.view",
            "expenses.view", "expenses.approve",
            "assets.*",
            "contracts.view",
            "hr.payroll.view",
            "branches.view",
            "notifications.view",
            "intercompany.view", "intercompany.manage",
            "costing.view",
            "finance.cashflow_view", "finance.cashflow_generate",
            "matching.view",
        ]
    },
    "sales": {
        "name_ar": "مسؤول مبيعات",
        "description": "إدارة المبيعات والعملاء ونقطة البيع",
        "permissions": [
            "dashboard.view",
            "sales.*",
            "products.view", "stock.view",
            "pos.*",
            "contracts.view", "contracts.create",
            "reports.view",
            "approvals.create",
            "notifications.view",
            "branches.view",
        ]
    },
    "purchasing": {
        "name_ar": "مسؤول مشتريات",
        "description": "إدارة المشتريات والموردين وأوامر الشراء",
        "permissions": [
            "dashboard.view",
            "buying.*",
            "products.view", "stock.view", "inventory.view",
            "expenses.create", "expenses.view",
            "reports.view",
            "approvals.create",
            "contracts.view",
            "notifications.view",
            "branches.view",
            "matching.view", "matching.approve",
        ]
    },
    "inventory": {
        "name_ar": "أمين مستودع",
        "description": "إدارة المخزون والمستودعات والنقل والتسوية",
        "permissions": [
            "dashboard.view",
            "inventory.*", "stock.*", "products.*",
            "reports.view",
            "notifications.view",
            "branches.view",
        ]
    },
    "hr_manager": {
        "name_ar": "مدير الموارد البشرية",
        "description": "إدارة الموظفين والرواتب والحضور والإجازات",
        "permissions": [
            "dashboard.view",
            "hr.*", "hr.payroll.*",
            "hr.self_service", "hr.self_service_approve",
            "expenses.view", "expenses.approve",
            "reports.view",
            "approvals.view", "approvals.approve",
            "notifications.view",
            "branches.view",
        ]
    },
    "employee": {
        "name_ar": "موظف",
        "description": "صلاحيات الخدمة الذاتية الأساسية للموظفين",
        "permissions": [
            "dashboard.view",
            "hr.self_service",
            "notifications.view",
        ]
    },
    "cashier": {
        "name_ar": "كاشير / أمين صندوق",
        "description": "تشغيل نقطة البيع وعمليات الصندوق",
        "permissions": [
            "dashboard.view",
            "pos.*",
            "sales.view", "sales.create",
            "products.view", "stock.view",
            "treasury.view", "treasury.create",
            "notifications.view",
        ]
    },
    "manufacturing_user": {
        "name_ar": "مسؤول تصنيع",
        "description": "إدارة أوامر الإنتاج وقوائم المواد ومراكز العمل",
        "permissions": [
            "dashboard.view",
            "manufacturing.*",
            "products.view", "stock.view", "inventory.view",
            "reports.view",
            "notifications.view",
            "branches.view",
        ]
    },
    "project_manager": {
        "name_ar": "مدير مشاريع",
        "description": "إدارة المشاريع والمهام والعقود",
        "permissions": [
            "dashboard.view",
            "projects.*",
            "contracts.*",
            "expenses.view", "expenses.create",
            "reports.view",
            "approvals.create",
            "hr.view",
            "notifications.view",
            "branches.view",
        ]
    },
    "viewer": {
        "name_ar": "مستخدم عرض فقط",
        "description": "عرض البيانات فقط بدون أي صلاحية تعديل",
        "permissions": [
            "dashboard.view",
            "sales.view", "buying.view",
            "products.view", "stock.view",
            "accounting.view",
            "treasury.view",
            "taxes.view", "currencies.view",
            "reports.view",
            "hr.view",
            "assets.view",
            "expenses.view",
            "contracts.view",
            "projects.view",
            "manufacturing.view",
            "notifications.view",
            "branches.view",
        ]
    },
}


# --- Endpoints ---

@router.get("/permissions", response_model=List[dict], dependencies=[Depends(require_permission("admin.roles"))])
def list_available_permissions(current_user: UserResponse = Depends(get_current_user)):
    """عرض قائمة الصلاحيات المتاحة مع أقسامها"""
    return AVAILABLE_PERMISSIONS


@router.get("/permissions/sections", response_model=dict, dependencies=[Depends(require_permission("admin.roles"))])
def list_permission_sections(current_user: UserResponse = Depends(get_current_user)):
    """عرض أقسام الصلاحيات مع أيقوناتها"""
    return PERMISSION_SECTIONS


@router.post("/init-defaults", dependencies=[Depends(require_permission("admin.roles"))], response_model=Dict[str, Any])
def init_default_roles(
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """
    تهيئة / تحديث الأدوار الافتراضية للشركة
    يضيف أدوار جديدة ناقصة ويحدث صلاحيات الأدوار الافتراضية الموجودة
    """
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    db = get_db_connection(target_company_id)
    try:
        created = 0
        updated = 0
        for role_name, role_data in DEFAULT_ROLES.items():
            perms = role_data["permissions"]
            name_ar = role_data.get("name_ar", role_name)
            description = role_data.get("description", "")

            existing = db.execute(text(
                "SELECT id, permissions FROM roles WHERE role_name = :name"
            ), {"name": role_name}).fetchone()

            if existing:
                # Update permissions for system roles
                import json
                db.execute(text("""
                    UPDATE roles SET permissions = :perms, role_name_ar = :name_ar,
                           description = :desc, is_system_role = TRUE
                    WHERE role_name = :name
                """), {
                    "perms": json.dumps(perms),
                    "name_ar": name_ar,
                    "desc": description,
                    "name": role_name
                })
                updated += 1
            else:
                import json
                db.execute(text("""
                    INSERT INTO roles (role_name, role_name_ar, description, permissions, is_system_role)
                    VALUES (:name, :name_ar, :desc, :perms, TRUE)
                """), {
                    "name": role_name,
                    "name_ar": name_ar,
                    "desc": description,
                    "perms": json.dumps(perms)
                })
                created += 1

        db.commit()
        log_activity(
            db, user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', ''),
            action="roles_init_defaults", resource_type="role",
            resource_id="system",
            details={"created": created, "updated": updated},
            critical=True,
        )
        return {"message": f"تم تحديث الأدوار الافتراضية: {created} جديد، {updated} محدث", "created": created, "updated": updated}
    except Exception as e:
        db.rollback()
        logger.error(f"Error initializing default roles: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/", response_model=List[dict], dependencies=[Depends(require_permission("admin.roles"))])
def list_roles(
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """عرض قائمة الأدوار"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        return []

    with transactional(target_company_id) as db:
        result = db.execute(text("""
            SELECT id, role_name, role_name_ar, description, permissions, 
                   is_system_role, created_at
            FROM roles
            ORDER BY is_system_role DESC, role_name
        """)).fetchall()
        
        roles = []
        for row in result:
            roles.append({
                "id": row.id,
                "role_name": row.role_name,
                "role_name_ar": row.role_name_ar,
                "description": row.description,
                "permissions": row.permissions or [],
                "is_system_role": row.is_system_role,
                "created_at": row.created_at.isoformat() if row.created_at else None
            })
        
        return roles


@router.get("/{role_id}", response_model=dict, dependencies=[Depends(require_permission("admin.roles"))])
def get_role(
    role_id: int, 
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """جلب تفاصيل دور محدد"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    with transactional(target_company_id) as db:
        row = db.execute(text("""
            SELECT id, role_name, role_name_ar, description, permissions, 
                   is_system_role, created_at
            FROM roles WHERE id = :id
        """), {"id": role_id}).fetchone()
        
        if not row:
            raise HTTPException(**http_error(404, "role_not_found"))
        
        return {
            "id": row.id,
            "role_name": row.role_name,
            "role_name_ar": row.role_name_ar,
            "description": row.description,
            "permissions": row.permissions or [],
            "is_system_role": row.is_system_role,
            "created_at": row.created_at.isoformat() if row.created_at else None
        }


@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("admin.roles"))], response_model=Dict[str, Any])
def create_role(
    role: RoleCreate, 
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """إنشاء دور جديد"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    db = get_db_connection(target_company_id)
    try:
        # Check name uniqueness
        exists = db.execute(text("SELECT 1 FROM roles WHERE role_name = :name"), {"name": role.role_name}).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="اسم الدور موجود بالفعل")
        
        import json
        result = db.execute(text("""
            INSERT INTO roles (role_name, role_name_ar, description, permissions, is_system_role)
            VALUES (:name, :name_ar, :desc, :perms, FALSE)
            RETURNING id
        """), {
            "name": role.role_name,
            "name_ar": role.role_name_ar,
            "desc": role.description,
            "perms": json.dumps(role.permissions)
        }).fetchone()
        
        db.commit()
        log_activity(
            db, user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', ''),
            action="role_create", resource_type="role",
            resource_id=str(result[0]),
            details={"role_name": role.role_name, "permissions_count": len(role.permissions)},
            critical=True,
        )
        return {"id": result[0], "message": "تم إنشاء الدور بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/{role_id}", dependencies=[Depends(require_permission("admin.roles"))], response_model=Dict[str, Any])
def update_role(
    role_id: int, 
    role: RoleUpdate, 
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """تحديث دور"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    db = get_db_connection(target_company_id)
    try:
        # Check if role exists and is not system role
        existing = db.execute(text("SELECT is_system_role, role_name FROM roles WHERE id = :id"), {"id": role_id}).fetchone()
        
        if not existing:
            raise HTTPException(**http_error(404, "role_not_found"))
        
        # Build update query dynamically
        updates = []
        params = {"id": role_id}
        
        if role.role_name is not None:
            updates.append("role_name = :name")
            params["name"] = role.role_name
        
        if role.role_name_ar is not None:
            updates.append("role_name_ar = :name_ar")
            params["name_ar"] = role.role_name_ar
        
        if role.description is not None:
            updates.append("description = :desc")
            params["desc"] = role.description
        
        if role.permissions is not None:
            import json
            updates.append("permissions = :perms")
            params["perms"] = json.dumps(role.permissions)
        
        if updates:
            query = f"UPDATE roles SET {', '.join(updates)} WHERE id = :id"
            db.execute(text(query), params)
            db.commit()
            log_activity(
                db, user_id=getattr(current_user, 'id', None),
                username=getattr(current_user, 'username', ''),
                action="role_update", resource_type="role",
                resource_id=str(role_id),
                details={"role_name": existing.role_name, "updated_fields": list(params.keys())},
                critical=True,
            )
        
        return {"message": "تم تحديث الدور بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/{role_id}", dependencies=[Depends(require_permission("admin.roles"))], response_model=Dict[str, Any])
def delete_role(
    role_id: int, 
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """حذف دور"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    if not target_company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    db = get_db_connection(target_company_id)
    try:
        # Check if role exists and is not system role
        existing = db.execute(text("SELECT is_system_role FROM roles WHERE id = :id"), {"id": role_id}).fetchone()
        
        if not existing:
            raise HTTPException(**http_error(404, "role_not_found"))
        
        if existing.is_system_role:
            raise HTTPException(status_code=400, detail="لا يمكن حذف الأدوار الافتراضية للنظام")
        
        # Check if any users are using this role
        usage = db.execute(text("SELECT COUNT(*) FROM company_users WHERE role = (SELECT role_name FROM roles WHERE id = :id)"), {"id": role_id}).scalar()
        if usage > 0:
            raise HTTPException(status_code=400, detail=f"لا يمكن حذف الدور لأنه مستخدم من قبل {usage} مستخدم")
        
        role_name = db.execute(text("SELECT role_name FROM roles WHERE id = :id"), {"id": role_id}).scalar()
        db.execute(text("DELETE FROM roles WHERE id = :id"), {"id": role_id})
        db.commit()
        log_activity(
            db, user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', ''),
            action="role_delete", resource_type="role",
            resource_id=str(role_id),
            details={"role_name": role_name},
            critical=True,
        )
        
        return {"message": "تم حذف الدور بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
