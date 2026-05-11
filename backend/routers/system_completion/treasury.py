"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
import io
import csv
import json
import logging
import subprocess
import os
from database import get_db_connection, engine as system_engine
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.fiscal_lock import create_fiscal_lock_table, check_fiscal_period_open
from utils.duplicate_detection import find_duplicate_parties, find_duplicate_products
from services.gl_service import create_journal_entry

logger = logging.getLogger(__name__)

def _u(current_user, key, default=None):
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)

router = APIRouter()

@router.post("/treasury/bank-import", dependencies=[Depends(require_permission("accounting.manage"))],
             tags=["Treasury"], response_model=Dict[str, Any])
async def import_bank_statement(
    request: Request,
    file: UploadFile = File(...),
    bank_account_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    استيراد كشف حساب بنكي من ملف CSV
    Expected columns: date, description, reference, debit, credit, balance
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            if not file.filename.lower().endswith(('.csv', '.txt')):
                raise HTTPException(**http_error(400, "csv_file_required", request))
    
            content = await file.read()
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                text_content = content.decode('windows-1256')  # Arabic Windows encoding
    
            reader = csv.reader(io.StringIO(text_content))
            rows_list = list(reader)
    
            if len(rows_list) < 2:
                raise HTTPException(**http_error(400, "file_empty", request))
    
            # Auto-detect header
            header = [h.strip().lower() for h in rows_list[0]]
    
            # Map common column names
            col_map = {}
            for i, h in enumerate(header):
                if h in ('date', 'تاريخ', 'value_date', 'transaction_date'):
                    col_map['date'] = i
                elif h in ('description', 'details', 'وصف', 'البيان', 'narrative'):
                    col_map['description'] = i
                elif h in ('reference', 'ref', 'مرجع', 'cheque_no', 'check'):
                    col_map['reference'] = i
                elif h in ('debit', 'مدين', 'withdrawal', 'سحب'):
                    col_map['debit'] = i
                elif h in ('credit', 'دائن', 'deposit', 'إيداع'):
                    col_map['credit'] = i
                elif h in ('balance', 'رصيد', 'running_balance'):
                    col_map['balance'] = i
                elif h in ('amount', 'مبلغ'):
                    col_map['amount'] = i
    
            if 'date' not in col_map:
                raise HTTPException(**http_error(400, "date_column_not_found", request))
    
            # Create batch
            batch_result = db.execute(text("""
                INSERT INTO bank_import_batches (
                    file_name, bank_account_id, total_lines, status, uploaded_by
                ) VALUES (:fn, :baid, :total, 'pending', :uid)
                RETURNING id
            """), {
                "fn": file.filename,
                "baid": bank_account_id,
                "total": len(rows_list) - 1,
                "uid": user_id
            })
            batch_id = batch_result.fetchone()[0]
    
            # Parse lines
            imported = 0
            errors = []
            for idx, row in enumerate(rows_list[1:], start=2):
                try:
                    if not row or all(not cell.strip() for cell in row):
                        continue
    
                    txn_date = row[col_map['date']].strip() if 'date' in col_map else None
                    description = row[col_map['description']].strip() if 'description' in col_map and col_map['description'] < len(row) else ''
                    reference = row[col_map['reference']].strip() if 'reference' in col_map and col_map['reference'] < len(row) else ''
    
                    debit = 0
                    credit = 0
                    if 'debit' in col_map and col_map['debit'] < len(row):
                        val = row[col_map['debit']].strip().replace(',', '')
                        debit = float(val) if val else 0
                    if 'credit' in col_map and col_map['credit'] < len(row):
                        val = row[col_map['credit']].strip().replace(',', '')
                        credit = float(val) if val else 0
                    if 'amount' in col_map and col_map['amount'] < len(row) and debit == 0 and credit == 0:
                        val = row[col_map['amount']].strip().replace(',', '')
                        amount = float(val) if val else 0
                        if amount > 0:
                            credit = amount
                        else:
                            debit = abs(amount)
    
                    balance = 0
                    if 'balance' in col_map and col_map['balance'] < len(row):
                        val = row[col_map['balance']].strip().replace(',', '')
                        balance = float(val) if val else 0
    
                    # Parse date (try multiple formats)
                    parsed_date = None
                    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                        try:
                            parsed_date = datetime.strptime(txn_date, fmt).date()
                            break
                        except (ValueError, TypeError):
                            continue
    
                    if not parsed_date:
                        errors.append(f"سطر {idx}: تاريخ غير صالح '{txn_date}'")
                        continue
    
                    db.execute(text("""
                        INSERT INTO bank_import_lines (
                            batch_id, line_number, transaction_date, description,
                            reference, debit, credit, balance, status
                        ) VALUES (:bid, :ln, :td, :desc, :ref, :dr, :cr, :bal, 'unmatched')
                    """), {
                        "bid": batch_id, "ln": idx - 1, "td": parsed_date,
                        "desc": description, "ref": reference,
                        "dr": debit, "cr": credit, "bal": balance
                    })
                    imported += 1
    
                except Exception:
                    logger.warning("Bank import line %d failed", idx, exc_info=True)
                    errors.append(f"سطر {idx}: خطأ في البيانات")
    
            # Update batch
            db.execute(text("""
                UPDATE bank_import_batches SET
                    imported_lines = :imp, status = 'imported',
                    total_debit = (SELECT COALESCE(SUM(debit), 0) FROM bank_import_lines WHERE batch_id = :bid),
                    total_credit = (SELECT COALESCE(SUM(credit), 0) FROM bank_import_lines WHERE batch_id = :bid)
                WHERE id = :bid
            """), {"imp": imported, "bid": batch_id})
    
    
            return {
                "batch_id": batch_id,
                "file_name": file.filename,
                "total_lines": len(rows_list) - 1,
                "imported": imported,
                "errors": errors[:20],
                "message": i18n_message("bank_transactions_imported", request)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/treasury/bank-import/batches", dependencies=[Depends(require_permission("accounting.view"))],
            tags=["Treasury"], response_model=List[Dict[str, Any]])
def list_bank_import_batches(current_user: dict = Depends(get_current_user)):
    """List Bank Import Batches."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        rows = db.execute(text("""
            SELECT bib.*, cu.full_name as uploaded_by_name
            FROM bank_import_batches bib
            LEFT JOIN company_users cu ON cu.id = bib.uploaded_by
            ORDER BY bib.id DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/treasury/bank-import/{batch_id}/lines",
            dependencies=[Depends(require_permission("accounting.view"))], tags=["Treasury"], response_model=List[Dict[str, Any]])
