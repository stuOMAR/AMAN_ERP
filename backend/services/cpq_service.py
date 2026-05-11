"""CPQ Service — validation, pricing, PDF generation."""
import os
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text


def validate_configuration(conn, configuration_id: int, selected_option_ids: list[int]) -> dict:
    """Validate selected options against requires/excludes rules.
    Returns { valid: bool, errors: [...] }.
    """
    rules = conn.execute(text("""
        SELECT vr.rule_type, vr.source_option_id, vr.target_option_id, vr.error_message,
               so.name as source_name, to2.name as target_name
        FROM config_validation_rules vr
        JOIN config_options so ON so.id = vr.source_option_id
        JOIN config_options to2 ON to2.id = vr.target_option_id
        WHERE vr.configuration_id = :cid
    """), {"cid": configuration_id}).fetchall()

    errors = []
    selected = set(selected_option_ids)

    for r in rules:
        row = dict(r._mapping)
        src_selected = row["source_option_id"] in selected
        tgt_selected = row["target_option_id"] in selected

        if row["rule_type"] == "requires" and src_selected and not tgt_selected:
            errors.append({
                "rule_type": "requires",
                "source_option": row["source_name"],
                "target_option": row["target_name"],
                "message": row["error_message"] or f"'{row['source_name']}' requires '{row['target_name']}'",
            })
        elif row["rule_type"] == "excludes" and src_selected and tgt_selected:
            errors.append({
                "rule_type": "excludes",
                "source_option": row["source_name"],
                "target_option": row["target_name"],
                "message": row["error_message"] or f"'{row['source_name']}' is incompatible with '{row['target_name']}'",
            })

    # Check required groups
    groups = conn.execute(text("""
        SELECT g.id, g.name, g.is_required
        FROM config_option_groups g
        WHERE g.configuration_id = :cid AND g.is_required = true
    """), {"cid": configuration_id}).fetchall()

    for g in groups:
        gd = dict(g._mapping)
        options_in_group = conn.execute(text(
            "SELECT id FROM config_options WHERE group_id = :gid"
        ), {"gid": gd["id"]}).fetchall()
        group_option_ids = {o.id for o in options_in_group}
        if not group_option_ids.intersection(selected):
            errors.append({
                "rule_type": "required_group",
                "source_option": gd["name"],
                "target_option": "",
                "message": i18n_message("cpq_group_requires_selection"),
            })

    return {"valid": len(errors) == 0, "errors": errors}


