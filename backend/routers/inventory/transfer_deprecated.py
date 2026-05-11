"""Deprecated /inventory/transfer endpoint — 410 Gone.

Feature 023 — T103.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.api_route("/transfer", methods=["GET", "POST", "PUT", "DELETE"])
async def deprecated_transfer(request: Request):
    return JSONResponse(
        status_code=410,
        content={
            "code": "endpoint_gone",
            "message": i18n_message("endpoint_removed", request),
            "moved_to": "/inventory/transfers",
        },
    )