def get_bank_import_lines(batch_id: int, status_filter: Optional[str] = None,
                          current_user: dict = Depends(get_current_user)):
    """Get Bank Import Lines."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        query = "SELECT * FROM bank_import_lines WHERE batch_id = :bid"
        params = {"bid": batch_id}
        if status_filter:
            query += " AND status = :st"
            params["st"] = status_filter
        query += " ORDER BY line_number"

        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/treasury/bank-import/{batch_id}/auto-match",
             dependencies=[Depends(require_permission("accounting.manage"))], tags=["Treasury"], response_model=Dict[str, Any])
def auto_match_bank_lines(request: Request, batch_id: int, current_user: dict = Depends(get_current_user)):
    """مطابقة تلقائية للحركات البنكية مع المعاملات الموجودة"""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        try:
            lines = db.execute(text("""
                SELECT * FROM bank_import_lines
                WHERE batch_id = :bid AND status = 'unmatched'
            """), {"bid": batch_id}).fetchall()
    
            matched = 0
            for line in lines:
                amount = float(line.debit or 0) or float(line.credit or 0)
                ref = line.reference or ''
    
                # Try matching by reference number and amount
                match = None
                if ref:
                    # Match against payments/receipts
                    match = db.execute(text("""
                        SELECT 'payment' as type, id, reference_number, amount
                        FROM payments
                        WHERE (reference_number = :ref OR check_number = :ref)
                        AND ABS(amount - :amt) < 0.01
                        LIMIT 1
                    """), {"ref": ref, "amt": amount}).fetchone()
    
                    if not match:
                        # Match against invoices
                        match = db.execute(text("""
                            SELECT 'invoice' as type, id, invoice_number as reference_number, total_amount as amount
                            FROM invoices
                            WHERE invoice_number = :ref
                            AND ABS(total_amount - :amt) < 0.01
                            LIMIT 1
                        """), {"ref": ref, "amt": amount}).fetchone()
    
                if not match and amount > 0:
                    # Try matching by amount and date (±1 day)
                    match = db.execute(text("""
                        SELECT 'payment' as type, id, reference_number, amount
                        FROM payments
                        WHERE ABS(amount - :amt) < 0.01
                        AND payment_date BETWEEN :d1 AND :d2
                        AND id NOT IN (
                            SELECT COALESCE(matched_transaction_id, 0)
                            FROM bank_import_lines
                            WHERE batch_id = :bid AND status = 'matched'
                        )
                        LIMIT 1
                    """), {
                        "amt": amount,
                        "d1": line.transaction_date,
                        "d2": line.transaction_date,
                        "bid": batch_id
                    }).fetchone()
    
                if match:
                    db.execute(text("""
                        UPDATE bank_import_lines SET
                            status = 'matched',
                            matched_transaction_id = :tid,
                            notes = :notes
                        WHERE id = :lid
                    """), {
                        "tid": match.id,
                        "notes": f"Matched to {match.type} #{match.reference_number}",
                        "lid": line.id
                    })
                    matched += 1
    
            db.execute(text("""
                UPDATE bank_import_batches SET
                    matched_lines = :mc,
                    status = CASE WHEN :mc = total_lines THEN 'fully_matched'
                             WHEN :mc > 0 THEN 'partially_matched'
                             ELSE status END
                WHERE id = :bid
            """), {"mc": matched, "bid": batch_id})
    
    
            return {
                "total_unmatched": len(lines),
                "matched": matched,
                "remaining": len(lines) - matched,
                "message": i18n_message("bank_transactions_matched", request)
            }
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ═══════════════════════════════════════════════════════════════════════════════
#  2. ZAKAT CALCULATOR
#     حاسبة الزكاة — حساب الزكاة الشرعي للشركات
#     ⚠️ Islamic Zakat — applies to Muslim-majority countries (SA, AE, etc.)
#     Non-Islamic countries may ignore this module.
#     Frontend should show/hide based on company settings.
#
#     الطرق المدعومة:
#     1. صافي الملكية (ZATCA) — المعتمدة نظامياً في السعودية (الافتراضية)
#     2. صافي الأصول المتداولة — النقد + عروض التجارة + المدينون المرجوون - الديون الحالة
#     3. الربح المعدل — للتقدير
#
#     المراجع: ZATCA، AAOIFI، بيت الزكاة الكويتي
# ═══════════════════════════════════════════════════════════════════════════════

