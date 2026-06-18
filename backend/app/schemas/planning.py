"""
Scheme Pydantic pentru endpoint-urile de planificare.

Pydantic = o librărie care validează datele automat.
Când dispecerul trimite o cerere la API, Pydantic verifică
că datele sunt corecte (ex: date_start e o dată validă,
nu un text random). Dacă nu sunt corecte, returnează eroare.

BaseModel = clasa de bază din Pydantic. Fiecare clasă care
moștenește BaseModel devine un "formular" cu validare automată.
"""
from pydantic import BaseModel, field_validator
from datetime import date, time
import uuid


# ============================================
# REQUEST: Ce trimite dispecerul la API
# ============================================

class EligibleOrdersRequest(BaseModel):
    """
    Parametrii pe care dispecerul îi trimite când vrea să vadă
    comenzile disponibile pentru un interval de date.

    Exemplu: date_start = 2026-06-16, date_end = 2026-06-18
    → "arată-mi toate comenzile care pot fi livrate luni-miercuri"
    """
    date_start: date
    date_end: date

    @field_validator("date_end")
    @classmethod
    def end_after_start(cls, v, info):
        """
        Validare: date_end trebuie să fie >= date_start.
        Nu poți planifica de miercuri până luni.

        @field_validator = decorator Pydantic care rulează
        automat această funcție când cineva trimite date_end.
        Dacă validarea eșuează, API-ul returnează eroare 422.
        """
        if "date_start" in info.data and v < info.data["date_start"]:
            raise ValueError("date_end trebuie să fie >= date_start")
        return v


class GeneratePlanRequest(BaseModel):
    """
    Parametrii pentru generarea planului real (după ce dispecerul
    a comparat strategiile și a ales una).

    strategy trebuie să fie una din cele 3 valori acceptate.
    """
    date_start: date
    date_end: date
    strategy: str

    @field_validator("date_end")
    @classmethod
    def end_after_start(cls, v, info):
        if "date_start" in info.data and v < info.data["date_start"]:
            raise ValueError("date_end trebuie să fie >= date_start")
        return v

    @field_validator("strategy")
    @classmethod
    def valid_strategy(cls, v):
        """
        Verifică că strategia e una din cele 3 acceptate.
        Dacă dispecerul trimite "RANDOM_STRATEGY", primește eroare.
        """
        allowed = ["GREEDY_DEADLINE", "MAX_DENSITY", "HYBRID"]
        if v not in allowed:
            raise ValueError(f"Strategia trebuie să fie una din: {allowed}")
        return v


# ============================================
# RESPONSE: Ce primește dispecerul înapoi
# ============================================

class EligibleOrderSummary(BaseModel):
    """
    Rezumatul unei comenzi eligibile — ce vede dispecerul
    în lista de comenzi disponibile pentru planificare.

    Nu trimitem TOATE câmpurile comenzii, doar ce e relevant
    pentru decizia de planificare.
    """
    id: uuid.UUID
    order_ref: str
    client_name: str | None = None
    status: str

    # Adrese - text
    address_pickup: str
    address_delivery: str

    # Adrese - structurate
    pickup_county: str | None = None
    pickup_city: str | None = None
    pickup_street: str | None = None
    pickup_number: str | None = None
    delivery_county: str | None = None
    delivery_city: str | None = None
    delivery_street: str | None = None
    delivery_number: str | None = None

    # Marfă
    kg: float
    m3: float
    type_marfa: str
    priority: str

    # Deadline & flexibilitate
    delivery_deadline: date
    earliest_delivery_date: date | None = None
    flexibility_days: int = 0

    # Time windows
    pickup_time_window_start: time | None = None
    pickup_time_window_end: time | None = None
    delivery_time_window_start: time | None = None
    delivery_time_window_end: time | None = None

    model_config = {"from_attributes": True}


class EligibleOrdersResponse(BaseModel):
    """
    Răspunsul complet pentru endpoint-ul de comenzi eligibile.

    Conține:
    - Lista de comenzi eligibile
    - Rezumatul (câte sunt, kg total, etc.)
    - Intervalul cerut
    """
    date_start: date
    date_end: date
    total_eligible: int
    total_kg: float
    total_m3: float

    # Câte comenzi per prioritate — util pentru dispecer
    # să vadă rapid: "am 3 CRITIC, 5 URGENT, 12 NORMAL"
    by_priority: dict[str, int]

    orders: list[EligibleOrderSummary]


class ChangeDriverRequest(BaseModel):
    """
    Schema pentru schimbarea șoferului pe un trip.

    Dispecerul trimite UUID-ul noului șofer.
    """
    driver_id: uuid.UUID


class ChangeVehicleRequest(BaseModel):
    """
    Schema pentru schimbarea vehiculului pe un trip.

    Dispecerul trimite UUID-ul noului vehicul.
    """
    vehicle_id: uuid.UUID


class AddOrderToTripRequest(BaseModel):
    """
    Schema pentru adăugarea unei comenzi PENDING într-un trip PROPOSED.

    Dispecerul trimite UUID-ul comenzii care trebuie adăugată.
    """
    order_id: uuid.UUID


class AdHocTripRequest(BaseModel):
    """
    Schema pentru preview/create sesiune de planificare ad-hoc.

    Dispecerul selectează:
    - data planificării;
    - șoferul;
    - vehiculul;
    - una sau mai multe comenzi PENDING.

    Sistemul creează automat o PlanningSession (PROPOSED)
    cu un Trip (PROPOSED) atunci când dry_run=False.
    """
    planned_date: date
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    order_ids: list[uuid.UUID]

    @field_validator("order_ids")
    @classmethod
    def order_ids_not_empty(cls, v):
        if not v:
            raise ValueError("Trebuie selectată cel puțin o comandă")
        return v


# Backward compatibility
CreateAdHocTripRequest = AdHocTripRequest
