from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import AuditMixin, ModelBase


class PendingReceivable(AuditMixin, ModelBase):
    __tablename__ = "pending_receivables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    due_date: Mapped[Date | None] = mapped_column(Date)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    outstanding_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    days_overdue: Mapped[int | None] = mapped_column(Integer, default=0)
    status: Mapped[str | None] = mapped_column(String(20), default="pending")


class PosKitchenOrder(AuditMixin, ModelBase):
    __tablename__ = "pos_kitchen_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="SET NULL"))
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("pos_order_lines.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    product_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 3))
    notes: Mapped[str | None] = mapped_column(Text)
    station: Mapped[str | None] = mapped_column(String(100), default="main")
    status: Mapped[str | None] = mapped_column(String(30), default="pending")
    priority: Mapped[int | None] = mapped_column(Integer, default=0)
    sent_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))


class PosLoyaltyPoint(AuditMixin, ModelBase):
    __tablename__ = "pos_loyalty_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("pos_loyalty_programs.id"))
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    points_earned: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0)
    points_redeemed: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0)
    balance: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0)
    tier: Mapped[str | None] = mapped_column(String(50), default="standard")
    last_activity_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PosLoyaltyProgram(AuditMixin, ModelBase):
    __tablename__ = "pos_loyalty_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    points_per_unit: Mapped[float | None] = mapped_column(Numeric(10, 4), default=1)
    currency_per_point: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0.01)
    min_points_redeem: Mapped[int | None] = mapped_column(Integer, default=100)
    tier_rules: Mapped[list | None] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))


class PosLoyaltyTransaction(AuditMixin, ModelBase):
    __tablename__ = "pos_loyalty_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loyalty_id: Mapped[int | None] = mapped_column(ForeignKey("pos_loyalty_points.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="SET NULL"))
    txn_type: Mapped[str] = mapped_column(String(20), nullable=False)
    points: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class PosOrderLine(AuditMixin, ModelBase):
    __tablename__ = "pos_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    original_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), default=0)
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    tax_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    discount_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2), default=0)
    discount_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    subtotal: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    total: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class PosOrderPayment(AuditMixin, ModelBase):
    __tablename__ = "pos_order_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))


class PosOrder(AuditMixin, ModelBase):
    __tablename__ = "pos_orders"
    __table_args__ = (UniqueConstraint("order_number", name="pos_orders_order_number_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sessions.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    walk_in_customer_name: Mapped[str | None] = mapped_column(String(255))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    order_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str | None] = mapped_column(String(20), default="draft")
    subtotal: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    discount_type: Mapped[str | None] = mapped_column(String(20), default="amount")
    discount_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    tax_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    total_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    change_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    note: Mapped[str | None] = mapped_column(Text)
    coupon_code: Mapped[str | None] = mapped_column(String(100))
    loyalty_points_earned: Mapped[float | None] = mapped_column(Numeric(12, 2))
    loyalty_points_redeemed: Mapped[float | None] = mapped_column(Numeric(12, 2))
    party_id: Mapped[int | None] = mapped_column(Integer)
    promotion_id: Mapped[int | None] = mapped_column(Integer)
    table_id: Mapped[int | None] = mapped_column(Integer)


class PosPayment(AuditMixin, ModelBase):
    __tablename__ = "pos_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sessions.id"))
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100))


class PosPromotion(AuditMixin, ModelBase):
    __tablename__ = "pos_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    promotion_type: Mapped[str] = mapped_column(String(50), nullable=False, default="percentage")
    value: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    buy_qty: Mapped[int | None] = mapped_column(Integer)
    get_qty: Mapped[int | None] = mapped_column(Integer)
    coupon_code: Mapped[str | None] = mapped_column(String(100))
    applicable_products: Mapped[str | None] = mapped_column(Text)
    applicable_categories: Mapped[str | None] = mapped_column(Text)
    min_order_amount: Mapped[float | None] = mapped_column(Numeric(15, 2), default=0)
    start_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))


class PosReturnItem(AuditMixin, ModelBase):
    __tablename__ = "pos_return_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int | None] = mapped_column(ForeignKey("pos_returns.id", ondelete="CASCADE"))
    original_item_id: Mapped[int | None] = mapped_column(ForeignKey("pos_order_lines.id", ondelete="SET NULL"))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    reason: Mapped[str | None] = mapped_column(Text)


class PosReturn(AuditMixin, ModelBase):
    __tablename__ = "pos_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sessions.id"))
    refund_amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    refund_method: Mapped[str | None] = mapped_column(String(50), default="cash")
    notes: Mapped[str | None] = mapped_column(Text)


class PosSession(AuditMixin, ModelBase):
    __tablename__ = "pos_sessions"
    __table_args__ = (UniqueConstraint("session_code", name="pos_sessions_session_code_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_code: Mapped[str | None] = mapped_column(String(50))
    pos_profile_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    opening_balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    closing_balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    total_sales: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    total_returns: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    cash_register_balance: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    difference: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str | None] = mapped_column(String(20), default="opened")
    opened_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    treasury_account_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_accounts.id"))


class PosTableOrder(AuditMixin, ModelBase):
    __tablename__ = "pos_table_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("pos_tables.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("pos_orders.id", ondelete="SET NULL"))
    seated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cleared_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    guests: Mapped[int | None] = mapped_column(Integer, default=1)
    waiter_id: Mapped[int | None] = mapped_column(ForeignKey("company_users.id", ondelete="SET NULL"))
    status: Mapped[str | None] = mapped_column(String(20), default="seated")


class PosTable(AuditMixin, ModelBase):
    __tablename__ = "pos_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_number: Mapped[str] = mapped_column(String(50), nullable=False)
    table_name: Mapped[str | None] = mapped_column(String(100))
    floor: Mapped[str | None] = mapped_column(String(50), default="main")
    capacity: Mapped[int | None] = mapped_column(Integer, default=4)
    status: Mapped[str | None] = mapped_column(String(20), default="available")
    shape: Mapped[str | None] = mapped_column(String(20), default="square")
    pos_x: Mapped[float | None] = mapped_column(Numeric(8, 2), default=0)
    pos_y: Mapped[float | None] = mapped_column(Numeric(8, 2), default=0)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"))
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)


class Receipt(AuditMixin, ModelBase):
    __tablename__ = "receipts"
    __table_args__ = (UniqueConstraint("receipt_number", name="receipts_receipt_number_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_number: Mapped[str | None] = mapped_column(String(50))
    receipt_type: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    receipt_date: Mapped[Date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    exchange_rate: Mapped[float | None] = mapped_column(Numeric(10, 6), default=1)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_accounts.id", ondelete="SET NULL"))
    reference: Mapped[str | None] = mapped_column(String(100))
    check_number: Mapped[str | None] = mapped_column(String(50))
    check_date: Mapped[Date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="pending")


__all__ = [
    "PendingReceivable",
    "PosKitchenOrder",
    "PosLoyaltyPoint",
    "PosLoyaltyProgram",
    "PosLoyaltyTransaction",
    "PosOrderLine",
    "PosOrderPayment",
    "PosOrder",
    "PosPayment",
    "PosPromotion",
    "PosReturnItem",
    "PosReturn",
    "PosSession",
    "PosTableOrder",
    "PosTable",
    "Receipt",
]
