"""Intercompany module Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ── Entity Group ──

class EntityGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = None
    branch_id: Optional[int] = None
    company_id: str = Field(..., min_length=1, max_length=100)
    group_currency: str = Field(default="SAR", max_length=10)


class EntityGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    parent_id: Optional[int] = None
    branch_id: Optional[int] = None
    group_currency: Optional[str] = Field(default=None, max_length=10)


class EntityGroupRead(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    branch_id: Optional[int] = None
    company_id: str
    group_currency: str
    consolidation_level: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EntityGroupTree(EntityGroupRead):
    children: List["EntityGroupTree"] = []


# ── Intercompany Transaction ──

class IntercompanyTransactionCreate(BaseModel):
    source_entity_id: int
    target_entity_id: int
    transaction_type: str = Field(default="sale", pattern="^(sale|purchase|service|loan|transfer)$")
    source_amount: Decimal = Field(..., ge=0, decimal_places=4)
    source_currency: str = Field(default="SAR", max_length=10)
    target_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=4)
    target_currency: Optional[str] = Field(default=None, max_length=10)
    # Tri-currency: the *money* moved (e.g., USD between SAR and EGP
    # branches). When omitted the transaction is treated as legacy
    # single-currency (transaction_currency = source_currency).
    transaction_currency: Optional[str] = Field(default=None, max_length=10)
    transaction_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=4)
    exchange_rate: Decimal = Field(default=Decimal("1"), gt=0, decimal_places=8)
    description: Optional[str] = Field(default=None, max_length=255)
    reference_document: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _fill_target(self):
        if self.target_amount is None:
            self.target_amount = (self.source_amount * self.exchange_rate).quantize(Decimal("0.0001"))
        if self.target_currency is None:
            self.target_currency = self.source_currency
        if self.transaction_currency is None:
            self.transaction_currency = self.source_currency
        if self.transaction_amount is None:
            self.transaction_amount = self.source_amount
        return self


class IntercompanyTransactionRead(BaseModel):
    id: int
    source_entity_id: int
    target_entity_id: int
    transaction_type: str
    source_amount: Decimal
    source_currency: str
    target_amount: Decimal
    target_currency: str
    transaction_currency: Optional[str] = None
    transaction_amount: Optional[Decimal] = None
    exchange_rate: Decimal
    source_journal_entry_id: Optional[int] = None
    target_journal_entry_id: Optional[int] = None
    elimination_status: str
    elimination_journal_entry_id: Optional[int] = None
    reference_document: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    source_entity_name: Optional[str] = None
    target_entity_name: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Consolidation ──

class ConsolidationRequest(BaseModel):
    entity_group_id: int
    as_of_date: Optional[str] = None  # YYYY-MM-DD


class EliminationLine(BaseModel):
    source_entity_name: str
    target_entity_name: str
    amount: Decimal
    currency: str
    transaction_id: int


class ConsolidationResult(BaseModel):
    entity_group_id: int
    entity_group_name: str
    eliminations: List[EliminationLine]
    total_eliminated: Decimal
    journal_entry_ids: List[int]
    status: str


# ── Account Mapping ──

class AccountMappingCreate(BaseModel):
    source_entity_id: int
    target_entity_id: int
    source_account_id: int
    target_account_id: int


class AccountMappingRead(BaseModel):
    id: int
    source_entity_id: int
    target_entity_id: int
    source_account_id: int
    target_account_id: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Balance Report ──

class IntercompanyBalanceItem(BaseModel):
    source_entity_id: int
    source_entity_name: str
    target_entity_id: int
    target_entity_name: str
    net_amount: Decimal
    currency: str
    pending_count: int


class IntercompanyBalanceReport(BaseModel):
    balances: List[IntercompanyBalanceItem]
    total_pending: Decimal
