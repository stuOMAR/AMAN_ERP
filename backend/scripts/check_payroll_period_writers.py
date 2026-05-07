#!/usr/bin/env python3
"""CI lint: forbid direct UPDATE payroll_periods SET state outside period_writer/period_reversal.

Scans all Python files in backend/ (excluding the canonical writers) for
direct state mutations on payroll_periods.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Files allowed to write payroll_periods.state
ALLOWED_FILES = {
    "services/payroll/period_writer.py",
    "services/payroll/period_reversal.py",
    "alembic/versions",  # migrations
}

# Patterns that indicate direct state mutation
STATE_WRITE_PATTERNS = [
    re.compile(r"UPDATE\s+payroll_periods\s+SET\s+.*state\s*=", re.IGNORECASE),
    re.compile(r"payroll_periods.*\bstate\b.*=", re.IGNORECASE),
]


def _is_allowed(filepath: Path) -> bool:
    rel = str(filepath.relative_to(BACKEND_DIR))
    return any(rel.startswith(allowed) for allowed in ALLOWED_FILES)


def check_payroll_period_writers() -> list[str]:
    """Return list of violations (empty = all pass)."""
    violations = []

    for py_file in sorted(BACKEND_DIR.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue
        if _is_allowed(py_file):
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for pattern in STATE_WRITE_PATTERNS:
            if pattern.search(content):
                rel = py_file.relative_to(BACKEND_DIR)
                violations.append(
                    f"VIOLATION: {rel} contains direct payroll_periods.state mutation; "
                    f"use period_writer.transition_state() instead"
                )
                break

    return violations


def main():
    violations = check_payroll_period_writers()
    if violations:
        print("Payroll period writers lint FAILED:")
        for v in violations:
            print(f"  ✗ {v}")
        sys.exit(1)
    print("Payroll period writers lint: OK — all state writes go through period_writer")
    sys.exit(0)


if __name__ == "__main__":
    main()
