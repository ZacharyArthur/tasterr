"""ORM models (SPEC §5). Session rows hold hashed tokens and encrypted Plex tokens only."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC — SQLite has no timezone type, so naive-UTC is used everywhere."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    seerr_user_id: Mapped[int] = mapped_column(unique=True)
    display_name: Mapped[str]
    avatar_url: Mapped[str | None]
    auth_type: Mapped[str] = mapped_column(String(8))  # 'plex' | 'local'
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seerr_cookie: Mapped[str]
    plex_token_enc: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
