"""JE Source enum — single source of truth for journal_entries.source values.

All JE producers MUST import and use these constants instead of free-form strings.
The CHECK constraint in migration 022g enforces the same set at the DB level.
"""
from __future__ import annotations

from enum import Enum


class JESource(str, Enum):
    """Valid source values for journal_entries and invoices."""

    SALES = "sales"
    PURCHASE = "purchase"
    PAYROLL = "payroll"
    TREASURY = "treasury"
    MANUFACTURING = "manufacturing"
    MANUAL = "manual"
    RECURRING = "recurring"
    ASSET = "asset"
    SYSTEM = "system"
    # Extended sources used by specific modules
    EXPENSE = "expense"
    SETTLEMENT = "settlement"
    REVERSAL = "reversal"
    PAYROLL_REVERSE = "payroll_reverse"
    TICKET_ALLOWANCE = "ticket_allowance"
    SERVICE_INVOICE = "service_invoice"
    SERVICE_INVOICE_REVERSE = "service_invoice_reverse"
    INTERCOMPANY = "intercompany"
    INTERCOMPANY_ELIMINATION = "intercompany_elimination"
    SUBSCRIPTION = "subscription"
    FX_REVALUATION = "fx_revaluation"
    REVENUE_RECOGNITION = "revenue_recognition"
    IMPAIRMENT = "impairment"
    ECL_PROVISION = "ecl_provision"
    NRV_TEST = "nrv_test"
    IFRS15_REVENUE = "ifrs15_revenue"
    LEASE = "lease"
    TAX = "tax"
    PROVISION = "provision"
    POS = "pos"
    SHIPMENT = "shipment"
    DELIVERY = "delivery"
    PAYMENT = "payment"

    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        """Normalize a legacy source string to a valid enum value.

        Handles common variations: mixed case, hyphens, prefixes.
        Returns None if input is None.
        """
        if value is None:
            return None
        v = value.strip().lower()
        # Direct match
        try:
            return cls(v).value
        except ValueError:
            pass
        # Common normalizations
        _ALIASES = {
            "manual": cls.MANUAL.value,
            "pos-order": cls.POS.value,
            "pos-return": cls.POS.value,
            "deliveryorder": cls.DELIVERY.value,
            "shipment_dispatch": cls.SHIPMENT.value,
            "shipment_receive": cls.SHIPMENT.value,
            "treasury_account_opening": cls.TREASURY.value,
            "treasury_transfer": cls.TREASURY.value,
            "bad_debt_provision": cls.PROVISION.value,
            "leave_provision": cls.PROVISION.value,
            "tax_payment": cls.TAX.value,
            "tax_settlement": cls.TAX.value,
            "asset_transfer": cls.ASSET.value,
            "lease_contract": cls.LEASE.value,
            "lease_payment": cls.LEASE.value,
            "impairment_test": cls.IMPAIRMENT.value,
            "payroll_reverse": cls.PAYROLL_REVERSE.value,
            "ticket_allowance": cls.TICKET_ALLOWANCE.value,
            "service_invoice": cls.SERVICE_INVOICE.value,
            "service_invoice_reverse": cls.SERVICE_INVOICE_REVERSE.value,
        }
        return _ALIASES.get(v, cls.SYSTEM.value)


# All valid source values as a set (for CHECK constraint reference)
VALID_SOURCES: frozenset[str] = frozenset(s.value for s in JESource)

__all__ = ["JESource", "VALID_SOURCES"]
