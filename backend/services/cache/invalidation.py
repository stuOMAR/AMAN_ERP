"""T014: Cache invalidation registry.

Provides scoped, domain-event-based cache invalidation. Instead of
mass-evicting all tenant cache on every write, callers emit domain
events that map to specific key prefixes.

Usage::

    from backend.services.cache.invalidation import registry, emit_je_posted

    # Registration (at import time)
    registry.register("je.posted", ["report:{tenant}:income_statement", "dashboard:{tenant}:*"])

    # At write site
    emit_je_posted(company_id)
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)


class InvalidationRegistry:
    """Maps domain events to cache key prefix lists for scoped eviction."""

    def __init__(self) -> None:
        self._rules: dict[str, list[str]] = {}

    def register(self, domain_event: str, key_prefixes: Sequence[str]) -> None:
        """Register key prefixes to evict when *domain_event* fires."""
        existing = self._rules.get(domain_event, [])
        for p in key_prefixes:
            if p not in existing:
                existing.append(p)
        self._rules[domain_event] = existing

    def get_prefixes(self, domain_event: str) -> list[str]:
        return self._rules.get(domain_event, [])

    def evict(self, domain_event: str, company_id: str, cache_client: object | None = None) -> int:
        """Evict all cache keys matching the registered prefixes for *domain_event*.

        Returns number of patterns issued.
        """
        from backend.utils.cache import cache

        prefixes = self.get_prefixes(domain_event)
        if not prefixes:
            logger.warning("No invalidation rules for event: %s", domain_event)
            return 0

        client = cache_client or cache
        issued = 0
        for prefix in prefixes:
            resolved = prefix.replace("{tenant}", str(company_id))
            try:
                client.delete_pattern(resolved)
                issued += 1
                logger.debug("Invalidated cache pattern: %s", resolved)
            except Exception as exc:
                logger.error("Cache invalidation failed for %s: %s", resolved, exc)
        return issued


# ── Singleton registry ───────────────────────────────────────────────────

registry = InvalidationRegistry()

# ── Default domain-event registrations ───────────────────────────────────

# COA changed → reports that depend on account structure
registry.register("coa.changed", [
    "t:{tenant}:reports",
    "t:{tenant}:coa",
    "t:{tenant}:trial_balance",
    "t:{tenant}:chart_of_accounts",
])

# Role dashboard changed → only that role's dashboard
registry.register("role_dashboard.changed", [
    "t:{tenant}:dashboard",
])

# JE posted → financial reports + dashboards
registry.register("je.posted", [
    "t:{tenant}:reports",
    "t:{tenant}:dashboard",
    "t:{tenant}:trial_balance",
    "t:{tenant}:income_statement",
    "t:{tenant}:balance_sheet",
])

# Invoice posted → sales reports + dashboards
registry.register("invoice_posted", [
    "t:{tenant}:reports",
    "t:{tenant}:dashboard",
    "t:{tenant}:invoices",
])

# Payroll closed → HR reports + dashboards
registry.register("payroll_closed", [
    "t:{tenant}:reports",
    "t:{tenant}:dashboard",
    "t:{tenant}:payroll",
])

# Inventory changed → inventory reports + dashboards
registry.register("inventory_changed", [
    "t:{tenant}:inventory",
    "t:{tenant}:dashboard",
    "t:{tenant}:products",
])


# ── Convenience emitters ────────────────────────────────────────────────

def emit_coa_changed(company_id: str) -> int:
    """Call after chart-of-accounts write."""
    return registry.evict("coa.changed", company_id)


def emit_role_dashboard_changed(company_id: str) -> int:
    """Call after role dashboard config change."""
    return registry.evict("role_dashboard.changed", company_id)


def emit_je_posted(company_id: str) -> int:
    """Call after journal entry post."""
    return registry.evict("je.posted", company_id)


def emit_invoice_posted(company_id: str) -> int:
    """Call after invoice post."""
    return registry.evict("invoice_posted", company_id)


def emit_payroll_closed(company_id: str) -> int:
    """Call after payroll close."""
    return registry.evict("payroll_closed", company_id)


def emit_inventory_changed(company_id: str) -> int:
    """Call after inventory write."""
    return registry.evict("inventory_changed", company_id)
