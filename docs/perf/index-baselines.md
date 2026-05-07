# Performance Index Baselines — Feature 025

**Purpose**: Record EXPLAIN (BUFFERS) output before and after BRIN/composite index migrations.

## Queries to EXPLAIN

### 1. Income Statement (journal/account/date)

```sql
EXPLAIN (BUFFERS, ANALYZE)
SELECT jl.account_id, SUM(jl.debit), SUM(jl.credit)
FROM journal_lines jl
JOIN journal_entries je ON je.id = jl.journal_entry_id
WHERE jl.tenant_id = :tenant_id
  AND jl.posting_date BETWEEN :start_date AND :end_date
GROUP BY jl.account_id;
```

**Before** (baseline): _TODO — run before T101/T102 migration_
**After**: _TODO — run after T101/T102 migration_
**Target**: ≥ 50% reduction in buffer reads

### 2. Trial Balance

```sql
EXPLAIN (BUFFERS, ANALYZE)
SELECT account_id, SUM(debit), SUM(credit)
FROM journal_lines
WHERE tenant_id = :tenant_id
  AND posting_date <= :as_of_date
GROUP BY account_id;
```

**Before**: _TODO_
**After**: _TODO_

### 3. Period Stats (pre-MV baseline)

```sql
EXPLAIN (BUFFERS, ANALYZE)
SELECT period_id, SUM(debit), SUM(credit)
FROM journal_lines jl
JOIN journal_entries je ON je.id = jl.journal_entry_id
WHERE jl.tenant_id = :tenant_id
  AND jl.posting_date BETWEEN :period_start AND :period_end
GROUP BY period_id;
```

**Before**: _TODO_
**After**: _TODO — post-MV this should read from `mv_period_stats`

### 4. Inventory Item Activity

```sql
EXPLAIN (BUFFERS, ANALYZE)
SELECT item_id, transaction_type, SUM(quantity)
FROM inventory_transactions
WHERE tenant_id = :tenant_id
  AND item_id = :item_id
  AND transaction_date BETWEEN :start_date AND :end_date
GROUP BY item_id, transaction_type;
```

**Before**: _TODO_
**After**: _TODO_

## Notes

- All EXPLAINs run against the largest tenant's dataset
- Buffer reads are the primary metric (not execution time)
- Target: ≥ 50% reduction on the journal/account/date report (query #1)
