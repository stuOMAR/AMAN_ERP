"""
AMAN ERP — Mobile API Router
Endpoints for mobile sync, dashboard, and device registration.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["Mobile"])


# ---------------------------------------------------------------------------
# Schemas (inline — small surface, keep co-located)
# ---------------------------------------------------------------------------

class SyncItem(BaseModel):
    entity_type: str = Field(..., max_length=50)
    entity_id: Optional[int] = None
    operation: str = Field(..., pattern=r"^(create|update)$")
    payload: dict = Field(default_factory=dict)
    device_timestamp: datetime


class SyncBatchRequest(BaseModel):
    device_id: str = Field(..., max_length=255)
    items: List[SyncItem]


class SyncResultItem(BaseModel):
    index: int
    status: str  # synced | conflict | error
    entity_id: Optional[int] = None
    message: Optional[str] = None
    server_version: Optional[dict] = None


class SyncBatchResponse(BaseModel):
    synced: int
    conflicts: int
    errors: int
    results: List[SyncResultItem]


class SyncStatusResponse(BaseModel):
    device_id: str
    pending: int
    conflicts: int
    last_sync: Optional[datetime] = None


class ConflictResolveRequest(BaseModel):
    sync_queue_id: int
    resolution: str = Field(..., pattern=r"^(keep_server|keep_device|merge)$")
    merged_payload: Optional[dict] = None


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(..., max_length=255)
    platform: str = Field(..., pattern=r"^(ios|android)$")
    fcm_token: str = Field(..., max_length=500)


class DashboardResponse(BaseModel):
    inventory_summary: dict
    pending_orders: int
    pending_approvals: int
    recent_quotations: list
    currency_code: str
    currency_symbol: str
    sales: float = 0
    expenses: float = 0
    profit: float = 0
    cash: float = 0
    total_customers: int = 0
    total_suppliers: int = 0
    total_invoices: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_company_id(current_user) -> str:
    cid = getattr(current_user, "company_id", None)
    if not cid:
        raise HTTPException(status_code=400, detail="company_id not available")
    return cid


# ---------------------------------------------------------------------------
# POST /mobile/sync  — Batch sync offline changes
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=SyncBatchResponse,
             dependencies=[Depends(require_permission("mobile.sync"))])
@limiter.limit("30/minute")
async def batch_sync(
    body: SyncBatchRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Sync a batch of offline changes from mobile device."""
    company_id = _get_company_id(current_user)
    user_id = current_user.id
    now = datetime.now(timezone.utc)

    synced = 0
    conflicts = 0
    errors = 0
    results: list[SyncResultItem] = []

    with transactional(company_id) as conn:
        with conn.begin():
            for idx, item in enumerate(body.items):
                try:
                    # Conflict detection: check if entity was modified after device_timestamp
                    conflict_detected = False
                    server_version = None

                    if item.operation == "update" and item.entity_id:
                        conflict_detected, server_version = _check_conflict(
                            conn, item.entity_type, item.entity_id, item.device_timestamp
                        )

                    if conflict_detected:
                        # Store in sync_queue as conflict
                        conn.execute(text("""
                            INSERT INTO sync_queue
                                (device_id, user_id, entity_type, entity_id, operation,
                                 payload, device_timestamp, server_timestamp, sync_status,
                                 conflict_resolution, created_at, updated_at)
                            VALUES
                                (:device_id, :user_id, :entity_type, :entity_id, :operation,
                                 :payload::jsonb, :device_ts, :now, 'conflict',
                                 :server_ver::jsonb, :now, :now)
                        """), {
                            "device_id": body.device_id, "user_id": user_id,
                            "entity_type": item.entity_type, "entity_id": item.entity_id,
                            "operation": item.operation,
                            "payload": _json_dumps(item.payload),
                            "device_ts": item.device_timestamp,
                            "now": now,
                            "server_ver": _json_dumps({"server": server_version, "device": item.payload}),
                        })
                        conflicts += 1
                        results.append(SyncResultItem(
                            index=idx, status="conflict",
                            entity_id=item.entity_id,
                            server_version=server_version,
                            message="Entity modified on server since device timestamp",
                        ))
                    else:
                        # Apply the change
                        applied_id = _apply_sync_item(conn, item, user_id)
                        # Record in sync_queue as synced
                        conn.execute(text("""
                            INSERT INTO sync_queue
                                (device_id, user_id, entity_type, entity_id, operation,
                                 payload, device_timestamp, server_timestamp, sync_status,
                                 created_at, updated_at)
                            VALUES
                                (:device_id, :user_id, :entity_type, :entity_id, :operation,
                                 :payload::jsonb, :device_ts, :now, 'synced', :now, :now)
                        """), {
                            "device_id": body.device_id, "user_id": user_id,
                            "entity_type": item.entity_type,
                            "entity_id": applied_id or item.entity_id,
                            "operation": item.operation,
                            "payload": _json_dumps(item.payload),
                            "device_ts": item.device_timestamp, "now": now,
                        })
                        synced += 1
                        results.append(SyncResultItem(
                            index=idx, status="synced", entity_id=applied_id or item.entity_id,
                        ))
                except Exception as exc:
                    logger.warning("Sync item %d failed: %s", idx, exc)
                    errors += 1
                    results.append(SyncResultItem(
                        index=idx, status="error", message="حدث خطأ أثناء المزامنة",
                    ))

    log_activity(
        user_id=user_id,
        username=getattr(current_user, "username", ""),
        action="mobile_batch_sync",
        resource_type="sync",
        details={"device_id": body.device_id, "synced": synced, "conflicts": conflicts, "errors": errors},
        request=request,
    )

    return SyncBatchResponse(synced=synced, conflicts=conflicts, errors=errors, results=results)


