"""
AMAN ERP — WPS Export, Saudization Tracking, End of Service Settlement
نظام حماية الأجور (WPS) — السعودة — مكافأة نهاية الخدمة
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import io
import csv
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, check_permission
from utils.audit import log_activity
from utils.masking import mask_pii
from utils.accounting import (
    get_mapped_account_id,
    get_base_currency
)
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open

router = APIRouter(prefix="/hr", tags=["HR - WPS & Compliance"])
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')

def _dec(v):
    """Convert a value to Decimal safely (None → 0)."""
    return Decimal(str(v or 0))

# ────────────────────────────────────────────────────────────────────────────
# ⚠️  REGION NOTE — الملاحظات الإقليمية
# The following features are REGION-SPECIFIC and should only appear in
# the UI when the company's country_code matches:
#
#   🇸🇦 WPS Export (SIF)         → Saudi Arabia only (country_code = 'SA')
#   🇸🇦 Saudization / Nitaqat   → Saudi Arabia only (country_code = 'SA')
#   🇸🇦 GOSI Integration        → Saudi Arabia only (country_code = 'SA')
#   🌍 End-of-Service (EOS)     → Follows Saudi labor law by default;
#                                 other countries may have different rules.
#
# The backend returns data regardless of country. The FRONTEND is responsible
# for showing/hiding these menu items based on the company's country_code.
# Each endpoint returns a 'region' field so the frontend can filter.
# ────────────────────────────────────────────────────────────────────────────

REGION_SA = "SA"  # Saudi Arabia region code


# ═══════════════════════════════════════════════════════════════════════════════
#  WPS — Wages Protection System (Saudi Format - SIF)
#  ⚠️ Saudi Arabia only — نظام حماية الأجور خاص بالسعودية
# ═══════════════════════════════════════════════════════════════════════════════

class WPSExportRequest(BaseModel):
    period_id: int
    bank_code: Optional[str] = None  # IBAN prefix
    branch_id: Optional[int] = None
    format: Optional[str] = "sif"   # 'sif' = SAMA fixed-width (default), 'csv' = legacy spreadsheet


# ── SAMA WPS-SIF fixed-width helpers ───────────────────────────────────────
# Reference: SAMA WPS Specification v3.0 (Saudi Arabian Monetary Authority).
# All fields are space-padded right or zero-padded left depending on type.

def _sif_alpha(value: str, width: int) -> str:
    """Right-pad alphanumeric with spaces, truncate if longer."""
    s = (value or "")
    # Strip non-ASCII (SAMA spec uses ASCII transliteration for names).
    s = s.encode("ascii", "ignore").decode("ascii")
    return (s.upper())[:width].ljust(width, " ")


def _sif_num(value, width: int, decimals: int = 0) -> str:
    """Left-pad numeric with zeros. Amount fields: decimals=2 (no decimal point — implicit)."""
    if decimals:
        d = (Decimal(str(value or 0)).quantize(Decimal(10) ** -decimals, ROUND_HALF_UP))
        # implicit decimals → multiply
        n = int((d * (Decimal(10) ** decimals)).quantize(Decimal('1'), ROUND_HALF_UP))
    else:
        n = int(Decimal(str(value or 0)).quantize(Decimal('1'), ROUND_HALF_UP))
    if n < 0:
        n = 0
    return str(n).zfill(width)[:width]


def _validate_mol_establishment_id(value: str) -> str:
    mol_id = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(mol_id) != 10 or mol_id == "0" * 10:
        raise HTTPException(**http_error(400, "mol_establishment_id_must_be_a_real_10_digit_value", request))
    return mol_id


@router.post("/wps/export", dependencies=[Depends(require_permission(["hr.manage", "hr.pii"]))])
def export_wps_file(body: WPSExportRequest, request: Request, current_user=Depends(get_current_user)):
    """
    تصدير ملف WPS (نظام حماية الأجور) بتنسيق SIF
    Saudi Bank SIF format compatible with GOSI and MOL
    
    SIF Record Format (per line):
    - EDR: Employer Data Record (header)
    - FDR: File Data Record (details per employee)
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            # Get payroll period
            period = db.execute(text("""
                SELECT * FROM payroll_periods WHERE id = :pid
            """), {"pid": body.period_id}).fetchone()
            if not period:
                raise HTTPException(**http_error(404, "payroll_period_not_found"))
            if period.status != 'posted':
                raise HTTPException(**http_error(400, "wps_must_post_payroll_first", request))
    
            # Get company info
            company = db.execute(text("""
                SELECT c.company_name, c.mol_establishment_id, c.bank_short_name,
                       c.bank_routing, c.bank_account_iban
                FROM company_info c LIMIT 1
            """)).fetchone()
    
            if body.branch_id:
                body.branch_id = validate_branch_access(current_user, body.branch_id)
    
            # Get payroll entries with employee bank details
            wps_query = """
                SELECT pe.*,
                       e.first_name, e.last_name, e.employee_code,
                       e.national_id, e.bank_name, e.bank_account_number,
                       e.iban_number, e.id_number, e.nationality,
                       COALESCE(e.nationality, 'SA') as nat_code
                FROM payroll_entries pe
                JOIN employees e ON pe.employee_id = e.id
                WHERE pe.period_id = :pid AND pe.net_salary > 0
            """
            wps_params = {"pid": body.period_id}
            if body.branch_id:
                wps_query += " AND e.branch_id = :bid"
                wps_params["bid"] = body.branch_id
            wps_query += " ORDER BY e.employee_code"
            entries = db.execute(text(wps_query), wps_params).fetchall()
    
            if not entries:
                raise HTTPException(**http_error(400, "wps_no_payroll_to_export", request))
    
            # ── Build SIF File ──
            lines = []
            total_amount = Decimal('0')
            record_count = 0
            month_str = period.start_date.strftime("%m%Y") if period.start_date else datetime.now().strftime("%m%Y")
    
            # EDR — Employer Data Record (header)
            mol_id = _validate_mol_establishment_id(getattr(company, 'mol_establishment_id', '') if company else '')
            employer_bank = body.bank_code or (getattr(company, 'bank_short_name', 'RJHI') if company else 'RJHI')
            employer_iban = getattr(company, 'bank_account_iban', '') if company else ''
    
            for entry in entries:
                net = _dec(entry.net_salary)
                total_amount += net
                record_count += 1
    
                iban = entry.iban_number or entry.bank_account_number or ''
                nat_id = entry.national_id or entry.id_number or ''
                emp_name = f"{entry.first_name} {entry.last_name}".strip()
    
                other_earnings = (_dec(entry.other_allowances) + _dec(entry.overtime_amount)).quantize(_D2, ROUND_HALF_UP)
    
                # SIF format fields
                lines.append({
                    "employee_code": entry.employee_code or str(entry.employee_id),
                    "employee_name": emp_name,
                    "national_id": nat_id,
                    "iban": iban,
                    "bank_code": entry.bank_name or '',
                    "net_salary": str(net.quantize(_D2, ROUND_HALF_UP)),
                    "basic_salary": str(_dec(entry.basic_salary).quantize(_D2, ROUND_HALF_UP)),
                    "housing_allowance": str(_dec(entry.housing_allowance).quantize(_D2, ROUND_HALF_UP)),
                    "other_earnings": str(other_earnings),
                    "deductions": str(_dec(entry.deductions).quantize(_D2, ROUND_HALF_UP)),
                    "nationality": entry.nat_code or 'SA'
                })
    
            # ── Build output ──
            export_format = (body.format or "sif").lower()
    
            if export_format == "sif":
                # SAMA WPS-SIF fixed-width format (bank-acceptance ready).
                #
                # EDR (Employer Data Record) — 100 chars:
                #   01..02  RecordType   "01"
                #   03..12  MOL ID         (10 numeric)
                #   13..16  Bank short     (4 alpha, e.g. RJHI)
                #   17..40  Employer IBAN  (24 alpha)
                #   41..46  Period YYYYMM (6 numeric)
                #   47..52  Total records  (6 numeric)
                #   53..67  Total amount  15 num, 2 implicit decimals
                #   68..100 Filler         (33 spaces)
                edr = (
                    "01"
                    + _sif_num(mol_id, 10)
                    + _sif_alpha(employer_bank, 4)
                    + _sif_alpha(employer_iban, 24)
                    + _sif_num(period.start_date.strftime("%Y%m") if period.start_date
                               else datetime.now().strftime("%Y%m"), 6)
                    + _sif_num(record_count, 6)
                    + _sif_num(total_amount, 15, decimals=2)
                    + " " * 33
                )
                sif_lines = [edr]
    
                # FDR (File Data Record) — 100 chars per employee:
                #   01..02  RecordType   "02"
                #   03..12  Employee ID  (10 numeric — national ID / iqama)
                #   13..36  Employee IBAN (24 alpha)
                #   37..40  Bank short    (4 alpha)
                #   41..55  Basic salary  15n,2d
                #   56..70  Housing       15n,2d
                #   71..85  Other earnings 15n,2d
                #   86..98  Deductions    13n,2d
                #   99..100 Filler        (2 spaces)
                for line in lines:
                    fdr = (
                        "02"
                        + _sif_num(line["national_id"], 10)
                        + _sif_alpha(line["iban"], 24)
                        + _sif_alpha(line["bank_code"], 4)
                        + _sif_num(line["basic_salary"], 15, decimals=2)
                        + _sif_num(line["housing_allowance"], 15, decimals=2)
                        + _sif_num(line["other_earnings"], 15, decimals=2)
                        + _sif_num(line["deductions"], 13, decimals=2)
                        + " " * 2
                    )
                    sif_lines.append(fdr)
    
                sif_content = "\r\n".join(sif_lines) + "\r\n"
                filename = f"WPS_{mol_id}_{month_str}.sif"
                response_body = sif_content
                response_media = "text/plain"
            else:
                # Legacy CSV (operator-readable preview / non-bank consumers).
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow([
                    "File Type", "SIF",
                    "Employer MOL ID", mol_id,
                    "Employer Bank", employer_bank,
                    "Month", month_str,
                    "Total Records", record_count,
                    "Total Amount", str(total_amount.quantize(_D2, ROUND_HALF_UP))
                ])
                writer.writerow([])
                writer.writerow([
                    "Employee Code", "Employee Name", "National/Iqama ID",
                    "IBAN", "Bank Code", "Net Salary",
                    "Basic Salary", "Housing Allowance",
                    "Other Earnings", "Deductions", "Nationality"
                ])
                for line in lines:
                    writer.writerow([
                        line["employee_code"], line["employee_name"],
                        line["national_id"], line["iban"], line["bank_code"],
                        line["net_salary"], line["basic_salary"],
                        line["housing_allowance"], line["other_earnings"],
                        line["deductions"], line["nationality"]
                    ])
                writer.writerow([])
                writer.writerow(["Total", "", "", "", "", str(total_amount.quantize(_D2, ROUND_HALF_UP))])
                response_body = output.getvalue()
                filename = f"WPS_{mol_id}_{month_str}.csv"
                response_media = "text/csv"
    
            # Log export
            user_id = current_user.get("user_id") if isinstance(current_user, dict) else current_user.id
            username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
            log_activity(db, user_id=user_id, username=username, action="wps.export",
                         resource_type="payroll_period", resource_id=body.period_id,
                         details={"period_name": period.name, "records": record_count,
                                  "total": str(total_amount), "format": export_format})

            # T028: Record bank movements for the WPS export
            try:
                from services.payroll.bank_movements import record_payroll_bank_movements
                record_payroll_bank_movements(
                    db,
                    tenant_id=int(company_id),
                    period_id=body.period_id,
                    run_id=0,  # WPS export without explicit run
                    treasury_account_id=0,  # Will be resolved from company settings
                    total_amount=float(total_amount),
                    description=f"WPS export for period {period.name}",
                )
            except Exception as e:
                logger.warning(f"Bank movement recording failed (non-blocking): {e}")

            return Response(
                content=response_body,
                media_type=response_media,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"WPS export error: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/wps/preview/{period_id}", dependencies=[Depends(require_permission("hr.pii"))], response_model=Dict[str, Any])
