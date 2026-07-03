from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.models.trip import Trip
from app.models.trip_cost import TripCost
from app.models.trip_stop import StopTypeEnum
from app.models.vehicle import Vehicle
from app.schemas.analytics import FleetUtilizationResponse
from app.services.analytics_service import (
    business_date_range_to_utc,
    get_costs,
    get_fleet_utilization,
    get_plan_vs_actual,
)


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.ordering = None

    def filter(self, *args):
        return self

    def join(self, *args):
        return self

    def order_by(self, *args):
        self.ordering = args
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, trips, operational_vehicles, trip_costs=None):
        self.trip_query = FakeQuery(trips)
        self.vehicle_query = FakeQuery(operational_vehicles)
        self.trip_cost_query = FakeQuery(trip_costs or [])

    def query(self, model):
        if model is Trip:
            return self.trip_query
        if model is Vehicle:
            return self.vehicle_query
        if model is TripCost:
            return self.trip_cost_query
        raise AssertionError(f"Unexpected query model: {model}")


def make_stop(order_id, sequence, stop_type, snapshot_kg, snapshot_m3):
    # Current order dimensions intentionally differ from the snapshots.
    order = SimpleNamespace(kg=9999, m3=9999)
    return SimpleNamespace(
        order_id=order_id,
        order=order,
        sequence=sequence,
        stop_type=stop_type,
        order_kg_snapshot=snapshot_kg,
        order_m3_snapshot=snapshot_m3,
    )


def make_trip(trip_id, vehicle, kg, m3, capacity_kg, capacity_m3):
    stops = [
        make_stop(f"order-{trip_id}", 1, StopTypeEnum.PICKUP, kg, m3),
        make_stop(f"order-{trip_id}", 2, StopTypeEnum.DELIVERY, kg, m3),
    ]
    return SimpleNamespace(
        id=trip_id,
        planned_date=date(2026, 7, 1),
        vehicle_id=vehicle.id,
        vehicle=vehicle,
        vehicle_plate_snapshot=f"SNAP-{trip_id}",
        vehicle_capacity_kg_snapshot=capacity_kg,
        vehicle_capacity_m3_snapshot=capacity_m3,
        stops=stops,
    )


def test_fleet_utilization_uses_snapshots_and_all_trips_for_averages():
    used_vehicle = SimpleNamespace(id="used", plate="CURRENT", capacity_kg=1, capacity_m3=1)
    unused_operational_vehicle = SimpleNamespace(id="unused")
    efficient_trip = make_trip("efficient", used_vehicle, 800, 4, 1000, 10)
    overloaded_trip = make_trip("overloaded", used_vehicle, 1200, 5, 1000, 10)
    db = FakeSession([efficient_trip, overloaded_trip], [unused_operational_vehicle])

    result = get_fleet_utilization(
        db,
        company_id="company",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert db.trip_query.ordering is not None
    assert result["trips"][0]["vehicle_plate"] == "SNAP-efficient"
    assert result["trips"][0]["orders_count"] == 1
    assert result["trips"][0]["stops_count"] == 2
    assert result["trips"][0]["total_kg"] == 800
    assert result["trips"][0]["load_kg_percent"] == 80

    summary = result["summary"]
    assert summary["used_vehicles"] == 1
    assert summary["unused_vehicles"] == 1
    assert summary["total_trips"] == 2
    assert summary["capacity_compliant_trips"] == 1
    assert summary["overloaded_trips"] == 1
    assert summary["efficient_trips"] == 1
    assert summary["normal_trips"] == 0
    assert summary["average_load_kg_percent"] == 100
    assert summary["average_load_m3_percent"] == 45

    # The response contract must retain every utilization bucket.
    validated = FleetUtilizationResponse.model_validate(result)
    assert validated.summary.normal_trips == 0


def test_plan_vs_actual_group_delay_and_stop_count_use_measured_stops():
    order = SimpleNamespace(
        delivery_city="Bucharest",
        pickup_city="Bucharest",
        pickup_service_minutes=5,
        delivery_service_minutes=5,
    )
    planned = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)
    measured_stop = SimpleNamespace(
        order=order,
        stop_type=StopTypeEnum.PICKUP,
        eta_planned=planned,
        arrival_time=planned.replace(minute=2),
        departure_time=planned.replace(minute=7),
    )
    unmeasured_stop = SimpleNamespace(
        order=order,
        stop_type=StopTypeEnum.DELIVERY,
        eta_planned=None,
        arrival_time=None,
        departure_time=None,
    )
    trip = SimpleNamespace(
        planned_km=100,
        actual_km=105,
        planned_duration_min=60,
        actual_duration_min=65,
        driver_id=None,
        vehicle_id=None,
        stops=[measured_stop, unmeasured_stop],
        status="COMPLETED",
    )
    db = FakeSession([trip], [])

    result = get_plan_vs_actual(
        db,
        company_id="company",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
    )

    driver = result["by_driver"][0]
    assert result["average_delay_minutes"] == 2
    assert driver["average_delay_minutes"] == 2
    assert driver["stops_count"] == 1
    assert driver["on_time_rate"] == 100


def test_business_date_range_uses_bucharest_boundaries():
    start, end = business_date_range_to_utc(date(2026, 7, 1), date(2026, 7, 31))

    assert start == datetime(2026, 6, 30, 21, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 31, 21, tzinfo=timezone.utc)


def test_costs_use_actual_km_rank_by_total_and_include_extra_cost():
    def make_cost_trip(trip_id, actual_km, order_count):
        stops = []
        for index in range(order_count):
            order = SimpleNamespace(kg=100, m3=1, delivery_city="Bucharest", pickup_city=None)
            stops.append(SimpleNamespace(order_id=f"{trip_id}-{index}", order=order))
        return SimpleNamespace(
            id=trip_id,
            actual_km=actual_km,
            planned_km=actual_km - 10,
            driver_id=None,
            vehicle_id=None,
            stops=stops,
        )

    higher_total_trip = make_cost_trip("higher-total", 120, 10)
    higher_unit_trip = make_cost_trip("higher-unit", 70, 1)
    costs = [
        SimpleNamespace(
            trip_id="higher-total",
            total_planned=900,
            total_actual=1000,
            extra_cost=50,
            fuel_cost_planned=300,
            driver_cost_planned=400,
            fuel_cost_actual=350,
            driver_cost_actual=440,
            amortization=160,
        ),
        SimpleNamespace(
            trip_id="higher-unit",
            total_planned=450,
            total_actual=500,
            extra_cost=0,
            fuel_cost_planned=150,
            driver_cost_planned=140,
            fuel_cost_actual=170,
            driver_cost_actual=170,
            amortization=160,
        ),
    ]
    db = FakeSession([higher_total_trip, higher_unit_trip], [], costs)

    result = get_costs(
        db,
        company_id="company",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )

    assert result["total_extra_cost"] == 50
    assert result["top_expensive_trips"][0]["trip_id"] == "higher-total"
    assert result["top_expensive_trips"][0]["actual_km"] == 120
    assert "planned_km" not in result["top_expensive_trips"][0]
