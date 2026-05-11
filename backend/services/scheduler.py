import logging
import os
from contextlib import contextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from sqlalchemy import text
from datetime import datetime, timedelta, date
from typing import Any, Generator, Optional

from database import engine as system_engine, _get_engine
from utils.email import send_email
from utils.exports import generate_pdf, generate_excel
from routers.reports import _get_profit_loss_data, _get_balance_sheet_data
from utils.i18n import i18n_message

logger = logging.getLogger(__name__)

# ── T4.1: Production-grade scheduler ─────────────────────────────────────────
# Use SQLAlchemyJobStore so jobs survive server restarts.
# Falls back to MemoryJobStore when SCHEDULER_DB_URL is not configured
# (e.g. unit-test environments).
_SCHEDULER_TZ = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Riyadh")
_SCHEDULER_DB_URL = os.environ.get("SCHEDULER_DB_URL", os.environ.get("DATABASE_URL", ""))

def _build_jobstores():
    if _SCHEDULER_DB_URL:
        try:
            return {"default": SQLAlchemyJobStore(url=_SCHEDULER_DB_URL, tablename="apscheduler_jobs")}
        except Exception as exc:
            logger.warning("SQLAlchemyJobStore init failed (%s) — falling back to MemoryJobStore", exc)
    return {}   # APScheduler default = MemoryJobStore

_job_execution_log: dict[str, dict] = {}   # job_id → {last_run, status, error}

def _wrap_job(fn, job_id: str):
    """Wrap a scheduler job to track last execution and capture Sentry errors."""
    def _inner(*args, **kwargs):
        _job_execution_log[job_id] = {"last_run": datetime.utcnow().isoformat(), "status": "running", "error": None}
        try:
            fn(*args, **kwargs)
            _job_execution_log[job_id]["status"] = "ok"
        except Exception as exc:
            _job_execution_log[job_id]["status"] = "error"
            _job_execution_log[job_id]["error"] = str(exc)
            logger.exception("Scheduler job '%s' failed", job_id)
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(exc)
            except ImportError:
                pass
            raise
    _inner.__name__ = fn.__name__
    return _inner

scheduler = BackgroundScheduler(
    jobstores=_build_jobstores(),
    executors={"default": ThreadPoolExecutor(max_workers=4)},
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120},
    timezone=_SCHEDULER_TZ,
)


class IdempotentSkip(Exception):
    """Raised when a scheduled job run is absorbed as a duplicate."""


def get_scheduler_instance() -> BackgroundScheduler:
    """Return the process-local APScheduler instance."""
    return scheduler


def get_scheduler_jobs() -> list[dict[str, Any]]:
    """List registered scheduler jobs for the operations UI."""
    jobs = []
    for job in scheduler.get_jobs():
        execution = _job_execution_log.get(job.id, {})
        status = execution.get("status")
        if status != "running":
            status = "scheduled" if job.next_run_time else "paused"

        jobs.append({
            "job_id": job.id,
            "name": job.name or job.id,
            "status": status,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "last_run": execution.get("last_run"),
            "last_error": execution.get("error"),
        })
    return jobs


async def trigger_job(job_id: str) -> bool:
    """Schedule an existing job to run as soon as the scheduler wakes up."""
    job = scheduler.get_job(job_id)
    if not job:
        return False

    try:
        scheduler.modify_job(job_id, next_run_time=datetime.now(scheduler.timezone))
        scheduler.wakeup()
        return True
    except Exception as exc:
        logger.error("Failed to trigger scheduler job %s: %s", job_id, exc)
        return False


@contextmanager
def idempotent_run(
    job_id: str,
    scheduled_for: datetime,
    attempt: int = 1,
    tenant_id: str | None = None,
) -> Generator[None, None, None]:
    """Guard scheduled work against duplicate execution."""
    from database import get_tenant_db

    run_id = None
    try:
        with get_tenant_db(tenant_id) as db:
            result = db.execute(
                text("""
                    INSERT INTO scheduled_job_runs
                        (job_id, scheduled_for, attempt, status, started_at, tenant_id)
                    VALUES
                        (:job_id, :scheduled_for, :attempt, 'running', NOW(), :tenant_id)
                    ON CONFLICT (job_id, scheduled_for, attempt) DO NOTHING
                    RETURNING id
                """),
                {
                    "job_id": job_id,
                    "scheduled_for": scheduled_for,
                    "attempt": attempt,
                    "tenant_id": tenant_id,
                },
            )
            row = result.fetchone()
            if row is None:
                logger.info(
                    "Idempotent skip: job=%s scheduled_for=%s attempt=%d",
                    job_id, scheduled_for, attempt,
                )
                raise IdempotentSkip(
                    f"Job {job_id} already run for {scheduled_for} attempt {attempt}"
                )
            run_id = row[0]
            db.commit()

        yield

        with get_tenant_db(tenant_id) as db:
            db.execute(
                text("""
                    UPDATE scheduled_job_runs
                    SET status = 'succeeded', finished_at = NOW()
                    WHERE id = :id
                """),
                {"id": run_id},
            )
            db.commit()
    except IdempotentSkip:
        raise
    except Exception as exc:
        if run_id is not None:
            try:
                with get_tenant_db(tenant_id) as db:
                    db.execute(
                        text("""
                            UPDATE scheduled_job_runs
                            SET status = 'failed', finished_at = NOW(), error = :error
                            WHERE id = :id
                        """),
                        {"id": run_id, "error": str(exc)[:2000]},
                    )
                    db.commit()
            except Exception:
                logger.exception("Failed to update scheduled_job_runs status")
        raise


def _get_company_engine_for_db(db_name: str):
    """Get a cached engine for a company DB by database name."""
    # Extract company_id from db_name (format: aman_{company_id})
    company_id = db_name.replace("aman_", "", 1)
    if company_id == "system":
        return system_engine
    return _get_engine(company_id)

def flatten_report_data(data_nodes):
    """Flatten hierarchical data for export"""
    flat_data = []
    
    def _flatten(nodes, indent=0):
        for node in nodes:
            flat_data.append({
                "Account Number": node.get("account_number", ""),
                "Account Name": f"{'  ' * indent}{node.get('name', '')}",
                "Balance": f"{float(node.get('balance', 0)):,.2f}",
                "Type": node.get("account_type", "")
            })
            if node.get("children"):
                _flatten(node["children"], indent + 1)
                
    _flatten(data_nodes)
    return flat_data

def process_scheduled_report(conn, report):
    try:
        report_id = report.id
        report_type = report.report_type
        branch_id = report.branch_id
        recipients = report.recipients.split(',')
        fmt = report.format or 'pdf'
        
        logger.info(f"⚙️ Processing report {report_id} ({report_type}) for branch {branch_id}")
        
        # Generate Data
        today = date.today()
        # Determined date range based on report type/frequency?
        # For now, default to 'This Month' or 'YTD'. Let's assume YTD for now or simple Month.
        # Ideally, scheduled report should have params for date range (e.g. 'last_month', 'ytd').
        # Using YTD for simplicity: Jan 1 to Today.
        start_date = today.replace(day=1, month=1)
        end_date = today
        
        filename = f"{report_type}_{today}.{fmt}"
        file_data = None
        
        if report_type == 'profit_loss':
            data = _get_profit_loss_data(conn, start_date, end_date, branch_id)
            flat = flatten_report_data(data["data"])
            # Add Total
            flat.append({
                "Account Number": "",
                "Account Name": "Net Income / صافي الدخل",
                "Balance": f"{float(data.get('total', 0)):,.2f}",
                "Type": ""
            })
            
            if fmt == 'excel':
                file_data = generate_excel(flat, ["Account Number", "Account Name", "Balance"]).read()
            else:
                pdf_rows = [["Account #", "Account Name", "Balance"]]
                for r in flat:
                    pdf_rows.append([r["Account Number"], r["Account Name"], r["Balance"]])
                file_data = generate_pdf(pdf_rows, f"Profit & Loss ({start_date} - {end_date})").read()

        elif report_type == 'balance_sheet':
            data = _get_balance_sheet_data(conn, end_date, branch_id)
            flat = flatten_report_data(data["data"])
            
            if fmt == 'excel':
                file_data = generate_excel(flat, ["Account Number", "Account Name", "Balance"]).read()
            else:
                pdf_rows = [["Account #", "Account Name", "Balance"]]
                for r in flat:
                    pdf_rows.append([r["Account Number"], r["Account Name"], r["Balance"]])
                file_data = generate_pdf(pdf_rows, f"Balance Sheet (As of {end_date})").read()
        
        if file_data:
            subject = f"Scheduled Report: {report_type.replace('_', ' ').title()}"
            body = f"Please find attached the {report_type} report for {today}."
            
            attachments = [{
                "filename": filename,
                "data": file_data,
                "content_type": "application/pdf" if fmt == 'pdf' else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }]
            
            sent = send_email(recipients, subject, body, attachments)
            
            if sent:
                # Update next_run
                next_run = datetime.now()
                if report.frequency == 'daily':
                    next_run += timedelta(days=1)
                elif report.frequency == 'weekly':
                    next_run += timedelta(weeks=1)
                elif report.frequency == 'monthly':
                    next_run += timedelta(days=30) # approx
                else:
                    next_run += timedelta(days=1)
                
                conn.execute(text("UPDATE scheduled_reports SET last_run_at = NOW(), next_run_at = :next WHERE id = :id"), {"next": next_run, "id": report_id})
                conn.commit()
                logger.info(f"✅ Report {report_id} processed and updated.")
            else:
                logger.warning(f"⚠️ Report {report_id} generated but email failed.")
        
    except Exception as e:
        logger.error(f"❌ Error processing report {report.id}: {e}")

def check_scheduled_reports():
    """Check all databases for due reports"""
    logger.info("⏰ Checking scheduled reports...")
    
    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ Failed to list DBs: {e}")
        return
        
    for db_name in databases:
        try:
            # Connect to company DB
            engine = _get_company_engine_for_db(db_name)
            
            with engine.begin() as conn:
                # T10.2 #139: use FOR UPDATE SKIP LOCKED so concurrent
                # scheduler workers do not pick the same due row twice.
                # The enclosing engine.begin() ensures the row lock is
                # held for the entire processing transaction (until the
                # UPDATE next_run_at commits in process_scheduled_report).
                reports = conn.execute(text(
                    "SELECT * FROM scheduled_reports "
                    "WHERE is_active = TRUE "
                    "  AND (next_run_at <= NOW() OR next_run_at IS NULL) "
                    "FOR UPDATE SKIP LOCKED"
                )).fetchall()

                for report in reports:
                    process_scheduled_report(conn, report)
                    
        except Exception as e:
            logger.error(f"❌ Error checking DB {db_name}: {e}")


MATERIALIZED_VIEWS = [
    "mv_revenue_summary",
    "mv_expense_summary",
    "mv_cash_position",
    "mv_top_customers",
    "mv_ar_aging",
    "mv_ap_aging",
    "mv_inventory_turnover",
    "mv_sales_pipeline",
]


