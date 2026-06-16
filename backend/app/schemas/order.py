import uuid
from datetime import date, time, datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, field_validator, model_validator

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

    client_id: uuid.UUID | None = None

    
    @field_validator("address_pickup", "address_delivery")
    @classmethod
    def non_empty_address(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Adresele de pickup și delivery sunt obligatorii")

        return value

    @field_validator("kg", "m3")
    @classmethod
    def positive_values(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Greutatea și volumul trebuie să fie valori pozitive")
        return value

    @field_validator("type_marfa")
    @classmethod
    def valid_type_marfa(cls, value: str) -> str:
        allowed = {"STANDARD", "FRAGIL", "PERISABIL", "ADR"}
        value = value.upper()

        if value not in allowed:
            raise ValueError("type_marfa trebuie să fie: STANDARD, FRAGIL, PERISABIL sau ADR")

        return value

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, value: str) -> str:
        allowed = {"NORMAL", "URGENT", "CRITIC"}
        value = value.upper()

        if value not in allowed:
            raise ValueError("priority trebuie să fie: NORMAL, URGENT sau CRITIC")

        return value

    @model_validator(mode="after")
    def validate_dates_and_time_windows(self):

        now = datetime.now(ZoneInfo("Europe/Bucharest"))

        if self.delivery_deadline <  now.date():
            raise ValueError("delivery_deadline nu poate fi în trecut")
        
        if self.delivery_deadline == now.date():
            if self.delivery_time_window_end and self.delivery_time_window_end <= now.time():
                raise ValueError(
                    "Fereastra de livrare pentru ziua de azi a trecut deja"
                )

        if self.earliest_delivery_date and self.earliest_delivery_date > self.delivery_deadline:
            raise ValueError("earliest_delivery_date nu poate fi după delivery_deadline")

        if (
            self.pickup_time_window_start
            and self.pickup_time_window_end
            and self.pickup_time_window_start >= self.pickup_time_window_end
        ):
            raise ValueError("Fereastra orară de pickup este invalidă")

        if (
            self.delivery_time_window_start
            and self.delivery_time_window_end
            and self.delivery_time_window_start >= self.delivery_time_window_end
        ):
            raise ValueError("Fereastra orară de delivery este invalidă")

        return self


class MarkOrderProblematicRequest(BaseModel):
    """Motivul pentru care o comandă este marcată ca problematică."""
    problem_reason: str

class UpdateOrderRequest(BaseModel):
    address_pickup: str | None = None
    pickup_time_window_start: time | None = None
    pickup_time_window_end: time | None = None
    address_delivery: str | None = None
    delivery_time_window_start: time | None = None
    delivery_time_window_end: time | None = None
    kg: float | None = None
    m3: float | None = None
    type_marfa: str | None = None
    priority: str | None = None
    delivery_deadline: date | None = None
    earliest_delivery_date: date | None = None
    special_instructions: str | None = None

    @field_validator("address_pickup", "address_delivery")
    @classmethod
    def non_empty_optional_address(cls, value: str | None) -> str | None:
        if value is None:
            return value

        value = value.strip()

        if not value:
            raise ValueError("Adresele de pickup și delivery sunt obligatorii")

        return value

    @field_validator("kg", "m3")
    @classmethod
    def positive_optional_values(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("Greutatea și volumul trebuie să fie valori pozitive")

        return value

    @field_validator("type_marfa")
    @classmethod
    def valid_optional_type_marfa(cls, value: str | None) -> str | None:
        if value is None:
            return value

        allowed = {"STANDARD", "FRAGIL", "PERISABIL", "ADR"}
        value = value.upper()

        if value not in allowed:
            raise ValueError("type_marfa trebuie să fie: STANDARD, FRAGIL, PERISABIL sau ADR")

        return value

    @field_validator("priority")
    @classmethod
    def valid_optional_priority(cls, value: str | None) -> str | None:
        if value is None:
            return value

        allowed = {"NORMAL", "URGENT", "CRITIC"}
        value = value.upper()

        if value not in allowed:
            raise ValueError("priority trebuie să fie: NORMAL, URGENT sau CRITIC")

        return value

class UpdateOrderServiceTimeRequest(BaseModel):
    """
    Permite Dispecerului/Managerului să ajusteze manual timpul de service
    pentru o comandă înainte de planificare.
    """
    pickup_service_minutes: int
    delivery_service_minutes: int

    @field_validator("pickup_service_minutes", "delivery_service_minutes")
    @classmethod
    def valid_service_time(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Timpul de service trebuie să fie pozitiv")

        if value > 240:
            raise ValueError("Timpul de service nu poate depăși 240 minute")

        return value

class OrderFeasibilityResponse(BaseModel):
    is_feasible: bool
    warnings: list[str]


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

    # Service time
    pickup_service_minutes: int | None
    delivery_service_minutes: int | None
    service_time_source: str

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

    is_problematic: bool
    problem_reason: str | None

    model_config = {"from_attributes": True}
