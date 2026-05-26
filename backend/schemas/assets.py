"""Assets module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import date
from decimal import Decimal


class AssetCreate(BaseModel):
    name: str
    code: Optional[str] = None
    type: str
    purchase_date: date
    cost: Decimal
    residual_value: Decimal = Decimal(0)
    life_years: int
    branch_id: Optional[int] = None
    currency: str = ""
    depreciation_method: str = "straight_line"


class AssetUpdate(BaseModel):
    """All mutable asset fields — every field optional for PATCH-style update."""
    name: Optional[str] = None
    code: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    cost: Optional[Decimal] = None
    residual_value: Optional[Decimal] = None
    life_years: Optional[int] = None
    location: Optional[str] = None
    branch_id: Optional[int] = None
    notes: Optional[str] = None
    purchase_date: Optional[date] = None


class AssetDisposal(BaseModel):
    disposal_date: date
    disposal_price: Decimal = Decimal(0)
    notes: Optional[str] = None
    payment_method: str = "cash"
    submitted_disposal_proceeds: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None


class AssetTransferCreate(BaseModel):
    """Transfer an asset between branches."""
    asset_id: int
    to_branch_id: int
    transfer_date: Optional[date] = None
    reason: Optional[str] = None


class AssetRevaluationCreate(BaseModel):
    """Revalue an asset to a new fair value."""
    asset_id: int
    new_value: Decimal
    revaluation_date: Optional[date] = None
    reason: Optional[str] = None


class MaintenanceComplete(BaseModel):
    """Mark maintenance as completed."""
    completed_date: Optional[date] = None
    actual_cost: Optional[Decimal] = None


class LeaseContractCreate(BaseModel):
    """IFRS 16 lease contract creation."""
    start_date: date
    end_date: date
    asset_id: Optional[int] = None
    description: Optional[str] = None
    lessor_name: Optional[str] = None
    lease_type: str = "operating"
    monthly_payment: Decimal = Decimal(0)
    total_payments: int = 0
    discount_rate: Decimal = Decimal(5)
    status: str = "active"


class DecliningBalanceInput(BaseModel):
    """Optional rate override for declining balance depreciation."""
    rate: Optional[Decimal] = None


class UnitsOfProductionInput(BaseModel):
    """Units of production depreciation input."""
    total_units: Optional[Decimal] = None
    units_used: Decimal = Decimal(0)


class InsuranceCreate(BaseModel):
    """Asset insurance policy."""
    policy_number: Optional[str] = None
    insurer: Optional[str] = None
    coverage_type: Optional[str] = None
    premium_amount: Decimal = Decimal(0)
    coverage_amount: Decimal = Decimal(0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class MaintenanceCreate(BaseModel):
    """Schedule asset maintenance."""
    maintenance_type: str = "preventive"
    description: Optional[str] = None
    scheduled_date: Optional[date] = None
    cost: Decimal = Decimal(0)
    vendor: Optional[str] = None
    notes: Optional[str] = None


class AssetQRUpdate(BaseModel):
    """Update QR code / barcode for asset."""
    qr_code: Optional[str] = None
    barcode: Optional[str] = None


class ImpairmentTestInput(BaseModel):
    """IAS 36 impairment test input."""
    recoverable_amount: Decimal = Decimal(0)
    test_date: Optional[date] = None
    reason: Optional[str] = None
    notes: Optional[str] = None


class LeasePaymentCreate(BaseModel):
    """IFRS 16 lease payment with interest/principal split."""
    payment_date: date
    amount: Decimal