def refresh_analytics_materialized_views():
    """Refresh all BI analytics materialized views across company databases."""
    logger.info("⏰ Refreshing analytics materialized views...")

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ Failed to list DBs for MV refresh: {e}")
        return

    for db_name in databases:
        try:
            engine = _get_company_engine_for_db(db_name)

            with engine.connect() as conn:
                # T10.1 P1 #11 — track per-MV refresh timestamps so the
                # frontend can show a "data refreshed N minutes ago" badge.
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS analytics_mv_freshness (
                        mv_name VARCHAR(128) PRIMARY KEY,
                        last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        refresh_duration_ms INTEGER
                    )
                """))
                conn.commit()
                for mv_name in MATERIALIZED_VIEWS:
                    try:
                        # Check if the materialized view exists before refreshing
                        exists = conn.execute(
                            text("SELECT EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = :name)"),
                            {"name": mv_name}
                        ).scalar()
                        if exists:
                            import time as _t
                            _start = _t.monotonic()
                            conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))  # noqa: sql-lint
                            _dur_ms = int((_t.monotonic() - _start) * 1000)
                            conn.execute(text("""
                                INSERT INTO analytics_mv_freshness (mv_name, last_refreshed_at, refresh_duration_ms)
                                VALUES (:n, NOW(), :d)
                                ON CONFLICT (mv_name) DO UPDATE
                                  SET last_refreshed_at = EXCLUDED.last_refreshed_at,
                                      refresh_duration_ms = EXCLUDED.refresh_duration_ms
                            """), {"n": mv_name, "d": _dur_ms})
                            conn.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to refresh {mv_name} in {db_name}: {e}")

                logger.info(f"✅ Refreshed materialized views in {db_name}")

            # T10.2 #148: invalidate the analytics aggregate caches that
            # are derived from these MVs. Without this, the API still
            # serves cached results computed BEFORE the refresh, so the
            # MV refresh has no observable effect for up to one cache
            # TTL on top of the 15-minute MV interval.
            try:
                from utils.cache import invalidate_aggregates
                company_id = db_name.replace("aman_", "", 1)
                invalidate_aggregates(
                    company_id,
                    "reports", "dashboard", "sales_kpi",
                    "trial_balance", "ar_aging", "ap_aging",
                )
            except Exception as e:
                logger.warning(f"⚠️ Cache invalidation after MV refresh failed for {db_name}: {e}")
        except Exception as e:
            logger.error(f"❌ Error refreshing MVs in {db_name}: {e}")


def check_subscription_billing():
    """Check all company databases for subscription billing due, trial expirations, and retries."""
    logger.info("⏰ Checking subscription billing...")

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ Failed to list DBs for subscription billing: {e}")
        return

    from services.subscription_service import check_billing_due, check_trial_expirations

    for db_name in databases:
        try:
            engine = _get_company_engine_for_db(db_name)

            with engine.connect() as conn:
                # Check if subscription tables exist
                has_table = conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'subscription_enrollments')")
                ).scalar()
                if not has_table:
                    continue

                # 1. Check trial expirations
                try:
                    converted = check_trial_expirations(conn)
                    if converted > 0:
                        logger.info(f"✅ Converted {converted} trials in {db_name}")
                except Exception as e:
                    logger.error(f"❌ Trial check failed in {db_name}: {e}")

                # 2. Generate due invoices
                try:
                    results = check_billing_due(conn, user="system")
                    if results:
                        logger.info(f"✅ Generated {len(results)} subscription invoices in {db_name}")
                except Exception as e:
                    logger.error(f"❌ Billing check failed in {db_name}: {e}")

        except Exception as e:
            logger.error(f"❌ Error checking subscription billing in {db_name}: {e}")


def archive_old_audit_logs():
    """T018 + T9.3: Soft-archive audit logs > 1 year (mark is_archived=TRUE),
    and **move** entries older than 7 years into ``audit_logs_archive``
    instead of hard-deleting them. The archive preserves the hash-chain
    columns so forensic verification can still walk the chain.
    """
    logger.info("⏰ Running audit log archival job...")

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list DBs for audit archival: {e}")
        return

    for db_name in databases:
        try:
            company_engine = _get_company_engine_for_db(db_name)

            with company_engine.connect() as conn:
                # Check if is_archived column exists
                has_col = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'audit_logs' AND column_name = 'is_archived')"
                )).scalar()
                if not has_col:
                    continue

                # Archive entries older than 1 year
                # T3.7 (audit #21): the immutability trigger blocks UPDATE/
                # DELETE on audit_logs unless this session-local flag is set.
                conn.execute(text("SET LOCAL audit_logs.allow_admin_op = 'retention'"))
                archived = conn.execute(text(
                    "UPDATE audit_logs SET is_archived = TRUE, archived_at = NOW() "
                    "WHERE created_at < NOW() - INTERVAL '1 year' AND (is_archived IS NULL OR is_archived = FALSE)"
                ))
                conn.commit()

                # T9.3: move entries older than 7 years into the archive table
                # instead of deleting them outright. CTE pattern guarantees the
                # INSERT and DELETE see the same row set atomically.
                has_archive_table = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'audit_logs_archive')"
                )).scalar()
                conn.execute(text("SET LOCAL audit_logs.allow_admin_op = 'retention'"))
                if has_archive_table:
                    moved_result = conn.execute(text(
                        """
                        WITH old_rows AS (
                            DELETE FROM audit_logs
                            WHERE created_at < NOW() - INTERVAL '7 years'
                            RETURNING id, user_id, username, action, resource_type, resource_id,
                                      details, ip_address, branch_id, prev_hash, hash, chain_seq, created_at
                        )
                        INSERT INTO audit_logs_archive
                            (id, user_id, username, action, resource_type, resource_id,
                             details, ip_address, branch_id, prev_hash, hash, chain_seq, created_at)
                        SELECT id, user_id, username, action, resource_type, resource_id,
                               details, ip_address, branch_id, prev_hash, hash, chain_seq, created_at
                        FROM old_rows
                        ON CONFLICT (id) DO NOTHING
                        RETURNING id
                        """
                    ))
                    moved = len(moved_result.fetchall() if moved_result.returns_rows else [])
                else:
                    # Fallback (older tenants without the archive table yet):
                    # keep the legacy hard-delete behaviour to bound table size.
                    moved_obj = conn.execute(text(
                        "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '7 years'"
                    ))
                    moved = moved_obj.rowcount or 0
                conn.commit()

                if archived.rowcount > 0 or moved > 0:
                    logger.info(
                        f"Audit archival in {db_name}: archived={archived.rowcount}, moved_to_archive={moved}"
                    )
        except Exception as e:
            logger.error(f"Error archiving audit logs in {db_name}: {e}")


def archive_old_inventory_transactions():
    """T9.3: Move ``inventory_transactions`` rows older than 7 years into
    ``inventory_transactions_archive``. Keeps the live table — and by
    extension every JOIN against it — performant.

    Runs monthly (cron: 1st of each month at 03:00). Safe on tenants that
    don't have the archive table yet (it just no-ops).
    """
    logger.info("⏰ Running inventory_transactions archival job...")

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list DBs for inventory archival: {e}")
        return

    for db_name in databases:
        try:
            company_engine = _get_company_engine_for_db(db_name)
            with company_engine.connect() as conn:
                has_archive_table = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'inventory_transactions_archive')"
                )).scalar()
                if not has_archive_table:
                    continue
                moved_result = conn.execute(text(
                    """
                    WITH old_rows AS (
                        DELETE FROM inventory_transactions
                        WHERE created_at < NOW() - INTERVAL '7 years'
                        RETURNING id, product_id, warehouse_id, transaction_type,
                                  reference_type, reference_id, reference_document,
                                  quantity, balance_before, balance_after,
                                  unit_cost, total_cost, notes, created_by, created_at
                    )
                    INSERT INTO inventory_transactions_archive
                        (id, product_id, warehouse_id, transaction_type,
                         reference_type, reference_id, reference_document,
                         quantity, balance_before, balance_after,
                         unit_cost, total_cost, notes, created_by, created_at)
                    SELECT id, product_id, warehouse_id, transaction_type,
                           reference_type, reference_id, reference_document,
                           quantity, balance_before, balance_after,
                           unit_cost, total_cost, notes, created_by, created_at
                    FROM old_rows
                    ON CONFLICT (id) DO NOTHING
                    RETURNING id
                    """
                ))
                moved = len(moved_result.fetchall() if moved_result.returns_rows else [])
                conn.commit()
                if moved > 0:
                    logger.info(f"inventory_transactions archival in {db_name}: moved={moved}")
        except Exception as e:
            logger.error(f"Error archiving inventory_transactions in {db_name}: {e}")


def retry_failed_notifications():
    """T019: Retry failed notifications with exponential backoff (1min/5min/30min)."""
    logger.info("⏰ Running notification retry job...")

    # Backoff intervals in seconds by retry_count
    backoff_seconds = {0: 60, 1: 300, 2: 1800}

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list DBs for notification retry: {e}")
        return

    for db_name in databases:
        try:
            company_engine = _get_company_engine_for_db(db_name)

            with company_engine.connect() as conn:
                # Check if delivery_status column exists
                has_col = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'notifications' AND column_name = 'delivery_status')"
                )).scalar()
                if not has_col:
                    continue

                # Find failed notifications eligible for retry
                failed = conn.execute(text(
                    "SELECT id, user_id, title, message, type, retry_count, delivery_channel "
                    "FROM notifications "
                    "WHERE delivery_status = 'failed' AND retry_count < 3 "
                    "AND (last_retry_at IS NULL OR last_retry_at < NOW() - INTERVAL '1 second' * :backoff)"
                ), {"backoff": 60}).fetchall()

                for notif in failed:
                    retry_count = notif.retry_count or 0
                    required_backoff = backoff_seconds.get(retry_count, 1800)

                    # Check actual backoff
                    eligible = conn.execute(text(
                        "SELECT 1 FROM notifications WHERE id = :id "
                        "AND (last_retry_at IS NULL OR last_retry_at < NOW() - INTERVAL '1 second' * :backoff)"
                    ), {"id": notif.id, "backoff": required_backoff}).fetchone()

                    if not eligible:
                        continue

                    # Attempt re-delivery (email channel)
                    try:
                        if notif.delivery_channel == 'email':
                            # Get user email
                            user_row = conn.execute(text(
                                "SELECT email FROM company_users WHERE id = :uid"
                            ), {"uid": notif.user_id}).fetchone()
                            if user_row and user_row.email:
                                send_email([user_row.email], notif.title or "Notification", notif.message or "")

                        # Mark as delivered
                        conn.execute(text(
                            "UPDATE notifications SET delivery_status = 'delivered', "
                            "retry_count = :rc, last_retry_at = NOW() WHERE id = :id"
                        ), {"rc": retry_count + 1, "id": notif.id})
                        conn.commit()
                    except Exception:
                        new_count = retry_count + 1
                        new_status = 'permanently_failed' if new_count >= 3 else 'failed'
                        conn.execute(text(
                            "UPDATE notifications SET delivery_status = :status, "
                            "retry_count = :rc, last_retry_at = NOW() WHERE id = :id"
                        ), {"status": new_status, "rc": new_count, "id": notif.id})
                        conn.commit()
                        logger.warning(f"Notification {notif.id} retry {new_count} failed in {db_name}")

        except Exception as e:
            logger.error(f"Error retrying notifications in {db_name}: {e}")


def auto_fx_revaluation():
    """Monthly FX revaluation pass across all tenant databases.

    Looks up the latest exchange rate per active foreign currency from
    ``currency_rates`` and posts unrealized FX gain/loss adjustments via the
    same logic exposed at ``/api/finance/accounting-depth/fx-revaluation``.
    Idempotent per (company, currency, period) using an idempotency key.
    """
    logger.info("⏰ Running monthly FX revaluation across tenants...")

    databases = []
    try:
        with system_engine.connect() as conn:
            result = conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'"))
            databases = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ Failed to list DBs for FX revaluation: {e}")
        return

    today = date.today()
    period = today.strftime("%Y-%m")
    for db_name in databases:
        company_id = db_name.replace("aman_", "", 1)
        if company_id == "system":
            continue
        try:
            from services import gl_service
            from utils.accounting import get_mapped_account_id
            from utils.fiscal_lock import check_fiscal_period_open

            engine = _get_company_engine_for_db(db_name)
            with engine.connect() as conn:
                base_ccy = conn.execute(
                    text("SELECT value FROM settings WHERE key='base_currency' LIMIT 1")
                ).scalar() or "SAR"
                rates = conn.execute(text("""
                    SELECT DISTINCT ON (currency_code) currency_code, rate
                    FROM currency_rates
                    WHERE currency_code <> :base
                    ORDER BY currency_code, rate_date DESC
                """), {"base": base_ccy}).fetchall()
                if not rates:
                    continue

                gain_acc = get_mapped_account_id(conn, "acc_map_fx_gain") or get_mapped_account_id(conn, "acc_map_unrealized_fx_gain")
                loss_acc = get_mapped_account_id(conn, "acc_map_fx_loss") or get_mapped_account_id(conn, "acc_map_unrealized_fx_loss")
                if not (gain_acc and loss_acc):
                    logger.warning(f"⚠️ FX revaluation: missing FX gain/loss accounts in {db_name}")
                    continue

                try:
                    check_fiscal_period_open(conn, today.isoformat())
                except Exception as e:
                    logger.warning(f"⚠️ FX revaluation skipped for {db_name}: {e}")
                    continue

                for r in rates:
                    ccy, new_rate = r.currency_code, float(r.rate)
                    balances = conn.execute(text("""
                        SELECT a.id AS account_id,
                               COALESCE(SUM(jl.debit_currency - jl.credit_currency), 0) AS fx_balance,
                               COALESCE(SUM(jl.debit - jl.credit), 0) AS local_balance
                        FROM journal_lines jl
                        JOIN accounts a ON a.id = jl.account_id
                        JOIN journal_entries je ON je.id = jl.journal_entry_id
                        WHERE jl.currency = :ccy
                          AND a.account_type IN ('asset','liability')
                          AND je.status = 'posted'
                        GROUP BY a.id
                        HAVING COALESCE(SUM(jl.debit_currency - jl.credit_currency), 0) <> 0
                    """), {"ccy": ccy}).fetchall()

                    lines = []
                    total_adj = 0.0
                    for b in balances:
                        revalued = float(b.fx_balance) * new_rate
                        adj = revalued - float(b.local_balance)
                        if abs(adj) < 0.005:
                            continue
                        if adj > 0:
                            lines.append({"account_id": b.account_id, "debit": adj, "credit": 0,
                                          "description": f"FX reval {ccy} @ {new_rate}"})
                        else:
                            lines.append({"account_id": b.account_id, "debit": 0, "credit": -adj,
                                          "description": f"FX reval {ccy} @ {new_rate}"})
                        total_adj += adj
                    if not lines:
                        continue
                    if total_adj > 0:
                        lines.append({"account_id": gain_acc, "debit": 0, "credit": total_adj,
                                      "description": f"Unrealized FX gain {ccy}"})
                    else:
                        lines.append({"account_id": loss_acc, "debit": -total_adj, "credit": 0,
                                      "description": f"Unrealized FX loss {ccy}"})

                    try:
                        gl_service.create_journal_entry(
                            conn,
                            company_id=company_id,
                            date=today.isoformat(),
                            description=f"Auto FX revaluation {ccy} {period}",
                            lines=lines,
                            user_id=0,
                            username="scheduler.fx_revaluation",
                            source="fx_revaluation",
                            idempotency_key=f"fx_reval:{company_id}:{ccy}:{period}",
                        )
                        conn.commit()
                        logger.info(f"✅ FX revaluation posted for {db_name} / {ccy}")
                    except Exception as e:
                        conn.rollback()
                        logger.warning(f"⚠️ FX revaluation post failed in {db_name}/{ccy}: {e}")
        except Exception as e:
            logger.error(f"❌ FX revaluation error in {db_name}: {e}")


def check_zatca_csid_expiry():
    """T1.5b (#7): Alert operators when an active ZATCA PCSID is approaching
    expiry. Production CSIDs typically last 12 months; an expired CSID causes
    every subsequent invoice submission to be rejected. We alert at 30/7/1
    days remaining and store the last alerted threshold so we don't spam.

    Tenants without the `zatca_csid` table (migration 0015 not applied yet)
    are silently skipped — this job is forward-compatible with older DBs.
    """
    logger.info("⏰ Running ZATCA CSID expiry check...")
    THRESHOLD_DAYS = (30, 7, 1)

    try:
        with system_engine.connect() as conn:
            databases = [r[0] for r in conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE 'aman_%'")
            ).fetchall()]
    except Exception as e:
        logger.error(f"ZATCA CSID check: failed to list DBs: {e}")
        return

    for db_name in databases:
        try:
            engine = _get_company_engine_for_db(db_name)
            with engine.connect() as conn:
                # Forward-compatibility: skip tenants without the table.
                if not conn.execute(text(
                    "SELECT to_regclass('public.zatca_csid')"
                )).scalar():
                    continue

                # 1) Auto-mark already-expired active rows.
                conn.execute(text(
                    "UPDATE zatca_csid SET status = 'expired', "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE status = 'active' AND expires_at <= CURRENT_TIMESTAMP"
                ))

                # 2) For each active CSID expiring soon, fire the strictest
                # threshold not yet alerted.
                rows = conn.execute(text(
                    "SELECT id, environment, pcsid, expires_at, "
                    "       EXTRACT(EPOCH FROM (expires_at - CURRENT_TIMESTAMP))/86400 AS days_left, "
                    "       last_alert_threshold_days "
                    "FROM zatca_csid WHERE status = 'active' "
                    "  AND expires_at <= CURRENT_TIMESTAMP + INTERVAL '30 days'"
                )).fetchall()

                for r in rows:
                    days_left = float(r.days_left or 0)
                    last_t = r.last_alert_threshold_days
                    # Choose the strictest threshold the row has crossed
                    # but not yet alerted at.
                    fire_at = None
                    for t in THRESHOLD_DAYS:
                        if days_left <= t and (last_t is None or t < last_t):
                            fire_at = t
                            break
                    if fire_at is None:
                        continue

                    msg = (
                        f"ZATCA CSID ({r.environment}) expires in "
                        f"{days_left:.1f} day(s) — pcsid prefix "
                        f"{(r.pcsid or '')[:8]}…; renew immediately."
                    )
                    logger.warning(f"[{db_name}] 🚨 {msg}")

                    # Persist a notification if the table exists in this tenant.
                    has_notifs = conn.execute(text(
                        "SELECT to_regclass('public.notifications')"
                    )).scalar()
                    if has_notifs:
                        try:
                            conn.execute(text(
                                "INSERT INTO notifications "
                                "  (user_id, title, message, type, is_read, created_at) "
                                "VALUES (NULL, :title, :msg, 'zatca_csid_expiry', "
                                "        FALSE, CURRENT_TIMESTAMP)"
                            ), {"title": "ZATCA CSID expiring soon", "msg": msg})
                        except Exception:
                            logger.exception(f"[{db_name}] failed to insert CSID notification")

                    conn.execute(text(
                        "UPDATE zatca_csid SET last_alert_at = CURRENT_TIMESTAMP, "
                        "  last_alert_threshold_days = :t, "
                        "  updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                    ), {"t": fire_at, "id": r.id})
                conn.commit()
        except Exception as e:
            logger.error(f"ZATCA CSID check failed in {db_name}: {e}")


# ── T4.6 — Auto-activate cheques on due date ─────────────────────────────────
def activate_due_cheques():
    """Mark pending cheques as 'due' when their due_date has arrived, then notify."""
    from database import _get_all_company_db_names
    today = date.today()
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                for tbl in ("checks_receivable", "checks_payable"):
                    rows = conn.execute(text(f"""  # noqa: sql-lint
                        UPDATE {tbl}
                           SET status = 'due', updated_at = CURRENT_TIMESTAMP
                         WHERE status = 'pending' AND due_date <= :today
                        RETURNING id, amount, check_number
                    """), {"today": today}).fetchall()  # noqa: sql-lint
                    for row in rows:
                        try:
                            conn.execute(text("""
                                INSERT INTO notifications
                                    (user_id, type, title, message, is_read, created_at)
                                SELECT u.id, 'cheque_due',
                                    :title, :msg, FALSE, CURRENT_TIMESTAMP
                                FROM company_users u
                                WHERE u.is_active = TRUE
                                  AND u.role IN ('admin', 'manager', 'superuser')
                            """), {
                                "title": i18n_message("notif_check_due"),
                                "msg": f"شيك رقم {row.check_number} بمبلغ {row.amount} أصبح مستحقاً ({tbl})",
                            })
                        except Exception:
                            pass
                    if rows:
                        logger.info("[%s] %s cheques activated as due in %s", db_name, len(rows), tbl)
        except Exception as e:
            logger.error("activate_due_cheques failed for %s: %s", db_name, e)


# ── T4.7 — Recurring expense/journal templates daily run ─────────────────────
def run_due_recurring_templates():
    """Generate journal entries for all active recurring templates that are due today."""
    from database import _get_all_company_db_names
    today = date.today()
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                templates = conn.execute(text("""
                    SELECT id, name, auto_post, frequency,
                           next_run_date, currency, exchange_rate,
                           branch_id, description
                    FROM recurring_journal_templates
                    WHERE is_active = TRUE
                      AND next_run_date <= :today
                      AND (end_date IS NULL OR end_date >= :today)
                      AND (max_runs IS NULL OR run_count < max_runs)
                    ORDER BY next_run_date
                """), {"today": today}).fetchall()

                for tmpl in templates:
                    try:
                        lines = conn.execute(text("""
                            SELECT account_id, debit, credit, description, cost_center_id
                            FROM recurring_journal_lines
                            WHERE template_id = :tid ORDER BY id
                        """), {"tid": tmpl.id}).fetchall()
                        if not lines:
                            continue

                        entry_status = "posted" if tmpl.auto_post else "draft"
                        entry_desc = f"{tmpl.name} - {today.strftime('%Y-%m-%d')}"
                        if tmpl.description:
                            entry_desc += f" / {tmpl.description}"

                        entry_num_row = conn.execute(text(
                            "SELECT COALESCE(MAX(CAST(SPLIT_PART(entry_number, '-', 2) AS INTEGER)), 0) + 1 "
                            "FROM journal_entries"
                        )).fetchone()
                        seq = entry_num_row[0] if entry_num_row else 1
                        entry_number = f"JE-{seq:06d}"

                        entry_id_row = conn.execute(text("""
                            INSERT INTO journal_entries
                                (entry_number, entry_date, description, status,
                                 currency, exchange_rate, branch_id,
                                 source, created_at)
                            VALUES (:num, :dt, :desc, :status,
                                    :curr, :rate, :branch,
                                    'recurring_template', CURRENT_TIMESTAMP)
                            RETURNING id
                        """), {
                            "num": entry_number,
                            "dt": today,
                            "desc": entry_desc,
                            "status": entry_status,
                            "curr": tmpl.currency,
                            "rate": tmpl.exchange_rate or 1,
                            "branch": tmpl.branch_id,
                        }).fetchone()
                        entry_id = entry_id_row[0]

                        for ln in lines:
                            conn.execute(text("""
                                INSERT INTO journal_lines
                                    (journal_entry_id, account_id, debit, credit,
                                     description, cost_center_id)
                                VALUES (:je, :acc, :dr, :cr, :desc, :cc)
                            """), {
                                "je": entry_id,
                                "acc": ln.account_id,
                                "dr": ln.debit,
                                "cr": ln.credit,
                                "desc": ln.description,
                                "cc": ln.cost_center_id,
                            })

                        # Advance next_run_date
                        freq = tmpl.frequency or "monthly"
                        if freq == "daily":
                            next_run = today + timedelta(days=1)
                        elif freq == "weekly":
                            next_run = today + timedelta(weeks=1)
                        elif freq == "quarterly":
                            next_run = today + timedelta(days=91)
                        elif freq == "yearly":
                            next_run = today.replace(year=today.year + 1)
                        else:  # monthly
                            m = today.month % 12 + 1
                            y = today.year + (1 if today.month == 12 else 0)
                            import calendar as _cal
                            last_day = _cal.monthrange(y, m)[1]
                            next_run = today.replace(year=y, month=m,
                                                     day=min(today.day, last_day))

                        conn.execute(text("""
                            UPDATE recurring_journal_templates
                               SET next_run_date = :nrd,
                                   run_count = run_count + 1,
                                   updated_at = CURRENT_TIMESTAMP
                             WHERE id = :tid
                        """), {"nrd": next_run, "tid": tmpl.id})
                        logger.info("[%s] Recurring template '%s' → %s (next %s)",
                                    db_name, tmpl.name, entry_number, next_run)
                    except Exception as tmpl_err:
                        logger.error("[%s] recurring template %d failed: %s",
                                     db_name, tmpl.id, tmpl_err)
        except Exception as e:
            logger.error("run_due_recurring_templates failed for %s: %s", db_name, e)


# ── T4.8 — Auto bank reconciliation (daily, all draft reconciliations) ───────
def auto_reconcile_all_drafts():
    """Run auto-match for every draft bank reconciliation across all companies."""
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.connect() as conn:
                recs = conn.execute(text("""
                    SELECT id FROM bank_reconciliations
                    WHERE status = 'draft'
                    ORDER BY id
                """)).fetchall()

            for rec in recs:
                try:
                    with eng.begin() as conn:
                        _auto_match_reconciliation(conn, rec.id)
                    logger.info("[%s] auto-reconcile rec_id=%s done", db_name, rec.id)
                except Exception as rec_err:
                    logger.error("[%s] auto-reconcile rec_id=%s failed: %s",
                                 db_name, rec.id, rec_err)
        except Exception as e:
            logger.error("auto_reconcile_all_drafts failed for %s: %s", db_name, e)


def _auto_match_reconciliation(conn, reconciliation_id: int):
    """Core auto-match logic reused by both the API and the scheduler."""
    from decimal import Decimal

    def _dec(value) -> Decimal:
        return Decimal(str(value or 0))

    rec = conn.execute(text("""
        SELECT r.id, t.gl_account_id, r.statement_date, r.branch_id,
               COALESCE(r.tolerance_amount, 0) AS tolerance_amount
        FROM bank_reconciliations r
        JOIN treasury_accounts t ON r.treasury_account_id = t.id
        WHERE r.id = :id AND r.status = 'draft'
    """), {"id": reconciliation_id}).fetchone()
    if not rec:
        return

    statement_lines = conn.execute(text("""
        SELECT id, transaction_date, debit, credit
        FROM bank_statement_lines
        WHERE reconciliation_id = :rid
          AND (is_reconciled = FALSE OR is_reconciled IS NULL)
        ORDER BY transaction_date, id
    """), {"rid": reconciliation_id}).fetchall()

    branch_filter = ""
    ledger_params = {"gl_id": rec.gl_account_id, "stmt_date": rec.statement_date}
    if rec.branch_id:
        branch_filter = "AND je.branch_id = :branch_id"
        ledger_params["branch_id"] = rec.branch_id

    ledger_lines = conn.execute(text(f"""  # noqa: sql-lint
        SELECT jl.id, je.entry_date, jl.debit, jl.credit
        FROM journal_lines jl
        JOIN journal_entries je ON jl.journal_entry_id = je.id
        WHERE jl.account_id = :gl_id
          AND (jl.is_reconciled = FALSE OR jl.is_reconciled IS NULL)
          AND je.status = 'posted'
          AND je.entry_date <= :stmt_date
          {branch_filter}
        ORDER BY je.entry_date, jl.id
        FOR UPDATE OF jl SKIP LOCKED
    """), ledger_params).fetchall()  # noqa: sql-lint

    amount_tolerance = max(_dec(rec.tolerance_amount), Decimal("0"))
    matched_journal_lines = set()
    matched_count = 0

    for statement_line in statement_lines:
        statement_debit = _dec(statement_line.debit)
        statement_credit = _dec(statement_line.credit)
        for journal_line in ledger_lines:
            if journal_line.id in matched_journal_lines:
                continue
            journal_debit = _dec(journal_line.debit)
            journal_credit = _dec(journal_line.credit)

            amounts_match = False
            if statement_debit > 0 and journal_credit > 0:
                amounts_match = abs(statement_debit - journal_credit) <= amount_tolerance
            elif statement_credit > 0 and journal_debit > 0:
                amounts_match = abs(statement_credit - journal_debit) <= amount_tolerance
            if not amounts_match:
                continue

            day_diff = abs((statement_line.transaction_date - journal_line.entry_date).days)
            if day_diff > 3:
                continue

            conn.execute(text("""
                UPDATE bank_statement_lines
                SET is_reconciled = TRUE, matched_journal_line_id = :journal_line_id
                WHERE id = :statement_line_id
            """), {
                "journal_line_id": journal_line.id,
                "statement_line_id": statement_line.id,
            })
            conn.execute(text("""
                UPDATE journal_lines
                SET is_reconciled = TRUE, reconciliation_id = :reconciliation_id
                WHERE id = :journal_line_id
            """), {
                "reconciliation_id": reconciliation_id,
                "journal_line_id": journal_line.id,
            })
            matched_journal_lines.add(journal_line.id)
            matched_count += 1
            break

    if matched_count:
        conn.execute(text(
            "UPDATE bank_reconciliations SET updated_at = CURRENT_TIMESTAMP WHERE id = :id"
        ), {"id": reconciliation_id})


# ── T4.4 — Low stock alerts ───────────────────────────────────────────────────
def check_low_stock_alerts():
    """Flag inventory items where effective qty (quantity - reserved) <= reorder_level."""
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.connect() as conn:
                low = conn.execute(text("""
                    SELECT i.id, i.product_id, i.quantity,
                           COALESCE(i.reserved_quantity, 0) AS reserved_quantity,
                           i.reorder_level, i.warehouse_id,
                           p.name AS product_name
                    FROM inventory i
                    LEFT JOIN products p ON i.product_id = p.id
                    WHERE i.reorder_level > 0
                      AND (i.quantity - COALESCE(i.reserved_quantity, 0)) <= i.reorder_level
                """)).fetchall()

            if not low:
                continue

            with eng.begin() as conn:
                for item in low:
                    effective = float(item.quantity) - float(item.reserved_quantity)
                    try:
                        conn.execute(text("""
                            INSERT INTO notifications
                                (user_id, type, title, message, is_read, created_at)
                            SELECT u.id, 'low_stock',
                                :title, :msg, FALSE, CURRENT_TIMESTAMP
                            FROM company_users u
                            WHERE u.is_active = TRUE
                              AND u.role IN ('admin', 'manager', 'inventory_manager')
                            ON CONFLICT DO NOTHING
                        """), {
                            "title": i18n_message("notif_low_stock"),
                            "msg": (
                                f"المنتج '{item.product_name or item.product_id}': "
                                f"الكمية المتاحة {effective:.2f} "
                                f"وصلت أو تجاوزت حد إعادة الطلب {float(item.reorder_level):.2f}"
                            ),
                        })
                    except Exception:
                        pass
            logger.info("[%s] Low stock check: %d items at/below reorder level", db_name, len(low))
        except Exception as e:
            logger.error("check_low_stock_alerts failed for %s: %s", db_name, e)


# ── T4.5 — POS Offline Inbox Worker ──────────────────────────────────────────
def process_pos_offline_inbox():
    """Process queued POS offline orders (FIFO), detect conflicts, create orders."""
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.connect() as conn:
                items = conn.execute(text("""
                    SELECT id, client_uuid, session_id, user_id, payload, client_created_at
                    FROM pos_offline_inbox
                    WHERE status = 'queued'
                    ORDER BY received_at ASC
                    LIMIT 100
                """)).fetchall()

            for item in items:
                try:
                    import json as _json
                    payload = item.payload if isinstance(item.payload, dict) else _json.loads(item.payload or "{}")
                    conflict_reason = None

                    with eng.begin() as conn:
                        # Conflict check 1 — price drift > 5%
                        order_lines = payload.get("lines") or payload.get("items") or []
                        for line in order_lines:
                            pid = line.get("product_id")
                            if not pid:
                                continue
                            cur_price_row = conn.execute(text(
                                "SELECT sale_price FROM products WHERE id = :pid"
                            ), {"pid": pid}).fetchone()
                            if cur_price_row:
                                cur = float(cur_price_row[0] or 0)
                                ordered = float(line.get("unit_price") or line.get("price") or 0)
                                if cur > 0 and ordered > 0 and abs(cur - ordered) / cur > 0.05:
                                    conflict_reason = (
                                        f"price drift >5% on product {pid}: "
                                        f"ordered={ordered} current={cur}"
                                    )
                                    break

                        # Conflict check 2 — insufficient stock
                        if not conflict_reason:
                            for line in order_lines:
                                pid = line.get("product_id")
                                qty = float(line.get("quantity") or line.get("qty") or 0)
                                if not pid or qty <= 0:
                                    continue
                                stock_row = conn.execute(text("""
                                    SELECT COALESCE(quantity,0) - COALESCE(reserved_quantity,0) AS avail
                                    FROM inventory WHERE product_id = :pid
                                    LIMIT 1
                                """), {"pid": pid}).fetchone()
                                if stock_row and float(stock_row.avail) < qty:
                                    conflict_reason = (
                                        f"insufficient stock for product {pid}: "
                                        f"need {qty} have {float(stock_row.avail):.2f}"
                                    )
                                    break

                        if conflict_reason:
                            conn.execute(text("""
                                UPDATE pos_offline_inbox
                                   SET status = 'conflict',
                                       error = :err,
                                       processed_at = CURRENT_TIMESTAMP
                                 WHERE id = :id
                            """), {"err": conflict_reason[:500], "id": item.id})
                            # T17 #88 — also surface in the sync-conflicts table
                            # so managers see it on the resolution dashboard.
                            try:
                                import json as _json2
                                kind = "price_drift" if "price drift" in (conflict_reason or "") else (
                                    "stock_oversold" if "stock" in (conflict_reason or "").lower() else "other"
                                )
                                conn.execute(text("""
                                    INSERT INTO pos_sync_conflicts
                                        (session_id, client_op_id, op_type,
                                         client_payload, conflict_kind, server_state,
                                         resolution, created_at)
                                    VALUES (:sid, :cop, 'order',
                                            CAST(:cp AS JSONB), :kind, NULL,
                                            'pending', NOW())
                                """), {
                                    "sid": item.session_id,
                                    "cop": item.client_uuid,
                                    "cp": _json2.dumps(payload),
                                    "kind": kind,
                                })
                            except Exception:
                                pass
                            logger.warning("[%s] POS offline conflict id=%s: %s",
                                           db_name, item.id, conflict_reason)
                            continue

                        # No conflict — create POS order
                        order_payload = {
                            **payload,
                            "_offline_inbox_id": item.id,
                            "_client_uuid": item.client_uuid,
                        }
                        try:
                            from routers.pos import _create_pos_order_direct
                            _create_pos_order_direct(conn, order_payload, user_id=item.user_id)
                        except (ImportError, AttributeError):
                            # If direct function not exposed, mark as conflict for manual review
                            conn.execute(text("""
                                UPDATE pos_offline_inbox
                                   SET status = 'conflict',
                                       error = 'direct order creation not available — manual review required',
                                       processed_at = CURRENT_TIMESTAMP
                                 WHERE id = :id
                            """), {"id": item.id})
                            continue

                        conn.execute(text("""
                            UPDATE pos_offline_inbox
                               SET status = 'processed',
                                   processed_at = CURRENT_TIMESTAMP
                             WHERE id = :id
                        """), {"id": item.id})

                except Exception as item_err:
                    logger.error("[%s] POS offline item id=%s error: %s",
                                 db_name, item.id, item_err)
                    try:
                        with eng.begin() as conn:
                            conn.execute(text("""
                                UPDATE pos_offline_inbox
                                   SET status = 'conflict',
                                       error = :err,
                                       processed_at = CURRENT_TIMESTAMP
                                 WHERE id = :id
                            """), {"err": str(item_err)[:500], "id": item.id})
                    except Exception:
                        pass
        except Exception as e:
            logger.error("process_pos_offline_inbox failed for %s: %s", db_name, e)


# ── T4.3 — Smart Alert rule evaluation ───────────────────────────────────────
def evaluate_smart_alerts():
    """Evaluate enabled alert rules across all companies and fire notifications."""
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.connect() as conn:
                # Check if alert_rules table exists (may not be created yet)
                tbl_exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'alert_rules' LIMIT 1
                """)).fetchone()
                if not tbl_exists:
                    continue

                rules = conn.execute(text("""
                    SELECT id, name, rule_type, condition_json, threshold, notify_users
                    FROM alert_rules WHERE enabled = TRUE
                """)).fetchall()

            for rule in rules:
                try:
                    import json as _json
                    condition = rule.condition_json if isinstance(rule.condition_json, dict) \
                                else _json.loads(rule.condition_json or "{}")
                    _evaluate_single_alert(eng, rule, condition)
                except Exception as re:
                    logger.error("[%s] alert rule %d failed: %s", db_name, rule.id, re)
        except Exception as e:
            logger.error("evaluate_smart_alerts failed for %s: %s", db_name, e)


