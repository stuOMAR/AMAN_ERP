"""Routing management endpoints — CRUD for manufacturing routings & operations.

Endpoints:
  POST /routing              — create routing with operations
  GET  /routing              — list all routings
  GET  /routing/{id}         — get routing with operations
  PUT  /routing/{id}         — update routing and operations
  GET  /routing/product/{id} — get routings for a product
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from schemas.routing import RoutingCreate
from utils.audit import log_activity
from utils.permissions import require_permission

logger = logging.getLogger(__name__)
routing_router = APIRouter(prefix="/manufacturing/routing", tags=["Manufacturing Routing"])


# ── helpers ───────────────────────────────────────────────────────────


def _fetch_routing(conn, routing_id: int) -> dict | None:
    """Fetch a single routing + its operations (reusable)."""
    row = conn.execute(
        text("""
            SELECT r.*, p.product_name
            FROM manufacturing_routes r
            LEFT JOIN products p ON p.id = r.product_id
            WHERE r.id = :rid AND r.is_deleted = false
        """),
        {"rid": routing_id},
    ).fetchone()
    if not row:
        return None
    d = dict(row._mapping)
    d["operations"] = _fetch_operations(conn, routing_id)
    return d


def _fetch_operations(conn, route_id: int) -> list[dict]:
    rows = conn.execute(
        text("""
            SELECT mo.*, wc.name AS work_center_name
            FROM manufacturing_operations mo
            LEFT JOIN work_centers wc ON wc.id = mo.work_center_id
            WHERE mo.route_id = :rid AND mo.is_deleted = false
            ORDER BY mo.sequence
        """),
        {"rid": route_id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Endpoints ─────────────────────────────────────────────────────────


@routing_router.post(
    "",
    dependencies=[Depends(require_permission("manufacturing.routing_manage"))],
)
def create_routing(
    body: RoutingCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Create a routing with its operations in a single transaction."""
    db = get_db_connection(current_user.company_id)
    txn = db.begin()
    try:
        new = db.execute(
            text("""
                INSERT INTO manufacturing_routes
                    (name, product_id, bom_id, is_default, is_active, description)
                VALUES (:name, :pid, :bid, :default, :active, :desc)
                RETURNING *
            """),
            {
                "name": body.name,
                "pid": body.product_id,
                "bid": body.bom_id,
                "default": body.is_default,
                "active": body.is_active,
                "desc": body.description,
            },
        ).fetchone()

        for op in body.operations:
            db.execute(
                text("""
                    INSERT INTO manufacturing_operations
                        (route_id, sequence, name, work_center_id, description,
                         setup_time, cycle_time, labor_rate_per_hour)
                    VALUES (:rid, :seq, :name, :wcid, :desc,
                            :setup, :cycle, :labor)
                """),
                {
                    "rid": new.id,
                    "seq": op.sequence,
                    "name": op.name,
                    "wcid": op.work_center_id,
                    "desc": op.description,
                    "setup": op.setup_time,
                    "cycle": op.cycle_time,
                    "labor": op.labor_rate_per_hour,
                },
            )

        txn.commit()
        result = _fetch_routing(db, new.id)
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="create_routing", resource_type="manufacturing_routes",
                     resource_id=str(new.id), details={"name": body.name},
                     request=request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        txn.rollback()
        logger.error(f"Error creating routing: {e}")
        raise HTTPException(**http_error(400, "routing_create_failed", request))
    finally:
        db.close()


@routing_router.get(
    "",
    dependencies=[Depends(require_permission("manufacturing.routing_view"))],
)
def list_routings(
    current_user: dict = Depends(get_current_user),
):
    """List all routings with their operations."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""
                SELECT r.*, p.product_name
                FROM manufacturing_routes r
                LEFT JOIN products p ON p.id = r.product_id
                WHERE r.is_deleted = false
                ORDER BY r.name
            """)
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r._mapping)
            d["operations"] = _fetch_operations(db, r.id)
            result.append(d)
        return result
    finally:
        db.close()


