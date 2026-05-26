"""
Generic Invoice Preview API
===========================
Endpoint واحد يُحسب إجماليات أي نوع فاتورة/عقد/إشعار.
يُستخدم من كل الصفحات بدلاً من الحساب في frontend.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal
from datetime import date
from sqlalchemy import text

from routers.auth import get_current_user
from utils.i18n import http_error
from utils.permissions import validate_branch_access
from utils.tx import transactional
from utils.accounting import compute_line_amounts, compute_invoice_totals
from utils.tax_precision import money_str, rate_str
from services.tax_engine import resolve_line_tax_group

router = APIRouter(prefix="/calculate", tags=["Calculator"])


class LineInput(BaseModel):
    product_id: Optional[int] = None
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    tax_rate: Optional[Decimal] = None
    discount: Decimal = Decimal("0")  # fixed amount (not percentage)


class InvoicePreviewRequest(BaseModel):
    lines: List[LineInput]
    branch_id: Optional[int] = None
    party_id: Optional[int] = None
    customer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    document_date: Optional[date] = None
    header_discount_pct: Decimal = Decimal("0")  # percentage
    markup_amount: Decimal = Decimal("0")  # fixed amount
    paid_amount: Decimal = Decimal("0")
    currency: str = "SAR"


def _is_empty_preview_line(ln: LineInput) -> bool:
    return (
        ln.product_id is None
        and ln.tax_rate is None
        and Decimal(str(ln.unit_price or 0)) == 0
        and Decimal(str(ln.discount or 0)) == 0
    )


@router.post("/invoice-totals")
def calculate_invoice_totals(
    req: InvoicePreviewRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    حساب إجماليات أي فاتورة/عقد/إشعار بدون حفظ.
    يُستخدم من كل الصفحات في frontend.
    
    المدخلات:
      - lines: قائمة الأسطر (product_id, quantity, unit_price, discount)
      - branch_id + party/customer/supplier: لحل الضريبة من محرك الضرائب
      - header_discount_pct: خصم على مستوى الفاتورة (نسبة مئوية)
      - markup_amount: هامش ربح (مبلغ ثابت)
      - paid_amount: المبلغ المدفوع
      - currency: العملة
    
    المخرجات:
      - subtotal: المجموع قبل الخصم والضريبة
      - total_discount: إجمالي الخصم
      - total_tax: إجمالي الضريبة
      - grand_total: الإجمالي النهائي
      - paid_amount: المبلغ المدفوع
      - remaining_balance: المتبقي
      - lines: تفاصيل كل سطر
    """
    branch_id = validate_branch_access(current_user, req.branch_id) if req.branch_id else None
    party_id = req.party_id or req.customer_id or req.supplier_id
    doc_date = req.document_date

    lines_data = []
    line_details = []
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        if branch_id is None and any(ln.product_id for ln in req.lines):
            default_branch_id = db.execute(text("""
                SELECT id
                FROM branches
                WHERE is_default = TRUE
                  AND is_active = TRUE
                LIMIT 1
            """)).scalar()
            if default_branch_id:
                branch_id = validate_branch_access(current_user, default_branch_id)

        for i, ln in enumerate(req.lines):
            if _is_empty_preview_line(ln):
                continue
            if branch_id and ln.product_id:
                taxes = resolve_line_tax_group(branch_id, ln.product_id, db, doc_date, customer_id=party_id)
                tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
                tax_rate_id = taxes[0]["tax_rate_id"] if len(taxes) == 1 else None
                applied_taxes = [
                    {
                        "tax_rate_id": t.get("tax_rate_id"),
                        "tax_name": t.get("tax_name"),
                        "tax_rate": rate_str(t.get("tax_rate", 0)),
                    }
                    for t in taxes
                ] if len(taxes) > 1 else None
            elif ln.tax_rate is not None:
                # Compatibility fallback for older screens that have not yet
                # supplied branch/product context. Saved documents must still
                # resolve tax server-side in their own routers.
                tax_rate = ln.tax_rate
                tax_rate_id = None
                applied_taxes = None
            else:
                raise HTTPException(**http_error(400, "calculator_tax_rate_required", request))

            line_payload = {
                "quantity": ln.quantity,
                "unit_price": ln.unit_price,
                "tax_rate": tax_rate,
                "discount": ln.discount,
            }
            lines_data.append(line_payload)
            la = compute_line_amounts(
                ln.quantity,
                ln.unit_price,
                tax_rate,
                ln.discount,
                discount_is_percent=False,
            )
            line_details.append({
                "index": i,
                "product_id": ln.product_id,
                "quantity": money_str(ln.quantity),
                "unit_price": money_str(ln.unit_price),
                "tax_rate": rate_str(tax_rate),
                "tax_rate_id": tax_rate_id,
                "applied_taxes": applied_taxes,
                "discount": money_str(ln.discount),
                "subtotal": money_str(la["subtotal"]),
                "discount_amount": money_str(la["discount_amount"]),
                "taxable": money_str(la["taxable"]),
                "tax_amount": money_str(la["tax_amount"]),
                "line_total": money_str(la["line_total"]),
            })

        totals = compute_invoice_totals(
            lines_data,
            header_discount_pct=req.header_discount_pct,
            markup_amount=req.markup_amount,
            discount_is_percent=False,  # frontend sends fixed amounts
        )

    grand = totals["grand_total"]
    paid = Decimal(str(req.paid_amount or 0))

    return {
        "subtotal": money_str(totals["subtotal"]),
        "total_discount": money_str(totals["total_discount"]),
        "total_tax": money_str(totals["total_tax"]),
        "grand_total": money_str(grand),
        "paid_amount": money_str(paid),
        "remaining_balance": money_str(grand - paid),
        "currency": req.currency,
        "lines": line_details,
    }


