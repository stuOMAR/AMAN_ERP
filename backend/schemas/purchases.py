"""Purchases module Pydantic schemas."""
from decimal import Decimal
from pydantic import BaseModel
from typing import List, Optional
from datetime import date


class PurchaseLineItem(BaseModel):
    product_id: Optional[int] = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    discount: Decimal = Decimal("0")
    markup: Decimal = Decimal("0")


class PurchaseCreate(BaseModel):
    supplier_id: int
    party_site_id: Optional[int] = None  # موقع المورد (اختياري)
    invoice_date: date
    due_date: Optional[date] = None
    items: List[PurchaseLineItem]
    notes: Optional[str] = None
    payment_method: str = "cash"
    down_payment_method: Optional[str] = None
    paid_amount: Decimal = Decimal("0")
    original_invoice_id: Optional[int] = None
    branch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    treasury_id: Optional[int] = None
    is_prepayment: bool = False

    # Group effects
    effect_type: str = "discount"
    effect_percentage: Decimal = Decimal("0")
    markup_amount: Decimal = Decimal("0")


class SupplierGroupCreate(BaseModel):
    group_name: str
    group_name_en: Optional[str] = None
    description: Optional[str] = None
    discount_percentage: Decimal = Decimal("0")
    effect_type: str = "discount"
    application_scope: str = "total"
    payment_days: int = 30
    branch_id: Optional[int] = None
    status: str = "active"


class POCreate(BaseModel):
    supplier_id: int
    party_site_id: Optional[int] = None
    order_date: date
    expected_date: Optional[date] = None
    items: List[PurchaseLineItem]
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Decimal("1")

    # Group effects
    effect_type: str = "discount"
    effect_percentage: Decimal = Decimal("0")
    markup_amount: Decimal = Decimal("0")


class ReceiveItem(BaseModel):
    line_id: int
    received_quantity: Decimal


class POReceiveRequest(BaseModel):
    items: List[ReceiveItem]
    warehouse_id: int
    notes: Optional[str] = None


class SupplierCreate(BaseModel):
    supplier_name: str
    supplier_name_en: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    branch_id: Optional[int] = None
    supplier_group_id: Optional[int] = None


class PaymentAllocationSchema(BaseModel):
    invoice_id: int
    allocated_amount: Decimal


class SupplierPaymentCreate(BaseModel):
    supplier_id: int
    party_site_id: Optional[int] = None
    voucher_date: date
    amount: Decimal
    payment_method: str
    bank_account_id: Optional[int] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    voucher_type: Optional[str] = 'payment'
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Decimal("1")
    treasury_account_id: Optional[int] = None
    transaction_rate: Optional[Decimal] = None
    allocations: List[PaymentAllocationSchema] = []
