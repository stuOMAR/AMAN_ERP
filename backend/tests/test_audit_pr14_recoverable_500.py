"""Audit PR 14 (Batch 14) — Recoverable-500 → structured 4xx.

Closes:

* F-NEW-294 — backend/routers/reports/accounting_analysis.py:604
              ``horizontal_analysis`` mapped per-period SQL failures to
              HTTP 500. After Batch 14 it raises HTTP 400 with a
              structured ``horizontal_analysis_period_failed`` body.
* F-NEW-299 — backend/routers/reports/custom.py:270
              ``_build_dynamic_query`` raised a bare ``ValueError`` for
              an unknown data source; outer ``except Exception`` then
              collapsed it to HTTP 500. After Batch 14 the helper raises
              ``HTTPException(400, ...)`` directly and the wrapping
              handlers re-raise HTTPException without remapping.

The fix also corrects three pre-existing latent ``NameError: request``
bugs in ``custom.py`` (``create_custom_report``, ``delete_custom_report``,
``get_custom_report``) that surfaced while wiring the structured error
body — see test ``test_request_parameter_present_on_handlers``.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCT_ANALYSIS_PY = REPO_ROOT / "backend/routers/reports/accounting_analysis.py"
CUSTOM_PY = REPO_ROOT / "backend/routers/reports/custom.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── F-NEW-294 — accounting_analysis.py:604 horizontal_analysis ────────────


def test_horizontal_analysis_period_failure_maps_to_400():
    src = _read(ACCT_ANALYSIS_PY)
    assert "horizontal_analysis: period" in src, "anchor missing"
    # The legacy 500 status is gone …
    assert "status_code=500" not in src or src.count("status_code=500") == 0, (
        "F-NEW-294: horizontal_analysis must not surface a 500 for a "
        "per-period failure."
    )
    # … and replaced by a structured 400 body.
    assert "horizontal_analysis_period_failed" in src, (
        "F-NEW-294: must surface the structured 400 error body."
    )


def test_horizontal_analysis_passes_http_exception_through():
    src = _read(ACCT_ANALYSIS_PY)
    # The handler must re-raise HTTPException so a downstream 4xx isn't
    # collapsed to 400 by the broad except clause.
    assert re.search(
        r"except\s+HTTPException\s*:\s*\n\s*(?:#[^\n]*\n\s*)*raise",
        src,
    ), "F-NEW-294: must include `except HTTPException: raise` re-raise."


# ── F-NEW-299 — custom.py:270 _build_dynamic_query ────────────────────────


def test_invalid_data_source_raises_http_400_not_value_error():
    src = _read(CUSTOM_PY)
    body_idx = src.find("source_map.get(config.resolved_source)")
    assert body_idx >= 0, "anchor missing"
    body = "\n".join(src[body_idx:].splitlines()[:25])
    assert 'raise ValueError(f"Invalid Data Source' not in body, (
        "F-NEW-299: legacy bare ValueError must be replaced."
    )
    assert 'status_code=400' in body, (
        "F-NEW-299: must raise HTTPException(400, ...)."
    )
    assert 'invalid_data_source' in body, (
        "F-NEW-299: must surface a structured invalid_data_source body."
    )


def test_custom_handlers_pass_http_exception_through():
    """All three handlers that delegate to ``_generate_custom_report_data``
    must re-raise HTTPException rather than collapse to 500."""
    src = _read(CUSTOM_PY)
    # Three independent try blocks must include `except HTTPException: raise`.
    occurrences = re.findall(
        r"except\s+HTTPException\s*:\s*\n\s*(?:#[^\n]*\n\s*)*(?:db\.rollback\(\)\s*\n\s*)?raise",
        src,
    )
    assert len(occurrences) >= 3, (
        "F-NEW-299: at least three handlers (preview, create, get) must "
        "include `except HTTPException: raise` after Batch 14. found="
        f"{len(occurrences)}"
    )


def test_request_parameter_present_on_handlers():
    """Bonus: Batch 14 cleans up three latent NameError(request) bugs in
    custom.py that would have shadowed the new 400 surface — verify the
    handlers now declare ``request: Request`` explicitly.
    """
    src = _read(CUSTOM_PY)
    for handler_def in (
        "async def create_custom_report(",
        "async def get_custom_report(",
        "async def delete_custom_report(",
    ):
        idx = src.find(handler_def)
        assert idx >= 0, f"anchor missing: {handler_def}"
        body = "\n".join(src[idx:].splitlines()[:6])
        assert "request: Request" in body, (
            f"{handler_def} must accept request: Request to use http_error()."
        )


def test_request_imported_from_fastapi():
    src = _read(CUSTOM_PY)
    assert re.search(
        r"^from fastapi import .*\bRequest\b",
        src,
        re.M,
    ), "Request must be imported from fastapi for the handlers above."
