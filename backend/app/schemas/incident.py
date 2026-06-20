import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class IncidentReportRequest(BaseModel):
    """Request pentru raportarea unui incident de către șofer."""
    trip_id: uuid.UUID
    type: Literal["MINOR", "MAJOR"]
    description: str
    location_city: str = Field(min_length=1, max_length=100)
    location_county: str = Field(min_length=1, max_length=100)
    location_street: str = Field(min_length=1, max_length=200)
    location_number: str = Field(min_length=1, max_length=30)


class IncidentReportResponse(BaseModel):
    """Response după raportarea unui incident."""
    message: str
    incident_id: uuid.UUID
    trip_id: uuid.UUID
    trip_status: str
    vehicle_id: uuid.UUID | None
    vehicle_status: str | None


class RouteStopResponse(BaseModel):
    """Stop din ruta optimizată de recovery."""
    sequence: int
    node_idx: int
    order_id: str
    order_ref: str | None
    stop_type: str
    eta_seconds: int
    is_virtual: bool


class RecoveryOptionResponse(BaseModel):
    """Opțiune de recovery cu valori reale calculate."""
    option_id: str
    type: str
    feasible: bool
    recommended: bool
    driver_id: str | None
    driver_name: str | None
    vehicle_id: str | None
    vehicle_plate: str | None
    planned_km: float
    planned_duration_min: float
    estimated_fuel_cost: float
    estimated_driver_cost: float
    estimated_total_cost: float
    late_orders_count: int
    warnings: list[str]
    route: list[RouteStopResponse]


class ImpactAnalysisResponse(BaseModel):
    """Analiza reală de impact cu optimizare ORS + OR-Tools."""
    incident_id: str
    original_trip_id: str
    original_vehicle_id: str | None
    broken_vehicle_plate: str | None
    recovery_start_source: str
    recovery_start_lat: float | None
    recovery_start_lon: float | None
    remaining_stops_count: int
    affected_orders_count: int
    total_kg: float
    total_m3: float
    options: list[RecoveryOptionResponse]
    warnings: list[str]


class RecoverIncidentRequest(BaseModel):
    option_id: str | None = None
    strategy: Literal[
        "RECOVER_ALL_REMAINING", "RECOVER_PICKED_UP_ONLY", "POSTPONE_REMAINING"
    ] | None = None
class RecoverIncidentResponse(BaseModel):
    """Response după crearea recovery trip-ului."""
    message: str
    incident_id: uuid.UUID
    original_trip_id: uuid.UUID
    recovery_trip_id: uuid.UUID | None
    planned_km: float
    planned_duration_min: float
    recovered_stops_count: int
    recovered_orders_count: int
    selected_strategy: str
    postponed_orders_count: int
    postponed_order_refs: list[str]
