"""
AMAN ERP - Pydantic Schemas
"""

from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from decimal import Decimal


class CompanyCreateRequest(BaseModel):
    """طلب إنشاء شركة - company_id يُنشأ تلقائياً"""
    company_name: str = Field(..., min_length=3, max_length=255)
    company_name_en: Optional[str] = Field(None, max_length=255)
    commercial_registry: Optional[str] = Field(None, max_length=50)
    tax_number: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    email: EmailStr
    address: Optional[str] = None
    country: str = Field(default="SY", max_length=5, description="Country code: SA, SY, etc.")
    currency: str = Field(default="SYP", max_length=3)
    
    admin_username: str = Field(..., min_length=4, max_length=50)
    admin_email: EmailStr
    admin_full_name: str = Field(..., min_length=3, max_length=255)
    admin_password: str = Field(..., min_length=8)
    
    timezone: str = Field(default="Asia/Damascus", max_length=100)
    plan_type: str = Field(default="basic")
    template_id: Optional[int] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "company_name": "شركة الأمل للتجارة",
            "email": "info@alamal.com",
            "country": "SY",
            "currency": "SYP",
            "admin_username": "admin",
            "admin_email": "admin@alamal.com",
            "admin_full_name": "أحمد محمد",
            "admin_password": "SecurePass123!@#",
            "timezone": "Asia/Damascus"
        }
    })


class CompanyUpdateRequest(BaseModel):
    """Update company details"""
    company_name: Optional[str] = Field(None, min_length=3, max_length=255)
    company_name_en: Optional[str] = Field(None, max_length=255)
    commercial_registry: Optional[str] = Field(None, max_length=50)
    tax_number: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    currency: Optional[str] = Field(None, max_length=3)
    plan_type: Optional[str] = Field(None, max_length=50)


class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    company_id: Optional[str] = None
    user: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: bool = True
    company_id: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    decimal_places: int = 2
    timezone: str = "Asia/Damascus"
    permissions: List[str] = []
    allowed_branches: List[int] = []
    enabled_modules: List[str] = []
    industry_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)



class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=4, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=3)
    role: str = Field(default="user")


class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: str = Field(default="user")
    branches: Optional[List[int]] = []
    permissions: Optional[List[str]] = []


class PartyResponse(BaseModel):
    id: int
    name: str
    party_type: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    current_balance: Decimal = Decimal("0")
    is_customer: bool = False
    is_supplier: bool = False

    model_config = ConfigDict(from_attributes=True)


class AccountingEntryLine(BaseModel):
    account_id: int
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    amount_currency: Decimal = Decimal("0")
    currency: Optional[str] = None
    description: Optional[str] = None
    cost_center_id: Optional[int] = None


class JournalEntryRequest(BaseModel):
    entry_date: str
    description: str
    lines: List[AccountingEntryLine]
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    branch_id: Optional[int] = None


class CompanyResponse(BaseModel):
    id: Optional[int] = None
    company_id: str
    company_name: str
    company_name_en: Optional[str] = None
    commercial_registry: Optional[str] = None
    tax_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    currency: str = "SYP"
    logo_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class CompanyCreateResponse(BaseModel):
    message: str
    company_id: str
    company_name: str
    admin_username: str


class CompanyListItem(BaseModel):
    id: str
    company_name: str
    database_name: Optional[str] = None
    email: Optional[str] = None
    status: str = "active"
    plan_type: str = "basic"
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CompanyListResponse(BaseModel):
    companies: List[CompanyListItem]
    total: int


class CategoryCreate(BaseModel):
    name: str
    code: Optional[str] = None
    branch_id: Optional[int] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    branch_id: Optional[int] = None


class WarehouseCreate(BaseModel):
    name: str 
    code: Optional[str] = None
    location: Optional[str] = None
    branch_id: Optional[int] = None
    is_default: bool = False
    # F-31: optional per-warehouse inventory GL account. When NULL we keep
    # using the global acc_map_inventory mapping (backward compatible).
    gl_inventory_account_id: Optional[int] = None


class WarehouseResponse(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    location: Optional[str] = None
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    is_default: bool = False
    gl_inventory_account_id: Optional[int] = None
    gl_inventory_account_code: Optional[str] = None
    gl_inventory_account_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CurrencyCreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    symbol: Optional[str] = None
    is_base: bool = False
    current_rate: Decimal = Decimal("1.0")
    is_active: bool = True


class CurrencyResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    symbol: Optional[str] = None
    is_base: bool = False
    current_rate: Decimal = Decimal("1.0")
    is_active: bool = True


class ExchangeRateCreate(BaseModel):
    currency_id: int
    rate: Decimal
    rate_date: Optional[date] = None
    source: Optional[str] = "manual"


class ExchangeRateResponse(BaseModel):
    id: int
    currency_id: int
    rate: Decimal
    rate_date: Optional[date] = None
    source: Optional[str] = None
    created_by: Optional[int] = None


class BranchCreate(BaseModel):
    branch_name: str
    branch_name_en: Optional[str] = None
    branch_code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    default_currency: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True
    is_default: bool = False


class BranchResponse(BaseModel):
    id: int
    branch_name: str
    branch_name_en: Optional[str] = None
    branch_code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    default_currency: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_default: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
