
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, require_module
from utils.audit import log_activity
from utils.limiter import limiter
from utils.tx import transactional


from services.costing_service import CostingService

from schemas.costing_policies import CostingPolicySet, CostingPolicyHistoryResponse
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/costing-policies", tags=["Costing Policies"], dependencies=[Depends(require_module("costing"))])

@router.get("/current", dependencies=[Depends(require_permission("settings.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_current_policy(request: Request, current_user: dict = Depends(get_current_user)):
    """Get the currently active costing policy"""
    db = get_db_connection(current_user.company_id)
    try:
        policy = db.execute(text("""
            SELECT policy_type, policy_name, is_active, created_at, description 
            FROM costing_policies 
            WHERE is_active = TRUE 
            LIMIT 1
        """)).fetchone()
        
        if not policy:
            return {
                "policy_type": "global_wac", 
                "policy_name": "Global WAC (Default)", 
                "is_active": True,
                "description": "Default system policy"
            }
            
        return dict(policy._mapping)
    finally:
        db.close()

@router.post("/set", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def set_costing_policy(request: Request, policy_data: CostingPolicySet, current_user: dict = Depends(get_current_user)):
    """Change the costing policy with impact analysis"""
    if policy_data.policy_type not in ['global_wac', 'per_warehouse_wac', 'hybrid', 'smart']:
        raise HTTPException(**http_error(400, "invalid_policy_type", request))
        
    with transactional(current_user.company_id) as db:
        try:
            # 1. Get current active policy
            current_policy = db.execute(text("SELECT policy_type FROM costing_policies WHERE is_active = TRUE LIMIT 1")).scalar()
        
            if current_policy == policy_data.policy_type:
                 return {"message": i18n_message("policy_already_set", request), "status": "no_change"}
             
            # 2. PERFORM IMPACT ANALYSIS (V2)
            impact = CostingService.validate_policy_switch(db, policy_data.policy_type)
        
            # 3. Deactivate old
            db.execute(text("UPDATE costing_policies SET is_active = FALSE WHERE is_active = TRUE"))
        
            # 4. Insert New
            new_name = {
                'global_wac': 'Global WAC',
                'per_warehouse_wac': 'Per-Warehouse WAC',
                'hybrid': 'Hybrid Costing',
                'smart': 'Smart Costing'
            }.get(policy_data.policy_type, 'Unknown Policy')
        
            db.execute(text("""
            INSERT INTO costing_policies (policy_name, policy_type, description, is_active, created_by)
            VALUES (:name, :type, :desc, TRUE, :user)
        """), {
                "name": new_name,
                "type": policy_data.policy_type,
                "desc": f"Policy changed to {new_name}",
                "user": current_user.id
            })
        
            # 5. Log History with Impact (V2)
            db.execute(text("""
            INSERT INTO costing_policy_history 
            (old_policy_type, new_policy_type, changed_by, reason, affected_products_count, total_cost_impact, status)
            VALUES (:old, :new, :user, :reason, :count, :impact, 'completed')
        """), {
                "old": current_policy,
                "new": policy_data.policy_type,
                "user": current_user.id,
                "reason": policy_data.reason,
                "count": impact["affected_products_count"],
                "impact": impact["total_cost_impact"]
            })
        
            # 6. MIGRATION LOGIC
            if current_policy == 'global_wac' and policy_data.policy_type == 'per_warehouse_wac':
                 db.execute(text("""
                UPDATE inventory 
                SET average_cost = p.cost_price, 
                    policy_version = 2,
                    last_costing_update = CURRENT_TIMESTAMP
                FROM products p 
                WHERE inventory.product_id = p.id AND (inventory.average_cost = 0 OR inventory.average_cost IS NULL)
             """))
        
            # 7. Create Full System Snapshot (V2)
            CostingService.create_snapshot(db)

            # 8. Audit log
            try:
                log_activity(
                    db,
                    user_id=current_user.id,
                    username=getattr(current_user, 'username', 'system'),
                    action="switch_costing_policy",
                    resource_type="costing_policies",
                    resource_id=str(policy_data.policy_type),
                    details={
                        "old_policy": current_policy,
                        "new_policy": policy_data.policy_type,
                        "affected_products": impact["affected_products_count"],
                        # F-NEW-097 (R-FLOAT-MONEY, Req 8.5): the audit-log
                        # ``cost_impact`` is a money aggregate; persist it as a
                        # canonical Decimal-string instead of demoting to float.
                        "cost_impact": str(impact["total_cost_impact"]) if impact["total_cost_impact"] else "0",
                    }
                )
            except Exception:
                logger.warning("Failed to log costing policy change activity")
             
            return {"message": i18n_message("policy_updated_to", request), "status": "success", "impact": impact}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/history", response_model=List[CostingPolicyHistoryResponse], dependencies=[Depends(require_permission("settings.view"))])
@limiter.limit("200/minute")
def get_policy_history(request: Request, current_user: dict = Depends(get_current_user)):
    """Get history of policy changes with impact metrics"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT h.*, u.full_name as changed_by_name
            FROM costing_policy_history h
            LEFT JOIN company_users u ON h.changed_by = u.id
            ORDER BY h.change_date DESC
        """)).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()
