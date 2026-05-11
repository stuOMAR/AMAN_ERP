# خطة إصلاح وحدة الضرائب — Tax Module Fix Plan

## Scope
backend/routers/finance/taxes/*, backend/routers/finance/tax_compliance.py, backend/routers/external.py, backend/routers/system_completion/accounting.py, backend/services/tax_engine.py, backend/routers/sales/*, backend/routers/purchases/*, frontend/src/pages/Taxes/*, frontend/src/pages/Accounting/ZakatCalculator.jsx, frontend/src/services/external.js, frontend/src/hooks/useInvoiceCalc.js.

**DO NOT** modify unrelated files. **DO NOT** revert existing changes. Use `Decimal` everywhere — never `float` in tax/financial arithmetic or API responses.

---

## Phase 1: Fix VAT Reports/Returns to Use Actual Invoice Tax (Critical)

### Problem
`returns_.py:187`, `reports.py:58`, `tax_compliance.py:767` all recalculate tax as `il.quantity * il.unit_price * (il.tax_rate / 100)`. This ignores header-level discounts applied in `accounting.py:257` (`compute_invoice_totals`). Result: tax return ≠ actual invoice tax_amount.

### Files to modify
- `backend/routers/finance/taxes/returns_.py`
- `backend/routers/finance/taxes/reports.py`
- `backend/routers/finance/tax_compliance.py`
- **NEW:** `backend/utils/tax_reporting.py`

### Changes

#### 1a. Create `backend/utils/tax_reporting.py`
```python
"""Centralized VAT aggregation helper for reports and returns."""
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any

_D2 = Decimal("0.01")

def invoice_vat_totals_subquery(
    invoice_type_param: str,
    branch_filter: str,
    *,
    date_column: str = "i.invoice_date",
) -> str:
    """Return a subquery that aggregates at invoice level.

    Do not use SUM(DISTINCT i.tax_amount): if two invoices have the same tax
    amount, DISTINCT will understate VAT. The invoice row is the authoritative
    source after header discount and exchange-rate locking.
    """
    return f"""
        SELECT
            COALESCE(SUM(inv.taxable_amount), 0) AS taxable,
            COALESCE(SUM(inv.vat_amount), 0) AS vat
        FROM (
            SELECT
                i.id,
                ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
            FROM invoices i
            WHERE i.invoice_type = :{invoice_type_param}
              AND i.status NOT IN ('draft', 'cancelled')
              AND {date_column} >= :start
              AND {date_column} < :end
              {branch_filter}
        ) inv
    """

def adjusted_line_taxable_cte(extra_where: str) -> str:
    """Use only for boxed/rate/classification reports that must split VAT by line.

    Important: invoices.discount may include line discounts plus header discount.
    Therefore compute header-only discount as:
    GREATEST(i.discount - SUM(line_discount), 0)

    The query exposes adjusted_taxable_base. VAT for a line is then:
    adjusted_taxable_base * (tax_rate / 100)
    """
    return f"""
        WITH line_base AS (
            SELECT
                i.id AS invoice_id,
                i.invoice_type,
                i.invoice_date,
                i.branch_id,
                COALESCE(i.exchange_rate, 1) AS exchange_rate,
                COALESCE(i.discount, 0) AS invoice_discount,
                il.tax_rate,
                (COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0)) AS gross_line_base,
                COALESCE(il.discount, 0) AS line_discount,
                (COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0) - COALESCE(il.discount, 0)) AS line_taxable_before_header,
                SUM(COALESCE(il.discount, 0)) OVER (PARTITION BY i.id) AS line_discount_sum,
                SUM(COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0) - COALESCE(il.discount, 0)) OVER (PARTITION BY i.id) AS invoice_line_taxable_sum
            FROM invoices i
            JOIN invoice_lines il ON il.invoice_id = i.id
            WHERE i.status NOT IN ('draft', 'cancelled')
              {extra_where}
        ),
        adjusted_lines AS (
            SELECT *,
                GREATEST(invoice_discount - line_discount_sum, 0) AS header_discount_only,
                (
                    line_taxable_before_header
                    - CASE
                        WHEN invoice_line_taxable_sum > 0
                        THEN GREATEST(invoice_discount - line_discount_sum, 0)
                             * line_taxable_before_header / invoice_line_taxable_sum
                        ELSE 0
                      END
                ) * exchange_rate AS adjusted_taxable_base
            FROM line_base
        )
    """
```

#### 1b. Modify `returns_.py` lines 187-204
Replace the SQL aggregation for output/input VAT to use invoice-level subqueries instead of joining invoice lines:
```sql
-- OLD:
COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat

-- NEW:
SELECT COALESCE(SUM(inv.vat_amount), 0)
FROM (
  SELECT i.id, COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1) AS vat_amount
  FROM invoices i
  WHERE ...
) inv
```
Same for taxable base: aggregate `(i.subtotal - COALESCE(i.discount, 0)) * i.exchange_rate` at invoice level inside the subquery.

Do not use `SUM(DISTINCT ...)` anywhere in VAT aggregation.

Apply the same change to: output (line 188), output_returns (line 199), input (line 210), input_returns (line 221).
Use separate bind parameter names for invoice type if multiple subqueries are executed in one request, e.g. `output_type = "sales"` and `input_type = "purchase"`.

#### 1c. Modify `reports.py` lines 58-95
Replace `taxable_base_sql` and `vat_base_sql` with invoice-level subqueries. Avoid joining `invoice_lines` for the high-level VAT report unless a detail drilldown is explicitly needed.

#### 1d. Modify `tax_compliance.py` lines 767+ (SA-VAT report)
For country box reports:
- For total output/input VAT, use invoice-level totals.
- For rate/classification boxes, use `adjusted_line_taxable_cte(...)` so the header-only invoice discount is allocated across lines without double-counting line discounts.
- Do not use raw `il.quantity * il.unit_price * il.tax_rate` without discount allocation.

#### 1e. Add test
In `backend/tests/test_64_tax_module_integrations.py`:
- Invoice: 1000 SAR, 15% VAT, 10% header discount → tax must be 135 (not 150).

---

## Phase 2: Fix Zakat All Branches Scope Collision (Critical)

### Problem
`accounting.py:50,508,586`: When user selects "All Branches", `branch_id = NULL`. Unique index is `(fiscal_year, COALESCE(branch_id, 0))`. Two users with different branch scopes writing "All Branches" collide on the same row.

### Files to modify
- `backend/routers/system_completion/accounting.py`
- `backend/models/domain_models/finance_fiscal_zakat.py`
- `backend/db_ddl/tenant_schema.py`
- **NEW:** `backend/alembic/versions/025l_zakat_branch_scope.py`

### Changes

#### 2a. Create Alembic migration `backend/alembic/versions/025l_zakat_branch_scope.py`
Use `down_revision = "025k_tax_compliance_hardening"`.

Upgrade SQL:
```sql
ALTER TABLE zakat_calculations
    ADD COLUMN IF NOT EXISTS branch_scope_key VARCHAR(160),
    ADD COLUMN IF NOT EXISTS branch_ids JSONB;

-- Backfill existing rows
UPDATE zakat_calculations
SET branch_scope_key = CASE
    WHEN branch_id IS NOT NULL THEN 'branch:' || branch_id
    ELSE 'all:company'
END
WHERE branch_scope_key IS NULL;

ALTER TABLE zakat_calculations
    ALTER COLUMN branch_scope_key SET NOT NULL;

-- Drop the old scope index from 025k before creating the replacement.
DROP INDEX IF EXISTS uq_zakat_calculations_year_branch;

-- New unique index
CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_year_scope
    ON zakat_calculations (fiscal_year, branch_scope_key);
```

#### 2b. Update `accounting.py` calculate_zakat (around line 50-66)
```python
def zakat_branch_scope_key(branch_scope: dict) -> tuple[str, list[int] | None]:
    if branch_scope.get("branch_id") is not None:
        return f"branch:{branch_scope['branch_id']}", None

    branch_ids = branch_scope.get("branch_ids")
    if branch_ids is None:
        return "all:company", None

    sorted_ids = sorted(int(b) for b in branch_ids)
    if not sorted_ids:
        return "branches:none", []
    return "branches:" + ",".join(str(b) for b in sorted_ids), sorted_ids

scope_key, scoped_branch_ids = zakat_branch_scope_key(branch_scope)
if selected_branch_id:
    scope_key = f"branch:{selected_branch_id}"
```

#### 2c. Update save logic (line 508)
Change lookup from `COALESCE(branch_id, 0) = COALESCE(:branch_id, 0)` to `branch_scope_key = :scope_key`.

#### 2d. Update GL posting (line 586)
Store `branch_ids` array in `calculation_details` for aggregated scope. Single-branch keeps `branch_id`.
The post endpoint must compute the same `scope_key` from `resolve_branch_scope(current_user, branch_id)` and select the calculation with:
```sql
WHERE fiscal_year = :fy AND branch_scope_key = :scope_key
FOR UPDATE
```

#### 2e. Update model
Add `branch_scope_key` and `branch_ids` to `finance_fiscal_zakat.py`.
Also update `backend/db_ddl/tenant_schema.py` so tenant bootstrap matches the Alembic schema.

#### 2f. Add test
User A scope [1,2] and User B scope [3] must not overwrite each other for same fiscal year.

---

## Phase 3: Fix ZATCA Manual Integration (Critical)

### Problem
`external.py:272`: `invoice_id` is a query parameter (`def generate_qr_code(invoice_id: int, ...)`), but `external.js:16` sends it as JSON body (`api.post('/external/zatca/generate-qr', { invoice_id: invoiceId })`). FastAPI returns 422.

### Files to modify
- `backend/routers/external.py`
- `frontend/src/services/external.js`

### Changes

#### 3a. Modify `external.py` line 272
```python
class ZatcaRequest(BaseModel):
    invoice_id: int

@router.post("/zatca/generate-qr", ...)
def generate_qr_code(body: ZatcaRequest, current_user=Depends(get_current_user)):
    invoice_id = body.invoice_id
    # ... rest unchanged
```

#### 3b. Add branch validation after fetching invoice (line 287)
```python
inv = db.execute(text("""
    SELECT i.id, i.invoice_number, i.invoice_date, i.total, i.tax_amount,
           i.branch_id, p.name as customer_name
    FROM invoices i
    LEFT JOIN parties p ON i.party_id = p.id
    WHERE i.id = :id
"""), {"id": invoice_id}).fetchone()
if not inv:
    raise HTTPException(**http_error(404, "invoice_not_found"))
if inv.branch_id:
    validate_branch_access(current_user, inv.branch_id)
```

#### 3c. Same for `/zatca/verify/{invoice_id}` (line 363)
Fetch `branch_id` with `zatca_hash`, then call `validate_branch_access(current_user, inv.branch_id)`.

#### 3d. Verify frontend `external.js` line 16
The existing `api.post('/external/zatca/generate-qr', { invoice_id: invoiceId })` will now work with the body-based endpoint.

#### 3e. Ensure Decimal formatting
When passing totals to `process_invoice_for_zatca` or clearance helpers, use Decimal values or `money_str(...)`, not `float(...)`.

#### 3f. Add tests
- Body JSON works (no 422).
- User without access to invoice's branch gets 403.
- QR/hash amounts serialize as Decimal money strings.

---

## Phase 4: Fix WHT Branch & Rate Validation (High)

### Problem
- `external.py:479`: `validate_branch_access` only runs `if data.branch_id` — allows NULL branch_id.
- `external.py:496`: Rate lookup doesn't check `is_active` or country match.

### Files to modify
- `backend/routers/external.py`
- `frontend/src/pages/Taxes/WithholdingTax.jsx`

### Changes

#### 4a. Modify `external.py` line 479
```python
# OLD:
branch_id = validate_branch_access(current_user, data.branch_id) if data.branch_id else None

# NEW:
branch_id = validate_branch_access(current_user, data.branch_id)
if branch_id is None:
    raise HTTPException(status_code=400, detail="يجب تحديد الفرع")
```
Apply the same rule to `/external/wht/calculate`; WHT calculation and creation are operational, not company-wide master data.

#### 4b. Modify rate lookup (line 496)
```python
rate_row = db.execute(text("""
    SELECT rate, name, country_code FROM wht_rates WHERE id = :id AND is_active = TRUE
"""), {"id": data.wht_rate_id}).fetchone()
if not rate_row:
    raise HTTPException(**http_error(404, "wht_rate_not_found_or_inactive"))

# Validate country match
if rate_row.country_code:
    branch = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
    branch_cc = (branch.country_code or "SA").upper() if branch else "SA"
    if rate_row.country_code.upper() != branch_cc:
        raise HTTPException(status_code=400, detail="معدل ال withholding لا يتطابق مع دولة الفرع")
```

#### 4c. Validate supplier/invoice/payment ownership
Before insert:
- `supplier_id` must exist.
- If `invoice_id` is supplied, it must belong to the same supplier and branch.
- If `payment_id` is supplied, it must belong to the same supplier and branch if those columns exist.

#### 4d. Frontend `WithholdingTax.jsx` line 123
Disable "Calculate" button when `currentBranch` is null/All Branches. Show message: "يرجى تحديد الفرع أولاً".

#### 4e. Add tests
- Missing branch → 400
- Inactive rate → 404
- Wrong country rate → 400
- Supplier/invoice branch mismatch → 400 or 403

---

## Phase 5: Harden Tax Engine Date/Country Validation (High)

### Problem
`tax_engine.py:490`: Product's `tax_rate_id` is used without checking `effective_from/to` or `country_code`. A product can point to an expired or foreign rate.

### File to modify
- `backend/services/tax_engine.py`

### Changes

#### 5a. Modify Priority 4 (line 490)
```python
# OLD:
if product and product.tax_rate_id and product.tax_is_active:
    return {...}

# NEW:
if product and product.tax_rate_id and product.tax_is_active:
    rate_row = db.execute(text("""
        SELECT id, rate_value, tax_name, tax_code, country_code, effective_from, effective_to
        FROM tax_rates WHERE id = :rid AND is_active = TRUE
    """), {"rid": product.tax_rate_id}).fetchone()
    if rate_row:
        # Validate date range
        if rate_row.effective_from and rate_row.effective_from > as_of_date:
            pass  # not yet effective, fall through
        elif rate_row.effective_to and rate_row.effective_to < as_of_date:
            pass  # expired, fall through
        # Validate country
        elif rate_row.country_code:
            branch = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
            branch_cc = (branch.country_code or "SA").upper() if branch else "SA"
            if rate_row.country_code.upper() != branch_cc:
                pass  # wrong country, fall through
            else:
                return {"tax_rate_id": rate_row.id, "tax_rate": Decimal(str(rate_row.rate_value)), "tax_name": rate_row.tax_name}
        else:
            return {"tax_rate_id": rate_row.id, "tax_rate": Decimal(str(rate_row.rate_value)), "tax_name": rate_row.tax_name}
```

#### 5b. Modify `_resolve_tax_group` (line 553)
Add `as_of_date` and `branch_country` parameters. Filter each rate in the group:
```python
def _resolve_tax_group(tax_group_id: int, db, as_of_date=None, branch_country=None) -> List[Dict]:
    # ... existing group fetch ...
    for tid in tax_ids:
        tax_row = db.execute(text("""
            SELECT id, tax_code, tax_name, rate_value, country_code, effective_from, effective_to
            FROM tax_rates WHERE id = :tid AND is_active = TRUE
        """), {"tid": tid}).fetchone()
        if not tax_row:
            continue
        if as_of_date:
            if tax_row.effective_from and tax_row.effective_from > as_of_date:
                continue
            if tax_row.effective_to and tax_row.effective_to < as_of_date:
                continue
        if tax_row.country_code and branch_country:
            if tax_row.country_code.upper() != branch_country.upper():
                continue
        taxes.append({...})
```

Update every caller of `_resolve_tax_group`, including:
- product group branch in `resolve_line_tax`
- classification group branch in `resolve_line_tax`
- product group branch in `resolve_line_tax_group`
- classification group branch in `resolve_line_tax_group`

Compute `branch_country` once near the start of both `resolve_line_tax` and `resolve_line_tax_group` to avoid repeated branch queries.

#### 5c. Harden classification-rate creation
In `backend/routers/finance/tax_compliance.py`:
- Reject requests where both `tax_rate_id` and `tax_group_id` are set.
- Reject requests where neither is set only if the UI does not intentionally use NULL to mean exempt. If NULL means exempt, document it in code and response.
- If `tax_rate_id` is set, verify its `country_code` is either NULL or equals `data.country_code`.
- If `tax_group_id` is set, verify every active group rate is either global or matches `data.country_code`.

#### 5d. Add tests
- Product with expired rate → falls through to branch default.
- Product with foreign country rate → falls through.
- Classification cannot link a foreign-country rate to a country.
- Tax group skips or rejects invalid-country/expired rates according to the chosen behavior.

---

## Phase 6: Fix Sales/Purchase Order Branch Validation (High)

### Problem
`sales/orders.py:90,120` and `purchases/orders.py:179,211`: Tax is calculated using `data.branch_id` before validating user has access to that branch.

### Files to modify
- `backend/routers/sales/orders.py`
- `backend/routers/purchases/orders.py`

### Changes

#### 6a. In `sales/orders.py` create_sales_order (line 90)
Add before tax calculation (line 113):
```python
validated_branch_id = validate_branch_access(current_user, data.branch_id)
if validated_branch_id is None:
    raise HTTPException(status_code=400, detail="يجب تحديد الفرع")
```
Use `validated_branch_id` for `resolve_line_tax`, header insert, and audit log.

#### 6b. In `purchases/orders.py` create_purchase_order (line 179)
Same: compute `validated_branch_id` before the tax loop and use it for `resolve_line_tax`, header insert, and audit log.

#### 6c. Ensure branch_id is required
Check `SOCreate` / `POCreate` schemas — `branch_id` should not be Optional.

#### 6d. Add test
User with branch [1] cannot create order with branch_id=2 → 403.

---

## Phase 7: Fix Invoice Preview (Medium)

### Problem
`sales/invoices.py:118`: Preview uses `item.tax_rate` from client (float), not from tax engine. Returns `float()` values. Actual save uses engine + Decimal.

### Files to modify
- `backend/routers/sales/invoices.py`
- `backend/routers/purchases/invoices.py`
- `frontend/src/hooks/useInvoiceCalc.js`

### Changes

#### 7a. In `sales/invoices.py` preview (line 118)
```python
# Instead of using item.tax_rate from client:
for item in invoice.items:
    taxes = resolve_line_tax_group(invoice.branch_id, item.product_id, db, invoice.invoice_date, customer_id=invoice.customer_id)
    effective_tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
    la = compute_line_amounts(item.quantity, item.unit_price, effective_tax_rate, item.discount, discount_is_percent=False)
    line_details.append({
        "product_id": item.product_id,
        "quantity": money_str(item.quantity),
        "unit_price": money_str(item.unit_price),
        "tax_rate": rate_str(effective_tax_rate),
        "discount": money_str(item.discount),
        "subtotal": money_str(la["subtotal"]),
        "discount_amount": money_str(la["discount_amount"]),
        "taxable": money_str(la["taxable"]),
        "tax_amount": money_str(la["tax_amount"]),
        "line_total": money_str(la["line_total"]),
    })
```
Validate `invoice.branch_id` before resolving taxes. Return `applied_taxes` when multiple taxes apply, matching the create-invoice endpoint.

#### 7b. Same for `purchases/invoices.py` preview.
Purchase preview can use `resolve_line_tax` unless purchase-side multi-tax groups are required; if multi-tax can apply to purchases too, use `resolve_line_tax_group` for both sales and purchases for consistency.

#### 7c. In `useInvoiceCalc.js`
Add comment that `quickCalc` is approximate. The `preview()` function already calls backend which is authoritative. No change needed if preview endpoint is fixed.

---

## Phase 8: Unify Decimal Serialization (Medium)

### Problem
`returns_.py:68`, `rates.py:70`: Some endpoints return raw SQL rows with Decimal objects.

### Files to modify
- `backend/routers/finance/taxes/returns_.py`
- `backend/routers/finance/taxes/rates.py`
- `backend/utils/tax_precision.py`

### Changes

#### 8a. Add to `tax_precision.py`
```python
def serialize_tax_row(row, money_fields=None, rate_fields=None):
    """Convert a SQL row dict to JSON-safe with Decimal→string."""
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    elif isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(row)
    for f in (money_fields or []):
        if f in d and d[f] is not None:
            d[f] = money_str(d[f])
    for f in (rate_fields or []):
        if f in d and d[f] is not None:
            d[f] = rate_str(d[f])
    return d
```

#### 8b. Apply in `returns_.py` list endpoint (line 68)
Serialize `taxable_amount`, `tax_amount`, `total_amount`, `paid_amount` as strings.

#### 8c. Apply in `rates.py` list endpoint (line 70)
Serialize `rate_value` as string.

---

## Phase 9: Fix Frontend Branch Name Display (Low)

### Problem
`TaxCompliance.jsx:420`: Uses `currentBranch.name` but API returns `branch_name`.

### Files to modify
- `frontend/src/pages/Taxes/TaxCompliance.jsx`

### Change
```jsx
// OLD:
{currentBranch?.name}

// NEW:
{currentBranch?.branch_name || currentBranch?.name}
```

---

## Test File

Create `backend/tests/test_64_tax_module_integrations.py` covering:
1. **VAT header discount**: invoice 1000, 15% VAT, 10% header discount → tax = 135
2. **Zakat branch scope**: user A [1,2] and user B [3] don't collide
3. **ZATCA body**: POST with JSON body works, no 422
4. **ZATCA branch access**: user without branch access → 403
5. **WHT missing branch**: no branch_id → 400
6. **WHT inactive rate**: inactive rate → 404
7. **WHT wrong country**: rate from different country → 400
8. **Tax engine expired rate**: product with expired rate → falls through
9. **Tax engine wrong country**: product with foreign rate → falls through
10. **Sales order branch validation**: user branch [1], order branch [2] → 403
11. **Preview Decimal strings**: preview returns strings, not floats

---

## Verification Commands

Run before considering the task done:

```bash
python3 -m compileall backend/routers/finance/taxes backend/routers/finance/tax_compliance.py backend/routers/external.py backend/routers/system_completion/accounting.py backend/services/tax_engine.py backend/utils

env POSTGRES_PASSWORD=test SECRET_KEY=0123456789abcdef0123456789abcdef .venv/bin/python -m pytest backend/tests/test_63_tax_constitution_hardening.py backend/tests/test_64_tax_module_integrations.py

(cd frontend && npm run test -- DataTable.test.jsx)
(cd frontend && npm run build)
git diff --check
```

---

## Definition of Done

- [ ] Every tax calculation uses Decimal + ROUND_HALF_UP
- [ ] Every high-risk tax mutation has idempotency or clear rejection
- [ ] Every operational tax record has correct branch scope
- [ ] "All Branches" does not mix limited-user scope with company-wide scope
- [ ] ZATCA and WHT do not bypass branch permissions
- [ ] Reports and returns match actual invoices after discounts
- [ ] Tests and build pass
