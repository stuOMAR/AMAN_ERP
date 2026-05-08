"""
وحدة الامتثال الضريبي — AMAN ERP
═══════════════════════════════════
• أنظمة الضرائب حسب الدولة (tax_regimes)
• إعدادات ضريبية للشركة والفروع (company_tax_settings, branch_tax_settings)
• الضرائب المطبقة تلقائياً حسب branch → jurisdiction
• تقارير ضريبية رسمية: إقرار VAT سعودي، ضريبة دخل سورية، إلخ
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, Field, validator
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access, require_module
from utils.audit import log_activity
from decimal import Decimal, ROUND_HALF_UP
import logging

router = APIRouter(prefix="/tax-compliance", tags=["Tax Compliance"], dependencies=[Depends(require_module("taxes"))])
logger = logging.getLogger(__name__)

_D2 = Decimal("0.01")


def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════════════

class CompanyTaxSettingsUpdate(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2)
    is_vat_registered: bool = False
    vat_number: Optional[str] = None
    zakat_number: Optional[str] = None
    tax_registration_number: Optional[str] = None
    commercial_registry: Optional[str] = None
    fiscal_year_start: str = "01-01"
    default_filing_frequency: str = "quarterly"
    zatca_phase: str = "none"

    @validator('vat_number')
    def validate_vat_number(cls, v, values):
        if v is not None and v.strip():
            cc = values.get('country_code', '')
            if cc == 'SA':
                import re
                if not re.fullmatch(r'3\d{14}', v.strip()):
                    raise ValueError('Saudi VAT number must be 15 digits starting with 3')
        return v

class BranchTaxSettingUpdate(BaseModel):
    branch_id: int
    tax_regime_id: int
    is_registered: bool = False
    registration_number: Optional[str] = None
    custom_rate: Optional[Decimal] = None
    is_exempt: bool = False
    exemption_reason: Optional[str] = None
    exemption_certificate: Optional[str] = None
    exemption_expiry: Optional[date] = None

class BranchTaxBulkUpdate(BaseModel):
    branch_id: int
    settings: List[BranchTaxSettingUpdate]

# ═══════════════════════════════════════════════════════════════════════════════
# Country metadata (used for UI)
# ═══════════════════════════════════════════════════════════════════════════════

COUNTRY_META = {
    "SA": {"name_ar": "المملكة العربية السعودية", "name_en": "Saudi Arabia",       "currency": "SAR", "has_vat": True,  "has_zakat": True,  "has_zatca": True},
    "SY": {"name_ar": "سوريا",                   "name_en": "Syria",              "currency": "SYP", "has_vat": False, "has_zakat": False, "has_zatca": False},
    "AE": {"name_ar": "الإمارات العربية المتحدة",  "name_en": "United Arab Emirates","currency": "AED", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "EG": {"name_ar": "مصر",                     "name_en": "Egypt",              "currency": "EGP", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "JO": {"name_ar": "الأردن",                   "name_en": "Jordan",             "currency": "JOD", "has_vat": False, "has_zakat": False, "has_zatca": False},
    "KW": {"name_ar": "الكويت",                   "name_en": "Kuwait",             "currency": "KWD", "has_vat": False, "has_zakat": True,  "has_zatca": False},
    "BH": {"name_ar": "البحرين",                  "name_en": "Bahrain",            "currency": "BHD", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "OM": {"name_ar": "عمان",                    "name_en": "Oman",               "currency": "OMR", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "QA": {"name_ar": "قطر",                     "name_en": "Qatar",              "currency": "QAR", "has_vat": False, "has_zakat": False, "has_zatca": False},
    "IQ": {"name_ar": "العراق",                   "name_en": "Iraq",               "currency": "IQD", "has_vat": False, "has_zakat": False, "has_zatca": False},
    "LB": {"name_ar": "لبنان",                   "name_en": "Lebanon",            "currency": "LBP", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "TR": {"name_ar": "تركيا",                   "name_en": "Turkey",             "currency": "TRY", "has_vat": True,  "has_zakat": False, "has_zatca": False},
    "YE": {"name_ar": "اليمن",                   "name_en": "Yemen",              "currency": "YER", "has_vat": False, "has_zakat": False, "has_zatca": False},
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TAX REGIMES — Master list per country
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/regimes", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=List[Dict[str, Any]])
def list_tax_regimes(
    country_code: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب أنظمة الضرائب — يمكن تصفيتها حسب الدولة"""
    with transactional(current_user.company_id) as db:
        where = "WHERE 1=1"
        params = {}
        if country_code:
            where += " AND country_code = :cc"
            params["cc"] = country_code.upper()
        if is_active is not None:
            where += " AND is_active = :active"
            params["active"] = is_active

        rows = db.execute(text(f"""
            SELECT id, country_code, tax_type, name_ar, name_en, default_rate,
                   is_required, applies_to, filing_frequency, is_active
            FROM tax_regimes {where}
            ORDER BY country_code, is_required DESC, tax_type
        """), params).fetchall()

        return [dict(r._mapping) for r in rows]


