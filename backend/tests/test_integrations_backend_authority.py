from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_integrations_checker_configuration_is_present():
    checker = _read("scripts/check_backend_authority.py")

    assert '"integrations": {' in checker
    assert "Integrations / DMS / Notifications / Imports" in checker
    assert '"backend/routers/integrations_admin.py"' in checker
    assert '"backend/routers/data_import.py"' in checker
    assert '"backend/routers/dms/quotas_admin.py"' in checker
    assert '"backend/routers/notifications/core.py"' in checker
    assert '"backend/services/webhooks/dispatch.py"' in checker
    assert '"frontend/src/pages/DataImport/DataImportPage.jsx"' in checker
    assert "Data import execution requires Idempotency-Key" in checker
    assert "Webhook dispatch dedupes already queued/sent deliveries" in checker


def test_integrations_backend_guards_and_sanitization():
    integrations_admin = _read("backend/routers/integrations_admin.py")
    data_import = _read("backend/routers/data_import.py")
    dms_quotas = _read("backend/routers/dms/quotas_admin.py")
    dms_paths = _read("backend/services/dms/storage_paths.py")
    antimalware = _read("backend/services/dms/antimalware.py")
    notifications = _read("backend/routers/notifications/core.py")
    queue_admin = _read("backend/routers/notifications/queue_admin.py")
    retry_service = _read("backend/services/integration_retry_service.py")
    webhook_dispatch = _read("backend/services/webhooks/dispatch.py")
    notification_worker = _read("backend/services/notifications/queue_worker.py")
    key_service = _read("backend/services/integration_keys_service.py")

    assert "encrypted_value" in key_service
    assert '"encrypted_value":' not in key_service

    assert "sanitize_for_audit" in integrations_admin
    assert "limit: int = Query(25, ge=1, le=100)" in integrations_admin
    assert 'require_idempotency_key(request, operation="integration DLQ replay")' in integrations_admin
    assert '"amount": str(Decimal(str(r[3])))' in integrations_admin
    assert re.search(r"\bfloat\(", integrations_admin) is None

    assert 'require_idempotency_key(request, operation="data import execute")' in data_import
    assert "validate_file_mime_and_signature" in data_import
    assert "skip_errors: bool = Query(False)" in data_import
    assert "_find_completed_import_by_idempotency_key" in data_import

    assert 'APIRouter(prefix="/dms"' in dms_quotas
    assert "quarantine_ref" in dms_quotas
    assert '"quarantine_path":' not in dms_quotas
    assert "file_name" in dms_quotas
    assert "tenant_id = :tnt AND deleted_at" not in dms_quotas
    assert "dms.path_traversal" in dms_paths
    assert '"clean": False, "engine": "clamav", "error": "scan_unavailable"' in antimalware

    assert 'require_idempotency_key(request, operation="notification send")' in notifications
    assert "feature_source = :source" in notifications
    assert "limit: int = Query(25, ge=1, le=100)" in notifications
    assert 'require_idempotency_key(request, operation="notification retry")' in queue_admin
    assert "sanitize_for_audit(r[6], context=\"notification_queue\")" in queue_admin

    assert "_sanitize_external_payload" in retry_service
    assert "gateway_response = outcome.get(\"gateway_response\")" not in retry_service
    assert "sanitize_for_audit(payload or {}, context=\"webhook_dispatch\")" in webhook_dispatch
    assert "WHERE NOT EXISTS" in webhook_dispatch
    assert "webhook_outbox" in webhook_dispatch
    assert "_safe_error" in notification_worker

    dms_quota_service = _read("backend/services/dms/quotas.py")
    dms_attachment_links = _read("backend/services/dms/attachment_links.py")
    assert "COALESCE(is_deleted, FALSE) = FALSE" in dms_quota_service
    assert "d.file_name" in dms_attachment_links
    assert "d.filename" not in dms_attachment_links


def test_integrations_frontend_uses_backend_authoritative_flows():
    data_import_service = _read("frontend/src/services/dataImport.js")
    data_import_page = _read("frontend/src/pages/DataImport/DataImportPage.jsx")
    integration_queues = _read("frontend/src/services/integrationQueues.js")
    notifications_service = _read("frontend/src/services/notifications.js")
    notification_queue = _read("frontend/src/pages/notifications/NotificationQueueMonitor.jsx")
    integration_dlq = _read("frontend/src/pages/Settings/IntegrationDLQ.jsx")
    treasury_service = _read("frontend/src/services/treasury.js")
    dms_service = _read("frontend/src/services/dms.js")
    dms_admin = _read("frontend/src/pages/dms/DmsAdmin.jsx")
    service_documents = _read("frontend/src/pages/Services/DocumentManagement.jsx")
    project_details = _read("frontend/src/pages/Projects/ProjectDetails.jsx")

    assert "'Idempotency-Key': idempotencyKey" in data_import_service
    assert "params: { entity_type: entityType, skip_errors: false }" in data_import_service
    assert "dataImportAPI.previewImport(formData, entity)" in data_import_page
    assert "dataImportAPI.executeImport(" in data_import_page
    assert "dataImportAPI.getEntityTypes()" in data_import_page
    assert "dataImportAPI.getTemplate(entity)" in data_import_page
    assert "/data-import/export/" not in data_import_page
    assert "previewData.preview_rows" in data_import_page
    assert "previewData.data" not in data_import_page
    assert "/finance/bank-feeds/import" in treasury_service
    assert "/treasury/bank-import', formData" not in treasury_service.split("importLegacyBankStatement", 1)[0]

    assert "replayDLQ: (id, idempotencyKey" in integration_queues
    assert "'Idempotency-Key': idempotencyKey" in integration_queues
    assert "'Idempotency-Key': idempotencyKey" in notifications_service
    assert "makeIdempotencyKey(`notification-retry:${id}`)" in notification_queue
    assert "it.amount?.toLocaleString" not in integration_dlq
    assert "/dms/quotas" in dms_service
    assert "/dms/scan-stats" in dms_service
    assert "/dms/storage/recalculate" in dms_service
    assert "'Idempotency-Key': idempotencyKey" in dms_service
    assert "QuotaMeter" in dms_admin
    assert "QuarantineAlerts" in dms_admin
    assert "servicesAPI.downloadDocument" in service_documents
    assert "doc.state === 'quarantined'" in service_documents
    assert "projectsAPI.downloadDocument" in project_details
    assert "doc.dms_state === 'quarantined'" in project_details