# ---------------------------------------------------------------------------
# GET /mobile/sync/status  — get sync status for device
# ---------------------------------------------------------------------------

@router.get("/sync/status", response_model=SyncStatusResponse,
            dependencies=[Depends(require_permission("mobile.sync"))])
async def sync_status(
    device_id: str,
    current_user=Depends(get_current_user),
):
    """Sync Status."""
    company_id = _get_company_id(current_user)
    with transactional(company_id) as conn:
        row = conn.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE sync_status = 'pending')  AS pending,
                COUNT(*) FILTER (WHERE sync_status = 'conflict') AS conflicts,
                MAX(server_timestamp) AS last_sync
            FROM sync_queue
            WHERE device_id = :did AND user_id = :uid
        """), {"did": device_id, "uid": current_user.id}).mappings().first()

    return SyncStatusResponse(
        device_id=device_id,
        pending=row["pending"] if row else 0,
        conflicts=row["conflicts"] if row else 0,
        last_sync=row["last_sync"] if row else None,
    )


# ---------------------------------------------------------------------------
# POST /mobile/sync/resolve  — resolve a sync conflict
# ---------------------------------------------------------------------------

@router.post("/sync/resolve",
             dependencies=[Depends(require_permission("mobile.sync"))], response_model=Dict[str, Any])
async def resolve_conflict(
    body: ConflictResolveRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Resolve Conflict."""
    company_id = _get_company_id(current_user)
    with transactional(company_id) as conn:
        with conn.begin():
            row = conn.execute(text("""
                SELECT id, entity_type, entity_id, payload, conflict_resolution, sync_status
                FROM sync_queue WHERE id = :sid AND user_id = :uid
            """), {"sid": body.sync_queue_id, "uid": current_user.id}).mappings().first()

            if not row:
                raise HTTPException(404, "Sync queue item not found")
            if row["sync_status"] != "conflict":
                raise HTTPException(400, "Item is not in conflict status")

            if body.resolution == "keep_server":
                # Just mark as resolved — server version already in DB
                pass
            elif body.resolution == "keep_device":
                # Apply device payload
                import json
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                _apply_sync_item_raw(conn, row["entity_type"], row["entity_id"], payload, current_user.id)
            elif body.resolution == "merge":
                if not body.merged_payload:
                    raise HTTPException(400, "merged_payload required for merge resolution")
                _apply_sync_item_raw(conn, row["entity_type"], row["entity_id"], body.merged_payload, current_user.id)

            conn.execute(text("""
                UPDATE sync_queue
                SET sync_status = 'resolved',
                    conflict_resolution = jsonb_set(
                        COALESCE(conflict_resolution, '{}'),
                        '{resolution}',
                        :res::jsonb
                    ),
                    updated_at = now()
                WHERE id = :sid
            """), {"sid": body.sync_queue_id, "res": f'"{body.resolution}"'})

    log_activity(
        user_id=current_user.id,
        username=getattr(current_user, "username", ""),
        action="mobile_resolve_conflict",
        resource_type="sync",
        resource_id=str(body.sync_queue_id),
        details={"resolution": body.resolution},
        request=request,
    )

    return {"status": "resolved", "resolution": body.resolution}


