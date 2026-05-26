"""Demand forecasting service.

Auto-selects forecasting method based on sales history depth:
  >=12 months → seasonal_decomposition
  >=3 months  → exponential_smoothing
  >=1 month   → moving_average

Uses Python statistics stdlib only (no numpy/pandas dependency).
"""

import logging
import math
import statistics
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_D4 = Decimal("0.0001")


def _dec(val) -> Decimal:
    if val is None:
        return _ZERO
    return Decimal(str(val)).quantize(_D4, rounding=ROUND_HALF_UP)


def _month_diff(d1: date, d2: date) -> int:
    """Return approximate month count between two dates."""
    return (d1.year - d2.year) * 12 + (d1.month - d2.month)


def _add_months(d: date, months: int) -> date:
    """Add *months* calendar months to *d*."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, 28)  # safe for all months
    return date(year, month, day)


# ── Forecasting algorithms ──────────────────────────────────────────


def _moving_average(monthly_qty: list[Decimal], horizon: int) -> list[dict]:
    """Simple moving average over all available history."""
    if not monthly_qty:
        return []
    avg = sum(monthly_qty) / len(monthly_qty)
    # Std-dev for confidence
    if len(monthly_qty) > 1:
        float(avg)
        std = Decimal(str(statistics.stdev([float(q) for q in monthly_qty])))
    else:
        std = avg * Decimal("0.2")  # fallback 20%

    results = []
    for i in range(horizon):
        results.append({
            "projected": _dec(avg),
            "lower": _dec(max(_ZERO, avg - std * 2)),
            "upper": _dec(avg + std * 2),
        })
    return results


def _exponential_smoothing(monthly_qty: list[Decimal], horizon: int, alpha: float = 0.3) -> list[dict]:
    """Single exponential smoothing (SES)."""
    if not monthly_qty:
        return []
    level = float(monthly_qty[0])
    residuals: list[float] = []
    for q in monthly_qty[1:]:
        fq = float(q)
        residuals.append(fq - level)
        level = alpha * fq + (1 - alpha) * level

    forecast_val = Decimal(str(level))
    if residuals:
        std = Decimal(str(statistics.stdev(residuals))) if len(residuals) > 1 else Decimal(str(abs(residuals[0])))
    else:
        std = forecast_val * Decimal("0.15")

    results = []
    for i in range(horizon):
        # Widen confidence over time
        width = std * Decimal(str(math.sqrt(i + 1))) * 2
        results.append({
            "projected": _dec(forecast_val),
            "lower": _dec(max(_ZERO, forecast_val - width)),
            "upper": _dec(forecast_val + width),
        })
    return results


def _seasonal_decomposition(monthly_qty: list[Decimal], horizon: int) -> list[dict]:
    """Simple additive seasonal decomposition (period=12)."""
    n = len(monthly_qty)
    period = 12

    # Compute trend via centered moving average
    vals = [float(q) for q in monthly_qty]
    trend: list[float | None] = [None] * n
    half = period // 2
    for i in range(half, n - half):
        trend[i] = statistics.mean(vals[i - half: i + half + 1])

    # Fill edges with nearest value
    first_trend = next((t for t in trend if t is not None), statistics.mean(vals))
    last_trend = next((t for t in reversed(trend) if t is not None), first_trend)
    for i in range(n):
        if trend[i] is None:
            trend[i] = first_trend if i < half else last_trend

    # Seasonal component
    seasonal = [0.0] * period
    counts = [0] * period
    for i in range(n):
        m = i % period
        seasonal[m] += vals[i] - trend[i]
        counts[m] += 1
    for m in range(period):
        if counts[m] > 0:
            seasonal[m] /= counts[m]

    # Residuals for confidence
    residuals = []
    for i in range(n):
        fitted = trend[i] + seasonal[i % period]
        residuals.append(vals[i] - fitted)
    std = statistics.stdev(residuals) if len(residuals) > 1 else abs(statistics.mean(residuals)) * 0.2

    # Project forward using last trend + seasonal pattern
    # Simple linear trend extrapolation
    trend_vals = [t for t in trend if t is not None]
    if len(trend_vals) >= 2:
        trend_slope = (trend_vals[-1] - trend_vals[0]) / max(len(trend_vals) - 1, 1)
    else:
        trend_slope = 0.0
    last_trend_val = trend_vals[-1] if trend_vals else statistics.mean(vals)

    results = []
    for i in range(horizon):
        proj = last_trend_val + trend_slope * (i + 1) + seasonal[(n + i) % period]
        width = std * math.sqrt(i + 1) * 2
        results.append({
            "projected": _dec(Decimal(str(max(0.0, proj)))),
            "lower": _dec(Decimal(str(max(0.0, proj - width)))),
            "upper": _dec(Decimal(str(max(0.0, proj + width)))),
        })
    return results


# ── Main entry points ────────────────────────────────────────────────


def generate_demand_forecast(
    db,
    *,
    product_id: int,
    warehouse_id: int | None,
    horizon_months: int,
    user_id: int,
) -> dict:
    """Generate a demand forecast for a product.

    Returns dict with ``forecast_id``, ``method``, ``period_count``.
    """
    today = date.today()

    # 1) Gather monthly sales history
    wh_filter = "AND il.warehouse_id = :wh" if warehouse_id else ""
    params: dict = {"pid": product_id}
    if warehouse_id:
        params["wh"] = warehouse_id

    history_sql = text(f"""
        SELECT
            date_trunc('month', i.invoice_date) AS month,
            COALESCE(SUM(il.quantity), 0) AS qty
        FROM invoices i
        JOIN invoice_lines il ON il.invoice_id = i.id
        WHERE i.invoice_type = 'sales'
          AND i.status NOT IN ('draft', 'cancelled')
          AND il.product_id = :pid
          {wh_filter}
        GROUP BY date_trunc('month', i.invoice_date)
        ORDER BY month
    """)
    rows = db.execute(history_sql, params).fetchall()

    if not rows:
        raise ValueError("No sales history found for this product")

    # Build monthly qty list (fill gaps with 0)
    first_month = rows[0].month.date() if hasattr(rows[0].month, 'date') else rows[0].month
    history_map: dict[str, Decimal] = {}
    for r in rows:
        m = r.month.date() if hasattr(r.month, 'date') else r.month
        history_map[m.strftime("%Y-%m")] = _dec(r.qty)

    months_count = _month_diff(today, first_month)
    if months_count < 1:
        months_count = 1

    monthly_qty: list[Decimal] = []
    for i in range(months_count):
        m = _add_months(first_month, i)
        key = m.strftime("%Y-%m")
        monthly_qty.append(history_map.get(key, _ZERO))

    # 2) Auto-select method
    if months_count >= 12:
        method = "seasonal_decomposition"
        projections = _seasonal_decomposition(monthly_qty, horizon_months)
    elif months_count >= 3:
        method = "exponential_smoothing"
        projections = _exponential_smoothing(monthly_qty, horizon_months)
    else:
        method = "moving_average"
        projections = _moving_average(monthly_qty, horizon_months)

    # 3) Create forecast header
    row = db.execute(
        text(
            "INSERT INTO demand_forecasts "
            "(product_id, warehouse_id, forecast_method, generated_date, generated_by, history_months_used) "
            "VALUES (:pid, :wid, :method, :gd, :uid, :hm) RETURNING id"
        ),
        {
            "pid": product_id,
            "wid": warehouse_id,
            "method": method,
            "gd": today,
            "uid": user_id,
            "hm": months_count,
        },
    ).fetchone()
    forecast_id = row[0]

    # 4) Insert periods
    for i, proj in enumerate(projections):
        p_start = _add_months(today, i)
        p_end = _add_months(today, i + 1) - timedelta(days=1)
        adjusted = proj["projected"]
        db.execute(
            text(
                "INSERT INTO demand_forecast_periods "
                "(forecast_id, period_start, period_end, projected_quantity, "
                "confidence_lower, confidence_upper, manual_adjustment, adjusted_quantity) "
                "VALUES (:fid, :ps, :pe, :pq, :cl, :cu, 0, :aq)"
            ),
            {
                "fid": forecast_id,
                "ps": p_start,
                "pe": p_end,
                "pq": proj["projected"],
                "cl": proj["lower"],
                "cu": proj["upper"],
                "aq": adjusted,
            },
        )

    db.commit()
    return {"forecast_id": forecast_id, "method": method, "period_count": len(projections)}


def manual_adjust(db, *, forecast_id: int, adjustments: list[dict]) -> dict:
    """Apply manual adjustments to forecast periods.

    Each adjustment dict: {period_id: int, manual_adjustment: Decimal}
    Returns dict with updated_count.
    """
    updated = 0
    for adj in adjustments:
        period_id = adj["period_id"]
        manual_adj = _dec(adj["manual_adjustment"])

        # Get current projected_quantity
        row = db.execute(
            text(
                "SELECT projected_quantity FROM demand_forecast_periods "
                "WHERE id = :pid AND forecast_id = :fid"
            ),
            {"pid": period_id, "fid": forecast_id},
        ).fetchone()
        if not row:
            continue

        projected = _dec(row[0])
        adjusted = projected + manual_adj

        db.execute(
            text(
                "UPDATE demand_forecast_periods "
                "SET manual_adjustment = :ma, adjusted_quantity = :aq, updated_at = NOW() "
                "WHERE id = :pid AND forecast_id = :fid"
            ),
            {"ma": manual_adj, "aq": adjusted, "pid": period_id, "fid": forecast_id},
        )
        updated += 1

    db.commit()
    return {"updated_count": updated}
