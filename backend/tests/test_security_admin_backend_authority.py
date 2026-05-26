import ast
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: set[str] = set()
        for item in node.elts:
            values.update(_literal_strings(item))
        return values
    return set()


def _required_permission_literals() -> set[str]:
    required: set[str] = set()
    for path in (REPO_ROOT / "backend" / "routers").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) not in {"require_permission", "require_sensitive_permission"}:
                continue
            if node.args:
                required.update(_literal_strings(node.args[0]))
            for keyword in node.keywords:
                if keyword.arg in {"permission", "scope"}:
                    required.update(_literal_strings(keyword.value))
    return required


def _registered_role_permission_keys() -> set[str]:
    tree = ast.parse(_read("backend/routers/roles.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "AVAILABLE_PERMISSIONS" for t in node.targets):
            permissions = ast.literal_eval(node.value)
            return {item["key"] for item in permissions}
    raise AssertionError("AVAILABLE_PERMISSIONS registry not found")


def _backend_permission_alias_literals() -> dict[str, list[str]]:
    tree = ast.parse(_read("backend/utils/permissions.py"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PERMISSION_ALIASES"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("PERMISSION_ALIASES not found")


def test_security_admin_checker_configuration_is_present():
    checker = _read("scripts/check_backend_authority.py")

    assert '"security_admin": {' in checker
    assert "Approvals / Workflow / Audit / Security / Admin" in checker
    assert '"backend/routers/approvals.py"' in checker
    assert '"backend/routers/finance/advanced_workflow.py"' in checker
    assert '"backend/routers/audit.py"' in checker
    assert '"backend/routers/security.py"' in checker
    assert '"backend/routers/settings.py"' in checker
    assert '"backend/routers/roles.py"' in checker
    assert "Approval action endpoint requires Idempotency-Key" in checker


def test_approval_permission_aliases_are_symmetric_between_backend_and_frontend():
    backend_permissions = _read("backend/utils/permissions.py")
    frontend_auth = _read("frontend/src/utils/auth.js")

    assert '"approvals.action": ["approvals.approve"]' in backend_permissions
    assert '"approvals.approve": ["approvals.action"]' in backend_permissions
    assert '"approvals.manage": [\n        "approvals.view", "approvals.create", "approvals.edit",' in backend_permissions
    assert '"approvals.action", "approvals.approve"' in backend_permissions

    assert "'approvals.action': ['approvals.approve']" in frontend_auth
    assert "'approvals.approve': ['approvals.action']" in frontend_auth
    assert "'approvals.manage': ['approvals.view', 'approvals.create', 'approvals.edit', 'approvals.action', 'approvals.approve']" in frontend_auth


def test_approval_actions_are_backend_authoritative_and_idempotent():
    approvals = _read("backend/routers/approvals.py")
    tenant_schema = _read("backend/db_ddl/tenant_schema.py")
    migration = _read("backend/alembic/versions/031f_approvals_workflow_security_authority.py")

    assert 'require_idempotency_key(http_request, operation="approval action")' in approvals
    assert "approval_request = db.execute" in approvals
    assert re.search(
        r"^\s*request\s*=\s*db\.execute\(text\(\"SELECT \* FROM approval_requests",
        approvals,
        re.MULTILINE,
    ) is None
    assert "INSERT INTO approval_actions (request_id, step, action, actioned_by, notes, idempotency_key)" in approvals
    assert "WHERE aa.idempotency_key = :idempotency_key" in approvals
    assert "duplicate_idempotency_key" in approvals
    assert "def _user_can_approve_step" in approvals
    assert "APPROVER_ELIGIBILITY_SQL" in approvals
    assert "WHERE role = :role AND is_active = TRUE" in approvals
    assert "JOIN user_roles" not in approvals
    assert "WHERE r.name = :role" not in approvals
    assert "critical=True" in approvals
    assert "@router.get(\"/document-types\", dependencies=[Depends(require_permission(\"approvals.view\"))]" in approvals
    assert "limit: int = Query(50, ge=1, le=100)" in approvals
    assert re.search(r"logger\.(exception|error|warning)\(f", approvals) is None

    assert "idempotency_key VARCHAR(120)" in tenant_schema
    assert "uq_approval_actions_idempotency" in tenant_schema
    assert "uq_approval_actions_idempotency" in migration
    assert 'down_revision: Union[str, None] = "031e_reports_analytics_mvs"' in migration


def test_workflow_audit_security_admin_guards_are_wired():
    workflow = _read("backend/routers/finance/advanced_workflow.py")
    governance = _read("backend/routers/governance.py")
    audit = _read("backend/routers/audit.py")
    security = _read("backend/routers/security.py")
    settings = _read("backend/routers/settings.py")
    roles = _read("backend/routers/roles.py")

    assert 'require_idempotency_key(request, operation="workflow auto approval")' in workflow
    assert 'require_permission("approvals.edit")' in workflow
    assert '"total_requests": total_requests' in workflow
    assert '"approval_rate": str(approval_rate)' in workflow
    assert "workflow.sla_update" in workflow
    assert "workflow.conditions_update" in workflow
    assert "logger.exception(" not in workflow

    assert 'action="approvals.sla_escalate"' in governance
    assert "critical=True" in governance

    assert "from utils.i18n import http_error" in audit
    assert "limit: int = Query(50, ge=1, le=100)" in audit
    assert "resolve_target_company_id" in audit
    assert "branch_scope_filter_from_scope" in audit

    assert security.count("limit: int = Query(50, ge=1, le=100)") >= 2
    assert "logger.exception(" not in security
    assert re.search(r"logger\.(error|warning)\(f", security) is None

    assert 'require_sensitive_permission("settings.manage", critical=True)' in settings
    assert "critical=True)" in settings
    assert 'require_permission("admin.roles")' in roles


def test_backend_required_permissions_are_assignable_from_roles_registry():
    required = _required_permission_literals()
    registered = _registered_role_permission_keys()

    missing = sorted(required - registered)
    assert missing == []


def test_backend_permission_alias_targets_are_visible_or_wildcard_assignable():
    registered = _registered_role_permission_keys()
    aliases = _backend_permission_alias_literals()

    referenced = set(aliases.keys())
    for values in aliases.values():
        referenced.update(values)

    hidden = sorted(key for key in referenced - registered if not key.endswith(".*"))
    assert hidden == []


def test_roles_reject_permissions_outside_registry_and_fsm_admin_routes_are_scoped():
    roles = _read("backend/routers/roles.py")
    pricelists = _read("backend/routers/fsm/pricelists_admin.py")
    technicians = _read("backend/routers/fsm/technicians_admin.py")

    assert "def _validate_role_permissions" in roles
    assert "_validate_role_permissions(role.permissions, request)" in roles
    assert 'prefix="/fsm/pricelists"' in pricelists
    assert 'prefix="/api/fsm/pricelists"' not in pricelists
    assert 'require_module("services")' in pricelists
    assert 'require_permission("services.edit")' in pricelists
    assert 'prefix="/fsm/technicians"' in technicians
    assert 'prefix="/api/fsm/technicians"' not in technicians
    assert 'require_module("services")' in technicians
    assert 'require_permission("services.edit")' in technicians


def test_high_risk_cross_module_routes_are_permission_guarded_and_tenant_scoped():
    kpi = _read("backend/routers/kpi.py")
    ops_scheduler = _read("backend/routers/ops_scheduler.py")
    ops_restore = _read("backend/routers/ops_restore.py")
    returns = _read("backend/routers/returns_unified.py")
    offline = _read("backend/routers/pos/offline.py")
    mrp = _read("backend/routers/manufacturing/mrp.py")
    production = _read("backend/routers/manufacturing/production.py")
    approval = _read("backend/routers/manufacturing/production_approval.py")
    qc = _read("backend/routers/manufacturing/qc.py")

    assert 'require_permission("dashboard.analytics_manage")' in kpi
    assert 'get_tenant_db(current_user.company_id)' in kpi
    assert 'require_sensitive_permission("ops.scheduler.admin"' in ops_scheduler
    assert 'get_tenant_db(company_id)' in ops_scheduler
    assert 'require_sensitive_permission("ops.restore"' in ops_restore
    assert 'get_tenant_db(company_id)' in ops_restore

    assert 'get_company_db(current_user.company_id)' in returns
    assert 'require_permission(["sales.approve_return", "pos.returns", "buying.create"])' in returns
    assert 'limit: int = Query(50, ge=1, le=100)' in returns

    assert 'require_module("pos")' in offline
    assert 'require_permission("pos.create")' in offline
    assert 'require_permission("pos.manage")' in offline

    for source in (mrp, production, approval, qc):
        assert 'get_company_db(current_user.company_id)' in source
        assert 'require_module("manufacturing")' in source
    assert 'require_permission("manufacturing.manage")' in mrp
    assert 'require_permission(["manufacturing.manage", "manufacturing.create"])' in production
    assert 'require_permission("manufacturing.manage")' in approval
    assert 'require_permission("manufacturing.manage")' in qc


def test_audit_pipeline_sanitizes_failures_and_preserves_outbox_contract():
    audit_utils = _read("backend/utils/audit.py")
    writer = _read("backend/services/audit_writer.py")
    worker = _read("backend/services/audit_outbox_worker.py")
    main = _read("backend/main.py")

    assert "services.audit_writer import log_activity as _outbox_log" in audit_utils
    assert "exc_info=True" not in audit_utils
    assert "err={e}" not in audit_utils

    assert "sanitize_for_audit(normalized, context=action)" in writer
    assert "exc_info=True" not in writer
    assert 'raise AuditWriteError(f"Failed to enqueue audit row for {action}")' in writer

    assert "SELECT setting_value FROM company_settings WHERE setting_key = :k" in worker
    assert '"flush_failed"' in worker
    assert "logger.exception(" not in worker

    assert "traceback.format_exc" not in main
    assert "Unhandled exception on %s %s" in main


def test_approvals_frontend_sends_actions_with_idempotency_not_final_status():
    page = _read("frontend/src/pages/Approvals/ApprovalsPage.jsx")
    service = _read("frontend/src/services/approvals.js")

    assert "makeIdempotencyKey('approval-action')" in page
    assert "'Idempotency-Key': makeIdempotencyKey('approval-action')" in page
    assert "openDetailsModal(item)" in page
    assert "navigate(`/approvals/requests/${item.id}`)" not in page
    assert "{actionType && (" in page
    assert "action: actionType" in page
    assert "notes: actionNotes" in page
    assert "status: actionType" not in page
    assert re.search(r"status\s*:\s*['\"](?:approved|rejected|posted|finalized)['\"]", page) is None

    assert "withIdempotency" in service
    assert "'Idempotency-Key'" in service
    assert "takeAction: (id, data) => api.post" in service
