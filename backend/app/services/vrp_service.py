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
) -> dict | None:
    """
    Optimizează ordinea stopurilor pentru un camion cu pickup & delivery.
    
    Input:
    - distance_matrix: distanțe între toate punctele (metri)
    - duration_matrix: timpi între toate punctele (secunde)
    - pickups_deliveries: perechi [[pickup_idx, delivery_idx], ...]
      Exemplu: [[1, 3], [2, 4]] = comanda 1 are pickup la index 1 și delivery la 3
    - demands: cererea la fiecare nod
      Pickup = +kg (se încarcă), Delivery = -kg (se descarcă), Depot = 0
      Exemplu: [0, 500, 300, -500, -300] (depot, pickup A +500, pickup B +300, delivery A -500, delivery B -300)
    - vehicle_capacity_kg: capacitatea maximă a camionului
    - depot_index: de unde pleacă (garajul)
    
    Output:
    - Lista de indici în ordinea optimă: [0, 1, 2, 3, 4, 0]
      (garaj → pickup A → pickup B → delivery A → delivery B → garaj)
    - None dacă nu găsește soluție
    
    Constrângeri respectate:
    1. Pickup ÎNAINTE de delivery pentru aceeași comandă
    2. Capacitatea camionului nu e depășită la niciun moment
    3. Minimizează distanța totală
    """
    num_locations = len(distance_matrix)
    if service_times is None:
        service_times = [0] * num_locations

    if time_windows is None:
        # Default: orice nod poate fi vizitat oricând în ziua respectivă.
        time_windows = [(0, 24 * 60 * 60)] * num_locations

    if num_locations <= 1:
        return {
            "route": [0],
            "arrival_times": {0: 0},
    }

    # Creează modelul OR-Tools
    manager = pywrapcp.RoutingIndexManager(
        num_locations,   # câte locații avem (depot + pickups + deliveries)
        1,               # 1 vehicul per cluster
        depot_index,     # de unde pleacă
    )
    routing = pywrapcp.RoutingModel(manager)

    # Funcția de cost: minimizează distanța totală
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(distance_matrix[from_node][to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Funcția de timp (pentru dimensiunea de durată)
    def duration_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        travel_time = int(duration_matrix[from_node][to_node])
        service_time = int(service_times[from_node])

        return travel_time + service_time

    duration_callback_index = routing.RegisterTransitCallback(duration_callback)

    # Dimensiune de durată (pentru a putea calcula timpul cumulat)
    # Dimensiune de timp.
    # CumulVar reprezintă timpul absolut din zi, în secunde de la 00:00.
    routing.AddDimension(
        duration_callback_index,
        2* 60 * 60,          # slack maxim 2h
        24 * 60 * 60,     # orizont maxim: 24h
        False,            # nu forțăm startul la 0, pentru că plecarea poate fi la 07:00
        "Time",
    )

    time_dimension = routing.GetDimensionOrDie("Time")

    # Aplică ferestrele orare pe fiecare nod.
    # Folosim SOFT constraints: dacă nu se poate respecta fereastra,
    # solver-ul adaugă o penalizare proporțională cu întârzierea,
    # dar NU refuză să genereze planul.
    PENALTY_PER_SECOND_LATE = 1000  # cât de "rău" e să întârzii (cost artificial)

    for node_idx, (window_start, window_end) in enumerate(time_windows):
        index = manager.NodeToIndex(node_idx)

        if node_idx == 0:
            # Depot-ul rămâne STRICT — camionul TREBUIE să plece din garaj
            time_dimension.CumulVar(index).SetRange(window_start, window_end)
        else:
            # Toate celelalte stopuri: SOFT constraint
            # SetSoftRange(start, end, penalizare_per_secundă)
            # Dacă ajunge la 10:45 dar fereastra e 9:00-10:00,
            # solver-ul adaugă (45min × 60sec × 1000) = 2.700.000 la costul total
            # Dar GENEREAZĂ planul în loc să returneze None
            # Sosire prea devreme → camionul AȘTEAPTĂ (hard lower bound)
            time_dimension.CumulVar(index).SetMin(window_start)

            # Sosire prea târziu → penalizare soft (nu blochează planul)
            time_dimension.SetCumulVarSoftUpperBound(
                index, window_end, PENALTY_PER_SECOND_LATE
            )

    # Permitem întoarcerea la depot până la finalul zilei.
    time_dimension.CumulVar(routing.End(0)).SetRange(0, 24 * 60 * 60)

    # Constrângere de capacitate
    # Demands: pickup = +kg, delivery = -kg, depot = 0
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,                          # fără slack
        [vehicle_capacity_kg],      # capacitate maximă
        True,                       # start cumul la zero
        "Capacity",
    )

    # Constrângeri Pickup & Delivery
    # Pentru fiecare pereche: pickup trebuie vizitat ÎNAINTE de delivery
    time_dimension = routing.GetDimensionOrDie("Time")

    for pickup_idx, delivery_idx in pickups_deliveries:
        pickup_index = manager.NodeToIndex(pickup_idx)
        delivery_index = manager.NodeToIndex(delivery_idx)

        # Pickup și delivery trebuie să fie pe același vehicul
        routing.AddPickupAndDelivery(pickup_index, delivery_index)

        # Pickup ÎNAINTE de delivery (constrângere de precedence)
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

    # Extrage ruta + timpii calculați de OR-Tools
    route = []
    arrival_times = {}

    # Salvăm ora de plecare din depot ÎNAINTE de a parcurge ruta
    start_index = routing.Start(0)
    depot_departure_seconds = solution.Value(time_dimension.CumulVar(start_index))

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