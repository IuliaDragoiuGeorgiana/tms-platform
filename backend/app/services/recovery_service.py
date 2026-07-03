"""
Serviciul de recuperare a comenzilor după o avarie majoră.
Implementează RECOVER_ALL_REMAINING strategy cu reoptimizare reală ORS + OR-Tools.
"""
from datetime import date, datetime, timezone, time as time_type, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException
from zoneinfo import ZoneInfo
import math
import uuid

from app.models.incident import Incident, IncidentTypeEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_stop import TripStop, StopStatusEnum, StopTypeEnum
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.models.driver import Driver, DriverStatusEnum
from app.models.order import Order, OrderStatusEnum
from app.models.system_config import SystemConfig

from app.services.ors_service import get_distance_matrix
from app.services.trip_cost_service import calculate_cost_components, upsert_trip_cost
from app.services.vrp_service import solve_pdp_for_cluster

LOCAL_TZ = ZoneInfo("Europe/Bucharest")


def time_to_seconds(t: time_type) -> int:
    """Convertește time în secunde de la 00:00."""
    if not t:
        return 0
    return t.hour * 3600 + t.minute * 60 + t.second


def incident_start_seconds(incident: Incident) -> int:
    """Returnează ora incidentului în secunde de la 00:00."""
    if not incident.created_at:
        return 0
    local_dt = incident.created_at.astimezone(LOCAL_TZ)
    return local_dt.hour * 3600 + local_dt.minute * 60 + local_dt.second


def get_remaining_stops_for_trip(trip: Trip) -> list[TripStop]:
    """Returnează stopurile PENDING din trip, sortate după sequence."""
    return sorted(
        [stop for stop in trip.stops if stop.status == StopStatusEnum.PENDING],
        key=lambda s: s.sequence
    )


def get_affected_orders_from_trip(trip: Trip) -> tuple[dict, list[str]]:
    """Returnează comenzile eligibile pentru RECOVER_ALL_REMAINING."""
    orders_dict = {}
    warnings = []

    for stop in trip.stops:
        if stop.order_id not in orders_dict:
            orders_dict[stop.order_id] = {
                "order": stop.order,
                "pickup_status": None,
                "delivery_status": None,
                "has_failed_or_skipped_stop": False,
            }

        if stop.status in (StopStatusEnum.FAILED, StopStatusEnum.SKIPPED):
            orders_dict[stop.order_id]["has_failed_or_skipped_stop"] = True

        if stop.stop_type == StopTypeEnum.PICKUP:
            orders_dict[stop.order_id]["pickup_status"] = stop.status
        elif stop.stop_type == StopTypeEnum.DELIVERY:
            orders_dict[stop.order_id]["delivery_status"] = stop.status

    affected_orders = {}
    for order_id, order_info in orders_dict.items():
        order = order_info["order"]
        order_ref = order.order_ref if order else str(order_id)

        if order_info["has_failed_or_skipped_stop"]:
            warnings.append(
                f"Comanda {order_ref} are stop FAILED/SKIPPED și nu intră în recovery."
            )
            continue

        pickup_status = order_info["pickup_status"]
        delivery_status = order_info["delivery_status"]
        pickup_is_completed = (
            pickup_status == StopStatusEnum.COMPLETED
            or (
                pickup_status is None
                and delivery_status == StopStatusEnum.PENDING
                and order
                and order.status == OrderStatusEnum.IN_DELIVERY
            )
            or (
                pickup_status is None
                and delivery_status == StopStatusEnum.PENDING
                and trip.recovery_for_trip_id is not None
            )
        )

        if (
            pickup_is_completed
            and delivery_status == StopStatusEnum.COMPLETED
        ):
            continue

        if (
            pickup_is_completed
            and delivery_status == StopStatusEnum.PENDING
        ):
            affected_orders[order_id] = {
                "order": order,
                "has_pending_pickup": False,
                "has_pending_delivery": True,
            }
            continue

        if (
            pickup_status == StopStatusEnum.PENDING
            and delivery_status == StopStatusEnum.PENDING
        ):
            affected_orders[order_id] = {
                "order": order,
                "has_pending_pickup": True,
                "has_pending_delivery": True,
            }
            continue

        if delivery_status == StopStatusEnum.PENDING:
            warnings.append(
                f"Comanda {order_ref} are delivery pending, dar pickup-ul nu este completat."
            )

    return affected_orders, warnings


def get_config_value(db: Session, company_id, key: str, default: float) -> float:
    """Citește valoare din SystemConfig sau returnează default."""
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


