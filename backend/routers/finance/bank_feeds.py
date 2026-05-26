"""
Phase 6 ext — Bank feeds ingestion (MT940 + CSV).

  POST /finance/bank-feeds/import       — upload an MT940 or CSV statement.
  GET  /finance/bank-feeds/statements   — list imported statements.
  GET  /finance/bank-feeds/statements/{id}/lines  — drill into lines.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import text

from database import get_db_connection
from integrations.bank_feeds import (
    parse_mt940, parse_csv_statement, CSVStatementConfig, parse_camt053,
)
from routers.auth import get_current_user
from utils.idempotency import find_bank_statement_by_source_hash
from utils.permissions import require_permission, validate_treasury_account_access, _is_branch_privileged
from utils.i18n import http_error
from utils.tax_precision import require_idempotency_key
from utils.tx import transactional

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
    request: Request = None,
    current_user=Depends(get_current_user),
):
    """Import Statement.

    P1 #60 fix: validate uploaded statement size + extension before
    parsing. Without these guards a hostile or accidental upload could
    DoS the worker (full-file read into memory) or smuggle disguised
    binaries through the parser.
    """
    from utils.sql_safety import (
        validate_file_size, validate_file_extension,
        validate_file_mime_and_signature,
        MAX_IMPORT_FILE_SIZE,
    )
    require_idempotency_key(request, operation="bank feed import")
    fmt = (source_format or "").lower().strip()
    raw = await file.read()
    # P1 #60 — size + extension guard. MT940 ships as .sta/.txt; CAMT.053
    # as .xml; CSV as .csv. Allow this wider set explicitly.
    validate_file_size(raw, MAX_IMPORT_FILE_SIZE, "كشف البنك")
    _BANKFEED_EXTS = {".csv", ".txt", ".sta", ".mt940", ".xml", ".camt", ".camt053"}
    if file.filename:
        validate_file_extension(file.filename.lower(), _BANKFEED_EXTS, "كشف البنك")
        validate_file_mime_and_signature(file.filename.lower(), file.content_type or "", raw, "كشف البنك", request)
    # F-NEW-068 (R-MISSING-IDEMPOTENCY) — PR16-fix:
    #
    # The original implementation hashed the raw payload once and reused
    # that single value as the ``source_hash`` for every statement
    # extracted from the file. Combined with the per-account unique
    # partial index ``uq_bank_statements_source_hash (bank_account_id,
    # source_hash)`` from migration 0030, any multi-statement MT940 or
    # CAMT.053 file would fail at the second INSERT with a constraint
    # violation. The natural anchor for a *statement* is the tuple
    # ``(file SHA-256, statement_index, statement_number)``; we keep the
    # whole-file hash as the *file-level* idempotency key so a duplicate
    # upload of the same file still short-circuits, but compute a
    # per-statement digest before each INSERT so the unique index never
    # collides on a legitimate multi-statement upload.
    raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else (raw or "").encode("utf-8")
    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    with transactional(current_user.company_id) as db:
        try:
            if bank_account_id:
                treasury_account = validate_treasury_account_access(db, current_user, bank_account_id)
                bank_account_id = int(treasury_account["id"])
            elif not _is_branch_privileged(current_user):
                raise HTTPException(**http_error(400, "select_bank_account_for_import", request))

            existing_id = find_bank_statement_by_source_hash(
                db, bank_account_id=bank_account_id, source_hash=file_hash,
            )
            if existing_id is not None:
                return {
                    "imported_statement_ids": [existing_id],
                    "count": 1,
                    "idempotent": True,
                }

            def _stmt_hash(idx: int, statement_number: Optional[str]) -> str:
                """Per-statement digest used for the unique-index key.

                Combines the whole-file hash with the statement's index in
                the file and its bank-supplied statement_number so a
                multi-statement upload writes distinct hashes. The whole
                file hash is still queried first (above) so re-uploading
                the *same* file collapses to the existing import.
                """
                seed = f"{file_hash}:{idx}:{statement_number or ''}".encode()
                return hashlib.sha256(seed).hexdigest()

            created: List[int] = []
            if fmt == "mt940":
                text_raw = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
                statements = parse_mt940(text_raw)
                for idx, st in enumerate(statements, start=1):
                    stmt_id = _insert_statement(
                        db, bank_account_id=bank_account_id, iban=st.account,
                        statement_number=st.statement_number, currency=st.currency,
                        opening=st.opening_balance, closing=st.closing_balance,
                        period_start=st.transactions[0].value_date if st.transactions else None,
                        period_end=st.transactions[-1].value_date if st.transactions else None,
                        source_format="mt940", source_filename=file.filename,
                        source_hash=_stmt_hash(idx, st.statement_number),
                        source_file_hash=file_hash if idx == 1 else None,
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
                    except Exception:
                        raise HTTPException(**http_error(400, "bank_feed_invalid_csv_config", request))
                rows = parse_csv_statement(raw, cfg)
                if not rows:
                    raise HTTPException(**http_error(400, "bank_feed_csv_no_transactions", request))
                stmt_id = _insert_statement(
                    db, bank_account_id=bank_account_id, iban=None,
                    statement_number=None, currency=rows[0]["currency"],
                    opening=None,
                    closing=rows[-1].get("balance"),
                    period_start=rows[0]["posting_date"],
                    period_end=rows[-1]["posting_date"],
                    source_format="csv", source_filename=file.filename,
                    source_hash=_stmt_hash(1, None),
                    source_file_hash=file_hash,
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
                except ValueError:
                    raise HTTPException(**http_error(400, "bank_feed_camt_parse_failed", request))
                for idx, st in enumerate(statements, start=1):
                    stmt_id = _insert_statement(
                        db, bank_account_id=bank_account_id, iban=st.account,
                        statement_number=st.statement_number, currency=st.currency,
                        opening=st.opening_balance, closing=st.closing_balance,
                        period_start=st.period_start,
                        period_end=st.period_end,
                        source_format="camt053", source_filename=file.filename,
                        source_hash=_stmt_hash(idx, st.statement_number),
                        source_file_hash=file_hash if idx == 1 else None,
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
                raise HTTPException(**http_error(400, "bank_feed_unsupported_format", request))
            return {"imported_statement_ids": created, "count": len(created)}
        except HTTPException:
            raise
        except Exception:
            logger.warning("bank-feed import failed")
            raise HTTPException(**http_error(500, "bank_feed_import_failed", request))


def _insert_statement(db, *, bank_account_id, iban, statement_number, currency,
                      opening, closing, period_start, period_end,
                      source_format, source_filename, imported_by,
                      source_hash=None, source_file_hash=None) -> int:
    row = db.execute(
        text("""
            INSERT INTO bank_statements
                (bank_account_id, account_iban, statement_number, currency,
                 opening_balance, closing_balance, period_start, period_end,
                 source_format, source_filename, source_hash, source_file_hash, imported_by)
            VALUES (:ba, :iban, :num, :cur, :ob, :cb, :ps, :pe, :sf, :fn, :sh, :sfh, :uid)
            RETURNING id
        """),
        {"ba": bank_account_id, "iban": iban, "num": statement_number,
         "cur": currency, "ob": opening, "cb": closing,
         "ps": period_start, "pe": period_end,
         "sf": source_format, "fn": source_filename, "sh": source_hash, "sfh": source_file_hash,
         "uid": imported_by},
    ).fetchone()
    return int(row[0])


@router.get(
    "/statements",
    dependencies=[Depends(require_permission("finance.reconciliation_view"))],
)
def list_statements(limit: int = 50, current_user=Depends(get_current_user)):
    """List Statements."""
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
        items = []
        for r in rows:
            if r[1]:
                try:
                    validate_treasury_account_access(db, current_user, r[1])
                except HTTPException:
                    continue
            elif not _is_branch_privileged(current_user):
                continue
            items.append({
                "id": r[0], "bank_account_id": r[1], "iban": r[2],
                "statement_number": r[3], "currency": r[4],
                "opening_balance": str(r[5]) if r[5] is not None else None,
                "closing_balance": str(r[6]) if r[6] is not None else None,
                "period_start": r[7].isoformat() if r[7] else None,
                "period_end": r[8].isoformat() if r[8] else None,
                "source_format": r[9], "source_filename": r[10],
                "created_at": r[11].isoformat() if r[11] else None,
            })
        return items
    finally:
        _close(db)


@router.get(
    "/statements/{statement_id}/lines",
    dependencies=[Depends(require_permission("finance.reconciliation_view"))],
)
def list_lines(request: Request, statement_id: int, current_user=Depends(get_current_user)):
    """List Lines."""
    db = get_db_connection(current_user.company_id)
    try:
        statement = db.execute(
            text("SELECT bank_account_id FROM bank_statements WHERE id = :sid"),
            {"sid": statement_id},
        ).fetchone()
        if not statement:
            raise HTTPException(**http_error(404, "bank_statement_not_found", request))
        if statement.bank_account_id:
            validate_treasury_account_access(db, current_user, statement.bank_account_id)
        elif not _is_branch_privileged(current_user):
            raise HTTPException(**http_error(403, "no_permission_unlinked_statement", request))

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
