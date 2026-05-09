import enum
from sqlalchemy import String, Enum, ForeignKey, Date, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class VehicleTypeEnum(str, enum.Enum):
    VAN = "VAN"
    TRUCK = "TRUCK"
    CAR = "CAR"


class VehicleStatusEnum(str, enum.Enum):
    DISPONIBIL = "DISPONIBIL"
    AVARIAT = "AVARIAT"
    SERVICE = "SERVICE"
    REZERVAT = "REZERVAT"


class FuelTypeEnum(str, enum.Enum):
    DIESEL = "DIESEL"
    GASOLINE = "GASOLINE"
    ELECTRIC = "ELECTRIC"
    HYBRID = "HYBRID"


class Vehicle(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "vehicles"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    plate: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    capacity_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    capacity_m3: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    type: Mapped[VehicleTypeEnum] = mapped_column(Enum(VehicleTypeEnum), nullable=False)
    status: Mapped[VehicleStatusEnum] = mapped_column(
        Enum(VehicleStatusEnum), default=VehicleStatusEnum.DISPONIBIL, nullable=False
    )
    itp_expiry: Mapped[str | None] = mapped_column(Date, nullable=True)
    fuel_type: Mapped[FuelTypeEnum] = mapped_column(
        Enum(FuelTypeEnum), default=FuelTypeEnum.DIESEL, nullable=False
    )
    avg_consumption: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="vehicles")
    driver = relationship("Driver", back_populates="vehicle", uselist=False)
    trips = relationship("Trip", back_populates="vehicle")

    def __repr__(self) -> str:
        return f"<Vehicle {self.plate} ({self.type.value})>"
