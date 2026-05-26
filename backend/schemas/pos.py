"""POS module Pydantic schemas."""
from decimal import Decimal
from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime
from uuid import UUID


class SessionCreate(BaseModel):
    pos_profile_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    opening_balance: Decimal = Decimal("0")
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    treasury_account_id: Optional[int] = None

    @field_validator("opening_balance")
    @classmethod
    def opening_balance_must_be_valid(cls, v):
        if v < 0:
            raise ValueError("رصيد الافتتاح لا يمكن أن يكون سالباً")
        if v > 1_000_000_000_000:
            raise ValueError("رصيد الافتتاح يتجاوز الحد الأقصى المسموح")
        return v


class SessionClose(BaseModel):
    closing_balance: Decimal
    cash_register_balance: Decimal
    notes: Optional[str] = None

    @field_validator("closing_balance", "cash_register_balance")
    @classmethod
    def close_balances_must_be_valid(cls, v):
        if v < 0:
            raise ValueError("أرصدة الإغلاق لا يمكن أن تكون سالبة")
        if v > 1_000_000_000_000:
            raise ValueError("الرصيد يتجاوز الحد الأقصى المسموح")
        return v


class SessionResponse(BaseModel):
    id: int
    session_code: Optional[str] = None
    user_id: int
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    treasury_account_id: Optional[int] = None
    cashier_name: Optional[str] = None
    status: str
    opened_at: datetime
    opening_balance: Decimal = Decimal("0")
    closing_balance: Optional[Decimal] = Decimal("0")
    total_sales: Optional[Decimal] = Decimal("0")
    total_cash: Optional[Decimal] = Decimal("0")
    total_bank: Optional[Decimal] = Decimal("0")
    total_returns: Optional[Decimal] = Decimal("0")
    total_returns_cash: Optional[Decimal] = Decimal("0")
    expected_cash: Optional[Decimal] = Decimal("0")
    order_count: Optional[int] = 0
    difference: Optional[Decimal] = Decimal("0")


class POSProductResponse(BaseModel):
    id: int
    name: str
    code: Optional[str]
    barcode: Optional[str]
    price: Decimal
    stock_quantity: Decimal
    category_id: Optional[int]
    image_url: Optional[str]
    tax_rate: Optional[Decimal] = Decimal("0")


class OrderLineCreate(BaseModel):
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def order_line_quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("الكمية يجب أن تكون أكبر من صفر")
        if v > 1_000_000_000:
            raise ValueError("الكمية تتجاوز الحد الأقصى المسموح")
        return v

    @field_validator("unit_price", "discount_amount")
    @classmethod
    def order_line_amounts_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("المبلغ لا يمكن أن يكون سالباً")
        if v > 1_000_000_000:
            raise ValueError("المبلغ يتجاوز الحد الأقصى المسموح")
        return v

    @field_validator("tax_rate")
    @classmethod
    def order_line_tax_must_be_valid(cls, v):
        if v < 0 or v > 100:
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        return v


class OrderPaymentCreate(BaseModel):
    method: str
    amount: Decimal
    reference: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def payment_amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("مبلغ الدفع يجب أن يكون أكبر من صفر")
        if v > 1_000_000_000_000:
            raise ValueError("مبلغ الدفع يتجاوز الحد الأقصى المسموح")
        return v


class OrderCreate(BaseModel):
    session_id: int
    client_order_id: Optional[str] = None
    customer_id: Optional[int] = None
    party_site_id: Optional[int] = None
    walk_in_customer_name: Optional[str] = None
    warehouse_id: Optional[int] = None
    branch_id: Optional[int] = None
    items: List[OrderLineCreate]
    discount_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    payments: List[OrderPaymentCreate] = []
    status: str = "paid"
    note: Optional[str] = None
    # T3.10: backend-resolved promotion / coupon. Either may be supplied;
    # the server validates and applies the discount before computing totals
    # so POS results match a sales invoice for identical inputs.
    coupon_code: Optional[str] = None
    promotion_id: Optional[int] = None
    # Backend authority verification
    submitted_grand_total: Optional[Decimal] = None

    @field_validator("discount_amount", "paid_amount")
    @classmethod
    def order_amounts_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("المبالغ لا يمكن أن تكون سالبة")
        if v > 1_000_000_000_000:
            raise ValueError("المبلغ يتجاوز الحد الأقصى المسموح")
        return v

    @field_validator("client_order_id")
    @classmethod
    def client_order_id_must_be_uuid(cls, v):
        if v is None:
            return v
        return str(UUID(str(v)))


class OrderResponse(BaseModel):
    id: int
    order_number: str
    total_amount: Decimal
    status: str
    created_at: datetime


class ReturnItemCreate(BaseModel):
    item_id: int
    quantity: Decimal
    reason: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def return_item_quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("كمية المرتجع يجب أن تكون أكبر من صفر")
        if v > 1_000_000_000:
            raise ValueError("كمية المرتجع تتجاوز الحد الأقصى المسموح")
        return v


class ReturnCreate(BaseModel):
    order_id: int
    items: List[ReturnItemCreate]
    refund_method: str = "cash"
    notes: Optional[str] = None
