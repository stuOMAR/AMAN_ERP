"""T3.7 (audit #21,#22,#23,#25,#26,#137) — audit_logs hash chain + DB triggers.

Pure-Python tests for the hash helper and the canonical-payload envelope,
plus an integration test that applies migration 0017 against the test DB
and verifies:

    1. Two log_activity inserts form a valid hash chain (prev_hash, hash,
       chain_seq are correct).
    2. Direct UPDATE/DELETE against audit_logs is rejected at the DB layer.
    3. Setting ``audit_logs.allow_admin_op`` lets retention jobs UPDATE
       only ``is_archived``/``archived_at`` (chain payload columns are
       still rejected).
    4. ``utils.permissions._log_permission_denied`` and
       ``log_permission_change`` go through ``log_activity`` (no more
       inline INSERT bypassing the chain).
"""
import json
import os
import urllib.parse as urlparse
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import pytest

from utils.audit import compute_audit_hash, make_change_details, log_activity


# ===== Pure unit tests ====================================================

def test_compute_audit_hash_is_deterministic():
    h1 = compute_audit_hash(
        prev_hash="", chain_seq=1,
        user_id=1, username="bbbb", action="login",
        resource_type=None, resource_id=None,
        details_json="{}", ip_address="127.0.0.1", branch_id=None,
        created_at_iso="2026-05-01T00:00:00.000000Z",
    )
    h2 = compute_audit_hash(
        prev_hash="", chain_seq=1,
        user_id=1, username="bbbb", action="login",
        resource_type=None, resource_id=None,
        details_json="{}", ip_address="127.0.0.1", branch_id=None,
        created_at_iso="2026-05-01T00:00:00.000000Z",
    )
    assert h1 == h2
    assert len(h1) == 64


def test_compute_audit_hash_changes_on_any_field():
    base = dict(
        prev_hash="", chain_seq=1,
        user_id=1, username="x", action="a",
        resource_type=None, resource_id=None,
        details_json="{}", ip_address=None, branch_id=None,
        created_at_iso="2026-05-01T00:00:00.000000Z",
    )
    h0 = compute_audit_hash(**base)
    for field, val in [
        ("user_id", 2), ("username", "y"), ("action", "b"),
        ("resource_type", "x"), ("resource_id", "1"),
        ("details_json", '{"k":1}'), ("ip_address", "1.2.3.4"),
        ("branch_id", 9), ("chain_seq", 2),
        ("prev_hash", "deadbeef"),
        ("created_at_iso", "2026-05-01T00:00:00.000001Z"),
    ]:
        variant = dict(base)
        variant[field] = val
        assert compute_audit_hash(**variant) != h0, f"hash unchanged on {field}"


def test_make_change_details_envelope():
    out = make_change_details({"a": 1}, {"a": 2}, reason="audit")
    assert out == {"old": {"a": 1}, "new": {"a": 2}, "reason": "audit"}


def test_make_change_details_handles_none():
    assert make_change_details(None, {"x": 1}) == {"old": {}, "new": {"x": 1}}


# ===== Integration tests against the test DB =============================

DB_URL = os.environ.get(
    "AMAN_TEST_DB_URL",
    "postgresql://aman:YourPassword123%21%40%23@localhost:5432/aman_d24b1b1c",
)


def _connect():
    p = urlparse.urlparse(DB_URL)
    return psycopg2.connect(
        host=p.hostname, port=p.port, user=p.username,
        password=urlparse.unquote(p.password or ""),
        dbname=p.path[1:],
    )


