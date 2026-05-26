from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_purchase_line_schema_accepts_raw_inputs_without_frontend_tax_rate():
    schemas = _read("backend/schemas/purchases.py")

    assert "tax_rate: Optional[Decimal] = None" in schemas


def test_purchase_backend_resolves_tax_groups_authoritatively():
    sources = [
        "backend/routers/purchases/orders.py",
        "backend/routers/purchases/invoices.py",
        "backend/routers/purchases/returns.py",
        "backend/routers/purchases/payments.py",
    ]

    missing = []
    for relative_path in sources:
        source = _read(relative_path)
        if "resolve_line_tax_group" not in source:
            missing.append(relative_path)
        if "resolve_line_tax(" in source:
            missing.append(f"{relative_path}: legacy resolve_line_tax")

    assert missing == []


def test_purchase_frontend_sends_raw_line_inputs_only():
    files = [
        "frontend/src/pages/Buying/BuyingOrderForm.jsx",
        "frontend/src/pages/Buying/PurchaseInvoiceForm.jsx",
        "frontend/src/pages/Buying/BuyingReturnForm.jsx",
        "frontend/src/pages/Buying/PurchaseCreditNotes.jsx",
        "frontend/src/pages/Buying/PurchaseDebitNotes.jsx",
    ]
    forbidden = [
        re.compile(r"tax_rate:\s*null"),
        re.compile(r"tax_rate:\s*String"),
        re.compile(r"updatedItem\.tax_rate"),
        re.compile(r"lines\[i\]\.tax_rate"),
        re.compile(r"updateLine\(i,\s*'tax_rate'"),
    ]

    offenders = []
    for relative_path in files:
        source = _read(relative_path)
        for pattern in forbidden:
            if pattern.search(source):
                offenders.append(f"{relative_path}: {pattern.pattern}")

    assert offenders == []


def test_purchase_frontend_displays_backend_preview_lines():
    files = [
        "frontend/src/pages/Buying/BuyingOrderForm.jsx",
        "frontend/src/pages/Buying/PurchaseInvoiceForm.jsx",
        "frontend/src/pages/Buying/BuyingReturnForm.jsx",
        "frontend/src/pages/Buying/PurchaseCreditNotes.jsx",
        "frontend/src/pages/Buying/PurchaseDebitNotes.jsx",
    ]

    missing = []
    for relative_path in files:
        source = _read(relative_path)
        if "backendLines" not in source:
            missing.append(f"{relative_path}: backendLines")
        if "line_total" not in source:
            missing.append(f"{relative_path}: line_total")

    assert missing == []


def test_purchase_invoice_and_return_forms_do_not_use_frontend_decimal_decisions():
    invoice_form = _read("frontend/src/pages/Buying/PurchaseInvoiceForm.jsx")
    return_form = _read("frontend/src/pages/Buying/BuyingReturnForm.jsx")

    assert "decimal.js" not in invoice_form
    assert "new Decimal" not in invoice_form
    assert ".gt(" not in invoice_form
    assert "item.can_invoice" in invoice_form
    assert "hasNonZeroDecimalInput(item.remaining_to_invoice)" in invoice_form

    assert "decimal.js" not in return_form
    assert "new Decimal" not in return_form
    assert ".gt(" not in return_form
    assert "Cannot return more than purchased" not in return_form


def test_landed_costs_blanket_and_matching_use_backend_authoritative_values():
    landed = _read("backend/routers/landed_costs.py")
    blanket_router = _read("backend/routers/purchases/blanket.py")
    blanket_list = _read("frontend/src/pages/BlanketPO/BlanketPOList.jsx")
    blanket_detail = _read("frontend/src/pages/BlanketPO/BlanketPODetail.jsx")
    matching_detail = _read("frontend/src/pages/Matching/MatchDetail.jsx")

    assert "money_str(total)" in landed
    assert '"total_allocated": money_str' in landed
    assert "_blanket_po_calculated_fields" in blanket_router
    assert "consumption_progress_pct" in blanket_router
    assert "bpo.consumption_progress_pct" in blanket_list
    assert "released_quantity / total_quantity" not in blanket_list
    assert "bpo.consumption_progress_pct" in blanket_detail
    assert "bpo.is_fully_released" in blanket_detail
    assert "remainingQty <= 0" not in blanket_detail
    assert "progressPct.toFixed" not in blanket_detail
    assert "row.line_status !== 'matched'" in matching_detail
    assert "val > 0" not in matching_detail


def test_purchase_order_receive_and_invoice_decisions_are_backend_flags():
    orders_router = _read("backend/routers/purchases/orders.py")
    order_details = _read("frontend/src/pages/Buying/PurchaseOrderDetails.jsx")
    legacy_order_details = _read("frontend/src/pages/Buying/BuyingOrderDetails.jsx")
    receive_form = _read("frontend/src/pages/Buying/PurchaseOrderReceive.jsx")

    for expected in [
        '"has_remaining_to_receive"',
        '"has_remaining_to_invoice"',
        '"has_received_value"',
        '"can_receive"',
        '"default_receive_quantity"',
    ]:
        assert expected in orders_router

    assert "Boolean(order.has_remaining_to_invoice)" in order_details
    assert "order.has_remaining_to_invoice" in legacy_order_details
    assert "item.has_remaining_to_receive" in order_details
    assert "item.has_remaining_to_invoice" in order_details
    assert "item.default_receive_quantity" in receive_form
    assert "item?.can_receive" in receive_form

    forbidden = [
        "new Decimal",
        ".gt(",
        "item.quantity - received",
        "remainingToInvoice > 0",
        "received > 0",
        "remaining > 0",
    ]
    combined = "\n".join([order_details, legacy_order_details, receive_form])
    offenders = [pattern for pattern in forbidden if pattern in combined]

    assert offenders == []


def test_supplier_payment_preview_drives_allocation_decisions():
    payments_router = _read("backend/routers/purchases/payments.py")
    payment_form = _read("frontend/src/pages/Purchases/PaymentForm.jsx")

    for expected in [
        '"amount_is_positive"',
        '"has_unallocated_amount"',
        '"has_allocations"',
        '"has_open_invoices"',
        '"can_auto_allocate"',
    ]:
        assert expected in payments_router

    assert "paymentPreview?.can_auto_allocate" in payment_form
    assert "paymentPreview?.has_unallocated_amount" in payment_form
    assert "decimal.js" not in payment_form
    assert "new Decimal" not in payment_form
    assert ".gt(" not in payment_form
    assert "isPositiveDecimal" not in payment_form