def build_recovery_problem_nodes(
    incident: Incident,
    affected_orders_dict: dict,
    depot_lat: float,
    depot_lon: float,
) -> tuple[list[dict], dict, list[tuple[int, int]], list[str]]:
    """
    Construiește lista de noduri pentru problema de recovery.
    Returnează și warnings pentru comenzile fără coordonate.
    """
    warnings = []
    start_node = {
        "lat": depot_lat,
        "lon": depot_lon,
        "source": "DEPOT",
    }
    has_incident_location = (
        incident.location_lat is not None and incident.location_lon is not None
    )
    transfer_lat = float(incident.location_lat) if has_incident_location else depot_lat
    transfer_lon = float(incident.location_lon) if has_incident_location else depot_lon

    nodes = [start_node]
    node_to_stop_map = {0: (None, None, None)}

    idx = 1
    pickups_deliveries_indices = []

    for order_id, order_info in affected_orders_dict.items():
        order = order_info["order"]
        has_pending_pickup = order_info["has_pending_pickup"]
        has_pending_delivery = order_info["has_pending_delivery"]

        pickup_idx = None
        delivery_idx = None

        if has_pending_delivery and (order.delivery_lat is None or order.delivery_lon is None):
            warnings.append(
                f"Comanda {order.order_ref} nu are coordonate delivery și nu poate fi inclusă în recovery optimizat."
            )
            continue

        if has_pending_pickup and (order.pickup_lat is None or order.pickup_lon is None):
            warnings.append(
                f"Comanda {order.order_ref} nu are coordonate pickup și nu poate fi inclusă în recovery optimizat."
            )
            continue

        if has_pending_delivery and not has_pending_pickup:
            pickup_idx = idx
            nodes.append({
                "lat": transfer_lat,
                "lon": transfer_lon,
                "source": "INCIDENT_TRANSFER",
            })
            node_to_stop_map[idx] = (order_id, "TRANSFER_FROM_BROKEN_VEHICLE", True)
            idx += 1
        else:
            pickup_idx = idx
            nodes.append({
                "lat": float(order.pickup_lat),
                "lon": float(order.pickup_lon),
                "source": "ORDER_PICKUP",
            })
            node_to_stop_map[idx] = (order_id, "PICKUP", False)
            idx += 1

        if has_pending_delivery:
            delivery_idx = idx
            nodes.append({
                "lat": float(order.delivery_lat),
                "lon": float(order.delivery_lon),
                "source": "ORDER_DELIVERY",
            })
            node_to_stop_map[idx] = (order_id, "DELIVERY", False)
            idx += 1

        if pickup_idx is not None and delivery_idx is not None:
            pickups_deliveries_indices.append((pickup_idx, delivery_idx))

    return nodes, node_to_stop_map, pickups_deliveries_indices, warnings


def build_time_windows(
    nodes: list[dict],
    node_to_stop_map: dict,
    affected_orders_dict: dict,
    incident_start_sec: int,
    driver_start_sec: int,
    driver_end_sec: int,
) -> list[tuple[int, int]]:
    """
    Construiește time windows pentru fiecare nod.
    FIX #7: Recovery poate începe din shift_start, minimum la incident_start_sec.
    """
    effective_start_sec = max(incident_start_sec, driver_start_sec)
    time_windows = []

    for idx in range(len(nodes)):
        order_id, stop_type, is_virtual = node_to_stop_map.get(idx, (None, None, None))

        if idx == 0:
            time_windows.append((effective_start_sec, driver_end_sec))
        elif is_virtual:
            time_windows.append((effective_start_sec, driver_end_sec))
        elif order_id and order_id in affected_orders_dict:
            order = affected_orders_dict[order_id]["order"]
            if stop_type == "PICKUP":
                start = time_to_seconds(order.pickup_time_window_start) if order.pickup_time_window_start else effective_start_sec
                end = time_to_seconds(order.pickup_time_window_end) if order.pickup_time_window_end else driver_end_sec
            else:  # DELIVERY
                start = time_to_seconds(order.delivery_time_window_start) if order.delivery_time_window_start else effective_start_sec
                end = time_to_seconds(order.delivery_time_window_end) if order.delivery_time_window_end else driver_end_sec

            tw_start = max(start, effective_start_sec)
            tw_end = min(end, driver_end_sec)

            if tw_start > tw_end:
                tw_start = tw_start
                tw_end = tw_start

            time_windows.append((tw_start, tw_end))
        else:
            time_windows.append((effective_start_sec, driver_end_sec))

    return time_windows


def build_service_times(
    nodes: list[dict],
    node_to_stop_map: dict,
    affected_orders_dict: dict,
) -> list[int]:
    """Construiește service times pentru fiecare nod, în secunde."""
    service_times = []

    for idx in range(len(nodes)):
        order_id, stop_type, is_virtual = node_to_stop_map.get(idx, (None, None, None))

        if idx == 0 or is_virtual:
            service_times.append(0)
        elif order_id and order_id in affected_orders_dict:
            order = affected_orders_dict[order_id]["order"]
            if stop_type == "PICKUP":
                minutes = order.pickup_service_minutes or 10
            else:  # DELIVERY
                minutes = order.delivery_service_minutes or 5
            service_times.append(int(minutes * 60))
        else:
            service_times.append(0)

    return service_times


