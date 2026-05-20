"""
Static regression test: no router file may use detail=str(e).
Constitution §4: 'raise HTTPException(detail=str(e)) is forbidden.'
"""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "routers"


def test_no_detail_str_e_in_routers():
    """Assert no router file contains detail=str(e) pattern."""
    violations = []
    pattern = re.compile(r'detail\s*=\s*str\s*\(\s*e\s*\)')
    
    for py_file in ROUTERS.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                violations.append(f"{py_file.relative_to(BACKEND)}:{lineno}: {line.strip()}")
    
    assert not violations, (
        "Constitution §4 violation — detail=str(e) found in routers:\n"
        + "\n".join(violations)
    )


def test_no_detail_str_e_in_services():
    """Assert no service file contains detail=str(e) pattern."""
    violations = []
    pattern = re.compile(r'detail\s*=\s*str\s*\(\s*e\s*\)')
    services_dir = BACKEND / "services"
    
    for py_file in services_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                violations.append(f"{py_file.relative_to(BACKEND)}:{lineno}: {line.strip()}")
    
    assert not violations, (
        "Constitution §4 violation — detail=str(e) found in services:\n"
        + "\n".join(violations)
    )
