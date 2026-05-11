"""
AMAN ERP — Intercompany Accounting Service
Handles reciprocal journal entries, entity group management, consolidation elimination,
and intercompany balance reporting.
"""

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from database import db_connection
from services.gl_service import create_journal_entry as gl_create_je
from utils.accounting import get_mapped_account_id

logger = logging.getLogger(__name__)

_D4 = Decimal("0.0001")


def _dec(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


# ---------------------------------------------------------------------------
# Entity Group CRUD
# ---------------------------------------------------------------------------

def get_entity_tree(company_id: str) -> List[Dict[str, Any]]:
    """Return all entity groups as a flat list (frontend builds the tree)."""
    with db_connection(company_id) as conn:
        rows = conn.execute(text(
            "SELECT id, name, parent_id, company_id, group_currency, consolidation_level, "
            "created_at, updated_at FROM entity_groups ORDER BY consolidation_level, name"
        )).fetchall()
        cols = ["id", "name", "parent_id", "company_id", "group_currency",
                "consolidation_level", "created_at", "updated_at"]
        return [dict(zip(cols, r)) for r in rows]


def create_entity_group(data: Dict[str, Any], company_id: str, user_id: int) -> Dict[str, Any]:
    """Create or update an entity group node."""
    with db_connection(company_id) as conn:
        # Compute consolidation_level from parent
        level = 0
        if data.get("parent_id"):
            parent = conn.execute(
                text("SELECT consolidation_level FROM entity_groups WHERE id = :pid"),
                {"pid": data["parent_id"]},
            ).fetchone()
            if parent:
                level = parent[0] + 1

        row = conn.execute(text("""
            INSERT INTO entity_groups (name, parent_id, company_id, group_currency, consolidation_level, created_by)
            VALUES (:name, :parent_id, :company_id, :currency, :level, :uid)
            RETURNING id, name, parent_id, company_id, group_currency, consolidation_level, created_at
        """), {
            "name": data["name"],
            "parent_id": data.get("parent_id"),
            "company_id": data.get("company_id", company_id),
            "currency": data.get("group_currency", "SAR"),
            "level": level,
            "uid": str(user_id),
        }).fetchone()
        conn.commit()
        cols = ["id", "name", "parent_id", "company_id", "group_currency",
                "consolidation_level", "created_at"]
        return dict(zip(cols, row))


def update_entity_group(
    entity_id: int,
    data: Dict[str, Any],
    company_id: str,
    user_id: int,
) -> Dict[str, Any]:
    """Update an entity group (name / parent / functional currency).

    Only fields explicitly present in ``data`` are touched, so callers can
    PATCH a single attribute (commonly ``group_currency`` to fix branches
    that were created with the SAR default).
    """
    fields: List[str] = []
    params: Dict[str, Any] = {"id": entity_id, "uid": str(user_id)}

    if "name" in data and data["name"] is not None:
        fields.append("name = :name")
        params["name"] = data["name"]
    if "parent_id" in data:
        fields.append("parent_id = :parent_id")
        params["parent_id"] = data["parent_id"]
    if "group_currency" in data and data["group_currency"]:
        fields.append("group_currency = :currency")
        params["currency"] = str(data["group_currency"]).upper()
    if not fields:
        raise ValueError("No updatable fields supplied")

    fields.append("updated_by = :uid")
    fields.append("updated_at = NOW()")

    with db_connection(company_id) as conn:
        # Recompute consolidation_level when parent changes.
        if "parent_id" in data:
            level = 0
            if data.get("parent_id"):
                parent = conn.execute(
                    text("SELECT consolidation_level FROM entity_groups WHERE id = :pid"),
                    {"pid": data["parent_id"]},
                ).fetchone()
                if parent:
                    level = parent[0] + 1
            fields.append("consolidation_level = :level")
            params["level"] = level

        row = conn.execute(text(
            f"""
            UPDATE entity_groups
               SET {', '.join(fields)}
             WHERE id = :id
             RETURNING id, name, parent_id, company_id, group_currency,
                       consolidation_level, created_at, updated_at
            """
        ), params).fetchone()
        if not row:
            raise ValueError("Entity not found")
        conn.commit()
        cols = ["id", "name", "parent_id", "company_id", "group_currency",
                "consolidation_level", "created_at", "updated_at"]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Intercompany Transaction — create with reciprocal JEs
# ---------------------------------------------------------------------------

def create_transaction(
    data: Dict[str, Any],
    company_id: str,
    user_id: int,
) -> Dict[str, Any]:
    """
    Create an intercompany transaction and post reciprocal journal entries.

    Tri-currency model
    ------------------
    Each entity has its own functional currency (``entity_groups.group_currency``).
    A transaction has its own *money* currency — ``transaction_currency`` /
    ``transaction_amount`` — which may differ from both functional currencies
    (e.g., 10 000 USD moved from an SAR branch to an EGP branch).

    For each leg we book:

      * ``debit`` / ``credit`` → company base currency (translated).
      * ``currency`` / ``amount_currency`` → leg's functional currency value.
      * ``txn_currency`` / ``txn_amount`` → the original transaction currency
        and amount, identical on both sides → enables exact reciprocal
        matching at consolidation regardless of FX differences.

    Back-compat: when ``transaction_currency`` / ``transaction_amount`` are
    omitted, the request is treated as legacy single-currency and the
    transaction currency is taken from ``source_currency``.
    """
    source_amount = _dec(data["source_amount"])
    source_currency_in = data.get("source_currency", "SAR")

    # The money actually being moved (defaults to the legacy single-currency
    # request shape).
    transaction_currency = (
        data.get("transaction_currency")
        or data.get("txn_currency")
        or source_currency_in
        or "SAR"
    ).upper()
    transaction_amount = _dec(
        data.get("transaction_amount")
        if data.get("transaction_amount") is not None
        else data.get("txn_amount") if data.get("txn_amount") is not None
        else source_amount
    )

    with db_connection(company_id) as conn:
        # Resolve entity names and branches
        src = conn.execute(
            text("SELECT id, name, company_id, branch_id, group_currency FROM entity_groups WHERE id = :id"),
            {"id": data["source_entity_id"]},
        ).fetchone()
        tgt = conn.execute(
            text("SELECT id, name, company_id, branch_id, group_currency FROM entity_groups WHERE id = :id"),
            {"id": data["target_entity_id"]},
        ).fetchone()
        if not src or not tgt:
            raise ValueError("Source or target entity not found")

        src_branch_id = src.branch_id
        tgt_branch_id = tgt.branch_id

        # Functional currency of each leg = entity.group_currency. Falls back
        # to the request's source_currency / SAR for legacy data without it.
        src_currency = (src.group_currency or source_currency_in or "SAR").upper()
        tgt_currency = (tgt.group_currency or "SAR").upper()

        # Pull rates against base. Base = currency flagged is_base
        # (defaults to SAR for legacy tenants).
        rate_rows = conn.execute(text(
            "SELECT code, current_rate, is_base FROM currencies WHERE is_active = TRUE"
        )).fetchall()
        rates: Dict[str, Decimal] = {}
        base_currency = "SAR"
        for r in rate_rows:
            rates[r.code.upper()] = _dec(r.current_rate)
            if r.is_base:
                base_currency = r.code.upper()
        rates.setdefault(base_currency, Decimal("1"))

        def _rate(code: str) -> Decimal:
            r = rates.get((code or "").upper())
            if not r or r <= 0:
                return Decimal("1")
            return r

        # Cross rates: from txn currency → each functional currency.
        # rate(X→Y) = rate(X→base) / rate(Y→base).
        rate_txn = _rate(transaction_currency)
        rate_src_func = _rate(src_currency)
        rate_tgt_func = _rate(tgt_currency)

        # Functional amounts each branch books.
        if transaction_currency == src_currency:
            source_func_amount = transaction_amount
        else:
            source_func_amount = (
                transaction_amount * rate_txn / rate_src_func
            ).quantize(_D4, ROUND_HALF_UP)

        if transaction_currency == tgt_currency:
            target_func_amount = transaction_amount
        else:
            target_func_amount = (
                transaction_amount * rate_txn / rate_tgt_func
            ).quantize(_D4, ROUND_HALF_UP)

        # gl_service expects ``exchange_rate`` to translate the *line*
        # currency (= functional currency) into the company base. Since
        # rates are stored vs base, that's just rate_func.
        src_line_rate = rate_src_func
        tgt_line_rate = rate_tgt_func

        # Final source/target amounts persisted on the IC txn record =
        # functional amounts each branch actually booked.
        target_amount = target_func_amount
        # Override legacy ``source_amount`` from request: it now represents
        # the source-functional booking value to keep one consistent meaning.
        source_amount = source_func_amount

        # Look up account mapping for this pair
        mapping = conn.execute(text("""
            SELECT source_account_id, target_account_id
            FROM intercompany_account_mappings
            WHERE source_entity_id = :sid AND target_entity_id = :tid
            LIMIT 1
        """), {"sid": data["source_entity_id"], "tid": data["target_entity_id"]}).fetchone()

        # Resolve IC accounts
        if mapping:
            ic_receivable_id, ic_payable_id = mapping[0], mapping[1]
        else:
            ic_receivable_id = get_mapped_account_id(conn, "ic_receivable_account_id")
            ic_payable_id = get_mapped_account_id(conn, "ic_payable_account_id")
        if not ic_receivable_id or not ic_payable_id:
            raise ValueError(
                "Intercompany receivable/payable accounts not configured. "
                "Set ic_receivable_account_id and ic_payable_account_id in company_settings "
                "or add an intercompany_account_mappings entry."
            )

        # Revenue and expense accounts from company settings
        revenue_acct = get_mapped_account_id(conn, "ic_revenue_account_id")
        expense_acct = get_mapped_account_id(conn, "ic_expense_account_id")
        if not revenue_acct:
            raise ValueError("ic_revenue_account_id not configured in company_settings")
        if not expense_acct:
            raise ValueError("ic_expense_account_id not configured in company_settings")

        if transaction_amount <= 0:
            raise ValueError("Intercompany amount must be positive")

        today = date.today().isoformat()
        ref = data.get("reference_document") or f"IC-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Both legs preserve the same (txn_currency, txn_amount) so that
        # consolidation/elimination matches them deterministically across
        # branches even when functional FX values differ.
        txn_tags = {
            "txn_currency": transaction_currency,
            "txn_amount": str(transaction_amount),
        }

        # --- Source entity JE: Dr IC Receivable, Cr Revenue (in src_func) ---
        source_je_id, _ = gl_create_je(
            db=conn,
            company_id=company_id,
            date=today,
            description=(
                f"معاملة بين الشركات — {src.name} → {tgt.name} "
                f"({transaction_amount} {transaction_currency})"
            ),
            lines=[
                {"account_id": ic_receivable_id, "debit": str(source_func_amount), "credit": "0",
                 "description": f"ذمم بين الشركات — {tgt.name}",
                 **txn_tags},
                {"account_id": revenue_acct, "debit": "0", "credit": str(source_func_amount),
                 "description": f"إيرادات بين الشركات — {tgt.name}",
                 **txn_tags},
            ],
            user_id=user_id,
            branch_id=src_branch_id,
            reference=ref,
            source="intercompany",
            currency=src_currency,
            exchange_rate=float(src_line_rate),
        )

        # --- Target entity JE: Dr Expense/COGS, Cr IC Payable (in tgt_func) ---
        target_je_id, _ = gl_create_je(
            db=conn,
            company_id=company_id,
            date=today,
            description=(
                f"معاملة بين الشركات — {tgt.name} ← {src.name} "
                f"({transaction_amount} {transaction_currency})"
            ),
            lines=[
                {"account_id": expense_acct, "debit": str(target_func_amount), "credit": "0",
                 "description": f"مصاريف بين الشركات — {src.name}",
                 **txn_tags},
                {"account_id": ic_payable_id, "debit": "0", "credit": str(target_func_amount),
                 "description": f"ذمم دائنة بين الشركات — {src.name}",
                 **txn_tags},
            ],
            user_id=user_id,
            branch_id=tgt_branch_id,
            reference=ref,
            source="intercompany",
            currency=tgt_currency,
            exchange_rate=float(tgt_line_rate),
        )

        # Insert the IC transaction record
        cross_rate = (
            (source_func_amount / target_func_amount)
            if target_func_amount and target_func_amount > 0 else Decimal("1")
        )

        row = conn.execute(text("""
            INSERT INTO intercompany_transactions_v2
                (source_entity_id, target_entity_id, transaction_type,
                 source_amount, source_currency, target_amount, target_currency,
                 transaction_currency, transaction_amount,
                 exchange_rate, source_journal_entry_id, target_journal_entry_id,
                 reference_document, created_by)
            VALUES
                (:src_eid, :tgt_eid, :txn_type,
                 :src_amt, :src_curr, :tgt_amt, :tgt_curr,
                 :txn_curr, :txn_amt,
                 :rate, :src_je, :tgt_je,
                 :ref, :uid)
            RETURNING id
        """), {
            "src_eid": data["source_entity_id"],
            "tgt_eid": data["target_entity_id"],
            "txn_type": data.get("transaction_type", "sale"),
            "src_amt": str(source_func_amount),
            "src_curr": src_currency,
            "tgt_amt": str(target_func_amount),
            "tgt_curr": tgt_currency,
            "txn_curr": transaction_currency,
            "txn_amt": str(transaction_amount),
            "rate": str(cross_rate.quantize(Decimal("0.00000001"), ROUND_HALF_UP)),
            "src_je": source_je_id,
            "tgt_je": target_je_id,
            "ref": ref,
            "uid": str(user_id),
        }).fetchone()
        conn.commit()

        return {
            "id": row[0],
            "source_journal_entry_id": source_je_id,
            "target_journal_entry_id": target_je_id,
            "reference_document": ref,
            "transaction_currency": transaction_currency,
            "transaction_amount": str(transaction_amount),
            "source_amount": str(source_func_amount),
            "source_currency": src_currency,
            "target_amount": str(target_func_amount),
            "target_currency": tgt_currency,
            "exchange_rate": str(cross_rate),
        }


# ---------------------------------------------------------------------------
# Query transactions
# ---------------------------------------------------------------------------

def get_transactions(
    company_id: str,
    status_filter: Optional[str] = None,
    entity_id: Optional[int] = None,
    branch_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    with db_connection(company_id) as conn:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}
        if status_filter:
            conditions.append("t.elimination_status = :status")
            params["status"] = status_filter
        if entity_id:
            conditions.append("(t.source_entity_id = :eid OR t.target_entity_id = :eid)")
            params["eid"] = entity_id
        if branch_id:
            conditions.append("(se.branch_id = :branch_id OR te.branch_id = :branch_id)")
            params["branch_id"] = branch_id

        rows = conn.execute(text(f"""
            SELECT t.*, se.name as source_entity_name, te.name as target_entity_name,
                   se.branch_id as source_branch_id, te.branch_id as target_branch_id
            FROM intercompany_transactions_v2 t
            LEFT JOIN entity_groups se ON se.id = t.source_entity_id
            LEFT JOIN entity_groups te ON te.id = t.target_entity_id
            WHERE {' AND '.join(conditions)}
            ORDER BY t.created_at DESC
        """), params).fetchall()
        return [dict(row._mapping) for row in rows]


def get_transaction_by_id(txn_id: int, company_id: str) -> Optional[Dict[str, Any]]:
    with db_connection(company_id) as conn:
        row = conn.execute(text("""
            SELECT t.*, se.name as source_entity_name, te.name as target_entity_name
            FROM intercompany_transactions_v2 t
            LEFT JOIN entity_groups se ON se.id = t.source_entity_id
            LEFT JOIN entity_groups te ON te.id = t.target_entity_id
            WHERE t.id = :id
        """), {"id": txn_id}).fetchone()
        if not row:
            return None
        return dict(row._mapping)


def process_transaction(txn_id: int, company_id: str, user_id: int) -> Dict[str, Any]:
    """Process/complete an intercompany transaction by updating its status."""
    with db_connection(company_id) as conn:
        # Verify transaction exists and is pending
        txn = conn.execute(text("""
            SELECT id, elimination_status FROM intercompany_transactions_v2
            WHERE id = :id
        """), {"id": txn_id}).fetchone()
        
        if not txn:
            raise ValueError("Transaction not found")
        
        if txn.elimination_status != 'pending':
            raise ValueError(f"Transaction is already {txn.elimination_status}, cannot process")
        
        # Update status to processed
        conn.execute(text("""
            UPDATE intercompany_transactions_v2
            SET elimination_status = 'processed', updated_by = :user_id, updated_at = NOW()
            WHERE id = :id
        """), {"id": txn_id, "user_id": user_id})
        
        conn.commit()
        
        return {"id": txn_id, "status": "processed", "message": i18n_message("intercompany_transaction_processed")}


# ---------------------------------------------------------------------------
# Consolidation — generate elimination JEs
# ---------------------------------------------------------------------------

def run_consolidation(
    entity_group_id: int,
    company_id: str,
    user_id: int,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Traverse the entity group hierarchy bottom-up and generate elimination
    journal entries for all pending intercompany transactions within the group.
    """
    with db_connection(company_id) as conn:
        # Get the entity group info
        group = conn.execute(
            text("SELECT id, name, group_currency FROM entity_groups WHERE id = :id"),
            {"id": entity_group_id},
        ).fetchone()
        if not group:
            raise ValueError("Entity group not found")
        group_id, group_name, group_currency = group

        # Get all entity IDs in this group (the group and its descendants)
        entity_ids = _get_descendant_ids(conn, entity_group_id)
        if not entity_ids:
            return {
                "entity_group_id": entity_group_id,
                "entity_group_name": group_name,
                "eliminations": [],
                "elimination_lines": [],
                "total_eliminated": Decimal("0"),
                "journal_entry_ids": [],
                "status": "no_transactions",
            }

        # Find pending IC transactions where both source and target are in this group
        placeholders = ", ".join(f":e{i}" for i in range(len(entity_ids)))
        params: Dict[str, Any] = {f"e{i}": eid for i, eid in enumerate(entity_ids)}

        date_filter = ""
        if as_of_date:
            date_filter = " AND t.created_at::date <= :cutoff"
            params["cutoff"] = as_of_date

        pending = conn.execute(text(f"""
            SELECT t.id, t.source_entity_id, t.target_entity_id,
                   t.source_amount, t.source_currency,
                   se.name as source_name, te.name as target_name
            FROM intercompany_transactions_v2 t
            JOIN entity_groups se ON se.id = t.source_entity_id
            JOIN entity_groups te ON te.id = t.target_entity_id
            WHERE t.elimination_status = 'pending'
              AND t.source_entity_id IN ({placeholders})
              AND t.target_entity_id IN ({placeholders})
              {date_filter}
            ORDER BY t.id
            FOR UPDATE OF t
        """), params).fetchall()

        if not pending:
            return {
                "entity_group_id": entity_group_id,
                "entity_group_name": group_name,
                "eliminations": [],
                "elimination_lines": [],
                "total_eliminated": Decimal("0"),
                "journal_entry_ids": [],
                "status": "no_pending",
            }

        # Generate elimination JEs
        eliminations = []
        je_ids = []
        total_eliminated = Decimal("0")

        # Find IC accounts for elimination — explicit settings required
        ic_receivable_id = get_mapped_account_id(conn, "ic_receivable_account_id")
        ic_payable_id = get_mapped_account_id(conn, "ic_payable_account_id")

        if not ic_receivable_id or not ic_payable_id:
            raise ValueError(
                "Intercompany receivable/payable accounts not configured. "
                "Set ic_receivable_account_id and ic_payable_account_id in company_settings."
            )

        today = (as_of_date or date.today().isoformat())

        for txn in pending:
            txn_id, src_eid, tgt_eid, src_amount, src_currency, src_name, tgt_name = txn
            amount = _dec(src_amount)

            # Elimination JE: Dr IC Payable, Cr IC Receivable (nets to zero)
            je_id, _ = gl_create_je(
                db=conn,
                company_id=company_id,
                date=today,
                description=f"استبعاد بين الشركات — {src_name} ↔ {tgt_name}",
                lines=[
                    {"account_id": ic_payable_id, "debit": str(amount), "credit": "0",
                     "description": f"استبعاد ذمم دائنة — {src_name}"},
                    {"account_id": ic_receivable_id, "debit": "0", "credit": str(amount),
                     "description": f"استبعاد ذمم مدينة — {tgt_name}"},
                ],
                user_id=user_id,
                reference=f"ELIM-{txn_id}",
                source="intercompany_elimination",
                source_id=txn_id,
                currency=src_currency,
            )
            je_ids.append(je_id)

            # Mark transaction as eliminated
            conn.execute(text("""
                UPDATE intercompany_transactions_v2
                SET elimination_status = 'eliminated',
                    elimination_journal_entry_id = :je_id,
                    updated_at = NOW()
                WHERE id = :tid
            """), {"je_id": je_id, "tid": txn_id})

            eliminations.append({
                "source_entity_id": src_eid,
                "source_entity_name": src_name,
                "target_entity_id": tgt_eid,
                "target_entity_name": tgt_name,
                "amount": amount,
                "currency": src_currency,
                "transaction_id": txn_id,
                "elimination_je_id": je_id,
            })
            total_eliminated += amount

        conn.commit()
        return {
            "entity_group_id": entity_group_id,
            "entity_group_name": group_name,
            "eliminations": eliminations,
            "elimination_lines": eliminations,
            "total_eliminated": total_eliminated,
            "journal_entry_ids": je_ids,
            "status": "eliminated",
        }


def _get_descendant_ids(conn, group_id: int) -> List[int]:
    """Get all entity IDs in this group and its children (recursive CTE)."""
    rows = conn.execute(text("""
        WITH RECURSIVE tree AS (
            SELECT id FROM entity_groups WHERE id = :gid
            UNION ALL
            SELECT eg.id FROM entity_groups eg JOIN tree t ON eg.parent_id = t.id
        )
        SELECT id FROM tree
    """), {"gid": group_id}).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Intercompany Balances Report
# ---------------------------------------------------------------------------

def get_intercompany_balances(company_id: str) -> Dict[str, Any]:
    """Report outstanding (pending) IC balances grouped by entity pair."""
    with db_connection(company_id) as conn:
        rows = conn.execute(text("""
            SELECT t.source_entity_id, se.name as source_entity_name,
                   t.target_entity_id, te.name as target_entity_name,
                   SUM(t.source_amount) as net_amount,
                   t.source_currency as currency,
                   COUNT(*) as pending_count
            FROM intercompany_transactions_v2 t
            JOIN entity_groups se ON se.id = t.source_entity_id
            JOIN entity_groups te ON te.id = t.target_entity_id
            WHERE t.elimination_status = 'pending'
            GROUP BY t.source_entity_id, se.name, t.target_entity_id, te.name, t.source_currency
            ORDER BY net_amount DESC
        """)).fetchall()

        balances = []
        total = Decimal("0")
        for r in rows:
            amt = _dec(r[4])
            balances.append({
                "source_entity_id": r[0],
                "source_entity_name": r[1],
                "target_entity_id": r[2],
                "target_entity_name": r[3],
                "net_amount": amt,
                "currency": r[5],
                "pending_count": r[6],
            })
            total += amt

        return {"balances": balances, "total_pending": total}


# ---------------------------------------------------------------------------
# Account Mapping CRUD
# ---------------------------------------------------------------------------

def get_account_mappings(company_id: str) -> List[Dict[str, Any]]:
    with db_connection(company_id) as conn:
        rows = conn.execute(text(
            "SELECT id, source_entity_id, target_entity_id, source_account_id, target_account_id, "
            "created_at FROM intercompany_account_mappings ORDER BY id"
        )).fetchall()
        cols = ["id", "source_entity_id", "target_entity_id", "source_account_id",
                "target_account_id", "created_at"]
        return [dict(zip(cols, r)) for r in rows]


def create_account_mapping(data: Dict[str, Any], company_id: str, user_id: int) -> Dict[str, Any]:
    with db_connection(company_id) as conn:
        row = conn.execute(text("""
            INSERT INTO intercompany_account_mappings
                (source_entity_id, target_entity_id, source_account_id, target_account_id, created_by)
            VALUES (:src_eid, :tgt_eid, :src_aid, :tgt_aid, :uid)
            RETURNING id, source_entity_id, target_entity_id, source_account_id, target_account_id, created_at
        """), {
            "src_eid": data["source_entity_id"],
            "tgt_eid": data["target_entity_id"],
            "src_aid": data["source_account_id"],
            "tgt_aid": data["target_account_id"],
            "uid": str(user_id),
        }).fetchone()
        conn.commit()
        cols = ["id", "source_entity_id", "target_entity_id", "source_account_id",
                "target_account_id", "created_at"]
        return dict(zip(cols, row))
