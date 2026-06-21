"""
Serviciu pentru comunicarea cu OpenRouteService API.
Funcții:
1. geocode() — transformă adresa text în coordonate GPS
2. reverse_geocode() — transformă coordonate GPS în adresă structurată
3. geocode_with_components() — geocodează și extrage componente (județ, oraș, stradă, număr)
4. get_distance_matrix() — calculează distanțele și timpii între toate perechile de puncte
"""
import requests
import math
import os
import threading
import time
from app.core.config import ORS_API_KEY, ORS_BASE_URL
from typing import Optional


ORS_MATRIX_MIN_INTERVAL_SECONDS = float(
    os.getenv("ORS_MATRIX_MIN_INTERVAL_SECONDS", "1.2")
)
ORS_MATRIX_MAX_RETRIES = int(os.getenv("ORS_MATRIX_MAX_RETRIES", "3"))
ORS_MATRIX_FALLBACK_ON_RATE_LIMIT = os.getenv(
    "ORS_MATRIX_FALLBACK_ON_RATE_LIMIT",
    "true",
).lower() == "true"
ORS_MATRIX_FALLBACK_SPEED_KMH = float(
    os.getenv("ORS_MATRIX_FALLBACK_SPEED_KMH", "55")
)
ORS_MATRIX_FALLBACK_ROAD_FACTOR = float(
    os.getenv("ORS_MATRIX_FALLBACK_ROAD_FACTOR", "1.28")
)

_matrix_cache: dict[tuple[tuple[float, float], ...], dict] = {}
_matrix_lock = threading.Lock()
_last_matrix_request_at = 0.0


def _matrix_cache_key(coordinates: list[list[float]]) -> tuple[tuple[float, float], ...]:
    return tuple(
        (round(float(lon), 6), round(float(lat), 6))
        for lon, lat in coordinates
    )


def _copy_matrix_result(result: dict) -> dict:
    return {
        "distances": result["distances"],
        "durations": result["durations"],
        "cache_hit": result.get("cache_hit", False),
        "fallback": result.get("fallback", False),
    }


def _haversine_distance_m(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
) -> float:
    radius_m = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_m * c


def _build_fallback_distance_matrix(coordinates: list[list[float]]) -> dict:
    speed_m_per_s = max(1, ORS_MATRIX_FALLBACK_SPEED_KMH * 1000 / 3600)
    distances = []
    durations = []

    for from_lon, from_lat in coordinates:
        distance_row = []
        duration_row = []

        for to_lon, to_lat in coordinates:
            if from_lon == to_lon and from_lat == to_lat:
                distance_m = 0
            else:
                distance_m = int(
                    _haversine_distance_m(
                        float(from_lon),
                        float(from_lat),
                        float(to_lon),
                        float(to_lat),
                    )
                    * ORS_MATRIX_FALLBACK_ROAD_FACTOR
                )

            distance_row.append(distance_m)
            duration_row.append(int(distance_m / speed_m_per_s))

        distances.append(distance_row)
        durations.append(duration_row)

    return {
        "distances": distances,
        "durations": durations,
        "cache_hit": False,
        "fallback": True,
    }