def _evaluate_single_alert(eng, rule, condition: dict):
    """Evaluate one alert rule and insert an alert if triggered."""
    import json as _json
    rule_type = rule.rule_type
    threshold = float(rule.threshold or 0)

    with eng.begin() as conn:
        triggered = False
        details: dict = {}

        if rule_type == "low_stock":
            count_row = conn.execute(text("""
                SELECT COUNT(*) FROM inventory
                WHERE reorder_level > 0
                  AND (quantity - COALESCE(reserved_quantity, 0)) <= reorder_level
            """)).scalar() or 0
            if count_row > threshold:
                triggered = True
                details = {"low_stock_items": count_row}

        elif rule_type == "overdue_receivable":
            days = int(condition.get("days_overdue", 30))
            total_row = conn.execute(text(f"""  # noqa: sql-lint
                SELECT COALESCE(SUM(amount_due), 0) FROM receivables
                WHERE status NOT IN ('paid','cancelled')
                  AND due_date < CURRENT_DATE - INTERVAL '{days} days'
            """)).scalar() or 0  # noqa: sql-lint
            if float(total_row) > threshold:
                triggered = True
                details = {"overdue_amount": float(total_row), "days": days}

        elif rule_type == "budget_overspend":
            pct = float(condition.get("overspend_pct", 100))
            over = conn.execute(text("""
                SELECT COUNT(*) FROM budget_items
                WHERE allocated_amount > 0
                  AND actual_amount > allocated_amount * (:pct / 100.0)
            """), {"pct": pct}).scalar() or 0
            if over > threshold:
                triggered = True
                details = {"overspend_items": over, "threshold_pct": pct}

        if not triggered:
            return

        # Insert alert record
        alert_row = conn.execute(text("""
            INSERT INTO alerts (rule_id, triggered_at, details_json, status)
            VALUES (:rid, CURRENT_TIMESTAMP, :det, 'open')
            RETURNING id
        """), {"rid": rule.id, "det": _json.dumps(details)}).fetchone()
        alert_id = alert_row[0]

        # Notify target users
        import json as _json2
        notify_users = rule.notify_users
        user_ids = notify_users if isinstance(notify_users, list) \
                   else (_json2.loads(notify_users) if notify_users else [])
        for uid in user_ids:
            try:
                conn.execute(text("""
                    INSERT INTO notifications
                        (user_id, type, title, message, is_read, created_at)
                    VALUES (:uid, 'smart_alert', :title, :msg, FALSE, CURRENT_TIMESTAMP)
                """), {
                    "uid": uid,
                    "title": f"تنبيه ذكي: {rule.name}",
                    "msg": f"قاعدة '{rule.name}' أُطلقت — {_json2.dumps(details, ensure_ascii=False)}",
                })
            except Exception:
                pass

        logger.info("Smart alert '%s' (id=%d) fired — alert_id=%d", rule.name, rule.id, alert_id)