@routing_router.get(
    "/product/{product_id}",
    dependencies=[Depends(require_permission("manufacturing.routing_view"))],
)
def get_routings_for_product(
    product_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Return all routings linked to a specific product."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""
                SELECT r.*, p.product_name
                FROM manufacturing_routes r
                LEFT JOIN products p ON p.id = r.product_id
                WHERE r.product_id = :pid AND r.is_deleted = false
                ORDER BY r.is_default DESC, r.name
            """),
            {"pid": product_id},
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r._mapping)
            d["operations"] = _fetch_operations(db, r.id)
            result.append(d)
        return result
    finally:
        db.close()


@routing_router.get(
    "/{routing_id}",
    dependencies=[Depends(require_permission("manufacturing.routing_view"))],
)
def get_routing(
    routing_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get a single routing with all operations."""
    db = get_db_connection(current_user.company_id)
    try:
        data = _fetch_routing(db, routing_id)
        if not data:
            raise HTTPException(**http_error(404, ("routing_not_found", request)))
        return data
    finally:
        db.close()


@routing_router.put(
    "/{routing_id}",
    dependencies=[Depends(require_permission("manufacturing.routing_manage"))],
)
def update_routing(
    routing_id: int,
    body: RoutingCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Update routing header and replace operations atomically."""
    db = get_db_connection(current_user.company_id)
    txn = db.begin()
    try:
        existing = db.execute(
            text("SELECT id FROM manufacturing_routes WHERE id = :rid AND is_deleted = false"),
            {"rid": routing_id},
        ).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, ("routing_not_found", request)))

        db.execute(
            text("""
                UPDATE manufacturing_routes
                SET name = :name, product_id = :pid, bom_id = :bid,
                    is_default = :default, is_active = :active,
                    description = :desc, updated_at = NOW()
                WHERE id = :rid
            """),
            {
                "name": body.name,
                "pid": body.product_id,
                "bid": body.bom_id,
                "default": body.is_default,
                "active": body.is_active,
                "desc": body.description,
                "rid": routing_id,
            },
        )

        # Replace operations
        db.execute(
            text("DELETE FROM manufacturing_operations WHERE route_id = :rid"),
            {"rid": routing_id},
        )
        for op in body.operations:
            db.execute(
                text("""
                    INSERT INTO manufacturing_operations
                        (route_id, sequence, name, work_center_id, description,
                         setup_time, cycle_time, labor_rate_per_hour)
                    VALUES (:rid, :seq, :name, :wcid, :desc,
                            :setup, :cycle, :labor)
                """),
                {
                    "rid": routing_id,
                    "seq": op.sequence,
                    "name": op.name,
                    "wcid": op.work_center_id,
                    "desc": op.description,
                    "setup": op.setup_time,
                    "cycle": op.cycle_time,
                    "labor": op.labor_rate_per_hour,
                },
            )

        txn.commit()
        result = _fetch_routing(db, routing_id)
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="update_routing", resource_type="manufacturing_routes",
                     resource_id=str(routing_id), details={"name": body.name},
                     request=request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        txn.rollback()
        logger.error(f"Error updating routing {routing_id}: {e}")
        raise HTTPException(**http_error(400, "routing_update_failed", request))
    finally:
        db.close()


@routing_router.get(
    "/{routing_id}/estimate",
    dependencies=[Depends(require_permission("manufacturing.routing_view"))],
)
def get_routing_estimate(
    routing_id: int,
    quantity: float = 1.0,
    current_user: dict = Depends(get_current_user),
):
    """Calculate total estimated time and labor cost for a routing at a given qty.

    Formula per operation:
      time = setup_time + cycle_time * quantity
      cost = (time / 60) * labor_rate_per_hour
    """
    db = get_db_connection(current_user.company_id)
    try:
        route = db.execute(
            text("SELECT id, name FROM manufacturing_routes WHERE id = :rid AND is_deleted = false"),
            {"rid": routing_id},
        ).fetchone()
        if not route:
            raise HTTPException(**http_error(404, ("routing_not_found", request)))

        ops = db.execute(
            text("""
                SELECT setup_time, cycle_time, labor_rate_per_hour
                FROM manufacturing_operations
                WHERE route_id = :rid AND is_deleted = false
            """),
            {"rid": routing_id},
        ).fetchall()

        total_setup = Decimal("0")
        total_run = Decimal("0")
        total_cost = Decimal("0")
        qty = Decimal(str(quantity))

        for op in ops:
            setup = Decimal(str(op.setup_time or 0))
            run = Decimal(str(op.cycle_time or 0)) * qty
            rate = Decimal(str(op.labor_rate_per_hour or 0))
            total_setup += setup
            total_run += run
            total_cost += ((setup + run) / Decimal("60")) * rate

        return {
            "routing_id": route.id,
            "routing_name": route.name,
            "total_setup_minutes": total_setup,
            "total_run_minutes": total_run,
            "total_time_minutes": total_setup + total_run,
            "total_labor_cost": round(total_cost, 4),
        }
    finally:
        db.close()
