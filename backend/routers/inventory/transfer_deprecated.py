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
            "message": "This endpoint has been removed. Use /inventory/transfers instead.",
            "moved_to": "/inventory/transfers",
        },
    )