# ── T10.1 P1 #67 — Monthly EOS provision snapshot ────────────────────────────
def run_eos_provision_snapshot():
    """Snapshot end-of-service gratuity for every active employee.

    Runs on the 1st of each month at 03:30 (after monthly inventory
    archival). Writes one row per (employee_id, period_end) into
    ``eos_provisions``. The delta vs. the previous snapshot represents
    the period's expense; finance can review and post the JE manually
    via a dedicated endpoint, or we auto-post it later.
    """
    from database import _get_all_company_db_names
    from utils.hr_helpers import calculate_eos_gratuity
    from decimal import Decimal as _D

    period_end = date.today().replace(day=1) - timedelta(days=1)  # last day of previous month
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'eos_provisions'
                """)).scalar()
                if not exists:
                    continue
                employees = conn.execute(text("""
                    SELECT id, hire_date,
                           COALESCE(basic_salary, 0)
                           + COALESCE(housing_allowance, 0)
                           + COALESCE(transport_allowance, 0) AS monthly_salary
                      FROM employees
                     WHERE is_active = TRUE
                       AND hire_date IS NOT NULL
                       AND hire_date <= :pe
                """), {"pe": period_end}).fetchall()

                for emp in employees:
                    years = _D(str((period_end - emp.hire_date).days)) / _D("365.25")
                    if years <= 0:
                        continue
                    salary = _D(str(emp.monthly_salary or 0))
                    if salary <= 0:
                        continue
                    eos = calculate_eos_gratuity(salary, years, "termination")
                    accrued = eos["full_gratuity"]
                    prev = conn.execute(text("""
                        SELECT accrued_gratuity FROM eos_provisions
                        WHERE employee_id = :eid AND period_end < :pe
                        ORDER BY period_end DESC LIMIT 1
                    """), {"eid": emp.id, "pe": period_end}).scalar()
                    delta = accrued - _D(str(prev or 0))
                    conn.execute(text("""
                        INSERT INTO eos_provisions
                            (employee_id, period_end, years_of_service,
                             monthly_salary, accrued_gratuity, delta_from_previous)
                        VALUES (:eid, :pe, :yrs, :sal, :acc, :delta)
                        ON CONFLICT (employee_id, period_end) DO UPDATE
                          SET years_of_service = EXCLUDED.years_of_service,
                              monthly_salary = EXCLUDED.monthly_salary,
                              accrued_gratuity = EXCLUDED.accrued_gratuity,
                              delta_from_previous = EXCLUDED.delta_from_previous
                    """), {
                        "eid": emp.id,
                        "pe": period_end,
                        "yrs": str(years.quantize(_D("0.0001"))),
                        "sal": str(salary),
                        "acc": str(accrued),
                        "delta": str(delta),
                    })
                logger.info("[%s] EOS provision snapshot for %s: %d employees",
                            db_name, period_end, len(employees))
        except Exception as e:
            logger.error("EOS provision snapshot failed for %s: %s", db_name, e)


# ── T10.1 P1 #57/#58 — Hard-delete soft-deleted documents past retention ────
def purge_soft_deleted_documents():
    """Hard-delete document rows + uploaded files older than retention.

    Reads ``document_retention_days`` from ``company_settings`` (default
    365 days). Documents soft-deleted before that cutoff are removed
    along with their files on disk. Set to 0 to disable.
    """
    from database import _get_all_company_db_names
    import os as _os
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                tbl_exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'documents'
                """)).scalar()
                if not tbl_exists:
                    continue
                col_exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = 'is_deleted'
                """)).scalar()
                if not col_exists:
                    continue

                limit_row = conn.execute(text(
                    "SELECT setting_value FROM company_settings "
                    "WHERE setting_key = 'document_retention_days'"
                )).scalar()
                try:
                    retention = int(limit_row) if limit_row not in (None, "") else 365
                except (ValueError, TypeError):
                    retention = 365
                if retention <= 0:
                    continue
                cutoff = datetime.utcnow() - timedelta(days=retention)

                rows = conn.execute(text("""
                    SELECT id, file_path FROM documents
                     WHERE is_deleted = TRUE
                       AND COALESCE(deleted_at, updated_at, created_at) < :cutoff
                """), {"cutoff": cutoff}).fetchall()

                deleted = 0
                for r in rows:
                    if r.file_path:
                        try:
                            if _os.path.isfile(r.file_path):
                                _os.remove(r.file_path)
                        except Exception:
                            logger.warning("Could not remove file %s", r.file_path)
                    conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": r.id})
                    deleted += 1
                if deleted:
                    logger.info("[%s] purged %d soft-deleted documents", db_name, deleted)
        except Exception as e:
            logger.error("purge_soft_deleted_documents failed for %s: %s", db_name, e)


# ── T10.1 P1 #110g — Treasury vs GL reconciliation health check ─────────────
def reconcile_treasury_balances():
    """Compare ``treasury_accounts.current_balance`` against the GL-derived
    balance for each treasury. Discrepancies are written to a
    ``treasury_reconciliation_alerts`` row (created on demand) and a
    high-priority notification is raised for finance admins.

    This is a *detection* job — it does NOT mutate balances. The
    canonical fix path is the helper ``utils.treasury_balance.recalc``
    triggered by an admin once the discrepancy is investigated.
    """
    from database import _get_all_company_db_names
    from decimal import Decimal as _D
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS treasury_reconciliation_alerts (
                        id SERIAL PRIMARY KEY,
                        treasury_account_id INTEGER NOT NULL,
                        as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        recorded_balance DECIMAL(18, 4) NOT NULL,
                        gl_balance DECIMAL(18, 4) NOT NULL,
                        discrepancy DECIMAL(18, 4) NOT NULL,
                        is_resolved BOOLEAN DEFAULT FALSE,
                        resolved_at TIMESTAMPTZ
                    )
                """))
                rows = conn.execute(text("""
                    SELECT ta.id, ta.name, ta.current_balance, ta.gl_account_id,
                           COALESCE((
                               SELECT SUM(jl.debit - jl.credit)
                                 FROM journal_lines jl
                                 JOIN journal_entries je ON jl.journal_entry_id = je.id
                                WHERE jl.account_id = ta.gl_account_id
                                  AND je.status = 'posted'
                           ), 0) AS gl_balance
                      FROM treasury_accounts ta
                     WHERE ta.is_active = TRUE
                       AND ta.gl_account_id IS NOT NULL
                """)).fetchall()
                for r in rows:
                    rec = _D(str(r.current_balance or 0))
                    gl = _D(str(r.gl_balance or 0))
                    diff = rec - gl
                    if abs(diff) > _D("0.01"):
                        conn.execute(text("""
                            INSERT INTO treasury_reconciliation_alerts
                                (treasury_account_id, recorded_balance, gl_balance, discrepancy)
                            VALUES (:tid, :rec, :gl, :diff)
                        """), {"tid": r.id, "rec": str(rec), "gl": str(gl), "diff": str(diff)})
                        logger.warning(
                            "[%s] treasury %s (#%s) discrepancy: recorded=%s gl=%s diff=%s",
                            db_name, r.name, r.id, rec, gl, diff,
                        )
        except Exception as e:
            logger.error("reconcile_treasury_balances failed for %s: %s", db_name, e)


