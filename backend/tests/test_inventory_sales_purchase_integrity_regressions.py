"""Regression pins for sales, purchases, and inventory integrity fixes."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_sales_invoice_clearance_happens_before_commit():
    src = _read("routers/sales/invoices.py")
    create_block = src.split("def create_sales_invoice(")[1].split("@invoices_router.get")[0]
    assert "with transactional(company_id) as db:" in create_block
    assert "attempt_clearance(" in create_block
    assert "db.commit()" not in create_block
    assert "db.rollback()" not in create_block


def test_sales_invoice_cancel_uses_reversal_je_not_manual_balance_updates():
    src = _read("routers/sales/invoices.py")
    cancel_block = src.split("def cancel_invoice(")[1].split("# ===========================================================================")[0]
    assert "reverse_journal_entry(" in cancel_block
    assert "update_account_balance(" not in cancel_block
    assert "UPDATE journal_entries" not in cancel_block
    assert "invoice_paid_cannot_cancel" not in cancel_block
    assert "has_independent_receipt_je" in cancel_block
    assert "invoice_has_payment_allocations" in cancel_block
    assert "DELETE FROM payment_allocations" in cancel_block
    assert "recalc_treasury_from_gl" in cancel_block
    assert "remaining_balance = (_dec(inv.total) - _dec(inv.paid_amount or 0))" in cancel_block
    assert "check_fiscal_period_open(db, reversal_date" in cancel_block
    assert "'reservation_restore'" in cancel_block
    assert "SET status = 'draft', updated_at = NOW()" in cancel_block


def test_sales_invoice_partial_cash_and_receipt_permission_are_enforced():
    src = _read("routers/sales/invoices.py")
    create_block = src.split("def create_sales_invoice(")[1].split("@invoices_router.get")[0]
    permissions = _read("utils/permissions.py")
    roles = _read("routers/roles.py")
    form = _read("../frontend/src/pages/Sales/InvoiceForm.jsx")
    vouchers = _read("routers/sales/vouchers.py")

    assert "and paid_amount <= _D2" in create_block
    assert "paid_amount = grand_total" in create_block
    assert 'check_permission(_user_permissions(current_user), "sales.receipt")' in create_block
    assert "paid_amount_exceeds_invoice_total" in create_block
    assert '"sales.receipt"' in permissions
    assert '"sales.receipt"' in roles
    assert 'require_permission("sales.receipt")' in vouchers
    assert "paid_amount: getTotals().total" in form
    assert "max={getTotals().total}" in form


def test_sales_invoice_wac_cost_is_read_under_inventory_lock():
    src = _read("routers/sales/invoices.py")
    create_block = src.split("def create_sales_invoice(")[1].split("@invoices_router.get")[0]
    assert "prefetched_unit_costs" not in create_block
    assert "SELECT average_cost" in create_block
    assert "FOR UPDATE" in create_block
    assert "item_cogs = (unit_cost * qty).quantize" in create_block


def test_sales_credit_limit_uses_invoice_date_rates():
    src = _read("routers/sales/invoices.py")
    create_block = src.split("def create_sales_invoice(")[1].split("@invoices_router.get")[0]
    assert "WHEN psb.currency = :inv_currency THEN :invoice_rate" in create_block
    assert "er.rate_date <= :invoice_date" in create_block
    assert '"invoice_rate": exchange_rate' in create_block


def test_sales_order_reservation_is_atomic():
    src = _read("routers/sales/orders.py")
    create_block = src.split("def create_sales_order(")[1]
    assert "UPDATE inventory" in create_block
    assert "quantity - COALESCE(reserved_quantity, 0) >= :qty" in create_block
    assert "RETURNING id" in create_block


def test_sales_order_cancel_releases_reservations():
    src = _read("routers/sales/orders.py")
    cancel_block = src.split("def cancel_sales_order(")[1].split("@orders_router.post(\"/orders\"")[0]
    assert '"/orders/{order_id}/cancel"' in src
    assert "FOR UPDATE" in cancel_block
    assert "reserved_quantity = GREATEST(0, COALESCE(reserved_quantity, 0) - :qty)" in cancel_block
    assert "'reservation_release', 'sales_order_cancel'" in cancel_block


def test_sales_return_approval_locks_and_cas_updates_status():
    src = _read("routers/sales/returns.py")
    approve_block = src.split("def approve_sales_return(")[1]
    create_block = src.split("def create_sales_return(")[1].split("@returns_router.post(\"/returns/{return_id}/approve\"")[0]
    assert "FROM sales_returns WHERE id = :id FOR UPDATE" in approve_block
    assert "WHERE id = :id AND status = 'draft'" in approve_block
    assert "paid_amount = COALESCE(paid_amount, 0) + :return_val" not in approve_block
    assert "paid_amount is left" in approve_block
    assert "return_warehouse_id = data.warehouse_id" in create_block
    assert "return_warehouse_mismatch_invoice" in create_block
    assert '"wh_id": return_warehouse_id' in create_block


def test_receipt_auto_match_uses_canonical_voucher_type():
    src = _read("routers/sales/vouchers.py")
    auto_match_block = src.split("def auto_match_receipt(")[1]
    assert "voucher_type = 'receipt'" in auto_match_block
    assert "party_type = 'customer'" in auto_match_block
    assert "customer_receipt" not in auto_match_block


def test_sales_routers_accept_dict_current_user_helpers():
    for relative in (
        "routers/sales/returns.py",
        "routers/sales/vouchers.py",
        "routers/sales/customers.py",
        "routers/sales/quotations.py",
    ):
        src = _read(relative)
        assert "def _company_id(user)" in src
        assert "def _user_id(user)" in src
        assert "def _username(user)" in src
        assert "current_user.company_id" not in src
        assert "current_user.id" not in src
        assert "current_user.username" not in src


def test_sales_quotation_cancel_endpoint_and_client_helper_exist():
    quotations = _read("routers/sales/quotations.py")
    sales_service = _read("../frontend/src/services/sales.js")
    assert '"/quotations/{id}/cancel"' in quotations
    assert "FOR UPDATE" in quotations.split("def cancel_quotation(")[1]
    assert "quotation_cannot_cancel_status" in quotations
    assert "cancelQuotation: (id) => api.post(`/sales/quotations/${id}/cancel`)" in sales_service


def test_sales_return_cancel_draft_endpoint_and_client_helper_exist():
    returns = _read("routers/sales/returns.py")
    sales_service = _read("../frontend/src/services/sales.js")
    cancel_block = returns.split("def cancel_sales_return(")[1]
    approve_block = returns.split("def approve_sales_return(")[1].split("@returns_router.post(\"/returns/{return_id}/cancel\"")[0]
    assert '"/returns/{return_id}/cancel"' in returns
    assert "FOR UPDATE" in cancel_block
    assert 'header.status == "draft"' in cancel_block
    assert 'header.status == "approved"' in cancel_block
    assert "sales_return_no_je_to_reverse" in cancel_block
    assert "reverse_journal_entry(" in cancel_block
    assert "'sales_return_cancel'" in cancel_block
    assert "insufficient_stock_for_sales_return_cancel" in cancel_block
    assert "refund_reversal_total" in cancel_block
    assert approve_block.index("create_journal_entry(") < approve_block.index("recalc_treasury_from_gl")
    assert "cancelReturn: (id) => api.post(`/sales/returns/${id}/cancel`)" in sales_service


def test_landed_costs_follow_buying_module_and_permissions():
    src = _read("routers/landed_costs.py")
    assert 'require_module("buying")' in src
    assert '"purchases.view"' not in src
    assert '"purchases.create"' not in src


def test_purchase_invoice_cancel_reverses_accounting_stock_and_links():
    src = _read("routers/purchases/invoices.py")
    cancel_block = src.split("def cancel_purchase_invoice(")[1].split("# === Purchase Returns ===")[0]
    assert '"/invoices/{id}/cancel"' in src
    assert 'require_sensitive_permission("buying.void")' in src
    assert "check_fiscal_period_open(db, reversal_date" in cancel_block
    assert "purchase_invoice_no_je_to_reverse" in cancel_block
    assert "reverse_journal_entry(" in cancel_block
    assert "source = 'purchase_invoice'" in cancel_block
    assert "source = 'payment_voucher'" in cancel_block
    assert "has_payment_voucher_je" in cancel_block
    assert "Payment for" not in cancel_block
    assert "'purchase_invoice_cancel'" in cancel_block
    assert "GREATEST(0, COALESCE(invoiced_quantity, 0) - :qty)" in cancel_block
    assert "purchase_invoice_has_payment_allocations" in cancel_block


def test_purchase_po_invoice_posts_extra_received_qty_to_inventory_not_variance():
    src = _read("routers/purchases/invoices.py")
    create_block = src.split("def create_purchase_invoice(")[1].split("@router.get(\"/invoices\"")[0]
    assert "invoice_stock_addition_base" in create_block
    assert "gl_stock_addition = invoice_stock_addition_base if invoice.original_invoice_id else Decimal('0')" in create_block
    assert "gl_purchase_variance = gl_inventory_debit - gl_stock_addition" in create_block
    assert "if invoice.original_invoice_id and gl_stock_addition > _D2" in create_block
    assert "elif not invoice.original_invoice_id and gl_inventory_debit > _D2" in create_block


def test_purchase_return_cancel_reverses_stock_gl_refund_and_balance():
    src = _read("routers/purchases/returns.py")
    service = _read("../frontend/src/services/purchases.js")
    party_balance = _read("utils/party_balance.py")
    cancel_block = src.split("def cancel_purchase_return(")[1]
    assert '"/returns/{id}/cancel"' in src
    assert 'require_sensitive_permission("buying.void")' in src
    assert "purchase_return_no_je_to_reverse" in cancel_block
    assert "'purchase_return_cancel'" in cancel_block
    assert "reverse_journal_entry(" in cancel_block
    assert "source = 'payment_voucher'" in cancel_block
    assert "recalc_treasury_from_gl" in cancel_block
    assert 'document_type="purchase_return_cancel"' in cancel_block
    assert 'document_type="supplier_refund_cancel"' in cancel_block
    assert '"purchase_return_cancel"' in party_balance
    assert '"supplier_refund_cancel"' in party_balance
    assert "cancelReturn: (id) => api.post(`/buying/returns/${id}/cancel`)" in service


def test_deprecated_inventory_transfer_no_longer_catches_post():
    src = _read("routers/inventory/transfer_deprecated.py")
    route_line = src.split("@router.api_route")[1].splitlines()[0]
    assert '"/transfer-legacy"' in route_line
    assert '"/transfer"' not in route_line
    assert '"POST"' not in route_line


def test_stock_transfer_gl_has_source_identity():
    src = _read("routers/inventory/transfers.py")
    single_block = src.split("def create_stock_transfer(")[1].split("@transfers_router.post(\"/transfer\"")[0]
    assert "with transactional(_company_id(current_user)) as db:" in single_block
    assert "db.commit()" not in single_block
    assert "db.rollback()" not in single_block
    # F-30: cross-currency transfers are now allowed (legacy rejection helper
    # has been removed). The branch currency rides along on txn_currency for
    # reporting while the JE itself is posted in base currency.
    assert "_reject_cross_currency_transfer" not in src
    assert "txn_currency" in src
    # F-31: per-warehouse inventory accounts on both sides of the transfer JE.
    assert "_resolve_inventory_account_for_wh(db, src_wh)" in src
    assert "_resolve_inventory_account_for_wh(db, dst_wh)" in src
    assert "WH#{dst_wh.id}" in src
    assert "WH#{src.id}" in src
    assert 'source="inventory_transfer"' in src
    assert "source_id=transfer_doc_id" in src
    assert 'idempotency_key=f"inventory_transfer:{transfer_doc_id}"' in src


def test_warehouse_per_warehouse_inventory_account_is_wired():
    """F-31 — the per-warehouse inventory account is exposed end-to-end.

    Migration adds the column, tenant_schema declares it, the schema
    layer round-trips it, the warehouses router exposes get/list/create/
    update, and the resolver helper falls back to the global mapping."""
    migration = _read("alembic/versions/029a_warehouse_gl_inventory_account.py")
    schema_dll = _read("db_ddl/tenant_schema.py")
    helper = _read("utils/inventory_accounts.py")
    schemas = _read("schemas/__init__.py")
    router = _read("routers/inventory/warehouses.py")

    assert 'down_revision = "028a_purchase_integrity"' in migration
    assert "ADD COLUMN IF NOT EXISTS gl_inventory_account_id" in migration
    assert "FROM company_settings s" in migration  # backfill present
    assert "gl_inventory_account_id INTEGER REFERENCES accounts(id)" in schema_dll
    assert "def resolve_warehouse_inventory_account" in helper
    assert "def require_warehouse_inventory_account" in helper
    assert "gl_inventory_account_id: Optional[int]" in schemas
    # Router accepts and persists the column on create + update, and surfaces
    # the resolved code/name on read.
    assert "INSERT INTO warehouses (warehouse_name, warehouse_code, branch_id, gl_inventory_account_id)" in router
    assert "gl_inventory_account_id = :acc_id" in router
    assert "gl_inventory_account_code" in router
    assert "inventory_account_must_be_leaf" in router
    assert "inventory_account_must_be_asset" in router


def test_inventory_account_resolution_used_at_each_inventory_callsite():
    """F-31 — every JE that touches inventory routes through the
    per-warehouse resolver instead of pulling acc_map_inventory directly.

    Callsites that genuinely have no warehouse context (service GL,
    supplier credit/debit notes, expense category map) keep using the
    global mapping; we explicitly exempt them from the assertion below.
    """
    callsites = [
        "routers/inventory/transfers.py",
        "routers/inventory/shipments.py",
        "routers/inventory/adjustments.py",
        "routers/inventory/stock_movements.py",
        "routers/inventory/batches.py",
        "routers/sales/invoices.py",
        "routers/sales/returns.py",
        "routers/purchases/invoices.py",
        "routers/purchases/orders.py",
        "routers/purchases/returns.py",
        "routers/landed_costs.py",
        "routers/delivery_orders.py",
        "routers/pos/orders.py",
        "routers/manufacturing/core/orders.py",
    ]
    for relative in callsites:
        src = _read(relative)
        assert "resolve_warehouse_inventory_account" in src, f"{relative} must use resolver"


def test_cross_currency_transfer_records_branch_currency():
    """F-30 — cross-currency transfers are no longer rejected; instead the
    JE keeps its booking-side amount in base currency while ``txn_currency``/
    ``txn_amount`` capture the source/destination branch currencies."""
    src = _read("routers/inventory/transfers.py")
    # The legacy reject helper is gone — both endpoints fall through.
    assert "cross_currency_inventory_transfer_not_supported" not in src
    # Both single + multi item paths emit txn_currency on each line.
    assert src.count('"txn_currency": dst_currency') >= 1
    assert src.count('"txn_currency": src_currency') >= 1


def test_landed_cost_je_splits_inventory_per_warehouse():
    """F-31 — landed-cost posting builds one Dr Inventory line per warehouse
    using the warehouse-mapped account so a multi-warehouse PO does not
    pile its allocated overhead onto a single global account."""
    src = _read("routers/landed_costs.py")
    assert "warehouse_debit_base" in src
    assert "resolve_warehouse_inventory_account" in src
    assert 'description": f"تكاليف مُضافة - مخزون (WH#{wh_id})"' in src


def test_pending_shipments_reduce_create_available_quantity():
    src = _read("routers/inventory/shipments.py")
    create_block = src.split("def create_shipment(")[1].split("@shipments_router.get")[0]
    assert "JOIN stock_shipments s ON s.id = si.shipment_id" in create_block
    assert "s.status = 'pending'" in create_block
    assert "available_qty = current_qty - reserved_qty - Decimal(str(pending_qty))" in create_block


def test_frontend_exposes_cancel_helpers_and_submit_guards():
    sales_service = _read("../frontend/src/services/sales.js")
    purchases_service = _read("../frontend/src/services/purchases.js")
    sales_form = _read("../frontend/src/pages/Sales/InvoiceForm.jsx")
    purchase_form = _read("../frontend/src/pages/Buying/PurchaseInvoiceForm.jsx")
    transfer_form = _read("../frontend/src/pages/Stock/StockTransferForm.jsx")
    shipment_form = _read("../frontend/src/pages/Stock/StockShipmentForm.jsx")

    assert "cancelOrder: (id) => api.post(`/sales/orders/${id}/cancel`)" in sales_service
    assert "cancelInvoice: (id) => api.post(`/buying/invoices/${id}/cancel`)" in purchases_service
    for form_src in (sales_form, purchase_form, transfer_form, shipment_form):
        assert "submittingRef.current" in form_src


def test_treasury_balance_updates_use_recalc_not_direct_router_updates():
    files = [
        "routers/purchases/payments.py",
        "routers/purchases/returns.py",
        "routers/purchases/invoices.py",
        "routers/finance/expenses.py",
        "routers/hr/core/payroll.py",
    ]
    for relative in files:
        src = _read(relative)
        assert "UPDATE treasury_accounts" not in src
        assert "SET current_balance" not in src

    assert "recalc_treasury_from_gl" in _read("routers/purchases/payments.py")
    assert "recalc_treasury_from_gl" in _read("routers/purchases/returns.py")
    assert "recalc_treasury_from_gl" in _read("routers/finance/expenses.py")
    assert "recalc_treasury_from_gl" in _read("routers/hr/core/payroll.py")


def test_buying_void_permission_and_party_balance_guard_are_registered():
    permissions = _read("utils/permissions.py")
    roles = _read("routers/roles.py")
    party_balance = _read("utils/party_balance.py")

    assert '"buying.void"' in permissions
    assert '"buying.manage"' in permissions and '"buying.void"' in permissions
    assert '"buying.void"' in roles
    assert '"purchase_invoice_cancel"' in party_balance.split("_NEGATIVE_BALANCE_DOCUMENTS")[0]
