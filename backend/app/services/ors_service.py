"""
Serviciu pentru comunicarea cu OpenRouteService API.
Funcții:
1. geocode() — transformă adresa text în coordonate GPS
2. reverse_geocode() — transformă coordonate GPS în adresă structurată
3. geocode_with_components() — geocodează și extrage componente (județ, oraș, stradă, număr)
4. get_distance_matrix() — calculează distanțele și timpii între toate perechile de puncte
"""
import requests
from app.core.config import ORS_API_KEY, ORS_BASE_URL
from typing import Optional


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
    url = f"{ORS_BASE_URL}/v2/matrix/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "locations": coordinates,
        "metrics": ["distance", "duration"],
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        return {
            "distances": data["distances"],    # matrice NxN în metri
            "durations": data["durations"],    # matrice NxN în secunde
        }

    except requests.RequestException as e:
        print(f"Eroare matrice distanțe: {e}")
        return None