# ── T10.1 P1 #41 — CRM stale opportunity & expected-close alerts ─────────────
def crm_followup_alerts():
    """Notify owners about:

    * opportunities not updated for ``crm_stale_days`` (default 14) days, and
        * opportunities whose ``expected_close_date`` is within
            ``crm_close_horizon_days`` (default 7) days but still open, and
        * opportunity activities whose ``due_date`` has arrived and are not done.

    Avoids duplicate alerts within 24h via a guard on the
    ``crm_followup_alerts_log`` table created here.
    """
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                # ensure log table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS crm_followup_alerts_log (
                        id SERIAL PRIMARY KEY,
                        opportunity_id INTEGER NOT NULL,
                        alert_type VARCHAR(40) NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_crm_followup_log "
                    "ON crm_followup_alerts_log(opportunity_id, alert_type, sent_at)"
                ))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS crm_activity_reminders_log (
                        id SERIAL PRIMARY KEY,
                        activity_id INTEGER NOT NULL,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_crm_activity_reminders_log "
                    "ON crm_activity_reminders_log(activity_id, sent_at)"
                ))

                def _setting(key, default):
                    try:
                        v = conn.execute(text(
                            "SELECT setting_value FROM company_settings WHERE setting_key = :k"
                        ), {"k": key}).scalar()
                        return int(v) if v is not None else default
                    except Exception:
                        return default

                stale_days = _setting("crm_stale_days", 14)
                horizon_days = _setting("crm_close_horizon_days", 7)

                # Stale: untouched > stale_days, still open
                stale_rows = conn.execute(text("""
                    SELECT o.id, o.title, o.assigned_to, o.expected_close_date
                      FROM sales_opportunities o
                     WHERE COALESCE(o.is_deleted, FALSE) = FALSE
                       AND o.stage NOT IN ('won','lost','closed','closed_won','closed_lost')
                       AND o.updated_at < NOW() - make_interval(days => :d)
                       AND NOT EXISTS (
                           SELECT 1 FROM crm_followup_alerts_log l
                            WHERE l.opportunity_id = o.id
                              AND l.alert_type = 'stale'
                              AND l.sent_at > NOW() - INTERVAL '24 hours'
                       )
                     LIMIT 500
                """), {"d": stale_days}).fetchall()

                for r in stale_rows:
                    if not r.assigned_to:
                        continue
                    conn.execute(text("""
                        INSERT INTO notifications
                            (user_id, type, title, message, is_read, created_at)
                        VALUES (:uid, 'crm_stale_opportunity',
                                'فرصة مهملة', :msg, FALSE, NOW())
                    """), {
                        "uid": r.assigned_to,
                        "msg": f"الفرصة #{r.id} ({r.title}) لم تُحدَّث منذ {stale_days} يوم",
                    })
                    conn.execute(text(
                        "INSERT INTO crm_followup_alerts_log (opportunity_id, alert_type) "
                        "VALUES (:oid, 'stale')"
                    ), {"oid": r.id})

                # Approaching close
                close_rows = conn.execute(text("""
                    SELECT o.id, o.title, o.assigned_to, o.expected_close_date
                      FROM sales_opportunities o
                     WHERE COALESCE(o.is_deleted, FALSE) = FALSE
                       AND o.stage NOT IN ('won','lost','closed','closed_won','closed_lost')
                       AND o.expected_close_date IS NOT NULL
                       AND o.expected_close_date <= CURRENT_DATE + make_interval(days => :h)
                       AND o.expected_close_date >= CURRENT_DATE
                       AND NOT EXISTS (
                           SELECT 1 FROM crm_followup_alerts_log l
                            WHERE l.opportunity_id = o.id
                              AND l.alert_type = 'expected_close'
                              AND l.sent_at > NOW() - INTERVAL '24 hours'
                       )
                     LIMIT 500
                """), {"h": horizon_days}).fetchall()

                for r in close_rows:
                    if not r.assigned_to:
                        continue
                    conn.execute(text("""
                        INSERT INTO notifications
                            (user_id, type, title, message, is_read, created_at)
                        VALUES (:uid, 'crm_expected_close',
                                'فرصة قاربت تاريخ الإغلاق', :msg, FALSE, NOW())
                    """), {
                        "uid": r.assigned_to,
                        "msg": f"الفرصة #{r.id} ({r.title}) تاريخ الإغلاق المتوقع {r.expected_close_date}",
                    })
                    conn.execute(text(
                        "INSERT INTO crm_followup_alerts_log (opportunity_id, alert_type) "
                        "VALUES (:oid, 'expected_close')"
                    ), {"oid": r.id})

                activity_rows = conn.execute(text("""
                    SELECT a.id, a.title, a.activity_type, a.due_date,
                           o.id AS opportunity_id, o.title AS opportunity_title,
                           o.assigned_to
                      FROM opportunity_activities a
                      JOIN sales_opportunities o ON o.id = a.opportunity_id
                     WHERE COALESCE(a.completed, FALSE) = FALSE
                       AND a.due_date IS NOT NULL
                       AND a.due_date <= CURRENT_DATE
                       AND COALESCE(o.is_deleted, FALSE) = FALSE
                       AND o.stage NOT IN ('won','lost','closed','closed_won','closed_lost')
                       AND NOT EXISTS (
                           SELECT 1 FROM crm_activity_reminders_log l
                            WHERE l.activity_id = a.id
                              AND l.sent_at > NOW() - INTERVAL '24 hours'
                       )
                     ORDER BY a.due_date ASC
                     LIMIT 500
                """)).fetchall()

                for activity in activity_rows:
                    if not activity.assigned_to:
                        continue
                    conn.execute(text("""
                        INSERT INTO notifications
                            (user_id, type, title, message, is_read, created_at)
                        VALUES (:uid, 'crm_activity_due',
                                'نشاط CRM مستحق', :msg, FALSE, NOW())
                    """), {
                        "uid": activity.assigned_to,
                        "msg": (
                            f"النشاط #{activity.id} ({activity.title or activity.activity_type}) "
                            f"للفرصة #{activity.opportunity_id} ({activity.opportunity_title}) "
                            f"مستحق في {activity.due_date}"
                        ),
                    })
                    conn.execute(text(
                        "INSERT INTO crm_activity_reminders_log (activity_id) VALUES (:activity_id)"
                    ), {"activity_id": activity.id})

                if stale_rows or close_rows or activity_rows:
                    logger.info(
                        "[%s] crm_followup_alerts: stale=%s close=%s activities=%s",
                        db_name, len(stale_rows), len(close_rows), len(activity_rows),
                    )
        except Exception as e:
            logger.error("crm_followup_alerts failed for %s: %s", db_name, e)


