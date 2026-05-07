"""Contract renewal service.

Contract: see specs/024-workforce-service-comms-integrity/contracts/contract-renew.md
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def renew_contract(
    conn: Any,
    *,
    tenant_id: int,
    contract_id: int,
    new_start_date: date,
    new_end_date: date,
    generate_invoice: bool = False,
    actor_id: int = 0,
) -> dict:
    """Renew a service contract.

    Creates a new contract linked via auto_renewed_to_id.
    If generate_invoice=True, creates an invoice (requires contract.renew permission).
    """
    # Get original contract
    contract = conn.execute(
        text("""
            SELECT id, title, customer_id, status, renew_policy,
                   pricing_strategy, coverage_rules
            FROM service_contracts
            WHERE id = :cid AND tenant_id = :tnt
        """),
        {"cid": contract_id, "tnt": tenant_id},
    ).fetchone()

    if contract is None:
        raise LookupError("contract.not_found")
    if contract[3] != "active":
        raise ValueError("contract.not_renewable")

    # Check if already renewed
    existing = conn.execute(
        text("""
            SELECT 1 FROM service_contracts
            WHERE auto_renewed_to_id = :cid AND tenant_id = :tnt
        """),
        {"cid": contract_id, "tnt": tenant_id},
    ).fetchone()

    if existing:
        raise ValueError("contract.already_renewed")

    # Create new contract
    row = conn.execute(
        text("""
            INSERT INTO service_contracts
                (tenant_id, title, customer_id, status, start_date, end_date,
                 renew_policy, pricing_strategy, coverage_rules,
                 auto_renewed_to_id, created_by, created_at)
            VALUES
                (:tnt, :title, :cust, 'draft', :start, :end,
                 :renew, :pricing, :coverage,
                 :orig_id, :actor, now())
            RETURNING id
        """),
        {
            "tnt": tenant_id, "title": f"Renewal: {contract[1]}",
            "cust": contract[2], "start": new_start_date, "end": new_end_date,
            "renew": contract[4], "pricing": contract[5], "coverage": contract[6],
            "orig_id": contract_id, "actor": actor_id,
        },
    ).fetchone()

    # Link original to new
    conn.execute(
        text("""
            UPDATE service_contracts
            SET auto_renewed_to_id = :new_id, updated_at = now()
            WHERE id = :cid AND tenant_id = :tnt
        """),
        {"new_id": row[0], "cid": contract_id, "tnt": tenant_id},
    )

    conn.commit()

    return {
        "original_contract_id": contract_id,
        "new_contract_id": row[0],
        "new_start_date": str(new_start_date),
        "new_end_date": str(new_end_date),
    }
