"""
Service de analytics pentru business insights și planning intelligence.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.order import Order, OrderStatusEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_stop import TripStop, StopStatusEnum, StopTypeEnum
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.models.driver import Driver, DriverStatusEnum
from app.models.planning_session import PlanningSession
from app.models.incident import Incident, IncidentTypeEnum
from app.models.trip_cost import TripCost
from app.models.system_config import SystemConfig


# Praguri și configurări
DEFAULT_DELAY_THRESHOLD_MINUTES = 30
DEFAULT_COST_PER_KM = 4.5


# ============== Helper Functions ==============

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Împărțire sigură evitând diviziunea la zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def clamp_score(value: float, min_val: int = 0, max_val: int = 100) -> int:
    """Limitează o valoare între min și max, apoi o convertește la int."""
    clamped = max(min_val, min(max_val, value))
    return int(round(clamped))


def enum_value(value) -> str:
    """Extrage valoarea stringului din enum."""
    return value.value if hasattr(value, "value") else str(value)


def money_to_float(value) -> float:
    """Convertește Decimal sau None la float."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def get_zone_from_order(order: Order) -> str:
    """Extrage zona din comandă (delivery_city > pickup_city > UNKNOWN)."""
    if order.delivery_city:
        return order.delivery_city
    if order.pickup_city:
        return order.pickup_city
    return "UNKNOWN"


