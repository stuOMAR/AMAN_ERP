"""Regression checks for docs/AUDIT_REPORT_FINANCE_TREASURY_TAX.md fixes."""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_vat_report_includes_sales_notes_and_excludes_uncleared_zatca():
    src = _read("backend/routers/finance/taxes/reports.py")
    body = src.split("def get_vat_report(", 1)[1].split("# ==================== TAX AUDIT", 1)[0]

    assert 'sales_credit_note' in body
    assert 'sales_debit_note' in body
    assert "- _dec(output_credit_notes.vat_amount)" in body
    assert "+ _dec(output_debit_notes.vat_amount)" in body
    assert "zatca_clearance_status" in body
    assert "'pending_clearance', 'rejected'" in body


def test_fiscal_period_lock_unique_index_is_in_migration_and_schema():
    migration = _read("backend/alembic/versions/0032_finance_treasury_tax_audit_fixes.py")
    schema = _read("backend/db_ddl/tenant_schema.py")

    assert "uq_fiscal_period_locks_period" in migration
    assert "ON fiscal_period_locks (period_start, period_end)" in migration
    assert "uq_fiscal_period_locks_period" in schema
    assert "ON fiscal_period_locks (period_start, period_end)" in schema


def test_cashflow_report_does_not_cast_money_to_float():
    src = _read("backend/routers/finance/treasury.py")
    body = src.split("def get_treasury_cashflow_report(", 1)[1]
    body = body.split("\n@router.", 1)[0]

    assert "float(" not in body
    assert '"total_inflow": str(total_in)' in body
    assert '"net_flow": str((total_in - total_out).quantize(_D2, ROUND_HALF_UP))' in body


def test_treasury_recalc_derives_from_posted_journal_lines():
    src = _read("backend/utils/treasury_balance.py")

    assert "FROM journal_lines jl" in src
    assert "JOIN journal_entries je" in src
    assert "je.status = 'posted'" in src
    assert "info.balance" not in src
    assert "info.balance_currency" not in src


def test_reconciliation_auto_match_locks_bank_lines():
    src = _read("backend/routers/finance/reconciliation.py")
    body = src.split("def auto_match(", 1)[1].split("# Get unmatched ledger entries", 1)[0]

    assert "FROM bank_statement_lines" in body
    assert "FOR UPDATE SKIP LOCKED" in body
    auto_match = src.split("def auto_match(", 1)[1].split("def delete_statement_line", 1)[0]
    assert "t.currency" in auto_match
    assert "jl.amount_currency" in auto_match


def test_zatca_outbox_is_enqueued_and_scheduled():
    invoices = _read("backend/routers/sales/invoices.py")
    scheduler = _read("backend/services/scheduler.py")
    outbox = _read("backend/services/einvoicing/outbox.py")
    migration = _read("backend/alembic/versions/0032_finance_treasury_tax_audit_fixes.py")

    assert "enqueue_zatca_outbox(" in invoices
    assert "process_zatca_outbox_all_tenants" in scheduler
    assert "'zatca_outbox_flush'" in scheduler
    assert "process_batch(conn)" in scheduler
    assert "max_attempts" in migration
    assert "state = 'submitting'" in outbox


def test_remaining_audit_points_are_hardened():
    reports = _read("backend/routers/finance/taxes/reports.py")
    tax_engine = _read("backend/services/tax_engine.py")
    sales_invoices = _read("backend/routers/sales/invoices.py")
    wht = _read("backend/routers/external.py")
    accounting_depth = _read("backend/routers/finance/accounting_depth.py")
    zatca_adapter = _read("backend/integrations/einvoicing/zatca_adapter.py")
    statements = _read("backend/routers/reports/accounting_statements.py")
    multibook = _read("backend/services/multibook_service.py")
    treasury_js = _read("frontend/src/services/treasury.js")
    invoice_form = _read("frontend/src/pages/Sales/InvoiceForm.jsx")

    assert "get_mapped_account_id(db, \"acc_map_vat_out\")" in reports
    assert "SUM(jl.credit - jl.debit)" in reports
    assert "SUM(jl.debit - jl.credit)" in reports

    assert "product_tax_rate_expired" in tax_engine
    assert "product_tax_rate_wrong_country" in tax_engine
    assert "fall through" not in tax_engine.split("# Priority 4: Product has a specific tax assigned", 1)[1].split("# Priority 5", 1)[0]

    assert "transition_invoice_state(" in sales_invoices
    assert "dispatch_side_effects=False" in sales_invoices
    cancel_body = sales_invoices.split("def cancel_invoice(", 1)[1]
    assert "state = CASE WHEN state IN" not in cancel_body
    assert "wht_payment_required" in wht
    assert "gl_create_journal_entry(" in wht
    assert "source=\"payment_voucher_wht\"" in wht
    assert "UPDATE wht_transactions" in wht
    assert "journal_entry_id = :journal_entry_id" in wht

    assert "SELECT id, invoice_id, adapter, payload, attempts, idempotency_key" in accounting_depth
    assert "payload[\"idempotency_key\"]" in accounting_depth
    assert "headers[\"Idempotency-Key\"]" in zatca_adapter

    assert "COALESCE(je.source, '') <> 'reversal'" in statements
    assert 'results.append({"ledger_id": ledger_id, "error": str(e)})' not in multibook
    assert "raise" in multibook.split("except Exception:", 1)[1]

    assert "createExpense: (data) => withPermission('treasury.manage'" in treasury_js
    assert "createTransfer: (data) => withPermission('treasury.manage'" in treasury_js
    assert "listAccounts: (branchId) => withPermission('treasury.view'" in treasury_js
    assert "getCashflowReport: (params) => withPermission('treasury.view'" in treasury_js
    assert "finalize: (id) => withPermission('finance.reconciliation.finalize'" in treasury_js
    assert "status: 'draft'" in invoice_form


