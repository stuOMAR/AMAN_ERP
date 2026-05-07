# Contract: DMS Attachment Links

## Purpose
Replace freeform `documents.related_module` / `related_id` strings with a typed FK linkage table.

## Helper

`services/dms/attachment_links.py::link(document_id, entity_type, entity_id, link_role=None)`
`services/dms/attachment_links.py::unlink(document_id, entity_type, entity_id, link_role=None)`
`services/dms/attachment_links.py::list_for(entity_type, entity_id) -> [Document]`
`services/dms/attachment_links.py::list_links(document_id) -> [Link]`

## Behavior

- Table `dms_attachment_links(tenant_id, document_id, entity_type, entity_id, link_role, created_by_user_id)`.
- Unique `(tenant_id, document_id, entity_type, entity_id, link_role)`.
- Any module attaching a document to an entity MUST go through this helper.
- Legacy `documents.related_module` / `related_id` columns deprecated; backfilled in migration 024m via mapping table; columns dropped one release later.
- `entity_type` whitelist enforced (matches business entity registry).

## Storage Path Centralization

`services/dms/storage_paths.py::resolve(document_id, version=None) -> str` is the only storage-path producer. Format: `<dms.storage_root>/<tenant_id>/<yyyy>/<mm>/<document_id>[/<version>]`. Quarantine path: `<dms.quarantine_root>/<tenant_id>/<document_id>`.

## CI Lints

- `scripts/check_storage_paths.py` — no inline path arithmetic outside `storage_paths.py`.
- `scripts/check_attachment_links.py` — no INSERT into `documents` with non-null `related_module`/`related_id` (deprecated path).

## Errors

| Code | When |
|------|------|
| 422 `attachment.unknown_entity_type` | Not in whitelist. |
| 409 `attachment.duplicate_link` | Same `(document, entity, role)` tuple. |
