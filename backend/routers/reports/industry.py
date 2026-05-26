"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, Optional
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
_D2 = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(_D2, rounding=ROUND_HALF_UP)


def _pct(numerator, denominator) -> Decimal:
    return _q(Decimal(str(numerator if numerator is not None else 0)) / Decimal(str(denominator)) * 100)

def _period_params(from_date: Optional[date] = None, to_date: Optional[date] = None):
    """Return (from_date, to_date) defaulting to current month."""
    today = date.today()
    if not from_date:
        from_date = today.replace(day=1)
    if not to_date:
        to_date = today
    return from_date, to_date


def _gl_balance(db, account_prefix: str, from_date: date, to_date: date, side: str = "debit"):
    """Sum journal line debits/credits for accounts matching a category.

    Uses account_classifications when available, falling back to
    account_number LIKE for legacy compatibility.
    """
    col = "debit" if side == "debit" else "credit"

    # Map common prefixes to classifier categories
    _CATEGORY_MAP = {
        "51": ("expense", "cost_of_goods"),
        "41": ("revenue", "sales"),
        "6": ("expense", "operating"),
    }
    hint_key = _CATEGORY_MAP.get(account_prefix)

    if hint_key:
        try:
            cat, hint = hint_key
            acc_rows = db.execute(text("""
                SELECT account_id FROM account_classifications
                WHERE tenant_id = current_setting('app.tenant_id', true)::bigint
                  AND statement_category = :cat AND aggregation_hint = :hint
                  AND is_active = true
            """), {"cat": cat, "hint": hint}).fetchall()
            if acc_rows:
                acc_ids = [r[0] for r in acc_rows]
                row = db.execute(text(f"""
                    SELECT COALESCE(SUM(jl.{col}), 0) AS total
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.journal_entry_id
                    WHERE jl.account_id = ANY(:acc_ids)
                      AND je.entry_date BETWEEN :d1 AND :d2
                      AND je.status = 'posted'
                """), {"acc_ids": acc_ids, "d1": from_date, "d2": to_date}).fetchone()
                return Decimal(str(row.total)) if row else Decimal("0")
        except Exception:
            pass  # fall through to legacy

    # Legacy fallback: code-range check
    row = db.execute(text(f"""
        SELECT COALESCE(SUM(jl.{col}), 0) AS total
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE a.account_number LIKE :prefix
          AND je.entry_date BETWEEN :d1 AND :d2
          AND je.status = 'posted'
    """), {"prefix": f"{account_prefix}%", "d1": from_date, "d2": to_date}).fetchone()
    return Decimal(str(row.total)) if row else Decimal("0")


