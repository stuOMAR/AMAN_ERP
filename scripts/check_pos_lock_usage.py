#!/usr/bin/env python3
"""
CI guard — scans backend/services/pos/ for functions that write to
inventory tables without holding pos_stock_lock.

Exit code 0: clean. Exit code 1: violation detected.

Feature 023 — T048.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

POS_DIR = BACKEND / "services" / "pos"

# Table names that indicate inventory writes
WRITE_TABLES = re.compile(
    r"""INSERT\s+INTO\s+(?:inventory_transactions|pos_sales|pos_sale_lines|pos_returns)""",
    re.IGNORECASE,
)

# Lock acquisition pattern
LOCK_PATTERN = re.compile(r"""pos_stock_lock\s*\(""", re.IGNORECASE)

# Files to skip (lock module itself, offline reconcile)
SKIP_FILES = {
    "stock_lock.py",
    "pos_offline_reconcile.py",
}


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    if not POS_DIR.exists():
        print("[check_pos_lock_usage] ✅ No pos services directory — skipping")
        return 0

    violations: list[str] = []

    for fpath in POS_DIR.glob("*.py"):
        if fpath.name in SKIP_FILES or fpath.name == "__init__.py":
            continue

        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception:
            continue

        rf = rel(fpath)

        # Check if file has inventory writes
        has_writes = bool(WRITE_TABLES.search(text))
        if not has_writes:
            continue

        # Check if file uses pos_stock_lock
        has_lock = bool(LOCK_PATTERN.search(text))
        if not has_lock:
            violations.append(f"{rf}: writes to inventory tables without pos_stock_lock()")

    if violations:
        print("[check_pos_lock_usage] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  {v}")
        print(f"\nTotal: {len(violations)} violation(s). "
              "All POS inventory writes must be wrapped in pos_stock_lock().")
        return 1

    print("[check_pos_lock_usage] ✅ No violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
