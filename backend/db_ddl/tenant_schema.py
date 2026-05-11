"""T6.4 — Tenant DDL functions extracted from backend/database.py.

Each ``get_*_tables_sql()`` function returns a single SQL string of
one or more ``CREATE TABLE`` / ``CREATE INDEX`` statements. This is
the **single source of truth** for the per-tenant schema.
"""

from __future__ import annotations

__all__ = [
    "get_foundation_tables_sql",
    "get_additional_base_tables_sql",
    "get_treasury_base_tables_sql",
    "get_core_dependent_tables_sql",
    "get_additional_dependent_tables_sql",
    "get_organization_tables_sql",
    "get_financial_tables_sql",
    "get_treasury_dependent_tables_sql",
    "get_currency_tables_sql",
    "get_contract_tables_sql",
    "get_costing_policy_tables_sql",
    "get_advanced_inventory_tables_sql",
    "get_advanced_inventory_phase2_tables_sql",
    "get_manufacturing_tables_sql",
    "get_pos_tables_sql",
    "get_approval_tables_sql",
    "get_security_tables_sql",
    "get_cashflow_forecast_tables_sql",
    "get_phase_features_tables_sql",
    "get_system_completion_tables_sql",
    "get_extended_features_tables_sql",
    "get_performance_indexes_sql",
    "get_gl_integrity_guards_sql",
    "get_phase5_integration_tables_sql",
    "get_audit_security_finance_tables_sql",
    "get_feature023_tables_sql",
    "get_feature024_tables_sql",
]


