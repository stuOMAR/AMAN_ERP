"""
Generic Invoice Preview API
===========================
Endpoint واحد يُحسب إجماليات أي نوع فاتورة/عقد/إشعار.
يُستخدم من كل الصفحات بدلاً من الحساب في frontend.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from decimal import Decimal, ROUND_HALF_UP

from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.accounting import compute_line_amounts, compute_invoice_totals
from utils.tax_precision import money_str, rate_str

router = APIRouter(prefix="/calculate", tags=["Calculator"])


class LineInput(BaseModel):
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")  # fixed amount (not percentage)


class InvoicePreviewRequest(BaseModel):
    lines: List[LineInput]
    header_discount_pct: Decimal = Decimal("0")  # percentage
    markup_amount: Decimal = Decimal("0")  # fixed amount
    paid_amount: Decimal = Decimal("0")
    currency: str = "SAR"


@router.post("/invoice-totals")
def calculate_invoice_totals(
    req: InvoicePreviewRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    حساب إجماليات أي فاتورة/عقد/إشعار بدون حفظ.
    يُستخدم من كل الصفحات في frontend.
    
    المدخلات:
      - lines: قائمة الأسطر (quantity, unit_price, tax_rate, discount)
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
    lines_data = [
        {"quantity": ln.quantity, "unit_price": ln.unit_price, "tax_rate": ln.tax_rate, "discount": ln.discount}
        for ln in req.lines
    ]

    totals = compute_invoice_totals(
        lines_data,
        header_discount_pct=req.header_discount_pct,
        markup_amount=req.markup_amount,
        discount_is_percent=False,  # frontend sends fixed amounts
    )

    line_details = []
    for i, ln in enumerate(req.lines):
        la = compute_line_amounts(ln.quantity, ln.unit_price, ln.tax_rate, ln.discount, discount_is_percent=False)
        line_details.append({
            "index": i,
            "quantity": money_str(ln.quantity),
            "unit_price": money_str(ln.unit_price),
            "tax_rate": rate_str(ln.tax_rate),
            "discount": money_str(ln.discount),
            "subtotal": money_str(la["subtotal"]),
            "discount_amount": money_str(la["discount_amount"]),
            "taxable": money_str(la["taxable"]),
            "tax_amount": money_str(la["tax_amount"]),
            "line_total": money_str(la["line_total"]),
        })

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
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")


class ContractPreviewRequest(BaseModel):
    lines: List[ContractLineInput]
    currency: str = "SAR"


@router.post("/contract-totals")
def calculate_contract_totals(
    req: ContractPreviewRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    حساب إجماليات العقد.
    الخصم في العقود يكون 0 (بدون خصم).
    """
    lines_data = [
        {"quantity": ln.quantity, "unit_price": ln.unit_price, "tax_rate": ln.tax_rate, "discount": 0}
        for ln in req.lines
    ]

    totals = compute_invoice_totals(lines_data, discount_is_percent=False)

    line_details = []
    for i, ln in enumerate(req.lines):
        la = compute_line_amounts(ln.quantity, ln.unit_price, ln.tax_rate, 0, discount_is_percent=False)
        line_details.append({
            "index": i,
            "quantity": money_str(ln.quantity),
            "unit_price": money_str(ln.unit_price),
            "tax_rate": rate_str(ln.tax_rate),
            "subtotal": money_str(la["subtotal"]),
            "tax_amount": money_str(la["tax_amount"]),
            "line_total": money_str(la["line_total"]),
        })

    return {
        "subtotal": money_str(totals["subtotal"]),
        "total_tax": money_str(totals["total_tax"]),
        "grand_total": money_str(totals["grand_total"]),
        "currency": req.currency,
        "lines": line_details,
    }
