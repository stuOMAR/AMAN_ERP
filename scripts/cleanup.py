#!/usr/bin/env python3
"""
AMAN ERP - Cleanup Company Data
================================
يحذف كل بيانات الشركة بالترتيب الصحيح (مراعاة foreign keys).

الاستخدام:
    python scripts/cleanup.py                          # القيم الافتراضية
    python scripts/cleanup.py --company-code 34773f13
    python scripts/cleanup.py --company-code 34773f13 --confirm

المتطلبات:
    pip install psycopg2-binary
"""

import argparse
import sys
import os

import psycopg2

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

COMPANY_CODE = "34773f13"

# Database connection - reads from environment or uses defaults
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "aman")
DB_PASS = os.environ.get("DB_PASSWORD", "YourPassword123!@#")

# ═══════════════════════════════════════════════════════════════
# Tables to clean (in reverse dependency order)
# ═══════════════════════════════════════════════════════════════

TABLES_TO_CLEAN = [
    # Transactional data (deepest dependencies first)
    "journal_lines",
    "journal_entries",
    "invoice_lines",
    "invoices",
    "payment_vouchers",
    "payment_allocations",
    "supplier_transactions",
    "customer_transactions",
    "party_transactions",
    "treasury_transactions",
    "bank_reconciliations",
    "bank_statement_lines",

    # Sales
    "sales_quotation_lines",
    "sales_quotations",
    "sales_order_lines",
    "sales_orders",
    "sales_return_lines",
    "sales_returns",
    "sales_commissions",
    "commission_rules",

    # Purchases
    "purchase_order_lines",
    "purchase_orders",
    "supplier_payments",
    "customer_receipts",

    # Inventory
    "inventory_transactions",
    "inventory",
    "stock_adjustments",
    "stock_shipment_items",
    "stock_shipments",
    "stock_transfer_log",

    # POS
    "pos_order_lines",
    "pos_orders",
    "pos_payments",
    "pos_sessions",
    "pos_kitchen_orders",

    # Projects
    "project_timesheets",
    "project_expenses",
    "project_documents",
    "project_change_orders",
    "project_risks",
    "project_budgets",
    "project_tasks",
    "projects",

    # HR
    "payroll_entries",
    "payroll_periods",
    "attendance",
    "leave_requests",
    "employee_loans",
    "employee_documents",
    "employee_salary_components",
    "performance_reviews",
    "training_participants",
    "training_programs",
    "violations",
    "custodies",
    "overtime_requests",
    "gosi_calculations",

    # Manufacturing
    "shop_floor_logs",
    "mrp_items",
    "mrp_plans",
    "production_order_operations",
    "production_orders",
    "manufacturing_operations",
    "manufacturing_equipment",
    "manufacturing_routes",
    "bom_outputs",
    "bom_components",
    "bills_of_material",
    "work_centers",

    # Assets
    "asset_maintenance",
    "asset_impairments",
    "asset_transfers",
    "asset_revaluations",
    "asset_disposals",
    "asset_insurances",
    "asset_depreciation_schedules",
    "assets",
    "asset_categories",

    # Finance advanced
    "budget_items",
    "budgets",
    "cost_centers_budgets",
    "cash_flow_forecasts",
    "fiscal_period_locks",
    "fiscal_periods",
    "fiscal_years",
    "tax_returns",
    "tax_payments",
    "costing_policies",

    # Approvals & Security
    "approval_requests",
    "approval_workflows",
    "audit_logs",
    "security_events",
    "user_sessions",
    "user_2fa_settings",
    "password_history",
    "token_blacklist",

    # Notifications
    "notifications",

    # CRM
    "crm_tickets",
    "crm_campaigns",
    "crm_contacts",
    "crm_opportunities",
    "crm_leads",

    # Contracts
    "contract_milestones",
    "contract_items",
    "contracts",

    # Services
    "service_costs",
    "service_requests",

    # Reports
    "custom_reports",
    "scheduled_report_results",
    "scheduled_reports",
    "shared_reports",

    # Core entities (after all dependencies removed)
    # ⚠️ company_users and user_branches are NOT deleted — main user must stay
    "employees",
    # "company_users",   # ← محمي: لا نحذف المستخدم الرئيسي
    # "user_branches",   ← محمي: لا نحذف فروع المستخدم الرئيسي
    "parties",
    "party_groups",
    "customer_groups",
    "supplier_groups",
    "customer_price_lists",
    "products",
    "product_categories",
    "product_units",
    "product_variants",
    "product_attributes",
    "product_kits",
    "product_batches",
    "product_serials",
    "item_warehouse_settings",

    # Organization
    "warehouses",
    "bin_locations",
    "departments",
    "employee_positions",
    "cost_centers",
    "expense_policies",
    "work_policies",
    "salary_structures",
    "salary_components",

    # Finance core
    # ⚠️ accounts is NOT deleted — only balances are reset
    # "accounts",
    "treasury_accounts",
    "exchange_rates",
    "currencies",
    "tax_rates",
    "tax_groups",
    "tax_regimes",
    "branch_tax_settings",

    # Branches
    "branches",

    # Settings
    "company_settings",
]


def get_db_name(company_code: str) -> str:
    return f"aman_{company_code}"