def minutes_between(start: datetime, end: datetime) -> int:
    """Calculează minutele între două datetime-uri."""
    if not start or not end:
        return 0
    delta = end - start
    return int(delta.total_seconds() // 60)


def calculate_on_time(arrival_time: datetime, eta_planned: datetime, threshold_minutes: int = 30) -> bool:
    """Verifică dacă stopul s-a finalizat la timp."""
    if not arrival_time or not eta_planned:
        return False
    delay = minutes_between(eta_planned, arrival_time)
    return delay <= threshold_minutes


def get_config_value(db: Session, company_id, key: str, default: float) -> float:
    """Citește valoare din SystemConfig."""
    try:
        config = db.query(SystemConfig).filter(
            SystemConfig.company_id == company_id,
            SystemConfig.key == key,
        ).first()
        if not config:
            return default
        return float(config.value)
    except (TypeError, ValueError):
        return default


def parse_date_range(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    """Parsează interval de date, default ultimele 30 de zile."""
    today = datetime.now(timezone.utc).date()
    if not end_date:
        end_date = today
    if not start_date:
        start_date = end_date - timedelta(days=29)
    return start_date, end_date


# ============== Zone Demand ==============

def get_zone_demand(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Calculează cererea per zonă."""
    start_date, end_date = parse_date_range(start_date, end_date)

    orders = db.query(Order).filter(
        Order.company_id == company_id,
        or_(
            and_(
                Order.assigned_delivery_date.isnot(None),
                Order.assigned_delivery_date >= start_date,
                Order.assigned_delivery_date <= end_date,
            ),
            and_(
                Order.assigned_delivery_date.is_(None),
                Order.delivery_deadline >= start_date,
                Order.delivery_deadline <= end_date,
            ),
        ),
    ).all()

    zones_data = defaultdict(lambda: {
        "orders": [],
        "stats": {
            "orders_count": 0,
            "pending_orders": 0,
            "planned_orders": 0,
            "delivered_orders": 0,
            "failed_orders": 0,
            "problematic_orders": 0,
            "total_kg": 0.0,
            "total_m3": 0.0,
            "urgent_orders": 0,
            "critical_orders": 0,
            "adr_orders": 0,
            "fragil_orders": 0,
            "perisabil_orders": 0,
            "strict_time_window_orders": 0,
            "unplanned_orders": 0,
        }
    })

    for order in orders:
        zone = get_zone_from_order(order)
        zones_data[zone]["orders"].append(order)
        stats = zones_data[zone]["stats"]

        stats["orders_count"] += 1

        if order.status == OrderStatusEnum.PENDING:
            stats["pending_orders"] += 1
        elif order.status == OrderStatusEnum.PLANNED:
            stats["planned_orders"] += 1
        elif order.status == OrderStatusEnum.DELIVERED:
            stats["delivered_orders"] += 1
        elif order.status == OrderStatusEnum.FAILED:
            stats["failed_orders"] += 1

        if order.is_problematic:
            stats["problematic_orders"] += 1

        stats["total_kg"] += money_to_float(order.kg)
        stats["total_m3"] += money_to_float(order.m3)

        if order.priority and "URGENT" in enum_value(order.priority).upper():
            stats["urgent_orders"] += 1
        if order.priority and "CRITIC" in enum_value(order.priority).upper():
            stats["critical_orders"] += 1

        if order.type_marfa:
            marfa_type = enum_value(order.type_marfa).upper()
            if "ADR" in marfa_type:
                stats["adr_orders"] += 1
            if "FRAGIL" in marfa_type:
                stats["fragil_orders"] += 1
            if "PERISABIL" in marfa_type:
                stats["perisabil_orders"] += 1

        has_pickup_window = order.pickup_time_window_start and order.pickup_time_window_end
        has_delivery_window = order.delivery_time_window_start and order.delivery_time_window_end
        if has_pickup_window or has_delivery_window:
            stats["strict_time_window_orders"] += 1

        if order.status == OrderStatusEnum.PENDING and not order.assigned_delivery_date:
            stats["unplanned_orders"] += 1

    # Calculează scoruri
    zones_list = []
    all_scores = []

    for zone, data in zones_data.items():
        stats = data["stats"]
        avg_kg = safe_divide(stats["total_kg"], stats["orders_count"])
        avg_m3 = safe_divide(stats["total_m3"], stats["orders_count"])

        raw_score = (
            stats["orders_count"] * 2
            + stats["total_kg"] / 100
            + stats["total_m3"] * 2
            + stats["urgent_orders"] * 3
            + stats["critical_orders"] * 5
            + stats["strict_time_window_orders"] * 2
            + stats["problematic_orders"]
        )
        all_scores.append(raw_score)

        zones_list.append({
            "zone": zone,
            "orders_count": stats["orders_count"],
            "pending_orders": stats["pending_orders"],
            "planned_orders": stats["planned_orders"],
            "delivered_orders": stats["delivered_orders"],
            "failed_orders": stats["failed_orders"],
            "problematic_orders": stats["problematic_orders"],
            "total_kg": round(stats["total_kg"], 2),
            "total_m3": round(stats["total_m3"], 2),
            "average_kg": round(avg_kg, 2),
            "average_m3": round(avg_m3, 2),
            "urgent_orders": stats["urgent_orders"],
            "critical_orders": stats["critical_orders"],
            "adr_orders": stats["adr_orders"],
            "fragil_orders": stats["fragil_orders"],
            "perisabil_orders": stats["perisabil_orders"],
            "strict_time_window_orders": stats["strict_time_window_orders"],
            "unplanned_orders": stats["unplanned_orders"],
            "raw_score": raw_score,
        })

    # Normalizează scorurile
    max_score = max(all_scores) if all_scores else 1
    for zone_data in zones_list:
        normalized = safe_divide(zone_data["raw_score"] * 100, max_score)
        zone_data["zone_demand_score"] = clamp_score(normalized)

        score = zone_data["zone_demand_score"]
        if score >= 70:
            zone_data["demand_level"] = "HIGH"
        elif score >= 40:
            zone_data["demand_level"] = "MEDIUM"
        else:
            zone_data["demand_level"] = "LOW"

        # Recomandări
        if zone_data["critical_orders"] > 0:
            zone_data["recommendation"] = "Cerere ridicată. Recomandat minimum 2 vehicule și șofer cu experiență în zonă."
        elif zone_data["total_m3"] > 50:
            zone_data["recommendation"] = "Volum m³ ridicat. Verifică disponibilitatea vehiculelor cu capacitate mare."
        elif zone_data["demand_level"] == "HIGH":
            zone_data["recommendation"] = "Cerere ridicată. Prioritizează zona în planificare."
        else:
            zone_data["recommendation"] = "Cerere normală. Planificare standard recomandată."

        del zone_data["raw_score"]

    # Sortează descrescător după scor
    zones_list.sort(key=lambda x: x["zone_demand_score"], reverse=True)

    return {"zones": zones_list}


# ============== Driver Zone Fit ==============

def get_driver_zone_fit(db: Session, company_id, zone: str, start_date: date | None, end_date: date | None) -> dict:
    """Recomandă șoferi pentru o zonă pe baza istoricului."""
    start_date, end_date = parse_date_range(start_date, end_date)
    zone_lower = zone.lower()

    trips = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        Trip.status == TripStatusEnum.COMPLETED,
    ).all()

    drivers = db.query(Driver).filter(Driver.company_id == company_id).all()

    # Inițializează driver_stats pentru toți șoferii din companie
    driver_stats = {}
    for driver in drivers:
        driver_stats[driver.id] = {
            "driver": driver,
            "total_stops_in_zone": 0,
            "completed_stops_in_zone": 0,
            "failed_stops_in_zone": 0,
            "skipped_stops_in_zone": 0,
            "on_time_count": 0,
            "late_count": 0,
            "delays": [],
            "service_times": [],
            "incidents": defaultdict(int),
            "adr_experience": 0,
            "fragil_experience": 0,
            "perisabil_experience": 0,
            "critical_orders": 0,
        }

    # Filtrează incidente după company, date range și driver
    incidents = db.query(Incident).join(
        Trip, Incident.trip_id == Trip.id
    ).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        Incident.driver_id.in_([d.id for d in drivers]),
    ).all()

    for incident in incidents:
        driver_id = incident.driver_id
        if driver_id in driver_stats:
            incident_type = enum_value(incident.type).upper()
            if "MAJOR" in incident_type:
                driver_stats[driver_id]["incidents"]["major"] += 1
            else:
                driver_stats[driver_id]["incidents"]["minor"] += 1

    for trip in trips:
        for stop in trip.stops:
            if not stop.order:
                continue

            if trip.driver_id not in driver_stats:
                continue

            stop_zone = get_zone_from_order(stop.order)
            # Case-insensitive zone matching
            if stop_zone.lower() != zone_lower:
                continue

            driver_stats[trip.driver_id]["total_stops_in_zone"] += 1

            if stop.status == StopStatusEnum.COMPLETED:
                driver_stats[trip.driver_id]["completed_stops_in_zone"] += 1

                if stop.eta_planned and stop.arrival_time:
                    if calculate_on_time(stop.arrival_time, stop.eta_planned):
                        driver_stats[trip.driver_id]["on_time_count"] += 1
                    else:
                        driver_stats[trip.driver_id]["late_count"] += 1
                        delay = minutes_between(stop.eta_planned, stop.arrival_time)
                        driver_stats[trip.driver_id]["delays"].append(delay)

                if stop.arrival_time and stop.departure_time:
                    service_time = minutes_between(stop.arrival_time, stop.departure_time)
                    driver_stats[trip.driver_id]["service_times"].append(service_time)

            elif stop.status == StopStatusEnum.FAILED:
                driver_stats[trip.driver_id]["failed_stops_in_zone"] += 1
            elif stop.status == StopStatusEnum.SKIPPED:
                driver_stats[trip.driver_id]["skipped_stops_in_zone"] += 1

            if stop.order.type_marfa:
                marfa_type = enum_value(stop.order.type_marfa).upper()
                if "ADR" in marfa_type:
                    driver_stats[trip.driver_id]["adr_experience"] += 1
                if "FRAGIL" in marfa_type:
                    driver_stats[trip.driver_id]["fragil_experience"] += 1
                if "PERISABIL" in marfa_type:
                    driver_stats[trip.driver_id]["perisabil_experience"] += 1

            if stop.order.priority and "CRITIC" in enum_value(stop.order.priority).upper():
                driver_stats[trip.driver_id]["critical_orders"] += 1

    # Calculează scoruri
    recommended_drivers = []

    for driver_id, stats in driver_stats.items():
        if stats["driver"] is None:
            continue

        driver = stats["driver"]

        # Dacă nu are istoric în zonă dar este AVAILABLE, includ cu scor mic
        if stats["total_stops_in_zone"] == 0:
            if driver.status == DriverStatusEnum.AVAILABLE:
                # Fallback: șofer disponibil fără istoric
                recommended_drivers.append({
                    "driver_id": str(driver_id),
                    "driver_name": driver.user.full_name if driver.user else f"Driver {str(driver_id)[:8]}",
                    "total_stops_in_zone": 0,
                    "completed_stops_in_zone": 0,
                    "failed_stops_in_zone": 0,
                    "skipped_stops_in_zone": 0,
                    "on_time_rate": 0.0,
                    "average_delay_minutes": 0.0,
                    "average_service_minutes": 0.0,
                    "minor_incidents": 0,
                    "major_incidents": 0,
                    "adr_experience_count": 0,
                    "fragil_experience_count": 0,
                    "perisabil_experience_count": 0,
                    "critical_orders_handled": 0,
                    "driver_zone_fit_score": 30,
                    "recommendation_reason": ["Nu există istoric în zonă, dar șoferul este disponibil."],
                })
            continue

        on_time_rate = safe_divide(
            stats["on_time_count"],
            stats["on_time_count"] + stats["late_count"],
            default=0.0
        ) * 100

        avg_delay = safe_divide(sum(stats["delays"]), len(stats["delays"])) if stats["delays"] else 0.0
        avg_service_time = safe_divide(sum(stats["service_times"]), len(stats["service_times"])) if stats["service_times"] else 0.0

        experience_score = min(stats["total_stops_in_zone"] / 20 * 100, 100)
        on_time_score = on_time_rate

        if avg_service_time <= 30:
            service_efficiency_score = 100.0
        else:
            service_efficiency_score = max(0, 100 - (avg_service_time - 30) * 2)

        cargo_experience = stats["adr_experience"] + stats["fragil_experience"] + stats["perisabil_experience"] + stats["critical_orders"]
        cargo_experience_score = min(cargo_experience / 10 * 100, 100)

        incident_score = 100 - stats["incidents"]["minor"] * 10 - stats["incidents"]["major"] * 30
        incident_score = max(0, incident_score)

        fit_score = (
            experience_score * 0.30
            + on_time_score * 0.25
            + service_efficiency_score * 0.15
            + cargo_experience_score * 0.15
            + incident_score * 0.15
        )
        fit_score = clamp_score(fit_score)

        driver_name = driver.user.full_name if driver.user else f"Driver {str(driver_id)[:8]}"

        reasons = []
        if stats["total_stops_in_zone"] >= 20:
            reasons.append("Experiență ridicată în zonă")
        if on_time_rate >= 90:
            reasons.append("Rată mare de livrare la timp")
        if stats["incidents"]["major"] == 0:
            reasons.append("Fără incidente majore")
        if cargo_experience > 5:
            reasons.append("Experiență cu mărfuri speciale")

        if not reasons:
            reasons.append("Profil acceptabil pentru zonă")

        recommended_drivers.append({
            "driver_id": str(driver_id),
            "driver_name": driver_name,
            "total_stops_in_zone": stats["total_stops_in_zone"],
            "completed_stops_in_zone": stats["completed_stops_in_zone"],
            "failed_stops_in_zone": stats["failed_stops_in_zone"],
            "skipped_stops_in_zone": stats["skipped_stops_in_zone"],
            "on_time_rate": round(on_time_rate, 1),
            "average_delay_minutes": round(avg_delay, 1),
            "average_service_minutes": round(avg_service_time, 1),
            "minor_incidents": stats["incidents"]["minor"],
            "major_incidents": stats["incidents"]["major"],
            "adr_experience_count": stats["adr_experience"],
            "fragil_experience_count": stats["fragil_experience"],
            "perisabil_experience_count": stats["perisabil_experience"],
            "critical_orders_handled": stats["critical_orders"],
            "driver_zone_fit_score": fit_score,
            "recommendation_reason": reasons,
        })

    # Sortează și limitează la top 10
    recommended_drivers.sort(key=lambda x: x["driver_zone_fit_score"], reverse=True)
    recommended_drivers = recommended_drivers[:10]

    return {
        "zone": zone,
        "recommended_drivers": recommended_drivers,
    }


# ============== Vehicle Trip Fit ==============

def get_vehicle_trip_fit(db: Session, company_id, trip_id: str | None, order_ids: list[str] | None) -> dict:
    """Recomandă vehicule pentru o cursă sau set de comenzi."""
    required_kg = 0.0
    required_m3 = 0.0
    planned_km = 0.0

    if trip_id:
        # Security: verifică company_id
        trip = db.query(Trip).filter(
            Trip.id == trip_id,
            Trip.company_id == company_id,
        ).first()
        if not trip:
            return {"error": "Trip not found"}

        planned_km = money_to_float(trip.planned_km)
        # Evită dublare: folosește comenzi unice
        unique_orders = {}
        for stop in trip.stops:
            if stop.order_id and stop.order_id not in unique_orders:
                unique_orders[stop.order_id] = stop.order

        for order in unique_orders.values():
            required_kg += money_to_float(order.kg)
            required_m3 += money_to_float(order.m3)
    elif order_ids:
        # Security: verifică company_id
        orders = db.query(Order).filter(
            Order.id.in_(order_ids),
            Order.company_id == company_id,
        ).all()

        if not orders:
            return {"error": "No valid orders found"}

        for order in orders:
            required_kg += money_to_float(order.kg)
            required_m3 += money_to_float(order.m3)
    else:
        return {"recommended_vehicles": []}

    vehicles = db.query(Vehicle).filter(Vehicle.company_id == company_id).all()
    cost_per_km = get_config_value(db, company_id, "cost_per_km", DEFAULT_COST_PER_KM)

    recent_incidents = db.query(Incident).filter(
        Incident.vehicle_id.in_([v.id for v in vehicles]),
        Incident.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
    ).all()

    incident_counts = defaultdict(lambda: {"minor": 0, "major": 0})
    for incident in recent_incidents:
        incident_type = enum_value(incident.type).upper()
        if "MAJOR" in incident_type:
            incident_counts[incident.vehicle_id]["major"] += 1
        else:
            incident_counts[incident.vehicle_id]["minor"] += 1

    vehicle_recommendations = []

    for vehicle in vehicles:
        cap_kg = money_to_float(vehicle.capacity_kg)
        cap_m3 = money_to_float(vehicle.capacity_m3)

        load_kg_percent = safe_divide(required_kg, cap_kg, default=0.0) * 100 if cap_kg > 0 else 0.0
        load_m3_percent = safe_divide(required_m3, cap_m3, default=0.0) * 100 if cap_m3 > 0 else 0.0

        capacity_fit = required_kg <= cap_kg and required_m3 <= cap_m3

        estimated_cost = None
        if planned_km > 0:
            estimated_cost = round(planned_km * cost_per_km, 2)

        incidents = incident_counts.get(vehicle.id, {"minor": 0, "major": 0})

        # Calculează scor
        if capacity_fit:
            capacity_fit_score = 100.0
        else:
            capacity_fit_score = 0.0

        avg_load = (load_kg_percent + load_m3_percent) / 2
        if 60 <= avg_load <= 90:
            utilization_score = 100.0
        elif avg_load < 40 or avg_load > 95:
            utilization_score = max(0, 100 - abs(avg_load - 70))
        else:
            utilization_score = 80.0

        vehicle_consumption = money_to_float(vehicle.avg_consumption)
        if vehicle_consumption > 0:
            max_consumption = max([money_to_float(v.avg_consumption) for v in vehicles], default=vehicle_consumption)
            cost_score = max(0, 100 - safe_divide(vehicle_consumption, max_consumption, default=1.0) * 50)
        else:
            cost_score = 50.0

        reliability_score = 100 - incidents["minor"] * 10 - incidents["major"] * 30
        reliability_score = max(0, reliability_score)

        # Status score: penalizează vehiculele nu sunt disponibile
        if enum_value(vehicle.status) == "DISPONIBIL":
            status_score = 100.0
        elif enum_value(vehicle.status) in ("SERVICE", "REZERVAT"):
            status_score = 30.0
        else:  # AVARIAT și altele
            status_score = 0.0

        fit_score = (
            capacity_fit_score * 0.35
            + utilization_score * 0.25
            + cost_score * 0.15
            + reliability_score * 0.15
            + status_score * 0.10
        )
        fit_score = clamp_score(fit_score)

        reasons = []
        if capacity_fit:
            reasons.append("Capacitate suficientă")
        else:
            reasons.append(f"Capacitate insuficientă (kg: {load_kg_percent:.0f}%, m³: {load_m3_percent:.0f}%)")

        if 60 <= avg_load <= 90:
            reasons.append("Utilizare optimă")
        elif avg_load < 40:
            reasons.append("Vehicul subutilizat")
        elif avg_load > 95:
            reasons.append("Vehicul aproape de limită")

        if incidents["major"] == 0 and incidents["minor"] == 0:
            reasons.append("Fără incidente recente")

        vehicle_recommendations.append({
            "vehicle_id": str(vehicle.id),
            "plate": vehicle.plate or "UNKNOWN",
            "status": enum_value(vehicle.status),
            "capacity_kg": round(cap_kg, 2),
            "capacity_m3": round(cap_m3, 2),
            "required_kg": round(required_kg, 2),
            "required_m3": round(required_m3, 2),
            "load_kg_percent": round(load_kg_percent, 1),
            "load_m3_percent": round(load_m3_percent, 1),
            "capacity_fit": capacity_fit,
            "recent_incidents": incidents["minor"] + incidents["major"],
            "major_incidents": incidents["major"],
            "estimated_cost": estimated_cost,
            "vehicle_trip_fit_score": fit_score,
            "recommendation_reason": reasons,
        })

    # Sortează descrescător după scor
    vehicle_recommendations.sort(key=lambda x: x["vehicle_trip_fit_score"], reverse=True)

    return {"recommended_vehicles": vehicle_recommendations}


# ============== Fleet Utilization ==============

def get_fleet_utilization(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Analizează utilizarea flotei."""
    start_date, end_date = parse_date_range(start_date, end_date)

    # Include și trip-uri PROPOSED/APPROVED, nu doar COMPLETED/IN_PROGRESS
    trips = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        Trip.status.in_([
            TripStatusEnum.PROPOSED,
            TripStatusEnum.APPROVED,
            TripStatusEnum.IN_PROGRESS,
            TripStatusEnum.COMPLETED,
        ]),
    ).all()

    trips_list = []
    stats = {
        "used_vehicles": set(),
        "all_vehicles": set(),
        "underutilized": 0,
        "near_capacity": 0,
        "efficient": 0,
        "total_kg_percent": 0.0,
        "total_m3_percent": 0.0,
        "trip_count": 0,
    }

    vehicles = db.query(Vehicle).filter(Vehicle.company_id == company_id).all()
    for vehicle in vehicles:
        stats["all_vehicles"].add(vehicle.id)

    for trip in trips:
        if not trip.vehicle:
            continue

        stats["used_vehicles"].add(trip.vehicle_id)

        # Evită dublare: comenzi unice
        unique_orders = {}
        for stop in trip.stops:
            if stop.order_id and stop.order_id not in unique_orders:
                unique_orders[stop.order_id] = stop.order

        total_kg = 0.0
        total_m3 = 0.0
        orders_count = len(unique_orders)
        stops_count = len(trip.stops)

        for order in unique_orders.values():
            total_kg += money_to_float(order.kg)
            total_m3 += money_to_float(order.m3)

        cap_kg = money_to_float(trip.vehicle.capacity_kg)
        cap_m3 = money_to_float(trip.vehicle.capacity_m3)

        load_kg_percent = safe_divide(total_kg, cap_kg, default=0.0) * 100 if cap_kg > 0 else 0.0
        load_m3_percent = safe_divide(total_m3, cap_m3, default=0.0) * 100 if cap_m3 > 0 else 0.0

        stats["total_kg_percent"] += load_kg_percent
        stats["total_m3_percent"] += load_m3_percent
        stats["trip_count"] += 1

        # Determinează nivelul
        if load_kg_percent < 40 and load_m3_percent < 40:
            utilization_level = "UNDERUTILIZED"
            stats["underutilized"] += 1
            recommendation = "Cursa este subutilizată. Ia în considerare consolidarea cu altă cursă sau folosirea unui vehicul mai mic."
        elif load_kg_percent > 90 or load_m3_percent > 90:
            utilization_level = "NEAR_CAPACITY"
            stats["near_capacity"] += 1
            recommendation = "Cursa este aproape de capacitate. Verifică riscul de supraîncărcare sau împarte comenzile."
        elif (
            60 <= max(load_kg_percent, load_m3_percent) <= 90
            and min(load_kg_percent, load_m3_percent) >= 20
        ):
            utilization_level = "EFFICIENT"
            stats["efficient"] += 1
            recommendation = "Cursa are un grad bun de utilizare."
        else:
            utilization_level = "NORMAL"
            recommendation = "Utilizare normală."

        trips_list.append({
            "trip_id": str(trip.id),
            "planned_date": str(trip.planned_date),
            "vehicle_id": str(trip.vehicle_id) if trip.vehicle_id else None,
            "vehicle_plate": trip.vehicle.plate if trip.vehicle else None,
            "orders_count": orders_count,
            "stops_count": stops_count,
            "total_kg": round(total_kg, 2),
            "total_m3": round(total_m3, 2),
            "vehicle_capacity_kg": round(cap_kg, 2),
            "vehicle_capacity_m3": round(cap_m3, 2),
            "load_kg_percent": round(load_kg_percent, 1),
            "load_m3_percent": round(load_m3_percent, 1),
            "utilization_level": utilization_level,
            "recommendation": recommendation,
        })

    # Calculează summary
    unused_vehicles = len(stats["all_vehicles"] - stats["used_vehicles"])
    avg_kg_percent = safe_divide(stats["total_kg_percent"], stats["trip_count"])
    avg_m3_percent = safe_divide(stats["total_m3_percent"], stats["trip_count"])

    return {
        "trips": trips_list,
        "summary": {
            "used_vehicles": len(stats["used_vehicles"]),
            "unused_vehicles": unused_vehicles,
            "average_load_kg_percent": round(avg_kg_percent, 1),
            "average_load_m3_percent": round(avg_m3_percent, 1),
            "underutilized_trips": stats["underutilized"],
            "near_capacity_trips": stats["near_capacity"],
            "efficient_trips": stats["efficient"],
        }
    }


# ============== Planning Quality ==============

def get_planning_quality(db: Session, company_id, planning_session_id: str) -> dict:
    """Evaluează calitatea unei sesiuni de planificare."""
    session = db.query(PlanningSession).filter(
        PlanningSession.id == planning_session_id,
        PlanningSession.company_id == company_id,
    ).first()

    if not session:
        return {
            "planning_session_id": planning_session_id,
            "error": "Planning session not found",
        }

    eligible_orders = session.total_orders if session.total_orders else 0

    trips = db.query(Trip).filter(
        Trip.planning_session_id == planning_session_id,
        Trip.company_id == company_id,
    ).all()

    # Comenzi unice planificate
    planned_order_ids = set()
    total_stops = 0
    unassigned_trips = 0

    for trip in trips:
        total_stops += len(trip.stops)
        if trip.driver_id is None or trip.vehicle_id is None:
            unassigned_trips += 1

        for stop in trip.stops:
            if stop.order_id:
                planned_order_ids.add(stop.order_id)

    planned_orders = len(planned_order_ids)
    unplanned_orders = max(eligible_orders - planned_orders, 0)
    planned_orders_rate = safe_divide(planned_orders, eligible_orders, default=0.0) * 100 if eligible_orders > 0 else 0.0

    avg_stops_per_trip = safe_divide(total_stops, len(trips)) if trips else 0.0

    total_planned_km = 0.0
    total_planned_duration = 0
    warnings_count = 0
    critical_warnings_count = 0

    for trip in trips:
        total_planned_km += money_to_float(trip.planned_km)
        total_planned_duration += trip.planned_duration_min if trip.planned_duration_min else 0

    if session.optimization_stats:
        stats_dict = session.optimization_stats if isinstance(session.optimization_stats, dict) else {}
        warnings_count = stats_dict.get("warnings_count", 0)
        critical_warnings_count = stats_dict.get("critical_warnings_count", 0)

    # Estimare manual_adjustments_count ca 0 pentru acum (fără AuditLog)
    manual_adjustments_count = 0

    base_score = planned_orders_rate
    penalty = (
        unplanned_orders * 3
        + warnings_count * 2
        + critical_warnings_count * 5
        + manual_adjustments_count
        + unassigned_trips * 5
    )
    planning_quality_score = clamp_score(base_score - penalty)

    if planning_quality_score >= 90:
        quality_level = "EXCELLENT"
    elif planning_quality_score >= 75:
        quality_level = "GOOD"
    elif planning_quality_score >= 50:
        quality_level = "MEDIUM"
    else:
        quality_level = "LOW"

    recommendation_parts = []
    if unassigned_trips > 0:
        recommendation_parts.append(f"Există {unassigned_trips} curse fără șofer/vehicul.")
    if unplanned_orders > 0:
        recommendation_parts.append(f"{unplanned_orders} comenzi au rămas neplanificate.")
    if warnings_count > 0:
        recommendation_parts.append(f"Sesiunea are {warnings_count} avertismente.")

    if quality_level == "EXCELLENT":
        recommendation = "Sesiune de planificare excelentă. Gata pentru execuție."
    elif quality_level == "GOOD":
        recommendation = "Planificare de bună calitate. " + " ".join(recommendation_parts) if recommendation_parts else ""
    elif quality_level == "MEDIUM":
        recommendation = "Planificare acceptabilă, dar cu probleme. " + " ".join(recommendation_parts)
    else:
        recommendation = "Calitate scăzută. " + " ".join(recommendation_parts)

    return {
        "planning_session_id": planning_session_id,
        "eligible_orders": eligible_orders,
        "planned_orders": planned_orders,
        "unplanned_orders": unplanned_orders,
        "planned_orders_rate": round(planned_orders_rate, 1),
        "total_trips": len(trips),
        "total_stops": total_stops,
        "average_stops_per_trip": round(avg_stops_per_trip, 1),
        "total_planned_km": round(total_planned_km, 2),
        "total_planned_duration_min": total_planned_duration,
        "warnings_count": warnings_count,
        "critical_warnings_count": critical_warnings_count,
        "manual_adjustments_count": manual_adjustments_count,
        "unassigned_trips_count": unassigned_trips,
        "planning_quality_score": planning_quality_score,
        "quality_level": quality_level,
        "recommendation": recommendation.strip(),
    }


# ============== Unplanned Orders ==============

def get_unplanned_orders(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Analizează comenzile neplanificate."""
    start_date, end_date = parse_date_range(start_date, end_date)

    orders = db.query(Order).filter(
        Order.company_id == company_id,
        Order.delivery_deadline >= start_date,
        Order.delivery_deadline <= end_date,
        or_(
            Order.status == OrderStatusEnum.PENDING,
            Order.assigned_delivery_date.is_(None),
        ),
    ).all()

    unplanned = [o for o in orders if o.status == OrderStatusEnum.PENDING or o.assigned_delivery_date is None]

    by_reason = defaultdict(int)
    by_zone = defaultdict(lambda: {"kg": 0.0, "m3": 0.0, "orders": 0})

    total_kg = 0.0
    total_m3 = 0.0
    critical_count = 0
    urgent_count = 0

    vehicles = db.query(Vehicle).filter(Vehicle.company_id == company_id).all()
    max_capacity_kg = max([money_to_float(v.capacity_kg) for v in vehicles], default=1000)
    max_capacity_m3 = max([money_to_float(v.capacity_m3) for v in vehicles], default=100)

    available_vehicles_count = sum(1 for v in vehicles if v.status == VehicleStatusEnum.DISPONIBIL)
    available_drivers_count = db.query(Driver).filter(
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).count()

    for order in unplanned:
        reason = "unknown"

        if not order.pickup_lat or not order.pickup_lon or not order.delivery_lat or not order.delivery_lon:
            reason = "missing_coordinates"
        elif order.is_problematic:
            reason = "problematic_order"
        elif order.pickup_time_window_start and order.pickup_time_window_end and order.delivery_time_window_start and order.delivery_time_window_end:
            reason = "strict_time_window"
        elif money_to_float(order.kg) > max_capacity_kg:
            reason = "capacity_kg"
        elif money_to_float(order.m3) > max_capacity_m3:
            reason = "capacity_m3"
        elif available_vehicles_count == 0:
            reason = "no_available_vehicle"
        elif available_drivers_count == 0:
            reason = "no_available_driver"

        by_reason[reason] += 1

        zone = get_zone_from_order(order)
        by_zone[zone]["orders"] += 1
        by_zone[zone]["kg"] += money_to_float(order.kg)
        by_zone[zone]["m3"] += money_to_float(order.m3)

        total_kg += money_to_float(order.kg)
        total_m3 += money_to_float(order.m3)

        if order.priority:
            priority_str = enum_value(order.priority).upper()
            if "CRITIC" in priority_str:
                critical_count += 1
            elif "URGENT" in priority_str:
                urgent_count += 1

    # Recomandări
    recommendations = []
    if by_reason.get("capacity_m3", 0) + by_reason.get("capacity_kg", 0) > 0:
        recommendations.append("Adaugă un vehicul cu volum mai mare pentru zonele cu multe comenzi neplanificate.")
    if by_reason.get("missing_coordinates", 0) > 0:
        recommendations.append("Verifică adresele comenzilor fără coordonate.")
    if critical_count > 0:
        recommendations.append("Revizuiește comenzile CRITIC neplanificate.")
    if by_reason.get("strict_time_window", 0) > 0:
        recommendations.append("Unele comenzi au time windows stricte. Planifică-le prioritar.")
    if not recommendations:
        recommendations.append("Analizează cauzele rămase ale neplanificării.")

    by_zone_list = [
        {
            "zone": zone,
            "orders": data["orders"],
            "kg": round(data["kg"], 2),
            "m3": round(data["m3"], 2),
        }
        for zone, data in sorted(by_zone.items(), key=lambda x: x[1]["orders"], reverse=True)
    ]

    return {
        "total_unplanned_orders": len(unplanned),
        "total_unplanned_kg": round(total_kg, 2),
        "total_unplanned_m3": round(total_m3, 2),
        "critical_unplanned_orders": critical_count,
        "urgent_unplanned_orders": urgent_count,
        "by_reason": dict(by_reason),
        "by_zone": by_zone_list,
        "recommendations": recommendations,
    }


# ============== Plan vs Actual ==============

def get_plan_vs_actual(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Compară planificarea cu execuția reală."""
    start_date, end_date = parse_date_range(start_date, end_date)

    trips = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        Trip.status.in_([TripStatusEnum.COMPLETED, TripStatusEnum.IN_PROGRESS]),
    ).all()

    total_planned_km = 0.0
    total_actual_km = 0.0
    total_planned_duration = 0
    total_actual_duration = 0
    delays = []
    on_time_count = 0
    late_count = 0
    on_time_trips = 0
    late_trips = 0
    service_times = []
    service_deviations = []

    by_driver = defaultdict(lambda: {
        "on_time": 0,
        "late": 0,
        "delays": [],
        "service_times": [],
        "stops": 0,
    })
    by_vehicle = defaultdict(lambda: {
        "on_time": 0,
        "late": 0,
        "delays": [],
        "service_times": [],
        "stops": 0,
    })
    by_zone = defaultdict(lambda: {
        "on_time": 0,
        "late": 0,
        "delays": [],
        "service_times": [],
        "stops": 0,
    })

    for trip in trips:
        total_planned_km += money_to_float(trip.planned_km)
        total_actual_km += money_to_float(trip.actual_km)
        total_planned_duration += trip.planned_duration_min if trip.planned_duration_min else 0
        total_actual_duration += trip.actual_duration_min if trip.actual_duration_min else 0

        trip_has_measured_stop = False
        trip_has_late_stop = False
        for stop in trip.stops:
            if not stop.order:
                continue

            by_zone[get_zone_from_order(stop.order)]["stops"] += 1

            # Exclude None driver/vehicle - folosește "Unassigned"
            driver_key = str(trip.driver_id) if trip.driver_id else "Unassigned"
            vehicle_key = str(trip.vehicle_id) if trip.vehicle_id else "Unassigned"

            by_driver[driver_key]["stops"] += 1
            by_vehicle[vehicle_key]["stops"] += 1

            if stop.eta_planned and stop.arrival_time:
                trip_has_measured_stop = True
                # Calculează lateness (nu delay care poate fi negativ)
                lateness = max(0, minutes_between(stop.eta_planned, stop.arrival_time))

                if calculate_on_time(stop.arrival_time, stop.eta_planned, DEFAULT_DELAY_THRESHOLD_MINUTES):
                    on_time_count += 1
                    by_zone[get_zone_from_order(stop.order)]["on_time"] += 1
                    by_driver[driver_key]["on_time"] += 1
                    by_vehicle[vehicle_key]["on_time"] += 1
                else:
                    late_count += 1
                    trip_has_late_stop = True
                    delays.append(lateness)
                    by_zone[get_zone_from_order(stop.order)]["late"] += 1
                    by_zone[get_zone_from_order(stop.order)]["delays"].append(lateness)
                    by_driver[driver_key]["late"] += 1
                    by_driver[driver_key]["delays"].append(lateness)
                    by_vehicle[vehicle_key]["late"] += 1
                    by_vehicle[vehicle_key]["delays"].append(lateness)

            if stop.arrival_time and stop.departure_time:
                actual_service_time = minutes_between(stop.arrival_time, stop.departure_time)
                service_times.append(actual_service_time)
                by_zone[get_zone_from_order(stop.order)]["service_times"].append(actual_service_time)
                by_driver[driver_key]["service_times"].append(actual_service_time)
                by_vehicle[vehicle_key]["service_times"].append(actual_service_time)

                # Calculează planned service minutes din stop type și order
                planned_service_minutes = 10 if stop.stop_type == StopTypeEnum.PICKUP else 5
                if stop.stop_type == StopTypeEnum.PICKUP and stop.order.pickup_service_minutes:
                    planned_service_minutes = stop.order.pickup_service_minutes
                elif stop.stop_type == StopTypeEnum.DELIVERY and stop.order.delivery_service_minutes:
                    planned_service_minutes = stop.order.delivery_service_minutes

                deviation = abs(actual_service_time - planned_service_minutes)
                service_deviations.append(deviation)

        if trip.status == TripStatusEnum.COMPLETED and trip_has_measured_stop:
            if trip_has_late_stop:
                late_trips += 1
            else:
                on_time_trips += 1

    km_difference = total_actual_km - total_planned_km
    duration_difference = total_actual_duration - total_planned_duration
    avg_delay = safe_divide(sum(delays), len(delays)) if delays else 0.0
    max_delay = max(delays) if delays else 0
    on_time_rate = safe_divide(on_time_count, on_time_count + late_count, default=0.0) * 100
    avg_service_time = safe_divide(sum(service_times), len(service_times)) if service_times else 0.0

    service_time_deviation = 0.0
    if service_deviations:
        service_time_deviation = safe_divide(sum(service_deviations), len(service_deviations))

    # Construiește grupurile
    by_driver_list = []
    for driver_key, data in by_driver.items():
        if data["stops"] > 0:
            driver_on_time_rate = safe_divide(data["on_time"], data["on_time"] + data["late"], default=0.0) * 100
            driver_avg_delay = safe_divide(sum(data["delays"]), len(data["delays"])) if data["delays"] else 0.0
            driver_avg_service = safe_divide(sum(data["service_times"]), len(data["service_times"])) if data["service_times"] else 0.0

            # Tratează "Unassigned"
            if driver_key == "Unassigned":
                driver_name = "Unassigned"
            else:
                driver = db.query(Driver).filter(Driver.id == driver_key).first()
                driver_name = driver.user.full_name if driver and driver.user else f"Driver {driver_key[:8]}"

            by_driver_list.append({
                "name": driver_name,
                "on_time_rate": round(driver_on_time_rate, 1),
                "average_delay_minutes": round(driver_avg_delay, 1),
                "average_service_minutes": round(driver_avg_service, 1),
                "stops_count": data["stops"],
            })

    by_vehicle_list = []
    for vehicle_key, data in by_vehicle.items():
        if data["stops"] > 0:
            vehicle_on_time_rate = safe_divide(data["on_time"], data["on_time"] + data["late"], default=0.0) * 100
            vehicle_avg_delay = safe_divide(sum(data["delays"]), len(data["delays"])) if data["delays"] else 0.0
            vehicle_avg_service = safe_divide(sum(data["service_times"]), len(data["service_times"])) if data["service_times"] else 0.0

            # Tratează "Unassigned"
            if vehicle_key == "Unassigned":
                vehicle_name = "Unassigned"
            else:
                vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_key).first()
                vehicle_name = vehicle.plate if vehicle else f"Vehicle {vehicle_key[:8]}"

            by_vehicle_list.append({
                "name": vehicle_name,
                "on_time_rate": round(vehicle_on_time_rate, 1),
                "average_delay_minutes": round(vehicle_avg_delay, 1),
                "average_service_minutes": round(vehicle_avg_service, 1),
                "stops_count": data["stops"],
            })

    by_zone_list = []
    for zone, data in by_zone.items():
        if data["stops"] > 0:
            zone_on_time_rate = safe_divide(data["on_time"], data["on_time"] + data["late"], default=0.0) * 100
            zone_avg_delay = safe_divide(sum(data["delays"]), len(data["delays"])) if data["delays"] else 0.0
            zone_avg_service = safe_divide(sum(data["service_times"]), len(data["service_times"])) if data["service_times"] else 0.0

            by_zone_list.append({
                "name": zone,
                "on_time_rate": round(zone_on_time_rate, 1),
                "average_delay_minutes": round(zone_avg_delay, 1),
                "average_service_minutes": round(zone_avg_service, 1),
                "stops_count": data["stops"],
            })

    return {
        "planned_vs_actual_km_difference": round(km_difference, 2),
        "planned_vs_actual_duration_difference": duration_difference,
        "average_delay_minutes": round(avg_delay, 1),
        "max_delay_minutes": max_delay,
        "on_time_stops": on_time_count,
        "late_stops": late_count,
        "on_time_rate": round(on_time_rate, 1),
        "average_real_service_time": round(avg_service_time, 1),
        "average_service_time_deviation": round(service_time_deviation, 1),
        "trips_finished_on_time": on_time_trips,
        "trips_delayed": late_trips,
        "by_driver": by_driver_list,
        "by_vehicle": by_vehicle_list,
        "by_zone": by_zone_list,
    }


# ============== Service Time Accuracy ==============

def get_service_time_accuracy(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Analizează acuratețea service time-ului și sugerează ajustări."""
    start_date, end_date = parse_date_range(start_date, end_date)

    stops = db.query(TripStop).join(
        Trip, TripStop.trip_id == Trip.id
    ).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        TripStop.status == StopStatusEnum.COMPLETED,
        TripStop.arrival_time.isnot(None),
        TripStop.departure_time.isnot(None),
    ).all()

    by_cargo_type = defaultdict(lambda: {"planned": [], "real": [], "deviation": []})
    by_zone = defaultdict(lambda: {"planned": [], "real": [], "deviation": []})
    by_stop_type = defaultdict(lambda: {"planned": [], "real": [], "deviation": []})

    for stop in stops:
        if not stop.order:
            continue

        # Determină planned service time pe baza tipului de stop
        if stop.stop_type == StopTypeEnum.PICKUP:
            planned_service = money_to_float(stop.order.pickup_service_minutes)
            if planned_service <= 0:
                planned_service = 10  # fallback
        else:  # DELIVERY
            planned_service = money_to_float(stop.order.delivery_service_minutes)
            if planned_service <= 0:
                planned_service = 5  # fallback

        real_service = minutes_between(stop.arrival_time, stop.departure_time)
        deviation = real_service - planned_service

        # Cargo type
        cargo_type = "GENERAL"
        if stop.order.type_marfa:
            cargo_type = enum_value(stop.order.type_marfa).upper()
        by_cargo_type[cargo_type]["planned"].append(planned_service)
        by_cargo_type[cargo_type]["real"].append(real_service)
        by_cargo_type[cargo_type]["deviation"].append(deviation)

        # Zone
        zone = get_zone_from_order(stop.order)
        by_zone[zone]["planned"].append(planned_service)
        by_zone[zone]["real"].append(real_service)
        by_zone[zone]["deviation"].append(deviation)

        # Stop type
        stop_type_str = enum_value(stop.stop_type)
        by_stop_type[stop_type_str]["planned"].append(planned_service)
        by_stop_type[stop_type_str]["real"].append(real_service)
        by_stop_type[stop_type_str]["deviation"].append(deviation)

    def build_accuracy_list(data_dict):
        result = []
        for category, data in data_dict.items():
            if len(data["planned"]) == 0:
                continue

            avg_planned = safe_divide(sum(data["planned"]), len(data["planned"]))
            avg_real = safe_divide(sum(data["real"]), len(data["real"]))
            avg_deviation = avg_real - avg_planned
            deviation_percent = safe_divide(avg_deviation, avg_planned, default=0.0) * 100 if avg_planned > 0 else 0.0

            if avg_real > avg_planned + 10:
                recommendation = "Service time subestimat. Recomandat să crești parametrul pentru această categorie."
            elif avg_real < avg_planned - 10:
                recommendation = "Service time supraestimat. Poți reduce parametrul pentru planificări mai compacte."
            else:
                recommendation = "Service time realist."

            result.append({
                "category": category,
                "planned_service_minutes_avg": round(avg_planned, 1),
                "real_service_minutes_avg": round(avg_real, 1),
                "deviation_minutes": round(avg_deviation, 1),
                "deviation_percent": round(deviation_percent, 1),
                "samples_count": len(data["planned"]),
                "recommendation": recommendation,
            })

        return result

    return {
        "by_cargo_type": build_accuracy_list(by_cargo_type),
        "by_zone": build_accuracy_list(by_zone),
        "by_stop_type": build_accuracy_list(by_stop_type),
    }


# ============== Costs ==============

def get_costs(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Analizează costurile operaționale."""
    start_date, end_date = parse_date_range(start_date, end_date)

    trips = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
    ).all()

    trip_costs = db.query(TripCost).join(
        Trip, TripCost.trip_id == Trip.id
    ).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
    ).all()
    trip_by_id = {trip.id: trip for trip in trips}
    cost_trip_ids = {cost.trip_id for cost in trip_costs}

    total_planned_cost = 0.0
    total_actual_cost = 0.0
    total_extra_cost = 0.0
    fuel_cost_planned = 0.0
    fuel_cost_actual = 0.0
    driver_cost_planned = 0.0
    driver_cost_actual = 0.0
    amortization_cost = 0.0

    for cost in trip_costs:
        total_planned_cost += money_to_float(cost.total_planned)
        total_actual_cost += money_to_float(cost.total_actual)
        total_extra_cost += money_to_float(cost.extra_cost)
        fuel_cost_planned += money_to_float(cost.fuel_cost_planned)
        fuel_cost_actual += money_to_float(cost.fuel_cost_actual)
        driver_cost_planned += money_to_float(cost.driver_cost_planned)
        driver_cost_actual += money_to_float(cost.driver_cost_actual)
        amortization_cost += money_to_float(cost.amortization)

    # Total comenzi unice
    total_order_ids = set()
    total_km = sum(money_to_float(trip_by_id[trip_id].planned_km) for trip_id in cost_trip_ids if trip_id in trip_by_id)
    total_kg = 0.0
    total_m3 = 0.0

    for trip_id in cost_trip_ids:
        trip = trip_by_id.get(trip_id)
        if not trip:
            continue

        unique_orders = {}
        for stop in trip.stops:
            if stop.order_id and stop.order_id not in unique_orders:
                unique_orders[stop.order_id] = stop.order

        for order_id in unique_orders:
            total_order_ids.add(order_id)

        for order in unique_orders.values():
            total_kg += money_to_float(order.kg)
            total_m3 += money_to_float(order.m3)

    total_orders = len(total_order_ids)
    cost_per_trip = safe_divide(total_actual_cost, len(trip_costs))
    cost_per_order = safe_divide(total_actual_cost, total_orders) if total_orders > 0 else 0.0
    cost_per_km = safe_divide(total_actual_cost, total_km) if total_km > 0 else None
    cost_per_kg = safe_divide(total_actual_cost, total_kg) if total_kg > 0 else None
    cost_per_m3 = safe_divide(total_actual_cost, total_m3) if total_m3 > 0 else None

    variance = total_actual_cost - total_planned_cost
    variance_percent = safe_divide(variance, total_planned_cost, default=0.0) * 100 if total_planned_cost > 0 else 0.0

    # Grupări
    by_driver = defaultdict(lambda: {"orders": 0, "trips": 0, "cost": 0.0})
    by_vehicle = defaultdict(lambda: {"orders": 0, "trips": 0, "cost": 0.0})
    by_zone = defaultdict(lambda: {"orders": 0, "trips": 0, "cost": 0.0})

    for cost in trip_costs:
        trip = trip_by_id.get(cost.trip_id)
        if not trip:
            continue

        actual_cost = money_to_float(cost.total_actual)

        # Comenzi unice pe trip
        unique_orders_for_trip = {}
        for stop in trip.stops:
            if stop.order_id and stop.order_id not in unique_orders_for_trip:
                unique_orders_for_trip[stop.order_id] = stop.order

        trip_orders_count = len(unique_orders_for_trip)
        cost_per_order_in_trip = safe_divide(actual_cost, trip_orders_count) if trip_orders_count > 0 else actual_cost

        if trip.driver_id:
            by_driver[str(trip.driver_id)]["trips"] += 1
            by_driver[str(trip.driver_id)]["orders"] += trip_orders_count
            by_driver[str(trip.driver_id)]["cost"] += actual_cost

        if trip.vehicle_id:
            by_vehicle[str(trip.vehicle_id)]["trips"] += 1
            by_vehicle[str(trip.vehicle_id)]["orders"] += trip_orders_count
            by_vehicle[str(trip.vehicle_id)]["cost"] += actual_cost

        # Aloc cost proporțional pe zone
        for order_id, order in unique_orders_for_trip.items():
            zone = get_zone_from_order(order)
            by_zone[zone]["trips"] += safe_divide(1.0, trip_orders_count) if trip_orders_count > 0 else 0.0
            by_zone[zone]["orders"] += 1
            by_zone[zone]["cost"] += cost_per_order_in_trip

    def build_group_list(data_dict, id_type="id"):
        result = []
        for key, data in data_dict.items():
            if data["trips"] == 0:
                continue

            cost_per_order_group = safe_divide(data["cost"], data["orders"])
            cost_per_km_group = None

            # Determină numele pe baza tipului
            if id_type == "driver":
                driver = db.query(Driver).filter(Driver.id == key).first()
                name = driver.user.full_name if driver and driver.user else f"Driver {key[:8]}"
            elif id_type == "vehicle":
                vehicle = db.query(Vehicle).filter(Vehicle.id == key).first()
                name = vehicle.plate if vehicle else f"Vehicle {key[:8]}"
                if vehicle:
                    trip_km = sum(
                        money_to_float(t.planned_km) for t in trips
                        if t.id in cost_trip_ids and t.vehicle_id == vehicle.id
                    )
                    if trip_km > 0:
                        cost_per_km_group = safe_divide(data["cost"], trip_km)
            else:
                name = key

            result.append({
                "name": name,
                "orders_count": int(data["orders"]),
                "trips_count": int(data["trips"]),
                "total_cost": round(data["cost"], 2),
                "cost_per_order": round(cost_per_order_group, 2),
                "cost_per_km": round(cost_per_km_group, 2) if cost_per_km_group else None,
            })

        return sorted(result, key=lambda x: x["total_cost"], reverse=True)

    by_driver_list = build_group_list(by_driver, "driver")
    by_vehicle_list = build_group_list(by_vehicle, "vehicle")
    by_zone_list = build_group_list(by_zone, "zone")

    # Top expensive trips
    expensive_trips = []
    for cost in trip_costs:
        trip = trip_by_id.get(cost.trip_id)
        if not trip:
            continue

        # Comenzi unice pe trip
        unique_order_ids = set()
        for stop in trip.stops:
            if stop.order_id:
                unique_order_ids.add(stop.order_id)

        orders_count = len(unique_order_ids)
        actual_cost = money_to_float(cost.total_actual)
        trip_km = money_to_float(trip.planned_km)

        cost_per_order_trip = safe_divide(actual_cost, orders_count) if orders_count > 0 else 0.0

        if cost_per_order_trip > safe_divide(cost_per_order * 1.5, 1):
            recommendation = "Cost mare per comandă. Verifică posibilitatea de consolidare."
        elif actual_cost > money_to_float(cost.total_planned) * 1.2:
            recommendation = "Costul real depășește costul planificat. Verifică abaterea km/durată."
        else:
            recommendation = "Cost într-o marjă acceptabilă."

        expensive_trips.append({
            "trip_id": str(trip.id),
            "planned_km": round(trip_km, 2),
            "orders_count": orders_count,
            "total_cost": round(actual_cost, 2),
            "cost_per_order": round(cost_per_order_trip, 2),
            "recommendation": recommendation,
        })

    expensive_trips.sort(key=lambda x: (x["cost_per_order"], x["total_cost"]), reverse=True)
    expensive_trips = expensive_trips[:10]

    return {
        "total_planned_cost": round(total_planned_cost, 2),
        "total_actual_cost": round(total_actual_cost, 2),
        "total_extra_cost": round(total_extra_cost, 2),
        "fuel_cost_planned": round(fuel_cost_planned, 2),
        "fuel_cost_actual": round(fuel_cost_actual, 2),
        "driver_cost_planned": round(driver_cost_planned, 2),
        "driver_cost_actual": round(driver_cost_actual, 2),
        "amortization_cost": round(amortization_cost, 2),
        "cost_per_trip": round(cost_per_trip, 2),
        "cost_per_order": round(cost_per_order, 2),
        "cost_per_km": round(cost_per_km, 2) if cost_per_km else None,
        "cost_per_kg": round(cost_per_kg, 2) if cost_per_kg else None,
        "cost_per_m3": round(cost_per_m3, 2) if cost_per_m3 else None,
        "planned_vs_actual_variance": round(variance, 2),
        "planned_vs_actual_variance_percent": round(variance_percent, 1),
        "by_driver": by_driver_list,
        "by_vehicle": by_vehicle_list,
        "by_zone": by_zone_list,
        "top_expensive_trips": expensive_trips,
    }


