import enum
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, UUIDPrimaryKey
from sqlalchemy import func

class MessageTypeEnum(str, enum.Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    LOCATION = "LOCATION"
    SYSTEM = "SYSTEM"


class ChatMessage(UUIDPrimaryKey, Base):
    __tablename__ = "chat_messages"

    trip_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False
    )
    sender_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_type: Mapped[MessageTypeEnum] = mapped_column(
        Enum(MessageTypeEnum), default=MessageTypeEnum.TEXT, nullable=False
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    trip = relationship("Trip", back_populates="chat_messages")
    sender = relationship("User", foreign_keys=[sender_id])
