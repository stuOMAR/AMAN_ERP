# Contract: Contract Coverage Resolver

## Helper

`services/fsm/coverage.py::resolve_coverage(contract_id, line) -> CoverageOutcome`

`CoverageOutcome` fields: `covered: bool`, `billable_amount: Decimal`, `category: 'labour'|'parts'|'travel'`, `cap_applied: bool`, `reason: str`.

## `coverage_rules` JSONB Shape

```json
{
  "labour": {"covered": true, "cap_amount": "5000.0000", "cap_hours": "40.0000"},
  "parts": {"covered": true, "cap_amount": "10000.0000", "exclusions": [item_id1, item_id2]},
  "travel": {"covered": false}
}
```

Validated via Pydantic at write.

## Behavior

- For each service-order line: classify into `labour|parts|travel` (line type).
- Apply category rule: if `covered=false`, line is fully billable.
- If `covered=true` and within caps (counting prior consumption in the same contract period): line is non-billable; portion above cap is billable.
- Excluded item ids are billable regardless of `parts.covered`.
- Returns `CoverageOutcome` per line; aggregator produces invoice line set.

## Errors

| Code | When |
|------|------|
| 422 `coverage.invalid_rules` | JSON shape fails Pydantic validation. |
| 422 `coverage.contract_inactive` | Contract not active at `as_of`. |
