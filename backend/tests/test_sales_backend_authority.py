from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_sales_backend_exposes_authoritative_aging_and_commission_fields():
    reports = _read("backend/routers/reports/sales.py")
    commissions = _read("backend/routers/sales/sales_improvements.py")

    for token in [
        '"/sales/aging/summary"',
        '"buckets"',
        '"total_due"',
        "_money_str",
    ]:
        assert token in reports

    for token in [
        "total_commissions",
        "total_pending",
        "total_paid",
        "validate_branch_access",
    ]:
        assert token in commissions


def test_sales_frontend_uses_backend_aging_summary_and_raw_commission_payloads():
    aging = _read("frontend/src/pages/Sales/AgingReport.jsx")
    commissions = _read("frontend/src/pages/Sales/SalesCommissions.jsx")
    reports_service = _read("frontend/src/services/reports.js")

    assert "getAgingSummary" in aging
    assert "getAgingSummary" in reports_service
    assert "res.data.buckets" in aging
    assert "res.data.total_due" in aging
    assert "rate: String(ruleForm.rate || '0')" in commissions
    assert "min_amount: String(ruleForm.min_amount || '0')" in commissions


def test_sales_frontend_no_longer_runs_targeted_authoritative_calculations():
    files = [
        "frontend/src/pages/Sales/AgingReport.jsx",
        "frontend/src/pages/Sales/SalesCommissions.jsx",
        "frontend/src/pages/Sales/DeliveryOrderForm.jsx",
        "frontend/src/pages/Sales/ContractForm.jsx",
    ]
    forbidden = [
        re.compile(r"\.reduce\("),
        re.compile(r"agg\[item\.bucket\]"),
        re.compile(r"\+=\s*item\.amount"),
        re.compile(r"\bNumber\(ruleForm\.(rate|min_amount)\)"),
        re.compile(r"\bNumber\(l\.quantity\)"),
        re.compile(r"total_amount:\s*String\(totals\.total\)"),
        re.compile(r"tax_rate:\s*String\(item\.tax_rate"),
        re.compile(r"unit_price:\s*String\(line\.unit_price"),
        re.compile(r"TODO\(backend-authority\)"),
    ]

    offenders = []
    for relative_path in files:
        source = _read(relative_path)
        for pattern in forbidden:
            if pattern.search(source):
                offenders.append(f"{relative_path}: {pattern.pattern}")

    assert offenders == []


def test_sales_contracts_and_delivery_resolve_authoritative_backend_fields():
    calculator = _read("backend/routers/calculator.py")
    contracts_router = _read("backend/routers/contracts.py")
    delivery_router = _read("backend/routers/delivery_orders.py")
    contract_form = _read("frontend/src/pages/Sales/ContractForm.jsx")
    delivery_form = _read("frontend/src/pages/Sales/DeliveryOrderForm.jsx")
    credit_notes_form = _read("frontend/src/pages/Sales/SalesCreditNotes.jsx")
    debit_notes_form = _read("frontend/src/pages/Sales/SalesDebitNotes.jsx")
    credit_notes_router = _read("backend/routers/sales/credit_notes.py")

    assert "resolve_line_tax_group" in calculator
    assert "resolve_line_tax_group" in contracts_router
    assert "item.tax_rate" not in contracts_router
    assert "total_amount: formData" not in contract_form
    assert "tax_rate: String(item.tax_rate" not in contract_form
    assert "backendLines" in contract_form

    assert "delivery_quantity_exceeds_remaining" in delivery_router
    assert "validate_branch_access(current_user, branch_id" in delivery_router
    assert "delivered_qty: String(line.delivered_qty" in delivery_form
    assert "unit_price: String(line.unit_price" not in delivery_form
    assert "tax_rate" not in delivery_form

    assert "resolve_line_tax_group" in credit_notes_router
    assert 'http_error(400, "branch_required"' in credit_notes_router
    assert "tax_rate:" not in credit_notes_form
    assert "updateLine(i, 'tax_rate'" not in credit_notes_form
    assert "tax_rate:" not in debit_notes_form
    assert "updateLine(i, 'tax_rate'" not in debit_notes_form
