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
from zoneinfo import ZoneInfo
from sqlalchemy import or_

# Garajul firmei (punct de plecare și întoarcere al camioanelor)
# TODO: configurabil per companie din system_config
DEPOT_COORDS = {"lat": 46.7712, "lon": 23.5896}  # Sediu Cluj-Napoca
LOCAL_TZ = ZoneInfo("Europe/Bucharest")

def time_to_seconds(t) -> int:
    """
    Transformă un obiect time în secunde de la începutul zilei.
    Exemplu: 08:30 -> 30600 secunde.
    """
    return t.hour * 3600 + t.minute * 60 + t.second

def choose_vehicle_for_cluster(cluster_orders: list[Order], vehicles: list[Vehicle]) -> Vehicle | None:
    """
    Alege cel mai mic vehicul disponibil care poate transporta totalul clusterului.
    Verifică atât kg, cât și m3.
    """
    total_kg = sum(float(order.kg) for order in cluster_orders)
    total_m3 = sum(float(order.m3) for order in cluster_orders)

    compatible_vehicles = [
        vehicle for vehicle in vehicles
        if float(vehicle.capacity_kg) >= total_kg
        and float(vehicle.capacity_m3) >= total_m3
    ]

    if not compatible_vehicles:
        return None

    return sorted(
        compatible_vehicles,
        key=lambda vehicle: (float(vehicle.capacity_kg), float(vehicle.capacity_m3))
    )[0]


