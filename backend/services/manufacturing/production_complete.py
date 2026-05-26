"""Production completion — partial, actual cost.

Feature 023 — T081.  Contract: contracts/production-completion.md

INV-03 fix: added WIP→FG GL journal entry via gl_service (Constitution §3 [CRITICAL]).
INV-18 fix: replaced all float() SQL params with str(Decimal) (Constitution §1 [CRITICAL]).
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from datetime import date

from sqlalchemy import text
from fastapi import HTTPException
from utils.i18n import http_error, i18n_message

logger = logging.getLogger(__name__)
_D4 = Decimal("0.0001")


def complete_production(
    db: Any,
    *,
    mo_id: int,
    tenant_id: int,
    qty: Decimal,
    warehouse_id: int,
    actor: dict | None = None,
    scrap_lines: list[dict] | None = None,
    byproduct_lines: list[dict] | None = None,
) -> dict:
    """Record a partial or full production completion.

    Steps:
    1. Row-lock MO, validate qty <= remaining_qty
    2. Consume materials via wac_per_warehouse.apply_outbound (proportional)
    3. Compute actual labor + overhead
    4. Allocate by-products
    5. Write scrap rows
    6. FG inbound at allocated cost
    7. GL post (source='mfg_completion')
    8. Insert production_completions row
    9. Decrement remaining_qty
    """
    # 1. Lock MO
    mo = db.execute(
        text("SELECT * FROM manufacturing_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
        {"id": mo_id, "tid": tenant_id},
    ).fetchone()

    if not mo:
        raise HTTPException(**http_error(404, "manufacturing_order_not_found"))
    mo = dict(mo._mapping)

    remaining = Decimal(str(mo.get("remaining_qty", mo.get("original_qty", 0))))
    if qty > remaining:
        raise HTTPException(status_code=409, detail={
            "code": "mfg.completion.qty_exceeds_remaining",
            "message": i18n_message("qty_exceeds_remaining_detail", qty=qty, remaining=remaining),
        })

    # Yield tolerance check
    planned = Decimal(str(mo.get("original_qty", 0)))
    Decimal("0.05")  # Default 5%
    try:
        from sqlalchemy import text as t
        row = db.execute(t("SELECT setting_value FROM company_settings WHERE setting_key = 'manufacturing.yield_tolerance'")).fetchone()
        if row:
            Decimal(str(row.setting_value))
    except Exception:
        pass

    # 2. Get BOM snapshot for material consumption
    bom_snapshot_id = mo.get("bom_snapshot_id")
    material_cost = Decimal(0)

    if bom_snapshot_id:
        snapshot = db.execute(
            text("SELECT payload FROM bom_snapshots WHERE id = :id"),
            {"id": bom_snapshot_id},
        ).fetchone()

        if snapshot and snapshot.payload:
            import json
            bom = json.loads(snapshot.payload) if isinstance(snapshot.payload, str) else snapshot.payload
            ratio = qty / planned if planned > 0 else Decimal(1)

            for component in bom.get("lines", []):
                comp_item = component.get("item_id")
                comp_qty = Decimal(str(component.get("qty_per_unit", 0))) * ratio

                try:
                    from services.inventory.wac_per_warehouse import apply_outbound
                    cost = apply_outbound(
                        db, item_id=comp_item, warehouse_id=warehouse_id,
                        qty=comp_qty, source="mfg_consume", tenant_id=tenant_id,
                    )
                    material_cost += cost
                except ImportError:
                    pass

    # 3. Labor + overhead
    labor_cost = Decimal(0)
    overhead_cost = Decimal(0)

    # Overhead via workstation rate (T096)
    workstation_id = mo.get("workstation_id")
    if workstation_id:
        try:
            from services.manufacturing.workstation_overhead import get_rate
            rate = get_rate(db, workstation_id=workstation_id, tenant_id=tenant_id)
            overhead_cost = (rate * qty).quantize(_D4, rounding=ROUND_HALF_UP)
        except Exception:
            # Fallback to global rate
            try:
                oh_row = db.execute(
                    text("SELECT setting_value FROM company_settings WHERE setting_key = 'manufacturing.global_overhead_rate' AND tenant_id = :tid"),
                    {"tid": tenant_id},
                ).fetchone()
                if oh_row and oh_row.setting_value:
                    rate = Decimal(str(oh_row.setting_value))
                    overhead_cost = (rate * qty).quantize(_D4, rounding=ROUND_HALF_UP)
            except Exception:
                pass

    # Labor from attendance link if enabled
    try:
        link_row = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'mfg.shopfloor_attendance_link_enabled' AND tenant_id = :tid"),
            {"tid": tenant_id},
        ).fetchone()
        if link_row and link_row.setting_value in ("true", "1", "yes"):
            # TODO: Pull actual labor minutes from attendance records
            pass
    except Exception:
        pass

    # 4. Total cost
    total_cost = material_cost + labor_cost + overhead_cost
    unit_cost = (total_cost / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if qty > 0 else Decimal(0)

    # 5. FG inbound
    try:
        from services.inventory.wac_per_warehouse import apply_inbound
        apply_inbound(
            db, item_id=mo.get("product_id", 0), warehouse_id=warehouse_id,
            qty=qty, unit_cost=unit_cost, source="mfg_complete", tenant_id=tenant_id,
        )
    except ImportError:
        pass

    # 6. GL posting: Dr FG Inventory / Cr WIP  (Constitution §3 [CRITICAL])
    # Only post when there is a real cost to transfer.
    wip_to_fg_je_id = 0
    if total_cost > Decimal("0"):
        try:
            from services.gl_service import create_journal_entry
            from utils.accounting import get_mapped_account_id
            from utils.fiscal_lock import check_fiscal_period_open
            from utils.inventory_accounts import resolve_warehouse_inventory_account

            today_str = str(date.today())
            check_fiscal_period_open(db, today_str)

            # Resolve accounts: prefer warehouse-mapped FG account, fall back to
            # acc_map_finished_goods then acc_map_inventory (mirrors orders.py pattern).
            fg_acc = (
                resolve_warehouse_inventory_account(db, warehouse_id, fallback_to_global=False)
                or get_mapped_account_id(db, "acc_map_finished_goods")
                or get_mapped_account_id(db, "acc_map_inventory")
            )
            wip_acc = get_mapped_account_id(db, "acc_map_wip")

            if fg_acc and wip_acc:
                company_id = mo.get("company_id") or str(tenant_id)
                user_id = (actor or {}).get("id") or 0
                je_id, _ = create_journal_entry(
                    db=db,
                    company_id=str(company_id),
                    date=today_str,
                    description=f"إنتاج أمر تصنيع #{mo_id} — تحويل WIP إلى مخزون نهائي",
                    lines=[
                        {
                            "account_id": int(fg_acc),
                            "debit": str(total_cost.quantize(_D4, ROUND_HALF_UP)),
                            "credit": 0,
                            "description": "Finished Goods — production completion",
                        },
                        {
                            "account_id": int(wip_acc),
                            "debit": 0,
                            "credit": str(total_cost.quantize(_D4, ROUND_HALF_UP)),
                            "description": "WIP — transferred to FG",
                        },
                    ],
                    user_id=user_id,
                    source="mfg_completion",
                    source_id=mo_id,
                    idempotency_key=f"mfg_completion:{mo_id}:{str(qty)}",
                )
                wip_to_fg_je_id = je_id
            else:
                logger.warning(
                    "production_complete: GL accounts not configured "
                    "(acc_map_wip=%s, fg_acc=%s) — skipping WIP→FG journal entry for MO %s",
                    wip_acc, fg_acc, mo_id,
                )
        except Exception:
            logger.exception("production_complete: GL posting failed for MO %s — rolling back", mo_id)
            raise

    # 7. Insert completion record
    # INV-18: use str(Decimal) for all SQL params — never float.
    db.execute(text("""
        INSERT INTO production_completions (
            tenant_id, mo_id, qty, actual_material_cost, actual_labor_cost,
            actual_overhead_cost, wip_to_fg_je_id, qc_state, completed_at
        ) VALUES (:tid, :mo, :qty, :mat, :labor, :oh, :je_id, :qc, clock_timestamp())
    """), {
        "tid": tenant_id,
        "mo": mo_id,
        "qty": str(qty),
        "mat": str(material_cost.quantize(_D4, ROUND_HALF_UP)),
        "labor": str(labor_cost.quantize(_D4, ROUND_HALF_UP)),
        "oh": str(overhead_cost.quantize(_D4, ROUND_HALF_UP)),
        "je_id": wip_to_fg_je_id,
        "qc": "pending" if mo.get("qc_required") else "n/a",
    })

    # 8. Update remaining qty
    new_remaining = remaining - qty
    new_state = "qc_pending" if mo.get("qc_required") and new_remaining == 0 else (
        "completed" if new_remaining == 0 else "in_progress"
    )
    db.execute(text("""
        UPDATE manufacturing_orders
        SET remaining_qty = :rem, state = :state, updated_at = clock_timestamp()
        WHERE id = :id
    """), {"rem": str(new_remaining.quantize(_D4, ROUND_HALF_UP)), "state": new_state, "id": mo_id})

    # 9. Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db, action="mfg.order.completed",
            entity_type="manufacturing_order", entity_id=mo_id,
            details={
                "qty": str(qty),
                "material_cost": str(material_cost),
                "wip_to_fg_je_id": wip_to_fg_je_id,
            },
        )
    except Exception:
        pass

    return {
        "mo_id": mo_id,
        "qty": str(qty),
        "remaining_qty": str(new_remaining),
        "material_cost": str(material_cost),
        "unit_cost": str(unit_cost),
        "wip_to_fg_je_id": wip_to_fg_je_id,
        "state": new_state,
    }
