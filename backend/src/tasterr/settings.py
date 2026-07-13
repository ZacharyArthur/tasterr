"""Application settings. Secrets and connections are env-only (SPEC §9)."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tasterr.runtime_settings import Appearance, RuntimeSettings


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

    @field_validator("seerr_internal_url", "seerr_external_url")
    @classmethod
    def _http_url_or_none(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Seerr URLs must be http(s) — the external one becomes a client-facing
        redirect (SPEC §9: built from *validated* config). A malformed value
        degrades to unset rather than crashing boot (the M0 resilience rule):
        /health then reports Seerr unconfigured, and no unvalidated string can
        reach an `href` or an outbound request target.

        The external URL additionally rejects embedded credentials
        (`https://user:pass@host`), which would leak into the browser `href`; the
        internal URL is server-side only and may legitimately carry basic-auth for
        a reverse-proxied Seerr."""
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        if info.field_name == "seerr_external_url" and (parsed.username or parsed.password):
            return None
        return value

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
    appearance: Appearance

    @classmethod
    def from_settings(
        cls, settings: Settings, runtime: RuntimeSettings | None = None
    ) -> "PublicConfig":
        resolved = runtime if runtime is not None else RuntimeSettings()
        return cls(
            tmdb_configured=settings.tmdb_configured,
            seerr_configured=settings.seerr_configured,
            appearance=resolved.appearance,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
