"""Local identities, linked accounts, sessions, and taste storage."""

import logging
from datetime import UTC, datetime
from typing import Literal, get_args

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates
from sqlalchemy.types import TypeDecorator

from tasterr.recommend.signals import TasteSource

_SOURCES = TypeAdapter(list[TasteSource])
logger = logging.getLogger("tasterr.db")


class TasteSources(TypeDecorator[list[TasteSource]]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> str:
        return _SOURCES.dump_json(_SOURCES.validate_python(value)).decode()

    def process_result_value(self, value: object, dialect: Dialect) -> list[TasteSource]:
        try:
            if isinstance(value, str):
                return _SOURCES.validate_json(value)
        except ValidationError:
            pass
        logger.warning("taste sources: unreadable preferences")
        return []


Provider = Literal["plex", "jellyfin", "seerr"]
SIGNAL_UNIQUE_INDEX_WHERE = text(
    "kind IN ('watchlist', 'not_interested', 'seed_request_history', "
    "'watched_plex', 'watched_jellyfin')"
)


def utcnow() -> datetime:
    """Naive UTC — SQLite has no timezone type, so naive-UTC is used everywhere."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    avatar_url: Mapped[str | None]
    is_admin: Mapped[bool] = mapped_column(default=False)
    taste_onboarding_seen: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    seerr_unlinked_at: Mapped[datetime | None] = mapped_column(DateTime())
    taste_excluded_sources: Mapped[list[TasteSource]] = mapped_column(
        TasteSources(), default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_linked_accounts_external"),
        UniqueConstraint("user_id", "provider", name="uq_linked_accounts_user_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[Provider] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str]
    avatar_url: Mapped[str | None]
    credential_enc: Mapped[str | None]
    sync_attempted_at: Mapped[datetime | None] = mapped_column(DateTime())
    sync_synced_at: Mapped[datetime | None] = mapped_column(DateTime())
    linked_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    @validates("provider")
    def validate_provider(self, _key: str, value: Provider) -> Provider:
        if value not in get_args(Provider):
            raise ValueError("Unknown account provider")
        return value


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
            sqlite_where=SIGNAL_UNIQUE_INDEX_WHERE,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tmdb_id: Mapped[int]
    media_type: Mapped[str] = mapped_column(String(8))  # 'movie' | 'tv'
    # 'request' | 'watchlist' | 'detail_open' | 'not_interested' |
    # 'seed_request_history' | 'watched_plex' | 'watched_jellyfin'
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


class Setting(Base):
    """One typed, non-secret runtime-settings document (M5).

    The generic-looking table shape mirrors the founding data model, but M5 owns
    exactly one key (``global``); validation and serialization live in
    ``runtime_settings.py``/``db.runtime_settings`` rather than in callers.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
