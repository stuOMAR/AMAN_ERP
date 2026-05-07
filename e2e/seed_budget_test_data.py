"""
Seed script for Budget & Cost Center tests.
Creates test data via API calls.

Usage:
    python seed_budget_test_data.py

Requirements:
    - Server running at http://localhost:8000
    - Valid company credentials
"""

import requests
import json
from datetime import date, timedelta

BASE_URL = "http://localhost:8000/api"
COMPANY_CODE = "test"  # Change to your test company code
USERNAME = "omar"
PASSWORD = "As123321"

def login():
    """Login and get access token."""
    # First get the company ID
    resp = requests.post(f"{BASE_URL}/auth/login", json={
        "company_code": COMPANY_CODE,
        "username": USERNAME,
        "password": PASSWORD
    })
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} - {resp.text}")
        return None
    data = resp.json()
    return data.get("access_token")

def get_headers(token):
    """Get authorization headers."""
    return {"Authorization": f"Bearer {token}"}

def create_cost_center(token, name, name_en="", code=None):
    """Create a cost center."""
    payload = {
        "center_name": name,
        "center_name_en": name_en,
        "is_active": True
    }
    if code:
        payload["center_code"] = code
    
    resp = requests.post(
        f"{BASE_URL}/cost-centers/",
        headers=get_headers(token),
        json=payload
    )
    if resp.status_code in [200, 201]:
        print(f"✅ Cost center created: {name}")
        return resp.json()
    else:
        print(f"❌ Failed to create cost center '{name}': {resp.status_code} - {resp.text}")
        return None

def get_accounts(token):
    """Get list of accounts."""
    resp = requests.get(
        f"{BASE_URL}/accounting/accounts/",
        headers=get_headers(token)
    )
    if resp.status_code == 200:
        return resp.json()
    return []

def create_budget(token, name, start_date, end_date, description="", branch_id=None, cost_center_id=None):
    """Create a budget."""
    payload = {
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "description": description
    }
    if branch_id:
        payload["branch_id"] = branch_id
    if cost_center_id:
        payload["cost_center_id"] = cost_center_id
    
    resp = requests.post(
        f"{BASE_URL}/accounting/budgets/",
        headers=get_headers(token),
        json=payload
    )
    if resp.status_code in [200, 201]:
        print(f"✅ Budget created: {name}")
        return resp.json()
    else:
        print(f"❌ Failed to create budget '{name}': {resp.status_code} - {resp.text}")
        return None

def set_budget_items(token, budget_id, items):
    """Set budget items."""
    resp = requests.post(
        f"{BASE_URL}/accounting/budgets/{budget_id}/items",
        headers=get_headers(token),
        json=items
    )
    if resp.status_code == 200:
        print(f"✅ Budget items set for budget {budget_id}")
        return resp.json()
    else:
        print(f"❌ Failed to set budget items: {resp.status_code} - {resp.text}")
        return None

def activate_budget(token, budget_id):
    """Activate a budget."""
    resp = requests.post(
        f"{BASE_URL}/accounting/budgets/{budget_id}/activate",
        headers=get_headers(token)
    )
    if resp.status_code == 200:
        print(f"✅ Budget {budget_id} activated")
        return resp.json()
    else:
        print(f"❌ Failed to activate budget: {resp.status_code} - {resp.text}")
        return None

def create_journal_entry(token, entry_date, lines, description="Test JE", branch_id=None):
    """Create and post a journal entry."""
    payload = {
        "entry_date": entry_date,
        "description": description,
        "lines": lines
    }
    if branch_id:
        payload["branch_id"] = branch_id
    
    # Create
    resp = requests.post(
        f"{BASE_URL}/accounting/journal-entries/",
        headers=get_headers(token),
        json=payload
    )
    if resp.status_code not in [200, 201]:
        print(f"❌ Failed to create JE: {resp.status_code} - {resp.text}")
        return None
    
    je = resp.json()
    je_id = je.get("id")
    
    # Post
    resp = requests.post(
        f"{BASE_URL}/accounting/journal-entries/{je_id}/post",
        headers=get_headers(token)
    )
    if resp.status_code == 200:
        print(f"✅ Journal entry {je_id} created and posted")
        return je
    else:
        print(f"⚠️ JE created but posting failed: {resp.status_code}")
        return je

def get_branches(token):
    """Get list of branches."""
    resp = requests.get(
        f"{BASE_URL}/branches/",
        headers=get_headers(token)
    )
    if resp.status_code == 200:
        return resp.json()
    return []

