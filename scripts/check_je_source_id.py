#!/usr/bin/env python3
"""
CI guard — fails on gl_service.reverse(...) or gl_service.post(...) calls
that pass reference_number= instead of source= and source_id=.

Exit code 0: clean. Exit code 1: violation detected.

Feature 023 — T029.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# Patterns that indicate old-style reference_number usage
BAD_PATTERNS = [
    re.compile(r"""gl_service\.(?:post|reverse|create_journal_entry)\s*\([^)]*reference_number\s*=""", re.DOTALL),
    re.compile(r"""create_journal_entry\s*\([^)]*reference_number\s*=""", re.DOTALL),
]

# Allowlist: modules that may still use reference_number during transition
ALLOWLIST = set()

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
            if rf in ALLOWLIST:
                continue

            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            for i, line in enumerate(text.splitlines(), 1):
                for bad in BAD_PATTERNS:
                    if bad.search(line):
                        violations.append(f"{rf}:{i}: {line.strip()}")

    if violations:
        print("[check_je_source_id] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  {v}")
        print(f"\nTotal: {len(violations)} violation(s). "
              "Use source= and source_id= instead of reference_number=.")
        return 1

    print("[check_je_source_id] ✅ No violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
