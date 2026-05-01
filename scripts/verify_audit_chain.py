#!/usr/bin/env python3
"""T3.7 (audit #22): CLI verifier for the audit_logs hash chain.

Reads every row of ``audit_logs`` (from a tenant DB) in chain_seq order
and recomputes ``hash`` from ``prev_hash`` and the canonical payload.
Reports the first row whose stored hash does not match — any mismatch
means the row, or one preceding it, was tampered with.

Usage::

    python scripts/verify_audit_chain.py <tenant_db_name>

Returns 0 on a valid chain, 1 on the first mismatch (with details).
The verifier is read-only.
"""
from __future__ import annotations

import hashlib
import os
import sys

from sqlalchemy import create_engine, text


def compute_audit_hash(
    *, prev_hash, chain_seq, user_id, username, action, resource_type,
    resource_id, details_json, ip_address, branch_id, created_at_iso,
):
    """Inline copy of utils.audit.compute_audit_hash so the CLI verifier
    does not depend on the FastAPI app's full config bootstrap."""
    parts = [
        prev_hash or "",
        str(chain_seq),
        "" if user_id is None else str(user_id),
        username or "",
        action or "",
        resource_type or "",
        resource_id or "",
        details_json or "{}",
        ip_address or "",
        "" if branch_id is None else str(branch_id),
        created_at_iso or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _format_ts(ts) -> str:
    """Match Postgres `to_char(... 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`."""
    if ts is None:
        return ""
    # ts is a tz-aware datetime when SQLAlchemy returns TIMESTAMPTZ.
    if ts.tzinfo is not None:
        from datetime import timezone
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond:06d}Z"


def verify(db_name: str) -> int:
    pg_user = os.environ.get("PGUSER", "postgres")
    pg_pwd = os.environ.get("PGPASSWORD", "")
    pg_host = os.environ.get("PGHOST", "localhost")
    pg_port = os.environ.get("PGPORT", "5432")
    from urllib.parse import quote_plus
    auth = f"{quote_plus(pg_user)}:{quote_plus(pg_pwd)}" if pg_pwd else quote_plus(pg_user)
    url = f"postgresql+psycopg2://{auth}@{pg_host}:{pg_port}/{db_name}"
    engine = create_engine(url)

    prev = ""
    seq_expected = 0
    bad = 0

    with engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT id, user_id, username, action, resource_type, resource_id,
                   details::text AS details_text, ip_address, branch_id,
                   created_at, prev_hash, hash, chain_seq
            FROM audit_logs
            ORDER BY chain_seq ASC NULLS LAST, id ASC
            """
        )).mappings().all()

    if not rows:
        print(f"[verify_audit_chain] {db_name}: no rows.")
        return 0

    for r in rows:
        seq_expected += 1
        # CHAR(64) columns pad with spaces — strip so VARCHAR/CHAR
        # storage are interchangeable for verification.
        stored_prev = (r["prev_hash"] or "").rstrip()
        stored_hash = (r["hash"] or "").rstrip()
        if r["chain_seq"] != seq_expected:
            print(
                f"[verify_audit_chain] FAIL id={r['id']}: "
                f"chain_seq={r['chain_seq']} expected={seq_expected}"
            )
            bad += 1
            return 1
        if stored_prev != prev:
            print(
                f"[verify_audit_chain] FAIL id={r['id']} seq={r['chain_seq']}: "
                f"prev_hash mismatch (stored={stored_prev!r}, expected={prev!r})"
            )
            return 1

        recomputed = compute_audit_hash(
            prev_hash=prev,
            chain_seq=r["chain_seq"],
            user_id=r["user_id"],
            username=r["username"],
            action=r["action"],
            resource_type=r["resource_type"],
            resource_id=r["resource_id"],
            details_json=r["details_text"] or "{}",
            ip_address=r["ip_address"],
            branch_id=r["branch_id"],
            created_at_iso=_format_ts(r["created_at"]),
        )
        if recomputed != stored_hash:
            print(
                f"[verify_audit_chain] FAIL id={r['id']} seq={r['chain_seq']}: "
                f"hash mismatch (stored={stored_hash}, recomputed={recomputed})"
            )
            return 1
        prev = stored_hash

    print(
        f"[verify_audit_chain] OK {db_name}: {len(rows)} rows, "
        f"chain head seq={seq_expected}, head hash={prev}"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: verify_audit_chain.py <tenant_db_name>", file=sys.stderr)
        sys.exit(2)
    sys.exit(verify(sys.argv[1]))
