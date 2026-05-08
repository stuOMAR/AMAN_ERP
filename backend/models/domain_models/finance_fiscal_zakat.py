from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ModelBase


class FiscalYear(ModelBase):
    __tablename__ = "fiscal_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), default="open")
    retained_earnings_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    closing_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id", ondelete="SET NULL"))
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    closed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    reopened_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    reopened_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FiscalPeriodLock(ModelBase):
    __tablename__ = "fiscal_period_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_name: Mapped[str] = mapped_column(String(100), nullable=False)
    period_start: Mapped[Date] = mapped_column(Date, nullable=False)
    period_end: Mapped[Date] = mapped_column(Date, nullable=False)
    is_locked: Mapped[bool | None] = mapped_column(Boolean, default=False)
    locked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    unlocked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    unlocked_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ZakatCalculation(ModelBase):
    __tablename__ = "zakat_calculations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    method: Mapped[str | None] = mapped_column(String(30), default="net_assets")
    zakat_base: Mapped[float | None] = mapped_column(Numeric(15, 4), default=0)
    zakat_rate: Mapped[float | None] = mapped_column(Numeric(8, 4), default=2.5)
    zakat_amount: Mapped[float | None] = mapped_column(Numeric(15, 4), default=0)
    details: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    status: Mapped[str | None] = mapped_column(String(20), default="calculated")
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    calculated_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    calculated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ZakatBaseItem(ModelBase):
    __tablename__ = "zakat_base_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(6, 4), default=1.0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
