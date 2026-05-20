"""Shop floor control Pydantic schemas."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class StartOperationRequest(BaseModel):
    work_order_id: int
    routing_operation_id: int
    operator_id: int
    supervisor_override: bool = False


class CompleteOperationRequest(BaseModel):
    log_id: int
    output_quantity: Decimal = Decimal("0")
    scrap_quantity: Decimal = Decimal("0")
    downtime_minutes: Decimal = Decimal("0")
    notes: Optional[str] = None


class PauseOperationRequest(BaseModel):
    log_id: int
    notes: Optional[str] = None


class ShopFloorLogRead(BaseModel):
    id: int
    work_order_id: int
    routing_operation_id: int
    operator_id: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_quantity: Decimal = Decimal("0")
    scrap_quantity: Decimal = Decimal("0")
    downtime_minutes: Decimal = Decimal("0")
    status: str
    notes: Optional[str] = None


class WorkOrderDashboardItem(BaseModel):
    work_order_id: int
    order_number: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Decimal
    produced_quantity: Decimal = Decimal("0")
    status: str
    due_date: Optional[str] = None
    current_operation: Optional[str] = None
    current_operation_status: Optional[str] = None
    progress_pct: Decimal = Decimal("0.0")
    is_delayed: bool = False


class OperationProgressRead(BaseModel):
    operation_id: int
    operation_name: Optional[str] = None
    sequence: int
    status: str
    operator_name: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_quantity: Decimal = Decimal("0")
    scrap_quantity: Decimal = Decimal("0")


class WorkOrderProgressRead(BaseModel):
    work_order_id: int
    order_number: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Decimal
    status: str
    operations: List[OperationProgressRead] = []