def build_demands(
    nodes: list[dict],
    node_to_stop_map: dict,
    affected_orders_dict: dict,
) -> tuple[list[int], list[int]]:
    """
    Construiește demands (kg și m3 scalat în litri).
    FIX #3: m3 scalat × 1000 pentru a păstra zecimalele.
    """
    kg_demands = []
    m3_demands = []

    for idx in range(len(nodes)):
        order_id, stop_type, is_virtual = node_to_stop_map.get(idx, (None, None, None))

        if idx == 0:
            kg_demands.append(0)
            m3_demands.append(0)
        elif order_id and order_id in affected_orders_dict:
            order = affected_orders_dict[order_id]["order"]
            kg = int(float(order.kg)) if order.kg else 0
            m3 = int(float(order.m3) * 1000) if order.m3 else 0

            if stop_type == "PICKUP" or is_virtual:
                kg_demands.append(kg)
                m3_demands.append(m3)
            else:  # DELIVERY
                kg_demands.append(-kg)
                m3_demands.append(-m3)
        else:
            kg_demands.append(0)
            m3_demands.append(0)

    return kg_demands, m3_demands


def find_candidate_drivers_vehicles(
    db: Session,
    company_id,
    planned_date,
    original_vehicle_id,
    original_driver_id,
    affected_orders_dict: dict,
) -> list[tuple[Driver, Vehicle]]:
    """Caută toți șoferii și vehiculele disponibile pentru recovery."""
    candidates = []

    vehicles = db.query(Vehicle).filter(
        and_(
            Vehicle.company_id == company_id,
            Vehicle.status == VehicleStatusEnum.DISPONIBIL,
            Vehicle.id != original_vehicle_id,
        )
    ).all()

    drivers = db.query(Driver).filter(
        and_(
            Driver.company_id == company_id,
            Driver.status == DriverStatusEnum.AVAILABLE,
            Driver.id != original_driver_id,
        )
    ).all()

    for vehicle in vehicles:
        vehicle_kg = float(vehicle.capacity_kg) if vehicle.capacity_kg else 0
        vehicle_m3 = int(float(vehicle.capacity_m3) * 1000) if vehicle.capacity_m3 else 0

        max_order_kg = max(
            (float(o["order"].kg) if o["order"].kg else 0 for o in affected_orders_dict.values()),
            default=0
        )
        max_order_m3 = max(
            (int(float(o["order"].m3) * 1000) if o["order"].m3 else 0 for o in affected_orders_dict.values()),
            default=0
        )

        if vehicle_kg < max_order_kg or vehicle_m3 < max_order_m3:
            continue

        vehicle_trips_same_day = db.query(Trip).filter(
            and_(
                Trip.vehicle_id == vehicle.id,
                Trip.planned_date == planned_date,
                Trip.status.in_([TripStatusEnum.APPROVED, TripStatusEnum.IN_PROGRESS]),
            )
        ).first()

        if vehicle_trips_same_day:
            continue

        for driver in drivers:
            driver_trips_same_day = db.query(Trip).filter(
                and_(
                    Trip.driver_id == driver.id,
                    Trip.planned_date == planned_date,
                    Trip.status.in_([TripStatusEnum.APPROVED, TripStatusEnum.IN_PROGRESS]),
                )
            ).first()

            if driver_trips_same_day:
                continue

            candidates.append((driver, vehicle))

    return candidates


