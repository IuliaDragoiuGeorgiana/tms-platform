from datetime import datetime
from sqlalchemy import String, ForeignKey, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDPrimaryKey
from sqlalchemy import func
from datetime import datetime, date


class DailyReport(UUIDPrimaryKey, Base):
    __tablename__ = "daily_reports"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_to_email: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    kpi_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
