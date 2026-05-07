# Contract: HTTP Endpoints (Summary)

| Method | Path | Module | Permission | Sensitive |
|--------|------|--------|------------|-----------|
| POST | `/sales/orders/{id}/invoice` | `routers/sales/order_to_invoice.py` | `sales.invoice.create` | yes |
| POST | `/sales/invoices/{id}/cancel` | `routers/sales/cancellation.py` | `sales.invoice.cancel` | yes |
| POST | `/pos/sales/{id}/cancel` | `routers/pos/cancellation.py` | `pos.sale.cancel` | yes |
| POST | `/returns` | `routers/returns_unified.py` | `sales.return.create` | yes |
| POST | `/returns/{id}/post` | `routers/returns_unified.py` | `sales.return.post` | yes |
| POST | `/returns/{id}/cancel` | `routers/returns_unified.py` | `sales.return.cancel` | yes |
| GET  | `/returns` | `routers/returns_unified.py` | `sales.return.read` | no |
| POST | `/pos/offline/batches` | `routers/pos/offline.py` | `pos.offline.submit` | no (device-scoped) |
| GET  | `/pos/offline/batches` | `routers/pos/offline.py` | `pos.offline.read` | no |
| POST | `/pos/offline/batches/{id}/retry` | `routers/pos/offline.py` | `pos.offline.admin` | yes |
| GET  | `/crm/velocity` | `routers/crm/velocity.py` | `crm.read` | no |
| GET  | `/crm/funnel` | `routers/crm/funnel.py` | `crm.read` | no |
| GET  | `/crm/cashflow-forecast` | `routers/crm/cashflow.py` | `crm.read` | no |
| GET  | `/einvoicing/outbox` | `routers/einvoicing/outbox_admin.py` | `einvoicing.outbox.read` | yes |
| POST | `/einvoicing/outbox/{id}/reprocess` | `routers/einvoicing/outbox_admin.py` | `einvoicing.outbox.reprocess` | yes |
| POST | `/manufacturing/mrp/run` | `routers/manufacturing/mrp.py` | `mfg.mrp.run` | yes |
| GET  | `/manufacturing/mrp/recommendations` | `routers/manufacturing/mrp_recommendations.py` | `mfg.mrp.read` | no |
| POST | `/manufacturing/mrp/recommendations/{id}/accept` | `routers/manufacturing/mrp_recommendations.py` | `mfg.mrp.accept` | yes |
| POST | `/manufacturing/orders/{id}/approve` | `routers/manufacturing/production_approval.py` | `mfg.order.approve` | yes |
| POST | `/manufacturing/orders/{id}/complete` | `routers/manufacturing/production.py` | `mfg.order.complete` | yes |
| POST | `/manufacturing/orders/{id}/qc/pass` | `routers/manufacturing/qc.py` | `mfg.qc.pass` | yes |
| POST | `/manufacturing/orders/{id}/qc/fail` | `routers/manufacturing/qc.py` | `mfg.qc.fail` | yes |
| GET  | `/inventory/transfers` (canonical) | `routers/inventory/transfers.py` | `inventory.transfer.read` | no |
| POST | `/inventory/transfers` (canonical) | `routers/inventory/transfers.py` | `inventory.transfer.create` | yes |
| ANY  | `/inventory/transfer` | router stub | — | — (returns 410 Gone) |
| GET  | `/inventory/archival/status` | `routers/inventory/archival_admin.py` | `inventory.archival.read` | no |
| POST | `/inventory/archival/run` | `routers/inventory/archival_admin.py` | `inventory.archival.admin` | yes |

All sensitive endpoints are wrapped by 022's `require_sensitive_permission` decorator and registered with the startup discovery hook.

## Idempotency

Endpoints that mutate state and may be retried by clients accept `Idempotency-Key` header (≤64 chars). Server stores `(tenant_id, endpoint, idempotency_key) → (response_hash, response_body)` for replay during a 24h window.

## Error envelope

All error responses share:

```
{ "code": "<dotted.code>", "message": "<i18n key>", "detail": <object|null> }
```

`code` values are namespaced (`sales.*`, `pos.*`, `mfg.*`, `inventory.*`, `einvoicing.*`, `crm.*`).
