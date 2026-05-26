"""
Party Sites API endpoints.
Manage sites/locations of parties (customers/suppliers).
"""
from fastapi import Request, APIRouter, Depends, HTTPException
from sqlalchemy import text
from typing import Optional
from pydantic import BaseModel
from utils.tx import transactional
from utils.permissions import require_permission
from routers.auth import get_current_user
from utils.i18n import http_error, i18n_message
from decimal import Decimal

router = APIRouter(prefix="/party-sites", tags=["Party Sites"])


class PartySiteCreate(BaseModel):
    party_id: int
    site_name: str
    site_name_en: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    currency: str = "SAR"
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    tax_number: Optional[str] = None
    bank_account: Optional[str] = None
    payment_terms: int = 30
    is_default: bool = False


@router.get("", dependencies=[Depends(require_permission(["parties.view", "buying.view", "sales.view"]))])
def list_party_sites(
    party_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """List party sites, optionally filtered by party_id."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        query = """
            SELECT ps.*, p.name as party_name
            FROM party_sites ps
            JOIN parties p ON ps.party_id = p.id
            WHERE ps.is_active = TRUE
        """
        params = {}

        if party_id:
            query += " AND ps.party_id = :pid"
            params["pid"] = party_id

        query += " ORDER BY p.name, ps.is_default DESC, ps.site_name"

        rows = db.execute(text(query), params).fetchall()
        return [
            {
                "id": r.id,
                "party_id": r.party_id,
                "party_name": r.party_name,
                "site_name": r.site_name,
                "site_name_en": r.site_name_en,
                "country": r.country,
                "country_code": r.country_code,
                "currency": r.currency,
                "contact_name": r.contact_name,
                "phone": r.phone,
                "email": r.email,
                "address": r.address,
                "city": r.city,
                "tax_number": r.tax_number,
                "bank_account": r.bank_account,
                "payment_terms": r.payment_terms,
                "is_default": r.is_default,
                "is_active": r.is_active,
            }
            for r in rows
        ]


@router.get("/{site_id}", dependencies=[Depends(require_permission(["parties.view", "buying.view", "sales.view"]))])
def get_party_site(request: Request, 
    site_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific party site."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        row = db.execute(text("""
            SELECT ps.*, p.name as party_name
            FROM party_sites ps
            JOIN parties p ON ps.party_id = p.id
            WHERE ps.id = :sid
        """), {"sid": site_id}).fetchone()

        if not row:
            raise HTTPException(**http_error(404, "party_site_not_found", request))

        # Get balances
        balances = db.execute(text("""
            SELECT psb.company_branch_id, b.branch_name, psb.account_type, psb.currency, psb.balance
            FROM party_site_balances psb
            JOIN branches b ON psb.company_branch_id = b.id
            WHERE psb.party_site_id = :sid
        """), {"sid": site_id}).fetchall()

        return {
            "id": row.id,
            "party_id": row.party_id,
            "party_name": row.party_name,
            "site_name": row.site_name,
            "site_name_en": row.site_name_en,
            "country": row.country,
            "country_code": row.country_code,
            "currency": row.currency,
            "contact_name": row.contact_name,
            "phone": row.phone,
            "email": row.email,
            "address": row.address,
            "city": row.city,
            "tax_number": row.tax_number,
            "bank_account": row.bank_account,
            "payment_terms": row.payment_terms,
            "is_default": row.is_default,
            "is_active": row.is_active,
            "balances": [
                {
                    "branch_id": b.company_branch_id,
                    "branch_name": b.branch_name,
                    "account_type": b.account_type,
                    "currency": b.currency,
                    "balance": Decimal(str(b.balance))
                }
                for b in balances
            ]
        }


@router.post("", dependencies=[Depends(require_permission(["parties.manage", "buying.edit", "sales.edit"]))])
def create_party_site(request: Request, 
    data: PartySiteCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new party site."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        # Verify party exists
        party = db.execute(text("SELECT id FROM parties WHERE id = :pid"), {"pid": data.party_id}).fetchone()
        if not party:
            raise HTTPException(**http_error(404, "party_not_found", request))

        result = db.execute(text("""
            INSERT INTO party_sites (party_id, site_name, site_name_en, country, country_code, currency,
                contact_name, phone, email, address, city, tax_number, bank_account, payment_terms, is_default, is_active)
            VALUES (:pid, :name, :name_en, :country, :cc, :cur, :contact, :phone, :email, :addr, :city, :tax, :bank, :terms, :def, TRUE)
            RETURNING id
        """), {
            "pid": data.party_id, "name": data.site_name, "name_en": data.site_name_en,
            "country": data.country, "cc": data.country_code, "cur": data.currency,
            "contact": data.contact_name, "phone": data.phone, "email": data.email,
            "addr": data.address, "city": data.city, "tax": data.tax_number,
            "bank": data.bank_account, "terms": data.payment_terms, "def": data.is_default
        })
        site_id = result.fetchone()[0]

        # Update default_site_id if this is the default
        if data.is_default:
            db.execute(text("UPDATE parties SET default_site_id = :sid WHERE id = :pid"),
                      {"sid": site_id, "pid": data.party_id})

        db.commit()
        return {"id": site_id, "message": i18n_message("site_created", request)}


@router.put("/{site_id}", dependencies=[Depends(require_permission(["parties.manage", "buying.edit", "sales.edit"]))])
def update_party_site(request: Request, 
    site_id: int,
    data: PartySiteCreate,
    current_user: dict = Depends(get_current_user)
):
    """Update a party site."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        db.execute(text("""
            UPDATE party_sites SET
                site_name = :name, site_name_en = :name_en, country = :country, country_code = :cc,
                currency = :cur, contact_name = :contact, phone = :phone, email = :email,
                address = :addr, city = :city, tax_number = :tax, bank_account = :bank,
                payment_terms = :terms, is_default = :def, updated_at = NOW()
            WHERE id = :sid
        """), {
            "sid": site_id, "name": data.site_name, "name_en": data.site_name_en,
            "country": data.country, "cc": data.country_code, "cur": data.currency,
            "contact": data.contact_name, "phone": data.phone, "email": data.email,
            "addr": data.address, "city": data.city, "tax": data.tax_number,
            "bank": data.bank_account, "terms": data.payment_terms, "def": data.is_default
        })
        db.commit()
        return {"message": i18n_message("site_updated_success", request)}
