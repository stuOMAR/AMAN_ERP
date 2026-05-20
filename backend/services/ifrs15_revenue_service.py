"""
TASK-036 — IFRS 15 / ASC 606 revenue recognition engine (core).

Implements the essential mechanics:

  * Create a contract with performance obligations (POs).
  * Allocate the transaction price to POs using the relative-standalone-
    selling-price method.
  * Recognise revenue:
      - point_in_time: flips satisfied_pct 0→1 and recognises the full
        allocated amount in one shot.
      - over_time:     caller supplies a new cumulative satisfied_pct
        (e.g. cost-to-cost input method); engine recognises the delta.
  * Optional JE: Dr: Contract asset / Cash, Cr: Revenue. Accounts are
    passed in — CoA mapping is tenant-specific.

Contract modifications (adding/removing POs, reallocation of transaction
price) are intentionally out of this service's scope; they are recorded
by mutating rows and calling `allocate_transaction_price` again.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)
_D2 = Decimal("0.01")


def create_contract(db, contract_number: str, customer_id: Optional[int],
                    total_transaction_price: Decimal, currency: str = "SAR",
                    start_date: Optional[date] = None, end_date: Optional[date] = None,
                    obligations: Optional[list] = None) -> int:
    """Create a contract; optionally seed its performance obligations.

    Each obligation dict: {description, standalone_selling_price, recognition_method}.
    """
    ins = db.execute(text("""
        INSERT INTO revenue_contracts (contract_number, customer_id, total_transaction_price,
            currency, start_date, end_date, status)
        VALUES (:cn, :cid, :tp, :cur, :sd, :ed, 'active')
        RETURNING id
    """), {
        "cn": contract_number, "cid": customer_id,
        "tp": str(total_transaction_price), "cur": currency,
        "sd": start_date, "ed": end_date,
    })
    contract_id = ins.scalar()
    if obligations:
        for ob in obligations:
            db.execute(text("""
                INSERT INTO performance_obligations (contract_id, description,
                    standalone_selling_price, recognition_method)
                VALUES (:cid, :desc, :ssp, :rm)
            """), {
                "cid": contract_id,
                "desc": ob["description"],
                "ssp": str(ob.get("standalone_selling_price") or 0),
                "rm": ob.get("recognition_method", "point_in_time"),
            })
        allocate_transaction_price(db, contract_id, commit=False)
    db.commit()
    return contract_id


def allocate_transaction_price(db, contract_id: int, commit: bool = True) -> dict:
    """Allocate contract TP across POs by relative SSP. Returns per-PO allocations."""
    c = db.execute(text(
        "SELECT total_transaction_price FROM revenue_contracts WHERE id = :id"
    ), {"id": contract_id}).fetchone()
    if not c:
        raise ValueError(f"contract {contract_id} not found")
    tp = Decimal(str(c.total_transaction_price))

    pos = db.execute(text("""
        SELECT id, standalone_selling_price FROM performance_obligations
        WHERE contract_id = :cid ORDER BY id
    """), {"cid": contract_id}).fetchall()
    if not pos:
        return {"contract_id": contract_id, "allocated": []}

    total_ssp = sum((Decimal(str(p.standalone_selling_price or 0)) for p in pos), Decimal("0"))
    allocations = []
    running = Decimal("0")
    for i, p in enumerate(pos):
        ssp = Decimal(str(p.standalone_selling_price or 0))
        if total_ssp > 0:
            alloc = (tp * ssp / total_ssp).quantize(_D2, rounding=ROUND_HALF_UP)
        else:
            alloc = (tp / len(pos)).quantize(_D2, rounding=ROUND_HALF_UP)
        # Absorb rounding diff into the last PO.
        if i == len(pos) - 1:
            alloc = (tp - running).quantize(_D2, rounding=ROUND_HALF_UP)
        running += alloc
        db.execute(text(
            "UPDATE performance_obligations SET allocated_price = :a WHERE id = :id"
        ), {"a": str(alloc), "id": p.id})
        allocations.append({"po_id": p.id, "allocated_price": str(alloc)})
    if commit:
        db.commit()
    return {"contract_id": contract_id, "total_transaction_price": str(tp),
            "allocated": allocations}


def recognise_revenue(db, po_id: int,
                      company_id: Optional[str] = None,
                      as_of_date: Optional[date] = None,
                      new_satisfied_pct: Optional[Decimal] = None,
                      post_journal: bool = False,
                      debit_account_id: Optional[int] = None,
                      credit_account_id: Optional[int] = None,
                      user_id: Optional[int] = None,
                      username: Optional[str] = None) -> dict:
    """Recognise revenue on a PO.

    * For `point_in_time` POs: ignores `new_satisfied_pct` and marks satisfied=1.
    * For `over_time` POs: requires `new_satisfied_pct` in [0, 1]; recognises
      the delta since last recognition.
    """
    as_of = as_of_date or date.today()
    po = db.execute(text("""
        SELECT id, contract_id, description, allocated_price, recognition_method,
               satisfied_pct, revenue_recognized
        FROM performance_obligations WHERE id = :id FOR UPDATE
    """), {"id": po_id}).fetchone()
    if not po:
        raise ValueError(f"performance_obligation {po_id} not found")
    allocated = Decimal(str(po.allocated_price or 0))
    prev_pct = Decimal(str(po.satisfied_pct or 0))
    prev_rev = Decimal(str(po.revenue_recognized or 0))

    if po.recognition_method == "point_in_time":
        target_pct = Decimal("1")
    else:
        if new_satisfied_pct is None:
            raise ValueError("over_time PO requires new_satisfied_pct")
        target_pct = Decimal(str(new_satisfied_pct))
        if not (Decimal("0") <= target_pct <= Decimal("1")):
            raise ValueError("new_satisfied_pct must be in [0, 1]")

    if target_pct <= prev_pct:
        return {"po_id": po_id, "recognised_now": "0.00",
                "total_recognised": str(prev_rev), "satisfied_pct": str(prev_pct),
                "journal_entry_id": None}

    new_total_rev = (allocated * target_pct).quantize(_D2, rounding=ROUND_HALF_UP)
    delta = (new_total_rev - prev_rev).quantize(_D2, rounding=ROUND_HALF_UP)

    journal_entry_id = None
    if post_journal and delta > 0:
        if not (debit_account_id and credit_account_id):
            raise ValueError("post_journal=True requires debit_account_id + credit_account_id")
        if not (user_id and company_id):
            raise ValueError("post_journal=True requires user_id + company_id")
        from services.gl_service import create_journal_entry
        from utils.fiscal_lock import check_fiscal_period_open

        # Fiscal-period lock: block posting into a closed period.
        check_fiscal_period_open(db, str(as_of))
        journal_entry_id, _ = create_journal_entry(
            db,
            company_id=company_id,
            date=str(as_of),
            description=f"IFRS 15 revenue recognition PO#{po_id}",
            lines=[
                {"account_id": debit_account_id,
                 "debit": delta, "credit": Decimal("0"),
                 "description": f"Contract asset — {po.description}"},
                {"account_id": credit_account_id,
                 "debit": Decimal("0"), "credit": delta,
                 "description": f"Revenue — {po.description}"},
            ],
            user_id=user_id,
            username=username or "revenue_service",
            source="ifrs15_revenue",
            source_id=po_id,
            status="posted",
        )

    db.execute(text("""
        UPDATE performance_obligations
           SET satisfied_pct = :pct, revenue_recognized = :rev
         WHERE id = :id
    """), {"pct": str(target_pct), "rev": str(new_total_rev), "id": po_id})
    db.commit()

    return {
        "po_id": po_id,
        "recognised_now": str(delta),
        "total_recognised": str(new_total_rev),
        "satisfied_pct": str(target_pct),
        "journal_entry_id": journal_entry_id,
    }