class ContractLineInput(BaseModel):
    product_id: Optional[int] = None
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")


class ContractPreviewRequest(BaseModel):
    lines: List[ContractLineInput]
    branch_id: Optional[int] = None
    party_id: Optional[int] = None
    document_date: Optional[date] = None
    currency: str = "SAR"


@router.post("/contract-totals")
def calculate_contract_totals(
    req: ContractPreviewRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    حساب إجماليات العقد.
    الخصم في العقود يكون 0 (بدون خصم).
    """
    branch_id = validate_branch_access(current_user, req.branch_id) if req.branch_id else None
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id

    lines_data = []
    line_details = []
    with transactional(company_id) as db:
        if branch_id is None and any(ln.product_id for ln in req.lines):
            default_branch_id = db.execute(text("""
                SELECT id
                FROM branches
                WHERE is_default = TRUE
                  AND is_active = TRUE
                LIMIT 1
            """)).scalar()
            if default_branch_id:
                branch_id = validate_branch_access(current_user, default_branch_id)

        if any(ln.product_id for ln in req.lines) and branch_id is None:
            raise HTTPException(**http_error(400, "branch_required", request))

        for i, ln in enumerate(req.lines):
            if not ln.product_id and Decimal(str(ln.unit_price or 0)) == 0:
                continue
            if not ln.product_id:
                raise HTTPException(**http_error(400, "product_required", request))
            taxes = resolve_line_tax_group(branch_id, ln.product_id, db, req.document_date, customer_id=req.party_id)
            tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
            tax_rate_id = taxes[0]["tax_rate_id"] if len(taxes) == 1 else None
            applied_taxes = [
                {
                    "tax_rate_id": t.get("tax_rate_id"),
                    "tax_name": t.get("tax_name"),
                    "tax_rate": rate_str(t.get("tax_rate", 0)),
                }
                for t in taxes
            ] if len(taxes) > 1 else None

            lines_data.append({
                "quantity": ln.quantity,
                "unit_price": ln.unit_price,
                "tax_rate": tax_rate,
                "discount": 0,
            })
            la = compute_line_amounts(ln.quantity, ln.unit_price, tax_rate, 0, discount_is_percent=False)
            line_details.append({
                "index": i,
                "product_id": ln.product_id,
                "quantity": money_str(ln.quantity),
                "unit_price": money_str(ln.unit_price),
                "tax_rate": rate_str(tax_rate),
                "tax_rate_id": tax_rate_id,
                "applied_taxes": applied_taxes,
                "subtotal": money_str(la["subtotal"]),
                "tax_amount": money_str(la["tax_amount"]),
                "line_total": money_str(la["line_total"]),
            })

        totals = compute_invoice_totals(lines_data, discount_is_percent=False)

    return {
        "subtotal": money_str(totals["subtotal"]),
        "total_tax": money_str(totals["total_tax"]),
        "grand_total": money_str(totals["grand_total"]),
        "currency": req.currency,
        "lines": line_details,
    }
