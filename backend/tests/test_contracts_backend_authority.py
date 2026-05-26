from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_contracts_checker_and_schema_cover_backend_authority():
    checker = _read("scripts/check_backend_authority.py")
    schema = _read("backend/schemas/contracts.py")

    assert '"contracts": {' in checker
    assert "ContractInvoiceGenerateRequest" in checker
    assert "class ContractBillingCyclePreviewRequest" in schema
    assert "submitted_grand_total: Optional[Decimal] = None" in schema


def test_contract_router_uses_backend_preview_idempotency_and_decimal_money():
    router = _read("backend/routers/contracts.py")
    fsm_router = _read("backend/routers/fsm/contracts_renewal.py")

    required_tokens = [
        '@router.post("/preview"',
        '@router.post("/billing-cycle/preview"',
        'require_idempotency_key(request, operation="contract invoice generation")',
        'require_idempotency_key(request, operation="contract renewal")',
        "_assert_submitted_total_matches",
        "renewal_idempotency_key",
        "idempotency_key = :key",
        "money_str(total)",
    ]
    missing = [token for token in required_tokens if token not in router]

    assert missing == []
    assert "def _float" not in router
    assert re.search(r"\bfloat\(", router) is None
    assert 'APIRouter(prefix="/fsm/service-contracts"' in fsm_router
    assert 'APIRouter(prefix="/api/fsm/service-contracts"' not in fsm_router


def test_contract_schema_drift_columns_are_in_migration_and_tenant_schema():
    migration = _read("backend/alembic/versions/031d_contracts_backend_authority.py")
    tenant_schema = _read("backend/db_ddl/tenant_schema.py")

    for source in (migration, tenant_schema):
        assert "renewal_idempotency_key" in source
        assert "contract_id" in source
        assert "uq_contract_milestones_idempotency_key" in source


def test_contract_frontend_sends_backend_preview_total_and_idempotency_key():
    service = _read("frontend/src/services/contracts.js")
    details = _read("frontend/src/pages/Sales/ContractDetails.jsx")
    form = _read("frontend/src/pages/Sales/ContractForm.jsx")
    calc_hook = _read("frontend/src/hooks/useInvoiceCalc.js")
    app = _read("frontend/src/App.jsx")

    assert "const idempotencyHeaders" in service
    assert "previewContract: (data) => api.post('/contracts/preview', data)" in service
    assert "renewContract: (id) => api.post(`/contracts/${id}/renew`, null, idempotencyHeaders())" in service
    assert "generateInvoice: (id, data) => api.post(`/contracts/${id}/generate-invoice`, data, idempotencyHeaders())" in service
    assert "previewBillingCycle" in details
    assert "submitted_grand_total" in details
    assert "contractsAPI.previewContract" in form
    assert "/calculate/contract-totals" not in form
    assert "api.post('/contracts/preview', data)" in calc_hook
    assert 'path="/sales/contracts" element={<PrivateRoute permission="contracts.view">' in app
    assert 'path="/sales/contracts/:id" element={<PrivateRoute permission="contracts.view">' in app


def test_services_frontend_does_not_format_money_with_js_number():
    service_requests = _read("frontend/src/pages/Services/ServiceRequests.jsx")
    subscription_plan_form = _read("frontend/src/pages/Subscription/PlanForm.jsx")

    forbidden = [
        r"\bNumber\(req\.actual_cost",
        r"\bNumber\(detail\.estimated_cost",
        r"\bNumber\(detail\.actual_cost",
        r"\bNumber\(c\.unit_cost",
        r"\bNumber\(c\.total_cost",
        r"\.toLocaleString\(",
    ]

    offenders = [pattern for pattern in forbidden if re.search(pattern, service_requests)]
    assert offenders == []
    assert 'type="number" name="base_amount"' not in subscription_plan_form
    assert 'inputMode="decimal" name="base_amount"' in subscription_plan_form
