#!/usr/bin/env python3
"""
CI guard — fails on any import or call of get_acc_id outside
services/sales/account_mapping.py.

Exit code 0: clean. Exit code 1: violation detected.

Feature 023 — T032.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

ALLOWED = {
    "backend/services/sales/account_mapping.py",
}

# Patterns to detect
IMPORT_PATTERN = re.compile(r"""(?:from\s+\S+\s+import\s+.*\bget_acc_id\b|import\s+.*\bget_acc_id\b)""")
CALL_PATTERN = re.compile(r"""\bget_acc_id\s*\(""")
ACC_MAP_SALES_REV_PATTERN = re.compile(r"""\bacc_map_sales_rev\b""", re.IGNORECASE)

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
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                if IMPORT_PATTERN.search(line):
                    violations.append(f"{rf}:{i}: imports get_acc_id — use account_mapping.resolve() instead")
                elif CALL_PATTERN.search(line):
                    violations.append(f"{rf}:{i}: calls get_acc_id() — use account_mapping.resolve() instead")
                elif ACC_MAP_SALES_REV_PATTERN.search(line):
                    violations.append(f"{rf}:{i}: reads acc_map_sales_rev — use account_mapping.resolve(direction='reversal') instead")

    if violations:
        print("[check_get_acc_id_callsites] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  {v}")
        print(f"\nTotal: {len(violations)} violation(s). "
              "Use services/sales/account_mapping.resolve() instead.")
        return 1

    print("[check_get_acc_id_callsites] ✅ No violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
