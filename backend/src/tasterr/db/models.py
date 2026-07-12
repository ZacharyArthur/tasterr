"""ORM models (SPEC §5). Session rows hold hashed tokens and encrypted Plex tokens only."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
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


class Signal(Base):
    """Append-only per-user interaction event (SPEC §5). `weight` is stored
    per row so history keeps the weight it earned if constants are retuned.
    The partial unique index makes the at-most-one-row-per-title kinds
    (toggles + seed) a database guarantee, so concurrent writers — a
    background login-seed racing a reset, or two tabs toggling — cannot
    duplicate a title's influence."""

    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_user_id_kind", "user_id", "kind"),
        Index(
            "ux_signals_unique_per_title",
            "user_id",
            "media_type",
            "tmdb_id",
            "kind",
            unique=True,
            sqlite_where=text("kind IN ('watchlist', 'not_interested', 'seed_request_history')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tmdb_id: Mapped[int]
    media_type: Mapped[str] = mapped_column(String(8))  # 'movie' | 'tv'
    # 'request' | 'watchlist' | 'detail_open' | 'not_interested' | 'seed_request_history'
    kind: Mapped[str] = mapped_column(String(24))
    weight: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class TitleFeatures(Base):
    """Persistent per-title feature-vector cache. `features` is opaque JSON
    text owned by recommend/store.py (SQLite JSON1 is not required)."""

    __tablename__ = "title_features"

    tmdb_id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    features: Mapped[str]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Profile(Base):
    """Materialized per-user taste vector — a pure cache, rebuildable from
    signals alone. `vector` is opaque JSON text owned by recommend/store.py."""

    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[str]
    computed_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
