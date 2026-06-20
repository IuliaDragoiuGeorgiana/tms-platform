"""
Serviciu de distribuție comenzi pe zile în funcție de strategie.

Acest fișier conține logica care diferențiază cele 3 strategii de planificare:
GREEDY_DEADLINE, MAX_DENSITY, HYBRID.

Funcția principală distribute_orders_by_strategy() primește comenzile eligibile
și returnează un dicționar {data: [comenzi]} care spune care comenzi merg pe care zi.
"""
from datetime import date, timedelta
from app.models.order import Order
from app.models.planning_session import PlanningStrategyEnum
import numpy as np
from sklearn.cluster import KMeans


def _priority_weight(order: Order) -> int:
    """
    Returnează un scor numeric pentru prioritatea comenzii.
    Mai mare = mai urgent.

    CRITIC = 3 puncte (cel mai urgent)
    URGENT = 2 puncte
    NORMAL = 1 punct
    """
    priority = order.priority.value if hasattr(order.priority, "value") else str(order.priority)
    weights = {"CRITIC": 3, "URGENT": 2, "NORMAL": 1}
    return weights.get(priority, 1)


def _urgency_score(order: Order, reference_date: date) -> float:
    """
    Calculează un scor de urgență între 0 și 1.

    Formula: priority_weight / (zile_până_la_deadline + 1)
    Apoi normalizat la [0, 1] prin împărțire la 3 (max priority_weight).

    Exemple:
    - CRITIC cu deadline mâine:   3 / (1 + 1) = 1.5  → normalizat 0.50
    - CRITIC cu deadline azi:     3 / (0 + 1) = 3.0  → normalizat 1.00
    - NORMAL cu deadline peste 5: 1 / (5 + 1) = 0.17 → normalizat 0.06

    reference_date = prima zi a intervalului (date_start)
    """
    days_until = max(0, (order.delivery_deadline - reference_date).days)
    raw = _priority_weight(order) / (days_until + 1)
    # Normalizare: maximul posibil e 3.0 (CRITIC cu deadline = reference_date)
    return min(raw / 3.0, 1.0)


def _get_order_coords(order: Order) -> tuple[float, float]:
    """
    Returnează coordonatele medii ale unei comenzi (punctul de mijloc
    între pickup și delivery). Folosit pentru clustering geografic.
    """
    mid_lat = (float(order.pickup_lat) + float(order.delivery_lat)) / 2
    mid_lon = (float(order.pickup_lon) + float(order.delivery_lon)) / 2
    return mid_lat, mid_lon


