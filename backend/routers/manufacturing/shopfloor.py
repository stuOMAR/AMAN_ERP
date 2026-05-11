"""Shop floor control endpoints — real-time work order tracking.

Endpoints:
  GET  /shopfloor/dashboard         — active work orders with current operation
  POST /shopfloor/start             — start an operation (sequence enforced)
  POST /shopfloor/complete          — complete operation (record output/scrap)
  POST /shopfloor/pause             — pause operation
  GET  /shopfloor/work-order/{id}   — progress by operation
  WS   /shopfloor/ws                — live updates for supervisor dashboards
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from schemas.shopfloor import (
    CompleteOperationRequest,
    PauseOperationRequest,
    StartOperationRequest,
)
from utils.audit import log_activity
from utils.i18n import http_error
from utils.permissions import require_permission

shopfloor_router = APIRouter(prefix="/manufacturing/shopfloor", tags=["Shop Floor"])
logger = logging.getLogger(__name__)


# ── WebSocket connection manager ─────────────────────────────────────


class _ConnectionManager:
    """Simple in-process broadcast manager for shop floor dashboards."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: dict):
        payload = json.dumps(message, default=str)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


_manager = _ConnectionManager()


# ── Helper: check delay threshold ────────────────────────────────────


_DELAY_THRESHOLD_HOURS = 4  # alert if operation takes >4h over planned


def _check_delay(db, log_id: int, work_order_id: int):
    """Return True if the operation appears delayed."""
    row = db.execute(
        text("""
            SELECT sfl.started_at,
                   mo.cycle_time,
                   po.quantity
            FROM shop_floor_logs sfl
            JOIN manufacturing_operations mo ON mo.id = sfl.routing_operation_id
            JOIN production_orders po ON po.id = sfl.work_order_id
            WHERE sfl.id = :lid
        """),
        {"lid": log_id},
    ).fetchone()
    if not row or not row.started_at or not row.cycle_time:
        return False
    planned_minutes = Decimal(str(row.cycle_time)) * Decimal(str(row.quantity))
    elapsed = (datetime.now(timezone.utc) - row.started_at).total_seconds() / 60
    return elapsed > (planned_minutes + _DELAY_THRESHOLD_HOURS * 60)


# ── Endpoints ─────────────────────────────────────────────────────────


@shopfloor_router.get(
    "/dashboard",
    dependencies=[Depends(require_permission("manufacturing.shopfloor_view"))],
)
def get_dashboard(current_user: dict = Depends(get_current_user)):
    """Return active work orders with current operation status."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT po.id AS work_order_id,
                   po.order_number,
                   p.product_name,
                   po.quantity,
                   po.produced_quantity,
                   po.status,
                   po.due_date,
                   -- current operation info
                   (SELECT mo.description FROM shop_floor_logs sfl2
                    JOIN manufacturing_operations mo ON mo.id = sfl2.routing_operation_id
                    WHERE sfl2.work_order_id = po.id AND sfl2.status = 'in_progress'
                    ORDER BY sfl2.started_at DESC LIMIT 1) AS current_operation,
                   (SELECT sfl3.status FROM shop_floor_logs sfl3
                    WHERE sfl3.work_order_id = po.id
                    ORDER BY sfl3.started_at DESC LIMIT 1) AS current_operation_status,
                   -- progress: completed ops / total ops
                   COALESCE((SELECT COUNT(*) FROM shop_floor_logs sfl4
                    WHERE sfl4.work_order_id = po.id AND sfl4.status = 'completed'), 0) AS completed_ops,
                   COALESCE((SELECT COUNT(*) FROM production_order_operations poo
                    WHERE poo.production_order_id = po.id), 0) AS total_ops
            FROM production_orders po
            JOIN products p ON p.id = po.product_id
            WHERE po.status IN ('in_progress', 'released', 'started')
            ORDER BY po.due_date ASC NULLS LAST
        """)).fetchall()

        result = []
        today = datetime.now(timezone.utc).date()
        for r in rows:
            d = dict(r._mapping)
            total = d.pop("total_ops", 0) or 1
            completed = d.pop("completed_ops", 0)
            d["progress_pct"] = round((completed / total) * 100, 1) if total else 0
            d["is_delayed"] = bool(d.get("due_date") and d["due_date"] < today and d["progress_pct"] < 100)
            result.append(d)

        return result
    finally:
        db.close()


