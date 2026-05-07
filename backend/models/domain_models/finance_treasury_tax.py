from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ModelBase


class TreasuryTransaction(ModelBase):
    __tablename__ = "treasury_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    transaction_date: Mapped[Date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    treasury_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_accounts.id"))
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    target_treasury_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_accounts.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    description: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(20), default="posted")
    exchange_rate: Mapped[float | None] = mapped_column(Numeric(18, 6), server_default=sa_text("1.0"))
    currency: Mapped[str | None] = mapped_column(String(3))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankReconciliation(ModelBase):
    __tablename__ = "bank_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    treasury_account_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_accounts.id"))
    statement_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    end_balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str | None] = mapped_column(String(20), default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankStatementLine(ModelBase):
    __tablename__ = "bank_statement_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reconciliation_id: Mapped[int | None] = mapped_column(ForeignKey("bank_reconciliations.id", ondelete="CASCADE"))
    transaction_date: Mapped[Date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(100))
    debit: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    credit: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    is_reconciled: Mapped[bool | None] = mapped_column(Boolean, default=False)
    matched_journal_line_id: Mapped[int | None] = mapped_column(ForeignKey("journal_lines.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxRate(ModelBase):
    __tablename__ = "tax_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tax_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    tax_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_name_en: Mapped[str | None] = mapped_column(String(255))
    rate_type: Mapped[str | None] = mapped_column(String(20), default="percentage")
    rate_value: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0)
    country_code: Mapped[str | None] = mapped_column(String(5))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(2))
    description: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[Date | None] = mapped_column(Date)
    effective_to: Mapped[Date | None] = mapped_column(Date)
    is_default: Mapped[bool | None] = mapped_column(Boolean, default=False)
    legal_entity_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxGroup(ModelBase):
    __tablename__ = "tax_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name_en: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    tax_ids: Mapped[list | None] = mapped_column(JSONB)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxReturn(ModelBase):
    __tablename__ = "tax_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    tax_period: Mapped[str | None] = mapped_column(String(50))
    tax_type: Mapped[str] = mapped_column(String(50), nullable=False)
    taxable_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    tax_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    penalty_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    interest_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    due_date: Mapped[Date | None] = mapped_column(Date)
    filed_date: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(20), default="draft")
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    jurisdiction_code: Mapped[str | None] = mapped_column(String(2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxPayment(ModelBase):
    __tablename__ = "tax_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    tax_return_id: Mapped[int | None] = mapped_column(ForeignKey("tax_returns.id"))
    payment_date: Mapped[Date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(20), default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaxRegime(ModelBase):
    __tablename__ = "tax_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    tax_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    default_rate: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0)
    is_required: Mapped[bool | None] = mapped_column(Boolean, default=False)
    applies_to: Mapped[str | None] = mapped_column(String(50), default="all")
    filing_frequency: Mapped[str | None] = mapped_column(String(20), default="quarterly")
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BranchTaxSetting(ModelBase):
    __tablename__ = "branch_tax_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    tax_regime_id: Mapped[int] = mapped_column(ForeignKey("tax_regimes.id", ondelete="CASCADE"), nullable=False)
    is_registered: Mapped[bool | None] = mapped_column(Boolean, default=False)
    registration_number: Mapped[str | None] = mapped_column(String(100))
    custom_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    is_exempt: Mapped[bool | None] = mapped_column(Boolean, default=False)
    exemption_reason: Mapped[str | None] = mapped_column(Text)
    exemption_certificate: Mapped[str | None] = mapped_column(String(100))
    exemption_expiry: Mapped[Date | None] = mapped_column(Date)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyTaxSetting(ModelBase):
    __tablename__ = "company_tax_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    is_vat_registered: Mapped[bool | None] = mapped_column(Boolean, default=False)
    vat_number: Mapped[str | None] = mapped_column(String(50))
    zakat_number: Mapped[str | None] = mapped_column(String(50))
    tax_registration_number: Mapped[str | None] = mapped_column(String(100))
    commercial_registry: Mapped[str | None] = mapped_column(String(100))
    fiscal_year_start: Mapped[str | None] = mapped_column(String(5), default="01-01")
    default_filing_frequency: Mapped[str | None] = mapped_column(String(20), default="quarterly")
    zatca_phase: Mapped[str | None] = mapped_column(String(20), default="none")
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "BankReconciliation",
    "BankStatementLine",
    "BranchTaxSetting",
    "CompanyTaxSetting",
    "TaxGroup",
    "TaxPayment",
    "TaxRate",
    "TaxRegime",
    "TaxReturn",
    "TreasuryTransaction",
]
