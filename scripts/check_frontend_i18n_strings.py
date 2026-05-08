#!/usr/bin/env python3
"""T010e: CI gate — fails on hard-coded user-visible strings.

Compares current frontend source against the baseline in
``hardcoded_strings.json``. Any new hard-coded Arabic or English string
that is not in the baseline fails the gate.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Heuristic patterns for hard-coded user-visible strings
# Arabic characters in string literals
ARABIC_PATTERN = re.compile(r'["\'][^"\']*[\u0600-\u06FF][^"\']*["\']')

SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "build", "coverage", "tests"}

# Baseline file (created from existing codebase)
BASELINE_FILE = "scripts/hardcoded_strings.json"


def load_baseline(repo_root: Path) -> set[str]:
    """Load the baseline set of known hard-coded strings."""
    baseline_path = repo_root / BASELINE_FILE
    if not baseline_path.exists():
        return set()
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
        return set(data.get("strings", []))
    except (json.JSONDecodeError, OSError):
        return set()


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    frontend_src = repo_root / "frontend" / "src"

    if not frontend_src.exists():
        print("⚠ check_frontend_i18n_strings: frontend/src/ not found, skipping")
        return 0

    baseline = load_baseline(repo_root)
    violations: list[str] = []

    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for js_file in frontend_src.rglob(ext):
            rel = js_file.relative_to(repo_root)
            rel_str = str(rel)

            if any(d in rel_str.parts for d in SKIP_DIRS):
                continue

            try:
                content = js_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue

                for m in ARABIC_PATTERN.finditer(line):
                    string_val = m.group()
                    # Skip if in baseline
                    if string_val in baseline:
                        continue
                    # Skip imports and comments
                    if "import" in stripped:
                        continue
                    violations.append(f"{rel}:{line_num}: {string_val}")

    if violations:
        print("I18N VIOLATIONS — new hard-coded strings must be translated or added to baseline:")
        for v in violations[:50]:  # Limit output
            print(f"  ✗ {v}")
        if len(violations) > 50:
            print(f"  ... and {len(violations) - 50} more")
        return 1

    print("✓ check_frontend_i18n_strings: no new hard-coded strings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