def _calculate_density_scores(orders: list[Order]) -> dict[str, float]:
    """
    Calculează un scor de densitate pentru fiecare comandă, bazat pe
    câte alte comenzi sunt aproape de ea geografic.

    Pași:
    1. Clusterizează toate comenzile în grupuri geografice
    2. Pentru fiecare cluster, calculează densitatea:
       densitate = num_comenzi_din_cluster / raza_clusterului
    3. Fiecare comandă primește scorul clusterului ei
    4. Normalizează toate scorurile la [0, 1]

    Returnează: {order_id_str: density_score}
    """
    if len(orders) <= 1:
        return {str(o.id): 1.0 for o in orders}

    # Extrage coordonatele
    coords = np.array([_get_order_coords(o) for o in orders])

    # Număr de clustere: ~1 cluster per 5 comenzi, minim 2, maxim 10
    n_clusters = max(2, min(10, len(orders) // 5))
    n_clusters = min(n_clusters, len(orders))  # Nu mai multe clustere decât comenzi

    # Clustering cu KMeans
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(coords)

    # Calculează densitatea per cluster
    cluster_densities = {}
    for cluster_id in range(n_clusters):
        # Comenzile din acest cluster
        mask = labels == cluster_id
        cluster_coords = coords[mask]
        cluster_size = len(cluster_coords)

        if cluster_size <= 1:
            # O singură comandă = densitate minimă (izolată)
            cluster_densities[cluster_id] = 0.1
            continue

        # Raza = distanța maximă de la centrul clusterului la orice punct
        # Folosim standard deviation ca măsură de "răspândire"
        center = kmeans.cluster_centers_[cluster_id]
        distances = np.sqrt(np.sum((cluster_coords - center) ** 2, axis=1))
        spread = np.std(distances) + 0.001  # +0.001 evită împărțire la 0

        # Densitate = câte comenzi per unitate de suprafață
        cluster_densities[cluster_id] = cluster_size / spread

    # Normalizare la [0, 1]
    max_density = max(cluster_densities.values())
    min_density = min(cluster_densities.values())
    density_range = max_density - min_density

    density_scores = {}
    for i, order in enumerate(orders):
        cluster_id = labels[i]
        raw_density = cluster_densities[cluster_id]

        if density_range > 0:
            normalized = (raw_density - min_density) / density_range
        else:
            normalized = 1.0

        density_scores[str(order.id)] = normalized

    return density_scores


def _chunk_orders_into_days(
    ordered_list: list[Order],
    day_dates: list[date],
    capacity_by_day_minutes: dict[date, int],
    estimated_minutes_by_order: dict[str, int],
) -> dict:
    """
    Distribuie o listă sortată de comenzi pe zile, respectând capacitatea zilnică
    exprimată în minute disponibile, nu în număr fix de comenzi.

    Exemplu:
    - ziua are 510 minute disponibile
    - comanda estimată are 80 minute
    - sistemul pune comenzi până când suma minutelor estimative ajunge la 510.
    """
    result = {d: [] for d in day_dates}
    used_minutes = {d: 0 for d in day_dates}
    deferred = []

    for order in ordered_list:
        placed = False
        order_id = str(order.id)

        estimated_minutes = estimated_minutes_by_order.get(order_id, 0)

        for day in day_dates:
            # Comanda trebuie livrată cel târziu la deadline.
            if day > order.delivery_deadline:
                continue

            # Respectă earliest_delivery_date, dacă există.
            if order.earliest_delivery_date and day < order.earliest_delivery_date:
                continue

            # Respectă flexibility_days.
            earliest_flexible = order.delivery_deadline - timedelta(
                days=order.flexibility_days
            )

            if day < earliest_flexible:
                continue

            day_capacity = capacity_by_day_minutes.get(day, 0)

            # Noua verificare:
            # în loc de "mai sunt locuri pentru comenzi?",
            # întrebăm "mai sunt minute disponibile în acea zi?"
            if used_minutes[day] + estimated_minutes <= day_capacity:
                result[day].append(order)
                used_minutes[day] += estimated_minutes
                placed = True
                break

        if not placed:
            deferred.append(order)

    return {
        "days": result,
        "deferred": deferred,
        "used_minutes": used_minutes,
        "capacity_by_day_minutes": capacity_by_day_minutes,
    }

def distribute_greedy_deadline(
    orders: list[Order],
    day_dates: list[date],
    capacity_by_day_minutes: dict[date, int],
    estimated_minutes_by_order: dict[str, int],
) -> dict:
    """
    Strategia GREEDY_DEADLINE:
    Sortează comenzile după prioritate și deadline, apoi le distribuie
    pe zile în funcție de minutele disponibile.
    """
    sorted_orders = sorted(
        orders,
        key=lambda o: (
            0 if o.was_postponed else 1,
            -_priority_weight(o),
            o.delivery_deadline,
            o.created_at,
        ),
    )

    return _chunk_orders_into_days(
        ordered_list=sorted_orders,
        day_dates=day_dates,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )


def distribute_max_density(
    orders: list[Order],
    day_dates: list[date],
    capacity_by_day_minutes: dict[date, int],
    estimated_minutes_by_order: dict[str, int],
) -> dict:
    """
    Strategia MAX_DENSITY:
    Prioritizează zonele geografice dense, apoi distribuie comenzile
    pe zile în funcție de minutele disponibile.
    """
    if not orders:
        return {
            "days": {d: [] for d in day_dates},
            "deferred": [],
            "used_minutes": {d: 0 for d in day_dates},
            "capacity_by_day_minutes": capacity_by_day_minutes,
        }

    if len(orders) == 1:
        return _chunk_orders_into_days(
            ordered_list=orders,
            day_dates=day_dates,
            capacity_by_day_minutes=capacity_by_day_minutes,
            estimated_minutes_by_order=estimated_minutes_by_order,
        )

    coords = np.array([_get_order_coords(o) for o in orders])

    n_clusters = max(2, min(10, len(orders) // 5))
    n_clusters = min(n_clusters, len(orders))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(coords)

    cluster_groups: dict[int, list[Order]] = {}

    for i, order in enumerate(orders):
        cluster_id = int(labels[i])
        cluster_groups.setdefault(cluster_id, []).append(order)

    cluster_densities = {}

    for cluster_id, cluster_orders_list in cluster_groups.items():
        cluster_size = len(cluster_orders_list)

        if cluster_size <= 1:
            cluster_densities[cluster_id] = 0.1
            continue

        cluster_coords = np.array([_get_order_coords(o) for o in cluster_orders_list])
        center = kmeans.cluster_centers_[cluster_id]
        distances = np.sqrt(np.sum((cluster_coords - center) ** 2, axis=1))
        spread = np.std(distances) + 0.001

        cluster_densities[cluster_id] = cluster_size / spread

    sorted_cluster_ids = sorted(
        cluster_groups.keys(),
        key=lambda cid: -cluster_densities[cid],
    )

    ordered_orders: list[Order] = []

    for cluster_id in sorted_cluster_ids:
        cluster_orders_list = cluster_groups[cluster_id]

        cluster_orders_list = sorted(
            cluster_orders_list,
            key=lambda o: (
                0 if o.was_postponed else 1,
                -_priority_weight(o),
                o.delivery_deadline,
                o.created_at,
            ),
        )

        ordered_orders.extend(cluster_orders_list)
    ordered_orders.sort(
        key=lambda o: 0 if o.was_postponed else 1
    )

    return _chunk_orders_into_days(
        ordered_list=ordered_orders,
        day_dates=day_dates,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )


def distribute_hybrid(
    orders: list[Order],
    day_dates: list[date],
    capacity_by_day_minutes: dict[date, int],
    estimated_minutes_by_order: dict[str, int],
    date_start: date,
    urgency_weight: float = 0.7,
    density_weight: float = 0.3,
) -> dict:
    """
    Strategia HYBRID:
    Calculează un scor compus per comandă:
    scor = urgency_weight × urgență + density_weight × densitate.

    După sortare, comenzile sunt distribuite pe zile în funcție
    de timpul estimativ disponibil, nu de un număr fix de comenzi.
    """
    if not orders:
        return {
            "days": {d: [] for d in day_dates},
            "deferred": [],
            "used_minutes": {d: 0 for d in day_dates},
            "capacity_by_day_minutes": capacity_by_day_minutes,
        }

    density_scores = _calculate_density_scores(orders)

    composite_scores = {}

    for order in orders:
        urgency = _urgency_score(order, date_start)
        density = density_scores.get(str(order.id), 0)

        composite_scores[str(order.id)] = (
            urgency_weight * urgency
            + density_weight * density
        )

    sorted_orders = sorted(
        orders,
        key=lambda o: (
            0 if o.was_postponed else 1,
            -composite_scores.get(str(o.id), 0),
            o.delivery_deadline,
        ),
    )

    return _chunk_orders_into_days(
        ordered_list=sorted_orders,
        day_dates=day_dates,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )


def distribute_orders_by_strategy(
    orders: list[Order],
    strategy: PlanningStrategyEnum,
    date_start: date,
    date_end: date,
    capacity_by_day_minutes: dict[date, int],
    estimated_minutes_by_order: dict[str, int],
) -> dict:
    """
    Funcția principală — apelată din run_planning.

    Primește:
    - orders: lista de comenzi eligibile (PENDING, geocodate)
    - strategy: GREEDY_DEADLINE / MAX_DENSITY / HYBRID
    - date_start, date_end: intervalul de planificare
    - num_vehicles: câte vehicule disponibile are compania
    - max_orders_per_vehicle: câte comenzi estimăm per vehicul pe zi (implicit 8)

    Returnează:
    {
        "days": {
            date(2026, 6, 16): [order1, order2, ...],
            date(2026, 6, 17): [order3, order4, ...],
        },
        "deferred": [order5, order6, ...],  # comenzi care nu au încăput
    }
    """
    day_dates = []
    current_day = date_start

    while current_day <= date_end:
        day_dates.append(current_day)
        current_day += timedelta(days=1)

    strategy_value = (
        strategy.value
        if hasattr(strategy, "value")
        else str(strategy)
    )

    if strategy_value == "GREEDY_DEADLINE":
        return distribute_greedy_deadline(
            orders=orders,
            day_dates=day_dates,
            capacity_by_day_minutes=capacity_by_day_minutes,
            estimated_minutes_by_order=estimated_minutes_by_order,
        )

    if strategy_value == "MAX_DENSITY":
        return distribute_max_density(
            orders=orders,
            day_dates=day_dates,
            capacity_by_day_minutes=capacity_by_day_minutes,
            estimated_minutes_by_order=estimated_minutes_by_order,
        )

    if strategy_value == "HYBRID":
        return distribute_hybrid(
            orders=orders,
            day_dates=day_dates,
            capacity_by_day_minutes=capacity_by_day_minutes,
            estimated_minutes_by_order=estimated_minutes_by_order,
            date_start=date_start,
        )

    return distribute_greedy_deadline(
        orders=orders,
        day_dates=day_dates,
        capacity_by_day_minutes=capacity_by_day_minutes,
        estimated_minutes_by_order=estimated_minutes_by_order,
    )