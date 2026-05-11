"""
Data Import / Export Router - DI-001, DI-002
استيراد/تصدير البيانات (Excel / CSV)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission
import logging
import io
from datetime import datetime

logger = logging.getLogger("aman.data_import")

router = APIRouter(prefix="/data-import", tags=["Data Import/Export"])


# ===================== Supported Entity Types =====================

IMPORT_CONFIGS = {
    "accounts": {
        "label": "دليل الحسابات",
        "table": "accounts",
        "required_columns": ["account_code", "account_name", "account_type"],
        "optional_columns": ["parent_code", "is_active", "description", "level", "currency"],
        "unique_key": "account_code",
    },
    "parties": {
        "label": "العملاء والموردين",
        "table": "parties",
        "required_columns": ["name", "party_type"],
        "optional_columns": ["tax_number", "phone", "email", "address", "city", "credit_limit"],
        "unique_key": "name",
    },
    "customers": {
        "label": "العملاء",
        "table": "customers",
        "required_columns": ["customer_name"],
        "optional_columns": ["customer_code", "tax_number", "phone", "email", "address", "city", "credit_limit"],
        "unique_key": "customer_name",
    },
    "suppliers": {
        "label": "الموردين",
        "table": "suppliers",
        "required_columns": ["supplier_name"],
        "optional_columns": ["supplier_code", "tax_number", "phone", "email", "address", "city", "credit_limit"],
        "unique_key": "supplier_name",
    },
    "products": {
        "label": "المنتجات",
        "table": "products",
        "required_columns": ["name", "sku"],
        "optional_columns": ["description", "unit_price", "cost_price", "is_active", "barcode"],
        "unique_key": "sku",
    },
    "employees": {
        "label": "الموظفين",
        "table": "employees",
        "required_columns": ["employee_number", "full_name"],
        "optional_columns": ["national_id", "department_id", "position", "hire_date", "basic_salary", "phone", "email"],
        "unique_key": "employee_number",
    },
}


@router.get("/entity-types", dependencies=[Depends(require_permission("data_import.view"))])
def list_importable_entities(current_user=Depends(get_current_user)):
    """قائمة الكيانات المتاحة للاستيراد"""
    return [
        {
            "value": key,
            "label": cfg["label"],
            "required_columns": cfg["required_columns"],
            "optional_columns": cfg["optional_columns"],
        }
        for key, cfg in IMPORT_CONFIGS.items()
    ]


@router.get("/template/{entity_type}", dependencies=[Depends(require_permission("data_import.view"))])
def download_template(entity_type: str, request: Request, current_user=Depends(get_current_user)):
    """تحميل قالب Excel/CSV للاستيراد"""
    if entity_type not in IMPORT_CONFIGS:
        raise HTTPException(**http_error(400, "unsupported_entity_type", request, type=entity_type))

    config = IMPORT_CONFIGS[entity_type]
    headers = config["required_columns"] + config["optional_columns"]

    # Return as CSV
    from fastapi.responses import StreamingResponse
    csv_content = ",".join(headers) + "\n"
    # Add example row
    example = {
        "accounts": "1001,حساب نقدي,asset,,true,,1,SAR",
        "parties": "شركة أمان,customer,,0500000000,info@aman.com,الرياض,الرياض,50000",
        "products": "لابتوب,PROD-001,لابتوب 15 بوصة,إلكترونيات,قطعة,3000,4500,10,",
        "employees": "EMP-001,أحمد محمد,,1,مدير,2024-01-01,15000,,",
    }
    csv_content += example.get(entity_type, "") + "\n"

    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={entity_type}_template.csv"}
    )


@router.post("/preview", dependencies=[Depends(require_permission(["data_import.create", "data_import.manage"]))])
async def preview_import(
    request: Request,
    file: UploadFile = File(...),
    entity_type: str = Query(...),
    current_user=Depends(get_current_user)
):
    """
    معاينة ملف الاستيراد مع التحقق من الصحة
    يدعم Excel (.xlsx) و CSV (.csv)
    """
    if entity_type not in IMPORT_CONFIGS:
        raise HTTPException(**http_error(400, "unsupported_entity_type", request, type=entity_type))

    config = IMPORT_CONFIGS[entity_type]
    content = await file.read()
    filename = file.filename.lower()

    # SEC-FIX-013/014: Validate file size and extension
    from utils.sql_safety import validate_file_size, validate_file_extension, MAX_IMPORT_FILE_SIZE, ALLOWED_IMPORT_EXTENSIONS
    validate_file_size(content, MAX_IMPORT_FILE_SIZE, "ملف الاستيراد")
    validate_file_extension(filename, ALLOWED_IMPORT_EXTENSIONS, "ملف الاستيراد")

    try:
        rows = _parse_file(content, filename)
    except Exception:
        logger.exception("Error parsing import file")
        raise HTTPException(**http_error(400, "file_read_error"))

    if not rows:
        raise HTTPException(**http_error(400, "file_empty"))

    # Validate columns
    headers = list(rows[0].keys()) if rows else []
    missing = [c for c in config["required_columns"] if c not in headers]
    if missing:
        raise HTTPException(**http_error(400, "missing_required_columns", request, columns=", ".join(missing)))

    # Validate rows
    preview_rows = []
    errors = []
    for i, row in enumerate(rows[:100]):  # Preview max 100 rows
        row_errors = []
        for col in config["required_columns"]:
            if not row.get(col) or str(row[col]).strip() == "":
                row_errors.append(f"الحقل '{col}' مطلوب")

        preview_rows.append({
            "row_number": i + 2,  # +2 for header + 1-indexing
            "data": row,
            "errors": row_errors,
            "valid": len(row_errors) == 0
        })
        if row_errors:
            errors.extend([f"سطر {i + 2}: {e}" for e in row_errors])

    valid_count = sum(1 for r in preview_rows if r["valid"])
    invalid_count = sum(1 for r in preview_rows if not r["valid"])

    return {
        "total_rows": len(rows),
        "preview_rows": preview_rows[:50],  # Show first 50 rows in preview
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "columns": headers,
        "required_columns": config["required_columns"],
        "errors": errors[:20],  # Show first 20 errors
    }


@router.post("/execute", dependencies=[Depends(require_permission(["data_import.create", "data_import.manage"]))])
async def execute_import(
    request: Request,
    file: UploadFile = File(...),
    entity_type: str = Query(...),
    skip_errors: bool = Query(True),
    current_user=Depends(get_current_user)
):
    """
    تنفيذ الاستيراد الفعلي
    """
    if entity_type not in IMPORT_CONFIGS:
        raise HTTPException(**http_error(400, "unsupported_entity_type", request, type=entity_type))

    config = IMPORT_CONFIGS[entity_type]

    # T2.1 / SEC-FIX-012: Defense-in-depth — validate config table & unique_key
    # before any f-string interpolation, even though IMPORT_CONFIGS is hardcoded.
    from utils.sql_safety import validate_sql_identifier
    validate_sql_identifier(config["table"], "table name")
    validate_sql_identifier(config["unique_key"], "unique key")

    content = await file.read()
    filename = file.filename.lower()

    # SEC-FIX-013/014: Validate file size and extension
    from utils.sql_safety import validate_file_size, validate_file_extension, MAX_IMPORT_FILE_SIZE, ALLOWED_IMPORT_EXTENSIONS
    validate_file_size(content, MAX_IMPORT_FILE_SIZE, "ملف الاستيراد")
    validate_file_extension(filename, ALLOWED_IMPORT_EXTENSIONS, "ملف الاستيراد")

    try:
        rows = _parse_file(content, filename)
    except Exception:
        logger.exception("Error parsing import file")
        raise HTTPException(**http_error(400, "file_read_error"))

    if not rows:
        raise HTTPException(**http_error(400, "file_empty"))

    with transactional(current_user.company_id) as db:
        try:
            inserted = 0
            updated = 0
            skipped = 0
            errors = []
            all_columns = config["required_columns"] + config["optional_columns"]
    
            for i, row in enumerate(rows):
                try:
                    # Validate required fields
                    missing = [c for c in config["required_columns"] if not row.get(c) or str(row[c]).strip() == ""]
                    if missing:
                        if skip_errors:
                            skipped += 1
                            errors.append(f"سطر {i + 2}: حقول ناقصة: {', '.join(missing)}")
                            continue
                        else:
                            raise HTTPException(**http_error(400, "missing_required_fields_line", request, line=i + 2, fields=", ".join(missing)))
    
                    # Build columns/values
                    # SEC-FIX-012: Validate column names are safe SQL identifiers
                    from utils.sql_safety import validate_sql_identifier
                    row_cols = [c for c in all_columns if c in row and row[c] is not None and str(row[c]).strip() != ""]
                    for col in row_cols:
                        validate_sql_identifier(col, "column name")
                    col_names = ", ".join(row_cols)
                    col_params = ", ".join([f":{c}" for c in row_cols])
                    params = {c: row[c] for c in row_cols}
    
                    # Upsert logic
                    unique_key = config["unique_key"]
                    if unique_key in params:
                        # Check if exists
                        existing = db.execute(text( # noqa: sql-lint
                                    f"""
                            SELECT id FROM {config['table']} WHERE {unique_key} = :ukey
                        """), {"ukey": params[unique_key]}).fetchone()
    
                        if existing:
                            # Update
                            set_clause = ", ".join([f"{c} = :{c}" for c in row_cols if c != unique_key])
                            if set_clause:
                                db.execute(text( # noqa: sql-lint
                                            f"""
                                    UPDATE {config['table']} SET {set_clause} WHERE {unique_key} = :{unique_key}
                                """), params)
                                updated += 1
                            else:
                                skipped += 1
                        else:
                            # Insert
                            db.execute(text( # noqa: sql-lint
                                        f"""
                                INSERT INTO {config['table']} ({col_names}) VALUES ({col_params})
                            """), params)
                            inserted += 1
                    else:
                        db.execute(text( # noqa: sql-lint
                                    f"""
                            INSERT INTO {config['table']} ({col_names}) VALUES ({col_params})
                        """), params)
                        inserted += 1
    
                except HTTPException:
                    raise
                except Exception:
                    if skip_errors:
                        skipped += 1
                        errors.append(f"سطر {i + 2}: خطأ في البيانات")
                        logger.warning(f"Import row {i + 2} error", exc_info=True)
                    else:
                        logger.exception(f"Import error at row {i + 2}")
                        raise HTTPException(**http_error(400, "import_line_error", request, line=i + 2))
    
    
            try:
                log_activity(db, current_user.id, current_user.username, "import",
                             config["table"], "batch",
                             {"entity_type": entity_type, "inserted": inserted, "updated": updated, "skipped": skipped})
            except Exception:
                pass
    
            return {
                "message": i18n_message("import_successful", request),
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "total": len(rows),
                "errors": errors[:50]
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Export =====================

@router.get("/export/{entity_type}", dependencies=[Depends(require_permission("data_import.view"))])
def export_data(
    entity_type: str,
    request: Request,
    format: str = Query("csv", enum=["csv", "json"]),
    current_user=Depends(get_current_user)
):
    """تصدير البيانات بتنسيق CSV أو JSON"""
    if entity_type not in IMPORT_CONFIGS:
        raise HTTPException(**http_error(400, "unsupported_entity_type", request, type=entity_type))

    config = IMPORT_CONFIGS[entity_type]

    # T2.1 / SEC-FIX-012: Defense-in-depth — validate config table before f-string.
    from utils.sql_safety import validate_sql_identifier
    validate_sql_identifier(config["table"], "table name")

    with transactional(current_user.company_id) as db:
        try:
            all_columns = config["required_columns"] + config["optional_columns"]
            
            # Get actual columns in the table to avoid missing column errors
            actual_cols = db.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = :table
            """), {"table": config["table"]}).fetchall()
            existing_cols = {r[0] for r in actual_cols}
            col_list_filtered = [c for c in all_columns if c in existing_cols]
            
            if not col_list_filtered:
                raise HTTPException(**http_error(500, "no_matching_columns", request))
            
            col_list = ", ".join(col_list_filtered)
    
            rows = db.execute(text(f"SELECT {col_list} FROM {config['table']}")).fetchall() # noqa: sql-lint
            data = [dict(r._mapping) for r in rows]
    
            if format == "json":
                from fastapi.responses import JSONResponse
                return JSONResponse(content=data)
            else:
                from fastapi.responses import StreamingResponse
                csv_lines = [",".join(col_list_filtered)]
                for row in data:
                    csv_lines.append(",".join([_csv_escape(str(row.get(c, "") or "")) for c in col_list_filtered]))
    
                csv_content = "\n".join(csv_lines)
                return StreamingResponse(
                    io.StringIO(csv_content),
                    media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={entity_type}_export_{datetime.now().strftime('%Y%m%d')}.csv"}
                )
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Import History =====================