def geocode(address: str) -> dict | None:
    """
    Transformă o adresă text în coordonate GPS.
    
    Exemplu:
    geocode("Strada Memorandumului 21, Cluj-Napoca")
    → {"lat": 46.7712, "lon": 23.5896}
    
    Returnează None dacă adresa nu e găsită.
    """
    url = f"{ORS_BASE_URL}/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": address,
        "boundary.country": "RO",  # Căutăm doar în România
        "size": 1,                  # Vrem doar primul rezultat (cel mai relevant)
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("features"):
            # GeoJSON returnează coordonatele ca [lon, lat] (inversate!)
            coords = data["features"][0]["geometry"]["coordinates"]
            return {
                "lat": coords[1],  # latitudine = al doilea element
                "lon": coords[0],  # longitudine = primul element
            }
        return None

    except requests.RequestException as e:
        print(f"Eroare geocodare pentru '{address}': {e}")
        return None


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """
    Transformă coordonate GPS în adresă structurată.

    Returnează dict cu componente: {
        "county": "Cluj",
        "city": "Cluj-Napoca",
        "street": "Strada Memorandumului",
        "number": "21",
        "formatted": "...",
    }

    Pentru România, mapare de câmpuri:
    - county: county, region, state
    - city: locality, localadmin, city
    - street: street, name
    - number: housenumber
    """
    url = f"{ORS_BASE_URL}/geocode/reverse"
    params = {
        "api_key": ORS_API_KEY,
        "point.lon": lon,
        "point.lat": lat,
        "boundary.country": "RO",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("features"):
            feature = data["features"][0]
            props = feature.get("properties", {})

            return {
                "county": props.get("county") or props.get("region") or props.get("state"),
                "city": (
                    props.get("locality")
                    or props.get("localadmin")
                    or props.get("city")
                    or props.get("county")
                ),
                "street": props.get("street") or props.get("name"),
                "number": props.get("housenumber"),
                "formatted": props.get("label") or props.get("name") or "",
            }
        return None

    except requests.RequestException as e:
        print(f"Eroare reverse geocodare pentru ({lat}, {lon}): {e}")
        return None


def geocode_with_components(address: str) -> dict | None:
    """
    Geocodează o adresă și extrage componente structurate (județ, oraș, stradă, număr).

    Returnează dict cu: {
        "lat": 46.7712,
        "lon": 23.5896,
        "county": "Cluj",
        "city": "Cluj-Napoca",
        "street": "Strada Memorandumului",
        "number": "21",
    }
    """
    # Getter les coordonate
    coords = geocode(address)
    if not coords:
        return None

    # Cu reverse geocoding, obținem componente structurate
    components = reverse_geocode(coords["lat"], coords["lon"])

    if components:
        return {
            **coords,
            **components,
        }

    # Dacă reverse geocoding eșuează, returnez doar coordonatele
    return coords


def geocode_batch(addresses: list[str]) -> list[dict | None]:
    """
    Geocodează o listă de adrese.
    Returnează o listă de {lat, lon} sau None pentru adresele negăsite.
    """
    results = []
    for address in addresses:
        result = geocode(address)
        results.append(result)
    return results


def geocode_batch_with_components(addresses: list[str]) -> list[dict | None]:
    """
    Geocodează o listă de adrese cu componente structurate.
    Returnează o listă de {lat, lon, county, city, street, number} sau None.
    """
    results = []
    for address in addresses:
        result = geocode_with_components(address)
        results.append(result)
    return results


def get_distance_matrix(
    coordinates: list[list[float]],
) -> dict | None:
    """
    Calculează matricea de distanțe și timpi între toate perechile de puncte.
    
    Input: lista de coordonate [[lon1, lat1], [lon2, lat2], ...]
    ATENȚIE: ORS așteaptă [lon, lat], NU [lat, lon]!
    
    Output: {
        "distances": [[0, 5200, 3100], [5200, 0, 4800], ...],   # metri
        "durations": [[0, 620, 380], [620, 0, 540], ...],       # secunde
    }
    
    Exemplu: distances[0][2] = 3100 înseamnă 3.1 km de la punctul 0 la punctul 2
             durations[0][2] = 380 înseamnă 6.3 minute de la punctul 0 la punctul 2
    """
    global _last_matrix_request_at

    cache_key = _matrix_cache_key(coordinates)
    cached_result = _matrix_cache.get(cache_key)
    if cached_result:
        result = _copy_matrix_result(cached_result)
        result["cache_hit"] = True
        return result

    url = f"{ORS_BASE_URL}/v2/matrix/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "locations": coordinates,
        "metrics": ["distance", "duration"],
    }

    with _matrix_lock:
        cached_result = _matrix_cache.get(cache_key)
        if cached_result:
            result = _copy_matrix_result(cached_result)
            result["cache_hit"] = True
            return result

        for attempt in range(1, ORS_MATRIX_MAX_RETRIES + 1):
            elapsed_since_last = time.monotonic() - _last_matrix_request_at
            wait_seconds = ORS_MATRIX_MIN_INTERVAL_SECONDS - elapsed_since_last
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            try:
                response = requests.post(url, json=body, headers=headers, timeout=30)
                _last_matrix_request_at = time.monotonic()

                if response.status_code == 403 and ORS_MATRIX_FALLBACK_ON_RATE_LIMIT:
                    print(
                        "ORS matrix forbidden; "
                        "using approximate fallback matrix"
                    )
                    result = _build_fallback_distance_matrix(coordinates)
                    _matrix_cache[cache_key] = result
                    return _copy_matrix_result(result)

                if response.status_code == 429:
                    if attempt >= ORS_MATRIX_MAX_RETRIES and ORS_MATRIX_FALLBACK_ON_RATE_LIMIT:
                        print(
                            "ORS matrix rate limit hit; "
                            "using approximate fallback matrix"
                        )
                        result = _build_fallback_distance_matrix(coordinates)
                        _matrix_cache[cache_key] = result
                        return _copy_matrix_result(result)

                    retry_after = response.headers.get("Retry-After")
                    try:
                        backoff_seconds = float(retry_after) if retry_after else 0
                    except ValueError:
                        backoff_seconds = 0

                    if backoff_seconds <= 0:
                        backoff_seconds = ORS_MATRIX_MIN_INTERVAL_SECONDS * attempt * 2

                    print(
                        "ORS matrix rate limit hit; "
                        f"retrying in {backoff_seconds:.1f}s "
                        f"(attempt {attempt}/{ORS_MATRIX_MAX_RETRIES})"
                    )
                    time.sleep(backoff_seconds)
                    continue

                response.raise_for_status()
                data = response.json()

                result = {
                    "distances": data["distances"],    # matrice NxN în metri
                    "durations": data["durations"],    # matrice NxN în secunde
                    "cache_hit": False,
                }
                _matrix_cache[cache_key] = result
                return _copy_matrix_result(result)

            except requests.RequestException as e:
                if attempt < ORS_MATRIX_MAX_RETRIES:
                    backoff_seconds = ORS_MATRIX_MIN_INTERVAL_SECONDS * attempt
                    print(
                        f"Eroare matrice distanțe: {e}; "
                        f"retry in {backoff_seconds:.1f}s "
                        f"(attempt {attempt}/{ORS_MATRIX_MAX_RETRIES})"
                    )
                    time.sleep(backoff_seconds)
                    continue

                print(f"Eroare matrice distanțe: {e}")
                return None

    return None