@shopfloor_router.post(
    "/start",
    dependencies=[Depends(require_permission("manufacturing.shopfloor_operate"))],
)
async def start_operation(
    body: StartOperationRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Start a routing operation for a work order.

    Validates sequence: operation N cannot start until N-1 is completed,
    unless supervisor_override is True.
    """
    db = get_db_connection(current_user.company_id)
    try:
        # 1) Verify work order exists and is active
        wo = db.execute(
            text("SELECT id, status, branch_id, route_id FROM production_orders WHERE id = :wid"),
            {"wid": body.work_order_id},
        ).fetchone()
        if not wo:
            raise HTTPException(**http_error(404, ("work_order_not_found", request)))

        # Branch validation
        from utils.permissions import validate_branch_access
        if wo.branch_id:
            validate_branch_access(current_user, wo.branch_id)

        # 2) Verify operation exists
        op = db.execute(
            text("SELECT id, sequence, route_id FROM manufacturing_operations WHERE id = :oid AND is_deleted = false"),
            {"oid": body.routing_operation_id},
        ).fetchone()
        if not op:
            raise HTTPException(**http_error(404, ("operation_not_found", request)))

        if wo.route_id != op.route_id:
            raise HTTPException(**http_error(400, ("operation_not_in_route", request)))

        # 3) Sequence enforcement
        if op.sequence > 1 and not body.supervisor_override:
            # Find previous operation in same route
            prev_op = db.execute(
                text("""
                    SELECT mo.id
                    FROM manufacturing_operations mo
                    WHERE mo.route_id = (
                        SELECT route_id FROM manufacturing_operations WHERE id = :oid
                    )
                    AND mo.sequence = :prev_seq
                    AND mo.is_deleted = false
                """),
                {"oid": body.routing_operation_id, "prev_seq": op.sequence - 1},
            ).fetchone()

            if prev_op:
                prev_complete = db.execute(
                    text("""
                        SELECT 1 FROM shop_floor_logs
                        WHERE work_order_id = :wid
                          AND routing_operation_id = :prev_oid
                          AND status = 'completed'
                    """),
                    {"wid": body.work_order_id, "prev_oid": prev_op.id},
                ).fetchone()
                if not prev_complete:
                    logger.warning(f"Operation sequence {op.sequence} started before previous completed for work order {body.work_order_id}")
                    raise HTTPException(**http_error(400, "previous_operation_must_complete", request))

        # 4) Check no duplicate in-progress log
        existing = db.execute(
            text("""
                SELECT id FROM shop_floor_logs
                WHERE work_order_id = :wid
                  AND routing_operation_id = :oid
                  AND status = 'in_progress'
            """),
            {"wid": body.work_order_id, "oid": body.routing_operation_id},
        ).fetchone()
        if existing:
            raise HTTPException(**http_error(400, ("operation_already_in_progress", request)))

        # 5) Insert log
        now = datetime.now(timezone.utc)
        row = db.execute(
            text("""
                INSERT INTO shop_floor_logs
                (work_order_id, routing_operation_id, operator_id, started_at, status)
                VALUES (:wid, :oid, :opid, :now, 'in_progress')
                RETURNING id
            """),
            {
                "wid": body.work_order_id,
                "oid": body.routing_operation_id,
                "opid": body.operator_id,
                "now": now,
            },
        ).fetchone()
        db.commit()

        log_id = row[0]

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="shopfloor_start_operation", resource_type="shop_floor_logs",
                     resource_id=str(log_id),
                     details={"work_order_id": body.work_order_id, "operation_id": body.routing_operation_id},
                     request=request)

        # Broadcast update
        await _manager.broadcast({
            "event": "operation_started",
            "work_order_id": body.work_order_id,
            "operation_id": body.routing_operation_id,
            "log_id": log_id,
            "timestamp": now.isoformat(),
        })

        return {"log_id": log_id, "status": "in_progress", "started_at": now}
    finally:
        db.close()


@shopfloor_router.post(
    "/complete",
    dependencies=[Depends(require_permission("manufacturing.shopfloor_operate"))],
)
async def complete_operation(
    body: CompleteOperationRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Complete an operation — record output, scrap, and check delay."""
    db = get_db_connection(current_user.company_id)
    try:
        # Verify log exists and is in_progress
        log = db.execute(
            text("SELECT id, work_order_id, status FROM shop_floor_logs WHERE id = :lid"),
            {"lid": body.log_id},
        ).fetchone()
        if not log:
            raise HTTPException(**http_error(404, "log_entry_not_found", request))
        if log.status != "in_progress":
            logger.warning(f"Cannot complete log {body.log_id} with status {log.status}")
            raise HTTPException(**http_error(400, "cannot_complete_operation", request))

        # Branch validation via work order
        from utils.permissions import validate_branch_access
        po = db.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": log.work_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        now = datetime.now(timezone.utc)
        delayed = _check_delay(db, body.log_id, log.work_order_id)

        db.execute(
            text("""
                UPDATE shop_floor_logs
                SET completed_at = :now,
                    output_quantity = :oq,
                    scrap_quantity = :sq,
                    downtime_minutes = :dm,
                    notes = :notes,
                    status = 'completed',
                    updated_at = NOW()
                WHERE id = :lid
            """),
            {
                "now": now,
                "oq": body.output_quantity,
                "sq": body.scrap_quantity,
                "dm": body.downtime_minutes,
                "notes": body.notes,
                "lid": body.log_id,
            },
        )
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="shopfloor_complete_operation", resource_type="shop_floor_logs",
                     resource_id=str(body.log_id),
                     details={"output_quantity": str(body.output_quantity), "scrap_quantity": str(body.scrap_quantity)},
                     request=request)

        # Broadcast
        await _manager.broadcast({
            "event": "operation_completed",
            "work_order_id": log.work_order_id,
            "log_id": body.log_id,
            "output_quantity": str(body.output_quantity),
            "scrap_quantity": str(body.scrap_quantity),
            "is_delayed": delayed,
            "timestamp": now.isoformat(),
        })

        result = {"log_id": body.log_id, "status": "completed", "completed_at": now, "is_delayed": delayed}

        # Dispatch delay notification if needed
        if delayed:
            try:
                from services.notification_service import NotificationService
                ns = NotificationService()
                asyncio.ensure_future(ns.dispatch(
                    db=get_db_connection(current_user.company_id),
                    company_id=current_user.company_id,
                    recipient_id=current_user.id,
                    event_type="shopfloor_delay",
                    title="Shop Floor Delay Alert",
                    body=f"Work order {log.work_order_id} operation completed with delay",
                    feature_source="manufacturing",
                    reference_type="shop_floor_log",
                    reference_id=body.log_id,
                ))
            except Exception:
                logger.warning("Could not dispatch delay notification", exc_info=True)

        return result
    finally:
        db.close()