# ============== Incident Impact ==============

def get_incident_impact(db: Session, company_id, start_date: date | None, end_date: date | None) -> dict:
    """Analizează impactul incidentelor."""
    start_date, end_date = parse_date_range(start_date, end_date)

    incidents = db.query(Incident).join(
        Trip, Incident.trip_id == Trip.id
    ).filter(
        Trip.company_id == company_id,
        Incident.created_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
        Incident.created_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc),
    ).all()

    total_incidents = len(incidents)
    minor_incidents = sum(1 for i in incidents if "MINOR" in enum_value(i.type).upper())
    major_incidents = total_incidents - minor_incidents

    interrupted_trips = sum(1 for i in incidents if i.trip and i.trip.status == TripStatusEnum.INTERRUPTED)
    recovery_trips_created = sum(1 for i in incidents if i.recovery_trip_id)

    # incident_rate ca procent
    total_trips = len(db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date >= start_date,
        Trip.planned_date <= end_date,
        Trip.status.in_([TripStatusEnum.IN_PROGRESS, TripStatusEnum.COMPLETED, TripStatusEnum.INTERRUPTED]),
    ).all())
    incident_rate = safe_divide(total_incidents, total_trips, default=0.0) * 100 if total_trips > 0 else 0.0

    major_incident_rate = safe_divide(major_incidents, total_incidents, default=0.0) * 100 if total_incidents > 0 else 0.0

    recovery_times = []
    for incident in incidents:
        if incident.created_at and incident.resolved_at:
            recovery_time = minutes_between(incident.created_at, incident.resolved_at)
            recovery_times.append(recovery_time)

    avg_recovery_time = safe_divide(sum(recovery_times), len(recovery_times)) if recovery_times else None

    # Detalii incidente majore
    major_incidents_detail = []

    for incident in incidents:
        if "MINOR" in enum_value(incident.type).upper():
            continue

        trip = incident.trip
        if not trip:
            continue

        # Comenzi unice necompletate
        affected_order_ids = set()
        affected_kg = 0.0
        affected_m3 = 0.0

        for stop in trip.stops:
            if stop.status != StopStatusEnum.COMPLETED:
                if stop.order_id and stop.order_id not in affected_order_ids:
                    affected_order_ids.add(stop.order_id)
                    if stop.order:
                        affected_kg += money_to_float(stop.order.kg)
                        affected_m3 += money_to_float(stop.order.m3)

        affected_orders = len(affected_order_ids)
        affected_stops = sum(1 for s in trip.stops if s.status != StopStatusEnum.COMPLETED)

        extra_recovery_km = 0.0
        extra_recovery_duration = 0
        extra_recovery_cost = money_to_float(incident.extra_cost_estimated) if incident.extra_cost_estimated else 0.0

        if incident.recovery_trip_id:
            recovery_trip = db.query(Trip).filter(Trip.id == incident.recovery_trip_id).first()
            if recovery_trip:
                extra_recovery_km = money_to_float(recovery_trip.planned_km)
                extra_recovery_duration = recovery_trip.planned_duration_min if recovery_trip.planned_duration_min else 0

        estimated_delay = 0
        if trip.actual_duration_min and trip.planned_duration_min:
            estimated_delay = max(0, trip.actual_duration_min - trip.planned_duration_min)
        elif incident.resolved_at:
            estimated_delay = minutes_between(incident.created_at, incident.resolved_at)

        impact_score_value = (
            affected_orders * 10
            + extra_recovery_cost / 10
            + extra_recovery_km
            + estimated_delay
        )

        max_impact = 1000
        impact_score = clamp_score(impact_score_value / max_impact * 100)

        if impact_score >= 70:
            impact_level = "HIGH"
        elif impact_score >= 40:
            impact_level = "MEDIUM"
        else:
            impact_level = "LOW"

        if impact_level == "HIGH":
            if affected_orders > 0:
                recommendation = "Incident cu impact ridicat. Prioritizează recovery pentru comenzile CRITIC și PERISABIL."
            else:
                recommendation = "Incident major cu impact ridicat asupra operațiunilor."
        elif not incident.recovery_trip_id:
            recommendation = "Incident major fără recovery trip. Creează o cursă de recovery sau reprogramează comenzile afectate."
        else:
            recommendation = "Incident gestionat prin recovery trip."

        resolved_at_str = incident.resolved_at.isoformat() if incident.resolved_at else None

        major_incidents_detail.append({
            "incident_id": str(incident.id),
            "original_trip_id": str(incident.trip_id) if incident.trip_id else "UNKNOWN",
            "type": enum_value(incident.type),
            "created_at": incident.created_at.isoformat() if incident.created_at else "UNKNOWN",
            "resolved_at": resolved_at_str,
            "recovery_trip_id": str(incident.recovery_trip_id) if incident.recovery_trip_id else None,
            "affected_orders_count": affected_orders,
            "affected_stops_count": affected_stops,
            "affected_kg": round(affected_kg, 2),
            "affected_m3": round(affected_m3, 2),
            "extra_recovery_km": round(extra_recovery_km, 2),
            "extra_recovery_duration_min": extra_recovery_duration,
            "extra_recovery_cost": round(extra_recovery_cost, 2),
            "estimated_delay_minutes": estimated_delay,
            "incident_impact_score": impact_score,
            "impact_level": impact_level,
            "recommendation": recommendation,
        })

    return {
        "total_incidents": total_incidents,
        "minor_incidents": minor_incidents,
        "major_incidents": major_incidents,
        "interrupted_trips": interrupted_trips,
        "recovery_trips_created": recovery_trips_created,
        "incident_rate": round(incident_rate, 2),
        "major_incident_rate": round(major_incident_rate, 1),
        "average_recovery_time_minutes": round(avg_recovery_time, 1) if avg_recovery_time is not None else None,
        "major_incidents_detail": major_incidents_detail,
    }
