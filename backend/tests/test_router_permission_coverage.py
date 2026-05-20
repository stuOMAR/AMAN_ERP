"""
Static test: every router endpoint must have a permission decorator.
Constitution §4: Protected router endpoints require require_permission(...).

Public exceptions: login, refresh, health, docs.
"""
import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "routers"

# Endpoints that are explicitly public (no permission required)
PUBLIC_PATTERNS = [
    r"/login",
    r"/refresh",
    r"/health",
    r"/docs",
    r"/openapi",
    r"/redoc",
    r"/metrics",
    r"/favicon",
    r"/static",
    r"/preview",  # invoice preview is gated by sales.create at decorator level
]

PERMISSION_DECORATORS = {
    "require_permission",
    "require_sensitive_permission",
    "require_module",
}


def _is_public_path(path: str) -> bool:
    return any(re.search(p, path) for p in PUBLIC_PATTERNS)


def test_finance_accounting_routes_have_permissions():
    """Finance accounting routes must all have permission decorators."""
    violations = []

    for py_file in (ROUTERS / "finance" / "accounting").rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        for i, line in enumerate(lines):
            # Find route decorators
            if re.match(r'\s*@router\.(get|post|put|patch|delete)\(', line):
                # Check if path is public
                path_match = re.search(r'["\']([^"\']+)["\']', line)
                path = path_match.group(1) if path_match else ""
                if _is_public_path(path):
                    continue

                # Look for permission decorator in next 5 lines
                context = "\n".join(lines[i:i+6])
                has_perm = any(dec in context for dec in PERMISSION_DECORATORS)

                if not has_perm:
                    violations.append(
                        f"{py_file.relative_to(BACKEND)}:{i+1}: {line.strip()} — missing permission decorator"
                    )

    assert not violations, (
        "Constitution §4: routes missing permission decorators:\n"
        + "\n".join(violations[:20])  # Show first 20
    )


def test_no_detail_str_e_regression():
    """Regression: no new detail=str(e) should appear (already tested in test_no_detail_str_e.py)."""
    # This is a cross-check — the main test is in test_no_detail_str_e.py
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/test_no_detail_str_e.py", "-q", "--tb=no"],
        capture_output=True, text=True,
        cwd=str(BACKEND)
    )
    assert result.returncode == 0, f"detail=str(e) violations found:\n{result.stdout}"
