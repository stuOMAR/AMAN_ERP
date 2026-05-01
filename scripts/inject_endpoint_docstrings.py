#!/usr/bin/env python3
"""T9.2 helper — insert one-line docstrings into router endpoints that lack one.

This script is conservative:
- Operates only on `@router.<method>(...)`-decorated functions inside
  `backend/routers/**/*.py`.
- Skips functions that already have ANY docstring or whose decorator already
  passes `summary=` / `description=`.
- Inserts a single-line docstring derived from the function name (snake_case
  → Title Case humanization).
- Idempotent: running twice changes nothing.

Usage:
    python scripts/inject_endpoint_docstrings.py              # dry-run
    python scripts/inject_endpoint_docstrings.py --write      # apply
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Domain abbreviation expansions for nicer summaries.
ABBR = {
    "id": "ID",
    "ids": "IDs",
    "po": "PO",
    "pi": "PI",
    "rfq": "RFQ",
    "ot": "OT",
    "kpi": "KPI",
    "wps": "WPS",
    "qr": "QR",
    "csid": "CSID",
    "url": "URL",
    "api": "API",
    "ui": "UI",
    "pos": "POS",
    "fsm": "FSM",
    "mrp": "MRP",
    "bom": "BOM",
    "dlq": "DLQ",
    "csv": "CSV",
    "pdf": "PDF",
    "xml": "XML",
    "json": "JSON",
    "ldap": "LDAP",
    "smtp": "SMTP",
    "sms": "SMS",
    "hr": "HR",
    "wht": "WHT",
    "iban": "IBAN",
    "gosi": "GOSI",
    "zatca": "ZATCA",
    "eta": "ETA",
}


def humanize(name: str) -> str:
    parts = name.split("_")
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        out.append(ABBR.get(p.lower(), p.capitalize()))
    return " ".join(out)


def is_router_call(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute) and target.attr in HTTP_METHODS:
        return target.attr
    return None


def has_summary_kw(deco: ast.expr) -> bool:
    return isinstance(deco, ast.Call) and any(kw.arg in ("summary", "description") for kw in deco.keywords)


def find_endpoints_without_docstrings(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    found: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_endpoint = False
        for deco in node.decorator_list:
            if is_router_call(deco):
                if has_summary_kw(deco):
                    is_endpoint = False
                    break
                is_endpoint = True
        if is_endpoint and not (ast.get_docstring(node) or "").strip():
            found.append((node, node.name))
    return found


# Match the closing ): of a `def func(...):` block (handles multi-line signatures).
DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)


def inject(text: str, names_to_inject: set[str]) -> tuple[str, int]:
    """Insert a one-line docstring after the first `):` that closes the matching def header.

    Returns (new_text, count).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    inserted = 0
    while i < len(lines):
        line = lines[i]
        m = DEF_RE.match(line)
        if not m or m.group(2) not in names_to_inject:
            out.append(line)
            i += 1
            continue

        indent = m.group(1)
        fname = m.group(2)
        # Walk lines (including the def line itself) until we find the line that
        # closes the signature. A signature is closed by a line ending with `):`
        # or `): ...` annotations like `-> X:`. The plain colon-suffix test was
        # too loose — it would match a `try:` or `with foo:` further down the
        # body when the def signature was already single-line. Use a paren-
        # balance check instead.
        sig_chunk: list[str] = []
        paren_depth = 0
        j = i
        seen_open = False
        closed = False
        while j < len(lines):
            sig_chunk.append(lines[j])
            for ch in lines[j]:
                if ch == "(":
                    paren_depth += 1
                    seen_open = True
                elif ch == ")":
                    paren_depth -= 1
            if seen_open and paren_depth == 0:
                # Found the closing paren on this line; the line should also end
                # with `:` (possibly after `-> Annotation`). If not, bail out.
                if lines[j].rstrip("\n").rstrip().endswith(":"):
                    closed = True
                break
            j += 1
        if not closed:
            out.append(line)
            i += 1
            continue
        # Emit signature.
        out.extend(sig_chunk)
        # Compute body indent — same as def indent + 4 spaces (typical).
        body_indent = indent + "    "
        # Look ahead for an existing docstring just to be defensive.
        peek = lines[j + 1] if j + 1 < len(lines) else ""
        if peek.lstrip().startswith(('"""', "'''")):
            i = j + 1
            continue
        summary = humanize(fname)
        # Avoid empty summaries.
        if not summary:
            i = j + 1
            continue
        out.append(f'{body_indent}"""{summary}."""\n')
        inserted += 1
        i = j + 1
    return "".join(out), inserted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="backend/routers")
    ap.add_argument("--write", action="store_true", help="apply changes")
    args = ap.parse_args()

    root = Path(args.root)
    files = sorted(root.rglob("*.py"))
    total_inserted = 0
    files_changed = 0
    for f in files:
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        targets = {name for _, name in find_endpoints_without_docstrings(tree)}
        if not targets:
            continue
        new_src, count = inject(src, targets)
        if count == 0:
            continue
        files_changed += 1
        total_inserted += count
        print(f"{f}: +{count}")
        if args.write:
            f.write_text(new_src, encoding="utf-8")

    print(f"\n{'WROTE' if args.write else 'WOULD WRITE'} {total_inserted} docstrings across {files_changed} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
