# Contract: Service Order Margin

## Helper

`services/fsm/margin.py::compute_margin(service_order_id) -> MarginResult`

`MarginResult` fields: `revenue_total: Decimal`, `cost_total: Decimal`, `margin_amount: Decimal`, `margin_pct: Decimal`.

## Inputs

- `revenue_total`: sum of billable amounts per coverage resolver + pricelist resolver, in order currency.
- `cost_total`: sum of:
  - Parts: `qty * wac_per_warehouse(item_id, warehouse_id)` (from 023).
  - Labour: `hours * technician.hourly_cost` (from `technicians` or default).
  - Travel: actual travel expenses + per-diem.
  - Subcontract: actual paid amount.

## Side Effects

At service-order close:
- Sets `service_orders.revenue_total`, `cost_total`, `margin_amount`, `margin_pct`, `revenue_resolved_at=now()`.
- Margin is also surfaced in finance reports via GL posting from the corresponding service invoice (which is created by 023's Order→Invoice when applicable).

## Errors

| Code | When |
|------|------|
| 422 `margin.cost_unresolved` | Any cost component cannot be priced (e.g., missing WAC). |
| 422 `margin.revenue_unresolved` | Pricelist + default both missing. |
