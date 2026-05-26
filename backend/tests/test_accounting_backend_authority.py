from decimal import Decimal
from pathlib import Path
import re

from routers.reports.accounting_statements import _money_str
from routers.reports.accounting_analysis import _decimal_str
from routers.reports.kpi import _pct_change, _ratio_str
from routers.finance.accounting.core import _dec as accounting_decimal
from schemas.budgets import BudgetItemCreate
from utils.currency_display import base_to_display_amount


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_decimal_helpers_return_plain_strings():
    assert _money_str(Decimal("0E+6")) == "0.00"
    assert _money_str(Decimal("123.4")) == "123.40"
    assert _decimal_str(Decimal("987.6")) == "987.60"
    assert _ratio_str(Decimal("12.345")) == "12.35"
    assert _pct_change(Decimal("125"), Decimal("100")) == "25.0"
    assert base_to_display_amount(
        Decimal("12.345"),
        {"currency": "SAR", "base_currency": "SAR", "rate": Decimal("1")},
    ) == "12.34"


def test_accounting_decimal_helper_accepts_blank_raw_inputs():
    assert accounting_decimal("") == Decimal("0")
    assert accounting_decimal("   ") == Decimal("0")


def test_budget_item_accepts_raw_monthly_amount_without_frontend_planned_total():
    item = BudgetItemCreate(account_id=7, monthly_amount="100.25", notes="ops")

    assert item.account_id == 7
    assert item.planned_amount is None
    assert item.monthly_amount == Decimal("100.25")


def test_accounting_report_pages_do_not_recompute_authoritative_totals():
    files = [
        "frontend/src/pages/Accounting/ChartOfAccounts.jsx",
        "frontend/src/pages/Accounting/FiscalYears.jsx",
        "frontend/src/pages/Accounting/GeneralLedger.jsx",
        "frontend/src/pages/Accounting/IncomeStatement.jsx",
        "frontend/src/pages/Accounting/BalanceSheet.jsx",
        "frontend/src/pages/Accounting/BudgetItems.jsx",
        "frontend/src/pages/Accounting/BudgetReport.jsx",
        "frontend/src/pages/Accounting/JournalEntryForm.jsx",
        "frontend/src/pages/Accounting/JournalEntryList.jsx",
        "frontend/src/pages/Accounting/OpeningBalances.jsx",
        "frontend/src/pages/Accounting/RecurringTemplates.jsx",
        "frontend/src/pages/Accounting/TrialBalance.jsx",
        "frontend/src/pages/Accounting/VATReport.jsx",
        "frontend/src/pages/Accounting/ZakatCalculator.jsx",
        "frontend/src/pages/Accounting/Budgets.jsx",
        "frontend/src/pages/Accounting/RevenueRecognition.jsx",
        "frontend/src/pages/Accounting/ClosingEntries.jsx",
        "frontend/src/pages/Accounting/TaxAudit.jsx",
        "frontend/src/pages/Accounting/PeriodComparison.jsx",
        "frontend/src/pages/Accounting/IntercompanyTransactions.jsx",
        "frontend/src/pages/Reports/CashFlowIAS7.jsx",
        "frontend/src/pages/Reports/DetailedProfitLoss.jsx",
        "frontend/src/pages/Reports/FXGainLossReport.jsx",
        "frontend/src/pages/Reports/IndustryReport.jsx",
        "frontend/src/pages/Reports/KPIDashboard.jsx",
        "frontend/src/pages/Reports/ConsolidationReports.jsx",
    ]
    forbidden = [
        re.compile(r"new Decimal"),
        re.compile(r"\.toNumber\("),
        re.compile(r"\.toFixed\("),
        re.compile(r"parseFloat"),
        re.compile(r"Math\.abs"),
        re.compile(r"Math\.round"),
        re.compile(r"Math\.min"),
        re.compile(r"\.reduce\("),
        re.compile(r"\bnet_income\s*(?:>=|<=|>|<)"),
        re.compile(r"\brow\.change\s*(?:>=|<=|>|<)"),
        re.compile(r"\brow\.change_pct\s*(?:>=|<=|>|<)"),
    ]
    allowed_number_contexts = {
        "frontend/src/pages/Accounting/ZakatCalculator.jsx": ["setFiscalYear(Number(e.target.value))"],
    }

    offenders = []
    for relative_path in files:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(source):
                offenders.append(f"{relative_path}: {pattern.pattern}")
        for match in re.finditer(r"\bNumber\(", source):
            line = source[:match.start()].count("\n") + 1
            line_text = source.splitlines()[line - 1].strip()
            allowed = any(fragment in line_text for fragment in allowed_number_contexts.get(relative_path, []))
            if not allowed:
                offenders.append(f"{relative_path}:{line}: Number(")

    assert offenders == []


def test_phase_c_comments_removed_from_accounting_authority_files():
    files = [
        "frontend/src/pages/Accounting/TrialBalance.jsx",
        "frontend/src/pages/Reports/DetailedProfitLoss.jsx",
        "frontend/src/pages/Reports/CashFlowIAS7.jsx",
        "frontend/src/pages/Reports/FXGainLossReport.jsx",
    ]

    offenders = [
        relative_path
        for relative_path in files
        if "Phase C" in (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_backend_exposes_authoritative_report_amount_fields():
    sources = {
        "backend/routers/reports/accounting_statements.py": [
            "closing_difference",
            "group_totals",
        ],
        "backend/routers/reports/accounting_analysis.py": [
            "total_revenue",
            "total_cogs",
            "overall_gross_margin_pct",
        ],
        "backend/routers/reports/accounting_compare_export.py": [
            "result_type",
            "change_direction",
            "change_pct_prefix",
        ],
        "backend/routers/finance/taxes/reports.py": [
            "net_vat_abs",
            "net_vat_status",
        ],
        "backend/routers/finance/accounting/fiscal.py": [
            "net_income_abs",
            "result_type",
        ],
    }

    missing = []
    for relative_path, expected_tokens in sources.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for token in expected_tokens:
            if token not in source:
                missing.append(f"{relative_path}: {token}")

    assert missing == []


def test_accounting_gl_mutations_carry_idempotency_keys():
    sources = {
        "backend/routers/finance/revenue_recognition.py": [
            'request.headers.get("Idempotency-Key")',
            "FOR UPDATE",
            "recognition_source_id",
            "deferred_revenue_account_not_found",
            "source_id=recognition_source_id",
            "idempotency_key=idempotency_key",
        ],
        "backend/routers/finance/accounting/fiscal.py": [
            'request.headers.get("Idempotency-Key")',
            'entry_idempotency_key("revenue")',
            'entry_idempotency_key("expense")',
            'entry_idempotency_key("transfer")',
        ],
        "frontend/src/services/accounting.js": [
            "generateClosingEntries: (data, idempotencyKey)",
            "recognizeRevenue: (id, periodIndex, idempotencyKey)",
            "'Idempotency-Key': idempotencyKey",
        ],
        "frontend/src/pages/Accounting/ClosingEntries.jsx": [
            "closingIdempotencyKey",
            "setClosingIdempotencyKey(crypto.randomUUID())",
        ],
        "frontend/src/pages/Accounting/RevenueRecognition.jsx": [
            "recognitionKeys",
            "recognizeRevenue(scheduleId, periodIndex, idempotencyKey)",
        ],
    }

    missing = []
    for relative_path, expected_tokens in sources.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for token in expected_tokens:
            if token not in source:
                missing.append(f"{relative_path}: {token}")

    assert missing == []
