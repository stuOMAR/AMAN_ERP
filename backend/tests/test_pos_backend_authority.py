from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_pos_frontend_submits_backend_preview_total_and_idempotency_key():
    source = _read("frontend/src/pages/POS/POSInterface.jsx")

    assert "submitted_grand_total: preview?.total_amount ? String(preview.total_amount) : null" in source
    assert "orderPreview?.total ?" not in source
    assert "const idempotencyKey = newClientOperationId();" in source
    assert "client_order_id: clientOrderId" in source
    assert "'Idempotency-Key': idempotencyKey" in source
    assert "savePendingOrder({ orderData, idempotencyKey })" in source


def test_pos_offline_sync_replays_with_stored_idempotency_key():
    offline_manager = _read("frontend/src/pages/POS/POSOfflineManager.jsx")
    service = _read("frontend/src/services/pos.js")

    assert "order.idempotencyKey || order.orderData?.client_order_id" in offline_manager
    assert "posAPI.createOrder(order.orderData, idempotencyKey)" in offline_manager
    assert "createOrder: (data, idempotencyKey)" in service
    assert "'Idempotency-Key': idempotencyKey" in service


def test_pos_backend_idempotent_replay_returns_order_response_shape():
    source = _read("backend/routers/pos/orders.py")

    assert "SELECT id, order_number, total_amount, status, created_at" in source
    assert "WHERE idempotency_key = :key" in source
    assert "return OrderResponse(" in source
    assert 'http_error(400, "idempotency_key_required", request)' in source
