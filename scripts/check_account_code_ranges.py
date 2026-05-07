"""CI lint: detect hard-coded account-code-range checks in reports.

Fails (exit 1) when regex/AST scan finds code-range checks in
``backend/services/reports/**`` or ``backend/routers/reports*``.

All report modules MUST use ``account_classifier.classify()`` or
``account_classifier.classify_many()`` instead of inspecting account
codes directly.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# Patterns that indicate a hard-coded code-range check
_PATTERNS = [
    # account_code starts with digit
    re.compile(r"""account_code\s*(?:LIKE|ILIKE)\s*['"][0-9]""", re.IGNORECASE),
    # substring/LEFT of account_code or account_number
    re.compile(r"""(?:LEFT|SUBSTR|SUBSTRING)\s*\(\s*(?:a\.)?(?:account_code|account_number)""", re.IGNORECASE),
    # account_number comparison with LIKE
    re.compile(r"""account_number\s*(?:LIKE|ILIKE)\s*['"][0-9]""", re.IGNORECASE),
    # Python string startswith on account codes
    re.compile(r"""(?:account_code|account_number)\.startswith\s*\(\s*['"][0-9]"""),
    # Direct digit prefix comparison: account_code[0] == '1'
    re.compile(r"""(?:account_code|account_number)\[0\]\s*(?:==|!=|in)\s*['"][0-9]"""),
    # BETWEEN on account codes
    re.compile(r"""account_(?:code|number)\s+BETWEEN\s+['"]?[0-9]""", re.IGNORECASE),
    # CASE WHEN LEFT(account_number, 1) — the seed heuristic
    re.compile(r"""CASE\s+LEFT\s*\(\s*(?:a\.)?account_number""", re.IGNORECASE),
]

# Directories to scan
_SCAN_DIRS = [
    BACKEND / "services" / "reports",
    BACKEND / "routers" / "reports",
]

# Files that are allowed to have code-range checks (e.g., the classifier seed migration)
_ALLOWED_FILES: set[Path] = set()


def main() -> int:
    violations: list[tuple[Path, int, str]] = []

    for scan_dir in _SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for pyfile in scan_dir.rglob("*.py"):
            if pyfile in _ALLOWED_FILES:
                continue
            try:
                source = pyfile.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for lineno, line in enumerate(source.splitlines(), start=1):
                for pattern in _PATTERNS:
                    if pattern.search(line):
                        violations.append((pyfile, lineno, line.strip()))
                        break  # one violation per line

    if violations:
        print(
            f"[check_account_code_ranges] FAIL — {len(violations)} hard-coded "
            f"code-range check(s) found:\n",
            file=sys.stderr,
        )
        for filepath, lineno, line in violations:
            rel = filepath.relative_to(ROOT)
            print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
        print(
            "\nAll report modules MUST use "
            "backend.services.account_classifier.classify() or "
            "classify_many() instead of inspecting account codes directly.\n",
            file=sys.stderr,
        )
        return 1

    print("[check_account_code_ranges] PASS — no hard-coded code-range checks found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
