import enum
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, DateTime, Text, Numeric, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey


class IncidentTypeEnum(str, enum.Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class Incident(UUIDPrimaryKey, Base):
    __tablename__ = "incidents"

    trip_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False
    )
    driver_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False
    )
    type: Mapped[IncidentTypeEnum] = mapped_column(Enum(IncidentTypeEnum), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    location_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_trip_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), nullable=True
    )
    extra_cost_estimated: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    impact_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    trip = relationship("Trip", back_populates="incidents", foreign_keys=[trip_id])
    driver = relationship("Driver", foreign_keys=[driver_id])
    vehicle = relationship("Vehicle", foreign_keys=[vehicle_id])
    recovery_trip = relationship("Trip", foreign_keys=[recovery_trip_id], uselist=False)

    def __repr__(self) -> str:
        return f"<Incident {self.type.value} on trip {self.trip_id}>"
