"""
Serviciul principal de planificare — Pickup & Delivery.
Orchestrează pipeline-ul: geocodare → clustering → PDP → salvare în DB.
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatusEnum
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.models.driver import Driver, DriverStatusEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_stop import TripStop, StopStatusEnum, StopTypeEnum
from app.models.planning_session import PlanningSession, PlanningStrategyEnum, PlanningStatusEnum
from app.services.ors_service import geocode, get_distance_matrix
from app.services.clustering_service import calculate_num_clusters, cluster_orders
from app.services.vrp_service import solve_pdp_for_cluster
from app.services.service_time_service import ensure_order_service_times
from app.services.order_feasibility_service import check_order_operational_warnings
from app.services.load_compatibility_service import check_load_compatibility_warnings
from app.services.strategy_service import distribute_orders_by_strategy
from zoneinfo import ZoneInfo
from sqlalchemy import or_

DEPOT_COORDS = {"lat": 46.7712, "lon": 23.5896}
LOCAL_TZ = ZoneInfo("Europe/Bucharest")
DEFAULT_BREAK_MINUTES = 30
DEFAULT_TRAVEL_BUFFER_MINUTES = 30
DEFAULT_WAITING_BUFFER_MINUTES = 15



def time_to_seconds(t) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second

def priority_rank(order: Order) -> int:
    priority = order.priority.value if hasattr(order.priority, "value") else str(order.priority)
    return {"CRITIC": 0, "URGENT": 1, "NORMAL": 2}.get(priority, 2)

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


def _build_capacity_by_day_minutes(
    day_dates: list[date],
    drivers: list,
) -> dict[date, int]:
    """
    Construiește capacitatea estimativă pe zi, în minute.

    Pentru moment folosim aceeași capacitate pentru fiecare zi din interval,
    bazată pe șoferii disponibili.
    """
    total_available_minutes = sum(
        _driver_available_minutes(driver)
        for driver in drivers
    )

    return {
        day: total_available_minutes
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


def _build_solver_data(orders, db, depot_start_seconds=5 * 3600):
    """
    Construiește toate datele necesare pentru OR-Tools dintr-o listă de comenzi.
    Returnează un dict cu coords, pickups_deliveries, demands, volume_demands,
    time_windows, service_times.

    Args:
        depot_start_seconds: ora de start a depotului (implicit 05:00)
    """
    num_orders = len(orders)
    full_day_window = (0, 24 * 3600)
    depot_window = (depot_start_seconds, 24 * 3600)

    # Coordonate: depot + pickups + deliveries
    coords = [[DEPOT_COORDS["lon"], DEPOT_COORDS["lat"]]]
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

    available_vehicles = vehicles.copy()
    available_drivers = drivers.copy()

    driver_state = {
        driver.id: {
            "driver": driver,
            "remaining_minutes": _driver_available_minutes(driver),
            "available_from_seconds": time_to_seconds(driver.shift_start)
            if driver.shift_start
            else 5 * 3600,
        }
        for driver in drivers
    }

    vehicle_state = {
        vehicle.id: {
            "vehicle": vehicle,
            "available_from_seconds": 5 * 3600,
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
                depot_start_seconds=depot_start_seconds,
            )

            # Calculează matricea ORS
            retry_matrix = get_distance_matrix(solver_data["coords"])

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
                candidate_result = solve_pdp_for_cluster(
                    distance_matrix=retry_matrix["distances"],
                    duration_matrix=retry_matrix["durations"],
                    pickups_deliveries=solver_data["pickups_deliveries"],
                    demands=solver_data["demands"],
                    vehicle_capacity_kg=int(float(vehicle_candidate.capacity_kg)),
                    volume_demands=solver_data["volume_demands"],
                    vehicle_capacity_m3=int(float(vehicle_candidate.capacity_m3) * 100),
                    time_windows=solver_data["time_windows"],
                    service_times=solver_data["service_times"],
                    max_time_seconds=2,
                )

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

        vehicle_state[chosen_vehicle.id]["available_from_seconds"] = trip_end_seconds

        driver_available_after_trip = driver_state[chosen_driver.id]["remaining_minutes"]

        vehicle = chosen_vehicle
        driver = chosen_driver
        planned_cluster_orders = current_orders
        num_orders_in_cluster = len(planned_cluster_orders)

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
            )

            db.add(trip)
            db.flush()

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
                )

                db.add(trip_stop)

                if stop_type == StopTypeEnum.DELIVERY:
                    order.status = OrderStatusEnum.PLANNED
                    order.assigned_delivery_date = planned_date

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

    return {
        "used_num_clusters": num_clusters,
        "cluster_debug": cluster_debug,
        "trips": trips_created,
        "warnings": all_warnings,
        "operational_warnings": all_operational_warnings,
        "load_compatibility_warnings": all_load_compatibility_warnings,
        "dropped_orders": dropped_orders_info,
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
) -> dict:
    """
    Reintroduce comenzile deferred într-o zi eligibilă înainte de planificarea reală.

    Motiv:
    - strategy_service folosește doar estimări;
    - _plan_day + OR-Tools trebuie să ia decizia finală;
    - nu vrem ca o comandă să fie dropped doar pentru că estimarea a fost conservatoare.
    """
    deferred_orders = distribution.get("deferred", [])

    if not deferred_orders:
        return distribution

    still_deferred = []

    for order in deferred_orders:
        earliest_day, latest_day = _get_order_planning_window(order)

        # Alegem ultima zi posibilă din intervalul selectat.
        retry_day = min(latest_day, date_end)

        # Dacă retry_day nu este validă pentru comanda respectivă,
        # comanda chiar nu poate fi planificată în interval.
        if retry_day < date_start or retry_day < earliest_day:
            still_deferred.append(order)
            continue

        if retry_day not in distribution["days"]:
            distribution["days"][retry_day] = []

        existing_order_ids = {
            str(existing_order.id)
            for existing_order in distribution["days"][retry_day]
        }

        if str(order.id) not in existing_order_ids:
            distribution["days"][retry_day].append(order)

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
    if date_start is None:
        date_start = planned_date
    if date_end is None:
        date_end = planned_date

    day_dates = []
    current_day = date_start
    while current_day <= date_end:
        day_dates.append(current_day)
        current_day += timedelta(days=1)


    # PAS 1: Comenzi eligibile
    orders = db.query(Order).filter(
        Order.company_id == company_id,
        Order.status == OrderStatusEnum.PENDING,
        Order.is_problematic.is_(False),
    ).all()

    if not orders:
        return {"error": "Nu există comenzi PENDING pentru planificare"}

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

    # PAS 2: Geocodare (cache)
    for order in eligible_orders:
        if order.pickup_lat is None or order.pickup_lon is None:
            result = geocode(order.address_pickup)
            if result:
                order.pickup_lat = result["lat"]
                order.pickup_lon = result["lon"]
            else:
                print(f"Nu am putut geocoda pickup: {order.address_pickup}")

        if order.delivery_lat is None or order.delivery_lon is None:
            result = geocode(order.address_delivery)
            if result:
                order.delivery_lat = result["lat"]
                order.delivery_lon = result["lon"]
            else:
                print(f"Nu am putut geocoda delivery: {order.address_delivery}")

    db.commit()

    geocoded_orders = [
        o for o in eligible_orders
        if o.pickup_lat is not None and o.pickup_lon is not None
        and o.delivery_lat is not None and o.delivery_lon is not None
    ]

    if not geocoded_orders:
        return {"error": "Nicio comandă nu a putut fi geocodată complet"}

    geocoded_orders = sorted(
        geocoded_orders,
        key=lambda order: (priority_rank(order), order.delivery_deadline, order.created_at),
    )

    # PAS 3: Vehicule și driveri
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
    
    capacity_by_day_minutes = _build_capacity_by_day_minutes(
        day_dates=day_dates,
        drivers=drivers,
    )

    estimated_minutes_by_order = _build_estimated_minutes_by_order(
        db=db,
        orders=geocoded_orders,
    )

    # PAS 4: Distribuie pe zile
    distribution = distribute_orders_by_strategy(
        orders=geocoded_orders,
        strategy=strategy,
        date_start=date_start,
        date_end=date_end,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )

    # PAS 4.5: Repair pentru comenzile deferred.
    # Nu le marcăm dropped doar pe baza estimării.
    distribution = _repair_deferred_distribution(
        distribution=distribution,
        date_start=date_start,
        date_end=date_end,
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
        )

        cluster_debug_by_day.append({
            "planned_date": str(day_date),
            "used_num_clusters": day_result.get("used_num_clusters"),
            "cluster_debug": day_result.get("cluster_debug", []),
        })

        all_trips.extend(day_result["trips"])
        all_warnings.extend(day_result["warnings"])
        all_operational_warnings.extend(day_result["operational_warnings"])
        all_load_compatibility_warnings.extend(day_result["load_compatibility_warnings"])
        all_dropped_orders.extend(day_result["dropped_orders"])

    for order in distribution.get("deferred", []):
        all_dropped_orders.append({
            "order_id": str(order.id),
            "order_ref": order.order_ref,
            "reason_code": "DEFERRED_OUTSIDE_PLANNING_INTERVAL",
            "reason": "Comanda nu poate fi planificată în intervalul selectat",
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
    }
