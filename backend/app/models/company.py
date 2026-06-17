import enum
from sqlalchemy import String, Boolean, Integer, Enum, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, FullTimestampMixin
from app.models.user import RoleEnum


class PlanEnum(str, enum.Enum):
    FREE = "FREE"
    BASIC = "BASIC"
    PRO = "PRO"


class Company(UUIDPrimaryKey, FullTimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    plan: Mapped[PlanEnum] = mapped_column(Enum(PlanEnum), default=PlanEnum.FREE, nullable=False)
    max_vehicles: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    settings: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    depot_county: Mapped[str | None] = mapped_column(String(100), nullable=True)
    depot_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    depot_street: Mapped[str | None] = mapped_column(String(150), nullable=True)
    depot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    depot_lat: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    depot_lon: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Relationships
    users = relationship("User", back_populates="company", lazy="selectin")
    vehicles = relationship("Vehicle", back_populates="company", lazy="selectin")
    drivers = relationship("Driver", back_populates="company", lazy="selectin")
    orders = relationship("Order", back_populates="company", lazy="selectin")
    planning_sessions = relationship("PlanningSession", back_populates="company", lazy="selectin")
    trips = relationship("Trip", back_populates="company", lazy="selectin")

    @property
    def managers_count(self) -> int:
        return sum(1 for user in self.users if user.role == RoleEnum.MANAGER)

    @property
    def users_count(self) -> int:
        return len(self.users)

    @property
    def dispatchers_count(self) -> int:
        return sum(1 for user in self.users if user.role == RoleEnum.DISPECER)

    @property
    def drivers_count(self) -> int:
        return sum(1 for user in self.users if user.role == RoleEnum.SOFER)

    @property
    def clients_count(self) -> int:
        return sum(1 for user in self.users if user.role == RoleEnum.CLIENT)

    @property
    def vehicles_count(self) -> int:
        return len(self.vehicles)

    def __repr__(self) -> str:
        return f"<Company {self.name} ({self.slug})>"
