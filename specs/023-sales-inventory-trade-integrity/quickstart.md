# Quickstart: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing

**Feature**: 023-sales-inventory-trade-integrity
**Audience**: implementer running the change set after merge.
**Prereq**: feature 022 has been deployed (vault, sensitive-permission decorator, audit writer/sanitizer, account classifier, JE source enum, treasury trigger).

---

## 1. Apply migrations

Run in order — each migration ships **alongside** the matching `tenant_schema.py` + `database.py` updates:

```bash
cd backend
alembic upgrade 023a   # invoice state + idempotency_key
alembic upgrade 023b   # sales_orders.converted_to_invoice_id, responsible_user_id
alembic upgrade 023c   # returns_unified + sales_returns/pos_returns views
alembic upgrade 023d   # acc_map_sales consolidation (+ acc_map_sales_rev view)
alembic upgrade 023e   # zatca_outbox
alembic upgrade 023f   # opportunity_stage_history
alembic upgrade 023g   # pos_offline_batches
alembic upgrade 023h   # item_warehouse_settings (or backfill)
alembic upgrade 023i   # mrp_recommendations
alembic upgrade 023j   # bom_snapshots + manufacturing_orders extensions
alembic upgrade 023k   # production_completions + scrap_movements
alembic upgrade 023l   # workstations.overhead_rate (+ effective dating)
alembic upgrade 023m   # inventory_transactions_archive
```

Verify schema sync:

```bash
python scripts/check_schema_sync.py    # from feature 022; ensures tenant_schema == migrations == database.py
```

## 2. Seed tenant settings

For each existing tenant, apply the new settings keys (idempotent UPSERT):

```sql
INSERT INTO company_settings (tenant_id, key, value) VALUES
  (:tid, 'pos.lock_ttl_seconds', '5'),
  (:tid, 'pos.offline_batch_max_age_hours', '72'),
  (:tid, 'zatca.outbox_max_attempts', '8'),
  (:tid, 'zatca.outbox_backoff_base_seconds', '30'),
  (:tid, 'zatca.outbox_backoff_cap_seconds', '1800'),
  (:tid, 'zatca.profile', 'standard'),
  (:tid, 'inventory.retention_days', '365'),
  (:tid, 'inventory.low_stock_debounce_hours', '36'),
  (:tid, 'inventory.auto_reorder_enabled', 'false'),
  (:tid, 'inventory.allow_negative_balance', 'block'),
  (:tid, 'manufacturing.large_mo_threshold', '100000.0000'),
  (:tid, 'manufacturing.yield_tolerance', '0.05'),
  (:tid, 'manufacturing.missing_mapping_policy', 'warn'),
  (:tid, 'manufacturing.global_overhead_rate', '0.0000'),
  (:tid, 'manufacturing.qc_required_default', 'false'),
  (:tid, 'crm.velocity_window_days', '90'),
  (:tid, 'crm.funnel_window_days', '90'),
  (:tid, 'crm.cashflow_horizon_days', '180'),
  (:tid, 'mrp.horizon_days', '60')
ON CONFLICT (tenant_id, key) DO NOTHING;
```

For ZATCA-enabled tenants: ensure `credentials_vault` has integration `zatca` populated with `cert_pem` and `private_key_pem`. Without these, the outbox worker will mark rows `failed` with code `signing_unavailable`.

## 3. Start backend + workers

```bash
./safe-start.sh
```

Expected new startup log lines:

- `worker.zatca_outbox started (interval=5s, batch=25)`
- `worker.pos_offline_reconciler started (interval=10s, batch=50)`
- `worker.auto_reorder scheduled (every 60m)`
- `worker.mrp scheduled (every <mfg.mrp_interval_minutes>m)`
- `worker.inventory_archiver scheduled (daily 03:00 UTC)`
- `permissions.sensitive_discovery: registered <N> sensitive endpoints`

## 4. Smoke checks

