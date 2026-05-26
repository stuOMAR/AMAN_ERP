import sys
import os
import random
from datetime import datetime, timedelta
import logging

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_system_db, create_company_database, get_db_connection
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for Seeding
COMPANY_ID = "TEST001"
ADMIN_PASSWORD = os.environ.get("AMAN_SEED_ADMIN_PASSWORD") or os.environ.get("AMAN_ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("AMAN_SEED_ADMIN_PASSWORD (or AMAN_ADMIN_PASSWORD) must be set before running seed_data.py")
NUM_BRANCHES = 5
NUM_ACCOUNTS = 1000
NUM_PARTIES = 5000
NUM_PRODUCTS = 2000
NUM_JOURNAL_ENTRIES = 100000 # Serious volume for optimization testingcrease later
BATCH_SIZE = 1000

def teardown_company():
    """Drop the test company database if it exists"""
    db_name = f"aman_{COMPANY_ID}"
    logger.info(f"🗑️ Tearing down database {db_name}...")
    try:
        db = get_system_db()
        # Terminate connections first
        db.execute(text(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
            AND pid <> pg_backend_pid();
        """))
        db.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        
        # Handle Role Drop Aggressively
        role_name = f"company_{COMPANY_ID.lower()}"
        try:
            db.execute(text(f'REASSIGN OWNED BY "{role_name}" TO CURRENT_USER'))
            db.execute(text(f'DROP OWNED BY "{role_name}"'))
            db.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
        except Exception as e:
             logger.warning(f"⚠️ Could not drop role {role_name}: {e}")

        db.commit()
        logger.info("✅ Database and Role dropped.")
    except Exception as e:
        logger.error(f"⚠️ Could not drop database: {e}")
    finally:
        db.close()

def setup_company():
    """Create the test company database"""
    logger.info(f"Checking company database for {COMPANY_ID}...")
    success, msg, db_name, db_user = create_company_database(COMPANY_ID, ADMIN_PASSWORD)
    
    if success:
        logger.info(f"✅ Created company database: {db_name}")
    else:
        logger.info(f"ℹ️ Company database might already exist: {msg}")
        # Proceed anyway!
        if 'already exists' in str(msg) and 'role' not in str(msg):
             # If DB exists, we assume it's fine. 
             # If role exists but DB creation failed, we might have issues if permissions weren't granted.
             pass

    # Initialize Schema with ALL tables in correct order
    from database import (
        get_all_table_sql, 
        get_organization_tables_sql,
        get_financial_tables_sql,
        get_treasury_tables_sql,
        get_currency_tables_sql,
        get_contract_tables_sql,
        get_costing_policy_tables_sql,
        get_advanced_inventory_tables_sql,
        get_advanced_inventory_phase2_tables_sql,
        get_additional_tables_sql
    )
    
    logger.info("Initializing schema...")
    try:
        with get_db_connection(COMPANY_ID) as conn:
            # 1. CORE (Users, Branches, Parties, Accounts, Journals)
            logger.info("  - Creating Core Tables...")
            try:
                conn.execute(text(get_all_table_sql()))
                conn.commit() # Commit Core separately
            except Exception as e:
                logger.error(f"  ❌ Core Tables Failed: {e}")
                raise e

            # 2. CURRENCY & ORG
            logger.info("  - Creating Org/Currency Tables...")
            try:
                conn.execute(text(get_currency_tables_sql()))
                conn.execute(text(get_organization_tables_sql()))
                conn.commit()
            except Exception as e:
                logger.error(f"  ❌ Org/Currency Failed: {e}")
                raise e

            # 3. ADDITIONAL (Customers, Products, Warehouses...)
            logger.info("  - Creating Additional Tables...")
            try:
                conn.execute(text(get_additional_tables_sql()))
                conn.commit()
            except Exception as e:
                logger.error(f"  ❌ Additional Tables Failed: {e}")
                raise e
            
            # 4. FINANCIAL (Projects...)
            logger.info("  - Creating Financial Tables...")
            try:
                conn.execute(text(get_financial_tables_sql()))
                conn.commit()
            except Exception as e:
                logger.error(f"  ❌ Financial Tables Failed: {e}")
                raise e

            # 5. OTHERS (Treasury, Contract...)
            logger.info("  - Creating Other Tables...")
            try:
                conn.execute(text(get_treasury_tables_sql()))
                conn.execute(text(get_contract_tables_sql()))
                conn.execute(text(get_costing_policy_tables_sql()))
                conn.execute(text(get_advanced_inventory_tables_sql()))
                conn.execute(text(get_advanced_inventory_phase2_tables_sql()))
                conn.commit()
            except Exception as e:
                logger.error(f"  ❌ Other Tables Failed: {e}")
                raise e
            
            logger.info("✅ Schema initialized.")
    except Exception as e:
        logger.error(f"❌ Schema Init Failed (Outer): {e}")
        raise e

def seed_branches(conn):
    """Seed branches"""
    logger.info("Seeding Branches...")
    branches = []
    for i in range(NUM_BRANCHES):
        branches.append({
            "code": f"BR-{i+1:03d}",
            "name": f"Branch {i+1}",
            "type": "branch",
            "is_active": True
        })
    
    # Check if branches exist
    count = conn.execute(text("SELECT COUNT(*) FROM branches")).scalar()
    if count < NUM_BRANCHES:
        conn.execute(text("""
            INSERT INTO branches (branch_code, branch_name, branch_type, is_active)
            VALUES (:code, :name, :type, :is_active)
            ON CONFLICT (branch_code) DO NOTHING
        """), branches)
        conn.commit()
        logger.info(f"✅ Seeded {NUM_BRANCHES} branches.")

def seed_accounts(conn):
    """Seed Chart of Accounts"""
    logger.info("Seeding Accounts...")
    
    # Ensure basic accounts exist
    base_accounts = [
        {"num": "1000", "name": "Assets", "type": "asset", "parent": None},
        {"num": "2000", "name": "Liabilities", "type": "liability", "parent": None},
        {"num": "3000", "name": "Equity", "type": "equity", "parent": None},
        {"num": "4000", "name": "Revenue", "type": "revenue", "parent": None},
        {"num": "5000", "name": "Expenses", "type": "expense", "parent": None},
    ]
    
    for acc in base_accounts:
        conn.execute(text("""
            INSERT INTO accounts (account_number, name, account_type, parent_id)
            VALUES (:num, :name, :type, :parent)
            ON CONFLICT (account_number) DO NOTHING
        """), acc)
    conn.commit()
    
    # Get IDs of parents
    parents = conn.execute(text("SELECT id, account_number, account_type FROM accounts WHERE parent_id IS NULL")).fetchall()
    
    accounts_batch = []
    for i in range(NUM_ACCOUNTS):
        parent = random.choice(parents)
        acc_num = f"{parent.account_number}-{i+1:04d}"
        accounts_batch.append({
            "num": acc_num,
            "name": f"Account {i+1} - {parent.account_type}",
            "type": parent.account_type,
            "parent": parent.id
        })
        
        if len(accounts_batch) >= BATCH_SIZE:
             conn.execute(text("""
                INSERT INTO accounts (account_number, name, account_type, parent_id)
                VALUES (:num, :name, :type, :parent)
                ON CONFLICT (account_number) DO NOTHING
            """), accounts_batch)
             conn.commit()
             accounts_batch = []
             
    if accounts_batch:
        conn.execute(text("""
            INSERT INTO accounts (account_number, name, account_type, parent_id)
            VALUES (:num, :name, :type, :parent)
            ON CONFLICT (account_number) DO NOTHING
        """), accounts_batch)
        conn.commit()
    
    logger.info(f"✅ Seeded ~{NUM_ACCOUNTS} accounts.")

def seed_parties(conn):
    """Seed Customers and Suppliers"""
    logger.info("Seeding Parties...")
    
    parties_batch = []
    for i in range(NUM_PARTIES):
        is_customer = random.choice([True, False])
        parties_batch.append({
            "code": f"P-{i+1:05d}",
            "name": f"Party {i+1}",
            "type": "company" if random.random() > 0.5 else "individual",
            "is_customer": is_customer,
            "is_supplier": not is_customer,
            "phone": f"05{random.randint(10000000, 99999999)}"
        })
        
        if len(parties_batch) >= BATCH_SIZE:
            conn.execute(text("""
                INSERT INTO parties (party_code, name, party_type, is_customer, is_supplier, phone)
                VALUES (:code, :name, :type, :is_customer, :is_supplier, :phone)
                ON CONFLICT (party_code) DO NOTHING
            """), parties_batch)
            conn.commit()
            parties_batch = []
            
    if parties_batch:
        conn.execute(text("""
            INSERT INTO parties (party_code, name, party_type, is_customer, is_supplier, phone)
            VALUES (:code, :name, :type, :is_customer, :is_supplier, :phone)
            ON CONFLICT (party_code) DO NOTHING
        """), parties_batch)
        conn.commit()
        
    logger.info(f"✅ Seeded {NUM_PARTIES} parties.")


def seed_scenario_references(conn):
    """Seed deterministic references used by docs/Scenario."""
    logger.info("Seeding Scenario reference data...")

    scenario_branches = [
        {"code": "BR-01", "name": "فرع الرياض"},
        {"code": "BR-02", "name": "فرع جدة"},
        {"code": "BR-03", "name": "فرع الدمام"},
    ]
    conn.execute(text("""
        INSERT INTO branches (branch_code, branch_name, branch_type, is_active)
        VALUES (:code, :name, 'branch', TRUE)
        ON CONFLICT (branch_code) DO UPDATE SET
            branch_name = EXCLUDED.branch_name,
            is_active = TRUE
    """), scenario_branches)

    br01_id = conn.execute(text("SELECT id FROM branches WHERE branch_code = 'BR-01'")).scalar()
    conn.execute(text("""
        INSERT INTO parties (
            party_code, name, party_type, is_customer, is_supplier,
            email, phone, currency, credit_limit, branch_id, status
        ) VALUES (
            'CUST-001', 'عميل السيناريو CUST-001', 'customer', TRUE, FALSE,
            'cust001@example.com', '0500000001', 'SAR', 1000000, :branch_id, 'active'
        )
        ON CONFLICT (party_code) DO UPDATE SET
            name = EXCLUDED.name,
            is_customer = TRUE,
            email = EXCLUDED.email,
            branch_id = EXCLUDED.branch_id,
            status = 'active'
    """), {"branch_id": br01_id})

    unit_id = conn.execute(text("""
        INSERT INTO product_units (unit_code, unit_name, unit_name_en, abbreviation, is_active)
        VALUES ('PCS', 'قطعة', 'Piece', 'pcs', TRUE)
        ON CONFLICT (unit_code) DO UPDATE SET unit_name = EXCLUDED.unit_name, is_active = TRUE
        RETURNING id
    """)).scalar()
    category_id = conn.execute(text("""
        INSERT INTO product_categories (category_code, category_name, category_name_en, is_active)
        VALUES ('SCENARIO-SALES', 'أصناف سيناريوهات المبيعات', 'Sales Scenario Items', TRUE)
        ON CONFLICT (category_code) DO UPDATE SET category_name = EXCLUDED.category_name, is_active = TRUE
        RETURNING id
    """)).scalar()

    conn.execute(text("""
        INSERT INTO products (
            product_code, sku, product_name, product_name_en, product_type,
            category_id, unit_id, selling_price, cost_price, tax_rate,
            is_taxable, is_active, is_track_inventory
        ) VALUES (
            'ITM-001', 'ITM-001', 'الصنف القياسي ITM-001', 'Standard Item ITM-001', 'product',
            :category_id, :unit_id, 5000, 3000, 0,
            FALSE, TRUE, TRUE
        )
        ON CONFLICT (product_code) DO UPDATE SET
            sku = EXCLUDED.sku,
            product_name = EXCLUDED.product_name,
            product_name_en = EXCLUDED.product_name_en,
            selling_price = EXCLUDED.selling_price,
            tax_rate = EXCLUDED.tax_rate,
            is_taxable = EXCLUDED.is_taxable,
            is_active = TRUE
    """), {"category_id": category_id, "unit_id": unit_id})
    conn.commit()
    logger.info("✅ Seeded Scenario references: BR-01/02/03, CUST-001, ITM-001.")

def seed_journal_entries(conn):
    """Seed Journal Entries (The Heavy Load)"""
    logger.info(f"Seeding {NUM_JOURNAL_ENTRIES} Journal Entries...")
    
    # Get IDs for relationships
    account_ids = [r[0] for r in conn.execute(text("SELECT id FROM accounts WHERE parent_id IS NOT NULL")).fetchall()]
    branch_ids = [r[0] for r in conn.execute(text("SELECT id FROM branches")).fetchall()]
    
    if not account_ids or not branch_ids:
        logger.error("❌ No accounts or branches found. Skipping JEs.")
        return

    # Use a large batch size for JEs
    JE_BATCH_SIZE = 1000
    
    start_num = 1
    total_seeded = 0
    while total_seeded < NUM_JOURNAL_ENTRIES:
        
        # Create Header Batch
        
        # Generate JE IDs and Numbers
        # We need to insert JEs first to get their IDs, OR rely on a known sequence.
        # Using RETURNING id efficiently in executemany is tricky in some drivers.
        # Let's insert JEs one by one? No, too slow.
        # Let's insert JEs in batch, then fetch IDs? Or assume serial if single threaded?
        # A better way is to generate UUIDs or rely on separate calls.
        
        # Actually, let's just fetch them by the numbers we just generated
        # Or better, just select the last N IDs.
        
        # Let's fetch the IDs for the current batch
        # This might be slow.
        # Alternative: Generate Lines *WITH* Headers in a stored procedure?
        # Or Use a simpler approach: 
        # Just loop 1000 times inside a transaction?
        
        # 100,000 / 1000 batch = 100 transactions.
        # Inside each transaction, we loop 1000 times to insert header then lines.
        # This is reasonably fast because commit is the expensive part.
        
        for _ in range(JE_BATCH_SIZE):
            entry_num = f"JE-SEED-{start_num:07d}"
            branch_id = random.choice(branch_ids)
            entry_date = datetime.now() - timedelta(days=random.randint(0, 365))

            # INV-21 fix: route through gl_service instead of direct INSERT
            # so the balance trigger and all GL guards are respected.
            amount = round(random.uniform(10.0, 10000.0), 2)
            acc1 = random.choice(account_ids)
            acc2 = random.choice(account_ids)
            while acc2 == acc1:
                acc2 = random.choice(account_ids)

            from services.gl_service import create_journal_entry as _gl_create
            _gl_create(
                conn,
                company_id="seed",
                date=entry_date.strftime("%Y-%m-%d"),
                description=f"Seeded Entry {start_num}",
                lines=[
                    {"account_id": acc1, "debit": amount, "credit": 0, "description": "Debit Line"},
                    {"account_id": acc2, "debit": 0, "credit": amount, "description": "Credit Line"},
                ],
                user_id=1,
                branch_id=branch_id,
                reference=f"REF-{start_num}",
                status="posted",
                currency="SAR",
                entry_number_override=entry_num,
            )

            start_num += 1

        conn.commit()
        total_seeded += JE_BATCH_SIZE
        if total_seeded % 10000 == 0:
            logger.info(f"   ...seeded {total_seeded} entries")

    logger.info(f"✅ Seeded {NUM_JOURNAL_ENTRIES} Journal Entries.")
    
def main():
    logger.info("🚀 Starting Data Seeding Script...")

    import os as _os
    if _os.environ.get("AMAN_ENV", "").lower() == "production":
        raise RuntimeError(
            "seed_data.py must NOT be run in production (AMAN_ENV=production). "
            "This script uses raw SQL inserts that bypass GL service constraints."
        )

    teardown_company()
    setup_company()
    
    with get_db_connection(COMPANY_ID) as conn:
        seed_branches(conn)
        seed_accounts(conn)
        seed_parties(conn)
        seed_scenario_references(conn)
        seed_journal_entries(conn)
        
    logger.info("✨ Seeding Completed Successfully!")

if __name__ == "__main__":
    main()
