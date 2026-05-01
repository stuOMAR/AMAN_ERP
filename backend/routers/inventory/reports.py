"""
Inventory Module - Reports (Summary, Warehouse Stock, Movements, Valuation)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

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
        if branch_id:
            prod_count_query = """
                SELECT COUNT(DISTINCT p.id) FROM products p
                JOIN inventory i ON p.id = i.product_id
                JOIN warehouses w ON i.warehouse_id = w.id
                WHERE w.branch_id = :branch_id AND i.quantity > 0
            """
            prod_count_params["branch_id"] = branch_id
        else:
            # INV-R01: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                prod_count_query = f"""
                    SELECT COUNT(DISTINCT p.id) FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    JOIN warehouses w ON i.warehouse_id = w.id
                    WHERE w.branch_id IN ({branch_placeholders}) AND i.quantity > 0
                """
                for i, bid in enumerate(allowed):
                    prod_count_params[f"_ab_{i}"] = bid
            else:
                prod_count_query = "SELECT COUNT(*) FROM products"

        product_count = db.execute(text(prod_count_query), prod_count_params).scalar() or 0

        # 2. Total Inventory Value (Cost * Qty)
        val_query = """
            SELECT COALESCE(SUM(p.cost_price * i.quantity), 0)
            FROM products p
            JOIN inventory i ON p.id = i.product_id
        """
        val_params = {}

        # 3. Low Stock Items
        low_query_join = "LEFT JOIN inventory i ON p.id = i.product_id"
        low_where = ""
        low_params = {}

        if branch_id:
            val_query += " JOIN warehouses w ON i.warehouse_id = w.id WHERE w.branch_id = :bid"
            val_params["bid"] = branch_id

            low_query_join = """
                LEFT JOIN inventory i ON p.id = i.product_id 
                AND i.warehouse_id IN (SELECT id FROM warehouses WHERE branch_id = :bid)
            """
            low_params["bid"] = branch_id

        inventory_value = db.execute(text(val_query), val_params).scalar() or 0

        low_stock_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT p.id
                FROM products p
                {low_query_join}
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
        """
        reserved_params = {}
        if branch_id:
            reserved_query += """ 
                JOIN warehouses w ON i.warehouse_id = w.id
                WHERE i.reserved_quantity > 0 AND w.branch_id = :bid
            """
            reserved_params["bid"] = branch_id
        else:
            reserved_query += " WHERE i.reserved_quantity > 0"

        reserved_query += " GROUP BY p.product_name"

        reserved_data = db.execute(text(reserved_query), reserved_params).fetchall()
        reserved_stock = [{"product": row.product_name, "quantity": int(row.reserved_qty)} for row in reserved_data]

        return {
            "product_count": product_count,
            "inventory_value": inventory_value,
            "low_stock_count": low_stock_count,
            "reserved_stock": reserved_stock
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
        if branch_id:
            query += " AND w.branch_id = :branch_id"
            params['branch_id'] = branch_id
        else:
            # INV-R01: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND w.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

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

        if branch_id:
            query += " AND w.branch_id = :branch_id"
            params['branch_id'] = branch_id
        else:
            # INV-R01: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND w.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

        if item_name:
            query += " AND (p.product_name ILIKE :item OR p.product_code ILIKE :item)"
            params['item'] = f"%{item_name}%"

        if warehouse and warehouse.strip():
            query += " AND t.warehouse_id = :warehouse"
            params['warehouse'] = int(warehouse)

        if transaction_type:
            types = {
                'purchase_in': ['purchase_in'],
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="تعذّر جلب حركات المخزون"
        )
    finally:
        db.close()


@reports_router.get("/valuation-report", response_model=List[dict], dependencies=[Depends(require_permission(["stock.view", "stock.reports"]))])
def get_valuation_report(
    branch_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تقييم المخزون (الكمية * التكلفة المتحركة)"""
    company_id = current_user.company_id if not isinstance(current_user, dict) else current_user.get("company_id")
    db = get_db_connection(company_id)
    try:
        query = """
            SELECT 
                p.id, p.product_code as code, p.product_name as name,
                u.unit_name as unit, 
                p.cost_price as moving_avg_cost,
                cat.category_name,
                SUM(i.quantity) as total_quantity,
                SUM(i.quantity * p.cost_price) as total_valuation
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            JOIN warehouses w ON i.warehouse_id = w.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            LEFT JOIN product_categories cat ON p.category_id = cat.id
            WHERE p.product_type = 'product'
        """

        params = {}
        if branch_id:
            query += " AND w.branch_id = :bid"
            params["bid"] = branch_id
        else:
            # INV-R01: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND w.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid
        if warehouse_id:
            query += " AND w.id = :wid"
            params["wid"] = warehouse_id

        query += " GROUP BY p.id, u.unit_name, cat.category_name, p.product_code, p.product_name, p.cost_price ORDER BY total_valuation DESC"

        result = db.execute(text(query), params).fetchall()

        return [
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "unit": r.unit,
                "category": r.category_name,
                "quantity": str(r.total_quantity or 0),
                "cost": str(r.moving_avg_cost or 0),
                "valuation": str(r.total_valuation or 0)
            }
            for r in result
        ]
    finally:
        db.close()