@router.get("/history", dependencies=[Depends(require_permission("data_import.view"))])
def import_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user)
):
    """سجل عمليات الاستيراد السابقة"""
    with transactional(current_user.company_id) as db:
        try:
            offset = (page - 1) * limit
            rows = db.execute(text("""
                SELECT * FROM audit_logs
                WHERE action = 'import'
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), {"limit": limit, "offset": offset}).fetchall()
    
            return {"items": [dict(r._mapping) for r in rows], "page": page}
        except Exception:
            return {"items": [], "page": page}


# ===================== Helpers =====================

def _parse_file(content: bytes, filename: str) -> list:
    """Parse uploaded file (CSV or Excel) into list of dicts."""
    if filename.endswith(".csv"):
        import csv
        text_content = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))
        return [dict(row) for row in reader]
    elif filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            headers = [str(h).strip() for h in next(rows_iter)]
            data = []
            for row in rows_iter:
                row_dict = {}
                for j, val in enumerate(row):
                    if j < len(headers):
                        row_dict[headers[j]] = val
                data.append(row_dict)
            return data
        except ImportError:
            raise ValueError("مكتبة openpyxl غير مثبتة. قم بتشغيل: pip install openpyxl")
    else:
        raise ValueError("الصيغة غير مدعومة. يرجى استخدام CSV أو Excel")


def _csv_escape(value: str) -> str:
    """Escape CSV field value."""
    if "," in value or '"' in value or "\n" in value:
        return f'"{value.replace(chr(34), chr(34)+chr(34))}"'
    return value