# ---------------------------------------------------------------------------
# GET /mobile/dashboard  — aggregated dashboard for mobile
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_model=DashboardResponse,
            dependencies=[Depends(require_permission("mobile.dashboard"))])
async def mobile_dashboard(current_user=Depends(get_current_user)):
    """Mobile Dashboard."""
    company_id = _get_company_id(current_user)
    with transactional(company_id) as conn:
        # Company currency settings
        currency_row = conn.execute(text("""
            SELECT setting_value
            FROM company_settings
            WHERE setting_key = 'default_currency'
            ORDER BY id DESC
            LIMIT 1
        """)).mappings().first()
        currency_code = (
            (currency_row["setting_value"] if currency_row else None)
            or "SAR"
        )
        currency_code = str(currency_code).upper()
        currency_symbol = {
            "SAR": "ر.س",
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "AED": "د.إ",
            "KWD": "د.ك",
            "QAR": "ر.ق",
            "BHD": "د.ب",
            "OMR": "ر.ع",
        }.get(currency_code, currency_code)

        # Inventory summary
        inv_row = conn.execute(text("""
            SELECT COUNT(DISTINCT p.id) AS total_products,
                   COALESCE(SUM(i.quantity), 0) AS total_stock
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
        """)).mappings().first()
        inventory_summary = {
            "total_products": inv_row["total_products"] if inv_row else 0,
            "total_stock": float(inv_row["total_stock"]) if inv_row else 0,
        }

        # Pending orders
        pending_orders_row = conn.execute(text("""
            SELECT COUNT(*) AS cnt FROM sales_orders WHERE status IN ('draft', 'confirmed')
        """)).mappings().first()
        pending_orders = pending_orders_row["cnt"] if pending_orders_row else 0

        # Pending approvals for current user
        pending_approvals_row = conn.execute(text("""
            SELECT COUNT(*) AS cnt FROM approval_requests
            WHERE current_approver_id = :uid AND status = 'pending'
        """), {"uid": current_user.id}).mappings().first()
        pending_approvals = pending_approvals_row["cnt"] if pending_approvals_row else 0

        # Recent quotations
        quot_rows = conn.execute(text("""
            SELECT sq.id, sq.sq_number, p.name AS customer_name,
                   sq.total AS total_amount, sq.status, sq.created_at
            FROM sales_quotations sq
            LEFT JOIN parties p ON p.id = sq.party_id
            ORDER BY sq.created_at DESC LIMIT 10
        """)).mappings().all()
        recent_quotations = [dict(r) for r in quot_rows]

        # Financial stats: sales = revenue, expenses, profit, cash
        sales = 0.0
        expenses = 0.0
        cash = 0.0
        try:
            rev_row = conn.execute(text("""
                SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS total
                FROM journal_lines jl
                JOIN accounts a ON jl.account_id = a.id
                JOIN journal_entries je ON jl.journal_entry_id = je.id AND je.status = 'posted'
                WHERE a.account_type = 'revenue'
            """)).mappings().first()
            sales = float(rev_row["total"]) if rev_row else 0.0

            exp_row = conn.execute(text("""
                SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS total
                FROM journal_lines jl
                JOIN accounts a ON jl.account_id = a.id
                JOIN journal_entries je ON jl.journal_entry_id = je.id AND je.status = 'posted'
                WHERE a.account_type = 'expense'
            """)).mappings().first()
            expenses = float(exp_row["total"]) if exp_row else 0.0

            # Cash from treasury accounts or BOX/BNK accounts
            cash_row = conn.execute(text("""
                SELECT COALESCE(SUM(a.balance), 0) AS total
                FROM accounts a
                WHERE a.id IN (
                    SELECT gl_account_id FROM treasury_accounts WHERE is_active = true
                    UNION
                    SELECT id FROM accounts WHERE account_code LIKE 'BOX%%' OR account_code LIKE 'BNK%%'
                )
            """)).mappings().first()
            cash = float(cash_row["total"]) if cash_row else 0.0
        except Exception:
            conn.rollback()  # reset transaction state after error

        profit = sales - expenses

        # Counts
        total_customers = 0
        total_suppliers = 0
        total_invoices = 0
        try:
            cust_row = conn.execute(text("""
                SELECT COUNT(*) AS cnt FROM parties
                WHERE party_type = 'customer' OR is_customer = true
            """)).mappings().first()
            total_customers = cust_row["cnt"] if cust_row else 0

            supp_row = conn.execute(text("""
                SELECT COUNT(*) AS cnt FROM parties WHERE is_supplier = true
            """)).mappings().first()
            total_suppliers = supp_row["cnt"] if supp_row else 0

            inv_cnt_row = conn.execute(text("""
                SELECT COUNT(*) AS cnt FROM invoices
            """)).mappings().first()
            total_invoices = inv_cnt_row["cnt"] if inv_cnt_row else 0
        except Exception:
            conn.rollback()

    return DashboardResponse(
        inventory_summary=inventory_summary,
        pending_orders=pending_orders,
        pending_approvals=pending_approvals,
        recent_quotations=recent_quotations,
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        sales=sales,
        expenses=expenses,
        profit=profit,
        cash=cash,
        total_customers=total_customers,
        total_suppliers=total_suppliers,
        total_invoices=total_invoices,
    )


