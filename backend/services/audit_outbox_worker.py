"""
Audit outbox flush worker.

Reads pending rows from ``audit_outbox``, inserts them into ``audit_logs``
(maintaining the tamper-evident hash chain), and marks them flushed.

Designed to run periodically via APScheduler or as a dedicated worker.

Contract: see specs/022-audit-security-finance-integrity/contracts/audit-writer.md
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 200
_DEFAULT_SLA_SECONDS = 60
_MAX_ATTEMPTS = 10


@dataclass
class FlushReport:
    tenant_id: str | None
    attempted: int
    flushed: int
    failed: int
    elapsed_ms: float


def _get_setting(conn, key: str, default):
    """Read a company_settings value, returning *default* on miss."""
    try:
        row = conn.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = :k"),
            {"k": key},
        ).scalar()
        if row is None:
            return default
        if isinstance(default, int):
            return int(row)
        return row
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return default


def _payload_legacy(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    legacy = payload.get("legacy")
    if isinstance(legacy, dict):
        return legacy
    return payload


def _safe_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flush_tenant(conn, tenant_id: str | None, batch_size: int, sla_seconds: int) -> FlushReport:
    """Flush up to *batch_size* rows for one tenant."""
    from utils.audit import compute_audit_hash  # reuse hash helper

    t0 = time.monotonic()
    rows = conn.execute(
        text(
            """
                 SELECT id, tenant_id, actor_id, action, entity_type, entity_id,
                   payload, critical, enqueued_at
              FROM audit_outbox
             WHERE flushed_at IS NULL
               AND attempt_count < :max_att
             ORDER BY enqueued_at
             LIMIT :n
               FOR UPDATE SKIP LOCKED
            """
        ),
        {"n": batch_size, "max_att": _MAX_ATTEMPTS},
    ).fetchall()

    flushed = failed = 0
    for r in rows:
        outbox_id = r[0]
        try:
            conn.execute(text("SAVEPOINT flush_row"))
            # Fetch current hash chain tail.
            payload = r[6] or {}
            legacy = _payload_legacy(payload)
            username = legacy.get("_legacy_username")
            branch_id = _safe_int(legacy.get("_legacy_branch_id"))
            ip_address = legacy.get("ip_address")
            if not ip_address and isinstance(legacy.get("request"), dict):
                ip_address = legacy["request"].get("ip_address")

            tail = conn.execute(
                text(
                    "SELECT chain_seq, hash FROM audit_logs "
                    "ORDER BY chain_seq DESC NULLS LAST LIMIT 1"
                )
            ).fetchone()
            prev_seq = (tail.chain_seq if tail and tail.chain_seq else 0) or 0
            prev_hash = (tail.hash if tail and tail.hash else "") or ""
            new_seq = int(prev_seq) + 1

            now = datetime.now(timezone.utc)
            created_at_iso = (
                now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
            )
            details_json = json.dumps(payload, default=str, sort_keys=True)

            new_hash = compute_audit_hash(
                prev_hash=prev_hash,
                chain_seq=new_seq,
                user_id=r[2],
                username=username,
                action=r[3],
                resource_type=r[4],
                resource_id=str(r[5]) if r[5] is not None else None,
                details_json=details_json,
                ip_address=ip_address,
                branch_id=branch_id,
                created_at_iso=created_at_iso,
            )

            conn.execute(
                text(
                    """
                    INSERT INTO audit_logs
                        (tenant_id, user_id, username, action, resource_type, resource_id,
                         details, ip_address, branch_id, created_at,
                         prev_hash, hash, chain_seq, critical)
                    VALUES
                        (:tenant_id, :uid, :username, :act, :rtype, :rid,
                         CAST(:det AS JSONB), :ip, :branch_id, :now,
                         :prev, :h, :seq, :crit)
                    """
                ),
                {
                    "tenant_id": str(r[1] or tenant_id or "unknown"),
                    "uid": r[2],
                    "username": username,
                    "act": r[3],
                    "rtype": r[4],
                    "rid": str(r[5]) if r[5] is not None else None,
                    "det": details_json,
                    "ip": ip_address,
                    "branch_id": branch_id,
                    "now": now,
                    "prev": prev_hash or None,
                    "h": new_hash,
                    "seq": new_seq,
                    "crit": r[7],
                },
            )

            conn.execute(
                text(
                    "UPDATE audit_outbox SET flushed_at = clock_timestamp() "
                    "WHERE id = :id"
                ),
                {"id": outbox_id},
            )
            conn.execute(text("RELEASE SAVEPOINT flush_row"))
            flushed += 1
        except Exception:
            try:
                conn.execute(text("ROLLBACK TO SAVEPOINT flush_row"))
            except Exception:
                pass
            logger.error("audit_outbox_worker: failed to flush outbox id=%s", outbox_id)
            conn.execute(
                text(
                    "UPDATE audit_outbox "
                    "SET attempt_count = attempt_count + 1, last_error = :err "
                    "WHERE id = :id"
                ),
                {"err": "flush_failed", "id": outbox_id},
            )
            failed += 1

    conn.commit()
    elapsed = (time.monotonic() - t0) * 1000

    if elapsed > sla_seconds * 1000:
        logger.warning(
            "audit_outbox_worker: SLA breach for tenant %s — %.0fms > %ds",
            tenant_id,
            elapsed,
            sla_seconds,
        )

    return FlushReport(
        tenant_id=tenant_id,
        attempted=len(rows),
        flushed=flushed,
        failed=failed,
        elapsed_ms=elapsed,
    )


def flush(batch_size: int | None = None, max_runtime_seconds: int = 300) -> list[FlushReport]:
    """Run one flush pass across all tenants.

    Returns a list of per-tenant ``FlushReport``.
    """
    from database import engine

    reports: list[FlushReport] = []
    with engine.connect() as sys_conn:
        bs = batch_size or _get_setting(sys_conn, "audit.outbox.batch_size", _DEFAULT_BATCH_SIZE)
        sla = _get_setting(sys_conn, "audit.outbox.flush_sla_seconds", _DEFAULT_SLA_SECONDS)

        # The outbox is tenant-local; discover active tenants from the system DB.
        tenants = sys_conn.execute(
            text(
                "SELECT id, database_name FROM system_companies "
                "WHERE status = 'active' "
                "ORDER BY id"
            )
        ).fetchall()

        for (tid, db_name) in tenants:
            # Extract company code from database_name (e.g. 'aman_e24bcd11' -> 'e24bcd11')
            tenant_key = str(tid)
            company_code = db_name.replace('aman_', '', 1) if db_name and db_name.startswith('aman_') else tenant_key
            tenant_id = company_code or tenant_key
            try:
                from database import get_db_connection
                conn = get_db_connection(company_code)
                try:
                    rpt = _flush_tenant(conn, tenant_id, bs, sla)
                    reports.append(rpt)
                    if rpt.flushed:
                        logger.info(
                            "audit_outbox_worker: tenant=%s flushed=%d failed=%d %.0fms",
                            tenant_id, rpt.flushed, rpt.failed, rpt.elapsed_ms,
                        )
                finally:
                    conn.close()
            except Exception:
                logger.error("audit_outbox_worker: error on tenant %s", tenant_key)

    return reports


def start_worker():
    """Print the startup banner (called once during app init)."""
    logger.info("audit.outbox.worker: started (batch_size=%d, sla=%ds)",
                _DEFAULT_BATCH_SIZE, _DEFAULT_SLA_SECONDS)
