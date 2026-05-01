"""Cash-flow forecast generation service.

Generates forecast lines from open AR/AP invoices, deferred cheques,
scheduled payroll, and recurring journal entries, then computes a running
balance starting from the real opening bank balance.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_D4 = Decimal("0.0001")


def _dec(val) -> Decimal:
    if val is None:
        return _ZERO
    return Decimal(str(val))


def _get_lag_days(db, setting_key: str, default: int) -> int:
    """Read configurable lag days from company_settings with a fallback default."""
    try:
        row = db.execute(
            text(
                "SELECT setting_value FROM company_settings "
                "WHERE setting_key = :k LIMIT 1"
            ),
            {"k": setting_key},
        ).fetchone()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return default


def generate_cashflow_forecast(
    db,
    *,
    name: str,
    horizon_days: int,
    mode: str,
    user_id: int,
    scenario_weights: dict | None = None,
    bank_account_id: Optional[int] = None,
) -> dict:
    """Build a cashflow forecast and persist it.

    Returns dict with ``forecast_id`` and ``line_count``.

    Optional ``bank_account_id`` limits the opening balance and cheque sources
    to a specific treasury account; AR/AP/recurring are always included.

    TREAS-F3 (Phase-11 Sprint-5): optional ``scenario_weights`` produces a
    probability-weighted projected balance. Accepted keys: ``best``, ``likely``,
    ``worst``. Values must sum to ~1.0. When provided:
      * inflow × (best: 1.0, likely: weight, worst: 0.5)
      * outflow × (best: 0.7, likely: 1.0, worst: 1.2)
    to model collection delays and cost overruns.
    """
    today = date.today()
    end_date = today + timedelta(days=horizon_days)

    weights = None
    if scenario_weights:
        _w = {k: _dec(scenario_weights.get(k, 0)) for k in ("best", "likely", "worst")}
        s = _w["best"] + _w["likely"] + _w["worst"]
        if s <= 0:
            weights = None
        else:
            # Normalize
            weights = {k: (_w[k] / s) for k in _w}

    # ── Configurable collection / payment lag from company_settings ──────
    collection_lag = _get_lag_days(db, "forecast_collection_lag_days", 7)
    payment_lag = _get_lag_days(db, "forecast_payment_lag_days", 3)

    # 1) Create the forecast header
    row = db.execute(
        text(
            "INSERT INTO cashflow_forecasts (name, forecast_date, horizon_days, mode, generated_by) "
            "VALUES (:name, :fd, :hd, :mode, :uid) RETURNING id"
        ),
        {"name": name, "fd": today, "hd": horizon_days, "mode": mode, "uid": user_id},
    ).fetchone()
    forecast_id = row[0]

    # ── Opening balance: sum of active treasury/bank account balances ─────
    if bank_account_id:
        ob_row = db.execute(
            text(
                "SELECT COALESCE(current_balance, 0) FROM treasury_accounts "
                "WHERE id = :bid AND is_active = TRUE LIMIT 1"
            ),
            {"bid": bank_account_id},
        ).fetchone()
        opening_balance = _dec(ob_row[0]) if ob_row else _ZERO
    else:
        ob_row = db.execute(
            text(
                "SELECT COALESCE(SUM(current_balance), 0) FROM treasury_accounts "
                "WHERE is_active = TRUE"
            )
        ).fetchone()
        opening_balance = _dec(ob_row[0]) if ob_row else _ZERO

    # 2) Collect projected cash-flow items
    lines: list[dict] = []

    # --- AR (receivables): open sales invoices with due_date in horizon ---
    ar_sql = text(
        "SELECT id, due_date, (total - paid_amount) AS balance "
        "FROM invoices "
        "WHERE invoice_type = 'sales' AND status NOT IN ('paid','cancelled','draft') "
        "  AND due_date BETWEEN :start AND :end "
        "  AND (total - paid_amount) > 0"
    )
    for inv in db.execute(ar_sql, {"start": today, "end": end_date}):
        due = inv.due_date
        if mode == "expected":
            due = due + timedelta(days=collection_lag)
            if due > end_date:
                continue
        lines.append({
            "date": due,
            "bank_account_id": bank_account_id,
            "source_type": "ar",
            "source_document_id": inv.id,
            "inflow": _dec(inv.balance),
            "outflow": _ZERO,
        })

    # --- AP (payables): open purchase invoices with due_date in horizon ---
    ap_sql = text(
        "SELECT id, due_date, (total - paid_amount) AS balance "
        "FROM invoices "
        "WHERE invoice_type = 'purchase' AND status NOT IN ('paid','cancelled','draft') "
        "  AND due_date BETWEEN :start AND :end "
        "  AND (total - paid_amount) > 0"
    )
    for inv in db.execute(ap_sql, {"start": today, "end": end_date}):
        due = inv.due_date
        if mode == "expected":
            due = due + timedelta(days=payment_lag)
            if due > end_date:
                continue
        lines.append({
            "date": due,
            "bank_account_id": bank_account_id,
            "source_type": "ap",
            "source_document_id": inv.id,
            "inflow": _ZERO,
            "outflow": _dec(inv.balance),
        })

    # --- Checks receivable: deferred inflows ---
    cr_params: dict = {"start": today, "end": end_date}
    cr_filter = ""
    if bank_account_id:
        cr_filter = " AND treasury_account_id = :bid"
        cr_params["bid"] = bank_account_id
    cr_sql = text(
        "SELECT id, due_date, amount, treasury_account_id "
        "FROM checks_receivable "
        "WHERE status = 'pending' AND due_date BETWEEN :start AND :end"
        + cr_filter
    )
    for chk in db.execute(cr_sql, cr_params):
        lines.append({
            "date": chk.due_date,
            "bank_account_id": chk.treasury_account_id,
            "source_type": "check_in",
            "source_document_id": chk.id,
            "inflow": _dec(chk.amount),
            "outflow": _ZERO,
        })

    # --- Checks payable: deferred outflows ---
    cp_params: dict = {"start": today, "end": end_date}
    cp_filter = ""
    if bank_account_id:
        cp_filter = " AND treasury_account_id = :bid"
        cp_params["bid"] = bank_account_id
    cp_sql = text(
        "SELECT id, due_date, amount, treasury_account_id "
        "FROM checks_payable "
        "WHERE status IN ('issued', 'pending') AND due_date BETWEEN :start AND :end"
        + cp_filter
    )
    for chk in db.execute(cp_sql, cp_params):
        lines.append({
            "date": chk.due_date,
            "bank_account_id": chk.treasury_account_id,
            "source_type": "check_out",
            "source_document_id": chk.id,
            "inflow": _ZERO,
            "outflow": _dec(chk.amount),
        })

    # --- Payroll: approved entries grouped by payment_date ---
    payroll_sql = text(
        "SELECT pp.payment_date, SUM(pe.net_salary) AS total_salary "
        "FROM payroll_entries pe "
        "JOIN payroll_periods pp ON pe.period_id = pp.id "
        "WHERE pe.status = 'approved' "
        "  AND pp.payment_date BETWEEN :start AND :end "
        "  AND pp.payment_date IS NOT NULL "
        "GROUP BY pp.payment_date"
    )
    for pr in db.execute(payroll_sql, {"start": today, "end": end_date}):
        lines.append({
            "date": pr.payment_date,
            "bank_account_id": bank_account_id,
            "source_type": "payroll",
            "source_document_id": None,
            "inflow": _ZERO,
            "outflow": _dec(pr.total_salary),
        })

    # --- Recurring journal entries ---
    rec_sql = text(
        "SELECT id, next_run_date, total_amount "
        "FROM recurring_journal_templates "
        "WHERE is_active = true AND next_run_date BETWEEN :start AND :end"
    )
    for rec in db.execute(rec_sql, {"start": today, "end": end_date}):
        amt = _dec(rec.total_amount)
        lines.append({
            "date": rec.next_run_date,
            "bank_account_id": bank_account_id,
            "source_type": "recurring",
            "source_document_id": rec.id,
            "inflow": amt if amt > 0 else _ZERO,
            "outflow": abs(amt) if amt < 0 else _ZERO,
        })

    # 3) Sort by date and compute running balance starting from opening_balance
    lines.sort(key=lambda l: l["date"])
    running_balance = opening_balance
    for line in lines:
        if weights:
            # Probability-weighted scenario math (TREAS-F3)
            inf = line["inflow"]
            out = line["outflow"]
            weighted_inf = (
                inf * Decimal("1.0") * weights["best"]
                + inf * Decimal("1.0") * weights["likely"]
                + inf * Decimal("0.5") * weights["worst"]
            )
            weighted_out = (
                out * Decimal("0.7") * weights["best"]
                + out * Decimal("1.0") * weights["likely"]
                + out * Decimal("1.2") * weights["worst"]
            )
            running_balance += weighted_inf - weighted_out
        else:
            running_balance += line["inflow"] - line["outflow"]
        line["balance"] = running_balance

    # 4) Persist lines
    if lines:
        insert_sql = text(
            "INSERT INTO cashflow_forecast_lines "
            "(forecast_id, date, bank_account_id, source_type, source_document_id, "
            " projected_inflow, projected_outflow, projected_balance) "
            "VALUES (:fid, :dt, :ba, :st, :sd, :inf, :out, :bal)"
        )
        for line in lines:
            db.execute(insert_sql, {
                "fid": forecast_id,
                "dt": line["date"],
                "ba": line["bank_account_id"],
                "st": line["source_type"],
                "sd": line["source_document_id"],
                "inf": line["inflow"],
                "out": line["outflow"],
                "bal": line["balance"],
            })

    db.commit()
    logger.info(
        "Forecast %s created with %d lines (horizon=%d, mode=%s, opening_balance=%s)",
        forecast_id, len(lines), horizon_days, mode, opening_balance,
    )
    return {
        "forecast_id": forecast_id,
        "line_count": len(lines),
        "opening_balance": float(opening_balance),
    }
