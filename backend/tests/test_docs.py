"""Living operator documentation stays complete as settings and release commands evolve."""

import re
import tomllib
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
    index = _read(ROOT / "frontend" / "index.html")

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
    assert "TASTERR_HTTP_PORT=8000" in readme
    assert "github.com/ZacharyArthur/tasterr/actions/workflows/gate.yml/badge.svg" in readme
    assert "image: ghcr.io/zacharyarthur/tasterr:1.0.0" in readme
    assert '- "127.0.0.1:8000:8000"' in readme
    assert "tasterr-data:/data" in readme
    assert "does not require a\n`.env` file" in readme
    assert "Host variables are not passed into a Compose service automatically" in readme
    assert "      - TMDB_API_KEY" in readme
    assert 'src="frontend/public/favicon.svg"' in readme
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />' in index
    assert (ROOT / "frontend" / "public" / "favicon.svg").is_file()

    for screenshot in ("home.jpg", "detail.jpg", "search.jpg"):
        path = DOCS / "screenshots" / screenshot
        assert f'src="docs/screenshots/{screenshot}"' in readme
        assert path.is_file()
        assert path.stat().st_size < 1_000_000

    configuration = _read(DOCS / "CONFIGURATION.md")
    assert "docker-compose.seerr-network.yml" in configuration
    assert "Docker networks do not span hosts" in configuration
    assert "`127.0.0.1:8000`" in configuration
    assert "omit or redact query" in configuration
    assert "application does not parse or require a `.env` file" in configuration
    assert "This is a Compose concern, not an application requirement" in configuration

    releasing = _read(DOCS / "RELEASING.md")
    evidence = _read(DOCS / "releases" / "v1.0.0.md")
    assert "OWNER/REPOSITORY" not in readme + releasing + evidence
    assert "empty **private** `ZacharyArthur/tasterr` repository" in releasing
    assert "`check`, `e2e`, and `container-smoke`" in releasing
    assert "sha-<full-commit>" in releasing
    assert "make the repository public" in releasing
    assert "private vulnerability reporting" in releasing
    assert "do not use a create-and-push shortcut" in releasing


def test_agpl_license_is_declared_consistently() -> None:
    license_text = _read(ROOT / "LICENSE")
    readme = _read(ROOT / "README.md")
    package = tomllib.loads(_read(ROOT / "backend" / "pyproject.toml"))

    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "](LICENSE)" in readme
    assert package["project"]["license"] == "AGPL-3.0-only"


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
    assert "archive v1-public-release-readiness" in releasing


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
