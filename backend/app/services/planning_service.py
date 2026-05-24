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

# Garajul firmei (punct de plecare și întoarcere al camioanelor)
# TODO: configurabil per companie din system_config
DEPOT_COORDS = {"lat": 46.7712, "lon": 23.5896}  # Sediu Cluj-Napoca


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
        return {"error": "Nu există vehicule disponibile"}
    if not drivers:
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

    for cluster_idx in sorted(clusters.keys()):
        cluster_orders_list = clusters[cluster_idx]

        vehicle = vehicles[cluster_idx % len(vehicles)]
        driver = drivers[cluster_idx % len(drivers)]

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

        # Calculează matricea de distanțe
        matrix_result = get_distance_matrix(all_coords)

        if not matrix_result:
            print(f"Eroare matrice pentru cluster {cluster_idx}, folosim ordine implicită")
            # Fallback: pickup-uri apoi delivery-uri în ordine
            optimized_route = [0]
            for i in range(num_orders_in_cluster):
                optimized_route.append(i + 1)  # pickups
            for i in range(num_orders_in_cluster):
                optimized_route.append(i + 1 + num_orders_in_cluster)  # deliveries
            optimized_route.append(0)  # înapoi la garaj
        else:
            optimized_route = solve_pdp_for_cluster(
                distance_matrix=matrix_result["distances"],
                duration_matrix=matrix_result["durations"],
                pickups_deliveries=pickups_deliveries,
                demands=demands,
                vehicle_capacity_kg=int(float(vehicle.capacity_kg)),
            )

            if not optimized_route:
                # Fallback
                optimized_route = [0]
                for i in range(num_orders_in_cluster):
                    optimized_route.append(i + 1)
                for i in range(num_orders_in_cluster):
                    optimized_route.append(i + 1 + num_orders_in_cluster)
                optimized_route.append(0)

        # Calculează distanța și durata totală
        total_km = 0.0
        total_minutes = 0
        if matrix_result:
            for i in range(len(optimized_route) - 1):
                from_idx = optimized_route[i]
                to_idx = optimized_route[i + 1]
                total_km += matrix_result["distances"][from_idx][to_idx] / 1000
                total_minutes += matrix_result["durations"][from_idx][to_idx] / 60

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
        service_time_pickup = 30     # 30 min încărcare
        service_time_delivery = 20   # 20 min descărcare

        departure_time = datetime(
            planned_date.year, planned_date.month, planned_date.day,
            7, 0, 0, tzinfo=timezone.utc  # plecare la 07:00
        )

        for route_idx in optimized_route:
            if route_idx == 0:  # skip depot
                continue

            # Determină dacă e pickup sau delivery
            if route_idx <= num_orders_in_cluster:
                # E un pickup (indexele 1..N)
                order_idx = route_idx - 1
                stop_type = StopTypeEnum.PICKUP
                service_time = service_time_pickup
            else:
                # E un delivery (indexele N+1..2N)
                order_idx = route_idx - 1 - num_orders_in_cluster
                stop_type = StopTypeEnum.DELIVERY
                service_time = service_time_delivery

            if order_idx >= len(cluster_orders_list):
                continue

            order = cluster_orders_list[order_idx]

            # Calculează ETA
            cumulative_minutes = 0
            if matrix_result:
                route_position = optimized_route.index(route_idx)
                for i in range(route_position):
                    from_i = optimized_route[i]
                    to_i = optimized_route[i + 1]
                    cumulative_minutes += matrix_result["durations"][from_i][to_i] / 60
                    # Adaugă timp serviciu pentru stopurile anterioare
                    if optimized_route[i + 1] != route_idx and optimized_route[i + 1] != 0:
                        prev_idx = optimized_route[i + 1]
                        if prev_idx <= num_orders_in_cluster:
                            cumulative_minutes += service_time_pickup
                        else:
                            cumulative_minutes += service_time_delivery

            eta = departure_time + timedelta(minutes=cumulative_minutes)

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
    db.commit()

    return {
        "planning_session_id": str(planning_session.id),
        "planned_date": str(planned_date),
        "total_orders": len(geocoded_orders),
        "total_trips": len(trips_created),
        "trips": trips_created,
    }