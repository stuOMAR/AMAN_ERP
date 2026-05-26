"""Sales module Pydantic schemas."""
from decimal import Decimal
from pydantic import BaseModel, Field, validator, field_validator
from typing import List, Optional
from datetime import date
import re


# --- Customer Groups ---
class CustomerGroupCreate(BaseModel):
    group_name: str
    group_name_en: Optional[str] = None
    description: Optional[str] = None
    discount_percentage: Decimal = Decimal("0")
    effect_type: str = "discount"
    application_scope: str = "total"
    payment_days: int = 30
    status: str = "active"

    @field_validator('discount_percentage')
    @classmethod
    def discount_must_be_valid(cls, v):
        if v < 0 or v > 100:
            raise ValueError("نسبة الخصم يجب أن تكون بين 0 و 100")
        return v


# --- Customer ---
class CustomerCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    tax_exempt: Optional[bool] = False
    contact_person: Optional[str] = None
    credit_limit: Decimal = Decimal("0")
    payment_terms: Optional[int] = 30
    notes: Optional[str] = None
    group_id: Optional[int] = None
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    status: str = "active"

    @field_validator('credit_limit')
    @classmethod
    def credit_limit_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("حد الائتمان لا يمكن أن يكون سالباً")
        return v

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


class CustomerResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    current_balance: Decimal = Decimal("0")


