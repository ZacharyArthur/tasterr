"""Application settings. Secrets and connections are env-only (SPEC §9)."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven configuration. Never stored in the DB, never editable via any API.

    Integration secrets are optional at boot: the app must come up (and report
    itself unconfigured) rather than crash before an admin can see /health.
    """

    model_config = SettingsConfigDict(extra="ignore")

    tmdb_api_key: SecretStr | None = None
    seerr_internal_url: str | None = None
    seerr_external_url: str | None = None
    seerr_api_key: SecretStr | None = None
    tasterr_secret_key: SecretStr | None = None

    database_path: Path = Path("data/tasterr.db")
    static_dir: Path = Path("static")
    tasterr_host: str = "0.0.0.0"
    tasterr_port: int = 8000

    @property
    def tmdb_configured(self) -> bool:
        return self.tmdb_api_key is not None

    @property
    def seerr_configured(self) -> bool:
        return self.seerr_internal_url is not None and self.seerr_api_key is not None


class PublicConfig(BaseModel):
    """The only settings shape ever serialized toward the client.

    Built as an explicit allowlist projection — never by excluding fields from
    Settings — so a new secret field can never leak by default.
    """

    tmdb_configured: bool
    seerr_configured: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "PublicConfig":
        return cls(
            tmdb_configured=settings.tmdb_configured,
            seerr_configured=settings.seerr_configured,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
