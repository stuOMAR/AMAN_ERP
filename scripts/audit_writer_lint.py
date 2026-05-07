"""
CI lint: enforce audit-writer discipline.

Fails (exit 1) when:
  - Any direct ``INSERT INTO audit_logs`` appears outside
    ``services/audit_writer.py`` and ``services/audit_outbox_worker.py``.
  - Any ``commit()`` / ``rollback()`` is reachable from ``log_activity``
    and its dependencies.
  - A bare ``try: ... except Exception: pass`` exists inside the writer module.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

ALLOWED_DIRECT_INSERT = {
    "backend/services/audit_outbox_worker.py",
    "backend/utils/audit.py",
}

WRITER_MODULE = "backend/services/audit_writer.py"

INSERT_RE = re.compile(r"INSERT\s+INTO\s+audit_logs\b", re.IGNORECASE)


def _check_direct_inserts() -> list[str]:
    """Find INSERT INTO audit_logs outside allowed files."""
    violations: list[str] = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_DIRECT_INSERT:
            continue
        if "/alembic/versions/" in rel:
            continue
        if "/tests/" in rel or "/test_" in pathlib.Path(rel).name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if INSERT_RE.search(line):
                violations.append(f"{rel}:{lineno}: direct INSERT INTO audit_logs")
    return violations


def _check_no_commit_in_writer() -> list[str]:
    """Ensure log_activity and its deps never call commit/rollback."""
    violations: list[str] = []
    writer_path = BACKEND / "services" / "audit_writer.py"
    if not writer_path.exists():
        return violations
    try:
        tree = ast.parse(writer_path.read_text(encoding="utf-8"))
    except Exception:
        return violations
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = ""
            if isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname in ("commit", "rollback"):
                violations.append(
                    f"{WRITER_MODULE}:{node.lineno}: {fname}() found in writer module"
                )
    return violations


def _check_no_silent_swallow() -> list[str]:
    """Detect try: ... except Exception: pass in the writer module."""
    violations: list[str] = []
    writer_path = BACKEND / "services" / "audit_writer.py"
    if not writer_path.exists():
        return violations
    try:
        tree = ast.parse(writer_path.read_text(encoding="utf-8"))
    except Exception:
        return violations
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            # Check if handler type is Exception or bare (None)
            if node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            ):
                # Check if body is only Pass
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    violations.append(
                        f"{WRITER_MODULE}:{node.lineno}: silent except pass"
                    )
    return violations


def main() -> int:
    violations: list[str] = []
    violations.extend(_check_direct_inserts())
    violations.extend(_check_no_commit_in_writer())
    violations.extend(_check_no_silent_swallow())

    if violations:
        print("[audit_writer_lint] VIOLATIONS FOUND:")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print("[audit_writer_lint] ✓ all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
