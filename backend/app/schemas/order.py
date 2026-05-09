import uuid
from datetime import date, time, datetime
from pydantic import BaseModel


class CreateOrderRequest(BaseModel):
    """
    Ce trimite CLIENT-ul când plasează o comandă de transport.
    Două adrese: de unde preia marfa (pickup) și unde o livrează (delivery).
    """
    # Adresa de PRELUARE
    address_pickup: str                          # "Str. Fabricii 5, București"
    pickup_time_window_start: time | None = None # Când poate fi preluată (start)
    pickup_time_window_end: time | None = None   # Când poate fi preluată (end)

    # Adresa de LIVRARE
    address_delivery: str                        # "Str. Victoriei 12, Cluj-Napoca"
    delivery_time_window_start: time | None = None
    delivery_time_window_end: time | None = None

    # Detalii marfă
    kg: float
    m3: float
    type_marfa: str = "STANDARD"                 # STANDARD / FRAGIL / PERISABIL / ADR
    priority: str = "NORMAL"                     # NORMAL / URGENT / CRITIC

    # Deadline
    delivery_deadline: date                      # Până când trebuie livrată
    earliest_delivery_date: date | None = None   # Cea mai devreme dată posibilă

    # Extra
    special_instructions: str | None = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    order_ref: str
    client_id: uuid.UUID

    # Pickup
    address_pickup: str
    pickup_lat: float | None
    pickup_lon: float | None
    pickup_time_window_start: time | None
    pickup_time_window_end: time | None

    # Delivery
    address_delivery: str
    delivery_lat: float | None
    delivery_lon: float | None
    delivery_time_window_start: time | None
    delivery_time_window_end: time | None

    # Marfă
    kg: float
    m3: float
    type_marfa: str
    priority: str

    # Planning
    delivery_deadline: date
    earliest_delivery_date: date | None
    flexibility_days: int
    assigned_delivery_date: date | None

    # Status
    status: str
    tracking_token: str
    source: str
    attempts_count: int
    special_instructions: str | None
    created_at: datetime

    model_config = {"from_attributes": True}