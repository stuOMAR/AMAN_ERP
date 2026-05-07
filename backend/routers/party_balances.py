"""
Party Balance API endpoints.
Provides per-branch, per-currency balance views for customers and suppliers.
Uses party_sites and party_site_balances tables.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from typing import Optional
from utils.tx import transactional
from utils.permissions import require_permission, resolve_branch_scope
from routers.auth import get_current_user

router = APIRouter(prefix="/party-balances", tags=["Party Balances"])


@router.get("/{party_id}", dependencies=[Depends(require_permission(["sales.view", "purchases.view"]))])
def get_party_balance_detail(
    party_id: int,
    branch_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Get per-site, per-branch balance for a party."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        party = db.execute(text("SELECT id, name, party_type FROM parties WHERE id = :pid"), {"pid": party_id}).fetchone()
        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT ps.id as site_id, ps.site_name, ps.currency as site_currency,
                   psb.company_branch_id, b.branch_name, psb.account_type, psb.currency, psb.balance
            FROM party_sites ps
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            LEFT JOIN branches b ON psb.company_branch_id = b.id
            WHERE ps.party_id = :pid AND ps.is_active = TRUE
        """
        params = {"pid": party_id}

        if branch_id:
            query += " AND (psb.company_branch_id = :bid OR psb.company_branch_id IS NULL)"
            params["bid"] = branch_id

        query += " ORDER BY ps.site_name, b.branch_name"
        rows = db.execute(text(query), params).fetchall()

        # Group by site
        sites = {}
        total_sar = 0
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        
        for r in rows:
            if r.site_id not in sites:
                sites[r.site_id] = {
                    "site_id": r.site_id,
                    "site_name": r.site_name,
                    "currency": r.site_currency,
                    "balances": []
                }
            if r.balance is not None:
                bal = float(r.balance)
                sites[r.site_id]["balances"].append({
                    "branch_id": r.company_branch_id,
                    "branch_name": r.branch_name,
                    "account_type": r.account_type,
                    "currency": r.currency,
                    "balance": bal
                })
                # Convert to SAR for total
                if r.currency and r.currency != base_cur:
                    rate = db.execute(text("SELECT current_rate FROM currencies WHERE code = :c"), {"c": r.currency}).scalar()
                    total_sar += bal * float(rate or 1)
                else:
                    total_sar += bal

        return {
            "party_id": party_id,
            "party_name": party.name,
            "party_type": party.party_type,
            "sites": list(sites.values()),
            "total_sar": total_sar
        }


@router.get("/summary/customers", dependencies=[Depends(require_permission("sales.view"))])
def get_customers_balance_summary(
    branch_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Get balance summary for all customers, optionally filtered by branch."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT 
                p.id, p.name,
                ps.id as site_id, ps.site_name, ps.currency as site_currency,
                psb.company_branch_id, b.branch_name,
                psb.balance, psb.currency as balance_currency
            FROM party_sites ps
            JOIN parties p ON ps.party_id = p.id
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            LEFT JOIN branches b ON psb.company_branch_id = b.id
            WHERE (p.is_customer = TRUE OR p.party_type = 'customer')
            AND (psb.balance IS NULL OR psb.balance > 0)
        """
        params = {}

        if branch_id:
            query += " AND (psb.company_branch_id = :bid OR psb.company_branch_id IS NULL)"
            params["bid"] = branch_id
        elif branch_scope:
            allowed_ids = branch_scope.get("branch_ids", [])
            if allowed_ids:
                query += " AND (psb.company_branch_id = ANY(:aids) OR psb.company_branch_id IS NULL)"
                params["aids"] = allowed_ids

        query += " ORDER BY p.name, ps.site_name"

        rows = db.execute(text(query), params).fetchall()

        return {
            "items": [
                {
                    "customer_id": r.id,
                    "customer_name": r.name,
                    "site_id": r.site_id,
                    "site_name": r.site_name,
                    "branch_id": r.company_branch_id,
                    "branch_name": r.branch_name,
                    "currency": r.balance_currency or r.site_currency,
                    "balance": float(r.balance or 0)
                }
                for r in rows
            ]
        }


@router.get("/summary/suppliers", dependencies=[Depends(require_permission("purchases.view"))])
def get_suppliers_balance_summary(
    branch_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Get balance summary for all suppliers, optionally filtered by branch."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        branch_scope = resolve_branch_scope(current_user, branch_id)

        query = """
            SELECT 
                p.id, p.name,
                ps.id as site_id, ps.site_name, ps.currency as site_currency,
                psb.company_branch_id, b.branch_name,
                psb.balance, psb.currency as balance_currency
            FROM party_sites ps
            JOIN parties p ON ps.party_id = p.id
            LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
            LEFT JOIN branches b ON psb.company_branch_id = b.id
            WHERE (p.is_supplier = TRUE OR p.party_type = 'supplier')
            AND (psb.balance IS NULL OR psb.balance < 0)
        """
        params = {}

        if branch_id:
            query += " AND (psb.company_branch_id = :bid OR psb.company_branch_id IS NULL)"
            params["bid"] = branch_id
        elif branch_scope:
            allowed_ids = branch_scope.get("branch_ids", [])
            if allowed_ids:
                query += " AND (psb.company_branch_id = ANY(:aids) OR psb.company_branch_id IS NULL)"
                params["aids"] = allowed_ids

        query += " ORDER BY p.name, ps.site_name"

        rows = db.execute(text(query), params).fetchall()

        return {
            "items": [
                {
                    "supplier_id": r.id,
                    "supplier_name": r.name,
                    "site_id": r.site_id,
                    "site_name": r.site_name,
                    "branch_id": r.company_branch_id,
                    "branch_name": r.branch_name,
                    "currency": r.balance_currency or r.site_currency,
                    "balance": float(r.balance or 0)
                }
                for r in rows
            ]
        }
