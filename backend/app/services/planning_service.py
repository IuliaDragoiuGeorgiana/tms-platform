"""
Serviciul principal de planificare — Pickup & Delivery.
Orchestrează pipeline-ul: geocodare → clustering → PDP → salvare în DB.
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from time import perf_counter
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatusEnum
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.models.driver import Driver, DriverStatusEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_stop import TripStop, StopStatusEnum, StopTypeEnum
from app.models.planning_session import PlanningSession, PlanningStrategyEnum, PlanningStatusEnum
from app.models.company import Company
from app.services.ors_service import geocode, geocode_with_components, get_distance_matrix
from app.services.clustering_service import calculate_num_clusters, cluster_orders
from app.services.vrp_service import solve_pdp_for_cluster
from app.services.service_time_service import ensure_order_service_times
from app.services.order_feasibility_service import check_order_operational_warnings
from app.services.load_compatibility_service import check_load_compatibility_warnings
from app.services.strategy_service import distribute_orders_by_strategy
from app.services.trip_cost_service import upsert_trip_cost
from zoneinfo import ZoneInfo
from sqlalchemy import or_

LOCAL_TZ = ZoneInfo("Europe/Bucharest")
DEFAULT_BREAK_MINUTES = 30
DEFAULT_TRAVEL_BUFFER_MINUTES = 30
DEFAULT_WAITING_BUFFER_MINUTES = 15
PDP_SOLVER_MAX_TIME_SECONDS = 2
PDP_SOLVER_DRY_RUN_MAX_TIME_SECONDS = 1
PLANNING_POOL_STATUSES = (
    OrderStatusEnum.PENDING,
    OrderStatusEnum.FAILED,
)

_pdp_solver_cache: dict[tuple, dict | None] = {}



def time_to_seconds(t) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second

def priority_rank(order: Order) -> int:
    priority = order.priority.value if hasattr(order.priority, "value") else str(order.priority)
    return {"CRITIC": 0, "URGENT": 1, "NORMAL": 2}.get(priority, 2)


def _build_order_address_for_geocoding(order: Order, address_type: str) -> str:
    """
    Construiește o adresă structurată pentru geocodare din comenză.

    În câmpurile modelului, `county` înseamnă județ (ex: Timiș, Hunedoara),
    iar țara rămâne fixată la Romania pentru ORS.

    Prioritate:
    1. Dacă sunt componente structurate, le folosește (mai precis)
    2. Altfel, folosește textul adresei libere

    address_type: "pickup" sau "delivery"
    """
    if address_type == "pickup":
        parts = [
            order.pickup_street,
            order.pickup_number,
            order.pickup_city,
            order.pickup_county,
        ]
        fallback = order.address_pickup
    else:
        parts = [
            order.delivery_street,
            order.delivery_number,
            order.delivery_city,
            order.delivery_county,
        ]
        fallback = order.address_delivery

    clean_parts = [str(p).strip() for p in parts if p and str(p).strip()]

    if clean_parts:
        clean_parts.append("Romania")
        return ", ".join(clean_parts)

    return fallback


def _build_company_depot_address(company: Company) -> str | None:
    """
    Construiește adresa textuală a garajului companiei pentru geocodare.
    Format: street number, city, county/județ, Romania
    """
    address_parts = [
        company.depot_street,
        company.depot_number,
        company.depot_city,
        company.depot_county,
    ]

    clean_parts = [
        str(part).strip()
        for part in address_parts
        if part and str(part).strip()
    ]

    if not clean_parts:
        return None

    clean_parts.append("Romania")

    return ", ".join(clean_parts)


def _ensure_company_depot_coords(db: Session, company: Company) -> tuple[float, float]:
    """
    Returnează coordonatele garajului companiei.

    Dacă depot_lat/depot_lon există, le folosește.
    Dacă lipsesc, încearcă să geocodeze adresa garajului și salvează coordonatele.
    """
    if company.depot_lat is not None and company.depot_lon is not None:
        return float(company.depot_lat), float(company.depot_lon)

    depot_address = _build_company_depot_address(company)

    if not depot_address:
        raise ValueError(
            "Compania nu are adresa garajului configurată. "
            "Trebuie completate cel puțin: oraș și județ."
        )

    result = geocode(depot_address)

    if not result:
        raise ValueError(
            f"Adresa garajului companiei nu a putut fi geocodată: {depot_address}. "
            "Verificați dacă adresa este corectă."
        )

    company.depot_lat = result["lat"]
    company.depot_lon = result["lon"]

    db.flush()

    return float(company.depot_lat), float(company.depot_lon)


def _time_to_minutes(value) -> int:
    """
    Transformă un obiect time în minute de la 00:00.
    """
    return value.hour * 60 + value.minute


def _driver_available_minutes(driver) -> int:
    """
    Calculează câte minute mai are disponibile un șofer într-o zi.

    Folosește:
    - shift_start / shift_end, dacă există;
    - altfel max_hours_day;
    - scade hours_driven_today;
    - scade o pauză estimativă.
    """
    if driver.shift_start and driver.shift_end:
        start_minutes = _time_to_minutes(driver.shift_start)
        end_minutes = _time_to_minutes(driver.shift_end)

        # Pentru ture care trec peste miezul nopții.
        if end_minutes < start_minutes:
            end_minutes += 24 * 60

        work_minutes = end_minutes - start_minutes
    else:
        work_minutes = int(float(driver.max_hours_day or 8) * 60)

    already_driven_minutes = int(float(driver.hours_driven_today or 0) * 60)

    available = (
        work_minutes
        - already_driven_minutes
        - DEFAULT_BREAK_MINUTES
    )

    return max(0, available)


def _get_existing_resource_usage(
    db: Session,
    company_id,
    planned_date: date,
    exclude_planning_session_id=None,
) -> dict:
    """
    Returneaza intervalele deja ocupate de curse existente pentru o zi.

    Sunt luate in calcul cursele care blocheaza operational resursele:
    PROPOSED, APPROVED si IN_PROGRESS.
    """
    query = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.planned_date == planned_date,
        Trip.status.in_([
            TripStatusEnum.PROPOSED,
            TripStatusEnum.APPROVED,
            TripStatusEnum.IN_PROGRESS,
        ]),
    )

    if exclude_planning_session_id:
        query = query.filter(Trip.planning_session_id != exclude_planning_session_id)

    usage = {
        "drivers": {},
        "vehicles": {},
        "driver_busy_minutes": {},
    }

    for trip in query.all():
        trip_start, trip_end = _get_trip_time_interval(trip)

        if not trip_start or not trip_end:
            continue

        start_seconds = (
            trip_start.hour * 3600
            + trip_start.minute * 60
            + trip_start.second
        )
        end_seconds = (
            trip_end.hour * 3600
            + trip_end.minute * 60
            + trip_end.second
        )

        if end_seconds <= start_seconds:
            end_seconds += 24 * 3600

        busy_minutes = max(0, int((end_seconds - start_seconds) / 60))
        interval = (start_seconds, end_seconds)

        if trip.driver_id:
            usage["drivers"].setdefault(trip.driver_id, []).append(interval)
            usage["driver_busy_minutes"][trip.driver_id] = (
                usage["driver_busy_minutes"].get(trip.driver_id, 0)
                + busy_minutes
            )

        if trip.vehicle_id:
            usage["vehicles"].setdefault(trip.vehicle_id, []).append(interval)

    return usage


def _interval_seconds_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _build_capacity_by_day_minutes(
    day_dates: list[date],
    drivers: list,
    existing_usage_by_day: dict[date, dict] | None = None,
) -> dict[date, int]:
    """
    Construieste capacitatea estimativa pe zi, in minute.

    Scade minutele deja ocupate de curse existente PROPOSED / APPROVED /
    IN_PROGRESS, ca o planificare noua sa nu trateze aceiasi soferi ca liberi.
    """
    existing_usage_by_day = existing_usage_by_day or {}

    return {
        day: sum(
            max(
                0,
                _driver_available_minutes(driver)
                - existing_usage_by_day
                .get(day, {})
                .get("driver_busy_minutes", {})
                .get(driver.id, 0),
            )
            for driver in drivers
        )
        for day in day_dates
    }


def _build_estimated_minutes_by_order(
    db: Session,
    orders: list[Order],
) -> dict[str, int]:
    """
    Estimează câte minute consumă fiecare comandă la distribuirea pe zile.

    Include:
    - pickup_service_minutes;
    - delivery_service_minutes;
    - buffer estimativ de drum;
    - buffer estimativ de așteptare.

    Atenție:
    Aceasta este doar estimare pentru strategy_service.
    Durata reală se calculează mai târziu cu ORS + OR-Tools.
    """
    result = {}

    for order in orders:
        ensure_order_service_times(db, order)

        pickup_service = int(order.pickup_service_minutes or 0)
        delivery_service = int(order.delivery_service_minutes or 0)

        estimated_minutes = (
            pickup_service
            + delivery_service
            + DEFAULT_TRAVEL_BUFFER_MINUTES
            + DEFAULT_WAITING_BUFFER_MINUTES
        )

        result[str(order.id)] = estimated_minutes

    return result


def calculate_peak_loads(
    route: list[int],
    kg_demands: list[int],
    volume_demands: list[int],
) -> tuple[int, int]:
    current_kg = 0
    current_volume = 0
    peak_kg = 0
    peak_volume = 0

    for node_idx in route:
        current_kg += kg_demands[node_idx]
        current_volume += volume_demands[node_idx]
        peak_kg = max(peak_kg, current_kg)
        peak_volume = max(peak_volume, current_volume)

    return peak_kg, peak_volume


def _rebalance_clusters_by_workload(
    clusters: dict,
    max_iterations: int = 10,
    tolerance_percent: float = 20.0,
) -> dict:
    """
    Rebalansează clusterele după workload estimat pentru a evita cazuri de tip 1+10.

    Strategie:
    1. Calculează workload per cluster
    2. Dacă coeficientul de variație e mare (> tolerance_percent), mut comenzi
    3. Mut comenzile ușoare din clusterele mari în clusterele mici
    4. Repetă până când clusterele sunt echilibrate sau atingem max_iterations

    Args:
        clusters: dict {cluster_idx: [orders]}
        max_iterations: câte iterații de rebalansare
        tolerance_percent: prag de dezechilibru acceptabil (%)

    Returnează: clusters rebalansat
    """
    if len(clusters) <= 1:
        return clusters

    rebalanced = {k: list(v) for k, v in clusters.items()}

    for iteration in range(max_iterations):
        workloads = {}
        for cluster_idx, cluster_orders_list in rebalanced.items():
            workloads[cluster_idx] = _estimate_cluster_workload_minutes(cluster_orders_list)

        # Calculează metrici de dezechilibru
        min_workload = min(workloads.values())
        max_workload = max(workloads.values())
        avg_workload = sum(workloads.values()) / len(workloads)

        if avg_workload == 0:
            break

        coefficient_variation = ((max_workload - min_workload) / avg_workload) * 100

        if coefficient_variation < tolerance_percent:
            break

        # Găsește clusterul cu cel mai mult workload
        max_cluster_idx = max(workloads, key=workloads.get)
        min_cluster_idx = min(workloads, key=workloads.get)

        max_cluster_orders = rebalanced[max_cluster_idx]

        if len(max_cluster_orders) <= 1:
            break

        # Alege comanda cu cel mai mic workload din clusterul mare
        orders_with_workload = [
            (order, _estimate_cluster_workload_minutes([order]))
            for order in max_cluster_orders
        ]
        orders_with_workload.sort(key=lambda x: x[1])
        order_to_move, _ = orders_with_workload[0]

        # Mută comanda din clusterul mare în clusterul mic
        rebalanced[max_cluster_idx].remove(order_to_move)
        rebalanced[min_cluster_idx].append(order_to_move)

    return rebalanced


def _split_large_clusters(
    clusters: dict,
    max_orders_per_cluster: int = 4,
) -> dict:
    """
    Sparge clusterele prea mari în bucăți mai mici.

    Strategie simplă:
    - parcurge fiecare cluster;
    - dacă are >max_orders_per_cluster, sparge în sub-clustere;
    - sub-clusterele sunt ordonate crescător (păstrează aproximativ ordonarea).

    Exemplu cu 11 comenzi și max=4:
    - cluster inițial: 11 comenzi → sparte în: 4, 4, 3 ordine
    """
    if not clusters:
        return clusters

    new_clusters = {}
    new_idx = 0

    for _, cluster_orders in clusters.items():
        # Dacă clusterul e mic, păstrează-l
        if len(cluster_orders) <= max_orders_per_cluster:
            new_clusters[new_idx] = list(cluster_orders)
            new_idx += 1
        else:
            # Sparte clusterul mare în bucăți
            for i in range(0, len(cluster_orders), max_orders_per_cluster):
                chunk = cluster_orders[i:i + max_orders_per_cluster]
                if chunk:
                    new_clusters[new_idx] = chunk
                    new_idx += 1

    return new_clusters


def _estimate_cluster_workload_minutes(cluster_orders: list[Order]) -> int:
    """
    Estimează câte minute va consuma un cluster.

    Include:
    - pickup_service_minutes
    - delivery_service_minutes
    - buffer estimativ de drum
    - buffer estimativ de așteptare
    """
    total_minutes = 0

    for order in cluster_orders:
        pickup_service = int(order.pickup_service_minutes or 0)
        delivery_service = int(order.delivery_service_minutes or 0)
        estimated_minutes = (
            pickup_service
            + delivery_service
            + DEFAULT_TRAVEL_BUFFER_MINUTES
            + DEFAULT_WAITING_BUFFER_MINUTES
        )
        total_minutes += estimated_minutes

    return total_minutes


def _calculate_penalty(order: Order, planned_date: date) -> int:
    """
    Calculează penalizarea pentru scoaterea unei comenzi din plan.
    Penalizare mare = comanda e greu de scos.
    Folosită pentru a decide care comandă se scoate când niciun vehicul
    nu poate duce toate comenzile din cluster.
    """
    priority = order.priority.value if hasattr(order.priority, "value") else str(order.priority)
    base = {"CRITIC": 1000000, "URGENT": 500000, "NORMAL": 100000}
    base_penalty = base.get(priority, 100000)

    days_until = max(1, (order.delivery_deadline - planned_date).days)
    deadline_bonus = int(50000 / days_until)

    return base_penalty + deadline_bonus


def _build_solver_data(orders, db, depot_lat, depot_lon, depot_start_seconds=5 * 3600):
    """
    Construiește toate datele necesare pentru OR-Tools dintr-o listă de comenzi.
    Returnează un dict cu coords, pickups_deliveries, demands, volume_demands,
    time_windows, service_times.

    Args:
        depot_lat: latitudinea garajului
        depot_lon: longitudinea garajului
        depot_start_seconds: ora de start a depotului (implicit 05:00)
    """
    num_orders = len(orders)
    full_day_window = (0, 24 * 3600)
    depot_window = (depot_start_seconds, 24 * 3600)

    # Coordonate: depot + pickups + deliveries
    coords = [[depot_lon, depot_lat]]
    for order in orders:
        coords.append([float(order.pickup_lon), float(order.pickup_lat)])
    for order in orders:
        coords.append([float(order.delivery_lon), float(order.delivery_lat)])

    # Perechi pickup-delivery
    pickups_deliveries = []
    for i in range(num_orders):
        pickups_deliveries.append([i + 1, i + 1 + num_orders])

    # Demands kg
    demands = [0]
    for order in orders:
        demands.append(int(float(order.kg)))
    for order in orders:
        demands.append(-int(float(order.kg)))

    # Volume demands (scalate ×100)
    volume_demands = [0]
    for order in orders:
        volume_demands.append(int(float(order.m3) * 100))
    for order in orders:
        volume_demands.append(-int(float(order.m3) * 100))

    # Time windows + service times
    time_windows = [depot_window]
    service_times = [0]

    for order in orders:
        ensure_order_service_times(db, order)
        if order.pickup_time_window_start and order.pickup_time_window_end:
            time_windows.append((
                time_to_seconds(order.pickup_time_window_start),
                time_to_seconds(order.pickup_time_window_end),
            ))
        else:
            time_windows.append(full_day_window)
        service_times.append(int(order.pickup_service_minutes or 0) * 60)

    for order in orders:
        ensure_order_service_times(db, order)
        if order.delivery_time_window_start and order.delivery_time_window_end:
            time_windows.append((
                time_to_seconds(order.delivery_time_window_start),
                time_to_seconds(order.delivery_time_window_end),
            ))
        else:
            time_windows.append(full_day_window)
        service_times.append(int(order.delivery_service_minutes or 0) * 60)

    return {
        "coords": coords,
        "pickups_deliveries": pickups_deliveries,
        "demands": demands,
        "volume_demands": volume_demands,
        "time_windows": time_windows,
        "service_times": service_times,
        "num_orders": num_orders,
    }

def _calculate_day_num_clusters(
    day_orders: list[Order],
    vehicles: list[Vehicle],
    drivers: list[Driver],
) -> int:
    import math

    # Calculează clustering după capacitatea vehiculelor
    avg_capacity_kg = sum(float(v.capacity_kg) for v in vehicles) / len(vehicles)
    avg_capacity_m3 = sum(float(v.capacity_m3) for v in vehicles) / len(vehicles)

    total_kg = sum(float(o.kg) for o in day_orders)
    total_m3 = sum(float(o.m3) for o in day_orders)

    num_by_capacity = calculate_num_clusters(
        total_kg=total_kg,
        total_m3=total_m3,
        avg_vehicle_capacity_kg=avg_capacity_kg,
        avg_vehicle_capacity_m3=avg_capacity_m3,
        num_orders=len(day_orders),
    )

    # Calculează clustering după timpul disponibil al șoferilor
    total_estimated_minutes = sum(
        int(order.pickup_service_minutes or 0)
        + int(order.delivery_service_minutes or 0)
        + DEFAULT_TRAVEL_BUFFER_MINUTES
        + DEFAULT_WAITING_BUFFER_MINUTES
        for order in day_orders
    )

    max_driver_minutes = max(
        (_driver_available_minutes(driver) for driver in drivers),
        default=0,
    )

    if max_driver_minutes > 0:
        num_by_time = math.ceil(total_estimated_minutes / max_driver_minutes)
    else:
        num_by_time = len(day_orders)

    # Alegem maximul - clustering-ul care necesită mai multe split-uri
    num_clusters = max(num_by_capacity, num_by_time)

    # Limită de siguranță: nu putem avea mai multe clustere decât comenzi
    num_clusters = min(num_clusters, len(day_orders))
    num_clusters = max(1, num_clusters)

    return num_clusters


def _choose_driver_for_trip(
    drivers: list[Driver],
    driver_remaining_minutes: dict,
    trip_minutes: int,
):
    """
    Alege un șofer care are suficient timp disponibil pentru cursa curentă.

    Pentru această variantă:
    - folosim doar șoferii încă disponibili;
    - alegem șoferul cu cel mai mult timp rămas;
    - păstrăm comportamentul vechi: după folosire, șoferul este scos din available_drivers.
    """
    candidates = [
        driver
        for driver in drivers
        if driver_remaining_minutes.get(driver.id, 0) >= trip_minutes
    ]

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda driver: driver_remaining_minutes.get(driver.id, 0),
        reverse=True,
    )[0]


def _choose_driver_vehicle_pair_for_trip(
    drivers: list[Driver],
    driver_state: dict,
    vehicles: list[Vehicle],
    vehicle_state: dict,
    trip_minutes: int,
    route_start_seconds: int,
    route_end_seconds: int,
) -> tuple | None:
    """
    Alege o pereche (șofer, vehicul) care poate efectua cursa curentă.

    Validări:
    - șoferul are suficient timp disponibil;
    - vehiculul este disponibil;
    - șoferul și vehiculul sunt disponibile până la ora de start calculată de solver;
    - cursa se termină în ziua curentă (< 24 * 3600);
    - cursa se termină înainte de shift_end al șoferului.

    Întoarce (driver, vehicle, actual_start_seconds) sau None.
    """
    best_pair = None
    best_available_time = None

    for driver in drivers:
        driver_info = driver_state.get(driver.id)
        if not driver_info:
            continue

        remaining_min = driver_info.get("remaining_minutes", 0)
        if remaining_min < trip_minutes:
            continue

        driver_available_from = driver_info.get("available_from_seconds", 5 * 3600)

        # Verifica shift_end al șoferului
        driver_shift_end_seconds = 24 * 3600
        if driver.shift_end:
            driver_shift_end_seconds = time_to_seconds(driver.shift_end)
            if driver.shift_start:
                driver_shift_start_seconds = time_to_seconds(driver.shift_start)
                if driver_shift_end_seconds < driver_shift_start_seconds:
                    driver_shift_end_seconds += 24 * 3600

        for vehicle in vehicles:
            vehicle_info = vehicle_state.get(vehicle.id)
            if not vehicle_info:
                continue

            vehicle_available_from = vehicle_info.get("available_from_seconds", 5 * 3600)

            if driver_available_from > route_start_seconds:
                continue

            if vehicle_available_from > route_start_seconds:
                continue

            trip_end = route_end_seconds

            if trip_end > 24 * 3600:
                continue

            if trip_end > driver_shift_end_seconds:
                continue

            driver_busy_intervals = driver_info.get("busy_intervals", [])
            if any(
                _interval_seconds_overlap(route_start_seconds, trip_end, start, end)
                for start, end in driver_busy_intervals
            ):
                continue

            vehicle_busy_intervals = vehicle_info.get("busy_intervals", [])
            if any(
                _interval_seconds_overlap(route_start_seconds, trip_end, start, end)
                for start, end in vehicle_busy_intervals
            ):
                continue

            if best_pair is None or route_start_seconds < best_available_time:
                best_pair = (driver, vehicle, route_start_seconds)
                best_available_time = route_start_seconds

    return best_pair

def _plan_day(
    db: Session,
    day_orders: list[Order],
    vehicles: list[Vehicle],
    drivers: list[Driver],
    company_id,
    planned_date: date,
    planning_session_id,
    dry_run: bool,
    depot_lat: float,
    depot_lon: float,
    forced_num_clusters: int | None = None,
) -> dict:
    """
    Planifică O SINGURĂ ZI: clustering → ORS → OR-Tools → Trip-uri.

    Variantă stabilă:
    - păstrează logica veche de clustering;
    - păstrează logica veche de retry pe vehicule;
    - păstrează logica veche de dropped pe penalty;
    - adaugă verificarea timpului disponibil al șoferului;
    - NU face split dinamic / queue în interiorul funcției.
    """
    trips_created = []
    all_warnings = []
    all_operational_warnings = []
    all_load_compatibility_warnings = []
    dropped_orders_info = []
    day_started_at = perf_counter()
    performance_debug = {
        "planned_date": str(planned_date),
        "initial_orders": len(day_orders),
        "matrix_calls": 0,
        "matrix_cache_hits": 0,
        "matrix_fallbacks": 0,
        "matrix_elapsed_ms": 0.0,
        "solver_calls": 0,
        "solver_cache_hits": 0,
        "solver_elapsed_ms": 0.0,
        "retry_attempts": 0,
        "clusters": [],
    }

    available_vehicles = vehicles.copy()
    available_drivers = drivers.copy()
    existing_usage = _get_existing_resource_usage(
        db=db,
        company_id=company_id,
        planned_date=planned_date,
        exclude_planning_session_id=planning_session_id,
    )

    driver_state = {
        driver.id: {
            "driver": driver,
            "remaining_minutes": max(
                0,
                _driver_available_minutes(driver)
                - existing_usage["driver_busy_minutes"].get(driver.id, 0),
            ),
            "available_from_seconds": time_to_seconds(driver.shift_start)
            if driver.shift_start
            else 5 * 3600,
            "busy_intervals": list(existing_usage["drivers"].get(driver.id, [])),
        }
        for driver in drivers
    }

    vehicle_state = {
        vehicle.id: {
            "vehicle": vehicle,
            "available_from_seconds": 5 * 3600,
            "busy_intervals": list(existing_usage["vehicles"].get(vehicle.id, [])),
        }
        for vehicle in vehicles
    }

    # ---- CLUSTERING ----
    if forced_num_clusters is not None:
        num_clusters = forced_num_clusters
        num_clusters = min(num_clusters, len(day_orders))
        num_clusters = max(1, num_clusters)
    else:
        num_clusters = _calculate_day_num_clusters(
            day_orders=day_orders,
            vehicles=available_vehicles,
            drivers=available_drivers,
        )

    coords_for_clustering = []

    for order in day_orders:
        mid_lat = (float(order.pickup_lat) + float(order.delivery_lat)) / 2
        mid_lon = (float(order.pickup_lon) + float(order.delivery_lon)) / 2
        coords_for_clustering.append([mid_lat, mid_lon])

    cluster_labels = cluster_orders(coords_for_clustering, num_clusters)

    clusters = {}

    for i, label in enumerate(cluster_labels):
        if label not in clusters:
            clusters[label] = []

        clusters[label].append(day_orders[i])

    # ---- Rebalansare clustere după workload estimat ----
    # Rebalansează dacă avem >1 cluster (chiar 2 clustere pot fi dezechilibrate: 1+10)
    if len(clusters) > 1:
        clusters = _rebalance_clusters_by_workload(clusters, max_iterations=3, tolerance_percent=25.0)

    # ---- Split clustere prea mari ----
    # Ținem PDP-urile mici ca să evităm retry-uri lente pe combinații mari
    # de comenzi × vehicule × șoferi.
    clusters = _split_large_clusters(clusters, max_orders_per_cluster=4)

    # ---- Ordonare clustere după workload (procesează mai întâi clusterele mari) ----
    cluster_workloads = [
        (cluster_idx, _estimate_cluster_workload_minutes(cluster_orders_list))
        for cluster_idx, cluster_orders_list in clusters.items()
        if len(cluster_orders_list) > 0
    ]
    cluster_workloads.sort(key=lambda x: x[1], reverse=True)
    sorted_cluster_indices = [cluster_idx for cluster_idx, _ in cluster_workloads]

    cluster_debug = [
    {
        "cluster_idx": int(cluster_idx),
        "num_orders": len(clusters[cluster_idx]),
        "estimated_workload_minutes": _estimate_cluster_workload_minutes(clusters[cluster_idx]),
        "order_refs": [order.order_ref for order in clusters[cluster_idx]],
    }
    for cluster_idx in sorted_cluster_indices
    if len(clusters[cluster_idx]) > 0
]

    # ---- Pentru fiecare cluster → retry vehicule → retry comenzi → trip ----
    for cluster_idx in sorted_cluster_indices:
        cluster_orders_list = clusters[cluster_idx]
        cluster_started_at = perf_counter()
        cluster_performance = {
            "cluster_idx": int(cluster_idx),
            "initial_orders": len(cluster_orders_list),
            "retry_attempts": 0,
            "matrix_calls": 0,
            "matrix_cache_hits": 0,
            "matrix_fallbacks": 0,
            "matrix_elapsed_ms": 0.0,
            "solver_calls": 0,
            "solver_cache_hits": 0,
            "solver_elapsed_ms": 0.0,
            "vehicle_attempts": 0,
            "dropped_orders": 0,
            "final_orders": 0,
            "planned": False,
            "total_km": 0.0,
            "total_minutes": 0,
            "elapsed_ms": 0.0,
        }

        # Verificări operaționale
        for order in cluster_orders_list:
            ensure_order_service_times(db, order)

            order_warnings = check_order_operational_warnings(order)

            for warning in order_warnings:
                all_operational_warnings.append({
                    "order_id": str(order.id),
                    "order_ref": order.order_ref,
                    "type": "OPERATIONAL_WARNING",
                    "message": warning,
                    "severity": "WARNING",
                })

        if not available_drivers:
            for order in cluster_orders_list:
                dropped_orders_info.append({
                    "order_id": str(order.id),
                    "order_ref": order.order_ref,
                    "reason_code": "NO_DRIVER_AVAILABLE",
                    "reason": "Niciun șofer disponibil",
                    "priority": (
                        order.priority.value
                        if hasattr(order.priority, "value")
                        else str(order.priority)
                    ),
                    "delivery_deadline": str(order.delivery_deadline),
                })

            cluster_performance["dropped_orders"] = len(cluster_orders_list)
            cluster_performance["elapsed_ms"] = round(
                (perf_counter() - cluster_started_at) * 1000,
                2,
            )
            performance_debug["clusters"].append(cluster_performance)
            continue

        # ======================================================
        # RETRY COMPLET: vehicule mai mari → scoatere comenzi
        # ======================================================
        current_orders = cluster_orders_list.copy()
        solver_result = None
        matrix_result = None
        chosen_vehicle = None
        chosen_pair = None
        total_km = 0.0
        total_minutes = 0
        dropped_from_cluster = []

        while current_orders:
            performance_debug["retry_attempts"] += 1
            cluster_performance["retry_attempts"] += 1

            # Găsește vehiculele compatibile cu comenzile curente
            max_order_kg = max(float(order.kg) for order in current_orders)
            max_order_m3 = max(float(order.m3) for order in current_orders)

            compatible_vehicles = sorted(
                [
                    vehicle
                    for vehicle in available_vehicles
                    if float(vehicle.capacity_kg) >= max_order_kg
                    and float(vehicle.capacity_m3) >= max_order_m3
                ],
                key=lambda vehicle: (
                    float(vehicle.capacity_kg),
                    float(vehicle.capacity_m3),
                ),
            )

            if not compatible_vehicles:
                # Caută comenzile care nu încap individual în niciun vehicul disponibil.
                impossible_orders = []

                for order in current_orders:
                    fits_any_vehicle = any(
                        float(vehicle.capacity_kg) >= float(order.kg)
                        and float(vehicle.capacity_m3) >= float(order.m3)
                        for vehicle in available_vehicles
                    )

                    if not fits_any_vehicle:
                        impossible_orders.append(order)

                if impossible_orders:
                    removed_order = sorted(
                        impossible_orders,
                        key=lambda order: _calculate_penalty(order, planned_date),
                    )[0]
                else:
                    removed_order = sorted(
                        current_orders,
                        key=lambda order: _calculate_penalty(order, planned_date),
                    )[0]

                dropped_from_cluster.append({
                    "order": removed_order,
                    "reason_code": "VEHICLE_OR_ROUTE_INFEASIBLE",
                    "reason": "Niciun vehicul disponibil nu are capacitate suficientă",
                })
                current_orders.remove(removed_order)

                continue

            earliest_driver_start = min(
                (
                    driver_state[driver.id]["available_from_seconds"]
                    for driver in available_drivers
                    if driver.id in driver_state
                    and driver_state[driver.id].get("remaining_minutes", 0) > 0
                ),
                default=5 * 3600,
            )
            earliest_vehicle_start = min(
                (
                    vehicle_state[vehicle.id]["available_from_seconds"]
                    for vehicle in compatible_vehicles
                    if vehicle.id in vehicle_state
                ),
                default=5 * 3600,
            )
            depot_start_seconds = max(
                5 * 3600,
                earliest_driver_start,
                earliest_vehicle_start,
            )

            # Construiește datele solver
            solver_data = _build_solver_data(
                current_orders,
                db,
                depot_lat=depot_lat,
                depot_lon=depot_lon,
                depot_start_seconds=depot_start_seconds,
            )

            # Calculează matricea ORS
            matrix_started_at = perf_counter()
            retry_matrix = get_distance_matrix(solver_data["coords"])
            matrix_elapsed_ms = (perf_counter() - matrix_started_at) * 1000
            performance_debug["matrix_calls"] += 1
            performance_debug["matrix_elapsed_ms"] += matrix_elapsed_ms
            cluster_performance["matrix_calls"] += 1
            cluster_performance["matrix_elapsed_ms"] += matrix_elapsed_ms
            if retry_matrix and retry_matrix.get("cache_hit"):
                performance_debug["matrix_cache_hits"] += 1
                cluster_performance["matrix_cache_hits"] += 1
            if retry_matrix and retry_matrix.get("fallback"):
                performance_debug["matrix_fallbacks"] += 1
                cluster_performance["matrix_fallbacks"] += 1

            if not retry_matrix:
                for order in current_orders:
                    dropped_from_cluster.append({
                        "order": order,
                        "reason_code": "VEHICLE_OR_ROUTE_INFEASIBLE",
                        "reason": "Nu s-a putut calcula matricea de distanțe pentru cluster",
                    })

                current_orders = []
                break

            # Încearcă fiecare vehicul, de la mic la mare.
            # O soluție este acceptată doar dacă există și șofer care încape
            # în program. Dacă ruta merge, dar perechea șofer+vehicul nu,
            # continuăm cu următorul vehicul înainte să scoatem comenzi.
            found_solution = False
            route_found_without_driver = False

            for vehicle_candidate in compatible_vehicles:
                cluster_performance["vehicle_attempts"] += 1
                vehicle_capacity_kg = int(float(vehicle_candidate.capacity_kg))
                vehicle_capacity_m3 = int(float(vehicle_candidate.capacity_m3) * 100)
                solver_cache_key = (
                    tuple(
                        (
                            str(order.id),
                            round(float(order.pickup_lat), 6),
                            round(float(order.pickup_lon), 6),
                            round(float(order.delivery_lat), 6),
                            round(float(order.delivery_lon), 6),
                            int(float(order.kg)),
                            int(float(order.m3) * 100),
                            order.pickup_time_window_start.isoformat()
                            if order.pickup_time_window_start
                            else None,
                            order.pickup_time_window_end.isoformat()
                            if order.pickup_time_window_end
                            else None,
                            order.delivery_time_window_start.isoformat()
                            if order.delivery_time_window_start
                            else None,
                            order.delivery_time_window_end.isoformat()
                            if order.delivery_time_window_end
                            else None,
                            int(order.pickup_service_minutes or 0),
                            int(order.delivery_service_minutes or 0),
                        )
                        for order in current_orders
                    ),
                    vehicle_capacity_kg,
                    vehicle_capacity_m3,
                    depot_start_seconds,
                )

                if solver_cache_key in _pdp_solver_cache:
                    candidate_result = _pdp_solver_cache[solver_cache_key]
                    performance_debug["solver_cache_hits"] += 1
                    cluster_performance["solver_cache_hits"] += 1
                else:
                    performance_debug["solver_calls"] += 1
                    cluster_performance["solver_calls"] += 1
                    solver_started_at = perf_counter()
                    candidate_result = solve_pdp_for_cluster(
                        distance_matrix=retry_matrix["distances"],
                        duration_matrix=retry_matrix["durations"],
                        pickups_deliveries=solver_data["pickups_deliveries"],
                        demands=solver_data["demands"],
                        vehicle_capacity_kg=vehicle_capacity_kg,
                        volume_demands=solver_data["volume_demands"],
                        vehicle_capacity_m3=vehicle_capacity_m3,
                        time_windows=solver_data["time_windows"],
                        service_times=solver_data["service_times"],
                        max_time_seconds=(
                            PDP_SOLVER_DRY_RUN_MAX_TIME_SECONDS
                            if dry_run
                            else PDP_SOLVER_MAX_TIME_SECONDS
                        ),
                    )
                    _pdp_solver_cache[solver_cache_key] = candidate_result
                    solver_elapsed_ms = (perf_counter() - solver_started_at) * 1000
                    performance_debug["solver_elapsed_ms"] += solver_elapsed_ms
                    cluster_performance["solver_elapsed_ms"] += solver_elapsed_ms

                if not candidate_result:
                    continue

                route_found_without_driver = True
                optimized_route = candidate_result["route"]

                candidate_total_km = 0.0
                for i in range(len(optimized_route) - 1):
                    from_idx = optimized_route[i]
                    to_idx = optimized_route[i + 1]
                    candidate_total_km += retry_matrix["distances"][from_idx][to_idx] / 1000

                candidate_total_minutes = round(
                    candidate_result.get("total_duration_seconds", 0) / 60
                )

                candidate_pair = _choose_driver_vehicle_pair_for_trip(
                    drivers=available_drivers,
                    driver_state=driver_state,
                    vehicles=[vehicle_candidate],
                    vehicle_state=vehicle_state,
                    trip_minutes=candidate_total_minutes,
                    route_start_seconds=candidate_result.get("start_seconds", 0),
                    route_end_seconds=candidate_result.get("end_seconds", 0),
                )

                if candidate_pair:
                    solver_result = candidate_result
                    chosen_vehicle = vehicle_candidate
                    matrix_result = retry_matrix
                    total_km = candidate_total_km
                    total_minutes = candidate_total_minutes
                    chosen_pair = candidate_pair
                    found_solution = True
                    break

                # If a feasible route exists but no driver can fit its time range,
                # larger vehicles will not add driver time. Drop/retry orders now
                # instead of spending the solver time limit on every vehicle.
                break

            if found_solution:
                break

            if route_found_without_driver:
                # Rutele sunt fezabile cu cel puțin un vehicul, dar niciun șofer
                # nu are suficient timp pentru clusterul curent.
                if len(current_orders) <= 1:
                    for order in current_orders:
                        dropped_from_cluster.append({
                            "order": order,
                            "reason_code": "DRIVER_TIME_EXCEEDED",
                            "reason": (
                                "Niciun șofer disponibil nu are suficient timp rămas "
                                "pentru această cursă"
                            ),
                        })

                    current_orders = []
                    solver_result = None
                    break

                removed_order = sorted(
                    current_orders,
                    key=lambda order: _calculate_penalty(order, planned_date),
                )[0]

                dropped_from_cluster.append({
                    "order": removed_order,
                    "reason_code": "DRIVER_TIME_EXCEEDED",
                    "reason": (
                        "Comanda a fost scoasă pentru ca ruta să se încadreze "
                        "în timpul disponibil al șoferului"
                    ),
                })

                current_orders.remove(removed_order)

                # Reset pentru a reia while cu listă redusă
                solver_result = None
                matrix_result = None
                chosen_vehicle = None
                chosen_pair = None
                continue

            # Niciun vehicul nu a mers → scoatem comanda cu penalty minim
            if len(current_orders) <= 1:
                for order in current_orders:
                    dropped_from_cluster.append({
                        "order": order,
                        "reason_code": "VEHICLE_OR_ROUTE_INFEASIBLE",
                        "reason": "Nu s-a găsit vehicul care să poată plani această comandă",
                    })
                current_orders = []
                break

            penalties = [
                (_calculate_penalty(order, planned_date), i, order)
                for i, order in enumerate(current_orders)
            ]

            penalties.sort(key=lambda item: item[0])

            _, remove_idx, removed_order = penalties[0]

            dropped_from_cluster.append({
                "order": removed_order,
                "reason_code": "VEHICLE_OR_ROUTE_INFEASIBLE",
                "reason": "Comanda a fost scoasă pentru a permite planificarea celorlalte comenzi",
            })
            current_orders.pop(remove_idx)

        # Înregistrează comenzile scoase din motive diverse
        cluster_performance["dropped_orders"] = len(dropped_from_cluster)
        for item in dropped_from_cluster:
            order = item["order"]

            dropped_orders_info.append({
                "order_id": str(order.id),
                "order_ref": order.order_ref,
                "reason_code": item["reason_code"],
                "reason": item["reason"],
                "priority": (
                    order.priority.value
                    if hasattr(order.priority, "value")
                    else str(order.priority)
                ),
                "delivery_deadline": str(order.delivery_deadline),
            })

        # Dacă nu a rămas nicio comandă sau nu avem soluție, skip
        if not current_orders or not solver_result or not chosen_pair:
            cluster_performance["elapsed_ms"] = round(
                (perf_counter() - cluster_started_at) * 1000,
                2,
            )
            performance_debug["clusters"].append(cluster_performance)
            continue

        # Extrage metrici care au fost deja calculate în while
        optimized_route = solver_result["route"]
        solver_arrival_times = solver_result["arrival_times"]
        chosen_driver, chosen_vehicle, actual_start_seconds = chosen_pair

        driver_available_before_trip = driver_state[chosen_driver.id]["remaining_minutes"]
        trip_end_seconds = solver_result.get(
            "end_seconds",
            actual_start_seconds + total_minutes * 60,
        )

        driver_state[chosen_driver.id]["remaining_minutes"] -= total_minutes
        driver_state[chosen_driver.id]["available_from_seconds"] = trip_end_seconds
        driver_state[chosen_driver.id].setdefault("busy_intervals", []).append(
            (actual_start_seconds, trip_end_seconds)
        )

        vehicle_state[chosen_vehicle.id]["available_from_seconds"] = trip_end_seconds
        vehicle_state[chosen_vehicle.id].setdefault("busy_intervals", []).append(
            (actual_start_seconds, trip_end_seconds)
        )

        driver_available_after_trip = driver_state[chosen_driver.id]["remaining_minutes"]

        vehicle = chosen_vehicle
        driver = chosen_driver
        planned_cluster_orders = current_orders
        num_orders_in_cluster = len(planned_cluster_orders)
        cluster_performance["planned"] = True
        cluster_performance["final_orders"] = num_orders_in_cluster
        cluster_performance["total_km"] = round(total_km, 1)
        cluster_performance["total_minutes"] = round(total_minutes)

        # Reconstruim demands pentru peak load
        final_demands = [0]

        for order in planned_cluster_orders:
            final_demands.append(int(float(order.kg)))

        for order in planned_cluster_orders:
            final_demands.append(-int(float(order.kg)))

        final_volume_demands = [0]

        for order in planned_cluster_orders:
            final_volume_demands.append(int(float(order.m3) * 100))

        for order in planned_cluster_orders:
            final_volume_demands.append(-int(float(order.m3) * 100))

        peak_kg, peak_volume_scaled = calculate_peak_loads(
            route=optimized_route,
            kg_demands=final_demands,
            volume_demands=final_volume_demands,
        )

        peak_m3 = peak_volume_scaled / 100

        # ---- Creează Trip ----
        trip_id = None

        if not dry_run:
            trip = Trip(
                company_id=company_id,
                driver_id=driver.id,
                vehicle_id=vehicle.id,
                planning_session_id=planning_session_id,
                planned_date=planned_date,
                status=TripStatusEnum.PROPOSED,
                planned_km=round(total_km, 1),
                planned_duration_min=round(total_minutes),
                vehicle_plate_snapshot=vehicle.plate,
                vehicle_capacity_kg_snapshot=vehicle.capacity_kg,
                vehicle_capacity_m3_snapshot=vehicle.capacity_m3,
            )

            db.add(trip)
            db.flush()
            upsert_trip_cost(db, trip)

            trip_id = trip.id

        # Load compatibility warnings
        load_warnings = check_load_compatibility_warnings(
            cluster_orders=planned_cluster_orders,
            vehicle=vehicle,
            total_minutes=total_minutes,
            peak_kg=peak_kg,
            peak_m3=peak_m3,
        )

        for warning in load_warnings:
            warning["trip_id"] = str(trip_id) if trip_id else None
            warning["vehicle_plate"] = vehicle.plate
            warning["cluster_idx"] = cluster_idx
            all_load_compatibility_warnings.append(warning)

        # ---- Creează TripStops ----
        sequence = 1
        trip_stops_preview = []

        for route_idx in optimized_route:
            if route_idx == 0:
                continue

            if route_idx <= num_orders_in_cluster:
                order_idx = route_idx - 1
                stop_type = StopTypeEnum.PICKUP
            else:
                order_idx = route_idx - 1 - num_orders_in_cluster
                stop_type = StopTypeEnum.DELIVERY

            if order_idx >= num_orders_in_cluster:
                continue

            order = planned_cluster_orders[order_idx]

            eta = None

            if solver_arrival_times and route_idx in solver_arrival_times:
                arrival_seconds = solver_arrival_times[route_idx]

                eta = datetime(
                    planned_date.year,
                    planned_date.month,
                    planned_date.day,
                    tzinfo=LOCAL_TZ,
                ) + timedelta(seconds=arrival_seconds)

            if not dry_run:
                trip_stop = TripStop(
                    trip_id=trip.id,
                    order_id=order.id,
                    sequence=sequence,
                    stop_type=stop_type,
                    eta_planned=eta,
                    status=StopStatusEnum.PENDING,
                    order_kg_snapshot=order.kg,
                    order_m3_snapshot=order.m3,
                )

                db.add(trip_stop)

                if stop_type == StopTypeEnum.DELIVERY:
                    order.status = OrderStatusEnum.PLANNED
                    order.assigned_delivery_date = planned_date
                    order.was_postponed = False

            stop_type_value = (
                stop_type.value
                if hasattr(stop_type, "value")
                else str(stop_type)
            )

            trip_stops_preview.append({
                "sequence": sequence,
                "order_ref": order.order_ref,
                "order_id": str(order.id),
                "stop_type": stop_type_value,
                "address": (
                    order.address_pickup
                    if stop_type_value == "PICKUP"
                    else order.address_delivery
                ),
                "eta_planned": eta.isoformat() if eta else None,
                "kg": float(order.kg),
                "priority": (
                    order.priority.value
                    if hasattr(order.priority, "value")
                    else str(order.priority)
                ),
            })

            sequence += 1

        # ---- Time window warnings ----
        if solver_arrival_times:
            for i in range(num_orders_in_cluster):
                order = planned_cluster_orders[i]
                delivery_node_idx = i + 1 + num_orders_in_cluster

                if (
                    order.delivery_time_window_end
                    and delivery_node_idx in solver_arrival_times
                ):
                    arrival_sec = solver_arrival_times[delivery_node_idx]
                    window_end_sec = time_to_seconds(order.delivery_time_window_end)

                    if arrival_sec > window_end_sec:
                        delay_minutes = round((arrival_sec - window_end_sec) / 60)
                        eta_h = arrival_sec // 3600
                        eta_m = (arrival_sec % 3600) // 60

                        win_start_str = (
                            order.delivery_time_window_start.strftime("%H:%M")
                            if order.delivery_time_window_start
                            else "00:00"
                        )

                        win_end_str = order.delivery_time_window_end.strftime("%H:%M")

                        suggestion = None

                        if order.flexibility_days and order.flexibility_days > 0:
                            next_day = planned_date + timedelta(days=1)

                            if next_day <= order.delivery_deadline:
                                suggestion = (
                                    f"Comanda poate fi mutată pe {next_day.isoformat()}"
                                    f" (deadline: {order.delivery_deadline.isoformat()})"
                                )

                        severity = "CRITICAL" if delay_minutes > 60 else "WARNING"

                        all_warnings.append({
                            "order_id": str(order.id),
                            "order_ref": order.order_ref,
                            "trip_id": str(trip_id) if trip_id else None,
                            "address": order.address_delivery,
                            "stop_type": "DELIVERY",
                            "requested_window": f"{win_start_str} - {win_end_str}",
                            "eta_planned": f"{int(eta_h):02d}:{int(eta_m):02d}",
                            "delay_minutes": delay_minutes,
                            "severity": severity,
                            "suggestion": suggestion,
                        })

                pickup_node_idx = i + 1

                if (
                    order.pickup_time_window_end
                    and pickup_node_idx in solver_arrival_times
                ):
                    arrival_sec = solver_arrival_times[pickup_node_idx]
                    window_end_sec = time_to_seconds(order.pickup_time_window_end)

                    if arrival_sec > window_end_sec:
                        delay_minutes = round((arrival_sec - window_end_sec) / 60)
                        eta_h = arrival_sec // 3600
                        eta_m = (arrival_sec % 3600) // 60

                        pickup_start = (
                            order.pickup_time_window_start.strftime("%H:%M")
                            if order.pickup_time_window_start
                            else "00:00"
                        )

                        pickup_end = order.pickup_time_window_end.strftime("%H:%M")

                        all_warnings.append({
                            "order_id": str(order.id),
                            "order_ref": order.order_ref,
                            "trip_id": str(trip_id) if trip_id else None,
                            "address": order.address_pickup,
                            "stop_type": "PICKUP",
                            "requested_window": f"{pickup_start} - {pickup_end}",
                            "eta_planned": f"{int(eta_h):02d}:{int(eta_m):02d}",
                            "delay_minutes": delay_minutes,
                            "severity": "WARNING",
                            "suggestion": None,
                        })

        def format_time_from_seconds(seconds: int) -> str:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"

        trips_created.append({
            "trip_id": str(trip_id) if trip_id else None,
            "planned_date": str(planned_date),
            "driver": str(driver.user_id),
            "driver_name": driver.user.full_name if driver.user else None,
            "vehicle_plate": vehicle.plate,
            "num_stops": sequence - 1,
            "total_km": round(total_km, 1),
            "total_minutes": round(total_minutes),
            "driver_available_minutes_before_trip": driver_available_before_trip,
            "driver_remaining_minutes_after_trip": driver_available_after_trip,
            "driver_overtime_minutes": max(
                0,
                total_minutes - driver_available_before_trip,
            ),
            "actual_start_time": format_time_from_seconds(actual_start_seconds),
            "trip_end_time": format_time_from_seconds(trip_end_seconds),
            "peak_kg": peak_kg,
            "peak_m3": round(peak_m3, 2),
            "stops": trip_stops_preview,
        })

        cluster_performance["elapsed_ms"] = round(
            (perf_counter() - cluster_started_at) * 1000,
            2,
        )
        performance_debug["clusters"].append(cluster_performance)

    performance_debug["matrix_elapsed_ms"] = round(
        performance_debug["matrix_elapsed_ms"],
        2,
    )
    performance_debug["solver_elapsed_ms"] = round(
        performance_debug["solver_elapsed_ms"],
        2,
    )
    performance_debug["elapsed_ms"] = round(
        (perf_counter() - day_started_at) * 1000,
        2,
    )

    return {
        "used_num_clusters": num_clusters,
        "cluster_debug": cluster_debug,
        "trips": trips_created,
        "warnings": all_warnings,
        "operational_warnings": all_operational_warnings,
        "load_compatibility_warnings": all_load_compatibility_warnings,
        "dropped_orders": dropped_orders_info,
        "performance_debug": performance_debug,
    }

def _has_driver_time_exceeded(result: dict | None) -> bool:
    """
    Verifică dacă planul a eșuat din cauza timpului insuficient al șoferului.
    """
    if not result:
        return False

    return any(
        dropped.get("reason_code") == "DRIVER_TIME_EXCEEDED"
        for dropped in result.get("dropped_orders", [])
    )


def _is_plan_acceptable_for_driver_time(result: dict | None) -> bool:
    """
    Plan acceptabil pentru retry-ul pe șofer:
    - există rezultat;
    - nu există comenzi dropped;
    - nu există DRIVER_TIME_EXCEEDED;
    - niciun trip nu are overtime.
    """
    if not result:
        return False

    if result.get("dropped_orders"):
        return False

    if _has_driver_time_exceeded(result):
        return False

    for trip in result.get("trips", []):
        if trip.get("driver_overtime_minutes", 0) > 0:
            return False

    return True


def _score_plan_result(result: dict | None) -> tuple[int, int, int, int]:
    """
    Scor pentru alegerea celui mai bun rezultat dacă niciun plan nu este perfect.

    Mai mic = mai bun.
    Prioritate:
    1. cât mai puține comenzi dropped;
    2. cât mai puține time-window warnings;
    3. cât mai puține load warnings;
    4. cât mai puține trip-uri/clustere.
    """
    if not result:
        return (999999, 999999, 999999, 999999)

    return (
        len(result.get("dropped_orders", [])),
        len(result.get("warnings", [])),
        len(result.get("load_compatibility_warnings", [])),
        len(result.get("trips", [])),
    )

def _get_order_planning_window(order: Order) -> tuple[date, date]:
    """
    Returnează intervalul în care comanda poate fi planificată:
    [earliest_day, latest_day].

    latest_day = delivery_deadline
    earliest_day = delivery_deadline - flexibility_days,
    ajustat cu earliest_delivery_date dacă există.
    """
    flexibility_days = order.flexibility_days or 0

    earliest_day = order.delivery_deadline - timedelta(days=flexibility_days)

    if order.earliest_delivery_date:
        earliest_day = max(earliest_day, order.earliest_delivery_date)

    latest_day = order.delivery_deadline

    return earliest_day, latest_day


def _repair_deferred_distribution(
    distribution: dict,
    date_start: date,
    date_end: date,
    estimated_minutes_by_order: dict[str, int],
) -> dict:
    """
    Reintroduce comenzile deferred numai dacă mai există capacitate estimată.

    Păstrează invariantul distribuției: used_minutes nu poate depăși
    capacity_by_day_minutes pentru nicio zi din interval.
    """
    deferred_orders = distribution.get("deferred", [])

    if not deferred_orders:
        return distribution

    still_deferred = []

    for order in deferred_orders:
        earliest_day, latest_day = _get_order_planning_window(order)

        # Alegem ultima zi posibilă din intervalul selectat.
        first_day = max(earliest_day, date_start)
        last_day = min(latest_day, date_end)
        estimated_minutes = estimated_minutes_by_order.get(str(order.id))
        placed = False

        if estimated_minutes is not None and first_day <= last_day:
            retry_day = last_day
            while retry_day >= first_day:
                day_capacity = distribution["capacity_by_day_minutes"].get(retry_day, 0)
                used_minutes = distribution["used_minutes"].get(retry_day, 0)
                if used_minutes + estimated_minutes <= day_capacity:
                    distribution["days"].setdefault(retry_day, []).append(order)
                    distribution["used_minutes"][retry_day] = used_minutes + estimated_minutes
                    placed = True
                    break
                retry_day -= timedelta(days=1)

        if not placed:
            still_deferred.append(order)

    distribution["deferred"] = still_deferred

    return distribution


def _plan_day_with_driver_time_retry(
    db: Session,
    day_orders: list[Order],
    vehicles: list[Vehicle],
    drivers: list[Driver],
    company_id,
    planned_date: date,
    planning_session_id,
    dry_run: bool,
    depot_lat: float,
    depot_lon: float,
) -> dict:
    """
    Variantă simplificată și rapidă:
    - calculează o singură dată numărul de clustere (pe baza capacității + timpului);
    - rulează _plan_day o singură dată;
    - retry-ul pe timp se face LOCAL în _plan_day (scoate comenzi din cluster dacă nu încap);
    - NU face retry global pe numărul de clustere.

    Performanță: de la minute (11 iterații) la secunde (1 iterație).
    """
    for order in day_orders:
        ensure_order_service_times(db, order)

    num_clusters = _calculate_day_num_clusters(
        day_orders=day_orders,
        vehicles=vehicles,
        drivers=drivers,
    )

    return _plan_day(
        db=db,
        day_orders=day_orders,
        vehicles=vehicles,
        drivers=drivers,
        company_id=company_id,
        planned_date=planned_date,
        planning_session_id=planning_session_id,
        dry_run=dry_run,
        depot_lat=depot_lat,
        depot_lon=depot_lon,
        forced_num_clusters=num_clusters,
    )


def _get_trip_time_interval(trip: Trip) -> tuple:
    """
    Calculează intervalul estimat al unui trip.

    Folosește:
    - primul eta_planned din stopuri ca start;
    - planned_duration_min ca durată totală.

    Returnează:
    - trip_start (datetime | None)
    - trip_end (datetime | None)
    """
    stops = sorted(trip.stops, key=lambda stop: stop.sequence)

    first_eta = None

    for stop in stops:
        if stop.eta_planned:
            first_eta = stop.eta_planned
            break

    if not first_eta or not trip.planned_duration_min:
        return None, None

    trip_start = first_eta
    trip_end = first_eta + timedelta(minutes=int(trip.planned_duration_min))

    return trip_start, trip_end


def _check_trip_within_driver_shift(trip: Trip, driver: Driver) -> None:
    """
    Verifică dacă intervalul trip-ului se încadrează în programul șoferului.

    Dacă șoferul nu are shift definit, validarea se sare.
    """
    trip_start, trip_end = _get_trip_time_interval(trip)

    if not trip_start or not trip_end:
        return

    if not driver.shift_start or not driver.shift_end:
        return

    shift_start = datetime.combine(
        trip.planned_date,
        driver.shift_start,
        tzinfo=trip_start.tzinfo,
    )

    shift_end = datetime.combine(
        trip.planned_date,
        driver.shift_end,
        tzinfo=trip_start.tzinfo,
    )

    # Pentru ture care trec peste miezul nopții
    if shift_end <= shift_start:
        shift_end += timedelta(days=1)

    if trip_start < shift_start or trip_end > shift_end:
        raise ValueError(
            "Trip-ul nu se încadrează în programul de lucru al șoferului"
        )


def _intervals_overlap(start_a, end_a, start_b, end_b) -> bool:
    """
    Două intervale se suprapun dacă: start_a < end_b și start_b < end_a
    """
    return start_a < end_b and start_b < end_a


def _check_driver_trip_overlap(
    db: Session,
    trip: Trip,
    new_driver_id: uuid.UUID,
    company_id: uuid.UUID,
) -> None:
    """
    Verifică dacă șoferul are alt trip care se suprapune ca interval orar
    cu trip-ul curent.

    Verifica trip-uri în stare PROPOSED, APPROVED, IN_PROGRESS.
    """
    new_start, new_end = _get_trip_time_interval(trip)

    if not new_start or not new_end:
        return

    other_trips = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.driver_id == new_driver_id,
        Trip.id != trip.id,
        Trip.status.in_([
            TripStatusEnum.PROPOSED,
            TripStatusEnum.APPROVED,
            TripStatusEnum.IN_PROGRESS,
        ]),
    ).all()

    for other_trip in other_trips:
        other_start, other_end = _get_trip_time_interval(other_trip)

        if not other_start or not other_end:
            continue

        if _intervals_overlap(new_start, new_end, other_start, other_end):
            raise ValueError(
                "Șoferul are deja un alt trip care se suprapune cu acest interval orar"
            )


def change_trip_driver(
    db: Session,
    trip_id: uuid.UUID,
    new_driver_id: uuid.UUID,
    company_id: uuid.UUID,
) -> dict:
    """
    Schimbă șoferul pe un trip PROPOSED.

    Validări:
    - Trip-ul există și aparține companiei
    - Trip-ul este în stare PROPOSED
    - PlanningSession asociată este PROPOSED
    - Noul șofer există, e AVAILABLE, aparține aceleiași companii
    - Trip-ul se încadrează în programul șoferului
    - Șoferul nu are alt trip care se suprapune orar
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == company_id,
    ).first()

    if not trip:
        raise ValueError("Trip-ul nu a fost găsit")

    if trip.status != TripStatusEnum.PROPOSED:
        raise ValueError(
            f"Trip-ul nu este în stare PROPOSED. Status actual: {trip.status.value}"
        )

    if trip.planning_session_id:
        session = db.query(PlanningSession).filter(
            PlanningSession.id == trip.planning_session_id,
            PlanningSession.company_id == company_id,
        ).first()

        if session and session.status != PlanningStatusEnum.PROPOSED:
            raise ValueError(
                f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}"
            )

    new_driver = db.query(Driver).filter(
        Driver.id == new_driver_id,
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).first()

    if not new_driver:
        raise ValueError("Noul șofer nu a fost găsit sau nu este disponibil")

    _check_trip_within_driver_shift(trip, new_driver)

    _check_driver_trip_overlap(
        db=db,
        trip=trip,
        new_driver_id=new_driver_id,
        company_id=company_id,
    )

    old_driver_id = trip.driver_id
    trip.driver_id = new_driver_id

    db.commit()
    db.refresh(trip)

    return {
        "trip_id": str(trip.id),
        "old_driver_id": str(old_driver_id) if old_driver_id else None,
        "new_driver_id": str(new_driver_id),
        "planned_date": str(trip.planned_date),
        "message": "Șoferul trip-ului a fost schimbat cu succes",
    }