def optimize_recovery_for_candidate(
    nodes: list[dict],
    pickups_deliveries_indices: list[tuple[int, int]],
    kg_demands: list[int],
    m3_demands: list[int],
    time_windows: list[tuple[int, int]],
    service_times: list[int],
    driver: Driver,
    vehicle: Vehicle,
    node_to_stop_map: dict,
    affected_orders_dict: dict,
) -> dict | None:
    """
    Rulează ORS + OR-Tools pentru o pereche șofer/vehicul.
    """
    coordinates = [[float(n["lon"]), float(n["lat"])] for n in nodes]

    try:
        matrix_result = get_distance_matrix(coordinates)
    except Exception:
        return None

    if not matrix_result:
        return None

    distance_matrix = matrix_result.get("distances")
    duration_matrix = matrix_result.get("durations")

    if not distance_matrix or not duration_matrix:
        return None

    try:
        solution = solve_pdp_for_cluster(
            distance_matrix=distance_matrix,
            duration_matrix=duration_matrix,
            pickups_deliveries=pickups_deliveries_indices,
            demands=kg_demands,
            vehicle_capacity_kg=int(float(vehicle.capacity_kg)),
            volume_demands=m3_demands,
            vehicle_capacity_m3=int(float(vehicle.capacity_m3) * 1000),
            time_windows=time_windows,
            service_times=service_times,
            depot_index=0,
            max_time_seconds=5,
        )
    except Exception:
        return None

    if not solution:
        return None

    route = solution.get("route", [])
    arrival_times = solution.get("arrival_times", {})

    if not route or len(route) < 2:
        return None

    route_for_metrics = route

    total_distance_m = sum(
        distance_matrix[route_for_metrics[i]][route_for_metrics[i + 1]]
        for i in range(len(route_for_metrics) - 1)
    )
    total_distance_km = total_distance_m / 1000.0

    start_sec = solution.get("start_seconds", arrival_times.get(route[0], 0))
    end_sec = solution.get("end_seconds")
    if end_sec is not None:
        total_duration_s = max(0, end_sec - start_sec)
    else:
        total_duration_s = sum(
            duration_matrix[route_for_metrics[i]][route_for_metrics[i + 1]]
            + service_times[route_for_metrics[i]]
            for i in range(len(route_for_metrics) - 1)
        )
    total_duration_min = total_duration_s / 60.0

    route_stops = []
    late_orders_count = 0

    for node_idx in route:
        if node_idx == 0:
            continue

        order_id, stop_type, is_virtual = node_to_stop_map.get(node_idx, (None, None, None))

        if order_id and order_id in affected_orders_dict:
            arrival_sec = arrival_times.get(node_idx)

            if arrival_sec is None:
                continue

            order = affected_orders_dict[order_id]["order"]

            if stop_type == "DELIVERY":
                deadline = time_to_seconds(order.delivery_time_window_end) if order.delivery_time_window_end else 86400
                if arrival_sec > deadline:
                    late_orders_count += 1

            route_stops.append({
                "node_idx": node_idx,
                "order_id": str(order_id),
                "order_ref": order.order_ref if order else None,
                "stop_type": stop_type,
                "sequence": len(route_stops) + 1,
                "eta_seconds": int(arrival_sec),
                "is_virtual": bool(is_virtual),
            })

    return {
        "route": route,
        "planned_km": round(total_distance_km, 2),
        "planned_duration_min": round(total_duration_min, 2),
        "route_stops": route_stops,
        "late_orders_count": late_orders_count,
    }


