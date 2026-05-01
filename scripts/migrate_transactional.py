#!/usr/bin/env python3
"""
T6.1 migration helper — converts the boilerplate try/finally pattern to
`with transactional(company_id) as db:` across router files.

Pattern A (read-only — no commit/rollback in body):
    db = get_db_connection(EXPR)
    try:
        BODY
    finally:
        db.close()

Pattern B (write — manual commit/rollback):
    db = get_db_connection(EXPR)
    try:
        BODY
        db.commit()
        return ...
    except [Opt]Exception [as e]:
        db.rollback()
        raise ...
    finally:
        db.close()

Both become:
    with transactional(EXPR) as db:
        BODY  # (db.commit() removed; rollback/close handled by ctx mgr)

Usage:
    python scripts/migrate_transactional.py backend/routers/dashboard.py [--dry-run]
"""

import re
import sys
import pathlib
import argparse

# ── helpers ────────────────────────────────────────────────────────────────────

def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _reindent(lines: list[str], old_indent: int, new_indent: int) -> list[str]:
    delta = new_indent - old_indent
    result = []
    for line in lines:
        if line.strip() == "":
            result.append("\n")
        elif delta >= 0:
            result.append(" " * delta + line)
        else:
            stripped = line[abs(delta):]
            result.append(stripped)
    return result


# ── main transform ─────────────────────────────────────────────────────────────

