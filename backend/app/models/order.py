import enum
from sqlalchemy import String, Integer, Enum, ForeignKey, Date, Time, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, FullTimestampMixin


class MarfaTypeEnum(str, enum.Enum):
    STANDARD = "STANDARD"
    FRAGIL = "FRAGIL"
    PERISABIL = "PERISABIL"
    ADR = "ADR"


class PriorityEnum(str, enum.Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"
    CRITIC = "CRITIC"


class OrderStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    IN_DELIVERY = "IN_DELIVERY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderSourceEnum(str, enum.Enum):
    PORTAL = "PORTAL"
    PDF = "PDF"
    API = "API"


class Order(UUIDPrimaryKey, FullTimestampMixin, Base):
    __tablename__ = "orders"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    order_ref: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Adresa de PRELUARE (de unde ia marfa)
    address_pickup: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    pickup_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    # Adresa de LIVRARE (unde duce marfa)
    address_delivery: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    delivery_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    m3: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    type_marfa: Mapped[MarfaTypeEnum] = mapped_column(
        Enum(MarfaTypeEnum), default=MarfaTypeEnum.STANDARD, nullable=False
    )
    priority: Mapped[PriorityEnum] = mapped_column(
        Enum(PriorityEnum), default=PriorityEnum.NORMAL, nullable=False
    )

    # Multi-day planning fields
    delivery_deadline: Mapped[str] = mapped_column(Date, nullable=False)
    earliest_delivery_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    flexibility_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assigned_delivery_date: Mapped[str | None] = mapped_column(Date, nullable=True)

    # Time window
    # Time window PICKUP (când poate fi preluată marfa)
    pickup_time_window_start: Mapped[str | None] = mapped_column(Time, nullable=True)
    pickup_time_window_end: Mapped[str | None] = mapped_column(Time, nullable=True)

    # Time window DELIVERY (când trebuie livrată)
    delivery_time_window_start: Mapped[str | None] = mapped_column(Time, nullable=True)
    delivery_time_window_end: Mapped[str | None] = mapped_column(Time, nullable=True)
    status: Mapped[OrderStatusEnum] = mapped_column(
        Enum(OrderStatusEnum), default=OrderStatusEnum.PENDING, nullable=False
    )
    tracking_token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[OrderSourceEnum] = mapped_column(
        Enum(OrderSourceEnum), default=OrderSourceEnum.PORTAL, nullable=False
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    company = relationship("Company", back_populates="orders")
    client = relationship("User", foreign_keys=[client_id])
    trip_stops = relationship(
    "TripStop",
    back_populates="order",
    cascade="all, delete-orphan",
)

    def __repr__(self) -> str:
        return f"<Order {self.order_ref} ({self.status.value})>"