# --- Invoice ---
class InvoiceLineItem(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Optional[Decimal] = None  # Ignored — resolved by tax engine on backend
    discount: Decimal = Decimal("0")
    markup: Decimal = Decimal("0")

    @validator("quantity")
    def quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("الكمية يجب أن تكون أكبر من صفر")
        return v

    @validator("unit_price")
    def price_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("سعر الوحدة لا يمكن أن يكون سالباً")
        return v

    @validator("discount")
    def discount_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("الخصم لا يمكن أن يكون سالباً")
        return v

    @validator("quantity", "unit_price", "discount", "markup")
    def values_must_be_within_max_limit(cls, v):
        if abs(v) > 1_000_000_000:
            raise ValueError("القيمة تتجاوز الحد الأقصى المسموح")
        return v

    @validator("tax_rate")
    def tax_rate_must_be_valid(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        return v


class InvoiceCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None  # موقع العميل (اختياري)
    invoice_date: date
    due_date: Optional[date] = None
    items: List[InvoiceLineItem]
    notes: Optional[str] = None
    payment_method: Optional[str] = None
    paid_amount: Optional[Decimal] = Decimal("0")
    down_payment_method: Optional[str] = None   # method used when payment_method='credit' + partial down payment
    branch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    treasury_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    cost_center_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    submitted_grand_total: Optional[Decimal] = None

    # Group effects
    effect_type: str = "discount"
    effect_percentage: Decimal = Decimal("0")
    markup_amount: Decimal = Decimal("0")

    @validator("paid_amount", "effect_percentage", "markup_amount")
    def invoice_amounts_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("القيم المالية لا يمكن أن تكون سالبة")
        if v is not None and abs(v) > 1_000_000_000_000:
            raise ValueError("القيمة تتجاوز الحد الأقصى المسموح")
        return v

    @validator("exchange_rate")
    def invoice_exchange_rate_must_be_valid(cls, v):
        if v is None:
            return v
        if v <= 0:
            raise ValueError("سعر الصرف يجب أن يكون أكبر من صفر")
        if v > 1_000_000:
            raise ValueError("سعر الصرف يتجاوز الحد الأقصى")
        return v


class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    customer_name: Optional[str] = None
    invoice_date: date
    total: Decimal
    status: str


# --- Sales Order ---
class SOLineItem(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Optional[Decimal] = None  # Ignored — resolved by tax engine on backend
    discount: Decimal = Decimal("0")


class SOCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None
    order_date: date
    expected_delivery_date: Optional[date] = None
    items: List[SOLineItem]
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    quotation_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None


# --- Quotation ---
class QuotationLineItem(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Optional[Decimal] = None  # Ignored — resolved by tax engine on backend
    discount: Decimal = Decimal("0")

    @field_validator('product_id')
    @classmethod
    def quotation_product_required(cls, v):
        if v is None or v <= 0:
            raise ValueError("يجب اختيار صنف صالح لكل سطر في عرض السعر")
        return v

    @field_validator('quantity')
    @classmethod
    def quotation_quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("كمية عرض السعر يجب أن تكون أكبر من صفر")
        return v

    @field_validator('unit_price')
    @classmethod
    def quotation_price_non_negative(cls, v):
        if v < 0:
            raise ValueError("سعر الوحدة في عرض السعر لا يمكن أن يكون سالباً")
        return v

    @field_validator('tax_rate')
    @classmethod
    def quotation_tax_rate_valid(cls, v):
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        return v

    @field_validator('discount')
    @classmethod
    def quotation_discount_non_negative(cls, v):
        if v < 0:
            raise ValueError("الخصم لا يمكن أن يكون سالباً")
        return v


class QuotationCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None
    quotation_date: date
    expiry_date: Optional[date] = None
    items: List[QuotationLineItem]
    notes: Optional[str] = None
    terms_conditions: Optional[str] = None
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None

    @field_validator('items')
    @classmethod
    def quotation_must_have_items(cls, v):
        if not v:
            raise ValueError("يجب إضافة صنف واحد على الأقل إلى عرض السعر")
        return v


# --- Sales Return ---
class SalesReturnLineItem(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Optional[Decimal] = Decimal("0")
    reason: Optional[str] = None

    @validator("quantity")
    def return_quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("الكمية المرتجعة يجب أن تكون أكبر من صفر")
        if v > 1_000_000_000:
            raise ValueError("الكمية تتجاوز الحد الأقصى المسموح")
        return v

    @validator("unit_price")
    def return_price_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("سعر الوحدة لا يمكن أن يكون سالباً")
        if v > 1_000_000_000:
            raise ValueError("سعر الوحدة يتجاوز الحد الأقصى المسموح")
        return v

    @validator("tax_rate")
    def return_tax_rate_must_be_valid(cls, v):
        if v is None:
            return v
        if v < 0 or v > 100:
            raise ValueError("نسبة الضريبة يجب أن تكون بين 0 و 100")
        return v


class SalesReturnCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None
    invoice_id: Optional[int] = None
    return_date: date
    items: List[SalesReturnLineItem]
    notes: Optional[str] = None
    refund_method: Optional[str] = None
    refund_amount: Optional[Decimal] = Decimal("0")
    bank_account_id: Optional[int] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    branch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None

    @validator("refund_amount")
    def refund_amount_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("مبلغ الاسترداد لا يمكن أن يكون سالباً")
        if v is not None and v > 1_000_000_000_000:
            raise ValueError("مبلغ الاسترداد يتجاوز الحد الأقصى المسموح")
        return v

    @validator("exchange_rate")
    def return_exchange_rate_must_be_valid(cls, v):
        if v is None:
            return v
        if v <= 0:
            raise ValueError("سعر الصرف يجب أن يكون أكبر من صفر")
        if v > 1_000_000:
            raise ValueError("سعر الصرف يتجاوز الحد الأقصى")
        return v


# --- Payment Vouchers ---
class PaymentAllocation(BaseModel):
    invoice_id: int
    allocated_amount: Decimal


class CustomerReceiptCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None
    voucher_date: date
    amount: Decimal
    payment_method: str
    bank_account_id: Optional[int] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    allocations: List[PaymentAllocation] = []
    branch_id: Optional[int] = None
    treasury_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None


class CustomerPaymentCreate(BaseModel):
    customer_id: int
    party_site_id: Optional[int] = None
    voucher_date: date
    amount: Decimal
    payment_method: str
    bank_account_id: Optional[int] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    allocations: List[PaymentAllocation] = []
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None


# --- Sales Previews ---
class SalesPreviewLineInput(BaseModel):
    product_id: Optional[int] = None
    description: Optional[str] = None
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    tax_rate: Optional[Decimal] = None
    discount: Decimal = Decimal("0")
    reason: Optional[str] = None


class SalesDocumentPreviewRequest(BaseModel):
    lines: List[SalesPreviewLineInput] = Field(default_factory=list)
    branch_id: Optional[int] = None
    party_id: Optional[int] = None
    customer_id: Optional[int] = None
    related_invoice_id: Optional[int] = None
    document_date: Optional[date] = None
    currency: Optional[str] = None
    paid_amount: Decimal = Decimal("0")
    header_discount_pct: Decimal = Decimal("0")
    markup_amount: Decimal = Decimal("0")


class SalesReceiptAllocationPreviewRequest(BaseModel):
    customer_id: Optional[int] = None
    voucher_date: Optional[date] = None
    amount: Decimal = Decimal("0")
    branch_id: Optional[int] = None
    voucher_type: Optional[str] = "receipt"
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    treasury_account_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    transaction_rate: Optional[Decimal] = None
    allocations: List[PaymentAllocation] = Field(default_factory=list)
    auto_allocate: bool = False
    pay_all: bool = False
    fill_invoice_id: Optional[int] = None
