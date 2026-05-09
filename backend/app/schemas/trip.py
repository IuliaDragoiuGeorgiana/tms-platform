import uuid
from datetime import date, datetime
from pydantic import BaseModel


class TripResponse(BaseModel):
    """Datele unei curse returnate de API."""
    id: uuid.UUID
    company_id: uuid.UUID
    driver_id: uuid.UUID | None
    vehicle_id: uuid.UUID | None
    planned_date: date
    status: str
    planned_km: float | None
    actual_km: float | None
    planned_duration_min: int | None
    actual_duration_min: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TripStopResponse(BaseModel):
    """Datele unui stop returnate de API."""
    id: uuid.UUID
    trip_id: uuid.UUID
    order_id: uuid.UUID
    sequence: int
    stop_type: str
    eta_planned: datetime | None
    eta_actual: datetime | None
    arrival_time: datetime | None
    departure_time: datetime | None
    status: str
    failure_reason: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class CompleteStopRequest(BaseModel):
    """Ce trimite SOFERUL când finalizează un stop (pickup sau delivery)."""
    notes: str | None = None


class FailStopRequest(BaseModel):
    """Ce trimite SOFERUL când un stop eșuează."""
    failure_reason: str    # ABSENT / REFUSED / WRONG_ADDRESS / DAMAGED / OTHER
    notes: str | None = None