"""Costing module Pydantic schemas — FIFO/LIFO cost layers."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class CostingMethodEnum(str, Enum):
    fifo = "fifo"
    lifo = "lifo"


class SourceDocTypeEnum(str, Enum):
    purchase_invoice = "purchase_invoice"
    opening_balance = "opening_balance"
    return_ = "return"
    adjustment = "adjustment"


class SaleDocTypeEnum(str, Enum):
    sales_invoice = "sales_invoice"
    pos_order = "pos_order"
    adjustment = "adjustment"


# --- Cost Layer ---

class CostLayerRead(BaseModel):
    id: int
    product_id: int
    warehouse_id: int
    costing_method: str
    purchase_date: date
    original_quantity: Decimal
    remaining_quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal = Decimal("0")
    source_document_type: str
    source_document_id: Optional[int] = None
    is_exhausted: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Costing Method Change ---

class CostingMethodChange(BaseModel):
    product_id: int
    warehouse_id: int
    new_method: CostingMethodEnum


class CostingMethodChangeResult(BaseModel):
    product_id: int
    warehouse_id: int
    old_method: Optional[str] = None
    new_method: str
    layers_created: int = 0
    message: str = ""


# --- Consumption History ---

class ConsumptionHistoryRead(BaseModel):
    id: int
    cost_layer_id: int
    quantity_consumed: Decimal
    sale_document_type: str
    sale_document_id: Optional[int] = None
    consumed_at: Optional[datetime] = None
    unit_cost: Optional[Decimal] = None  # enriched from parent layer

    class Config:
        from_attributes = True


# --- Inventory Valuation ---

class ValuationLineItem(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    costing_method: str
    total_quantity: Decimal = Decimal("0")
    total_value: Decimal = Decimal("0")
    weighted_avg_cost: Optional[Decimal] = None
    weighted_unit_cost: Optional[Decimal] = None
    layer_count: int = 0


class InventoryValuationReport(BaseModel):
    as_of_date: str
    items: list[ValuationLineItem] = []
    grand_total: Decimal = Decimal("0")
    grand_total_value: Decimal = Decimal("0")
    grand_total_quantity: Decimal = Decimal("0")
