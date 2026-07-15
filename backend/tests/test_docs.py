"""Living operator documentation stays complete as settings and release commands evolve."""

import re
from pathlib import Path

from tasterr.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
COMPOSE_VARIABLES = {
    "TASTERR_MEDIA_NETWORK",
    "TASTERR_IMAGE",
    "TASTERR_HTTP_PORT",
    "TASTERR_ENV_FILE",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_example_variables() -> set[str]:
    return {
        line.removeprefix("#").split("=", 1)[0].strip()
        for line in _read(ROOT / ".env.example").splitlines()
        if "=" in line and not line.lstrip().startswith("# ")
    }


def test_configuration_documents_every_app_and_compose_variable() -> None:
    configuration = _read(DOCS / "CONFIGURATION.md")
    expected = {name.upper() for name in Settings.model_fields} | COMPOSE_VARIABLES

    assert expected == _env_example_variables()
    missing = {name for name in expected if f"`{name}`" not in configuration}
    assert not missing, f"CONFIGURATION.md is missing: {sorted(missing)}"


def test_readme_links_every_living_operator_document() -> None:
    readme = _read(ROOT / "README.md")

    for target in (
        "docs/CONFIGURATION.md",
        "docs/ARCHITECTURE.md",
        "SECURITY.md",
        "docs/SECURITY.md",
        "docs/RELEASING.md",
    ):
        assert f"]({target})" in readme
    assert "docker compose up -d --build" in readme
    assert "SEERR_INTERNAL_URL" in readme
    assert "A shared Docker network is not required" in readme

    configuration = _read(DOCS / "CONFIGURATION.md")
    assert "docker-compose.seerr-network.yml" in configuration
    assert "Docker networks do not span hosts" in configuration


def test_architecture_pins_enforced_boundaries_and_degradation() -> None:
    architecture = _read(DOCS / "ARCHITECTURE.md")

    for term in (
        "Only `backend/src/tasterr/clients/`",
        "Only `backend/src/tasterr/api/`",
        "`PublicConfig`",
        "SQLite",
        "in-process",
        "`just types`",
        "Seerr unconfigured/down",
    ):
        assert term in architecture


def test_release_check_is_deterministic_and_keeps_external_checks_explicit() -> None:
    justfile = _read(ROOT / "justfile")
    match = re.search(r"(?m)^release-check:\n(?P<body>(?:    .+\n?)+)", justfile)
    assert match is not None
    body = match.group("body")

    assert body.index("just check") < body.index("just e2e") < body.index("just container-smoke")
    assert "audit" not in body
    assert "test-live" not in body

    releasing = _read(DOCS / "RELEASING.md")
    assert "just release-check" in releasing
    assert "just audit" in releasing
    assert "just test-live" in releasing
    assert "v1.0.0" in releasing
    assert "archive m6-hardening-release" in releasing


def test_public_security_policy_is_private_and_actionable() -> None:
    policy = _read(ROOT / "SECURITY.md")
    engineering = _read(DOCS / "SECURITY.md")

    assert "1.0.x" in policy
    assert "Security → Advisories → Report a vulnerability" in policy
    assert "Do not open a public issue" in policy
    assert "three business days" in policy
    assert "private vulnerability reporting" in engineering
    assert "Secret scanning" in engineering
    assert "Dependabot alerts" in engineering
