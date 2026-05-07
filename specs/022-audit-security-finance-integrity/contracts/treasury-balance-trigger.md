# Contract: Treasury Balance Trigger (`alembic/versions/022f_treasury_balance_trigger.py`)

**Feature**: 022-audit-security-finance-integrity

## Trigger

- Name: `tg_treasury_balance_authority`.
- Target: `treasury_accounts`, `BEFORE UPDATE OF current_balance FOR EACH ROW`.
- Behavior: raises a domain error unless `current_setting('aman.gl_context', true) = 'on'` is set on the current session.
- On block: also writes a row to `audit_logs` with `action = "treasury.balance.blocked"`, `critical = true`, capturing `OLD.current_balance`, `NEW.current_balance`, `current_user`, `inet_client_addr()`, and the SQL stack via `current_query()`.

## Application contract

- `services/treasury_service.update_balance(...)` MUST set the GUC inside its `transactional()` block:

  ```python
  with transactional(conn):
      conn.execute("SELECT set_config('aman.gl_context', 'on', true)")
      ...  # update + GL post via gl_service
  ```

- The flag is **transaction-local** (`is_local=true`) so it never leaks beyond the current transaction.

## Migration bypass

- Alembic migrations that legitimately need to rewrite balances MUST set the GUC explicitly **and** write a one-line audit row before the update. The migration template in `backend/alembic/script.py.mako` is updated to include a helper.

## Coverage list

The trigger MUST also be considered for any future column/table that holds an authoritative balance (out of scope here, documented for follow-up).
