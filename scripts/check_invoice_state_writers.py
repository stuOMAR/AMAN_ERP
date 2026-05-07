#!/usr/bin/env python3
"""
CI guard — forbids UPDATE invoices SET state outside
services/sales/invoice_state.py. Also forbids direct assignment to
invoice.state outside the same module.

Exit code 0: clean. Exit code 1: violation detected.

Feature 023 — T028.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

ALLOWED = {
    "backend/services/sales/invoice_state.py",
}

# Patterns to detect
SQL_PATTERN = re.compile(
    r"""(?:UPDATE\s+invoices\s+SET|UPDATE\s+invoices\b[^;]*?\bstate\s*=)""",
    re.IGNORECASE | re.DOTALL,
)
PY_ASSIGN_PATTERN = re.compile(
    r"""(?:\[["']state["']\s*=|\.state\s*=\s*(?!None))""",
    re.IGNORECASE,
)

# Files to scan
SCAN_GLOBS = [
    "backend/services/**/*.py",
    "backend/routers/**/*.py",
]


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    violations: list[str] = []

    for pattern in SCAN_GLOBS:
        for fpath in BACKEND.parent.glob(pattern):
            if fpath.is_dir():
                continue
            rf = rel(fpath)
            if rf in ALLOWED:
                continue

            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            for i, line in enumerate(text.splitlines(), 1):
                if SQL_PATTERN.search(line):
                    violations.append(f"{rf}:{i}: {line.strip()}")
                elif PY_ASSIGN_PATTERN.search(line) and "state" in line.lower():
                    # Skip comments and strings
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    violations.append(f"{rf}:{i}: {line.strip()}")

    if violations:
        print("[check_invoice_state_writers] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  {v}")
        print(f"\nTotal: {len(violations)} violation(s). "
              "Use services/sales/invoice_state.transition() instead.")
        return 1

    print("[check_invoice_state_writers] ✅ No violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
