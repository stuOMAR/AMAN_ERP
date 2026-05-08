from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text as sa_text
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal

from ..base import ModelBase


class Contract(ModelBase):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"))
    contract_type: Mapped[str | None] = mapped_column(String(50), default="subscription")
    status: Mapped[str | None] = mapped_column(String(20), default="draft")
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date | None] = mapped_column(Date)
    billing_interval: Mapped[str | None] = mapped_column(String(20), default="monthly")
    next_billing_date: Mapped[Date | None] = mapped_column(Date)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str | None] = mapped_column(String(3), default="SAR")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("1"))


class ContractItem(ModelBase):
    __tablename__ = "contract_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=1)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=0)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=0)
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), default=0)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpensePolicy(ModelBase):
    __tablename__ = "expense_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    expense_type: Mapped[str | None] = mapped_column(String(50))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), default=0)
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), default=0)
    annual_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), default=0)
    requires_receipt: Mapped[bool | None] = mapped_column(Boolean, default=True)
    requires_approval: Mapped[bool | None] = mapped_column(Boolean, default=True)
    auto_approve_below: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), default=0)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
