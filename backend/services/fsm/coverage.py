"""Contract coverage resolver — determines if a service order is covered by a contract.

Contract: see specs/024-workforce-service-comms-integrity/contracts/contract-coverage.md
"""
from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import text

logger = logging.getLogger(__name__)


class CoverageRules(BaseModel):
    """Schema for contract coverage_rules JSONB field."""
    included_item_ids: list[int] = []
    excluded_item_ids: list[int] = []
    max_hours_per_visit: Optional[Decimal] = None
    max_visits_per_period: Optional[int] = None
    labor_discount_pct: Decimal = Decimal("0")
    parts_discount_pct: Decimal = Decimal("0")
    response_time_hours: Optional[int] = None


def resolve_coverage(
    conn: Any,
    *,
    tenant_id: int,
    contract_id: int,
    item_id: int,
    service_date: date = None,
) -> dict:
    """Check if a service item is covered by a contract.

    Returns dict with coverage status and discount rates.
    """
    if service_date is None:
        service_date = date.today()

    contract = conn.execute(
        text("""
            SELECT id, status, coverage_rules, pricing_strategy,
                   start_date, end_date
            FROM service_contracts
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"cid": contract_id, "tid": tenant_id},
    ).fetchone()

    if contract is None:
        return {"covered": False, "reason": "contract.not_found"}

    if contract[1] != "active":
        return {"covered": False, "reason": "coverage.contract_inactive"}

    # Check date range
    if contract[4] and service_date < contract[4]:
        return {"covered": False, "reason": "coverage.contract_inactive"}
    if contract[5] and service_date > contract[5]:
        return {"covered": False, "reason": "coverage.contract_inactive"}

    # Parse coverage rules
    rules_raw = contract[2]
    if rules_raw:
        if isinstance(rules_raw, str):
            rules = json.loads(rules_raw)
        else:
            rules = rules_raw
    else:
        rules = {}

    try:
        coverage = CoverageRules(**rules)
    except Exception:
        return {"covered": False, "reason": "coverage.invalid_rules"}

    # Check item inclusion/exclusion
    if coverage.excluded_item_ids and item_id in coverage.excluded_item_ids:
        return {"covered": False, "reason": "coverage.item_excluded"}

    if coverage.included_item_ids and item_id not in coverage.included_item_ids:
        return {"covered": False, "reason": "coverage.item_not_included"}

    return {
        "covered": True,
        "contract_id": contract_id,
        "pricing_strategy": contract[3],
        "labor_discount_pct": str(coverage.labor_discount_pct),
        "parts_discount_pct": str(coverage.parts_discount_pct),
        "response_time_hours": coverage.response_time_hours,
    }
