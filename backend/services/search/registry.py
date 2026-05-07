"""T141: Search registry — data-driven entity list with permissions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchEntity:
    entity_code: str
    label: str
    route_template: str
    icon: str
    permissions_required: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()


# ── Registry ─────────────────────────────────────────────────────────────

SEARCH_REGISTRY: tuple[SearchEntity, ...] = (
    SearchEntity("customer", "Customers", "/sales/customers/{id}", "Users", ("sales.view",), ("name", "email", "phone")),
    SearchEntity("supplier", "Suppliers", "/purchases/suppliers/{id}", "Truck", ("purchases.view",), ("name", "email")),
    SearchEntity("invoice", "Invoices", "/sales/invoices/{id}", "FileText", ("sales.view",), ("invoice_number", "customer_name")),
    SearchEntity("product", "Products", "/inventory/products/{id}", "Package", ("inventory.view",), ("name", "sku", "barcode")),
    SearchEntity("journal_entry", "Journal Entries", "/accounting/journal-entries/{id}", "BookOpen", ("accounting.view",), ("reference", "description")),
    SearchEntity("account", "Accounts", "/accounting/chart-of-accounts/{id}", "List", ("accounting.view",), ("code", "name")),
    SearchEntity("employee", "Employees", "/hr/employees/{id}", "User", ("hr.view",), ("name", "employee_id")),
    SearchEntity("project", "Projects", "/projects/{id}", "Folder", ("projects.view",), ("name", "code")),
)


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
        }
        for e in SEARCH_REGISTRY
    ]


def get_registry_for_user(user_permissions: set[str]) -> list[dict]:
    """Return registry entries the user has permission to see."""
    return [
        entry for entry in get_registry()
        if not entry["permissions_required"] or
           any(p in user_permissions for p in entry["permissions_required"])
    ]
