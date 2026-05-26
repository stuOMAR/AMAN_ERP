"""
AMAN ERP — Alembic environment configuration.

Supports multi-tenant: runs migrations on ALL company databases
when --x company=all is passed, or on a single company with --x company=<id>.

Usage:
    alembic upgrade head                          # system DB only
    alembic -x company=all upgrade head           # all company DBs
    alembic -x company=be67ce39 upgrade head      # specific company DB
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, text
from alembic import context
import sys
import os

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from models import MODELED_TABLES, target_metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from settings.
# Alembic uses ConfigParser interpolation, so literal '%' in passwords must be escaped.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

def _get_company_arg():
    return context.get_x_argument(as_dictionary=True).get("company", None)


def _is_autogenerate_mode() -> bool:
    cmd_opts = getattr(config, "cmd_opts", None)
    return bool(cmd_opts and getattr(cmd_opts, "autogenerate", False))


def _include_object(object_, name, type_, reflected, compare_to):
    """Limit autogenerate to modeled tables and additive changes only."""
    if type_ == "table":
        return name in MODELED_TABLES

    table_name = None
    if hasattr(object_, "table") and getattr(object_.table, "name", None):
        table_name = object_.table.name
    elif compare_to is not None and hasattr(compare_to, "table") and getattr(compare_to.table, "name", None):
        table_name = compare_to.table.name

    if table_name and table_name not in MODELED_TABLES:
        return False

    # During phased modeling, ignore destructive diffs for unmodeled columns.
    if type_ == "column" and reflected and compare_to is None:
        return False

    # Constraints/indexes will be modeled in later phases.
    if type_ in {
        "index",
        "unique_constraint",
        "foreign_key_constraint",
        "check_constraint",
        "primary_key_constraint",
    }:
        return False

    return True


def _get_company_urls():
    """Get list of company database URLs to migrate."""
    company_arg = _get_company_arg()

    if not company_arg:
        return []  # Only system DB

    from sqlalchemy import create_engine
    eng = create_engine(settings.DATABASE_URL)

    if company_arg == "all":
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT id FROM system_companies WHERE status = 'active'")).fetchall()
        eng.dispose()
        return [settings.get_company_database_url(r[0]) for r in rows]
    else:
        eng.dispose()
        return [settings.get_company_database_url(company_arg)]


def _get_single_company_url_for_autogen() -> str:
    company_arg = _get_company_arg()
    if not company_arg:
        raise RuntimeError(
            "Autogenerate requires company target. Use: alembic -x company=<company_id> revision --autogenerate -m 'msg'"
        )
    if company_arg == "all":
        raise RuntimeError("Autogenerate does not support company=all. Provide one company_id.")
    return settings.get_company_database_url(company_arg)


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    if _is_autogenerate_mode():
        # Autogenerate compares metadata against one tenant DB only.
        from sqlalchemy import create_engine

        autogen_url = _get_single_company_url_for_autogen()
        eng = create_engine(autogen_url, poolclass=pool.NullPool)
        try:
            with eng.connect() as connection:
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    include_object=_include_object,
                    compare_type=True,
                    compare_server_default=False,
                )
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            eng.dispose()
        return

    company_arg = _get_company_arg()

    # 1. Run on system DB only when no tenant target was requested.
    # For `-x company=...`, many migrations are tenant-only and can fail on system DB.
    if not company_arg:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()

    # 2. Run on company DBs (if requested)
    tenant_failures = []
    companies = []
    company_arg = _get_company_arg()
    if company_arg:
        if company_arg == "all":
            from sqlalchemy import create_engine
            sys_eng = create_engine(settings.DATABASE_URL)
            with sys_eng.connect() as conn:
                rows = conn.execute(text("SELECT id FROM system_companies WHERE status = 'active'")).fetchall()
            sys_eng.dispose()
            companies = [(r[0], settings.get_company_database_url(r[0])) for r in rows]
        else:
            companies = [(company_arg, settings.get_company_database_url(company_arg))]

    for company_id, url in companies:
        from sqlalchemy import create_engine
        eng = create_engine(url, poolclass=pool.NullPool)
        try:
            with eng.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    # Set the app.tenant_id session variable so triggers and migrations can read it
                    try:
                        tenant_int = int(company_id, 16)
                        connection.execute(text(f"SELECT set_config('app.tenant_id', '{tenant_int}', false)"))
                        connection.execute(text(f"SET LOCAL app.tenant_id = '{tenant_int}'"))
                    except ValueError:
                        connection.execute(text(f"SELECT set_config('app.tenant_id', '{company_id}', false)"))
                        connection.execute(text(f"SET LOCAL app.tenant_id = '{company_id}'"))
                    context.run_migrations()
        except Exception as e:
            tenant_failures.append((url, str(e)))
        finally:
            eng.dispose()

    if tenant_failures:
        details = " | ".join([f"{url}: {err}" for url, err in tenant_failures])
        raise RuntimeError(f"Tenant migrations failed: {details}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
