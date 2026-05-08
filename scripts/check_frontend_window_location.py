#!/usr/bin/env python3
"""T010d: CI gate — fails on window.location outside the documented allow-list.

Scans frontend source for ``window.location`` usage. Only files listed in
the allow-list may use it (e.g., logout, OAuth redirect).

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Files explicitly allowed to use window.location
ALLOWED_FILES: set[str] = {
    "frontend/src/utils/auth.js",
    "frontend/src/services/apiClient.js",
    "frontend/src/utils/navigation-allowlist.md",
    "frontend/src/components/Layout.jsx",
    "frontend/src/pages/Login.jsx",
    "frontend/src/pages/Setup/IndustrySetup.jsx",
    "frontend/src/pages/Setup/ModuleCustomization.jsx",
    "frontend/src/pages/Setup/OnboardingWizard.jsx",
    "frontend/src/pages/Settings/CompanySettings.jsx",
}

WINDOW_LOCATION_PATTERN = re.compile(r'window\.location\s*[\.\[]')

SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "build", "coverage", "tests"}


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    frontend_src = repo_root / "frontend" / "src"

    if not frontend_src.exists():
        print("⚠ check_frontend_window_location: frontend/src/ not found, skipping")
        return 0

    violations: list[str] = []

    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for js_file in frontend_src.rglob(ext):
            rel = js_file.relative_to(repo_root)
            rel_str = str(rel)

            if rel_str in ALLOWED_FILES:
                continue
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
                if WINDOW_LOCATION_PATTERN.search(line):
                    violations.append(f"{rel}:{line_num}: uses window.location")

    if violations:
        print("WINDOW LOCATION VIOLATIONS — use useNavigate() from react-router-dom:")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print("✓ check_frontend_window_location: no forbidden window.location usage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
