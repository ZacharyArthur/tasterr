# PyYAML is a runtime transitive dependency without inline typing; this test only
# asks it to parse trusted repository files, then performs typed text assertions.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

"""Delivery workflow contracts: triggers, least privilege, pins, and commands."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_REF = re.compile(r"uses:\s+[^@\s]+@(?P<sha>[0-9a-f]{40})\s+#\s+v[^\s]+\s*$")


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_repository_has_only_gate_and_image_workflows() -> None:
    assert {path.name for path in WORKFLOWS.glob("*.yml")} == {"gate.yml", "image.yml"}


def test_workflows_are_valid_yaml() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None


def test_every_third_party_action_is_immutable_and_versioned() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        uses_lines = [
            line for line in path.read_text(encoding="utf-8").splitlines() if "uses:" in line
        ]
        assert uses_lines, f"{path.name} has no actions"
        for line in uses_lines:
            match = ACTION_REF.search(line)
            assert match is not None, f"mutable or undocumented action ref: {line.strip()}"
            assert len(match.group("sha")) == 40


def test_pull_request_gate_runs_all_blocking_local_contracts() -> None:
    gate = _text("gate.yml")

    assert "pull_request:" in gate
    assert "\n  push:" not in gate
    assert "permissions:\n  contents: read" in gate
    assert "  check:" in gate
    assert "  e2e:" in gate
    assert "  container-smoke:" in gate
    assert "just check" in gate
    assert "just e2e" in gate
    assert "just container-smoke" in gate
    assert "npx playwright install --with-deps chromium" in gate


def test_image_workflow_publishes_only_after_native_smoke() -> None:
    image = _text("image.yml")

    assert "pull_request:" not in image
    assert "branches:\n      - main" in image
    assert 'tags:\n      - "v*"' in image
    assert "permissions:\n  contents: read" in image
    assert "needs: smoke" in image
    assert image.index("just container-smoke") < image.index("docker/login-action")
    assert "fetch-depth: 0" in image
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+$" in image
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main' in image
    assert "packages: write" in image
    assert "platforms: linux/amd64,linux/arm64" in image
    assert "type=raw,value=main" in image
    sha_rules = [line.strip() for line in image.splitlines() if line.strip().startswith("type=sha")]
    assert sha_rules == [
        "type=sha,format=long,prefix=sha-,enable=${{ github.ref == 'refs/heads/main' }}"
    ]
    assert "type=semver,pattern={{version}}" in image
    assert "type=semver,pattern={{major}}.{{minor}}" in image
    assert "type=semver,pattern={{major}}" in image
    assert "type=raw,value=latest" in image
    assert "build-args:" not in image
