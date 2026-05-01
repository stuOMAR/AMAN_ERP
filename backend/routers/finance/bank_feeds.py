"""
Phase 6 ext — Bank feeds ingestion (MT940 + CSV).

  POST /finance/bank-feeds/import       — upload an MT940 or CSV statement.
  GET  /finance/bank-feeds/statements   — list imported statements.
  GET  /finance/bank-feeds/statements/{id}/lines  — drill into lines.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text

from database import get_db_connection
from integrations.bank_feeds import (
    parse_mt940, parse_csv_statement, CSVStatementConfig, parse_camt053,
)
from routers.auth import get_current_user
from utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/finance/bank-feeds", tags=["bank-feeds"])


def _close(db):
    try:
        db.close()
    except Exception:
        pass


@router.post(
    "/import",
    dependencies=[Depends(require_permission("finance.reconciliation_manage"))],
)
async def import_statement(
    file: UploadFile = File(...),
    source_format: str = Form(...),          # mt940 | csv
    bank_account_id: Optional[int] = Form(None),
    csv_config: Optional[str] = Form(None),  # JSON override for CSVStatementConfig
    current_user=Depends(get_current_user),
):
    raw = await file.read()
    fmt = (source_format or "").lower().strip()
    db = get_db_connection(current_user.company_id)
    try:
        created: List[int] = []
        if fmt == "mt940":
            text_raw = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
            statements = parse_mt940(text_raw)
            for st in statements:
                stmt_id = _insert_statement(
                    db, bank_account_id=bank_account_id, iban=st.account,
                    statement_number=st.statement_number, currency=st.currency,
                    opening=st.opening_balance, closing=st.closing_balance,
                    period_start=st.transactions[0].value_date if st.transactions else None,
                    period_end=st.transactions[-1].value_date if st.transactions else None,
                    source_format="mt940", source_filename=file.filename,
                    imported_by=current_user.id,
                )
                for i, t in enumerate(st.transactions, start=1):
                    db.execute(
                        text("""INSERT INTO bank_statement_lines
                                    (statement_id, line_no, value_date, posting_date,
                                     amount, currency, tx_type, reference,
                                     bank_reference, description)
                                VALUES (:sid, :n, :vd, :pd, :amt, :cur, :tt, :ref, :br, :desc)"""),
                        {"sid": stmt_id, "n": i, "vd": t.value_date,
                         "pd": t.entry_date or t.value_date,
                         "amt": t.amount, "cur": t.currency or st.currency,
                         "tt": t.transaction_type, "ref": t.reference[:120] if t.reference else None,
                         "br": t.bank_reference, "desc": t.description},
                    )
                created.append(stmt_id)
        elif fmt == "csv":
            cfg = CSVStatementConfig()
            if csv_config:
                try:
                    override = json.loads(csv_config)
                    cfg = CSVStatementConfig(**{**cfg.__dict__, **override})
                except Exception as e:
                    raise HTTPException(400, f"invalid csv_config JSON: {e}")
            rows = parse_csv_statement(raw, cfg)
            if not rows:
                raise HTTPException(400, "CSV produced no transactions")
            stmt_id = _insert_statement(
                db, bank_account_id=bank_account_id, iban=None,
                statement_number=None, currency=rows[0]["currency"],
                opening=None,
                closing=rows[-1].get("balance"),
                period_start=rows[0]["posting_date"],
                period_end=rows[-1]["posting_date"],
                source_format="csv", source_filename=file.filename,
                imported_by=current_user.id,
            )
            for i, r in enumerate(rows, start=1):
                db.execute(
                    text("""INSERT INTO bank_statement_lines
                                (statement_id, line_no, value_date, posting_date,
                                 amount, currency, reference, description, raw)
                            VALUES (:sid, :n, :vd, :pd, :amt, :cur, :ref, :desc,
                                    CAST(:raw AS JSONB))"""),
                    {"sid": stmt_id, "n": i,
                     "vd": r.get("value_date"), "pd": r.get("posting_date"),
                     "amt": r["amount"], "cur": r["currency"],
                     "ref": r.get("reference"), "desc": r.get("description"),
                     "raw": json.dumps(r.get("raw") or {}, default=str)},
                )
            created.append(stmt_id)
        elif fmt in ("camt053", "camt.053", "camt", "iso20022"):
            try:
                statements = parse_camt053(raw)
            except ValueError as e:
                raise HTTPException(400, f"CAMT.053 parse failed: {e}")
            for st in statements:
                stmt_id = _insert_statement(
                    db, bank_account_id=bank_account_id, iban=st.account,
                    statement_number=st.statement_number, currency=st.currency,
                    opening=st.opening_balance, closing=st.closing_balance,
                    period_start=st.period_start,
                    period_end=st.period_end,
                    source_format="camt053", source_filename=file.filename,
                    imported_by=current_user.id,
                )
                for i, t in enumerate(st.transactions, start=1):
                    db.execute(
                        text("""INSERT INTO bank_statement_lines
                                    (statement_id, line_no, value_date, posting_date,
                                     amount, currency, tx_type, reference,
                                     bank_reference, description)
                                VALUES (:sid, :n, :vd, :pd, :amt, :cur, :tt, :ref, :br, :desc)"""),
                        {"sid": stmt_id, "n": i, "vd": t.value_date,
                         "pd": t.entry_date or t.value_date,
                         "amt": t.amount, "cur": t.currency or st.currency,
                         "tt": t.transaction_type,
                         "ref": (t.reference or "")[:120] or None,
                         "br": t.bank_reference, "desc": t.description},
                    )
                created.append(stmt_id)
        else:
            raise HTTPException(400, f"unsupported source_format: {source_format!r}")
        db.commit()
        return {"imported_statement_ids": created, "count": len(created)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("bank-feed import failed")
        raise HTTPException(500, f"bank feed import failed: {e}")
    finally:
        _close(db)


def _insert_statement(db, *, bank_account_id, iban, statement_number, currency,
                      opening, closing, period_start, period_end,
                      source_format, source_filename, imported_by) -> int:
    row = db.execute(
        text("""
            INSERT INTO bank_statements
                (bank_account_id, account_iban, statement_number, currency,
                 opening_balance, closing_balance, period_start, period_end,
                 source_format, source_filename, imported_by)
            VALUES (:ba, :iban, :num, :cur, :ob, :cb, :ps, :pe, :sf, :fn, :uid)
            RETURNING id
        """),
        {"ba": bank_account_id, "iban": iban, "num": statement_number,
         "cur": currency, "ob": opening, "cb": closing,
         "ps": period_start, "pe": period_end,
         "sf": source_format, "fn": source_filename, "uid": imported_by},
    ).fetchone()
    return int(row[0])


@router.get(
    "/statements",
    dependencies=[Depends(require_permission("finance.reconciliation_view"))],
)
def list_statements(limit: int = 50, current_user=Depends(get_current_user)):
    limit = max(1, min(int(limit), 500))
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""SELECT id, bank_account_id, account_iban, statement_number,
                           currency, opening_balance, closing_balance,
                           period_start, period_end, source_format,
                           source_filename, created_at
                      FROM bank_statements ORDER BY id DESC LIMIT :n"""),
            {"n": limit},
        ).fetchall()
        return [
            {
                "id": r[0], "bank_account_id": r[1], "iban": r[2],
                "statement_number": r[3], "currency": r[4],
                "opening_balance": str(r[5]) if r[5] is not None else None,
                "closing_balance": str(r[6]) if r[6] is not None else None,
                "period_start": r[7].isoformat() if r[7] else None,
                "period_end": r[8].isoformat() if r[8] else None,
                "source_format": r[9], "source_filename": r[10],
                "created_at": r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ]
    finally:
        _close(db)


@router.get(
    "/statements/{statement_id}/lines",
    dependencies=[Depends(require_permission("finance.reconciliation_view"))],
)
def list_lines(statement_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(
            text("""SELECT id, line_no, value_date, posting_date, amount,
                           currency, tx_type, reference, bank_reference,
                           description, match_status, matched_entry_id
                      FROM bank_statement_lines
                     WHERE statement_id = :sid ORDER BY line_no"""),
            {"sid": statement_id},
        ).fetchall()
        return [
            {
                "id": r[0], "line_no": r[1],
                "value_date": r[2].isoformat() if r[2] else None,
                "posting_date": r[3].isoformat() if r[3] else None,
                "amount": str(r[4]), "currency": r[5],
                "tx_type": r[6], "reference": r[7], "bank_reference": r[8],
                "description": r[9], "match_status": r[10],
                "matched_entry_id": r[11],
            }
            for r in rows
        ]
    finally:
        _close(db)