@pytest.fixture(scope="module")
def db_with_chain():
    """Apply migration 0017 DDL to the test DB (idempotent), yield a conn."""
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    # Replicate migration 0017 (idempotent guards).
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute("""
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64),
            ADD COLUMN IF NOT EXISTS hash      VARCHAR(64),
            ADD COLUMN IF NOT EXISTS chain_seq BIGINT
    """)
    # Backfill any NULL hash rows by chain_seq.
    cur.execute("""
        DO $$
        DECLARE r RECORD; seq BIGINT := 0; prev TEXT := '';
                payload TEXT; new_hash TEXT;
        BEGIN
            IF EXISTS (SELECT 1 FROM audit_logs WHERE hash IS NULL) THEN
                FOR r IN SELECT * FROM audit_logs ORDER BY id LOOP
                    seq := seq + 1;
                    payload := concat_ws('|',
                        prev, seq::TEXT,
                        COALESCE(r.user_id::TEXT, ''),
                        COALESCE(r.username, ''),
                        COALESCE(r.action, ''),
                        COALESCE(r.resource_type, ''),
                        COALESCE(r.resource_id, ''),
                        COALESCE(r.details::TEXT, '{}'),
                        COALESCE(r.ip_address, ''),
                        COALESCE(r.branch_id::TEXT, ''),
                        COALESCE(to_char(r.created_at AT TIME ZONE 'UTC',
                                 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), '')
                    );
                    new_hash := encode(digest(payload, 'sha256'), 'hex');
                    UPDATE audit_logs SET prev_hash=prev, hash=new_hash, chain_seq=seq WHERE id=r.id;
                    prev := new_hash;
                END LOOP;
            END IF;
        END $$
    """)
    cur.execute("ALTER TABLE audit_logs ALTER COLUMN hash SET NOT NULL")
    cur.execute("ALTER TABLE audit_logs ALTER COLUMN chain_seq SET NOT NULL")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_logs_chain_seq ON audit_logs(chain_seq)")
    cur.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_immutable_fn() RETURNS trigger AS $$
        DECLARE allowed TEXT;
        BEGIN
            BEGIN allowed := current_setting('audit_logs.allow_admin_op', true);
            EXCEPTION WHEN OTHERS THEN allowed := NULL;
            END;
            IF allowed IS NULL OR allowed = '' THEN
                RAISE EXCEPTION 'audit_logs is append-only (T3.7)';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.id IS DISTINCT FROM NEW.id OR OLD.user_id IS DISTINCT FROM NEW.user_id
                   OR OLD.username IS DISTINCT FROM NEW.username OR OLD.action IS DISTINCT FROM NEW.action
                   OR OLD.resource_type IS DISTINCT FROM NEW.resource_type
                   OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
                   OR OLD.details IS DISTINCT FROM NEW.details
                   OR OLD.ip_address IS DISTINCT FROM NEW.ip_address
                   OR OLD.branch_id IS DISTINCT FROM NEW.branch_id
                   OR OLD.created_at IS DISTINCT FROM NEW.created_at
                   OR OLD.prev_hash IS DISTINCT FROM NEW.prev_hash
                   OR OLD.hash IS DISTINCT FROM NEW.hash
                   OR OLD.chain_seq IS DISTINCT FROM NEW.chain_seq THEN
                    RAISE EXCEPTION 'audit_logs UPDATE limited to is_archived/archived_at';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
    """)
    cur.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
    cur.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs")
    cur.execute("CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn()")
    cur.execute("CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn()")
    yield conn
    conn.close()


class _DBConnAdapter:
    """Thin wrapper exposing SQLAlchemy-like .execute(text, params) on
    a raw psycopg2 connection so log_activity can be reused unchanged."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, stmt, params=None):
        sql = str(stmt)
        # Convert :name placeholders to %(name)s.
        import re
        sql = re.sub(r":(\w+)", r"%(\1)s", sql)
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor)
        cur.execute(sql, params or {})

        class _Result:
            def __init__(self, c):
                self.c = c
            def scalar(self):
                if self.c.description is None:
                    return None
                row = self.c.fetchone()
                return None if row is None else row[0]
            def fetchone(self):
                return None if self.c.description is None else self.c.fetchone()
            def fetchall(self):
                return [] if self.c.description is None else self.c.fetchall()

        return _Result(cur)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


@pytest.fixture
def chain_conn(db_with_chain):
    """Yield a wrapped connection inside a savepoint that's rolled back."""
    raw = _connect()
    raw.autocommit = False
    yield _DBConnAdapter(raw)
    raw.rollback()
    raw.close()


def test_log_activity_builds_chain(chain_conn):
    log_activity(chain_conn, user_id=None, username="t1", action="x.a", details={"a": 1})
    log_activity(chain_conn, user_id=None, username="t2", action="x.b", details={"b": 2})
    rows = chain_conn.execute(
        "SELECT chain_seq, prev_hash, hash, action FROM audit_logs ORDER BY chain_seq DESC LIMIT 2"
    ).fetchall()
    # rows[0] is the newest (x.b), rows[1] is x.a
    assert rows[0].action == "x.b"
    assert rows[1].action == "x.a"
    # x.b's prev_hash must equal x.a's hash
    assert (rows[0].prev_hash or "") == (rows[1].hash or "")
    assert rows[0].chain_seq == rows[1].chain_seq + 1


def test_direct_update_rejected(chain_conn):
    log_activity(chain_conn, user_id=None, username="t", action="will.not.change")
    with pytest.raises(psycopg2.errors.RaiseException):
        chain_conn.execute(
            "UPDATE audit_logs SET action = 'tampered' WHERE chain_seq = "
            "(SELECT MAX(chain_seq) FROM audit_logs)"
        )


def test_direct_delete_rejected(chain_conn):
    log_activity(chain_conn, user_id=None, username="t", action="will.not.delete")
    with pytest.raises(psycopg2.errors.RaiseException):
        chain_conn.execute(
            "DELETE FROM audit_logs WHERE chain_seq = (SELECT MAX(chain_seq) FROM audit_logs)"
        )


def test_archival_flag_allows_only_archive_columns(chain_conn):
    log_activity(chain_conn, user_id=None, username="t", action="archivable")
    # Archive: should succeed.
    chain_conn.execute("SET LOCAL audit_logs.allow_admin_op = 'retention'")
    chain_conn.execute(
        "UPDATE audit_logs SET is_archived = TRUE, archived_at = NOW() "
        "WHERE chain_seq = (SELECT MAX(chain_seq) FROM audit_logs)"
    )
    # Even with the flag, mutating the payload must still be rejected.
    chain_conn.execute("SET LOCAL audit_logs.allow_admin_op = 'retention'")
    with pytest.raises(psycopg2.errors.RaiseException):
        chain_conn.execute(
            "UPDATE audit_logs SET action = 'tampered' "
            "WHERE chain_seq = (SELECT MAX(chain_seq) FROM audit_logs)"
        )


def test_no_inline_inserts_bypass_chain():
    """T3.7 (audit #137): permissions.py must not contain any direct
    INSERT into audit_logs anymore — those bypassed the unified
    log_activity helper and the hash chain.
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "utils" / "permissions.py"
    text = src.read_text(encoding="utf-8")
    assert "INSERT INTO audit_logs" not in text, (
        "utils/permissions.py still has a direct INSERT into audit_logs"
    )
