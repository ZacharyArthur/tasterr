"""Regression test for the secrets-never-reach-the-client invariant (SPEC §1)."""

from pathlib import Path
from typing import cast

from pydantic import SecretStr

from tasterr.settings import PublicConfig, Settings

SECRET_MARKERS = ("key", "secret", "token", "internal", "password", "cookie")
SENTINEL = "SENTINEL-SECRET-VALUE"


def _property_names(node: object) -> set[str]:
    """Collect every property name in a JSON schema, including nested $defs."""
    names: set[str] = set()
    if isinstance(node, dict):
        typed = cast("dict[object, object]", node)
        properties = typed.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in cast("dict[object, object]", properties))
        for value in typed.values():
            names |= _property_names(value)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            names |= _property_names(item)
    return names


def test_schema_contains_no_secret_field_names() -> None:
    for name in _property_names(PublicConfig.model_json_schema()):
        for marker in SECRET_MARKERS:
            assert marker not in name.lower(), f"secret-looking field {name!r} in PublicConfig"


def test_serialized_output_contains_no_secret_values() -> None:
    # seerr_external_url is deliberately not sentineled: it is client-visible by
    # design (SPEC §9 redirects) and may legitimately join PublicConfig later.
    settings = Settings(
        tmdb_api_key=SecretStr(f"{SENTINEL}-tmdb"),
        seerr_internal_url=f"http://{SENTINEL}-seerr:5055",
        seerr_external_url="https://requests.example.com",
        seerr_api_key=SecretStr(f"{SENTINEL}-seerr-key"),
        tasterr_secret_key=SecretStr(f"{SENTINEL}-fernet"),
        database_path=Path(f"{SENTINEL}/tasterr.db"),
    )

    dumped = PublicConfig.from_settings(settings).model_dump_json()

    assert SENTINEL not in dumped
