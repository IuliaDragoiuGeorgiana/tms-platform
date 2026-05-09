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
    depot_index: int = 0,
    max_time_seconds: int = 5,
) -> list[int] | None:
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

    if num_locations <= 1:
        return [0]

    # Dacă avem doar depot + 1 pickup + 1 delivery, ordinea e trivială
    if num_locations == 3 and len(pickups_deliveries) == 1:
        p, d = pickups_deliveries[0]
        return [depot_index, p, d, depot_index]

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
        return int(duration_matrix[from_node][to_node])

    duration_callback_index = routing.RegisterTransitCallback(duration_callback)

    # Dimensiune de durată (pentru a putea calcula timpul cumulat)
    routing.AddDimension(
        duration_callback_index,
        30 * 60,          # slack maxim 30 minute (timp de așteptare permis)
        24 * 60 * 60,     # durata maximă a cursei: 24h în secunde
        True,             # start cumul la zero
        "Duration",
    )

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
    duration_dimension = routing.GetDimensionOrDie("Duration")

    for pickup_idx, delivery_idx in pickups_deliveries:
        pickup_index = manager.NodeToIndex(pickup_idx)
        delivery_index = manager.NodeToIndex(delivery_idx)

        # Pickup și delivery trebuie să fie pe același vehicul
        routing.AddPickupAndDelivery(pickup_index, delivery_index)

        # Pickup ÎNAINTE de delivery (constrângere de precedence)
        routing.solver().Add(
            duration_dimension.CumulVar(pickup_index)
            <= duration_dimension.CumulVar(delivery_index)
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

    # Extrage ruta
    route = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        route.append(node)
        index = solution.Value(routing.NextVar(index))
    route.append(manager.IndexToNode(index))  # adaugă ultimul nod (garajul)

    return route