@router.get("/countries", response_model=Dict[str, Any])
def list_supported_countries(current_user: dict = Depends(get_current_user)):
    """جلب قائمة الدول المدعومة مع خصائصها الضريبية"""
    with transactional(current_user.company_id) as db:
        # Get countries that have tax regimes defined
        rows = db.execute(text("""
            SELECT DISTINCT country_code, 
                   COUNT(*) as tax_count,
                   COUNT(*) FILTER (WHERE is_required) as required_count
            FROM tax_regimes WHERE is_active = TRUE
            GROUP BY country_code
            ORDER BY country_code
        """)).fetchall()

        # Get countries that have WHT rules
        wht_rows = db.execute(text("""
            SELECT DISTINCT country_code FROM wht_rules WHERE is_active = TRUE
        """)).fetchall()
        wht_countries = {r.country_code for r in wht_rows}

        # Get tax types per country
        regime_rows = db.execute(text("""
            SELECT country_code, tax_type, default_rate
            FROM tax_regimes WHERE is_active = TRUE
            ORDER BY country_code, tax_type
        """)).fetchall()

        regimes_by_country: dict = {}
        for rr in regime_rows:
            regimes_by_country.setdefault(rr.country_code, []).append({
                "tax_type": rr.tax_type,
                "default_rate": float(rr.default_rate or 0),
            })

        # Report endpoint mapping
        _REPORT_MAP = {
            "SA": "/tax-compliance/reports/sa-vat",
            "AE": "/tax-compliance/reports/ae-vat",
            "EG": "/tax-compliance/reports/eg-vat",
            "SY": "/tax-compliance/reports/sy-income",
            "TR": "/tax-compliance/reports/tr-kdv",
        }

        result = []
        for r in rows:
            meta = COUNTRY_META.get(r.country_code, {})
            tax_types = regimes_by_country.get(r.country_code, [])
            has_vat = any(t["tax_type"] in ("vat", "kdv", "sales_tax") for t in tax_types)
            result.append({
                "country_code": r.country_code,
                "name_ar": meta.get("name_ar", r.country_code),
                "name_en": meta.get("name_en", r.country_code),
                "currency": meta.get("currency", ""),
                "tax_types": [t["tax_type"] for t in tax_types],
                "has_vat": has_vat,
                "has_wht": r.country_code in wht_countries,
                "has_zakat": meta.get("has_zakat", False),
                "has_zatca": meta.get("has_zatca", False),
                "report_endpoint": _REPORT_MAP.get(r.country_code),
                "tax_types_count": r.tax_count,
                "required_taxes": r.required_count,
            })
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 1.5 TAX CLASSIFICATIONS — Product-type-based tax mapping
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/classifications", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=List[Dict[str, Any]])
def list_tax_classifications(current_user: dict = Depends(get_current_user)):
    """جلب جميع التصنيفات الضريبية النشطة"""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT id, code, name_ar, name_en, description, is_active
            FROM tax_classifications
            WHERE is_active = TRUE
            ORDER BY code
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/classifications/by-country/{country_code}", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=List[Dict[str, Any]])
def list_classifications_for_country(
    country_code: str,
    current_user: dict = Depends(get_current_user)
):
    """جلب التصنيفات الضريبية مع معدلاتها لدولة محددة"""
    with transactional(current_user.company_id) as db:
        cc = country_code.upper()
        rows = db.execute(text("""
            SELECT
                tc.id as classification_id,
                tc.code as classification_code,
                tc.name_ar,
                tc.name_en,
                tcr.tax_rate_id,
                tcr.tax_group_id,
                COALESCE(tr.rate_value, 0) as tax_rate,
                tr.tax_name,
                tr.tax_code,
                tcr.country_code,
                tcr.effective_from,
                tcr.effective_to
            FROM tax_classifications tc
            LEFT JOIN tax_classification_rates tcr
                ON tc.id = tcr.classification_id
                AND tcr.country_code = :cc
                AND tcr.effective_from <= CURRENT_DATE
                AND (tcr.effective_to IS NULL OR tcr.effective_to >= CURRENT_DATE)
            LEFT JOIN tax_rates tr ON tcr.tax_rate_id = tr.id
            WHERE tc.is_active = TRUE
            ORDER BY tc.code
        """), {"cc": cc}).fetchall()

        result = []
        for r in rows:
            entry = {
                "classification_id": r.classification_id,
                "classification_code": r.classification_code,
                "name_ar": r.name_ar,
                "name_en": r.name_en,
                "country_code": cc,
                "tax_rate_id": r.tax_rate_id,
                "tax_group_id": r.tax_group_id,
                "tax_rate": float(r.tax_rate or 0),
                "tax_name": r.tax_name or ("Exempt" if r.classification_id and not r.tax_rate_id else None),
                "tax_code": r.tax_code,
            }
            # If classification points to a tax group, resolve its rates
            if r.tax_group_id:
                group_rows = db.execute(text("""
                    SELECT tr.rate_value, tr.tax_name, tr.tax_code
                    FROM tax_groups tg
                    CROSS JOIN LATERAL jsonb_array_elements_text(tg.tax_ids) AS elem(val)
                    JOIN tax_rates tr ON tr.id = elem.val::int
                    WHERE tg.id = :gid AND tg.is_active = TRUE AND tr.is_active = TRUE
                """), {"gid": r.tax_group_id}).fetchall()
                entry["tax_group_rates"] = [
                    {"rate": float(g.rate_value), "name": g.tax_name, "code": g.tax_code}
                    for g in group_rows
                ]
            result.append(entry)

        return result


class ClassificationCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name_ar: str = Field(..., min_length=1, max_length=100)
    name_en: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


