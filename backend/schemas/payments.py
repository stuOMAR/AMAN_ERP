"""Unified payment voucher schemas.

Replaces the following duplicated schemas:
- SupplierPaymentCreate (schemas/purchases.py)
- CustomerReceiptCreate (routers/sales/schemas.py)
- CustomerPaymentCreate (routers/sales/schemas.py)
- PaymentAllocationSchema (schemas/purchases.py)
- PaymentAllocation (routers/sales/schemas.py)

All payment vouchers use the `payment_vouchers` table with `party_type`
discriminator ('customer' or 'supplier').
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from decimal import Decimal


class PaymentAllocation(BaseModel):
    """Allocation of a payment to a specific invoice."""
    invoice_id: int
    allocated_amount: Decimal


# Alias for backward compatibility
PaymentAllocationSchema = PaymentAllocation


class PaymentVoucherCreate(BaseModel):
    """Unified payment voucher schema for all party types.

    Used for:
    - Customer receipts (voucher_type='receipt', party_type='customer')
    - Customer payments/refunds (voucher_type='payment', party_type='customer')
    - Supplier payments (voucher_type='payment', party_type='supplier')
    - Supplier receipts (voucher_type='receipt', party_type='supplier')
    """
    # Party
    party_id: int
    party_type: str = "customer"  # 'customer' or 'supplier'
    voucher_type: str = "receipt"  # 'receipt' or 'payment'

    # Core
    voucher_date: date
    amount: Decimal
    payment_method: str

    # Bank/Check details
    bank_account_id: Optional[int] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None

    # Reference
    reference: Optional[str] = None
    notes: Optional[str] = None

    # Branch & Treasury
    branch_id: Optional[int] = None
    treasury_id: Optional[int] = None
    treasury_account_id: Optional[int] = None

    # Currency
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Decimal("1.0")
    transaction_rate: Optional[Decimal] = None

    # Allocations
    allocations: List[PaymentAllocation] = []


# Backward-compatible aliases
class CustomerReceiptCreate(PaymentVoucherCreate):
    """Customer receipt - alias for PaymentVoucherCreate."""
    party_type: str = "customer"
    voucher_type: str = "receipt"
    # Alias field: customer_id maps to party_id
    customer_id: Optional[int] = None

    def __init__(self, **data):
        if 'customer_id' in data and 'party_id' not in data:
            data['party_id'] = data.pop('customer_id')
        elif 'customer_id' in data:
            data.pop('customer_id')
        super().__init__(**data)


class CustomerPaymentCreate(PaymentVoucherCreate):
    """Customer payment/refund - alias for PaymentVoucherCreate."""
    party_type: str = "customer"
    voucher_type: str = "payment"
    customer_id: Optional[int] = None

    def __init__(self, **data):
        if 'customer_id' in data and 'party_id' not in data:
            data['party_id'] = data.pop('customer_id')
        elif 'customer_id' in data:
            data.pop('customer_id')
        super().__init__(**data)


class SupplierPaymentCreate(PaymentVoucherCreate):
    """Supplier payment - alias for PaymentVoucherCreate."""
    party_type: str = "supplier"
    voucher_type: str = "payment"
    supplier_id: Optional[int] = None

    def __init__(self, **data):
        if 'supplier_id' in data and 'party_id' not in data:
            data['party_id'] = data.pop('supplier_id')
        elif 'supplier_id' in data:
            data.pop('supplier_id')
        super().__init__(**data)
