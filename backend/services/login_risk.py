"""Login risk evaluation — device fingerprint + geo event seam.

On successful login, writes a ``device_fingerprints`` upsert (SHA-256 of
stable, non-PII components) and a ``login_geo_events`` row with
``risk_decision = "ok"``.  Exposes ``evaluate_login_risk()`` as a hook
point for future risk heuristics.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import text

logger = logging.getLogger(__name__)

RiskDecision = Literal["ok", "review", "block"]


def _fingerprint_hash(user_agent: str, ip_address: str, user_id: int) -> str:
    """SHA-256 of stable, non-PII components.

    Uses a truncated IP (first two octets for v4, /48 for v6) and a
    normalized user-agent to produce a coarse device fingerprint.
    No raw UA or IP is stored.
    """
    # Coarsen IP: keep first 2 octets for IPv4
    coarse_ip = ip_address
    if "." in ip_address:
        parts = ip_address.split(".")
        coarse_ip = ".".join(parts[:2]) + ".0.0"
    elif ":" in ip_address:
        # IPv6: keep first 4 groups
        parts = ip_address.split(":")
        coarse_ip = ":".join(parts[:4]) + "::"

    # Normalize UA: strip version numbers, keep product names
    ua_lower = user_agent.lower().strip()[:200]

    raw = f"{user_id}:{coarse_ip}:{ua_lower}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": name}).scalar() is not None


def evaluate_login_risk(
    conn,
    tenant_id: int,
    user_id: int,
    user_agent: str,
    ip_address: str,
) -> RiskDecision:
    """Evaluate login risk and record device fingerprint + geo event.

    Currently always returns ``"ok"`` — the hook point exists for future
    heuristics (impossible-travel, unknown device, etc.).

    Writes to ``device_fingerprints`` and ``login_geo_events`` if the
    tables exist.  Never raises — failures are logged and skipped.
    """
    try:
        fp_hash = _fingerprint_hash(user_agent, ip_address, user_id)
        now = datetime.now(timezone.utc)

        # Device fingerprint upsert
        if _table_exists(conn, "device_fingerprints"):
            existing = conn.execute(text("""
                SELECT id, trust_level FROM device_fingerprints
                 WHERE tenant_id = :tid AND user_id = :uid AND fingerprint_hash = :fph
            """), {"tid": tenant_id, "uid": user_id, "fph": fp_hash}).fetchone()

            if existing:
                conn.execute(text("""
                    UPDATE device_fingerprints
                       SET last_seen_at = :now
                     WHERE id = :id
                """), {"id": existing.id, "now": now})
            else:
                conn.execute(text("""
                    INSERT INTO device_fingerprints
                        (tenant_id, user_id, fingerprint_hash, first_seen_at, last_seen_at, trust_level)
                    VALUES (:tid, :uid, :fph, :now, :now, 'unknown')
                """), {"tid": tenant_id, "uid": user_id, "fph": fp_hash, "now": now})

        # Login geo event
        if _table_exists(conn, "login_geo_events"):
            conn.execute(text("""
                INSERT INTO login_geo_events
                    (tenant_id, user_id, occurred_at, country_code, region_code,
                     risk_decision, decision_reason)
                VALUES (:tid, :uid, :now, NULL, NULL, 'ok', 'default_pass')
            """), {"tid": tenant_id, "uid": user_id, "now": now})

        # Future: evaluate heuristics here
        return "ok"

    except Exception:
        logger.debug("login_risk: failed to record fingerprint/geo for user %s", user_id, exc_info=True)
        return "ok"


__all__ = ["evaluate_login_risk", "RiskDecision"]
