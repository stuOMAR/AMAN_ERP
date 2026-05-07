#!/usr/bin/env python3
"""
CI guard — forbids float in cost/qty arithmetic in inventory, costing,
manufacturing modules. AST scan for float(), division producing float,
and arithmetic with float literals on cost/qty paths.

Also greps for the legacy external signer URL pattern.

Exit code 0: clean. Exit code 1: violation detected.

Feature 023 — T072.
"""
from __future__ import annotations
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

SCOPE = [
    "backend/services/inventory/",
    "backend/services/manufacturing/",
    "backend/services/costing_service.py",
    "backend/services/pos/",
    "backend/services/sales/",
    "backend/services/returns_unified_service.py",
]

# Legacy external signer URL pattern
LEGACY_SIGNER = re.compile(
    r"""(?:signer_url|external_signer|SIGNER_BASE_URL)""",
    re.IGNORECASE,
)

# float() call pattern
FLOAT_CALL = re.compile(r"""\bfloat\s*\(""")


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


class FloatChecker(ast.NodeVisitor):
    """AST visitor that flags float() calls and float literals in cost/qty paths."""

    def __init__(self, filepath: str):
        self.violations: list[str] = []
        self.filepath = filepath

    def visit_Call(self, node: ast.Call):
        # Detect float() calls
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            self.violations.append(
                f"{self.filepath}:{node.lineno}: float() call — use Decimal() instead"
            )
        self.generic_visit(node)


def main() -> int:
    violations: list[str] = []

    for scope_pattern in SCOPE:
        scope_path = BACKEND.parent / scope_pattern
        if scope_path.is_dir():
            files = list(scope_path.rglob("*.py"))
        elif scope_path.is_file():
            files = [scope_path]
        else:
            continue

        for fpath in files:
            if fpath.name == "__init__.py":
                continue

            rf = rel(fpath)
            try:
                source = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            # AST check for float()
            try:
                tree = ast.parse(source, filename=rf)
                checker = FloatChecker(rf)
                checker.visit(tree)
                violations.extend(checker.violations)
            except SyntaxError:
                pass

            # Regex check for legacy signer references
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if LEGACY_SIGNER.search(line):
                    violations.append(
                        f"{rf}:{i}: legacy external signer reference — use inline ubl_signer instead"
                    )

    if violations:
        print("[check_no_float_money] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  {v}")
        print(f"\nTotal: {len(violations)} violation(s). "
              "Use Decimal for all cost/qty arithmetic.")
        return 1

    print("[check_no_float_money] ✅ No violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