# ── T10.1 P1 #110c — Temporal correlation fraud detection ────────────────────
def detect_suspicious_temporal_patterns():
    """Flag suspicious user activity patterns inside a short time window.

    Pattern A — *vendor speed-run*: same user creates a supplier, then
    posts a purchase invoice for that supplier, then approves it, all
    inside ``fraud_window_minutes`` (default 5).

    Pattern B — *self approval*: same user approves a document they
    themselves created (covers expenses, purchase invoices, journal
    entries) — independent of timing.

    Findings are written to ``fraud_correlation_alerts`` (created on
    demand) and a high-priority notification is sent to users with
    role ``admin`` / ``superuser``.
    """
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS fraud_correlation_alerts (
                        id SERIAL PRIMARY KEY,
                        pattern VARCHAR(80) NOT NULL,
                        user_id INTEGER,
                        related_resource_type VARCHAR(60),
                        related_resource_id VARCHAR(60),
                        details JSONB,
                        is_resolved BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_fraud_corr_alerts_pattern_user "
                    "ON fraud_correlation_alerts(pattern, user_id, created_at)"
                ))

                # window setting
                try:
                    val = conn.execute(text(
                        "SELECT setting_value FROM company_settings WHERE setting_key='fraud_window_minutes'"
                    )).scalar()
                    window_min = int(val) if val else 5
                except Exception:
                    window_min = 5

                # Pattern A — vendor speed-run within last 24h
                # Use audit_logs for resource_type='supplier' (create) and
                # resource_type='purchase_invoice' (create + approve).
                try:
                    rows_a = conn.execute(text("""
                        WITH suppliers AS (
                            SELECT user_id, resource_id::text AS supplier_id, created_at
                              FROM audit_logs
                             WHERE action = 'supplier.create'
                               AND created_at > NOW() - INTERVAL '24 hours'
                        ), inv AS (
                            SELECT user_id, resource_id::text AS invoice_id, created_at,
                                   (details->>'supplier_id') AS supplier_id
                              FROM audit_logs
                             WHERE action IN ('purchase_invoice.create','purchase.create')
                               AND created_at > NOW() - INTERVAL '24 hours'
                        ), appr AS (
                            SELECT user_id, resource_id::text AS invoice_id, created_at
                              FROM audit_logs
                             WHERE action IN ('purchase_invoice.approve','approval.approve')
                               AND created_at > NOW() - INTERVAL '24 hours'
                        )
                        SELECT s.user_id, s.supplier_id, i.invoice_id,
                               s.created_at AS sup_at, i.created_at AS inv_at, a.created_at AS app_at
                          FROM suppliers s
                          JOIN inv i ON i.user_id = s.user_id
                                    AND i.supplier_id = s.supplier_id
                                    AND i.created_at BETWEEN s.created_at
                                                     AND s.created_at + make_interval(mins => :w)
                          JOIN appr a ON a.user_id = s.user_id
                                     AND a.invoice_id = i.invoice_id
                                     AND a.created_at BETWEEN i.created_at
                                                       AND i.created_at + make_interval(mins => :w)
                          WHERE NOT EXISTS (
                              SELECT 1 FROM fraud_correlation_alerts f
                               WHERE f.pattern = 'vendor_speedrun'
                                 AND f.related_resource_type = 'purchase_invoice'
                                 AND f.related_resource_id = i.invoice_id
                          )
                         LIMIT 200
                    """), {"w": window_min}).fetchall()
                except Exception as e:
                    logger.debug("[%s] vendor_speedrun query skipped: %s", db_name, e)
                    rows_a = []

                import json as _json
                for r in rows_a:
                    conn.execute(text("""
                        INSERT INTO fraud_correlation_alerts
                            (pattern, user_id, related_resource_type, related_resource_id, details)
                        VALUES ('vendor_speedrun', :uid, 'purchase_invoice', :iid, CAST(:det AS JSONB))
                    """), {
                        "uid": r.user_id,
                        "iid": r.invoice_id,
                        "det": _json.dumps({
                            "supplier_id": r.supplier_id,
                            "supplier_at": str(r.sup_at),
                            "invoice_at": str(r.inv_at),
                            "approved_at": str(r.app_at),
                            "window_minutes": window_min,
                        }),
                    })

                # Pattern B — self approval (last 24h)
                try:
                    rows_b = conn.execute(text("""
                        WITH creates AS (
                            SELECT user_id, action, resource_type, resource_id, created_at
                              FROM audit_logs
                             WHERE action IN ('expense.create','purchase_invoice.create',
                                              'journal_entry.create','expense.submit')
                               AND created_at > NOW() - INTERVAL '24 hours'
                        ), approvals AS (
                            SELECT user_id, resource_type, resource_id, created_at
                              FROM audit_logs
                             WHERE action IN ('expense.approve','purchase_invoice.approve',
                                              'journal_entry.approve','approval.approve')
                               AND created_at > NOW() - INTERVAL '24 hours'
                        )
                        SELECT c.user_id, c.resource_type, c.resource_id,
                               c.created_at AS create_at, a.created_at AS approve_at
                          FROM creates c
                          JOIN approvals a USING (user_id, resource_type, resource_id)
                         WHERE NOT EXISTS (
                              SELECT 1 FROM fraud_correlation_alerts f
                               WHERE f.pattern = 'self_approval'
                                 AND f.related_resource_type = c.resource_type
                                 AND f.related_resource_id = c.resource_id::text
                         )
                         LIMIT 200
                    """)).fetchall()
                except Exception as e:
                    logger.debug("[%s] self_approval query skipped: %s", db_name, e)
                    rows_b = []

                for r in rows_b:
                    conn.execute(text("""
                        INSERT INTO fraud_correlation_alerts
                            (pattern, user_id, related_resource_type, related_resource_id, details)
                        VALUES ('self_approval', :uid, :rt, :rid, CAST(:det AS JSONB))
                    """), {
                        "uid": r.user_id,
                        "rt": r.resource_type,
                        "rid": str(r.resource_id),
                        "det": _json.dumps({
                            "created_at": str(r.create_at),
                            "approved_at": str(r.approve_at),
                        }),
                    })

                if rows_a or rows_b:
                    # Notify admins
                    try:
                        conn.execute(text("""
                            INSERT INTO notifications
                                (user_id, type, title, message, is_read, created_at)
                            SELECT u.id, 'fraud_alert',
                                'تنبيه: نمط نشاط مشبوه',
                                :msg, FALSE, NOW()
                              FROM company_users u
                             WHERE u.is_active = TRUE
                               AND u.role IN ('admin','superuser','system_admin')
                        """), {
                            "msg": f"تم رصد {len(rows_a)} نمط 'إنشاء+اعتماد سريع' و {len(rows_b)} حالة اعتماد ذاتي خلال 24 ساعة"
                        })
                    except Exception:
                        pass
                    logger.warning(
                        "[%s] fraud patterns detected: vendor_speedrun=%s self_approval=%s",
                        db_name, len(rows_a), len(rows_b),
                    )
        except Exception as e:
            logger.error("detect_suspicious_temporal_patterns failed for %s: %s", db_name, e)


