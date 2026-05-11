"""
Inventory Module - Reports (Summary, Warehouse Stock, Movements, Valuation)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter, require_permission

reports_router = APIRouter()
logger = logging.getLogger(__name__)


@reports_router.get("/summary", response_model=dict, dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def get_inventory_summary(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب ملخص إحصائيات المخزون"""
    db = get_db_connection(current_user.company_id)
    try:
        # 1. Total Products
        prod_count_params = {}
        prod_count_filter = branch_scope_filter(current_user, branch_id, "w.branch_id", prod_count_params, branch_param="bid")
        prod_count_query = f"""
            SELECT COUNT(DISTINCT p.id) FROM products p
            JOIN inventory i ON p.id = i.product_id
            JOIN warehouses w ON i.warehouse_id = w.id
            WHERE i.quantity > 0 {prod_count_filter}
        """

        product_count = db.execute(text(prod_count_query), prod_count_params).scalar() or 0

        # 2. Total Inventory Value (Cost * Qty)
        val_query = """
            SELECT COALESCE(SUM(p.cost_price * i.quantity), 0)
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            JOIN warehouses w ON i.warehouse_id = w.id
            WHERE 1=1
        """
        val_params = {}

        # 3. Low Stock Items
        low_query_join = """
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN warehouses w ON i.warehouse_id = w.id
        """
        low_params = {}
        low_where = branch_scope_filter(current_user, branch_id, "w.branch_id", low_params, branch_param="bid")

        val_query += " " + branch_scope_filter(current_user, branch_id, "w.branch_id", val_params, branch_param="bid")

        inventory_value = db.execute(text(val_query), val_params).scalar() or 0

        low_stock_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT p.id
                FROM products p
                {low_query_join}
                WHERE 1=1 {low_where}
                GROUP BY p.id
                HAVING COALESCE(SUM(i.quantity), 0) < COALESCE(MAX(p.reorder_level), 0)
            ) AS subquery
        """

        low_stock_count = db.execute(text(low_stock_sql), low_params).scalar() or 0

        # 4. Reserved Stock Items
        reserved_query = """
            SELECT p.product_name, SUM(i.reserved_quantity) as reserved_qty
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            JOIN warehouses w ON i.warehouse_id = w.id
            WHERE i.reserved_quantity > 0
        """
        reserved_params = {}
        reserved_query += " " + branch_scope_filter(current_user, branch_id, "w.branch_id", reserved_params, branch_param="bid")

        reserved_query += " GROUP BY p.product_name"

        reserved_data = db.execute(text(reserved_query), reserved_params).fetchall()
        reserved_stock = [{"product": row.product_name, "quantity": int(row.reserved_qty)} for row in reserved_data]

        # Get base currency and convert to branch currency
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        display_cur = base_cur
        convert_rate = 1.0

        if branch_id:
            branch_cur = db.execute(text(
                "SELECT default_currency FROM branches WHERE id = :bid"
            ), {"bid": branch_id}).scalar()
            if branch_cur and branch_cur != base_cur:
                rate_val = db.execute(text(
                    "SELECT current_rate FROM currencies WHERE code = :c"
                ), {"c": branch_cur}).scalar()
                if rate_val and rate_val > 0:
                    display_cur = branch_cur
                    convert_rate = float(rate_val)

        # Convert inventory value to display currency
        if convert_rate != 1.0:
            inventory_value = float(inventory_value) / convert_rate

        return {
            "product_count": product_count,
            "inventory_value": round(inventory_value, 2),
            "low_stock_count": low_stock_count,
            "reserved_stock": reserved_stock,
            "currency": display_cur
        }
    finally:
        db.close()


@reports_router.get("/warehouse-stock", response_model=List[dict], dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def get_warehouse_stock(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب كميات المنتجات في كل مستودع"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT 
                w.warehouse_name as warehouse,
                p.product_name as item_name,
                p.product_code as item_code,
                u.unit_name as unit,
                i.quantity
            FROM inventory i
            JOIN products p ON i.product_id = p.id
            JOIN warehouses w ON i.warehouse_id = w.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE 1=1
        """
        params = {}
        query += " " + branch_scope_filter(current_user, branch_id, "w.branch_id", params)

        query += " ORDER BY w.warehouse_name, p.product_name"

        result = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error fetching warehouse stock: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@reports_router.get("/movements", dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))], response_model=List[Dict[str, Any]])
