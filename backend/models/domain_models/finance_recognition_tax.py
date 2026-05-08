from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ModelBase


class RevenueRecognitionSchedule(ModelBase):
    __tablename__ = "revenue_recognition_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(Integer)
    contract_id: Mapped[int | None] = mapped_column(Integer)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    recognized_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), default=0)
    deferred_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), default=0)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    method: Mapped[str | None] = mapped_column(String(30), default="straight_line")
    status: Mapped[str | None] = mapped_column(String(20), default="active")
    schedule_lines: Mapped[dict | list | None] = mapped_column(JSONB, default=list)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxCalendar(ModelBase):
    __tablename__ = "tax_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_type: Mapped[str | None] = mapped_column(String(50))
    due_date: Mapped[Date] = mapped_column(Date, nullable=False)
    reminder_days: Mapped[dict | list | None] = mapped_column(JSONB, default=lambda: [7, 3, 1])
    is_recurring: Mapped[bool | None] = mapped_column(Boolean, default=False)
    recurrence_months: Mapped[int | None] = mapped_column(Integer, default=3)
    is_completed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recurrence_pattern: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str | None] = mapped_column(String(20))


class WhtRate(ModelBase):
    __tablename__ = "wht_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(100))
    rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), default="general")
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhtTransaction(ModelBase):
    __tablename__ = "wht_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(Integer)
    payment_id: Mapped[int | None] = mapped_column(Integer)
    supplier_id: Mapped[int | None] = mapped_column(Integer)
    wht_rate_id: Mapped[int | None] = mapped_column(ForeignKey("wht_rates.id"))
    gross_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    wht_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    wht_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    net_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    certificate_number: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(20), default="pending")
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    journal_entry_id: Mapped[int | None] = mapped_column(Integer)
    period_date: Mapped[Date | None] = mapped_column(Date)


class WhtRule(ModelBase):
    __tablename__ = "wht_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(5), nullable=False)
    payment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    gl_account_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "RevenueRecognitionSchedule",
    "TaxCalendar",
    "WhtRate",
    "WhtRule",
    "WhtTransaction",
]
