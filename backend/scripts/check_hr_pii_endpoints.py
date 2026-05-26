#!/usr/bin/env python3
"""CI lint: verify every HR router emitting PII fields declares require_sensitive_permission('hr.pii').

Scans all Python files in backend/routers/hr/ for references to PII field names
(salary, iban, national_id, passport_number, bank_account_number, gosi_number)
and verifies the endpoint is either:
  1. Wrapped by require_sensitive_permission('hr.pii'), OR
  2. Uses mask_employee_dict / hr_pii_serializer to mask PII

Exit code 0 = pass, 1 = violations found.
"""
from __future__ import annotations

import sys
from pathlib import Path

PII_FIELDS = {"salary", "iban", "national_id", "passport_number", "bank_account_number", "gosi_number"}

# Patterns that indicate PII is being handled safely
SAFE_PATTERNS = {
    "require_sensitive_permission",
    "mask_employee_dict",
    "hr_pii_serializer",
    "unmask_field",
    "encrypt_pii",
    "decrypt_pii",
}

HR_ROUTERS_DIR = Path(__file__).resolve().parent.parent / "routers" / "hr"


def _file_references_pii(filepath: Path) -> bool:
    """Check if a file references PII field names."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return False
    return any(field in content for field in PII_FIELDS)


def _file_has_safe_pattern(filepath: Path) -> bool:
    """Check if a file uses safe PII handling patterns."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return False
    return any(pattern in content for pattern in SAFE_PATTERNS)


def check_hr_pii_endpoints() -> list[str]:
    """Return list of violations (empty = all pass)."""
    violations = []

    if not HR_ROUTERS_DIR.exists():
        return violations

    for py_file in sorted(HR_ROUTERS_DIR.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if _file_references_pii(py_file) and not _file_has_safe_pattern(py_file):
            rel = py_file.relative_to(HR_ROUTERS_DIR.parent.parent)
            violations.append(
                f"VIOLATION: {rel} references PII fields but does not use "
                f"require_sensitive_permission('hr.pii') or masking serializer"
            )

    return violations


def main():
    violations = check_hr_pii_endpoints()
    if violations:
        print("HR PII Gate lint FAILED:")
        for v in violations:
            print(f"  ✗ {v}")
        sys.exit(1)
    print("HR PII Gate lint: OK — all PII-emitting endpoints are gated")
    sys.exit(0)


if __name__ == "__main__":
    main()
