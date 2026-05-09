import uuid
from datetime import datetime
from pydantic import BaseModel


class CreateCompanyRequest(BaseModel):
    """Ce trimite SUPER_ADMIN când creează o companie nouă."""
    name: str                          # Numele companiei (ex: "Transport Rapid SRL")
    slug: str                          # URL-friendly (ex: "transport-rapid")
    plan: str = "FREE"                 # Planul de abonament: FREE / BASIC / PRO
    max_vehicles: int = 10             # Câte vehicule poate avea
    max_users: int = 20                # Câți utilizatori poate avea


class CompanyResponse(BaseModel):
    """Ce returnează API-ul când arată datele unei companii."""
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    plan: str
    max_vehicles: int
    max_users: int
    created_at: datetime

    model_config = {"from_attributes": True}
    # from_attributes = True permite Pydantic să citească direct din obiectul
    # SQLAlchemy (care are atribute, nu dicționar). Fără asta, ar da eroare
    # când încerci să returnezi un obiect Company din DB.