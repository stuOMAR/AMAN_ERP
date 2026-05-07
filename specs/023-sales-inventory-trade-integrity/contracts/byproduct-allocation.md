# Contract: By-Product Allocator

**Module**: `services/manufacturing/byproduct_allocator.py`.

## Purpose

Decide what fraction of total production cost is allocated to each by-product, deterministically, with documented fallbacks.

## Public function

```
allocate(*, total_cost: Decimal, primary_qty: Decimal, byproducts: list[Byproduct], method: Literal['by_sales_value','by_quantity','fixed']) -> dict[item_id, Decimal]
```

## Methods

- `by_sales_value` — share each by-product its `sales_value / Σ sales_value`. Sales value comes from item.standard_price × qty, fallback to last invoice price within 30 days.
  - If any by-product is missing a sales value: fall back to `by_quantity` and emit `mfg.byproduct.fallback_to_qty` warning.
- `by_quantity` — `qty_i / Σ qty`.
- `fixed` — each by-product carries an explicit per-unit cost defined on `items.byproduct_cost`. Total allocated = `Σ qty × fixed_cost`. Remainder stays on primary.

## Outputs

Map `{ item_id: allocated_cost }`. Sum of values + primary residual = `total_cost` (within `gl.je_epsilon`).

## Errors

- `ByproductCostExceedsTotal` when `fixed` method's allocated > total_cost.

## Audit

Method choice and any fallback are logged once per MO completion.
