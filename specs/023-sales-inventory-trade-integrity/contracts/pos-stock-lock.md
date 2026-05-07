# Contract: POS Stock Lock

**Module**: `services/pos/stock_lock.py`
**Public**: context manager `pos_stock_lock(tenant_id, warehouse_id, *, ttl=None)`.

## Purpose

Serialize the critical section of every POS commit and POS-side return per `(tenant_id, warehouse_id)`. The lock is what prevents two concurrent commits from over-decrementing the same item.

## Behavior

1. Compute key `pos:lock:<tenant_id>:<warehouse_id>`.
2. Try `SET NX PX <ttl_ms>` against Redis. TTL = `pos.lock_ttl_seconds × 1000`.
3. If acquired → yield. On exit, delete key only if still owned (Lua `if redis.call('get',k)==token then return redis.call('del',k) end`).
4. If not acquired → one short retry after 50ms. If still not acquired → fall back to `pg_advisory_xact_lock(hash(tenant_id, warehouse_id))` for the duration of the surrounding transaction.
5. If Redis is unreachable → log once per minute and use the advisory-lock path immediately.

## Inputs / outputs

- Inputs: `tenant_id`, `warehouse_id`, optional `ttl` override.
- Yields: a token (string) used by the caller for diagnostic logging only.
- Raises: `PosLockTimeout` after `5s` when both Redis and DB advisory paths fail.

## Lint enforcement

`scripts/check_pos_lock_usage.py` fails CI if any function in `services/pos/` writes to `inventory_transactions` or `pos_sales` outside the context manager.

## Audit

Lock acquisition is **not** audited (high frequency). Lock timeouts are audited as `pos.stock_lock_timeout` with `(tenant_id, warehouse_id)`.
