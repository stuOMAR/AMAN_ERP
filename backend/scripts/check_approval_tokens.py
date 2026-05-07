#!/usr/bin/env python3
"""CI lint: flag HMAC issuance/verification of approval tokens outside approval_tokens.py."""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

ALLOWED_FILES = {
    "services/auth/approval_tokens.py",
    "alembic/versions",
}

PATTERNS = [
    re.compile(r"hmac\.new.*approval", re.IGNORECASE),
    re.compile(r"APPROVAL_TOKEN_SIGNING_KEY"),
    re.compile(r"approval_tokens.*nonce.*signature"),
]


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
        for p in PATTERNS:
            if p.search(content):
                violations.append(f"VIOLATION: {rel} — use services/auth/approval_tokens.py")
                break
    return violations


def main():
    violations = check()
    if violations:
        print("Approval tokens lint FAILED:")
        for v in violations:
            print(f"  ✗ {v}")
        sys.exit(1)
    print("Approval tokens lint: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
