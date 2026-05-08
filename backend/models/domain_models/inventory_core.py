from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ModelBase


class ProductCategory(ModelBase):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_name_en: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))


class ProductUnit(ModelBase):
    __tablename__ = "product_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    unit_name: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_name_en: Mapped[str | None] = mapped_column(String(100))
    abbreviation: Mapped[str | None] = mapped_column(String(10))
    base_unit_id: Mapped[int | None] = mapped_column(ForeignKey("product_units.id"))
    conversion_factor: Mapped[float | None] = mapped_column(Numeric(10, 6), default=1)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(ModelBase):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name_en: Mapped[str | None] = mapped_column(String(255))
    product_type: Mapped[str | None] = mapped_column(String(50), default="product")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("product_units.id"))
    barcode: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    short_description: Mapped[str | None] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    origin_country: Mapped[str | None] = mapped_column(String(100))
    weight: Mapped[float | None] = mapped_column(Numeric(10, 4))
    volume: Mapped[float | None] = mapped_column(Numeric(10, 4))
    dimensions: Mapped[str | None] = mapped_column(String(100))
    cost_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    last_purchase_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    selling_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    wholesale_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    min_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    max_price: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    sku: Mapped[str | None] = mapped_column(String(100), unique=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    is_taxable: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_track_inventory: Mapped[bool | None] = mapped_column(Boolean, default=True)
    reorder_level: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    reorder_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    has_batch_tracking: Mapped[bool | None] = mapped_column(Boolean, default=False)
    has_serial_tracking: Mapped[bool | None] = mapped_column(Boolean, default=False)
    has_expiry_tracking: Mapped[bool | None] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, default=0)
    expiry_alert_days: Mapped[int | None] = mapped_column(Integer, default=30)
    has_variants: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_kit: Mapped[bool | None] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("1"))


class Inventory(ModelBase):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    reserved_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    available_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    average_cost: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    policy_version: Mapped[int | None] = mapped_column(Integer, default=1)
    last_costing_update: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_movement_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryTransaction(ModelBase):
    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    reference_document: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    balance_before: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    balance_after: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    total_cost: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockAdjustment(ModelBase):
    __tablename__ = "stock_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    adjustment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    old_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    new_quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    difference: Mapped[float | None] = mapped_column(Numeric(18, 4), default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="pending")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("company_users.id"))


__all__ = [
    "Inventory",
    "InventoryTransaction",
    "Product",
    "ProductCategory",
    "ProductUnit",
    "StockAdjustment",
]
