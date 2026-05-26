from types import SimpleNamespace
from pathlib import Path

from routers.search import CONFIGURED_SEARCH_ENTITIES, _filter_items
from services.search.registry import get_registry_for_user

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_search_registry_expands_permission_aliases_and_wildcards():
    entities = get_registry_for_user({"inventory.*"}, enabled_modules=["stock"])
    codes = {entry["entity_code"] for entry in entities}

    assert "product" in codes


def test_search_registry_filters_disabled_modules():
    entities = get_registry_for_user({"*"}, enabled_modules=["sales"])
    codes = {entry["entity_code"] for entry in entities}

    assert "invoice" in codes
    assert "product" not in codes
    assert "project" not in codes


def test_search_registry_accepts_legacy_inventory_module_key_for_stock():
    entities = get_registry_for_user({"products.view"}, enabled_modules=["inventory"])
    codes = {entry["entity_code"] for entry in entities}

    assert "product" in codes


def test_search_registry_includes_extended_erp_entities_with_valid_routes():
    entities = get_registry_for_user({"*"}, enabled_modules=[])
    by_code = {entry["entity_code"]: entry for entry in entities}

    for code in {
        "customer_group",
        "supplier_group",
        "sales_order",
        "quotation",
        "sales_return",
        "sales_credit_note",
        "sales_debit_note",
        "customer_receipt",
        "purchase_order",
        "purchase_invoice",
        "purchase_return",
        "purchase_credit_note",
        "purchase_debit_note",
        "supplier_payment",
        "contract",
        "expense",
        "budget",
        "treasury_account",
        "treasury_transaction",
        "bank_reconciliation",
        "note_receivable",
        "note_payable",
        "warehouse",
        "product_category",
        "product_unit",
        "price_list",
        "inventory_transaction",
        "stock_adjustment",
        "stock_shipment",
        "product_batch",
        "product_serial",
        "quality_inspection",
        "cycle_count",
        "cost_layer",
        "cost_center",
        "fiscal_year",
        "fiscal_period",
        "recurring_journal_template",
        "fiscal_period_lock",
        "currency",
        "exchange_rate",
        "production_order",
        "delivery_order",
        "blanket_po",
        "rfq",
        "supplier_rating",
        "purchase_agreement",
        "landed_cost",
        "department",
        "position",
        "leave_request",
        "attendance_record",
        "employee_loan",
        "overtime_request",
        "performance_review",
        "payroll_period",
        "payroll_entry",
        "salary_structure",
        "employee_document",
        "review_cycle",
        "training_program",
        "employee_violation",
        "employee_custody",
        "job_opening",
        "job_application",
        "leave_carryover",
        "project_task",
        "project_timesheet",
        "project_risk",
        "resource_allocation",
        "task_dependency",
        "work_center",
        "manufacturing_route",
        "manufacturing_bom",
        "manufacturing_equipment",
        "mrp_plan",
        "capacity_plan",
        "shop_floor_log",
        "asset",
        "asset_category",
        "asset_transfer",
        "asset_disposal",
        "asset_revaluation",
        "asset_insurance",
        "asset_maintenance",
        "lease_contract",
        "asset_impairment",
        "document",
        "service_request",
        "pos_order",
        "pos_session",
        "pos_return",
        "pos_promotion",
        "pos_loyalty_program",
        "pos_table",
        "pos_kitchen_order",
        "tax_return",
        "tax_calendar_event",
        "tax_rate",
        "tax_group",
        "tax_classification",
        "tax_payment",
        "tax_regime",
        "wht_rate",
        "wht_transaction",
        "zakat_calculation",
        "crm_opportunity",
        "support_ticket",
        "marketing_campaign",
        "crm_contact",
        "crm_segment",
        "crm_knowledge_base",
        "crm_sales_forecast",
        "approval_workflow",
        "approval_request",
        "cashflow_forecast",
        "subscription_plan",
        "subscription_enrollment",
        "revenue_schedule",
        "intercompany_entity",
        "intercompany_transaction",
        "branch",
        "role",
        "audit_log",
        "security_event",
        "email_template",
        "print_template",
        "webhook",
        "sso_configuration",
        "integration_key",
        "integration_dlq",
        "notification_queue_item",
        "company_setting",
        "report_template",
        "custom_report",
        "scheduled_report",
        "analytics_dashboard",
        "sales_commission",
        "cpq_quote",
        "cpq_pricing_rule",
        "demand_forecast",
        "expense_policy",
        "bank_import_batch",
        "match_tolerance",
        "eos_provision",
        "alert_rule",
    }:
        assert code in by_code
        assert by_code[code]["route_template"]
        assert by_code[code]["resource"]


