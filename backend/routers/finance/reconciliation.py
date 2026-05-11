from fastapi import Request, APIRouter, Depends, HTTPException, status, UploadFile, File
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime
import csv
import io
import re
import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, require_sensitive_permission, require_module, validate_branch_access, validate_treasury_account_access
from utils.audit import log_activity
from schemas.reconciliation import ReconciliationCreate, StatementLineCreate, MatchRequest, UnmatchRequest

router = APIRouter(prefix="/reconciliation", tags=["Bank Reconciliation"], dependencies=[Depends(require_module("accounting"))])

_D2 = Decimal("0.01")


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

# --- Endpoints ---

@router.get("", dependencies=[Depends(require_permission("reconciliation.view"))], response_model=List[Dict[str, Any]])
def list_reconciliations(
    account_id: Optional[int] = None, 
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة التسويات"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT r.*, t.name as account_name, t.currency,
                   u.username as created_by_name,
                   (SELECT COUNT(*) FROM bank_statement_lines bsl 
                    WHERE bsl.reconciliation_id = r.id AND bsl.is_reconciled = FALSE) as unmatched_count,
                   (SELECT COUNT(*) FROM bank_statement_lines bsl 
                    WHERE bsl.reconciliation_id = r.id AND bsl.is_reconciled = TRUE) as matched_count,
                   (SELECT COUNT(*) FROM bank_statement_lines bsl 
                    WHERE bsl.reconciliation_id = r.id) as total_lines
            FROM bank_reconciliations r
            JOIN treasury_accounts t ON r.treasury_account_id = t.id
            LEFT JOIN company_users u ON r.created_by = u.id
            WHERE 1=1
        """
        params = {}
        if account_id:
            query += " AND r.treasury_account_id = :aid"
            params["aid"] = account_id
        query += " " + branch_scope_filter(current_user, branch_id, "r.branch_id", params, branch_param="bid")
             
        query += " ORDER BY r.statement_date DESC"
        
        result = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in result]

@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def create_reconciliation(request: Request, data: ReconciliationCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء مسودة تسوية جديدة"""
    with transactional(current_user.company_id) as db:
        branch_id = validate_branch_access(current_user, data.branch_id)
        treasury_account = validate_treasury_account_access(
            db, current_user, data.treasury_account_id, branch_id
        )
        if branch_id is None and treasury_account.get("branch_id") is not None:
            branch_id = int(treasury_account["branch_id"])

        # Check if draft already exists for this account
        existing = db.execute(text("""
            SELECT id FROM bank_reconciliations 
            WHERE treasury_account_id = :tid 
            AND status = 'draft'
        """), {"tid": data.treasury_account_id}).fetchone()
        
        if existing:
            raise HTTPException(**http_error(400, "reconciliation_draft_exists", request))

        tolerance_amount = data.tolerance_amount
        if tolerance_amount is None:
            tolerance_amount = db.execute(text("""
                SELECT setting_value
                FROM company_settings
                WHERE setting_key = 'reconciliation_auto_match_tolerance'
                LIMIT 1
            """)).scalar()
        try:
            tolerance_amount = float(tolerance_amount or 0)
        except (TypeError, ValueError):
            tolerance_amount = 0

        rec_id = db.execute(text("""
            INSERT INTO bank_reconciliations (
                treasury_account_id, statement_date, start_balance, end_balance, 
                status, notes, created_by, branch_id, tolerance_amount
            ) VALUES (
                :tid, :date, :start, :end, 
                'draft', :notes, :uid, :bid, :tol
            ) RETURNING id
        """), {
            "tid": data.treasury_account_id, "date": data.statement_date,
            "start": data.start_balance, "end": data.end_balance,
            "notes": data.notes, "uid": current_user.id, "bid": branch_id,
            "tol": tolerance_amount,
        }).scalar()
        
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="reconciliation.create",
                     resource_type="bank_reconciliation", resource_id=str(rec_id),
                     details={"treasury_account_id": data.treasury_account_id, "statement_date": str(data.statement_date)})
        return {"id": rec_id, "message": i18n_message("reconciliation_created", request)}

