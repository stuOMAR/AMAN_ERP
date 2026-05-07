from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from utils.accounting import get_base_currency


_CURRENCY_UNITS = {
    "SAR", "AED", "EGP", "USD", "EUR", "GBP", "KWD", "QAR", "BHD", "OMR", "JOD",
    "currency",
}

_MONETARY_CHART_IDS = {
    "revenue_vs_expenses",
    "sales_trend",
    "ar_aging",
    "ap_aging",
    "top_customers",
    "top_suppliers",
    "top_products_today",
    "pipeline_stages",
}

_MONEY_FIELD_NAMES = {
    "amount", "value", "total", "total_amount", "tax_amount", "taxable", "vat",
    "output_vat", "input_vat", "net_vat", "sales", "revenue", "expenses", "expense",
    "cost", "profit", "balance", "cash", "budget", "spent", "paid_amount",
    "pending_amount", "total_tax", "debit", "credit",
}


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _branch_ids_from_scope(branch_scope: Any) -> tuple[int | None, list[int] | None]:
    if isinstance(branch_scope, Mapping):
        branch_id = branch_scope.get("branch_id")
        branch_ids = branch_scope.get("branch_ids")
        return (int(branch_id) if branch_id is not None else None, list(branch_ids) if branch_ids is not None else None)
    if isinstance(branch_scope, Sequence) and not isinstance(branch_scope, (str, bytes, bytearray)):
        return None, [int(branch_id) for branch_id in branch_scope]
    if branch_scope is not None:
        return int(branch_scope), None
    return None, None


def resolve_display_currency(db, branch_scope: Any = None) -> dict[str, Any]:
    """Resolve display currency for a branch scope.

    Monetary aggregations are first computed in company base currency. A single
    branch, or a multi-branch scope whose branches share one currency, displays
    in that branch currency. Mixed-currency scopes display in base currency.
    """
    base_currency = (get_base_currency(db) or "SAR").upper()
    branch_id, branch_ids = _branch_ids_from_scope(branch_scope)

    currencies: list[str] = []
    if branch_id:
        row = db.execute(
            text("SELECT COALESCE(default_currency, :base) AS currency FROM branches WHERE id = :id"),
            {"id": branch_id, "base": base_currency},
        ).fetchone()
        if row and row.currency:
            currencies = [str(row.currency).upper()]
    elif branch_ids is not None:
        if branch_ids:
            rows = db.execute(
                text("SELECT DISTINCT COALESCE(default_currency, :base) AS currency FROM branches WHERE id = ANY(:ids)"),
                {"ids": branch_ids, "base": base_currency},
            ).fetchall()
            currencies = [str(row.currency).upper() for row in rows if row.currency]
    else:
        rows = db.execute(
            text("SELECT DISTINCT COALESCE(default_currency, :base) AS currency FROM branches WHERE is_active = TRUE"),
            {"base": base_currency},
        ).fetchall()
        currencies = [str(row.currency).upper() for row in rows if row.currency]

    unique = sorted(set(currencies))
    display_currency = unique[0] if len(unique) == 1 else base_currency
    if len(unique) > 1:
        default_filter = ""
        params = {"base": base_currency}
        if branch_ids is not None:
            if branch_ids:
                default_filter = "AND id = ANY(:ids)"
                params["ids"] = branch_ids
            else:
                default_filter = "AND 1=0"
        row = db.execute(
            text(f"""
                SELECT COALESCE(default_currency, :base) AS currency
                FROM branches
                WHERE is_active = TRUE {default_filter}
                ORDER BY is_default DESC, id ASC
                LIMIT 1
            """),
            params,
        ).fetchone()
        if row and row.currency:
            display_currency = str(row.currency).upper()

    rate = Decimal("1")
    if display_currency != base_currency:
        rate_row = db.execute(
            text("SELECT NULLIF(current_rate, 0) AS rate FROM currencies WHERE UPPER(code) = UPPER(:code) LIMIT 1"),
            {"code": display_currency},
        ).fetchone()
        rate = _dec(rate_row.rate if rate_row and rate_row.rate else 1)
        if rate <= 0:
            rate = Decimal("1")

    return {
        "currency": display_currency,
        "base_currency": base_currency,
        "rate": rate,
        "is_multi_currency_scope": len(unique) > 1,
    }


def base_to_display_amount(value: Any, display_meta: Mapping[str, Any]) -> float:
    amount = _dec(value)
    rate = display_meta.get("rate") or Decimal("1")
    if display_meta.get("currency") != display_meta.get("base_currency") and rate:
        amount = amount / _dec(rate)
    return float(amount)