def main():
    print("=" * 60)
    print("Budget & Cost Center Test Data Seeder")
    print("=" * 60)
    
    # Login
    token = login()
    if not token:
        print("❌ Cannot proceed without authentication")
        return
    
    print("\n📊 Step 1: Getting accounts...")
    accounts = get_accounts(token)
    expense_accounts = [a for a in accounts if a.get("account_type") == "expense"]
    revenue_accounts = [a for a in accounts if a.get("account_type") == "revenue"]
    
    if not expense_accounts:
        print("❌ No expense accounts found. Please create expense accounts first.")
        return
    
    print(f"   Found {len(expense_accounts)} expense accounts")
    print(f"   Found {len(revenue_accounts)} revenue accounts")
    
    # Get branches
    print("\n🏢 Step 2: Getting branches...")
    branches = get_branches(token)
    branch_id = branches[0]["id"] if branches else None
    print(f"   Using branch_id: {branch_id}")
    
    # Create Cost Centers
    print("\n🎯 Step 3: Creating cost centers...")
    cc1 = create_cost_center(token, "مركز التكلفة - المبيعات", "Sales Cost Center", "CC-001")
    cc2 = create_cost_center(token, "مركز التكلفة - الإدارة", "Admin Cost Center", "CC-002")
    cc3 = create_cost_center(token, "مركز التكلفة - الإنتاج", "Production Cost Center", "CC-003")
    
    # Create Budgets
    print("\n📊 Step 4: Creating budgets...")
    today = date.today()
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    
    budget1 = create_budget(
        token, 
        f"ميزانية {today.year} - المبيعات",
        str(year_start),
        str(year_end),
        "ميزانية تقديرية لقسم المبيعات",
        branch_id=branch_id,
        cost_center_id=cc1["id"] if cc1 else None
    )
    
    budget2 = create_budget(
        token,
        f"ميزانية {today.year} - الإدارة",
        str(year_start),
        str(year_end),
        "ميزانية تقديرية للإدارة العامة",
        branch_id=branch_id,
        cost_center_id=cc2["id"] if cc2 else None
    )
    
    # Set Budget Items
    if budget1 and expense_accounts:
        print("\n📝 Step 5: Setting budget items...")
        items1 = []
        for i, acc in enumerate(expense_accounts[:3]):
            items1.append({
                "account_id": acc["id"],
                "planned_amount": (i + 1) * 50000,
                "notes": f"Budget for {acc.get('name', 'account')}"
            })
        set_budget_items(token, budget1["id"], items1)
    
    if budget2 and expense_accounts:
        items2 = []
        for i, acc in enumerate(expense_accounts[:2]):
            items2.append({
                "account_id": acc["id"],
                "planned_amount": (i + 1) * 30000,
                "notes": f"Admin budget for {acc.get('name', 'account')}"
            })
        set_budget_items(token, budget2["id"], items2)
    
    # Activate Budgets
    if budget1:
        print("\n✅ Step 6: Activating budgets...")
        activate_budget(token, budget1["id"])
    
    # Create Journal Entries (actuals)
    if budget1 and expense_accounts:
        print("\n📒 Step 7: Creating journal entries (actuals)...")
        # Create a JE that spends 30000 on the first expense account
        je_lines = [
            {"account_id": expense_accounts[0]["id"], "debit": 30000, "credit": 0, "description": "Expense 1"},
        ]
        # Find a cash/bank account for the credit side
        cash_accounts = [a for a in accounts if a.get("account_type") == "asset" and "cash" in a.get("name", "").lower()]
        bank_accounts = [a for a in accounts if a.get("account_type") == "asset" and "bank" in a.get("name", "").lower()]
        
        credit_account = cash_accounts[0] if cash_accounts else (bank_accounts[0] if bank_accounts else None)
        if credit_account:
            je_lines.append({
                "account_id": credit_account["id"],
                "debit": 0,
                "credit": 30000,
                "description": "Cash/Bank"
            })
            create_journal_entry(
                token,
                str(today),
                je_lines,
                "Test expense entry",
                branch_id=branch_id
            )
    
    # Verify data
    print("\n" + "=" * 60)
    print("📊 VERIFICATION")
    print("=" * 60)
    
    # Check budgets list
    resp = requests.get(
        f"{BASE_URL}/accounting/budgets/",
        headers=get_headers(token),
        params={"branch_id": branch_id} if branch_id else {}
    )
    if resp.status_code == 200:
        budgets = resp.json()
        print(f"\n✅ Budgets count: {len(budgets)}")
        for b in budgets:
            print(f"   - {b['name']} ({b['status']})")
    
    # Check stats
    resp = requests.get(
        f"{BASE_URL}/accounting/budgets/stats/summary",
        headers=get_headers(token),
        params={"branch_id": branch_id} if branch_id else {}
    )
    if resp.status_code == 200:
        stats = resp.json()
        print(f"\n✅ Budget Stats:")
        print(f"   Total: {stats.get('total_budgets')}")
        print(f"   Active: {stats.get('active_count')}")
        print(f"   Draft: {stats.get('draft_count')}")
        print(f"   Total Planned: {stats.get('total_planned')}")
        print(f"   Total Actual: {stats.get('total_actual')}")
        print(f"   Usage: {stats.get('overall_usage_pct')}%")
    
    # Check cost centers
    resp = requests.get(
        f"{BASE_URL}/cost-centers/",
        headers=get_headers(token)
    )
    if resp.status_code == 200:
        centers = resp.json()
        print(f"\n✅ Cost Centers count: {len(centers)}")
        for c in centers:
            print(f"   - {c['center_name']} ({c.get('center_code', 'no code')})")
    
    print("\n" + "=" * 60)
    print("✅ Test data seeding complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
