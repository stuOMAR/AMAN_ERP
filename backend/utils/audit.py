from datetime import datetime, timezone
from sqlalchemy import text
from fastapi import Request, HTTPException
from database import engine
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# T3.7 (audit #21, #22): tamper-evident hash chain over audit_logs.
# ---------------------------------------------------------------------------

def _canonical_payload(
    *,
    prev_hash: str,
    chain_seq: int,
    user_id,
    username,
    action,
    resource_type,
    resource_id,
    details_json: str,
    ip_address,
    branch_id,
    created_at_iso: str,
) -> str:
    """Build the pipe-joined canonical string hashed for one audit row.

    Field order matches the SQL backfill in migration 0017 so the Python
    chain and the in-DB backfill produce identical hashes for the same
    inputs (the CLI verifier in scripts/verify_audit_chain.py relies on
    that equivalence).
    """
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
    return "|".join(parts)


def compute_audit_hash(
    *,
    prev_hash: str,
    chain_seq: int,
    user_id,
    username,
    action,
    resource_type,
    resource_id,
    details_json: str,
    ip_address,
    branch_id,
    created_at_iso: str,
) -> str:
    payload = _canonical_payload(
        prev_hash=prev_hash,
        chain_seq=chain_seq,
        user_id=user_id,
        username=username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details_json=details_json,
        ip_address=ip_address,
        branch_id=branch_id,
        created_at_iso=created_at_iso,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_change_details(old: dict | None, new: dict | None, **extra) -> dict:
    """T3.7 (audit #25): canonical {"old": ..., "new": ...} envelope.

    All audit details for record mutations should adopt this shape so the
    audit viewer can render diffs uniformly. Pass extra context as kwargs
    (e.g. ``reason='...'``, ``request_id=...``) — they are merged at the
    top level alongside ``old`` and ``new``.
    """
    payload: dict = {"old": old or {}, "new": new or {}}
    if extra:
        payload.update(extra)
    return payload


def log_activity(
    db_conn,
    user_id: int,
    username: str,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details: dict = None,
    request: Request = None,
    branch_id: int = None,
    critical: bool = False,
):
    """
    سجل نشاط المستخدم في قاعدة البيانات.
    يسجل: من، ماذا، أين، متى، وتفاصيل إضافية.

    Feature 022: Now routes through the outbox-backed audit writer so the
    row commits/rolls back atomically with the caller's business transaction.

    Args:
        critical: When True, a failure to persist the audit row raises
            AuditWriteError so the caller can rollback.  Use for operations
            where losing the audit trail is unacceptable.
    """
    try:
        ip_address = None
        if request:
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",", 1)[0].strip()
            elif request.client:
                ip_address = request.client.host
            request_meta = {
                "method": request.method,
                "endpoint": request.url.path,
            }
            details = {**(details or {}), "request": request_meta}
            # Also capture client IP in details for audit trail
            if ip_address:
                details = {**details, "ip_address": ip_address}

        # Feature 022: delegate to outbox-backed writer
        from services.audit_writer import log_activity as _outbox_log, AuditWriteError

        # Enrich details with legacy context fields
        enriched = dict(details) if details else {}
        if username:
            enriched["_legacy_username"] = username
        if branch_id is not None:
            enriched["_legacy_branch_id"] = branch_id

        _outbox_log(
            db_conn,
            action=action,
            entity_type=resource_type,
            entity_id=str(resource_id) if resource_id is not None else None,
            actor_id=user_id,
            details=enriched,
            critical=critical,
        )
        logger.info(f"📝 AUDIT[enqueue]: {username} -> {action} ({resource_id})")

    except Exception as e:
        # Never swallow silently — emit full stack for observability
        logger.error(
            f"❌ FAILED TO LOG AUDIT: user={username} action={action} resource={resource_type}:{resource_id} err={e}",
            exc_info=True,
        )
        if critical:
            # fail-closed — reject the operation so the caller rolls back.
            from services.audit_writer import AuditWriteError as _AWE
            raise _AWE(f"Audit write failed for critical action {action}: {e}")


def log_system_activity(
    action: str,
    company_id: str = None,
    performed_by: str = None,
    description: str = None,
    request: Request = None
):
    """سجل نشاط على مستوى النظام (في قاعدة البيانات الرئيسية)"""
    try:
        ip_address = None
        user_agent = None
        if request:
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",", 1)[0].strip()
            elif request.client:
                ip_address = request.client.host
            user_agent = request.headers.get("user-agent")
            
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO system_activity_log 
                    (company_id, action_type, action_description, performed_by, ip_address, user_agent, created_at)
                    VALUES 
                    (:cid, :act, :desc, :by, :ip, :ua, CURRENT_TIMESTAMP)
                """),
                {
                    "cid": company_id,
                    "act": action,
                    "desc": description,
                    "by": performed_by,
                    "ip": ip_address,
                    "ua": user_agent
                }
            )
            conn.commit()
    except Exception as e:
        logger.error(f"❌ FAILED TO LOG SYSTEM ACTIVITY: {e}")
