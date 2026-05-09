import uuid
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Self-registration — doar pentru CLIENT."""
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    company_slug: str   # slug-ul companiei la care se înregistrează
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class UserResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID | None = None
    email: str
    full_name: str
    role: str
    is_active: bool
    is_approved: bool
    must_change_password: bool

    model_config = {"from_attributes": True}


class InviteUserRequest(BaseModel):
    """Admin/Manager creează cont pentru alt user."""
    email: EmailStr
    full_name: str
    role: str  # MANAGER, DISPECER, SOFER
    company_id: uuid.UUID | None = None  # doar SUPER_ADMIN pune asta; MANAGER o ia din token
    phone: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)