"""
Inventory Module - Shared Pydantic Schemas
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import re


# --- Product Schemas ---
class ProductCreate(BaseModel):
    item_code: str
    item_name: str
    item_name_en: Optional[str] = None
    item_type: str = 'product'  # product, service, consumable
    unit: str = 'قطعة'
    # M4: monetary and quantity fields use Decimal to prevent floating-point
    # accumulation errors in WAC/FIFO calculations and transfer valuations.
    selling_price: Decimal = Field(default=Decimal('0'), ge=0)
    buying_price: Decimal = Field(default=Decimal('0'), ge=0)  # Represents WAC (Weighted Average Cost)
    last_buying_price: Decimal = Field(default=Decimal('0'), ge=0)  # Represents Last Purchase Price
    tax_rate: Optional[Decimal] = None  # Ignored — resolved by tax engine; kept for backward compat
    tax_rate_id: Optional[int] = None  # Link to tax_rates table
    tax_group_id: Optional[int] = None  # Link to tax_groups table (multi-tax)
    tax_classification_id: Optional[int] = None  # Link to tax_classifications table
    is_exempt: bool = False  # If true, product is exempt from tax
    description: Optional[str] = None
    category_id: Optional[int] = None
    is_active: bool = True
    has_batch_tracking: bool = False
    has_serial_tracking: bool = False
    has_expiry_tracking: bool = False
    shelf_life_days: int = 0
    expiry_alert_days: int = 30


class ProductResponse(ProductCreate):
    id: int
    category_name: Optional[str] = None
    current_stock: Decimal
    reserved_quantity: Decimal = Decimal('0')
    has_batch_tracking: bool = False
    has_serial_tracking: bool = False
    has_expiry_tracking: bool = False
    shelf_life_days: int = 0
    expiry_alert_days: int = 30
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Supplier Schemas ---
class SupplierCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    tax_exempt: Optional[bool] = False
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    group_id: Optional[int] = None

    @field_validator('email')
    @classmethod
    def email_must_be_valid(cls, v):
        if v is not None and v != '':
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v):
                raise ValueError("صيغة البريد الإلكتروني غير صحيحة")
        return v

    @field_validator('tax_number')
    @classmethod
    def tax_number_must_be_valid(cls, v):
        if v is not None and v != '':
            if not re.match(r'^[\d\-]{5,20}$', v):
                raise ValueError("الرقم الضريبي يجب أن يكون أرقام فقط (5-20 خانة)")
        return v

class SupplierResponse(SupplierCreate):
    id: int
    current_balance: float
    balance: Optional[float] = None
    balance_bc: Optional[float] = None
    is_active: bool
    currency: Optional[str] = None
    created_at: datetime
    display_currency: Optional[str] = None
    balance_display: Optional[float] = None
    balance_sar: Optional[float] = None
    balances: Optional[list] = None
    sites: Optional[list] = None
    site_id: Optional[int] = None
    site_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Stock Transfer Schemas ---
class StockTransferSingleCreate(BaseModel):
    """Single-item transfer (with GL + WAC costing)"""
    product_id: int
    source_warehouse_id: int
    destination_warehouse_id: int
    # M4: Decimal prevents floating-point drift in WAC recalculation
    quantity: Decimal = Field(..., gt=0)
    notes: Optional[str] = None


class StockTransferItem(BaseModel):
    product_id: int
    quantity: Decimal = Field(..., gt=0)


class StockTransferCreate(BaseModel):
    """Multi-item transfer"""
    source_warehouse_id: int
    destination_warehouse_id: int
    items: List[StockTransferItem] = Field(..., min_length=1)
    notes: Optional[str] = None


class StockMovementCreate(BaseModel):
    warehouse_id: int
    items: List[StockTransferItem] = Field(..., min_length=1)
    notes: Optional[str] = None
    date: Optional[str] = None
    reference: Optional[str] = None


# --- Price List Schemas ---
class PriceListCreate(BaseModel):
    name: str
    currency: str
    branch_id: Optional[int] = None
    is_active: bool = True
    is_default: bool = False


class PriceListItemUpdate(BaseModel):
    product_id: int
    price: Decimal  # M4: price must be Decimal


# --- Shipment Schemas ---
class ShipmentItemCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(..., gt=0)  # M4


class ShipmentCreate(BaseModel):
    source_warehouse_id: int
    destination_warehouse_id: int
    items: List[ShipmentItemCreate] = Field(..., min_length=1)
    notes: Optional[str] = None


# --- Stock Adjustment Schemas ---
class StockAdjustmentCreate(BaseModel):
    warehouse_id: int
    product_id: int
    new_quantity: Decimal = Field(..., ge=0)  # M4
    reason: Optional[str] = "Physical Count"
    notes: Optional[str] = None
