"""Technician profile matcher — CRUD + assignment matching.

Contract: see specs/024-workforce-service-comms-integrity/contracts/technician-profile-matcher.md
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_technician(conn: Any, *, tenant_id: int, technician_id: int) -> Optional[dict]:
    """Get a technician profile."""
    row = conn.execute(
        text("""
            SELECT id, employee_id, skills, zones, certifications,
                   availability, is_active
            FROM technicians
            WHERE id = :tid AND tenant_id = :tnt
        """),
        {"tid": technician_id, "tnt": tenant_id},
    ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "employee_id": row[1],
        "skills": json.loads(row[2]) if row[2] else [],
        "zones": json.loads(row[3]) if row[3] else [],
        "certifications": json.loads(row[4]) if row[4] else [],
        "availability": json.loads(row[5]) if row[5] else {},
        "is_active": row[6],
    }


def upsert_technician(
    conn: Any,
    *,
    tenant_id: int,
    employee_id: int,
    skills: list[str],
    zones: list[str] = None,
    certifications: list[str] = None,
    availability: dict = None,
) -> dict:
    """Create or update a technician profile."""
    row = conn.execute(
        text("""
            INSERT INTO technicians
                (tenant_id, employee_id, skills, zones, certifications,
                 availability, is_active, created_at)
            VALUES
                (:tnt, :eid, :skills, :zones, :certs, :avail, true, now())
            ON CONFLICT (tenant_id, employee_id)
            DO UPDATE SET
                skills = :skills, zones = :zones, certifications = :certs,
                availability = :avail, updated_at = now()
            RETURNING id
        """),
        {
            "tnt": tenant_id, "eid": employee_id,
            "skills": json.dumps(skills),
            "zones": json.dumps(zones or []),
            "certs": json.dumps(certifications or []),
            "avail": json.dumps(availability or {}),
        },
    ).fetchone()
    conn.commit()
    return {"id": row[0], "employee_id": employee_id}


def technician_assignment_matcher(
    conn: Any,
    *,
    tenant_id: int,
    required_skills: list[str],
    zone: Optional[str] = None,
    service_date: str = None,
) -> list[dict]:
    """Find and rank technicians matching required skills.

    Returns list sorted by match score (descending).
    """
    technicians = conn.execute(
        text("""
            SELECT id, employee_id, skills, zones, certifications, availability
            FROM technicians
            WHERE tenant_id = :tnt AND is_active = true
        """),
        {"tnt": tenant_id},
    ).fetchall()

    candidates = []
    required_set = set(required_skills)

    for tech in technicians:
        tech_skills = set(json.loads(tech[2])) if tech[2] else set()
        tech_zones = json.loads(tech[3]) if tech[3] else []

        # Skill match score
        matched_skills = required_set & tech_skills
        if not matched_skills:
            continue

        score = len(matched_skills) / len(required_set) if required_set else 0

        # Zone bonus
        if zone and zone in tech_zones:
            score += 0.1

        candidates.append({
            "technician_id": tech[0],
            "employee_id": tech[1],
            "score": round(score, 2),
            "matched_skills": list(matched_skills),
            "missing_skills": list(required_set - matched_skills),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates
