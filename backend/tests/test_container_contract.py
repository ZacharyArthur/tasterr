"""Static and Compose-rendered contracts for the production container smoke."""

import os
import re
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel
from tests.test_docs import ENVIRONMENT_VARIABLES
from tests.test_release_version import VERSION

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
SMOKE = ROOT / "scripts" / "container-smoke.sh"


class ComposeMount(BaseModel):
    type: str
    source: str
    target: str


class ComposePort(BaseModel):
    mode: str
    target: int
    published: str
    protocol: str
    host_ip: str | None = None


class ComposeService(BaseModel):
    image: str
    volumes: list[ComposeMount]
    networks: dict[str, object | None]
    ports: list[ComposePort]
    environment: dict[str, str | None]


class ComposeNetwork(BaseModel):
    name: str
    external: bool = False


class ComposeConfig(BaseModel):
    services: dict[str, ComposeService]
    networks: dict[str, ComposeNetwork]


def _write_compose_env(
    tmp_path: Path,
    *,
    network_name: str | None = None,
    http_port: str | None = None,
    port: int | None = None,
) -> Path:
    env_file = tmp_path / "placeholder.env"
    values = [
        "TMDB_API_KEY=placeholder",
        "SEERR_INTERNAL_URL=http://seerr.invalid:5055",
        "SEERR_EXTERNAL_URL=https://seerr.invalid",
        "SEERR_API_KEY=placeholder",
        "TASTERR_SECRET_KEY=placeholder",
        "TASTERR_IMAGE=tasterr:contract",
        f"TASTERR_ENV_FILE={env_file}",
    ]
    if http_port is not None:
        values.append(f"TASTERR_HTTP_PORT={http_port}")
    if port is not None:
        values.append(f"TASTERR_PORT={port}")
    if network_name is not None:
        values.append(f"TASTERR_MEDIA_NETWORK={network_name}")
    env_file.write_text("\n".join(values) + "\n", encoding="utf-8")
    return env_file


def _run_compose_config(
    env_file: Path,
    *,
    external_network: bool,
    check: bool,
    compose_file: str = "docker-compose.yml",
    shell_port: str | None = None,
) -> subprocess.CompletedProcess[str]:
    compose_files = ["-f", compose_file]
    if external_network:
        compose_files.extend(("-f", "docker-compose.seerr-network.yml"))
    environment = {
        key: value for key, value in os.environ.items() if key.upper() not in ENVIRONMENT_VARIABLES
    }
    if shell_port is not None:
        environment["TASTERR_PORT"] = shell_port
    return subprocess.run(
        [
            "docker",
            "compose",
            *compose_files,
            "--project-name",
            "tasterr-contract",
            "--env-file",
            str(env_file),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("external_network", [False, True])
def test_published_compose_renders_with_placeholder_environment(
    tmp_path: Path, external_network: bool
) -> None:
    env_file = _write_compose_env(
        tmp_path, network_name="contract-media" if external_network else None
    )
    # Exercise the example's pinned default rather than the source-image override.
    env_file.write_text(
        env_file.read_text().replace("TASTERR_IMAGE=tasterr:contract\n", ""), encoding="utf-8"
    )
    result = _run_compose_config(
        env_file, external_network=external_network, check=True, compose_file="compose.example.yaml"
    )
    config = ComposeConfig.model_validate_json(result.stdout)
    assert set(config.services) == {"tasterr"}
    service = config.services["tasterr"]
    assert service.image == f"ghcr.io/zacharyarthur/tasterr:{VERSION}"
    assert service.ports[0].host_ip == "127.0.0.1"
    assert service.ports[0].target == 8000
    assert any(mount.target == "/data" and mount.type == "volume" for mount in service.volumes)
    assert service.environment["TMDB_API_KEY"] == "placeholder"
    assert service.environment["TASTERR_SECRET_KEY"] == "placeholder"
    # Passed only through env_file, not the example's environment mapping.
    assert service.environment["SEERR_API_KEY"] == "placeholder"
    if external_network:
        assert config.networks["seerr"] == ComposeNetwork(name="contract-media", external=True)
    else:
        assert set(service.networks) == {"default"}


@pytest.mark.parametrize("required", ["TMDB_API_KEY", "TASTERR_SECRET_KEY"])
def test_published_compose_rejects_missing_required_values(tmp_path: Path, required: str) -> None:
    env_file = _write_compose_env(tmp_path)
    env_file.write_text(
        env_file.read_text().replace(f"{required}=placeholder\n", f"{required}=\n"),
        encoding="utf-8",
    )
    result = _run_compose_config(
        env_file, external_network=False, check=False, compose_file="compose.example.yaml"
    )

    assert result.returncode != 0
    assert required in result.stderr


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "compose.example.yaml"])
def test_compose_contract_ignores_exported_deployment_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compose_file: str
) -> None:
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "invented-shell-value")
    env_file = _write_compose_env(tmp_path)
    result = _run_compose_config(
        env_file, external_network=False, check=True, compose_file=compose_file
    )

    assert "invented-shell-value" not in result.stdout + result.stderr
    service = ComposeConfig.model_validate_json(result.stdout).services["tasterr"]
    assert service.environment["TMDB_API_KEY"] == "placeholder"
    assert service.environment["TASTERR_SECRET_KEY"] == "placeholder"
    assert service.image == "tasterr:contract"
    assert service.ports[0].host_ip == "127.0.0.1"


