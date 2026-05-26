from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_reports_checker_configuration_is_present():
    checker = _read("scripts/check_backend_authority.py")

    assert '"reports": {' in checker
    assert "Reports / KPI / Dashboards / Analytics" in checker
    assert '"backend/routers/reports/accounting_statements.py"' in checker
    assert '"backend/routers/reports/accounting_compare_export.py"' in checker
    assert '"backend/routers/reports/kpi.py"' in checker
    assert '"backend/routers/dashboard.py"' in checker
    assert '"backend/db_ddl/tenant_schema.py"' in checker
    assert '"frontend/src/pages/Accounting/GeneralLedger.jsx"' in checker
    assert '"frontend/src/pages/Analytics/DashboardView.jsx"' in checker
    assert "Report cache refresh is scoped to the authenticated tenant" in checker


def test_reports_backend_returns_decimal_summaries_and_pagination():
    statements = _read("backend/routers/reports/accounting_statements.py")
    exports = _read("backend/routers/reports/accounting_compare_export.py")
    reports_init = _read("backend/routers/reports/__init__.py")
    mv_refresh = _read("backend/services/reports/mv_refresh.py")
    dashboard = _read("backend/routers/dashboard.py")
    kpi = _read("backend/routers/reports/kpi.py")
    tenant_schema = _read("backend/db_ddl/tenant_schema.py")
    migration = _read("backend/alembic/versions/031e_reports_analytics_mvs.py")

    assert "limit: int = Query(25, ge=1, le=100)" in statements
    assert '"pagination": {' in statements
    assert '"summary": {' in statements
    assert re.search(r"\bfloat\(", statements) is None

    assert "_get_general_ledger_data(" in exports
    assert "limit=None" in exports
    assert "get_general_ledger(" not in exports
    assert re.search(r"\bfloat\(", exports) is None

    assert "def _widget_summary" in dashboard
    assert '"summary": _widget_summary' in dashboard
    assert "limit: int = Query(25, ge=1, le=100)" in dashboard
    assert "branch_id = ANY(:branch_ids)" in dashboard
    assert "Decimal(" in dashboard
    assert re.search(r"\bfloat\(", dashboard) is None

    assert "Decimal(" in kpi
    assert '"financial_ratios": {' in kpi
    assert re.search(r"\bfloat\(", kpi) is None

    assert "CREATE TABLE IF NOT EXISTS analytics_mv_freshness" in tenant_schema
    assert "ux_mv_revenue_month ON mv_revenue_summary(month, branch_id)" in tenant_schema
    assert "customer_name" in tenant_schema
    assert "supplier_name" in tenant_schema
    assert "turnover_ratio" in tenant_schema
    assert "avg_probability" in tenant_schema
    assert "DROP MATERIALIZED VIEW IF EXISTS mv_revenue_summary" in migration

    assert "refresh_report_mvs(tenant_id=tenant_id)" in reports_init
    assert "company_id_missing" in reports_init
    assert "ANALYTICS_MVS = {" in mv_refresh
    assert '"mv_revenue_summary"' in mv_refresh
    assert "analytics_mv_freshness" in mv_refresh
    assert "pg_matviews" in mv_refresh


def test_reports_frontend_uses_backend_authoritative_values():
    dashboard_view = _read("frontend/src/pages/Analytics/DashboardView.jsx")
    general_ledger = _read("frontend/src/pages/Accounting/GeneralLedger.jsx")
    kpi_dashboard = _read("frontend/src/pages/Reports/KPIDashboard.jsx")
    service = _read("frontend/src/services/dashboard.js")

    forbidden = [
        r"\.reduce\(",
        r"\bNumber\(",
        r"parseFloat",
        r"toFixed\(",
        r"toLocaleString\(",
    ]

    for pattern in forbidden:
        assert re.search(pattern, dashboard_view) is None
        assert re.search(pattern, general_ledger) is None
        assert re.search(pattern, kpi_dashboard) is None

    assert "skip: (page - 1) * pageSize" in general_ledger
    assert "limit: pageSize" in general_ledger
    assert "<Pagination" in general_ledger
    assert "widget.summary" in dashboard_view
    assert "widget.value_keys" in dashboard_view
    assert "widget.pie_data" in dashboard_view
    assert "params.limit = 25" in dashboard_view
    assert "getAnalyticsDashboard: (id, config = {})" in service
