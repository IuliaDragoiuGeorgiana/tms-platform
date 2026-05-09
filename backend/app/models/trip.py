import enum
from datetime import datetime
from sqlalchemy import Integer, Enum, ForeignKey, Date, DateTime, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class TripStatusEnum(str, enum.Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


class Trip(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "trips"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    driver_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True
    )
    planning_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planning_sessions.id"), nullable=True
    )
    planned_date: Mapped[str] = mapped_column(Date, nullable=False)
    status: Mapped[TripStatusEnum] = mapped_column(
        Enum(TripStatusEnum), default=TripStatusEnum.PROPOSED, nullable=False
    )
    planned_km: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    actual_km: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    planned_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_for_trip_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="trips")
    driver = relationship("Driver", back_populates="trips", foreign_keys=[driver_id])
    vehicle = relationship("Vehicle", back_populates="trips", foreign_keys=[vehicle_id])
    planning_session = relationship("PlanningSession", back_populates="trips")
    recovery_for = relationship("Trip", remote_side="Trip.id", uselist=False)
    stops = relationship("TripStop", back_populates="trip", order_by="TripStop.sequence")
    incidents = relationship(
    "Incident",
    back_populates="trip",
    foreign_keys="Incident.trip_id",
    )
    cost = relationship("TripCost", back_populates="trip", uselist=False)
    chat_messages = relationship("ChatMessage", back_populates="trip")

    def __repr__(self) -> str:
        return f"<Trip {self.planned_date} ({self.status.value})>"