def _check_vehicle_capacity_for_trip(
    trip: Trip,
    vehicle: Vehicle,
) -> dict:
    """
    Validează dacă un vehicul poate duce toate comenzile unui trip
    pe baza încărcării dinamice pe ordinea stopurilor.

    Logica:
    - La fiecare PICKUP adaugă kg/m³
    - La fiecare DELIVERY scade kg/m³
    - Verifică că încărcătura nu depășește capacitatea în niciun moment
    - La final, verifică că vehiculul e gol (fiecare preluare are livrare)
    """
    current_kg = 0.0
    current_m3 = 0.0
    max_kg = 0.0
    max_m3 = 0.0

    stops = sorted(trip.stops, key=lambda s: s.sequence)
    picked_orders = set()

    for stop in stops:
        if not stop.order:
            continue

        order_kg = float(stop.order.kg)
        order_m3 = float(stop.order.m3)

        if stop.stop_type.value == "PICKUP":
            current_kg += order_kg
            current_m3 += order_m3
            picked_orders.add(stop.order.id)

        elif stop.stop_type.value == "DELIVERY":
            if stop.order.id not in picked_orders:
                raise ValueError(
                    f"Trip invalid: livrare înainte de preluare pentru comanda {stop.order.order_ref}"
                )

            current_kg -= order_kg
            current_m3 -= order_m3

        max_kg = max(max_kg, current_kg)
        max_m3 = max(max_m3, current_m3)

        if current_kg > float(vehicle.capacity_kg):
            raise ValueError(
                f"Vehiculul depășește capacitatea kg la stopul {stop.sequence}: "
                f"{current_kg:.2f} kg > {float(vehicle.capacity_kg)} kg"
            )

        if current_m3 > float(vehicle.capacity_m3):
            raise ValueError(
                f"Vehiculul depășește capacitatea m³ la stopul {stop.sequence}: "
                f"{current_m3:.2f} m³ > {float(vehicle.capacity_m3)} m³"
            )

    if abs(current_kg) > 0.001 or abs(current_m3) > 0.001:
        raise ValueError(
            "Trip invalid: la final există marfă în vehicul. "
            "Verifică dacă fiecare preluare are livrare."
        )

    return {
        "max_load_kg": round(max_kg, 2),
        "max_load_m3": round(max_m3, 2),
    }