# ── T10.1 P1 #80 — FSM SLA breach detection ─────────────────────────────────
def check_fsm_sla_breaches():
    """Notify FSM owners when service-request SLA timers cross thresholds.

    Two checks run for non-completed/non-cancelled service_requests:
      * **response breach**: ``response_due_at < NOW()`` and
        ``first_response_at IS NULL``.
      * **resolution breach**: ``resolution_due_at < NOW()`` and
        ``status NOT IN ('completed','cancelled')``.

    Each breach flips the corresponding ``sla_breach_*`` flag once, then
    fires a single notification. Warning notifications also fire when the
    SLA window has < ``fsm_sla_warn_minutes`` (default 30) remaining and
    ``sla_warned_at`` is NULL.
    """
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                # Skip tenants without the SLA columns yet.
                has_cols = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns
                     WHERE table_name='service_requests'
                       AND column_name='response_due_at' LIMIT 1
                """)).fetchone()
                if not has_cols:
                    continue

                try:
                    val = conn.execute(text(
                        "SELECT setting_value FROM company_settings "
                        "WHERE setting_key='fsm_sla_warn_minutes'"
                    )).scalar()
                    warn_min = int(val) if val else 30
                except Exception:
                    warn_min = 30

                # Response breaches (newly crossed).
                resp_rows = conn.execute(text("""
                    UPDATE service_requests
                       SET sla_breach_response = TRUE,
                           updated_at = NOW()
                     WHERE COALESCE(is_deleted,FALSE) = FALSE
                       AND status NOT IN ('completed','cancelled')
                       AND first_response_at IS NULL
                       AND response_due_at < NOW()
                       AND COALESCE(sla_breach_response,FALSE) = FALSE
                 RETURNING id, assigned_to, title
                """)).fetchall()

                # Resolution breaches.
                resol_rows = conn.execute(text("""
                    UPDATE service_requests
                       SET sla_breach_resolution = TRUE,
                           updated_at = NOW()
                     WHERE COALESCE(is_deleted,FALSE) = FALSE
                       AND status NOT IN ('completed','cancelled')
                       AND resolution_due_at < NOW()
                       AND COALESCE(sla_breach_resolution,FALSE) = FALSE
                 RETURNING id, assigned_to, title
                """)).fetchall()

                # Approaching-deadline warnings.
                warn_rows = conn.execute(text("""
                    UPDATE service_requests
                       SET sla_warned_at = NOW()
                     WHERE COALESCE(is_deleted,FALSE) = FALSE
                       AND status NOT IN ('completed','cancelled')
                       AND sla_warned_at IS NULL
                       AND (
                           (first_response_at IS NULL
                              AND response_due_at BETWEEN NOW()
                                                  AND NOW() + make_interval(mins => :w))
                           OR
                           resolution_due_at BETWEEN NOW()
                                              AND NOW() + make_interval(mins => :w)
                       )
                 RETURNING id, assigned_to, title
                """), {"w": warn_min}).fetchall()

                def _notify(rows, kind: str, title: str):
                    for r in rows:
                        if not r.assigned_to:
                            continue
                        try:
                            conn.execute(text("""
                                INSERT INTO notifications
                                    (user_id, type, title, message, is_read, created_at)
                                VALUES (:uid, :tp, :ttl, :msg, FALSE, NOW())
                            """), {
                                "uid": r.assigned_to,
                                "tp": f"fsm_sla_{kind}",
                                "ttl": title,
                                "msg": f"#{r.id} — {r.title or ''}",
                            })
                        except Exception:
                            pass

                _notify(resp_rows,  "response_breach",   "خرق SLA — وقت الاستجابة")
                _notify(resol_rows, "resolution_breach", "خرق SLA — وقت الحل")
                _notify(warn_rows,  "warn",              "اقتراب موعد SLA")
                if resp_rows or resol_rows or warn_rows:
                    logger.info(
                        "[%s] FSM SLA: response=%s resolution=%s warn=%s",
                        db_name, len(resp_rows), len(resol_rows), len(warn_rows),
                    )
        except Exception as e:
            logger.error("check_fsm_sla_breaches failed for %s: %s", db_name, e)


# ── T10.1 P1 #89 — Payment gateway retry worker ─────────────────────────────
def process_payment_gateway_retries():
    """Drain queued payment-gateway operations with exponential back-off.

    The gateway adapter (Stripe / Tap / PayTabs / etc.) writes to
    ``payment_gateway_retries`` when a transient error occurs. This worker
    picks rows with ``status='pending' AND next_attempt_at < NOW()``,
    invokes ``integrations.payments.dispatch.replay(row)`` if available,
    and either marks ``succeeded``/``failed``/``dead`` accordingly. Rows
    that exceed ``max_attempts`` move to ``dead``.
    """
    from database import _get_all_company_db_names
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.connect() as conn:
                has_tbl = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables
                     WHERE table_name='payment_gateway_retries' LIMIT 1
                """)).fetchone()
                if not has_tbl:
                    continue

                rows = conn.execute(text("""
                    SELECT id, gateway, operation, reference_type, reference_id,
                           request_payload, attempt_count, max_attempts
                      FROM payment_gateway_retries
                     WHERE status = 'pending'
                       AND next_attempt_at < NOW()
                     ORDER BY next_attempt_at ASC
                     LIMIT 50
                """)).fetchall()

            try:
                from integrations.payments import dispatch as _payment_dispatch
            except Exception:
                _payment_dispatch = None

            for r in rows:
                with eng.begin() as conn:
                    success = False
                    err: Optional[str] = None
                    try:
                        if _payment_dispatch and hasattr(_payment_dispatch, "replay"):
                            _payment_dispatch.replay(
                                gateway=r.gateway,
                                operation=r.operation,
                                payload=r.request_payload,
                                reference_type=r.reference_type,
                                reference_id=r.reference_id,
                            )
                            success = True
                        else:
                            err = "no payments dispatch.replay implementation"
                    except Exception as e:
                        err = str(e)[:500]

                    if success:
                        conn.execute(text("""
                            UPDATE payment_gateway_retries
                               SET status='succeeded', updated_at=NOW(),
                                   attempt_count = attempt_count + 1
                             WHERE id = :id
                        """), {"id": r.id})
                    else:
                        new_attempt = (r.attempt_count or 0) + 1
                        is_dead = new_attempt >= (r.max_attempts or 5)
                        # Exponential back-off: 1, 2, 4, 8, 16 ... minutes.
                        backoff_min = min(2 ** (new_attempt - 1), 60)
                        conn.execute(text("""
                            UPDATE payment_gateway_retries
                               SET status = CASE WHEN :dead THEN 'dead' ELSE 'pending' END,
                                   attempt_count = :att,
                                   last_error = :err,
                                   next_attempt_at = NOW() + make_interval(mins => :bo),
                                   updated_at = NOW()
                             WHERE id = :id
                        """), {
                            "dead": is_dead,
                            "att": new_attempt,
                            "err": err,
                            "bo": backoff_min,
                            "id": r.id,
                        })
        except Exception as e:
            logger.error("process_payment_gateway_retries failed for %s: %s", db_name, e)


