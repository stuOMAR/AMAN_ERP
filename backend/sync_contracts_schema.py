import os
import sys

# Ensure backend dir is in path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(backend_dir)

from database import engine, get_db_connection  # noqa: E402
from sqlalchemy import text  # noqa: E402

def sync_contracts_schema():
    print("Starting tenant schema sync for contracts...")
    with engine.connect() as system_conn:
        tenants = system_conn.execute(
            text("SELECT id, database_name FROM system_companies WHERE status = 'active'")
        ).fetchall()

    for tenant in tenants:
        company_id = tenant.id
        db_name = tenant.database_name
        print(f"Syncing {db_name} (ID: {company_id})")
        
        try:
            with get_db_connection(company_id) as tenant_conn:
                tenant_conn.execute(text("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id)"))
                tenant_conn.execute(text("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64) UNIQUE"))
                tenant_conn.commit()
            print(f"  -> Successfully synced {db_name}")
        except Exception as e:
            print(f"  -> Error syncing {db_name}: {e}")

if __name__ == "__main__":
    sync_contracts_schema()