def change_trip_vehicle(
    db: Session,
    trip_id: uuid.UUID,
    new_vehicle_id: uuid.UUID,
    company_id: uuid.UUID,
) -> dict:
    """
    Schimbă vehiculul pe un trip PROPOSED.

    Validări:
    - Trip-ul există și aparține companiei
    - Trip-ul este în stare PROPOSED
    - PlanningSession asociată este PROPOSED
    - Noul vehicul există, e DISPONIBIL, aparține aceleiași companii
    - Noul vehicul suportă încărcarea dinamică pe traseu (pickup → delivery)
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == company_id,
    ).first()

    if not trip:
        raise ValueError("Trip-ul nu a fost găsit")

    if trip.status != TripStatusEnum.PROPOSED:
        raise ValueError(f"Trip-ul nu este în stare PROPOSED. Status actual: {trip.status.value}")

    if trip.planning_session_id:
        session = db.query(PlanningSession).filter(
            PlanningSession.id == trip.planning_session_id,
            PlanningSession.company_id == company_id,
        ).first()

        if session and session.status != PlanningStatusEnum.PROPOSED:
            raise ValueError(
                f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}"
            )

    new_vehicle = db.query(Vehicle).filter(
        Vehicle.id == new_vehicle_id,
        Vehicle.company_id == company_id,
        Vehicle.status == VehicleStatusEnum.DISPONIBIL,
    ).first()

    if not new_vehicle:
        raise ValueError("Noul vehicul nu a fost găsit sau nu este disponibil")

    # Validează capacitate pe baza ordinii stopurilor
    capacity_check = _check_vehicle_capacity_for_trip(trip, new_vehicle)

    old_vehicle_id = trip.vehicle_id
    trip.vehicle_id = new_vehicle_id
    trip.capture_vehicle_snapshot(new_vehicle)
    upsert_trip_cost(db, trip)
    db.commit()
    db.refresh(trip)

    return {
        "trip_id": str(trip.id),
        "old_vehicle_id": str(old_vehicle_id) if old_vehicle_id else None,
        "new_vehicle_id": str(new_vehicle_id),
        "new_vehicle_plate": new_vehicle.plate,
        "planned_date": str(trip.planned_date),
        "max_load_kg": capacity_check["max_load_kg"],
        "max_load_m3": capacity_check["max_load_m3"],
        "vehicle_capacity_kg": float(new_vehicle.capacity_kg),
        "vehicle_capacity_m3": float(new_vehicle.capacity_m3),
        "message": "Vehiculul trip-ului a fost schimbat cu succes",
    }


def _get_trip_start_seconds(trip: Trip) -> int:
    """
    Returnează ora de start estimată a trip-ului, în secunde de la 00:00.

    Folosește primul eta_planned din stopuri.
    Dacă nu există ETA, folosește 05:00 ca fallback.
    """
    stops = sorted(trip.stops, key=lambda stop: stop.sequence)

    for stop in stops:
        if stop.eta_planned:
            return (
                stop.eta_planned.hour * 3600
                + stop.eta_planned.minute * 60
                + stop.eta_planned.second
            )

    return 5 * 3600


def _get_unique_orders_from_trip(trip: Trip) -> list[Order]:
    """
    Returnează comenzile unice dintr-un trip, în ordinea apariției primului stop.

    Deoarece fiecare comandă are două stopuri:
    - PICKUP
    - DELIVERY

    trebuie să evităm dublarea comenzilor.
    """
    result = []
    seen_order_ids = set()

    stops = sorted(trip.stops, key=lambda stop: stop.sequence)

    for stop in stops:
        if not stop.order:
            continue

        if stop.order.id in seen_order_ids:
            continue

        seen_order_ids.add(stop.order.id)
        result.append(stop.order)

    return result


def _validate_dynamic_load_on_route(
    trip: Trip,
    orders: list[Order],
    route: list[int],
) -> None:
    """
    Verifica dacă încărcarea dinamică pe noua rută nu depășește capacitatea.

    Logica:
    - La fiecare PICKUP adaugă kg/m³
    - La fiecare DELIVERY scade kg/m³
    - După fiecare stop, verifica că nu depășim capacitatea
    """
    vehicle = trip.vehicle

    if not vehicle:
        return

    current_kg = 0.0
    current_m3 = 0.0
    num_orders = len(orders)

    for route_idx in route:
        if route_idx == 0:
            continue

        if route_idx <= num_orders:
            order = orders[route_idx - 1]
            order_kg = float(order.kg)
            order_m3 = float(order.m3)

            current_kg += order_kg
            current_m3 += order_m3
        else:
            order = orders[route_idx - 1 - num_orders]
            current_kg -= float(order.kg)
            current_m3 -= float(order.m3)

        if current_kg > float(vehicle.capacity_kg):
            raise ValueError(
                f"Ruta reoptimizată depășește capacitate kg: "
                f"{current_kg:.2f} kg > {float(vehicle.capacity_kg)} kg"
            )

        if current_m3 > float(vehicle.capacity_m3):
            raise ValueError(
                f"Ruta reoptimizată depășește capacitate m³: "
                f"{current_m3:.2f} m³ > {float(vehicle.capacity_m3)} m³"
            )


def _validate_time_windows_on_route(
    orders: list[Order],
    solver_result: dict,
) -> None:
    """
    Verifica dacă ETA-urile noi respectă time windows-urile comenzilor.
    """
    arrival_times = solver_result.get("arrival_times", {})
    num_orders = len(orders)

    for i, order in enumerate(orders):
        pickup_idx = i + 1
        delivery_idx = i + 1 + num_orders

        if order.pickup_time_window_end and pickup_idx in arrival_times:
            arrival_sec = arrival_times[pickup_idx]
            window_end = time_to_seconds(order.pickup_time_window_end)

            if arrival_sec > window_end:
                raise ValueError(
                    f"Comanda {order.order_ref} nu se încadrează în pickup window: "
                    f"ETA {arrival_sec}s > window {window_end}s"
                )

        if order.delivery_time_window_end and delivery_idx in arrival_times:
            arrival_sec = arrival_times[delivery_idx]
            window_end = time_to_seconds(order.delivery_time_window_end)

            if arrival_sec > window_end:
                raise ValueError(
                    f"Comanda {order.order_ref} nu se încadrează în delivery window: "
                    f"ETA {arrival_sec}s > window {window_end}s"
                )


def _validate_reoptimized_trip(
    trip: Trip,
    orders: list[Order],
    solver_result: dict,
) -> None:
    """
    Validează dacă trip-ul reoptimizat respectă:
    - Programul șoferului (shift_start și shift_end)
    - Capacitatea dinamică pe noua rută
    - Time windows ale comenzilor
    """
    trip_start_seconds = solver_result.get("start_seconds", 5 * 3600)
    trip_end_seconds = solver_result.get(
        "end_seconds",
        trip_start_seconds + solver_result.get("total_duration_seconds", 0),
    )

    if trip.driver and trip.driver.shift_start and trip.driver.shift_end:
        shift_start_seconds = time_to_seconds(trip.driver.shift_start)
        shift_end_seconds = time_to_seconds(trip.driver.shift_end)

        # Pentru ture care trec peste miezul nopții
        if shift_end_seconds <= shift_start_seconds:
            shift_end_seconds += 24 * 3600

        # Ajustare dacă trip-ul trece peste miezul nopții
        if trip_end_seconds <= trip_start_seconds:
            trip_end_seconds += 24 * 3600

        if trip_start_seconds < shift_start_seconds or trip_end_seconds > shift_end_seconds:
            raise ValueError(
                "Ruta reoptimizată nu se încadrează în programul de lucru al șoferului"
            )

    _validate_dynamic_load_on_route(trip, orders, solver_result["route"])

    _validate_time_windows_on_route(orders, solver_result)


def _solve_orders_for_vehicle(
    db: Session,
    orders: list[Order],
    vehicle: Vehicle,
    depot_lat: float,
    depot_lon: float,
    depot_start_seconds: int,
) -> dict:
    """
    Rulează ORS + OR-Tools pentru o listă de comenzi și un vehicul fix.

    Folosit la:
    - reoptimizare după scoaterea unei comenzi din trip;
    - reoptimizare după adăugarea unei comenzi în trip.
    """
    solver_data = _build_solver_data(
        orders=orders,
        db=db,
        depot_lat=depot_lat,
        depot_lon=depot_lon,
        depot_start_seconds=depot_start_seconds,
    )

    matrix_result = get_distance_matrix(solver_data["coords"])

    if not matrix_result:
        raise ValueError("Nu s-a putut recalcula matricea de distanțe pentru trip")

    solver_result = solve_pdp_for_cluster(
        distance_matrix=matrix_result["distances"],
        duration_matrix=matrix_result["durations"],
        pickups_deliveries=solver_data["pickups_deliveries"],
        demands=solver_data["demands"],
        vehicle_capacity_kg=int(float(vehicle.capacity_kg)),
        volume_demands=solver_data["volume_demands"],
        vehicle_capacity_m3=int(float(vehicle.capacity_m3) * 100),
        time_windows=solver_data["time_windows"],
        service_times=solver_data["service_times"],
        max_time_seconds=2,
    )

    if not solver_result:
        raise ValueError(
            "Nu s-a găsit o rută fezabilă pentru combinația de comenzi. "
            "Cauze posibile: capacitate kg/m³ depășită, time windows incompatibile, "
            "durată prea mare pentru ziua respectivă, sau imposibilitate de rutare."
        )

    optimized_route = solver_result["route"]

    total_km = 0.0

    for i in range(len(optimized_route) - 1):
        from_idx = optimized_route[i]
        to_idx = optimized_route[i + 1]
        total_km += matrix_result["distances"][from_idx][to_idx] / 1000

    total_minutes = round(
        solver_result.get("total_duration_seconds", 0) / 60
    )

    return {
        "solver_data": solver_data,
        "matrix_result": matrix_result,
        "solver_result": solver_result,
        "total_km": round(total_km, 1),
        "total_minutes": round(total_minutes),
    }


def _reoptimize_trip_with_orders(
    db: Session,
    trip: Trip,
    orders: list[Order],
) -> dict:
    """
    Reoptimizează un trip existent folosind lista de comenzi primită.

    Face:
    - reconstruire solver data;
    - recalculare matrice distanță/durată;
    - rulare OR-Tools PDP;
    - ștergere stopuri vechi;
    - creare stopuri noi;
    - actualizare planned_km și planned_duration_min.
    """
    if not orders:
        raise ValueError("Nu există comenzi pentru reoptimizarea trip-ului")

    vehicle = trip.vehicle

    if not vehicle:
        raise ValueError("Trip-ul nu are vehicul asociat")

    company = db.query(Company).filter(Company.id == trip.company_id).first()

    if not company:
        raise ValueError("Compania nu a fost găsită")

    depot_lat, depot_lon = _ensure_company_depot_coords(db, company)

    # Păstrează ora de start a trip-ului existent, nu folosi mereu 05:00
    depot_start_seconds = _get_trip_start_seconds(trip)

    # Rulează ORS + OR-Tools pentru ordine
    route_result = _solve_orders_for_vehicle(
        db=db,
        orders=orders,
        vehicle=vehicle,
        depot_lat=depot_lat,
        depot_lon=depot_lon,
        depot_start_seconds=depot_start_seconds,
    )

    solver_result = route_result["solver_result"]
    optimized_route = solver_result["route"]
    solver_arrival_times = solver_result.get("arrival_times", {})
    total_km = route_result["total_km"]
    total_minutes = route_result["total_minutes"]

    # Validează că ruta reoptimizată respectă toate constrângerile
    _validate_reoptimized_trip(trip, orders, solver_result)

    old_stops = db.query(TripStop).filter(
        TripStop.trip_id == trip.id,
    ).all()

    for stop in old_stops:
        db.delete(stop)

    db.flush()

    sequence = 1
    num_orders = len(orders)
    new_stops_preview = []

    for route_idx in optimized_route:
        if route_idx == 0:
            continue

        if route_idx <= num_orders:
            order_idx = route_idx - 1
            stop_type = StopTypeEnum.PICKUP
        else:
            order_idx = route_idx - 1 - num_orders
            stop_type = StopTypeEnum.DELIVERY

        if order_idx >= num_orders:
            continue

        order = orders[order_idx]

        eta = None

        if solver_arrival_times and route_idx in solver_arrival_times:
            arrival_seconds = solver_arrival_times[route_idx]

            eta = datetime(
                trip.planned_date.year,
                trip.planned_date.month,
                trip.planned_date.day,
                tzinfo=LOCAL_TZ,
            ) + timedelta(seconds=arrival_seconds)

        trip_stop = TripStop(
            trip_id=trip.id,
            order_id=order.id,
            sequence=sequence,
            stop_type=stop_type,
            eta_planned=eta,
            status=StopStatusEnum.PENDING,
            order_kg_snapshot=order.kg,
            order_m3_snapshot=order.m3,
        )

        db.add(trip_stop)

        new_stops_preview.append({
            "sequence": sequence,
            "order_id": str(order.id),
            "order_ref": order.order_ref,
            "stop_type": stop_type.value,
            "eta_planned": eta.isoformat() if eta else None,
        })

        sequence += 1

    trip.planned_km = round(total_km, 1)
    trip.planned_duration_min = round(total_minutes)
    upsert_trip_cost(db, trip)

    return {
        "planned_km": trip.planned_km,
        "planned_duration_min": trip.planned_duration_min,
        "num_stops": sequence - 1,
        "stops": new_stops_preview,
    }


def remove_order_from_trip(
    db: Session,
    trip_id: uuid.UUID,
    order_id: uuid.UUID,
    company_id: uuid.UUID,
) -> dict:
    """
    Scoate o comandă dintr-un trip PROPOSED și reoptimizează ruta rămasă.

    Efecte:
    - comanda scoasă revine în PENDING;
    - assigned_delivery_date devine NULL;
    - stopurile trip-ului sunt regenerate;
    - planned_km și planned_duration_min sunt recalculate;
    - ETA-urile sunt recalculate;
    - dacă trip-ul rămâne fără comenzi, trip-ul este șters.
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == company_id,
    ).first()

    if not trip:
        raise ValueError("Trip-ul nu a fost găsit")

    if trip.status != TripStatusEnum.PROPOSED:
        raise ValueError(
            f"Trip-ul nu este în stare PROPOSED. Status actual: {trip.status.value}"
        )

    if trip.planning_session_id:
        session = db.query(PlanningSession).filter(
            PlanningSession.id == trip.planning_session_id,
            PlanningSession.company_id == company_id,
        ).first()

        if session and session.status != PlanningStatusEnum.PROPOSED:
            raise ValueError(
                f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}"
            )

    order_to_remove = db.query(Order).filter(
        Order.id == order_id,
        Order.company_id == company_id,
    ).first()

    if not order_to_remove:
        raise ValueError("Comanda nu a fost găsită")

    stops_for_order = db.query(TripStop).filter(
        TripStop.trip_id == trip_id,
        TripStop.order_id == order_id,
    ).all()

    if not stops_for_order:
        raise ValueError("Comanda nu există în acest trip")

    existing_orders = _get_unique_orders_from_trip(trip)

    remaining_orders = [
        order for order in existing_orders
        if order.id != order_id
    ]

    if not remaining_orders:
        old_trip_id = trip.id

        old_stops = db.query(TripStop).filter(
            TripStop.trip_id == trip.id,
        ).all()

        for stop in old_stops:
            db.delete(stop)

        order_to_remove.status = OrderStatusEnum.PENDING
        order_to_remove.assigned_delivery_date = None

        db.delete(trip)
        db.commit()

        return {
            "trip_id": str(old_trip_id),
            "removed_order_id": str(order_to_remove.id),
            "removed_order_ref": order_to_remove.order_ref,
            "removed_order_status": order_to_remove.status.value,
            "trip_deleted": True,
            "message": (
                "Comanda a fost scoasă din trip și a revenit în PENDING. "
                "Trip-ul a fost șters deoarece nu mai avea alte comenzi."
            ),
        }

    reoptimization_result = _reoptimize_trip_with_orders(
        db=db,
        trip=trip,
        orders=remaining_orders,
    )

    # Setează comanda scoasă în PENDING doar după reoptimizare reușită
    order_to_remove.status = OrderStatusEnum.PENDING
    order_to_remove.assigned_delivery_date = None

    db.commit()
    db.refresh(trip)

    return {
        "trip_id": str(trip.id),
        "removed_order_id": str(order_to_remove.id),
        "removed_order_ref": order_to_remove.order_ref,
        "removed_order_status": order_to_remove.status.value,
        "trip_deleted": False,
        "new_planned_km": float(trip.planned_km),
        "new_planned_duration_min": trip.planned_duration_min,
        "remaining_orders": len(remaining_orders),
        "remaining_stops": reoptimization_result["num_stops"],
        "stops": reoptimization_result["stops"],
        "message": (
            "Comanda a fost scoasă din trip, a revenit în PENDING, "
            "iar ruta rămasă a fost reoptimizată."
        ),
    }


