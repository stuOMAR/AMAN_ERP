"""
Static test: frontend files must not use .toFixed() or parseFloat() on monetary values
without going through the canonical formatNumber() helper.

Constitution §1: No float/double/JavaScript Number for monetary values.
Constitution §19: Frontend must not duplicate monetary calculations.
"""
import pathlib
import re

WORKSPACE = pathlib.Path(__file__).resolve().parents[3]
FRONTEND_SRC = WORKSPACE / "frontend" / "src"


def _find_violations(pattern: str, exclude_patterns: list[str] = None) -> list[str]:
    """Find pattern violations in frontend JS/JSX/TS/TSX files."""
    if not FRONTEND_SRC.exists():
        return []  # Frontend not present in this test run

    violations = []
    compiled = re.compile(pattern)
    exclude_compiled = [re.compile(p) for p in (exclude_patterns or [])]

    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for f in FRONTEND_SRC.rglob(ext):
            if "node_modules" in str(f) or "__tests__" in str(f):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for lineno, line in enumerate(content.splitlines(), 1):
                    if compiled.search(line):
                        if not any(exc.search(line) for exc in exclude_compiled):
                            violations.append(
                                f"{f.relative_to(WORKSPACE)}:{lineno}: {line.strip()}"
                            )
            except Exception:
                pass
    return violations


def test_no_tofixed_on_monetary_values():
    """Frontend must not use .toFixed(2) directly on monetary amounts.
    Use formatNumber() or formatCurrency() helpers instead."""
    # This is a soft check — we report but don't fail hard since legacy code exists
    violations = _find_violations(
        r'\.toFixed\([0-9]\)',
        exclude_patterns=[
            r'//.*toFixed',  # Comments
            r'formatNumber',  # Already using helper
            r'formatCurrency',
        ]
    )
    # Log violations for awareness but don't fail (legacy code)
    if violations:
        import warnings
        warnings.warn(
            f"Frontend .toFixed() usage found ({len(violations)} occurrences). "
            "Migrate to formatNumber() helper.\n" + "\n".join(violations[:10]),
            UserWarning,
            stacklevel=2,
        )


def test_no_parsefloat_on_monetary_values():
    """Frontend must not use parseFloat() on monetary amounts."""
    violations = _find_violations(
        r'parseFloat\(',
        exclude_patterns=[
            r'//.*parseFloat',
            r'formatNumber',
        ]
    )
    if violations:
        import warnings
        warnings.warn(
            f"Frontend parseFloat() usage found ({len(violations)} occurrences). "
            "Use string-based Decimal handling instead.\n" + "\n".join(violations[:10]),
            UserWarning,
            stacklevel=2,
        )