def get_foundation_tables_sql() -> str:
    """Returns SQL for foundation tables (Users, Branches, Accounts, Treasury, Settings, Suppliers)"""
    return """
    -- ===== CORE TABLES (7) =====
    CREATE TABLE IF NOT EXISTS company_users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        email VARCHAR(255) UNIQUE,
        full_name VARCHAR(255),
        role VARCHAR(50) DEFAULT 'user',
        permissions JSONB DEFAULT '{}',
        is_active BOOLEAN DEFAULT TRUE,
        last_login TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS branches (
        id SERIAL PRIMARY KEY,
        branch_code VARCHAR(50) UNIQUE,
        branch_name VARCHAR(255) NOT NULL,
        branch_name_en VARCHAR(255),
        branch_type VARCHAR(50) DEFAULT 'branch',
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        country_code VARCHAR(5) DEFAULT NULL,
        default_currency VARCHAR(3) DEFAULT NULL,
        phone VARCHAR(50),
        email VARCHAR(255),
        manager_id INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        is_default BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS user_branches (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES company_users(id) ON DELETE CASCADE,
        branch_id INTEGER REFERENCES branches(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, branch_id)
    );

    -- ===== PARTIES (Consolidated) =====
    CREATE TABLE IF NOT EXISTS party_groups (
        id SERIAL PRIMARY KEY,
        group_code VARCHAR(50) UNIQUE,
        group_name VARCHAR(255) NOT NULL,
        group_name_en VARCHAR(255),
        branch_id INTEGER REFERENCES branches(id),
        discount_percentage DECIMAL(5, 2) DEFAULT 0,
        effect_type VARCHAR(20) DEFAULT 'discount',
        application_scope VARCHAR(20) DEFAULT 'total',
        payment_days INTEGER DEFAULT 30,
        description TEXT,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        account_number VARCHAR(50) UNIQUE NOT NULL,
        account_code VARCHAR(20),
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),
        account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
        parent_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
        is_header BOOLEAN DEFAULT FALSE,
        balance DECIMAL(18, 4) DEFAULT 0,
        balance_currency DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS treasury_accounts (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),
        account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('cash', 'bank')),
        currency VARCHAR(3) DEFAULT NULL,
        current_balance DECIMAL(18, 4) DEFAULT 0,
        gl_account_id INTEGER REFERENCES accounts(id),
        branch_id INTEGER REFERENCES branches(id),
        bank_name VARCHAR(255),
        account_number VARCHAR(100),
        iban VARCHAR(100),
        allow_overdraft BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- bank_accounts table removed (ARCH-006): merged into treasury_accounts
    
    CREATE TABLE IF NOT EXISTS journal_entries (
        id SERIAL PRIMARY KEY,
        entry_number VARCHAR(50) UNIQUE NOT NULL,
        entry_date DATE NOT NULL,
        reference VARCHAR(100),
        description TEXT,
        status VARCHAR(20) DEFAULT 'draft',
        currency VARCHAR(10) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        branch_id INTEGER REFERENCES branches(id),
        source VARCHAR(100),
        source_id INTEGER,
        idempotency_key VARCHAR(255),
        created_by INTEGER REFERENCES company_users(id) ON DELETE RESTRICT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        posted_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS company_settings (
        id SERIAL PRIMARY KEY,
        setting_key VARCHAR(100) UNIQUE NOT NULL,
        setting_value TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
-- ===== SUPPLIERS TABLES (Legacy/Deprecated) =====
    CREATE TABLE IF NOT EXISTS supplier_groups (
        id SERIAL PRIMARY KEY,
        group_code VARCHAR(50) UNIQUE,
        group_name VARCHAR(255) NOT NULL,
        group_name_en VARCHAR(255),
        description TEXT,
        parent_id INTEGER REFERENCES supplier_groups(id),
        branch_id INTEGER REFERENCES branches(id),
        discount_percentage DECIMAL(5, 2) DEFAULT 0,
        effect_type VARCHAR(20) DEFAULT 'discount',
        application_scope VARCHAR(20) DEFAULT 'total',
        payment_days INTEGER DEFAULT 30,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS suppliers (
        id SERIAL PRIMARY KEY,
        supplier_code VARCHAR(50) UNIQUE,
        supplier_name VARCHAR(255) NOT NULL,
        supplier_name_en VARCHAR(255),
        tax_number VARCHAR(50),
        commercial_register VARCHAR(50),
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        fax VARCHAR(50),
        website VARCHAR(255),
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        postal_code VARCHAR(20),
        supplier_group_id INTEGER REFERENCES supplier_groups(id),
        branch_id INTEGER REFERENCES branches(id),
        payment_terms VARCHAR(100),
        credit_limit DECIMAL(18, 4) DEFAULT 0,
        current_balance DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        tax_exempt BOOLEAN DEFAULT FALSE,
        status VARCHAR(20) DEFAULT 'active',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS supplier_contacts (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
        contact_name VARCHAR(255) NOT NULL,
        contact_name_en VARCHAR(255),
        position VARCHAR(100),
        department VARCHAR(100),
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        is_primary BOOLEAN DEFAULT FALSE,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS supplier_bank_accounts (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
        bank_name VARCHAR(255) NOT NULL,
        bank_name_en VARCHAR(255),
        account_number VARCHAR(50),
        iban VARCHAR(50),
        swift_code VARCHAR(20),
        branch_name VARCHAR(255),
        branch_code VARCHAR(50),
        account_holder VARCHAR(255),
        is_default BOOLEAN DEFAULT FALSE,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS supplier_payments (
        id SERIAL PRIMARY KEY,
        payment_number VARCHAR(50) UNIQUE,
        supplier_id INTEGER REFERENCES suppliers(id),
        payment_date DATE NOT NULL,
        payment_method VARCHAR(50),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(3) DEFAULT NULL,
        exchange_rate DECIMAL(10, 6) DEFAULT 1,
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        reference VARCHAR(100),
        notes TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_additional_base_tables_sql() -> str:
    """Returns SQL for additional base tables (Customer groups, Price lists, Products, Warehouses, Inventory, RFQ, etc.)"""
    return """
    -- ===== CUSTOMERS TABLES (7) =====
    CREATE TABLE IF NOT EXISTS customer_groups (
        id SERIAL PRIMARY KEY,
        group_code VARCHAR(50) UNIQUE,
        group_name VARCHAR(255) NOT NULL,
        group_name_en VARCHAR(255),
        description TEXT,
        parent_id INTEGER REFERENCES customer_groups(id),
        branch_id INTEGER REFERENCES branches(id),
        discount_percentage DECIMAL(5, 2) DEFAULT 0,
        effect_type VARCHAR(20) DEFAULT 'discount',
        application_scope VARCHAR(20) DEFAULT 'total',
        price_list_id INTEGER,
        payment_days INTEGER DEFAULT 30,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS customer_price_lists (
        id SERIAL PRIMARY KEY,
        price_list_code VARCHAR(50) UNIQUE,
        price_list_name VARCHAR(255) NOT NULL,
        price_list_name_en VARCHAR(255),
        customer_group_id INTEGER REFERENCES customer_groups(id),
        currency VARCHAR(3) DEFAULT NULL,
        branch_id INTEGER REFERENCES branches(id),
        discount_type VARCHAR(20) DEFAULT 'percentage',
        discount_value DECIMAL(10, 4) DEFAULT 0,
        valid_from DATE,
        valid_to DATE,
        status VARCHAR(20) DEFAULT 'active',
        is_default BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        customer_code VARCHAR(50) UNIQUE,
        customer_name VARCHAR(255) NOT NULL,
        customer_name_en VARCHAR(255),
        customer_type VARCHAR(50) DEFAULT 'individual',
        tax_number VARCHAR(50),
        commercial_register VARCHAR(50),
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        fax VARCHAR(50),
        website VARCHAR(255),
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        postal_code VARCHAR(20),
        customer_group_id INTEGER REFERENCES customer_groups(id),
        branch_id INTEGER REFERENCES branches(id),
        payment_terms VARCHAR(100),
        credit_limit DECIMAL(18, 4) DEFAULT 0,
        current_balance DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        price_list_id INTEGER REFERENCES customer_price_lists(id) ON DELETE SET NULL,
        tax_exempt BOOLEAN DEFAULT FALSE,
        status VARCHAR(20) DEFAULT 'active',
        notes TEXT,
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS customer_contacts (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
        contact_name VARCHAR(255) NOT NULL,
        contact_name_en VARCHAR(255),
        position VARCHAR(100),
        department VARCHAR(100),
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        is_primary BOOLEAN DEFAULT FALSE,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS customer_bank_accounts (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
        bank_name VARCHAR(255) NOT NULL,
        bank_name_en VARCHAR(255),
        account_number VARCHAR(50),
        iban VARCHAR(50),
        swift_code VARCHAR(20),
        branch_name VARCHAR(255),
        account_holder VARCHAR(255),
        is_default BOOLEAN DEFAULT FALSE,
        status VARCHAR(20) DEFAULT 'active',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    -- customer_transactions moved to additional_dependent
    
    CREATE TABLE IF NOT EXISTS customer_receipts (
        id SERIAL PRIMARY KEY,
        receipt_number VARCHAR(50) UNIQUE,
        customer_id INTEGER REFERENCES customers(id),
        receipt_date DATE NOT NULL,
        receipt_method VARCHAR(50),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(3) DEFAULT NULL,
        exchange_rate DECIMAL(10, 6) DEFAULT 1,
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        reference VARCHAR(100),
        notes TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    -- customer_price_lists moved above customers
    
    -- ===== PRODUCTS & INVENTORY TABLES (7) =====
    CREATE TABLE IF NOT EXISTS product_categories (
        id SERIAL PRIMARY KEY,
        category_code VARCHAR(50) UNIQUE,
        category_name VARCHAR(255) NOT NULL,
        category_name_en VARCHAR(255),
        description TEXT,
        parent_id INTEGER REFERENCES product_categories(id),
        branch_id INTEGER REFERENCES branches(id),
        image_url TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES company_users(id),
        updated_at TIMESTAMPTZ,
        updated_by INTEGER REFERENCES company_users(id)
    );
    
    CREATE TABLE IF NOT EXISTS product_units (
        id SERIAL PRIMARY KEY,
        unit_code VARCHAR(20) UNIQUE,
        unit_name VARCHAR(100) NOT NULL,
        unit_name_en VARCHAR(100),
        abbreviation VARCHAR(10),
        base_unit_id INTEGER REFERENCES product_units(id),
        conversion_factor DECIMAL(10, 6) DEFAULT 1,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        product_code VARCHAR(50) UNIQUE,
        product_name VARCHAR(255) NOT NULL,
        product_name_en VARCHAR(255),
        product_type VARCHAR(50) DEFAULT 'product',
        category_id INTEGER REFERENCES product_categories(id),
        unit_id INTEGER REFERENCES product_units(id),
        barcode VARCHAR(100),
        description TEXT,
        short_description VARCHAR(500),
        brand VARCHAR(100),
        manufacturer VARCHAR(100),
        origin_country VARCHAR(100),
        weight DECIMAL(10, 4),
        volume DECIMAL(10, 4),
        dimensions VARCHAR(100),
        cost_price DECIMAL(18, 4) DEFAULT 0,
        last_purchase_price DECIMAL(18, 4) DEFAULT 0,
        selling_price DECIMAL(18, 4) DEFAULT 0,
        wholesale_price DECIMAL(18, 4) DEFAULT 0,
        min_price DECIMAL(18, 4) DEFAULT 0,
        max_price DECIMAL(18, 4) DEFAULT 0,
        sku VARCHAR(100) UNIQUE,
        tax_rate DECIMAL(5, 2) DEFAULT NULL,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        tax_group_id INTEGER REFERENCES tax_groups(id) ON DELETE SET NULL,
        tax_classification_id INTEGER REFERENCES tax_classifications(id) ON DELETE SET NULL,
        is_exempt BOOLEAN DEFAULT FALSE,
        is_taxable BOOLEAN DEFAULT TRUE,
        is_active BOOLEAN DEFAULT TRUE,
        is_track_inventory BOOLEAN DEFAULT TRUE,
        reorder_level DECIMAL(18, 4) DEFAULT 0,
        reorder_quantity DECIMAL(18, 4) DEFAULT 0,
        image_url TEXT,
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS customer_price_list_items (
        id SERIAL PRIMARY KEY,
        price_list_id INTEGER NOT NULL REFERENCES customer_price_lists(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE RESTRICT,
        price DECIMAL(18, 4) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS warehouses (
        id SERIAL PRIMARY KEY,
        warehouse_code VARCHAR(50) UNIQUE,
        warehouse_name VARCHAR(255) NOT NULL,
        warehouse_name_en VARCHAR(255),
        location VARCHAR(255),
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        branch_id INTEGER REFERENCES branches(id),
        manager_id INTEGER REFERENCES company_users(id),
        is_default BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS inventory (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        quantity DECIMAL(18, 4) DEFAULT 0,
        reserved_quantity DECIMAL(18, 4) DEFAULT 0,
        available_quantity DECIMAL(18, 4) DEFAULT 0,
        in_transit_quantity DECIMAL(18, 4) DEFAULT 0,  -- TASK-026: stock dispatched but not yet received
        average_cost DECIMAL(18, 4) DEFAULT 0, -- Total company-wide or per-wh cost
        policy_version INTEGER DEFAULT 1,
        last_costing_update TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        last_movement_date TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_id, warehouse_id)
    );
    
    CREATE TABLE IF NOT EXISTS inventory_transactions (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        transaction_type VARCHAR(50) NOT NULL,
        reference_type VARCHAR(50),
        reference_id INTEGER,
        reference_document VARCHAR(100),
        quantity DECIMAL(18, 4) NOT NULL,
        balance_before DECIMAL(18, 4) DEFAULT 0,
        balance_after DECIMAL(18, 4) DEFAULT 0,
        unit_cost DECIMAL(18, 4) DEFAULT 0,
        total_cost DECIMAL(18, 4) DEFAULT 0,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS stock_adjustments (
        id SERIAL PRIMARY KEY,
        adjustment_number VARCHAR(50) UNIQUE,
        warehouse_id INTEGER REFERENCES warehouses(id),
        adjustment_type VARCHAR(50) NOT NULL,
        reason VARCHAR(255),
        product_id INTEGER REFERENCES products(id),
        old_quantity DECIMAL(18, 4) DEFAULT 0,
        new_quantity DECIMAL(18, 4) DEFAULT 0,
        difference DECIMAL(18, 4) DEFAULT 0,
        notes TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ,
        updated_by INTEGER REFERENCES company_users(id)
    );

    -- ===== STOCK SHIPMENTS (2) =====
    CREATE TABLE IF NOT EXISTS stock_shipments (
        id SERIAL PRIMARY KEY,
        shipment_ref VARCHAR(50) UNIQUE,
        source_warehouse_id INTEGER REFERENCES warehouses(id),
        destination_warehouse_id INTEGER REFERENCES warehouses(id),
        status VARCHAR(20) DEFAULT 'pending', -- pending, shipped, received, cancelled
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        shipped_at TIMESTAMPTZ,
        received_at TIMESTAMPTZ,
        received_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS stock_shipment_items (
        id SERIAL PRIMARY KEY,
        shipment_id INTEGER REFERENCES stock_shipments(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        quantity DECIMAL(18, 4) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stock_transfer_log (
        id SERIAL PRIMARY KEY,
        shipment_id INTEGER REFERENCES stock_shipments(id) ON DELETE SET NULL,
        product_id INTEGER REFERENCES products(id),
        from_warehouse_id INTEGER REFERENCES warehouses(id),
        to_warehouse_id INTEGER REFERENCES warehouses(id),
        quantity DECIMAL(18, 4) DEFAULT 0,
        transfer_cost DECIMAL(18, 4) DEFAULT 0,
        from_avg_cost_before DECIMAL(18, 4) DEFAULT 0,
        to_avg_cost_before DECIMAL(18, 4) DEFAULT 0,
        to_avg_cost_after DECIMAL(18, 4) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- purchase_orders, purchase_order_lines moved to additional_dependent

    CREATE TABLE IF NOT EXISTS notifications (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES company_users(id) ON DELETE CASCADE,
        title VARCHAR(255) NOT NULL,
        message TEXT,
        link VARCHAR(255),
        is_read BOOLEAN DEFAULT FALSE,
        type VARCHAR(20) DEFAULT 'info',
        channel VARCHAR(20),
        event_type VARCHAR(100),
        feature_source VARCHAR(100),
        body TEXT,
        reference_type VARCHAR(100),
        reference_id INTEGER,
        status VARCHAR(20) DEFAULT 'pending',
        sent_at TIMESTAMPTZ,
        delivery_status VARCHAR DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        last_retry_at TIMESTAMPTZ,
        delivery_channel VARCHAR,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS custom_reports (
        id SERIAL PRIMARY KEY,
        report_name VARCHAR(255) NOT NULL,
        description TEXT,
        config JSONB DEFAULT '{}',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS scheduled_reports (
        id SERIAL PRIMARY KEY,
        report_name VARCHAR(255),
        report_type VARCHAR(50) NOT NULL,
        report_config JSONB DEFAULT '{}',
        frequency VARCHAR(20) NOT NULL,
        recipients JSONB DEFAULT '[]',
        format VARCHAR(10) DEFAULT 'pdf',
        branch_id INTEGER REFERENCES branches(id),
        next_run_at TIMESTAMPTZ,
        last_run_at TIMESTAMPTZ,
        last_status VARCHAR(20) DEFAULT 'pending',
        is_active BOOLEAN DEFAULT TRUE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS scheduled_report_results (
        id SERIAL PRIMARY KEY,
        scheduled_report_id INTEGER REFERENCES scheduled_reports(id) ON DELETE CASCADE,
        report_data JSONB NOT NULL,
        generated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'completed'
    );
    CREATE INDEX IF NOT EXISTS idx_report_results_schedule ON scheduled_report_results(scheduled_report_id);

    CREATE TABLE IF NOT EXISTS shared_reports (
        id SERIAL PRIMARY KEY,
        report_type VARCHAR(30) NOT NULL CHECK (report_type IN ('custom', 'scheduled')),
        report_id INTEGER NOT NULL,
        shared_by INTEGER REFERENCES company_users(id),
        shared_with INTEGER REFERENCES company_users(id),
        permission VARCHAR(20) DEFAULT 'view' CHECK (permission IN ('view', 'edit')),
        message TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(report_type, report_id, shared_with)
    );

    -- sales_quotations, sales_orders, sales_returns, payment_vouchers, commissions moved to additional_dependent

    -- ===== REQUEST FOR QUOTATIONS =====
    CREATE TABLE IF NOT EXISTS request_for_quotations (
        id SERIAL PRIMARY KEY,
        rfq_number VARCHAR(50) UNIQUE,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        status VARCHAR(30) DEFAULT 'draft',
        deadline TIMESTAMPTZ,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS rfq_lines (
        id SERIAL PRIMARY KEY,
        rfq_id INTEGER REFERENCES request_for_quotations(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        product_name VARCHAR(255),
        quantity NUMERIC(12, 3) NOT NULL,
        unit VARCHAR(50),
        specifications TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS rfq_responses (
        id SERIAL PRIMARY KEY,
        rfq_id INTEGER REFERENCES request_for_quotations(id) ON DELETE CASCADE,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
        supplier_name VARCHAR(255),
        unit_price NUMERIC(15, 2),
        total_price NUMERIC(15, 2),
        delivery_days INTEGER,
        notes TEXT,
        is_selected BOOLEAN DEFAULT FALSE,
        submitted_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS rfq_response_lines (
        id SERIAL PRIMARY KEY,
        response_id INTEGER NOT NULL REFERENCES rfq_responses(id) ON DELETE CASCADE,
        rfq_line_id INTEGER NOT NULL REFERENCES rfq_lines(id) ON DELETE CASCADE,
        unit_price NUMERIC(15, 4) NOT NULL DEFAULT 0,
        total_price NUMERIC(15, 4) NOT NULL DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(response_id, rfq_line_id)
    );

    CREATE TABLE IF NOT EXISTS rfq_suppliers (
        id SERIAL PRIMARY KEY,
        rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,
        party_id INTEGER NOT NULL REFERENCES parties(id),
        status VARCHAR(20) DEFAULT 'invited',
        invited_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        responded_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== SUPPLIER RATINGS =====
    CREATE TABLE IF NOT EXISTS supplier_ratings (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
        po_id INTEGER, -- FK to purchase_orders deferred (created in additional_dependent)
        quality_score NUMERIC(3, 1) DEFAULT 0,
        delivery_score NUMERIC(3, 1) DEFAULT 0,
        price_score NUMERIC(3, 1) DEFAULT 0,
        service_score NUMERIC(3, 1) DEFAULT 0,
        overall_score NUMERIC(3, 1) DEFAULT 0,
        comments TEXT,
        rated_by INTEGER REFERENCES company_users(id),
        rated_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        updated_by INTEGER REFERENCES company_users(id)
    );

    -- ===== PURCHASE AGREEMENTS =====
    CREATE TABLE IF NOT EXISTS purchase_agreements (
        id SERIAL PRIMARY KEY,
        agreement_number VARCHAR(50) UNIQUE,
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
        agreement_type VARCHAR(30) DEFAULT 'blanket',
        title VARCHAR(255),
        start_date DATE,
        end_date DATE,
        total_amount NUMERIC(15, 2) DEFAULT 0,
        consumed_amount NUMERIC(15, 2) DEFAULT 0,
        status VARCHAR(30) DEFAULT 'draft',
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS purchase_agreement_lines (
        id SERIAL PRIMARY KEY,
        agreement_id INTEGER REFERENCES purchase_agreements(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        product_name VARCHAR(255),
        quantity NUMERIC(12, 3),
        unit_price NUMERIC(15, 2),
        delivered_qty NUMERIC(12, 3) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_rfq_status ON request_for_quotations(status);
    CREATE INDEX IF NOT EXISTS idx_supplier_ratings_supplier ON supplier_ratings(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_purchase_agreements_status ON purchase_agreements(status);
    """


def get_treasury_base_tables_sql() -> str:
    """Returns SQL for treasury base tables (transactions, reconciliations) — no forward FK deps"""
    return """
    -- ===== TREASURY BASE TABLES =====

    CREATE TABLE IF NOT EXISTS treasury_transactions (
        id SERIAL PRIMARY KEY,
        transaction_number VARCHAR(50) UNIQUE,
        transaction_date DATE NOT NULL,
        transaction_type VARCHAR(50) NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        treasury_id INTEGER REFERENCES treasury_accounts(id),
        target_account_id INTEGER REFERENCES accounts(id),
        target_treasury_id INTEGER REFERENCES treasury_accounts(id),
        branch_id INTEGER REFERENCES branches(id),
        description TEXT,
        reference_number VARCHAR(100),
        status VARCHAR(20) DEFAULT 'posted',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS bank_reconciliations (
        id SERIAL PRIMARY KEY,
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        statement_date DATE NOT NULL,
        start_balance DECIMAL(18, 4) DEFAULT 0,
        end_balance DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        notes TEXT,
        -- Absolute tolerance used when auto-matching bank lines against
        -- ledger entries (defaults to zero = strict match).
        tolerance_amount DECIMAL(18, 4) DEFAULT 0,
        created_by INTEGER REFERENCES company_users(id),
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_core_dependent_tables_sql() -> str:
    """Returns SQL for core dependent tables that need bank_reconciliations, cost_centers, customers, warehouses, products, etc."""
    return """
    -- ===== CORE DEPENDENT TABLES =====

    CREATE TABLE IF NOT EXISTS journal_lines (
        id SERIAL PRIMARY KEY,
        -- FIN-C5 / TASK-016: RESTRICT prevents accidental cascade deletion of
        -- journal lines. Drafts can still be removed by explicitly deleting
        -- their lines first; posted entries are further protected by
        -- trg_je_immutable / trg_jl_immutable.
        journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE RESTRICT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
        debit DECIMAL(18, 4) DEFAULT 0,
        credit DECIMAL(18, 4) DEFAULT 0,
        cost_center_id INTEGER REFERENCES cost_centers(id) ON DELETE SET NULL,
        amount_currency DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        -- txn_currency/txn_amount preserve the *original* transaction
        -- currency and amount per line. They support tri-currency journals
        -- (e.g., USD intercompany line booked into an EGP functional ledger)
        -- where ``currency`` records the booking-side functional currency
        -- and ``debit``/``credit`` are translated to the company base.
        txn_currency VARCHAR(10) DEFAULT NULL,
        txn_amount DECIMAL(18, 4) DEFAULT NULL,
        description TEXT,
        is_reconciled BOOLEAN DEFAULT FALSE,
        reconciliation_id INTEGER REFERENCES bank_reconciliations(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE OR REPLACE FUNCTION check_journal_balance() RETURNS TRIGGER AS $$
    DECLARE
        target_journal_entry_id INTEGER;
        total_debit NUMERIC;
        total_credit NUMERIC;
    BEGIN
        target_journal_entry_id := COALESCE(NEW.journal_entry_id, OLD.journal_entry_id);

        SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
          INTO total_debit, total_credit
        FROM journal_lines
        WHERE journal_entry_id = target_journal_entry_id;

        IF ABS(total_debit - total_credit) > 0.01 THEN
            RAISE EXCEPTION
                'Journal entry % is not balanced (debit %, credit %)',
                target_journal_entry_id, total_debit, total_credit;
        END IF;

        RETURN COALESCE(NEW, OLD);
    END;
    $$ LANGUAGE plpgsql;

    DO $$
    BEGIN
        IF to_regclass('public.journal_lines') IS NOT NULL THEN
            IF EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_journal_balance'
                  AND tgrelid = 'journal_lines'::regclass
            ) THEN
                DROP TRIGGER trg_journal_balance ON journal_lines;
            END IF;

            CREATE CONSTRAINT TRIGGER trg_journal_balance
            AFTER INSERT OR UPDATE OR DELETE ON journal_lines
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION check_journal_balance();
        END IF;
    END
    $$;

    CREATE TABLE IF NOT EXISTS bank_statement_lines (
        id SERIAL PRIMARY KEY,
        reconciliation_id INTEGER REFERENCES bank_reconciliations(id) ON DELETE CASCADE,
        transaction_date DATE NOT NULL,
        description TEXT,
        reference VARCHAR(100),
        debit DECIMAL(18, 4) DEFAULT 0,
        credit DECIMAL(18, 4) DEFAULT 0,
        balance DECIMAL(18, 4) DEFAULT 0,
        is_reconciled BOOLEAN DEFAULT FALSE,
        matched_journal_line_id INTEGER REFERENCES journal_lines(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS parties (
        id SERIAL PRIMARY KEY,
        party_type VARCHAR(20) DEFAULT 'individual', -- individual/company
        party_code VARCHAR(50) UNIQUE,
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),

        -- Contact Info
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        fax VARCHAR(50),
        website VARCHAR(255),

        -- Address
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        postal_code VARCHAR(20),

        -- Financial & Legal
        tax_number VARCHAR(50),
        commercial_register VARCHAR(50),
        tax_exempt BOOLEAN DEFAULT FALSE,
        currency VARCHAR(3),

        -- Classification
        is_customer BOOLEAN DEFAULT FALSE,
        is_supplier BOOLEAN DEFAULT FALSE,
        party_group_id INTEGER REFERENCES party_groups(id),
        branch_id INTEGER REFERENCES branches(id),

        -- Commercial Terms
        price_list_id INTEGER REFERENCES customer_price_lists(id) ON DELETE SET NULL,
        payment_terms VARCHAR(100),
        credit_limit DECIMAL(18, 4) DEFAULT 0,

        -- Balances (Denormalized)
        current_balance DECIMAL(18, 4) DEFAULT 0,
        balance_currency DECIMAL(18, 4) DEFAULT 0,

        status VARCHAR(20) DEFAULT 'active',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS invoices (
        id SERIAL PRIMARY KEY,
        invoice_number VARCHAR(50) UNIQUE NOT NULL,
        invoice_type VARCHAR(20) NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL, -- Deprecated
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL, -- Deprecated
        invoice_date DATE NOT NULL,
        due_date DATE,
        subtotal DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        discount DECIMAL(18, 4) DEFAULT 0,
        effect_type VARCHAR(20) DEFAULT 'discount',
        effect_percentage DECIMAL(5, 2) DEFAULT 0,
        markup_amount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        paid_amount DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        notes TEXT,
        down_payment_method VARCHAR(20),
        branch_id INTEGER REFERENCES branches(id),
        warehouse_id INTEGER REFERENCES warehouses(id) ON DELETE SET NULL,
        related_invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        currency VARCHAR(3) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS invoice_lines (
        id SERIAL PRIMARY KEY,
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        po_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE SET NULL,
        description VARCHAR(500),
        quantity DECIMAL(18, 4) DEFAULT 1,
        unit_price DECIMAL(18, 4) DEFAULT 0,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        discount DECIMAL(18, 4) DEFAULT 0,
        markup DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS idx_invoice_lines_po_line_id ON invoice_lines(po_line_id);
    CREATE INDEX IF NOT EXISTS idx_invoice_lines_tax_rate ON invoice_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS supplier_transactions (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id),
        transaction_type VARCHAR(50) NOT NULL,
        reference_number VARCHAR(100),
        transaction_date DATE NOT NULL,
        description TEXT,
        debit DECIMAL(18, 4) DEFAULT 0,
        credit DECIMAL(18, 4) DEFAULT 0,
        balance DECIMAL(18, 4) DEFAULT 0,
        payment_id INTEGER REFERENCES supplier_payments(id) ON DELETE SET NULL,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_additional_dependent_tables_sql() -> str:
    """Returns SQL for additional dependent tables that need parties, invoices, employees, etc."""
    return """
    -- ===== ADDITIONAL DEPENDENT TABLES =====

    CREATE TABLE IF NOT EXISTS customer_transactions (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id),
        transaction_type VARCHAR(50) NOT NULL,
        reference_number VARCHAR(100),
        transaction_date DATE NOT NULL,
        description TEXT,
        debit DECIMAL(18, 4) DEFAULT 0,
        credit DECIMAL(18, 4) DEFAULT 0,
        balance DECIMAL(18, 4) DEFAULT 0,
        receipt_id INTEGER REFERENCES customer_receipts(id) ON DELETE SET NULL,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS purchase_orders (
        id SERIAL PRIMARY KEY,
        po_number VARCHAR(50) UNIQUE NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL, -- Deprecated
        branch_id INTEGER REFERENCES branches(id),
        order_date DATE NOT NULL,
        expected_date DATE,
        subtotal DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft', -- draft, confirmed, received, cancelled
        notes TEXT,
        currency VARCHAR(3) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id SERIAL PRIMARY KEY,
        po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        description VARCHAR(500),
        quantity DECIMAL(18, 4) DEFAULT 1,
        unit_price DECIMAL(18, 4) DEFAULT 0,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        received_quantity DECIMAL(18, 4) DEFAULT 0,
        invoiced_quantity DECIMAL(18, 4) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );
    CREATE INDEX IF NOT EXISTS idx_purchase_order_lines_tax_rate ON purchase_order_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS po_receipts (
        id SERIAL PRIMARY KEY,
        po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        receipt_date DATE NOT NULL DEFAULT CURRENT_DATE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS po_receipt_lines (
        id SERIAL PRIMARY KEY,
        receipt_id INTEGER NOT NULL REFERENCES po_receipts(id) ON DELETE CASCADE,
        po_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
        product_id INTEGER REFERENCES products(id),
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        quantity DECIMAL(18, 4) NOT NULL,
        unit_cost DECIMAL(18, 4) NOT NULL DEFAULT 0,
        total_cost DECIMAL(18, 4) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_po_receipt_lines_po_line_id ON po_receipt_lines(po_line_id);
    CREATE INDEX IF NOT EXISTS idx_po_receipt_lines_receipt_id ON po_receipt_lines(receipt_id);

    CREATE TABLE IF NOT EXISTS sales_quotations (
        id SERIAL PRIMARY KEY,
        sq_number VARCHAR(50) UNIQUE NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL, -- Deprecated
        branch_id INTEGER REFERENCES branches(id),
        quotation_date DATE NOT NULL,
        expiry_date DATE,
        subtotal DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        notes TEXT,
        terms_conditions TEXT,
        currency VARCHAR(3) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS sales_quotation_lines (
        id SERIAL PRIMARY KEY,
        sq_id INTEGER REFERENCES sales_quotations(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        description TEXT,
        quantity DECIMAL(18, 4) NOT NULL,
        unit_price DECIMAL(18, 4) NOT NULL,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS idx_sales_quotation_lines_tax_rate ON sales_quotation_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS sales_orders (
        id SERIAL PRIMARY KEY,
        so_number VARCHAR(50) UNIQUE NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL, -- Deprecated
        branch_id INTEGER REFERENCES branches(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        quotation_id INTEGER REFERENCES sales_quotations(id),
        order_date DATE NOT NULL,
        expected_delivery_date DATE,
        subtotal DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        notes TEXT,
        currency VARCHAR(3) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS sales_order_lines (
        id SERIAL PRIMARY KEY,
        so_id INTEGER REFERENCES sales_orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        description TEXT,
        quantity DECIMAL(18, 4) NOT NULL,
        unit_price DECIMAL(18, 4) NOT NULL,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        discount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS idx_sales_order_lines_tax_rate ON sales_order_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS sales_returns (
        id SERIAL PRIMARY KEY,
        return_number VARCHAR(50) UNIQUE NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL, -- Deprecated
        branch_id INTEGER REFERENCES branches(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        invoice_id INTEGER REFERENCES invoices(id),
        return_date DATE NOT NULL,
        subtotal DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        total DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        notes TEXT,
        refund_method VARCHAR(20),
        refund_amount DECIMAL(18, 4) DEFAULT 0,
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL, -- legacy, use treasury_account_id
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        check_number VARCHAR(50),
        check_date DATE,
        exchange_rate DECIMAL(10, 6) DEFAULT 1.0,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS sales_return_lines (
        id SERIAL PRIMARY KEY,
        return_id INTEGER REFERENCES sales_returns(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        description TEXT,
        quantity DECIMAL(18, 4) NOT NULL,
        unit_price DECIMAL(18, 4) NOT NULL,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        total DECIMAL(18, 4) NOT NULL,
        reason TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS idx_sales_return_lines_tax_rate ON sales_return_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS payment_vouchers (
        id SERIAL PRIMARY KEY,
        voucher_number VARCHAR(50) UNIQUE NOT NULL,
        branch_id INTEGER REFERENCES branches(id),
        voucher_type VARCHAR(20) NOT NULL, -- receipt, payment
        voucher_date DATE NOT NULL,
        party_type VARCHAR(20) NOT NULL, -- customer, supplier
        party_id INTEGER NOT NULL REFERENCES parties(id),
        amount DECIMAL(18, 4) NOT NULL,
        payment_method VARCHAR(20) NOT NULL, -- cash, bank, check
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL, -- legacy, use treasury_account_id
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        check_number VARCHAR(50),
        check_date DATE,
        reference VARCHAR(100),
        notes TEXT,
        currency VARCHAR(3) DEFAULT 'SAR',
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        status VARCHAR(20) DEFAULT 'posted',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS payment_allocations (
        id SERIAL PRIMARY KEY,
        voucher_id INTEGER REFERENCES payment_vouchers(id) ON DELETE CASCADE,
        invoice_id INTEGER REFERENCES invoices(id),
        allocated_amount DECIMAL(18, 4) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS party_transactions (
        id SERIAL PRIMARY KEY,
        party_id INTEGER REFERENCES parties(id),
        transaction_type VARCHAR(50) NOT NULL,
        reference_number VARCHAR(100),
        transaction_date DATE NOT NULL,
        description TEXT,
        debit DECIMAL(18, 4) DEFAULT 0,
        credit DECIMAL(18, 4) DEFAULT 0,
        balance DECIMAL(18, 4) DEFAULT 0,
        payment_id INTEGER REFERENCES payment_vouchers(id) ON DELETE SET NULL,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== SALES COMMISSIONS =====
    CREATE TABLE IF NOT EXISTS commission_rules (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        salesperson_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        category_id INTEGER REFERENCES product_categories(id) ON DELETE SET NULL,
        rate_type VARCHAR(20) DEFAULT 'percentage',
        rate DECIMAL(10, 4) DEFAULT 0,
        min_amount DECIMAL(18, 4) DEFAULT 0,
        max_amount DECIMAL(18, 4),
        is_active BOOLEAN DEFAULT TRUE,
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sales_commissions (
        id SERIAL PRIMARY KEY,
        salesperson_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
        salesperson_name VARCHAR(255),
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        invoice_number VARCHAR(50),
        invoice_date DATE,
        invoice_total DECIMAL(18, 4) DEFAULT 0,
        commission_rate DECIMAL(10, 4) DEFAULT 0,
        commission_amount DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        paid_date DATE,
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        UNIQUE(invoice_id, salesperson_id)
    );

    -- Add deferred FK for supplier_ratings.po_id (created in additional_base before purchase_orders)
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'supplier_ratings_po_id_fkey' AND table_name = 'supplier_ratings'
        ) THEN
            ALTER TABLE supplier_ratings ADD CONSTRAINT supplier_ratings_po_id_fkey
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE SET NULL;
        END IF;
    END $$;
    """


def get_organization_tables_sql() -> str:
    """Organization and HR tables"""
    return """
    -- ===== BRANCHES & EMPLOYEES (5) =====

    -- MOVED HERE TO FIX CIRCULAR DEPENDENCY
    CREATE TABLE IF NOT EXISTS payroll_periods (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        payment_date DATE,
        status VARCHAR(20) DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS departments (
        id SERIAL PRIMARY KEY,
        department_code VARCHAR(50) UNIQUE,
        department_name VARCHAR(255) NOT NULL,
        department_name_en VARCHAR(255),
        parent_id INTEGER REFERENCES departments(id),
        branch_id INTEGER REFERENCES branches(id),
        manager_id INTEGER,
        description TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employee_positions (
        id SERIAL PRIMARY KEY,
        position_code VARCHAR(50) UNIQUE,
        position_name VARCHAR(255) NOT NULL,
        position_name_en VARCHAR(255),
        department_id INTEGER REFERENCES departments(id),
        description TEXT,
        level INTEGER DEFAULT 1,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS roles (
        id SERIAL PRIMARY KEY,
        role_name VARCHAR(50) UNIQUE NOT NULL,
        role_name_ar VARCHAR(50),
        description TEXT,
        permissions JSONB DEFAULT '[]',
        is_system_role BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id SERIAL PRIMARY KEY,
        tenant_id VARCHAR(100),
        user_id INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        username VARCHAR(100),
        action VARCHAR(100),
        resource_type VARCHAR(50),
        resource_id VARCHAR(50),
        details JSONB,
        ip_address VARCHAR(50),
        branch_id INTEGER REFERENCES branches(id),
        is_archived BOOLEAN DEFAULT FALSE,
        archived_at TIMESTAMPTZ,
        -- T3.7 (audit #21,#22): tamper-evident chain.
        prev_hash VARCHAR(64),
        hash      VARCHAR(64),
        chain_seq BIGINT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
        
    CREATE TABLE IF NOT EXISTS employees (
        id SERIAL PRIMARY KEY,
        employee_code VARCHAR(50) UNIQUE,
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100) NOT NULL,
        first_name_en VARCHAR(100),
        last_name_en VARCHAR(100),
        email VARCHAR(255),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        gender VARCHAR(10),
        birth_date DATE,
        hire_date DATE,
        termination_date DATE,
        department_id INTEGER REFERENCES departments(id),
        position_id INTEGER REFERENCES employee_positions(id),
        branch_id INTEGER REFERENCES branches(id),
        manager_id INTEGER REFERENCES employees(id),
        employment_type VARCHAR(50) DEFAULT 'full_time',
        status VARCHAR(20) DEFAULT 'active',
        salary DECIMAL(18, 4) DEFAULT 0,
        housing_allowance DECIMAL(18, 4) DEFAULT 0,
        transport_allowance DECIMAL(18, 4) DEFAULT 0,
        other_allowances DECIMAL(18, 4) DEFAULT 0,
        hourly_cost DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        user_id INTEGER REFERENCES company_users(id),
        account_id INTEGER REFERENCES accounts(id),
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        tax_id VARCHAR(50),
        social_security VARCHAR(50),
        address TEXT,
        emergency_contact TEXT,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS cost_centers (
        id SERIAL PRIMARY KEY,
        center_code VARCHAR(50) UNIQUE,
        center_name VARCHAR(255) NOT NULL,
        center_name_en VARCHAR(255),
        department_id INTEGER REFERENCES departments(id),
        manager_id INTEGER REFERENCES employees(id),
        budget DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        date DATE NOT NULL,
        check_in TIMESTAMPTZ,
        check_out TIMESTAMPTZ,
        status VARCHAR(20) DEFAULT 'present',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- T13 P1 #64/#65 — Work-policy table linking attendance discipline to
    -- payroll. Without this the payroll engine had no canonical contracted
    -- hours/working-days source so absence deductions could not be computed.
    CREATE TABLE IF NOT EXISTS work_policies (
        id SERIAL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        name_en VARCHAR(120),
        weekly_hours NUMERIC(5,2) DEFAULT 40,
        daily_hours  NUMERIC(5,2) DEFAULT 8,
        -- ISO weekday numbers (1=Mon..7=Sun) of contracted working days.
        -- Saudi default = Sun..Thu => [7,1,2,3,4]; configurable per policy.
        work_days JSONB DEFAULT '[7,1,2,3,4]'::jsonb,
        late_threshold_minutes INTEGER DEFAULT 15,
        -- 'daily_rate' = (monthly_salary / contracted_days) per absent day,
        -- 'hourly'     = (monthly_salary / (weekly_hours*4.33)) per missed hour.
        absence_deduction_method VARCHAR(20) DEFAULT 'daily_rate',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employee_loans (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        amount DECIMAL(18, 4) NOT NULL,
        total_installments INTEGER DEFAULT 1,
        monthly_installment DECIMAL(18, 4) NOT NULL,
        paid_amount DECIMAL(18, 4) DEFAULT 0,
        start_date DATE,
        status VARCHAR(20) DEFAULT 'pending',
        reason TEXT,
        approved_by INTEGER REFERENCES company_users(id),
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS leave_requests (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        leave_type VARCHAR(50) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        reason TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        approved_by INTEGER REFERENCES company_users(id),
        attachment_url TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== ADVANCED HR TABLES (Phase 4) =====

    CREATE TABLE IF NOT EXISTS salary_structures (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),
        description TEXT,
        base_type VARCHAR(50) DEFAULT 'monthly',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS salary_components (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),
        component_type VARCHAR(20) NOT NULL CHECK (component_type IN ('earning', 'deduction')),
        calculation_type VARCHAR(20) NOT NULL DEFAULT 'fixed' CHECK (calculation_type IN ('fixed', 'percentage', 'formula')),
        percentage_of VARCHAR(50),
        percentage_value DECIMAL(8, 4) DEFAULT 0,
        formula TEXT,
        is_taxable BOOLEAN DEFAULT TRUE,
        is_gosi_applicable BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        structure_id INTEGER REFERENCES salary_structures(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employee_salary_components (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        component_id INTEGER REFERENCES salary_components(id) ON DELETE CASCADE,
        amount DECIMAL(18, 4) DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        effective_date DATE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, component_id)
    );

    CREATE TABLE IF NOT EXISTS overtime_requests (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        request_date DATE NOT NULL,
        overtime_date DATE NOT NULL,
        hours DECIMAL(5, 2) NOT NULL,
        overtime_type VARCHAR(20) DEFAULT 'normal' CHECK (overtime_type IN ('normal', 'holiday', 'weekend')),
        multiplier DECIMAL(4, 2) DEFAULT 1.5,
        calculated_amount DECIMAL(18, 4) DEFAULT 0,
        reason TEXT,
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'processed')),
        approved_by INTEGER REFERENCES company_users(id),
        approved_at TIMESTAMPTZ,
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS gosi_settings (
        id SERIAL PRIMARY KEY,
        employee_share_percentage DECIMAL(5, 2) DEFAULT 9.75,
        employer_share_percentage DECIMAL(5, 2) DEFAULT 11.75,
        occupational_hazard_percentage DECIMAL(5, 2) DEFAULT 2.0,
        max_contributable_salary DECIMAL(18, 4) DEFAULT 45000,
        is_active BOOLEAN DEFAULT TRUE,
        effective_date DATE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employee_documents (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        document_type VARCHAR(50) NOT NULL CHECK (document_type IN ('passport', 'iqama', 'license', 'certificate', 'contract', 'other')),
        document_number VARCHAR(100),
        issue_date DATE,
        expiry_date DATE,
        issuing_authority VARCHAR(255),
        file_url TEXT,
        notes TEXT,
        alert_days INTEGER DEFAULT 30,
        status VARCHAR(20) DEFAULT 'valid' CHECK (status IN ('valid', 'expired', 'expiring_soon')),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_cycles (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        self_assessment_deadline DATE,
        manager_review_deadline DATE,
        status VARCHAR(20) DEFAULT 'draft',
        created_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS performance_reviews (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        reviewer_id INTEGER REFERENCES employees(id),
        review_period VARCHAR(50) NOT NULL,
        review_date DATE NOT NULL,
        review_type VARCHAR(30) DEFAULT 'annual' CHECK (review_type IN ('quarterly', 'semi_annual', 'annual', 'probation')),
        overall_rating DECIMAL(3, 1) DEFAULT 0,
        strengths TEXT,
        weaknesses TEXT,
        goals TEXT,
        self_rating DECIMAL(3, 1),
        self_comments TEXT,
        manager_comments TEXT,
        status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'self_review', 'manager_review', 'completed')),
        cycle_id INTEGER REFERENCES review_cycles(id),
        self_assessment JSONB,
        manager_assessment JSONB,
        composite_score DECIMAL(5, 2),
        final_comments TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS training_programs (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        name_en VARCHAR(255),
        description TEXT,
        trainer VARCHAR(255),
        location VARCHAR(255),
        start_date DATE,
        end_date DATE,
        max_participants INTEGER,
        cost DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'planned' CHECK (status IN ('planned', 'in_progress', 'completed', 'cancelled')),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS training_participants (
        id SERIAL PRIMARY KEY,
        training_id INTEGER REFERENCES training_programs(id) ON DELETE CASCADE,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        attendance_status VARCHAR(20) DEFAULT 'registered' CHECK (attendance_status IN ('registered', 'attended', 'absent', 'completed')),
        certificate_issued BOOLEAN DEFAULT FALSE,
        score DECIMAL(5, 2),
        feedback TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(training_id, employee_id)
    );

    CREATE TABLE IF NOT EXISTS employee_violations (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        violation_date DATE NOT NULL,
        violation_type VARCHAR(100) NOT NULL,
        severity VARCHAR(20) DEFAULT 'minor' CHECK (severity IN ('minor', 'major', 'critical')),
        description TEXT,
        action_taken VARCHAR(100),
        penalty_amount DECIMAL(18, 4) DEFAULT 0,
        deduct_from_salary BOOLEAN DEFAULT FALSE,
        payroll_period_id INTEGER REFERENCES payroll_periods(id),
        reported_by INTEGER REFERENCES company_users(id),
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'appealed', 'dismissed')),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employee_custody (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        item_name VARCHAR(255) NOT NULL,
        item_type VARCHAR(50) CHECK (item_type IN ('mobile', 'laptop', 'vehicle', 'key', 'equipment', 'other')),
        serial_number VARCHAR(100),
        assigned_date DATE NOT NULL,
        return_date DATE,
        condition_on_assign VARCHAR(50) DEFAULT 'new',
        condition_on_return VARCHAR(50),
        value DECIMAL(18, 4) DEFAULT 0,
        notes TEXT,
        status VARCHAR(20) DEFAULT 'assigned' CHECK (status IN ('assigned', 'returned', 'lost', 'damaged')),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );


    CREATE TABLE IF NOT EXISTS payroll_entries (
        id SERIAL PRIMARY KEY,
        period_id INTEGER REFERENCES payroll_periods(id) ON DELETE CASCADE,
        employee_id INTEGER REFERENCES employees(id),
        basic_salary DECIMAL(18, 4) DEFAULT 0,
        housing_allowance DECIMAL(18, 4) DEFAULT 0,
        transport_allowance DECIMAL(18, 4) DEFAULT 0,
        other_allowances DECIMAL(18, 4) DEFAULT 0,
        salary_components_earning DECIMAL(18, 4) DEFAULT 0,
        salary_components_deduction DECIMAL(18, 4) DEFAULT 0,
        overtime_amount DECIMAL(18, 4) DEFAULT 0,
        gosi_employee_share DECIMAL(18, 4) DEFAULT 0,
        gosi_employer_share DECIMAL(18, 4) DEFAULT 0,
        violation_deduction DECIMAL(18, 4) DEFAULT 0,
        loan_deduction DECIMAL(18, 4) DEFAULT 0,
        deductions DECIMAL(18, 4) DEFAULT 0,
        net_salary DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        exchange_rate DECIMAL(18, 6) DEFAULT 1.0,
        net_salary_base DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== JOB OPENINGS & APPLICATIONS (HR Recruitment) =====
    CREATE TABLE IF NOT EXISTS job_openings (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        department_id INTEGER REFERENCES departments(id),
        position_id INTEGER REFERENCES employee_positions(id) ON DELETE SET NULL,
        description TEXT,
        requirements TEXT,
        employment_type VARCHAR(50) DEFAULT 'full_time',
        vacancies INTEGER DEFAULT 1,
        status VARCHAR(30) DEFAULT 'open',
        branch_id INTEGER REFERENCES branches(id),
        published_at TIMESTAMPTZ,
        closing_date DATE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS job_applications (
        id SERIAL PRIMARY KEY,
        opening_id INTEGER REFERENCES job_openings(id),
        applicant_name VARCHAR(255) NOT NULL,
        email VARCHAR(255),
        phone VARCHAR(50),
        resume_url TEXT,
        cover_letter TEXT,
        stage VARCHAR(50) DEFAULT 'applied',
        rating INTEGER DEFAULT 0,
        interview_date TIMESTAMPTZ,
        interviewer_id INTEGER REFERENCES company_users(id),
        notes TEXT,
        status VARCHAR(30) DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- ===== LEAVE CARRYOVER =====
    CREATE TABLE IF NOT EXISTS leave_carryover (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        leave_type VARCHAR(50) NOT NULL,
        year INTEGER NOT NULL,
        entitled_days NUMERIC(6, 1) DEFAULT 0,
        used_days NUMERIC(6, 1) DEFAULT 0,
        carried_days NUMERIC(6, 1) DEFAULT 0,
        expired_days NUMERIC(6, 1) DEFAULT 0,
        max_carryover NUMERIC(6, 1) DEFAULT 5,
        calculated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(employee_id, leave_type, year)
    );

    CREATE INDEX IF NOT EXISTS idx_job_openings_status ON job_openings(status);
    CREATE INDEX IF NOT EXISTS idx_job_applications_opening ON job_applications(opening_id);
    CREATE INDEX IF NOT EXISTS idx_leave_carryover_emp ON leave_carryover(employee_id, year);
    """


def get_financial_tables_sql() -> str:
    """Financial, Assets, Tax, Projects tables"""
    return """
    -- ===== AR/AP TABLES (6) =====
    CREATE TABLE IF NOT EXISTS customer_balances (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id) UNIQUE,
        currency VARCHAR(3) DEFAULT NULL,
        total_receivable DECIMAL(18, 4) DEFAULT 0,
        total_paid DECIMAL(18, 4) DEFAULT 0,
        outstanding_balance DECIMAL(18, 4) DEFAULT 0,
        overdue_amount DECIMAL(18, 4) DEFAULT 0,
        aging_30 DECIMAL(18, 4) DEFAULT 0,
        aging_60 DECIMAL(18, 4) DEFAULT 0,
        aging_90 DECIMAL(18, 4) DEFAULT 0,
        aging_120 DECIMAL(18, 4) DEFAULT 0,
        aging_120_plus DECIMAL(18, 4) DEFAULT 0,
        last_payment_date DATE,
        last_invoice_date DATE,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS supplier_balances (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id) UNIQUE,
        currency VARCHAR(3) DEFAULT NULL,
        total_payable DECIMAL(18, 4) DEFAULT 0,
        total_paid DECIMAL(18, 4) DEFAULT 0,
        outstanding_balance DECIMAL(18, 4) DEFAULT 0,
        overdue_amount DECIMAL(18, 4) DEFAULT 0,
        aging_30 DECIMAL(18, 4) DEFAULT 0,
        aging_60 DECIMAL(18, 4) DEFAULT 0,
        aging_90 DECIMAL(18, 4) DEFAULT 0,
        aging_120 DECIMAL(18, 4) DEFAULT 0,
        aging_120_plus DECIMAL(18, 4) DEFAULT 0,
        last_payment_date DATE,
        last_invoice_date DATE,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS receipts (
        id SERIAL PRIMARY KEY,
        receipt_number VARCHAR(50) UNIQUE,
        receipt_type VARCHAR(50) NOT NULL,
        customer_id INTEGER REFERENCES customers(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        receipt_date DATE NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(3) DEFAULT NULL,
        exchange_rate DECIMAL(10, 6) DEFAULT 1,
        payment_method VARCHAR(50),
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        reference VARCHAR(100),
        check_number VARCHAR(50),
        check_date DATE,
        notes TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );
    
    CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY,
        payment_number VARCHAR(50) UNIQUE,
        payment_type VARCHAR(50) NOT NULL,
        customer_id INTEGER REFERENCES customers(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        payment_date DATE NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(3) DEFAULT NULL,
        exchange_rate DECIMAL(10, 6) DEFAULT 1,
        payment_method VARCHAR(50),
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        reference VARCHAR(100),
        check_number VARCHAR(50),
        check_date DATE,
        notes TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS pending_receivables (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id),
        invoice_id INTEGER REFERENCES invoices(id),
        invoice_number VARCHAR(50),
        due_date DATE,
        amount DECIMAL(18, 4) DEFAULT 0,
        paid_amount DECIMAL(18, 4) DEFAULT 0,
        outstanding_amount DECIMAL(18, 4) DEFAULT 0,
        days_overdue INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    
    CREATE TABLE IF NOT EXISTS pending_payables (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id),
        invoice_id INTEGER REFERENCES invoices(id),
        invoice_number VARCHAR(50),
        due_date DATE,
        amount DECIMAL(18, 4) DEFAULT 0,
        paid_amount DECIMAL(18, 4) DEFAULT 0,
        outstanding_amount DECIMAL(18, 4) DEFAULT 0,
        days_overdue INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== FISCAL YEARS =====
    CREATE TABLE IF NOT EXISTS fiscal_years (
        id SERIAL PRIMARY KEY,
        year INTEGER NOT NULL UNIQUE,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed')),
        retained_earnings_account_id INTEGER REFERENCES accounts(id),
        closing_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        closed_by INTEGER REFERENCES company_users(id),
        closed_at TIMESTAMPTZ,
        reopened_by INTEGER REFERENCES company_users(id),
        reopened_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== RECURRING JOURNAL TEMPLATES (ACC-003) =====
    CREATE TABLE IF NOT EXISTS recurring_journal_templates (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        reference VARCHAR(100),
        frequency VARCHAR(20) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')),
        start_date DATE NOT NULL,
        end_date DATE,
        next_run_date DATE NOT NULL,
        last_run_date DATE,
        is_active BOOLEAN DEFAULT TRUE,
        auto_post BOOLEAN DEFAULT FALSE,
        branch_id INTEGER REFERENCES branches(id),
        currency VARCHAR(10) DEFAULT 'SAR',
        exchange_rate DECIMAL(18,6) DEFAULT 1.0,
        run_count INTEGER DEFAULT 0,
        max_runs INTEGER,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS recurring_journal_lines (
        id SERIAL PRIMARY KEY,
        template_id INTEGER NOT NULL REFERENCES recurring_journal_templates(id) ON DELETE CASCADE,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        debit DECIMAL(18,4) DEFAULT 0,
        credit DECIMAL(18,4) DEFAULT 0,
        description TEXT,
        cost_center_id INTEGER REFERENCES cost_centers(id) ON DELETE SET NULL
    );

    -- ===== FISCAL PERIODS =====
    CREATE TABLE IF NOT EXISTS fiscal_periods (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        fiscal_year INTEGER,
        is_closed BOOLEAN DEFAULT FALSE,
        closed_by INTEGER REFERENCES company_users(id),
        closed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );



    -- ===== BUDGETS & REPORTS (5) =====
    CREATE TABLE IF NOT EXISTS budgets (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        budget_code VARCHAR(50) UNIQUE,
        budget_name VARCHAR(255),
        budget_name_en VARCHAR(255),
        description TEXT,
        fiscal_year INTEGER,
        branch_id INTEGER REFERENCES branches(id),
        department_id INTEGER REFERENCES departments(id),
        cost_center_id INTEGER REFERENCES cost_centers(id),
        budget_type VARCHAR(30) DEFAULT 'annual',
        status VARCHAR(20) DEFAULT 'draft',
        total_budget DECIMAL(18, 4) DEFAULT 0,
        used_budget DECIMAL(18, 4) DEFAULT 0,
        remaining_budget DECIMAL(18, 4) DEFAULT 0,
        start_date DATE,
        end_date DATE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS budget_items (
        id SERIAL PRIMARY KEY,
        budget_id INTEGER REFERENCES budgets(id) ON DELETE CASCADE,
        account_id INTEGER REFERENCES accounts(id),
        planned_amount DECIMAL(18, 4) DEFAULT 0,
        actual_amount DECIMAL(18, 4) DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS budget_lines (
        id SERIAL PRIMARY KEY,
        budget_id INTEGER REFERENCES budgets(id) ON DELETE CASCADE,
        account_id INTEGER REFERENCES accounts(id),
        budget_amount DECIMAL(18, 4) DEFAULT 0,
        used_amount DECIMAL(18, 4) DEFAULT 0,
        remaining_amount DECIMAL(18, 4) DEFAULT 0,
        percentage DECIMAL(5, 2) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS cost_centers_budgets (
        id SERIAL PRIMARY KEY,
        cost_center_id INTEGER REFERENCES cost_centers(id),
        budget_id INTEGER REFERENCES budgets(id),
        allocated_amount DECIMAL(18, 4) DEFAULT 0,
        used_amount DECIMAL(18, 4) DEFAULT 0,
        fiscal_year INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS financial_reports (
        id SERIAL PRIMARY KEY,
        report_name VARCHAR(255) NOT NULL,
        report_type VARCHAR(50) NOT NULL,
        report_period VARCHAR(50),
        generated_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        parameters JSONB DEFAULT '{}',
        data JSONB DEFAULT '{}',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS report_templates (
        id SERIAL PRIMARY KEY,
        template_name VARCHAR(255) NOT NULL,
        template_type VARCHAR(50) NOT NULL,
        description TEXT,
        parameters JSONB DEFAULT '{}',
        template_content TEXT,
        is_default BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES company_users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_report_templates_type ON report_templates(template_type);

    CREATE TABLE IF NOT EXISTS asset_categories (
        id SERIAL PRIMARY KEY,
        category_code VARCHAR(50) UNIQUE,
        category_name VARCHAR(255) NOT NULL,
        category_name_en VARCHAR(255),
        description TEXT,
        depreciation_rate DECIMAL(5, 2) DEFAULT 0,
        useful_life INTEGER DEFAULT 0,
        parent_id INTEGER REFERENCES asset_categories(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS assets (
        id SERIAL PRIMARY KEY,
        company_id VARCHAR(100),
        branch_id INTEGER REFERENCES branches(id),
        name VARCHAR(255) NOT NULL,
        code VARCHAR(50) UNIQUE,
        type VARCHAR(50), -- 'tangible', 'intangible'
        purchase_date DATE,
        cost DECIMAL(18, 4) DEFAULT 0,
        residual_value DECIMAL(18, 4) DEFAULT 0,
        life_years INTEGER DEFAULT 0,
        currency VARCHAR(3) DEFAULT NULL,
        depreciation_method VARCHAR(50) DEFAULT 'straight_line',
        status VARCHAR(20) DEFAULT 'active',
        current_value DECIMAL(18, 4),
        revaluation_surplus DECIMAL(18, 4) DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS asset_depreciation_schedule (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        fiscal_year INTEGER,
        date DATE,
        amount DECIMAL(18, 4) DEFAULT 0,
        accumulated_amount DECIMAL(18, 4) DEFAULT 0,
        book_value DECIMAL(18, 4) DEFAULT 0,
        posted BOOLEAN DEFAULT FALSE,
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS asset_transfers (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        from_branch_id INTEGER REFERENCES branches(id),
        to_branch_id INTEGER REFERENCES branches(id),
        transfer_date DATE NOT NULL DEFAULT CURRENT_DATE,
        reason TEXT,
        notes TEXT,
        book_value_at_transfer DECIMAL(18, 4) DEFAULT 0,
        approved_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_asset_transfers_asset ON asset_transfers(asset_id);
    CREATE INDEX IF NOT EXISTS idx_asset_transfers_status ON asset_transfers(status);

    
    CREATE TABLE IF NOT EXISTS asset_disposals (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        disposal_date DATE NOT NULL,
        disposal_method VARCHAR(50),
        disposal_value DECIMAL(18, 4) DEFAULT 0,
        disposal_reason TEXT,
        buyer_name VARCHAR(255),
        buyer_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
        notes TEXT,
        approved_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== ASSET ADVANCED (Revaluations, Insurance, Maintenance) =====
    CREATE TABLE IF NOT EXISTS asset_revaluations (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        revaluation_date DATE NOT NULL,
        old_value DECIMAL(18, 4) NOT NULL,
        new_value DECIMAL(18, 4) NOT NULL,
        difference DECIMAL(18, 4) NOT NULL,
        reason TEXT,
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS asset_insurance (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        policy_number VARCHAR(100),
        insurer VARCHAR(255),
        coverage_type VARCHAR(100),
        premium_amount DECIMAL(18, 4) DEFAULT 0,
        coverage_amount DECIMAL(18, 4) DEFAULT 0,
        start_date DATE,
        end_date DATE,
        status VARCHAR(30) DEFAULT 'active',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS asset_maintenance (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        maintenance_type VARCHAR(50) DEFAULT 'preventive',
        description TEXT,
        scheduled_date DATE,
        completed_date DATE,
        cost DECIMAL(18, 4) DEFAULT 0,
        vendor VARCHAR(255),
        status VARCHAR(30) DEFAULT 'scheduled',
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_asset_revaluations_asset ON asset_revaluations(asset_id);
    CREATE INDEX IF NOT EXISTS idx_asset_insurance_asset ON asset_insurance(asset_id);
    CREATE INDEX IF NOT EXISTS idx_asset_maintenance_asset ON asset_maintenance(asset_id);

    -- ===== TAX TABLES (4) =====
    CREATE TABLE IF NOT EXISTS tax_rates (
        id SERIAL PRIMARY KEY,
        tax_code VARCHAR(50) UNIQUE,
        tax_name VARCHAR(255) NOT NULL,
        tax_name_en VARCHAR(255),
        rate_type VARCHAR(20) DEFAULT 'percentage',
        rate_value DECIMAL(10, 4) DEFAULT 0,
        country_code VARCHAR(5) DEFAULT NULL,
        jurisdiction_code VARCHAR(10),
        description TEXT,
        effective_from DATE,
        effective_to DATE,
        is_default BOOLEAN DEFAULT FALSE,
        legal_entity_id INTEGER,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tax_rate_history (
        id SERIAL PRIMARY KEY,
        tax_rate_id INTEGER NOT NULL REFERENCES tax_rates(id) ON DELETE CASCADE,
        changed_by INTEGER NOT NULL REFERENCES company_users(id),
        old_rate DECIMAL(10, 4),
        new_rate DECIMAL(10, 4),
        old_name VARCHAR(255),
        new_name VARCHAR(255),
        old_country VARCHAR(5),
        new_country VARCHAR(5),
        reason TEXT,
        changed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_tax_rate_history_rate ON tax_rate_history(tax_rate_id);
    CREATE INDEX IF NOT EXISTS idx_tax_rate_history_date ON tax_rate_history(changed_at);

    CREATE INDEX IF NOT EXISTS idx_tax_rates_country_active ON tax_rates(country_code, is_active, is_default);
    
    CREATE TABLE IF NOT EXISTS tax_groups (
        id SERIAL PRIMARY KEY,
        group_code VARCHAR(50) UNIQUE,
        group_name VARCHAR(255) NOT NULL,
        group_name_en VARCHAR(255),
        description TEXT,
        tax_ids JSONB DEFAULT '[]',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tax_classifications (
        id           SERIAL PRIMARY KEY,
        code         VARCHAR(50) UNIQUE NOT NULL,
        name_ar      VARCHAR(100) NOT NULL,
        name_en      VARCHAR(100) NOT NULL,
        description  TEXT,
        is_active    BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tax_classification_rates (
        id                    SERIAL PRIMARY KEY,
        classification_id     INT NOT NULL REFERENCES tax_classifications(id) ON DELETE CASCADE,
        country_code          VARCHAR(5) NOT NULL,
        tax_rate_id           INT REFERENCES tax_rates(id) ON DELETE SET NULL,
        tax_group_id          INT REFERENCES tax_groups(id) ON DELETE SET NULL,
        effective_from        DATE NOT NULL DEFAULT CURRENT_DATE,
        effective_to          DATE NULL,
        created_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(classification_id, country_code, effective_from)
    );
    CREATE INDEX IF NOT EXISTS idx_tcr_country
        ON tax_classification_rates(country_code, effective_from);
    CREATE INDEX IF NOT EXISTS idx_tcr_classification
        ON tax_classification_rates(classification_id);
    
    CREATE TABLE IF NOT EXISTS tax_returns (
        id SERIAL PRIMARY KEY,
        return_number VARCHAR(50) UNIQUE,
        tax_period VARCHAR(50),
        tax_type VARCHAR(50) NOT NULL,
        taxable_amount DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        penalty_amount DECIMAL(18, 4) DEFAULT 0,
        interest_amount DECIMAL(18, 4) DEFAULT 0,
        total_amount DECIMAL(18, 4) DEFAULT 0,
        due_date DATE,
        filed_date DATE,
        status VARCHAR(20) DEFAULT 'draft',
        branch_id INTEGER REFERENCES branches(id),
        jurisdiction_code VARCHAR(2),
        currency VARCHAR(3),
        base_currency VARCHAR(3),
        display_currency VARCHAR(3),
        exchange_rate NUMERIC(18,6) DEFAULT 1,
        calculation_version VARCHAR(40),
        calculation_details JSONB DEFAULT '{}',
        idempotency_key VARCHAR(120),
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_returns_idempotency
        ON tax_returns (idempotency_key) WHERE idempotency_key IS NOT NULL;
    
    CREATE TABLE IF NOT EXISTS tax_payments (
        id SERIAL PRIMARY KEY,
        payment_number VARCHAR(50) UNIQUE,
        tax_return_id INTEGER REFERENCES tax_returns(id),
        branch_id INTEGER REFERENCES branches(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        payment_date DATE NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        payment_method VARCHAR(50),
        reference VARCHAR(100),
        status VARCHAR(20) DEFAULT 'pending',
        currency VARCHAR(3),
        base_currency VARCHAR(3),
        exchange_rate NUMERIC(18,6) DEFAULT 1,
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        idempotency_key VARCHAR(120),
        calculation_version VARCHAR(40),
        calculation_details JSONB DEFAULT '{}',
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_payments_idempotency
        ON tax_payments (idempotency_key) WHERE idempotency_key IS NOT NULL;
    
    -- ===== TAX COMPLIANCE TABLES (3) =====
    CREATE TABLE IF NOT EXISTS tax_regimes (
        id SERIAL PRIMARY KEY,
        country_code VARCHAR(2) NOT NULL,
        tax_type VARCHAR(50) NOT NULL,
        name_ar VARCHAR(255) NOT NULL,
        name_en VARCHAR(255) NOT NULL,
        default_rate NUMERIC(10, 4) DEFAULT 0,
        is_required BOOLEAN DEFAULT FALSE,
        applies_to VARCHAR(50) DEFAULT 'all',
        filing_frequency VARCHAR(20) DEFAULT 'quarterly',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(country_code, tax_type)
    );

    CREATE TABLE IF NOT EXISTS branch_tax_settings (
        id SERIAL PRIMARY KEY,
        branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
        tax_regime_id INTEGER NOT NULL REFERENCES tax_regimes(id) ON DELETE CASCADE,
        is_registered BOOLEAN DEFAULT FALSE,
        registration_number VARCHAR(100),
        custom_rate NUMERIC(10, 4),
        is_exempt BOOLEAN DEFAULT FALSE,
        exemption_reason TEXT,
        exemption_certificate VARCHAR(100),
        exemption_expiry DATE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(branch_id, tax_regime_id)
    );

    CREATE TABLE IF NOT EXISTS company_tax_settings (
        id SERIAL PRIMARY KEY,
        country_code VARCHAR(2) NOT NULL,
        is_vat_registered BOOLEAN DEFAULT FALSE,
        vat_number VARCHAR(50),
        zakat_number VARCHAR(50),
        tax_registration_number VARCHAR(100),
        commercial_registry VARCHAR(100),
        fiscal_year_start VARCHAR(5) DEFAULT '01-01',
        default_filing_frequency VARCHAR(20) DEFAULT 'quarterly',
        zatca_phase VARCHAR(20) DEFAULT 'none',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(country_code)
    );

    CREATE INDEX IF NOT EXISTS idx_tax_regimes_country ON tax_regimes(country_code);
    CREATE INDEX IF NOT EXISTS idx_branch_tax_settings_branch ON branch_tax_settings(branch_id);

    -- ===== PROJECTS (5) =====
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        project_code VARCHAR(50) UNIQUE,
        project_name VARCHAR(255) NOT NULL,
        project_name_en VARCHAR(255),
        description TEXT,
        customer_id INTEGER REFERENCES customers(id),
        project_type VARCHAR(50),
        status VARCHAR(20) DEFAULT 'planning',
        start_date DATE,
        end_date DATE,
        planned_budget DECIMAL(18, 4) DEFAULT 0,
        actual_cost DECIMAL(18, 4) DEFAULT 0,
        progress_percentage DECIMAL(5, 2) DEFAULT 0,
        manager_id INTEGER REFERENCES employees(id),
        branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
        contract_type VARCHAR(30) DEFAULT 'fixed_price',
        retainer_amount DECIMAL(18, 4) DEFAULT 0,
        billing_cycle VARCHAR(20),
        next_billing_date DATE,
        created_by INTEGER REFERENCES company_users(id),
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS project_tasks (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        task_name VARCHAR(255) NOT NULL,
        task_name_en VARCHAR(255),
        description TEXT,
        parent_task_id INTEGER REFERENCES project_tasks(id),
        start_date DATE,
        end_date DATE,
        planned_hours DECIMAL(10, 2) DEFAULT 0,
        actual_hours DECIMAL(10, 2) DEFAULT 0,
        progress DECIMAL(5, 2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        assigned_to INTEGER REFERENCES employees(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id);
    
    CREATE TABLE IF NOT EXISTS project_budgets (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        budget_type VARCHAR(50) NOT NULL,
        planned_amount DECIMAL(18, 4) DEFAULT 0,
        actual_amount DECIMAL(18, 4) DEFAULT 0,
        variance DECIMAL(18, 4) DEFAULT 0,
        approved_by INTEGER REFERENCES company_users(id),
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_project_budgets_project ON project_budgets(project_id);
    
    CREATE TABLE IF NOT EXISTS project_expenses (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        expense_type VARCHAR(50) NOT NULL,
        expense_date DATE NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        description TEXT,
        receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
        approved_by INTEGER REFERENCES company_users(id),
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_project_expenses_project ON project_expenses(project_id);

    CREATE TABLE IF NOT EXISTS project_revenues (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        revenue_type VARCHAR(50) NOT NULL,
        revenue_date DATE NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        description TEXT,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
        approved_by INTEGER REFERENCES company_users(id),
        status VARCHAR(20) DEFAULT 'pending',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_project_revenues_project ON project_revenues(project_id);

    CREATE TABLE IF NOT EXISTS project_documents (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        file_name VARCHAR(255) NOT NULL,
        file_url TEXT NOT NULL,
        file_type VARCHAR(50),
        uploaded_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_project_documents_project ON project_documents(project_id);

    CREATE TABLE IF NOT EXISTS project_change_orders (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        change_order_number VARCHAR(50),
        title VARCHAR(255) NOT NULL,
        description TEXT,
        change_type VARCHAR(50) DEFAULT 'scope',
        cost_impact DECIMAL(18, 4) DEFAULT 0,
        time_impact_days INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        requested_by INTEGER REFERENCES company_users(id),
        approved_by INTEGER REFERENCES company_users(id),
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    -- ===== ATTACHMENTS (3) =====
    CREATE TABLE IF NOT EXISTS document_types (
        id SERIAL PRIMARY KEY,
        type_code VARCHAR(50) UNIQUE,
        type_name VARCHAR(255) NOT NULL,
        type_name_en VARCHAR(255),
        description TEXT,
        allowed_extensions VARCHAR(255) DEFAULT 'pdf,jpg,png,doc,docx,xls,xlsx',
        max_size INTEGER DEFAULT 10485760,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS attachments (
        id SERIAL PRIMARY KEY,
        entity_type VARCHAR(50) NOT NULL,
        entity_id INTEGER NOT NULL,
        file_name VARCHAR(255) NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        file_type VARCHAR(50),
        mime_type VARCHAR(100),
        description TEXT,
        uploaded_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS document_templates (
        id SERIAL PRIMARY KEY,
        template_name VARCHAR(255) NOT NULL,
        template_type VARCHAR(50) NOT NULL,
        description TEXT,
        template_content TEXT,
        variables JSONB DEFAULT '{}',
        is_default BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    -- (Duplicate notifications table removed)
    
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER REFERENCES company_users(id),
        receiver_id INTEGER REFERENCES company_users(id),
        subject VARCHAR(255),
        body TEXT,
        message_type VARCHAR(50) DEFAULT 'internal',
        is_read BOOLEAN DEFAULT FALSE,
        read_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS email_templates (
        id SERIAL PRIMARY KEY,
        template_name VARCHAR(255) NOT NULL,
        subject VARCHAR(255),
        body TEXT,
        variables JSONB DEFAULT '{}',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== DASHBOARD LAYOUTS =====
    CREATE TABLE IF NOT EXISTS dashboard_layouts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES company_users(id),
        layout_name VARCHAR(255) DEFAULT 'default',
        widgets JSONB DEFAULT '[]'::jsonb,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== SALES TARGETS =====
    CREATE TABLE IF NOT EXISTS sales_targets (
        id SERIAL PRIMARY KEY,
        year INTEGER NOT NULL,
        month_number INTEGER NOT NULL,
        target_amount DECIMAL(18, 4) DEFAULT 0,
        branch_id INTEGER REFERENCES branches(id),
        salesperson_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_targets_unique ON sales_targets(year, month_number, COALESCE(branch_id, 0), COALESCE(salesperson_id, 0));

    CREATE INDEX IF NOT EXISTS idx_dashboard_layouts_user ON dashboard_layouts(user_id);
    CREATE INDEX IF NOT EXISTS idx_sales_targets_year ON sales_targets(year);
    """


def get_treasury_dependent_tables_sql() -> str:
    """Returns SQL for treasury dependent tables (checks, notes, expense_policies, expenses) — needs parties, payment_vouchers, etc."""
    return """
    -- ===== TREASURY DEPENDENT TABLES =====
    -- treasury_transactions, bank_reconciliations moved to get_treasury_base_tables_sql()
    -- bank_statement_lines moved to get_core_dependent_tables_sql()

    -- ===== CHECKS MANAGEMENT =====
    CREATE TABLE IF NOT EXISTS checks_receivable (
        id SERIAL PRIMARY KEY,
        check_number VARCHAR(50) NOT NULL,
        drawer_name VARCHAR(200),
        bank_name VARCHAR(200),
        branch_name VARCHAR(100),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        issue_date DATE,
        due_date DATE NOT NULL,
        collection_date DATE,
        bounce_date DATE,
        party_id INTEGER REFERENCES parties(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        collection_journal_id INTEGER REFERENCES journal_entries(id),
        bounce_journal_id INTEGER REFERENCES journal_entries(id),
        status VARCHAR(30) DEFAULT 'pending',
        bounce_reason TEXT,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS checks_payable (
        id SERIAL PRIMARY KEY,
        check_number VARCHAR(50) NOT NULL,
        beneficiary_name VARCHAR(200),
        bank_name VARCHAR(200),
        branch_name VARCHAR(100),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        issue_date DATE NOT NULL,
        due_date DATE NOT NULL,
        clearance_date DATE,
        bounce_date DATE,
        party_id INTEGER REFERENCES parties(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        payment_voucher_id INTEGER REFERENCES payment_vouchers(id) ON DELETE SET NULL,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        clearance_journal_id INTEGER REFERENCES journal_entries(id),
        bounce_journal_id INTEGER REFERENCES journal_entries(id),
        status VARCHAR(30) DEFAULT 'issued',
        bounce_reason TEXT,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== NOTES RECEIVABLE / PAYABLE =====
    CREATE TABLE IF NOT EXISTS notes_receivable (
        id SERIAL PRIMARY KEY,
        note_number VARCHAR(50) NOT NULL,
        drawer_name VARCHAR(200),
        bank_name VARCHAR(200),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        issue_date DATE,
        due_date DATE NOT NULL,
        maturity_date DATE,
        collection_date DATE,
        protest_date DATE,
        party_id INTEGER REFERENCES parties(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        collection_journal_id INTEGER REFERENCES journal_entries(id),
        protest_journal_id INTEGER REFERENCES journal_entries(id),
        status VARCHAR(20) DEFAULT 'pending',
        protest_reason TEXT,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS notes_payable (
        id SERIAL PRIMARY KEY,
        note_number VARCHAR(50) NOT NULL,
        beneficiary_name VARCHAR(200),
        bank_name VARCHAR(200),
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        issue_date DATE,
        due_date DATE NOT NULL,
        maturity_date DATE,
        payment_date DATE,
        protest_date DATE,
        party_id INTEGER REFERENCES parties(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        payment_journal_id INTEGER REFERENCES journal_entries(id),
        protest_journal_id INTEGER REFERENCES journal_entries(id),
        status VARCHAR(20) DEFAULT 'issued',
        protest_reason TEXT,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== EXPENSE POLICIES & EXPENSES =====
    CREATE TABLE IF NOT EXISTS expense_policies (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        expense_type VARCHAR(50),
        department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
        daily_limit NUMERIC(15,4) DEFAULT 0,
        monthly_limit NUMERIC(15,4) DEFAULT 0,
        annual_limit NUMERIC(15,4) DEFAULT 0,
        requires_receipt BOOLEAN DEFAULT TRUE,
        requires_approval BOOLEAN DEFAULT TRUE,
        auto_approve_below NUMERIC(15,4) DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY,
        expense_number VARCHAR(50) UNIQUE NOT NULL,
        expense_date DATE NOT NULL,
        expense_type VARCHAR(50) NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        currency VARCHAR(3),
        exchange_rate NUMERIC(18,6) DEFAULT 1,
        description TEXT,
        category VARCHAR(50) DEFAULT 'general',
        payment_method VARCHAR(50) DEFAULT 'cash',
        treasury_id INTEGER REFERENCES treasury_accounts(id),
        expense_account_id INTEGER REFERENCES accounts(id),
        cost_center_id INTEGER REFERENCES cost_centers(id),
        project_id INTEGER REFERENCES projects(id),
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        branch_id INTEGER REFERENCES branches(id),
        policy_id INTEGER REFERENCES expense_policies(id),
        approval_status VARCHAR(20) DEFAULT 'pending',
        approved_by INTEGER REFERENCES company_users(id),
        approved_at TIMESTAMPTZ,
        approval_notes TEXT,
        receipt_number VARCHAR(100),
        vendor_name VARCHAR(255),
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id),
        -- T3.13: reversal bookkeeping (alembic 0018)
        reversal_journal_entry_id INTEGER REFERENCES journal_entries(id),
        reversed_at TIMESTAMPTZ,
        reversed_by INTEGER REFERENCES company_users(id),
        reversal_reason TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_expenses_expense_date ON expenses(expense_date);
    CREATE INDEX IF NOT EXISTS idx_expenses_approval_status ON expenses(approval_status);
    CREATE INDEX IF NOT EXISTS idx_expenses_branch_id ON expenses(branch_id);
    CREATE INDEX IF NOT EXISTS idx_expenses_created_by ON expenses(created_by);
    CREATE INDEX IF NOT EXISTS idx_expenses_reversal_je
        ON expenses(reversal_journal_entry_id)
        WHERE reversal_journal_entry_id IS NOT NULL;
    """


def get_currency_tables_sql() -> str:
    """Returns SQL for Multi-Currency System tables"""
    return """
    -- ===== MULTI-CURRENCY TABLES (3) =====
    CREATE TABLE IF NOT EXISTS currencies (
        id SERIAL PRIMARY KEY,
        code VARCHAR(3) UNIQUE NOT NULL, -- USD, EUR, SAR
        name VARCHAR(100) NOT NULL,
        name_en VARCHAR(100),
        symbol VARCHAR(10),
        is_base BOOLEAN DEFAULT FALSE,
        current_rate DECIMAL(18, 6) DEFAULT 1, -- Relative to base currency
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS exchange_rates (
        id SERIAL PRIMARY KEY,
        currency_id INTEGER REFERENCES currencies(id) ON DELETE CASCADE,
        rate_date DATE NOT NULL,
        rate DECIMAL(18, 6) NOT NULL,
        source VARCHAR(50) DEFAULT 'manual', -- manual, api
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(currency_id, rate_date)
    );

    CREATE TABLE IF NOT EXISTS currency_transactions (
        id SERIAL PRIMARY KEY,
        transaction_type VARCHAR(50) NOT NULL, -- invoice, payment, journal
        transaction_id INTEGER NOT NULL, -- ID of the related record
        account_id INTEGER REFERENCES accounts(id), -- Critical for revaluation
        currency_code VARCHAR(3) NOT NULL,
        exchange_rate DECIMAL(18, 6) NOT NULL,
        amount_fc DECIMAL(18, 4) NOT NULL, -- Amount in Foreign Currency
        amount_bc DECIMAL(18, 4) NOT NULL, -- Amount in Base Currency
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_contract_tables_sql() -> str:
    """Returns SQL for Contracts & Subscriptions tables"""
    return """
    -- ===== CONTRACTS & SUBSCRIPTIONS (2) =====
    CREATE TABLE IF NOT EXISTS contracts (
        id SERIAL PRIMARY KEY,
        contract_number VARCHAR(50) UNIQUE NOT NULL,
        party_id INTEGER REFERENCES parties(id),
        contract_type VARCHAR(50) DEFAULT 'subscription', -- fixed, subscription, recurring
        status VARCHAR(20) DEFAULT 'draft', -- draft, active, expired, cancelled
        start_date DATE NOT NULL,
        end_date DATE,
        billing_interval VARCHAR(20) DEFAULT 'monthly', -- monthly, quarterly, yearly
        next_billing_date DATE,
        total_amount DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT 'SAR',
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS contract_items (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER REFERENCES contracts(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        description TEXT,
        quantity DECIMAL(18, 4) DEFAULT 1,
        unit_price DECIMAL(18, 4) DEFAULT 0,
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        total DECIMAL(18, 4) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_contract_items_contract ON contract_items(contract_id);
    CREATE INDEX IF NOT EXISTS idx_contract_items_tax_rate ON contract_items(tax_rate_id);

    -- CON-F1: contract milestone-based billing
    CREATE TABLE IF NOT EXISTS contract_milestones (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
        sequence INTEGER DEFAULT 1,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        due_date DATE,
        amount DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'billed', 'cancelled')),
        completed_at TIMESTAMPTZ,
        billed_at TIMESTAMPTZ,
        invoice_id INTEGER REFERENCES invoices(id),
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_contract_milestones_contract ON contract_milestones(contract_id);
    CREATE INDEX IF NOT EXISTS idx_contract_milestones_status ON contract_milestones(status, due_date);
    """


def get_costing_policy_tables_sql() -> str:
    """Returns SQL for Costing Policy tables"""
    return """
    -- ===== COSTING POLICY TABLES (3) =====
    CREATE TABLE IF NOT EXISTS costing_policies (
        id SERIAL PRIMARY KEY,
        policy_name VARCHAR(100) NOT NULL,
        policy_type VARCHAR(50) NOT NULL, -- global_wac, per_warehouse_wac, hybrid, smart
        description TEXT,
        is_active BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER,
        updated_by INTEGER
    );

    CREATE TABLE IF NOT EXISTS costing_policy_details (
        id SERIAL PRIMARY KEY,
        policy_id INTEGER NOT NULL REFERENCES costing_policies(id) ON DELETE CASCADE,
        setting_key VARCHAR(100) NOT NULL,
        setting_value VARCHAR(500)
    );

    CREATE TABLE IF NOT EXISTS costing_policy_history (
        id SERIAL PRIMARY KEY,
        old_policy_type VARCHAR(50),
        new_policy_type VARCHAR(50),
        change_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        changed_by INTEGER,
        reason TEXT,
        affected_products_count INTEGER,
        total_cost_impact DECIMAL(18, 4),
        status VARCHAR(20) DEFAULT 'completed'
    );

    CREATE TABLE IF NOT EXISTS inventory_cost_snapshots (
        id SERIAL PRIMARY KEY,
        warehouse_id INTEGER REFERENCES warehouses(id) ON DELETE SET NULL,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        average_cost DECIMAL(18, 4),
        quantity DECIMAL(18, 4),
        policy_type VARCHAR(50),
        snapshot_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_advanced_inventory_tables_sql() -> str:
    """Returns SQL for advanced inventory tables (Batch, Serial, Expiry, QC, Cycle Counts)"""
    return """
    ALTER TABLE products ADD COLUMN IF NOT EXISTS has_batch_tracking BOOLEAN DEFAULT FALSE;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS has_serial_tracking BOOLEAN DEFAULT FALSE;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS has_expiry_tracking BOOLEAN DEFAULT FALSE;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER DEFAULT 0;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS expiry_alert_days INTEGER DEFAULT 30;

    -- ===== BATCH NUMBERS (INV-101) =====
    CREATE TABLE IF NOT EXISTS product_batches (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id),
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        batch_number VARCHAR(100) NOT NULL,
        manufacturing_date DATE,
        expiry_date DATE,
        quantity DECIMAL(18, 4) DEFAULT 0,
        available_quantity DECIMAL(18, 4) DEFAULT 0,
        unit_cost DECIMAL(18, 4) DEFAULT 0,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
        reference_type VARCHAR(50),
        reference_id INTEGER,
        status VARCHAR(20) DEFAULT 'active',
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_id, warehouse_id, batch_number)
    );

    -- ===== SERIAL NUMBERS (INV-102) =====
    CREATE TABLE IF NOT EXISTS product_serials (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        serial_number VARCHAR(200) NOT NULL,
        batch_id INTEGER REFERENCES product_batches(id),
        status VARCHAR(20) DEFAULT 'available',
        purchase_date DATE,
        purchase_reference VARCHAR(100),
        purchase_price DECIMAL(18, 4) DEFAULT 0,
        sale_date DATE,
        sale_reference VARCHAR(100),
        sale_price DECIMAL(18, 4) DEFAULT 0,
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
        warranty_start DATE,
        warranty_end DATE,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_id, serial_number)
    );

    -- ===== BATCH/SERIAL MOVEMENT LOG =====
    CREATE TABLE IF NOT EXISTS batch_serial_movements (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id),
        batch_id INTEGER REFERENCES product_batches(id),
        serial_id INTEGER REFERENCES product_serials(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        movement_type VARCHAR(50) NOT NULL,
        reference_type VARCHAR(50),
        reference_id INTEGER,
        quantity DECIMAL(18, 4) DEFAULT 1,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== QUALITY CONTROL (INV-104) =====
    CREATE TABLE IF NOT EXISTS quality_inspections (
        id SERIAL PRIMARY KEY,
        inspection_number VARCHAR(50) UNIQUE,
        inspection_type VARCHAR(50) NOT NULL,
        product_id INTEGER NOT NULL REFERENCES products(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        batch_id INTEGER REFERENCES product_batches(id),
        reference_type VARCHAR(50),
        reference_id INTEGER,
        inspected_quantity DECIMAL(18, 4) DEFAULT 0,
        accepted_quantity DECIMAL(18, 4) DEFAULT 0,
        rejected_quantity DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        result_notes TEXT,
        rejection_reason TEXT,
        inspector_id INTEGER REFERENCES company_users(id),
        inspection_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        completed_date TIMESTAMPTZ,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS quality_inspection_criteria (
        id SERIAL PRIMARY KEY,
        inspection_id INTEGER NOT NULL REFERENCES quality_inspections(id) ON DELETE CASCADE,
        criteria_name VARCHAR(255) NOT NULL,
        expected_value VARCHAR(255),
        actual_value VARCHAR(255),
        is_passed BOOLEAN DEFAULT FALSE,
        notes TEXT
    );

    -- ===== CYCLE COUNTS (INV-105) =====
    CREATE TABLE IF NOT EXISTS cycle_counts (
        id SERIAL PRIMARY KEY,
        count_number VARCHAR(50) UNIQUE,
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        count_type VARCHAR(50) DEFAULT 'full',
        status VARCHAR(20) DEFAULT 'draft',
        scheduled_date DATE,
        start_date TIMESTAMPTZ,
        end_date TIMESTAMPTZ,
        total_items INTEGER DEFAULT 0,
        counted_items INTEGER DEFAULT 0,
        variance_items INTEGER DEFAULT 0,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS cycle_count_items (
        id SERIAL PRIMARY KEY,
        cycle_count_id INTEGER NOT NULL REFERENCES cycle_counts(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        batch_id INTEGER REFERENCES product_batches(id),
        system_quantity DECIMAL(18, 4) DEFAULT 0,
        counted_quantity DECIMAL(18, 4),
        variance DECIMAL(18, 4) DEFAULT 0,
        variance_value DECIMAL(18, 4) DEFAULT 0,
        unit_cost DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        counted_by INTEGER REFERENCES company_users(id),
        counted_at TIMESTAMPTZ,
        notes TEXT
    );
    """


def get_advanced_inventory_phase2_tables_sql() -> str:
    """Returns SQL for Phase 2 advanced inventory: Variants, Bins, Kits"""
    return """
    -- ===== PRODUCT ATTRIBUTES & VARIANTS (INV-106) =====
    CREATE TABLE IF NOT EXISTS product_attributes (
        id SERIAL PRIMARY KEY,
        attribute_name VARCHAR(100) NOT NULL,
        attribute_name_en VARCHAR(100),
        attribute_type VARCHAR(50) DEFAULT 'select',
        sort_order INTEGER DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_attribute_values (
        id SERIAL PRIMARY KEY,
        attribute_id INTEGER NOT NULL REFERENCES product_attributes(id) ON DELETE CASCADE,
        value_name VARCHAR(100) NOT NULL,
        value_name_en VARCHAR(100),
        color_code VARCHAR(20),
        sort_order INTEGER DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_variants (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        variant_code VARCHAR(100),
        variant_name VARCHAR(255),
        sku VARCHAR(100),
        barcode VARCHAR(100),
        cost_price DECIMAL(15,2) DEFAULT 0,
        selling_price DECIMAL(15,2) DEFAULT 0,
        weight DECIMAL(10,3),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_variant_attributes (
        id SERIAL PRIMARY KEY,
        variant_id INTEGER NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
        attribute_id INTEGER NOT NULL REFERENCES product_attributes(id),
        attribute_value_id INTEGER NOT NULL REFERENCES product_attribute_values(id),
        UNIQUE(variant_id, attribute_id)
    );

    -- ===== BIN LOCATIONS (INV-107) =====
    CREATE TABLE IF NOT EXISTS bin_locations (
        id SERIAL PRIMARY KEY,
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
        bin_code VARCHAR(50) NOT NULL,
        bin_name VARCHAR(100),
        zone VARCHAR(50),
        aisle VARCHAR(20),
        rack VARCHAR(20),
        shelf VARCHAR(20),
        position VARCHAR(20),
        bin_type VARCHAR(30) DEFAULT 'storage',
        max_weight DECIMAL(10,2),
        max_volume DECIMAL(10,2),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(warehouse_id, bin_code)
    );

    CREATE TABLE IF NOT EXISTS bin_inventory (
        id SERIAL PRIMARY KEY,
        bin_id INTEGER NOT NULL REFERENCES bin_locations(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        batch_id INTEGER REFERENCES product_batches(id),
        quantity DECIMAL(15,4) DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(bin_id, product_id, batch_id)
    );

    -- ===== PRODUCT KITS (INV-108) =====
    CREATE TABLE IF NOT EXISTS product_kits (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        kit_name VARCHAR(200),
        kit_type VARCHAR(30) DEFAULT 'fixed',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_kit_items (
        id SERIAL PRIMARY KEY,
        kit_id INTEGER NOT NULL REFERENCES product_kits(id) ON DELETE CASCADE,
        component_product_id INTEGER NOT NULL REFERENCES products(id),
        quantity DECIMAL(15,4) NOT NULL DEFAULT 1,
        unit_cost DECIMAL(15,2),
        sort_order INTEGER DEFAULT 0,
        notes TEXT
    );

    ALTER TABLE products ADD COLUMN IF NOT EXISTS has_variants BOOLEAN DEFAULT FALSE;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS is_kit BOOLEAN DEFAULT FALSE;
    """


def get_manufacturing_tables_sql() -> str:
    """SQL for Advanced Manufacturing (Phase 5)"""
    return """
    -- ===== WORK CENTERS (MFG-001) =====
    CREATE TABLE IF NOT EXISTS work_centers (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        code VARCHAR(50) UNIQUE,
        capacity_per_day DECIMAL(5, 2) DEFAULT 8.0, -- hours
        cost_per_hour DECIMAL(18, 4) DEFAULT 0,
        location VARCHAR(100),
        cost_center_id INTEGER REFERENCES cost_centers(id), -- For linking to Cost Accounting
        default_expense_account_id INTEGER REFERENCES accounts(id), -- For Overhead Absorption
        status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'maintenance')),
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== ROUTING (MFG-002) =====
    CREATE TABLE IF NOT EXISTS manufacturing_routes (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        product_id INTEGER REFERENCES products(id), -- Default route for product
        bom_id INTEGER, -- FK to bill_of_materials (circular dep, enforced at app level)
        is_default BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        description TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS manufacturing_operations (
        id SERIAL PRIMARY KEY,
        route_id INTEGER REFERENCES manufacturing_routes(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        name VARCHAR(255),
        work_center_id INTEGER REFERENCES work_centers(id),
        description VARCHAR(255),
        setup_time DECIMAL(8, 2) DEFAULT 0, -- minutes
        cycle_time DECIMAL(8, 2) DEFAULT 0, -- minutes per unit
        labor_rate_per_hour DECIMAL(10, 2) DEFAULT 0,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== BILL OF MATERIALS (MFG-003) =====
    CREATE TABLE IF NOT EXISTS bill_of_materials (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id), -- Output Product
        code VARCHAR(50),
        name VARCHAR(255),
        yield_quantity DECIMAL(15, 4) DEFAULT 1.0,
        route_id INTEGER REFERENCES manufacturing_routes(id),
        is_active BOOLEAN DEFAULT TRUE,
        notes TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS bom_components (
        id SERIAL PRIMARY KEY,
        bom_id INTEGER REFERENCES bill_of_materials(id) ON DELETE CASCADE,
        component_product_id INTEGER REFERENCES products(id), -- Input Material
        quantity DECIMAL(15, 4) NOT NULL,
        waste_percentage DECIMAL(5, 2) DEFAULT 0,
        cost_share_percentage DECIMAL(5, 2) DEFAULT 0,
        is_percentage BOOLEAN DEFAULT FALSE, -- Variable BOM: quantity = % of order qty
        notes TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== BY-PRODUCTS (MFG-010) =====
    CREATE TABLE IF NOT EXISTS bom_outputs (
        id SERIAL PRIMARY KEY,
        bom_id INTEGER REFERENCES bill_of_materials(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id), -- Output Product (By-product)
        quantity DECIMAL(15, 4) NOT NULL,
        cost_allocation_percentage DECIMAL(5, 2) DEFAULT 0,
        notes TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== PRODUCTION ORDERS (MFG-004) =====
    CREATE TABLE IF NOT EXISTS production_orders (
        id SERIAL PRIMARY KEY,
        order_number VARCHAR(50) UNIQUE,
        product_id INTEGER REFERENCES products(id),
        bom_id INTEGER REFERENCES bill_of_materials(id),
        route_id INTEGER REFERENCES manufacturing_routes(id),
        quantity DECIMAL(15, 4) NOT NULL,
        produced_quantity DECIMAL(15, 4) DEFAULT 0,
        scrapped_quantity DECIMAL(15, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'in_progress', 'completed', 'cancelled')),
        start_date DATE,
        due_date DATE,
        warehouse_id INTEGER REFERENCES warehouses(id),
        destination_warehouse_id INTEGER REFERENCES warehouses(id),
        branch_id INTEGER REFERENCES branches(id),
        -- Costing columns
        actual_material_cost DECIMAL(18, 4) DEFAULT 0,
        actual_labor_cost DECIMAL(18, 4) DEFAULT 0,
        actual_overhead_cost DECIMAL(18, 4) DEFAULT 0,
        actual_total_cost DECIMAL(18, 4) DEFAULT 0,
        standard_cost DECIMAL(18, 4) DEFAULT 0,
        variance_amount DECIMAL(18, 4) DEFAULT 0,
        variance_percentage DECIMAL(8, 4) DEFAULT 0,
        costing_status VARCHAR(20) DEFAULT 'pending',
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== MANUFACTURING ORDERS (MFG-004b) =====
    -- Feature-023 style orders: tenant-scoped, state machine, BOM snapshot,
    -- partial completions, QC gate, approval workflow.
    CREATE TABLE IF NOT EXISTS manufacturing_orders (
        id                  BIGSERIAL       PRIMARY KEY,
        tenant_id           BIGINT          NOT NULL,
        order_number        VARCHAR(64),
        product_id          INTEGER         REFERENCES products(id),
        bom_id              INTEGER         REFERENCES bill_of_materials(id),
        workstation_id      INTEGER         REFERENCES work_centers(id),
        original_qty        NUMERIC(18,4)   NOT NULL DEFAULT 0,
        planned_qty         NUMERIC(18,4)   NOT NULL DEFAULT 0,
        completed_qty       NUMERIC(18,4)   NOT NULL DEFAULT 0,
        remaining_qty       NUMERIC(18,4),
        bom_snapshot_id     BIGINT,
        state               VARCHAR(32)     NOT NULL DEFAULT 'planned',
        qc_required         BOOLEAN         NOT NULL DEFAULT FALSE,
        requires_approval   BOOLEAN         NOT NULL DEFAULT FALSE,
        approved_by         BIGINT,
        approved_at         TIMESTAMPTZ,
        start_date          DATE,
        due_date            DATE,
        warehouse_id        INTEGER         REFERENCES warehouses(id),
        branch_id           INTEGER         REFERENCES branches(id),
        notes               TEXT,
        created_by          INTEGER         REFERENCES company_users(id),
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE manufacturing_orders ADD CONSTRAINT chk_mo_state
            CHECK (state IN ('planned','pending_approval','released','in_progress','qc_pending','completed','cancelled'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE INDEX IF NOT EXISTS idx_manufacturing_orders_tenant_state
        ON manufacturing_orders (tenant_id, state);
    CREATE INDEX IF NOT EXISTS idx_manufacturing_orders_product
        ON manufacturing_orders (tenant_id, product_id);

    CREATE TABLE IF NOT EXISTS production_order_operations (
        id SERIAL PRIMARY KEY,
        production_order_id INTEGER REFERENCES production_orders(id) ON DELETE CASCADE,
        operation_id INTEGER REFERENCES manufacturing_operations(id),
        work_center_id INTEGER REFERENCES work_centers(id),
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped', 'paused')),
        worker_id INTEGER REFERENCES company_users(id),
        actual_setup_time DECIMAL(8, 2) DEFAULT 0,
        actual_run_time DECIMAL(8, 2) DEFAULT 0,
        completed_quantity DECIMAL(15, 4) DEFAULT 0,
        scrapped_quantity DECIMAL(15, 4) DEFAULT 0,
        planned_start_time TIMESTAMPTZ,
        planned_end_time TIMESTAMPTZ,
        start_time TIMESTAMPTZ,
        end_time TIMESTAMPTZ,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== MRP - Material Requirements Planning (MFG-005) =====
    CREATE TABLE IF NOT EXISTS mrp_plans (
        id SERIAL PRIMARY KEY,
        plan_name VARCHAR(255) NOT NULL,
        production_order_id INTEGER REFERENCES production_orders(id) ON DELETE CASCADE,
        status VARCHAR(50) DEFAULT 'draft', -- draft, confirmed, converted
        calculated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        created_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS mrp_items (
        id SERIAL PRIMARY KEY,
        mrp_plan_id INTEGER REFERENCES mrp_plans(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        required_quantity DECIMAL(18, 4) NOT NULL,
        available_quantity DECIMAL(18, 4) DEFAULT 0,
        on_hand_quantity DECIMAL(18, 4) DEFAULT 0,
        on_order_quantity DECIMAL(18, 4) DEFAULT 0,
        shortage_quantity DECIMAL(18, 4) DEFAULT 0,
        lead_time_days INTEGER DEFAULT 0,
        suggested_action VARCHAR(50), -- purchase_order, transfer, production_order
        status VARCHAR(50) DEFAULT 'pending'
    );

    -- ===== IN-PROCESS QC CHECKS (MFG-108) =====
    CREATE TABLE IF NOT EXISTS mfg_qc_checks (
        id SERIAL PRIMARY KEY,
        production_order_id INTEGER REFERENCES production_orders(id) ON DELETE CASCADE,
        operation_id INTEGER REFERENCES manufacturing_operations(id),
        check_name VARCHAR(200) NOT NULL,
        check_type VARCHAR(30) DEFAULT 'visual' CHECK (check_type IN ('visual','measurement','test','weight','count')),
        specification TEXT,
        actual_value VARCHAR(200),
        result VARCHAR(20) DEFAULT 'pending' CHECK (result IN ('pending','pass','fail','warning')),
        failure_action VARCHAR(20) DEFAULT 'warn' CHECK (failure_action IN ('stop','warn','continue')),
        checked_by INTEGER REFERENCES company_users(id),
        notes TEXT,
        checked_at TIMESTAMPTZ,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== EQUIPMENT & MAINTENANCE (MFG-011) =====
    CREATE TABLE IF NOT EXISTS manufacturing_equipment (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        code VARCHAR(50) UNIQUE,
        work_center_id INTEGER REFERENCES work_centers(id),
        status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'broken', 'retired')),
        purchase_date DATE,
        last_maintenance_date DATE,
        next_maintenance_date DATE,
        notes TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS maintenance_logs (
        id SERIAL PRIMARY KEY,
        equipment_id INTEGER REFERENCES manufacturing_equipment(id) ON DELETE CASCADE,
        maintenance_type VARCHAR(50) NOT NULL, -- preventive, corrective, breakdown
        description TEXT,
        cost DECIMAL(18, 4) DEFAULT 0,
        performed_by INTEGER REFERENCES company_users(id),
        external_service_provider VARCHAR(255),
        maintenance_date DATE NOT NULL,
        next_due_date DATE,
        status VARCHAR(20) DEFAULT 'completed',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS project_timesheets (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES company_users(id),
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        task_id INTEGER REFERENCES project_tasks(id),
        date DATE NOT NULL,
        hours DECIMAL(5, 2) NOT NULL,
        description TEXT,
        status VARCHAR(20) DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== SVC-001: SERVICE / MAINTENANCE REQUESTS =====
    CREATE TABLE IF NOT EXISTS service_requests (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        category VARCHAR(100) DEFAULT 'maintenance',
        priority VARCHAR(50) DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
        status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'assigned', 'in_progress', 'on_hold', 'completed', 'cancelled')),
        customer_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
        asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
        assigned_to INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        assigned_at TIMESTAMPTZ,
        estimated_hours DECIMAL(8, 2),
        actual_hours DECIMAL(8, 2),
        hourly_rate NUMERIC(15, 4),
        estimated_cost DECIMAL(15, 2) DEFAULT 0,
        actual_cost DECIMAL(15, 2) DEFAULT 0,
        scheduled_date DATE,
        completion_date DATE,
        location TEXT,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS service_request_costs (
        id SERIAL PRIMARY KEY,
        service_request_id INTEGER REFERENCES service_requests(id) ON DELETE CASCADE,
        cost_type VARCHAR(50) DEFAULT 'other' CHECK (cost_type IN ('labor', 'parts', 'travel', 'other')),
        description TEXT,
        quantity DECIMAL(10, 4) DEFAULT 1,
        unit_cost DECIMAL(15, 2) DEFAULT 0,
        markup_pct NUMERIC(8, 4) DEFAULT 0,
        total_cost DECIMAL(15, 2) DEFAULT 0,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );
    -- T10.1 P1 #76 / #110j — link parts consumption to actual inventory
    -- so add_service_cost can decrement on-hand and the close-out JE can
    -- credit acc_map_inventory instead of a generic clearing account.
    ALTER TABLE service_request_costs ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id);
    ALTER TABLE service_request_costs ADD COLUMN IF NOT EXISTS warehouse_id INTEGER REFERENCES warehouses(id);
    ALTER TABLE service_request_costs ADD COLUMN IF NOT EXISTS markup_pct NUMERIC(8, 4) DEFAULT 0;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC(15, 4);

    -- ===== SVC-002: DOCUMENT MANAGEMENT =====
    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        doc_number VARCHAR(50),
        title VARCHAR(255) NOT NULL,
        description TEXT,
        category VARCHAR(100) DEFAULT 'general',
        file_name VARCHAR(255),
        file_path TEXT,
        file_size INTEGER,
        mime_type VARCHAR(100),
        tags JSONB DEFAULT '[]',
        access_level VARCHAR(50) DEFAULT 'company',
        related_module VARCHAR(100),
        related_id INTEGER,
        current_version INTEGER DEFAULT 1,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_documents_related ON documents(related_module, related_id);
    CREATE INDEX IF NOT EXISTS idx_documents_created_by ON documents(created_by);

    CREATE TABLE IF NOT EXISTS document_versions (
        id SERIAL PRIMARY KEY,
        document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL DEFAULT 1,
        file_name VARCHAR(255),
        file_path TEXT,
        file_size INTEGER,
        change_notes TEXT,
        uploaded_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_pos_tables_sql() -> str:
    """Returns SQL for POS module tables"""
    return """
    -- ===== POS TABLES =====
    CREATE TABLE IF NOT EXISTS pos_sessions (
        id SERIAL PRIMARY KEY,
        session_code VARCHAR(50) UNIQUE,
        pos_profile_id INTEGER, 
        user_id INTEGER REFERENCES company_users(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        opening_balance DECIMAL(18, 4) DEFAULT 0,
        closing_balance DECIMAL(18, 4) DEFAULT 0,
        total_sales DECIMAL(18, 4) DEFAULT 0,
        total_returns DECIMAL(18, 4) DEFAULT 0,
        cash_register_balance DECIMAL(18, 4) DEFAULT 0,
        difference DECIMAL(18, 4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'opened', 
        opened_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        closed_at TIMESTAMPTZ,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_orders (
        id SERIAL PRIMARY KEY,
        order_number VARCHAR(50) UNIQUE NOT NULL,
        session_id INTEGER REFERENCES pos_sessions(id) ON DELETE CASCADE,
        customer_id INTEGER REFERENCES customers(id),
        walk_in_customer_name VARCHAR(255),
        branch_id INTEGER REFERENCES branches(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        order_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'draft', 
        client_order_id VARCHAR(100),
        
        -- Money Fields
        subtotal DECIMAL(18, 4) DEFAULT 0,
        discount_type VARCHAR(20) DEFAULT 'amount',
        discount_amount DECIMAL(18, 4) DEFAULT 0,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        total_amount DECIMAL(18, 4) DEFAULT 0,
        paid_amount DECIMAL(18, 4) DEFAULT 0,
        change_amount DECIMAL(18, 4) DEFAULT 0,
        
        note TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_order_lines (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        description VARCHAR(255),
        quantity DECIMAL(18, 4) NOT NULL DEFAULT 1,
        original_price DECIMAL(18, 4) NOT NULL,
        unit_price DECIMAL(18, 4) NOT NULL, 
        tax_rate DECIMAL(5, 2) DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        applied_taxes JSONB,
        tax_amount DECIMAL(18, 4) DEFAULT 0,
        discount_percentage DECIMAL(5, 2) DEFAULT 0,
        discount_amount DECIMAL(18, 4) DEFAULT 0,
        subtotal DECIMAL(18, 4) NOT NULL, 
        total DECIMAL(18, 4) NOT NULL,    
        
        warehouse_id INTEGER REFERENCES warehouses(id),
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );
    CREATE INDEX IF NOT EXISTS idx_pos_order_lines_tax_rate ON pos_order_lines(tax_rate_id);

    CREATE TABLE IF NOT EXISTS pos_payments (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE CASCADE,
        session_id INTEGER REFERENCES pos_sessions(id),
        payment_method VARCHAR(50) NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        reference_number VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    -- POS Order Payments (per-order payment method breakdown)
    CREATE TABLE IF NOT EXISTS pos_order_payments (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE CASCADE,
        method VARCHAR(50) NOT NULL,
        amount DECIMAL(18, 4) NOT NULL,
        reference VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    -- POS Returns
    CREATE TABLE IF NOT EXISTS pos_returns (
        id SERIAL PRIMARY KEY,
        original_order_id INTEGER REFERENCES pos_orders(id),
        user_id INTEGER REFERENCES company_users(id),
        session_id INTEGER REFERENCES pos_sessions(id),
        refund_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
        refund_method VARCHAR(50) DEFAULT 'cash',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_return_items (
        id SERIAL PRIMARY KEY,
        return_id INTEGER REFERENCES pos_returns(id) ON DELETE CASCADE,
        original_item_id INTEGER REFERENCES pos_order_lines(id) ON DELETE SET NULL,
        quantity DECIMAL(18, 4) NOT NULL DEFAULT 1,
        reason TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    -- POS Promotions
    CREATE TABLE IF NOT EXISTS pos_promotions (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        promotion_type VARCHAR(50) NOT NULL DEFAULT 'percentage',
        value NUMERIC(15, 2) NOT NULL DEFAULT 0,
        buy_qty INTEGER,
        get_qty INTEGER,
        coupon_code VARCHAR(100),
        applicable_products TEXT,
        applicable_categories TEXT,
        min_order_amount NUMERIC(15, 2) DEFAULT 0,
        start_date TIMESTAMPTZ,
        end_date TIMESTAMPTZ,
        is_active BOOLEAN DEFAULT TRUE,
        branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        updated_by VARCHAR(100)
    );

    -- POS Loyalty Programs
    CREATE TABLE IF NOT EXISTS pos_loyalty_programs (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        points_per_unit NUMERIC(10, 4) DEFAULT 1,
        currency_per_point NUMERIC(10, 4) DEFAULT 0.01,
        min_points_redeem INTEGER DEFAULT 100,
        tier_rules JSONB DEFAULT '[]'::jsonb,
        is_active BOOLEAN DEFAULT TRUE,
        branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_loyalty_points (
        id SERIAL PRIMARY KEY,
        program_id INTEGER REFERENCES pos_loyalty_programs(id),
        party_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
        points_earned NUMERIC(12, 2) DEFAULT 0,
        points_redeemed NUMERIC(12, 2) DEFAULT 0,
        balance NUMERIC(12, 2) DEFAULT 0,
        tier VARCHAR(50) DEFAULT 'standard',
        last_activity_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_loyalty_transactions (
        id SERIAL PRIMARY KEY,
        loyalty_id INTEGER REFERENCES pos_loyalty_points(id),
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE SET NULL,
        txn_type VARCHAR(20) NOT NULL,
        points NUMERIC(12, 2) NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    -- POS Tables (Restaurant/Dine-in)
    CREATE TABLE IF NOT EXISTS pos_tables (
        id SERIAL PRIMARY KEY,
        table_number VARCHAR(50) NOT NULL,
        table_name VARCHAR(100),
        floor VARCHAR(50) DEFAULT 'main',
        capacity INTEGER DEFAULT 4,
        status VARCHAR(20) DEFAULT 'available',
        shape VARCHAR(20) DEFAULT 'square',
        pos_x NUMERIC(8, 2) DEFAULT 0,
        pos_y NUMERIC(8, 2) DEFAULT 0,
        branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS pos_table_orders (
        id SERIAL PRIMARY KEY,
        table_id INTEGER REFERENCES pos_tables(id),
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE SET NULL,
        seated_at TIMESTAMPTZ DEFAULT NOW(),
        cleared_at TIMESTAMPTZ,
        guests INTEGER DEFAULT 1,
        waiter_id INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        status VARCHAR(20) DEFAULT 'seated',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    -- POS Kitchen Display
    CREATE TABLE IF NOT EXISTS pos_kitchen_orders (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES pos_orders(id) ON DELETE SET NULL,
        order_line_id INTEGER REFERENCES pos_order_lines(id) ON DELETE SET NULL,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name VARCHAR(255),
        quantity NUMERIC(12, 3),
        notes TEXT,
        station VARCHAR(100) DEFAULT 'main',
        status VARCHAR(30) DEFAULT 'pending',
        priority INTEGER DEFAULT 0,
        sent_at TIMESTAMPTZ DEFAULT NOW(),
        accepted_at TIMESTAMPTZ,
        ready_at TIMESTAMPTZ,
        served_at TIMESTAMPTZ,
        branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100)
    );

    CREATE INDEX IF NOT EXISTS idx_pos_returns_session ON pos_returns(session_id);
    CREATE INDEX IF NOT EXISTS idx_pos_returns_order ON pos_returns(original_order_id);
    CREATE INDEX IF NOT EXISTS idx_pos_order_payments_order ON pos_order_payments(order_id);
    CREATE INDEX IF NOT EXISTS idx_pos_promotions_active ON pos_promotions(is_active);
    CREATE INDEX IF NOT EXISTS idx_pos_kitchen_status ON pos_kitchen_orders(status);
    """


def get_approval_tables_sql() -> str:
    """Returns SQL for Approval Workflow tables (Phase 7)"""
    return """
    -- ===== APPROVAL WORKFLOWS (Phase 7) =====

    CREATE TABLE IF NOT EXISTS approval_workflows (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        document_type VARCHAR(50) NOT NULL,
        description TEXT,
        conditions JSONB DEFAULT '{}',
        steps JSONB DEFAULT '[]',
        is_active BOOLEAN DEFAULT TRUE,
        sla_hours INT DEFAULT 48,
        escalation_to INT,
        allow_parallel BOOLEAN DEFAULT FALSE,
        auto_approve_below DECIMAL(18,2),
        created_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS approval_requests (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER REFERENCES approval_workflows(id),
        document_type VARCHAR(50) NOT NULL,
        document_id INTEGER NOT NULL,
        amount DECIMAL(18, 4) DEFAULT 0,
        description TEXT,
        current_step INTEGER DEFAULT 1,
        total_steps INTEGER DEFAULT 1,
        status VARCHAR(20) DEFAULT 'pending',
        requested_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        completed_at TIMESTAMPTZ,
        action_date TIMESTAMPTZ,
        action_notes TEXT,
        current_approver_id INTEGER REFERENCES company_users(id),
        escalated_to INTEGER REFERENCES company_users(id),
        escalated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS approval_actions (
        id SERIAL PRIMARY KEY,
        request_id INTEGER REFERENCES approval_requests(id) ON DELETE CASCADE,
        step INTEGER NOT NULL,
        action VARCHAR(20) NOT NULL,
        actioned_by INTEGER REFERENCES company_users(id),
        notes TEXT,
        actioned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
    CREATE INDEX IF NOT EXISTS idx_approval_requests_doc ON approval_requests(document_type, document_id);
    CREATE INDEX IF NOT EXISTS idx_approval_actions_request ON approval_actions(request_id);
    CREATE INDEX IF NOT EXISTS idx_approval_requests_workflow ON approval_requests(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_approval_requests_requested_by ON approval_requests(requested_by);
    CREATE INDEX IF NOT EXISTS idx_approval_workflows_doc_type ON approval_workflows(document_type);
    """


def get_security_tables_sql() -> str:
    """Returns SQL for Security tables (2FA, Password Policy, Sessions) - Phase 7"""
    return """
    -- ===== SECURITY TABLES (Phase 7) =====

    CREATE TABLE IF NOT EXISTS user_2fa_settings (
        id SERIAL PRIMARY KEY,
        user_id INTEGER UNIQUE NOT NULL,
        secret_key VARCHAR(100),
        is_enabled BOOLEAN DEFAULT FALSE,
        backup_codes TEXT,
        verified_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS password_history (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS user_sessions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        token_hash VARCHAR(255),
        ip_address VARCHAR(50),
        user_agent TEXT,
        login_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        last_activity TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE
    );

    CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id, is_active);
    CREATE INDEX IF NOT EXISTS idx_password_history_user ON password_history(user_id);

    -- ===== PHASE 9: External API + CRM + ZATCA + WHT =====

    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS zatca_hash TEXT;
    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS zatca_signature TEXT;
    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS zatca_qr TEXT;
    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS zatca_status VARCHAR(20) DEFAULT 'pending';
    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS zatca_submission_id TEXT;

    CREATE TABLE IF NOT EXISTS api_keys (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        key_hash VARCHAR(255) NOT NULL UNIQUE,
        key_prefix VARCHAR(10) NOT NULL,
        permissions JSONB DEFAULT '[]',
        rate_limit_per_minute INT DEFAULT 60,
        is_active BOOLEAN DEFAULT TRUE,
        created_by INT,
        expires_at TIMESTAMPTZ,
        last_used_at TIMESTAMPTZ,
        usage_count INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS webhooks (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        url TEXT NOT NULL,
        secret VARCHAR(255),
        events JSONB NOT NULL DEFAULT '[]',
        is_active BOOLEAN DEFAULT TRUE,
        retry_count INT DEFAULT 3,
        timeout_seconds INT DEFAULT 10,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS webhook_logs (
        id SERIAL PRIMARY KEY,
        webhook_id INT REFERENCES webhooks(id) ON DELETE CASCADE,
        event VARCHAR(100),
        payload JSONB,
        response_status INT,
        response_body TEXT,
        success BOOLEAN DEFAULT FALSE,
        attempt INT DEFAULT 1,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS wht_rates (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        name_ar VARCHAR(100),
        rate DECIMAL(5,2) NOT NULL,
        country_code VARCHAR(5),
        category VARCHAR(50) DEFAULT 'general',
        description TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    INSERT INTO wht_rates (name, name_ar, rate, country_code, category)
    SELECT * FROM (VALUES
        ('Services - Resident', 'خدمات - مقيم', 5.00, 'SA', 'services'),
        ('Services - Non-Resident', 'خدمات - غير مقيم', 15.00, 'SA', 'services'),
        ('Rent', 'إيجار', 5.00, 'SA', 'rent'),
        ('Consulting', 'استشارات', 5.00, 'SA', 'consulting'),
        ('Royalties', 'حقوق الملكية', 15.00, 'SA', 'royalties'),
        ('Insurance', 'تأمين', 5.00, 'SA', 'insurance'),
        ('International Transport', 'نقل دولي', 5.00, 'SA', 'transport'),
        ('Dividend', 'أرباح الأسهم', 5.00, 'SA', 'dividend')
    ) AS v(name, name_ar, rate, country_code, category)
    WHERE NOT EXISTS (SELECT 1 FROM wht_rates LIMIT 1);

    CREATE TABLE IF NOT EXISTS wht_transactions (
        id SERIAL PRIMARY KEY,
        invoice_id INT,
        payment_id INT,
        supplier_id INT,
        branch_id INTEGER REFERENCES branches(id),
        wht_rate_id INT REFERENCES wht_rates(id),
        gross_amount DECIMAL(18,2) NOT NULL,
        wht_rate DECIMAL(5,2) NOT NULL,
        wht_amount DECIMAL(18,2) NOT NULL,
        net_amount DECIMAL(18,2) NOT NULL,
        currency VARCHAR(3),
        base_currency VARCHAR(3),
        exchange_rate NUMERIC(18,6) DEFAULT 1,
        certificate_number VARCHAR(50),
        status VARCHAR(20) DEFAULT 'pending',
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        idempotency_key VARCHAR(120),
        calculation_version VARCHAR(40),
        calculation_details JSONB DEFAULT '{}',
        period_date DATE,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_wht_transactions_idempotency
        ON wht_transactions (idempotency_key) WHERE idempotency_key IS NOT NULL;

    CREATE TABLE IF NOT EXISTS sales_opportunities (
        id SERIAL PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        customer_id INT REFERENCES parties(id),
        contact_name VARCHAR(100),
        contact_email VARCHAR(100),
        contact_phone VARCHAR(30),
        stage VARCHAR(30) DEFAULT 'lead',
        probability INT DEFAULT 10,
        expected_value DECIMAL(18,2) DEFAULT 0,
        expected_close_date DATE,
        currency VARCHAR(10) DEFAULT 'SAR',
        source VARCHAR(50),
        assigned_to INT,
        branch_id INT,
        notes TEXT,
        lost_reason TEXT,
        won_quotation_id INT,
        created_by INT,
        version INTEGER NOT NULL DEFAULT 0,  -- TASK-020: optimistic locking
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS opportunity_activities (
        id SERIAL PRIMARY KEY,
        opportunity_id INT REFERENCES sales_opportunities(id) ON DELETE CASCADE,
        activity_type VARCHAR(30),
        title VARCHAR(200),
        description TEXT,
        due_date DATE,
        completed BOOLEAN DEFAULT FALSE,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS support_tickets (
        id SERIAL PRIMARY KEY,
        ticket_number VARCHAR(30) UNIQUE,
        subject VARCHAR(200) NOT NULL,
        description TEXT,
        customer_id INT REFERENCES parties(id),
        contact_name VARCHAR(100),
        contact_email VARCHAR(100),
        contact_phone VARCHAR(30),
        status VARCHAR(20) DEFAULT 'open',
        priority VARCHAR(20) DEFAULT 'medium',
        category VARCHAR(50),
        assigned_to INT,
        branch_id INT,
        sla_hours INT DEFAULT 24,
        resolution TEXT,
        resolved_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ticket_comments (
        id SERIAL PRIMARY KEY,
        ticket_id INT REFERENCES support_tickets(id) ON DELETE CASCADE,
        comment TEXT NOT NULL,
        is_internal BOOLEAN DEFAULT FALSE,
        attachment_url TEXT,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax_calendar (
        id SERIAL PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        tax_type VARCHAR(50),
        branch_id INTEGER REFERENCES branches(id),
        due_date DATE NOT NULL,
        reminder_days JSONB DEFAULT '[7, 3, 1]',
        is_recurring BOOLEAN DEFAULT FALSE,
        recurrence_months INT DEFAULT 3,
        is_completed BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        completed_at TIMESTAMPTZ,
        notes TEXT,
        recurrence_pattern VARCHAR(20),
        status VARCHAR(20) DEFAULT 'pending',
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- ========== CRM Advanced: Customer Segmentation (moved before marketing_campaigns) ==========
    CREATE TABLE IF NOT EXISTS crm_customer_segments (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        description TEXT,
        criteria JSONB DEFAULT '{}',
        color VARCHAR(20) DEFAULT '#3B82F6',
        auto_assign BOOLEAN DEFAULT FALSE,
        customer_count INT DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS crm_customer_segment_members (
        id SERIAL PRIMARY KEY,
        segment_id INT REFERENCES crm_customer_segments(id) ON DELETE CASCADE,
        customer_id INT REFERENCES parties(id) ON DELETE CASCADE,
        added_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(segment_id, customer_id)
    );

    -- ========== Marketing Campaigns ==========
    CREATE TABLE IF NOT EXISTS marketing_campaigns (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        campaign_type VARCHAR(50) DEFAULT 'email',
        status VARCHAR(30) DEFAULT 'draft',
        start_date DATE,
        end_date DATE,
        budget DECIMAL(15,2) DEFAULT 0,
        spent DECIMAL(15,2) DEFAULT 0,
        target_audience TEXT,
        description TEXT,
        branch_id INT,
        segment_id INTEGER REFERENCES crm_customer_segments(id),
        subject VARCHAR(500),
        content TEXT,
        scheduled_date TIMESTAMPTZ,
        executed_at TIMESTAMPTZ,
        total_sent INTEGER DEFAULT 0,
        total_delivered INTEGER DEFAULT 0,
        total_opened INTEGER DEFAULT 0,
        total_clicked INTEGER DEFAULT 0,
        total_responded INTEGER DEFAULT 0,
        estimated_cost DECIMAL(18,4) DEFAULT 0,
        actual_cost DECIMAL(18,4) DEFAULT 0,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- ========== CRM Knowledge Base ==========
    CREATE TABLE IF NOT EXISTS crm_knowledge_base (
        id SERIAL PRIMARY KEY,
        title VARCHAR(300) NOT NULL,
        category VARCHAR(50) DEFAULT 'general',
        content TEXT,
        tags TEXT,
        is_published BOOLEAN DEFAULT FALSE,
        views INT DEFAULT 0,
        helpful_count INT DEFAULT 0,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_sales_opp_stage ON sales_opportunities(stage);
    CREATE INDEX IF NOT EXISTS idx_sales_opp_customer ON sales_opportunities(customer_id);
    -- T10.1 P1 #38 — soft-delete column so opportunity history is preserved.
    ALTER TABLE sales_opportunities ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
    ALTER TABLE sales_opportunities ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
    CREATE INDEX IF NOT EXISTS idx_sales_opp_active ON sales_opportunities(stage) WHERE is_deleted = FALSE;

    -- T10.1 P1 #84 — explicit IAS 7 cash-flow classification override per
    -- account ('operating' / 'investing' / 'financing'). NULL falls back
    -- to the heuristic implemented in routers.reports.accounting_analysis.
    ALTER TABLE accounts ADD COLUMN IF NOT EXISTS cash_flow_classification VARCHAR(20)
        CHECK (cash_flow_classification IN ('operating', 'investing', 'financing'));

    -- T10.1 P1 #67 — periodic end-of-service provision snapshot. The
    -- scheduler (services.scheduler.run_eos_provision_snapshot) writes
    -- one row per active employee per period_end documenting the
    -- accrued gratuity at that point in time, so finance can post the
    -- monthly provision JE without recomputing history.
    CREATE TABLE IF NOT EXISTS eos_provisions (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        period_end DATE NOT NULL,
        years_of_service DECIMAL(6, 4) NOT NULL,
        monthly_salary DECIMAL(18, 4) NOT NULL,
        accrued_gratuity DECIMAL(18, 4) NOT NULL,
        delta_from_previous DECIMAL(18, 4) NOT NULL DEFAULT 0,
        je_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (employee_id, period_end)
    );
    CREATE INDEX IF NOT EXISTS idx_eos_provisions_period
        ON eos_provisions(period_end);
    CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status, priority);
    CREATE INDEX IF NOT EXISTS idx_tickets_assigned ON support_tickets(assigned_to);
    CREATE INDEX IF NOT EXISTS idx_campaigns_status ON marketing_campaigns(status);
    CREATE INDEX IF NOT EXISTS idx_kb_category ON crm_knowledge_base(category);

    -- ========== CRM Advanced: Lead Scoring ==========
    CREATE TABLE IF NOT EXISTS crm_lead_scoring_rules (
        id SERIAL PRIMARY KEY,
        rule_name VARCHAR(100) NOT NULL,
        field_name VARCHAR(50) NOT NULL,
        operator VARCHAR(20) NOT NULL DEFAULT 'equals',
        field_value VARCHAR(200),
        score INT NOT NULL DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS crm_lead_scores (
        id SERIAL PRIMARY KEY,
        opportunity_id INT REFERENCES sales_opportunities(id) ON DELETE CASCADE,
        total_score INT DEFAULT 0,
        grade VARCHAR(1) DEFAULT 'C',
        scoring_details JSONB DEFAULT '[]',
        last_scored_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(opportunity_id)
    );

    -- crm_customer_segments and crm_customer_segment_members moved above marketing_campaigns

    -- ========== CRM Advanced: Contacts Management ==========
    CREATE TABLE IF NOT EXISTS crm_contacts (
        id SERIAL PRIMARY KEY,
        customer_id INT REFERENCES parties(id) ON DELETE CASCADE,
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100),
        job_title VARCHAR(100),
        email VARCHAR(150),
        phone VARCHAR(30),
        mobile VARCHAR(30),
        department VARCHAR(100),
        is_primary BOOLEAN DEFAULT FALSE,
        is_decision_maker BOOLEAN DEFAULT FALSE,
        notes TEXT,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- ========== CRM Advanced: Sales Forecasting ==========
    CREATE TABLE IF NOT EXISTS crm_sales_forecasts (
        id SERIAL PRIMARY KEY,
        period VARCHAR(7) NOT NULL,
        forecast_type VARCHAR(30) DEFAULT 'revenue',
        predicted_value DECIMAL(18,2) DEFAULT 0,
        actual_value DECIMAL(18,2) DEFAULT 0,
        confidence DECIMAL(5,2) DEFAULT 0,
        method VARCHAR(30) DEFAULT 'weighted_pipeline',
        details JSONB DEFAULT '{}',
        branch_id INT,
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_crm_contacts_customer ON crm_contacts(customer_id);
    CREATE INDEX IF NOT EXISTS idx_crm_lead_scores_opp ON crm_lead_scores(opportunity_id);
    CREATE INDEX IF NOT EXISTS idx_crm_segment_members ON crm_customer_segment_members(segment_id, customer_id);

    -- ========== Intercompany Transactions ==========
    CREATE TABLE IF NOT EXISTS intercompany_transactions (
        id SERIAL PRIMARY KEY,
        source_company_id UUID NOT NULL,
        target_company_id UUID NOT NULL,
        transaction_type VARCHAR(50) NOT NULL,
        reference VARCHAR(50),
        description TEXT,
        amount DECIMAL(18,2) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        source_journal_id INT,
        target_journal_id INT,
        status VARCHAR(20) DEFAULT 'pending',
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        processed_at TIMESTAMPTZ
    );

    -- ========== Revenue Recognition ==========
    CREATE TABLE IF NOT EXISTS revenue_recognition_schedules (
        id SERIAL PRIMARY KEY,
        invoice_id INT,
        contract_id INT,
        total_amount DECIMAL(18,2) NOT NULL,
        recognized_amount DECIMAL(18,2) DEFAULT 0,
        deferred_amount DECIMAL(18,2) DEFAULT 0,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        method VARCHAR(30) DEFAULT 'straight_line',
        status VARCHAR(20) DEFAULT 'active',
        schedule_lines JSONB DEFAULT '[]',
        created_by INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """


def get_cashflow_forecast_tables_sql() -> str:
    """Returns SQL for Cash Flow Forecast tables (Phase 7 - US5)"""
    return """
    -- ===== CASH FLOW FORECAST =====
    CREATE TABLE IF NOT EXISTS cashflow_forecasts (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        forecast_date DATE NOT NULL DEFAULT CURRENT_DATE,
        horizon_days INTEGER NOT NULL DEFAULT 90,
        mode VARCHAR(20) NOT NULL DEFAULT 'contractual',
        generated_by INTEGER REFERENCES company_users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS cashflow_forecast_lines (
        id SERIAL PRIMARY KEY,
        forecast_id INTEGER NOT NULL REFERENCES cashflow_forecasts(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        source_type VARCHAR(20) NOT NULL,
        source_document_id INTEGER,
        projected_inflow DECIMAL(18, 4) NOT NULL DEFAULT 0,
        projected_outflow DECIMAL(18, 4) NOT NULL DEFAULT 0,
        projected_balance DECIMAL(18, 4) NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMPTZ
    );
    """


def get_phase_features_tables_sql() -> str:
    """Returns SQL for matching, SSO, costing, intercompany, notification-preferences tables."""
    return """
    -- ===== THREE-WAY MATCHING =====
    CREATE TABLE IF NOT EXISTS match_tolerances (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        quantity_percent NUMERIC(5,2) DEFAULT 0,
        quantity_absolute NUMERIC(18,4) DEFAULT 0,
        price_percent NUMERIC(5,2) DEFAULT 0,
        price_absolute NUMERIC(18,4) DEFAULT 0,
        supplier_id INTEGER REFERENCES parties(id) ON DELETE SET NULL,
        product_category_id INTEGER,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS three_way_matches (
        id SERIAL PRIMARY KEY,
        purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
        invoice_id INTEGER NOT NULL,
        match_status VARCHAR(30) NOT NULL DEFAULT 'matched',
        matched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        matched_by INTEGER,
        exception_approved_by INTEGER,
        exception_notes TEXT,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS three_way_match_lines (
        id SERIAL PRIMARY KEY,
        match_id INTEGER NOT NULL REFERENCES three_way_matches(id) ON DELETE CASCADE,
        po_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
        grn_ids JSONB,
        invoice_line_id INTEGER,
        po_quantity NUMERIC(18,4) DEFAULT 0,
        received_quantity NUMERIC(18,4) DEFAULT 0,
        invoiced_quantity NUMERIC(18,4) DEFAULT 0,
        po_unit_price NUMERIC(18,4) DEFAULT 0,
        invoiced_unit_price NUMERIC(18,4) DEFAULT 0,
        quantity_variance_pct NUMERIC(5,2) DEFAULT 0,
        quantity_variance_abs NUMERIC(18,4) DEFAULT 0,
        price_variance_pct NUMERIC(5,2) DEFAULT 0,
        price_variance_abs NUMERIC(18,4) DEFAULT 0,
        tolerance_id INTEGER REFERENCES match_tolerances(id) ON DELETE SET NULL,
        line_status VARCHAR(30) NOT NULL DEFAULT 'matched',
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    -- ===== SSO / LDAP =====
    CREATE TABLE IF NOT EXISTS sso_configurations (
        id SERIAL PRIMARY KEY,
        provider_type VARCHAR(10) NOT NULL,
        display_name VARCHAR(255) NOT NULL,
        metadata_url VARCHAR(1024),
        metadata_xml TEXT,
        ldap_host VARCHAR(255),
        ldap_port INTEGER,
        ldap_base_dn VARCHAR(512),
        ldap_bind_dn VARCHAR(512),
        ldap_use_tls BOOLEAN DEFAULT true,
        is_active BOOLEAN DEFAULT false,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS sso_group_role_mappings (
        id SERIAL PRIMARY KEY,
        sso_configuration_id INTEGER NOT NULL REFERENCES sso_configurations(id) ON DELETE CASCADE,
        external_group_name VARCHAR(255) NOT NULL,
        aman_role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ,
        UNIQUE(sso_configuration_id, external_group_name)
    );

    CREATE TABLE IF NOT EXISTS sso_fallback_admins (
        id SERIAL PRIMARY KEY,
        sso_configuration_id INTEGER NOT NULL REFERENCES sso_configurations(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES company_users(id) ON DELETE CASCADE,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    -- ===== COST LAYERS (FIFO/LIFO) =====
    CREATE TABLE IF NOT EXISTS cost_layers (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
        costing_method VARCHAR(10) NOT NULL,
        purchase_date DATE NOT NULL,
        original_quantity NUMERIC(18,4) NOT NULL,
        remaining_quantity NUMERIC(18,4) NOT NULL,
        unit_cost NUMERIC(18,4) NOT NULL,
        source_document_type VARCHAR(30) NOT NULL,
        source_document_id INTEGER,
        is_exhausted BOOLEAN DEFAULT false,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ,
        CONSTRAINT ck_cost_layers_remaining_qty_non_negative CHECK (remaining_quantity >= 0)
    );

    CREATE INDEX IF NOT EXISTS ix_cost_layers_product_wh_exhausted_date
        ON cost_layers(product_id, warehouse_id, is_exhausted, purchase_date);

    CREATE TABLE IF NOT EXISTS cost_layer_consumptions (
        id SERIAL PRIMARY KEY,
        cost_layer_id INTEGER NOT NULL REFERENCES cost_layers(id) ON DELETE CASCADE,
        quantity_consumed NUMERIC(18,4) NOT NULL,
        sale_document_type VARCHAR(30) NOT NULL,
        sale_document_id INTEGER,
        consumed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS ix_cost_layer_consumptions_layer_id ON cost_layer_consumptions(cost_layer_id);

    -- ===== INTERCOMPANY =====
    CREATE TABLE IF NOT EXISTS entity_groups (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        parent_id INTEGER REFERENCES entity_groups(id) ON DELETE SET NULL,
        company_id VARCHAR(100) NOT NULL,
        group_currency VARCHAR(10) NOT NULL DEFAULT 'SAR',
        consolidation_level INTEGER NOT NULL DEFAULT 0,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS intercompany_transactions_v2 (
        id SERIAL PRIMARY KEY,
        source_entity_id INTEGER NOT NULL REFERENCES entity_groups(id) ON DELETE RESTRICT,
        target_entity_id INTEGER NOT NULL REFERENCES entity_groups(id) ON DELETE RESTRICT,
        transaction_type VARCHAR(30) NOT NULL,
        source_amount NUMERIC(18,4) NOT NULL,
        source_currency VARCHAR(10) NOT NULL,
        target_amount NUMERIC(18,4) NOT NULL,
        target_currency VARCHAR(10) NOT NULL,
        -- transaction_currency/transaction_amount = the actual money moved
        -- (e.g., USD between SAR and EGP branches). source_*/target_* are
        -- the booking values in each branch's functional currency.
        transaction_currency VARCHAR(10),
        transaction_amount NUMERIC(18,4),
        exchange_rate NUMERIC(18,8) NOT NULL DEFAULT 1,
        source_journal_entry_id INTEGER,
        target_journal_entry_id INTEGER,
        elimination_status VARCHAR(30) NOT NULL DEFAULT 'pending',
        elimination_journal_entry_id INTEGER,
        reference_document VARCHAR(255),
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ,
        CONSTRAINT ck_ic_txn_diff_entities CHECK (source_entity_id != target_entity_id)
    );

    CREATE TABLE IF NOT EXISTS intercompany_account_mappings (
        id SERIAL PRIMARY KEY,
        source_entity_id INTEGER NOT NULL REFERENCES entity_groups(id) ON DELETE CASCADE,
        target_entity_id INTEGER NOT NULL REFERENCES entity_groups(id) ON DELETE CASCADE,
        source_account_id INTEGER NOT NULL,
        target_account_id INTEGER NOT NULL,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ
    );

    -- ===== NOTIFICATION PREFERENCES =====
    CREATE TABLE IF NOT EXISTS notification_preferences (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES company_users(id) ON DELETE CASCADE,
        event_type VARCHAR(50) NOT NULL,
        email_enabled BOOLEAN DEFAULT true,
        in_app_enabled BOOLEAN DEFAULT true,
        push_enabled BOOLEAN DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN NOT NULL DEFAULT false,
        deleted_at TIMESTAMPTZ,
        UNIQUE(user_id, event_type)
    );
    """


def get_system_completion_tables_sql() -> str:
    """Returns SQL for system completion tables (Phase 9)"""
    return """
    -- ===== DELIVERY ORDERS =====
    CREATE TABLE IF NOT EXISTS delivery_orders (
        id SERIAL PRIMARY KEY,
        delivery_number VARCHAR(50) UNIQUE NOT NULL,
        delivery_date DATE NOT NULL DEFAULT CURRENT_DATE,
        sales_order_id INTEGER REFERENCES sales_orders(id),
        invoice_id INTEGER REFERENCES invoices(id),
        party_id INTEGER REFERENCES parties(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        branch_id INTEGER REFERENCES branches(id),
        status VARCHAR(30) DEFAULT 'draft',
        shipping_method VARCHAR(100),
        tracking_number VARCHAR(100),
        driver_name VARCHAR(100),
        driver_phone VARCHAR(50),
        vehicle_number VARCHAR(50),
        delivery_address TEXT,
        notes TEXT,
        total_items INTEGER DEFAULT 0,
        total_quantity NUMERIC(15,4) DEFAULT 0,
        shipped_at TIMESTAMPTZ,
        delivered_at TIMESTAMPTZ,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS delivery_order_lines (
        id SERIAL PRIMARY KEY,
        delivery_order_id INTEGER NOT NULL REFERENCES delivery_orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        so_line_id INTEGER REFERENCES sales_order_lines(id) ON DELETE SET NULL,
        description TEXT,
        ordered_qty NUMERIC(15,4) DEFAULT 0,
        delivered_qty NUMERIC(15,4) DEFAULT 0,
        unit VARCHAR(50),
        batch_number VARCHAR(100),
        serial_numbers TEXT,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== LANDED COSTS =====
    CREATE TABLE IF NOT EXISTS landed_costs (
        id SERIAL PRIMARY KEY,
        lc_number VARCHAR(50) UNIQUE NOT NULL,
        lc_date DATE NOT NULL DEFAULT CURRENT_DATE,
        purchase_order_id INTEGER REFERENCES purchase_orders(id),
        grn_id INTEGER,
        reference VARCHAR(100),
        description TEXT,
        total_amount NUMERIC(15,4) DEFAULT 0,
        allocation_method VARCHAR(30) DEFAULT 'by_value',
        status VARCHAR(20) DEFAULT 'draft',
        currency VARCHAR(10) DEFAULT 'SAR',
        exchange_rate NUMERIC(18,6) DEFAULT 1,
        notes TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_by INTEGER REFERENCES company_users(id),
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS landed_cost_items (
        id SERIAL PRIMARY KEY,
        landed_cost_id INTEGER NOT NULL REFERENCES landed_costs(id) ON DELETE CASCADE,
        cost_type VARCHAR(50) NOT NULL,
        description TEXT,
        amount NUMERIC(15,4) NOT NULL DEFAULT 0,
        vendor_id INTEGER REFERENCES parties(id),
        invoice_ref VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE TABLE IF NOT EXISTS landed_cost_allocations (
        id SERIAL PRIMARY KEY,
        landed_cost_id INTEGER NOT NULL REFERENCES landed_costs(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        po_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE SET NULL,
        original_cost NUMERIC(15,4) NOT NULL DEFAULT 0,
        allocated_amount NUMERIC(15,4) NOT NULL DEFAULT 0,
        new_cost NUMERIC(15,4) NOT NULL DEFAULT 0,
        allocation_basis NUMERIC(15,6) DEFAULT 0,
        allocation_share NUMERIC(15,6) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE OR REPLACE VIEW supplier_subledger AS
    SELECT i.party_id, i.branch_id, i.currency,
           'purchase_invoice' AS document_type, i.id AS document_id,
           i.invoice_number AS document_number, i.invoice_date AS document_date,
           0::numeric AS debit, i.total AS credit,
           0::numeric AS base_debit, (i.total * COALESCE(i.exchange_rate, 1)) AS base_credit,
           COALESCE(i.exchange_rate, 1) AS exchange_rate
    FROM invoices i
    WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
    UNION ALL
    SELECT i.party_id, i.branch_id, i.currency,
           'purchase_return' AS document_type, i.id, i.invoice_number, i.invoice_date,
           i.total, 0::numeric, (i.total * COALESCE(i.exchange_rate, 1)), 0::numeric,
           COALESCE(i.exchange_rate, 1)
    FROM invoices i
    WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft', 'cancelled')
    UNION ALL
    SELECT pv.party_id, pv.branch_id, pv.currency,
           pv.voucher_type AS document_type, pv.id, pv.voucher_number, pv.voucher_date,
           CASE WHEN pv.voucher_type = 'payment' THEN pv.amount ELSE 0 END AS debit,
           CASE WHEN pv.voucher_type = 'refund' THEN pv.amount ELSE 0 END AS credit,
           CASE WHEN pv.voucher_type = 'payment' THEN (pv.amount * COALESCE(pv.exchange_rate, 1)) ELSE 0 END AS base_debit,
           CASE WHEN pv.voucher_type = 'refund' THEN (pv.amount * COALESCE(pv.exchange_rate, 1)) ELSE 0 END AS base_credit,
           COALESCE(pv.exchange_rate, 1)
    FROM payment_vouchers pv
    WHERE pv.voucher_type IN ('payment', 'refund') AND pv.status NOT IN ('draft', 'cancelled')
    UNION ALL
    SELECT i.party_id, i.branch_id, i.currency,
           i.invoice_type AS document_type, i.id, i.invoice_number, i.invoice_date,
           CASE WHEN i.invoice_type = 'purchase_credit_note' THEN i.total ELSE 0 END,
           CASE WHEN i.invoice_type = 'purchase_debit_note' THEN i.total ELSE 0 END,
           CASE WHEN i.invoice_type = 'purchase_credit_note' THEN (i.total * COALESCE(i.exchange_rate, 1)) ELSE 0 END,
           CASE WHEN i.invoice_type = 'purchase_debit_note' THEN (i.total * COALESCE(i.exchange_rate, 1)) ELSE 0 END,
           COALESCE(i.exchange_rate, 1)
    FROM invoices i
    WHERE i.invoice_type IN ('purchase_credit_note', 'purchase_debit_note') AND i.status NOT IN ('draft', 'cancelled')
    UNION ALL
    SELECT lci.vendor_id, lc.branch_id, COALESCE(lc.currency, 'SAR'),
           'landed_cost', lc.id, lc.lc_number, lc.lc_date,
           0::numeric, lci.amount, 0::numeric, (lci.amount * COALESCE(lc.exchange_rate, 1)),
           COALESCE(lc.exchange_rate, 1)
    FROM landed_cost_items lci
    JOIN landed_costs lc ON lc.id = lci.landed_cost_id
    WHERE lci.vendor_id IS NOT NULL AND lc.status = 'posted';

    -- ===== PRINT TEMPLATES =====
    CREATE TABLE IF NOT EXISTS print_templates (
        id SERIAL PRIMARY KEY,
        template_type VARCHAR(50) NOT NULL,
        name VARCHAR(200) NOT NULL,
        html_template TEXT NOT NULL,
        css_styles TEXT,
        header_html TEXT,
        footer_html TEXT,
        paper_size VARCHAR(20) DEFAULT 'A4',
        orientation VARCHAR(20) DEFAULT 'portrait',
        is_default BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== BANK IMPORT =====
    CREATE TABLE IF NOT EXISTS bank_import_batches (
        id SERIAL PRIMARY KEY,
        file_name VARCHAR(300),
        bank_account_id INTEGER REFERENCES treasury_accounts(id) ON DELETE SET NULL,
        total_lines INTEGER DEFAULT 0,
        imported_lines INTEGER DEFAULT 0,
        matched_lines INTEGER DEFAULT 0,
        total_debit NUMERIC(15,4) DEFAULT 0,
        total_credit NUMERIC(15,4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        uploaded_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS bank_import_lines (
        id SERIAL PRIMARY KEY,
        batch_id INTEGER NOT NULL REFERENCES bank_import_batches(id) ON DELETE CASCADE,
        line_number INTEGER DEFAULT 0,
        transaction_date DATE,
        description TEXT,
        reference VARCHAR(200),
        debit NUMERIC(15,4) DEFAULT 0,
        credit NUMERIC(15,4) DEFAULT 0,
        balance NUMERIC(15,4),
        status VARCHAR(20) DEFAULT 'unmatched',
        matched_transaction_id INTEGER REFERENCES treasury_transactions(id) ON DELETE SET NULL,
        account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== ZAKAT CALCULATIONS =====
    CREATE TABLE IF NOT EXISTS zakat_calculations (
        id SERIAL PRIMARY KEY,
        fiscal_year INTEGER NOT NULL,
        branch_id INTEGER REFERENCES branches(id),
        branch_scope_key VARCHAR(160) NOT NULL DEFAULT 'all:company',
        branch_ids JSONB,
        method VARCHAR(30) DEFAULT 'net_assets',
        zakat_base NUMERIC(15,4) DEFAULT 0,
        zakat_rate NUMERIC(8,4) DEFAULT 0,
        zakat_amount NUMERIC(15,4) DEFAULT 0,
        details JSONB DEFAULT '{}',
        calculation_details JSONB DEFAULT '{}',
        calculation_version VARCHAR(40),
        currency VARCHAR(3),
        base_currency VARCHAR(3),
        idempotency_key VARCHAR(120),
        status VARCHAR(20) DEFAULT 'calculated',
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        notes TEXT,
        calculated_by INTEGER REFERENCES company_users(id),
        calculated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_year_scope
        ON zakat_calculations (fiscal_year, branch_scope_key);
    CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_idempotency
        ON zakat_calculations (idempotency_key) WHERE idempotency_key IS NOT NULL;

    -- ===== FISCAL PERIOD LOCKS =====
    CREATE TABLE IF NOT EXISTS fiscal_period_locks (
        id SERIAL PRIMARY KEY,
        period_name VARCHAR(100) NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        is_locked BOOLEAN DEFAULT FALSE,
        locked_at TIMESTAMPTZ,
        locked_by INTEGER REFERENCES company_users(id),
        unlocked_at TIMESTAMPTZ,
        unlocked_by INTEGER REFERENCES company_users(id),
        reason TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- ===== BACKUP HISTORY =====
    CREATE TABLE IF NOT EXISTS backup_history (
        id SERIAL PRIMARY KEY,
        backup_type VARCHAR(20) DEFAULT 'manual',
        file_name VARCHAR(300),
        file_size BIGINT DEFAULT 0,
        file_path TEXT,
        status VARCHAR(20) DEFAULT 'completed',
        error_message TEXT,
        tables_included INTEGER DEFAULT 0,
        rows_exported BIGINT DEFAULT 0,
        created_by INTEGER REFERENCES company_users(id),
        started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ
    );

    -- ===== ADD COLUMNS TO EXISTING TABLES =====
    ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_order_id INTEGER REFERENCES delivery_orders(id) ON DELETE SET NULL;
    -- Absolute tolerance for bank recon auto-match
    ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS tolerance_amount DECIMAL(18, 4) DEFAULT 0;

    -- Parallel / any-of / all-of approval steps
    ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS step_group INTEGER DEFAULT 0;
    ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS quorum_required INTEGER DEFAULT 1;
    ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS approvals_collected INTEGER DEFAULT 0;

    -- Richer depreciation + revaluation tracking for fixed assets
    ALTER TABLE assets ADD COLUMN IF NOT EXISTS depreciation_method VARCHAR(40) DEFAULT 'straight_line';
    ALTER TABLE assets ADD COLUMN IF NOT EXISTS expected_production_units DECIMAL(18, 4);
    ALTER TABLE assets ADD COLUMN IF NOT EXISTS cumulative_production_units DECIMAL(18, 4) DEFAULT 0;
    ALTER TABLE assets ADD COLUMN IF NOT EXISTS revaluation_reserve DECIMAL(18, 4) DEFAULT 0;

    -- Track when SLA escalation last ran to avoid duplicate notifies
    ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS sla_escalated_at TIMESTAMPTZ;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS nationality VARCHAR(5) DEFAULT NULL;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS is_saudi BOOLEAN DEFAULT FALSE;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS eos_eligible BOOLEAN DEFAULT TRUE;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS eos_amount NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS iqama_number VARCHAR(20);
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS iqama_expiry DATE;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS passport_number VARCHAR(30);
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS sponsor VARCHAR(200);
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS annual_leave_days INTEGER DEFAULT 30;
    ALTER TABLE employees ADD COLUMN IF NOT EXISTS annual_leave_entitlement NUMERIC(8,2) DEFAULT 30;
    ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT NULL;
    ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1.0;
    ALTER TABLE payroll_entries ADD COLUMN IF NOT EXISTS net_salary_base NUMERIC(18,4) DEFAULT 0;
    ALTER TABLE pos_orders ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(100);
    ALTER TABLE opportunity_activities ADD COLUMN IF NOT EXISTS contact_id INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS actual_material_cost NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS actual_labor_cost NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS actual_overhead_cost NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS actual_total_cost NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS standard_cost NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS variance_amount NUMERIC(15,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS variance_percentage NUMERIC(8,4) DEFAULT 0;
    ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS costing_status VARCHAR(20) DEFAULT 'pending';

    -- ===== PHASE B: ★★★★½ → ★★★★★ TABLES =====

    -- B1: Security Events
    CREATE TABLE IF NOT EXISTS security_events (
        id SERIAL PRIMARY KEY,
        event_type VARCHAR(50) NOT NULL,
        severity VARCHAR(20) DEFAULT 'info',
        user_id INTEGER REFERENCES company_users(id),
        ip_address VARCHAR(45),
        user_agent TEXT,
        details JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_sec_events_user ON security_events(user_id);
    CREATE INDEX IF NOT EXISTS idx_sec_events_date ON security_events(created_at DESC);

    CREATE TABLE IF NOT EXISTS login_attempts (
        id SERIAL PRIMARY KEY,
        ip_address VARCHAR(45) NOT NULL,
        username VARCHAR(100),
        success BOOLEAN DEFAULT FALSE,
        attempted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address, attempted_at);

    -- B3: Check Lifecycle Log
    CREATE TABLE IF NOT EXISTS check_status_log (
        id SERIAL PRIMARY KEY,
        check_type VARCHAR(20) NOT NULL,
        check_id INTEGER NOT NULL,
        old_status VARCHAR(30),
        new_status VARCHAR(30) NOT NULL,
        notes TEXT,
        changed_by INTEGER REFERENCES company_users(id),
        changed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_check_log_check ON check_status_log(check_type, check_id);

    -- B4: Manufacturing Capacity Planning
    CREATE TABLE IF NOT EXISTS capacity_plans (
        id SERIAL PRIMARY KEY,
        work_center_id INTEGER NOT NULL REFERENCES work_centers(id) ON DELETE CASCADE,
        plan_date DATE NOT NULL,
        available_hours NUMERIC(8,2) DEFAULT 8,
        planned_hours NUMERIC(8,2) DEFAULT 0,
        actual_hours NUMERIC(8,2) DEFAULT 0,
        efficiency_pct NUMERIC(5,2) DEFAULT 0,
        notes TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by VARCHAR(100),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(work_center_id, plan_date)
    );
    CREATE INDEX IF NOT EXISTS idx_cap_plan_wc ON capacity_plans(work_center_id, plan_date);

    -- B5: Project Risks
    CREATE TABLE IF NOT EXISTS project_risks (
        id SERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        title VARCHAR(200) NOT NULL,
        description TEXT,
        probability VARCHAR(20) DEFAULT 'medium',
        impact VARCHAR(20) DEFAULT 'medium',
        risk_score INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'open',
        mitigation_plan TEXT,
        owner_id INTEGER REFERENCES company_users(id),
        due_date DATE,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_proj_risks_project ON project_risks(project_id);

    -- B5: Task Dependencies
    CREATE TABLE IF NOT EXISTS task_dependencies (
        id SERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
        depends_on_task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
        dependency_type VARCHAR(20) DEFAULT 'finish_to_start',
        lag_days INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(project_id, task_id);

    -- B6: Lease Contracts (IFRS 16)
    CREATE TABLE IF NOT EXISTS lease_contracts (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
        description VARCHAR(300) NOT NULL,
        lessor_name VARCHAR(200),
        lease_type VARCHAR(30) DEFAULT 'operating',
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        monthly_payment NUMERIC(15,4) DEFAULT 0,
        total_payments NUMERIC(15,4) DEFAULT 0,
        discount_rate NUMERIC(8,4) DEFAULT 5.0,
        right_of_use_value NUMERIC(15,4) DEFAULT 0,
        lease_liability NUMERIC(15,4) DEFAULT 0,
        accumulated_depreciation NUMERIC(15,4) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'active',
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_lease_status ON lease_contracts(status);

    -- B6: Asset Impairment (IAS 36)
    CREATE TABLE IF NOT EXISTS asset_impairments (
        id SERIAL PRIMARY KEY,
        asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
        test_date DATE NOT NULL,
        carrying_amount NUMERIC(15,4) NOT NULL,
        recoverable_amount NUMERIC(15,4) NOT NULL,
        impairment_loss NUMERIC(15,4) DEFAULT 0,
        reason TEXT,
        journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_impairment_asset ON asset_impairments(asset_id);

    -- expense_policies moved to get_treasury_dependent_tables_sql() (before expenses)
    -- expenses.policy_id FK now inline in get_treasury_dependent_tables_sql()

    -- C2: Contract Amendments
    CREATE TABLE IF NOT EXISTS contract_amendments (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER REFERENCES contracts(id) ON DELETE CASCADE,
        amendment_type VARCHAR(50) DEFAULT 'value_change',
        old_value TEXT,
        new_value TEXT,
        description TEXT,
        effective_date DATE,
        approved_by INTEGER REFERENCES company_users(id),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_amendments_contract ON contract_amendments(contract_id);

    -- Add enabled_modules to company_settings for B2
    ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS enabled_modules JSONB DEFAULT '["accounting","sales","purchases","inventory","hr","manufacturing","projects","pos","crm","treasury","assets","expenses","contracts","reports","taxes"]';
    ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS industry_template VARCHAR(50) DEFAULT 'general';
    """


def get_extended_features_tables_sql() -> str:
    """Returns SQL for extended feature tables (US6-US18: Subscriptions, Self-Service, Analytics,
    Mobile, Blanket POs, Shop Floor, Timesheets, Resource Planning, Performance Cycles,
    CPQ, Demand Forecast, Campaigns)"""
    return """
    -- ===== EXTENDED FEATURES TABLES (US6-US18) =====

    -- ========== US7: Subscription Management ==========
    CREATE TABLE IF NOT EXISTS subscription_plans (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        billing_frequency VARCHAR(20) NOT NULL DEFAULT 'monthly',
        base_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
        currency VARCHAR(3) DEFAULT 'SAR',
        trial_period_days INTEGER DEFAULT 0,
        auto_renewal BOOLEAN DEFAULT TRUE,
        is_active BOOLEAN DEFAULT TRUE,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS subscription_enrollments (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES parties(id),
        plan_id INTEGER REFERENCES subscription_plans(id),
        start_date DATE NOT NULL,
        end_date DATE,
        next_billing_date DATE,
        status VARCHAR(20) DEFAULT 'active',
        failed_payment_count INTEGER DEFAULT 0,
        trial_end_date DATE,
        cancelled_at TIMESTAMPTZ,
        cancellation_reason TEXT,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS subscription_invoices (
        id SERIAL PRIMARY KEY,
        enrollment_id INTEGER REFERENCES subscription_enrollments(id),
        invoice_id INTEGER REFERENCES invoices(id),
        billing_period_start DATE,
        billing_period_end DATE,
        amount DECIMAL(18, 4) DEFAULT 0,
        tax_rate NUMERIC(5,2),
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        tax_amount NUMERIC(18,4) DEFAULT 0,
        currency VARCHAR(3),
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        is_prorated BOOLEAN DEFAULT FALSE,
        proration_details JSONB,
        is_deleted BOOLEAN DEFAULT FALSE,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_sub_enrollments_customer ON subscription_enrollments(customer_id);
    CREATE INDEX IF NOT EXISTS ix_sub_enrollments_plan ON subscription_enrollments(plan_id);
    CREATE INDEX IF NOT EXISTS ix_sub_invoices_enrollment ON subscription_invoices(enrollment_id);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_sub_enrollments_active_unique ON subscription_enrollments(customer_id, plan_id) WHERE status IN ('active', 'paused');

    CREATE TABLE IF NOT EXISTS deferred_revenue_schedules (
        id SERIAL PRIMARY KEY,
        subscription_invoice_id INTEGER REFERENCES subscription_invoices(id) NOT NULL,
        enrollment_id INTEGER REFERENCES subscription_enrollments(id) NOT NULL,
        recognition_date DATE NOT NULL,
        amount NUMERIC(18,4) NOT NULL,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'posted', 'skipped')),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES company_users(id)
    );

    CREATE INDEX IF NOT EXISTS ix_deferred_rev_enrollment ON deferred_revenue_schedules(enrollment_id);
    CREATE INDEX IF NOT EXISTS ix_deferred_rev_recognition ON deferred_revenue_schedules(recognition_date, status);
    CREATE INDEX IF NOT EXISTS ix_deferred_rev_invoice ON deferred_revenue_schedules(subscription_invoice_id);

    -- SUB-F1: Dunning cases for overdue subscription / normal invoices
    CREATE TABLE IF NOT EXISTS dunning_cases (
        id SERIAL PRIMARY KEY,
        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
        subscription_invoice_id INTEGER REFERENCES subscription_invoices(id) ON DELETE CASCADE,
        party_id INTEGER REFERENCES parties(id),
        amount_outstanding DECIMAL(18, 4) DEFAULT 0,
        currency VARCHAR(3) DEFAULT 'SAR',
        days_overdue INTEGER DEFAULT 0,
        dunning_level INTEGER DEFAULT 1 CHECK (dunning_level BETWEEN 1 AND 5),
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'notified', 'escalated', 'resolved', 'written_off')),
        last_reminder_at TIMESTAMPTZ,
        next_action_at TIMESTAMPTZ,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_dunning_source
            CHECK (invoice_id IS NOT NULL OR subscription_invoice_id IS NOT NULL)
    );
    CREATE INDEX IF NOT EXISTS ix_dunning_status ON dunning_cases(status, next_action_at);
    CREATE INDEX IF NOT EXISTS ix_dunning_party ON dunning_cases(party_id);

    -- EINV-F2: e-invoice outbox for resubmitting failed ZATCA/FTA/ETA payloads
    CREATE TABLE IF NOT EXISTS einvoice_outbox (
        id SERIAL PRIMARY KEY,
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        adapter VARCHAR(20) NOT NULL DEFAULT 'zatca',
        payload JSONB,
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'failed', 'giveup')),
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        last_attempt_at TIMESTAMPTZ,
        next_attempt_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        response JSONB,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ix_einvoice_outbox_due ON einvoice_outbox(status, next_attempt_at);
    CREATE INDEX IF NOT EXISTS ix_einvoice_outbox_invoice ON einvoice_outbox(invoice_id);

    -- ==========================================================================
    -- Cross-module configuration + workflow + treasury hardening tables
    -- ==========================================================================

    -- Overtime rate multipliers (replaces hardcoded 1.5 / 2.0)
    CREATE TABLE IF NOT EXISTS overtime_rates_config (
        id SERIAL PRIMARY KEY,
        rate_key VARCHAR(40) UNIQUE NOT NULL,
        description VARCHAR(200),
        multiplier DECIMAL(6, 3) NOT NULL CHECK (multiplier > 0),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO overtime_rates_config (rate_key, description, multiplier) VALUES
      ('weekday_ot', 'Weekday overtime multiplier', 1.500),
      ('weekend_ot', 'Weekend / public holiday overtime', 2.000),
      ('night_shift', 'Night-shift premium', 1.250)
    ON CONFLICT (rate_key) DO NOTHING;

    -- Document access control per department / role (complements existing DMS)
    CREATE TABLE IF NOT EXISTS document_permissions (
        id SERIAL PRIMARY KEY,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        department_id INTEGER REFERENCES departments(id) ON DELETE CASCADE,
        role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES company_users(id) ON DELETE CASCADE,
        access_level VARCHAR(10) NOT NULL DEFAULT 'view' CHECK (access_level IN ('view','edit','owner')),
        granted_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_doc_perm_target CHECK (
            department_id IS NOT NULL OR role_id IS NOT NULL OR user_id IS NOT NULL
        )
    );
    CREATE INDEX IF NOT EXISTS ix_doc_perm_doc ON document_permissions(document_id);
    CREATE INDEX IF NOT EXISTS ix_doc_perm_dept ON document_permissions(department_id);

    -- Geofences and their bindings to branches (attendance check-in)
    CREATE TABLE IF NOT EXISTS geofences (
        id SERIAL PRIMARY KEY,
        name VARCHAR(150) NOT NULL,
        branch_id INTEGER REFERENCES branches(id) ON DELETE CASCADE,
        center_lat DECIMAL(10, 7) NOT NULL,
        center_lng DECIMAL(10, 7) NOT NULL,
        radius_m INTEGER NOT NULL CHECK (radius_m > 0),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ix_geofences_branch ON geofences(branch_id);

    -- Canonical zakat base items mapping (replaces fragile LIKE matching)
    CREATE TABLE IF NOT EXISTS zakat_base_items (
        id SERIAL PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        category VARCHAR(30) NOT NULL CHECK (category IN ('asset','deductible','addition','exclude')),
        weight DECIMAL(6, 4) DEFAULT 1.0000,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (account_id)
    );
    CREATE INDEX IF NOT EXISTS ix_zakat_base_category ON zakat_base_items(category);

    -- POS offline batch sync inbox (deduped by client_uuid)
    CREATE TABLE IF NOT EXISTS pos_offline_inbox (
        id SERIAL PRIMARY KEY,
        client_uuid VARCHAR(64) UNIQUE NOT NULL,
        session_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        payload JSONB NOT NULL,
        client_created_at TIMESTAMPTZ,
        received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        processed_at TIMESTAMPTZ,
        error TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_pos_offline_inbox_status ON pos_offline_inbox(status, received_at);

    -- ========== T4.3: Smart Alerts ==========
    CREATE TABLE IF NOT EXISTS alert_rules (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        rule_type VARCHAR(60) NOT NULL,
        condition_json JSONB DEFAULT '{}',
        threshold NUMERIC(20,4) DEFAULT 0,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        notify_users JSONB DEFAULT '[]',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id SERIAL PRIMARY KEY,
        rule_id INTEGER REFERENCES alert_rules(id) ON DELETE CASCADE,
        triggered_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        details_json JSONB DEFAULT '{}',
        status VARCHAR(30) NOT NULL DEFAULT 'open',
        resolved_at TIMESTAMPTZ
    );
    CREATE TABLE IF NOT EXISTS alert_history (
        id SERIAL PRIMARY KEY,
        alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
        action VARCHAR(60) NOT NULL,
        actor INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ix_alerts_rule_id ON alerts(rule_id, triggered_at);
    CREATE INDEX IF NOT EXISTS ix_alert_rules_enabled ON alert_rules(enabled) WHERE enabled = TRUE;


    -- ========== US6: Employee Self-Service ==========
    CREATE TABLE IF NOT EXISTS self_service_requests (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        request_type VARCHAR(30) NOT NULL,
        details JSONB,
        status VARCHAR(20) DEFAULT 'pending',
        approver_id INTEGER REFERENCES employees(id),
        approved_at TIMESTAMPTZ,
        rejection_reason TEXT,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_self_service_employee ON self_service_requests(employee_id);

    -- ========== US9: Analytics / BI Dashboard ==========
    CREATE TABLE IF NOT EXISTS analytics_dashboards (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        is_system BOOLEAN DEFAULT FALSE,
        access_roles JSONB DEFAULT '[]',
        branch_scope INTEGER,
        refresh_interval_minutes INTEGER DEFAULT 60,
        created_by INTEGER REFERENCES company_users(id),
        updated_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS analytics_dashboard_widgets (
        id SERIAL PRIMARY KEY,
        dashboard_id INTEGER REFERENCES analytics_dashboards(id) ON DELETE CASCADE,
        widget_type VARCHAR(50) NOT NULL,
        title VARCHAR(200),
        data_source VARCHAR(100),
        filters JSONB DEFAULT '{}',
        position JSONB DEFAULT '{}',
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_dashboard_widgets_dashboard ON analytics_dashboard_widgets(dashboard_id);

    -- Materialized Views for BI Dashboard
    -- AUDIT-FIX-2026-04-22: column/table names aligned with the actual tenant
    -- schema (see backend/database.py block 4-22). Previously these MVs were
    -- silently skipped during tenant bootstrap because they referenced
    -- nonexistent columns/tables (issue: "16 MVs disabled" in audit plan).
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_revenue_summary AS
        SELECT date_trunc('month', invoice_date) AS month,
               SUM(total) AS total_revenue,
               COUNT(*) AS invoice_count
        FROM invoices
        WHERE invoice_type = 'sale' AND status = 'posted'
        GROUP BY date_trunc('month', invoice_date);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_revenue_month ON mv_revenue_summary(month);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_expense_summary AS
        SELECT date_trunc('month', invoice_date) AS month,
               SUM(total) AS total_expenses,
               COUNT(*) AS invoice_count
        FROM invoices
        WHERE invoice_type = 'purchase' AND status = 'posted'
        GROUP BY date_trunc('month', invoice_date);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_expense_month ON mv_expense_summary(month);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_cash_position AS
        SELECT ta.id AS account_id,
               ta.name AS account_name,
               COALESCE(SUM(CASE
                   WHEN tt.transaction_type IN ('deposit','receipt','transfer_in') THEN tt.amount
                   WHEN tt.transaction_type IN ('withdraw','payment','transfer_out') THEN -tt.amount
                   ELSE 0
               END), 0) AS balance
        FROM treasury_accounts ta
        LEFT JOIN treasury_transactions tt
               ON tt.treasury_id = ta.id AND tt.status = 'completed'
        GROUP BY ta.id, ta.name;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_cash_account ON mv_cash_position(account_id);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_customers AS
        SELECT i.party_id,
               p.name AS customer_name,
               SUM(i.total) AS total_revenue,
               COUNT(*) AS order_count
        FROM invoices i
        JOIN parties p ON p.id = i.party_id
        WHERE i.invoice_type = 'sale' AND i.status = 'posted'
        GROUP BY i.party_id, p.name;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_top_cust_party ON mv_top_customers(party_id);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ar_aging AS
        SELECT party_id,
               SUM(CASE WHEN NOW() - due_date <= INTERVAL '30 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS current_bucket,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '30 days' AND NOW() - due_date <= INTERVAL '60 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_30,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '60 days' AND NOW() - due_date <= INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_60,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_90_plus
        FROM invoices
        WHERE invoice_type = 'sale' AND status IN ('posted', 'partially_paid')
        GROUP BY party_id;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ar_aging_party ON mv_ar_aging(party_id);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ap_aging AS
        SELECT party_id,
               SUM(CASE WHEN NOW() - due_date <= INTERVAL '30 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS current_bucket,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '30 days' AND NOW() - due_date <= INTERVAL '60 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_30,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '60 days' AND NOW() - due_date <= INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_60,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_90_plus
        FROM invoices
        WHERE invoice_type = 'purchase' AND status IN ('posted', 'partially_paid')
        GROUP BY party_id;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ap_aging_party ON mv_ap_aging(party_id);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_inventory_turnover AS
        SELECT product_id,
               SUM(CASE WHEN transaction_type = 'out' THEN quantity ELSE 0 END) AS total_sold,
               AVG(quantity) AS avg_stock
        FROM inventory_transactions
        GROUP BY product_id;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_inv_turn_product ON mv_inventory_turnover(product_id);

    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sales_pipeline AS
        SELECT stage,
               COUNT(*) AS deal_count,
               SUM(expected_value) AS total_value
        FROM sales_opportunities
        GROUP BY stage;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_pipeline_stage ON mv_sales_pipeline(stage);

    -- ========== US10: Mobile Push Devices & Sync ==========
    CREATE TABLE IF NOT EXISTS push_devices (
        id SERIAL PRIMARY KEY,
        device_id VARCHAR(255) NOT NULL,
        user_id INTEGER NOT NULL,
        platform VARCHAR(10) NOT NULL CHECK (platform IN ('ios', 'android')),
        fcm_token TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        last_seen_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(device_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS ix_push_devices_user ON push_devices(user_id);
    CREATE INDEX IF NOT EXISTS ix_push_devices_active ON push_devices(is_active) WHERE is_active = TRUE;

    CREATE TABLE IF NOT EXISTS sync_queue (
        id SERIAL PRIMARY KEY,
        device_id VARCHAR(255) NOT NULL,
        user_id INTEGER NOT NULL,
        entity_type VARCHAR(50) NOT NULL,
        entity_id INTEGER NOT NULL,
        operation VARCHAR(10) NOT NULL,
        payload JSONB,
        device_timestamp TIMESTAMPTZ,
        server_timestamp TIMESTAMPTZ DEFAULT NOW(),
        sync_status VARCHAR(20) DEFAULT 'pending',
        conflict_resolution JSONB,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_sync_queue_device_status ON sync_queue(device_id, sync_status);

    -- ========== US11: Blanket Purchase Orders ==========
    CREATE TABLE IF NOT EXISTS blanket_purchase_orders (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER REFERENCES parties(id),
        agreement_number VARCHAR(50) NOT NULL UNIQUE,
        total_quantity DECIMAL(18, 4) DEFAULT 0,
        unit_price DECIMAL(18, 4) DEFAULT 0,
        total_amount DECIMAL(18, 4) DEFAULT 0,
        released_quantity DECIMAL(18, 4) DEFAULT 0,
        released_amount DECIMAL(18, 4) DEFAULT 0,
        valid_from DATE,
        valid_to DATE,
        status VARCHAR(20) DEFAULT 'draft',
        price_amendment_history JSONB DEFAULT '[]',
        branch_id INTEGER REFERENCES branches(id),
        currency VARCHAR(3) DEFAULT 'SAR',
        notes TEXT,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS blanket_po_release_orders (
        id SERIAL PRIMARY KEY,
        blanket_po_id INTEGER REFERENCES blanket_purchase_orders(id) ON DELETE CASCADE,
        purchase_order_id INTEGER REFERENCES purchase_orders(id),
        release_quantity DECIMAL(18, 4) DEFAULT 0,
        release_amount DECIMAL(18, 4) DEFAULT 0,
        release_date DATE,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_blanket_po_supplier ON blanket_purchase_orders(supplier_id);
    CREATE INDEX IF NOT EXISTS ix_blanket_po_status ON blanket_purchase_orders(status);
    CREATE INDEX IF NOT EXISTS ix_blanket_po_release_bpo ON blanket_po_release_orders(blanket_po_id);

    -- ========== US13: Shop Floor Logging ==========
    CREATE TABLE IF NOT EXISTS shop_floor_logs (
        id SERIAL PRIMARY KEY,
        work_order_id INTEGER REFERENCES production_orders(id),
        routing_operation_id INTEGER REFERENCES manufacturing_operations(id),
        operator_id INTEGER REFERENCES employees(id),
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        output_quantity DECIMAL(18, 4) DEFAULT 0,
        scrap_quantity DECIMAL(18, 4) DEFAULT 0,
        downtime_minutes INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'in_progress',
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_shopfloor_work_order ON shop_floor_logs(work_order_id);
    CREATE INDEX IF NOT EXISTS ix_shopfloor_operator ON shop_floor_logs(operator_id);

    -- ========== US14: Timesheet Entries ==========
    CREATE TABLE IF NOT EXISTS timesheet_entries (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        project_id INTEGER REFERENCES projects(id),
        task_id INTEGER REFERENCES project_tasks(id),
        date DATE NOT NULL,
        hours DECIMAL(5, 2) NOT NULL CHECK (hours > 0 AND hours <= 24),
        is_billable BOOLEAN DEFAULT FALSE,
        billing_rate DECIMAL(18, 4) DEFAULT 0,
        description TEXT,
        status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
        approved_by INTEGER REFERENCES employees(id),
        rejection_reason TEXT,
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_timesheet_employee ON timesheet_entries(employee_id);
    CREATE INDEX IF NOT EXISTS ix_timesheet_project ON timesheet_entries(project_id);
    CREATE INDEX IF NOT EXISTS ix_timesheet_date ON timesheet_entries(date);

    -- ========== US15: Resource Allocations ==========
    CREATE TABLE IF NOT EXISTS resource_allocations (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        project_id INTEGER REFERENCES projects(id),
        role VARCHAR(50),
        allocation_percent DECIMAL(5, 2) DEFAULT 100 CHECK (allocation_percent > 0 AND allocation_percent <= 100),
        start_date DATE NOT NULL,
        end_date DATE NOT NULL CHECK (end_date >= start_date),
        created_by INTEGER REFERENCES company_users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_resource_alloc_employee ON resource_allocations(employee_id);
    CREATE INDEX IF NOT EXISTS ix_resource_alloc_project ON resource_allocations(project_id);
    CREATE INDEX IF NOT EXISTS ix_resource_alloc_dates ON resource_allocations(start_date, end_date);

    -- review_cycles moved to get_organization_tables_sql()
    -- performance_reviews.cycle_id FK now inline in get_organization_tables_sql()

    CREATE TABLE IF NOT EXISTS performance_goals (
        id SERIAL PRIMARY KEY,
        review_id INTEGER REFERENCES performance_reviews(id) ON DELETE CASCADE,
        title VARCHAR(300) NOT NULL,
        description TEXT,
        weight DECIMAL(5, 2) DEFAULT 0,
        target VARCHAR(200),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_perf_goals_review ON performance_goals(review_id);

    -- ========== US17: CPQ (Configure-Price-Quote) ==========
    CREATE TABLE IF NOT EXISTS product_configurations (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id),
        name VARCHAR(200) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS config_option_groups (
        id SERIAL PRIMARY KEY,
        configuration_id INTEGER REFERENCES product_configurations(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        is_required BOOLEAN DEFAULT FALSE,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS config_options (
        id SERIAL PRIMARY KEY,
        group_id INTEGER REFERENCES config_option_groups(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        price_adjustment DECIMAL(18, 4) DEFAULT 0,
        is_default BOOLEAN DEFAULT FALSE,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS config_validation_rules (
        id SERIAL PRIMARY KEY,
        configuration_id INTEGER REFERENCES product_configurations(id) ON DELETE CASCADE,
        rule_type VARCHAR(30) NOT NULL,
        source_option_id INTEGER REFERENCES config_options(id),
        target_option_id INTEGER REFERENCES config_options(id),
        error_message TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cpq_pricing_rules (
        id SERIAL PRIMARY KEY,
        configuration_id INTEGER REFERENCES product_configurations(id) ON DELETE CASCADE,
        rule_type VARCHAR(30) NOT NULL,
        min_quantity DECIMAL(18, 4),
        max_quantity DECIMAL(18, 4),
        discount_percent DECIMAL(5, 2) DEFAULT 0,
        discount_amount DECIMAL(18, 4) DEFAULT 0,
        customer_group_id INTEGER,
        priority INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cpq_quotes (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER REFERENCES parties(id),
        quotation_id INTEGER,
        total_amount DECIMAL(18, 4) DEFAULT 0,
        discount_amount DECIMAL(18, 4) DEFAULT 0,
        final_amount DECIMAL(18, 4) DEFAULT 0,
        pdf_path TEXT,
        status VARCHAR(20) DEFAULT 'draft',
        valid_until DATE,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cpq_quote_lines (
        id SERIAL PRIMARY KEY,
        quote_id INTEGER REFERENCES cpq_quotes(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        selected_options JSONB DEFAULT '[]',
        quantity DECIMAL(18, 4) DEFAULT 1,
        base_unit_price DECIMAL(18, 4) DEFAULT 0,
        option_adjustments DECIMAL(18, 4) DEFAULT 0,
        discount_applied DECIMAL(18, 4) DEFAULT 0,
        final_unit_price DECIMAL(18, 4) DEFAULT 0,
        line_total DECIMAL(18, 4) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_cpq_config_product ON product_configurations(product_id);
    CREATE INDEX IF NOT EXISTS ix_cpq_quotes_customer ON cpq_quotes(customer_id);
    CREATE INDEX IF NOT EXISTS ix_cpq_quote_lines_quote ON cpq_quote_lines(quote_id);

    -- ========== US17: Demand Forecast ==========
    CREATE TABLE IF NOT EXISTS demand_forecasts (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id),
        warehouse_id INTEGER,
        forecast_method VARCHAR(30) DEFAULT 'moving_average',
        generated_date DATE NOT NULL,
        generated_by INTEGER REFERENCES company_users(id),
        history_months_used INTEGER DEFAULT 12,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS demand_forecast_periods (
        id SERIAL PRIMARY KEY,
        forecast_id INTEGER REFERENCES demand_forecasts(id) ON DELETE CASCADE,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        projected_quantity DECIMAL(18, 4) DEFAULT 0,
        confidence_lower DECIMAL(18, 4) DEFAULT 0,
        confidence_upper DECIMAL(18, 4) DEFAULT 0,
        manual_adjustment DECIMAL(18, 4),
        adjusted_quantity DECIMAL(18, 4),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_demand_forecast_product ON demand_forecasts(product_id);
    CREATE INDEX IF NOT EXISTS ix_demand_forecast_date ON demand_forecasts(generated_date);
    CREATE INDEX IF NOT EXISTS ix_demand_periods_forecast ON demand_forecast_periods(forecast_id);

    -- ========== US18: Campaign Recipients & Lead Attribution ==========
    CREATE TABLE IF NOT EXISTS campaign_recipients (
        id SERIAL PRIMARY KEY,
        campaign_id INTEGER REFERENCES marketing_campaigns(id) ON DELETE CASCADE,
        contact_id INTEGER REFERENCES parties(id) ON DELETE CASCADE,
        channel VARCHAR(30) DEFAULT 'email',
        delivery_status VARCHAR(20) DEFAULT 'pending',
        opened_at TIMESTAMPTZ,
        clicked_at TIMESTAMPTZ,
        responded_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS campaign_lead_attributions (
        id SERIAL PRIMARY KEY,
        campaign_id INTEGER REFERENCES marketing_campaigns(id) ON DELETE CASCADE,
        lead_id INTEGER REFERENCES sales_opportunities(id) ON DELETE CASCADE,
        attributed_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_campaign_recipients_campaign ON campaign_recipients(campaign_id);
    CREATE INDEX IF NOT EXISTS ix_campaign_recipients_contact ON campaign_recipients(contact_id);
    CREATE INDEX IF NOT EXISTS ix_campaign_lead_attr_campaign ON campaign_lead_attributions(campaign_id);
    """


def get_performance_indexes_sql() -> str:
    """Returns SQL for performance optimization indexes (Phase 7.5)"""
    return """
    -- ===== PERFORMANCE INDEXES (Phase 7.5) =====

    -- Journal Entries - heavily queried for reports
    CREATE INDEX IF NOT EXISTS idx_je_date_status ON journal_entries(entry_date, status);
    CREATE INDEX IF NOT EXISTS idx_je_source ON journal_entries(source);
    CREATE INDEX IF NOT EXISTS idx_je_created_by ON journal_entries(created_by);
    CREATE INDEX IF NOT EXISTS idx_journal_entries_created_at ON journal_entries(created_at DESC);

    -- Journal Lines - joins and aggregations
    CREATE INDEX IF NOT EXISTS idx_jl_account ON journal_lines(account_id);
    CREATE INDEX IF NOT EXISTS idx_jl_je_account ON journal_lines(journal_entry_id, account_id);

    -- Invoices - filtering by date / status / party
    CREATE INDEX IF NOT EXISTS idx_inv_date_status ON invoices(invoice_date, status);
    CREATE INDEX IF NOT EXISTS idx_inv_party ON invoices(party_id);
    CREATE INDEX IF NOT EXISTS idx_inv_type_status ON invoices(invoice_type, status);

    -- Products - SKU and barcode lookups
    CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
    CREATE INDEX IF NOT EXISTS idx_products_code ON products(product_code);
    CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);

    -- Inventory/POS/CRM hot paths
    CREATE INDEX IF NOT EXISTS idx_inventory_product_warehouse ON inventory(product_id, warehouse_id);
    CREATE UNIQUE INDEX IF NOT EXISTS ux_pos_orders_client_order_id
        ON pos_orders(client_order_id) WHERE client_order_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_opportunity_activities_contact_id ON opportunity_activities(contact_id);


    -- Audit Log - most recent activity
    CREATE INDEX IF NOT EXISTS idx_audit_user_date ON audit_logs(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, resource_id);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_live ON audit_logs(created_at DESC) WHERE NOT is_archived;
    CREATE INDEX IF NOT EXISTS idx_audit_logs_archival ON audit_logs(created_at) WHERE is_archived = TRUE;
    -- T9.3: cold-storage archive tables for >7 year retention. Live tables
    -- stay slim; long-term forensic data still queryable from archive.
    CREATE TABLE IF NOT EXISTS audit_logs_archive (
        id              INTEGER       PRIMARY KEY,
        user_id         INTEGER,
        username        VARCHAR(100),
        action          VARCHAR(100),
        resource_type   VARCHAR(50),
        resource_id     VARCHAR(50),
        details         JSONB,
        ip_address      VARCHAR(50),
        branch_id       INTEGER,
        prev_hash       VARCHAR(64),
        hash            VARCHAR(64),
        chain_seq       BIGINT,
        created_at      TIMESTAMPTZ   NOT NULL,
        archived_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_created ON audit_logs_archive (created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_user ON audit_logs_archive (user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_chain ON audit_logs_archive (chain_seq);

    CREATE TABLE IF NOT EXISTS inventory_transactions_archive (
        id                  INTEGER       PRIMARY KEY,
        product_id          INTEGER,
        warehouse_id        INTEGER,
        transaction_type    VARCHAR(50)   NOT NULL,
        reference_type      VARCHAR(50),
        reference_id        INTEGER,
        reference_document  VARCHAR(100),
        quantity            DECIMAL(18, 4) NOT NULL,
        balance_before      DECIMAL(18, 4),
        balance_after       DECIMAL(18, 4),
        unit_cost           DECIMAL(18, 4),
        total_cost          DECIMAL(18, 4),
        notes               TEXT,
        created_by          INTEGER,
        created_at          TIMESTAMPTZ   NOT NULL,
        archived_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_inv_tx_arch_created ON inventory_transactions_archive (created_at);
    CREATE INDEX IF NOT EXISTS idx_inv_tx_arch_product ON inventory_transactions_archive (product_id);
    -- T3.7 (audit #21,#22): hash-chain unique index + immutability trigger.
    CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_logs_chain_seq ON audit_logs(chain_seq);
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    -- T10.1 P1 #110i — pg_trgm + GIN trigram indexes so the product
    -- search box (substring ILIKE on product_name and party search on
    -- name/phone) can use an index instead of falling back to seq scan.
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS idx_products_name_trgm
        ON products USING GIN (product_name gin_trgm_ops);
    CREATE INDEX IF NOT EXISTS idx_products_code_prefix
        ON products (product_code text_pattern_ops);
    CREATE INDEX IF NOT EXISTS idx_parties_name_trgm
        ON parties USING GIN (name gin_trgm_ops);
    -- T10.1 P1 #97 — phone lookups normalise whitespace/dashes; index
    -- on the cleaned form so equality lookups can use the index.
    CREATE INDEX IF NOT EXISTS idx_parties_phone_clean
        ON parties (REGEXP_REPLACE(COALESCE(phone, ''), '[^0-9+]', '', 'g'));
    -- T10.1 P1 #94 — broader pg_trgm coverage for high-frequency search
    -- surfaces so leading-wildcard ILIKE can use an index. Each index
    -- is wrapped in a DO-block guard because the underlying column may
    -- be missing on legacy tenants — silently skip rather than abort.
    DO $do_trgm_extras$
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='invoices' AND column_name='invoice_number') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_invoices_number_trgm
                       ON invoices USING GIN (invoice_number gin_trgm_ops)';
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='expenses' AND column_name='expense_number') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_expenses_number_trgm
                       ON expenses USING GIN (expense_number gin_trgm_ops)';
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='journal_entries' AND column_name='entry_number') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_journal_entries_number_trgm
                       ON journal_entries USING GIN (entry_number gin_trgm_ops)';
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='purchase_invoices' AND column_name='invoice_number') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_purchase_invoices_number_trgm
                       ON purchase_invoices USING GIN (invoice_number gin_trgm_ops)';
        END IF;
    END
    $do_trgm_extras$;
    -- T10.1 P1 #80 — FSM SLA tracking. Default response window = 4h,
    -- resolution window = 24h * (priority weight). Lazy ALTERs so we
    -- don't disturb existing tenants.
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_response_minutes INTEGER DEFAULT 240;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_resolution_minutes INTEGER DEFAULT 1440;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS response_due_at TIMESTAMPTZ;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS resolution_due_at TIMESTAMPTZ;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS first_response_at TIMESTAMPTZ;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_breach_response BOOLEAN DEFAULT FALSE;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_breach_resolution BOOLEAN DEFAULT FALSE;
    ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_warned_at TIMESTAMPTZ;
    -- Auto-populate due timestamps on INSERT when caller didn't supply them.
    CREATE OR REPLACE FUNCTION service_requests_set_sla_fn()
    RETURNS trigger AS $sr_sla$
    BEGIN
        IF NEW.response_due_at IS NULL THEN
            NEW.response_due_at := COALESCE(NEW.created_at, NOW())
                + make_interval(mins => COALESCE(NEW.sla_response_minutes, 240));
        END IF;
        IF NEW.resolution_due_at IS NULL THEN
            NEW.resolution_due_at := COALESCE(NEW.created_at, NOW())
                + make_interval(mins => COALESCE(NEW.sla_resolution_minutes, 1440));
        END IF;
        RETURN NEW;
    END;
    $sr_sla$ LANGUAGE plpgsql;
    DROP TRIGGER IF EXISTS trg_service_requests_set_sla ON service_requests;
    CREATE TRIGGER trg_service_requests_set_sla
        BEFORE INSERT ON service_requests
        FOR EACH ROW EXECUTE FUNCTION service_requests_set_sla_fn();
    CREATE INDEX IF NOT EXISTS idx_service_requests_sla_due
        ON service_requests(response_due_at, resolution_due_at)
        WHERE COALESCE(is_deleted, FALSE) = FALSE;

    -- T10.1 P1 #89 — Payment gateway retry tracking. Outbox-style queue so
    -- transient gateway failures (Stripe/Tap/PayTabs) can be retried by
    -- a scheduler job instead of failing the user request once.
    CREATE TABLE IF NOT EXISTS payment_gateway_retries (
        id SERIAL PRIMARY KEY,
        gateway VARCHAR(40) NOT NULL,
        operation VARCHAR(40) NOT NULL,
        reference_type VARCHAR(60),
        reference_id VARCHAR(60),
        request_payload JSONB NOT NULL,
        last_error TEXT,
        attempt_count INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 5,
        next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','succeeded','failed','dead')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_payment_retries_status_due
        ON payment_gateway_retries(status, next_attempt_at)
        WHERE status = 'pending';
    CREATE INDEX IF NOT EXISTS idx_payment_retries_ref
        ON payment_gateway_retries(reference_type, reference_id);

    -- T11 P1 #50/#56/#66 — widen PII columns so AES-256-GCM ciphertext
    -- (≈70-80 base64 chars) fits without truncation. Application-layer
    -- encryption helper lives in ``utils/pii_encryption.py``; backfill
    -- runs via ``scripts/encrypt_existing_pii.py``. Idempotent: only
    -- promotes VARCHAR(*) → TEXT, never narrows.
    DO $do_pii_widen$
    BEGIN
        -- treasury_accounts.iban / account_number
        BEGIN ALTER TABLE treasury_accounts      ALTER COLUMN iban           TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE treasury_accounts      ALTER COLUMN account_number TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE supplier_bank_accounts ALTER COLUMN iban           TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE supplier_bank_accounts ALTER COLUMN account_number TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE customer_bank_accounts ALTER COLUMN iban           TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE customer_bank_accounts ALTER COLUMN account_number TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE parties                ALTER COLUMN iban           TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE parties                ALTER COLUMN tax_number     TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE employees              ALTER COLUMN tax_id         TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
        BEGIN ALTER TABLE employees              ALTER COLUMN social_security TYPE TEXT; EXCEPTION WHEN OTHERS THEN NULL; END;
    END
    $do_pii_widen$;

    -- T13 P1 #64/#65 — link employees to a work_policy (nullable, opt-in).
    DO $do_emp_workpolicy$
    BEGIN
        BEGIN
            ALTER TABLE employees
                ADD COLUMN IF NOT EXISTS work_policy_id INTEGER REFERENCES work_policies(id);
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END
    $do_emp_workpolicy$;
    CREATE INDEX IF NOT EXISTS idx_employees_work_policy ON employees(work_policy_id);
    CREATE INDEX IF NOT EXISTS idx_attendance_emp_date ON attendance(employee_id, date);

    -- T13 P1 #64/#65 — surface absence deduction on payroll entries so the
    -- payslip can show it as its own line item (instead of being silently
    -- folded into ``violation_deduction``).
    DO $do_payroll_absence$
    BEGIN
        BEGIN
            ALTER TABLE payroll_entries
                ADD COLUMN IF NOT EXISTS absence_deduction NUMERIC(18,4) DEFAULT 0;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
        BEGIN
            ALTER TABLE payroll_entries
                ADD COLUMN IF NOT EXISTS absent_days INTEGER DEFAULT 0;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END
    $do_payroll_absence$;

    -- =====================================================================
    -- T15 P1 #70/#71/#72/#104 — Petty cash funds + salary advances + state
    -- history for service requests + attachment content text. All idempotent
    -- so re-running is a no-op on upgraded tenants.
    -- =====================================================================

    -- Petty cash fund: a small cash float held by a custodian (employee or
    -- branch manager) for everyday small expenses. Replenished when low,
    -- reconciled to a treasury account on each top-up.
    CREATE TABLE IF NOT EXISTS petty_cash_funds (
        id SERIAL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        custodian_employee_id INTEGER REFERENCES employees(id),
        treasury_account_id   INTEGER REFERENCES treasury_accounts(id),
        gl_account_id         INTEGER REFERENCES accounts(id),
        branch_id             INTEGER REFERENCES branches(id),
        currency VARCHAR(3) DEFAULT 'SAR',
        ceiling_amount  NUMERIC(18,4) DEFAULT 0,    -- max float allowed
        current_balance NUMERIC(18,4) DEFAULT 0,    -- current cash on hand
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- Petty cash transactions: every disbursement/replenishment/return
    -- against a fund. Application code adjusts ``petty_cash_funds.current_balance``
    -- atomically when posting one of these rows.
    CREATE TABLE IF NOT EXISTS petty_cash_transactions (
        id SERIAL PRIMARY KEY,
        fund_id INTEGER REFERENCES petty_cash_funds(id) ON DELETE CASCADE,
        -- replenish: + balance (treasury → fund). disburse: - balance (fund → expense).
        -- return: + balance (employee returns unspent). adjustment: signed.
        txn_type VARCHAR(20) NOT NULL DEFAULT 'disburse',
        amount   NUMERIC(18,4) NOT NULL,
        txn_date DATE NOT NULL DEFAULT CURRENT_DATE,
        description TEXT,
        expense_id  INTEGER REFERENCES expenses(id),
        je_id       INTEGER REFERENCES journal_entries(id),
        created_by  INTEGER REFERENCES company_users(id),
        created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_petty_cash_txn_fund ON petty_cash_transactions(fund_id, txn_date);

    -- Salary advances: similar to employee_loans but a *single* lump sum
    -- recovered from one or more upcoming payroll periods. Kept separate
    -- so reporting can distinguish "loans" (long-term, multi-installment)
    -- from "advances" (short-term, often single deduction).
    CREATE TABLE IF NOT EXISTS salary_advances (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES employees(id),
        amount         NUMERIC(18,4) NOT NULL,
        recovered_amount NUMERIC(18,4) DEFAULT 0,
        installments   INTEGER DEFAULT 1,    -- spread across N payrolls
        request_date   DATE DEFAULT CURRENT_DATE,
        approved_by    INTEGER REFERENCES company_users(id),
        approved_at    TIMESTAMPTZ,
        paid_at        TIMESTAMPTZ,         -- when treasury actually paid out
        treasury_account_id INTEGER REFERENCES treasury_accounts(id),
        je_id          INTEGER REFERENCES journal_entries(id),
        status VARCHAR(20) DEFAULT 'pending',  -- pending|approved|paid|recovering|recovered|cancelled
        reason TEXT,
        branch_id INTEGER REFERENCES branches(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_salary_advances_emp_status ON salary_advances(employee_id, status);

    -- T15 #104 — surface advance recovery as its own line on the payslip
    -- (parallel to the absence_deduction column added by T13).
    DO $do_payroll_advance$
    BEGIN
        BEGIN
            ALTER TABLE payroll_entries
                ADD COLUMN IF NOT EXISTS advance_deduction NUMERIC(18,4) DEFAULT 0;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END
    $do_payroll_advance$;

    -- T18 #77/#78/#79/#81 — service-request state history (audit trail of
    -- every transition, with actor, timestamp, optional comment). The hot
    -- path in routers/services.py inserts one row per transition.
    CREATE TABLE IF NOT EXISTS service_request_state_history (
        id SERIAL PRIMARY KEY,
        request_id INTEGER REFERENCES service_requests(id) ON DELETE CASCADE,
        from_status VARCHAR(30),
        to_status   VARCHAR(30) NOT NULL,
        actor_user_id INTEGER REFERENCES company_users(id),
        actor_username VARCHAR(120),
        comment TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_sr_state_history_req ON service_request_state_history(request_id, created_at);

    -- T18 #96 — Attachment full-text content. Populated by background
    -- extractors (PDF / DOCX / XLSX). NULL ⇒ extraction not yet attempted
    -- or unsupported MIME. We store raw extracted text plus a tsvector for
    -- fast ILIKE/FTS search; a partial GIN index keeps the hot path quick.
    DO $do_attach_content$
    BEGIN
        BEGIN
            ALTER TABLE attachments
                ADD COLUMN IF NOT EXISTS content_text TEXT;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
        BEGIN
            ALTER TABLE attachments
                ADD COLUMN IF NOT EXISTS content_extracted_at TIMESTAMPTZ;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
        BEGIN
            ALTER TABLE attachments
                ADD COLUMN IF NOT EXISTS content_extraction_error TEXT;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END
    $do_attach_content$;
    CREATE INDEX IF NOT EXISTS idx_attachments_content_trgm
        ON attachments USING gin (content_text gin_trgm_ops)
        WHERE content_text IS NOT NULL;

    -- T17 #88 — POS offline sync conflicts. When a client comes back online
    -- with stale operations, the server records the conflict here for human
    -- review (vs. silently dropping or blindly applying).
    CREATE TABLE IF NOT EXISTS pos_sync_conflicts (
        id SERIAL PRIMARY KEY,
        session_id INTEGER REFERENCES pos_sessions(id) ON DELETE CASCADE,
        client_op_id VARCHAR(80),       -- client-generated UUID for idempotency
        op_type VARCHAR(30),            -- create_order|void|return|payment
        client_payload JSONB,
        conflict_kind VARCHAR(40),      -- duplicate|stale_session|stock_oversold|price_changed
        server_state JSONB,             -- what the server has now
        resolution VARCHAR(20) DEFAULT 'pending',  -- pending|accepted|rejected|merged
        resolved_by INTEGER REFERENCES company_users(id),
        resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_pos_sync_conflicts_session
        ON pos_sync_conflicts(session_id, resolution);

    -- T16 #44: invoice header amendment fields.
    DO $do_inv_amend_cols$
    BEGIN
        BEGIN
            ALTER TABLE invoices ADD COLUMN IF NOT EXISTS customer_reference VARCHAR(100);
            ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sales_rep_id INTEGER REFERENCES company_users(id) ON DELETE SET NULL;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END $do_inv_amend_cols$;

    CREATE OR REPLACE FUNCTION audit_logs_immutable_fn()
    RETURNS trigger AS $audit_immut$
    DECLARE
        allowed TEXT;
    BEGIN
        BEGIN
            allowed := current_setting('audit_logs.allow_admin_op', true);
        EXCEPTION WHEN OTHERS THEN
            allowed := NULL;
        END;
        IF allowed IS NULL OR allowed = '' THEN
            RAISE EXCEPTION
                'audit_logs is append-only (T3.7 audit #21) — set audit_logs.allow_admin_op for retention jobs';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF OLD.id          IS DISTINCT FROM NEW.id          OR
               OLD.user_id     IS DISTINCT FROM NEW.user_id     OR
               OLD.username    IS DISTINCT FROM NEW.username    OR
               OLD.action      IS DISTINCT FROM NEW.action      OR
               OLD.resource_type IS DISTINCT FROM NEW.resource_type OR
               OLD.resource_id IS DISTINCT FROM NEW.resource_id OR
               OLD.details     IS DISTINCT FROM NEW.details     OR
               OLD.ip_address  IS DISTINCT FROM NEW.ip_address  OR
               OLD.branch_id   IS DISTINCT FROM NEW.branch_id   OR
               OLD.created_at  IS DISTINCT FROM NEW.created_at  OR
               OLD.prev_hash   IS DISTINCT FROM NEW.prev_hash   OR
               OLD.hash        IS DISTINCT FROM NEW.hash        OR
               OLD.chain_seq   IS DISTINCT FROM NEW.chain_seq THEN
                RAISE EXCEPTION
                    'audit_logs UPDATE limited to is_archived/archived_at';
            END IF;
        END IF;
        RETURN COALESCE(NEW, OLD);
    END;
    $audit_immut$ LANGUAGE plpgsql;
    DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
    DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs;
    CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn();
    CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn();

    -- Parties - name search
    CREATE INDEX IF NOT EXISTS idx_parties_name ON parties(name);
    CREATE INDEX IF NOT EXISTS idx_parties_type ON parties(party_type);

    -- Employees
    CREATE INDEX IF NOT EXISTS idx_emp_code ON employees(employee_code);
    CREATE INDEX IF NOT EXISTS idx_emp_dept ON employees(department_id);

    -- Checks
    CREATE INDEX IF NOT EXISTS idx_checks_recv_status ON checks_receivable(status);
    CREATE INDEX IF NOT EXISTS idx_checks_recv_due ON checks_receivable(due_date);
    CREATE INDEX IF NOT EXISTS idx_checks_pay_status ON checks_payable(status);
    CREATE INDEX IF NOT EXISTS idx_checks_pay_due ON checks_payable(due_date);

    -- Notifications
    CREATE INDEX IF NOT EXISTS idx_notif_user_read ON notifications(user_id, is_read);
    CREATE INDEX IF NOT EXISTS idx_notifications_retry ON notifications(last_retry_at) WHERE delivery_status = 'failed' AND retry_count < 3;

    -- Phase 1 Hardening: Missing FK and query indexes
    CREATE INDEX IF NOT EXISTS idx_parties_party_code ON parties(party_code);
    CREATE INDEX IF NOT EXISTS idx_parties_branch_id ON parties(branch_id);
    CREATE INDEX IF NOT EXISTS idx_parties_party_group_id ON parties(party_group_id);

    CREATE INDEX IF NOT EXISTS idx_party_transactions_payment_id ON party_transactions(payment_id);
    CREATE INDEX IF NOT EXISTS idx_party_transactions_invoice_id ON party_transactions(invoice_id);

    CREATE INDEX IF NOT EXISTS idx_invoices_warehouse_id ON invoices(warehouse_id);
    CREATE INDEX IF NOT EXISTS idx_invoices_branch_id ON invoices(branch_id);

    CREATE INDEX IF NOT EXISTS idx_invoice_lines_product_id ON invoice_lines(product_id);

    CREATE INDEX IF NOT EXISTS idx_journal_lines_cost_center_id ON journal_lines(cost_center_id);
    CREATE INDEX IF NOT EXISTS idx_journal_entries_branch_id ON journal_entries(branch_id);

    CREATE INDEX IF NOT EXISTS idx_suppliers_branch_id ON suppliers(branch_id);
    CREATE INDEX IF NOT EXISTS idx_suppliers_supplier_group_id ON suppliers(supplier_group_id);

    CREATE INDEX IF NOT EXISTS idx_supplier_transactions_payment_id ON supplier_transactions(payment_id);
    CREATE INDEX IF NOT EXISTS idx_supplier_transactions_invoice_id ON supplier_transactions(invoice_id);

    CREATE INDEX IF NOT EXISTS idx_customers_branch_id ON customers(branch_id);
    CREATE INDEX IF NOT EXISTS idx_customers_customer_group_id ON customers(customer_group_id);

    CREATE INDEX IF NOT EXISTS idx_customer_transactions_receipt_id ON customer_transactions(receipt_id);
    CREATE INDEX IF NOT EXISTS idx_customer_transactions_invoice_id ON customer_transactions(invoice_id);

    CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);
    CREATE INDEX IF NOT EXISTS idx_products_unit_id ON products(unit_id);

    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_warehouse_id ON inventory_transactions(warehouse_id);
    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_product_id ON inventory_transactions(product_id);
    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_product_date ON inventory_transactions(product_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_reference_id ON inventory_transactions(reference_id);

    -- T10.1 P1 #110d \u2014 hot path on the shop floor: filter open production
    -- orders by status & due_date. Without this index it does a full scan.
    CREATE INDEX IF NOT EXISTS idx_production_orders_status_due ON production_orders(status, due_date);
    CREATE INDEX IF NOT EXISTS idx_production_orders_product ON production_orders(product_id);
    -- T10.1 P1 #63 \u2014 same for HR leave queries.
    CREATE INDEX IF NOT EXISTS idx_leave_requests_status_start ON leave_requests(status, start_date);
    CREATE INDEX IF NOT EXISTS idx_leave_requests_employee_start ON leave_requests(employee_id, start_date);

    CREATE INDEX IF NOT EXISTS idx_purchase_orders_party_id ON purchase_orders(party_id);
    CREATE INDEX IF NOT EXISTS idx_purchase_orders_branch_id ON purchase_orders(branch_id);

    CREATE INDEX IF NOT EXISTS idx_sales_orders_party_id ON sales_orders(party_id);
    CREATE INDEX IF NOT EXISTS idx_sales_orders_branch_id ON sales_orders(branch_id);

    CREATE INDEX IF NOT EXISTS idx_sales_returns_party_id ON sales_returns(party_id);
    CREATE INDEX IF NOT EXISTS idx_sales_returns_branch_id ON sales_returns(branch_id);
    CREATE INDEX IF NOT EXISTS idx_sales_returns_invoice_id ON sales_returns(invoice_id);

    CREATE INDEX IF NOT EXISTS idx_payment_vouchers_party_id ON payment_vouchers(party_id);
    CREATE INDEX IF NOT EXISTS idx_payment_vouchers_party_type_id ON payment_vouchers(party_type, party_id);
    CREATE INDEX IF NOT EXISTS idx_payment_vouchers_branch_id ON payment_vouchers(branch_id);

    CREATE INDEX IF NOT EXISTS idx_employees_position_id ON employees(position_id);
    CREATE INDEX IF NOT EXISTS idx_employees_manager_id ON employees(manager_id);
    CREATE INDEX IF NOT EXISTS idx_employees_user_id ON employees(user_id);

    CREATE INDEX IF NOT EXISTS idx_employee_loans_employee_id ON employee_loans(employee_id);
    CREATE INDEX IF NOT EXISTS idx_employee_loans_branch_id ON employee_loans(branch_id);

    CREATE INDEX IF NOT EXISTS idx_cost_centers_department_id ON cost_centers(department_id);

    CREATE INDEX IF NOT EXISTS idx_commission_rules_salesperson_id ON commission_rules(salesperson_id);
    CREATE INDEX IF NOT EXISTS idx_sales_commissions_invoice_id ON sales_commissions(invoice_id);

    CREATE INDEX IF NOT EXISTS idx_customer_price_list_items_price_list_id ON customer_price_list_items(price_list_id);

    CREATE INDEX IF NOT EXISTS idx_stock_adjustments_product_id ON stock_adjustments(product_id);
    CREATE INDEX IF NOT EXISTS idx_stock_adjustments_warehouse_id ON stock_adjustments(warehouse_id);
    """


def get_gl_integrity_guards_sql() -> str:
    """Returns SQL that enforces GL invariants at the database level.

    Mirrors Alembic migration 0008_gl_integrity_guards so that freshly
    created tenant databases (which are stamped to head, not upgraded) gain
    the same protections as migrated tenants.

    Must run AFTER journal_entries, journal_lines, fiscal_periods, and
    currencies have been created (i.e. last in the bootstrap sequence).
    Every statement is idempotent.
    """
    return """
    -- ===== GL INTEGRITY GUARDS =====
    -- FIN-C1 / DB-C1: Idempotency & source-duplicate unique indexes
    CREATE UNIQUE INDEX IF NOT EXISTS uq_je_idempotency
        ON journal_entries (idempotency_key)
        WHERE idempotency_key IS NOT NULL;

    CREATE UNIQUE INDEX IF NOT EXISTS uq_je_source
        ON journal_entries (source, source_id, entry_date)
        WHERE source <> 'Manual' AND source_id IS NOT NULL;

    -- FIN-C2 / DB-C2: CHECK constraints on journal_lines
    DO $chk$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_jl_nonneg') THEN
            ALTER TABLE journal_lines
                ADD CONSTRAINT chk_jl_nonneg CHECK (debit >= 0 AND credit >= 0);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_jl_exclusive') THEN
            ALTER TABLE journal_lines
                ADD CONSTRAINT chk_jl_exclusive CHECK (NOT (debit > 0 AND credit > 0));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_jl_nonzero') THEN
            ALTER TABLE journal_lines
                ADD CONSTRAINT chk_jl_nonzero CHECK (debit + credit > 0);
        END IF;
    END $chk$;

    -- DB-C3: status vocabulary CHECK on journal_entries
    DO $st$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_je_status') THEN
            ALTER TABLE journal_entries
                ADD CONSTRAINT chk_je_status
                CHECK (status IN ('draft','posted','void','reversed'));
        END IF;
    END $st$;

    -- FIN-C8 / DB-C6: at most one base currency
    CREATE UNIQUE INDEX IF NOT EXISTS uq_currency_one_base
        ON currencies ((TRUE))
        WHERE is_base = TRUE;

    -- FIN-C3: Closed-period guard
    CREATE OR REPLACE FUNCTION assert_period_open() RETURNS trigger AS $fn1$
    DECLARE
        v_closed BOOLEAN;
    BEGIN
        IF NEW.status IS DISTINCT FROM 'posted' THEN
            RETURN NEW;
        END IF;
        SELECT TRUE INTO v_closed
        FROM fiscal_periods
        WHERE NEW.entry_date BETWEEN start_date AND end_date
          AND is_closed = TRUE
        LIMIT 1;
        IF v_closed THEN
            RAISE EXCEPTION 'Posting into a closed fiscal period is forbidden (entry_date=%)', NEW.entry_date
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $fn1$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_je_period_open ON journal_entries;
    CREATE TRIGGER trg_je_period_open
        BEFORE INSERT OR UPDATE OF status, entry_date ON journal_entries
        FOR EACH ROW EXECUTE FUNCTION assert_period_open();

    -- FIN-C4: Posted journal entries are immutable
    CREATE OR REPLACE FUNCTION block_posted_je_changes() RETURNS trigger AS $fn2$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.status = 'posted' THEN
                RAISE EXCEPTION 'Posted journal entries cannot be deleted (id=%)', OLD.id
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END IF;
        IF OLD.status = 'posted' AND NEW.status NOT IN ('void','reversed','posted') THEN
            RAISE EXCEPTION 'Posted journal entries are immutable (id=%, old=%, new=%)',
                OLD.id, OLD.status, NEW.status USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'posted' AND NEW.status = 'posted' THEN
            IF (NEW.entry_date <> OLD.entry_date)
               OR (NEW.description IS DISTINCT FROM OLD.description)
               OR (NEW.currency IS DISTINCT FROM OLD.currency)
               OR (NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate)
               OR (NEW.branch_id IS DISTINCT FROM OLD.branch_id)
               OR (NEW.reference IS DISTINCT FROM OLD.reference) THEN
                RAISE EXCEPTION 'Posted journal entry fields are immutable (id=%)', OLD.id
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $fn2$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_je_immutable ON journal_entries;
    CREATE TRIGGER trg_je_immutable
        BEFORE UPDATE OR DELETE ON journal_entries
        FOR EACH ROW EXECUTE FUNCTION block_posted_je_changes();

    CREATE OR REPLACE FUNCTION block_posted_jl_changes() RETURNS trigger AS $fn3$
    DECLARE
        v_status TEXT;
        v_id     BIGINT;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            v_id := OLD.journal_entry_id;
        ELSE
            v_id := NEW.journal_entry_id;
        END IF;
        SELECT status INTO v_status FROM journal_entries WHERE id = v_id;
        IF v_status = 'posted' THEN
            RAISE EXCEPTION 'Lines of a posted journal entry are immutable (je_id=%)', v_id
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END;
    $fn3$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_jl_immutable ON journal_lines;
    CREATE TRIGGER trg_jl_immutable
        BEFORE UPDATE OR DELETE ON journal_lines
        FOR EACH ROW EXECUTE FUNCTION block_posted_jl_changes();

    -- Status-aware balance trigger (supersedes legacy trg_journal_balance)
    DROP TRIGGER IF EXISTS trg_journal_balance ON journal_lines;

    CREATE OR REPLACE FUNCTION assert_je_balanced() RETURNS trigger AS $fn4$
    DECLARE
        v_je  BIGINT;
        v_sum NUMERIC;
        v_status TEXT;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            v_je := OLD.journal_entry_id;
        ELSE
            v_je := NEW.journal_entry_id;
        END IF;
        SELECT status INTO v_status FROM journal_entries WHERE id = v_je;
        IF v_status IS DISTINCT FROM 'posted' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END IF;
        SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0)
          INTO v_sum
          FROM journal_lines
         WHERE journal_entry_id = v_je;
        IF ABS(v_sum) > 0.005 THEN
            RAISE EXCEPTION 'Unbalanced journal entry (je_id=%, diff=%)', v_je, v_sum
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END;
    $fn4$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_je_balanced ON journal_lines;
    CREATE CONSTRAINT TRIGGER trg_je_balanced
        AFTER INSERT OR UPDATE OR DELETE ON journal_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_je_balanced();

    -- PERF-H1 / DB-H8: composite indexes
    CREATE INDEX IF NOT EXISTS idx_je_branch_date ON journal_entries (branch_id, entry_date);
    CREATE INDEX IF NOT EXISTS idx_je_status_date ON journal_entries (status, entry_date);
    CREATE INDEX IF NOT EXISTS idx_je_entry_date  ON journal_entries (entry_date);
    -- TASK-031: composite index on (source, source_id, entry_date) so gl_service's
    -- duplicate-source guard uses an index scan instead of a seq scan on JE.
    CREATE INDEX IF NOT EXISTS idx_je_source_srcid_date ON journal_entries (source, source_id, entry_date);
    CREATE INDEX IF NOT EXISTS idx_jl_account_je  ON journal_lines (account_id, journal_entry_id);
    CREATE INDEX IF NOT EXISTS idx_jl_je          ON journal_lines (journal_entry_id);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-034: Multi-Book Accounting (parallel ledgers).
    -- Each tenant gets a `primary` ledger by default. Add IFRS / tax / mgmt
    -- ledgers as needed; reporting filters by ledger_id.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS ledgers (
        id SERIAL PRIMARY KEY,
        code VARCHAR(30) UNIQUE NOT NULL,
        name VARCHAR(100) NOT NULL,
        is_primary BOOLEAN DEFAULT FALSE,
        framework VARCHAR(30),  -- e.g. 'local_gaap' | 'ifrs' | 'tax' | 'mgmt'
        currency VARCHAR(10),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO ledgers (code, name, is_primary, framework)
    VALUES ('primary', 'Primary Ledger', TRUE, 'local_gaap')
    ON CONFLICT (code) DO NOTHING;

    ALTER TABLE journal_entries
        ADD COLUMN IF NOT EXISTS ledger_id INTEGER REFERENCES ledgers(id);
    UPDATE journal_entries SET ledger_id = (SELECT id FROM ledgers WHERE code='primary')
        WHERE ledger_id IS NULL;
    CREATE INDEX IF NOT EXISTS idx_je_ledger_date ON journal_entries (ledger_id, entry_date);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-035: Dimensional Accounting — 6 analytical dimensions on each JL.
    -- Dimensions are free-form VARCHARs so tenants can assign meaning without
    -- schema migrations. Reporting aggregates with GROUP BY dim_N.
    -- ═════════════════════════════════════════════════════════════════════
    ALTER TABLE journal_lines
        ADD COLUMN IF NOT EXISTS dim_segment        VARCHAR(50),
        ADD COLUMN IF NOT EXISTS dim_project        VARCHAR(50),
        ADD COLUMN IF NOT EXISTS dim_product_line   VARCHAR(50),
        ADD COLUMN IF NOT EXISTS dim_customer_group VARCHAR(50),
        ADD COLUMN IF NOT EXISTS dim_employee       VARCHAR(50),
        ADD COLUMN IF NOT EXISTS dim_custom_1       VARCHAR(50);
    CREATE INDEX IF NOT EXISTS idx_jl_dim_project ON journal_lines (dim_project) WHERE dim_project IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_jl_dim_segment ON journal_lines (dim_segment) WHERE dim_segment IS NOT NULL;

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-037: IFRS 9 ECL — expected credit loss provisions on AR aging.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS ecl_rate_matrix (
        id SERIAL PRIMARY KEY,
        bucket_label VARCHAR(50) NOT NULL,
        min_days_overdue INTEGER NOT NULL,
        max_days_overdue INTEGER,  -- NULL = open upper bound
        loss_rate DECIMAL(7, 4) NOT NULL,  -- 0.0000..1.0000
        is_active BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO ecl_rate_matrix (bucket_label, min_days_overdue, max_days_overdue, loss_rate) VALUES
        ('current',    0,    0,    0.0050),
        ('1-30',       1,    30,   0.0150),
        ('31-60',      31,   60,   0.0500),
        ('61-90',      61,   90,   0.1500),
        ('91-180',     91,   180,  0.3500),
        ('181-365',    181,  365,  0.6000),
        ('over_1y',    366,  NULL, 1.0000)
    ON CONFLICT DO NOTHING;

    CREATE TABLE IF NOT EXISTS ecl_provisions (
        id SERIAL PRIMARY KEY,
        as_of_date DATE NOT NULL,
        customer_id INTEGER,
        total_exposure DECIMAL(18, 2) NOT NULL,
        provision_amount DECIMAL(18, 2) NOT NULL,
        details JSONB,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_ecl_prov_date ON ecl_provisions (as_of_date);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-038: IAS 2 NRV — inventory write-downs to lower-of-cost-or-NRV.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS inventory_nrv_tests (
        id SERIAL PRIMARY KEY,
        as_of_date DATE NOT NULL,
        product_id INTEGER,
        warehouse_id INTEGER,
        cost_value DECIMAL(18, 4) NOT NULL,
        nrv_value DECIMAL(18, 4) NOT NULL,
        writedown_amount DECIMAL(18, 4) NOT NULL DEFAULT 0,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_nrv_date ON inventory_nrv_tests (as_of_date);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-039: IAS 36 Impairment — CGU recoverable amount testing.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS cash_generating_units (
        id SERIAL PRIMARY KEY,
        code VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(200) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS impairment_tests (
        id SERIAL PRIMARY KEY,
        cgu_id INTEGER NOT NULL REFERENCES cash_generating_units(id),
        as_of_date DATE NOT NULL,
        carrying_amount DECIMAL(18, 2) NOT NULL,
        value_in_use DECIMAL(18, 2),
        fair_value_less_costs DECIMAL(18, 2),
        recoverable_amount DECIMAL(18, 2) NOT NULL,
        impairment_loss DECIMAL(18, 2) NOT NULL DEFAULT 0,
        journal_entry_id INTEGER REFERENCES journal_entries(id),
        details JSONB,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_impairment_cgu_date ON impairment_tests (cgu_id, as_of_date);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-036: IFRS 15 / ASC 606 — performance obligations & allocation.
    -- Scaffold only; deep revenue recognition logic lives in services.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS revenue_contracts (
        id SERIAL PRIMARY KEY,
        contract_number VARCHAR(100) UNIQUE NOT NULL,
        customer_id INTEGER,
        total_transaction_price DECIMAL(18, 2) NOT NULL,
        currency VARCHAR(10) DEFAULT 'SAR',
        start_date DATE,
        end_date DATE,
        status VARCHAR(30) DEFAULT 'active',  -- active | modified | terminated | completed
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS performance_obligations (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL REFERENCES revenue_contracts(id) ON DELETE CASCADE,
        description TEXT NOT NULL,
        standalone_selling_price DECIMAL(18, 2),
        allocated_price DECIMAL(18, 2),
        recognition_method VARCHAR(30) DEFAULT 'point_in_time',  -- point_in_time | over_time
        satisfied_pct DECIMAL(7, 4) DEFAULT 0,
        revenue_recognized DECIMAL(18, 2) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_po_contract ON performance_obligations (contract_id);

    -- ═════════════════════════════════════════════════════════════════════
    -- TASK-040: E-Invoicing (Egypt ETA + UAE 2026) — submission registry.
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS e_invoice_submissions (
        id SERIAL PRIMARY KEY,
        jurisdiction VARCHAR(10) NOT NULL,  -- 'EG' | 'AE' | 'SA'
        invoice_type VARCHAR(20) NOT NULL,  -- 'sales' | 'credit_note' | ...
        invoice_id INTEGER NOT NULL,
        document_uuid VARCHAR(100),
        submission_status VARCHAR(30) DEFAULT 'pending',
            -- pending | submitted | accepted | rejected | cancelled
        submitted_at TIMESTAMPTZ,
        response_payload JSONB,
        error_message TEXT,
        retry_count INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_einv_jurisdiction_status
        ON e_invoice_submissions (jurisdiction, submission_status);
    CREATE INDEX IF NOT EXISTS idx_einv_invoice
        ON e_invoice_submissions (invoice_type, invoice_id);

    -- ═════════════════════════════════════════════════════════════════════
    -- Phase 6 — Global parity: payment gateways + ZATCA hash chain + multi-book
    -- ═════════════════════════════════════════════════════════════════════

    -- Payment gateway transactions (Stripe / Tap / PayTabs / …)
    CREATE TABLE IF NOT EXISTS gateway_charges (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(30) NOT NULL,          -- stripe | tap | paytabs | …
        charge_id VARCHAR(120) NOT NULL,        -- provider's id
        invoice_id INTEGER,                     -- optional link
        amount NUMERIC(18,2) NOT NULL,
        currency VARCHAR(10) NOT NULL,
        status VARCHAR(30) NOT NULL,            -- pending|authorised|captured|failed|refunded|cancelled
        error_message TEXT,
        gateway_response JSONB,
        idempotency_key VARCHAR(120),
        created_by INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_gateway_charge
        ON gateway_charges (provider, charge_id);
    CREATE INDEX IF NOT EXISTS idx_gateway_invoice
        ON gateway_charges (invoice_id);

    CREATE TABLE IF NOT EXISTS gateway_webhook_events (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(30) NOT NULL,
        event_type VARCHAR(80),
        charge_id VARCHAR(120),
        signature VARCHAR(512),
        verified BOOLEAN NOT NULL DEFAULT FALSE,
        payload JSONB,
        received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_webhook_provider_charge
        ON gateway_webhook_events (provider, charge_id);

    -- ZATCA hash-chain tracker (Phase 2 requirement: every invoice must
    -- carry the previous invoice's hash so the sequence is tamper-evident).
    CREATE TABLE IF NOT EXISTS zatca_invoice_hashes (
        id SERIAL PRIMARY KEY,
        invoice_id INTEGER NOT NULL,
        icv BIGINT NOT NULL,                    -- Invoice Counter Value
        invoice_hash VARCHAR(128) NOT NULL,     -- base64 SHA-256 of UBL XML
        previous_invoice_hash VARCHAR(128) NOT NULL DEFAULT '0',
        qr_payload TEXT NOT NULL,               -- base64 TLV
        submitted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_zatca_hash_invoice
        ON zatca_invoice_hashes (invoice_id);
    CREATE UNIQUE INDEX IF NOT EXISTS uq_zatca_hash_icv
        ON zatca_invoice_hashes (icv);

    -- Multi-book accounting: allow each JE to belong to a ledger/book
    -- (primary IFRS, local GAAP, tax book, management book).
    -- Nullable so existing JEs remain valid; default-populated by service.
    ALTER TABLE journal_entries
        ADD COLUMN IF NOT EXISTS ledger_id INTEGER;
    CREATE INDEX IF NOT EXISTS idx_je_ledger ON journal_entries (ledger_id);

    -- Parallel multi-book posting map: source account → per-ledger target.
    CREATE TABLE IF NOT EXISTS ledger_account_maps (
        id SERIAL PRIMARY KEY,
        ledger_id INTEGER NOT NULL,
        source_account_id INTEGER NOT NULL,
        target_account_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (ledger_id, source_account_id)
    );
    CREATE INDEX IF NOT EXISTS idx_ledger_account_maps_ledger
        ON ledger_account_maps (ledger_id);

    -- Distributed event bus: persistent outbox (used by the Redis-Streams
    -- bridge and any future Kafka/RabbitMQ relay).
    CREATE TABLE IF NOT EXISTS event_outbox (
        id BIGSERIAL PRIMARY KEY,
        event_name VARCHAR(80) NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        delivered_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_event_outbox_undelivered
        ON event_outbox (created_at)
        WHERE delivered_at IS NULL;

    -- ═════════════════════════════════════════════════════════════════════
    -- Phase 6 extensions — SMS log, shipments, bank feeds, WHT rules
    -- ═════════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS sms_log (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(30) NOT NULL,
        message_id VARCHAR(120),
        to_number VARCHAR(40) NOT NULL,
        body TEXT,
        segments INTEGER DEFAULT 1,
        status VARCHAR(30) NOT NULL,
        cost NUMERIC(10,4),
        error_message TEXT,
        gateway_response JSONB,
        created_by INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_sms_log_created ON sms_log (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_sms_log_msgid ON sms_log (message_id);

    CREATE TABLE IF NOT EXISTS shipments (
        id SERIAL PRIMARY KEY,
        carrier VARCHAR(30) NOT NULL,
        tracking_number VARCHAR(80),
        reference VARCHAR(80),
        invoice_id INTEGER,
        delivery_order_id INTEGER,
        status VARCHAR(30) NOT NULL DEFAULT 'created',
        cost NUMERIC(18,2),
        currency VARCHAR(10),
        label_url TEXT,
        awb_label BYTEA,
        carrier_response JSONB,
        created_by INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_shipment_tracking
        ON shipments (carrier, tracking_number)
        WHERE tracking_number IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_shipment_invoice ON shipments (invoice_id);

    CREATE TABLE IF NOT EXISTS bank_statements (
        id SERIAL PRIMARY KEY,
        bank_account_id INTEGER,
        account_iban VARCHAR(40),
        statement_number VARCHAR(40),
        currency VARCHAR(10),
        opening_balance NUMERIC(18,2),
        closing_balance NUMERIC(18,2),
        period_start DATE,
        period_end DATE,
        source_format VARCHAR(20),        -- mt940 | csv | openbanking
        source_filename TEXT,
        imported_by INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );

    -- AUDIT-FIX-2026-04-22: The original block-22 redefinition of
    -- bank_statement_lines (with columns statement_id/match_status/...) is a
    -- no-op because the table is already created in block 4 with a different
    -- (reconciliation-focused) schema. The duplicate CREATE TABLE was harmless
    -- but the two follow-up indexes targeted the unused schema and failed.
    -- Indexes that match the actual schema:
    CREATE INDEX IF NOT EXISTS idx_bsl_reconciliation
        ON bank_statement_lines (reconciliation_id);
    CREATE INDEX IF NOT EXISTS idx_bsl_unreconciled
        ON bank_statement_lines (is_reconciled) WHERE is_reconciled = FALSE;

    CREATE TABLE IF NOT EXISTS wht_rules (
        id SERIAL PRIMARY KEY,
        country_code VARCHAR(5) NOT NULL,
        payment_type VARCHAR(40) NOT NULL,      -- royalties | services | dividends | interest | rent
        rate NUMERIC(6,4) NOT NULL,             -- 0.0500 = 5%
        gl_account_id INTEGER,
        description TEXT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_wht_rule
        ON wht_rules (country_code, payment_type) WHERE is_active;

    -- FIN-H (TASK-018): exchange_rates is append-only FX history
    CREATE OR REPLACE FUNCTION block_exchange_rate_mutation() RETURNS trigger AS $fn5$
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'exchange_rates rows are immutable; insert a new row for a new rate_date'
                USING ERRCODE = '23514';
        END IF;
        RAISE EXCEPTION 'exchange_rates rows cannot be deleted; mark corrections via a new dated row'
            USING ERRCODE = '23514';
    END;
    $fn5$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_exchange_rates_immutable ON exchange_rates;
    CREATE TRIGGER trg_exchange_rates_immutable
        BEFORE UPDATE OR DELETE ON exchange_rates
        FOR EACH ROW EXECUTE FUNCTION block_exchange_rate_mutation();

    -- FIN-H (TASK-019): fiscal_periods non-overlap exclusion constraint
    CREATE EXTENSION IF NOT EXISTS btree_gist;
    DO $fp$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'excl_fp_nooverlap'
        ) THEN
            ALTER TABLE fiscal_periods
                ADD CONSTRAINT excl_fp_nooverlap
                EXCLUDE USING GIST (
                    daterange(start_date, end_date, '[]') WITH &&
                );
        END IF;
    END $fp$;
    """


def get_phase5_integration_tables_sql() -> str:
    """Phase 5 — Integration hardening: integration keys, retry queues, DLQ.

    Tables:
      * ``integration_keys``       — per-tenant API keys with rotation lifecycle.
      * ``payment_retry_queue``    — pending payment retries (3 attempts).
      * ``sms_retry_queue``        — pending SMS retries (3 attempts).
      * ``integration_dlq``        — terminal failures escalated for review.
      * ``integration_circuit_state`` — persisted breaker state per provider.

    Idempotent. Safe to run on every tenant bootstrap.
    """
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- T5.3: integration_keys — rotate provider credentials without downtime.
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS integration_keys (
        id SERIAL PRIMARY KEY,
        integration_type VARCHAR(40) NOT NULL,    -- payment | sms | einvoicing | bank_feeds
        provider VARCHAR(60) NOT NULL,            -- stripe | tap | taqnyat | zatca | ...
        key_name VARCHAR(80) NOT NULL,            -- api_key | secret | client_secret | ...
        encrypted_value TEXT NOT NULL,            -- AES/Fernet ciphertext
        key_status VARCHAR(20) NOT NULL DEFAULT 'active'
            CHECK (key_status IN ('active','rotated','revoked','pending')),
        valid_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        valid_to TIMESTAMPTZ,
        rotated_at TIMESTAMPTZ,
        rotated_to_id INTEGER REFERENCES integration_keys(id),
        branch_id INTEGER,
        created_by INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intkey_active
        ON integration_keys (integration_type, provider, key_name)
        WHERE key_status = 'active';
    CREATE INDEX IF NOT EXISTS idx_intkey_status
        ON integration_keys (key_status);

    -- ═══════════════════════════════════════════════════════════════════
    -- T5.3: integration_circuit_state — breaker state survives restarts.
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS integration_circuit_state (
        id SERIAL PRIMARY KEY,
        integration_type VARCHAR(40) NOT NULL,
        provider VARCHAR(60) NOT NULL,
        state VARCHAR(20) NOT NULL DEFAULT 'closed'
            CHECK (state IN ('closed','open','half_open')),
        failure_count INTEGER NOT NULL DEFAULT 0,
        last_failure_at TIMESTAMPTZ,
        opened_at TIMESTAMPTZ,
        opens_until TIMESTAMPTZ,
        last_error TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_circuit_breaker
        ON integration_circuit_state (integration_type, provider);

    -- ═══════════════════════════════════════════════════════════════════
    -- T5.4: payment_retry_queue.
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS payment_retry_queue (
        id SERIAL PRIMARY KEY,
        payment_id INTEGER,
        provider VARCHAR(60),
        amount NUMERIC(18, 4) NOT NULL,
        currency VARCHAR(10) NOT NULL,
        idempotency_key VARCHAR(120),
        request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        retry_count INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 3,
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','processing','succeeded','permanently_failed')),
        last_attempt_at TIMESTAMPTZ,
        next_retry_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_error TEXT,
        gateway_response JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_payment_retry_due
        ON payment_retry_queue (status, next_retry_at)
        WHERE status = 'pending';
    CREATE INDEX IF NOT EXISTS idx_payment_retry_payment
        ON payment_retry_queue (payment_id);

    -- ═══════════════════════════════════════════════════════════════════
    -- T5.4: sms_retry_queue.
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS sms_retry_queue (
        id SERIAL PRIMARY KEY,
        notification_id INTEGER,
        provider VARCHAR(60),
        recipient_phone VARCHAR(40) NOT NULL,
        message_text TEXT NOT NULL,
        sender_id VARCHAR(40),
        retry_count INTEGER NOT NULL DEFAULT 0,
        max_retries INTEGER NOT NULL DEFAULT 3,
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','processing','sent','permanently_failed')),
        last_attempt_at TIMESTAMPTZ,
        next_retry_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_error TEXT,
        gateway_response JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_sms_retry_due
        ON sms_retry_queue (status, next_retry_at)
        WHERE status = 'pending';

    -- ═══════════════════════════════════════════════════════════════════
    -- T5.4: integration_dlq — terminal failures parked for human review.
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS integration_dlq (
        id SERIAL PRIMARY KEY,
        queue_type VARCHAR(20) NOT NULL CHECK (queue_type IN ('payment','sms')),
        queue_item_id INTEGER NOT NULL,
        provider VARCHAR(60),
        final_status VARCHAR(40) NOT NULL DEFAULT 'permanently_failed',
        reason TEXT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        gateway_response JSONB,
        archived_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_intdlq_unresolved
        ON integration_dlq (queue_type, archived_at) WHERE archived_at IS NULL;
    """


def get_audit_security_finance_tables_sql() -> str:
    """Feature 022: Audit & Security + Finance Integrity Remediation (R1+R2).

    New tables: audit_outbox, integration_credentials, account_classifications,
    device_fingerprints, login_geo_events, employee_receipt_settlements.
    Modified tables: audit_logs (critical flag + index), recurring_journal_templates
    (review_threshold, auto_approve, expense_category_id), journal_entries /
    invoices (source normalization — handled in 022g migration).
    """
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Audit outbox (transactional buffer for audit rows)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS audit_outbox (
        id            BIGSERIAL    PRIMARY KEY,
        tenant_id     VARCHAR(100) NOT NULL,
        actor_id      BIGINT,
        action        VARCHAR(64)  NOT NULL,
        entity_type   VARCHAR(64),
        entity_id     VARCHAR(100),
        payload       JSONB        NOT NULL DEFAULT '{}',
        critical      BOOLEAN      NOT NULL DEFAULT false,
        enqueued_at   TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        flushed_at    TIMESTAMPTZ,
        attempt_count INT          NOT NULL DEFAULT 0,
        last_error    TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_audit_outbox_pending
        ON audit_outbox (tenant_id, enqueued_at)
        WHERE flushed_at IS NULL;

    ALTER TABLE audit_outbox
        ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text,
        ALTER COLUMN entity_id TYPE VARCHAR(100) USING entity_id::text;

    ALTER TABLE audit_logs
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
        ADD COLUMN IF NOT EXISTS critical BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE audit_logs
        ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;
    SELECT set_config('audit_logs.allow_admin_op', 'retention', true);
    UPDATE audit_logs
       SET tenant_id = COALESCE(NULLIF(tenant_id, ''), regexp_replace(current_database(), '^aman_', ''))
     WHERE tenant_id IS NULL OR tenant_id = '';
    CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action_created
        ON audit_logs (tenant_id, action, created_at DESC);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Integration credential vault
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS integration_credentials (
        id                   BIGSERIAL    PRIMARY KEY,
        tenant_id            BIGINT       NOT NULL,
        integration          VARCHAR(32)  NOT NULL,
        name                 VARCHAR(128) NOT NULL,
        secret_ciphertext    BYTEA        NOT NULL,
        key_version          INT          NOT NULL DEFAULT 1,
        metadata             JSONB        NOT NULL DEFAULT '{}',
        status               VARCHAR(16)  NOT NULL DEFAULT 'active',
        consecutive_failures INT          NOT NULL DEFAULT 0,
        rotated_at           TIMESTAMPTZ,
        expires_at           TIMESTAMPTZ,
        created_by           BIGINT,
        created_at           TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        deleted_at           TIMESTAMPTZ
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_credentials_active
        ON integration_credentials (tenant_id, integration, name)
        WHERE status != 'soft_deleted';

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Account classifications (replaces hard-coded ranges)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS account_classifications (
        id                 BIGSERIAL    PRIMARY KEY,
        tenant_id          BIGINT       NOT NULL,
        account_id         BIGINT       NOT NULL REFERENCES accounts(id),
        statement_category VARCHAR(32)  NOT NULL,
        sign               SMALLINT     NOT NULL,
        aggregation_hint   VARCHAR(64),
        is_active          BOOLEAN      NOT NULL DEFAULT true,
        valid_from         DATE         NOT NULL DEFAULT CURRENT_DATE,
        valid_to           DATE,
        created_at         TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        updated_at         TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_account_classifications_active
        ON account_classifications (tenant_id, account_id)
        WHERE is_active = true;

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Device fingerprints + login geo events (seam)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS device_fingerprints (
        id               BIGSERIAL    PRIMARY KEY,
        tenant_id        BIGINT       NOT NULL,
        user_id          BIGINT       NOT NULL,
        fingerprint_hash VARCHAR(64)  NOT NULL,
        first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        last_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        trust_level      VARCHAR(16)  NOT NULL DEFAULT 'unknown'
    );
    CREATE INDEX IF NOT EXISTS ix_device_fingerprints_lookup
        ON device_fingerprints (tenant_id, user_id, fingerprint_hash);

    CREATE TABLE IF NOT EXISTS login_geo_events (
        id              BIGSERIAL    PRIMARY KEY,
        tenant_id       BIGINT       NOT NULL,
        user_id         BIGINT       NOT NULL,
        occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
        country_code    CHAR(2),
        region_code     VARCHAR(8),
        risk_decision   VARCHAR(16)  NOT NULL DEFAULT 'ok',
        decision_reason VARCHAR(64)
    );
    CREATE INDEX IF NOT EXISTS ix_login_geo_events_user
        ON login_geo_events (tenant_id, user_id, occurred_at DESC);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Employee receipt settlements
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS employee_receipt_settlements (
        id          BIGSERIAL       PRIMARY KEY,
        tenant_id   BIGINT          NOT NULL,
        employee_id BIGINT          NOT NULL,
        advance_id  BIGINT          NOT NULL,
        receipt_id  BIGINT          NOT NULL,
        amount      NUMERIC(18,4)   NOT NULL,
        status      VARCHAR(16)     NOT NULL DEFAULT 'draft',
        approved_by BIGINT,
        je_id       BIGINT,
        created_at  TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at  TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX IF NOT EXISTS ix_employee_receipt_settlements_emp
        ON employee_receipt_settlements (tenant_id, employee_id, status);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: recurring_journal_templates extensions
    -- ═══════════════════════════════════════════════════════════════════
    ALTER TABLE recurring_journal_templates
        ADD COLUMN IF NOT EXISTS review_threshold  NUMERIC(18,4),
        ADD COLUMN IF NOT EXISTS auto_approve       BOOLEAN NOT NULL DEFAULT false,
        ADD COLUMN IF NOT EXISTS expense_category_id BIGINT;

    CREATE TABLE IF NOT EXISTS recurring_je_pending_review (
        id                  BIGSERIAL     PRIMARY KEY,
        tenant_id           BIGINT        NOT NULL,
        template_id         BIGINT        NOT NULL REFERENCES recurring_journal_templates(id) ON DELETE CASCADE,
        run_date            DATE          NOT NULL,
        amount              NUMERIC(18,4) NOT NULL,
        expense_category_id BIGINT,
        lines               JSONB         NOT NULL DEFAULT '[]',
        status              VARCHAR(16)   NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','rejected','posted')),
        journal_entry_id    BIGINT,
        approved_by         BIGINT,
        approved_at         TIMESTAMPTZ,
        rejected_by         BIGINT,
        rejected_at         TIMESTAMPTZ,
        rejection_reason    TEXT,
        created_at          TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX IF NOT EXISTS ix_recurring_review_tenant_status
        ON recurring_je_pending_review (tenant_id, status);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 022: Default settings keys (idempotent on re-run)
    -- ═══════════════════════════════════════════════════════════════════
    INSERT INTO company_settings (setting_key, setting_value)
    VALUES
        ('audit.outbox.flush_sla_seconds', '60'),
        ('audit.outbox.batch_size', '200'),
        ('webhook.ratelimit.window_seconds', '60'),
        ('webhook.ratelimit.max_requests', '120'),
        ('bank_feed.failure_alert_threshold', '3'),
        ('reconciliation.drift_tolerance', '0.01'),
        ('gl.je_epsilon', '0.005'),
        ('fiscal.allow_drafts_in_closed_period', 'false'),
        ('expenses.auto_approve_threshold', '0'),
        ('expenses.cost_center_policy', 'warn'),
        ('recurring.review_threshold_default', '0')
    ON CONFLICT (setting_key) DO NOTHING;

    INSERT INTO company_settings (setting_key, setting_value)
    VALUES ('tax.zakat.gregorian_rate', '2.57764')
    ON CONFLICT (setting_key) DO NOTHING;
    """


def get_feature023_tables_sql() -> str:
    """Feature 023: Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing tables.

    New tables: zatca_outbox, returns_unified, returns_unified_lines,
    opportunity_stage_history, pos_offline_batches, item_warehouse_settings,
    mrp_recommendations, bom_snapshots, production_completions, scrap_movements,
    inventory_transactions_archive.

    Extensions: invoices (state, idempotency), sales_orders (invoice link),
    manufacturing_orders (bom_snapshot, remaining_qty, qc, approval),
    workstations (overhead_rate), acc_map_sales (direction).
    """
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Invoice state + idempotency
    -- ═══════════════════════════════════════════════════════════════════
    ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS state VARCHAR(32) NOT NULL DEFAULT 'draft';
    ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);
    ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
    ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS posted_by BIGINT;
    ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS state_reason TEXT;

    DO $$ BEGIN
        ALTER TABLE invoices ADD CONSTRAINT chk_invoice_state
            CHECK (state IN ('draft','posted','submitted','cleared','reported','reversed','cancelled'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE UNIQUE INDEX IF NOT EXISTS uix_invoice_idempotency
        ON invoices (tenant_id, sales_order_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL;
    CREATE INDEX IF NOT EXISTS ix_invoices_state
        ON invoices (tenant_id, state);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Sales order → invoice link
    -- ═══════════════════════════════════════════════════════════════════
    ALTER TABLE sales_orders
        ADD COLUMN IF NOT EXISTS converted_to_invoice_id BIGINT;
    ALTER TABLE sales_orders
        ADD COLUMN IF NOT EXISTS responsible_user_id BIGINT;

    CREATE UNIQUE INDEX IF NOT EXISTS uix_so_converted_invoice
        ON sales_orders (tenant_id, converted_to_invoice_id)
        WHERE converted_to_invoice_id IS NOT NULL;

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Returns unified
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS returns_unified (
        id                  BIGSERIAL       PRIMARY KEY,
        tenant_id           BIGINT          NOT NULL,
        source              VARCHAR(16)     NOT NULL,
        original_invoice_id BIGINT,
        original_pos_sale_id BIGINT,
        state               VARCHAR(20)     NOT NULL DEFAULT 'draft',
        restock_warehouse_id BIGINT,
        je_id               BIGINT,
        total_amount        NUMERIC(18,4)   NOT NULL DEFAULT 0,
        reason              TEXT,
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        created_by          BIGINT,
        updated_by          BIGINT,
        deleted_at          TIMESTAMPTZ
    );

    CREATE TABLE IF NOT EXISTS returns_unified_lines (
        id          BIGSERIAL       PRIMARY KEY,
        tenant_id   BIGINT          NOT NULL,
        return_id   BIGINT          NOT NULL,
        line_no     INT             NOT NULL,
        item_id     BIGINT          NOT NULL,
        qty         NUMERIC(18,4)   NOT NULL,
        unit_price  NUMERIC(18,4)   NOT NULL,
        tax_id      BIGINT,
        tax_rate    NUMERIC(8,4),
        tax_rate_id INTEGER         REFERENCES tax_rates(id),
        created_at  TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX IF NOT EXISTS idx_returns_unified_lines_tax_rate ON returns_unified_lines(tax_rate_id);

    CREATE INDEX IF NOT EXISTS ix_returns_unified_tenant
        ON returns_unified (tenant_id, state);
    CREATE INDEX IF NOT EXISTS ix_returns_unified_lines_return
        ON returns_unified_lines (tenant_id, return_id);
    CREATE UNIQUE INDEX IF NOT EXISTS uix_return_draft_invoice
        ON returns_unified (tenant_id, original_invoice_id)
        WHERE state = 'draft' AND original_invoice_id IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS uix_return_draft_pos
        ON returns_unified (tenant_id, original_pos_sale_id)
        WHERE state = 'draft' AND original_pos_sale_id IS NOT NULL;

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: acc_map_sales direction consolidation
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS acc_map_sales (
        id           BIGSERIAL      PRIMARY KEY,
        tenant_id    BIGINT,
        mapping_key  VARCHAR(64)    NOT NULL,
        account_code VARCHAR(64)    NOT NULL,
        direction    VARCHAR(16)    NOT NULL DEFAULT 'forward',
        created_at   TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
        updated_at   TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_map_sales_key_direction
        ON acc_map_sales (tenant_id, mapping_key, direction);

    ALTER TABLE acc_map_sales
        ADD COLUMN IF NOT EXISTS direction VARCHAR(16) NOT NULL DEFAULT 'forward';

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: ZATCA outbox
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS zatca_outbox (
        id                  BIGSERIAL       PRIMARY KEY,
        tenant_id           BIGINT          NOT NULL,
        invoice_id          BIGINT          NOT NULL,
        state               VARCHAR(20)     NOT NULL DEFAULT 'pending',
        attempts            INT             NOT NULL DEFAULT 0,
        next_attempt_at     TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        last_error          TEXT,
        idempotency_key     VARCHAR(64),
        signed_xml          TEXT,
        cleared_reference   VARCHAR(64),
        reported_reference  VARCHAR(64),
        submitted_at        TIMESTAMPTZ,
        acknowledged_at     TIMESTAMPTZ,
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE zatca_outbox ADD CONSTRAINT chk_zatca_outbox_state
            CHECK (state IN ('pending','submitting','submitted','cleared','reported','failed','dead_letter'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE UNIQUE INDEX IF NOT EXISTS uix_zatca_outbox_invoice
        ON zatca_outbox (tenant_id, invoice_id);
    CREATE INDEX IF NOT EXISTS ix_zatca_outbox_worker
        ON zatca_outbox (tenant_id, state, next_attempt_at)
        WHERE state IN ('pending', 'failed');

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Opportunity stage history
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS opportunity_stage_history (
        id              BIGSERIAL       PRIMARY KEY,
        tenant_id       BIGINT          NOT NULL,
        opportunity_id  BIGINT          NOT NULL,
        from_stage      VARCHAR(32),
        to_stage        VARCHAR(32)     NOT NULL,
        entered_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        actor_id        BIGINT,
        reason          TEXT,
        created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    CREATE INDEX IF NOT EXISTS ix_opp_stage_history_lookup
        ON opportunity_stage_history (tenant_id, opportunity_id, entered_at);
    CREATE INDEX IF NOT EXISTS ix_opp_stage_history_funnel
        ON opportunity_stage_history (tenant_id, to_stage, entered_at);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: POS offline batches
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS pos_offline_batches (
        id                  BIGSERIAL       PRIMARY KEY,
        tenant_id           BIGINT          NOT NULL,
        device_id           VARCHAR(64)     NOT NULL,
        client_uuid         UUID            NOT NULL,
        state               VARCHAR(20)     NOT NULL DEFAULT 'queued',
        payload             JSONB           NOT NULL DEFAULT '{}',
        pos_sale_id         BIGINT,
        failure_reason_code VARCHAR(32),
        failure_detail      TEXT,
        queued_at           TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        processed_at        TIMESTAMPTZ,
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE pos_offline_batches ADD CONSTRAINT chk_pos_offline_state
            CHECK (state IN ('queued','reconciling','committed','manual_review','failed'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE UNIQUE INDEX IF NOT EXISTS uix_pos_offline_device_uuid
        ON pos_offline_batches (tenant_id, device_id, client_uuid);
    CREATE INDEX IF NOT EXISTS ix_pos_offline_queued
        ON pos_offline_batches (tenant_id, state, queued_at)
        WHERE state = 'queued';

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Item warehouse settings
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS item_warehouse_settings (
        tenant_id           BIGINT          NOT NULL,
        item_id             BIGINT          NOT NULL,
        warehouse_id        BIGINT          NOT NULL,
        reorder_point       NUMERIC(18,4),
        reorder_quantity    NUMERIC(18,4),
        safety_stock        NUMERIC(18,4),
        lead_time_days      INT,
        preferred_supplier_id BIGINT,
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (tenant_id, item_id, warehouse_id)
    );

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: MRP recommendations
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS mrp_recommendations (
        id              BIGSERIAL       PRIMARY KEY,
        tenant_id       BIGINT          NOT NULL,
        run_id          UUID            NOT NULL,
        item_id         BIGINT          NOT NULL,
        warehouse_id    BIGINT          NOT NULL,
        recommended_qty NUMERIC(18,4),
        due_date        DATE,
        supplier_id     BIGINT,
        state           VARCHAR(20)     NOT NULL DEFAULT 'open',
        po_id           BIGINT,
        reason          TEXT,
        created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        updated_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE mrp_recommendations ADD CONSTRAINT chk_mrp_rec_state
            CHECK (state IN ('open','accepted','dismissed','converted_to_po'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE INDEX IF NOT EXISTS ix_mrp_recommendations_state
        ON mrp_recommendations (tenant_id, state, run_id);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: BOM snapshots + MO extensions
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS bom_snapshots (
        id              BIGSERIAL       PRIMARY KEY,
        tenant_id       BIGINT          NOT NULL,
        mo_id           BIGINT          NOT NULL UNIQUE,
        bom_id          BIGINT          NOT NULL,
        bom_version     INT             NOT NULL,
        payload         JSONB           NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS bom_snapshot_id BIGINT;
    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS remaining_qty NUMERIC(18,4);
    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS qc_required BOOLEAN DEFAULT FALSE;
    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS requires_approval BOOLEAN DEFAULT FALSE;
    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS approved_by BIGINT;
    ALTER TABLE manufacturing_orders
        ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

    DO $$ BEGIN
        ALTER TABLE manufacturing_orders
            ADD CONSTRAINT fk_mo_bom_snapshot
            FOREIGN KEY (bom_snapshot_id) REFERENCES bom_snapshots(id);
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Production completions + scrap
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS production_completions (
        id                      BIGSERIAL       PRIMARY KEY,
        tenant_id               BIGINT          NOT NULL,
        mo_id                   BIGINT          NOT NULL,
        qty                     NUMERIC(18,4)   NOT NULL,
        actual_material_cost    NUMERIC(18,4),
        actual_labor_cost       NUMERIC(18,4),
        actual_overhead_cost    NUMERIC(18,4),
        byproduct_allocation_method VARCHAR(20),
        wip_to_fg_je_id         BIGINT          NOT NULL,
        qc_state                VARCHAR(20),
        completed_at            TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        created_at              TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE production_completions ADD CONSTRAINT chk_pc_qc_state
            CHECK (qc_state IN ('pending','passed','failed','n/a'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE INDEX IF NOT EXISTS ix_prod_completions_mo
        ON production_completions (tenant_id, mo_id, completed_at);

    CREATE TABLE IF NOT EXISTS scrap_movements (
        id                  BIGSERIAL       PRIMARY KEY,
        tenant_id           BIGINT          NOT NULL,
        item_id             BIGINT          NOT NULL,
        warehouse_id        BIGINT          NOT NULL,
        qty                 NUMERIC(18,4)   NOT NULL,
        unit_cost_at_scrap  NUMERIC(18,4)   NOT NULL,
        reason              VARCHAR(64)     NOT NULL,
        mo_id               BIGINT,
        je_id               BIGINT          NOT NULL,
        occurred_at         TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
        created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
    );

    DO $$ BEGIN
        ALTER TABLE scrap_movements ADD CONSTRAINT chk_scrap_reason
            CHECK (reason IN ('mo_loss','qc_fail','expiry','damage','other'));
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;

    CREATE INDEX IF NOT EXISTS ix_scrap_movements_item
        ON scrap_movements (tenant_id, item_id, occurred_at);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Workstation overhead
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS workstations (
        id             BIGSERIAL      PRIMARY KEY,
        tenant_id      BIGINT,
        name           VARCHAR(255),
        code           VARCHAR(64),
        overhead_rate  NUMERIC(18,4),
        effective_from DATE,
        effective_to   DATE,
        created_at     TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
        updated_at     TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp()
    );

    ALTER TABLE workstations
        ADD COLUMN IF NOT EXISTS overhead_rate NUMERIC(18,4);
    ALTER TABLE workstations
        ADD COLUMN IF NOT EXISTS effective_from DATE;
    ALTER TABLE workstations
        ADD COLUMN IF NOT EXISTS effective_to DATE;

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Inventory transactions archive
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS inventory_transactions_archive (
        LIKE inventory_transactions INCLUDING DEFAULTS INCLUDING CONSTRAINTS
    );

    CREATE INDEX IF NOT EXISTS ix_inv_txn_archive_product_wh_created
        ON inventory_transactions_archive (product_id, warehouse_id, created_at);
    CREATE INDEX IF NOT EXISTS ix_inv_txn_archive_created
        ON inventory_transactions_archive (created_at);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 023: Settings keys
    -- ═══════════════════════════════════════════════════════════════════
    INSERT INTO company_settings (setting_key, setting_value)
    VALUES
        ('pos.lock_ttl_seconds', '5'),
        ('pos.offline_batch_max_age_hours', '72'),
        ('zatca.outbox_max_attempts', '8'),
        ('zatca.outbox_backoff_base_seconds', '30'),
        ('zatca.outbox_backoff_cap_seconds', '1800'),
        ('zatca.profile', 'standard'),
        ('inventory.retention_days', '365'),
        ('inventory.low_stock_debounce_hours', '36'),
        ('inventory.auto_reorder_enabled', 'false'),
        ('inventory.allow_negative_balance', 'block'),
        ('manufacturing.large_mo_threshold', '100000.0000'),
        ('manufacturing.yield_tolerance', '0.05'),
        ('manufacturing.missing_mapping_policy', 'warn'),
        ('manufacturing.global_overhead_rate', '0.0000'),
        ('manufacturing.qc_required_default', 'false'),
        ('crm.velocity_window_days', '90'),
        ('crm.funnel_window_days', '90'),
        ('crm.cashflow_horizon_days', '180'),
        ('mrp.horizon_days', '60')
    ON CONFLICT (setting_key) DO NOTHING;
    """


def get_feature024_tables_sql() -> str:
    """Feature 024: Workforce/Service/Comms integrity settings seed.

    Table DDL is handled by Alembic migrations (024a–024r). This function
    seeds the 17 new company_settings keys required by Feature 024 and
    creates the scheduled_job_runs table for scheduler idempotency.
    """
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 024: scheduled_job_runs (scheduler idempotency)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS scheduled_job_runs (
        id              SERIAL PRIMARY KEY,
        tenant_id       INTEGER,
        job_id          VARCHAR(255) NOT NULL,
        scheduled_for   TIMESTAMP WITH TIME ZONE NOT NULL,
        attempt         INTEGER NOT NULL DEFAULT 1,
        status          VARCHAR(50) NOT NULL DEFAULT 'running',
        started_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        finished_at     TIMESTAMP WITH TIME ZONE,
        error           TEXT,
        UNIQUE (job_id, scheduled_for, attempt)
    );
    CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_status
        ON scheduled_job_runs (status, scheduled_for);

    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 024: Settings keys
    -- ═══════════════════════════════════════════════════════════════════
    INSERT INTO company_settings (setting_key, setting_value)
    VALUES
        ('hr.salary_encryption_enabled', 'true'),
        ('hr.service_years_policy', 'months_precise'),
        ('company_timezone', 'Asia/Riyadh'),
        ('payroll.allow_backdated_increment', 'false'),
        ('fsm.auto_assign_threshold', '0.75'),
        ('fsm.zero_revenue_approval_required', 'true'),
        ('dms.tenant_quota_mb', '51200'),
        ('dms.user_quota_mb', '2048'),
        ('dms.orphan_retention_days', '30'),
        ('dms.storage_root', '/var/aman/dms'),
        ('dms.scan_max_pending_minutes', '30'),
        ('dms.scan_engine', 'clamav'),
        ('dms.allowed_mime_groups', '["image/*","application/pdf","application/zip","application/vnd.openxmlformats-officedocument*","text/plain","text/csv"]'),
        ('notifications.max_attempts', '5'),
        ('notifications.dedupe_window_seconds', '300'),
        ('notifications.default_locale', 'en'),
        ('auth.approval_token_ttl_minutes', '1440')
    ON CONFLICT (setting_key) DO NOTHING;
    """


def get_feature025_settings_seed_sql() -> str:
    """Feature 025: Reports/Cache/KPI/Scheduler/Backup/Search settings seed.

    Seeds the company_settings keys required by Feature 025 per data-model.md §F.
    """
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- Feature 025: Settings keys (R7 + R8)
    -- ═══════════════════════════════════════════════════════════════════
    INSERT INTO company_settings (setting_key, setting_value)
    VALUES
        ('cache.backend', 'redis'),
        ('cache.circuit_breaker.failures', '5'),
        ('cache.circuit_breaker.cool_down_seconds', '30'),
        ('reports.mv.refresh_interval_minutes', '15'),
        ('reports.warmup_keys', '["coa:summary","kpi:operating_margin","dashboard:home"]'),
        ('reports.kpi.evaluation_interval_minutes', '15'),
        ('reports.income_statement.include_headers', 'true'),
        ('reports.trial_balance.tolerance', '0.01'),
        ('audit.retention_months', '36'),
        ('search.autocomplete_debounce_ms', '300'),
        ('search.query_logs_retention_days', '90'),
        ('fx.cache_ttl_minutes', '30'),
        ('fx.stale_tolerance_minutes', '120'),
        ('backup.local_time', '02:00'),
        ('backup.retention_days', '30'),
        ('backup.min_retained', '3'),
        ('backup.max_consecutive_failures', '3'),
        ('backup.offsite_provider', 's3')
    ON CONFLICT (setting_key) DO NOTHING;
    """