def add_order_to_trip(
    db: Session,
    trip_id: uuid.UUID,
    order_id: uuid.UUID,
    company_id: uuid.UUID,
) -> dict:
    """
    Adaugă o comandă PENDING într-un trip PROPOSED și reoptimizează ruta.

    Păstrează:
    - același șofer;
    - același vehicul;
    - aceeași dată;
    - aceeași sesiune de planificare.

    Validări complete:
    - Trip și session PROPOSED;
    - Comanda PENDING și neproblematică;
    - Comanda nu e deja în trip;
    - Comanda eligibilă pentru data trip-ului;
    - Ruta cu noua comandă fezabilă.

    Dacă vreo validare eșuează, operația nu modifică nimic.
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == company_id,
    ).first()

    if not trip:
        raise ValueError("Trip-ul nu a fost găsit")

    if trip.status != TripStatusEnum.PROPOSED:
        raise ValueError(
            f"Trip-ul nu este în stare PROPOSED. Status actual: {trip.status.value}"
        )

    if trip.planning_session_id:
        session = db.query(PlanningSession).filter(
            PlanningSession.id == trip.planning_session_id,
            PlanningSession.company_id == company_id,
        ).first()

        if session and session.status != PlanningStatusEnum.PROPOSED:
            raise ValueError(
                f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}"
            )

    if not trip.vehicle:
        raise ValueError("Trip-ul nu are vehicul asociat")

    if not trip.driver:
        raise ValueError("Trip-ul nu are șofer asociat")

    order_to_add = db.query(Order).filter(
        Order.id == order_id,
        Order.company_id == company_id,
    ).first()

    if not order_to_add:
        raise ValueError("Comanda nu a fost găsită")

    if order_to_add.status not in PLANNING_POOL_STATUSES:
        raise ValueError(
            f"Comanda nu poate fi adăugată deoarece nu este PENDING sau FAILED. "
            f"Status actual: {order_to_add.status.value}"
        )

    if order_to_add.is_problematic:
        raise ValueError(
            "Comanda este marcată ca problematică și nu poate fi adăugată în trip"
        )

    existing_orders = _get_unique_orders_from_trip(trip)
    existing_order_ids = {order.id for order in existing_orders}

    if order_to_add.id in existing_order_ids:
        raise ValueError("Comanda există deja în acest trip")

    earliest_day, latest_day = _get_order_planning_window(order_to_add)

    if trip.planned_date < earliest_day or trip.planned_date > latest_day:
        raise ValueError(
            "Comanda nu este eligibilă pentru data acestui trip. "
            f"Data trip-ului: {trip.planned_date}. "
            f"Interval eligibil comandă: {earliest_day} - {latest_day}"
        )

    if order_to_add.pickup_lat is None or order_to_add.pickup_lon is None:
        pickup_address = _build_order_address_for_geocoding(order_to_add, "pickup")
        result = geocode_with_components(pickup_address)

        if not result:
            raise ValueError(
                "Comanda nu poate fi adăugată deoarece adresa de pickup nu a putut fi geocodată"
            )

        order_to_add.pickup_lat = result["lat"]
        order_to_add.pickup_lon = result["lon"]
        order_to_add.pickup_county = result.get("county") or order_to_add.pickup_county
        order_to_add.pickup_city = result.get("city") or order_to_add.pickup_city
        order_to_add.pickup_street = result.get("street") or order_to_add.pickup_street
        order_to_add.pickup_number = result.get("number") or order_to_add.pickup_number

    if order_to_add.delivery_lat is None or order_to_add.delivery_lon is None:
        delivery_address = _build_order_address_for_geocoding(order_to_add, "delivery")
        result = geocode_with_components(delivery_address)

        if not result:
            raise ValueError(
                "Comanda nu poate fi adăugată deoarece adresa de livrare nu a putut fi geocodată"
            )

        order_to_add.delivery_lat = result["lat"]
        order_to_add.delivery_lon = result["lon"]
        order_to_add.delivery_county = result.get("county") or order_to_add.delivery_county
        order_to_add.delivery_city = result.get("city") or order_to_add.delivery_city
        order_to_add.delivery_street = result.get("street") or order_to_add.delivery_street
        order_to_add.delivery_number = result.get("number") or order_to_add.delivery_number

    vehicle = trip.vehicle

    if float(order_to_add.kg) > float(vehicle.capacity_kg):
        raise ValueError(
            f"Comanda nu poate fi adăugată: greutatea comenzii "
            f"({float(order_to_add.kg):.2f} kg) depășește capacitatea vehiculului "
            f"({float(vehicle.capacity_kg):.2f} kg)"
        )

    if float(order_to_add.m3) > float(vehicle.capacity_m3):
        raise ValueError(
            f"Comanda nu poate fi adăugată: volumul comenzii "
            f"({float(order_to_add.m3):.2f} m³) depășește capacitatea vehiculului "
            f"({float(vehicle.capacity_m3):.2f} m³)"
        )

    updated_orders = existing_orders + [order_to_add]

    try:
        reoptimization_result = _reoptimize_trip_with_orders(
            db=db,
            trip=trip,
            orders=updated_orders,
        )

    except ValueError as e:
        raise ValueError(
            "Comanda nu poate fi adăugată în acest trip. "
            f"Motiv: {str(e)}"
        )

    try:
        _check_driver_trip_overlap(
            db=db,
            trip=trip,
            new_driver_id=trip.driver_id,
            company_id=company_id,
        )

    except ValueError as e:
        raise ValueError(
            "Comanda nu poate fi adăugată în acest trip. "
            f"Motiv: {str(e)}"
        )

    order_to_add.status = OrderStatusEnum.PLANNED
    order_to_add.assigned_delivery_date = trip.planned_date
    order_to_add.was_postponed = False

    db.commit()
    db.refresh(trip)

    return {
        "trip_id": str(trip.id),
        "added_order_id": str(order_to_add.id),
        "added_order_ref": order_to_add.order_ref,
        "added_order_status": order_to_add.status.value,
        "new_planned_km": float(trip.planned_km),
        "new_planned_duration_min": trip.planned_duration_min,
        "total_orders_in_trip": len(updated_orders),
        "total_stops": reoptimization_result["num_stops"],
        "stops": reoptimization_result["stops"],
        "message": (
            "Comanda a fost adăugată în trip, a fost marcată ca PLANNED, "
            "iar ruta a fost reoptimizată cu succes."
        ),
    }


def _get_route_interval_from_solver(
    planned_date: date,
    solver_result: dict,
) -> tuple:
    """
    Calculează intervalul real al rutei din rezultatul solverului,
    fără să depindă de TripStop-uri salvate în DB.

    Returnează (start_dt, end_dt) sau (None, None) dacă nu se poate calcula.
    """
    start_seconds = solver_result.get("start_seconds")
    end_seconds = solver_result.get("end_seconds")

    if start_seconds is None or end_seconds is None:
        return None, None

    start_dt = datetime(
        planned_date.year,
        planned_date.month,
        planned_date.day,
        tzinfo=LOCAL_TZ,
    ) + timedelta(seconds=start_seconds)

    end_dt = datetime(
        planned_date.year,
        planned_date.month,
        planned_date.day,
        tzinfo=LOCAL_TZ,
    ) + timedelta(seconds=end_seconds)

    return start_dt, end_dt


def _check_driver_interval_overlap(
    db: Session,
    driver_id: uuid.UUID,
    company_id: uuid.UUID,
    new_start,
    new_end,
    exclude_trip_id: uuid.UUID | None = None,
) -> None:
    """
    Verifică dacă șoferul are alt trip care se suprapune
    cu intervalul calculat pentru ad-hoc trip.

    Exclude trip-ul cu ID-ul dat (util pentru validare trip-ului creat).
    """
    if not new_start or not new_end:
        return

    query = db.query(Trip).filter(
        Trip.company_id == company_id,
        Trip.driver_id == driver_id,
        Trip.status.in_([
            TripStatusEnum.PROPOSED,
            TripStatusEnum.APPROVED,
            TripStatusEnum.IN_PROGRESS,
        ]),
    )

    if exclude_trip_id:
        query = query.filter(Trip.id != exclude_trip_id)

    other_trips = query.all()

    for other_trip in other_trips:
        other_start, other_end = _get_trip_time_interval(other_trip)

        if not other_start or not other_end:
            continue

        if _intervals_overlap(new_start, new_end, other_start, other_end):
            raise ValueError(
                "Șoferul are deja un alt trip care se suprapune cu acest interval orar"
            )


def create_ad_hoc_trip(
    db: Session,
    session_id: uuid.UUID,
    company_id: uuid.UUID,
    planned_date: date,
    driver_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    dry_run: bool = False,
) -> dict:
    """
    Creează un trip nou ad-hoc într-o sesiune de planificare PROPOSED.

    Validări:
    - sesiunea există și este PROPOSED;
    - data trip-ului este în intervalul sesiunii;
    - șoferul există, aparține companiei și este AVAILABLE;
    - vehiculul există, aparține companiei și este DISPONIBIL;
    - comenzile există, aparțin companiei, sunt PENDING și neproblematice;
    - comenzile sunt eligibile pentru data trip-ului;
    - comenzile au coordonate sau pot fi geocodate;
    - fiecare comandă încape individual în vehicul;
    - ruta este fezabilă cu OR-Tools;
    - ruta respectă time windows, capacitate dinamică și programul șoferului;
    - șoferul nu are alt trip suprapus.
    """
    if not order_ids:
        raise ValueError("Trebuie selectată cel puțin o comandă")

    unique_order_ids = list(dict.fromkeys(order_ids))

    if len(unique_order_ids) != len(order_ids):
        raise ValueError("Lista de comenzi conține duplicate")

    session = db.query(PlanningSession).filter(
        PlanningSession.id == session_id,
        PlanningSession.company_id == company_id,
    ).first()

    if not session:
        raise ValueError("Sesiunea de planificare nu a fost găsită")

    if session.status != PlanningStatusEnum.PROPOSED:
        raise ValueError(
            f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}"
        )

    if planned_date < session.date_range_start or planned_date > session.date_range_end:
        raise ValueError(
            "Data trip-ului nu este în intervalul sesiunii de planificare. "
            f"Interval sesiune: {session.date_range_start} - {session.date_range_end}"
        )

    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).first()

    if not driver:
        driver_check = db.query(Driver).filter(
            Driver.id == driver_id,
            Driver.company_id == company_id,
        ).first()

        if not driver_check:
            raise ValueError(f"Șoferul cu ID {driver_id} nu a fost găsit în compania ta")
        else:
            raise ValueError(
                f"Șoferul {driver_check.user.full_name if driver_check.user else 'N/A'} "
                f"nu este disponibil. Status: {driver_check.status.value if hasattr(driver_check.status, 'value') else str(driver_check.status)}"
            )

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == company_id,
        Vehicle.status == VehicleStatusEnum.DISPONIBIL,
    ).first()

    if not vehicle:
        vehicle_check = db.query(Vehicle).filter(
            Vehicle.id == vehicle_id,
            Vehicle.company_id == company_id,
        ).first()

        if not vehicle_check:
            raise ValueError(f"Vehiculul cu ID {vehicle_id} nu a fost găsit în compania ta")
        else:
            raise ValueError(
                f"Vehiculul {vehicle_check.plate} nu este disponibil. "
                f"Status: {vehicle_check.status.value if hasattr(vehicle_check.status, 'value') else str(vehicle_check.status)}"
            )

    orders = db.query(Order).filter(
        Order.id.in_(unique_order_ids),
        Order.company_id == company_id,
    ).all()

    orders_by_id = {order.id: order for order in orders}

    if len(orders) != len(unique_order_ids):
        raise ValueError("Una sau mai multe comenzi nu au fost găsite")

    ordered_orders = []

    for order_id in unique_order_ids:
        order = orders_by_id.get(order_id)

        if not order:
            raise ValueError("Una sau mai multe comenzi nu au fost găsite")

        if order.status != OrderStatusEnum.PENDING:
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi adăugată deoarece nu este PENDING. "
                f"Status actual: {order.status.value}"
            )

        if order.is_problematic:
            raise ValueError(
                f"Comanda {order.order_ref} este marcată ca problematică și nu poate fi planificată"
            )

        earliest_day, latest_day = _get_order_planning_window(order)

        if planned_date < earliest_day or planned_date > latest_day:
            raise ValueError(
                f"Comanda {order.order_ref} nu este eligibilă pentru data trip-ului. "
                f"Data trip-ului: {planned_date}. "
                f"Interval eligibil comandă: {earliest_day} - {latest_day}"
            )

        if order.pickup_lat is None or order.pickup_lon is None:
            pickup_address = _build_order_address_for_geocoding(order, "pickup")
            result = geocode_with_components(pickup_address)

            if not result:
                raise ValueError(
                    f"Comanda {order.order_ref} nu poate fi planificată deoarece "
                    "adresa de pickup nu a putut fi geocodată"
                )

            order.pickup_lat = result["lat"]
            order.pickup_lon = result["lon"]
            order.pickup_county = result.get("county") or order.pickup_county
            order.pickup_city = result.get("city") or order.pickup_city
            order.pickup_street = result.get("street") or order.pickup_street
            order.pickup_number = result.get("number") or order.pickup_number

        if order.delivery_lat is None or order.delivery_lon is None:
            delivery_address = _build_order_address_for_geocoding(order, "delivery")
            result = geocode_with_components(delivery_address)

            if not result:
                raise ValueError(
                    f"Comanda {order.order_ref} nu poate fi planificată deoarece "
                    "adresa de livrare nu a putut fi geocodată"
                )

            order.delivery_lat = result["lat"]
            order.delivery_lon = result["lon"]
            order.delivery_county = result.get("county") or order.delivery_county
            order.delivery_city = result.get("city") or order.delivery_city
            order.delivery_street = result.get("street") or order.delivery_street
            order.delivery_number = result.get("number") or order.delivery_number

        if float(order.kg) > float(vehicle.capacity_kg):
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi planificată: greutatea "
                f"({float(order.kg):.2f} kg) depășește capacitatea vehiculului "
                f"({float(vehicle.capacity_kg):.2f} kg)"
            )

        if float(order.m3) > float(vehicle.capacity_m3):
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi planificată: volumul "
                f"({float(order.m3):.2f} m³) depășește capacitatea vehiculului "
                f"({float(vehicle.capacity_m3):.2f} m³)"
            )

        ensure_order_service_times(db, order)
        ordered_orders.append(order)

    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise ValueError("Compania nu a fost găsită")

    depot_lat, depot_lon = _ensure_company_depot_coords(db, company)

    depot_start_seconds = time_to_seconds(driver.shift_start) if driver.shift_start else 5 * 3600

    try:
        route_result = _solve_orders_for_vehicle(
            db=db,
            orders=ordered_orders,
            vehicle=vehicle,
            depot_lat=depot_lat,
            depot_lon=depot_lon,
            depot_start_seconds=depot_start_seconds,
        )

    except ValueError as e:
        raise ValueError(
            "Trip-ul ad-hoc nu poate fi creat. "
            f"Motiv: {str(e)}"
        )

    solver_result = route_result["solver_result"]
    optimized_route = solver_result["route"]
    solver_arrival_times = solver_result.get("arrival_times", {})
    total_km = route_result["total_km"]
    total_minutes = route_result["total_minutes"]

    trip = Trip(
        company_id=company_id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        planning_session_id=session.id,
        planned_date=planned_date,
        status=TripStatusEnum.PROPOSED,
        planned_km=round(total_km, 1),
        planned_duration_min=round(total_minutes),
        vehicle_plate_snapshot=vehicle.plate,
        vehicle_capacity_kg_snapshot=vehicle.capacity_kg,
        vehicle_capacity_m3_snapshot=vehicle.capacity_m3,
    )

    if not dry_run:
        db.add(trip)
        db.flush()
        upsert_trip_cost(db, trip)

    sequence = 1
    num_orders = len(ordered_orders)
    stops_preview = []

    for route_idx in optimized_route:
        if route_idx == 0:
            continue

        if route_idx <= num_orders:
            order_idx = route_idx - 1
            stop_type = StopTypeEnum.PICKUP
        else:
            order_idx = route_idx - 1 - num_orders
            stop_type = StopTypeEnum.DELIVERY

        if order_idx >= num_orders:
            continue

        order = ordered_orders[order_idx]

        eta = None

        if solver_arrival_times and route_idx in solver_arrival_times:
            arrival_seconds = solver_arrival_times[route_idx]

            eta = datetime(
                planned_date.year,
                planned_date.month,
                planned_date.day,
                tzinfo=LOCAL_TZ,
            ) + timedelta(seconds=arrival_seconds)

        if not dry_run:
            trip_stop = TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=stop_type,
                eta_planned=eta,
                status=StopStatusEnum.PENDING,
                order_kg_snapshot=order.kg,
                order_m3_snapshot=order.m3,
            )

            db.add(trip_stop)

        stops_preview.append({
            "sequence": sequence,
            "order_id": str(order.id),
            "order_ref": order.order_ref,
            "stop_type": stop_type.value,
            "eta_planned": eta.isoformat() if eta else None,
        })

        sequence += 1

    if not dry_run:
        db.flush()
        db.expire(trip, ["stops"])

    try:
        trip.driver = driver
        trip.vehicle = vehicle

        _validate_reoptimized_trip(
            trip=trip,
            orders=ordered_orders,
            solver_result=solver_result,
        )

        route_start, route_end = _get_route_interval_from_solver(
            planned_date=planned_date,
            solver_result=solver_result,
        )

        _check_driver_interval_overlap(
            db=db,
            driver_id=driver.id,
            company_id=company_id,
            new_start=route_start,
            new_end=route_end,
            exclude_trip_id=trip.id if not dry_run else None,
        )

    except ValueError as e:
        raise ValueError(
            "Trip-ul ad-hoc nu poate fi creat. "
            f"Motiv: {str(e)}"
        )

    if not dry_run:
        for order in ordered_orders:
            order.status = OrderStatusEnum.PLANNED
            order.assigned_delivery_date = planned_date
            order.was_postponed = False

        db.commit()
        db.refresh(trip)

    final_demands = [0]
    for order in ordered_orders:
        final_demands.append(int(float(order.kg)))
    for order in ordered_orders:
        final_demands.append(-int(float(order.kg)))

    final_volume_demands = [0]
    for order in ordered_orders:
        final_volume_demands.append(int(float(order.m3) * 100))
    for order in ordered_orders:
        final_volume_demands.append(-int(float(order.m3) * 100))

    peak_kg, peak_volume_scaled = calculate_peak_loads(
        route=optimized_route,
        kg_demands=final_demands,
        volume_demands=final_volume_demands,
    )
    peak_m3 = peak_volume_scaled / 100

    driver_available_minutes = _driver_available_minutes(driver)
    driver_remaining_after = max(0, driver_available_minutes - total_minutes)
    driver_overtime = max(0, total_minutes - driver_available_minutes)

    def format_time_from_seconds(seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    trip_start_seconds = solver_result.get("start_seconds", 5 * 3600)
    trip_end_seconds = solver_result.get("end_seconds", trip_start_seconds + total_minutes * 60)

    # Colectează warnings
    warnings = []

    # Warning: capacitate vehicul aproape de limită
    vehicle_capacity_kg = float(vehicle.capacity_kg)
    vehicle_capacity_m3 = float(vehicle.capacity_m3)

    if vehicle_capacity_kg > 0:
        kg_utilization = (peak_kg / vehicle_capacity_kg) * 100
        if kg_utilization > 85:
            warnings.append({
                "type": "VEHICLE_CAPACITY_WARNING",
                "severity": "WARNING",
                "message": f"Vehiculul este utilizat la {kg_utilization:.1f}% din capacitate kg (limită: 85%)",
            })

    if vehicle_capacity_m3 > 0:
        m3_utilization = (peak_m3 / vehicle_capacity_m3) * 100
        if m3_utilization > 85:
            warnings.append({
                "type": "VEHICLE_VOLUME_WARNING",
                "severity": "WARNING",
                "message": f"Vehiculul este utilizat la {m3_utilization:.1f}% din capacitate m³ (limită: 85%)",
            })

    # Warning: durata cursei aproape de limita șoferului
    if driver_available_minutes > 0:
        time_utilization = (total_minutes / driver_available_minutes) * 100
        if time_utilization > 90:
            warnings.append({
                "type": "DRIVER_TIME_WARNING",
                "severity": "WARNING",
                "message": f"Cursa utilizează {time_utilization:.1f}% din timpul disponibil al șoferului",
            })

    # Warning: marfă cu risc operațional
    for order in ordered_orders:
        type_marfa = order.type_marfa.value if hasattr(order.type_marfa, "value") else str(order.type_marfa)

        if type_marfa in ["FRAGIL", "ADR", "PERISABIL"]:
            warnings.append({
                "type": "CARGO_RISK_WARNING",
                "severity": "WARNING",
                "order_ref": order.order_ref,
                "message": f"Comanda {order.order_ref} conține marfă {type_marfa} cu risc operațional",
            })

    # Warning: ETA aproape de finalul ferestrei orare
    num_orders = len(ordered_orders)
    for i in range(num_orders):
        order = ordered_orders[i]
        delivery_node_idx = i + 1 + num_orders

        if (
            order.delivery_time_window_end
            and delivery_node_idx in solver_arrival_times
        ):
            arrival_sec = solver_arrival_times[delivery_node_idx]
            window_end_sec = time_to_seconds(order.delivery_time_window_end)

            if arrival_sec < window_end_sec:
                minutes_until_window_end = (window_end_sec - arrival_sec) / 60

                if minutes_until_window_end < 15:
                    eta_h = arrival_sec // 3600
                    eta_m = (arrival_sec % 3600) // 60
                    win_end_str = order.delivery_time_window_end.strftime("%H:%M")

                    warnings.append({
                        "type": "TIME_WINDOW_WARNING",
                        "severity": "WARNING",
                        "order_ref": order.order_ref,
                        "message": (
                            f"Comanda {order.order_ref}: ETA {int(eta_h):02d}:{int(eta_m):02d} "
                            f"este la doar {int(minutes_until_window_end)} min de finalul ferestrei orare ({win_end_str})"
                        ),
                    })

    return {
        "trip_id": str(trip.id) if not dry_run else None,
        "planning_session_id": str(session.id),
        "planned_date": str(trip.planned_date),
        "status": trip.status.value,
        "driver_id": str(driver.id),
        "driver_name": driver.user.full_name if driver.user else None,
        "vehicle_id": str(vehicle.id),
        "vehicle_plate": vehicle.plate,
        "planned_km": round(float(trip.planned_km), 1),
        "planned_duration_min": int(trip.planned_duration_min),
        "total_orders": len(ordered_orders),
        "total_stops": len(stops_preview),
        "total_kg": round(sum(float(o.kg) for o in ordered_orders), 2),
        "total_m3": round(sum(float(o.m3) for o in ordered_orders), 2),
        "peak_kg": peak_kg,
        "peak_m3": round(peak_m3, 2),
        "driver_available_minutes_before": driver_available_minutes,
        "driver_remaining_minutes_after": driver_remaining_after,
        "driver_overtime_minutes": driver_overtime,
        "trip_start_time": format_time_from_seconds(trip_start_seconds),
        "trip_end_time": format_time_from_seconds(trip_end_seconds),
        "orders": [
            {
                "order_id": str(order.id),
                "order_ref": order.order_ref,
                "status": order.status.value if not dry_run else "PENDING",
                "kg": float(order.kg),
                "m3": float(order.m3),
            }
            for order in ordered_orders
        ],
        "stops": stops_preview,
        "warnings": warnings,
        "warnings_count": len(warnings),
        "message": "Trip-ul ad-hoc a fost creat cu succes ca PROPOSED." if not dry_run else "Previzualizare trip-ul ad-hoc.",
    }


def create_adhoc_planning_session(
    db: Session,
    company_id: uuid.UUID,
    created_by_id: uuid.UUID,
    planned_date: date,
    driver_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    dry_run: bool = False,
) -> dict:
    """
    Creează o nouă sesiune de planificare ad-hoc pentru o dată specifică.

    Dispecerul alege manual:
    - data trip-ului;
    - șoferul;
    - vehiculul;
    - una sau mai multe comenzi PENDING.

    Sistemul:
    - validează toate restricțiile (șofer, vehicul, capacitate, time windows, deadline);
    - geocodează comenzile dacă necesare;
    - calculează ruta optimă cu OR-Tools;
    - creează o nouă PlanningSession (PROPOSED) cu un Trip (PROPOSED) în ea;
    - marchează comenzile ca PLANNED (dacă dry_run=False).

    dry_run=True → validare și preview fără a salva în DB.
    dry_run=False → creează și salvează în DB.
    """
    if planned_date < date.today():
        raise ValueError("Nu poți planifica pentru o dată din trecut")

    if not order_ids:
        raise ValueError("Trebuie selectată cel puțin o comandă")

    unique_order_ids = list(dict.fromkeys(order_ids))
    if len(unique_order_ids) != len(order_ids):
        raise ValueError("Lista de comenzi conține duplicate")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise ValueError("Compania nu a fost găsită")

    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).first()

    if not driver:
        driver_check = db.query(Driver).filter(
            Driver.id == driver_id,
            Driver.company_id == company_id,
        ).first()

        if not driver_check:
            raise ValueError(f"Șoferul cu ID {driver_id} nu a fost găsit în compania ta")
        else:
            raise ValueError(
                f"Șoferul {driver_check.user.full_name if driver_check.user else 'N/A'} "
                f"nu este disponibil. Status: {driver_check.status.value if hasattr(driver_check.status, 'value') else str(driver_check.status)}"
            )

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == company_id,
        Vehicle.status == VehicleStatusEnum.DISPONIBIL,
    ).first()

    if not vehicle:
        vehicle_check = db.query(Vehicle).filter(
            Vehicle.id == vehicle_id,
            Vehicle.company_id == company_id,
        ).first()

        if not vehicle_check:
            raise ValueError(f"Vehiculul cu ID {vehicle_id} nu a fost găsit în compania ta")
        else:
            raise ValueError(
                f"Vehiculul {vehicle_check.plate} nu este disponibil. "
                f"Status: {vehicle_check.status.value if hasattr(vehicle_check.status, 'value') else str(vehicle_check.status)}"
            )

    orders = db.query(Order).filter(
        Order.id.in_(unique_order_ids),
        Order.company_id == company_id,
    ).all()

    orders_by_id = {order.id: order for order in orders}

    if len(orders) != len(unique_order_ids):
        raise ValueError("Una sau mai multe comenzi nu au fost găsite")

    ordered_orders = []

    for order_id in unique_order_ids:
        order = orders_by_id.get(order_id)

        if not order:
            raise ValueError("Una sau mai multe comenzi nu au fost găsite")

        if order.status != OrderStatusEnum.PENDING:
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi planificată deoarece nu este PENDING. "
                f"Status actual: {order.status.value}"
            )

        if order.is_problematic:
            raise ValueError(
                f"Comanda {order.order_ref} este marcată ca problematică și nu poate fi planificată"
            )

        earliest_day, latest_day = _get_order_planning_window(order)

        if planned_date < earliest_day or planned_date > latest_day:
            raise ValueError(
                f"Comanda {order.order_ref} nu este eligibilă pentru data {planned_date}. "
                f"Interval eligibil: {earliest_day} - {latest_day}"
            )

        if order.pickup_lat is None or order.pickup_lon is None:
            pickup_address = _build_order_address_for_geocoding(order, "pickup")
            result = geocode_with_components(pickup_address)

            if not result:
                raise ValueError(
                    f"Comanda {order.order_ref} nu poate fi planificată deoarece "
                    "adresa de pickup nu a putut fi geocodată"
                )

            order.pickup_lat = result["lat"]
            order.pickup_lon = result["lon"]
            order.pickup_county = result.get("county") or order.pickup_county
            order.pickup_city = result.get("city") or order.pickup_city
            order.pickup_street = result.get("street") or order.pickup_street
            order.pickup_number = result.get("number") or order.pickup_number

        if order.delivery_lat is None or order.delivery_lon is None:
            delivery_address = _build_order_address_for_geocoding(order, "delivery")
            result = geocode_with_components(delivery_address)

            if not result:
                raise ValueError(
                    f"Comanda {order.order_ref} nu poate fi planificată deoarece "
                    "adresa de livrare nu a putut fi geocodată"
                )

            order.delivery_lat = result["lat"]
            order.delivery_lon = result["lon"]
            order.delivery_county = result.get("county") or order.delivery_county
            order.delivery_city = result.get("city") or order.delivery_city
            order.delivery_street = result.get("street") or order.delivery_street
            order.delivery_number = result.get("number") or order.delivery_number

        if float(order.kg) > float(vehicle.capacity_kg):
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi planificată: greutatea "
                f"({float(order.kg):.2f} kg) depășește capacitatea vehiculului "
                f"({float(vehicle.capacity_kg):.2f} kg)"
            )

        if float(order.m3) > float(vehicle.capacity_m3):
            raise ValueError(
                f"Comanda {order.order_ref} nu poate fi planificată: volumul "
                f"({float(order.m3):.2f} m³) depășește capacitatea vehiculului "
                f"({float(vehicle.capacity_m3):.2f} m³)"
            )

        ensure_order_service_times(db, order)
        ordered_orders.append(order)

    depot_lat, depot_lon = _ensure_company_depot_coords(db, company)

    depot_start_seconds = time_to_seconds(driver.shift_start) if driver.shift_start else 5 * 3600

    try:
        route_result = _solve_orders_for_vehicle(
            db=db,
            orders=ordered_orders,
            vehicle=vehicle,
            depot_lat=depot_lat,
            depot_lon=depot_lon,
            depot_start_seconds=depot_start_seconds,
        )

    except ValueError as e:
        raise ValueError(
            "Trip-ul ad-hoc nu poate fi creat. "
            f"Motiv: {str(e)}"
        )

    solver_result = route_result["solver_result"]
    optimized_route = solver_result["route"]
    solver_arrival_times = solver_result.get("arrival_times", {})
    total_km = route_result["total_km"]
    total_minutes = route_result["total_minutes"]

    planning_session = None
    trip = None

    if not dry_run:
        planning_session = PlanningSession(
            company_id=company_id,
            created_by=created_by_id,
            date_range_start=planned_date,
            date_range_end=planned_date,
            strategy=PlanningStrategyEnum.AD_HOC,
            status=PlanningStatusEnum.PROPOSED,
            total_orders=len(ordered_orders),
        )
        db.add(planning_session)
        db.flush()

    trip = Trip(
        company_id=company_id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        planning_session_id=planning_session.id if not dry_run else None,
        planned_date=planned_date,
        status=TripStatusEnum.PROPOSED,
        planned_km=round(total_km, 1),
        planned_duration_min=round(total_minutes),
        vehicle_plate_snapshot=vehicle.plate,
        vehicle_capacity_kg_snapshot=vehicle.capacity_kg,
        vehicle_capacity_m3_snapshot=vehicle.capacity_m3,
    )

    if not dry_run:
        db.add(trip)
        db.flush()
        upsert_trip_cost(db, trip)

    sequence = 1
    num_orders = len(ordered_orders)
    stops_preview = []

    for route_idx in optimized_route:
        if route_idx == 0:
            continue

        if route_idx <= num_orders:
            order_idx = route_idx - 1
            stop_type = StopTypeEnum.PICKUP
        else:
            order_idx = route_idx - 1 - num_orders
            stop_type = StopTypeEnum.DELIVERY

        if order_idx >= num_orders:
            continue

        order = ordered_orders[order_idx]

        eta = None

        if solver_arrival_times and route_idx in solver_arrival_times:
            arrival_seconds = solver_arrival_times[route_idx]

            eta = datetime(
                planned_date.year,
                planned_date.month,
                planned_date.day,
                tzinfo=LOCAL_TZ,
            ) + timedelta(seconds=arrival_seconds)

        if not dry_run:
            trip_stop = TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=stop_type,
                eta_planned=eta,
                status=StopStatusEnum.PENDING,
                order_kg_snapshot=order.kg,
                order_m3_snapshot=order.m3,
            )

            db.add(trip_stop)

        stops_preview.append({
            "sequence": sequence,
            "order_id": str(order.id),
            "order_ref": order.order_ref,
            "stop_type": stop_type.value,
            "eta_planned": eta.isoformat() if eta else None,
        })

        sequence += 1

    if not dry_run:
        db.flush()
        db.expire(trip, ["stops"])

    try:
        trip.driver = driver
        trip.vehicle = vehicle

        _validate_reoptimized_trip(
            trip=trip,
            orders=ordered_orders,
            solver_result=solver_result,
        )

        route_start, route_end = _get_route_interval_from_solver(
            planned_date=planned_date,
            solver_result=solver_result,
        )

        _check_driver_interval_overlap(
            db=db,
            driver_id=driver.id,
            company_id=company_id,
            new_start=route_start,
            new_end=route_end,
            exclude_trip_id=trip.id if not dry_run else None,
        )

    except ValueError as e:
        raise ValueError(
            "Trip-ul ad-hoc nu poate fi creat. "
            f"Motiv: {str(e)}"
        )

    if not dry_run:
        for order in ordered_orders:
            order.status = OrderStatusEnum.PLANNED
            order.assigned_delivery_date = planned_date
            order.was_postponed = False

        db.commit()
        db.refresh(trip)

    final_demands = [0]
    for order in ordered_orders:
        final_demands.append(int(float(order.kg)))
    for order in ordered_orders:
        final_demands.append(-int(float(order.kg)))

    final_volume_demands = [0]
    for order in ordered_orders:
        final_volume_demands.append(int(float(order.m3) * 100))
    for order in ordered_orders:
        final_volume_demands.append(-int(float(order.m3) * 100))

    peak_kg, peak_volume_scaled = calculate_peak_loads(
        route=optimized_route,
        kg_demands=final_demands,
        volume_demands=final_volume_demands,
    )
    peak_m3 = peak_volume_scaled / 100

    driver_available_minutes = _driver_available_minutes(driver)
    driver_remaining_after = max(0, driver_available_minutes - total_minutes)
    driver_overtime = max(0, total_minutes - driver_available_minutes)

    def format_time_from_seconds(seconds: int) -> str:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    trip_start_seconds = solver_result.get("start_seconds", 5 * 3600)
    trip_end_seconds = solver_result.get("end_seconds", trip_start_seconds + total_minutes * 60)

    warnings = []

    vehicle_capacity_kg = float(vehicle.capacity_kg)
    vehicle_capacity_m3 = float(vehicle.capacity_m3)

    if vehicle_capacity_kg > 0:
        kg_utilization = (peak_kg / vehicle_capacity_kg) * 100
        if kg_utilization > 85:
            warnings.append({
                "type": "VEHICLE_CAPACITY_WARNING",
                "severity": "WARNING",
                "message": f"Vehiculul este utilizat la {kg_utilization:.1f}% din capacitate kg (limită: 85%)",
            })

    if vehicle_capacity_m3 > 0:
        m3_utilization = (peak_m3 / vehicle_capacity_m3) * 100
        if m3_utilization > 85:
            warnings.append({
                "type": "VEHICLE_VOLUME_WARNING",
                "severity": "WARNING",
                "message": f"Vehiculul este utilizat la {m3_utilization:.1f}% din capacitate m³ (limită: 85%)",
            })

    if driver_available_minutes > 0:
        time_utilization = (total_minutes / driver_available_minutes) * 100
        if time_utilization > 90:
            warnings.append({
                "type": "DRIVER_TIME_WARNING",
                "severity": "WARNING",
                "message": f"Cursa utilizează {time_utilization:.1f}% din timpul disponibil al șoferului",
            })

    for order in ordered_orders:
        type_marfa = order.type_marfa.value if hasattr(order.type_marfa, "value") else str(order.type_marfa)

        if type_marfa in ["FRAGIL", "ADR", "PERISABIL"]:
            warnings.append({
                "type": "CARGO_RISK_WARNING",
                "severity": "WARNING",
                "order_ref": order.order_ref,
                "message": f"Comanda {order.order_ref} conține marfă {type_marfa} cu risc operațional",
            })

    num_orders = len(ordered_orders)
    for i in range(num_orders):
        order = ordered_orders[i]
        delivery_node_idx = i + 1 + num_orders

        if (
            order.delivery_time_window_end
            and delivery_node_idx in solver_arrival_times
        ):
            arrival_sec = solver_arrival_times[delivery_node_idx]
            window_end_sec = time_to_seconds(order.delivery_time_window_end)

            if arrival_sec < window_end_sec:
                minutes_until_window_end = (window_end_sec - arrival_sec) / 60

                if minutes_until_window_end < 15:
                    eta_h = arrival_sec // 3600
                    eta_m = (arrival_sec % 3600) // 60
                    win_end_str = order.delivery_time_window_end.strftime("%H:%M")

                    warnings.append({
                        "type": "TIME_WINDOW_WARNING",
                        "severity": "WARNING",
                        "order_ref": order.order_ref,
                        "message": (
                            f"Comanda {order.order_ref}: ETA {int(eta_h):02d}:{int(eta_m):02d} "
                            f"este la doar {int(minutes_until_window_end)} min de finalul ferestrei orare ({win_end_str})"
                        ),
                    })

    return {
        "planning_session_id": str(planning_session.id) if not dry_run else None,
        "trip_id": str(trip.id) if not dry_run else None,
        "planned_date": str(planned_date),
        "status": "PROPOSED",
        "driver_id": str(driver.id),
        "driver_name": driver.user.full_name if driver.user else None,
        "vehicle_id": str(vehicle.id),
        "vehicle_plate": vehicle.plate,
        "planned_km": round(float(trip.planned_km), 1),
        "planned_duration_min": int(trip.planned_duration_min),
        "total_orders": len(ordered_orders),
        "total_stops": len(stops_preview),
        "total_kg": round(sum(float(o.kg) for o in ordered_orders), 2),
        "total_m3": round(sum(float(o.m3) for o in ordered_orders), 2),
        "peak_kg": peak_kg,
        "peak_m3": round(peak_m3, 2),
        "driver_available_minutes_before": driver_available_minutes,
        "driver_remaining_minutes_after": driver_remaining_after,
        "driver_overtime_minutes": driver_overtime,
        "trip_start_time": format_time_from_seconds(trip_start_seconds),
        "trip_end_time": format_time_from_seconds(trip_end_seconds),
        "orders": [
            {
                "order_id": str(order.id),
                "order_ref": order.order_ref,
                "status": order.status.value if not dry_run else "PENDING",
                "kg": float(order.kg),
                "m3": float(order.m3),
            }
            for order in ordered_orders
        ],
        "stops": stops_preview,
        "warnings": warnings,
        "warnings_count": len(warnings),
        "message": "Sesiune ad-hoc creată cu succes ca PROPOSED." if not dry_run else "Previzualizare sesiune ad-hoc.",
    }


def run_planning(
    db: Session,
    company_id: uuid.UUID,
    planned_date: date,
    created_by_id: uuid.UUID,
    strategy: PlanningStrategyEnum = PlanningStrategyEnum.GREEDY_DEADLINE,
    dry_run: bool = False,
    date_start: date | None = None,
    date_end: date | None = None,
) -> dict:
    """
    Pipeline complet de planificare Pickup & Delivery — cu suport multi-day.
    """
    planning_started_at = perf_counter()
    stage_started_at = perf_counter()
    debug_timings = {}

    if date_start is None:
        date_start = planned_date
    if date_end is None:
        date_end = planned_date

    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        return {"error": "Compania nu a fost găsită"}

    try:
        depot_lat, depot_lon = _ensure_company_depot_coords(db, company)
    except ValueError as e:
        return {"error": str(e)}

    debug_timings["company_depot_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    day_dates = []
    current_day = date_start
    while current_day <= date_end:
        day_dates.append(current_day)
        current_day += timedelta(days=1)

    # PAS 1: Comenzi eligibile
    stage_started_at = perf_counter()
    orders = db.query(Order).filter(
        Order.company_id == company_id,
        Order.status.in_(PLANNING_POOL_STATUSES),
        Order.is_problematic.is_(False),
    ).all()

    if not orders:
        return {"error": "Nu există comenzi PENDING sau FAILED pentru planificare"}

    eligible_orders = []
    for order in orders:
        flexibility_days = order.flexibility_days or 0
        order_earliest = order.delivery_deadline - timedelta(days=flexibility_days)
        if order.earliest_delivery_date:
            order_earliest = max(order_earliest, order.earliest_delivery_date)
        order_latest = order.delivery_deadline

        if order_earliest <= date_end and order_latest >= date_start:
            eligible_orders.append(order)

    if not eligible_orders:
        return {"error": "Nu există comenzi eligibile pentru intervalul selectat"}

    debug_timings["eligible_orders_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    # PAS 2: Geocodare (cache)
    stage_started_at = perf_counter()
    for order in eligible_orders:
        if order.pickup_lat is None or order.pickup_lon is None:
            pickup_address = _build_order_address_for_geocoding(order, "pickup")
            result = geocode_with_components(pickup_address)
            if result:
                order.pickup_lat = result["lat"]
                order.pickup_lon = result["lon"]
                order.pickup_county = result.get("county") or order.pickup_county
                order.pickup_city = result.get("city") or order.pickup_city
                order.pickup_street = result.get("street") or order.pickup_street
                order.pickup_number = result.get("number") or order.pickup_number
            else:
                print(f"Nu am putut geocoda pickup: {pickup_address}")

        if order.delivery_lat is None or order.delivery_lon is None:
            delivery_address = _build_order_address_for_geocoding(order, "delivery")
            result = geocode_with_components(delivery_address)
            if result:
                order.delivery_lat = result["lat"]
                order.delivery_lon = result["lon"]
                order.delivery_county = result.get("county") or order.delivery_county
                order.delivery_city = result.get("city") or order.delivery_city
                order.delivery_street = result.get("street") or order.delivery_street
                order.delivery_number = result.get("number") or order.delivery_number
            else:
                print(f"Nu am putut geocoda delivery: {delivery_address}")

    db.commit()

    debug_timings["geocoding_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    geocoded_orders = [
        o for o in eligible_orders
        if o.pickup_lat is not None and o.pickup_lon is not None
        and o.delivery_lat is not None and o.delivery_lon is not None
    ]

    if not geocoded_orders:
        return {"error": "Nicio comandă nu a putut fi geocodată complet"}

    geocoded_orders = sorted(
        geocoded_orders,
        key=lambda order: (
            0 if order.was_postponed else 1,
            priority_rank(order),
            order.delivery_deadline,
            order.created_at,
        ),
    )

    # PAS 3: Vehicule și driveri
    stage_started_at = perf_counter()
    vehicles = db.query(Vehicle).filter(
        Vehicle.company_id == company_id,
        Vehicle.status == VehicleStatusEnum.DISPONIBIL,
    ).all()

    drivers = db.query(Driver).filter(
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).all()

    if not vehicles:
        return {"error": "Nu există vehicule disponibile"}
    if not drivers:
        return {"error": "Nu există șoferi disponibili"}
    
    existing_usage_by_day = {
        day: _get_existing_resource_usage(
            db=db,
            company_id=company_id,
            planned_date=day,
        )
        for day in day_dates
    }

    capacity_by_day_minutes = _build_capacity_by_day_minutes(
        day_dates=day_dates,
        drivers=drivers,
        existing_usage_by_day=existing_usage_by_day,
    )

    estimated_minutes_by_order = _build_estimated_minutes_by_order(
        db=db,
        orders=geocoded_orders,
    )

    debug_timings["resources_and_estimates_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    # PAS 4: Distribuie pe zile
    stage_started_at = perf_counter()
    distribution = distribute_orders_by_strategy(
        orders=geocoded_orders,
        strategy=strategy,
        date_start=date_start,
        date_end=date_end,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )

    # PAS 4.5: Repair doar în limita capacității estimate rămase.
    distribution = _repair_deferred_distribution(
        distribution=distribution,
        date_start=date_start,
        date_end=date_end,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )

    debug_timings["distribution_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    # PAS 5: PlanningSession
    planning_session_id = None

    if not dry_run:
        planning_session = PlanningSession(
            company_id=company_id,
            created_by=created_by_id,
            date_range_start=date_start,
            date_range_end=date_end,
            strategy=strategy,
            status=PlanningStatusEnum.PROPOSED,
            total_orders=len(geocoded_orders),
        )
        db.add(planning_session)
        db.flush()
        planning_session_id = planning_session.id

    # PAS 6: Planifică fiecare zi
    all_trips = []
    all_warnings = []
    all_operational_warnings = []
    all_load_compatibility_warnings = []
    all_dropped_orders = []
    cluster_debug_by_day = []
    performance_debug_by_day = []
    stage_started_at = perf_counter()

    for day_date in sorted(distribution["days"].keys()):
        day_orders = distribution["days"][day_date]
        if not day_orders:
            continue

        day_result = _plan_day_with_driver_time_retry(
            db=db,
            day_orders=day_orders,
            vehicles=vehicles,
            drivers=drivers,
            company_id=company_id,
            planned_date=day_date,
            planning_session_id=planning_session_id,
            dry_run=dry_run,
            depot_lat=depot_lat,
            depot_lon=depot_lon,
        )

        cluster_debug_by_day.append({
            "planned_date": str(day_date),
            "used_num_clusters": day_result.get("used_num_clusters"),
            "cluster_debug": day_result.get("cluster_debug", []),
        })
        performance_debug_by_day.append(day_result.get("performance_debug", {}))

        all_trips.extend(day_result["trips"])
        all_warnings.extend(day_result["warnings"])
        all_operational_warnings.extend(day_result["operational_warnings"])
        all_load_compatibility_warnings.extend(day_result["load_compatibility_warnings"])
        all_dropped_orders.extend(day_result["dropped_orders"])

    debug_timings["plan_days_ms"] = round(
        (perf_counter() - stage_started_at) * 1000,
        2,
    )

    for order in distribution.get("deferred", []):
        all_dropped_orders.append({
            "order_id": str(order.id),
            "order_ref": order.order_ref,
            "reason_code": "DEFERRED_CAPACITY_OR_INTERVAL",
            "reason": "Comanda nu încape în capacitatea estimată din interval",
            "priority": (
                order.priority.value
                if hasattr(order.priority, "value")
                else str(order.priority)
            ),
            "delivery_deadline": str(order.delivery_deadline),
        })

    # PAS 7: Finalizare
    orders_delayed = len(set(w["order_id"] for w in all_warnings))
    total_planned = sum(
        1 for t in all_trips for s in t["stops"] if s["stop_type"] == "DELIVERY"
    )
    orders_on_time = total_planned - orders_delayed

    if all_dropped_orders:
        feasibility = "PARTIAL"
    elif orders_delayed > 0:
        feasibility = "FEASIBLE_WITH_WARNINGS"
    else:
        feasibility = "FEASIBLE"

    if not dry_run:
        planning_session.optimization_stats = {
            "feasibility": feasibility,
            "total_orders": len(geocoded_orders),
            "total_planned": total_planned,
            "orders_on_time": orders_on_time,
            "orders_delayed": orders_delayed,
            "orders_dropped": len(all_dropped_orders),
            "warnings": all_warnings,
            "operational_warnings": all_operational_warnings,
            "load_compatibility_warnings": all_load_compatibility_warnings,
        }
        db.commit()

    debug_timings["total_elapsed_ms"] = round(
        (perf_counter() - planning_started_at) * 1000,
        2,
    )

    return {
        "planning_session_id": str(planning_session_id) if planning_session_id else None,
        "strategy": strategy.value if hasattr(strategy, "value") else str(strategy),
        "date_start": str(date_start),
        "date_end": str(date_end),
        "dry_run": dry_run,
        "total_orders": len(geocoded_orders),
        "total_planned": total_planned,
        "total_dropped": len(all_dropped_orders),
        "total_trips": len(all_trips),
        "total_km": round(sum(t["total_km"] for t in all_trips), 1),
        "total_minutes": round(sum(t["total_minutes"] for t in all_trips)),
        "trips": all_trips,
        "feasibility": feasibility,
        "orders_on_time": orders_on_time,
        "delayed_orders_count": orders_delayed,
        "warnings_count": len(all_warnings),
        "warnings": all_warnings,
        "operational_warnings_count": len(all_operational_warnings),
        "operational_warnings": all_operational_warnings,
        "load_compatibility_warnings_count": len(all_load_compatibility_warnings),
        "load_compatibility_warnings": all_load_compatibility_warnings,
        "dropped_orders": all_dropped_orders,
        "cluster_debug_by_day": cluster_debug_by_day,
        "performance_debug_by_day": performance_debug_by_day,
        "debug_timings": debug_timings,
    }
