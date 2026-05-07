#!/usr/bin/env python3
"""CI lint: verify maintenance work orders go through unified_writer.

Checks that direct INSERT into service_orders with kind='maintenance'
only happens in the unified_writer module.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

ALLOWED_FILES = {
    "services/fsm/maintenance/unified_writer.py",
    "alembic/versions",
}

PATTERN = re.compile(
    r"INSERT\s+INTO\s+service_orders.*maintenance",
    re.IGNORECASE | re.DOTALL,
)


def check() -> list[str]:
    violations = []
    for py_file in sorted(BACKEND_DIR.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue
        rel = str(py_file.relative_to(BACKEND_DIR))
        if any(rel.startswith(a) for a in ALLOWED_FILES):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if PATTERN.search(content):
            violations.append(f"VIOLATION: {rel} — use unified_writer.create_work_order()")
    return violations


def main():
    violations = check()
    if violations:
        print("Maintenance writers lint FAILED:")
        for v in violations:
            print(f"  ✗ {v}")
        sys.exit(1)
    print("Maintenance writers lint: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