def migrate(source: str) -> tuple[str, int]:
    """Return (new_source, change_count).

    Handles Pattern A ONLY (safe — no except blocks at the outer try level):

        db = get_db_connection(EXPR)    ← removed
        try:                             ← replaced with `with transactional(EXPR) as db:`
            BODY                         ← unchanged indentation
        finally:                         ← removed
            db.close()                   ← removed

    Pattern B (try/except/finally) is intentionally skipped to avoid
    orphaning except clauses. Migrate those manually.
    """
    lines = source.splitlines(keepends=True)
    out = []
    i = 0
    changes = 0

    while i < len(lines):
        line = lines[i]
        # Match: `    db = get_db_connection(EXPR)` (variable indent)
        m = re.match(r'^( +)(db|conn) = get_db_connection\((.+)\)\s*$', line)
        if not m:
            out.append(line)
            i += 1
            continue

        base_indent = m.group(1)
        var = m.group(2)
        expr = m.group(3).strip()
        base_spaces = len(base_indent)

        # Next non-blank line must be `try:` at the same indent
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j >= len(lines) or lines[j].rstrip() != f"{base_indent}try:":
            out.append(line)
            i += 1
            continue

        # Scan from try: body to find finally: db.close()
        # Track whether there are except blocks at the outer level.
        k = j + 1
        finally_idx = None
        close_idx = None
        has_except_at_level = False

        while k < len(lines):
            stripped = lines[k].strip()
            if not stripped:
                k += 1
                continue
            this_indent = _leading_spaces(lines[k])

            if this_indent == base_spaces:
                if stripped.startswith("except"):
                    has_except_at_level = True
                    # Don't break — keep scanning to find `finally:`
                elif stripped == "finally:":
                    finally_idx = k
                    k2 = k + 1
                    while k2 < len(lines) and not lines[k2].strip():
                        k2 += 1
                    if k2 < len(lines) and f"{var}.close()" in lines[k2]:
                        close_idx = k2
                    break
                elif stripped.startswith(("def ", "class ", "@")):
                    break
            elif this_indent < base_spaces:
                break
            k += 1

        if has_except_at_level or finally_idx is None or close_idx is None:
            # Pattern B — handle if except blocks are safe (only rollback+raise+log)
            if not has_except_at_level or finally_idx is None or close_idx is None:
                out.append(line)
                i += 1
                continue
            # Scan except blocks to check safety
            direct_body_indent = base_spaces + 4
            safe_prefixes = (
                f"{var}.rollback()", f"{var}.commit()",
                "raise", "logger.", "logging.", "pass",
                "return",  # returning from except is safe (function ends)
            )
            kk = j + 1
            except_bodies_safe = True
            while kk < finally_idx:
                sl = lines[kk].strip()
                si = _leading_spaces(lines[kk]) if sl else direct_body_indent + 1
                if si == base_spaces and sl.startswith("except"):
                    # Check lines of this except block
                    kk += 1
                    while kk < finally_idx:
                        bl = lines[kk]
                        bls = bl.strip()
                        bli = _leading_spaces(bl) if bls else direct_body_indent + 1
                        if bls and bli <= base_spaces:
                            break  # next clause at same level
                        if bls:
                            if not any(bls.startswith(p) for p in safe_prefixes):
                                except_bodies_safe = False
                                break
                        kk += 1
                    if not except_bodies_safe:
                        break
                else:
                    kk += 1
            if not except_bodies_safe:
                out.append(line)
                i += 1
                continue
            # Safe Pattern B: emit `with transactional(...) as db:` wrapping the
            # entire try/except block (we keep try/except, just remove finally).
            # Also remove standalone commit from main body; replace rollback in
            # except with `pass` to avoid empty except blocks.
            out.append(f"{base_indent}with transactional({expr}) as {var}:\n")
            # Emit the outer try: (keeps except blocks intact)
            out.append(f"{base_indent}    try:\n")
            in_except_at_outer = False
            for bl in lines[j + 1 : finally_idx]:
                bls = bl.strip()
                bli = _leading_spaces(bl) if bls else direct_body_indent + 1
                # Track entering/exiting outer-level except blocks
                if bli == base_spaces and bls.startswith("except"):
                    in_except_at_outer = True
                    out.append("    " + bl)  # re-indent 4 more spaces
                    continue
                elif bli == base_spaces and bls:
                    in_except_at_outer = False
                # Remove commit from main body
                if not in_except_at_outer and bli == direct_body_indent and bls == f"{var}.commit()":
                    continue
                # Replace rollback with pass in except blocks
                if in_except_at_outer and bli == direct_body_indent and bls == f"{var}.rollback()":
                    out.append("    " + bl.replace(f"{var}.rollback()", "pass"))
                    continue
                out.append("    " + bl)  # add 4-space indent for `with` level
            changes += 1
            i = close_idx + 1
            continue
        # Emit `with transactional(expr) as db:` in place of `try:`
        # (db = get_db_connection(...) line is dropped)
        # Body lines keep their original indentation (no change needed).
        out.append(f"{base_indent}with transactional({expr}) as {var}:\n")
        # Emit body lines (between `try:\n` and `finally:`) removing manual commits.
        # Only remove commit/rollback at the direct body level (base_spaces + 4).
        # Do NOT remove them when inside nested except/try blocks (deeper indent).
        direct_body_indent = base_spaces + 4
        for bl in lines[j + 1 : finally_idx]:
            stripped_bl = bl.strip()
            bl_indent = _leading_spaces(bl) if stripped_bl else direct_body_indent + 1
            if bl_indent == direct_body_indent and stripped_bl in (f"{var}.commit()", f"{var}.rollback()"):
                continue
            out.append(bl)
        changes += 1

        # Skip past db.close() line
        i = close_idx + 1
        continue

    return "".join(out), changes


# ── import injection ───────────────────────────────────────────────────────────

def ensure_import(source: str) -> str:
    """Inject `from utils.tx import transactional` if not present."""
    if "from utils.tx import transactional" in source:
        return source
    # Insert after the last 'from database import' or 'from routers.auth import'
    lines = source.split("\n")
    insert_at = 0
    for idx, line in enumerate(lines):
        if line.startswith("from database import") or line.startswith("from routers.auth import"):
            insert_at = idx + 1
    lines.insert(insert_at, "from utils.tx import transactional")
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Migrate router files to use transactional()")
    parser.add_argument("files", nargs="+", help="Router .py files to migrate")
    parser.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    args = parser.parse_args()

    total = 0
    for path_str in args.files:
        path = pathlib.Path(path_str)
        if not path.exists():
            print(f"[SKIP] {path} not found", file=sys.stderr)
            continue
        source = path.read_text()
        new_source, count = migrate(source)
        if count > 0:
            new_source = ensure_import(new_source)
        print(f"[{path.name}] {count} blocks migrated")
        total += count
        if count > 0 and not args.dry_run:
            path.write_text(new_source)
    print(f"\nTotal: {total} blocks migrated")


if __name__ == "__main__":
    main()
