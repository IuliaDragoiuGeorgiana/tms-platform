import enum
from datetime import datetime
from sqlalchemy import String, Enum, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDPrimaryKey


class ConfigDataTypeEnum(str, enum.Enum):
    INT = "INT"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"


class SystemConfig(UUIDPrimaryKey, Base):
    __tablename__ = "system_config"

    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    data_type: Mapped[ConfigDataTypeEnum] = mapped_column(
        Enum(ConfigDataTypeEnum), default=ConfigDataTypeEnum.STRING, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
