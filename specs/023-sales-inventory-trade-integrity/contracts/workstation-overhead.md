# Contract: Workstation Overhead

**Module**: `services/manufacturing/workstation_overhead.py`.

## Purpose

Provide a per-workstation overhead rate (per minute) to the production completion service, with effective-dating and a global fallback.

## Public function

```
get_rate(workstation_id, *, as_of: date) -> Decimal
```

Lookup order:

1. `workstations` row where `workstation_id = ?` AND `(effective_from IS NULL OR effective_from ≤ as_of)` AND `(effective_to IS NULL OR effective_to ≥ as_of)` — return `overhead_rate`.
2. If null/missing → return `manufacturing.global_overhead_rate` from `company_settings`.

## Validation

- Effective ranges must not overlap on the same `workstation_id` (CHECK + EXCLUSION constraint).
- Rate `≥ 0`.

## Errors

- `ConflictingOverheadRanges` (DB constraint surfaced).

## Audit

Rate edits audited as `mfg.workstation.overhead_updated`.
