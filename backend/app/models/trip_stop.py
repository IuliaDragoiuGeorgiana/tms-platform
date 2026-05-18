import enum
from datetime import datetime
from sqlalchemy import Integer, Enum, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey

class StopTypeEnum(str, enum.Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"

class StopStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class FailureReasonEnum(str, enum.Enum):
    ABSENT = "ABSENT"
    REFUSED = "REFUSED"
    WRONG_ADDRESS = "WRONG_ADDRESS"
    DAMAGED = "DAMAGED"
    OTHER = "OTHER"


class TripStop(UUIDPrimaryKey, Base):
    __tablename__ = "trip_stops"

    trip_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_type: Mapped[StopTypeEnum] = mapped_column(
        Enum(StopTypeEnum), nullable=False
    )
    eta_planned: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eta_actual: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departure_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[StopStatusEnum] = mapped_column(
        Enum(StopStatusEnum), default=StopStatusEnum.PENDING, nullable=False
    )
    failure_reason: Mapped[FailureReasonEnum | None] = mapped_column(
        Enum(FailureReasonEnum), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    trip = relationship("Trip", back_populates="stops")
    order = relationship("Order", back_populates="trip_stops")
    def __repr__(self) -> str:
        return f"<TripStop #{self.sequence} ({self.status.value})>"