def calculate_price(conn, lines: list[dict], customer_id: int | None = None) -> dict:
    """Calculate price for each line, applying pricing rules.
    lines: [{product_id, configuration_id, selected_option_ids, quantity}]
    Returns: {lines: [...], total_amount, discount_total, final_amount}
    """
    result_lines = []
    total_amount = Decimal("0")
    discount_total = Decimal("0")
    final_amount = Decimal("0")

    # Resolve customer group if needed
    customer_group_id = None
    if customer_id:
        cg = conn.execute(text(
            "SELECT party_group_id FROM parties WHERE id = :pid"
        ), {"pid": customer_id}).fetchone()
        if cg:
            customer_group_id = cg.party_group_id

    for line in lines:
        product_id = line["product_id"]
        config_id = line["configuration_id"]
        selected_ids = line["selected_option_ids"]
        quantity = Decimal(str(line.get("quantity", 1)))

        # Base price from product
        prod = conn.execute(text(
            "SELECT selling_price FROM products WHERE id = :pid"
        ), {"pid": product_id}).fetchone()
        base_price = Decimal(str(prod.selling_price or 0)) if prod else Decimal("0")

        # Option adjustments
        option_adj = Decimal("0")
        if selected_ids:
            placeholders = ",".join(str(int(oid)) for oid in selected_ids)
            options = conn.execute(text(
                f"SELECT COALESCE(SUM(price_adjustment), 0) as total_adj FROM config_options WHERE id IN ({placeholders})"
            )).fetchone()
            option_adj = Decimal(str(options.total_adj))

        unit_before_discount = base_price + option_adj

        # Apply pricing rules (priority order: volume → customer → bundle)
        pricing_rules = conn.execute(text("""
            SELECT rule_type, min_quantity, max_quantity, discount_percent, discount_amount, customer_group_id
            FROM cpq_pricing_rules
            WHERE configuration_id = :cid
            ORDER BY priority ASC
        """), {"cid": config_id}).fetchall()

        discount = Decimal("0")
        for pr in pricing_rules:
            prd = dict(pr._mapping)
            if prd["rule_type"] == "volume_discount":
                mq = prd["min_quantity"] or 0
                xq = prd["max_quantity"] or 999999999
                if mq <= quantity <= xq:
                    if prd["discount_percent"]:
                        discount += (unit_before_discount * Decimal(str(prd["discount_percent"])) / Decimal("100"))
                    elif prd["discount_amount"]:
                        discount += Decimal(str(prd["discount_amount"]))
            elif prd["rule_type"] == "customer_discount":
                if customer_group_id and prd["customer_group_id"] == customer_group_id:
                    if prd["discount_percent"]:
                        discount += (unit_before_discount * Decimal(str(prd["discount_percent"])) / Decimal("100"))
                    elif prd["discount_amount"]:
                        discount += Decimal(str(prd["discount_amount"]))
            elif prd["rule_type"] == "bundle_discount":
                if prd["discount_percent"]:
                    discount += (unit_before_discount * Decimal(str(prd["discount_percent"])) / Decimal("100"))
                elif prd["discount_amount"]:
                    discount += Decimal(str(prd["discount_amount"]))

        discount = discount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        final_unit = (unit_before_discount - discount).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if final_unit < Decimal("0"):
            final_unit = Decimal("0")
        line_total = (final_unit * quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        result_lines.append({
            "product_id": product_id,
            "base_unit_price": base_price,
            "option_adjustments": option_adj,
            "discount_applied": discount,
            "final_unit_price": final_unit,
            "quantity": quantity,
            "line_total": line_total,
        })

        total_amount += (unit_before_discount * quantity).quantize(Decimal("0.0001"))
        discount_total += (discount * quantity).quantize(Decimal("0.0001"))
        final_amount += line_total

    return {
        "lines": result_lines,
        "total_amount": total_amount,
        "discount_total": discount_total,
        "final_amount": final_amount,
    }


def generate_quote_pdf(conn, quote_id: int, upload_dir: str) -> str:
    """Generate a professional PDF for a CPQ quote. Returns the file path."""
    # Fetch quote
    q = conn.execute(text("""
        SELECT q.*, p.name as customer_name
        FROM cpq_quotes q
        JOIN parties p ON p.id = q.customer_id
        WHERE q.id = :qid
    """), {"qid": quote_id}).fetchone()
    if not q:
        raise ValueError("Quote not found")
    qd = dict(q._mapping)

    # Fetch lines
    lines = conn.execute(text("""
        SELECT ql.*, pr.product_name
        FROM cpq_quote_lines ql
        JOIN products pr ON pr.id = ql.product_id
        WHERE ql.quote_id = :qid
        ORDER BY ql.id
    """), {"qid": quote_id}).fetchall()
    lines_data = [dict(l._mapping) for l in lines]

    # Build PDF
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        pdf_dir = os.path.join(upload_dir, "cpq_quotes")
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f"cpq_quote_{quote_id}.pdf")

        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"CPQ Quote #{quote_id}", styles["Title"]))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"Customer: {qd['customer_name']}", styles["Normal"]))
        elements.append(Paragraph(f"Status: {qd['status']}", styles["Normal"]))
        if qd.get("valid_until"):
            elements.append(Paragraph(f"Valid Until: {qd['valid_until']}", styles["Normal"]))
        elements.append(Spacer(1, 20))

        # Line items table
        table_data = [["Product", "Qty", "Base Price", "Options", "Discount", "Unit Price", "Total"]]
        for ld in lines_data:
            table_data.append([
                str(ld.get("product_name", "")),
                str(ld.get("quantity", 0)),
                str(ld.get("base_unit_price", 0)),
                str(ld.get("option_adjustments", 0)),
                str(ld.get("discount_applied", 0)),
                str(ld.get("final_unit_price", 0)),
                str(ld.get("line_total", 0)),
            ])

        t = Table(table_data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 20))

        # Totals
        elements.append(Paragraph(f"Subtotal: {qd.get('total_amount', 0)}", styles["Normal"]))
        elements.append(Paragraph(f"Discount: {qd.get('discount_total', 0)}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Total: {qd.get('final_amount', 0)}</b>", styles["Normal"]))

        doc.build(elements)
        return pdf_path

    except ImportError:
        # Fallback: generate a simple text-based receipt
        pdf_dir = os.path.join(upload_dir, "cpq_quotes")
        os.makedirs(pdf_dir, exist_ok=True)
        txt_path = os.path.join(pdf_dir, f"cpq_quote_{quote_id}.txt")

        with open(txt_path, "w") as f:
            f.write(f"CPQ Quote #{quote_id}\n")
            f.write(f"Customer: {qd['customer_name']}\n")
            f.write(f"Status: {qd['status']}\n")
            f.write(f"Valid Until: {qd.get('valid_until', 'N/A')}\n\n")
            f.write(f"{'Product':<30} {'Qty':>6} {'Base':>10} {'Adj':>10} {'Disc':>10} {'Unit':>10} {'Total':>10}\n")
            f.write("-" * 96 + "\n")
            for ld in lines_data:
                f.write(f"{str(ld.get('product_name','')):<30} {str(ld.get('quantity',0)):>6} "
                        f"{str(ld.get('base_unit_price',0)):>10} {str(ld.get('option_adjustments',0)):>10} "
                        f"{str(ld.get('discount_applied',0)):>10} {str(ld.get('final_unit_price',0)):>10} "
                        f"{str(ld.get('line_total',0)):>10}\n")
            f.write(f"\nSubtotal: {qd.get('total_amount', 0)}\n")
            f.write(f"Discount: {qd.get('discount_total', 0)}\n")
            f.write(f"Total:    {qd.get('final_amount', 0)}\n")
        return txt_path
