from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_project_invoice_uses_backend_preview_total_before_create():
    source = _read("frontend/src/pages/Projects/ProjectDetails.jsx")
    service = _read("frontend/src/services/projects.js")

    assert "previewInvoice: (id, data) => api.post(`/projects/${id}/create-invoice/preview`, data)" in service
    assert "const previewRes = await projectsAPI.previewInvoice(id, payload);" in source
    assert "submitted_grand_total: preview.grand_total" in source
    assert "createInvoice: (id, data) => api.post(`/projects/${id}/create-invoice`, data, idempotencyHeaders())" in service


def test_project_backend_authority_contracts_are_present():
    schema = _read("backend/schemas/projects.py")
    core = _read("backend/routers/projects/core.py")
    finance = _read("backend/routers/projects/finance.py")

    assert "class ProjectExpenseCreate" in schema
    assert "class ProjectRevenueCreate" in schema
    assert "class ProjectInvoiceCreate" in schema
    assert schema.count("submitted_grand_total: Optional[Decimal] = None") >= 3

    assert '@router.post("/{project_id}/create-invoice/preview"' in core
    assert "compute_invoice_totals" in core
    assert "invoice_data.submitted_grand_total" in core
    assert "submitted_grand_total_mismatch" in core
    assert "require_idempotency_key(request, operation=\"project invoice create\")" in core

    assert "expense.submitted_grand_total" in finance
    assert "revenue.submitted_grand_total" in finance
    assert "require_idempotency_key(request, operation=\"project expense create\")" in finance
    assert "require_idempotency_key(request, operation=\"project revenue create\")" in finance


def test_projects_checker_includes_project_frontend_and_schema_targets():
    checker = _read("scripts/check_backend_authority.py")

    assert '"submitted_total_schemas": [' in checker
    assert '"ProjectExpenseCreate"' in checker
    assert '"ProjectRevenueCreate"' in checker
    assert '"ProjectInvoiceCreate"' in checker
    assert '"frontend/src/pages/Projects/ProjectDetails.jsx"' in checker


def test_static_project_routes_are_registered_before_project_id_route():
    source = _read("backend/routers/projects/__init__.py")

    assert source.index("router.include_router(_timetracking_router)") < source.index("router.include_router(_core_router)")


def test_project_subresources_validate_branch_access():
    tasks = _read("backend/routers/projects/tasks.py")
    risks = _read("backend/routers/projects/risks.py")
    change_orders = _read("backend/routers/projects/change_orders.py")

    assert "def _validate_project_access" in tasks
    assert tasks.count("validate_branch_access(current_user") >= 2
    assert "task_dependency_project_mismatch" in tasks
    assert "def _validate_project_access" in risks
    assert "def _validate_risk_access" in risks
    assert "validate_branch_access(current_user, risk.branch_id)" in risks
    assert "def _validate_project_access" in change_orders
    assert "validate_branch_access(current_user, project.branch_id)" in change_orders
