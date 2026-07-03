"""
Pydantic schemas pentru analytics endpoints.
"""
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional


# ============== Zone Demand ==============
class ZoneDemandItem(BaseModel):
    zone: str
    orders_count: int
    pending_orders: int
    planned_orders: int
    delivered_orders: int
    failed_orders: int
    problematic_orders: int
    total_kg: float
    total_m3: float
    average_kg: float
    average_m3: float
    urgent_orders: int
    critical_orders: int
    adr_orders: int
    fragil_orders: int
    perisabil_orders: int
    strict_time_window_orders: int
    unplanned_orders: int
    zone_demand_score: int
    demand_level: str  # LOW, MEDIUM, HIGH
    recommendation: str


class ZoneDemandResponse(BaseModel):
    zones: list[ZoneDemandItem]


# ============== Driver Zone Fit ==============
class DriverZoneFitItem(BaseModel):
    driver_id: str
    driver_name: str
    total_stops_in_zone: int
    completed_stops_in_zone: int
    failed_stops_in_zone: int
    skipped_stops_in_zone: int
    on_time_rate: float
    average_delay_minutes: float
    average_service_minutes: float
    minor_incidents: int
    major_incidents: int
    adr_experience_count: int
    fragil_experience_count: int
    perisabil_experience_count: int
    critical_orders_handled: int
    driver_zone_fit_score: int
    recommendation_reason: list[str]


class DriverZoneFitResponse(BaseModel):
    zone: str
    recommended_drivers: list[DriverZoneFitItem]


# ============== Vehicle Trip Fit ==============
class VehicleTripFitItem(BaseModel):
    vehicle_id: str
    plate: str
    status: str
    capacity_kg: float
    capacity_m3: float
    required_kg: float
    required_m3: float
    load_kg_percent: float
    load_m3_percent: float
    capacity_fit: bool
    recent_incidents: int
    major_incidents: int
    estimated_cost: Optional[float]
    vehicle_trip_fit_score: int
    recommendation_reason: list[str]


class VehicleTripFitResponse(BaseModel):
    recommended_vehicles: list[VehicleTripFitItem]


# ============== Fleet Utilization ==============
class FleetUtilizationTripItem(BaseModel):
    trip_id: str
    planned_date: str
    vehicle_id: str
    vehicle_plate: str
    orders_count: int
    stops_count: int
    total_kg: float
    total_m3: float
    vehicle_capacity_kg: float
    vehicle_capacity_m3: float
    load_kg_percent: float
    load_m3_percent: float
    utilization_level: str
    recommendation: str


class FleetUtilizationSummary(BaseModel):
    used_vehicles: int
    unused_vehicles: int
    total_trips: int
    capacity_compliant_trips: int
    overloaded_trips: int
    average_load_kg_percent: float
    average_load_m3_percent: float
    underutilized_trips: int
    near_capacity_trips: int
    efficient_trips: int


class FleetUtilizationResponse(BaseModel):
    trips: list[FleetUtilizationTripItem]
    summary: FleetUtilizationSummary


# ============== Planning Quality ==============
class PlanningQualityResponse(BaseModel):
    planning_session_id: str
    eligible_orders: int
    planned_orders: int
    unplanned_orders: int
    planned_orders_rate: float
    total_trips: int
    total_stops: int
    average_stops_per_trip: float
    total_planned_km: float
    total_planned_duration_min: int
    warnings_count: int
    critical_warnings_count: int
    manual_adjustments_count: int
    unassigned_trips_count: int
    planning_quality_score: int
    quality_level: str  # EXCELLENT, GOOD, MEDIUM, LOW
    recommendation: str


# ============== Unplanned Orders ==============
class UnplannedByZoneItem(BaseModel):
    zone: str
    orders: int
    kg: float
    m3: float


class UnplannedOrdersResponse(BaseModel):
    total_unplanned_orders: int
    total_unplanned_kg: float
    total_unplanned_m3: float
    critical_unplanned_orders: int
    urgent_unplanned_orders: int
    by_reason: dict[str, int]
    by_zone: list[UnplannedByZoneItem]
    recommendations: list[str]


# ============== Plan vs Actual ==============
class PlanVsActualGroupItem(BaseModel):
    name: str
    on_time_rate: float
    average_delay_minutes: float
    average_service_minutes: float
    stops_count: int


class PlanVsActualResponse(BaseModel):
    planned_vs_actual_km_difference: float
    planned_vs_actual_duration_difference: float
    average_delay_minutes: float
    max_delay_minutes: float
    on_time_stops: int
    late_stops: int
    on_time_rate: float
    average_real_service_time: float
    average_service_time_deviation: float
    trips_finished_on_time: int
    trips_delayed: int
    by_driver: list[PlanVsActualGroupItem]
    by_vehicle: list[PlanVsActualGroupItem]
    by_zone: list[PlanVsActualGroupItem]


# ============== Service Time Accuracy ==============
class ServiceTimeAccuracyItem(BaseModel):
    category: str
    planned_service_minutes_avg: float
    real_service_minutes_avg: float
    deviation_minutes: float
    deviation_percent: float
    samples_count: int
    recommendation: str


class ServiceTimeAccuracyResponse(BaseModel):
    by_cargo_type: list[ServiceTimeAccuracyItem]
    by_zone: list[ServiceTimeAccuracyItem]
    by_stop_type: list[ServiceTimeAccuracyItem]


# ============== Costs ==============
class CostGroupItem(BaseModel):
    name: str
    orders_count: int
    trips_count: int
    total_cost: float
    cost_per_order: float
    cost_per_km: Optional[float]


class ExpensiveTripItem(BaseModel):
    trip_id: str
    planned_km: float
    orders_count: int
    total_cost: float
    cost_per_order: float
    recommendation: str


class CostAnalyticsResponse(BaseModel):
    total_planned_cost: float
    total_actual_cost: float
    total_extra_cost: float
    fuel_cost_planned: float
    fuel_cost_actual: float
    driver_cost_planned: float
    driver_cost_actual: float
    amortization_cost: float
    cost_per_trip: float
    cost_per_order: float
    total_actual_km: float
    cost_per_km: Optional[float]
    cost_per_kg: Optional[float]
    cost_per_m3: Optional[float]
    planned_vs_actual_variance: float
    planned_vs_actual_variance_percent: float
    by_driver: list[CostGroupItem]
    by_vehicle: list[CostGroupItem]
    by_zone: list[CostGroupItem]
    top_expensive_trips: list[ExpensiveTripItem]


# ============== Incident Impact ==============
class IncidentImpactItem(BaseModel):
    incident_id: str
    original_trip_id: str
    type: str
    created_at: str
    resolved_at: Optional[str]
    recovery_trip_id: Optional[str]
    affected_orders_count: int
    affected_stops_count: int
    affected_kg: float
    affected_m3: float
    extra_recovery_km: float
    extra_recovery_duration_min: int
    extra_recovery_cost: float
    estimated_delay_minutes: int
    incident_impact_score: int
    impact_level: str  # LOW, MEDIUM, HIGH
    recommendation: str


class IncidentImpactResponse(BaseModel):
    total_incidents: int
    minor_incidents: int
    major_incidents: int
    interrupted_trips: int
    recovery_trips_created: int
    incident_rate: float
    major_incident_rate: float
    average_recovery_time_minutes: Optional[float]
    major_incidents_detail: list[IncidentImpactItem]