@router.post("/classifications", dependencies=[Depends(require_permission(["taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_classification(
    data: ClassificationCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء تصنيف ضريبي جديد"""
    with transactional(current_user.company_id) as db:
        existing = db.execute(text(
            "SELECT id FROM tax_classifications WHERE code = :code"
        ), {"code": data.code.upper()}).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Classification '{data.code}' already exists")

        result = db.execute(text("""
            INSERT INTO tax_classifications (code, name_ar, name_en, description)
            VALUES (:code, :ar, :en, :desc)
            RETURNING id, code, name_ar, name_en
        """), {
            "code": data.code.upper(),
            "ar": data.name_ar,
            "en": data.name_en,
            "desc": data.description,
        }).fetchone()

        return dict(result._mapping)


class ClassificationUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=2, max_length=50)
    name_ar: Optional[str] = Field(None, min_length=1, max_length=100)
    name_en: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.put("/classifications/{classification_id}", dependencies=[Depends(require_permission(["taxes.manage"]))], response_model=Dict[str, Any])
def update_tax_classification(
    classification_id: int,
    data: ClassificationUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تعديل تصنيف ضريبي"""
    with transactional(current_user.company_id) as db:
        existing = db.execute(text(
            "SELECT id FROM tax_classifications WHERE id = :id"
        ), {"id": classification_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Classification not found")

        updates = []
        params = {"id": classification_id}
        if data.code is not None:
            updates.append("code = :code")
            params["code"] = data.code.upper()
        if data.name_ar is not None:
            updates.append("name_ar = :ar")
            params["ar"] = data.name_ar
        if data.name_en is not None:
            updates.append("name_en = :en")
            params["en"] = data.name_en
        if data.description is not None:
            updates.append("description = :desc")
            params["desc"] = data.description
        if data.is_active is not None:
            updates.append("is_active = :active")
            params["active"] = data.is_active

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = db.execute(text(f"""
            UPDATE tax_classifications SET {', '.join(updates)}
            WHERE id = :id
            RETURNING id, code, name_ar, name_en, description, is_active
        """), params).fetchone()

        return dict(result._mapping)


@router.delete("/classifications/{classification_id}", dependencies=[Depends(require_permission(["taxes.manage"]))])
def delete_tax_classification(
    classification_id: int,
    current_user: dict = Depends(get_current_user)
):
    """حذف تصنيف ضريبي (soft delete)"""
    with transactional(current_user.company_id) as db:
        existing = db.execute(text(
            "SELECT id, code FROM tax_classifications WHERE id = :id"
        ), {"id": classification_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Classification not found")

        db.execute(text(
            "UPDATE tax_classifications SET is_active = FALSE WHERE id = :id"
        ), {"id": classification_id})

        return {"message": f"Classification '{existing.code}' deactivated", "id": classification_id}


@router.get("/classifications/{classification_id}/rates", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=List[Dict[str, Any]])
def get_classification_rates(
    classification_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب معدلات التصنيف الضريبي لجميع الدول"""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT
                tcr.id as rate_link_id,
                tcr.country_code,
                tcr.tax_rate_id,
                tcr.tax_group_id,
                COALESCE(tr.rate_value, 0) as tax_rate,
                tr.tax_name,
                tr.tax_code,
                tcr.effective_from,
                tcr.effective_to
            FROM tax_classification_rates tcr
            LEFT JOIN tax_rates tr ON tcr.tax_rate_id = tr.id
            WHERE tcr.classification_id = :cid
            ORDER BY tcr.country_code
        """), {"cid": classification_id}).fetchall()
        return [dict(r._mapping) for r in rows]


class ClassificationRateCreate(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=5)
    tax_rate_id: Optional[int] = None
    tax_group_id: Optional[int] = None


@router.post("/classifications/{classification_id}/rates", dependencies=[Depends(require_permission(["taxes.manage"]))], response_model=Dict[str, Any])
def add_classification_rate(
    classification_id: int,
    data: ClassificationRateCreate,
    current_user: dict = Depends(get_current_user)
):
    """إضافة معدل ضريبي لتصنيف في دولة معينة"""
    with transactional(current_user.company_id) as db:
        existing = db.execute(text(
            "SELECT id FROM tax_classifications WHERE id = :id AND is_active = TRUE"
        ), {"id": classification_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Classification not found")

        duplicate = db.execute(text("""
            SELECT id FROM tax_classification_rates
            WHERE classification_id = :cid AND country_code = :cc AND effective_from = CURRENT_DATE
        """), {"cid": classification_id, "cc": data.country_code.upper()}).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Rate already exists for this country today")

        result = db.execute(text("""
            INSERT INTO tax_classification_rates
                (classification_id, country_code, tax_rate_id, tax_group_id, effective_from)
            VALUES (:cid, :cc, :rid, :gid, CURRENT_DATE)
            RETURNING id, country_code, tax_rate_id, tax_group_id, effective_from
        """), {
            "cid": classification_id,
            "cc": data.country_code.upper(),
            "rid": data.tax_rate_id,
            "gid": data.tax_group_id,
        }).fetchone()

        return dict(result._mapping)


@router.delete("/classifications/{classification_id}/rates/{rate_link_id}", dependencies=[Depends(require_permission(["taxes.manage"]))])
def delete_classification_rate(
    classification_id: int,
    rate_link_id: int,
    current_user: dict = Depends(get_current_user)
):
    """حذف ربط معدل ضريبي بتصنيف"""
    with transactional(current_user.company_id) as db:
        db.execute(text("""
            DELETE FROM tax_classification_rates
            WHERE id = :rid AND classification_id = :cid
        """), {"rid": rate_link_id, "cid": classification_id})
        return {"message": "Rate link deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. COMPANY TAX SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/company-settings", dependencies=[Depends(require_permission(["taxes.view", "settings.view"]))], response_model=List[Dict[str, Any]])
def get_company_tax_settings(current_user: dict = Depends(get_current_user)):
    """جلب إعدادات الضرائب على مستوى الشركة"""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT * FROM company_tax_settings ORDER BY country_code
        """)).fetchall()

        if not rows:
            # Fallback: read from company_settings
            cc = db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'company_country'"
            )).scalar() or "SA"
            return [{"country_code": cc, "is_vat_registered": False}]

        return [dict(r._mapping) for r in rows]


@router.put("/company-settings", dependencies=[Depends(require_permission(["taxes.manage", "settings.manage"]))], response_model=Dict[str, Any])
def update_company_tax_settings(
    request: Request,
    data: CompanyTaxSettingsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث إعدادات الضرائب للشركة"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            INSERT INTO company_tax_settings 
                (country_code, is_vat_registered, vat_number, zakat_number, 
                 tax_registration_number, commercial_registry, 
                 fiscal_year_start, default_filing_frequency, zatca_phase, updated_at)
            VALUES (:cc, :vat_reg, :vat_num, :zakat_num, :tax_reg, :cr, :fy, :freq, :zatca, :now)
            ON CONFLICT (country_code)
            DO UPDATE SET 
                is_vat_registered = :vat_reg, vat_number = :vat_num,
                zakat_number = :zakat_num, tax_registration_number = :tax_reg,
                commercial_registry = :cr, fiscal_year_start = :fy,
                default_filing_frequency = :freq, zatca_phase = :zatca,
                updated_at = :now
        """), {
            "cc": data.country_code.upper(), "vat_reg": data.is_vat_registered,
            "vat_num": data.vat_number, "zakat_num": data.zakat_number,
            "tax_reg": data.tax_registration_number, "cr": data.commercial_registry,
            "fy": data.fiscal_year_start, "freq": data.default_filing_frequency,
            "zatca": data.zatca_phase, "now": datetime.now(timezone.utc)
        })
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="tax_compliance.company_settings.update",
                     resource_type="company_tax_settings",
                     resource_id=data.country_code,
                     details=data.model_dump(), request=request)

        return {"success": True, "message": "تم تحديث إعدادات الضرائب بنجاح"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating company tax settings: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BRANCH TAX SETTINGS — Per-branch jurisdiction
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/branch-settings/{branch_id}", dependencies=[Depends(require_permission(["taxes.view", "branches.view"]))], response_model=Dict[str, Any])
def get_branch_tax_settings(branch_id: int, current_user: dict = Depends(get_current_user)):
    """جلب إعدادات الضرائب لفرع معين مع أنظمة الدولة المطبقة"""
    with transactional(current_user.company_id) as db:
        # Get branch info
        branch = db.execute(text(
            "SELECT id, branch_name, branch_name_en, country, country_code FROM branches WHERE id = :id"
        ), {"id": branch_id}).fetchone()
        if not branch:
            raise HTTPException(**http_error(404, "branch_not_found"))

        branch_cc = branch.country_code or "SA"

        # Get all regimes for this branch's country
        regimes = db.execute(text("""
            SELECT tr.id, tr.country_code, tr.tax_type, tr.name_ar, tr.name_en,
                   tr.default_rate, tr.is_required, tr.applies_to, tr.filing_frequency,
                   bts.id as setting_id, bts.is_registered, bts.registration_number,
                   bts.custom_rate, bts.is_exempt, bts.exemption_reason,
                   bts.exemption_certificate, bts.exemption_expiry, bts.is_active as setting_active
            FROM tax_regimes tr
            LEFT JOIN branch_tax_settings bts ON tr.id = bts.tax_regime_id AND bts.branch_id = :bid
            WHERE tr.country_code = :cc AND tr.is_active = TRUE
            ORDER BY tr.is_required DESC, tr.tax_type
        """), {"bid": branch_id, "cc": branch_cc}).fetchall()

        return {
            "branch": {
                "id": branch.id,
                "name": branch.branch_name,
                "name_en": branch.branch_name_en,
                "country": branch.country,
                "country_code": branch_cc,
            },
            "country_meta": COUNTRY_META.get(branch_cc, {}),
            "tax_settings": [dict(r._mapping) for r in regimes]
        }


@router.put("/branch-settings", dependencies=[Depends(require_permission(["taxes.manage", "branches.manage"]))], response_model=Dict[str, Any])
def update_branch_tax_setting(
    request: Request,
    data: BranchTaxSettingUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث إعداد ضريبي لفرع معين"""
    db = get_db_connection(current_user.company_id)
    try:
        # Verify branch exists
        branch = db.execute(text("SELECT 1 FROM branches WHERE id = :id"), {"id": data.branch_id}).fetchone()
        if not branch:
            raise HTTPException(**http_error(404, "branch_not_found"))

        # Verify tax regime exists
        regime = db.execute(text("SELECT 1 FROM tax_regimes WHERE id = :id"), {"id": data.tax_regime_id}).fetchone()
        if not regime:
            raise HTTPException(status_code=404, detail="نظام الضريبة غير موجود")

        db.execute(text("""
            INSERT INTO branch_tax_settings 
                (branch_id, tax_regime_id, is_registered, registration_number,
                 custom_rate, is_exempt, exemption_reason, exemption_certificate,
                 exemption_expiry, is_active, updated_at)
            VALUES (:bid, :rid, :reg, :num, :rate, :exempt, :reason, :cert, :expiry, TRUE, :now)
            ON CONFLICT (branch_id, tax_regime_id)
            DO UPDATE SET
                is_registered = :reg, registration_number = :num,
                custom_rate = :rate, is_exempt = :exempt,
                exemption_reason = :reason, exemption_certificate = :cert,
                exemption_expiry = :expiry, updated_at = :now
        """), {
            "bid": data.branch_id, "rid": data.tax_regime_id,
            "reg": data.is_registered, "num": data.registration_number,
            "rate": data.custom_rate, "exempt": data.is_exempt,
            "reason": data.exemption_reason, "cert": data.exemption_certificate,
            "expiry": data.exemption_expiry, "now": datetime.now(timezone.utc)
        })
        db.commit()

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="tax_compliance.branch_settings.update",
                     resource_type="branch_tax_settings",
                     resource_id=f"{data.branch_id}-{data.tax_regime_id}",
                     details=data.model_dump(mode="json"), request=request)

        return {"success": True, "message": "تم تحديث إعدادات الضرائب للفرع بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating branch tax settings: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. APPLICABLE TAXES — What taxes apply to a given branch
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/applicable-taxes/{branch_id}", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=Dict[str, Any])
def get_applicable_taxes(branch_id: int, current_user: dict = Depends(get_current_user)):
    """
    جلب الضرائب المطبقة على فرع معين  
    يستخدم في الفواتير والمعاملات لتحديد الضرائب الواجبة تلقائياً
    يعتمد على tax_engine لضمان نفس المنطق المستخدم في إنشاء الفواتير
    """
    with transactional(current_user.company_id) as db:
        from services.tax_engine import get_active_tax_for_branch

        branch = db.execute(text(
            "SELECT id, branch_name, country_code FROM branches WHERE id = :id"
        ), {"id": branch_id}).fetchone()
        if not branch:
            raise HTTPException(**http_error(404, "branch_not_found"))

        branch_cc = (branch.country_code or "SA").upper()

        # Get the primary tax via engine (same logic as invoice creation)
        try:
            primary_tax = get_active_tax_for_branch(branch_id, db)
        except HTTPException:
            primary_tax = None

        # Also get all regime-level taxes for the branch (for compliance UI)
        taxes = db.execute(text("""
            SELECT tr.id as regime_id, tr.country_code, tr.tax_type, 
                   tr.name_ar, tr.name_en, tr.default_rate, tr.applies_to,
                   tr.filing_frequency,
                   COALESCE(bts.custom_rate, tr.default_rate) as effective_rate,
                   COALESCE(bts.is_exempt, FALSE) as is_exempt,
                   bts.is_registered, bts.registration_number
            FROM tax_regimes tr
            LEFT JOIN branch_tax_settings bts ON tr.id = bts.tax_regime_id AND bts.branch_id = :bid
            WHERE tr.country_code = :cc AND tr.is_active = TRUE
              AND (COALESCE(bts.is_exempt, FALSE) = FALSE)
              AND (tr.is_required = TRUE OR COALESCE(bts.is_registered, FALSE) = TRUE)
            ORDER BY tr.is_required DESC, tr.tax_type
        """), {"bid": branch_id, "cc": branch_cc}).fetchall()

        return {
            "branch_id": branch_id,
            "jurisdiction": branch_cc,
            "country": COUNTRY_META.get(branch_cc, {}).get("name_ar", branch_cc),
            "primary_tax": primary_tax,
            "taxes": [dict(r._mapping) for r in taxes]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. OFFICIAL TAX REPORTS — Country-specific formats
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/reports/sa-vat", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def saudi_vat_return_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    إقرار ضريبة القيمة المضافة — المملكة العربية السعودية
    يتبع نموذج هيئة الزكاة والضريبة والجمارك (ZATCA)
    
    يقبل إما period_start/period_end أو year + period اختياري (Q1-Q4, 01-12)
    """
    from datetime import date as date_cls
    # Resolve dates from year/period if not explicitly provided
    if period_start is None or period_end is None:
        y = year or date_cls.today().year
        if period and period.startswith("Q"):
            q = int(period[1])
            ms = (q - 1) * 3 + 1
            me = q * 3
            period_start = date_cls(y, ms, 1)
            period_end = date_cls(y, me, 28 if me == 2 else 30 if me in (4,6,9,11) else 31)
        elif period and period.isdigit():
            m = int(period)
            period_start = date_cls(y, m, 1)
            import calendar
            period_end = date_cls(y, m, calendar.monthrange(y, m)[1])
        else:
            period_start = date_cls(y, 1, 1)
            period_end = date_cls(y, 12, 31)
    with transactional(current_user.company_id) as db:
        params = {"start": period_start, "end": period_end}
        branch_filter = branch_scope_filter(current_user, branch_id, "i.branch_id", params)

        # ── Box 1: Standard-rated sales (15%) ────────────────────────────────
        box1 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        # ── Box 2: Zero-rated sales ──────────────────────────────────────────
        box2 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate = 0
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        # ── Box 3: Exempt sales ──────────────────────────────────────────────
        box3 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate IS NULL
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        # ── Box 4: Standard-rated purchases ──────────────────────────────────
        box4 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        # ── Box 6: Sales returns deductions ──────────────────────────────────
        box6 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        # ── Box 7: Purchase returns deductions ───────────────────────────────
        box7 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        box1_vat = _dec(box1.tax)
        box4_vat = _dec(box4.tax)
        box6_vat = _dec(box6.tax)
        box7_vat = _dec(box7.tax)
        total_output = (box1_vat - box6_vat).quantize(_D2, ROUND_HALF_UP)
        total_input = (box4_vat - box7_vat).quantize(_D2, ROUND_HALF_UP)
        net_vat = (total_output - total_input).quantize(_D2, ROUND_HALF_UP)

        # Company tax info
        company_tax = db.execute(text(
            "SELECT * FROM company_tax_settings WHERE country_code = 'SA' LIMIT 1"
        )).fetchone()

        return {
            "report_type": "sa_vat_return",
            "report_name_ar": "إقرار ضريبة القيمة المضافة — ZATCA",
            "report_name_en": "VAT Return — ZATCA Format",
            "period": {"start": period_start, "end": period_end},
            "vat_number": company_tax.vat_number if company_tax else None,
            "boxes": {
                "box_1": {
                    "label_ar": "المبيعات الخاضعة للضريبة بالنسبة الأساسية",
                    "label_en": "Standard Rated Sales",
                    "amount": float(box1.amount or 0),
                    "adjustment": float(box6.amount or 0),
                    "vat": float((box1_vat - box6_vat).quantize(_D2, ROUND_HALF_UP))
                },
                "box_2": {
                    "label_ar": "المبيعات الخاضعة لنسبة صفرية",
                    "label_en": "Zero-Rated Sales",
                    "amount": float(box2.amount or 0),
                    "vat": 0
                },
                "box_3": {
                    "label_ar": "المبيعات المعفاة",
                    "label_en": "Exempt Sales",
                    "amount": float(box3.amount or 0),
                    "vat": 0
                },
                "box_4": {
                    "label_ar": "المشتريات الخاضعة للضريبة بالنسبة الأساسية",
                    "label_en": "Standard Rated Purchases",
                    "amount": float(box4.amount or 0),
                    "adjustment": float(box7.amount or 0),
                    "vat": float((box4_vat - box7_vat).quantize(_D2, ROUND_HALF_UP))
                },
                "box_5": {
                    "label_ar": "الاستيراد الخاضع لآلية الاحتساب العكسي",
                    "label_en": "Imports subject to Reverse Charge",
                    "amount": 0,
                    "vat": 0
                },
                "box_6": {
                    "label_ar": "تصحيحات من فترات سابقة (المبيعات)",
                    "label_en": "Corrections (Sales)",
                    "amount": float(box6.amount or 0),
                    "vat": float(box6.tax or 0)
                },
                "box_7": {
                    "label_ar": "تصحيحات من فترات سابقة (المشتريات)",
                    "label_en": "Corrections (Purchases)",
                    "amount": float(box7.amount or 0),
                    "vat": float(box7.tax or 0)
                },
            },
            "totals": {
                "total_sales": float((_dec(box1.amount) + _dec(box2.amount) + _dec(box3.amount)).quantize(_D2, ROUND_HALF_UP)),
                "total_output_vat": float(total_output),
                "total_input_vat": float(total_input),
                "net_vat_due": float(net_vat),
                "status": "payable" if net_vat >= Decimal("0") else "refundable"
            }
        }


@router.get("/reports/sy-income", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def syrian_income_tax_report(
    fiscal_year: Optional[int] = None,
    year: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    إقرار ضريبة الدخل — الجمهورية العربية السورية
    يتبع نموذج مديرية المالية / وزارة المالية السورية
    
    يحسب:
      1. إجمالي الإيرادات
      2. تكلفة البضاعة المباعة
      3. مجمل الربح
      4. المصروفات التشغيلية
      5. صافي الربح قبل الضريبة
      6. ضريبة الدخل المستحقة (22%)
    """
    from datetime import date as date_cls
    fy = fiscal_year or year or date_cls.today().year
    with transactional(current_user.company_id) as db:
        start_date = f"{fy}-01-01"
        end_date = f"{fy}-12-31"
        params = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter(current_user, branch_id, "je.branch_id", params)

        # Revenue (account_type = 'revenue')
        revenue = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.credit - jl.debit), 0) as total
            FROM journal_lines jl 
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'revenue' AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        # COGS (account number starts with '51')
        cogs = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0) as total
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_number LIKE '51%' AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        # Operating Expenses (account number starts with '52', '53', '54', '55')
        op_expenses = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0) as total
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_number LIKE '52%' OR a.account_number LIKE '53%' 
                   OR a.account_number LIKE '54%' OR a.account_number LIKE '55%')
            AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        revenue_dec = _dec(revenue).quantize(_D2, ROUND_HALF_UP)
        cogs_dec = _dec(cogs).quantize(_D2, ROUND_HALF_UP)
        op_expenses_dec = _dec(op_expenses).quantize(_D2, ROUND_HALF_UP)
        gross_profit = (revenue_dec - cogs_dec).quantize(_D2, ROUND_HALF_UP)
        net_profit = (gross_profit - op_expenses_dec).quantize(_D2, ROUND_HALF_UP)

        # Syrian income tax rate = 22% for commercial/industrial activities 
        tax_rate_dec = Decimal("22")
        regime = db.execute(text(
            "SELECT default_rate FROM tax_regimes WHERE country_code = 'SY' AND tax_type = 'income_tax' LIMIT 1"
        )).fetchone()
        if regime:
            tax_rate_dec = _dec(regime.default_rate)

        tax_rate = float(tax_rate_dec)
        income_tax = max(Decimal("0"), (net_profit * (tax_rate_dec / Decimal("100"))).quantize(_D2, ROUND_HALF_UP))

        # Salary tax summary for the year
        salary_expenses = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_number = '5201' AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {branch_filter}
        """), params).scalar() or 0

        return {
            "report_type": "sy_income_tax",
            "report_name_ar": "إقرار ضريبة الدخل — وزارة المالية السورية",
            "report_name_en": "Income Tax Return — Syrian Ministry of Finance",
            "fiscal_year": fiscal_year,
            "period": {"start": start_date, "end": end_date},
            "income_statement": {
                "total_revenue": {"label_ar": "إجمالي الإيرادات", "label_en": "Total Revenue", "amount": float(revenue_dec)},
                "cost_of_sales": {"label_ar": "تكلفة البضاعة المباعة", "label_en": "Cost of Goods Sold", "amount": float(cogs_dec)},
                "gross_profit": {"label_ar": "مجمل الربح", "label_en": "Gross Profit", "amount": float(gross_profit)},
                "operating_expenses": {"label_ar": "المصروفات التشغيلية", "label_en": "Operating Expenses", "amount": float(op_expenses_dec)},
                "net_profit_before_tax": {"label_ar": "صافي الربح قبل الضريبة", "label_en": "Net Profit Before Tax", "amount": float(net_profit)},
            },
            "tax_computation": {
                "taxable_income": {"label_ar": "الدخل الخاضع للضريبة", "label_en": "Taxable Income", "amount": float(max(Decimal("0"), net_profit))},
                "tax_rate": {"label_ar": f"نسبة الضريبة ({tax_rate}%)", "label_en": f"Tax Rate ({tax_rate}%)", "rate": tax_rate},
                "income_tax_due": {"label_ar": "ضريبة الدخل المستحقة", "label_en": "Income Tax Due", "amount": float(income_tax)},
            },
            "supplementary": {
                "total_salaries": {"label_ar": "إجمالي الرواتب والأجور", "label_en": "Total Salaries & Wages", "amount": float(salary_expenses)},
            },
            "totals": {
                "net_profit": float(net_profit),
                "tax_due": float(income_tax),
            }
        }


@router.get("/reports/ae-vat", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def uae_vat_return_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    إقرار ضريبة القيمة المضافة — الإمارات العربية المتحدة
    يتبع نموذج الهيئة الاتحادية للضرائب (FTA)
    """
    from datetime import date as date_cls
    if period_start is None or period_end is None:
        y = year or date_cls.today().year
        if period and period.startswith("Q"):
            q = int(period[1])
            ms = (q - 1) * 3 + 1; me = q * 3
            period_start = date_cls(y, ms, 1)
            period_end = date_cls(y, me, 28 if me == 2 else 30 if me in (4,6,9,11) else 31)
        else:
            period_start = date_cls(y, 1, 1)
            period_end = date_cls(y, 12, 31)
    with transactional(current_user.company_id) as db:
        params = {"start": period_start, "end": period_end}
        bf = branch_scope_filter(current_user, branch_id, "i.branch_id", params)

        # Standard supplies (5%)
        standard = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Zero-rated
        zero_rated = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate = 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Exempt
        exempt = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate IS NULL
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Purchases
        purchases = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        total_output = _dec(standard.tax).quantize(_D2, ROUND_HALF_UP)
        total_input = _dec(purchases.tax).quantize(_D2, ROUND_HALF_UP)
        net_vat_due = (total_output - total_input).quantize(_D2, ROUND_HALF_UP)

        return {
            "report_type": "ae_vat_return",
            "report_name_ar": "إقرار ضريبة القيمة المضافة — الهيئة الاتحادية للضرائب",
            "report_name_en": "VAT Return — FTA Format",
            "period": {"start": period_start, "end": period_end},
            "supplies": {
                "standard_rated": {"label_ar": "توريدات خاضعة للنسبة الأساسية (5%)", "amount": float(standard.amount or 0), "vat": float(standard.tax or 0)},
                "zero_rated": {"label_ar": "توريدات خاضعة لنسبة الصفر", "amount": float(zero_rated.amount or 0), "vat": 0},
                "exempt": {"label_ar": "توريدات معفاة", "amount": float(exempt.amount or 0), "vat": 0},
            },
            "expenses": {
                "standard_rated_purchases": {"label_ar": "مشتريات خاضعة للنسبة الأساسية", "amount": float(purchases.amount or 0), "vat": float(purchases.tax or 0)},
            },
            "totals": {
                "total_output_vat": float(total_output),
                "total_input_vat": float(total_input),
                "net_vat_due": float(net_vat_due),
                "status": "payable" if net_vat_due >= Decimal("0") else "refundable"
            }
        }


@router.get("/reports/tr-kdv", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def turkey_kdv_return_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    إقرار ضريبة القيمة المضافة (KDV) — تركيا
    يتبع نموذج هيئة recep Tayyip الضرائب التركية
    يجمع حسب معدل الضريبة: 1%، 10%، 20%
    """
    from datetime import date as date_cls
    if period_start is None or period_end is None:
        y = year or date_cls.today().year
        if period and period.startswith("Q"):
            q = int(period[1])
            ms = (q - 1) * 3 + 1; me = q * 3
            period_start = date_cls(y, ms, 1)
            period_end = date_cls(y, me, 28 if me == 2 else 30 if me in (4,6,9,11) else 31)
        else:
            period_start = date_cls(y, 1, 1)
            period_end = date_cls(y, 12, 31)

    with transactional(current_user.company_id) as db:
        params = {"start": period_start, "end": period_end}
        bf = branch_scope_filter(current_user, branch_id, "i.branch_id", params)

        # KDV 20% (general goods)
        kdv_20 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate = 20
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # KDV 10% (food, books, medicine)
        kdv_10 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate = 10
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # KDV 1% (basic food items)
        kdv_1 = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as taxable_amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate = 1
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Input VAT (purchases — all KDV rates combined)
        input_vat = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        total_output = (
            _dec(kdv_20.tax_amount) + _dec(kdv_10.tax_amount) + _dec(kdv_1.tax_amount)
        ).quantize(_D2, ROUND_HALF_UP)
        total_input = _dec(input_vat.tax_amount).quantize(_D2, ROUND_HALF_UP)
        net_payable = (total_output - total_input).quantize(_D2, ROUND_HALF_UP)

        return {
            "report_type": "tr_kdv_return",
            "report_name_ar": "إقرار ضريبة القيمة المضافة (KDV) — تركيا",
            "report_name_en": "VAT Return (KDV) — Turkey",
            "period": {"start": str(period_start), "end": str(period_end)},
            "kdv_20": {
                "label_ar": "ضريبة القيمة المضافة 20% (السلع العامة)",
                "label_en": "KDV 20% (General Goods)",
                "taxable_amount": float(kdv_20.taxable_amount or 0),
                "tax_amount": float(kdv_20.tax_amount or 0),
            },
            "kdv_10": {
                "label_ar": "ضريبة القيمة المضافة 10% (الغذاء، الكتب، الأدوية)",
                "label_en": "KDV 10% (Food, Books, Medicine)",
                "taxable_amount": float(kdv_10.taxable_amount or 0),
                "tax_amount": float(kdv_10.tax_amount or 0),
            },
            "kdv_1": {
                "label_ar": "ضريبة القيمة المضافة 1% (السلع الأساسية)",
                "label_en": "KDV 1% (Basic Food Items)",
                "taxable_amount": float(kdv_1.taxable_amount or 0),
                "tax_amount": float(kdv_1.tax_amount or 0),
            },
            "totals": {
                "total_output_vat": float(total_output),
                "total_input_vat": float(total_input),
                "net_payable": float(net_payable),
                "status": "payable" if net_payable >= Decimal("0") else "refundable",
            },
        }


@router.get("/reports/eg-vat", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def egypt_vat_return_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    إقرار ضريبة القيمة المضافة — جمهورية مصر العربية
    يتبع نموذج مصلحة الضرائب المصرية (ETA)
    """
    from datetime import date as date_cls
    if period_start is None or period_end is None:
        y = year or date_cls.today().year
        if period and period.startswith("Q"):
            q = int(period[1])
            ms = (q - 1) * 3 + 1; me = q * 3
            period_start = date_cls(y, ms, 1)
            period_end = date_cls(y, me, 28 if me == 2 else 30 if me in (4,6,9,11) else 31)
        elif period and period.isdigit():
            m = int(period)
            import calendar
            period_start = date_cls(y, m, 1)
            period_end = date_cls(y, m, calendar.monthrange(y, m)[1])
        else:
            period_start = date_cls(y, 1, 1)
            period_end = date_cls(y, 12, 31)
    with transactional(current_user.company_id) as db:
        params = {"start": period_start, "end": period_end}
        bf = branch_scope_filter(current_user, branch_id, "i.branch_id", params)

        # Output VAT (14%)
        output = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Input VAT
        input_v = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount,
                   COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate * (il.tax_rate / 100)), 0) as tax
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND il.tax_rate > 0
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()

        # Stamp duty (table tax) — applicable to some services  
        # (simplified: calculated as 0.9% of service revenue)
        services = db.execute(text(f"""
            SELECT COALESCE(SUM(il.quantity * il.unit_price * i.exchange_rate), 0) as amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            LEFT JOIN products p ON il.product_id = p.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND (p.product_type = 'service' OR p.id IS NULL)
            AND i.invoice_date BETWEEN :start AND :end {bf}
        """), params).fetchone()
        service_revenue = _dec(services.amount).quantize(_D2, ROUND_HALF_UP)
        stamp_duty = (service_revenue * Decimal("0.009")).quantize(_D2, ROUND_HALF_UP)  # 0.9%

        total_output = _dec(output.tax).quantize(_D2, ROUND_HALF_UP)
        total_input = _dec(input_v.tax).quantize(_D2, ROUND_HALF_UP)
        net_vat_due = (total_output - total_input).quantize(_D2, ROUND_HALF_UP)
        total_tax_due = (net_vat_due + stamp_duty).quantize(_D2, ROUND_HALF_UP)

        return {
            "report_type": "eg_vat_return",
            "report_name_ar": "إقرار ضريبة القيمة المضافة — مصلحة الضرائب المصرية",
            "report_name_en": "VAT Return — ETA Format",
            "period": {"start": period_start, "end": period_end},
            "output": {
                "taxable_sales": {"label_ar": "مبيعات خاضعة للضريبة (14%)", "amount": float(output.amount or 0), "vat": float(total_output)},
            },
            "input": {
                "taxable_purchases": {"label_ar": "مشتريات خاضعة للضريبة", "amount": float(input_v.amount or 0), "vat": float(total_input)},
            },
            "stamp_duty": {
                "service_revenue": float(service_revenue),
                "stamp_duty_amount": float(stamp_duty)
            },
            "totals": {
                "total_output_vat": float(total_output),
                "total_input_vat": float(total_input),
                "net_vat_due": float(net_vat_due),
                "stamp_duty": float(stamp_duty),
                "total_tax_due": float(total_tax_due),
                "status": "payable" if net_vat_due >= Decimal("0") else "refundable"
            }
        }


@router.get("/reports/generic-income", dependencies=[Depends(require_permission(["taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def generic_income_tax_report(
    fiscal_year: Optional[int] = None,
    year: Optional[int] = None,
    country_code: str = "SA",
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير ضريبة الدخل العام — يعمل لأي دولة
    يحسب صافي الربح ويطبق نسبة الضريبة حسب البلد
    """
    from datetime import date as date_cls
    fy = fiscal_year or year or date_cls.today().year
    with transactional(current_user.company_id) as db:
        start_date = f"{fy}-01-01"
        end_date = f"{fy}-12-31"
        params = {"start": start_date, "end": end_date}
        bf = branch_scope_filter(current_user, branch_id, "je.branch_id", params)

        revenue = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.credit - jl.debit), 0)
            FROM journal_lines jl 
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'revenue' AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {bf}
        """), params).scalar() or 0

        expenses = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND je.status = 'posted'
            AND je.entry_date BETWEEN :start AND :end {bf}
        """), params).scalar() or 0

        revenue_dec = _dec(revenue).quantize(_D2, ROUND_HALF_UP)
        expenses_dec = _dec(expenses).quantize(_D2, ROUND_HALF_UP)
        net_profit = (revenue_dec - expenses_dec).quantize(_D2, ROUND_HALF_UP)

        # Get tax rate from regimes
        regime = db.execute(text("""
            SELECT default_rate, name_ar, name_en FROM tax_regimes 
            WHERE country_code = :cc AND tax_type = 'income_tax' AND is_active = TRUE
            LIMIT 1
        """), {"cc": country_code.upper()}).fetchone()

        tax_rate_dec = _dec(regime.default_rate) if regime else Decimal("20")
        tax_rate = float(tax_rate_dec)
        tax_name_ar = regime.name_ar if regime else "ضريبة الدخل"
        tax_name_en = regime.name_en if regime else "Income Tax"

        income_tax = max(Decimal("0"), (net_profit * (tax_rate_dec / Decimal("100"))).quantize(_D2, ROUND_HALF_UP))

        country_info = COUNTRY_META.get(country_code.upper(), {})

        return {
            "report_type": "generic_income_tax",
            "report_name_ar": f"إقرار {tax_name_ar} — {country_info.get('name_ar', country_code)}",
            "report_name_en": f"{tax_name_en} Return — {country_info.get('name_en', country_code)}",
            "country_code": country_code.upper(),
            "fiscal_year": fiscal_year,
            "period": {"start": start_date, "end": end_date},
            "summary": {
                "total_revenue": float(revenue_dec),
                "total_expenses": float(expenses_dec),
                "net_profit": float(net_profit),
                "tax_rate": tax_rate,
                "tax_due": float(income_tax),
            }
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. COMPLIANCE OVERVIEW / DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/overview", dependencies=[Depends(require_permission(["taxes.view", "accounting.view"]))], response_model=Dict[str, Any])
def compliance_overview(current_user: dict = Depends(get_current_user)):
    """
    نظرة عامة على حالة الامتثال الضريبي
    يعرض حالة التسجيل لكل فرع والضرائب المطبقة والإقرارات المعلقة
    """
    db = get_db_connection(current_user.company_id)
    try:
        # Company tax settings
        company_tax = db.execute(text("SELECT * FROM company_tax_settings")).fetchall()

        # Branches with their jurisdictions
        branches = db.execute(text("""
            SELECT b.id, b.branch_name, b.branch_name_en, b.country_code,
                   COUNT(bts.id) as configured_taxes,
                   COUNT(bts.id) FILTER (WHERE bts.is_registered) as registered_taxes
            FROM branches b
            LEFT JOIN branch_tax_settings bts ON b.id = bts.branch_id AND bts.is_active = TRUE
            WHERE b.is_active = TRUE
            GROUP BY b.id, b.branch_name, b.branch_name_en, b.country_code
            ORDER BY b.id
        """)).fetchall()

        # Pending tax returns
        pending = db.execute(text("""
            SELECT COUNT(*) FILTER (WHERE status = 'draft') as draft,
                   COUNT(*) FILTER (WHERE status = 'filed') as filed,
                   COUNT(*) FILTER (WHERE status = 'filed' AND due_date < CURRENT_DATE) as overdue
            FROM tax_returns WHERE status NOT IN ('cancelled', 'paid')
        """)).fetchone()

        # Jurisdictions breakdown
        jurisdictions = {}
        for b in branches:
            cc = b.country_code or "SA"
            if cc not in jurisdictions:
                meta = COUNTRY_META.get(cc, {})
                jurisdictions[cc] = {
                    "country_code": cc,
                    "name_ar": meta.get("name_ar", cc),
                    "name_en": meta.get("name_en", cc),
                    "branches": [],
                    "has_vat": meta.get("has_vat", False),
                    "has_zakat": meta.get("has_zakat", False),
                }
            jurisdictions[cc]["branches"].append({
                "id": b.id,
                "name": b.branch_name,
                "name_en": b.branch_name_en,
                "configured_taxes": b.configured_taxes,
                "registered_taxes": b.registered_taxes,
            })

        return {
            "company_settings": [dict(r._mapping) for r in company_tax] if company_tax else [],
            "jurisdictions": list(jurisdictions.values()),
            "pending_returns": {
                "draft": pending.draft or 0,
                "filed": pending.filed or 0,
                "overdue": pending.overdue or 0,
            },
            "total_branches": len(branches),
            "countries_count": len(jurisdictions),
        }
    except Exception as e:
        logger.error(f"Error in compliance overview: {e}")
        return {
            "company_settings": [],
            "jurisdictions": [],
            "pending_returns": {"draft": 0, "filed": 0, "overdue": 0},
            "total_branches": 0,
            "countries_count": 0,
        }
    finally:
        db.close()