def cleanup_company(db_name: str, confirm: bool = False, host: str = None, port: str = None, user: str = None, password: str = None):
    """حذف كل بيانات الشركة بالترتيب الصحيح"""
    db_host = host or DB_HOST
    db_port = port or DB_PORT
    db_user = user or DB_USER
    db_pass = password or DB_PASS

    print(f"\n╔══════════════════════════════════════════════════════════╗")
    print(f"║  حذف بيانات الشركة: {db_name:<38}║")
    print(f"╚══════════════════════════════════════════════════════════╝\n")

    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            dbname=db_name,
        )
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"  ✗ فشل الاتصال بقاعدة البيانات {db_name}: {e}")
        print(f"  تأكد من أن قاعدة البيانات موجودة وأن بيانات الاتصال صحيحة")
        return False

    # Count existing data first
    print("  ┌─ البيانات الموجودة قبل الحذف:")
    total_rows = 0
    tables_with_data = []
    for table in TABLES_TO_CLEAN:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            if count > 0:
                tables_with_data.append((table, count))
                total_rows += count
        except Exception:
            pass  # Table might not exist

    if total_rows == 0:
        print("  │  لا توجد بيانات للحذف.")
        conn.close()
        return True

    print(f"  │  إجمالي الصفوف: {total_rows}")
    for table, count in tables_with_data[:20]:
        print(f"  │  • {table}: {count}")
    if len(tables_with_data) > 20:
        print(f"  │  ... و {len(tables_with_data) - 20} جدول آخر")
    print("  └─")

    if not confirm:
        print("\n  ⚠️  تحذير: هذا الإجراء لا يمكن التراجع عنه!")
        response = input("  اكتب 'yes' للمتابعة: ").strip().lower()
        if response != "yes":
            print("  ✗ تم الإلغاء.")
            conn.close()
            return False

    # Delete data using TRUNCATE CASCADE to handle foreign keys
    print("\n  جاري حذف البيانات...")
    deleted_tables = 0
    deleted_rows = 0

    # Disable triggers to bypass audit/immutable triggers
    try:
        cur.execute("SET session_replication_role = 'replica'")
    except Exception:
        pass

    # First pass: count rows for all tables
    table_counts = {}
    for table in TABLES_TO_CLEAN:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            if count > 0:
                table_counts[table] = count
        except Exception:
            pass

    # Second pass: truncate with CASCADE
    tables_to_truncate = [t for t, c in table_counts.items() if c > 0]

    for table in tables_to_truncate:
        count = table_counts[table]
        try:
            cur.execute(f"TRUNCATE TABLE {table} CASCADE")
            deleted_rows += count
            deleted_tables += 1
            print(f"  ✓ {table}: {count} صف محذوف")
        except Exception as e1:
            # If truncate fails, try DELETE
            try:
                cur.execute(f"DELETE FROM {table}")
                deleted_rows += count
                deleted_tables += 1
                print(f"  ✓ {table}: {count} صف محذوف (DELETE)")
            except Exception as e2:
                print(f"  ⚠ {table}: {e2}")

    # Re-enable triggers
    try:
        cur.execute("SET session_replication_role = 'origin'")
    except Exception:
        pass

    print(f"\n  ✅ تم حذف {deleted_rows} صف من {deleted_tables} جدول")

    # Reset account balances (accounts are NOT deleted)
    print("\n  تصفير أرصدة الحسابات...")
    try:
        cur.execute("UPDATE accounts SET balance = 0, balance_currency = 0 WHERE balance != 0 OR balance_currency != 0")
        print(f"  ✓ تم تصفير {cur.rowcount} حساب")
    except Exception as e:
        print(f"  ⚠ فشل تصفير الحسابات: {e}")

    # Set accounts sequence to max ID + 1
    try:
        cur.execute("SELECT setval(pg_get_serial_sequence('accounts', 'id'), COALESCE((SELECT MAX(id) FROM accounts), 0) + 1, false)")
        print(f"  ✓ تم تعيين تسلسل الحسابات")
    except Exception as e:
        print(f"  ⚠ فشل تعيين تسلسل الحسابات: {e}")

    # Reset sequences (only for truncated tables + specific safe tables)
    print("\n  إعادة تعيين التسلسلات (sequences)...")
    try:
        cur.execute("""
            SELECT sequencename FROM pg_sequences 
            WHERE schemaname = 'public'
        """)
        sequences = cur.fetchall()
        reset_count = 0
        for (seq_name,) in sequences:
            # Skip accounts sequence — accounts are NOT deleted
            if seq_name == 'accounts_id_seq':
                continue
            # Skip company_users sequence — main user must stay
            if seq_name == 'company_users_id_seq':
                # Set to max ID + 1 instead of resetting to 1
                try:
                    cur.execute(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM company_users), 0) + 1, false)")
                    reset_count += 1
                except Exception:
                    pass
                continue
            try:
                cur.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")
                reset_count += 1
            except Exception:
                pass
        print(f"  ✓ تم إعادة تعيين {reset_count} تسلسل")
    except Exception as e:
        print(f"  ⚠ فشل إعادة التعيين: {e}")

    conn.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="AMAN ERP - Cleanup Company Data")
    parser.add_argument("--company-code", default=COMPANY_CODE, help="Company code")
    parser.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--host", default=DB_HOST, help="Database host")
    parser.add_argument("--port", default=DB_PORT, help="Database port")
    parser.add_argument("--user", default=DB_USER, help="Database user")
    parser.add_argument("--password", default=DB_PASS, help="Database password")
    args = parser.parse_args()

    db_name = get_db_name(args.company_code)
    success = cleanup_company(
        db_name,
        confirm=args.confirm,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
