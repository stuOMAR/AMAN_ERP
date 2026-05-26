#!/usr/bin/env python3
"""Compare historical tenant migrations with the tenant baseline DDL.

This is a pre-squash safety check. It verifies that tables/columns introduced
by historical Alembic migration files are represented by the current baseline
path used for new companies:

    db_ddl.tenant_runner.apply_tenant_schema()

The check is intentionally conservative and static. It catches straightforward
CREATE TABLE / ADD COLUMN operations in raw SQL plus common Alembic
op.create_table/op.add_column calls. Data backfills, temporary conversion
columns, constraints, and indexes are outside this first-pass column inventory.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ALEMBIC_DIRS = [
    BACKEND_DIR / "alembic" / "versions",
    BACKEND_DIR / "migrations" / "versions",
]

sys.path.insert(0, str(BACKEND_DIR))

from db_ddl import tenant_runner  # noqa: E402


IdentifierMap = dict[str, set[str]]


SKIP_TABLES = {
    # System DB tables are intentionally not part of per-tenant schema.
    "system_user_index",
    "system_companies",
    "industry_templates",
    "system_activity_log",
    "system_admin_2fa",
}


SKIP_COLUMNS = {
    # Transitional conversion columns from legacy repair migrations; they are
    # used only while casting old data and are not final schema columns.
    ("analytics_dashboards", "created_by_int"),
    ("analytics_dashboards", "updated_by_int"),
    ("analytics_dashboards", "created_by_varchar"),
    ("analytics_dashboards", "updated_by_varchar"),
    ("documents", "tags_text"),
}


def normalize_identifier(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip('"').strip("'")
    if not value:
        return None
    if "." in value:
        value = value.split(".")[-1]
    return value.lower()


def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def split_top_level_csv(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(body) and body[i + 1] == "'":
                current.append("''")
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth:
                depth -= 1
            elif ch == "," and depth == 0:
                item = "".join(current).strip()
                if item:
                    parts.append(item)
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def find_matching_paren(text: str, start: int) -> int:
    depth = 0
    in_single = False
    in_double = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def first_token(item: str) -> str | None:
    item = item.strip()
    if not item:
        return None
    match = re.match(r'"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*)', item)
    if not match:
        return None
    return normalize_identifier(match.group(1) or match.group(2))


def parse_create_tables(sql: str) -> IdentifierMap:
    found: IdentifierMap = defaultdict(set)
    cleaned = strip_sql_comments(sql)
    pattern = re.compile(
        r"\bCREATE\s+(?:TEMPORARY\s+|TEMP\s+)?TABLE\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_\.]*|\"[^\"]+\")\s*\(",
        re.I,
    )
    for match in pattern.finditer(cleaned):
        table = normalize_identifier(match.group(1))
        if not table or table in SKIP_TABLES:
            continue
        open_idx = cleaned.find("(", match.end() - 1)
        close_idx = find_matching_paren(cleaned, open_idx)
        if close_idx == -1:
            continue
        body = cleaned[open_idx + 1 : close_idx]
        for item in split_top_level_csv(body):
            token = first_token(item)
            if not token:
                continue
            if token in {
                "constraint",
                "primary",
                "foreign",
                "unique",
                "check",
                "exclude",
                "like",
            }:
                continue
            if (table, token) not in SKIP_COLUMNS:
                found[table].add(token)
    return found


def parse_alter_add_columns(sql: str) -> IdentifierMap:
    found: IdentifierMap = defaultdict(set)
    cleaned = strip_sql_comments(sql)
    alter_pattern = re.compile(
        r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
        r"([A-Za-z_][A-Za-z0-9_\.]*|\"[^\"]+\")(?P<body>.*?)(?=;\s*|\Z)",
        re.I | re.S,
    )
    add_pattern = re.compile(
        r"\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r'("([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))',
        re.I,
    )
    for match in alter_pattern.finditer(cleaned):
        table = normalize_identifier(match.group(1))
        if not table or table in SKIP_TABLES:
            continue
        for add_match in add_pattern.finditer(match.group("body")):
            column = normalize_identifier(add_match.group(2) or add_match.group(3))
            if column and (table, column) not in SKIP_COLUMNS:
                found[table].add(column)
    return found


def merge(into: IdentifierMap, other: IdentifierMap) -> None:
    for table, columns in other.items():
        into[table].update(columns)


def extract_from_sql(sql: str) -> IdentifierMap:
    found: IdentifierMap = defaultdict(set)
    merge(found, parse_create_tables(sql))
    merge(found, parse_alter_add_columns(sql))
    return found


def eval_static_string(node: ast.AST, names: dict[str, Any]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and isinstance(names.get(node.id), str):
        return names[node.id]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                rendered = eval_static_string(value.value, names)
                if rendered is None and isinstance(value.value, ast.Name):
                    raw = names.get(value.value.id)
                    if isinstance(raw, int):
                        rendered = str(raw)
                if rendered is None:
                    return None
                parts.append(rendered)
                continue
            return None
        return "".join(parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "text"
        and node.args
    ):
        return eval_static_string(node.args[0], names)
    return None


def eval_static_list(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.append(item.value)
    return values


def is_call_attr(call: ast.Call, attr: str) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == attr


def column_name_from_sa_column(node: ast.AST, names: dict[str, Any]) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "Column"
        or isinstance(node.func, ast.Name)
        and node.func.id == "Column"
    ):
        return None
    if not node.args:
        return None
    return normalize_identifier(eval_static_string(node.args[0], names))


def collect_module_strings(tree: ast.Module) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value: Any = None
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                value = node.value.value
            elif (list_value := eval_static_list(node.value)) is not None:
                value = list_value
            if value is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = value
    return values


def collect_from_upgrade_stmt(
    stmt: ast.stmt,
    names: dict[str, Any],
    found: IdentifierMap,
) -> None:
    if isinstance(stmt, ast.For) and isinstance(stmt.target, ast.Name):
        iterable = None
        if isinstance(stmt.iter, ast.Name) and isinstance(names.get(stmt.iter.id), list):
            iterable = names[stmt.iter.id]
        else:
            iterable = eval_static_list(stmt.iter)
        if iterable:
            for value in iterable:
                nested_names = dict(names)
                nested_names[stmt.target.id] = value
                for child in stmt.body:
                    collect_from_upgrade_stmt(child, nested_names, found)
            return

    for node in ast.walk(stmt):
        if not isinstance(node, ast.Call):
            continue

        if is_call_attr(node, "execute") and node.args:
            sql = eval_static_string(node.args[0], names)
            if sql:
                merge(found, extract_from_sql(sql))
            continue

        if is_call_attr(node, "add_column") and len(node.args) >= 2:
            table = normalize_identifier(eval_static_string(node.args[0], names))
            column = column_name_from_sa_column(node.args[1], names)
            if table and column and table not in SKIP_TABLES and (table, column) not in SKIP_COLUMNS:
                found[table].add(column)
            continue

        if is_call_attr(node, "create_table") and node.args:
            table = normalize_identifier(eval_static_string(node.args[0], names))
            if not table or table in SKIP_TABLES:
                continue
            for arg in node.args[1:]:
                column = column_name_from_sa_column(arg, names)
                if column and (table, column) not in SKIP_COLUMNS:
                    found[table].add(column)


def extract_expected_from_migration(path: Path) -> IdentifierMap:
    found: IdentifierMap = defaultdict(set)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise RuntimeError(f"Cannot parse {path}: {exc}") from exc
    names = collect_module_strings(tree)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            local_names = dict(names)
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    value: Any = None
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        value = stmt.value.value
                    elif (list_value := eval_static_list(stmt.value)) is not None:
                        value = list_value
                    if value is not None:
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                local_names[target.id] = value
                collect_from_upgrade_stmt(stmt, local_names, found)
    return found


def extract_actual_baseline() -> IdentifierMap:
    found: IdentifierMap = defaultdict(set)
    for block in tenant_runner._ordered_sql_blocks():
        merge(found, extract_from_sql(block))

    for block in [
        tenant_runner._OPPORTUNITY_ACTIVITIES_EXTEND_DO_BLOCK,
    ]:
        merge(found, extract_from_sql(block))

    for table, _src, generated, _idx in tenant_runner.PHASE7_PHONE_CLEAN_TARGETS:
        found[table].add(generated)
    for table, _cols, generated, _idx in tenant_runner.PHASE7_SEARCH_VECTORS:
        found[table].add(generated)

    return found


def main() -> int:
    expected: IdentifierMap = defaultdict(set)
    migration_files: list[Path] = []
    for directory in ALEMBIC_DIRS:
        migration_files.extend(sorted(directory.glob("*.py")))

    for path in migration_files:
        merge(expected, extract_expected_from_migration(path))

    actual = extract_actual_baseline()
    missing: list[tuple[str, str]] = []
    for table, columns in sorted(expected.items()):
        for column in sorted(columns):
            if table not in actual or column not in actual[table]:
                missing.append((table, column))

    print(f"migration_files={len(migration_files)}")
    print(f"expected_tables={len(expected)}")
    print(f"expected_columns={sum(len(cols) for cols in expected.values())}")
    print(f"baseline_tables={len(actual)}")
    print(f"baseline_columns={sum(len(cols) for cols in actual.values())}")
    print(f"missing_columns={len(missing)}")

    if missing:
        for table, column in missing:
            print(f"MISSING {table}.{column}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
