# Contract: QC Gate

**Module**: `services/manufacturing/qc_gate.py`.
**Endpoints**: `POST /manufacturing/orders/{id}/qc/pass`, `POST /manufacturing/orders/{id}/qc/fail` (sensitive).

## Purpose

Block FG release for MOs flagged `qc_required=true` until QC passes. Failed batches route to scrap or rework with a documented JE.

## Behavior

- `qc/pass` body: `{ "completion_ids": [...] }` — moves each completion's qty from the virtual `qc_pending` location to FG. State machine: `qc_pending → completed` when all completions are passed AND `remaining_qty == 0`.
- `qc/fail` body: `{ "completion_ids": [...], "disposition": "scrap"|"rework", "reason": "..." }`:
  - `scrap` → write `scrap_movements` row, `gl_service.post(source='mfg_qc_scrap', source_id=mo.id)`.
  - `rework` → return units to WIP, increment `mo.remaining_qty`, state `qc_pending → in_progress`.
- `production_completions.qc_state` updated to `passed` / `failed`.

## Validation

Cannot pass/fail a completion that's not `qc_state='pending'`.

## Errors

- `409 mfg.qc.no_pending_completions`.
- `422 mfg.qc.invalid_disposition`.

## Audit

`mfg.qc.passed`, `mfg.qc.failed_scrap`, `mfg.qc.failed_rework`.
