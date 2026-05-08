#!/usr/bin/env python3
"""T010c: CI gate — fails on .toFixed() or parseFloat() outside format.js.

Scans frontend source for forbidden number-formatting patterns.
Only ``frontend/src/utils/format.js`` is allowed to use these primitives.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_FILE = "frontend/src/utils/format.js"

FORBIDDEN_PATTERNS = [
    (re.compile(r'\.toFixed\s*\('), ".toFixed()"),
    (re.compile(r'parseFloat\s*\('), "parseFloat()"),
]

SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "build", "coverage"}


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    frontend_src = repo_root / "frontend" / "src"

    if not frontend_src.exists():
        print("⚠ check_frontend_number_format: frontend/src/ not found, skipping")
        return 0

    violations: list[str] = []

    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for js_file in frontend_src.rglob(ext):
            rel = js_file.relative_to(repo_root)
            rel_str = str(rel)

            # Skip allowed file and non-source dirs
            if rel_str == ALLOWED_FILE:
                continue
            if any(d in rel.parts for d in SKIP_DIRS):
                continue

            try:
                content = js_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                # Skip comments
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                for pattern, name in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        violations.append(f"{rel}:{line_num}: uses {name}")

    if violations:
        print("NUMBER FORMAT VIOLATIONS — use formatNumber() from utils/format.js:")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print("✓ check_frontend_number_format: no forbidden .toFixed/parseFloat usage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
