import enum
from sqlalchemy import String, Boolean, Integer, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, FullTimestampMixin


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

    # Relationships
    users = relationship("User", back_populates="company", lazy="selectin")
    vehicles = relationship("Vehicle", back_populates="company", lazy="selectin")
    drivers = relationship("Driver", back_populates="company", lazy="selectin")
    orders = relationship("Order", back_populates="company", lazy="selectin")
    planning_sessions = relationship("PlanningSession", back_populates="company", lazy="selectin")
    trips = relationship("Trip", back_populates="company", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Company {self.name} ({self.slug})>"
