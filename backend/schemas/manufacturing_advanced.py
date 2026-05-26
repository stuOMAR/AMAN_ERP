from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, date

# --- WORK CENTERS ---
class WorkCenterBase(BaseModel):
    name: str
    code: Optional[str] = None
    capacity_per_day: Optional[Decimal] = Field(default=Decimal("8.0"), ge=0)
    cost_per_hour: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    location: Optional[str] = None
    cost_center_id: Optional[int] = None
    default_expense_account_id: Optional[int] = None
    status: Optional[str] = 'active'

class WorkCenterCreate(WorkCenterBase):
    pass

class WorkCenterResponse(WorkCenterBase):
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# --- ROUTING ---
class OperationBase(BaseModel):
    sequence: int = Field(ge=1)
    name: Optional[str] = None
    work_center_id: Optional[int]
    description: Optional[str] = None
    setup_time: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    cycle_time: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    labor_rate_per_hour: Optional[Decimal] = Field(default=Decimal("0"), ge=0)

class RouteBase(BaseModel):
    name: str
    product_id: Optional[int] = None
    bom_id: Optional[int] = None
    is_default: bool = False
    is_active: bool = True
    description: Optional[str] = None

class RouteCreate(RouteBase):
    operations: List[OperationBase] = []

class OperationResponse(OperationBase):
    id: int
    work_center_name: Optional[str] = None # Calculated field
    
    model_config = ConfigDict(from_attributes=True)

class RouteResponse(RouteBase):
    id: int
    product_name: Optional[str] = None # Calculated field
    bom_id: Optional[int] = None
    is_default: bool = False
    operations: List[OperationResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# --- BILL OF MATERIALS (BOM) ---
class BOMComponentBase(BaseModel):
    component_product_id: int
    quantity: Decimal = Field(gt=0)            # إذا is_percentage=True يُعامَل كنسبة مئوية من كمية الأمر
    waste_percentage: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    cost_share_percentage: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    is_percentage: bool = False              # Variable BOM: كميات نسبية بدل كميات ثابتة
    notes: Optional[str] = None

class BOMBase(BaseModel):
    product_id: Optional[int]
    code: Optional[str] = None
    name: Optional[str] = None
    yield_quantity: Decimal = Field(default=Decimal("1.0"), gt=0)
    route_id: Optional[int] = None
    is_active: bool = True
    notes: Optional[str] = None

class BOMCreate(BOMBase):
    components: List[BOMComponentBase] = []
    outputs: List["BOMOutputCreate"] = []

class BOMComponentResponse(BOMComponentBase):
    id: int
    component_name: Optional[str] = None
    component_uom: Optional[str] = None
    computed_quantity: Optional[Decimal] = None  # populated by compute-materials endpoint
    
    model_config = ConfigDict(from_attributes=True)

class BOMResponse(BOMBase):
    id: int
    product_name: Optional[str] = None
    route_name: Optional[str] = None
    components: List[BOMComponentResponse] = []
    outputs: List["BOMOutputResponse"] = []
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# --- PRODUCTION ORDERS ---
class ProductionOrderOperationBase(BaseModel):
    operation_id: int
    work_center_id: Optional[int]
    status: Optional[str] = 'pending'
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    actual_setup_time: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    actual_run_time: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    completed_quantity: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    scrapped_quantity: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    notes: Optional[str] = None

class ProductionOrderBase(BaseModel):
    product_id: int
    bom_id: int
    route_id: Optional[int]
    quantity: Decimal = Field(gt=0)
    start_date: Optional[date]
    due_date: Optional[date]
    warehouse_id: Optional[int] # Source
    destination_warehouse_id: Optional[int] # Destination
    status: Optional[str] = 'draft'
    notes: Optional[str] = None

class ProductionOrderCreate(ProductionOrderBase):
    order_number: Optional[str] = None # Auto-generate if None

class ProductionOrderOperationResponse(ProductionOrderOperationBase):
    id: int
    operation_description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    worker_id: Optional[int] = None
    order_number: Optional[str] = None
    product_name: Optional[str] = None
    work_center_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ProductionOrderResponse(ProductionOrderBase):
    id: int
    order_number: str
    status: str
    produced_quantity: Decimal
    scrapped_quantity: Decimal
    product_name: Optional[str] = None
    bom_name: Optional[str] = None
    created_at: datetime
    operations: List[ProductionOrderOperationResponse] = []
    all_materials_sufficient: Optional[bool] = True
    total_material_cost: Optional[Decimal] = Decimal("0")
    total_labor_overhead_cost: Optional[Decimal] = Decimal("0")
    unit_production_cost: Optional[Decimal] = Decimal("0")
    total_output: Optional[Decimal] = Decimal("0")
    completion_percent: Optional[Decimal] = Decimal("0")
    completion_status: Optional[str] = "not_started"
    completion_direction: Optional[str] = "none"
    is_overdue: Optional[bool] = False
    materials: List[dict] = []
    transactions: List[dict] = []
    
    model_config = ConfigDict(from_attributes=True)

# --- MRP (Material Requirements Planning) ---
class MRPSubItem(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    required_quantity: Decimal = Field(ge=0)
    available_quantity: Decimal = Field(ge=0)
    on_hand_quantity: Decimal = Field(ge=0)
    on_order_quantity: Decimal = Field(ge=0)
    shortage_quantity: Decimal = Field(ge=0)
    lead_time_days: int
    suggested_action: str
    status: str

class MRPPlanResponse(BaseModel):
    id: int
    plan_name: str
    production_order_id: Optional[int]
    status: str
    calculated_at: datetime
    items: List[MRPSubItem] = []

    model_config = ConfigDict(from_attributes=True)

# --- BOM OUTPUTS (By-products) ---
class BOMOutputBase(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    cost_allocation_percentage: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    notes: Optional[str] = None

class BOMOutputCreate(BOMOutputBase):
    pass

class BOMOutputResponse(BOMOutputBase):
    id: int
    product_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- EQUIPMENT & MAINTENANCE ---
class EquipmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    work_center_id: Optional[int] = None
    status: Optional[str] = 'active'
    purchase_date: Optional[date] = None
    last_maintenance_date: Optional[date] = None
    next_maintenance_date: Optional[date] = None
    notes: Optional[str] = None

class EquipmentCreate(EquipmentBase):
    pass

class EquipmentResponse(EquipmentBase):
    id: int
    work_center_name: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class MaintenanceLogBase(BaseModel):
    equipment_id: int
    maintenance_type: str
    description: Optional[str] = None
    cost: Optional[Decimal] = Decimal("0")
    performed_by: Optional[int] = None
    external_service_provider: Optional[str] = None
    maintenance_date: date
    next_due_date: Optional[date] = None
    status: Optional[str] = 'completed'
    notes: Optional[str] = None

class MaintenanceLogCreate(MaintenanceLogBase):
    pass

class MaintenanceLogResponse(MaintenanceLogBase):
    id: int
    equipment_name: Optional[str] = None
    performed_by_name: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