# ---------------------------------------------------------------------------
# POST /mobile/register-device  — register device for push notifications
# ---------------------------------------------------------------------------

@router.post("/register-device", status_code=201,
             dependencies=[Depends(require_permission("mobile.sync"))], response_model=Dict[str, Any])
async def register_device(
    body: DeviceRegisterRequest,
    current_user=Depends(get_current_user),
):
    """Register Device."""
    company_id = _get_company_id(current_user)
    with transactional(company_id) as conn:
        with conn.begin():
            # NOTE: push_devices table must be created via Alembic migration,
            # not via DDL here.  The migration should include:
            #   CREATE TABLE push_devices ( ... UNIQUE(device_id, user_id) )
            # Upsert device registration into dedicated push_devices table
            conn.execute(text("""
                INSERT INTO push_devices
                    (device_id, user_id, platform, fcm_token, is_active, last_seen_at, created_at, updated_at)
                VALUES
                    (:device_id, :user_id, :platform, :fcm_token, TRUE, NOW(), NOW(), NOW())
                ON CONFLICT (device_id, user_id) DO UPDATE SET
                    fcm_token = EXCLUDED.fcm_token,
                    platform = EXCLUDED.platform,
                    is_active = TRUE,
                    last_seen_at = NOW(),
                    updated_at = NOW()
            """), {
                "device_id": body.device_id,
                "user_id": current_user.id,
                "platform": body.platform,
                "fcm_token": body.fcm_token,
            })

    return {"status": "registered", "device_id": body.device_id}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

import json as _json


def _json_dumps(obj) -> str:
    return _json.dumps(obj, default=str)


