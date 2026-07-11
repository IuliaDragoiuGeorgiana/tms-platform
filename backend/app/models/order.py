import enum
from datetime import date, time
from sqlalchemy import String, Integer, Enum, ForeignKey, Date, Time, Text, Numeric, Boolean
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


class ServiceTimeSourceEnum(str, enum.Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


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
    pickup_county: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pickup_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pickup_street: Mapped[str | None] = mapped_column(String(150), nullable=True)
    pickup_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pickup_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    pickup_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    # Adresa de LIVRARE (unde duce marfa)
    address_delivery: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_county: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_street: Mapped[str | None] = mapped_column(String(150), nullable=True)
    delivery_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    delivery_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    m3: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    pickup_service_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_service_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    service_time_source: Mapped[ServiceTimeSourceEnum] = mapped_column(
        Enum(ServiceTimeSourceEnum),
        default=ServiceTimeSourceEnum.AUTO,
        nullable=False,
    )

    type_marfa: Mapped[MarfaTypeEnum] = mapped_column(
        Enum(MarfaTypeEnum), default=MarfaTypeEnum.STANDARD, nullable=False
    )
    priority: Mapped[PriorityEnum] = mapped_column(
        Enum(PriorityEnum), default=PriorityEnum.NORMAL, nullable=False
    )

    # Multi-day planning fields
    delivery_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    earliest_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    flexibility_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assigned_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Time window
    # Time window PICKUP (când poate fi preluată marfa)
    pickup_time_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    pickup_time_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Time window DELIVERY (când trebuie livrată)
    delivery_time_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    delivery_time_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[OrderStatusEnum] = mapped_column(
        Enum(OrderStatusEnum), default=OrderStatusEnum.PENDING, nullable=False
    )
    tracking_token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[OrderSourceEnum] = mapped_column(
        Enum(OrderSourceEnum), default=OrderSourceEnum.PORTAL, nullable=False
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_problematic: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    was_postponed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    problem_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    company = relationship("Company", back_populates="orders")
    client = relationship("User", foreign_keys=[client_id])
    trip_stops = relationship(
    "TripStop",
    back_populates="order",
    cascade="all, delete-orphan",
)

    @property
    def company_name(self) -> str | None:
        return self.company.name if self.company else None

    @property
    def client_name(self) -> str | None:
        return self.client.full_name if self.client else None

    def __repr__(self) -> str:
        return f"<Order {self.order_ref} ({self.status.value})>"
