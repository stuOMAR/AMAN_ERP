"""
CLI entry for sensitive-permission discovery.

Usage:
    python -m backend.scripts.permissions_discover --strict
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Sensitive-permission discovery")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any sensitive route pattern is uncovered",
    )
    args = parser.parse_args()

    from services.permissions.sensitive import discover_sensitive_routes

    uncovered = discover_sensitive_routes(app=None, strict=args.strict)

    if uncovered:
        print(f"permissions_discover: {len(uncovered)} uncovered patterns:")
        for g in uncovered:
            print(f"  ✗ {g}")
        if args.strict:
            return 1
    else:
        print("permissions_discover: OK — all sensitive routes covered")

    return 0


if __name__ == "__main__":
    sys.exit(main())
