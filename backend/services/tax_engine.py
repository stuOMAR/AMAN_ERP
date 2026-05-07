"""
Tax Engine — AMAN ERP
═════════════════════
Central tax resolution service for multi-branch, multi-country operations.

Provides:
  • Branch-aware tax lookup (checks exemptions, custom rates, country defaults)
  • Immutable tax rate updates (append-only with history audit trail)
  • Line-level tax resolution for invoices, orders, POS, contracts, etc.

Usage::

    from services.tax_engine import resolve_line_tax, get_active_tax_for_branch

    # When creating an invoice line:
    tax = resolve_line_tax(branch_id=5, product_id=42, db=conn, customer_id=10)
    # → { "tax_rate_id": 12, "tax_rate": Decimal("15.00"), "tax_name": "VAT 15%" }
"""

from __future__ import annotations

import json
import logging
from datetime import date as _date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import text

from utils.i18n import http_error

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. get_active_tax_for_branch
# ─────────────────────────────────────────────────────────────────────────────

def get_active_tax_for_branch(
    branch_id: int,
    db,
    as_of_date: _date | None = None,
) -> Dict[str, Any]:
    """Fetch the effective tax rate for a specific branch.

    Resolution order:
      1. Look up the branch and its ``country_code``.
      2. Check ``branch_tax_settings`` for a matching ``tax_regime``:
         - If ``is_exempt = TRUE`` → return a zero-rate exempt record.
         - If ``custom_rate`` is set → return that custom rate.
      3. Otherwise fall back to :func:`get_active_tax_for_country`.

    Args:
        branch_id: The branch to resolve tax for.
        db: An open SQLAlchemy connection.
        as_of_date: The date to evaluate (defaults to today).

    Returns:
        ``{ id, rate, name, country_code }``

    Raises:
        HTTPException 404 if the branch is not found or no tax exists for
        the branch's country.
    """
    if as_of_date is None:
        as_of_date = _date.today()

    # ── Step 1: fetch branch ──────────────────────────────────────────────
    branch = db.execute(
        text("SELECT id, branch_name, country_code FROM branches WHERE id = :id"),
        {"id": branch_id},
    ).fetchone()

    if not branch:
        raise HTTPException(**http_error(404, "branch_not_found"))

    branch_cc = (branch.country_code or "SA").upper()

    # ── Step 2: check branch_tax_settings for exemptions / custom rates ───
    setting = db.execute(
        text("""
            SELECT bts.custom_rate,
                   bts.is_exempt,
                   bts.exemption_reason,
                   tr.default_rate,
                   tr.name_ar,
                   tr.name_en
            FROM tax_regimes tr
            LEFT JOIN branch_tax_settings bts
                ON tr.id = bts.tax_regime_id AND bts.branch_id = :bid
            WHERE tr.country_code = :cc
              AND tr.tax_type = 'vat'
              AND tr.is_active = TRUE
            ORDER BY tr.is_required DESC
            LIMIT 1
        """),
        {"bid": branch_id, "cc": branch_cc},
    ).fetchone()

    if setting:
        if setting.is_exempt:
            logger.info(
                "Branch %s is tax-exempt: %s", branch_id, setting.exemption_reason
            )
            return {
                "id": None,
                "rate": Decimal("0"),
                "name": "Exempt",
                "country_code": branch_cc,
            }

        if setting.custom_rate is not None:
            return {
                "id": None,  # custom rate has no tax_rates.id
                "rate": Decimal(str(setting.custom_rate)),
                "name": setting.name_ar or setting.name_en or "Custom",
                "country_code": branch_cc,
            }

    # ── Step 3: fall back to country default ──────────────────────────────
    return get_active_tax_for_country(branch_cc, db, as_of_date)


# ─────────────────────────────────────────────────────────────────────────────
# 2. get_active_tax_for_country
# ─────────────────────────────────────────────────────────────────────────────

