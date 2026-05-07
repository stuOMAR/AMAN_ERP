#!/usr/bin/env python3
"""
Balance Reconciliation Script
Verifies that cached balances match their source-of-truth sub-ledgers:
  1. accounts.balance == SUM(debit-credit) FROM journal_lines WHERE status='posted'
  2. treasury_accounts.current_balance == linked accounts.balance (converted to treasury currency)
  3. party_site_balances == SUM(debit-credit) FROM party_transactions (per site/branch/currency)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from config import settings

def get_company_dbs():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT database_name FROM system_companies WHERE status = 'active'")).fetchall()
    engine.dispose()
    dbs = []
    for r in rows:
        db_name = r[0]
        url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/" + db_name
        try:
            e = create_engine(url)
            with e.connect() as c:
                c.execute(text("SELECT 1"))
            dbs.append((db_name, url))
            e.dispose()
        except Exception:
            pass
    return dbs


def check_account_balances(conn, fix=False):
    """Check accounts.balance vs SUM from journal_lines (posted entries only)"""
    rows = conn.execute(text("""
        SELECT a.id, a.account_number, a.name,
               COALESCE(a.balance, 0) AS cached_balance,
               COALESCE(gl.computed, 0) AS computed_balance
        FROM accounts a
        LEFT JOIN (
            SELECT jl.account_id,
                   SUM(jl.debit - jl.credit) AS computed
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.status = 'posted'
            GROUP BY jl.account_id
        ) gl ON gl.account_id = a.id
        WHERE ABS(COALESCE(a.balance, 0) - COALESCE(gl.computed, 0)) > 0.01
        ORDER BY ABS(COALESCE(a.balance, 0) - COALESCE(gl.computed, 0)) DESC
    """)).fetchall()

    if not rows:
        print("  ✓ All account balances match journal_lines")
        return 0

    print(f"  ✗ {len(rows)} account balance mismatches:")
    for r in rows:
        diff = float(r.cached_balance) - float(r.computed_balance)
        print(f"    Account {r.account_number} ({r.name}): cached={r.cached_balance}, computed={r.computed_balance}, diff={diff:+.2f}")

    if fix:
        conn.execute(text("""
            UPDATE accounts a SET balance = CAST(COALESCE(sub.computed, 0) AS NUMERIC(18,4))
            FROM (
                SELECT jl.account_id,
                       CAST(SUM(jl.debit - jl.credit) AS NUMERIC(18,4)) AS computed
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                WHERE je.status = 'posted'
                GROUP BY jl.account_id
            ) sub
            WHERE sub.account_id = a.id
              AND ABS(COALESCE(a.balance, 0) - COALESCE(sub.computed, 0)) > 0.01
        """))
        # Also zero out accounts with no journal lines
        conn.execute(text("""
            UPDATE accounts SET balance = CAST(0 AS NUMERIC(18,4))
            WHERE balance != 0
              AND id NOT IN (
                  SELECT DISTINCT jl.account_id FROM journal_lines jl
                  JOIN journal_entries je ON je.id = jl.journal_entry_id
                  WHERE je.status = 'posted'
              )
        """))
        conn.commit()
        print(f"    → Fixed {len(rows)} account balances")

    return len(rows)


def check_treasury_balances(conn, fix=False):
    """Check treasury_accounts.current_balance vs linked GL account balance"""
    rows = conn.execute(text("""
        SELECT ta.id, ta.name, ta.currency,
               COALESCE(ta.current_balance, 0) AS cached_balance,
               CASE
                   WHEN ta.currency IS NOT NULL AND ta.currency != '' THEN
                       COALESCE(a.balance_currency, a.balance, 0)
                   ELSE
                       COALESCE(a.balance, 0)
               END AS gl_balance
        FROM treasury_accounts ta
        JOIN accounts a ON a.id = ta.gl_account_id
        WHERE ta.is_active = TRUE
          AND ABS(
              COALESCE(ta.current_balance, 0) -
              CASE
                  WHEN ta.currency IS NOT NULL AND ta.currency != '' THEN
                      COALESCE(a.balance_currency, a.balance, 0)
                  ELSE
                      COALESCE(a.balance, 0)
              END
          ) > 0.01
    """)).fetchall()

    if not rows:
        print("  ✓ All treasury balances match GL accounts")
        return 0

    print(f"  ✗ {len(rows)} treasury balance mismatches:")
    for r in rows:
        print(f"    Treasury '{r.name}' ({r.currency}): cached={r.cached_balance}, GL={r.gl_balance}")

    if fix:
        # Set GL context GUC so the treasury balance trigger allows this sanctioned path
        conn.execute(text("SELECT set_config('aman.gl_context', 'on', true)"))
        conn.execute(text("""
            UPDATE treasury_accounts ta
            SET current_balance = CAST(CASE
                WHEN ta.currency IS NOT NULL AND ta.currency != '' THEN
                    COALESCE(a.balance_currency, a.balance, 0)
                ELSE
                    COALESCE(a.balance, 0)
            END AS NUMERIC(18,4))
            FROM accounts a
            WHERE a.id = ta.gl_account_id
              AND ta.is_active = TRUE
              AND ABS(
                  COALESCE(ta.current_balance, 0) -
                  CASE
                      WHEN ta.currency IS NOT NULL AND ta.currency != '' THEN
                          COALESCE(a.balance_currency, a.balance, 0)
                      ELSE
                          COALESCE(a.balance, 0)
                  END
              ) > 0.01
        """))
        conn.commit()
        print(f"    → Fixed {len(rows)} treasury balances")

    return len(rows)


def check_party_balances(conn, fix=False):
    """Check party_site_balances vs SUM from party_transactions (per site/branch/currency)"""
    # Check if party_site_balances table exists
    table_exists = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'party_site_balances')"
    )).scalar()
    
    if not table_exists:
        print("  ⚠ party_site_balances table not found, skipping")
        return 0
    
    rows = conn.execute(text("""
        SELECT ps.id as site_id, ps.site_name, p.name as party_name, p.party_type,
               psb.company_branch_id, psb.currency, psb.account_type,
               COALESCE(psb.balance, 0) AS cached_balance,
               COALESCE(pt.computed, 0) AS computed_balance
        FROM party_site_balances psb
        JOIN party_sites ps ON psb.party_site_id = ps.id
        JOIN parties p ON ps.party_id = p.id
        LEFT JOIN (
            SELECT party_id, branch_id, currency, account_type,
                   SUM(debit - credit) AS computed
            FROM party_transactions
            GROUP BY party_id, branch_id, currency, account_type
        ) pt ON pt.party_id = p.id 
            AND pt.branch_id = psb.company_branch_id 
            AND pt.currency = psb.currency
            AND pt.account_type = psb.account_type
        WHERE ABS(COALESCE(psb.balance, 0) - COALESCE(pt.computed, 0)) > 0.01
        ORDER BY ABS(COALESCE(psb.balance, 0) - COALESCE(pt.computed, 0)) DESC
    """)).fetchall()

    if not rows:
        print("  ✓ All party_site_balances match party_transactions")
        return 0

    print(f"  ✗ {len(rows)} party_site_balance mismatches:")
    for r in rows:
        diff = float(r.cached_balance) - float(r.computed_balance)
        print(f"    Party '{r.party_name}' ({r.party_type}) Site '{r.site_name}' Branch {r.company_branch_id} {r.currency}: cached={r.cached_balance}, tx_sum={r.computed_balance}, diff={diff:+.2f}")

    if fix:
        conn.execute(text("""
            UPDATE party_site_balances psb 
            SET balance = CAST(COALESCE(sub.computed, 0) AS NUMERIC(18,4)),
                updated_at = NOW()
            FROM (
                SELECT pt.party_id, pt.branch_id, pt.currency, pt.account_type,
                       CAST(SUM(pt.debit - pt.credit) AS NUMERIC(18,4)) AS computed
                FROM party_transactions pt
                GROUP BY pt.party_id, pt.branch_id, pt.currency, pt.account_type
            ) sub
            JOIN party_sites ps ON ps.party_id = sub.party_id
            WHERE psb.party_site_id = ps.id
              AND psb.company_branch_id = sub.branch_id
              AND psb.currency = sub.currency
              AND psb.account_type = sub.account_type
              AND ABS(COALESCE(psb.balance, 0) - COALESCE(sub.computed, 0)) > 0.01
        """))
        conn.commit()
        print(f"    → Fixed {len(rows)} party_site_balances")

    return len(rows)


def check_party_balance_totals(conn, fix=False):
    """Verify total party balance (sum of all sites) matches expected total from transactions"""
    table_exists = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'party_site_balances')"
    )).scalar()
    
    if not table_exists:
        return 0
    
    # Compare party_site_balances total (converted to SAR) vs party_transactions total
    rows = conn.execute(text("""
        SELECT p.id, p.name, p.party_type,
               COALESCE(psb_total.total_sar, 0) AS sites_total_sar,
               COALESCE(pt_total.total_sar, 0) AS tx_total_sar
        FROM parties p
        LEFT JOIN (
            SELECT ps.party_id,
                   SUM(psb.balance * COALESCE(c.current_rate, 1)) as total_sar
            FROM party_site_balances psb
            JOIN party_sites ps ON psb.party_site_id = ps.id
            LEFT JOIN currencies c ON psb.currency = c.code
            GROUP BY ps.party_id
        ) psb_total ON psb_total.party_id = p.id
        LEFT JOIN (
            SELECT party_id,
                   SUM(debit - credit) as total_sar
            FROM party_transactions
            GROUP BY party_id
        ) pt_total ON pt_total.party_id = p.id
        WHERE ABS(COALESCE(psb_total.total_sar, 0) - COALESCE(pt_total.total_sar, 0)) > 0.01
        ORDER BY ABS(COALESCE(psb_total.total_sar, 0) - COALESCE(pt_total.total_sar, 0)) DESC
    """)).fetchall()

    if not rows:
        print("  ✓ All party totals (SAR) match between sites and transactions")
        return 0

    print(f"  ✗ {len(rows)} party total mismatches (SAR):")
    for r in rows:
        diff = float(r.sites_total_sar) - float(r.tx_total_sar)
        print(f"    Party '{r.name}' ({r.party_type}): sites_total={r.sites_total_sar:.2f}, tx_total={r.tx_total_sar:.2f}, diff={diff:+.2f}")

    return len(rows)


def main():
    fix = "--fix" in sys.argv
    if fix:
        print("=== RECONCILIATION (FIX MODE) ===\n")
    else:
        print("=== RECONCILIATION (READ-ONLY) ===")
        print("    Add --fix to auto-correct mismatches\n")

    dbs = get_company_dbs()
    if not dbs:
        print("No active company databases found")
        return

    total_issues = 0
    for db_name, url in dbs:
        print(f"── {db_name} ──")
        engine = create_engine(url)
        with engine.connect() as conn:
            total_issues += check_account_balances(conn, fix)
            total_issues += check_treasury_balances(conn, fix)
            total_issues += check_party_balances(conn, fix)
            total_issues += check_party_balance_totals(conn, fix)
        engine.dispose()
        print()

    if total_issues == 0:
        print("✓ All balances reconciled across all companies")
    else:
        print(f"✗ {total_issues} total mismatches found")
        if not fix:
            print("  Run with --fix to auto-correct")


if __name__ == "__main__":
    main()
