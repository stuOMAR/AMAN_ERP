#!/usr/bin/env python3
"""CI lint: forbid hardcoded bank codes in WPS/HR modules.

Scans backend/services/wps/ and backend/routers/hr_wps_compliance.py for
hardcoded bank code strings (e.g., 'RJHI', 'NCBS', 'SABB') and requires
usage of the bank_codes registry instead.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Known Saudi bank codes that should not be hardcoded
HARDCODED_BANK_CODES = {
    "RJHI", "NCBS", "SABB", "ALBI", "BSFR", "RIYAD",
    "ANB", "SAMB", "INMA", "BANK", "ALRAJHI",
}

# Files that are allowed to reference codes directly
ALLOWED_FILES = {
    "services/wps/bank_codes.py",
    "db_ddl/seed_bank_codes.json",
    "alembic/versions",
}


def _is_allowed(filepath: Path) -> bool:
    rel = str(filepath.relative_to(BACKEND_DIR))
    return any(rel.startswith(allowed) for allowed in ALLOWED_FILES)


def check_hardcoded_bank_codes() -> list[str]:
    """Return list of violations (empty = all pass)."""
    violations = []
    code_pattern = re.compile(r"['\"](" + "|".join(HARDCODED_BANK_CODES) + r")['\"]")

    target_dirs = [
        BACKEND_DIR / "services" / "wps",
        BACKEND_DIR / "routers",
    ]

    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for py_file in sorted(target_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            if _is_allowed(py_file):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            matches = code_pattern.findall(content)
            if matches:
                rel = py_file.relative_to(BACKEND_DIR)
                violations.append(
                    f"VIOLATION: {rel} contains hardcoded bank code(s): "
                    f"{', '.join(set(matches))}. Use bank_codes.lookup_by_code() instead."
                )

    return violations


def main():
    violations = check_hardcoded_bank_codes()
    if violations:
        print("Hardcoded bank codes lint FAILED:")
        for v in violations:
            print(f"  ✗ {v}")
        sys.exit(1)
    print("Hardcoded bank codes lint: OK — no hardcoded bank codes found")
    sys.exit(0)


if __name__ == "__main__":
    main()