def extract_attachment_content():
    """T18 #96 \u2014 walk attachments missing extracted content and run the
    best-effort extractor over them.

    We process at most ``BATCH`` rows per tenant per run so a single huge
    bulk-upload doesn't starve the scheduler of other work.
    """
    from database import _get_all_company_db_names
    from services.content_extraction import extract_text
    BATCH = 50
    for db_name in _get_all_company_db_names():
        try:
            eng = _get_company_engine_for_db(db_name)
            with eng.begin() as conn:
                rows = conn.execute(text("""
                    SELECT id, file_path, mime_type, file_name
                    FROM attachments
                    WHERE content_text IS NULL
                      AND content_extracted_at IS NULL
                      AND content_extraction_error IS NULL
                    ORDER BY id
                    LIMIT :n
                """), {"n": BATCH}).fetchall()
                for r in rows:
                    try:
                        extracted = extract_text(r.file_path, r.mime_type, r.file_name)
                        if extracted:
                            conn.execute(text("""
                                UPDATE attachments
                                SET content_text = :t,
                                    content_extracted_at = NOW()
                                WHERE id = :id
                            """), {"t": extracted, "id": r.id})
                        else:
                            # Mark as attempted-but-empty so we don't retry forever.
                            conn.execute(text("""
                                UPDATE attachments
                                SET content_extracted_at = NOW(),
                                    content_extraction_error = 'unsupported_or_empty'
                                WHERE id = :id
                            """), {"id": r.id})
                    except Exception as e:
                        conn.execute(text("""
                            UPDATE attachments
                            SET content_extracted_at = NOW(),
                                content_extraction_error = :err
                            WHERE id = :id
                        """), {"err": str(e)[:200], "id": r.id})
        except Exception as e:
            logger.error("extract_attachment_content failed for %s: %s", db_name, e)


def start_scheduler():
    # Helper: register with execution tracking wrapper
    def _add(fn, trigger, job_id, **kw):
        scheduler.add_job(
            _wrap_job(fn, job_id), trigger, id=job_id,
            replace_existing=True, **kw,
        )

    _add(check_scheduled_reports,             'interval', 'scheduled_reports',      minutes=5)
    _add(check_subscription_billing,          'interval', 'subscription_billing',   hours=24)
    _add(refresh_analytics_materialized_views,'interval', 'analytics_mv_refresh',   minutes=15)
    _add(archive_old_audit_logs,              'interval', 'audit_archival',          hours=24)
    # T9.3 — monthly archival of inventory_transactions older than 7 years.
    # T10.2 #138: monthly cron jobs need a wider misfire grace window than
    # the default (120s) — if the host is briefly busy at midnight on the
    # 1st, a 2-minute window misses the entire month. Use 30 minutes.
    _add(archive_old_inventory_transactions,  'cron',     'inventory_archival',       day=1, hour=3, misfire_grace_time=1800)
    _add(retry_failed_notifications,          'interval', 'notification_retry',      minutes=1)
    _add(auto_fx_revaluation,                 'cron',     'fx_monthly_reval',        day=1, hour=2, misfire_grace_time=1800)
    _add(check_zatca_csid_expiry,             'interval', 'zatca_csid_expiry',       hours=12)
    # T4.6 — auto-activate due cheques
    _add(activate_due_cheques,                'cron',     'activate_due_cheques',    hour=6, minute=0)
    # T4.7 — recurring journal templates
    _add(run_due_recurring_templates,         'cron',     'recurring_templates',     hour=6, minute=30)
    # T4.8 — auto bank reconciliation
    _add(auto_reconcile_all_drafts,           'cron',     'auto_reconcile',          hour=7, minute=0)
    # T10.1 P1 #67 — monthly EOS provision snapshot (T10.2 #138: wider grace).
    _add(run_eos_provision_snapshot,          'cron',     'eos_provision_snapshot', day=1, hour=3, minute=30, misfire_grace_time=1800)
    # T10.1 P1 #57/#58 — daily DMS soft-delete purge
    _add(purge_soft_deleted_documents,        'cron',     'dms_purge_soft_deleted', hour=4, minute=0)
    # T10.1 P1 #110g — daily treasury↔GL discrepancy scan
    _add(reconcile_treasury_balances,         'cron',     'treasury_gl_recon',       hour=5, minute=0)
    # T10.1 P1 #41 — CRM follow-up alerts (stale + expected close)
    _add(crm_followup_alerts,                 'cron',     'crm_followup_alerts',     hour=8, minute=0)
    # T10.1 P1 #110c — temporal correlation fraud detection (every 30 minutes)
    _add(detect_suspicious_temporal_patterns, 'interval', 'fraud_temporal_corr',     minutes=30)
    # T10.1 P1 #80 — FSM SLA breach detection (every 15 minutes)
    _add(check_fsm_sla_breaches,              'interval', 'fsm_sla_check',           minutes=15)
    # T10.1 P1 #89 — payment gateway retry worker (every 2 minutes)
    _add(process_payment_gateway_retries,     'interval', 'payment_retry_worker',    minutes=2)
    # T18 P1 #96 — attachment full-text extraction (every 10 minutes)
    _add(extract_attachment_content,          'interval', 'attachment_text_extract', minutes=10)
    # T4.4 — low stock alerts
    _add(check_low_stock_alerts,              'interval', 'low_stock_alerts',        minutes=30)
    # T4.5 — POS offline inbox worker
    _add(process_pos_offline_inbox,           'interval', 'pos_offline_worker',      minutes=5)
    # T4.3 — smart alert evaluation
    _add(evaluate_smart_alerts,              'interval', 'smart_alerts',             minutes=int(
        os.environ.get("SMART_ALERT_INTERVAL_MINUTES", "15")))

    # T5.4 — payment + SMS retry queues (exponential backoff → DLQ)
    try:
        from services.integration_retry_service import (
            process_payment_retries_all_tenants,
            process_sms_retries_all_tenants,
        )
        _add(process_payment_retries_all_tenants, 'interval', 'payment_retry_queue', minutes=1)
        _add(process_sms_retries_all_tenants,     'interval', 'sms_retry_queue',     minutes=1)
    except ImportError:
        logger.warning("integration_retry_service unavailable; skipping retry jobs")

    # Feature 022 — audit outbox flush worker (every 15 seconds)
    try:
        from services.audit_outbox_worker import flush as _flush_audit_outbox
        _add(_flush_audit_outbox, 'interval', 'audit_outbox_flush', seconds=15)
        logger.info("audit.outbox.worker: registered (interval=15s)")
    except ImportError:
        logger.warning("audit_outbox_worker unavailable; skipping")

    # Feature 022 — ghost-employee detection (daily at 3:00 AM)
    try:
        from services.ghost_employee_rule import run_ghost_employee_check
        _add(run_ghost_employee_check, 'cron', 'ghost_employee_check', hour=3, minute=0)
        logger.info("ghost_employee_check: registered (daily 03:00)")
    except ImportError:
        logger.warning("ghost_employee_rule unavailable; skipping")

    # Feature 022 — auto-approve expenses below threshold (daily at 7:30 AM)
    try:
        from services.expense_auto_approve import run_auto_approve
        _add(run_auto_approve, 'cron', 'expense_auto_approve', hour=7, minute=30)
        logger.info("expense_auto_approve: registered (daily 07:30)")
    except ImportError:
        logger.warning("expense_auto_approve unavailable; skipping")

    scheduler.start()
    logger.info("🚀 Scheduler started (jobstore=%s, tz=%s).",
                "SQLAlchemy" if _SCHEDULER_DB_URL else "Memory", _SCHEDULER_TZ)
