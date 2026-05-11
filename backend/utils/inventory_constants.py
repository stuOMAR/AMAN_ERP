"""Standardized inventory transaction type constants.

Replaces inconsistent string literals across the codebase:
- 'purchase_in' → TX_PURCHASE_RECEIPT
- 'purchase' → TX_PURCHASE_INVOICE
- 'purchase_return' → TX_PURCHASE_RETURN (unchanged)
"""

# Purchase flow
TX_PURCHASE_RECEIPT = "purchase_receipt"
TX_PURCHASE_INVOICE = "purchase_invoice"
TX_PURCHASE_RETURN = "purchase_return"

# Sales flow
TX_SALES_OUT = "sales_out"
TX_SALES_RETURN = "sales_return"

# Transfers
TX_TRANSFER_IN = "transfer_in"
TX_TRANSFER_OUT = "transfer_out"

# Adjustments
TX_ADJUSTMENT_IN = "adjustment_in"
TX_ADJUSTMENT_OUT = "adjustment_out"

# Shipments
TX_SHIPMENT_IN = "shipment_in"
TX_SHIPMENT_OUT = "shipment_out"

# All purchase-related types (for stock movement report filtering)
PURCHASE_TRANSACTION_TYPES = [
    TX_PURCHASE_RECEIPT,
    TX_PURCHASE_INVOICE,
    TX_PURCHASE_RETURN,
]
