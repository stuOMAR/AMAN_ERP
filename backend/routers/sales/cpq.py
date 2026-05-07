"""CPQ (Configure-Price-Quote) endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.audit import log_activity
from services.cpq_service import validate_configuration, calculate_price, generate_quote_pdf

cpq_router = APIRouter(prefix="/cpq", tags=["CPQ"])
logger = logging.getLogger(__name__)


# ─── GET /products — list configurable products ───
@cpq_router.get("/products", dependencies=[Depends(require_permission("sales.cpq_view"))])
def list_configurable_products(
    current_user: dict = Depends(get_current_user),
):
    """List Configurable Products."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT pc.id, pc.product_id, pc.name, pc.is_active,
                   p.product_name, p.product_code, p.selling_price
            FROM product_configurations pc
            JOIN products p ON p.id = pc.product_id
            WHERE pc.is_active = true
            ORDER BY pc.id DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ─── GET /products/{id}/configure — get full configuration ───
@cpq_router.get("/products/{config_id}/configure", dependencies=[Depends(require_permission("sales.cpq_view"))])
def get_configuration(
    config_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get Configuration."""
    db = get_db_connection(current_user.company_id)
    try:
        # Config header
        cfg = db.execute(text("""
            SELECT pc.*, p.product_name, p.selling_price
            FROM product_configurations pc
            JOIN products p ON p.id = pc.product_id
            WHERE pc.id = :cid
        """), {"cid": config_id}).fetchone()
        if not cfg:
            raise HTTPException(status_code=404, detail="Configuration not found")
        result = dict(cfg._mapping)

        # Groups + options
        groups = db.execute(text("""
            SELECT * FROM config_option_groups WHERE configuration_id = :cid ORDER BY sort_order
        """), {"cid": config_id}).fetchall()
        groups_data = []
        for g in groups:
            gd = dict(g._mapping)
            options = db.execute(text("""
                SELECT * FROM config_options WHERE group_id = :gid ORDER BY sort_order
            """), {"gid": gd["id"]}).fetchall()
            gd["options"] = [dict(o._mapping) for o in options]
            groups_data.append(gd)
        result["groups"] = groups_data

        # Validation rules
        rules = db.execute(text("""
            SELECT vr.*, so.name as source_name, to2.name as target_name
            FROM config_validation_rules vr
            JOIN config_options so ON so.id = vr.source_option_id
            JOIN config_options to2 ON to2.id = vr.target_option_id
            WHERE vr.configuration_id = :cid
        """), {"cid": config_id}).fetchall()
        result["rules"] = [dict(r._mapping) for r in rules]

        # Pricing rules
        pricing = db.execute(text("""
            SELECT * FROM cpq_pricing_rules WHERE configuration_id = :cid ORDER BY priority
        """), {"cid": config_id}).fetchall()
        result["pricing_rules"] = [dict(p._mapping) for p in pricing]

        return result
    finally:
        db.close()


# ─── POST /validate — validate configuration combination ───
@cpq_router.post("/validate", dependencies=[Depends(require_permission("sales.cpq_create"))])
def validate_config(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Validate Config."""
    db = get_db_connection(current_user.company_id)
    try:
        result = validate_configuration(
            db,
            body["configuration_id"],
            body.get("selected_option_ids", []),
        )
        return result
    finally:
        db.close()


# ─── POST /price — calculate price ───
@cpq_router.post("/price", dependencies=[Depends(require_permission("sales.cpq_create"))])
def calculate_price_endpoint(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Calculate Price Endpoint."""
    db = get_db_connection(current_user.company_id)
    try:
        result = calculate_price(
            db,
            body.get("lines", []),
            body.get("customer_id"),
        )
        # Convert Decimal to str for JSON serialization
        for line in result["lines"]:
            for k, v in line.items():
                if hasattr(v, "quantize"):
                    line[k] = str(v)
        result["total_amount"] = str(result["total_amount"])
        result["discount_total"] = str(result["discount_total"])
        result["final_amount"] = str(result["final_amount"])
        return result
    finally:
        db.close()


# ─── POST /quotes — create CPQ quote ───
@cpq_router.post("/quotes", dependencies=[Depends(require_permission("sales.cpq_create"))])
def create_quote(
    body: dict,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Create Quote."""
    db = get_db_connection(current_user.company_id)
    try:
        lines_input = body.get("lines", [])
        customer_id = body["customer_id"]
        valid_until = body.get("valid_until")

        # Calculate pricing
        pricing = calculate_price(db, lines_input, customer_id)

        # Create quote
        q = db.execute(text("""
            INSERT INTO cpq_quotes (customer_id, total_amount, discount_total, final_amount, status, valid_until)
            VALUES (:cust, :total, :disc, :final, 'draft', :valid)
            RETURNING id
        """), {
            "cust": customer_id,
            "total": str(pricing["total_amount"]),
            "disc": str(pricing["discount_total"]),
            "final": str(pricing["final_amount"]),
            "valid": valid_until,
        }).fetchone()
        quote_id = q.id

        # Create lines
        import json
        for i, line_input in enumerate(lines_input):
            pl = pricing["lines"][i]
            db.execute(text("""
                INSERT INTO cpq_quote_lines
                    (quote_id, product_id, selected_options, quantity,
                     base_unit_price, option_adjustments, discount_applied,
                     final_unit_price, line_total)
                VALUES (:qid, :pid, :opts, :qty, :base, :adj, :disc, :fup, :lt)
            """), {
                "qid": quote_id,
                "pid": line_input["product_id"],
                "opts": json.dumps(line_input.get("selected_option_ids", [])),
                "qty": str(pl["quantity"]),
                "base": str(pl["base_unit_price"]),
                "adj": str(pl["option_adjustments"]),
                "disc": str(pl["discount_applied"]),
                "fup": str(pl["final_unit_price"]),
                "lt": str(pl["line_total"]),
            })

        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="sales.cpq.quote_create", resource_type="cpq_quote",
            resource_id=str(quote_id), details={"customer_id": customer_id},
            request=request
        )
        db.commit()
        return {"id": quote_id, "status": "draft"}
    except Exception as e:
        db.rollback()
        logger.error(f"create_quote error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── GET /quotes/{id} — get quote detail ───
@cpq_router.get("/quotes/{quote_id}", dependencies=[Depends(require_permission("sales.cpq_view"))])
def get_quote(
    quote_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get Quote."""
    db = get_db_connection(current_user.company_id)
    try:
        q = db.execute(text("""
            SELECT q.*, p.name as customer_name
            FROM cpq_quotes q
            JOIN parties p ON p.id = q.customer_id
            WHERE q.id = :qid
        """), {"qid": quote_id}).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        result = dict(q._mapping)

        lines = db.execute(text("""
            SELECT ql.*, pr.product_name
            FROM cpq_quote_lines ql
            JOIN products pr ON pr.id = ql.product_id
            WHERE ql.quote_id = :qid
            ORDER BY ql.id
        """), {"qid": quote_id}).fetchall()
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
    finally:
        db.close()


# ─── POST /quotes/{id}/generate-pdf ───
@cpq_router.post("/quotes/{quote_id}/generate-pdf", dependencies=[Depends(require_permission("sales.cpq_create"))])
def generate_pdf(
    quote_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Generate PDF."""
    import os
    db = get_db_connection(current_user.company_id)
    try:
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
        pdf_path = generate_quote_pdf(db, quote_id, upload_dir)

        # Store path on quote
        db.execute(text(
            "UPDATE cpq_quotes SET pdf_path = :path WHERE id = :qid"
        ), {"path": pdf_path, "qid": quote_id})
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="sales.cpq.quote_generate_pdf", resource_type="cpq_quote",
            resource_id=str(quote_id), details={"pdf_path": pdf_path},
            request=request
        )
        db.commit()

        return {"pdf_path": pdf_path}
    except ValueError:
        logger.exception("Internal error")
        raise HTTPException(**http_error(404, "invalid_data"))
    except Exception as e:
        db.rollback()
        logger.error(f"generate_pdf error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ─── POST /quotes/{id}/convert — convert to standard quotation ───
@cpq_router.post("/quotes/{quote_id}/convert", dependencies=[Depends(require_permission("sales.cpq_create"))])
def convert_to_quotation(
    quote_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Convert To Quotation."""
    db = get_db_connection(current_user.company_id)
    try:
        q = db.execute(text(
            "SELECT * FROM cpq_quotes WHERE id = :qid"
        ), {"qid": quote_id}).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Quote not found")
        qd = dict(q._mapping)

        if qd.get("quotation_id"):
            raise HTTPException(status_code=400, detail="Quote already converted")

        # Find customer record
        cust = db.execute(text(
            "SELECT id FROM parties WHERE id = :pid AND (party_type = 'customer' OR is_customer = TRUE) LIMIT 1"
        ), {"pid": qd["customer_id"]}).fetchone()
        customer_id = cust.id if cust else qd["customer_id"]

        # Get branch of current user
        branch = db.execute(text(
            "SELECT branch_id FROM company_users WHERE id = :uid LIMIT 1"
        ), {"uid": current_user.id}).fetchone()
        branch_id = branch.branch_id if branch else None

        # Generate SQ number
        seq = db.execute(text(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(sq_number FROM '[0-9]+$') AS INTEGER)), 0) + 1 as next_num FROM sales_quotations"
        )).fetchone()
        sq_number = f"SQ-{seq.next_num:06d}"

        # Create sales quotation
        sq = db.execute(text("""
            INSERT INTO sales_quotations (sq_number, party_id, customer_id, branch_id, total, status)
            VALUES (:sqn, :pid, :cid, :bid, :total, 'draft')
            RETURNING id
        """), {
            "sqn": sq_number,
            "pid": qd["customer_id"],
            "cid": customer_id,
            "bid": branch_id,
            "total": str(qd.get("final_amount", 0)),
        }).fetchone()
        sq_id = sq.id

        # Create quotation lines from CPQ lines
        lines = db.execute(text(
            "SELECT * FROM cpq_quote_lines WHERE quote_id = :qid"
        ), {"qid": quote_id}).fetchall()
        for line in lines:
            ld = dict(line._mapping)
            db.execute(text("""
                INSERT INTO sales_quotation_lines (sq_id, product_id, quantity, unit_price, total, discount_amount)
                VALUES (:sqid, :pid, :qty, :up, :total, :disc)
            """), {
                "sqid": sq_id,
                "pid": ld["product_id"],
                "qty": str(ld["quantity"]),
                "up": str(ld["final_unit_price"]),
                "total": str(ld["line_total"]),
                "disc": str(ld["discount_applied"]),
            })

        # Update CPQ quote with conversion link
        db.execute(text(
            "UPDATE cpq_quotes SET quotation_id = :sqid, status = 'accepted' WHERE id = :qid"
        ), {"sqid": sq_id, "qid": quote_id})

        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="sales.cpq.quote_convert", resource_type="cpq_quote",
            resource_id=str(quote_id), details={"quotation_id": sq_id, "sq_number": sq_number},
            request=request
        )
        db.commit()
        return {"quotation_id": sq_id, "sq_number": sq_number}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"convert_to_quotation error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
