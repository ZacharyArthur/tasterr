from pathlib import Path

import pytest
from pydantic import ValidationError

from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings


def test_discovery_environment_overrides_include_false_and_empty(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = RuntimeSettings(hide_library_items=True, excluded_service_ids=[8])
    assert Settings().resolve_runtime(stored) == stored
    monkeypatch.setenv("TASTERR_HIDE_LIBRARY_ITEMS", "false")
    monkeypatch.setenv("TASTERR_EXCLUDED_SERVICE_IDS", "[]")
    settings = Settings()
    resolved = settings.resolve_runtime(stored)
    assert resolved.hide_library_items is False
    assert resolved.excluded_service_ids == []
    assert settings.locked_discovery_fields == ["hide_library_items", "excluded_service_ids"]
    assert stored.hide_library_items is True
    assert stored.excluded_service_ids == [8]


@pytest.mark.parametrize(
    "value", ["[0]", "[8,8]", "[1,2,3,4,5,6,7,8,9]", "null", "", "8", "[true]", '["8"]', "[8.0]"]
)
def test_discovery_environment_rejects_invalid_ids(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TASTERR_EXCLUDED_SERVICE_IDS", value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("value", ["", "null"])
def test_library_override_rejects_invalid_values(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TASTERR_HIDE_LIBRARY_ITEMS", value)
    with pytest.raises(ValidationError):
        Settings()


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
    "TASTERR_FORWARDED_ALLOW_IPS",
    "TASTERR_PLEX_MAX_CONNECTION_PROBES",
    "TASTERR_HIDE_LIBRARY_ITEMS",
    "TASTERR_EXCLUDED_SERVICE_IDS",
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
    monkeypatch.setenv("TASTERR_FORWARDED_ALLOW_IPS", "127.0.0.1, 172.20.1.9/16")

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
    assert settings.tasterr_forwarded_allow_ips == "127.0.0.1,172.20.0.0/16"
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
    assert settings.tasterr_forwarded_allow_ips == "127.0.0.1"
    assert settings.tasterr_plex_max_connection_probes == 6


def test_plex_connection_probe_limit_populates_from_env(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASTERR_PLEX_MAX_CONNECTION_PROBES", "8")

    assert Settings().tasterr_plex_max_connection_probes == 8


@pytest.mark.parametrize("value", ["2", "13"])
def test_plex_connection_probe_limit_rejects_out_of_range_values(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TASTERR_PLEX_MAX_CONNECTION_PROBES", value)

    with pytest.raises(ValidationError):
        Settings()


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


def test_forwarded_allowlist_normalizes_literal_addresses_and_networks(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "TASTERR_FORWARDED_ALLOW_IPS",
        "127.0.0.1, 10.0.0.42, 172.20.1.7/16, 2001:db8::1, 2001:db8:1::abcd/64",
    )

    settings = Settings()

    assert settings.tasterr_forwarded_allow_ips == (
        "127.0.0.1,10.0.0.42,172.20.0.0/16,2001:db8::1,2001:db8:1::/64"
    )


@pytest.mark.parametrize(
    "bad",
    ["", "*", "proxy", "proxy.local", "http://127.0.0.1", "127.0.0.1,,10.0.0.1", "10.0.0.0/99"],
)
def test_forwarded_allowlist_rejects_unsafe_entries(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("TASTERR_FORWARDED_ALLOW_IPS", bad)

    with pytest.raises(ValidationError):
        Settings()