@shopfloor_router.post(
    "/pause",
    dependencies=[Depends(require_permission("manufacturing.shopfloor_operate"))],
)
async def pause_operation(
    body: PauseOperationRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Pause an in-progress operation."""
    db = get_db_connection(current_user.company_id)
    try:
        log = db.execute(
            text("SELECT id, work_order_id, status FROM shop_floor_logs WHERE id = :lid"),
            {"lid": body.log_id},
        ).fetchone()
        if not log:
            raise HTTPException(**http_error(404, "log_entry_not_found", request))
        if log.status != "in_progress":
            logger.warning(f"Cannot pause log {body.log_id} with status {log.status}")
            raise HTTPException(**http_error(400, "cannot_pause_operation", request))

        # Branch validation via work order
        from utils.permissions import validate_branch_access
        po = db.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": log.work_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        db.execute(
            text("""
                UPDATE shop_floor_logs
                SET status = 'paused',
                    notes = COALESCE(:notes, notes),
                    updated_at = NOW()
                WHERE id = :lid
            """),
            {"notes": body.notes, "lid": body.log_id},
        )
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="shopfloor_pause_operation", resource_type="shop_floor_logs",
                     resource_id=str(body.log_id), request=request)

        await _manager.broadcast({
            "event": "operation_paused",
            "work_order_id": log.work_order_id,
            "log_id": body.log_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {"log_id": body.log_id, "status": "paused"}
    finally:
        db.close()


@shopfloor_router.get(
    "/work-order/{work_order_id}",
    dependencies=[Depends(require_permission("manufacturing.shopfloor_view"))],
)
def get_work_order_progress(
    work_order_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get work order progress broken down by operation."""
    db = get_db_connection(current_user.company_id)
    try:
        wo = db.execute(
            text("""
                SELECT po.id, po.order_number, po.quantity, po.status,
                       p.product_name
                FROM production_orders po
                JOIN products p ON p.id = po.product_id
                WHERE po.id = :wid
            """),
            {"wid": work_order_id},
        ).fetchone()
        if not wo:
            raise HTTPException(**http_error(404, ("work_order_not_found", request)))

        # Branch validation
        from utils.permissions import validate_branch_access
        po_branch = db.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": work_order_id}).fetchone()
        if po_branch and po_branch.branch_id:
            validate_branch_access(current_user, po_branch.branch_id)

        ops = db.execute(
            text("""
                SELECT mo.id AS operation_id,
                       mo.description AS operation_name,
                       mo.sequence,
                       COALESCE(sfl.status, 'pending') AS status,
                       e.employee_name AS operator_name,
                       sfl.started_at,
                       sfl.completed_at,
                       COALESCE(sfl.output_quantity, 0) AS output_quantity,
                       COALESCE(sfl.scrap_quantity, 0) AS scrap_quantity
                FROM manufacturing_operations mo
                LEFT JOIN LATERAL (
                    SELECT * FROM shop_floor_logs sfl2
                    WHERE sfl2.work_order_id = :wid
                      AND sfl2.routing_operation_id = mo.id
                    ORDER BY sfl2.started_at DESC
                    LIMIT 1
                ) sfl ON TRUE
                LEFT JOIN employees e ON e.id = sfl.operator_id
                WHERE mo.route_id = (SELECT route_id FROM production_orders WHERE id = :wid)
                  AND mo.is_deleted = false
                ORDER BY mo.sequence
            """),
            {"wid": work_order_id},
        ).fetchall()

        return {
            "work_order_id": wo.id,
            "order_number": wo.order_number,
            "product_name": wo.product_name,
            "quantity": wo.quantity,
            "status": wo.status,
            "operations": [dict(o._mapping) for o in ops],
        }
    finally:
        db.close()


# ── WebSocket endpoint for live updates ───────────────────────────────


@shopfloor_router.websocket("/ws")
async def shopfloor_ws(websocket: WebSocket):
    """WebSocket for supervisor dashboards — broadcasts operation status changes."""
    await _manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        _manager.disconnect(websocket)