def _build_route_recovery_analysis(
    db: Session,
    incident: Incident,
    strategy_type: str,
    picked_up_only: bool = False,
    unpicked_only: bool = False,
    planning_date: date | None = None,
    start_at_shift: bool = False,
) -> dict:
    """
    Construiește analiza reală de impact cu ORS + OR-Tools.
    """
    trip = incident.trip
    remaining_stops = get_remaining_stops_for_trip(trip)
    affected_orders_dict, eligibility_warnings = get_affected_orders_from_trip(trip)

    if picked_up_only:
        affected_orders_dict = {
            order_id: info
            for order_id, info in affected_orders_dict.items()
            if not info["has_pending_pickup"] and info["has_pending_delivery"]
        }
    elif unpicked_only:
        affected_orders_dict = {
            order_id: info
            for order_id, info in affected_orders_dict.items()
            if info["has_pending_pickup"] and info["has_pending_delivery"]
        }

    if not affected_orders_dict:
        warnings = eligibility_warnings or ["Nu există comenzi rămase pentru recovery."]
        return {
            "incident_id": str(incident.id),
            "original_trip_id": str(trip.id),
            "original_vehicle_id": str(trip.vehicle_id) if trip.vehicle_id else None,
            "broken_vehicle_plate": trip.vehicle.plate if trip.vehicle else None,
            "recovery_start_source": "UNKNOWN",
            "recovery_start_lat": None,
            "recovery_start_lon": None,
            "remaining_stops_count": 0,
            "affected_orders_count": 0,
            "total_kg": 0.0,
            "total_m3": 0.0,
            "options": [],
            "warnings": warnings,
        }

    # FIX #2 & #8: Folosește depot din company, nu hardcodat
    company = trip.company
    if not company or company.depot_lat is None or company.depot_lon is None:
        return {
            "incident_id": str(incident.id),
            "original_trip_id": str(trip.id),
            "original_vehicle_id": str(trip.vehicle_id) if trip.vehicle_id else None,
            "broken_vehicle_plate": trip.vehicle.plate if trip.vehicle else None,
            "recovery_start_source": "UNKNOWN",
            "recovery_start_lat": None,
            "recovery_start_lon": None,
            "remaining_stops_count": 0,
            "affected_orders_count": 0,
            "total_kg": 0.0,
            "total_m3": 0.0,
            "options": [],
            "warnings": ["Compania nu are depot configurat. Recuperare imposibilă."],
        }

    depot_lat = float(company.depot_lat)
    depot_lon = float(company.depot_lon)

    recovery_start_lat = depot_lat
    recovery_start_lon = depot_lon

    incident_start_sec = 0 if start_at_shift else incident_start_seconds(incident)
    candidate_planning_date = planning_date or trip.planned_date

    candidates = find_candidate_drivers_vehicles(
        db,
        company_id=trip.company_id,
        planned_date=candidate_planning_date,
        original_vehicle_id=trip.vehicle_id,
        original_driver_id=trip.driver_id,
        affected_orders_dict=affected_orders_dict,
    )

    total_kg = sum(float(o["order"].kg) for o in affected_orders_dict.values() if o["order"].kg)
    total_m3 = sum(float(o["order"].m3) for o in affected_orders_dict.values() if o["order"].m3)

    analysis_warnings = list(eligibility_warnings)
    options = []

    nodes, node_to_stop_map, pickups_deliveries_indices, node_warnings = build_recovery_problem_nodes(
        incident, affected_orders_dict, depot_lat, depot_lon
    )
    analysis_warnings.extend(node_warnings)

    if not nodes or len(nodes) <= 1:
        return {
            "incident_id": str(incident.id),
            "original_trip_id": str(trip.id),
            "original_vehicle_id": str(trip.vehicle_id) if trip.vehicle_id else None,
            "broken_vehicle_plate": trip.vehicle.plate if trip.vehicle else None,
            "recovery_start_source": "DEPOT",
            "recovery_start_lat": recovery_start_lat,
            "recovery_start_lon": recovery_start_lon,
            "remaining_stops_count": len(remaining_stops),
            "affected_orders_count": len(affected_orders_dict),
            "total_kg": total_kg,
            "total_m3": total_m3,
            "options": [],
            "warnings": analysis_warnings or ["Nu există comenzi cu coordonate valide pentru recovery."],
        }

    failed_candidates = 0
    shift_rejected_candidates = 0

    for driver, vehicle in candidates:
        # FIX #7: Folosește shift_start și shift_end
        driver_start_sec = (
            time_to_seconds(driver.shift_start)
            if driver.shift_start
            else incident_start_sec
        )
        driver_end_sec = (
            time_to_seconds(driver.shift_end)
            if driver.shift_end
            else 18 * 3600
        )

        if driver_end_sec <= max(incident_start_sec, driver_start_sec):
            shift_rejected_candidates += 1
            continue

        time_windows = build_time_windows(
            nodes, node_to_stop_map, affected_orders_dict, incident_start_sec, driver_start_sec, driver_end_sec
        )
        service_times = build_service_times(nodes, node_to_stop_map, affected_orders_dict)
        kg_demands, m3_demands = build_demands(nodes, node_to_stop_map, affected_orders_dict)

        solution = optimize_recovery_for_candidate(
            nodes,
            pickups_deliveries_indices,
            kg_demands,
            m3_demands,
            time_windows,
            service_times,
            driver,
            vehicle,
            node_to_stop_map,
            affected_orders_dict,
        )

        if not solution:
            failed_candidates += 1
            continue

        estimated_cost = calculate_cost_components(
            db,
            trip.company_id,
            vehicle,
            solution["planned_km"],
            solution["planned_duration_min"],
        )
        fuel_cost = float(estimated_cost["fuel_cost"])
        driver_cost = float(estimated_cost["driver_cost"])
        total_cost = float(estimated_cost["total_cost"])

        # FIX #6: getattr fallback pentru driver_name
        driver_name = "Unknown"
        if driver.user:
            driver_name = (
                getattr(driver.user, "full_name", None)
                or getattr(driver.user, "email", None)
                or "Unknown"
            )

        option = {
            "option_id": f"{strategy_type.lower()}_{len(options) + 1}",
            "type": strategy_type,
            "planned_date": candidate_planning_date.isoformat(),
            "feasible": True,
            "driver_id": str(driver.id),
            "driver_name": driver_name,
            "vehicle_id": str(vehicle.id),
            "vehicle_plate": vehicle.plate,
            "planned_km": solution["planned_km"],
            "planned_duration_min": solution["planned_duration_min"],
            "estimated_fuel_cost": round(fuel_cost, 2),
            "estimated_driver_cost": round(driver_cost, 2),
            "estimated_total_cost": round(total_cost, 2),
            "late_orders_count": solution["late_orders_count"],
            "warnings": [],
            "route": solution["route_stops"],
            "recommended": False,
        }
        options.append(option)

    if options:
        options.sort(key=lambda o: (
            o["late_orders_count"],
            o["planned_duration_min"],
            o["planned_km"],
            o["estimated_total_cost"]
        ))
        options[0]["recommended"] = True

    start_source = "DEPOT"

    if analysis_warnings:
        final_warnings = analysis_warnings
    elif options:
        final_warnings = []
    elif candidates and shift_rejected_candidates == len(candidates):
        final_warnings = [
            "Există șofer și vehicul candidat pentru recovery, dar programul șoferului nu permite recovery după ora incidentului. Verifică shift_start/shift_end pentru șoferul disponibil."
        ]
    elif candidates:
        final_warnings = [
            "Există șofer și vehicul candidat pentru recovery, dar optimizarea nu a găsit o rută fezabilă. Verifică ferestrele de timp, programul șoferului, capacitatea vehiculului și coordonatele comenzilor."
        ]
    else:
        final_warnings = ["Nu sunt disponibili șoferi sau vehicule pentru recovery."]

    return {
        "incident_id": str(incident.id),
        "original_trip_id": str(trip.id),
        "original_vehicle_id": str(trip.vehicle_id) if trip.vehicle_id else None,
        "broken_vehicle_plate": trip.vehicle.plate if trip.vehicle else None,
        "recovery_start_source": start_source,
        "recovery_start_lat": recovery_start_lat,
        "recovery_start_lon": recovery_start_lon,
        "remaining_stops_count": len(remaining_stops),
        "affected_orders_count": len(affected_orders_dict),
        "total_kg": total_kg,
        "total_m3": total_m3,
        "options": options,
        "warnings": final_warnings,
    }


