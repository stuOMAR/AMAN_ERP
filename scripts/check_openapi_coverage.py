#!/usr/bin/env python3
"""T9.2 — OpenAPI documentation coverage check.

Scans every `@router.<method>(...)` decorator in `backend/routers/**/*.py`
and reports how many endpoints have a docstring (FastAPI uses the first
line of the docstring as the OpenAPI `summary` automatically when neither
`summary=` nor a `description=` kwarg is supplied).

Usage:
    python scripts/check_openapi_coverage.py            # human report
    python scripts/check_openapi_coverage.py --json     # machine readable
    python scripts/check_openapi_coverage.py --fail-under 70   # CI gate

The script intentionally avoids importing FastAPI: it parses the AST so
it can run in a clean environment without DB connections.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Methods that produce an OpenAPI operation.
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def is_router_decorator(node: ast.expr) -> str | None:
    """Return the HTTP method name if `node` is a `@router.<method>(...)` decorator."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute) and target.attr in HTTP_METHODS:
        # @router.get / @router_finance.get / @invoices_router.post are all fine.
        return target.attr
    return None


def has_summary_kwarg(deco: ast.expr) -> bool:
    if not isinstance(deco, ast.Call):
        return False
    return any(kw.arg in ("summary", "description") for kw in deco.keywords)


def scan_file(path: Path) -> list[dict]:
    """Return a list of endpoint metadata dicts for `path`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            method = is_router_decorator(deco)
            if not method:
                continue
            doc = ast.get_docstring(node)
            out.append(
                {
                    "file": str(path),
                    "name": node.name,
                    "method": method.upper(),
                    "line": node.lineno,
                    "has_docstring": bool(doc and doc.strip()),
                    "has_summary_kwarg": has_summary_kwarg(deco),
                }
            )
    return out


def collect(root: Path) -> list[dict]:
    files = sorted(root.rglob("*.py"))
    results: list[dict] = []
    for f in files:
        results.extend(scan_file(f))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="backend/routers", help="routers directory")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument("--fail-under", type=float, default=0.0, help="exit non-zero if coverage < this %")
    parser.add_argument("--list-missing", action="store_true", help="print every undocumented endpoint")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"❌ root not found: {root}", file=sys.stderr)
        return 2

    items = collect(root)
    total = len(items)
    if total == 0:
        print(f"❌ no endpoints found under {root}", file=sys.stderr)
        return 2

    documented = sum(1 for x in items if x["has_docstring"] or x["has_summary_kwarg"])
    pct = (documented / total) * 100.0

    if args.json:
        print(json.dumps({"total": total, "documented": documented, "coverage_pct": round(pct, 2)}, indent=2))
    else:
        print(f"OpenAPI documentation coverage")
        print(f"  endpoints scanned: {total}")
        print(f"  documented (docstring or summary= kwarg): {documented}")
        print(f"  coverage: {pct:.2f}%")
        if args.list_missing:
            print("\nUndocumented endpoints:")
            for x in items:
                if not x["has_docstring"] and not x["has_summary_kwarg"]:
                    print(f"  {x['file']}:{x['line']}  {x['method']}  {x['name']}")

    if args.fail_under and pct < args.fail_under:
        print(f"❌ coverage {pct:.2f}% < required {args.fail_under}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
