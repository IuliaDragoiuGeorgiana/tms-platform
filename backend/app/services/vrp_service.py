"""
Serviciu de optimizare rute folosind Google OR-Tools.
Rezolvă problema PDPTW: Pickup and Delivery Problem with Time Windows.

Diferența față de VRP simplu:
- Fiecare comandă are 2 stopuri: PICKUP (încarcă) și DELIVERY (descarcă)
- PICKUP trebuie vizitat ÎNAINTE de DELIVERY pentru aceeași comandă
- Capacitatea camionului crește la pickup și scade la delivery
"""
from ortools.constraint_solver import routing_enums_pb2, pywrapcp


def solve_pdp_for_cluster(
    distance_matrix: list[list[int]],
    duration_matrix: list[list[int]],
    pickups_deliveries: list[list[int]],
    demands: list[int],
    vehicle_capacity_kg: int,
    time_windows: list[tuple[int, int]] | None = None,
    service_times: list[int] | None = None,
    depot_index: int = 0,
    max_time_seconds: int = 5,
    volume_demands: list[int] | None = None,
    vehicle_capacity_m3: int | None = None,
) -> dict | None:
    """
    Optimizează ordinea stopurilor pentru un camion cu pickup & delivery.

    Returnează ruta optimizată sau None dacă nu găsește soluție.
    Dacă returnează None, planning_service decide: încearcă alt vehicul
    sau scoate comenzi.
    """
    num_locations = len(distance_matrix)
    if service_times is None:
        service_times = [0] * num_locations

    if time_windows is None:
        time_windows = [(0, 24 * 60 * 60)] * num_locations

    if num_locations <= 1:
        return {
            "route": [0],
            "arrival_times": {0: 0},
            "start_seconds": 0,
            "end_seconds": 0,
            "total_duration_seconds": 0,
        }

    # Creează modelul OR-Tools
    manager = pywrapcp.RoutingIndexManager(
        num_locations,
        1,
        depot_index,
    )
    routing = pywrapcp.RoutingModel(manager)

    # Funcția de cost: minimizează distanța totală
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(distance_matrix[from_node][to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Funcția de timp
    def duration_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel_time = int(duration_matrix[from_node][to_node])
        service_time = int(service_times[from_node])
        return travel_time + service_time

    duration_callback_index = routing.RegisterTransitCallback(duration_callback)

    # Dimensiune de timp
    routing.AddDimension(
        duration_callback_index,
        2 * 60 * 60,
        24 * 60 * 60,
        False,
        "Time",
    )

    time_dimension = routing.GetDimensionOrDie("Time")

    # Ferestre orare — soft constraints
    PENALTY_PER_SECOND_LATE = 1000

    for node_idx, (window_start, window_end) in enumerate(time_windows):
        index = manager.NodeToIndex(node_idx)

        if node_idx == 0:
            time_dimension.CumulVar(index).SetRange(window_start, window_end)
        else:
            time_dimension.CumulVar(index).SetMin(window_start)
            time_dimension.SetCumulVarSoftUpperBound(
                index, window_end, PENALTY_PER_SECOND_LATE
            )

    time_dimension.CumulVar(routing.End(0)).SetRange(0, 24 * 60 * 60)

    # Constrângere de capacitate kg
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,
        [vehicle_capacity_kg],
        True,
        "Capacity",
    )

    # Constrângere de volum m³
    if volume_demands is not None and vehicle_capacity_m3 is not None:
        def volume_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            return volume_demands[from_node]

        volume_callback_index = routing.RegisterUnaryTransitCallback(volume_callback)
        routing.AddDimensionWithVehicleCapacity(
            volume_callback_index,
            0,
            [vehicle_capacity_m3],
            True,
            "Volume",
        )

    # Constrângeri Pickup & Delivery
    time_dimension = routing.GetDimensionOrDie("Time")

    for pickup_idx, delivery_idx in pickups_deliveries:
        pickup_index = manager.NodeToIndex(pickup_idx)
        delivery_index = manager.NodeToIndex(delivery_idx)

        routing.AddPickupAndDelivery(pickup_index, delivery_index)

        routing.solver().Add(
            time_dimension.CumulVar(pickup_index)
            <= time_dimension.CumulVar(delivery_index)
        )

    # Parametri de căutare
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = max_time_seconds

    # Rezolvă
    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        return None

    # Extrage ruta + timpii
    route = []
    arrival_times = {}

    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        route.append(node)
        arrival_times[node] = solution.Value(time_dimension.CumulVar(index))
        index = solution.Value(routing.NextVar(index))
    end_node = manager.IndexToNode(index)
    route.append(end_node)

    start_seconds = solution.Value(
        time_dimension.CumulVar(routing.Start(0))
    )

    end_seconds = solution.Value(
        time_dimension.CumulVar(routing.End(0))
    )

    total_duration_seconds = max(0, end_seconds - start_seconds)

    return {
        "route": route,
        "arrival_times": arrival_times,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "total_duration_seconds": total_duration_seconds,
    }