def get_stock_movements(
    request: Request,
    item_name: Optional[str] = None,
    warehouse: Optional[str] = None,
    branch_id: Optional[int] = None,
    transaction_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب سجل حركات المخزون"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT t.id, t.created_at, t.transaction_type, CONCAT(t.reference_type, ' #', t.reference_id) as reference_document,
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   t.quantity,
                   u.full_name as user_name
            FROM inventory_transactions t
            JOIN products p ON t.product_id = p.id
            JOIN warehouses w ON t.warehouse_id = w.id
            LEFT JOIN company_users u ON t.created_by = u.id
            WHERE 1=1
        """
        params = {}
        query += " " + branch_scope_filter(current_user, branch_id, "w.branch_id", params)

        if item_name:
            query += " AND (p.product_name ILIKE :item OR p.product_code ILIKE :item)"
            params['item'] = f"%{item_name}%"

        if warehouse and warehouse.strip():
            query += " AND t.warehouse_id = :warehouse"
            params['warehouse'] = int(warehouse)

        if transaction_type:
            # T038: Include all purchase-related transaction types
            from utils.inventory_constants import TX_PURCHASE_RECEIPT, TX_PURCHASE_INVOICE, TX_PURCHASE_RETURN
            types = {
                'purchase_in': [TX_PURCHASE_RECEIPT, TX_PURCHASE_INVOICE, TX_PURCHASE_RETURN],
                'purchase_receipt': [TX_PURCHASE_RECEIPT],
                'purchase_invoice': [TX_PURCHASE_INVOICE],
                'purchase_return': [TX_PURCHASE_RETURN],
                'sales_out': ['sales_out'],
                'transfer': ['transfer_in', 'transfer_out'],
                'adjustment': ['adjustment_in', 'adjustment_out'],
                'shipment': ['shipment_in', 'shipment_out']
            }
            if transaction_type in types:
                query += " AND t.transaction_type = ANY(:types)"
                params['types'] = types[transaction_type]

        if start_date:
            query += " AND t.created_at >= :start"
            params['start'] = start_date

        if end_date:
            query += " AND t.created_at <= :end"
            params['end'] = end_date

        query += " ORDER BY t.created_at DESC LIMIT 200"

        result = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in result]

    except Exception:
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Error fetching stock movements")
        raise HTTPException(**http_error(500, "inventory_movements_fetch_failed", request))
    finally:
        db.close()


@reports_router.get("/valuation-report", response_model=List[dict], dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def get_valuation_report(
    branch_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تقييم المخزون — T064: uses CostingService.calculate_inventory_valuation"""
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        from services.costing_service import CostingService
        from utils.permissions import validate_branch_access

        # T066: Validate branch access for explicit warehouse_id filters
        if warehouse_id:
            wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).scalar()
            if wh_branch:
                validate_branch_access(current_user, wh_branch)

        # T064: Use CostingService for valuation
        branch_ids = None
        if branch_id:
            branch_ids = [branch_id]
        elif hasattr(current_user, 'allowed_branches'):
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_ids = allowed

        valuation = CostingService.calculate_inventory_valuation(
            db,
            warehouse_id=warehouse_id,
            branch_id=branch_id,
            branch_ids=branch_ids,
        )

        # Also get selling price data for the response
        sell_query = """
            SELECT p.id, p.product_code as code, p.product_name as name,
                   u.unit_name as unit, cat.category_name,
                   SUM(i.quantity) as total_quantity,
                   p.selling_price
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            JOIN warehouses w ON i.warehouse_id = w.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            LEFT JOIN product_categories cat ON p.category_id = cat.id
            WHERE p.product_type = 'product'
        """
        sell_params = {}
        if warehouse_id:
            sell_query += " AND w.id = :wid"
            sell_params["wid"] = warehouse_id
        elif branch_ids:
            sell_query += " AND w.branch_id = ANY(:bids)"
            sell_params["bids"] = branch_ids

        sell_query += " GROUP BY p.id, u.unit_name, cat.category_name, p.product_code, p.product_name, p.selling_price"
        sell_rows = db.execute(text(sell_query), sell_params).fetchall()
        sell_map = {}
        for r in sell_rows:
            sell_map[r.id] = {
                "code": r.code, "name": r.name, "unit": r.unit,
                "category": r.category_name,
                "selling_price": float(r.selling_price or 0),
                "total_quantity": float(r.total_quantity or 0),
            }

        items = []
        for item in valuation.get("items", []):
            pid = item["product_id"]
            sell_info = sell_map.get(pid, {})
            qty = item["total_quantity"]
            cost_price = item["weighted_avg_cost"]
            selling_price = sell_info.get("selling_price", 0)
            items.append({
                "id": pid,
                "code": sell_info.get("code", ""),
                "name": item["product_name"],
                "unit": sell_info.get("unit", ""),
                "category": sell_info.get("category", ""),
                "quantity": str(qty),
                "cost": str(cost_price),
                "valuation": str(item["total_value"]),
                "selling_price": str(selling_price),
                "total_value_sell": str(qty * selling_price),
            })

        return items
    finally:
        db.close()
