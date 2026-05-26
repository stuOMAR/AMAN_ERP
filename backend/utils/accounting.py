from sqlalchemy import text
from typing import Optional, List, Dict
from fastapi import HTTPException
from decimal import Decimal, ROUND_HALF_UP
import logging

from utils.i18n import http_error

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')

# ── Precision constants for tax calculations ─────────────────────────────
#: Use for all tax rate and tax amount calculations (2 decimal places)
TAX_PRECISION = Decimal("0.01")
#: Use for storage of monetary amounts (4 decimal places)
AMOUNT_PRECISION = Decimal("0.0001")

def _to_decimal(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    if v is None:
        return Decimal('0')
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def prepare_je_lines(je_lines: List[Dict], source: str = "auto", request=None) -> List[Dict]:
    """
    Routing-layer JE preparation + validation.

    T3.4 (audit #19): single source of truth for JE balance/sign checks
    lives in `services.gl_service.validate_je_lines` (pure). This wrapper
    adds the higher-level concerns the routers need:

      1. Reject None account_id (caller must resolve mappings before this).
      2. Drop zero lines (helpers sometimes append a placeholder line).
      3. Require at least 2 non-zero lines for a valid double-entry.
      4. Delegate balance / sign / non-negative invariants to gl_service.

    Returns the filtered list of valid lines. Raises HTTPException on
    violation (Arabic message).

    NOTE: legacy callers may still import this as ``validate_je_lines``
    via the compatibility alias below. New code must use
    ``prepare_je_lines`` (or call ``gl_service.validate_je_lines`` directly
    when only the pure totals are needed).
    """
    # 1. None-account guard
    missing = [line.get("description", "unknown") for line in je_lines if line.get("account_id") is None]
    if missing:
        logger.error(f"JE validation ({source}): Missing account mappings for: {missing}")
        raise HTTPException(**http_error(400, "account_mapping.missing", request))

    # 2. Filter zero lines
    valid = [line for line in je_lines if line.get("debit", 0) > 0 or line.get("credit", 0) > 0]

    # 3. At least 2 non-zero lines
    if len(valid) < 2:
        raise HTTPException(**http_error(400, "journal_entry_minimum_two_lines", request))

    # 4. Delegate balance / sign / non-negative checks
    from services.gl_service import validate_je_lines as _validate
    try:
        _validate(valid)
    except HTTPException as exc:
        # Augment error context with the source tag for log triage.
        logger.error(f"JE validation ({source}): {exc.detail}")
        raise

    return valid


# Backward-compatibility alias — kept so existing imports keep working
# until callers migrate. New code should import `prepare_je_lines`
# instead. There is now only one balance-checking implementation
# (services.gl_service.validate_je_lines).
validate_je_lines = prepare_je_lines


def generate_sequential_number(db, prefix: str, table: str, column: str, branch_id: Optional[int] = None) -> str:
    """
    Generate a sequential document number.
    Example: prefix='SINV-2026' → 'SINV-2026-00001'
    If branch_id is supplied, the visible prefix becomes branch-scoped:
    prefix='SINV-2026', branch_id=1 → 'SINV-2026-B1-00001'.

    Uses MAX extraction of trailing digits from existing numbers to determine next.
    table and column are developer-defined constants (not user input).

    Concurrency: uses a PostgreSQL transaction-scoped advisory lock keyed by
    (table, column, prefix, branch_id) to serialize concurrent callers without violating
    PG's restriction against FOR UPDATE on aggregate queries.
    """
    # SEC-003: Validate table/column identifiers to prevent SQL injection
    from utils.sql_safety import validate_sql_identifier
    validate_sql_identifier(table, "table")
    validate_sql_identifier(column, "column")

    effective_prefix = f"{prefix}-B{int(branch_id)}" if branch_id is not None else prefix

    # Serialize concurrent number generation for this (table.column, prefix, branch)
    # pair. pg_advisory_xact_lock releases automatically at COMMIT/ROLLBACK.
    lock_key = f"{table}.{column}:{effective_prefix}:branch:{branch_id if branch_id is not None else 'global'}"
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": lock_key},
    )

    branch_clause = ""
    params = {"pattern": f"{effective_prefix}-%"}
    if branch_id is not None:
        branch_clause = " AND branch_id = :branch_id"
        params["branch_id"] = int(branch_id)

    result = db.execute(text( # noqa
                f"""
        SELECT MAX(CAST(SUBSTRING({column} FROM '[0-9]+$') AS INTEGER))
        FROM {table} WHERE {column} LIKE :pattern{branch_clause}
    """), params).scalar()
    next_num = (result or 0) + 1
    return f"{effective_prefix}-{str(next_num).zfill(5)}"


def get_mapped_account_id(db, mapping_key: str) -> Optional[int]:
    """
    Retrieves the account ID mapped to a specific system role from company_settings.
    """
    result = db.execute(
        text("SELECT setting_value FROM company_settings WHERE setting_key = :key"),
        {"key": mapping_key}
    ).fetchone()

    if not result or not result[0]:
        return None

    try:
        return int(result[0])
    except (TypeError, ValueError):
        logger.error("Invalid mapped account id for key '%s': %s", mapping_key, result[0])
        return None

def get_account_id_legacy(db, account_code: str) -> Optional[int]:
    """
    Legacy helper to find an account ID by its code. 
    Use get_mapped_account_id instead wherever possible.
    """
    result = db.execute(text("SELECT id FROM accounts WHERE account_code = :code"), {"code": account_code}).fetchone()
    return result[0] if result else None

