# Contract: Bank Codes Registry

## Helper

`services/wps/bank_codes.py::lookup(swift_bic) -> BankCode`
`services/wps/bank_codes.py::lookup_by_code(code) -> BankCode`

## Behavior

- Reads `bank_codes` table (per-tenant; seeded at bootstrap).
- WPS file builder MUST use this helper instead of any inline dict.
- Lookup misses raise `wps.unknown_bank_code` (HTTP 422).

## Admin

`GET/POST/PATCH /api/admin/bank-codes` (gated by `bank_codes.admin` permission).

## Seed Source

`backend/db_ddl/seed_bank_codes.json` — committed list aligned with regulator's published WPS routing codes. Updated via PR; new tenant bootstrap reads this file.

## CI Lint

`scripts/check_hardcoded_bank_codes.py` — flag any hardcoded SWIFT/BIC dict in WPS modules.