### Order → Invoice (idempotent)

```bash
curl -X POST $API/sales/orders/12345/invoice \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: smoke-001" -H "Content-Type: application/json" -d '{}'
# Run the same call twice — second response must equal the first byte-for-byte.
```

Verify: `SELECT converted_to_invoice_id FROM sales_orders WHERE id=12345;` is set; `SELECT state FROM invoices WHERE id=...;` is `posted`; `SELECT * FROM zatca_outbox WHERE invoice_id=...;` exists in `pending` (or `submitted` after a few seconds).

### POS commit lock contention

Issue 5 concurrent POS commits to the same warehouse with the same item:

```bash
seq 1 5 | xargs -n1 -P5 -I{} curl -X POST $API/pos/sales \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"warehouse_id":1,"lines":[{"item_id":99,"qty":1}]}'
```

Verify: at most stock-available commits succeed; the rest return `409 pos.stock_lock_conflict` or `409 inventory.preflight_failed` listing the short item; `inventory_transactions` shows exactly the successful count.

### POS offline reconcile

Push two batches with the same `client_uuid`:

```bash
curl -X POST $API/pos/offline/batches -d '{"device_id":"D1","batches":[{"client_uuid":"<uuid>","warehouse_id":1,"lines":[...]}]}'
curl -X POST $API/pos/offline/batches -d '{"device_id":"D1","batches":[{"client_uuid":"<uuid>","warehouse_id":1,"lines":[...]}]}'
```

Verify: response shows `queued=1, duplicates=1`; after reconciler tick, `pos_offline_batches.state` is `committed` and `pos_sale_id` is set.

### MRP run + draft PO

```bash
curl -X POST $API/manufacturing/mrp/run -H "Authorization: Bearer $TOKEN" -d '{"horizon_days":60,"auto_create":true}'
```

Verify: `mrp_recommendations` rows created; for `inventory.auto_reorder_enabled=true` tenant, draft POs grouped per supplier.

### Partial production completion

```bash
curl -X POST $API/manufacturing/orders/77/complete \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"qty":50,"warehouse_id":3,"labor_minutes_by_employee":{},"overhead_minutes_by_workstation":{},"scrap_lines":[],"byproduct_lines":[]}'
```

Verify: `production_completions` row inserted; `manufacturing_orders.remaining_qty` decremented; FG inventory increased; GL JE balanced via `gl_service`; `wip_to_fg_je_id` set.

### ZATCA reprocess (dead-letter recovery)

Force a `dead_letter` (e.g., bad cert), fix the cert in the vault, then:

```bash
curl -X POST $API/einvoicing/outbox/<id>/reprocess -H "Authorization: Bearer $TOKEN"
```

Verify state transitions back through `pending → submitting → submitted → cleared|reported`.

### Low-stock webhook debounce

Trigger two consecutive sales of the same item that cross reorder point twice in one day. Verify only **one** `inventory.low_stock` webhook delivery (Redis dedupe key set).

### `/transfer` deprecated

```bash
curl -i -X POST $API/inventory/transfer
# HTTP/1.1 410 Gone
# {"code":"endpoint_gone","moved_to":"/inventory/transfers"}
```

## 5. CI lints (run locally before pushing)

```bash
python scripts/check_no_float_money.py
python scripts/check_invoice_state_writers.py
python scripts/check_je_source_id.py
python scripts/check_pos_lock_usage.py
python scripts/check_get_acc_id_callsites.py
```

All must exit `0`. They are also wired into the pipeline.

## 6. Rollback

Each migration has a working `downgrade()`. Compatibility views (`sales_returns`, `pos_returns`, `acc_map_sales_rev`) remain available so a partial rollback (e.g. only 023d/023c) keeps readers working. The state-machine module reverts to a no-op if the new columns are removed — but rollback past 023a requires manual cleanup of any invoices created with the new states; do not roll back past 023a once production traffic has used the new endpoints.
