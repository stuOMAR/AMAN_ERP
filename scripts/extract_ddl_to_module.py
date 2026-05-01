#!/usr/bin/env python3
"""T6.4 — Extract DDL functions from backend/database.py to backend/db_ddl/tenant_schema.py.

Uses Python's AST module so that triple-quoted SQL strings (which can contain
column-0 ``--`` SQL comments) are handled correctly.

Idempotent: if database.py no longer contains the functions, exits with no
changes.
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(ROOT, "backend", "database.py")
DDL_DIR = os.path.join(ROOT, "backend", "db_ddl")
TARGET = os.path.join(DDL_DIR, "tenant_schema.py")

DDL_FUNCS = [
    "get_foundation_tables_sql",
    "get_additional_base_tables_sql",
    "get_treasury_base_tables_sql",
    "get_core_dependent_tables_sql",
    "get_additional_dependent_tables_sql",
    "get_organization_tables_sql",
    "get_financial_tables_sql",
    "get_treasury_dependent_tables_sql",
    "get_currency_tables_sql",
    "get_contract_tables_sql",
    "get_costing_policy_tables_sql",
    "get_advanced_inventory_tables_sql",
    "get_advanced_inventory_phase2_tables_sql",
    "get_manufacturing_tables_sql",
    "get_pos_tables_sql",
    "get_approval_tables_sql",
    "get_security_tables_sql",
    "get_cashflow_forecast_tables_sql",
    "get_phase_features_tables_sql",
    "get_system_completion_tables_sql",
    "get_extended_features_tables_sql",
    "get_performance_indexes_sql",
    "get_gl_integrity_guards_sql",
    "get_phase5_integration_tables_sql",
]


def main() -> int:
    with open(DB_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.split("\n")

    name_to_node = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            name_to_node[node.name] = node

    missing = [name for name in DDL_FUNCS if name not in name_to_node]
    if missing:
        if len(missing) == len(DDL_FUNCS):
            print("Already extracted. No-op.")
            return 0
        print(f"Some DDL functions not found: {missing}", file=sys.stderr)
        return 2

    ranges = []
    for name in DDL_FUNCS:
        node = name_to_node[name]
        start = node.lineno - 1
        end = (node.end_lineno or node.lineno) - 1
        ranges.append((start, end, name))
    ranges.sort()

    extracted_blocks = []
    remove = set()
    for s, e, name in ranges:
        block = "\n".join(lines[s : e + 1]).rstrip() + "\n"
        extracted_blocks.append((name, block))
        for k in range(s, e + 1):
            remove.add(k)

    out_lines = []
    blank_run = 0
    for k, ln in enumerate(lines):
        if k in remove:
            continue
        if ln.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                out_lines.append(ln)
        else:
            blank_run = 0
            out_lines.append(ln)
    new_db = "\n".join(out_lines)

    if "from db_ddl.tenant_schema import" not in new_db:
        anchor = "from config import settings"
        idx = new_db.find(anchor)
        if idx == -1:
            print("Anchor not found", file=sys.stderr)
            return 3
        eol = new_db.find("\n", idx) + 1
        import_block = (
            "\n# T6.4: DDL extracted to backend/db_ddl/tenant_schema.py.\n"
            "# Re-export here so any caller `from database import get_*_tables_sql`\n"
            "# continues to work. db_ddl is the single source of truth.\n"
            "from db_ddl.tenant_schema import (  # noqa: E402,F401\n"
            + "".join(f"    {fn},\n" for fn in DDL_FUNCS)
            + ")\n"
        )
        new_db = new_db[:eol] + import_block + new_db[eol:]

    os.makedirs(DDL_DIR, exist_ok=True)
    init_path = os.path.join(DDL_DIR, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(
                '"""T6.4 — Tenant DDL package.\n\n'
                "Single source of truth for the per-tenant CREATE TABLE/INDEX DDL\n"
                "that was previously inlined in ``backend/database.py``.\n"
                '"""\n'
            )

    header = (
        '"""T6.4 — Tenant DDL functions extracted from backend/database.py.\n\n'
        "Each ``get_*_tables_sql()`` function returns a single SQL string of\n"
        "one or more ``CREATE TABLE`` / ``CREATE INDEX`` statements. This is\n"
        "the **single source of truth** for the per-tenant schema.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "__all__ = [\n"
        + "".join(f'    "{fn}",\n' for fn in DDL_FUNCS)
        + "]\n\n\n"
    )
    body = "\n\n".join(b for _, b in extracted_blocks).rstrip() + "\n"

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(header + body)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        f.write(new_db)

    print(f"Extracted {len(DDL_FUNCS)} DDL functions to {TARGET}")
    print(f"database.py now: {len(new_db.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