def _infeasible_recovery_option(option_id: str, strategy_type: str, warning: str) -> dict:
    return {
        "option_id": option_id,
        "type": strategy_type,
        "planned_date": None,
        "feasible": False,
        "recommended": False,
        "driver_id": None,
        "driver_name": None,
        "vehicle_id": None,
        "vehicle_plate": None,
        "planned_km": 0.0,
        "planned_duration_min": 0.0,
        "estimated_fuel_cost": 0.0,
        "estimated_driver_cost": 0.0,
        "estimated_total_cost": 0.0,
        "late_orders_count": 0,
        "warnings": [warning],
        "route": [],
    }


def _best_recovery_option(options: list[dict]) -> dict | None:
    """Return the best candidate while keeping driver/vehicle alternatives internal."""
    if not options:
        return None
    return min(
        options,
        key=lambda option: (
            option["late_orders_count"],
            option["planned_duration_min"],
            option["planned_km"],
            option["estimated_total_cost"],
        ),
    )


def build_incident_recovery_analysis(db: Session, incident: Incident) -> dict:
    all_analysis = _build_route_recovery_analysis(
        db, incident, "RECOVER_ALL_REMAINING"
    )
    picked_analysis = _build_route_recovery_analysis(
        db, incident, "RECOVER_PICKED_UP_ONLY", picked_up_only=True
    )
    best_all_option = _best_recovery_option(all_analysis["options"])
    options = []
    if best_all_option:
        options.append(best_all_option)
    else:
        options.append(_infeasible_recovery_option(
            "all_unavailable",
            "RECOVER_ALL_REMAINING",
            "Nu există o variantă fezabilă pentru recuperarea tuturor comenzilor.",
        ))
    best_picked_option = _best_recovery_option(picked_analysis["options"])
    if best_picked_option:
        options.append(best_picked_option)
    else:
        options.append(_infeasible_recovery_option(
            "picked_up_unavailable",
            "RECOVER_PICKED_UP_ONLY",
            "Nu există comenzi deja preluate care pot fi recuperate sau nu există resurse disponibile.",
        ))
    affected_orders, _ = get_affected_orders_from_trip(incident.trip)
    unpicked_orders = [
        info for info in affected_orders.values()
        if info["has_pending_pickup"] and info["has_pending_delivery"]
    ]
    picked_orders = [
        info for info in affected_orders.values()
        if not info["has_pending_pickup"] and info["has_pending_delivery"]
    ]
    postpone_options = []
    postpone_failure_warning = "Nu există comenzi nepreluate care pot fi amânate."

    if unpicked_orders:
        first_day = incident.trip.planned_date + timedelta(days=1)
        last_day = first_day + timedelta(days=14)

        for info in unpicked_orders:
            order = info["order"]
            if order.delivery_deadline:
                flexibility_days = order.flexibility_days or 0
                order_first_day = order.delivery_deadline - timedelta(
                    days=flexibility_days
                )
                if order.earliest_delivery_date:
                    order_first_day = max(
                        order_first_day, order.earliest_delivery_date
                    )
                first_day = max(first_day, order_first_day)
                last_day = min(last_day, order.delivery_deadline)

        candidate_day = first_day
        while candidate_day <= last_day:
            postpone_analysis = _build_route_recovery_analysis(
                db,
                incident,
                "POSTPONE_REMAINING",
                unpicked_only=True,
                planning_date=candidate_day,
                start_at_shift=True,
            )
            if postpone_analysis["options"]:
                postpone_options = postpone_analysis["options"]
                for option in postpone_options:
                    option["warnings"] = [
                        (
                            "Rută proiectată pentru replanificare în data de "
                            f"{candidate_day.isoformat()}."
                        )
                    ]
                    if picked_orders:
                        option["warnings"].append(
                            "Marfa deja preluată necesită recovery separat."
                        )
                break
            candidate_day += timedelta(days=1)

        if not postpone_options:
            postpone_failure_warning = (
                "Nu s-a găsit în următoarea fereastră permisă o zi cu "
                "șofer, vehicul și rută fezabilă pentru comenzile amânate."
            )

    best_postpone_option = _best_recovery_option(postpone_options)
    if best_postpone_option:
        options.append(best_postpone_option)
    else:
        options.append(
            _infeasible_recovery_option(
                "postpone_unavailable",
                "POSTPONE_REMAINING",
                postpone_failure_warning,
            )
        )
    for option in options:
        option["recommended"] = False
    recovery_options = [
        option for option in options
        if option["feasible"] and option["type"] != "POSTPONE_REMAINING"
    ]
    if recovery_options:
        recommended = min(
            recovery_options,
            key=lambda option: (
                option["late_orders_count"],
                0 if option["type"] == "RECOVER_ALL_REMAINING" else 1,
                option["estimated_total_cost"],
                option["planned_duration_min"],
            ),
        )
        recommended["recommended"] = True
    else:
        postpone = next(
            option for option in options if option["type"] == "POSTPONE_REMAINING"
        )
        if postpone["feasible"]:
            postpone["recommended"] = True
    all_analysis["options"] = options
    return all_analysis
