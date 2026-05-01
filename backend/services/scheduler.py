import logging
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from datetime import datetime, timedelta, date

from database import engine as system_engine, _get_engine
from utils.email import send_email
from utils.exports import generate_pdf, generate_excel
from routers.reports import _get_profit_loss_data, _get_balance_sheet_data

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


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
            
            with engine.connect() as conn:
                reports = conn.execute(text("SELECT * FROM scheduled_reports WHERE is_active = TRUE AND (next_run_at <= NOW() OR next_run_at IS NULL)")).fetchall()
                
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
                for mv_name in MATERIALIZED_VIEWS:
                    try:
                        # Check if the materialized view exists before refreshing
                        exists = conn.execute(
                            text("SELECT EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = :name)"),
                            {"name": mv_name}
                        ).scalar()
                        if exists:
                            conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))
                            conn.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to refresh {mv_name} in {db_name}: {e}")

                logger.info(f"✅ Refreshed materialized views in {db_name}")
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
    """T018: Archive audit log entries older than 1 year, delete entries older than 7 years."""
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

                # Delete entries older than 7 years
                conn.execute(text("SET LOCAL audit_logs.allow_admin_op = 'retention'"))
                deleted = conn.execute(text(
                    "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '7 years'"
                ))
                conn.commit()

                if archived.rowcount > 0 or deleted.rowcount > 0:
                    logger.info(f"Audit archival in {db_name}: archived={archived.rowcount}, deleted={deleted.rowcount}")
        except Exception as e:
            logger.error(f"Error archiving audit logs in {db_name}: {e}")


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


def start_scheduler():
    scheduler.add_job(check_scheduled_reports, 'interval', minutes=5, id='scheduled_reports',
                      max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(check_subscription_billing, 'interval', hours=24, id='subscription_billing',
                      max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(refresh_analytics_materialized_views, 'interval', minutes=15, id='analytics_mv_refresh',
                      max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(archive_old_audit_logs, 'interval', hours=24, id='audit_archival',
                      max_instances=1, coalesce=True, misfire_grace_time=60)  # Daily
    scheduler.add_job(retry_failed_notifications, 'interval', minutes=1, id='notification_retry',
                      max_instances=1, coalesce=True, misfire_grace_time=60)  # Every minute
    scheduler.add_job(auto_fx_revaluation, 'cron', day=1, hour=2, id='fx_monthly_reval',
                      max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(check_zatca_csid_expiry, 'interval', hours=12, id='zatca_csid_expiry',
                      max_instances=1, coalesce=True, misfire_grace_time=600)
    scheduler.start()
    logger.info("🚀 Scheduler started.")
