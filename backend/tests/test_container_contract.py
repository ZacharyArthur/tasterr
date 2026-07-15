"""Static and Compose-rendered contracts for the production container smoke."""

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
SMOKE = ROOT / "scripts" / "container-smoke.sh"


class ComposeMount(BaseModel):
    type: str
    source: str
    target: str


class ComposeService(BaseModel):
    image: str
    volumes: list[ComposeMount]
    networks: dict[str, object | None]


class ComposeNetwork(BaseModel):
    name: str
    external: bool = False


class ComposeConfig(BaseModel):
    services: dict[str, ComposeService]
    networks: dict[str, ComposeNetwork]


def _write_compose_env(tmp_path: Path, *, network_name: str | None = None) -> Path:
    env_file = tmp_path / "placeholder.env"
    values = [
        "TMDB_API_KEY=placeholder",
        "SEERR_INTERNAL_URL=http://seerr.invalid:5055",
        "SEERR_EXTERNAL_URL=https://seerr.invalid",
        "SEERR_API_KEY=placeholder",
        "TASTERR_SECRET_KEY=placeholder",
        "TASTERR_IMAGE=tasterr:contract",
        "TASTERR_HTTP_PORT=0",
        f"TASTERR_ENV_FILE={env_file}",
    ]
    if network_name is not None:
        values.append(f"TASTERR_MEDIA_NETWORK={network_name}")
    env_file.write_text("\n".join(values) + "\n", encoding="utf-8")
    return env_file


def _run_compose_config(
    env_file: Path, *, external_network: bool, check: bool
) -> subprocess.CompletedProcess[str]:
    compose_files = ["-f", "docker-compose.yml"]
    if external_network:
        compose_files.extend(("-f", "docker-compose.seerr-network.yml"))
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
        env=os.environ.copy(),
        check=check,
        capture_output=True,
        text=True,
    )


def _compose_config(tmp_path: Path, *, external_network: bool) -> ComposeConfig:
    env_file = _write_compose_env(
        tmp_path,
        network_name="contract-media" if external_network else None,
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

    assert "USER app" in dockerfile
    assert "ARG " not in dockerfile
    assert "npm ci" in dockerfile
    assert dockerfile.count("uv sync --frozen") == 2
    assert "COPY .env" not in dockerfile
    assert "COPY backend/scripts" not in dockerfile

    assert "trap cleanup EXIT INT TERM" in smoke
    assert "mktemp" in smoke
    assert 'project="tasterr-smoke-${suffix}"' in smoke
    assert "container-smoke-placeholder" in smoke
    assert "compose up --detach --no-build --force-recreate tasterr" in smoke
    assert "docker image rm --force" in smoke
    assert "docker network rm" in smoke
    assert "docker network create" not in smoke
    assert "TASTERR_MEDIA_NETWORK" not in smoke
    assert "--volumes --remove-orphans" in smoke
    assert "cat .env" not in smoke
    assert "source .env" not in smoke
