import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator

class CreateCompanyRequest(BaseModel):
    """Ce trimite SUPER_ADMIN când creează o companie nouă."""
    name: str
    slug: str
    plan: str = "FREE"
    max_vehicles: int = 10
    max_users: int = 20

    @field_validator("slug")
    @classmethod
    def slug_alphanumeric(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Slug-ul poate conține doar litere, cifre, - și _")
        return value.lower()

class UpdateCompanyRequest(BaseModel):
    """Ce trimite SUPER_ADMIN când actualizează o companie."""
    name: str | None = None
    is_active: bool | None = None
    plan: str | None = None
    max_vehicles: int | None = None
    max_users: int | None = None


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    plan: str
    max_vehicles: int | None
    max_users: int | None
    managers_count: int = 0
    users_count: int = 0
    dispatchers_count: int = 0
    drivers_count: int = 0
    clients_count: int = 0
    vehicles_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublicCompanyResponse(BaseModel):
    name: str
    slug: str

    model_config = {"from_attributes": True}


class CompanyStatsResponse(BaseModel):
    """Statistici pentru o companie specifică."""
    company_id: uuid.UUID
    company_name: str
    is_active: bool
    total_users: int
    total_managers: int
    total_dispatchers: int
    total_drivers: int
    total_clients: int
    total_vehicles: int
    total_orders: int
    total_trips: int
    plan: str
    max_vehicles: int | None
    max_users: int | None
