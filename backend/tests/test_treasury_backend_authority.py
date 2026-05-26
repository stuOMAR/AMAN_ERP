from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_treasury_backend_exposes_authoritative_calculated_fields():
    reconciliation = _read("backend/routers/finance/reconciliation.py")
    treasury = _read("backend/routers/finance/treasury.py")

    for token in [
        "difference_abs",
        "tolerance_amount",
        "is_balanced",
        "difference_status",
        "progress_pct",
        "is_fully_matched",
        "progress_status",
    ]:
        assert token in reconciliation

    for token in [
        "opening-balance-preview",
        "opening_balance_base",
        "net_flow_direction",
        "net_direction",
        "current_balance_direction",
        "balance_in_base_direction",
    ]:
        assert token in treasury


def test_treasury_frontend_no_longer_runs_authoritative_calculations():
    files = [
        "frontend/src/pages/Treasury/TreasuryHome.jsx",
        "frontend/src/pages/Treasury/ReconciliationList.jsx",
        "frontend/src/pages/Treasury/ReconciliationForm.jsx",
        "frontend/src/pages/Treasury/TreasuryCashflowReport.jsx",
        "frontend/src/pages/Treasury/TreasuryAccountList.jsx",
        "frontend/src/pages/Treasury/TreasuryBalancesReport.jsx",
        "frontend/src/pages/Treasury/ExpenseForm.jsx",
        "frontend/src/pages/Treasury/TransferForm.jsx",
        "frontend/src/pages/finance/ReconciliationFinalizeDialog.jsx",
        "frontend/src/services/treasury.js",
        "frontend/src/services/checks.js",
    ]
    forbidden = [
        re.compile(r"\bnew Decimal\b"),
        re.compile(r"\.reduce\("),
        re.compile(r"\.mul\("),
        re.compile(r"Math\.abs"),
        re.compile(r"Math\.round"),
        re.compile(r"\binflow\s*-\s*outflow\b"),
        re.compile(r"\bnet_flow\s*>=\s*0\b"),
        re.compile(r"\bacc\.net\s*>=\s*0\b"),
        re.compile(r"parseFloat"),
        re.compile(r"\.toFixed\("),
        re.compile(r"\.toNumber\("),
        re.compile(r"current_balance\s*[<>]=?\s*0"),
    ]

    offenders = []
    for relative_path in files:
        source = _read(relative_path)
        for pattern in forbidden:
            if pattern.search(source):
                offenders.append(f"{relative_path}: {pattern.pattern}")

    assert offenders == []


def test_treasury_frontend_consumes_backend_authority_fields():
    home = _read("frontend/src/pages/Treasury/TreasuryHome.jsx")
    rec_list = _read("frontend/src/pages/Treasury/ReconciliationList.jsx")
    rec_form = _read("frontend/src/pages/Treasury/ReconciliationForm.jsx")
    cashflow = _read("frontend/src/pages/Treasury/TreasuryCashflowReport.jsx")
    account_list = _read("frontend/src/pages/Treasury/TreasuryAccountList.jsx")
    balances = _read("frontend/src/pages/Treasury/TreasuryBalancesReport.jsx")
    service = _read("frontend/src/services/treasury.js")

    assert "treasuryAPI.getBalancesReport" in home
    assert "summary.total_all" in home
    assert "row.progress_pct" in rec_list
    assert "row.progress_status" in rec_list
    assert "is_balanced" in rec_form
    assert "difference_status" in rec_form
    assert "data.net_flow_direction" in cashflow
    assert "acc.net_direction" in cashflow
    assert "d.net_direction" in cashflow
    assert "current_balance_direction" in balances
    assert "previewOpeningBalance" in service
    assert "openingBalancePreview?.opening_balance_base" in account_list
    assert "api.post('/treasury/accounts', data, idempotencyHeaders())" in service


def test_treasury_fx_rates_are_backend_resolved():
    treasury_router = _read("backend/routers/finance/treasury.py")
    treasury_schema = _read("backend/schemas/treasury.py")
    account_list = _read("frontend/src/pages/Treasury/TreasuryAccountList.jsx")
    expense_form = _read("frontend/src/pages/Treasury/ExpenseForm.jsx")
    transfer_form = _read("frontend/src/pages/Treasury/TransferForm.jsx")

    assert "_resolve_exchange_rate" in treasury_router
    assert "account.exchange_rate" not in treasury_router
    assert "data.exchange_rate" not in treasury_router
    assert 'exchange_rate=Decimal("1")' in treasury_router
    assert "exchange_rate:" not in account_list
    assert "form.exchange_rate" not in expense_form
    assert "form.exchange_rate" not in transfer_form
    assert "exchange_rate" not in treasury_schema


def test_treasury_phase_c_temporary_comments_removed():
    files = [
        "frontend/src/pages/Treasury/TreasuryHome.jsx",
        "frontend/src/pages/Treasury/ReconciliationList.jsx",
        "frontend/src/pages/Treasury/ReconciliationForm.jsx",
        "frontend/src/pages/Treasury/TreasuryCashflowReport.jsx",
        "frontend/src/pages/Treasury/TreasuryAccountList.jsx",
    ]

    offenders = [
        relative_path
        for relative_path in files
        if "backend-authority phase C" in _read(relative_path)
    ]

    assert offenders == []
