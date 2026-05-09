import uuid
from datetime import date
from pydantic import BaseModel


class CreateVehicleRequest(BaseModel):
    """Ce trimite MANAGER-ul când adaugă un vehicul nou în flotă."""
    plate: str                          # Număr înmatriculare (ex: "CJ-01-ABC")
    capacity_kg: float                  # Capacitate maximă greutate
    capacity_m3: float                  # Capacitate maximă volum
    type: str = "VAN"                   # VAN / TRUCK / CAR
    fuel_type: str = "DIESEL"           # DIESEL / GASOLINE / ELECTRIC / HYBRID
    avg_consumption: float | None = None  # litri/100km
    itp_expiry: date | None = None      # Data expirare ITP


class UpdateVehicleRequest(BaseModel):
    """
    Câmpuri opționale — MANAGER actualizează doar ce trimite.
    Toate câmpurile sunt opționale pentru că nu vrei să fii forțat
    să retrimiți tot vehiculul când vrei să schimbi doar statusul.
    """
    plate: str | None = None
    capacity_kg: float | None = None
    capacity_m3: float | None = None
    type: str | None = None
    status: str | None = None           # DISPONIBIL / AVARIAT / SERVICE / REZERVAT
    fuel_type: str | None = None
    avg_consumption: float | None = None
    itp_expiry: date | None = None


class VehicleResponse(BaseModel):
    """Ce returnează API-ul când arată datele unui vehicul."""
    id: uuid.UUID
    company_id: uuid.UUID
    plate: str
    capacity_kg: float
    capacity_m3: float
    type: str
    status: str
    fuel_type: str
    avg_consumption: float | None
    itp_expiry: date | None

    model_config = {"from_attributes": True}