def get_base_currency(db) -> str:
    """
    Resolve the company's base currency dynamically.
    Checks currencies table first, then company_settings, falls back to 'SAR'
    (T10.2 #124: aligned with default COA seed; was 'SYP' historically).
    """
    row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
    if not row:
        row = db.execute(text("SELECT setting_value AS code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
    return row[0] if row else "SAR"

def update_account_balance(db, account_id: int, debit_base, credit_base, debit_curr=0, credit_curr=0, currency: str = None):
    """
    Updates both the base balance and the foreign currency balance of an account.
    Accepts float or Decimal values — internally uses Decimal for precision.
    """
    # Convert all inputs to Decimal for precision
    debit_base = _to_decimal(debit_base)
    credit_base = _to_decimal(credit_base)
    debit_curr = _to_decimal(debit_curr)
    credit_curr = _to_decimal(credit_curr)

    # 1. Get account type and currency
    acct_data = db.execute(text(
        "SELECT account_type, currency FROM accounts WHERE id = :id FOR UPDATE"
    ), {"id": account_id}).fetchone()
    if not acct_data:
        return
        
    acct_type = acct_data.account_type
    acct_currency = acct_data.currency
    
    # 2. Calculate balance changes using Decimal
    if acct_type in ['asset', 'expense']:
        change_base = (debit_base - credit_base).quantize(_D2, ROUND_HALF_UP)
        change_curr = ((debit_curr - credit_curr).quantize(_D2, ROUND_HALF_UP)
                       if (currency and currency == acct_currency) else Decimal('0'))
    else:
        change_base = (credit_base - debit_base).quantize(_D2, ROUND_HALF_UP)
        change_curr = ((credit_curr - debit_curr).quantize(_D2, ROUND_HALF_UP)
                       if (currency and currency == acct_currency) else Decimal('0'))
        
    # 3. Always update base balance
    db.execute(text("""
        UPDATE accounts SET balance = balance + :change WHERE id = :id
    """), {"change": change_base, "id": account_id})
    
    # 4. Update foreign balance only if currency matches
    if acct_currency and change_curr != 0:
        db.execute(text("""
            UPDATE accounts SET balance_currency = balance_currency + :change WHERE id = :id
        """), {"change": change_curr, "id": account_id})


def compute_line_amounts(
    quantity, unit_price, tax_rate=0, discount=0, discount_is_percent=True
) -> Dict[str, Decimal]:
    """
    Compute amounts for a single invoice/contract line using Decimal arithmetic.
    Returns dict with: subtotal, discount_amount, taxable, tax_amount, line_total.
    
    discount_is_percent: if True, discount is a percentage (0-100).
                         if False, discount is a fixed amount.
    """
    qty = _to_decimal(quantity)
    price = _to_decimal(unit_price)
    tax_r = _to_decimal(tax_rate)
    disc = _to_decimal(discount)

    subtotal = (qty * price).quantize(_D2, ROUND_HALF_UP)

    if discount_is_percent:
        discount_amount = (subtotal * disc / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
    else:
        discount_amount = disc.quantize(_D2, ROUND_HALF_UP)

    # Discount cannot exceed subtotal
    if discount_amount > subtotal:
        discount_amount = subtotal

    taxable = subtotal - discount_amount
    tax_amount = (taxable * tax_r / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
    line_total = (taxable + tax_amount).quantize(_D2, ROUND_HALF_UP)

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "taxable": taxable,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }


def compute_invoice_totals(
    lines: List[Dict], header_discount_pct=0, markup_amount=0, discount_is_percent=True
) -> Dict[str, Decimal]:
    """
    Aggregate line-level amounts into invoice totals using Decimal arithmetic.
    Each line dict must have: quantity, unit_price, tax_rate; optional: discount.
    header_discount_pct reduces tax proportionally (ZATCA-compliant).
    discount_is_percent: if True, line discount is percentage; if False, fixed amount.
    """
    subtotal = Decimal("0")
    total_discount = Decimal("0")
    total_tax = Decimal("0")

    for ln in lines:
        la = compute_line_amounts(
            ln.get("quantity", 0),
            ln.get("unit_price", 0),
            ln.get("tax_rate", 0),
            ln.get("discount", 0),
            discount_is_percent=discount_is_percent,
        )
        subtotal += la["subtotal"]
        total_discount += la["discount_amount"]
        total_tax += la["tax_amount"]

    # Header-level discount (proportionally reduces tax — ZATCA rule)
    hdr_disc = _to_decimal(header_discount_pct)
    if hdr_disc > 0:
        hdr_disc_amt = (subtotal * hdr_disc / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
        total_discount += hdr_disc_amt
        tax_reduction = (total_tax * hdr_disc / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
        total_tax -= tax_reduction

    net = subtotal - total_discount
    markup = _to_decimal(markup_amount).quantize(_D2, ROUND_HALF_UP)
    grand_total = (net + total_tax + markup).quantize(_D2, ROUND_HALF_UP)

    return {
        "subtotal": subtotal.quantize(_D2, ROUND_HALF_UP),
        "total_discount": total_discount.quantize(_D2, ROUND_HALF_UP),
        "total_tax": total_tax.quantize(_D2, ROUND_HALF_UP),
        "grand_total": grand_total,
    }
