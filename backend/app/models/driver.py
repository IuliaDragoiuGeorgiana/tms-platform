import enum
from sqlalchemy import String, Enum, ForeignKey, Time, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class DriverStatusEnum(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    OFF_DUTY = "OFF_DUTY"
    BREAK = "BREAK"


class Driver(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "drivers"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True
    )
    shift_start: Mapped[str | None] = mapped_column(Time, nullable=True)
    shift_end: Mapped[str | None] = mapped_column(Time, nullable=True)
    max_hours_day: Mapped[float] = mapped_column(Numeric(4, 1), default=9.0, nullable=False)
    hours_driven_today: Mapped[float] = mapped_column(Numeric(4, 1), default=0.0, nullable=False)
    status: Mapped[DriverStatusEnum] = mapped_column(
        Enum(DriverStatusEnum), default=DriverStatusEnum.AVAILABLE, nullable=False
    )
    preferred_zones: Mapped[dict | None] = mapped_column(JSONB, default=list)

    # Relationships
    company = relationship("Company", back_populates="drivers")
    user = relationship("User", back_populates="driver_profile")
    vehicle = relationship("Vehicle", back_populates="driver")
    trips = relationship("Trip", back_populates="driver")

    def __repr__(self) -> str:
        return f"<Driver {self.user_id} ({self.status.value})>"