def display_currency_fields(display_meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "display_currency": display_meta.get("currency"),
        "base_currency": display_meta.get("base_currency"),
        "is_multi_currency_scope": bool(display_meta.get("is_multi_currency_scope")),
    }


def currency_rate_sql(currency_sql: str) -> str:
    return (
        "COALESCE(NULLIF((SELECT c.current_rate FROM currencies c "
        f"WHERE UPPER(c.code) = UPPER({currency_sql}) LIMIT 1), 0), 1)"
    )


def document_amount_base_sql(amount_sql: str, table_alias: str = "i") -> str:
    """SQL expression converting document-currency amounts into base currency.

    Requires a ``:base_currency`` bind param and a table alias with ``currency``,
    ``exchange_rate`` and ``branch_id`` columns.
    """
    currency_sql = (
        f"COALESCE({table_alias}.currency, "
        f"(SELECT b.default_currency FROM branches b WHERE b.id = {table_alias}.branch_id), "
        ":base_currency)"
    )
    rate_sql = (
        f"CASE WHEN UPPER({currency_sql}) = UPPER(:base_currency) THEN 1 ELSE "
        f"COALESCE(NULLIF(NULLIF({table_alias}.exchange_rate, 0), 1), "
        f"{currency_rate_sql(currency_sql)}, NULLIF({table_alias}.exchange_rate, 0), 1) END"
    )
    return f"(({amount_sql}) * ({rate_sql}))"


def currency_amount_base_sql(amount_sql: str, currency_sql: str) -> str:
    """SQL expression converting a currency-coded amount into base currency.

    Use for tables with an amount and currency code but no exchange rate column.
    Requires a ``:base_currency`` bind param.
    """
    resolved_currency_sql = f"COALESCE({currency_sql}, :base_currency)"
    rate_sql = (
        f"CASE WHEN UPPER({resolved_currency_sql}) = UPPER(:base_currency) THEN 1 "
        f"ELSE {currency_rate_sql(resolved_currency_sql)} END"
    )
    return f"(({amount_sql}) * ({rate_sql}))"


def branch_amount_base_sql(amount_sql: str, branch_id_sql: str) -> str:
    """SQL expression converting branch-local money into base currency.

    Use for legacy tables that have ``branch_id`` but no currency/exchange_rate.
    Requires a ``:base_currency`` bind param.
    """
    currency_sql = f"COALESCE((SELECT b.default_currency FROM branches b WHERE b.id = {branch_id_sql}), :base_currency)"
    rate_sql = (
        f"CASE WHEN UPPER({currency_sql}) = UPPER(:base_currency) THEN 1 "
        f"ELSE {currency_rate_sql(currency_sql)} END"
    )
    return f"(({amount_sql}) * ({rate_sql}))"


def _is_currency_unit(unit: Any) -> bool:
    if unit is None:
        return False
    unit_text = str(unit).strip()
    return unit_text in _CURRENCY_UNITS or unit_text.upper() in _CURRENCY_UNITS


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _convert_money_fields(value: Any, display_meta: Mapping[str, Any]) -> Any:
    if isinstance(value, list):
        return [_convert_money_fields(item, display_meta) for item in value]
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            if key in _MONEY_FIELD_NAMES and _is_number(item):
                converted[key] = base_to_display_amount(item, display_meta)
            else:
                converted[key] = _convert_money_fields(item, display_meta)
        return converted
    return value


def convert_dashboard_payload_to_display(payload: Mapping[str, Any], display_meta: Mapping[str, Any]) -> dict[str, Any]:
    """Convert currency KPI values/charts from base currency to display currency."""
    result = deepcopy(dict(payload))

    for key in ("kpis", "role_kpis", "industry_kpis"):
        for item in result.get(key, []) or []:
            if _is_currency_unit(item.get("unit")) and _is_number(item.get("value")):
                item["value"] = round(base_to_display_amount(item.get("value"), display_meta), 2)
                item["unit"] = "currency"
                item.pop("formatted", None)
                if _is_number(item.get("target")):
                    item["target"] = round(base_to_display_amount(item.get("target"), display_meta), 2)

    for key in ("charts", "role_charts", "industry_charts"):
        for chart in result.get(key, []) or []:
            chart["currency"] = display_meta.get("currency")
            if chart.get("id") in _MONETARY_CHART_IDS:
                chart["data"] = _convert_money_fields(chart.get("data"), display_meta)

    result.update(display_currency_fields(display_meta))
    return result