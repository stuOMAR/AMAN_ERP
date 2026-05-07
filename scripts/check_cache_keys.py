#!/usr/bin/env python3
"""T010a: CI gate — fails on any cache key without a ``tenant_id`` segment.

Scans backend source for cache key construction patterns and ensures every
key includes a tenant/company identifier segment.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that construct cache keys
KEY_PATTERNS = [
    # f-string key construction
    re.compile(r'f["\']([^"\']*(?:cache|key|prefix)[^"\']*)["\']', re.IGNORECASE),
    # cache.get/set with string literal
    re.compile(r'cache\.(?:get|set|delete)\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # tenant_key() — always valid, skip
]

# Files/patterns to skip (known safe or infrastructure)
SKIP_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    ".git/",
    "test_",
    "tests/",
    "conftest.py",
    "cache.py",  # the cache utility itself
    "settings/registry.py",
    "migrations/",
    "alembic/",
]

# Words that indicate a tenant/company ID segment is present
TENANT_INDICATORS = [
    "tenant_id", "company_id", "tenant", "company",
    "current_user.company_id", "current_user.tenant_id",
    "t:", "tenant_key(",
]


def has_tenant_segment(key_str: str) -> bool:
    """Check if a cache key string contains a tenant identifier segment."""
    lower = key_str.lower()
    return any(ind in lower for ind in TENANT_INDICATORS)


def check_file(filepath: Path) -> list[str]:
    """Check a single file for cache keys missing tenant_id."""
    violations = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return violations

    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue

        # Check for cache.get/set/delete with string literal keys
        for m in re.finditer(r'cache\.(?:get|set|delete)\s*\(\s*f?["\']([^"\']*)["\']', stripped):
            key = m.group(1)
            if not has_tenant_segment(key):
                violations.append(f"{filepath}:{line_num}: cache key missing tenant_id: {key}")

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"

    all_violations: list[str] = []

    for py_file in backend_dir.rglob("*.py"):
        rel = py_file.relative_to(repo_root)
        rel_str = str(rel)

        # Skip known safe paths
        if any(skip in rel_str for skip in SKIP_PATTERNS):
            continue

        violations = check_file(py_file)
        all_violations.extend(violations)

    if all_violations:
        print("CACHE KEY VIOLATIONS — every cache key must include tenant_id:")
        for v in all_violations:
            print(f"  ✗ {v}")
        return 1

    print("✓ check_cache_keys: all cache keys include tenant_id segment")
    return 0


if __name__ == "__main__":
    sys.exit(main())
