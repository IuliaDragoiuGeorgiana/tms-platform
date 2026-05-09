from sqlalchemy import ForeignKey, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey


class TripCost(UUIDPrimaryKey, Base):
    __tablename__ = "trip_costs"

    trip_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), unique=True, nullable=False
    )
    fuel_cost_planned: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    fuel_cost_actual: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    driver_cost_planned: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    driver_cost_actual: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    amortization: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    extra_cost: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    extra_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_planned: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_actual: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Relationships
    trip = relationship("Trip", back_populates="cost")

    def __repr__(self) -> str:
        return f"<TripCost trip={self.trip_id} planned={self.total_planned}>"