def test_published_compose_supports_inline_nonsecret_and_env_port(tmp_path: Path) -> None:
    env_file = _write_compose_env(tmp_path)
    with env_file.open("a", encoding="utf-8") as file:
        file.write("TASTERR_PORT=9000\nSTATIC_DIR=/unused-from-env-file\n")
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text(
        (ROOT / "compose.example.yaml")
        .read_text(encoding="utf-8")
        .replace('# STATIC_DIR: "/app/static"', 'STATIC_DIR: "/app/static"'),
        encoding="utf-8",
    )
    result = _run_compose_config(
        env_file, external_network=False, check=True, compose_file=str(compose_file)
    )
    service = ComposeConfig.model_validate_json(result.stdout).services["tasterr"]

    assert service.environment["STATIC_DIR"] == "/app/static"
    assert service.environment["TASTERR_PORT"] == "9000"
    assert service.ports[0].target == 9000


def _compose_config(
    tmp_path: Path, *, external_network: bool, http_port: str | None = None
) -> ComposeConfig:
    env_file = _write_compose_env(
        tmp_path,
        network_name="contract-media" if external_network else None,
        http_port=http_port,
    )
    result = _run_compose_config(env_file, external_network=external_network, check=True)
    return ComposeConfig.model_validate_json(result.stdout)


def test_compose_uses_managed_default_network_and_keeps_one_service(tmp_path: Path) -> None:
    config = _compose_config(tmp_path, external_network=False)

    assert set(config.services) == {"tasterr"}
    service = config.services["tasterr"]
    assert service.image == "tasterr:contract"
    assert set(service.networks) == {"default"}
    assert any(
        mount.type == "volume" and mount.source == "tasterr-data" and mount.target == "/data"
        for mount in service.volumes
    )
    assert config.networks["default"] == ComposeNetwork(name="tasterr-contract_default")
    assert service.ports == [
        ComposePort(
            mode="ingress",
            target=8000,
            published="8000",
            protocol="tcp",
            host_ip="127.0.0.1",
        )
    ]


@pytest.mark.parametrize(
    ("env_port", "shell_port", "expected_port"),
    [(None, None, 8000), (9000, None, 9000), (9000, "9100", 9100)],
)
def test_source_compose_aligns_listener_and_target_ports(
    tmp_path: Path, env_port: int | None, shell_port: str | None, expected_port: int
) -> None:
    env_file = _write_compose_env(tmp_path, port=env_port)
    result = _run_compose_config(
        env_file, external_network=False, check=True, shell_port=shell_port
    )
    service = ComposeConfig.model_validate_json(result.stdout).services["tasterr"]

    assert service.environment["TASTERR_PORT"] == str(expected_port)
    assert service.ports[0].target == expected_port
    assert service.ports[0].published == "8000"
    assert service.ports[0].host_ip == "127.0.0.1"
    assert service.environment["SEERR_API_KEY"] == "placeholder"


@pytest.mark.parametrize(
    ("http_port", "host_ip", "published"),
    [
        ("8000", None, "8000"),
        ("127.0.0.1:8080", "127.0.0.1", "8080"),
        ("192.0.2.10:8080", "192.0.2.10", "8080"),
    ],
)
def test_explicit_port_override_changes_only_host_publication(
    tmp_path: Path, http_port: str, host_ip: str | None, published: str
) -> None:
    config = _compose_config(tmp_path, external_network=False, http_port=http_port)

    service = config.services["tasterr"]
    assert service.environment["TASTERR_PORT"] == "8000"
    port = service.ports[0]
    assert port.target == 8000
    assert port.published == published
    assert port.host_ip == host_ip


def test_optional_override_joins_existing_seerr_network(tmp_path: Path) -> None:
    config = _compose_config(tmp_path, external_network=True)

    assert set(config.services) == {"tasterr"}
    assert set(config.services["tasterr"].networks) == {"seerr"}
    assert config.networks["seerr"] == ComposeNetwork(name="contract-media", external=True)


def test_optional_override_requires_network_name(tmp_path: Path) -> None:
    env_file = _write_compose_env(tmp_path)

    result = _run_compose_config(env_file, external_network=True, check=False)

    assert result.returncode != 0
    assert "TASTERR_MEDIA_NETWORK" in result.stderr


def test_dockerfile_and_smoke_are_fail_closed() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    smoke = SMOKE.read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    image_refs = [line.split()[1] for line in from_lines]
    stage_names = {line.split()[-1] for line in from_lines if " AS " in line}
    copy_sources = {
        line.removeprefix("COPY --from=").split()[0]
        for line in dockerfile.splitlines()
        if line.startswith("COPY --from=")
    }

    assert "USER app" in dockerfile
    assert len(image_refs) == 3
    assert all(re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", ref) for ref in image_refs)
    assert copy_sources <= stage_names
    assert "ARG " not in dockerfile
    assert "npm ci" in dockerfile
    assert dockerfile.count("uv sync --frozen") == 2
    assert "COPY .env" not in dockerfile
    assert "COPY backend/scripts" not in dockerfile
    assert "COPY LICENSE /usr/share/licenses/tasterr/LICENSE" in dockerfile

    assert "trap cleanup EXIT INT TERM" in smoke
    assert "export TASTERR_PORT=8000" in smoke
    assert "mktemp" in smoke
    assert 'project="tasterr-smoke-${suffix}"' in smoke
    assert "container-smoke-placeholder" in smoke
    assert "compose up --detach --no-build --force-recreate tasterr" in smoke
    assert "docker image rm --force" in smoke
    assert "docker network rm" in smoke
    assert "docker network create" not in smoke
    assert "TASTERR_MEDIA_NETWORK" not in smoke
    assert "TASTERR_HTTP_PORT=0" in smoke
    assert "test -f /usr/share/licenses/tasterr/LICENSE" in smoke
    assert "container-smoke-private-query" in smoke
    assert "request query leaked into logs" in smoke
    assert "X-Frame-Options" in smoke
    assert "Strict-Transport-Security" in smoke
    assert "--volumes --remove-orphans" in smoke
    assert "cat .env" not in smoke
    assert "source .env" not in smoke