def run_planning(
    db: Session,
    company_id: uuid.UUID,
    planned_date: date,
    created_by_id: uuid.UUID,
) -> dict:
    """
    Pipeline complet de planificare Pickup & Delivery.
    
    Pașii:
    1. Ia comenzile PENDING din companie
    2. Geocodează AMBELE adrese (pickup + delivery) pentru fiecare comandă
    3. Clustering pe coridoare geografice
    4. Pentru fiecare cluster: matrice distanțe + PDP optimization
    5. Salvează PlanningSession + Trips + TripStops (PICKUP + DELIVERY per comandă)
    """

    # ==========================================
    # PAS 1: Ia comenzile eligibile
    # ==========================================
    orders = db.query(Order).filter(
        Order.company_id == company_id,
        Order.status == OrderStatusEnum.PENDING,
        Order.is_problematic.is_(False),
        Order.delivery_deadline >= planned_date,
        or_(
            Order.earliest_delivery_date == None,
            Order.earliest_delivery_date <= planned_date,
        ),
    ).all()

    if not orders:
        return {"error": "Nu există comenzi PENDING pentru planificare"}

    # ==========================================
    # PAS 2: Geocodare AMBELE adrese per comandă
    # ==========================================
    for order in orders:
        # Geocodare pickup
        if order.pickup_lat is None or order.pickup_lon is None:
            result = geocode(order.address_pickup)
            if result:
                order.pickup_lat = result["lat"]
                order.pickup_lon = result["lon"]
            else:
                print(f"Nu am putut geocoda pickup: {order.address_pickup}")

        # Geocodare delivery
        if order.delivery_lat is None or order.delivery_lon is None:
            result = geocode(order.address_delivery)
            if result:
                order.delivery_lat = result["lat"]
                order.delivery_lon = result["lon"]
            else:
                print(f"Nu am putut geocoda delivery: {order.address_delivery}")

    db.commit()

    # Filtrează doar comenzile cu AMBELE coordonate valide
    geocoded_orders = [
        o for o in orders
        if o.pickup_lat is not None and o.pickup_lon is not None
        and o.delivery_lat is not None and o.delivery_lon is not None
    ]

    if not geocoded_orders:
        return {"error": "Nicio comandă nu a putut fi geocodată complet (pickup + delivery)"}

    # ==========================================
    # PAS 3: Ia vehiculele și driverii disponibili
    # ==========================================
    vehicles = db.query(Vehicle).filter(
        Vehicle.company_id == company_id,
        Vehicle.status == VehicleStatusEnum.DISPONIBIL,
    ).all()

    drivers = db.query(Driver).filter(
        Driver.company_id == company_id,
        Driver.status == DriverStatusEnum.AVAILABLE,
    ).all()

    if not vehicles:
        db.rollback()
        return {"error": "Nu există vehicule disponibile"}
    if not drivers:
        db.rollback()
        return {"error": "Nu există șoferi disponibili"}

    avg_capacity_kg = sum(float(v.capacity_kg) for v in vehicles) / len(vehicles)
    avg_capacity_m3 = sum(float(v.capacity_m3) for v in vehicles) / len(vehicles)

    # ==========================================
    # PAS 4: Clustering
    # ==========================================
    total_kg = sum(float(o.kg) for o in geocoded_orders)
    total_m3 = sum(float(o.m3) for o in geocoded_orders)

    num_clusters = calculate_num_clusters(
        total_kg=total_kg,
        total_m3=total_m3,
        avg_vehicle_capacity_kg=avg_capacity_kg,
        avg_vehicle_capacity_m3=avg_capacity_m3,
        num_orders=len(geocoded_orders),
    )

    num_clusters = min(num_clusters, len(vehicles), len(drivers))

    # Pentru clustering folosim punctul mediu între pickup și delivery
    # Asta grupează comenzile pe coridoare similare
    coords_for_clustering = []
    for o in geocoded_orders:
        mid_lat = (float(o.pickup_lat) + float(o.delivery_lat)) / 2
        mid_lon = (float(o.pickup_lon) + float(o.delivery_lon)) / 2
        coords_for_clustering.append([mid_lat, mid_lon])

    cluster_labels = cluster_orders(coords_for_clustering, num_clusters)

    # Grupează comenzile pe clustere
    clusters = {}
    for i, label in enumerate(cluster_labels):
        if label not in clusters:
            clusters[label] = []
        clusters[label].append(geocoded_orders[i])

    # ==========================================
    # PAS 5: Creează PlanningSession
    # ==========================================
    planning_session = PlanningSession(
        company_id=company_id,
        created_by=created_by_id,
        date_range_start=planned_date,
        date_range_end=planned_date,
        strategy=PlanningStrategyEnum.GREEDY_DEADLINE,
        status=PlanningStatusEnum.PROPOSED,
        total_orders=len(geocoded_orders),
    )
    db.add(planning_session)
    db.flush()

    # ==========================================
    # PAS 6: Pentru fiecare cluster → PDP → Trip + TripStops
    # ==========================================
    trips_created = []
    all_warnings = []
    available_vehicles = vehicles.copy()
    available_drivers = drivers.copy()

    for cluster_idx in sorted(clusters.keys()):
        cluster_orders_list = clusters[cluster_idx]

        vehicle = choose_vehicle_for_cluster(cluster_orders_list, available_vehicles)

        if not vehicle:
            return {
                "error": (
                    f"Nu există vehicul disponibil cu capacitate suficientă pentru clusterul {cluster_idx}."
                )
            }

        available_vehicles.remove(vehicle)

        if not available_drivers:
            return {
                "error": "Nu există suficienți șoferi disponibili pentru toate clusterele."
            }

        driver = available_drivers.pop(0)


        # Construiește lista de coordonate:
        # Index 0 = GARAJ (depot)
        # Index 1 = pickup comanda 1
        # Index 2 = pickup comanda 2
        # ...
        # Index N+1 = delivery comanda 1
        # Index N+2 = delivery comanda 2
        # ...
        num_orders_in_cluster = len(cluster_orders_list)

        # ORS așteaptă [lon, lat]!
        all_coords = [[DEPOT_COORDS["lon"], DEPOT_COORDS["lat"]]]

        # Mai întâi toate pickup-urile
        for order in cluster_orders_list:
            all_coords.append([float(order.pickup_lon), float(order.pickup_lat)])

        # Apoi toate delivery-urile
        for order in cluster_orders_list:
            all_coords.append([float(order.delivery_lon), float(order.delivery_lat)])

        # Construiește perechile pickup-delivery
        # pickup comanda i = index i+1
        # delivery comanda i = index i+1+num_orders
        pickups_deliveries = []
        for i in range(num_orders_in_cluster):
            pickup_idx = i + 1                          # pickup-urile încep de la 1
            delivery_idx = i + 1 + num_orders_in_cluster  # delivery-urile după pickups
            pickups_deliveries.append([pickup_idx, delivery_idx])

        # Demands: depot=0, pickups=+kg, deliveries=-kg
        demands = [0]  # depot
        for order in cluster_orders_list:
            demands.append(int(float(order.kg)))         # pickup: +kg
        for order in cluster_orders_list:
            demands.append(-int(float(order.kg)))        # delivery: -kg
        # Time windows și service times pentru fiecare nod.
        # Structura trebuie să fie aceeași ca all_coords/demands:
        # index 0 = depot
        # apoi pickup-urile
        # apoi delivery-urile
        full_day_window = (0, 24 * 3600)
        depot_window = (5 * 3600, 24 * 3600)

        time_windows = [depot_window]
        service_times = [0]  # depot

        # Pickup time windows + pickup service times
        for order in cluster_orders_list:
            ensure_order_service_times(db, order)

            if order.pickup_time_window_start and order.pickup_time_window_end:
                time_windows.append((
                    time_to_seconds(order.pickup_time_window_start),
                    time_to_seconds(order.pickup_time_window_end),
                ))
            else:
                time_windows.append(full_day_window)

            service_times.append(int(order.pickup_service_minutes or 0) * 60)

        # Delivery time windows + delivery service times
        for order in cluster_orders_list:
            ensure_order_service_times(db, order)

            if order.delivery_time_window_start and order.delivery_time_window_end:
                time_windows.append((
                    time_to_seconds(order.delivery_time_window_start),
                    time_to_seconds(order.delivery_time_window_end),
                ))
            else:
                time_windows.append(full_day_window)

            service_times.append(int(order.delivery_service_minutes or 0) * 60)
        
        # Calculează matricea de distanțe
        matrix_result = get_distance_matrix(all_coords)

        if not matrix_result:
            db.rollback()
            return {
                "error": (
                    f"Eroare la calculul matricei de distanțe pentru cluster {cluster_idx}. "
                    f"Verificați conexiunea la OpenRouteService."
                )
            }
        else:
            solver_result = solve_pdp_for_cluster(
                distance_matrix=matrix_result["distances"],
                duration_matrix=matrix_result["durations"],
                pickups_deliveries=pickups_deliveries,
                demands=demands,
                vehicle_capacity_kg=int(float(vehicle.capacity_kg)),
                time_windows=time_windows,
                service_times=service_times,
            )

            if not solver_result:
                db.rollback()
                return {
                    "error": (
                        f"Solver-ul nu a găsit soluție pentru cluster {cluster_idx} "
                        f"({num_orders_in_cluster} comenzi). "
                        f"Posibilă cauză: capacitate vehicul insuficientă."
                    )
                }
            else:
                optimized_route = solver_result["route"]
                solver_arrival_times = solver_result["arrival_times"]
        # Calculează distanța și durata totală
        total_km = 0.0
        for i in range(len(optimized_route) - 1):
            from_idx = optimized_route[i]
            to_idx = optimized_route[i + 1]
            total_km += matrix_result["distances"][from_idx][to_idx] / 1000

        # Durata totală din solver (include drum + așteptare + service time)
        end_node = optimized_route[-1]  # ultimul nod = depot retur
        total_minutes = round(
            solver_result.get("total_duration_seconds", 0) / 60
        )
        # Creează Trip-ul
        trip = Trip(
            company_id=company_id,
            driver_id=driver.id,
            vehicle_id=vehicle.id,
            planning_session_id=planning_session.id,
            planned_date=planned_date,
            status=TripStatusEnum.PROPOSED,
            planned_km=round(total_km, 1),
            planned_duration_min=round(total_minutes),
        )
        db.add(trip)
        db.flush()

        # Creează TripStops în ordinea optimizată
        sequence = 1

        for route_idx in optimized_route:
            if route_idx == 0:  # skip depot
                continue

            # Determină dacă e pickup sau delivery
            if route_idx <= num_orders_in_cluster:
                # E un pickup (indexele 1..N)
                order_idx = route_idx - 1
                stop_type = StopTypeEnum.PICKUP
            else:
                # E un delivery (indexele N+1..2N)
                order_idx = route_idx - 1 - num_orders_in_cluster
                stop_type = StopTypeEnum.DELIVERY

            if order_idx >= len(cluster_orders_list):
                continue

            order = cluster_orders_list[order_idx]

            # Calculează ETA
           # Calculează ETA
            eta = None
            if solver_arrival_times and route_idx in solver_arrival_times:
                # FOLOSIM TIMPII EXACTI DE LA OR-Tools
                # solver_arrival_times[route_idx] = secunde de la 00:00
                # Exemplu: 43200 = ora 12:00
                # Include automat: timp de drum + așteptare la fereastră + service time
                arrival_seconds = solver_arrival_times[route_idx]
                eta = datetime(
                    planned_date.year, planned_date.month, planned_date.day,
                    tzinfo=LOCAL_TZ
                ) + timedelta(seconds=arrival_seconds)

            trip_stop = TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=stop_type,
                eta_planned=eta,
                status=StopStatusEnum.PENDING,
            )
            db.add(trip_stop)

            # La DELIVERY, marcăm comanda ca PLANNED
            if stop_type == StopTypeEnum.DELIVERY:
                order.status = OrderStatusEnum.PLANNED
                order.assigned_delivery_date = planned_date

            sequence += 1
            # ---- VERIFICARE TIME WINDOW WARNINGS ----
        # După ce am creat toate stopurile, verificăm dacă vreun ETA
        # depășește fereastra orară cerută de client.
        if solver_arrival_times:
            for i in range(num_orders_in_cluster):
                order = cluster_orders_list[i]
                delivery_node_idx = i + 1 + num_orders_in_cluster

                # Verifică delivery time window
                if (order.delivery_time_window_end
                        and delivery_node_idx in solver_arrival_times):

                    # arrival_time e în secunde de la 00:00
                    arrival_sec = solver_arrival_times[delivery_node_idx]
                    window_end_sec = time_to_seconds(order.delivery_time_window_end)

                    if arrival_sec > window_end_sec:
                        delay_minutes = round((arrival_sec - window_end_sec) / 60)

                        # Formatare ore:minute din secunde
                        eta_h = arrival_sec // 3600
                        eta_m = (arrival_sec % 3600) // 60
                        win_start_str = (
                            order.delivery_time_window_start.strftime("%H:%M")
                            if order.delivery_time_window_start else "00:00"
                        )
                        win_end_str = order.delivery_time_window_end.strftime("%H:%M")

                        # Poate fi mutat pe altă zi?
                        suggestion = None
                        if order.flexibility_days and order.flexibility_days > 0:
                            from datetime import timedelta as td
                            next_day = planned_date + td(days=1)
                            if next_day <= order.delivery_deadline:
                                suggestion = (
                                    f"Comanda poate fi mutată pe {next_day.isoformat()}"
                                    f" (deadline: {order.delivery_deadline.isoformat()})"
                                )

                        # Severitate: > 60 min = CRITICAL, altfel WARNING
                        severity = "CRITICAL" if delay_minutes > 60 else "WARNING"

                        all_warnings.append({
                            "order_id": str(order.id),
                            "order_ref": order.order_ref,
                            "trip_id": str(trip.id),
                            "address": order.address_delivery,
                            "stop_type": "DELIVERY",
                            "requested_window": f"{win_start_str} - {win_end_str}",
                            "eta_planned": f"{int(eta_h):02d}:{int(eta_m):02d}",
                            "delay_minutes": delay_minutes,
                            "severity": severity,
                            "suggestion": suggestion,
                        })

                # Verifică și pickup time window
                pickup_node_idx = i + 1
                if (order.pickup_time_window_end
                        and pickup_node_idx in solver_arrival_times):

                    arrival_sec = solver_arrival_times[pickup_node_idx]
                    window_end_sec = time_to_seconds(order.pickup_time_window_end)

                    if arrival_sec > window_end_sec:
                        delay_minutes = round((arrival_sec - window_end_sec) / 60)
                        eta_h = arrival_sec // 3600
                        eta_m = (arrival_sec % 3600) // 60

                        all_warnings.append({
                            "order_id": str(order.id),
                            "order_ref": order.order_ref,
                            "trip_id": str(trip.id),
                            "address": order.address_pickup,
                            "stop_type": "PICKUP",
                            "requested_window": (
                                f"{order.pickup_time_window_start.strftime('%H:%M')}"
                                f" - {order.pickup_time_window_end.strftime('%H:%M')}"
                            ),
                            "eta_planned": f"{int(eta_h):02d}:{int(eta_m):02d}",
                            "delay_minutes": delay_minutes,
                            "severity": "WARNING",
                            "suggestion": None,
                        })
        # ---- SFÂRȘIT VERIFICARE WARNINGS ----

        trips_created.append({
            "trip_id": str(trip.id),
            "driver": str(driver.user_id),
            "vehicle_plate": vehicle.plate,
            "num_stops": sequence - 1,
            "total_km": round(total_km, 1),
            "total_minutes": round(total_minutes),
        })

    # ==========================================
    # PAS 7: Commit și returnează rezumatul
    # ==========================================
    # Salvează statisticile și warnings în planning_session
    orders_delayed = len(set(w["order_id"] for w in all_warnings))
    orders_on_time = len(geocoded_orders) - orders_delayed

    if orders_delayed > 0:
        feasibility = "FEASIBLE_WITH_WARNINGS"
    else:
        feasibility = "FEASIBLE"

    planning_session.optimization_stats = {
        "feasibility": feasibility,
        "total_orders": len(geocoded_orders),
        "orders_on_time": orders_on_time,
        "orders_delayed": orders_delayed,
        "warnings": all_warnings,
    }

    db.commit()
    return {
        "planning_session_id": str(planning_session.id),
        "planned_date": str(planned_date),
        "total_orders": len(geocoded_orders),
        "total_trips": len(trips_created),
        "trips": trips_created,
        "feasibility": planning_session.optimization_stats.get("feasibility", "FEASIBLE"),
        "delayed_orders_count": orders_delayed,
        "warnings_count": len(all_warnings),
        "warnings": all_warnings,
    }