def get_active_tax_for_country(
    country_code: str,
    db,
    as_of_date: _date | None = None,
) -> Dict[str, Any]:
    """Fetch the default active tax rate for a country on a given date.

    Queries ``tax_rates`` for the record where:
      - ``country_code`` matches (or is NULL for global rates)
      - ``is_default = TRUE``
      - ``effective_from <= as_of_date``
      - ``effective_to IS NULL OR effective_to >= as_of_date``
      - ``is_active = TRUE``

    Results are ordered by ``effective_from DESC`` (most recent first) and
    limited to 1 row.

    Args:
        country_code: Two-letter country code (e.g. ``"SA"``, ``"AE"``).
        db: An open SQLAlchemy connection.
        as_of_date: The date to evaluate (defaults to today).

    Returns:
        ``{ id, rate, name }``

    Raises:
        HTTPException 404 if no active default tax exists for the country.
    """
    if as_of_date is None:
        as_of_date = _date.today()

    cc = country_code.upper()

    row = db.execute(
        text("""
            SELECT id, tax_name, tax_name_en, rate_value
            FROM tax_rates
            WHERE (country_code = :cc OR country_code IS NULL)
              AND is_default = TRUE
              AND is_active = TRUE
              AND effective_from <= :dt
              AND (effective_to IS NULL OR effective_to >= :dt)
            ORDER BY
                CASE WHEN country_code = :cc THEN 0 ELSE 1 END,
                effective_from DESC
            LIMIT 1
        """),
        {"cc": cc, "dt": as_of_date},
    ).fetchone()

    if not row:
        raise HTTPException(
            **http_error(
                404,
                "no_tax_found_for_country",
                detail=f"No active default tax found for country '{cc}' on {date}",
            )
        )

    return {
        "id": row.id,
        "rate": Decimal(str(row.rate_value)),
        "name": row.tax_name or row.tax_name_en,
        "country_code": cc,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. update_tax_rate
# ─────────────────────────────────────────────────────────────────────────────

def update_tax_rate(
    tax_id: int,
    new_rate: Decimal,
    effective_from: _date | str,
    changed_by: int,
    reason: str,
    db,
) -> Dict[str, Any]:
    """Create a new tax rate version (append-only, immutable history).

    Instead of mutating the existing row (which would corrupt historical
    invoices), this function:

      1. Fetches the current record.
      2. Sets its ``effective_to = effective_from - 1 day``.
      3. Inserts a **new** record with the updated rate and ``effective_from``.
      4. Inserts an audit row into ``tax_rate_history``.

    Args:
        tax_id: The ``tax_rates.id`` to supersede.
        new_rate: The new tax rate percentage (e.g. ``Decimal("15")``).
        effective_from: The date the new rate takes effect.
        changed_by: The ``company_users.id`` performing the change.
        reason: A human-readable reason for the change.
        db: An open SQLAlchemy connection.

    Returns:
        The newly created tax rate record as a dict.

    Raises:
        HTTPException 404 if the tax record does not exist.
    """
    # Normalize effective_from to a date object
    if isinstance(effective_from, str):
        effective_from = _date.fromisoformat(effective_from)

    # ── Step 1: fetch current record ──────────────────────────────────────
    current = db.execute(
        text("""
            SELECT id, tax_code, tax_name, tax_name_en, rate_type,
                   rate_value, country_code, description,
                   effective_from, effective_to, is_default, is_active
            FROM tax_rates
            WHERE id = :id
        """),
        {"id": tax_id},
    ).fetchone()

    if not current:
        raise HTTPException(**http_error(404, "tax_rate_not_found"))

    old_rate = Decimal(str(current.rate_value))

    # ── Step 2: close the current record ──────────────────────────────────
    new_effective_to = effective_from - timedelta(days=1)

    db.execute(
        text("UPDATE tax_rates SET effective_to = :eto WHERE id = :id"),
        {"eto": new_effective_to, "id": tax_id},
    )

    # ── Step 3: insert the new version ────────────────────────────────────
    # Generate a unique tax_code for the new version (append timestamp suffix)
    import time
    new_tax_code = f"{current.tax_code}-{int(time.time())}" if current.tax_code else None

    result = db.execute(
        text("""
            INSERT INTO tax_rates (
                tax_code, tax_name, tax_name_en, rate_type, rate_value,
                country_code, description, effective_from, effective_to,
                is_default, is_active, legal_entity_id
            ) VALUES (
                :code, :name, :name_en, :rate_type, :rate_value,
                :cc, :desc, :eff_from, NULL,
                :is_default, TRUE, :legal_entity_id
            )
            RETURNING id
        """),
        {
            "code": new_tax_code, "name": current.tax_name, "name_en": current.tax_name_en,
            "rate_type": current.rate_type or "percentage", "rate_value": str(new_rate),
            "cc": current.country_code, "desc": current.description,
            "eff_from": effective_from, "is_default": current.is_default or False,
            "legal_entity_id": None,
        },
    )
    new_id = result.fetchone()[0]

    # ── Step 4: write audit trail ─────────────────────────────────────────
    db.execute(
        text("""
            INSERT INTO tax_rate_history (
                tax_rate_id, changed_by, old_rate, new_rate,
                old_name, new_name, old_country, new_country, reason
            ) VALUES (
                :tid, :cb, :old_r, :new_r,
                :old_n, :new_n, :old_c, :new_c, :reason
            )
        """),
        {
            "tid": tax_id,
            "cb": changed_by,
            "old_r": str(old_rate),
            "new_r": str(new_rate),
            "old_n": current.tax_name,
            "new_n": current.tax_name,
            "old_c": current.country_code,
            "new_c": current.country_code,
            "reason": reason,
        },
    )

    logger.info(
        "Tax rate %s updated: %s%% → %s%% (effective %s, reason: %s)",
        tax_id, old_rate, new_rate, effective_from, reason,
    )

    # ── Return the new record ─────────────────────────────────────────────
    new_record = db.execute(
        text("SELECT * FROM tax_rates WHERE id = :id"),
        {"id": new_id},
    ).fetchone()

    return dict(new_record._mapping)


# ─────────────────────────────────────────────────────────────────────────────
# 4. validate_tax_access
# ─────────────────────────────────────────────────────────────────────────────

def validate_tax_access(
    user_id: int,
    tax_id: int,
    db,
) -> None:
    """Verify that a user is allowed to modify a given tax rate.

    Rules:
      - If the tax has no ``country_code`` (global) → allow.
      - Otherwise, the tax's ``country_code`` must match the user's branch
        ``country_code``.

    Args:
        user_id: The ``company_users.id`` of the acting user.
        tax_id: The ``tax_rates.id`` being modified.
        db: An open SQLAlchemy connection.

    Raises:
        HTTPException 403 if the user's branch country does not match the
        tax record's country.
        HTTPException 404 if the tax record or user branch is not found.
    """
    # ── fetch tax record ──────────────────────────────────────────────────
    tax = db.execute(
        text("SELECT id, country_code FROM tax_rates WHERE id = :id"),
        {"id": tax_id},
    ).fetchone()

    if not tax:
        raise HTTPException(**http_error(404, "tax_rate_not_found"))

    # global taxes (no country_code) are accessible to everyone
    if not tax.country_code:
        return

    # ── fetch user's branch country ───────────────────────────────────────
    user_branch = db.execute(
        text("""
            SELECT b.country_code
            FROM company_users cu
            JOIN user_branches ub ON cu.id = ub.user_id
            JOIN branches b ON ub.branch_id = b.id
            WHERE cu.id = :uid
            ORDER BY b.is_default DESC
            LIMIT 1
        """),
        {"uid": user_id},
    ).fetchone()

    if not user_branch:
        raise HTTPException(**http_error(404, "user_branch_not_found"))

    user_cc = (user_branch.country_code or "SA").upper()
    tax_cc = tax.country_code.upper()

    if user_cc != tax_cc:
        raise HTTPException(
            **http_error(
                403,
                "cross_country_tax_access",
                detail=f"Cannot modify tax for country '{tax_cc}' from a '{user_cc}' branch",
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. resolve_line_tax
# ─────────────────────────────────────────────────────────────────────────────

def resolve_line_tax(
    branch_id: int,
    product_id: int,
    db,
    as_of_date: _date | None = None,
    customer_id: int | None = None,
) -> Dict[str, Any]:
    """Resolve the tax rate to apply to a document line.

    This is the **main entry point** called when creating any invoice line,
    order line, POS line, contract item, etc.

    Resolution order:
      0. If ``customer_id`` is provided and the customer is tax-exempt
         → return zero rate immediately.
      1. If the product is exempt or not taxable → return zero rate.
      2. If the product has ``tax_rate_id`` set → use that tax directly.
      3. Otherwise → call :func:`get_active_tax_for_branch`.

    Args:
        branch_id: The branch creating the document.
        product_id: The product on the line.
        db: An open SQLAlchemy connection.
        as_of_date: The document date (defaults to today).
        customer_id: Optional customer/parties ID for exemption check.

    Returns:
        ``{ tax_rate_id, tax_rate, tax_name }`` — ready to save to any line table.

    Raises:
        HTTPException 404 if no tax can be resolved.
    """
    if as_of_date is None:
        as_of_date = _date.today()

    # ── Step 0: check customer exemption ──────────────────────────────────
    if customer_id:
        customer = db.execute(
            text("""
                SELECT p.tax_exempt
                FROM parties p
                WHERE p.id = :cid
            """),
            {"cid": customer_id},
        ).fetchone()

        if customer and customer.tax_exempt:
            return {
                "tax_rate_id": None,
                "tax_rate": Decimal("0"),
                "tax_name": "Customer Exempt",
            }

    # ── Step 1: check product tax status ─────────────────────────────────
    product = db.execute(
        text("""
            SELECT p.tax_rate_id, p.tax_rate, p.is_taxable, p.is_exempt,
                   tr.rate_value, tr.tax_name, tr.is_active as tax_is_active
            FROM products p
            LEFT JOIN tax_rates tr ON p.tax_rate_id = tr.id
            WHERE p.id = :pid
        """),
        {"pid": product_id},
    ).fetchone()

    # Priority 2: Product is explicitly exempt
    if product and product.is_exempt:
        return {"tax_rate_id": None, "tax_rate": Decimal("0"), "tax_name": "Exempt"}

    # Priority 3: Product is not taxable
    if product and not product.is_taxable:
        return {"tax_rate_id": None, "tax_rate": Decimal("0"), "tax_name": "Non-Taxable"}

    # Priority 4: Product has a specific tax assigned
    if product and product.tax_rate_id and product.tax_is_active:
        return {
            "tax_rate_id": product.tax_rate_id,
            "tax_rate": Decimal(str(product.rate_value)),
            "tax_name": product.tax_name,
        }

    # ── Priority 5: fall back to branch-level resolution ──────────────────
    tax = get_active_tax_for_branch(branch_id, db, as_of_date)

    return {
        "tax_rate_id": tax.get("id"),
        "tax_rate": tax["rate"],
        "tax_name": tax.get("name"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. resolve_line_tax_group
# ─────────────────────────────────────────────────────────────────────────────

def resolve_line_tax_group(
    branch_id: int,
    product_id: int,
    db,
    as_of_date: _date | None = None,
    customer_id: int | None = None,
) -> List[Dict[str, Any]]:
    """Resolve **all** taxes to apply to a document line.

    If the product has a ``tax_group_id`` set, returns every active tax in
    that group.  Otherwise falls back to :func:`resolve_line_tax` wrapped
    in a single-item list.

    Args:
        branch_id: The branch creating the document.
        product_id: The product on the line.
        db: An open SQLAlchemy connection.
        as_of_date: The document date (defaults to today).
        customer_id: Optional customer/parties ID for exemption check.

    Returns:
        A list of ``{ tax_rate_id, tax_rate, tax_name, tax_code }`` dicts,
        one per applicable tax.  May be a single item for simple products.
    """
    if as_of_date is None:
        as_of_date = _date.today()

    # ── Step 0: check customer exemption (same as resolve_line_tax) ─────
    if customer_id:
        customer = db.execute(
            text("""
                SELECT p.tax_exempt
                FROM parties p
                WHERE p.id = :cid
            """),
            {"cid": customer_id},
        ).fetchone()

        if customer and customer.tax_exempt:
            return [{
                "tax_rate_id": None,
                "tax_rate": Decimal("0"),
                "tax_name": "Customer Exempt",
                "tax_code": None,
            }]

    # ── Step 1: check product tax status ────────────────────────────────
    product = db.execute(
        text("""
            SELECT p.tax_rate_id, p.tax_rate, p.is_taxable, p.is_exempt,
                   p.tax_group_id,
                   tr.rate_value, tr.tax_name, tr.is_active as tax_is_active
            FROM products p
            LEFT JOIN tax_rates tr ON p.tax_rate_id = tr.id
            WHERE p.id = :pid
        """),
        {"pid": product_id},
    ).fetchone()

    # Product explicitly exempt → zero
    if product and product.is_exempt:
        return [{"tax_rate_id": None, "tax_rate": Decimal("0"), "tax_name": "Exempt", "tax_code": None}]

    # Product not taxable → zero
    if product and not product.is_taxable:
        return [{"tax_rate_id": None, "tax_rate": Decimal("0"), "tax_name": "Non-Taxable", "tax_code": None}]

    # ── Step 2: multi-tax group ─────────────────────────────────────────
    if product and product.tax_group_id:
        group = db.execute(
            text("""
                SELECT id, group_code, group_name, tax_ids
                FROM tax_groups
                WHERE id = :gid AND is_active = TRUE
            """),
            {"gid": product.tax_group_id},
        ).fetchone()

        if group:
            raw_ids = group.tax_ids
            tax_ids = raw_ids if isinstance(raw_ids, list) else json.loads(raw_ids) if raw_ids else []
            taxes: List[Dict[str, Any]] = []
            for tid in tax_ids:
                tax_row = db.execute(
                    text("""
                        SELECT id, tax_code, tax_name, rate_value
                        FROM tax_rates
                        WHERE id = :tid AND is_active = TRUE
                    """),
                    {"tid": tid},
                ).fetchone()
                if tax_row:
                    taxes.append({
                        "tax_rate_id": tax_row.id,
                        "tax_rate": Decimal(str(tax_row.rate_value)),
                        "tax_name": tax_row.tax_name,
                        "tax_code": tax_row.tax_code,
                    })
            if taxes:
                return taxes

    # ── Step 3: single tax (product-specific) ───────────────────────────
    if product and product.tax_rate_id and product.tax_is_active:
        return [{
            "tax_rate_id": product.tax_rate_id,
            "tax_rate": Decimal(str(product.rate_value)),
            "tax_name": product.tax_name,
            "tax_code": None,
        }]

    # ── Step 4: branch / country default ────────────────────────────────
    tax = get_active_tax_for_branch(branch_id, db, as_of_date)
    return [{
        "tax_rate_id": tax.get("id"),
        "tax_rate": tax["rate"],
        "tax_name": tax.get("name"),
        "tax_code": None,
    }]
