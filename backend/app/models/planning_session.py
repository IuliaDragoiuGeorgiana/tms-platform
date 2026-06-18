import enum
from sqlalchemy import Integer, Enum, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class PlanningStrategyEnum(str, enum.Enum):
    GREEDY_DEADLINE = "GREEDY_DEADLINE"
    MAX_DENSITY = "MAX_DENSITY"
    HYBRID = "HYBRID"
    AD_HOC = "AD_HOC"


class PlanningStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class PlanningSession(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "planning_sessions"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    date_range_start: Mapped[str] = mapped_column(Date, nullable=False)
    date_range_end: Mapped[str] = mapped_column(Date, nullable=False)
    strategy: Mapped[PlanningStrategyEnum] = mapped_column(
        Enum(PlanningStrategyEnum), default=PlanningStrategyEnum.HYBRID, nullable=False
    )
    status: Mapped[PlanningStatusEnum] = mapped_column(
        Enum(PlanningStatusEnum), default=PlanningStatusEnum.DRAFT, nullable=False
    )
    total_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    optimization_stats: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    company = relationship("Company", back_populates="planning_sessions")
    created_by_user = relationship("User", foreign_keys=[created_by])
    trips = relationship("Trip", back_populates="planning_session")

    def __repr__(self) -> str:
        return f"<PlanningSession {self.date_range_start}→{self.date_range_end} ({self.status.value})>"
