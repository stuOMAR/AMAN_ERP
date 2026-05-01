"""T3.5 (audit #16) — FC balance sign for liabilities in revaluation.

Targets the pure helper `routers.finance.currencies.compute_fx_revaluation_diff`
which produces the JE side decision (gain/loss) given a foreign-currency
balance, a base-currency balance, the new rate, and the account type.

Both balances must be passed in the asset-positive convention
(``SUM(debit - credit)``). For a liability that means a natural credit
balance is a *negative* number — and the helper must still produce the
correct gain/loss direction.
"""
from routers.finance.currencies import compute_fx_revaluation_diff


# ----- Asset (debit-normal) ------------------------------------------------

def test_asset_rate_increase_books_gain():
    # FC cash: 100 FC, old rate 1.0 → bc 100. New rate 1.1.
    r = compute_fx_revaluation_diff(
        fc_balance=100.0, bc_balance=100.0, new_rate=1.1, account_type="asset",
    )
    assert r["side"] == "gain"
    assert round(r["diff"], 4) == 10.0


def test_asset_rate_decrease_books_loss():
    r = compute_fx_revaluation_diff(
        fc_balance=100.0, bc_balance=100.0, new_rate=0.9, account_type="asset",
    )
    assert r["side"] == "loss"
    assert round(r["diff"], 4) == -10.0


# ----- Liability (credit-normal) — the audit's core scenario ---------------

def test_liability_ap_rate_increase_books_loss():
    """AP owes 100 FC at rate 1.0 (bc -100). Rate rises to 1.1 (we owe more).
    Expected: side='loss' (we lost money), JE will Cr AP, Dr Loss.
    Regression for audit #16: old buggy code would have flagged this as a gain.
    """
    r = compute_fx_revaluation_diff(
        fc_balance=-100.0, bc_balance=-100.0, new_rate=1.1, account_type="liability",
    )
    assert r["side"] == "loss"
    # diff is in asset-positive convention: target=-110, bc=-100 → diff=-10
    assert round(r["diff"], 4) == -10.0
    # natural balance grew from 100 → 110 (we owe more BC)
    assert r["natural_old"] == 100.0
    assert r["natural_new"] == 110.0


def test_liability_rate_decrease_books_gain():
    r = compute_fx_revaluation_diff(
        fc_balance=-100.0, bc_balance=-100.0, new_rate=0.9, account_type="liability",
    )
    assert r["side"] == "gain"
    assert round(r["diff"], 4) == 10.0
    assert r["natural_old"] == 100.0
    assert r["natural_new"] == 90.0


# ----- Revenue (credit-normal) ---------------------------------------------

def test_revenue_credit_normal_treated_like_liability():
    r = compute_fx_revaluation_diff(
        fc_balance=-50.0, bc_balance=-50.0, new_rate=1.2, account_type="revenue",
    )
    assert r["side"] == "loss"  # owed credit grew in BC ⇒ unrealised loss
    assert round(r["diff"], 4) == -10.0


# ----- Edge cases ----------------------------------------------------------

def test_negligible_diff_returns_no_side():
    r = compute_fx_revaluation_diff(
        fc_balance=100.0, bc_balance=100.0001, new_rate=1.0, account_type="asset",
    )
    assert r["side"] is None


def test_unknown_account_type_defaults_to_asset_convention():
    r = compute_fx_revaluation_diff(
        fc_balance=100.0, bc_balance=100.0, new_rate=1.1, account_type="weird",
    )
    assert r["side"] == "gain"


def test_partially_settled_liability():
    """AP started at 100 FC credit @1.0, then 60 FC paid @1.05.
    journal_lines:  Cr 100 BC=100, Dr 60 BC=63 → fc=-40, bc=-37.
    New rate 1.10 → target_bc = -44 → diff = -7 (liability grew).
    """
    r = compute_fx_revaluation_diff(
        fc_balance=-40.0, bc_balance=-37.0, new_rate=1.10, account_type="liability",
    )
    assert r["side"] == "loss"
    assert round(r["diff"], 4) == -7.0
