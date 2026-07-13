"""Regression test for the secrets-never-reach-the-client invariant (SPEC §1)."""

from pathlib import Path
from typing import cast

from pydantic import SecretStr

from tasterr.runtime_settings import Accent, Appearance, RuntimeSettings, Theme
from tasterr.settings import PublicConfig, Settings

SECRET_MARKERS = (
    "key",
    "secret",
    "token",
    "internal",
    "password",
    "cookie",
    "credential",
    "bearer",
    "connection",
)
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


# Fields allowed to reach the client or that are non-sensitive operational
# knobs. Every other Settings field is sentineled automatically below, so a new
# field must either be added here (a reviewed decision) or it gets a sentinel —
# the test cannot drift from the model.
CLIENT_SAFE_FIELDS = {
    "seerr_external_url",  # client-visible by design (SPEC §9 redirects)
    "tasterr_host",
    "tasterr_port",
    "static_dir",
}


def _sentineled_settings() -> Settings:
    values: dict[str, object] = {}
    for name, field in Settings.model_fields.items():
        if name in CLIENT_SAFE_FIELDS:
            continue
        annotation = str(field.annotation)
        if "SecretStr" in annotation:
            values[name] = SecretStr(f"{SENTINEL}-{name}")
        elif "Path" in annotation:
            values[name] = Path(f"{SENTINEL}-{name}/file")
        else:
            values[name] = f"{SENTINEL}-{name}"
    return Settings.model_validate(values)


def test_serialized_output_contains_no_secret_values() -> None:
    runtime = RuntimeSettings(
        region="GB",
        service_ids=[8],
        appearance=Appearance(theme=Theme.LIGHT, accent=Accent.AZURE),
    )
    dumped = PublicConfig.from_settings(_sentineled_settings(), runtime).model_dump_json()

    assert SENTINEL not in dumped
    assert '"theme":"light"' in dumped
    assert '"accent":"azure"' in dumped
    assert "service_ids" not in dumped


def test_public_config_has_no_secretstr_fields() -> None:
    """Complements the sentinel check: pydantic masks SecretStr on dump, so a
    projected-but-wrapped secret would never surface a sentinel. Secret-shaped
    fields do not belong in the client projection at all, masked or not.
    """
    for name, field in PublicConfig.model_fields.items():
        assert "SecretStr" not in str(field.annotation), (
            f"SecretStr-typed field {name!r} in PublicConfig"
        )
