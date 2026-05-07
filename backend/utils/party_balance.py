"""
party_balance.py — Helper to update per-site, per-branch party balances.

Usage:
    from utils.party_balance import update_party_site_balance

    update_party_site_balance(db, party_id=4, site_id=2, branch_id=1, currency="SAR", amount=-92000)
    # Decreases supplier balance by 92,000 SAR in branch 1 for site 2
"""

from sqlalchemy import text


def update_party_site_balance(db, party_id: int, branch_id: int, currency: str, amount: float, account_type: str = None):
    """
    Update (or create) a party's balance for a specific site, branch and currency.

    Positive amount = party owes us more (customer debit / supplier credit increase)
    Negative amount = we owe party more (customer credit / supplier debit increase)

    For customers:
      - Invoice created: amount = +total (customer owes us)
      - Payment received: amount = -payment (reduces what they owe)

    For suppliers:
      - Invoice created: amount = -total (we owe supplier)
      - Payment made: amount = +payment (reduces what we owe)
    """
    # Find the default site for this party with matching currency
    site = db.execute(text("""
        SELECT id FROM party_sites 
        WHERE party_id = :pid AND currency = :cur AND is_active = TRUE
        ORDER BY is_default DESC LIMIT 1
    """), {"pid": party_id, "cur": currency}).fetchone()

    if not site:
        # Create a new site for this party/currency
        party = db.execute(text("SELECT name FROM parties WHERE id = :pid"), {"pid": party_id}).fetchone()
        site_name = f"{party.name} - {currency}" if party else f"Site {currency}"
        db.execute(text("""
            INSERT INTO party_sites (party_id, site_name, currency, is_default, is_active)
            VALUES (:pid, :name, :cur, FALSE, TRUE)
        """), {"pid": party_id, "name": site_name, "cur": currency})
        site = db.execute(text("SELECT LASTVAL() as id"), {}).fetchone()

    site_id = site.id

    # Determine account_type if not provided
    if not account_type:
        party = db.execute(text("""
            SELECT is_supplier, is_customer, party_type FROM parties WHERE id = :pid
        """), {"pid": party_id}).fetchone()
        if party and (party.is_supplier or party.party_type == 'supplier'):
            account_type = 'payable'
        else:
            account_type = 'receivable'

    # Upsert the balance
    db.execute(text("""
        INSERT INTO party_site_balances (company_branch_id, party_site_id, account_type, currency, balance, created_at, updated_at)
        VALUES (:bid, :sid, :at, :cur, :amt, NOW(), NOW())
        ON CONFLICT (company_branch_id, party_site_id, account_type, currency)
        DO UPDATE SET balance = party_site_balances.balance + :amt, updated_at = NOW()
    """), {"bid": branch_id, "sid": site_id, "at": account_type, "cur": currency, "amt": amount})


def get_party_balance(db, party_id: int, branch_id: int = None, currency: str = None) -> list:
    """
    Get party balances, optionally filtered by branch and/or currency.

    Returns list of dicts: [{site_id, site_name, branch_id, branch_name, currency, balance}, ...]
    """
    query = """
        SELECT ps.id as site_id, ps.site_name, ps.currency as site_currency,
               psb.company_branch_id, b.branch_name, psb.currency, psb.balance, psb.account_type
        FROM party_sites ps
        LEFT JOIN party_site_balances psb ON psb.party_site_id = ps.id
        LEFT JOIN branches b ON psb.company_branch_id = b.id
        WHERE ps.party_id = :pid AND ps.is_active = TRUE
    """
    params = {"pid": party_id}

    if branch_id:
        query += " AND (psb.company_branch_id = :bid OR psb.company_branch_id IS NULL)"
        params["bid"] = branch_id

    if currency:
        query += " AND ps.currency = :cur"
        params["cur"] = currency

    query += " ORDER BY ps.site_name, b.branch_name"

    rows = db.execute(text(query), params).fetchall()
    return [
        {
            "site_id": r.site_id,
            "site_name": r.site_name,
            "site_currency": r.site_currency,
            "branch_id": r.company_branch_id,
            "branch_name": r.branch_name,
            "currency": r.currency,
            "balance": float(r.balance) if r.balance is not None else 0,
            "account_type": r.account_type
        }
        for r in rows
    ]


def get_party_total_balance_sar(db, party_id: int, branch_id: int = None) -> float:
    """
    Get total balance in SAR (base currency) for a party, using current exchange rates.
    """
    query = """
        SELECT COALESCE(SUM(
            psb.balance * COALESCE(c.current_rate, 1)
        ), 0) as total_sar
        FROM party_site_balances psb
        JOIN party_sites ps ON psb.party_site_id = ps.id
        LEFT JOIN currencies c ON psb.currency = c.code
        WHERE ps.party_id = :pid
    """
    params = {"pid": party_id}

    if branch_id:
        query += " AND psb.company_branch_id = :bid"
        params["bid"] = branch_id

    result = db.execute(text(query), params).scalar()
    return float(result or 0)
