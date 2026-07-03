"""Calculul centralizat al costurilor unei curse."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig
from app.models.trip import Trip
from app.models.trip_cost import TripCost
from app.models.vehicle import Vehicle


MONEY_STEP = Decimal("0.01")

DEFAULT_COST_CONFIG = {
    "fuel_price_per_liter": Decimal("7.45"),
    "driver_hourly_rate": Decimal("35.00"),
    "vehicle_daily_amortization": Decimal("160.00"),
    "vehicle_consumption_van": Decimal("9.20"),
    "vehicle_consumption_truck": Decimal("19.50"),
    "vehicle_consumption_car": Decimal("6.10"),
}


def _decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def get_cost_config_value(db: Session, company_id, key: str) -> Decimal:
    """Returneaza configuratia companiei sau valoarea implicita."""
    default = DEFAULT_COST_CONFIG[key]
    config = (
        db.query(SystemConfig)
        .filter(
            SystemConfig.company_id == company_id,
            SystemConfig.key == key,
        )
        .first()
    )
    if not config:
        return default

    try:
        value = Decimal(config.value)
        return value if value > 0 else default
    except (InvalidOperation, TypeError):
        return default


def get_vehicle_consumption(
    db: Session,
    company_id,
    vehicle: Vehicle,
) -> Decimal:
    consumption = _decimal(vehicle.avg_consumption)
    if consumption > 0:
        return consumption

    vehicle_type = (
        vehicle.type.value if hasattr(vehicle.type, "value") else str(vehicle.type)
    )
    key = f"vehicle_consumption_{vehicle_type.lower()}"
    return get_cost_config_value(db, company_id, key)


def calculate_cost_components(
    db: Session,
    company_id,
    vehicle: Vehicle,
    distance_km,
    duration_min,
) -> dict[str, Decimal]:
    """Calculeaza componentele de cost folosind configuratia companiei."""
    consumption = get_vehicle_consumption(db, company_id, vehicle)
    fuel_price = get_cost_config_value(db, company_id, "fuel_price_per_liter")
    driver_rate = get_cost_config_value(db, company_id, "driver_hourly_rate")
    amortization = _money(
        get_cost_config_value(db, company_id, "vehicle_daily_amortization")
    )

    fuel_cost = _money(
        _decimal(distance_km) / Decimal("100") * consumption * fuel_price
    )
    driver_cost = _money(
        _decimal(duration_min) / Decimal("60") * driver_rate
    )

    return {
        "fuel_cost": fuel_cost,
        "driver_cost": driver_cost,
        "amortization": amortization,
        "total_cost": _money(fuel_cost + driver_cost + amortization),
    }


def _get_vehicle(db: Session, trip: Trip) -> Vehicle | None:
    if not trip.vehicle_id:
        return None
    return db.query(Vehicle).filter(Vehicle.id == trip.vehicle_id).first()


def upsert_trip_cost(
    db: Session,
    trip: Trip,
    *,
    extra_cost=None,
    extra_reason: str | None = None,
) -> TripCost | None:
    """
    Creeaza sau actualizeaza costul planificat si, cand exista date reale,
    costul real. Nu inventeaza kilometri sau durate lipsa.
    """
    vehicle = _get_vehicle(db, trip)
    if not vehicle:
        return None

    planned = calculate_cost_components(
        db,
        trip.company_id,
        vehicle,
        trip.planned_km,
        trip.planned_duration_min,
    )

    cost = db.query(TripCost).filter(TripCost.trip_id == trip.id).first()
    if not cost:
        cost = TripCost(trip_id=trip.id)
        db.add(cost)

    if extra_cost is not None:
        cost.extra_cost = _money(_decimal(extra_cost))
        cost.extra_reason = extra_reason

    cost.fuel_cost_planned = planned["fuel_cost"]
    cost.driver_cost_planned = planned["driver_cost"]
    cost.amortization = planned["amortization"]
    cost.total_planned = planned["total_cost"]

    if trip.actual_km is not None and trip.actual_duration_min is not None:
        actual = calculate_cost_components(
            db,
            trip.company_id,
            vehicle,
            trip.actual_km,
            trip.actual_duration_min,
        )
        cost.fuel_cost_actual = actual["fuel_cost"]
        cost.driver_cost_actual = actual["driver_cost"]
        cost.total_actual = _money(
            actual["total_cost"] + _decimal(cost.extra_cost)
        )
    else:
        cost.fuel_cost_actual = None
        cost.driver_cost_actual = None
        cost.total_actual = None

    return cost
