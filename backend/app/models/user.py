import enum
import uuid
from sqlalchemy import String, Boolean, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, FullTimestampMixin


class RoleEnum(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    MANAGER = "MANAGER"
    DISPECER = "DISPECER"
    SOFER = "SOFER"
    CLIENT = "CLIENT"
    GUEST = "GUEST"


class User(UUIDPrimaryKey, FullTimestampMixin, Base):
    __tablename__ = "users"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )  # NULL for SUPER_ADMIN
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(Enum(RoleEnum), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notification_prefs: Mapped[dict | None] = mapped_column(
        JSONB, default=lambda: {"email": True, "sms": False, "push": True}
    )

    # Relationships
    company = relationship("Company", back_populates="users")
    driver_profile = relationship("Driver", back_populates="user", uselist=False)
    invited_by = relationship("User", remote_side="User.id", foreign_keys=[invited_by_id])

    password_reset_tokens = relationship(
    "PasswordResetToken",
    back_populates="user",
    cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"