# Entity table mapping for conflict detection & sync application
_ENTITY_TABLE_MAP = {
    "quotation": {
        "table": "sales_quotations", "id_col": "id",
        "allowed_cols": {"quotation_number", "customer_id", "party_id", "quotation_date",
                         "valid_until", "subtotal", "tax_amount", "discount", "total",
                         "status", "notes", "branch_id", "currency"},
    },
    "sales_order": {
        "table": "sales_orders", "id_col": "id",
        "allowed_cols": {"so_number", "customer_id", "party_id", "order_date",
                         "subtotal", "tax_amount", "discount", "total",
                         "status", "notes", "branch_id", "currency"},
    },
    "approval": {
        "table": "approval_requests", "id_col": "id",
        "allowed_cols": {"status", "current_step", "notes", "description"},
    },
    "inventory_adjustment": {
        "table": "stock_adjustments", "id_col": "id",
        "allowed_cols": {"warehouse_id", "product_id", "quantity", "adjustment_type",
                         "reason", "notes", "status", "branch_id"},
    },
}

# Regex pattern for valid SQL column names (alphanumeric + underscore only)
import re
_VALID_COL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _check_conflict(conn, entity_type: str, entity_id: int, device_timestamp: datetime) -> tuple[bool, dict | None]:
    """Check if entity was modified on server after device_timestamp."""
    mapping = _ENTITY_TABLE_MAP.get(entity_type)
    if not mapping:
        return False, None

    table = mapping["table"]
    id_col = mapping["id_col"]

    row = conn.execute(text(f"""
        SELECT updated_at FROM {table} WHERE {id_col} = :eid
    """), {"eid": entity_id}).mappings().first()

    if not row:
        return False, None

    server_updated = row["updated_at"]
    if server_updated and server_updated > device_timestamp:
        # Fetch server version
        server_row = conn.execute(text(f"""
            SELECT * FROM {table} WHERE {id_col} = :eid
        """), {"eid": entity_id}).mappings().first()
        return True, {k: str(v) if v is not None else None for k, v in dict(server_row).items()} if server_row else None

    return False, None


def _apply_sync_item(conn, item: SyncItem, user_id: int) -> int | None:
    """Apply a single sync item (create or update) and return entity_id."""
    return _apply_sync_item_raw(conn, item.entity_type, item.entity_id, item.payload, user_id)


def _apply_sync_item_raw(conn, entity_type: str, entity_id: int | None, payload: dict, user_id: int) -> int | None:
    """Apply a sync change to the actual entity table."""
    mapping = _ENTITY_TABLE_MAP.get(entity_type)
    if not mapping:
        logger.warning("Unknown entity_type for sync: %s", entity_type)
        return entity_id

    table = mapping["table"]
    id_col = mapping["id_col"]
    allowed_cols = mapping.get("allowed_cols", set())

    # Filter payload to only include safe/known columns — prevents SQL injection
    # via malicious column names in the payload keys
    if entity_id and entity_type != "create":
        # UPDATE — set updated_at and updated_by
        safe_cols = {
            k: v for k, v in payload.items()
            if k not in ("id", "created_at", "created_by")
            and k in allowed_cols
            and _VALID_COL_RE.match(k)
        }
        if safe_cols:
            set_clause = ", ".join(f"{k} = :{k}" for k in safe_cols)
            safe_cols[id_col] = entity_id
            safe_cols["_user_id"] = user_id
            conn.execute(text(f"""
                UPDATE {table}
                SET {set_clause}, updated_at = now(), updated_by = :_user_id
                WHERE {id_col} = :{id_col}
            """), safe_cols)
        return entity_id
    else:
        # CREATE — use payload fields
        safe_cols = {
            k: v for k, v in payload.items()
            if k not in ("id", "created_at", "updated_at")
            and k in allowed_cols
            and _VALID_COL_RE.match(k)
        }
        safe_cols["created_by"] = str(user_id)
        safe_cols["updated_by"] = str(user_id)
        if safe_cols:
            col_names = ", ".join(safe_cols.keys())
            col_params = ", ".join(f":{k}" for k in safe_cols.keys())
            result = conn.execute(text(f"""
                INSERT INTO {table} ({col_names}, created_at, updated_at)
                VALUES ({col_params}, now(), now())
                RETURNING {id_col}
            """), safe_cols)
            row = result.first()
            return row[0] if row else None
        return None
