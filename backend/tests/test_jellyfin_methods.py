import pytest

from tasterr.api.auth import auth_methods
from tasterr.settings import PublicConfig, Settings


@pytest.mark.parametrize("url", [None, "http://jellyfin:8096"])
@pytest.mark.parametrize("key", [None, "key-sentinel"])
@pytest.mark.parametrize("secret", [None, "secret-sentinel"])
def test_methods_are_only_booleans(url: str | None, key: str | None, secret: str | None) -> None:
    settings = Settings.model_validate(
        {"jellyfin_internal_url": url, "jellyfin_api_key": key, "tasterr_secret_key": secret}
    )
    assert auth_methods(settings).model_dump() == {
        "plex": False,
        "jellyfin": bool(url and key and secret),
        "seerr": False,
    }
    assert "jellyfin" not in PublicConfig.from_settings(settings).model_dump_json()
