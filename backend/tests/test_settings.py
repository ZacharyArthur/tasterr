from pathlib import Path

import pytest

from tasterr.settings import Settings

ENV_VARS = (
    "TMDB_API_KEY",
    "SEERR_INTERNAL_URL",
    "SEERR_EXTERNAL_URL",
    "SEERR_API_KEY",
    "TASTERR_SECRET_KEY",
    "DATABASE_PATH",
    "STATIC_DIR",
    "TASTERR_HOST",
    "TASTERR_PORT",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_settings_populate_from_env(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-key-from-env")
    monkeypatch.setenv("SEERR_INTERNAL_URL", "http://seerr:5055")
    monkeypatch.setenv("SEERR_EXTERNAL_URL", "https://requests.example.com")
    monkeypatch.setenv("SEERR_API_KEY", "seerr-key-from-env")
    monkeypatch.setenv("TASTERR_SECRET_KEY", "fernet-key-from-env")
    monkeypatch.setenv("DATABASE_PATH", "custom/tasterr.db")
    monkeypatch.setenv("STATIC_DIR", "built/spa")
    monkeypatch.setenv("TASTERR_HOST", "127.0.0.1")
    monkeypatch.setenv("TASTERR_PORT", "9000")

    settings = Settings()

    assert settings.tmdb_api_key is not None
    assert settings.tmdb_api_key.get_secret_value() == "tmdb-key-from-env"
    assert settings.seerr_internal_url == "http://seerr:5055"
    assert settings.seerr_external_url == "https://requests.example.com"
    assert settings.tasterr_secret_key is not None
    assert settings.tasterr_secret_key.get_secret_value() == "fernet-key-from-env"
    assert settings.database_path == Path("custom/tasterr.db")
    assert settings.static_dir == Path("built/spa")
    assert settings.tasterr_host == "127.0.0.1"
    assert settings.tasterr_port == 9000
    assert settings.tmdb_configured is True
    assert settings.seerr_configured is True


def test_boot_with_nothing_set(clean_env: None) -> None:
    settings = Settings()

    assert settings.tmdb_api_key is None
    assert settings.seerr_api_key is None
    assert settings.tasterr_secret_key is None
    assert settings.tmdb_configured is False
    assert settings.seerr_configured is False
    assert settings.database_path == Path("data/tasterr.db")


def test_secrets_do_not_repr(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-key-from-env")

    settings = Settings()

    assert "tmdb-key-from-env" not in repr(settings)


@pytest.mark.parametrize("bad", ["javascript:alert(1)//", "//evil.example", "not-a-url", "ftp://h"])
def test_non_http_seerr_urls_degrade_to_unset(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    # A malformed Seerr URL must never reach a client-facing redirect or an
    # outbound target — it degrades to unset (SPEC §9 validated config), which
    # also flips seerr_configured off rather than crashing boot.
    monkeypatch.setenv("SEERR_INTERNAL_URL", bad)
    monkeypatch.setenv("SEERR_EXTERNAL_URL", bad)
    monkeypatch.setenv("SEERR_API_KEY", "seerr-key")

    settings = Settings()

    assert settings.seerr_internal_url is None
    assert settings.seerr_external_url is None
    assert settings.seerr_configured is False


def test_valid_http_seerr_urls_pass_through(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEERR_INTERNAL_URL", "http://seerr:5055")
    monkeypatch.setenv("SEERR_EXTERNAL_URL", "https://requests.example.com")

    settings = Settings()

    assert settings.seerr_internal_url == "http://seerr:5055"
    assert settings.seerr_external_url == "https://requests.example.com"


def test_external_url_rejects_embedded_credentials(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Credentials in the external URL would leak into the client-facing href, so it
    # degrades to unset; the internal URL is server-side and may carry basic-auth.
    monkeypatch.setenv("SEERR_EXTERNAL_URL", "https://user:pass@requests.example.com")
    monkeypatch.setenv("SEERR_INTERNAL_URL", "http://user:pass@seerr:5055")

    settings = Settings()

    assert settings.seerr_external_url is None
    assert settings.seerr_internal_url == "http://user:pass@seerr:5055"
