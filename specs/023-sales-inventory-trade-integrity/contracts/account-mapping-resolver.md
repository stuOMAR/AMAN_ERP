# Contract: Account-Mapping Resolver

**Module**: `services/sales/account_mapping.py`
**Public function**: `resolve(*, mapping_kind, account_code=None, classification=None, company_id) -> account_id`.

## Purpose

Be the single source of truth for "which GL account should this posting hit?". Replaces three legacy shortcuts:

- direct calls to `get_acc_id(code)` (now banned by lint),
- the separate `acc_map_sales_rev` table (consolidated into `acc_map_sales` with `direction='reversal'`),
- ad-hoc class-based fallbacks scattered through services.

## Inputs

- `mapping_kind` ∈ `{ sales_revenue, sales_tax_payable, sales_discount, cogs, ar, sales_return_revenue, sales_return_tax, sales_return_cogs, pos_revenue, pos_tax_payable, pos_cash_clearing, mfg_wip, mfg_fg, mfg_scrap_loss, mfg_byproduct }` (extensible).
- Optional `account_code` — if provided, looks up `accounts` directly (still subject to existence + active checks).
- Optional `classification` — when the mapping table points to a class, ask 022's `account_classifier` to materialize an account.
- `company_id` — required for tenant scoping.

## Output

- `account_id: int`.
- Raises `MissingAccountMapping(mapping_kind)` when no mapping exists and policy is `block`.
- Raises `AccountClassificationAmbiguous(classification)` when 022's classifier returns multiple candidates without a configured tie-break.

## Behavior

1. Look up `acc_map_sales` (or matching table per kind) by `(mapping_kind, direction)`.
2. If the mapping points to an `account_id`, validate it is active and return.
3. If the mapping points to a `class`, delegate to `account_classifier.resolve_one(classification, company_id)`.
4. If none, consult the policy `manufacturing.missing_mapping_policy` / `sales.missing_mapping_policy`:
   - `block` → raise.
   - `warn` → raise a structured warning + return the configured tenant default account; if no default, raise.

## Lint enforcement

`scripts/check_get_acc_id_callsites.py` fails CI if any module other than this resolver imports `get_acc_id`.

## Audit

Resolutions in `warn` policy emit `audit_writer.log_activity('account_mapping.fallback', ...)` once per (kind, classification, day) using a Redis dedupe key.
