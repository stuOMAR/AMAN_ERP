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

    Args:
        critical: TASK-021 — When True, a failure to persist the audit row
            raises HTTPException(503) so the caller's transaction is rolled
            back. Use this for operations where losing the audit trail is
            unacceptable (e.g., financial posts, role grants, user admin).
            When False (default), failures are only logged.
    """
    try:
        ip_address = None
        if request:
            ip_address = request.client.host
        
        # Branch Fallback Logic
        if branch_id is None:
            try:
                # 1. Try to get user's first assigned branch
                branch_id = db_conn.execute(
                    text("SELECT branch_id FROM user_branches WHERE user_id = :uid LIMIT 1"), 
                    {"uid": user_id}
                ).scalar()
                
                # 2. If user has no branches, fallback to company default branch
                if branch_id is None:
                    branch_id = db_conn.execute(
                        text("SELECT id FROM branches WHERE is_default = TRUE LIMIT 1")
                    ).scalar()
            except Exception as e:
                logger.warning(f"Could not determine branch for audit log: {e}")

        # Ensure details is JSON serializable
        details_json = json.dumps(details, default=str, sort_keys=True) if details else '{}'

        # T3.7: serialize on a per-table advisory lock so concurrent
        # writers see a consistent (chain_seq, prev_hash) tail.
        db_conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('audit_logs_chain', 0))")
        )
        tail = db_conn.execute(
            text("SELECT chain_seq, hash FROM audit_logs ORDER BY chain_seq DESC NULLS LAST LIMIT 1")
        ).fetchone()
        prev_seq = (tail.chain_seq if tail and tail.chain_seq is not None else 0) or 0
        prev_hash = (tail.hash if tail and tail.hash else "") or ""
        new_seq = int(prev_seq) + 1

        now = datetime.now(timezone.utc)
        # ISO with microseconds, matching to_char in the SQL backfill.
        created_at_iso = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"

        new_hash = compute_audit_hash(
            prev_hash=prev_hash,
            chain_seq=new_seq,
            user_id=user_id,
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details_json=details_json,
            ip_address=ip_address,
            branch_id=branch_id,
            created_at_iso=created_at_iso,
        )

        db_conn.execute(
            text("""
                INSERT INTO audit_logs
                (user_id, username, action, resource_type, resource_id, details,
                 ip_address, branch_id, created_at,
                 prev_hash, hash, chain_seq)
                VALUES
                (:uid, :uname, :act, :res_type, :res_id, :det,
                 :ip, :bid, :now,
                 :prev, :h, :seq)
            """),
            {
                "uid": user_id,
                "uname": username,
                "act": action,
                "res_type": resource_type,
                "res_id": str(resource_id) if resource_id is not None else None,
                "det": details_json,
                "ip": ip_address,
                "bid": branch_id,
                "now": now,
                "prev": prev_hash or None,
                "h": new_hash,
                "seq": new_seq,
            }
        )
        db_conn.commit()
        logger.info(f"📝 AUDIT[{new_seq}]: {username} -> {action} ({resource_id})")

    except Exception as e:
        # ACC-F6: never swallow silently — emit full stack for observability
        logger.error(
            f"❌ FAILED TO LOG AUDIT: user={username} action={action} resource={resource_type}:{resource_id} err={e}",
            exc_info=True,
        )
        if critical:
            # TASK-021: fail-closed — reject the operation so the caller
            # rolls back. The audit trail is a non-negotiable prerequisite
            # for critical actions.
            try:
                db_conn.rollback()
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail="تعذّر تسجيل الحدث في سجل التدقيق؛ تم إلغاء العملية للحفاظ على النزاهة.",
            )


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
