"""
Serviciu de clustering geografic.
Grupează comenzile pe zone folosind K-means, ca fiecare grup
să poată fi servit de un singur vehicul.
"""
import math
import numpy as np
from sklearn.cluster import KMeans


def calculate_num_clusters(
    total_kg: float,
    total_m3: float,
    avg_vehicle_capacity_kg: float,
    avg_vehicle_capacity_m3: float,
    num_orders: int,
    max_stops_per_trip: int = 15,
) -> int:
    """
    Calculează câte clustere (= câte curse) avem nevoie.
    
    Logica: luăm maximul dintre:
    - câte vehicule ne trebuie pe baza greutății totale
    - câte vehicule ne trebuie pe baza volumului total
    - câte vehicule ne trebuie dacă limităm stopurile per cursă
    
    Minim 1, maxim = numărul de comenzi (worst case: o cursă per comandă).
    """
    clusters_by_kg = math.ceil(total_kg / avg_vehicle_capacity_kg) if avg_vehicle_capacity_kg > 0 else 1
    clusters_by_m3 = math.ceil(total_m3 / avg_vehicle_capacity_m3) if avg_vehicle_capacity_m3 > 0 else 1
    clusters_by_stops = math.ceil(num_orders / max_stops_per_trip)

    num_clusters = max(clusters_by_kg, clusters_by_m3, clusters_by_stops, 1)

    # Nu mai multe clustere decât comenzi
    return min(num_clusters, num_orders)


def cluster_orders(
    coordinates: list[list[float]],
    num_clusters: int,
) -> list[int]:
    """
    Grupează coordonatele în clustere geografice folosind K-means.
    
    Input:
    - coordinates: [[lat1, lon1], [lat2, lon2], ...] — coordonatele comenzilor
    - num_clusters: câte grupuri vrem
    
    Output:
    - labels: [0, 0, 1, 2, 1, 0, ...] — pentru fiecare comandă, clusterul ei
      Comenzile cu același label merg pe aceeași cursă.
    
    Cum funcționează K-means:
    1. Alege random N puncte ca "centre" de cluster
    2. Asignează fiecare comandă la cel mai apropiat centru
    3. Recalculează centrele ca media punctelor din fiecare cluster
    4. Repetă pașii 2-3 până se stabilizează
    
    Rezultat: comenzile apropiate geografic ajung în același cluster.
    """
    if num_clusters <= 1:
        return [0] * len(coordinates)

    coords_array = np.array(coordinates)

    kmeans = KMeans(
        n_clusters=num_clusters,
        random_state=42,      # rezultate reproductibile (important pentru demo/testare)
        n_init=10,            # rulează algoritmul de 10 ori, alege cel mai bun rezultat
    )

    labels = kmeans.fit_predict(coords_array)

    return labels.tolist()