def postpone_remaining_orders(
    db: Session,
    incident: Incident,
    selected_option: dict | None = None,
) -> dict:
    original_trip = incident.trip
    if incident.type != IncidentTypeEnum.MAJOR:
        raise HTTPException(status_code=400, detail="Postpone este disponibil doar pentru incidente MAJOR")
    if original_trip.status != TripStatusEnum.INTERRUPTED:
        raise HTTPException(status_code=400, detail="Tripul original trebuie să fie INTERRUPTED")
    affected_orders, _ = get_affected_orders_from_trip(original_trip)
    unpicked_orders = {
        order_id: info
        for order_id, info in affected_orders.items()
        if info["has_pending_pickup"] and info["has_pending_delivery"]
    }
    if not unpicked_orders:
        raise HTTPException(status_code=400, detail="Nu există comenzi nepreluate care pot fi amânate")
    target_planning_date = None
    if selected_option and selected_option.get("planned_date"):
        try:
            target_planning_date = date.fromisoformat(selected_option["planned_date"])
        except (TypeError, ValueError):
            target_planning_date = None
    postponed_refs = []
    for order_id, info in unpicked_orders.items():
        order = info["order"]
        order.status = OrderStatusEnum.PENDING
        order.assigned_delivery_date = target_planning_date
        order.problem_reason = None
        order.is_problematic = False
        order.was_postponed = True
        postponed_refs.append(order.order_ref)
    postponed_order_ids = set(unpicked_orders)
    for stop in original_trip.stops:
        if stop.order_id in postponed_order_ids and stop.status == StopStatusEnum.PENDING:
            stop.status = StopStatusEnum.SKIPPED
            stop.notes = f"Amânat pentru replanificare din incidentul {incident.id}"
    incident.resolved_at = datetime.now(timezone.utc)
    incident.extra_cost_estimated = 0
    db.commit()
    return {
        "postponed_orders_count": len(unpicked_orders),
        "postponed_order_refs": postponed_refs,
    }
