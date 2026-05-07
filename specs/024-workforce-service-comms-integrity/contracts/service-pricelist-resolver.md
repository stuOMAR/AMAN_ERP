# Contract: Service Pricelist Resolver

## Helper

`services/fsm/pricelists.py::resolve_price(item_id, customer_id, contract_id, as_of=today) -> PriceResolution`

`PriceResolution` fields: `unit_price: Decimal`, `currency: str`, `level: 'contract'|'customer'|'tenant'|'default'`, `pricelist_row_id: int|None`.

## Behavior

Resolution precedence (most-specific wins):

1. `service_pricelists` row with `scope='contract'` and `scope_ref_id=contract_id` and `(item_id, as_of in [valid_from, valid_to])`.
2. `service_pricelists` row with `scope='customer'` and `scope_ref_id=customer_id`.
3. `service_pricelists` row with `scope='tenant'` and `scope_ref_id IS NULL`.
4. `items.default_unit_price` (level=`default`).

Active rows only (`active=true`, `valid_from<=as_of<=COALESCE(valid_to,'infinity')`).

## Side Effects

When called from service-order create, the resolver writes:
- `service_orders.pricelist_source_level = level`.
- `service_orders.unit_price` for each line.

## Errors

| Code | When |
|------|------|
| 422 `pricelist.no_price` | Default also missing. |
| 422 `pricelist.currency_mismatch` | Resolved currency != order currency and no FX rate available. |