def test_search_registry_routes_match_frontend_paths():
    entities = get_registry_for_user({"*"}, enabled_modules=[])
    routes = {entry["entity_code"]: entry["route_template"] for entry in entities}

    assert routes["supplier"].startswith("/buying/suppliers/")
    assert routes["product"].startswith("/stock/products")
    assert routes["account"].startswith("/accounting/coa")
    assert routes["treasury_account"].startswith("/treasury/accounts")
    assert routes["document"].startswith("/services/documents")
    assert routes["pos_order"].startswith("/pos")
    assert routes["stock_adjustment"].startswith("/stock/adjustments")
    assert routes["project_risk"].startswith("/projects/risks")
    assert routes["manufacturing_bom"].startswith("/manufacturing/boms")
    assert routes["support_ticket"].startswith("/crm/tickets")
    assert routes["tax_calendar_event"].startswith("/taxes/calendar")
    assert routes["branch"].startswith("/settings/branches")
    assert routes["approval_request"].startswith("/approvals")
    assert routes["subscription_enrollment"].startswith("/finance/subscriptions/enrollments")
    assert routes["cpq_quote"].startswith("/sales/cpq/quotes")
    assert routes["cpq_pricing_rule"].startswith("/sales/cpq/products")
    assert routes["demand_forecast"].startswith("/inventory/forecast")


def test_search_registry_has_no_duplicate_codes_or_unsupported_route_placeholders():
    entities = get_registry_for_user({"*"}, enabled_modules=[])
    codes = [entry["entity_code"] for entry in entities]

    assert len(codes) == len(set(codes))
    for entry in entities:
        route = entry["route_template"]
        assert "{work_order_id}" not in route
        assert "{project_id}" not in route


def test_configured_search_entities_are_registered_and_scoped():
    entities = get_registry_for_user({"*"}, enabled_modules=[])
    codes = {entry["entity_code"] for entry in entities}

    assert set(CONFIGURED_SEARCH_ENTITIES).issubset(codes)
    assert CONFIGURED_SEARCH_ENTITIES["stock_shipment"]["warehouse_columns"] == (
        ("ss", "source_warehouse_id"),
        ("ss", "destination_warehouse_id"),
    )
    assert CONFIGURED_SEARCH_ENTITIES["work_center"]["cost_center"] == ("wc", "cost_center_id")
    assert CONFIGURED_SEARCH_ENTITIES["project_task"]["branch_alias"] == "p"


def test_remaining_search_entities_have_precise_permissions_and_safe_config():
    entities = get_registry_for_user({"*"}, enabled_modules=[])
    by_code = {entry["entity_code"]: entry for entry in entities}

    assert by_code["demand_forecast"]["permissions_required"] == ["inventory.forecast_view"]
    assert by_code["match_tolerance"]["permissions_required"] == ["buying.edit"]
    assert "base_where" not in CONFIGURED_SEARCH_ENTITIES["cpq_quote"]
    assert "accrued_gratuity" not in CONFIGURED_SEARCH_ENTITIES["eos_provision"]["select"]


def test_search_field_filter_hides_entire_restricted_resource():
    user = SimpleNamespace(role="warehouse_keeper", permissions=[])
    items = [{"id": 1, "name": "INV-001", "customer_name": "Customer"}]

    assert _filter_items(items, "invoices", user, db=None) == []


def test_search_field_filter_removes_restricted_product_fields():
    user = SimpleNamespace(role="salesperson", permissions=[])
    items = [{"id": 1, "name": "A", "code": "P-1", "cost_price": "10.0000"}]

    assert _filter_items(items, "products", user, db=None) == [{"id": 1, "name": "A", "code": "P-1"}]


def test_contract_and_employee_lists_have_parameterized_search_filters():
    contracts = (REPO_ROOT / "backend/routers/contracts.py").read_text(encoding="utf-8")
    employees = (REPO_ROOT / "backend/routers/hr/core/employees.py").read_text(encoding="utf-8")

    assert "search: Optional[str] = None" in contracts
    assert "params[\"search\"] = f\"%{search}%\"" in contracts
    assert "c.contract_number ILIKE :search" in contracts
    assert "p.name ILIKE :search" in contracts

    assert "search: Optional[str] = None" in employees
    assert "params[\"search\"] = f\"%{search}%\"" in employees
    assert "e.employee_code ILIKE :search" in employees
    assert "p.position_name ILIKE :search" in employees