# ─── 1. Food Cost Report (FB - المطاعم) ───
@router.get("/industry/food-cost", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def food_cost_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة الطعام — نسبة تكلفة المواد إلى الإيرادات"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # تكلفة البضاعة المباعة (COGS) = حسابات 510xx
        cogs = _gl_balance(db, "510", d1, d2, "debit")
        # إيرادات المبيعات = حسابات 410xx
        revenue = _gl_balance(db, "410", d1, d2, "credit")
        # مشتريات المواد الغذائية = حسابات 510 (debit) كمؤشر إضافي
        # مصاريف التشغيل = حسابات 6xxxx
        operating_exp = _gl_balance(db, "6", d1, d2, "debit")

        food_cost_pct = _pct(cogs, revenue) if revenue > 0 else Decimal("0")
        gross_profit = revenue - cogs
        gross_margin = _pct(gross_profit, revenue) if revenue > 0 else Decimal("0")
        net_profit = gross_profit - operating_exp

        # Top 10 most-sold items
        top_items = db.execute(text("""
            SELECT p.product_name, p.product_name_en,
                   SUM(il.quantity) AS qty_sold,
                   SUM(il.total) AS total_revenue,
                   SUM(il.quantity * p.cost_price) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale','pos_invoice')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en
            ORDER BY total_revenue DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        items = []
        for r in top_items:
            row = dict(r._mapping)
            cost = Decimal(str(row.get("total_cost") or 0))
            rev  = Decimal(str(row.get("total_revenue") or 0))
            row["cost_pct"] = _pct(cost, rev) if rev > 0 else Decimal("0")
            items.append(row)

        return {
            "report_type": "food-cost",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "revenue": revenue,
                "cogs": cogs,
                "food_cost_pct": food_cost_pct,
                "gross_profit": gross_profit,
                "gross_margin_pct": gross_margin,
                "operating_expenses": operating_exp,
                "net_profit": net_profit,
            },
            "top_items": items,
        }
    except Exception as e:
        logger.error(f"Food cost report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 2. Production Cost Report (MF - التصنيع) ───
@router.get("/industry/production-cost", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def production_cost_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تكلفة الإنتاج — مقارنة التكلفة المخططة بالفعلية"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # أوامر الإنتاج في الفترة
        orders = db.execute(text("""
            SELECT po.id, po.order_number, po.status,
                   p.product_name, p.product_name_en,
                   po.quantity AS planned_qty,
                   po.produced_quantity,
                   po.scrapped_quantity,
                   (po.quantity * p.cost_price) AS planned_cost,
                   p.cost_price
            FROM production_orders po
            JOIN products p ON p.id = po.product_id
            WHERE (po.start_date BETWEEN :d1 AND :d2 OR po.due_date BETWEEN :d1 AND :d2)
            ORDER BY po.created_at DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        total_planned = Decimal("0")
        total_produced = Decimal("0")
        total_scrapped = Decimal("0")
        total_planned_cost = Decimal("0")
        order_list = []
        for r in orders:
            row = dict(r._mapping)
            total_planned += Decimal(str(row.get("planned_qty") or 0))
            total_produced += Decimal(str(row.get("produced_quantity") or 0))
            total_scrapped += Decimal(str(row.get("scrapped_quantity") or 0))
            total_planned_cost += Decimal(str(row.get("planned_cost") or 0))
            order_list.append(row)

        # تكلفة المواد الخام الفعلية من journal_lines (حسابات 510xx تصنيع)
        actual_material_cost = _gl_balance(db, "510", d1, d2, "debit")
        # مصاريف التصنيع غير المباشرة (حسابات 520xx)
        overhead_cost = _gl_balance(db, "520", d1, d2, "debit")

        efficiency = _pct(total_produced, total_planned) if total_planned > 0 else Decimal("0")
        scrap_rate = _pct(total_scrapped, total_produced + total_scrapped) if (total_produced + total_scrapped) > 0 else Decimal("0")
        variance = actual_material_cost - total_planned_cost
        variance_pct = _pct(variance, total_planned_cost) if total_planned_cost > 0 else Decimal("0")

        return {
            "report_type": "production-cost",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_orders": len(order_list),
                "planned_qty": total_planned,
                "produced_qty": total_produced,
                "scrapped_qty": total_scrapped,
                "efficiency_pct": efficiency,
                "scrap_rate_pct": scrap_rate,
                "planned_cost": total_planned_cost,
                "actual_material_cost": actual_material_cost,
                "overhead_cost": overhead_cost,
                "total_actual_cost": actual_material_cost + overhead_cost,
                "variance": variance,
                "variance_pct": variance_pct,
            },
            "orders": order_list[:20],
        }
    except Exception as e:
        logger.error(f"Production cost report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 3. Progress Billing Report (CN - المقاولات) ───
@router.get("/industry/progress-billing", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def progress_billing_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير مستخلصات المشاريع — نسبة الإنجاز والفواتير"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        projects = db.execute(text("""
            SELECT p.id, p.project_code, p.project_name, p.project_name_en,
                   p.status, p.planned_budget, p.actual_cost,
                   p.progress_percentage, p.contract_type,
                   p.start_date, p.end_date, p.customer_id,
                   COALESCE(exp_total.spent, 0) AS total_expenses
            FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) AS spent
                FROM project_expenses
                WHERE status != 'rejected'
                GROUP BY project_id
            ) exp_total ON exp_total.project_id = p.id
            WHERE p.status NOT IN ('cancelled')
            ORDER BY p.progress_percentage DESC
        """)).fetchall()

        project_list = []
        total_budget = 0
        total_invoiced = 0
        total_cost = 0
        for r in projects:
            row = dict(r._mapping)
            budget = Decimal(str(row.get("planned_budget") or 0))
            cost = Decimal(str(row.get("total_expenses") or 0)) or Decimal(str(row.get("actual_cost") or 0))
            # Use actual_cost as billed amount (represents invoiced work in progress billing)
            invoiced = Decimal(str(row.get("actual_cost") or 0))
            Decimal(str(row.get("progress_percentage") or 0))

            row["profit"] = invoiced - cost
            row["profit_margin_pct"] = _pct(row["profit"], invoiced) if invoiced > 0 else Decimal("0")
            row["billing_pct"] = _pct(invoiced, budget) if budget > 0 else Decimal("0")
            row["cost_pct"] = _pct(cost, budget) if budget > 0 else Decimal("0")

            total_budget += budget
            total_invoiced += invoiced
            total_cost += cost
            project_list.append(row)

        return {
            "report_type": "progress-billing",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_projects": len(project_list),
                "active_projects": sum(1 for p in project_list if p.get("status") == "in_progress"),
                "total_budget": total_budget,
                "total_invoiced": total_invoiced,
                "total_cost": total_cost,
                "overall_profit": total_invoiced - total_cost,
                "overall_billing_pct": _pct(total_invoiced, total_budget) if total_budget > 0 else Decimal("0"),
            },
            "projects": project_list,
        }
    except Exception as e:
        logger.error(f"Progress billing report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 4. Drug Expiry Report (PH - الصيدليات) ───
@router.get("/industry/drug-expiry", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def drug_expiry_report(
    days_ahead: int = 90,
    current_user: dict = Depends(get_current_user)
):
    """تقرير الأدوية/المنتجات قريبة الانتهاء"""
    db = get_db_connection(current_user.company_id)
    try:
        # INV-F4: normalize to UTC so cut-offs are deterministic regardless
        # of the server host timezone.
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=days_ahead)

        # من جدول product_batches
        batches = db.execute(text("""
            SELECT pb.batch_number, pb.expiry_date, pb.available_quantity,
                   pb.unit_cost,
                   p.product_name, p.product_name_en, p.product_code,
                   w.warehouse_name
            FROM product_batches pb
            JOIN products p ON p.id = pb.product_id
            LEFT JOIN warehouses w ON w.id = pb.warehouse_id
            WHERE pb.expiry_date IS NOT NULL
              AND pb.expiry_date <= :cutoff
              AND pb.available_quantity > 0
              AND pb.status = 'active'
            ORDER BY pb.expiry_date ASC
        """), {"cutoff": cutoff}).fetchall()

        expired = []
        expiring_30 = []
        expiring_60 = []
        expiring_90 = []
        total_value_at_risk = 0

        for r in batches:
            row = dict(r._mapping)
            exp_date = row.get("expiry_date")
            qty = Decimal(str(row.get("available_quantity") or 0))
            cost = Decimal(str(row.get("unit_cost") or 0))
            row["value_at_risk"] = _q(qty * cost)
            total_value_at_risk += row["value_at_risk"]

            if exp_date:
                days_left = (exp_date - today).days
                row["days_left"] = days_left
                if days_left <= 0:
                    row["urgency"] = "expired"
                    expired.append(row)
                elif days_left <= 30:
                    row["urgency"] = "critical"
                    expiring_30.append(row)
                elif days_left <= 60:
                    row["urgency"] = "warning"
                    expiring_60.append(row)
                else:
                    row["urgency"] = "notice"
                    expiring_90.append(row)

        all_items = expired + expiring_30 + expiring_60 + expiring_90

        return {
            "report_type": "drug-expiry",
            "as_of": str(today),
            "days_ahead": days_ahead,
            "summary": {
                "total_items": len(all_items),
                "expired_count": len(expired),
                "expiring_30_days": len(expiring_30),
                "expiring_60_days": len(expiring_60),
                "expiring_90_days": len(expiring_90),
                "total_value_at_risk": _q(total_value_at_risk),
            },
            "items": all_items[:50],
        }
    except Exception as e:
        logger.error(f"Drug expiry report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 5. Fleet Efficiency Report (LG - اللوجستيات) ───
@router.get("/industry/fleet-tracking", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def fleet_tracking_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير كفاءة الأسطول — أداء التوصيل والمركبات"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # بيانات التوصيل حسب المركبة
        vehicles = db.execute(text("""
            SELECT vehicle_number,
                   driver_name,
                   COUNT(*) AS total_deliveries,
                   COUNT(CASE WHEN status = 'delivered' THEN 1 END) AS completed,
                   COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
                   SUM(total_quantity) AS total_qty,
                   MIN(delivery_date) AS first_delivery,
                   MAX(delivery_date) AS last_delivery
            FROM delivery_orders
            WHERE delivery_date BETWEEN :d1 AND :d2
              AND vehicle_number IS NOT NULL AND vehicle_number != ''
            GROUP BY vehicle_number, driver_name
            ORDER BY total_deliveries DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        vehicle_list = []
        total_deliveries = 0
        total_completed = 0
        for r in vehicles:
            row = dict(r._mapping)
            completed = int(row.get("completed") or 0)
            total = int(row.get("total_deliveries") or 0)
            row["completion_rate"] = _pct(completed, total) if total > 0 else Decimal("0")
            total_deliveries += total
            total_completed += completed
            vehicle_list.append(row)

        # ملخص عام
        overall = db.execute(text("""
            SELECT COUNT(*) AS total,
                   COUNT(CASE WHEN status = 'delivered' THEN 1 END) AS delivered,
                   COUNT(CASE WHEN status = 'in_transit' THEN 1 END) AS in_transit,
                   COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled,
                   COUNT(DISTINCT vehicle_number) AS vehicles_used,
                   COUNT(DISTINCT driver_name) AS drivers_used,
                   AVG(EXTRACT(EPOCH FROM (delivered_at - shipped_at))/3600) AS avg_delivery_hours
            FROM delivery_orders
            WHERE delivery_date BETWEEN :d1 AND :d2
        """), {"d1": d1, "d2": d2}).fetchone()

        summary = dict(overall._mapping) if overall else {}
        summary["on_time_rate"] = _pct(total_completed, total_deliveries) if total_deliveries > 0 else Decimal("0")

        return {
            "report_type": "fleet-tracking",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": summary,
            "vehicles": vehicle_list,
        }
    except Exception as e:
        logger.error(f"Fleet tracking report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 6. Utilization Report (SV - الخدمات المهنية) ───
@router.get("/industry/utilization", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def utilization_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير معدل الاستغلال — ساعات مفوترة مقابل ساعات متاحة"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # ساعات من project_tasks
        tasks = db.execute(text("""
            SELECT e.id AS employee_id,
                   COALESCE(e.first_name || ' ' || e.last_name, 'غير محدد') AS employee_name,
                   SUM(pt.actual_hours) AS billable_hours,
                   SUM(pt.planned_hours) AS planned_hours,
                   COUNT(pt.id) AS tasks_count,
                   COUNT(CASE WHEN pt.status = 'completed' THEN 1 END) AS completed_tasks
            FROM project_tasks pt
            LEFT JOIN employees e ON e.id = pt.assigned_to
            WHERE (pt.start_date BETWEEN :d1 AND :d2 OR pt.end_date BETWEEN :d1 AND :d2)
            GROUP BY e.id, e.first_name, e.last_name
            ORDER BY billable_hours DESC NULLS LAST
        """), {"d1": d1, "d2": d2}).fetchall()

        # عدد أيام العمل في الفترة (تقريبي: 22 يوم/شهر * 8 ساعات)
        work_days = max(1, (d2 - d1).days * 5 // 7)
        available_hours_per_person = work_days * 8

        employee_list = []
        total_billable = 0
        total_planned = 0
        for r in tasks:
            row = dict(r._mapping)
            billable = Decimal(str(row.get("billable_hours") or 0))
            row["available_hours"] = available_hours_per_person
            row["utilization_pct"] = _pct(billable, available_hours_per_person) if available_hours_per_person > 0 else Decimal("0")
            total_billable += billable
            total_planned += Decimal(str(row.get("planned_hours") or 0))
            employee_list.append(row)

        # إيراد الخدمات
        svc_revenue = _gl_balance(db, "410", d1, d2, "credit")
        svc_expenses = _gl_balance(db, "6", d1, d2, "debit")
        effective_rate = _q(svc_revenue / total_billable) if total_billable > 0 else Decimal("0")

        return {
            "report_type": "utilization",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_employees": len(employee_list),
                "total_billable_hours": total_billable,
                "total_planned_hours": total_planned,
                "avg_utilization_pct": _pct(total_billable, available_hours_per_person * max(len(employee_list), 1)) if employee_list else Decimal("0"),
                "service_revenue": svc_revenue,
                "effective_hourly_rate": effective_rate,
                "operating_expenses": svc_expenses,
                "net_profit": svc_revenue - svc_expenses,
            },
            "employees": employee_list[:20],
        }
    except Exception as e:
        logger.error(f"Utilization report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 7. Workshop Revenue Report (WK - الورش) ───
@router.get("/industry/workshop-revenue", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def workshop_revenue_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير إيرادات الورشة — حسب نوع الخدمة"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # إيرادات حسب المنتج/الخدمة
        by_service = db.execute(text("""
            SELECT COALESCE(p.product_name, il.description, 'أخرى') AS service_name,
                   COALESCE(p.product_name_en, il.description, 'Other') AS service_name_en,
                   p.product_type,
                   COUNT(DISTINCT i.id) AS job_count,
                   SUM(il.quantity) AS total_qty,
                   SUM(il.total) AS total_revenue,
                   SUM(il.quantity * COALESCE(p.cost_price, 0)) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            LEFT JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale', 'pos_invoice')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_type, il.description
            ORDER BY total_revenue DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        service_list = []
        total_revenue = 0
        total_cost = 0
        total_jobs = 0
        for r in by_service:
            row = dict(r._mapping)
            rev = Decimal(str(row.get("total_revenue") or 0))
            cost = Decimal(str(row.get("total_cost") or 0))
            row["margin"] = rev - cost
            row["margin_pct"] = _pct(rev - cost, rev) if rev > 0 else Decimal("0")
            total_revenue += rev
            total_cost += cost
            total_jobs += int(row.get("job_count") or 0)
            service_list.append(row)

        # قطع الغيار المستخدمة (product_type = 'product')
        parts_count = sum(1 for s in service_list if s.get("product_type") == "product")
        services_count = sum(1 for s in service_list if s.get("product_type") == "service")

        return {
            "report_type": "workshop-revenue",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_jobs": total_jobs,
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "gross_profit": total_revenue - total_cost,
                "gross_margin_pct": _pct(total_revenue - total_cost, total_revenue) if total_revenue > 0 else Decimal("0"),
                "parts_items": parts_count,
                "service_items": services_count,
                "avg_job_value": _q(total_revenue / total_jobs) if total_jobs > 0 else Decimal("0"),
            },
            "services": service_list[:20],
        }
    except Exception as e:
        logger.error(f"Workshop revenue report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 8. E-Commerce Returns Report (EC - التجارة الإلكترونية) ───
@router.get("/industry/ecom-returns", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def ecom_returns_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المرتجعات — نسبة المرتجعات وأسبابها"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # إجمالي المبيعات
        sales = db.execute(text("""
            SELECT COUNT(*) AS sale_count, COALESCE(SUM(total), 0) AS sale_total
            FROM invoices
            WHERE invoice_type IN ('sale', 'pos_invoice')
              AND invoice_date BETWEEN :d1 AND :d2
              AND status != 'cancelled'
        """), {"d1": d1, "d2": d2}).fetchone()
        sale_count = int(sales.sale_count) if sales else 0
        sale_total = Decimal(str(sales.sale_total)) if sales else 0

        # مبيعات مرتجعة
        returns = db.execute(text("""
            SELECT COUNT(*) AS return_count, COALESCE(SUM(total), 0) AS return_total
            FROM sales_returns
            WHERE return_date BETWEEN :d1 AND :d2
              AND status != 'cancelled'
        """), {"d1": d1, "d2": d2}).fetchone()
        return_count = int(returns.return_count) if returns else 0
        return_total = Decimal(str(returns.return_total or 0)) if returns else Decimal("0")

        return_rate = _pct(return_count, sale_count) if sale_count > 0 else Decimal("0")
        value_return_rate = _pct(return_total, sale_total) if sale_total > 0 else Decimal("0")

        # أكثر المنتجات مرتجعاً
        top_returns = db.execute(text("""
            SELECT p.product_name, p.product_name_en, p.product_code,
                   SUM(srl.quantity) AS returned_qty,
                   SUM(srl.total) AS return_value,
                   COUNT(DISTINCT sr.id) AS return_count
            FROM sales_return_lines srl
            JOIN sales_returns sr ON sr.id = srl.return_id
            LEFT JOIN products p ON p.id = srl.product_id
            WHERE sr.return_date BETWEEN :d1 AND :d2
              AND sr.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_code
            ORDER BY return_value DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        return {
            "report_type": "ecom-returns",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_sales": sale_count,
                "total_sales_value": sale_total,
                "total_returns": return_count,
                "total_return_value": return_total,
                "return_rate_pct": return_rate,
                "value_return_rate_pct": value_return_rate,
                "net_sales": sale_total - return_total,
            },
            "top_returned_products": [dict(r._mapping) for r in top_returns],
        }
    except Exception as e:
        logger.error(f"E-com returns report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 9. Agent Performance Report (WS - الجملة) ───
@router.get("/industry/agent-performance", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def agent_performance_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير أداء الوكلاء/المناديب — مبيعات لكل مندوب/عميل"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # مبيعات حسب المندوب (created_by)
        by_agent = db.execute(text("""
            SELECT cu.username AS agent_name,
                   cu.full_name AS agent_full_name,
                   COUNT(i.id) AS invoice_count,
                   COALESCE(SUM(i.total), 0) AS total_sales,
                   COALESCE(SUM(i.paid_amount), 0) AS total_collected,
                   COUNT(DISTINCT i.party_id) AS customer_count
            FROM invoices i
            JOIN company_users cu ON cu.id = i.created_by
            WHERE i.invoice_type IN ('sale')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY cu.id, cu.username, cu.full_name
            ORDER BY total_sales DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        agent_list = []
        grand_total = 0
        for r in by_agent:
            row = dict(r._mapping)
            sales = Decimal(str(row.get("total_sales") or 0))
            collected = Decimal(str(row.get("total_collected") or 0))
            row["collection_rate_pct"] = _pct(collected, sales) if sales > 0 else Decimal("0")
            row["avg_invoice_value"] = _q(sales / max(int(row.get("invoice_count") or 1), 1))
            grand_total += sales
            agent_list.append(row)

        # حساب النسبة من الإجمالي
        for agent in agent_list:
            agent["share_pct"] = _pct(agent.get("total_sales") or 0, grand_total) if grand_total > 0 else Decimal("0")

        # أكبر العملاء
        top_customers = db.execute(text("""
            SELECT pa.name AS customer_name, pa.name_en AS customer_name_en,
                   COUNT(i.id) AS order_count,
                   COALESCE(SUM(i.total), 0) AS total_value
            FROM invoices i
            JOIN parties pa ON pa.id = i.party_id
            WHERE i.invoice_type = 'sale'
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY pa.id, pa.name, pa.name_en
            ORDER BY total_value DESC
            LIMIT 10
        """), {"d1": d1, "d2": d2}).fetchall()

        return {
            "report_type": "agent-performance",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_agents": len(agent_list),
                "grand_total_sales": grand_total,
                "avg_sales_per_agent": _q(grand_total / max(len(agent_list), 1)),
            },
            "agents": agent_list,
            "top_customers": [dict(r._mapping) for r in top_customers],
        }
    except Exception as e:
        logger.error(f"Agent performance report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── 10. Crop Yield Report (AG - الزراعة) ───
@router.get("/industry/crop-yield", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def crop_yield_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير إنتاجية المحاصيل — المنتجات الزراعية مقابل التكاليف"""
    d1, d2 = _period_params(from_date, to_date)
    db = get_db_connection(current_user.company_id)
    try:
        # مبيعات المنتجات (= حصاد)
        harvests = db.execute(text("""
            SELECT p.product_name, p.product_name_en, p.product_code,
                   SUM(il.quantity) AS total_qty_sold,
                   SUM(il.total) AS total_revenue,
                   p.cost_price,
                   SUM(il.quantity * p.cost_price) AS total_cost
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN products p ON p.id = il.product_id
            WHERE i.invoice_type IN ('sale')
              AND i.invoice_date BETWEEN :d1 AND :d2
              AND i.status != 'cancelled'
            GROUP BY p.id, p.product_name, p.product_name_en, p.product_code, p.cost_price
            ORDER BY total_revenue DESC
        """), {"d1": d1, "d2": d2}).fetchall()

        crop_list = []
        total_revenue = 0
        total_cost = 0
        for r in harvests:
            row = dict(r._mapping)
            rev = Decimal(str(row.get("total_revenue") or 0))
            cost = Decimal(str(row.get("total_cost") or 0))
            row["profit"] = rev - cost
            row["margin_pct"] = _pct(rev - cost, rev) if rev > 0 else Decimal("0")
            total_revenue += rev
            total_cost += cost
            crop_list.append(row)

        # تكاليف زراعية من GL (مصاريف 6xxxx)
        agri_expenses = _gl_balance(db, "6", d1, d2, "debit")
        # مشتريات مستلزمات (5xxxx)
        input_costs = _gl_balance(db, "5", d1, d2, "debit")

        return {
            "report_type": "crop-yield",
            "period": {"from": str(d1), "to": str(d2)},
            "summary": {
                "total_crops": len(crop_list),
                "total_revenue": total_revenue,
                "total_direct_cost": total_cost,
                "gross_profit": total_revenue - total_cost,
                "gross_margin_pct": _pct(total_revenue - total_cost, total_revenue) if total_revenue > 0 else Decimal("0"),
                "total_operating_expenses": agri_expenses,
                "total_input_costs": input_costs,
                "net_farm_income": total_revenue - input_costs - agri_expenses,
            },
            "crops": crop_list[:20],
        }
    except Exception as e:
        logger.error(f"Crop yield report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