def test_tax_summary_matches_vat_report_note_and_zatca_filters():
    src = _read("backend/routers/finance/taxes/reports.py")
    body = src.split("def get_tax_summary(", 1)[1].split("# ==================== TAX SETTLEMENT", 1)[0]

    assert "'sales_debit_note'" in body
    assert "'sales_credit_note'" in body
    assert "'purchase_debit_note'" in body
    assert "'purchase_credit_note'" in body
    assert "WHEN inv.invoice_type IN ('sales_return', 'sales_credit_note') THEN -inv.vat_amount" in body
    assert "WHEN inv.invoice_type IN ('purchase_return', 'purchase_credit_note') THEN -inv.vat_amount" in body
    assert "zatca_clearance_status" in body
    assert "'pending_clearance', 'rejected'" in body


def test_wht_transaction_posts_incremental_payment_voucher_gl():
    src = _read("backend/routers/external.py")
    body = src.split("def create_wht_transaction(", 1)[1].split("@router.get(\"/wht/transactions\"", 1)[0]

    assert "payment.voucher_type != \"payment\"" in body
    assert "je.source = 'payment_voucher'" in body
    assert "\"debit\": cash_debit_amount" in body
    assert "\"credit\": wht_base" in body
    assert "source=\"payment_voucher_wht\"" in body
    assert "idempotency_key=f\"{idempotency_key}:gl\"" in body
    assert "journal_entry_id = :journal_entry_id" in body


def test_treasury_account_listing_avoids_float_money_casts():
    src = _read("backend/routers/finance/treasury.py")
    body = src.split("def list_treasury_accounts(", 1)[1].split("\n@router.", 1)[0]

    assert "float(" not in body
    assert "_dec(d.get(\"current_balance\", 0)" in body
    assert "str(raw_balance)" in body


def test_remaining_verification_gaps_are_closed():
    treasury_balance = _read("backend/utils/treasury_balance.py")
    reconciliation = _read("backend/routers/finance/reconciliation.py")
    accounting_depth = _read("backend/routers/finance/accounting_depth.py")
    migration = _read("backend/alembic/versions/0032_finance_treasury_tax_audit_fixes.py")
    schema = _read("backend/db_ddl/tenant_schema.py")
    gl_service = _read("backend/services/gl_service.py")
    sales_invoices = _read("backend/routers/sales/invoices.py")
    invoice_state = _read("backend/services/sales/invoice_state.py")

    assert "setting current_balance to 0 instead of relabeling base balance" in treasury_balance
    assert 'new_balance = Decimal("0")' in treasury_balance

    assert "reconciliation_auto_match_tolerance.{code}" in reconciliation
    assert "reconciliation_auto_match_tolerance_" in reconciliation
    assert 'return Decimal("0.001")' in reconciliation
    assert 'return Decimal("0.01")' in reconciliation

    assert 'f"einvoice-outbox:{r.id}:{attempts}"' not in accounting_depth
    assert 'f"einvoice-outbox:{r.id}"' in accounting_depth

    assert "ORDER BY kept.locked_at DESC NULLS LAST" in migration
    assert "ORDER BY locked_at DESC NULLS LAST" in migration

    assert "assert_journal_line_account_currency" in migration
    assert "assert_journal_line_account_currency" in schema
    assert "journal_line_account_currency_mismatch" in gl_service

    assert "dispatch_side_effects: bool = True" in invoice_state
    assert "transition_invoice_state(" in sales_invoices
    assert "invalid_invoice_state_transition" in sales_invoices
