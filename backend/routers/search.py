"""T141: Search router — registry and cross-entity search endpoints.

Guarded by permissions and tenant isolation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Any

from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import text

from routers.auth.core import get_current_user
from database import get_tenant_db
from services.search.registry import get_registry_for_user
from services.search.logging import log_search_query
from utils.permissions import (
    build_cost_center_filter,
    build_warehouse_filter,
    filter_fields,
    get_allowed_warehouses,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


def _user_value(current_user: Any, key: str, default: Any = None) -> Any:
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)


def _allowed_branches(current_user: Any) -> list[int]:
    """Return normalized branch ids; empty means unrestricted."""
    values = _user_value(current_user, "allowed_branches", []) or []
    branches: list[int] = []
    for value in values:
        try:
            branches.append(int(value))
        except (TypeError, ValueError):
            continue
    return branches


def _tenant_id(current_user: Any) -> str:
    tenant_id = str(_user_value(current_user, "company_id", "") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Search requires an active company context")
    return tenant_id


def _user_permissions(current_user: Any) -> set[str]:
    return set(_user_value(current_user, "permissions", []) or [])


def _enabled_modules(current_user: Any) -> list[str]:
    return list(_user_value(current_user, "enabled_modules", []) or [])


def _username(current_user: Any) -> str:
    return str(_user_value(current_user, "username", "unknown") or "unknown")


def _filter_items(items: list[dict], resource: str, current_user: Any, db) -> list[dict]:
    try:
        filtered = filter_fields(items, resource, current_user, db)
        return filtered if isinstance(filtered, list) else []
    except HTTPException as exc:
        if exc.status_code == 403:
            return []
        raise


def _branch_clause(alias: str, allowed_branches: list[int]) -> str:
    if not allowed_branches:
        return ""
    return f"AND ({alias}.branch_id IS NULL OR {alias}.branch_id = ANY(:allowed_branches))"


def _search_invoices_by_type(
    db,
    *,
    invoice_type: str,
    search_param: str,
    limit: int,
    allowed_branches: list[int],
    branch_params: dict,
    current_user: Any,
    party_key: str,
    warehouse_scoped: bool = False,
) -> list[dict]:
    warehouse_filter = ""
    warehouse_params = {}
    if warehouse_scoped:
        warehouse_filter, warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "i")

    query_str = """
        SELECT i.id, i.invoice_number AS name,
               COALESCE(p.name, c.customer_name, s.supplier_name) AS party_name,
               i.status
        FROM invoices i
        LEFT JOIN parties p ON i.party_id = p.id
        LEFT JOIN customers c ON i.customer_id = c.id
        LEFT JOIN suppliers s ON i.supplier_id = s.id
        WHERE i.invoice_type = :invoice_type
          AND (
            i.invoice_number ILIKE :q
            OR p.name ILIKE :q
            OR c.customer_name ILIKE :q
            OR s.supplier_name ILIKE :q
            OR i.status ILIKE :q
            OR i.notes ILIKE :q
          )
        {branch_clause}
        {warehouse_filter}
        LIMIT :limit
    """.format(
        branch_clause=_branch_clause("i", allowed_branches),
        warehouse_filter=warehouse_filter,
    )
    rows = db.execute(
        text(query_str),
        {
            "invoice_type": invoice_type,
            "q": search_param,
            "limit": limit,
            **branch_params,
            **warehouse_params,
        },
    ).fetchall()
    return [
        {"id": r.id, "name": r.name, party_key: r.party_name, "status": r.status}
        for r in rows
    ]


def _warehouse_scope_clause(current_user: Any, db, columns: tuple[tuple[str, str], ...]) -> tuple[str, dict]:
    if not columns:
        return "", {}

    allowed = get_allowed_warehouses(current_user, db)
    if allowed is None:
        return "", {}

    if not allowed:
        return "AND 1=0", {}

    param_names = [f"_cfg_wh_{idx}" for idx in range(len(allowed))]
    placeholders = ", ".join(f":{name}" for name in param_names)
    params = {name: int(value) for name, value in zip(param_names, allowed)}
    clauses = [f"{alias}.{column} IN ({placeholders})" for alias, column in columns]
    return f"AND ({' OR '.join(clauses)})", params


def _search_configured_entity(
    db,
    *,
    config: dict[str, Any],
    search_param: str,
    limit: int,
    allowed_branches: list[int],
    branch_params: dict,
    current_user: Any,
) -> list[dict]:
    where_parts = [
        "(" + " OR ".join(f"{field} ILIKE :q" for field in config["search"]) + ")"
    ]
    where_parts.extend(config.get("base_where", ()))

    branch_scope = _branch_clause(config["branch_alias"], allowed_branches) if config.get("branch_alias") else ""
    warehouse_scope, warehouse_params = _warehouse_scope_clause(
        current_user,
        db,
        tuple(config.get("warehouse_columns", ())),
    )
    cost_center_scope = ""
    cost_center_params = {}
    if config.get("cost_center"):
        alias, column = config["cost_center"]
        cost_center_scope, cost_center_params = build_cost_center_filter(current_user, db, column, alias)

    query_str = """
        SELECT {select}
        FROM {from_clause}
        WHERE {where_clause}
        {branch_scope}
        {warehouse_scope}
        {cost_center_scope}
        LIMIT :limit
    """.format(
        select=config["select"],
        from_clause=config["from"],
        where_clause=" AND ".join(where_parts),
        branch_scope=branch_scope,
        warehouse_scope=warehouse_scope,
        cost_center_scope=cost_center_scope,
    )
    rows = db.execute(
        text(query_str),
        {
            "q": search_param,
            "limit": limit,
            **branch_params,
            **warehouse_params,
            **cost_center_params,
            **config.get("params", {}),
        },
    ).fetchall()
    return [dict(row._mapping) for row in rows]


CONFIGURED_SEARCH_ENTITIES: dict[str, dict[str, Any]] = {
    "customer_group": {
        "select": "cg.id, cg.group_name AS name, cg.group_code AS code, cg.status",
        "from": "customer_groups cg",
        "search": ("cg.group_name", "cg.group_name_en", "cg.group_code", "cg.description", "cg.status"),
        "branch_alias": "cg",
    },
    "supplier_group": {
        "select": "sg.id, sg.group_name AS name, sg.group_code AS code, sg.status",
        "from": "supplier_groups sg",
        "search": ("sg.group_name", "sg.group_name_en", "sg.group_code", "sg.description", "sg.status"),
        "branch_alias": "sg",
    },
    "product_category": {
        "select": "pc.id, pc.category_name AS name, pc.category_code AS code",
        "from": "product_categories pc",
        "search": ("pc.category_name", "pc.category_name_en", "pc.category_code", "pc.description"),
        "branch_alias": "pc",
    },
    "product_unit": {
        "select": "pu.id, pu.unit_name AS name, pu.unit_code AS code, pu.abbreviation",
        "from": "product_units pu",
        "search": ("pu.unit_name", "pu.unit_name_en", "pu.unit_code", "pu.abbreviation"),
    },
    "price_list": {
        "select": "pl.id, pl.price_list_name AS name, pl.price_list_code AS code, pl.status",
        "from": "customer_price_lists pl",
        "search": ("pl.price_list_name", "pl.price_list_name_en", "pl.price_list_code", "pl.status"),
        "branch_alias": "pl",
    },
    "inventory_transaction": {
        "select": "it.id, COALESCE(it.reference_document, it.reference_type || ' #' || it.reference_id::text) AS name, p.product_name, it.transaction_type",
        "from": "inventory_transactions it LEFT JOIN products p ON it.product_id = p.id",
        "search": ("it.transaction_type", "it.reference_type", "it.reference_document", "it.notes", "p.product_name", "p.product_code", "p.sku"),
        "warehouse_columns": (("it", "warehouse_id"),),
    },
    "stock_adjustment": {
        "select": "sa.id, sa.adjustment_number AS name, p.product_name, sa.status",
        "from": "stock_adjustments sa LEFT JOIN products p ON sa.product_id = p.id",
        "search": ("sa.adjustment_number", "sa.adjustment_type", "sa.reason", "sa.notes", "sa.status", "p.product_name", "p.product_code"),
        "warehouse_columns": (("sa", "warehouse_id"),),
    },
    "stock_shipment": {
        "select": "ss.id, ss.shipment_ref AS name, ss.status",
        "from": "stock_shipments ss",
        "search": ("ss.shipment_ref", "ss.status", "ss.notes"),
        "warehouse_columns": (("ss", "source_warehouse_id"), ("ss", "destination_warehouse_id")),
    },
    "product_batch": {
        "select": "pb.id, pb.batch_number AS name, p.product_name, pb.status",
        "from": "product_batches pb LEFT JOIN products p ON pb.product_id = p.id",
        "search": ("pb.batch_number", "pb.reference_type", "pb.notes", "pb.status", "p.product_name", "p.product_code", "p.sku"),
        "warehouse_columns": (("pb", "warehouse_id"),),
    },
    "product_serial": {
        "select": "ps.id, ps.serial_number AS name, p.product_name, ps.status",
        "from": "product_serials ps LEFT JOIN products p ON ps.product_id = p.id",
        "search": ("ps.serial_number", "ps.purchase_reference", "ps.sale_reference", "ps.notes", "ps.status", "p.product_name", "p.product_code", "p.sku"),
        "warehouse_columns": (("ps", "warehouse_id"),),
    },
    "quality_inspection": {
        "select": "qi.id, qi.inspection_number AS name, p.product_name, qi.status",
        "from": "quality_inspections qi LEFT JOIN products p ON qi.product_id = p.id",
        "search": ("qi.inspection_number", "qi.inspection_type", "qi.reference_type", "qi.result_notes", "qi.rejection_reason", "qi.status", "p.product_name", "p.product_code"),
        "warehouse_columns": (("qi", "warehouse_id"),),
    },
    "cycle_count": {
        "select": "cc.id, cc.count_number AS name, w.warehouse_name, cc.status",
        "from": "cycle_counts cc LEFT JOIN warehouses w ON cc.warehouse_id = w.id",
        "search": ("cc.count_number", "cc.count_type", "cc.status", "cc.notes", "w.warehouse_name", "w.warehouse_code"),
        "warehouse_columns": (("cc", "warehouse_id"),),
    },
    "cost_layer": {
        "select": "cl.id, (p.product_name || ' - ' || cl.source_document_type) AS name, p.product_name, cl.costing_method",
        "from": "cost_layers cl LEFT JOIN products p ON cl.product_id = p.id",
        "search": ("cl.costing_method", "cl.source_document_type", "p.product_name", "p.product_code", "p.sku"),
        "base_where": ("COALESCE(cl.is_deleted, FALSE) = FALSE",),
        "warehouse_columns": (("cl", "warehouse_id"),),
    },
    "cost_center": {
        "select": "cc.id, cc.center_name AS name, cc.center_code AS code",
        "from": "cost_centers cc",
        "search": ("cc.center_name", "cc.center_name_en", "cc.center_code"),
        "cost_center": ("cc", "id"),
    },
    "fiscal_year": {
        "select": "fy.id, CAST(fy.year AS TEXT) AS name, fy.status",
        "from": "fiscal_years fy",
        "search": ("CAST(fy.year AS TEXT)", "fy.status"),
    },
    "fiscal_period": {
        "select": "fp.id, fp.name, CAST(fp.fiscal_year AS TEXT) AS fiscal_year, CASE WHEN fp.is_closed THEN 'closed' ELSE 'open' END AS status",
        "from": "fiscal_periods fp",
        "search": ("fp.name", "CAST(fp.fiscal_year AS TEXT)", "CAST(fp.start_date AS TEXT)", "CAST(fp.end_date AS TEXT)"),
    },
    "recurring_journal_template": {
        "select": "rjt.id, rjt.name, rjt.reference, CASE WHEN rjt.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "recurring_journal_templates rjt",
        "search": ("rjt.name", "rjt.description", "rjt.reference", "rjt.frequency", "rjt.currency"),
        "branch_alias": "rjt",
    },
    "fiscal_period_lock": {
        "select": "fpl.id, fpl.period_name AS name, CASE WHEN fpl.is_locked THEN 'locked' ELSE 'open' END AS status",
        "from": "fiscal_period_locks fpl",
        "search": ("fpl.period_name", "fpl.reason", "CAST(fpl.period_start AS TEXT)", "CAST(fpl.period_end AS TEXT)"),
    },
    "currency": {
        "select": "c.id, c.name, c.code, c.symbol",
        "from": "currencies c",
        "search": ("c.code", "c.name", "c.name_en", "c.symbol"),
    },
    "exchange_rate": {
        "select": "er.id, (c.code || ' - ' || CAST(er.rate_date AS TEXT)) AS name, c.code AS currency_code, er.source",
        "from": "exchange_rates er LEFT JOIN currencies c ON er.currency_id = c.id",
        "search": ("c.code", "c.name", "er.source", "CAST(er.rate_date AS TEXT)"),
    },
    "report_template": {
        "select": "rt.id, rt.template_name AS name, rt.template_type",
        "from": "report_templates rt",
        "search": ("rt.template_name", "rt.template_type", "rt.description"),
    },
    "custom_report": {
        "select": "cr.id, cr.report_name AS name, cr.description",
        "from": "custom_reports cr",
        "search": ("cr.report_name", "cr.description"),
    },
    "scheduled_report": {
        "select": "sr.id, COALESCE(sr.report_name, sr.report_type) AS name, sr.report_type, sr.last_status AS status",
        "from": "scheduled_reports sr",
        "search": ("sr.report_name", "sr.report_type", "sr.frequency", "sr.format", "sr.last_status"),
        "branch_alias": "sr",
    },
    "analytics_dashboard": {
        "select": "ad.id, ad.name, ad.description",
        "from": "analytics_dashboards ad",
        "search": ("ad.name", "ad.description"),
    },
    "rfq": {
        "select": "rfq.id, COALESCE(rfq.rfq_number, rfq.title) AS name, rfq.title, rfq.status",
        "from": "request_for_quotations rfq",
        "search": ("rfq.rfq_number", "rfq.title", "rfq.description", "rfq.status"),
        "branch_alias": "rfq",
    },
    "supplier_rating": {
        "select": "sr.id, COALESCE(s.supplier_name, 'Supplier #' || sr.supplier_id::text) AS name, s.supplier_name, sr.comments",
        "from": "supplier_ratings sr LEFT JOIN suppliers s ON sr.supplier_id = s.id",
        "search": ("s.supplier_name", "s.supplier_code", "sr.comments"),
    },
    "purchase_agreement": {
        "select": "pa.id, COALESCE(pa.agreement_number, pa.title) AS name, pa.title, pa.status",
        "from": "purchase_agreements pa LEFT JOIN suppliers s ON pa.supplier_id = s.id",
        "search": ("pa.agreement_number", "pa.title", "pa.agreement_type", "pa.status", "s.supplier_name", "s.supplier_code"),
        "branch_alias": "pa",
    },
    "landed_cost": {
        "select": "lc.id, lc.lc_number AS name, lc.reference, lc.status",
        "from": "landed_costs lc",
        "search": ("lc.lc_number", "lc.reference", "lc.description", "lc.status", "lc.notes"),
        "branch_alias": "lc",
    },
    "department": {
        "select": "d.id, d.department_name AS name, d.department_code AS code",
        "from": "departments d",
        "search": ("d.department_name", "d.department_name_en", "d.department_code", "d.description"),
        "branch_alias": "d",
    },
    "position": {
        "select": "ep.id, ep.position_name AS name, ep.position_code AS code",
        "from": "employee_positions ep LEFT JOIN departments d ON ep.department_id = d.id",
        "search": ("ep.position_name", "ep.position_name_en", "ep.position_code", "ep.description", "d.department_name"),
        "branch_alias": "d",
    },
    "attendance_record": {
        "select": "a.id, (e.first_name || ' ' || e.last_name || ' - ' || CAST(a.date AS TEXT)) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, a.status",
        "from": "attendance a LEFT JOIN employees e ON a.employee_id = e.id",
        "search": ("CAST(a.date AS TEXT)", "a.status", "a.notes", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "employee_loan": {
        "select": "el.id, (e.first_name || ' ' || e.last_name || ' - loan') AS name, (e.first_name || ' ' || e.last_name) AS employee_name, el.status",
        "from": "employee_loans el LEFT JOIN employees e ON el.employee_id = e.id",
        "search": ("el.reason", "el.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "el",
    },
    "overtime_request": {
        "select": "ot.id, (e.first_name || ' ' || e.last_name || ' - overtime') AS name, (e.first_name || ' ' || e.last_name) AS employee_name, ot.status",
        "from": "overtime_requests ot LEFT JOIN employees e ON ot.employee_id = e.id",
        "search": ("ot.overtime_type", "ot.reason", "ot.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "ot",
    },
    "performance_review": {
        "select": "pr.id, (e.first_name || ' ' || e.last_name || ' - ' || pr.review_period) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, pr.status",
        "from": "performance_reviews pr LEFT JOIN employees e ON pr.employee_id = e.id",
        "search": ("pr.review_period", "pr.review_type", "pr.status", "pr.strengths", "pr.weaknesses", "pr.goals", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "payroll_entry": {
        "select": "pe.id, (e.first_name || ' ' || e.last_name || ' - ' || pp.name) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, pe.status",
        "from": "payroll_entries pe LEFT JOIN employees e ON pe.employee_id = e.id LEFT JOIN payroll_periods pp ON pe.period_id = pp.id",
        "search": ("pp.name", "pe.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "salary_structure": {
        "select": "ss.id, ss.name, ss.description",
        "from": "salary_structures ss",
        "search": ("ss.name", "ss.name_en", "ss.description", "ss.base_type"),
    },
    "employee_document": {
        "select": "ed.id, (e.first_name || ' ' || e.last_name || ' - ' || ed.document_type) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, ed.status",
        "from": "employee_documents ed LEFT JOIN employees e ON ed.employee_id = e.id",
        "search": ("ed.document_type", "ed.document_number", "ed.issuing_authority", "ed.notes", "ed.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "review_cycle": {
        "select": "rc.id, rc.name, rc.status",
        "from": "review_cycles rc",
        "search": ("rc.name", "rc.status", "CAST(rc.period_start AS TEXT)", "CAST(rc.period_end AS TEXT)"),
    },
    "training_program": {
        "select": "tp.id, tp.name, tp.trainer, tp.status",
        "from": "training_programs tp",
        "search": ("tp.name", "tp.name_en", "tp.description", "tp.trainer", "tp.location", "tp.status"),
    },
    "employee_violation": {
        "select": "ev.id, (e.first_name || ' ' || e.last_name || ' - ' || ev.violation_type) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, ev.status",
        "from": "employee_violations ev LEFT JOIN employees e ON ev.employee_id = e.id",
        "search": ("ev.violation_type", "ev.severity", "ev.description", "ev.action_taken", "ev.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "employee_custody": {
        "select": "ec.id, ec.item_name AS name, (e.first_name || ' ' || e.last_name) AS employee_name, ec.status",
        "from": "employee_custody ec LEFT JOIN employees e ON ec.employee_id = e.id",
        "search": ("ec.item_name", "ec.item_type", "ec.serial_number", "ec.notes", "ec.status", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "job_opening": {
        "select": "jo.id, jo.title AS name, d.department_name, jo.status",
        "from": "job_openings jo LEFT JOIN departments d ON jo.department_id = d.id LEFT JOIN employee_positions ep ON jo.position_id = ep.id",
        "search": ("jo.title", "jo.description", "jo.requirements", "jo.employment_type", "jo.status", "d.department_name", "ep.position_name"),
        "branch_alias": "jo",
    },
    "job_application": {
        "select": "ja.id, ja.applicant_name AS name, jo.title AS opening_title, ja.status",
        "from": "job_applications ja LEFT JOIN job_openings jo ON ja.opening_id = jo.id",
        "search": ("ja.applicant_name", "ja.email", "ja.phone", "ja.stage", "ja.notes", "ja.status", "jo.title"),
        "branch_alias": "jo",
    },
    "leave_carryover": {
        "select": "lc.id, (e.first_name || ' ' || e.last_name || ' - ' || lc.leave_type || ' ' || lc.year::text) AS name, (e.first_name || ' ' || e.last_name) AS employee_name, lc.leave_type",
        "from": "leave_carryover lc LEFT JOIN employees e ON lc.employee_id = e.id",
        "search": ("lc.leave_type", "CAST(lc.year AS TEXT)", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "project_task": {
        "select": "pt.id, pt.task_name AS name, p.project_name, pt.status",
        "from": "project_tasks pt LEFT JOIN projects p ON pt.project_id = p.id",
        "search": ("pt.task_name", "pt.task_name_en", "pt.description", "pt.status", "p.project_name", "p.project_code"),
        "branch_alias": "p",
    },
    "project_timesheet": {
        "select": "pts.id, (p.project_name || ' - ' || CAST(pts.date AS TEXT)) AS name, p.project_name, pts.status",
        "from": "project_timesheets pts LEFT JOIN projects p ON pts.project_id = p.id LEFT JOIN project_tasks pt ON pts.task_id = pt.id LEFT JOIN company_users cu ON pts.employee_id = cu.id",
        "search": ("CAST(pts.date AS TEXT)", "pts.description", "pts.status", "p.project_name", "p.project_code", "pt.task_name", "cu.full_name", "cu.username"),
        "branch_alias": "p",
    },
    "project_risk": {
        "select": "pr.id, pr.title AS name, p.project_name, pr.status",
        "from": "project_risks pr LEFT JOIN projects p ON pr.project_id = p.id",
        "search": ("pr.title", "pr.description", "pr.probability", "pr.impact", "pr.status", "pr.mitigation_plan", "p.project_name", "p.project_code"),
        "branch_alias": "p",
    },
    "resource_allocation": {
        "select": "ra.id, (p.project_name || ' - ' || COALESCE(e.first_name || ' ' || e.last_name, ra.role, 'resource')) AS name, p.project_name, ra.role",
        "from": "resource_allocations ra LEFT JOIN projects p ON ra.project_id = p.id LEFT JOIN employees e ON ra.employee_id = e.id",
        "search": ("ra.role", "p.project_name", "p.project_code", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "p",
    },
    "task_dependency": {
        "select": "td.id, (pt.task_name || ' -> ' || dep.task_name) AS name, p.project_name, td.dependency_type",
        "from": "task_dependencies td LEFT JOIN projects p ON td.project_id = p.id LEFT JOIN project_tasks pt ON td.task_id = pt.id LEFT JOIN project_tasks dep ON td.depends_on_task_id = dep.id",
        "search": ("td.dependency_type", "pt.task_name", "dep.task_name", "p.project_name", "p.project_code"),
        "branch_alias": "p",
    },
    "work_center": {
        "select": "wc.id, wc.name, wc.code, wc.status",
        "from": "work_centers wc",
        "search": ("wc.name", "wc.code", "wc.location", "wc.status"),
        "base_where": ("COALESCE(wc.is_deleted, FALSE) = FALSE",),
        "cost_center": ("wc", "cost_center_id"),
    },
    "manufacturing_route": {
        "select": "mr.id, mr.name, p.product_name",
        "from": "manufacturing_routes mr LEFT JOIN products p ON mr.product_id = p.id",
        "search": ("mr.name", "mr.description", "p.product_name", "p.product_code", "p.sku"),
        "base_where": ("COALESCE(mr.is_deleted, FALSE) = FALSE",),
    },
    "manufacturing_bom": {
        "select": "bom.id, COALESCE(bom.name, bom.code) AS name, bom.code, p.product_name",
        "from": "bill_of_materials bom LEFT JOIN products p ON bom.product_id = p.id",
        "search": ("bom.name", "bom.code", "bom.notes", "p.product_name", "p.product_code", "p.sku"),
        "base_where": ("COALESCE(bom.is_deleted, FALSE) = FALSE",),
    },
    "manufacturing_equipment": {
        "select": "me.id, me.name, me.code, me.status",
        "from": "manufacturing_equipment me LEFT JOIN work_centers wc ON me.work_center_id = wc.id",
        "search": ("me.name", "me.code", "me.status", "me.notes", "wc.name", "wc.code"),
        "base_where": ("COALESCE(me.is_deleted, FALSE) = FALSE",),
    },
    "mrp_plan": {
        "select": "mp.id, mp.plan_name AS name, mp.status",
        "from": "mrp_plans mp LEFT JOIN production_orders po ON mp.production_order_id = po.id",
        "search": ("mp.plan_name", "mp.status", "mp.notes", "po.order_number"),
    },
    "capacity_plan": {
        "select": "cp.id, (wc.name || ' - ' || CAST(cp.plan_date AS TEXT)) AS name, wc.name AS work_center_name",
        "from": "capacity_plans cp LEFT JOIN work_centers wc ON cp.work_center_id = wc.id",
        "search": ("CAST(cp.plan_date AS TEXT)", "cp.notes", "wc.name", "wc.code"),
        "base_where": ("COALESCE(cp.is_deleted, FALSE) = FALSE",),
    },
    "shop_floor_log": {
        "select": "sfl.id, COALESCE(po.order_number, 'Work order #' || sfl.work_order_id::text) AS name, po.order_number, sfl.status",
        "from": "shop_floor_logs sfl LEFT JOIN production_orders po ON sfl.work_order_id = po.id LEFT JOIN employees e ON sfl.operator_id = e.id",
        "search": ("po.order_number", "sfl.status", "sfl.notes", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "po",
    },
    "asset_category": {
        "select": "ac.id, ac.category_name AS name, ac.category_code AS code",
        "from": "asset_categories ac",
        "search": ("ac.category_name", "ac.category_name_en", "ac.category_code", "ac.description"),
    },
    "asset_transfer": {
        "select": "at.id, a.name, a.code, at.status",
        "from": "asset_transfers at LEFT JOIN assets a ON at.asset_id = a.id",
        "search": ("a.name", "a.code", "at.reason", "at.notes", "at.status"),
        "branch_alias": "a",
    },
    "asset_disposal": {
        "select": "ad.id, a.name, a.code, ad.status",
        "from": "asset_disposals ad LEFT JOIN assets a ON ad.asset_id = a.id",
        "search": ("a.name", "a.code", "ad.disposal_method", "ad.disposal_reason", "ad.buyer_name", "ad.notes", "ad.status"),
        "branch_alias": "a",
    },
    "asset_revaluation": {
        "select": "ar.id, a.name, a.code, ar.reason",
        "from": "asset_revaluations ar LEFT JOIN assets a ON ar.asset_id = a.id",
        "search": ("a.name", "a.code", "ar.reason"),
        "branch_alias": "a",
    },
    "asset_insurance": {
        "select": "ai.id, COALESCE(ai.policy_number, a.name) AS name, a.name AS asset_name, ai.status",
        "from": "asset_insurance ai LEFT JOIN assets a ON ai.asset_id = a.id",
        "search": ("ai.policy_number", "ai.insurer", "ai.coverage_type", "ai.notes", "ai.status", "a.name", "a.code"),
        "branch_alias": "a",
    },
    "asset_maintenance": {
        "select": "am.id, (a.name || ' - ' || am.maintenance_type) AS name, a.name AS asset_name, am.status",
        "from": "asset_maintenance am LEFT JOIN assets a ON am.asset_id = a.id",
        "search": ("am.maintenance_type", "am.description", "am.vendor", "am.status", "am.notes", "a.name", "a.code"),
        "branch_alias": "a",
    },
    "lease_contract": {
        "select": "lc.id, lc.description AS name, lc.lessor_name, lc.status",
        "from": "lease_contracts lc LEFT JOIN assets a ON lc.asset_id = a.id",
        "search": ("lc.description", "lc.lessor_name", "lc.lease_type", "lc.status", "a.name", "a.code"),
        "branch_alias": "a",
    },
    "asset_impairment": {
        "select": "ai.id, (a.name || ' - impairment') AS name, a.name AS asset_name, ai.reason",
        "from": "asset_impairments ai LEFT JOIN assets a ON ai.asset_id = a.id",
        "search": ("ai.reason", "a.name", "a.code", "CAST(ai.test_date AS TEXT)"),
        "branch_alias": "a",
    },
    "tax_calendar_event": {
        "select": "tc.id, tc.title AS name, tc.tax_type, tc.status",
        "from": "tax_calendar tc",
        "search": ("tc.title", "tc.tax_type", "tc.notes", "tc.status", "CAST(tc.due_date AS TEXT)"),
        "branch_alias": "tc",
    },
    "tax_rate": {
        "select": "tr.id, tr.tax_name AS name, tr.tax_code AS code, tr.rate_type",
        "from": "tax_rates tr",
        "search": ("tr.tax_name", "tr.tax_name_en", "tr.tax_code", "tr.rate_type", "tr.country_code", "tr.description"),
    },
    "tax_classification": {
        "select": "tc.id, tc.name_ar AS name, tc.code, tc.name_en",
        "from": "tax_classifications tc",
        "search": ("tc.code", "tc.name_ar", "tc.name_en", "tc.description"),
    },
    "tax_group": {
        "select": "tg.id, tg.group_name AS name, tg.group_code AS code",
        "from": "tax_groups tg",
        "search": ("tg.group_name", "tg.group_name_en", "tg.group_code", "tg.description"),
    },
    "tax_payment": {
        "select": "tp.id, COALESCE(tp.payment_number, tp.reference) AS name, tp.reference, tp.status",
        "from": "tax_payments tp",
        "search": ("tp.payment_number", "tp.reference", "tp.payment_method", "tp.status", "tp.notes"),
        "branch_alias": "tp",
    },
    "tax_regime": {
        "select": "tr.id, tr.name_en AS name, tr.country_code, tr.tax_type",
        "from": "tax_regimes tr",
        "search": ("tr.country_code", "tr.tax_type", "tr.name_ar", "tr.name_en", "tr.applies_to", "tr.filing_frequency"),
    },
    "wht_rate": {
        "select": "wr.id, wr.name, wr.name_ar, wr.category",
        "from": "wht_rates wr",
        "search": ("wr.name", "wr.name_ar", "wr.country_code", "wr.category", "wr.description"),
    },
    "wht_transaction": {
        "select": "wt.id, COALESCE(wt.certificate_number, 'WHT #' || wt.id::text) AS name, wt.status",
        "from": "wht_transactions wt LEFT JOIN suppliers s ON wt.supplier_id = s.id",
        "search": ("wt.certificate_number", "wt.status", "s.supplier_name", "s.supplier_code", "CAST(wt.period_date AS TEXT)"),
        "branch_alias": "wt",
    },
    "zakat_calculation": {
        "select": "zc.id, ('Zakat ' || zc.fiscal_year::text) AS name, zc.status",
        "from": "zakat_calculations zc",
        "search": ("CAST(zc.fiscal_year AS TEXT)", "zc.method", "zc.status", "zc.notes"),
        "branch_alias": "zc",
    },
    "pos_session": {
        "select": "ps.id, ps.session_code AS name, ps.status",
        "from": "pos_sessions ps",
        "search": ("ps.session_code", "ps.status", "ps.notes"),
        "branch_alias": "ps",
        "warehouse_columns": (("ps", "warehouse_id"),),
    },
    "pos_return": {
        "select": "pr.id, ('Return #' || pr.id::text) AS name, po.order_number, pr.refund_method",
        "from": "pos_returns pr LEFT JOIN pos_orders po ON pr.original_order_id = po.id",
        "search": ("po.order_number", "pr.refund_method", "pr.notes"),
        "branch_alias": "po",
        "warehouse_columns": (("po", "warehouse_id"),),
    },
    "pos_promotion": {
        "select": "pp.id, pp.name, pp.coupon_code, CASE WHEN pp.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "pos_promotions pp",
        "search": ("pp.name", "pp.promotion_type", "pp.coupon_code", "pp.applicable_products", "pp.applicable_categories"),
        "branch_alias": "pp",
    },
    "pos_loyalty_program": {
        "select": "plp.id, plp.name, CASE WHEN plp.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "pos_loyalty_programs plp",
        "search": ("plp.name",),
        "branch_alias": "plp",
    },
    "pos_table": {
        "select": "pt.id, COALESCE(pt.table_name, pt.table_number) AS name, pt.table_number AS code, pt.status",
        "from": "pos_tables pt",
        "search": ("pt.table_number", "pt.table_name", "pt.floor", "pt.status", "pt.shape"),
        "branch_alias": "pt",
    },
    "pos_kitchen_order": {
        "select": "pko.id, COALESCE(pko.product_name, po.order_number) AS name, pko.station, pko.status",
        "from": "pos_kitchen_orders pko LEFT JOIN pos_orders po ON pko.order_id = po.id",
        "search": ("pko.product_name", "pko.notes", "pko.station", "pko.status", "po.order_number"),
        "branch_alias": "pko",
    },
    "support_ticket": {
        "select": "st.id, COALESCE(st.ticket_number, st.subject) AS name, st.subject, p.name AS customer_name, st.status",
        "from": "support_tickets st LEFT JOIN parties p ON st.customer_id = p.id",
        "search": ("st.ticket_number", "st.subject", "st.description", "st.contact_name", "st.contact_email", "st.contact_phone", "st.status", "st.priority", "st.category", "p.name"),
        "branch_alias": "st",
    },
    "marketing_campaign": {
        "select": "mc.id, mc.name, mc.campaign_type, mc.status",
        "from": "marketing_campaigns mc",
        "search": ("mc.name", "mc.campaign_type", "mc.status", "mc.target_audience", "mc.description", "mc.subject"),
        "branch_alias": "mc",
    },
    "crm_contact": {
        "select": "cc.id, (cc.first_name || COALESCE(' ' || cc.last_name, '')) AS name, p.name AS customer_name, cc.job_title",
        "from": "crm_contacts cc LEFT JOIN parties p ON cc.customer_id = p.id",
        "search": ("cc.first_name", "cc.last_name", "(cc.first_name || ' ' || COALESCE(cc.last_name, ''))", "cc.job_title", "cc.email", "cc.phone", "cc.mobile", "cc.department", "cc.notes", "p.name"),
    },
    "crm_segment": {
        "select": "cs.id, cs.name, cs.description",
        "from": "crm_customer_segments cs",
        "search": ("cs.name", "cs.description"),
    },
    "crm_knowledge_base": {
        "select": "kb.id, kb.title AS name, kb.category, kb.tags",
        "from": "crm_knowledge_base kb",
        "search": ("kb.title", "kb.category", "kb.content", "kb.tags"),
    },
    "crm_sales_forecast": {
        "select": "sf.id, (sf.period || ' - ' || sf.forecast_type) AS name, sf.period, sf.forecast_type",
        "from": "crm_sales_forecasts sf",
        "search": ("sf.period", "sf.forecast_type", "sf.method"),
        "branch_alias": "sf",
    },
    "approval_workflow": {
        "select": "aw.id, aw.name, aw.document_type, CASE WHEN aw.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "approval_workflows aw",
        "search": ("aw.name", "aw.document_type", "aw.description"),
    },
    "approval_request": {
        "select": "ar.id, (ar.document_type || ' #' || ar.document_id::text) AS name, ar.document_type, ar.status",
        "from": "approval_requests ar",
        "search": ("ar.document_type", "ar.description", "ar.status", "CAST(ar.document_id AS TEXT)"),
    },
    "cashflow_forecast": {
        "select": "cf.id, cf.name, cf.mode",
        "from": "cashflow_forecasts cf",
        "search": ("cf.name", "cf.mode", "CAST(cf.forecast_date AS TEXT)"),
        "base_where": ("cf.deleted_at IS NULL",),
    },
    "subscription_plan": {
        "select": "sp.id, sp.name, sp.billing_frequency",
        "from": "subscription_plans sp",
        "search": ("sp.name", "sp.description", "sp.billing_frequency", "sp.currency"),
        "base_where": ("COALESCE(sp.is_deleted, FALSE) = FALSE",),
    },
    "subscription_enrollment": {
        "select": "se.id, (p.name || ' - ' || sp.name) AS name, p.name AS customer_name, se.status",
        "from": "subscription_enrollments se LEFT JOIN parties p ON se.customer_id = p.id LEFT JOIN subscription_plans sp ON se.plan_id = sp.id",
        "search": ("p.name", "sp.name", "se.status", "se.cancellation_reason", "CAST(se.next_billing_date AS TEXT)"),
        "base_where": ("COALESCE(se.is_deleted, FALSE) = FALSE",),
    },
    "revenue_schedule": {
        "select": "rrs.id, COALESCE(i.invoice_number, c.contract_number, 'Revenue schedule #' || rrs.id::text) AS name, rrs.method, rrs.status",
        "from": "revenue_recognition_schedules rrs LEFT JOIN invoices i ON rrs.invoice_id = i.id LEFT JOIN contracts c ON rrs.contract_id = c.id",
        "search": ("i.invoice_number", "c.contract_number", "rrs.method", "rrs.status"),
    },
    "intercompany_entity": {
        "select": "eg.id, eg.name, eg.company_id",
        "from": "entity_groups eg",
        "search": ("eg.name", "eg.company_id", "eg.group_currency"),
        "base_where": ("COALESCE(eg.is_deleted, FALSE) = FALSE",),
        "branch_alias": "eg",
    },
    "intercompany_transaction": {
        "select": "ict.id, COALESCE(ict.reference_document, ict.transaction_type) AS name, ict.transaction_type, ict.elimination_status AS status",
        "from": "intercompany_transactions_v2 ict LEFT JOIN entity_groups src ON ict.source_entity_id = src.id LEFT JOIN entity_groups dst ON ict.target_entity_id = dst.id",
        "search": ("ict.transaction_type", "ict.reference_document", "ict.elimination_status", "src.name", "dst.name"),
        "base_where": ("COALESCE(ict.is_deleted, FALSE) = FALSE",),
    },
    "branch": {
        "select": "b.id, b.branch_name AS name, b.branch_code AS code",
        "from": "branches b",
        "search": ("b.branch_name", "b.branch_name_en", "b.branch_code", "b.branch_type", "b.city", "b.country", "b.email", "b.phone"),
        "branch_alias": "b",
    },
    "role": {
        "select": "r.id, r.role_name AS name, r.role_name_ar",
        "from": "roles r",
        "search": ("r.role_name", "r.role_name_ar", "r.description"),
    },
    "audit_log": {
        "select": "al.id, (al.action || ' - ' || COALESCE(al.resource_type, 'resource')) AS name, al.username, al.resource_type",
        "from": "audit_logs al",
        "search": ("al.username", "al.action", "al.resource_type", "al.resource_id"),
        "branch_alias": "al",
    },
    "security_event": {
        "select": "se.id, se.event_type AS name, se.severity",
        "from": "security_events se",
        "search": ("se.event_type", "se.severity", "CAST(se.user_id AS TEXT)", "se.ip_address"),
    },
    "email_template": {
        "select": "et.id, COALESCE(et.template_name, et.code) AS name, et.code, et.locale",
        "from": "email_templates et",
        "search": ("et.template_name", "et.code", "et.locale", "et.subject"),
    },
    "print_template": {
        "select": "pt.id, pt.name, pt.template_type",
        "from": "print_templates pt",
        "search": ("pt.name", "pt.template_type", "pt.paper_size", "pt.orientation"),
    },
    "webhook": {
        "select": "w.id, w.name, CASE WHEN w.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "webhooks w",
        "search": ("w.name", "CAST(w.events AS TEXT)"),
    },
    "sso_configuration": {
        "select": "sso.id, sso.display_name AS name, sso.provider_type, CASE WHEN sso.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "sso_configurations sso",
        "search": ("sso.display_name", "sso.provider_type"),
        "base_where": ("COALESCE(sso.is_deleted, FALSE) = FALSE",),
    },
    "integration_key": {
        "select": "ik.id, (ik.integration_type || ' - ' || ik.provider || ' - ' || ik.key_name) AS name, ik.key_status AS status",
        "from": "integration_keys ik",
        "search": ("ik.integration_type", "ik.provider", "ik.key_name", "ik.key_status"),
        "branch_alias": "ik",
    },
    "integration_dlq": {
        "select": "dlq.id, (dlq.queue_type || ' - ' || COALESCE(dlq.provider, 'provider')) AS name, dlq.final_status AS status",
        "from": "integration_dlq dlq",
        "search": ("dlq.queue_type", "dlq.provider", "dlq.final_status", "dlq.reason"),
    },
    "notification_queue_item": {
        "select": "nq.id, (nq.event_type || ' - ' || nq.channel) AS name, nq.recipient, nq.state AS status",
        "from": "notifications_queue nq",
        "search": ("nq.event_type", "nq.channel", "nq.recipient", "nq.template_code", "nq.state"),
    },
    "company_setting": {
        "select": "cs.id, cs.setting_key AS name",
        "from": "company_settings cs",
        "search": ("cs.setting_key",),
    },
    "sales_commission": {
        "select": "sc.id, (sc.salesperson_name || ' - ' || COALESCE(sc.invoice_number, 'Commission #' || sc.id::text)) AS name, sc.salesperson_name, sc.invoice_number, sc.status",
        "from": "sales_commissions sc LEFT JOIN employees e ON sc.salesperson_id = e.id",
        "search": ("sc.salesperson_name", "sc.invoice_number", "sc.status", "CAST(sc.invoice_date AS TEXT)", "e.employee_code", "e.first_name", "e.last_name"),
        "branch_alias": "sc",
    },
    "cpq_quote": {
        "select": "cq.id, ('CPQ Quote #' || cq.id::text) AS name, p.name AS customer_name, cq.status",
        "from": "cpq_quotes cq LEFT JOIN parties p ON cq.customer_id = p.id",
        "search": ("cq.status", "CAST(cq.valid_until AS TEXT)", "p.name"),
    },
    "cpq_pricing_rule": {
        "select": "cpr.id, (cpr.rule_type || ' - Discount ' || COALESCE(CAST(cpr.discount_percent AS TEXT), '') || '%') AS name, cpr.rule_type",
        "from": "cpq_pricing_rules cpr LEFT JOIN product_configurations pc ON cpr.configuration_id = pc.id",
        "search": ("cpr.rule_type", "CAST(cpr.discount_percent AS TEXT)", "CAST(cpr.discount_amount AS TEXT)"),
    },
    "demand_forecast": {
        "select": "df.id, (p.product_name || ' - ' || df.forecast_method || ' - ' || CAST(df.generated_date AS TEXT)) AS name, p.product_name, df.forecast_method",
        "from": "demand_forecasts df LEFT JOIN products p ON df.product_id = p.id",
        "search": ("df.forecast_method", "CAST(df.generated_date AS TEXT)", "p.product_name", "p.product_code", "p.sku"),
        "warehouse_columns": (("df", "warehouse_id"),),
    },
    "expense_policy": {
        "select": "ep.id, ep.name, d.department_name, CASE WHEN ep.is_active THEN 'active' ELSE 'inactive' END AS status",
        "from": "expense_policies ep LEFT JOIN departments d ON ep.department_id = d.id",
        "search": ("ep.name", "ep.expense_type", "d.department_name"),
        "base_where": ("COALESCE(ep.is_deleted, FALSE) = FALSE",),
        "branch_alias": "d",
    },
    "bank_import_batch": {
        "select": "bib.id, bib.file_name AS name, ta.name AS bank_account_name, bib.status",
        "from": "bank_import_batches bib LEFT JOIN treasury_accounts ta ON bib.bank_account_id = ta.id",
        "search": ("bib.file_name", "bib.status", "ta.name", "ta.account_number"),
    },
    "match_tolerance": {
        "select": "mt.id, mt.name, CASE WHEN COALESCE(mt.is_deleted, FALSE) THEN 'deleted' ELSE 'active' END AS status",
        "from": "match_tolerances mt",
        "search": ("mt.name",),
        "base_where": ("COALESCE(mt.is_deleted, FALSE) = FALSE",),
    },
    "eos_provision": {
        "select": "eop.id, (e.first_name || ' ' || e.last_name || ' - ' || CAST(eop.period_end AS TEXT)) AS name, (e.first_name || ' ' || e.last_name) AS employee_name",
        "from": "eos_provisions eop LEFT JOIN employees e ON eop.employee_id = e.id",
        "search": ("CAST(eop.period_end AS TEXT)", "e.employee_code", "e.first_name", "e.last_name", "(e.first_name || ' ' || e.last_name)"),
        "branch_alias": "e",
    },
    "alert_rule": {
        "select": "ar.id, ar.name, ar.rule_type, CASE WHEN ar.enabled THEN 'enabled' ELSE 'disabled' END AS status",
        "from": "alert_rules ar",
        "search": ("ar.name", "ar.rule_type"),
    },
}


@router.get("/registry")
async def get_search_registry(current_user: Any = Depends(get_current_user)):
    """Return the search entity registry filtered by the user's permissions."""
    return {"entities": get_registry_for_user(_user_permissions(current_user), _enabled_modules(current_user))}


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=256),
    entities: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: Any = Depends(get_current_user),
):
    """Cross-entity search endpoint with query logging and strict tenant isolation."""
    start = time.monotonic()
    tenant_id = _tenant_id(current_user)
    allowed_branches = _allowed_branches(current_user)
    branch_params = {"allowed_branches": allowed_branches} if allowed_branches else {}
    branch_clause = "AND (branch_id IS NULL OR branch_id = ANY(:allowed_branches))" if allowed_branches else ""
    invoice_branch_clause = "AND (i.branch_id IS NULL OR i.branch_id = ANY(:allowed_branches))" if allowed_branches else ""

    # Filter the registry based on permissions
    user_registry = get_registry_for_user(_user_permissions(current_user), _enabled_modules(current_user))
    allowed_entity_codes = {e["entity_code"] for e in user_registry}
    registry_by_code = {e["entity_code"]: e for e in user_registry}

    # Optional filtering by entities passed from request
    target_entities = allowed_entity_codes
    if entities:
        req_entities = {e.strip() for e in entities.split(",") if e.strip()}
        target_entities = target_entities.intersection(req_entities)

    results = []
    entity_hits: dict[str, int] = {}

    # Search term for SQL LIKE
    search_param = f"%{q}%"

    # Query database under the user's specific company/tenant
    with get_tenant_db(tenant_id) as db:
        warehouse_filter, warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "inv")
        cost_center_filter, cost_center_params = build_cost_center_filter(current_user, db, "cost_center_id", "jl")

        for entity_code in target_entities:
            items = []
            try:
                configured = CONFIGURED_SEARCH_ENTITIES.get(entity_code)
                if configured:
                    items = _search_configured_entity(
                        db,
                        config=configured,
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                    )

                elif entity_code == "customer":
                    query_str = """
                        SELECT id, customer_name AS name, customer_code AS code
                        FROM customers
                        WHERE (
                            customer_name ILIKE :q
                            OR email ILIKE :q
                            OR phone ILIKE :q
                            OR mobile ILIKE :q
                            OR customer_code ILIKE :q
                        )
                        {branch_clause}
                        LIMIT :limit
                    """.format(branch_clause=branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code} for r in rows]

                elif entity_code == "supplier":
                    query_str = """
                        SELECT id, supplier_name AS name, supplier_code AS code
                        FROM suppliers
                        WHERE (
                            supplier_name ILIKE :q
                            OR email ILIKE :q
                            OR phone ILIKE :q
                            OR mobile ILIKE :q
                            OR supplier_code ILIKE :q
                        )
                        {branch_clause}
                        LIMIT :limit
                    """.format(branch_clause=branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code} for r in rows]

                elif entity_code == "invoice":
                    query_str = """
                        SELECT i.id, i.invoice_number AS name, p.name AS customer_name
                        FROM invoices i
                        LEFT JOIN parties p ON i.party_id = p.id
                        WHERE i.invoice_type = 'sales'
                          AND (
                            i.invoice_number ILIKE :q
                            OR p.name ILIKE :q
                          )
                        {invoice_branch_clause}
                        LIMIT :limit
                    """.format(invoice_branch_clause=invoice_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name} for r in rows]

                elif entity_code == "sales_order":
                    so_branch_clause = "AND (so.branch_id IS NULL OR so.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    so_warehouse_filter, so_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "so")
                    query_str = """
                        SELECT so.id, so.so_number AS name, p.name AS customer_name, so.status
                        FROM sales_orders so
                        LEFT JOIN parties p ON so.party_id = p.id
                        WHERE (
                            so.so_number ILIKE :q
                            OR p.name ILIKE :q
                            OR so.status ILIKE :q
                            OR so.notes ILIKE :q
                        )
                        {so_branch_clause}
                        {so_warehouse_filter}
                        LIMIT :limit
                    """.format(so_branch_clause=so_branch_clause, so_warehouse_filter=so_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **so_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "quotation":
                    sq_branch_clause = "AND (sq.branch_id IS NULL OR sq.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT sq.id, sq.sq_number AS name, p.name AS customer_name, sq.status
                        FROM sales_quotations sq
                        LEFT JOIN parties p ON sq.party_id = p.id
                        WHERE (
                            sq.sq_number ILIKE :q
                            OR p.name ILIKE :q
                            OR sq.status ILIKE :q
                            OR sq.notes ILIKE :q
                        )
                        {sq_branch_clause}
                        LIMIT :limit
                    """.format(sq_branch_clause=sq_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "sales_return":
                    sr_branch_clause = _branch_clause("sr", allowed_branches)
                    sr_warehouse_filter, sr_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "sr")
                    query_str = """
                        SELECT sr.id, sr.return_number AS name, p.name AS customer_name, sr.status
                        FROM sales_returns sr
                        LEFT JOIN parties p ON sr.party_id = p.id
                        WHERE (
                            sr.return_number ILIKE :q
                            OR p.name ILIKE :q
                            OR sr.status ILIKE :q
                            OR sr.notes ILIKE :q
                        )
                        {sr_branch_clause}
                        {sr_warehouse_filter}
                        LIMIT :limit
                    """.format(sr_branch_clause=sr_branch_clause, sr_warehouse_filter=sr_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **sr_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "sales_credit_note":
                    items = _search_invoices_by_type(
                        db,
                        invoice_type="sales_credit_note",
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                        party_key="customer_name",
                    )

                elif entity_code == "sales_debit_note":
                    items = _search_invoices_by_type(
                        db,
                        invoice_type="sales_debit_note",
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                        party_key="customer_name",
                    )

                elif entity_code == "customer_receipt":
                    pv_branch_clause = _branch_clause("pv", allowed_branches)
                    query_str = """
                        SELECT pv.id, pv.voucher_number AS name, p.name AS customer_name, pv.status
                        FROM payment_vouchers pv
                        LEFT JOIN parties p ON pv.party_id = p.id
                        WHERE pv.voucher_type = 'receipt'
                          AND (
                            pv.voucher_number ILIKE :q
                            OR p.name ILIKE :q
                            OR pv.reference ILIKE :q
                            OR pv.check_number ILIKE :q
                            OR pv.notes ILIKE :q
                          )
                        {pv_branch_clause}
                        LIMIT :limit
                    """.format(pv_branch_clause=pv_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "delivery_order":
                    do_branch_clause = "AND (d.branch_id IS NULL OR d.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    do_warehouse_filter, do_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "d")
                    query_str = """
                        SELECT d.id, d.delivery_number AS name, p.name AS customer_name, d.status, d.tracking_number
                        FROM delivery_orders d
                        LEFT JOIN parties p ON d.party_id = p.id
                        WHERE (
                            d.delivery_number ILIKE :q
                            OR d.tracking_number ILIKE :q
                            OR d.driver_name ILIKE :q
                            OR p.name ILIKE :q
                        )
                        {do_branch_clause}
                        {do_warehouse_filter}
                        LIMIT :limit
                    """.format(do_branch_clause=do_branch_clause, do_warehouse_filter=do_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **do_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status, "tracking_number": r.tracking_number} for r in rows]

                elif entity_code == "contract":
                    contract_branch_clause = "AND (c.branch_id IS NULL OR c.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT c.id, c.contract_number AS name, p.name AS party_name, c.status, c.contract_type
                        FROM contracts c
                        LEFT JOIN parties p ON c.party_id = p.id
                        WHERE (
                            c.contract_number ILIKE :q
                            OR c.contract_type ILIKE :q
                            OR c.status ILIKE :q
                            OR c.notes ILIKE :q
                            OR p.name ILIKE :q
                        )
                        {contract_branch_clause}
                        LIMIT :limit
                    """.format(contract_branch_clause=contract_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "party_name": r.party_name, "status": r.status, "contract_type": r.contract_type} for r in rows]

                elif entity_code == "product":
                    product_branch_clause = ""
                    product_scope_clause = ""
                    product_params = {"q": search_param, "limit": limit, **branch_params, **warehouse_params}
                    if allowed_branches or warehouse_filter:
                        product_scope_clause = """
                            AND EXISTS (
                                SELECT 1
                                FROM inventory inv
                                LEFT JOIN warehouses w ON w.id = inv.warehouse_id
                                WHERE inv.product_id = p.id
                                {product_branch_clause}
                                {warehouse_filter}
                            )
                        """
                        product_branch_clause = (
                            "AND (w.branch_id IS NULL OR w.branch_id = ANY(:allowed_branches))"
                            if allowed_branches else ""
                        )

                    query_str = """
                        SELECT p.id, p.product_name AS name, p.sku, p.barcode, p.product_code AS code
                        FROM products p
                        WHERE (
                            p.product_name ILIKE :q
                            OR p.sku ILIKE :q
                            OR p.barcode ILIKE :q
                            OR p.product_code ILIKE :q
                        )
                        {product_scope_clause}
                        LIMIT :limit
                    """.format(
                        product_scope_clause=product_scope_clause.format(
                            product_branch_clause=product_branch_clause,
                            warehouse_filter=warehouse_filter,
                        ) if product_scope_clause else ""
                    )
                    rows = db.execute(text(query_str), product_params).fetchall()
                    items = [{"id": r.id, "name": r.name, "sku": r.sku, "barcode": r.barcode, "code": r.code} for r in rows]

                elif entity_code == "warehouse":
                    wh_branch_clause = "AND (w.branch_id IS NULL OR w.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    wh_filter, wh_params = build_warehouse_filter(current_user, db, "id", "w")
                    query_str = """
                        SELECT w.id, w.warehouse_name AS name, w.warehouse_code AS code, w.location
                        FROM warehouses w
                        WHERE (
                            w.warehouse_name ILIKE :q
                            OR w.warehouse_name_en ILIKE :q
                            OR w.warehouse_code ILIKE :q
                            OR w.location ILIKE :q
                        )
                        {wh_branch_clause}
                        {wh_filter}
                        LIMIT :limit
                    """.format(wh_branch_clause=wh_branch_clause, wh_filter=wh_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **wh_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code, "location": r.location} for r in rows]

                elif entity_code == "journal_entry":
                    journal_cost_center_clause = ""
                    journal_params = {"q": search_param, "limit": limit, **branch_params, **cost_center_params}
                    if cost_center_filter:
                        journal_cost_center_clause = """
                            AND EXISTS (
                                SELECT 1
                                FROM journal_lines jl
                                WHERE jl.journal_entry_id = journal_entries.id
                                {cost_center_filter}
                            )
                        """.format(cost_center_filter=cost_center_filter)

                    query_str = """
                        SELECT id, entry_number AS name, reference, description
                        FROM journal_entries
                        WHERE (
                            entry_number ILIKE :q
                            OR reference ILIKE :q
                            OR description ILIKE :q
                        )
                        {branch_clause}
                        {journal_cost_center_clause}
                        LIMIT :limit
                    """.format(branch_clause=branch_clause, journal_cost_center_clause=journal_cost_center_clause)
                    rows = db.execute(text(query_str), journal_params).fetchall()
                    items = [{"id": r.id, "name": r.name, "reference": r.reference, "description": r.description} for r in rows]

                elif entity_code == "account":
                    query_str = """
                        SELECT id, name, account_code AS code
                        FROM accounts
                        WHERE account_code ILIKE :q
                           OR name ILIKE :q
                        LIMIT :limit
                    """
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code} for r in rows]

                elif entity_code == "treasury_account":
                    ta_branch_clause = "AND (ta.branch_id IS NULL OR ta.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT ta.id, ta.name, ta.account_number AS code, ta.bank_name, ta.account_type
                        FROM treasury_accounts ta
                        WHERE (
                            ta.name ILIKE :q
                            OR ta.name_en ILIKE :q
                            OR ta.account_number ILIKE :q
                            OR ta.bank_name ILIKE :q
                            OR ta.iban ILIKE :q
                        )
                        {ta_branch_clause}
                        LIMIT :limit
                    """.format(ta_branch_clause=ta_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code, "bank_name": r.bank_name, "account_type": r.account_type} for r in rows]

                elif entity_code == "treasury_transaction":
                    tt_branch_clause = _branch_clause("tt", allowed_branches)
                    query_str = """
                        SELECT tt.id, tt.transaction_number AS name, tt.reference_number, tt.transaction_type, tt.status
                        FROM treasury_transactions tt
                        WHERE (
                            tt.transaction_number ILIKE :q
                            OR tt.reference_number ILIKE :q
                            OR tt.transaction_type ILIKE :q
                            OR tt.status ILIKE :q
                            OR tt.description ILIKE :q
                        )
                        {tt_branch_clause}
                        LIMIT :limit
                    """.format(tt_branch_clause=tt_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "reference_number": r.reference_number, "transaction_type": r.transaction_type, "status": r.status} for r in rows]

                elif entity_code == "bank_reconciliation":
                    br_branch_clause = _branch_clause("br", allowed_branches)
                    query_str = """
                        SELECT br.id,
                               ('Reconciliation ' || br.id::text) AS name,
                               ta.name AS account_name,
                               br.status
                        FROM bank_reconciliations br
                        LEFT JOIN treasury_accounts ta ON br.treasury_account_id = ta.id
                        WHERE (
                            br.status ILIKE :q
                            OR br.notes ILIKE :q
                            OR ta.name ILIKE :q
                            OR ta.account_number ILIKE :q
                            OR CAST(br.statement_date AS TEXT) ILIKE :q
                        )
                        {br_branch_clause}
                        LIMIT :limit
                    """.format(br_branch_clause=br_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "account_name": r.account_name, "status": r.status} for r in rows]

                elif entity_code == "check_receivable":
                    cr_branch_clause = "AND (cr.branch_id IS NULL OR cr.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT cr.id, cr.check_number AS name, cr.drawer_name, cr.bank_name, cr.status
                        FROM checks_receivable cr
                        WHERE (
                            cr.check_number ILIKE :q
                            OR cr.drawer_name ILIKE :q
                            OR cr.bank_name ILIKE :q
                            OR cr.branch_name ILIKE :q
                            OR cr.notes ILIKE :q
                        )
                        {cr_branch_clause}
                        LIMIT :limit
                    """.format(cr_branch_clause=cr_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "drawer_name": r.drawer_name, "bank_name": r.bank_name, "status": r.status} for r in rows]

                elif entity_code == "check_payable":
                    cp_branch_clause = "AND (cp.branch_id IS NULL OR cp.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT cp.id, cp.check_number AS name, cp.beneficiary_name, cp.bank_name, cp.status
                        FROM checks_payable cp
                        WHERE (
                            cp.check_number ILIKE :q
                            OR cp.beneficiary_name ILIKE :q
                            OR cp.bank_name ILIKE :q
                            OR cp.branch_name ILIKE :q
                            OR cp.notes ILIKE :q
                        )
                        {cp_branch_clause}
                        LIMIT :limit
                    """.format(cp_branch_clause=cp_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "beneficiary_name": r.beneficiary_name, "bank_name": r.bank_name, "status": r.status} for r in rows]

                elif entity_code == "note_receivable":
                    nr_branch_clause = _branch_clause("nr", allowed_branches)
                    query_str = """
                        SELECT nr.id, nr.note_number AS name, nr.drawer_name, nr.bank_name, nr.status
                        FROM notes_receivable nr
                        WHERE (
                            nr.note_number ILIKE :q
                            OR nr.drawer_name ILIKE :q
                            OR nr.bank_name ILIKE :q
                            OR nr.notes ILIKE :q
                        )
                        {nr_branch_clause}
                        LIMIT :limit
                    """.format(nr_branch_clause=nr_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "drawer_name": r.drawer_name, "bank_name": r.bank_name, "status": r.status} for r in rows]

                elif entity_code == "note_payable":
                    np_branch_clause = _branch_clause("np", allowed_branches)
                    query_str = """
                        SELECT np.id, np.note_number AS name, np.beneficiary_name, np.bank_name, np.status
                        FROM notes_payable np
                        WHERE (
                            np.note_number ILIKE :q
                            OR np.beneficiary_name ILIKE :q
                            OR np.bank_name ILIKE :q
                            OR np.notes ILIKE :q
                        )
                        {np_branch_clause}
                        LIMIT :limit
                    """.format(np_branch_clause=np_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "beneficiary_name": r.beneficiary_name, "bank_name": r.bank_name, "status": r.status} for r in rows]

                elif entity_code == "expense":
                    exp_branch_clause = "AND (e.branch_id IS NULL OR e.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    exp_cc_filter, exp_cc_params = build_cost_center_filter(current_user, db, "cost_center_id", "e")
                    query_str = """
                        SELECT e.id, e.expense_number AS name, e.vendor_name, e.description, e.approval_status AS status
                        FROM expenses e
                        WHERE COALESCE(e.is_deleted, FALSE) = FALSE
                          AND (
                            e.expense_number ILIKE :q
                            OR e.vendor_name ILIKE :q
                            OR e.description ILIKE :q
                            OR e.receipt_number ILIKE :q
                            OR e.expense_type ILIKE :q
                          )
                        {exp_branch_clause}
                        {exp_cc_filter}
                        LIMIT :limit
                    """.format(exp_branch_clause=exp_branch_clause, exp_cc_filter=exp_cc_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **exp_cc_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "vendor_name": r.vendor_name, "description": r.description, "status": r.status} for r in rows]

                elif entity_code == "budget":
                    budget_branch_clause = _branch_clause("b", allowed_branches)
                    budget_cc_filter, budget_cc_params = build_cost_center_filter(current_user, db, "cost_center_id", "b")
                    query_str = """
                        SELECT b.id, COALESCE(b.budget_name, b.name) AS name, b.budget_code AS code, b.status
                        FROM budgets b
                        WHERE (
                            b.name ILIKE :q
                            OR b.budget_name ILIKE :q
                            OR b.budget_name_en ILIKE :q
                            OR b.budget_code ILIKE :q
                            OR b.description ILIKE :q
                            OR b.status ILIKE :q
                        )
                        {budget_branch_clause}
                        {budget_cc_filter}
                        LIMIT :limit
                    """.format(budget_branch_clause=budget_branch_clause, budget_cc_filter=budget_cc_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **budget_cc_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code, "status": r.status} for r in rows]

                elif entity_code == "purchase_order":
                    po_branch_clause = "AND (po.branch_id IS NULL OR po.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT po.id, po.po_number AS name, COALESCE(p.name, s.supplier_name) AS supplier_name, po.status
                        FROM purchase_orders po
                        LEFT JOIN parties p ON po.party_id = p.id
                        LEFT JOIN suppliers s ON po.supplier_id = s.id
                        WHERE (
                            po.po_number ILIKE :q
                            OR p.name ILIKE :q
                            OR s.supplier_name ILIKE :q
                            OR po.status ILIKE :q
                            OR po.notes ILIKE :q
                        )
                        {po_branch_clause}
                        LIMIT :limit
                    """.format(po_branch_clause=po_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "supplier_name": r.supplier_name, "status": r.status} for r in rows]

                elif entity_code == "purchase_invoice":
                    pi_branch_clause = "AND (i.branch_id IS NULL OR i.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    pi_warehouse_filter, pi_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "i")
                    query_str = """
                        SELECT i.id, i.invoice_number AS name, COALESCE(p.name, s.supplier_name) AS supplier_name, i.status
                        FROM invoices i
                        LEFT JOIN parties p ON i.party_id = p.id
                        LEFT JOIN suppliers s ON i.supplier_id = s.id
                        WHERE i.invoice_type = 'purchase'
                          AND (
                            i.invoice_number ILIKE :q
                            OR p.name ILIKE :q
                            OR s.supplier_name ILIKE :q
                            OR i.status ILIKE :q
                            OR i.notes ILIKE :q
                          )
                        {pi_branch_clause}
                        {pi_warehouse_filter}
                        LIMIT :limit
                    """.format(pi_branch_clause=pi_branch_clause, pi_warehouse_filter=pi_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **pi_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "supplier_name": r.supplier_name, "status": r.status} for r in rows]

                elif entity_code == "purchase_return":
                    items = _search_invoices_by_type(
                        db,
                        invoice_type="purchase_return",
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                        party_key="supplier_name",
                        warehouse_scoped=True,
                    )

                elif entity_code == "purchase_credit_note":
                    items = _search_invoices_by_type(
                        db,
                        invoice_type="purchase_credit_note",
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                        party_key="supplier_name",
                        warehouse_scoped=True,
                    )

                elif entity_code == "purchase_debit_note":
                    items = _search_invoices_by_type(
                        db,
                        invoice_type="purchase_debit_note",
                        search_param=search_param,
                        limit=limit,
                        allowed_branches=allowed_branches,
                        branch_params=branch_params,
                        current_user=current_user,
                        party_key="supplier_name",
                        warehouse_scoped=True,
                    )

                elif entity_code == "supplier_payment":
                    sp_branch_clause = _branch_clause("pv", allowed_branches)
                    query_str = """
                        SELECT pv.id, pv.voucher_number AS name, p.name AS supplier_name, pv.status
                        FROM payment_vouchers pv
                        LEFT JOIN parties p ON pv.party_id = p.id
                        WHERE pv.voucher_type = 'payment'
                          AND (
                            pv.voucher_number ILIKE :q
                            OR p.name ILIKE :q
                            OR pv.reference ILIKE :q
                            OR pv.check_number ILIKE :q
                            OR pv.notes ILIKE :q
                          )
                        {sp_branch_clause}
                        LIMIT :limit
                    """.format(sp_branch_clause=sp_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "supplier_name": r.supplier_name, "status": r.status} for r in rows]

                elif entity_code == "blanket_po":
                    bpo_branch_clause = "AND (b.branch_id IS NULL OR b.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    query_str = """
                        SELECT b.id, b.agreement_number AS name, p.name AS supplier_name, b.status
                        FROM blanket_purchase_orders b
                        LEFT JOIN parties p ON b.supplier_id = p.id
                        WHERE (
                            b.agreement_number ILIKE :q
                            OR p.name ILIKE :q
                            OR b.status ILIKE :q
                            OR b.notes ILIKE :q
                        )
                        {bpo_branch_clause}
                        LIMIT :limit
                    """.format(bpo_branch_clause=bpo_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "supplier_name": r.supplier_name, "status": r.status} for r in rows]

                elif entity_code == "employee":
                    query_str = """
                        SELECT id, (first_name || ' ' || last_name) AS name, employee_code AS employee_id
                        FROM employees
                        WHERE (
                            first_name ILIKE :q
                            OR last_name ILIKE :q
                            OR (first_name || ' ' || last_name) ILIKE :q
                            OR employee_code ILIKE :q
                        )
                        {branch_clause}
                        LIMIT :limit
                    """.format(branch_clause=branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "employee_id": r.employee_id} for r in rows]

                elif entity_code == "leave_request":
                    leave_branch_clause = ""
                    if allowed_branches:
                        leave_branch_clause = "AND (e.branch_id IS NULL OR e.branch_id = ANY(:allowed_branches))"
                    query_str = """
                        SELECT lr.id,
                               (e.first_name || ' ' || e.last_name || ' - ' || lr.leave_type) AS name,
                               (e.first_name || ' ' || e.last_name) AS employee_name,
                               lr.leave_type,
                               lr.status
                        FROM leave_requests lr
                        LEFT JOIN employees e ON lr.employee_id = e.id
                        WHERE (
                            lr.leave_type ILIKE :q
                            OR lr.reason ILIKE :q
                            OR lr.status ILIKE :q
                            OR e.employee_code ILIKE :q
                            OR e.first_name ILIKE :q
                            OR e.last_name ILIKE :q
                            OR (e.first_name || ' ' || e.last_name) ILIKE :q
                        )
                        {leave_branch_clause}
                        LIMIT :limit
                    """.format(leave_branch_clause=leave_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "employee_name": r.employee_name, "leave_type": r.leave_type, "status": r.status} for r in rows]

                elif entity_code == "payroll_period":
                    payroll_branch_clause = ""
                    if allowed_branches:
                        payroll_branch_clause = """
                            AND EXISTS (
                                SELECT 1
                                FROM payroll_entries pe
                                JOIN employees e ON e.id = pe.employee_id
                                WHERE pe.period_id = pp.id
                                  AND (e.branch_id IS NULL OR e.branch_id = ANY(:allowed_branches))
                            )
                        """
                    query_str = """
                        SELECT pp.id, pp.name, pp.status
                        FROM payroll_periods pp
                        WHERE (
                            pp.name ILIKE :q
                            OR pp.status ILIKE :q
                            OR CAST(pp.start_date AS TEXT) ILIKE :q
                            OR CAST(pp.end_date AS TEXT) ILIKE :q
                        )
                        {payroll_branch_clause}
                        LIMIT :limit
                    """.format(payroll_branch_clause=payroll_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "status": r.status} for r in rows]

                elif entity_code == "project":
                    query_str = """
                        SELECT id, project_name AS name, project_code AS code
                        FROM projects
                        WHERE (
                            project_name ILIKE :q
                            OR project_code ILIKE :q
                        )
                        {branch_clause}
                        LIMIT :limit
                    """.format(branch_clause=branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code} for r in rows]

                elif entity_code == "production_order":
                    prod_branch_clause = "AND (po.branch_id IS NULL OR po.branch_id = ANY(:allowed_branches))" if allowed_branches else ""
                    prod_warehouse_filter, prod_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "po")
                    query_str = """
                        SELECT po.id, po.order_number AS name, p.product_name, po.status
                        FROM production_orders po
                        LEFT JOIN products p ON po.product_id = p.id
                        WHERE (
                            po.order_number ILIKE :q
                            OR p.product_name ILIKE :q
                            OR p.product_code ILIKE :q
                            OR po.status ILIKE :q
                            OR po.notes ILIKE :q
                        )
                        {prod_branch_clause}
                        {prod_warehouse_filter}
                        LIMIT :limit
                    """.format(prod_branch_clause=prod_branch_clause, prod_warehouse_filter=prod_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **prod_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "product_name": r.product_name, "status": r.status} for r in rows]

                elif entity_code == "asset":
                    asset_branch_clause = _branch_clause("a", allowed_branches)
                    query_str = """
                        SELECT a.id, a.name, a.code, a.status
                        FROM assets a
                        WHERE (
                            a.name ILIKE :q
                            OR a.code ILIKE :q
                            OR a.type ILIKE :q
                            OR a.status ILIKE :q
                        )
                        {asset_branch_clause}
                        LIMIT :limit
                    """.format(asset_branch_clause=asset_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code, "status": r.status} for r in rows]

                elif entity_code == "document":
                    user_id = _user_value(current_user, "id")
                    query_str = """
                        SELECT d.id, COALESCE(d.title, d.doc_number, d.file_name) AS name,
                               d.doc_number AS code, d.file_name, d.state
                        FROM documents d
                        WHERE COALESCE(d.is_deleted, FALSE) = FALSE
                          AND (d.access_level <> 'private' OR d.created_by = :user_id)
                          AND (
                            d.doc_number ILIKE :q
                            OR d.title ILIKE :q
                            OR d.description ILIKE :q
                            OR d.file_name ILIKE :q
                            OR d.category ILIKE :q
                            OR d.related_module ILIKE :q
                          )
                        LIMIT :limit
                    """
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, "user_id": user_id}).fetchall()
                    items = [{"id": r.id, "name": r.name, "code": r.code, "file_name": r.file_name, "state": r.state} for r in rows]

                elif entity_code == "service_request":
                    srq_branch_clause = _branch_clause("srq", allowed_branches)
                    query_str = """
                        SELECT srq.id, srq.title AS name, p.name AS customer_name, srq.status
                        FROM service_requests srq
                        LEFT JOIN parties p ON srq.customer_id = p.id
                        WHERE COALESCE(srq.is_deleted, FALSE) = FALSE
                          AND (
                            srq.title ILIKE :q
                            OR srq.description ILIKE :q
                            OR srq.category ILIKE :q
                            OR srq.priority ILIKE :q
                            OR srq.status ILIKE :q
                            OR srq.location ILIKE :q
                            OR p.name ILIKE :q
                          )
                        {srq_branch_clause}
                        LIMIT :limit
                    """.format(srq_branch_clause=srq_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "pos_order":
                    pos_branch_clause = _branch_clause("po", allowed_branches)
                    pos_warehouse_filter, pos_warehouse_params = build_warehouse_filter(current_user, db, "warehouse_id", "po")
                    query_str = """
                        SELECT po.id, po.order_number AS name,
                               COALESCE(c.customer_name, po.walk_in_customer_name) AS customer_name,
                               po.status
                        FROM pos_orders po
                        LEFT JOIN customers c ON po.customer_id = c.id
                        WHERE (
                            po.order_number ILIKE :q
                            OR po.client_order_id ILIKE :q
                            OR po.walk_in_customer_name ILIKE :q
                            OR c.customer_name ILIKE :q
                            OR po.status ILIKE :q
                            OR po.note ILIKE :q
                        )
                        {pos_branch_clause}
                        {pos_warehouse_filter}
                        LIMIT :limit
                    """.format(pos_branch_clause=pos_branch_clause, pos_warehouse_filter=pos_warehouse_filter)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params, **pos_warehouse_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

                elif entity_code == "tax_return":
                    tax_branch_clause = _branch_clause("tr", allowed_branches)
                    query_str = """
                        SELECT tr.id, COALESCE(tr.return_number, tr.tax_period) AS name, tr.tax_type, tr.status
                        FROM tax_returns tr
                        WHERE (
                            tr.return_number ILIKE :q
                            OR tr.tax_period ILIKE :q
                            OR tr.tax_type ILIKE :q
                            OR tr.status ILIKE :q
                            OR tr.notes ILIKE :q
                        )
                        {tax_branch_clause}
                        LIMIT :limit
                    """.format(tax_branch_clause=tax_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "tax_type": r.tax_type, "status": r.status} for r in rows]

                elif entity_code == "crm_opportunity":
                    crm_branch_clause = _branch_clause("o", allowed_branches)
                    query_str = """
                        SELECT o.id, o.title AS name, p.name AS customer_name, o.stage AS status
                        FROM sales_opportunities o
                        LEFT JOIN parties p ON o.customer_id = p.id
                        WHERE (
                            o.title ILIKE :q
                            OR p.name ILIKE :q
                            OR o.contact_name ILIKE :q
                            OR o.contact_email ILIKE :q
                            OR o.stage ILIKE :q
                            OR o.source ILIKE :q
                            OR o.notes ILIKE :q
                        )
                        {crm_branch_clause}
                        LIMIT :limit
                    """.format(crm_branch_clause=crm_branch_clause)
                    rows = db.execute(text(query_str), {"q": search_param, "limit": limit, **branch_params}).fetchall()
                    items = [{"id": r.id, "name": r.name, "customer_name": r.customer_name, "status": r.status} for r in rows]

            except Exception:
                logger.error("Failed to execute search for entity %s", entity_code)
                items = []

            resource = registry_by_code.get(entity_code, {}).get("resource")
            if resource and items:
                try:
                    items = _filter_items(items, resource, current_user, db)
                except Exception:
                    logger.error("Failed to filter search fields for entity %s", entity_code)
                    items = []

            results.append({
                "entity": entity_code,
                "items": items,
                "count": len(items)
            })
            entity_hits[entity_code] = len(items)

    latency_ms = int((time.monotonic() - start) * 1000)
    total_count = sum(r["count"] for r in results)

    # Log the search query securely
    try:
        with get_tenant_db(tenant_id) as db:
            log_search_query(
                db=db,
                tenant_id=tenant_id,
                actor_id=_username(current_user),
                query=q,
                result_count=total_count,
                latency_ms=latency_ms,
                entity_hits=entity_hits,
            )
    except Exception:
        logger.error("Failed to log search query to DB")

    return {
        "query": q,
        "results": results,
        "total_count": total_count,
        "latency_ms": latency_ms,
    }