def create_recovery_trip(db: Session, incident: Incident, selected_option: dict | None = None) -> Trip:
    """
    Creează recovery trip din opțiunea recomandată din impact_analysis.
    """
    original_trip = incident.trip

    if incident.type != IncidentTypeEnum.MAJOR:
        raise HTTPException(status_code=400, detail="Recovery este disponibil doar pentru incidente MAJOR")

    if original_trip.status != TripStatusEnum.INTERRUPTED:
        raise HTTPException(status_code=400, detail="Trip-ul original trebuie să fie INTERRUPTED")

    if incident.recovery_trip_id:
        raise HTTPException(status_code=400, detail="Acest incident are deja un recovery trip")

    if not incident.impact_analysis:
        raise HTTPException(status_code=400, detail="Impact analysis nu a fost generat")

    options = incident.impact_analysis.get("options", [])
    recommended_option = selected_option or next((opt for opt in options if opt.get("recommended")), None)

    if not recommended_option:
        raise HTTPException(status_code=400, detail="Nu există opțiune recomandată în impact analysis")
    if not recommended_option.get("feasible") or recommended_option.get("type") not in (
        "RECOVER_ALL_REMAINING", "RECOVER_PICKED_UP_ONLY"
    ):
        raise HTTPException(status_code=400, detail="Opțiunea selectată nu poate crea un recovery trip")

    try:
        driver_id = uuid.UUID(recommended_option["driver_id"])
        vehicle_id = uuid.UUID(recommended_option["vehicle_id"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Opțiunea recomandată conține driver_id sau vehicle_id invalid")
    planned_km = recommended_option["planned_km"]
    planned_duration_min = math.ceil(recommended_option["planned_duration_min"])
    route_stops = recommended_option["route"]
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == original_trip.company_id,
    ).first()
    if not vehicle:
        raise HTTPException(status_code=400, detail="Vehiculul de recuperare nu a fost găsit")

    recovery_trip = Trip(
        company_id=original_trip.company_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        planning_session_id=original_trip.planning_session_id,
        planned_date=original_trip.planned_date,
        status=TripStatusEnum.APPROVED,
        recovery_for_trip_id=original_trip.id,
        planned_km=planned_km,
        planned_duration_min=planned_duration_min,
        vehicle_plate_snapshot=vehicle.plate,
        vehicle_capacity_kg_snapshot=vehicle.capacity_kg,
        vehicle_capacity_m3_snapshot=vehicle.capacity_m3,
    )

    db.add(recovery_trip)
    db.flush()
    upsert_trip_cost(db, recovery_trip)

    real_sequence = 1
    for stop_data in route_stops:
        if stop_data.get("is_virtual"):
            continue
        order_id_str = stop_data["order_id"]
        stop_type = stop_data["stop_type"]
        sequence = real_sequence
        eta_seconds = stop_data["eta_seconds"]

        try:
            order_id = uuid.UUID(order_id_str)
        except (ValueError, TypeError):
            continue

        order = db.query(Order).filter(
            Order.id == order_id,
            Order.company_id == original_trip.company_id,
        ).first()
        if not order:
            continue

        eta_datetime = datetime.combine(
            original_trip.planned_date,
            datetime.min.time(),
            tzinfo=LOCAL_TZ,
        ) + timedelta(seconds=eta_seconds)

        recovery_stop = TripStop(
            trip_id=recovery_trip.id,
            order_id=order_id,
            sequence=sequence,
            stop_type=StopTypeEnum(stop_type),
            eta_planned=eta_datetime,
            status=StopStatusEnum.PENDING,
            notes=f"Recovery stop from incident {incident.id}",
            order_kg_snapshot=order.kg,
            order_m3_snapshot=order.m3,
        )
        db.add(recovery_stop)
        real_sequence += 1

    vehicle.status = VehicleStatusEnum.REZERVAT

    # FIX #5: hasattr check pentru CANCELLED
    terminal_statuses = [
        OrderStatusEnum.DELIVERED,
        OrderStatusEnum.FAILED,
    ]

    if hasattr(OrderStatusEnum, "CANCELLED"):
        terminal_statuses.append(OrderStatusEnum.CANCELLED)

    for order_id_str in {
        str(s["order_id"])
        for s in route_stops
        if not s.get("is_virtual")
    }:
        try:
            order_id = uuid.UUID(order_id_str)
            order = db.query(Order).filter(Order.id == order_id).first()
            if order and order.status not in terminal_statuses:
                real_stop_types = {
                    s.get("stop_type")
                    for s in route_stops
                    if not s.get("is_virtual") and s.get("order_id") == order_id_str
                }
                order.status = (
                    OrderStatusEnum.IN_DELIVERY
                    if "DELIVERY" in real_stop_types and "PICKUP" not in real_stop_types
                    else OrderStatusEnum.PLANNED
                )
                order.assigned_delivery_date = original_trip.planned_date
        except (ValueError, TypeError):
            continue

    incident.recovery_trip_id = recovery_trip.id
    incident.resolved_at = datetime.now(timezone.utc)
    incident.extra_cost_estimated = recommended_option["estimated_total_cost"]

    db.commit()
    db.refresh(recovery_trip)

    return recovery_trip
def build_recover_all_remaining_analysis(db: Session, incident: Incident) -> dict:
    return _build_route_recovery_analysis(db, incident, "RECOVER_ALL_REMAINING")
def create_recover_all_remaining_trip(db: Session, incident: Incident) -> Trip:
    return create_recovery_trip(db, incident)