def preview_wps(period_id: int, branch_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """معاينة بيانات WPS قبل التصدير"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        period = db.execute(text("SELECT * FROM payroll_periods WHERE id = :pid"), {"pid": period_id}).fetchone()
        if not period:
            raise HTTPException(**http_error(404, "payroll_period_not_found"))

        preview_query = """
            SELECT pe.employee_id, pe.basic_salary, pe.housing_allowance,
                   pe.transport_allowance, pe.other_allowances,
                   pe.deductions, pe.net_salary,
                   e.first_name || ' ' || e.last_name as employee_name,
                   e.employee_code, e.national_id, e.iban_number,
                   e.bank_name, e.nationality,
                   CASE WHEN e.iban_number IS NULL OR e.iban_number = ''
                        THEN 'missing_iban' ELSE 'ok' END as iban_status,
                   CASE WHEN e.national_id IS NULL OR e.national_id = ''
                        THEN 'missing_id' ELSE 'ok' END as id_status
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            WHERE pe.period_id = :pid AND pe.net_salary > 0
        """
        preview_params = {"pid": period_id}
        preview_query += branch_scope_filter_from_scope(branch_scope, "e.branch_id", preview_params)
        preview_query += " ORDER BY e.employee_code"
        entries = db.execute(text(preview_query), preview_params).fetchall()

        result = []
        user_perms = current_user.get("permissions", []) if isinstance(current_user, dict) else getattr(current_user, "permissions", []) or []
        has_pii = check_permission(user_perms, "hr.pii")
        for e in entries:
            row = dict(e._mapping)
            if not has_pii:
                row["national_id"] = mask_pii(row.get("national_id"))
                row["iban_number"] = mask_pii(row.get("iban_number"))
            result.append(row)
        warnings = [e for e in result if e.get('iban_status') == 'missing_iban' or e.get('id_status') == 'missing_id']

        return {
            "period": dict(period._mapping),
            "entries": result,
            "total_employees": len(result),
            "total_amount": str(sum(_dec(e.get('net_salary', 0)) for e in result)),
            "warnings": warnings,
            "warnings_count": len(warnings)
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  SAUDIZATION / NITAQAT TRACKING
#  ⚠️ Saudi Arabia only — السعودة ونطاقات خاص بالسعودية
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/saudization/dashboard", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def saudization_dashboard(branch_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """
    لوحة بيانات السعودة — نسبة السعوديين وفئة نطاقات
    Nitaqat bands:
    - بلاتيني (Platinum): >= 40% for most sectors
    - أخضر مرتفع (High Green): >= 26%
    - أخضر منخفض (Low Green): >= 16%
    - أصفر (Yellow): >= 10%
    - أحمر (Red): < 10%
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        try:
            params = {}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "e.branch_id", params)
    
            # Count employees by nationality
            stats = db.execute(text(f"""
                SELECT
                    COUNT(*) as total_employees,
                    COUNT(*) FILTER (WHERE e.status = 'active') as active_employees,
                    COUNT(*) FILTER (WHERE e.status = 'active' AND (
                        LOWER(COALESCE(e.nationality, '')) IN ('sa', 'saudi', 'سعودي', 'saudi arabian')
                        OR COALESCE(e.is_saudi, false) = true
                    )) as saudi_count,
                    COUNT(*) FILTER (WHERE e.status = 'active' AND (
                        LOWER(COALESCE(e.nationality, '')) NOT IN ('sa', 'saudi', 'سعودي', 'saudi arabian', '')
                        AND COALESCE(e.is_saudi, false) = false
                    )) as non_saudi_count
                FROM employees e
                WHERE e.status = 'active' {branch_filter}
            """), params).fetchone()
    
            total = int(stats.active_employees or 0)
            saudi = int(stats.saudi_count or 0)
            non_saudi = int(stats.non_saudi_count or 0)
            pct = round((saudi / total * 100), 1) if total > 0 else 0
    
            # Nitaqat band
            if pct >= 40:
                band = "platinum"
                band_ar = "بلاتيني"
                color = "#8B5CF6"
            elif pct >= 26:
                band = "high_green"
                band_ar = "أخضر مرتفع"
                color = "#059669"
            elif pct >= 16:
                band = "low_green"
                band_ar = "أخضر منخفض"
                color = "#10B981"
            elif pct >= 10:
                band = "yellow"
                band_ar = "أصفر"
                color = "#F59E0B"
            else:
                band = "red"
                band_ar = "أحمر"
                color = "#EF4444"
    
            # Calculate how many saudis needed for next band
            needed_for_next = 0
            next_band = ""
            if band == "red":
                needed_for_next = max(0, int(total * 0.10) - saudi + 1)
                next_band = "أصفر"
            elif band == "yellow":
                needed_for_next = max(0, int(total * 0.16) - saudi + 1)
                next_band = "أخضر منخفض"
            elif band == "low_green":
                needed_for_next = max(0, int(total * 0.26) - saudi + 1)
                next_band = "أخضر مرتفع"
            elif band == "high_green":
                needed_for_next = max(0, int(total * 0.40) - saudi + 1)
                next_band = "بلاتيني"
    
            # Breakdown by department
            dept_breakdown = db.execute(text(f"""
                SELECT d.name as department,
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE
                           LOWER(COALESCE(e.nationality, '')) IN ('sa', 'saudi', 'سعودي')
                           OR COALESCE(e.is_saudi, false) = true
                       ) as saudi,
                       COUNT(*) FILTER (WHERE
                           LOWER(COALESCE(e.nationality, '')) NOT IN ('sa', 'saudi', 'سعودي', '')
                           AND COALESCE(e.is_saudi, false) = false
                       ) as non_saudi
                FROM employees e
                LEFT JOIN departments d ON e.department_id = d.id
                WHERE e.status = 'active' {branch_filter}
                GROUP BY d.name
                ORDER BY total DESC
            """), params).fetchall()
    
            # Nationality breakdown
            nat_breakdown = db.execute(text(f"""
                SELECT COALESCE(e.nationality, 'غير محدد') as nationality,
                       COUNT(*) as count
                FROM employees e
                WHERE e.status = 'active' {branch_filter}
                GROUP BY e.nationality
                ORDER BY count DESC
            """), params).fetchall()
    
            return {
                "total_employees": total,
                "saudi_count": saudi,
                "non_saudi_count": non_saudi,
                "saudization_percentage": pct,
                "nitaqat_band": band,
                "nitaqat_band_ar": band_ar,
                "nitaqat_color": color,
                "needed_for_next_band": needed_for_next,
                "next_band": next_band,
                "department_breakdown": [dict(d._mapping) for d in dept_breakdown],
                "nationality_breakdown": [dict(n._mapping) for n in nat_breakdown]
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/saudization/report", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def saudization_report(branch_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """تقرير السعودة التفصيلي — لكل فرع"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        report_query = """
            SELECT b.id, b.branch_name,
                   COUNT(e.id) as total,
                   COUNT(e.id) FILTER (WHERE
                       LOWER(COALESCE(e.nationality, '')) IN ('sa', 'saudi', 'سعودي')
                       OR COALESCE(e.is_saudi, false) = true
                   ) as saudi,
                   COUNT(e.id) FILTER (WHERE
                       LOWER(COALESCE(e.nationality, '')) NOT IN ('sa', 'saudi', 'سعودي', '')
                       AND COALESCE(e.is_saudi, false) = false
                   ) as non_saudi
            FROM branches b
            LEFT JOIN employees e ON e.branch_id = b.id AND e.status = 'active'
        """
        report_params = {}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "b.id", report_params, prefix="WHERE")
        if branch_filter:
            report_query += f" {branch_filter}"
        report_query += " GROUP BY b.id, b.branch_name ORDER BY b.branch_name"

        branches = db.execute(text(report_query), report_params).fetchall()

        results = []
        for br in branches:
            total = int(br.total or 0)
            saudi = int(br.saudi or 0)
            pct = round((saudi / total * 100), 1) if total > 0 else 0

            if pct >= 40: band = "بلاتيني"
            elif pct >= 26: band = "أخضر مرتفع"
            elif pct >= 16: band = "أخضر منخفض"
            elif pct >= 10: band = "أصفر"
            else: band = "أحمر"

            results.append({
                "branch_id": br.id,
                "branch_name": br.branch_name,
                "total_employees": total,
                "saudi_count": saudi,
                "non_saudi_count": int(br.non_saudi or 0),
                "saudization_percentage": pct,
                "nitaqat_band": band
            })

        return results


# ═══════════════════════════════════════════════════════════════════════════════
#  END OF SERVICE — Settlement with Journal Entry
#  🌍 Global — ينطبق على جميع الدول (حسابات خاصة بكل دولة)
#  Default: Saudi Labor Law Art. 84/85 — يمكن تخصيص القوانين حسب البلد
# ═══════════════════════════════════════════════════════════════════════════════

class EOSSettlementRequest(BaseModel):
    employee_id: int
    termination_date: Optional[str] = None
    termination_reason: str = "termination"  # termination, resignation, retirement, contract_end
    include_vacation_balance: bool = True
    include_pending_salary: bool = True
    additional_deductions: Decimal = Decimal("0")
    notes: Optional[str] = None


@router.post("/end-of-service/settle", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def settle_end_of_service(body: EOSSettlementRequest, request: Request, current_user=Depends(get_current_user)):
    """
    تسوية نهاية الخدمة — إنشاء قيد محاسبي وتسجيل المبلغ
    يشمل: مكافأة نهاية الخدمة + رصيد إجازات + راتب مستحق
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("user_id") if isinstance(current_user, dict) else current_user.id
    with transactional(company_id) as db:
        try:
            emp = db.execute(text("""
                SELECT id, first_name || ' ' || last_name as employee_name,
                       hire_date, salary as basic_salary,
                       COALESCE(housing_allowance, 0) as housing_allowance,
                       COALESCE(transport_allowance, 0) as transport_allowance,
                       annual_leave_entitlement
                FROM employees WHERE id = :eid
            """), {"eid": body.employee_id}).fetchone()
    
            if not emp:
                raise HTTPException(**http_error(404, "employee_not_found"))
    
            from dateutil.relativedelta import relativedelta
    
            term_date = datetime.strptime(body.termination_date, "%Y-%m-%d").date() if body.termination_date else date.today()
            join_date = emp.hire_date
            if not join_date:
                raise HTTPException(**http_error(400, "employment_date_not_set", request))
    
            delta = relativedelta(term_date, join_date)
            total_years = _dec(delta.years) + (_dec(delta.months) / Decimal('12')) + (_dec(delta.days) / Decimal('365.25'))
    
            # Enforce fiscal period lock before any GL posting
            check_fiscal_period_open(db, term_date)
    
            base_salary = _dec(emp.basic_salary)
            total_salary = base_salary + _dec(emp.housing_allowance) + _dec(emp.transport_allowance)
    
            # ── Calculate EOS Gratuity using shared helper (Saudi Labor Law Art. 84/85) ──
            from utils.hr_helpers import calculate_eos_gratuity
            unpaid_days = db.execute(text("""
                SELECT COALESCE(SUM(
                    CASE WHEN leave_type = 'unpaid' AND status = 'approved'
                         THEN (end_date - start_date + 1) ELSE 0 END
                ), 0)
                FROM leave_requests
                WHERE employee_id = :eid
                  AND end_date <= :term_date
            """), {"eid": body.employee_id, "term_date": term_date}).scalar() or 0
            eos = calculate_eos_gratuity(
                total_salary,
                total_years,
                body.termination_reason,
                unpaid_leave_days=int(unpaid_days),
            )
            eos_amount = _dec(eos["final_gratuity"])
    
            # ── Vacation balance ──
            vacation_amount = Decimal('0')
            if body.include_vacation_balance:
                used = db.execute(text("""
                    SELECT COALESCE(SUM(days_requested), 0) FROM leave_requests
                    WHERE employee_id = :eid AND status = 'approved'
                    AND leave_type = 'annual' AND EXTRACT(YEAR FROM start_date) = :y
                """), {"eid": body.employee_id, "y": term_date.year}).scalar() or 0
    
                entitled = _dec(emp.annual_leave_entitlement or 30)
                # Prorate for months worked this year
                months_worked = term_date.month
                prorated = (entitled * Decimal(str(months_worked)) / Decimal('12')).quantize(Decimal('0.1'), ROUND_HALF_UP)
                remaining_days = max(Decimal('0'), prorated - _dec(used))
                daily_rate = total_salary / Decimal('30')
                vacation_amount = (remaining_days * daily_rate).quantize(_D2, ROUND_HALF_UP)
    
            # ── Pending salary ──
            pending_salary = Decimal('0')
            if body.include_pending_salary:
                days_in_month = Decimal('30')  # Standard
                day_of_month = Decimal(str(term_date.day))
                pending_salary = (total_salary * day_of_month / days_in_month).quantize(_D2, ROUND_HALF_UP)
    
            total_settlement = eos_amount + vacation_amount + pending_salary - _dec(body.additional_deductions)
    
            # ── Create Journal Entry via centralized GL service ──
            base_currency = get_base_currency(db)
    
            lines = []
    
            # Dr: EOS Expense
            eos_exp = get_mapped_account_id(db, "acc_map_eos_expense")
            if eos_exp and eos_amount > 0:
                lines.append({
                    "account_id": eos_exp, "debit": eos_amount, "credit": 0,
                    "description": "مكافأة نهاية خدمة"
                })
    
            # Dr: Salary Expense (for vacation + pending)
            salary_exp = get_mapped_account_id(db, "acc_map_salary_expense")
            remaining_amount = vacation_amount + pending_salary
            if salary_exp and remaining_amount > 0:
                lines.append({
                    "account_id": salary_exp, "debit": remaining_amount, "credit": 0,
                    "description": f"رصيد إجازات {vacation_amount} + راتب مستحق {pending_salary}"
                })
    
            # Cr: EOS Provision (reverse)
            eos_prov = get_mapped_account_id(db, "acc_map_eos_provision")
            if eos_prov and eos_amount > 0:
                lines.append({
                    "account_id": eos_prov, "debit": 0, "credit": eos_amount,
                    "description": "عكس مخصص نهاية خدمة"
                })
    
            # Cr: Bank (preferred for EOS settlement \u2014 paid via bank
            # transfer per WPS), fall back to Cash if no bank account
            # is mapped. T10.2 #189: previously hard-coded acc_map_cash.
            cash_account = (
                get_mapped_account_id(db, "acc_map_bank")
                or get_mapped_account_id(db, "acc_map_cash")
            )
            if cash_account and total_settlement > 0:
                lines.append({
                    "account_id": cash_account, "debit": 0, "credit": total_settlement,
                    "description": "صرف تسوية نهاية خدمة"
                })
    
            je_id = None
            je_number = None
            if lines:
                je_result = gl_create_journal_entry(
                    db=db,
                    company_id=company_id,
                    date=date.today(),
                    reference=f"EOS-{body.employee_id}",
                    description=f"تسوية نهاية خدمة: {emp.employee_name}",
                    status="posted",
                    currency=base_currency,
                    exchange_rate=1.0,
                    source="eos_settlement",
                    source_id=body.employee_id,
                    lines=lines,
                    user_id=user_id
                )
                if isinstance(je_result, dict):
                    je_id = je_result.get("id")
                    je_number = je_result.get("entry_number")
                elif isinstance(je_result, (tuple, list)):
                    je_id = je_result[0] if len(je_result) > 0 else None
                    je_number = je_result[1] if len(je_result) > 1 else None
                else:
                    je_id = je_result
    
            # Update employee status
            db.execute(text("""
                UPDATE employees SET status = 'terminated',
                    eos_amount = :eos, eos_eligible = false,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :eid
            """), {"eos": total_settlement, "eid": body.employee_id})
    
    
            # Audit log
            log_activity(db, user_id=user_id, username=current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", ""),
                         action="eos.settle", resource_type="employee", resource_id=body.employee_id,
                         details={"total_settlement": str(total_settlement), "service_years": round(total_years, 2),
                                  "termination_reason": body.termination_reason,
                                  "unpaid_leave_days": int(unpaid_days),
                                  "unpaid_leave_deduction": str(eos.get("unpaid_leave_deduction", 0)),
                                  "journal_entry_id": je_id})
    
            return {
                "employee_id": body.employee_id,
                "employee_name": emp.employee_name,
                "service_years": round(total_years, 2),
                "termination_reason": body.termination_reason,
                "eos_gratuity": str(eos_amount),
                "unpaid_leave_days": int(unpaid_days),
                "unpaid_leave_deduction": str(eos.get("unpaid_leave_deduction", 0)),
                "vacation_balance_amount": str(vacation_amount),
                "pending_salary": str(pending_salary),
                "additional_deductions": body.additional_deductions,
                "total_settlement": str(total_settlement),
                "journal_entry_id": je_id,
                "journal_entry_number": je_number,
                "message": i18n_message("eos_settled", request)
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
