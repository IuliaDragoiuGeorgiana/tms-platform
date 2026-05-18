import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKey, FullTimestampMixin


class PasswordResetToken(UUIDPrimaryKey, FullTimestampMixin, Base):
    """
    Token temporar pentru resetarea parolei.

    Tokenul real NU este salvat în baza de date.
    În DB se salvează doar SHA-256(token), conform unei abordări mai sigure:
    dacă baza de date este expusă, tokenurile nu pot fi folosite direct.
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest = 64 caractere
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", back_populates="password_reset_tokens")

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)

        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        return now > expires

    def is_valid(self) -> bool:
        return self.used_at is None and not self.is_expired()

    def __repr__(self) -> str:
        if self.used_at:
            status = "used"
        elif self.is_expired():
            status = "expired"
        else:
            status = "active"

        return f"<PasswordResetToken user_id={self.user_id} status={status}>"