"""
Utility: ensure required treasury GL accounts exist in the chart of accounts.
Auto-creates 1205, 2105, 1210, 2110 under correct parent accounts with audit logging.
"""
from sqlalchemy import text
from utils.accounting import get_base_currency
from utils.audit import log_activity
import logging

logger = logging.getLogger(__name__)

_TREASURY_GL_ACCOUNTS = [
    ("1205", "شيكات تحت التحصيل", "Checks Under Collection", "asset", "1200"),
    ("2105", "شيكات تحت الدفع", "Checks Payable", "liability", "2100"),
    ("1210", "أوراق قبض", "Notes Receivable", "asset", "1200"),
    ("2110", "أوراق دفع", "Notes Payable", "liability", "2100"),
]


def ensure_treasury_gl_accounts(db, *, user_id=None, username=None, commit: bool = True):
    """Idempotently create required treasury GL accounts.

    Returns a dict mapping account_code -> account_id for all four accounts.
    """
    base_currency = get_base_currency(db)
    result = {}

    for code, name_ar, name_en, acc_type, parent_code in _TREASURY_GL_ACCOUNTS:
        existing = db.execute(
            text("SELECT id FROM accounts WHERE account_code = :code"),
            {"code": code},
        ).fetchone()

        if existing:
            result[code] = existing.id
            continue

        parent = db.execute(
            text("SELECT id FROM accounts WHERE account_code = :code"),
            {"code": parent_code},
        ).fetchone()

        new_id = db.execute(
            text("""
                INSERT INTO accounts
                    (account_number, account_code, name, name_en,
                     account_type, parent_id, is_active, currency)
                VALUES
                    (:code, :code, :name, :name_en,
                     :type, :pid, TRUE, :currency)
                ON CONFLICT (account_number) DO UPDATE
                    SET name = EXCLUDED.name
                RETURNING id
            """),
            {
                "code": code,
                "name": name_ar,
                "name_en": name_en,
                "type": acc_type,
                "pid": parent.id if parent else None,
                "currency": base_currency,
            },
        ).scalar()

        if commit:
            db.commit()
        result[code] = new_id

        if user_id:
            try:
                log_activity(
                    db,
                    user_id=user_id,
                    username=username or "system",
                    action="gl_account.auto_create",
                    resource_type="account",
                    resource_id=str(new_id),
                    details={"account_code": code, "name": name_ar, "trigger": "ensure_treasury_gl_accounts"},
                )
            except Exception:
                logger.debug("Audit log for auto-created GL account %s skipped", code)

    return result