@router.get("/{id}", dependencies=[Depends(require_permission("reconciliation.view"))], response_model=Dict[str, Any])
def get_reconciliation(id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل التسوية"""
    with transactional(current_user.company_id) as db:
        rec = db.execute(text("""
            SELECT r.*, t.name as account_name, t.currency, t.current_balance as book_balance
            FROM bank_reconciliations r
            JOIN treasury_accounts t ON r.treasury_account_id = t.id
            WHERE r.id = :id
        """), {"id": id}).fetchone()
        
        if not rec:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))

        # Branch access check
        if rec.branch_id:
            validate_branch_access(current_user, rec.branch_id)
            
        statement_lines = db.execute(text("""
            SELECT sl.*, 
                   CASE WHEN sl.is_reconciled = TRUE THEN 'matched' ELSE 'unmatched' END as match_status,
                   jl_ref.entry_number as matched_entry_number
            FROM bank_statement_lines sl
            LEFT JOIN (
                SELECT jl.id as jl_id, je.entry_number 
                FROM journal_lines jl 
                JOIN journal_entries je ON jl.journal_entry_id = je.id
            ) jl_ref ON sl.matched_journal_line_id = jl_ref.jl_id
            WHERE sl.reconciliation_id = :id
            ORDER BY sl.transaction_date, sl.id
        """), {"id": id}).fetchall()

        all_lines = [dict(r._mapping) for r in statement_lines]
        matched_lines = [l for l in all_lines if l.get('is_reconciled')]
        unmatched_lines = [l for l in all_lines if not l.get('is_reconciled')]

        matched_net = sum((_dec(l.get('credit', 0)) - _dec(l.get('debit', 0)) for l in matched_lines), Decimal("0"))
        unmatched_net = sum((_dec(l.get('credit', 0)) - _dec(l.get('debit', 0)) for l in unmatched_lines), Decimal("0"))
        total_net = sum((_dec(l.get('credit', 0)) - _dec(l.get('debit', 0)) for l in all_lines), Decimal("0"))

        calculated_end = _dec(rec.start_balance) + total_net
        difference = calculated_end - _dec(rec.end_balance)

        return {
            "header": dict(rec._mapping),
            "lines": all_lines,
            "summary": {
                "total_lines": len(all_lines),
                "matched_count": len(matched_lines),
                "unmatched_count": len(unmatched_lines),
                "matched_net": float(matched_net.quantize(_D2, ROUND_HALF_UP)),
                "unmatched_net": float(unmatched_net.quantize(_D2, ROUND_HALF_UP)),
                "total_net": float(total_net.quantize(_D2, ROUND_HALF_UP)),
                "calculated_end_balance": float(calculated_end.quantize(_D2, ROUND_HALF_UP)),
                "target_end_balance": float(_dec(rec.end_balance).quantize(_D2, ROUND_HALF_UP)),
                "difference": float(difference.quantize(_D2, ROUND_HALF_UP)),
            }
        }

@router.post("/{id}/lines", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def add_statement_lines(request: Request, id: int, lines: List[StatementLineCreate], current_user: dict = Depends(get_current_user)):
    """إضافة أسطر كشف الحساب يدوياً"""
    with transactional(current_user.company_id) as db:
        rec = db.execute(text("SELECT status, start_balance FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
        if not rec:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec.status != 'draft':
            raise HTTPException(**http_error(400, "cannot_add_to_approved", request))

        last_balance = db.execute(text("""
            SELECT balance FROM bank_statement_lines 
            WHERE reconciliation_id = :id ORDER BY id DESC LIMIT 1
        """), {"id": id}).scalar()
        
        running_balance = _dec(last_balance) if last_balance is not None else _dec(rec.start_balance)

        added = []
        for line in lines:
            running_balance = running_balance + _dec(line.credit) - _dec(line.debit)
            
            result = db.execute(text("""
                INSERT INTO bank_statement_lines (
                    reconciliation_id, transaction_date, description, reference, 
                    debit, credit, balance, is_reconciled
                ) VALUES (:rid, :date, :desc, :ref, :deb, :cred, :bal, FALSE)
                RETURNING id
            """), {
                "rid": id, "date": line.transaction_date, "desc": line.description,
                "ref": line.reference, "deb": line.debit, "cred": line.credit,
                "bal": float(running_balance.quantize(_D2, ROUND_HALF_UP))
            })
            added.append(result.scalar())
            
        return {"message": i18n_message("reconciliation_lines_added", request), "line_ids": added}


# ──────── BANK STATEMENT FILE IMPORT ────────

def _parse_date(val: str) -> Optional[str]:
    """Try multiple date formats common in Saudi bank exports."""
    val = val.strip()
    for fmt_str in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(val, fmt_str).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _detect_csv_columns(headers: List[str]) -> dict:
    """Auto-detect column mapping from CSV headers (Arabic + English)."""
    mapping = {}
    date_keywords = ['date', 'تاريخ', 'transaction_date', 'value_date', 'posting_date', 'تاريخ العملية', 'تاريخ القيد']
    desc_keywords = ['description', 'الوصف', 'details', 'البيان', 'التفاصيل', 'narrative', 'particulars', 'بيان']
    ref_keywords  = ['reference', 'المرجع', 'ref', 'رقم المرجع', 'cheque', 'رقم الشيك', 'transaction_id']
    deb_keywords  = ['debit', 'مدين', 'withdrawal', 'سحب', 'مسحوب', 'مبلغ مدين', 'withdrawals']
    cred_keywords = ['credit', 'دائن', 'deposit', 'إيداع', 'مبلغ دائن', 'deposits']
    bal_keywords  = ['balance', 'الرصيد', 'رصيد', 'running_balance']
    amount_keywords = ['amount', 'المبلغ', 'مبلغ']

    normalized = [h.strip().lower().replace('\ufeff', '') for h in headers]

    for i, h in enumerate(normalized):
        if not mapping.get('date') and any(k in h for k in date_keywords):
            mapping['date'] = i
        elif not mapping.get('description') and any(k in h for k in desc_keywords):
            mapping['description'] = i
        elif not mapping.get('reference') and any(k in h for k in ref_keywords):
            mapping['reference'] = i
        elif not mapping.get('debit') and any(k in h for k in deb_keywords):
            mapping['debit'] = i
        elif not mapping.get('credit') and any(k in h for k in cred_keywords):
            mapping['credit'] = i
        elif not mapping.get('balance') and any(k in h for k in bal_keywords):
            mapping['balance'] = i
        elif not mapping.get('amount') and any(k in h for k in amount_keywords):
            mapping['amount'] = i

    return mapping


def _parse_amount(val) -> Decimal:
    """Parse amount string handling commas, parentheses (negative), Arabic digits."""
    if val is None:
        return Decimal("0")
    s = str(val).strip()
    if not s or s in ('-', '—', '–', ''):
        return Decimal("0")
    # Arabic digits
    arabic_digits = {'٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9'}
    for ar, en in arabic_digits.items():
        s = s.replace(ar, en)
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    s = s.replace(',', '').replace(' ', '')
    s = re.sub(r'[^\d.\-]', '', s)
    try:
        v = Decimal(s)
        return -v if negative else v
    except Exception:
        return Decimal("0")


@router.post("/{id}/import-preview", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
async def preview_import(
    id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """معاينة ملف كشف الحساب قبل الاستيراد (CSV / Excel).

    P1 #59 / #61 fix: enforce file size + extension before parsing the
    body. Without these guards a 500 MB upload would be loaded fully
    into memory and a hostile client could ship arbitrary content types.
    """
    from utils.sql_safety import (
        validate_file_size, validate_file_extension,
        MAX_IMPORT_FILE_SIZE, ALLOWED_IMPORT_EXTENSIONS,
    )
    with transactional(current_user.company_id) as db:
        try:
            rec = db.execute(text("SELECT status FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
            if not rec:
                raise HTTPException(**http_error(404, "reconciliation_not_found"))
            if rec.status != 'draft':
                raise HTTPException(**http_error(400, "cannot_import_to_approved", request))
    
            content = await file.read()
            filename = file.filename.lower() if file.filename else ""
            # P1 #59/#61 — size + extension guard.
            validate_file_size(content, MAX_IMPORT_FILE_SIZE, "كشف الحساب")
            validate_file_extension(filename, ALLOWED_IMPORT_EXTENSIONS, "كشف الحساب")
    
            rows = []
            headers = []
    
            if filename.endswith(('.xlsx', '.xls')):
                try:
                    import openpyxl
                except ImportError:
                    raise HTTPException(**http_error(400, "openpyxl_required", request))
                wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
                ws = wb.active
                all_rows = list(ws.iter_rows(values_only=True))
                if not all_rows:
                    raise HTTPException(**http_error(400, "file_empty"))
                # Skip empty leading rows
                start_idx = 0
                for i, row in enumerate(all_rows):
                    if any(cell is not None and str(cell).strip() for cell in row):
                        start_idx = i
                        break
                headers = [str(cell or '').strip() for cell in all_rows[start_idx]]
                for row in all_rows[start_idx + 1:]:
                    rows.append([str(cell or '').strip() for cell in row])
            else:
                # Treat as CSV
                try:
                    text_content = content.decode('utf-8-sig')
                except UnicodeDecodeError:
                    try:
                        text_content = content.decode('cp1256')  # Arabic Windows encoding
                    except UnicodeDecodeError:
                        text_content = content.decode('latin-1')
    
                # Detect delimiter
                sample = text_content[:2000]
                if sample.count('\t') > sample.count(',') and sample.count('\t') > sample.count(';'):
                    delimiter = '\t'
                elif sample.count(';') > sample.count(','):
                    delimiter = ';'
                else:
                    delimiter = ','
    
                reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
                all_rows = list(reader)
                if not all_rows:
                    raise HTTPException(**http_error(400, "file_empty"))
                # Skip empty leading rows
                start_idx = 0
                for i, row in enumerate(all_rows):
                    if any(cell.strip() for cell in row):
                        start_idx = i
                        break
                headers = [h.strip() for h in all_rows[start_idx]]
                rows = all_rows[start_idx + 1:]
    
            # Auto-detect columns
            col_mapping = _detect_csv_columns(headers)
    
            # Parse rows into preview lines
            preview_lines = []
            skipped = 0
            for row in rows:
                if not any(str(cell).strip() for cell in row):
                    continue  # skip empty rows
    
                # Extract date
                raw_date = row[col_mapping['date']] if 'date' in col_mapping and col_mapping['date'] < len(row) else ''
                parsed_date = _parse_date(raw_date)
                if not parsed_date:
                    skipped += 1
                    continue
    
                desc = row[col_mapping['description']] if 'description' in col_mapping and col_mapping['description'] < len(row) else ''
                ref = row[col_mapping['reference']] if 'reference' in col_mapping and col_mapping['reference'] < len(row) else ''
    
                debit_val = Decimal("0")
                credit_val = Decimal("0")
    
                if 'debit' in col_mapping and 'credit' in col_mapping:
                    debit_val = _parse_amount(row[col_mapping['debit']] if col_mapping['debit'] < len(row) else '')
                    credit_val = _parse_amount(row[col_mapping['credit']] if col_mapping['credit'] < len(row) else '')
                elif 'amount' in col_mapping:
                    amt = _parse_amount(row[col_mapping['amount']] if col_mapping['amount'] < len(row) else '')
                    if amt < 0:
                        debit_val = abs(amt)
                    else:
                        credit_val = amt
    
                # Ensure positive values
                debit_val = abs(debit_val)
                credit_val = abs(credit_val)
    
                if debit_val == 0 and credit_val == 0:
                    skipped += 1
                    continue
    
                preview_lines.append({
                    "transaction_date": parsed_date,
                    "description": desc.strip(),
                    "reference": ref.strip(),
                    "debit": float(debit_val.quantize(_D2, ROUND_HALF_UP)),
                    "credit": float(credit_val.quantize(_D2, ROUND_HALF_UP)),
                })
    
            return {
                "filename": file.filename,
                "headers": headers,
                "column_mapping": col_mapping,
                "total_rows": len(rows),
                "parsed_lines": len(preview_lines),
                "skipped_rows": skipped,
                "preview": preview_lines[:200],  # Max 200 for preview
                "all_lines": preview_lines,
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error parsing reconciliation file")
            raise HTTPException(**http_error(400, "reconciliation_parse_error", request))


@router.post("/{id}/import-confirm", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def confirm_import(request: Request, id: int, lines: List[StatementLineCreate], current_user: dict = Depends(get_current_user)):
    """تأكيد استيراد أسطر كشف الحساب بعد المعاينة"""
    with transactional(current_user.company_id) as db:
        rec = db.execute(text("SELECT status, start_balance FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
        if not rec:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec.status != 'draft':
            raise HTTPException(**http_error(400, "cannot_import_to_approved", request))

        if not lines:
            raise HTTPException(**http_error(400, "reconciliation_no_lines_to_import", request))

        last_balance = db.execute(text("""
            SELECT balance FROM bank_statement_lines 
            WHERE reconciliation_id = :id ORDER BY id DESC LIMIT 1
        """), {"id": id}).scalar()

        running_balance = _dec(last_balance) if last_balance is not None else _dec(rec.start_balance)

        added = []
        for line in lines:
            running_balance = running_balance + _dec(line.credit) - _dec(line.debit)
            result = db.execute(text("""
                INSERT INTO bank_statement_lines (
                    reconciliation_id, transaction_date, description, reference, 
                    debit, credit, balance, is_reconciled
                ) VALUES (:rid, :date, :desc, :ref, :deb, :cred, :bal, FALSE)
                RETURNING id
            """), {
                "rid": id, "date": line.transaction_date, "desc": line.description,
                "ref": line.reference, "deb": line.debit, "cred": line.credit,
                "bal": float(running_balance.quantize(_D2, ROUND_HALF_UP))
            })
            added.append(result.scalar())

        return {"message": i18n_message("reconciliation_lines_imported", request), "line_ids": added, "imported_count": len(added)}


# ──────── AUTO RECONCILIATION ────────

@router.post("/{id}/auto-match", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def auto_match(request: Request, id: int, tolerance_days: int = 3, current_user: dict = Depends(get_current_user)):
    """مطابقة تلقائية بناءً على المبلغ والتاريخ"""
    with transactional(current_user.company_id) as db:
        rec_info = db.execute(text("""
            SELECT r.status, t.gl_account_id, r.statement_date, r.branch_id,
                   COALESCE(r.tolerance_amount, 0) AS tolerance_amount
            FROM bank_reconciliations r
            JOIN treasury_accounts t ON r.treasury_account_id = t.id
            WHERE r.id = :id
        """), {"id": id}).fetchone()

        if not rec_info:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec_info.status != 'draft':
            raise HTTPException(**http_error(400, "reconciliation_approved_no_match", request))

        # TREAS-F4: per-reconciliation absolute tolerance (0 = exact match)
        amt_tol = _dec(rec_info.tolerance_amount)
        if amt_tol < 0:
            amt_tol = Decimal("0")

        # Get unmatched statement lines
        stmt_lines = db.execute(text("""
            SELECT id, transaction_date, debit, credit 
            FROM bank_statement_lines 
            WHERE reconciliation_id = :id AND is_reconciled = FALSE
            ORDER BY transaction_date
        """), {"id": id}).fetchall()

        # Get unmatched ledger entries (filtered by branch to prevent cross-branch matching)
        branch_filter = ""
        ledger_params = {"gl_id": rec_info.gl_account_id, "stmt_date": rec_info.statement_date}
        if rec_info.branch_id:
            branch_filter = "AND je.branch_id = :branch_id"
            ledger_params["branch_id"] = rec_info.branch_id

        ledger = db.execute(text(f"""
            SELECT jl.id, je.entry_date, jl.debit, jl.credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE jl.account_id = :gl_id
            AND (jl.is_reconciled = FALSE OR jl.is_reconciled IS NULL)
            AND je.status = 'posted'
            AND je.entry_date <= :stmt_date
            {branch_filter}
            ORDER BY je.entry_date
            FOR UPDATE OF jl SKIP LOCKED
        """), ledger_params).fetchall()

        matched_stmt_ids = set()
        matched_jl_ids = set()
        matches = []

        for sl in stmt_lines:
            if sl.id in matched_stmt_ids:
                continue

            sl_debit = _dec(sl.debit)
            sl_credit = _dec(sl.credit)
            sl_date = sl.transaction_date

            for jl in ledger:
                if jl.id in matched_jl_ids:
                    continue

                jl_debit = _dec(jl.debit)
                jl_credit = _dec(jl.credit)
                jl_date = jl.entry_date

                # Check date tolerance \u2014 T10.2 #256: previously a non
                # ``%Y-%m-%d`` string silently produced ``day_diff=999``
                # which excluded the row from matching with no signal.
                # We now try ISO + a few common bank formats and log a
                # warning if none parse, so ops can spot the data issue.
                def _coerce_date(v):
                    if v is None:
                        return None
                    if isinstance(v, datetime):
                        return v.date()
                    if isinstance(v, date):
                        return v
                    if isinstance(v, str):
                        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                return datetime.strptime(v[:len(fmt)+5].strip(), fmt).date()
                            except ValueError:
                                continue
                    return None

                sl_d = _coerce_date(sl_date)
                jl_d = _coerce_date(jl_date)
                if sl_d and jl_d:
                    day_diff = abs((sl_d - jl_d).days)
                    if day_diff > tolerance_days:
                        continue
                else:
                    logger.warning(
                        "auto_match: unparseable date sl=%r jl=%r \u2014 row skipped",
                        sl_date, jl_date,
                    )
                    continue

                # Amount matching with TREAS-F4 tolerance: bank debit=withdrawal
                # matches GL credit, bank credit=deposit matches GL debit.
                amount_match = False
                if sl_debit > 0 and jl_credit > 0 and abs(sl_debit - jl_credit) <= amt_tol:
                    amount_match = True
                elif sl_credit > 0 and jl_debit > 0 and abs(sl_credit - jl_debit) <= amt_tol:
                    amount_match = True

                if amount_match:
                    # Mark as matched
                    db.execute(text("""
                        UPDATE bank_statement_lines 
                        SET is_reconciled = TRUE, matched_journal_line_id = :jid 
                        WHERE id = :sid
                    """), {"jid": jl.id, "sid": sl.id})

                    db.execute(text("""
                        UPDATE journal_lines 
                        SET is_reconciled = TRUE, reconciliation_id = :rid 
                        WHERE id = :jid
                    """), {"rid": id, "jid": jl.id})

                    matched_stmt_ids.add(sl.id)
                    matched_jl_ids.add(jl.id)
                    matches.append({
                        "statement_line_id": sl.id,
                        "journal_line_id": jl.id,
                        "amount": float((sl_debit if sl_debit > 0 else sl_credit).quantize(_D2, ROUND_HALF_UP)),
                    })
                    break  # Move to next statement line

        return {
            "matched_count": len(matches),
            "matches": matches,
            "remaining_unmatched": len(stmt_lines) - len(matches),
            "message": i18n_message("reconciliation_auto_matched", request)
        }

@router.delete("/{id}/lines/{line_id}", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def delete_statement_line(request: Request, id: int, line_id: int, current_user: dict = Depends(get_current_user)):
    """حذف سطر من كشف الحساب البنكي"""
    with transactional(current_user.company_id) as db:
        rec = db.execute(text("SELECT status FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
        if not rec:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec.status != 'draft':
            raise HTTPException(**http_error(400, "reconciliation_approved_no_delete_lines", request))

        line = db.execute(text("""
            SELECT is_reconciled, matched_journal_line_id 
            FROM bank_statement_lines WHERE id = :lid AND reconciliation_id = :rid
        """), {"lid": line_id, "rid": id}).fetchone()
        
        if not line:
            raise HTTPException(**http_error(404, "line_not_found"))
            
        if line.is_reconciled and line.matched_journal_line_id:
            db.execute(text("""
                UPDATE journal_lines SET is_reconciled = FALSE, reconciliation_id = NULL
                WHERE id = :jid
            """), {"jid": line.matched_journal_line_id})
        
        db.execute(text("DELETE FROM bank_statement_lines WHERE id = :lid"), {"lid": line_id})
        return {"message": i18n_message("reconciliation_line_deleted", request)}

@router.get("/{id}/ledger", dependencies=[Depends(require_permission("reconciliation.view"))], response_model=List[Dict[str, Any]])
def get_ledger_entries(id: int, current_user: dict = Depends(get_current_user)):
    """جلب قيود النظام غير المطابقة لهذا الحساب"""
    with transactional(current_user.company_id) as db:
        rec_info = db.execute(text("""
            SELECT t.gl_account_id, r.statement_date
            FROM bank_reconciliations r
            JOIN treasury_accounts t ON r.treasury_account_id = t.id
            WHERE r.id = :id
        """), {"id": id}).fetchone()
        
        if not rec_info:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))

        gl_id = rec_info.gl_account_id
        stmt_date = rec_info.statement_date
        
        ledger = db.execute(text("""
            SELECT jl.id, je.entry_date, je.entry_number, je.description as header_desc, 
                   jl.description as line_desc, jl.debit, jl.credit,
                   jl.currency, jl.amount_currency
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            WHERE jl.account_id = :gl_id
            AND (jl.is_reconciled = FALSE OR jl.is_reconciled IS NULL)
            AND je.status = 'posted'
            AND je.entry_date <= :stmt_date
            ORDER BY je.entry_date, je.id
        """), {"gl_id": gl_id, "stmt_date": stmt_date}).fetchall()
        
        return [dict(r._mapping) for r in ledger]

@router.post("/{id}/match", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def match_transaction(request: Request, id: int, match: MatchRequest, current_user: dict = Depends(get_current_user)):
    """مطابقة سطر بنكي مع قيد محاسبي"""
    with transactional(current_user.company_id) as db:
        rec_status = db.execute(text("SELECT status FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
        if not rec_status:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec_status.status != 'draft':
            raise HTTPException(**http_error(400, "reconciliation_approved_no_match", request))

        sl = db.execute(text("""
            SELECT debit, credit, is_reconciled 
            FROM bank_statement_lines WHERE id = :id AND reconciliation_id = :rid
        """), {"id": match.statement_line_id, "rid": id}).fetchone()
        
        jl = db.execute(text("""
            SELECT debit, credit, is_reconciled 
            FROM journal_lines WHERE id = :id
        """), {"id": match.journal_line_id}).fetchone()
        
        if not sl or not jl:
             raise HTTPException(**http_error(404, "reconciliation_lines_not_found", request))
        
        if sl.is_reconciled:
            raise HTTPException(**http_error(400, "bank_statement_line_already_matched", request))
        if jl.is_reconciled:
            raise HTTPException(**http_error(400, "journal_entry_matched_in_another_reconciliation", request))
             
        sl_debit = _dec(sl.debit)
        sl_credit = _dec(sl.credit)
        jl_debit = _dec(jl.debit)
        jl_credit = _dec(jl.credit)
        
        # Bank withdrawal (debit) matches GL credit (asset decrease)
        # Bank deposit (credit) matches GL debit (asset increase)
        if sl_debit > 0:
            if abs(sl_debit - jl_credit) > _D2:
                raise HTTPException(
                    status_code=400, 
                    detail=f"المبالغ غير متطابقة. سحب بنكي: {float(sl_debit):,.2f} ≠ قيد دائن: {float(jl_credit):,.2f}"
                )
        elif sl_credit > 0:
            if abs(sl_credit - jl_debit) > _D2:
                raise HTTPException(
                    status_code=400, 
                    detail=f"المبالغ غير متطابقة. إيداع بنكي: {float(sl_credit):,.2f} ≠ قيد مدين: {float(jl_debit):,.2f}"
                )
        else:
            raise HTTPException(**http_error(400, "bank_statement_line_has_no_amount", request))

        db.execute(text("""
            UPDATE bank_statement_lines 
            SET is_reconciled = TRUE, matched_journal_line_id = :jid 
            WHERE id = :sid
        """), {"jid": match.journal_line_id, "sid": match.statement_line_id})
        
        db.execute(text("""
            UPDATE journal_lines 
            SET is_reconciled = TRUE, reconciliation_id = :rid 
            WHERE id = :jid
        """), {"rid": id, "jid": match.journal_line_id})
        
        return {"success": True, "message": i18n_message("reconciliation_matched", request)}

@router.post("/{id}/unmatch", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def unmatch_transaction(request: Request, id: int, data: UnmatchRequest, current_user: dict = Depends(get_current_user)):
    """إلغاء مطابقة سطر بنكي"""
    with transactional(current_user.company_id) as db:
        rec_status = db.execute(text("SELECT status FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
        if not rec_status:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))
        if rec_status.status != 'draft':
            raise HTTPException(**http_error(400, "reconciliation_approved_no_unmatch", request))

        sl = db.execute(text("""
            SELECT matched_journal_line_id, is_reconciled 
            FROM bank_statement_lines WHERE id = :sid AND reconciliation_id = :rid
        """), {"sid": data.statement_line_id, "rid": id}).fetchone()
        
        if not sl:
            raise HTTPException(**http_error(404, "line_not_found"))
        if not sl.is_reconciled:
            raise HTTPException(**http_error(400, "reconciliation_line_not_matched", request))

        if sl.matched_journal_line_id:
            db.execute(text("""
                UPDATE journal_lines SET is_reconciled = FALSE, reconciliation_id = NULL
                WHERE id = :jid
            """), {"jid": sl.matched_journal_line_id})

        db.execute(text("""
            UPDATE bank_statement_lines 
            SET is_reconciled = FALSE, matched_journal_line_id = NULL
            WHERE id = :sid
        """), {"sid": data.statement_line_id})
        
        return {"success": True, "message": i18n_message("reconciliation_unmatched", request)}

@router.delete("/{id}", dependencies=[Depends(require_permission("reconciliation.create"))], response_model=Dict[str, Any])
def delete_reconciliation(request: Request, id: int, current_user: dict = Depends(get_current_user)):
    """حذف تسوية بنكية (مسودة فقط)"""
    with transactional(current_user.company_id) as db:
        try:
            rec = db.execute(text("SELECT status FROM bank_reconciliations WHERE id = :id"), {"id": id}).fetchone()
            if not rec:
                raise HTTPException(**http_error(404, "reconciliation_not_found"))
            
            if rec.status != 'draft':
                raise HTTPException(**http_error(400, "reconciliation_approved_cannot_delete", request))
            
            # Un-reconcile any matched journal lines first
            db.execute(text("""
                UPDATE journal_lines SET is_reconciled = FALSE, reconciliation_id = NULL
                WHERE reconciliation_id = :id
            """), {"id": id})
            
            db.execute(text("DELETE FROM bank_statement_lines WHERE reconciliation_id = :id"), {"id": id})
            db.execute(text("DELETE FROM bank_reconciliations WHERE id = :id"), {"id": id})
            return {"message": i18n_message("reconciliation_deleted_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            raise HTTPException(**http_error(500, "reconciliation_delete_error", request))


@router.post("/{id}/finalize", dependencies=[Depends(require_sensitive_permission("finance.reconciliation.finalize", critical=True))], response_model=Dict[str, Any])
def finalize_reconciliation(request: Request, id: int, current_user: dict = Depends(get_current_user)):
    """اعتماد التسوية وإغلاقها"""
    with transactional(current_user.company_id) as db:
        rec = db.execute(text("""
            SELECT start_balance, end_balance, status, branch_id 
            FROM bank_reconciliations WHERE id = :id
        """), {"id": id}).fetchone()
        
        if not rec:
            raise HTTPException(**http_error(404, "reconciliation_not_found"))

        # Branch access check
        if rec.branch_id:
            validate_branch_access(current_user, rec.branch_id)
        
        if rec.status == 'posted':
            raise HTTPException(**http_error(400, "reconciliation_already_approved", request))
        
        unmatched_count = db.execute(text("""
            SELECT COUNT(*) FROM bank_statement_lines 
            WHERE reconciliation_id = :id AND (is_reconciled = FALSE OR is_reconciled IS NULL)
        """), {"id": id}).scalar() or 0
        
        if unmatched_count > 0:
            raise HTTPException(
                status_code=400, 
                detail=f"يوجد {unmatched_count} سطر غير مطابق. يجب مطابقة جميع الأسطر قبل الاعتماد"
            )
        
        # Net = credits (in) - debits (out)
        calc = db.execute(text("""
            SELECT COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)
            FROM bank_statement_lines 
            WHERE reconciliation_id = :id AND is_reconciled = TRUE
        """), {"id": id}).scalar() or 0
        
        calculated_end = _dec(rec.start_balance) + _dec(calc)

        # T030: Read configurable reconciliation tolerance from company_settings
        tolerance = Decimal('1.00')
        try:
            tol_row = db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'reconciliation_tolerance' LIMIT 1"
            )).fetchone()
            if tol_row and tol_row.setting_value:
                tolerance = _dec(tol_row.setting_value)
            else:
                # Seed default on first read
                db.execute(text("""
                    INSERT INTO company_settings (setting_key, setting_value, description)
                    VALUES ('reconciliation_tolerance', '1.00', 'حد التفاوت المسموح في تسوية البنك')
                    ON CONFLICT (setting_key) DO NOTHING
                """))
        except Exception:
            pass  # Fall back to default 1.00 if company_settings unavailable

        difference = abs(calculated_end - _dec(rec.end_balance))
        if difference > tolerance:
            # T066: Return structured drift report for frontend dialog
            unmatched = db.execute(text("""
                SELECT id, description, COALESCE(credit, 0) - COALESCE(debit, 0) AS amount
                  FROM bank_statement_lines
                 WHERE reconciliation_id = :id AND (is_reconciled = FALSE OR is_reconciled IS NULL)
                 ORDER BY id
            """), {"id": id}).fetchall()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "reconciliation_drift",
                    "gl_total": float(calculated_end),
                    "bank_total": float(_dec(rec.end_balance)),
                    "difference": float(difference),
                    "tolerance": float(tolerance),
                    "unmatched_lines": [
                        {"id": r.id, "description": r.description, "amount": float(r.amount)}
                        for r in unmatched
                    ],
                },
            )
             
        db.execute(text("""
            UPDATE bank_reconciliations SET status = 'posted', updated_at = NOW() 
            WHERE id = :id
        """), {"id": id})
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="reconciliation.finalize",
                     resource_type="bank_reconciliation", resource_id=str(id),
                     details={"end_balance": float(_dec(rec.end_balance))})
        return {"success": True, "message": i18n_message("reconciliation_approved", request)}
