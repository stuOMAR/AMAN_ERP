# Contract: Account Classifier (`services/account_classifier.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def classify(account_id: int) -> AccountClassification: ...

def classify_many(account_ids: Iterable[int]) -> dict[int, AccountClassification]: ...

def upsert_classification(
    tenant_id: int,
    account_id: int,
    *,
    statement_category: str,
    sign: int,
    aggregation_hint: str | None = None,
    valid_from: date,
    valid_to: date | None = None,
    actor_id: int,
) -> AccountClassification: ...
```

`AccountClassification`:

```python
@dataclass(frozen=True)
class AccountClassification:
    account_id: int
    statement_category: Literal["asset","liability","equity","revenue","expense",
                                "contra_asset","contra_liability","contra_equity",
                                "contra_revenue","contra_expense"]
    sign: Literal[-1, 1]
    aggregation_hint: str | None
```

## Behavior

- MUST read from `account_classifications` filtered by `(tenant_id, account_id, is_active=true, valid_from <= today <= valid_to|inf)`.
- MUST cache results per request using the existing request-scoped cache; MUST invalidate the cache on `upsert_classification`.
- MUST raise `MissingClassificationError(account_id)` when no active row exists. The migration seeds defaults, so this should never fire post-migration; if it does, the report MUST fail loudly rather than silently fall back to code-range heuristics.
- `upsert_classification` MUST validate `sign ∈ {-1, +1}` matches `statement_category` semantics (e.g., `asset` → `+1`, `contra_asset` → `-1`); MUST close the previous active row by setting `valid_to = new_valid_from - 1 day`; MUST emit `log_activity(action="account_classification.upsert", critical=True)`.

## Consumers

The following modules MUST switch to `account_classifier`:

- `services/reports/balance_sheet.py`
- `services/reports/income_statement.py`
- `services/reports/trial_balance.py`
- `services/reports/kpi_dashboard.py`
- Any helper that previously asked "is this an asset/liability/...?" via account-code ranges.

A CI scan (`scripts/check_account_code_ranges.py`) fails the build if hard-coded code-range checks remain in `backend/services/reports/**` or `backend/routers/reports*`.

## Seed migration

Migration `022c_account_classifications` MUST:

- Create the table.
- Backfill one active row per account using the **current** code-range heuristic so day-one report behavior is preserved.
- Mark backfilled rows with `aggregation_hint = "seed"` for traceability.
