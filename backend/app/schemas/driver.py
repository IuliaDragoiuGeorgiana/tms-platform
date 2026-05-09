import uuid
from datetime import time
from pydantic import BaseModel


class CreateDriverRequest(BaseModel):
    """
    Crează un profil de șofer pentru un user existent cu rolul SOFER.
    user_id = ID-ul userului care a fost deja creat prin invite.
    Un user SOFER devine șofer operațional doar după ce i se creează
    acest profil cu vehiculul alocat, programul de lucru, etc.
    """
    user_id: uuid.UUID                  # User-ul cu rol SOFER
    vehicle_id: uuid.UUID | None = None # Vehicul alocat (poate fi setat mai târziu)
    shift_start: time | None = None     # Ora început program (ex: 08:00)
    shift_end: time | None = None       # Ora sfârșit program (ex: 17:00)
    max_hours_day: float = 9.0          # Limita legală ore/zi


class UpdateDriverRequest(BaseModel):
    vehicle_id: uuid.UUID | None = None
    shift_start: time | None = None
    shift_end: time | None = None
    max_hours_day: float | None = None
    status: str | None = None           # AVAILABLE / ON_TRIP / OFF_DUTY / BREAK


class DriverResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    shift_start: time | None
    shift_end: time | None
    max_hours_day: float
    hours_driven_today: float
    status: str

    model_config = {"from_attributes": True} 