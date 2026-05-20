from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Optional

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parties", tags=["Parties"])

@router.get("/customers", response_model=dict, dependencies=[Depends(require_permission(["parties.view", "sales.view"]))])
async def get_customers(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قائمة العملاء مع أرصدة حسب الفرع"""
    with transactional(current_user.company_id) as db:
        try:
            # Get base currency and branch currency
            base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
            branch_cur = base_cur
            if branch_id:
                branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
            
            # Subquery to get aggregated balance per party
            if branch_id:
                # When branch is selected: show balance in branch's local currency
                balance_subquery = """
                    SELECT ps.party_id,
                           COALESCE(SUM(psb.balance), 0) as total_balance,
                           psb.currency as balance_currency
                    FROM party_sites ps
                    LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                    WHERE psb.company_branch_id = :bid
                    GROUP BY ps.party_id, psb.currency
                """
                balance_params = {"bid": branch_id}
            else:
                # When all branches: show total in base currency
                balance_subquery = """
                    SELECT ps.party_id,
                           COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_balance,
                           :base_cur as balance_currency
                    FROM party_sites ps
                    LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                    LEFT JOIN currencies c ON psb.currency = c.code
                    GROUP BY ps.party_id
                """
                balance_params = {"base_cur": base_cur}

            query = f"""
                SELECT
                    p.id, p.name, p.name_en, p.email, p.phone, p.tax_number, p.address,
                    p.credit_limit,
                    CASE WHEN p.status = 'active' THEN true ELSE false END as is_active,
                    'customer' as party_type,
                    COALESCE(bal.total_balance, 0) as balance,
                    COALESCE(bal.balance_currency, :display_cur) as balance_currency,
                    ps_default.site_name as site_name,
                    ps_default.id as site_id
                FROM parties p
                LEFT JOIN party_sites ps_default ON ps_default.party_id = p.id AND ps_default.is_default = TRUE
                LEFT JOIN ({balance_subquery}) bal ON bal.party_id = p.id
                WHERE p.is_customer = true
            """
            params = {"limit": limit, "offset": offset, "display_cur": branch_cur, **balance_params}
            
            if search:
                query += " AND (p.name ILIKE :search OR p.phone LIKE :search)"
                params["search"] = f"%{search}%"
    
            # PTY-007: Enforce branch filtering
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND p.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

            query += " ORDER BY p.name ASC LIMIT :limit OFFSET :offset"
            
            result = db.execute(text(query), params)
            parties = []
            for row in result:
                 d = dict(row._mapping)
                 
                 # Determine display currency:
                 # - If branch_id specified: show in branch's local currency
                 # - If all branches: show in base currency (SAR)
                 display_currency = base_cur
                 if branch_id and d.get("balance_currency"):
                     display_currency = d["balance_currency"]
                 
                 d["display_currency"] = display_currency
                 d["balance"] = Decimal(str(d.get("balance") or 0))
                 d["balance_display"] = d["balance"]
                 
                 # Also provide SAR equivalent for "all branches" view
                 if d.get("balance_currency") and d["balance_currency"] != base_cur:
                     rate = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), 
                                     {"c": d["balance_currency"]}).scalar()
                     if rate:
                         d["balance_sar"] = float(d["balance"]) * float(rate)
                     else:
                         d["balance_sar"] = Decimal(str(d["balance"]))
                 else:
                     d["balance_sar"] = Decimal(str(d["balance"]))
                 
                 parties.append(d)
                 
            return {"items": parties}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/suppliers", response_model=dict, dependencies=[Depends(require_permission(["parties.view", "buying.view"]))])
async def get_suppliers(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قائمة الموردين مع أرصدة حسب الفرع"""
    with transactional(current_user.company_id) as db:
        try:
            # Get base currency and branch currency
            base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
            branch_cur = base_cur
            if branch_id:
                branch_cur = db.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": branch_id}).scalar() or base_cur
            
            # Subquery to get aggregated balance per party
            if branch_id:
                # When branch is selected: show balance in branch's local currency
                balance_subquery = """
                    SELECT ps.party_id,
                           COALESCE(SUM(psb.balance), 0) as total_balance,
                           psb.currency as balance_currency
                    FROM party_sites ps
                    LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                    WHERE psb.company_branch_id = :bid
                    GROUP BY ps.party_id, psb.currency
                """
                balance_params = {"bid": branch_id}
            else:
                # When all branches: show total in base currency
                balance_subquery = """
                    SELECT ps.party_id,
                           COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0) as total_balance,
                           :base_cur as balance_currency
                    FROM party_sites ps
                    LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
                    LEFT JOIN currencies c ON psb.currency = c.code
                    GROUP BY ps.party_id
                """
                balance_params = {"base_cur": base_cur}

            query = f"""
                SELECT
                    p.id, p.name, p.name_en, p.email, p.phone, p.tax_number, p.address,
                    p.credit_limit,
                    CASE WHEN p.status = 'active' THEN true ELSE false END as is_active,
                    'supplier' as party_type,
                    COALESCE(bal.total_balance, 0) as balance,
                    COALESCE(bal.balance_currency, :display_cur) as balance_currency,
                    ps_default.site_name as site_name,
                    ps_default.id as site_id
                FROM parties p
                LEFT JOIN party_sites ps_default ON ps_default.party_id = p.id AND ps_default.is_default = TRUE
                LEFT JOIN ({balance_subquery}) bal ON bal.party_id = p.id
                WHERE p.is_supplier = true
            """
            params = {"limit": limit, "offset": offset, "display_cur": branch_cur, **balance_params}
            
            if search:
                query += " AND (p.name ILIKE :search OR p.phone LIKE :search)"
                params["search"] = f"%{search}%"
    
            # PTY-007: Enforce branch filtering
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND p.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

            query += " ORDER BY p.name ASC LIMIT :limit OFFSET :offset"
            
            result = db.execute(text(query), params)
            parties = []
            for row in result:
                 d = dict(row._mapping)
                 
                 # Determine display currency:
                 # - If branch_id specified: show in branch's local currency
                 # - If all branches: show in base currency (SAR)
                 display_currency = base_cur
                 if branch_id and d.get("balance_currency"):
                     display_currency = d["balance_currency"]
                 
                 d["display_currency"] = display_currency
                 d["balance"] = Decimal(str(d.get("balance") or 0))
                 d["balance_display"] = d["balance"]
                 
                 # Also provide SAR equivalent for "all branches" view
                 if d.get("balance_currency") and d["balance_currency"] != base_cur:
                     rate = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), 
                                     {"c": d["balance_currency"]}).scalar()
                     if rate:
                         d["balance_sar"] = Decimal(str(d["balance"])) * float(rate)
                     else:
                         d["balance_sar"] = Decimal(str(d["balance"]))
                 else:
                     d["balance_sar"] = Decimal(str(d["balance"]))
                 
                 parties.append(d)
                 
            return {"items": parties}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get(
    "/duplicates-by-phone",
    response_model=dict,
    dependencies=[Depends(require_permission(["parties.view"]))],
)
async def find_duplicates_by_phone(
    phone: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """ابحث عن أطراف مكررة بنفس رقم الهاتف بعد إزالة الرموز/الفواصل.

    يستخدم العمود المُولَّد ``phone_clean`` (T7.3) المفهرس ببنية B-tree،
    لذا يبقى الاستعلام أقل من 100ms حتى على 100K طرف.
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return {"items": []}
    with transactional(current_user.company_id) as db:
        try:
            # phone_clean قد لا يكون موجوداً على قواعد قديمة لم تطبّق 0021 بعد؛
            # في تلك الحالة نتراجع إلى regexp_replace في الاستعلام (أبطأ).
            params = {"digits": digits, "limit": limit}
            try:
                result = db.execute(
                    text(
                        "SELECT id, name, name_en, phone, phone_clean, "
                        "  is_customer, is_supplier "
                        "FROM parties "
                        "WHERE phone_clean = :digits "
                        "ORDER BY name ASC LIMIT :limit"
                    ),
                    params,
                )
            except Exception:
                result = db.execute(
                    text(
                        "SELECT id, name, name_en, phone, "
                        "  regexp_replace(coalesce(phone,''), '\\D', '', 'g') "
                        "    AS phone_clean, "
                        "  is_customer, is_supplier "
                        "FROM parties "
                        "WHERE regexp_replace(coalesce(phone,''), '\\D', '', 'g') = :digits "
                        "ORDER BY name ASC LIMIT :limit"
                    ),
                    params,
                )
            return {"items": [dict(r._mapping) for r in result]}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
