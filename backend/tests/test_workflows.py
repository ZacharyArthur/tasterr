# PyYAML is a runtime transitive dependency without inline typing; this test only
# asks it to parse trusted repository files, then performs typed text assertions.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

"""Delivery workflow contracts: triggers, least privilege, pins, and commands."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
ACTION_REF = re.compile(r"uses:\s+[^@\s]+@(?P<sha>[0-9a-f]{40})\s+#\s+v[^\s]+\s*$")


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_repository_has_only_gate_and_image_workflows() -> None:
    assert {path.name for path in WORKFLOWS.glob("*.yml")} == {"gate.yml", "image.yml"}


def test_workflows_are_valid_yaml() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None


def test_dependabot_groups_every_repository_ecosystem_weekly() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    group = config["multi-ecosystem-groups"]["dependencies"]

    assert group["schedule"] == {"interval": "weekly"}
    assert group["commit-message"]["prefix"] == "chore(deps)"
    assert {
        (
            update["package-ecosystem"],
            tuple(update.get("directories") or [update["directory"]]),
        )
        for update in config["updates"]
    } == {
        ("uv", ("/backend",)),
        ("npm", ("/frontend",)),
        ("github-actions", ("/",)),
        ("docker", ("/", "/.devcontainer")),
        ("devcontainers", ("/",)),
    }
    assert all(update["patterns"] == ["*"] for update in config["updates"])
    assert all(update["multi-ecosystem-group"] == "dependencies" for update in config["updates"])


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
    jobs = yaml.safe_load(gate)["jobs"]

    assert "pull_request:" in gate
    assert "\n  push:" not in gate
    assert "paths:" not in gate
    assert "paths-ignore:" not in gate
    assert "permissions:\n  contents: read" in gate
    assert "group: gate-${{ github.event.pull_request.number }}" in gate
    assert "cancel-in-progress: true" in gate
    assert {name: job["timeout-minutes"] for name, job in jobs.items()} == {
        "check": 15,
        "e2e": 15,
        "container-smoke": 15,
    }
    assert "  check:" in gate
    assert "  e2e:" in gate
    assert "  container-smoke:" in gate
    assert "just check" in gate
    assert "just e2e" in gate
    assert "just container-smoke" in gate
    assert "npx playwright install --with-deps chromium" in gate


def test_image_workflow_publishes_only_after_native_smoke() -> None:
    image = _text("image.yml")
    image_config = yaml.safe_load(image)
    push_config = image_config[True]["push"]

    assert "pull_request:" not in image
    assert "branches:\n      - main" in image
    assert 'tags:\n      - "v*"' in image
    assert push_config["paths-ignore"] == ["docs/**", "README.md"]
    assert "permissions:\n  contents: read" in image
    assert image_config["concurrency"] == {
        "group": "image-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    assert {name: job["timeout-minutes"] for name, job in image_config["jobs"].items()} == {
        "smoke": 15,
        "publish": 30,
    }
    assert "needs: smoke" in image
    assert image.index("just container-smoke") < image.index("docker/login-action")
    assert "fetch-depth: 0" in image
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+$" in image
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main' in image
    assert "packages: write" in image
    assert "attestations: write" in image
    assert "id-token: write" in image
    assert "id: build" in image
    assert "actions/attest@" in image
    assert "subject-name: ghcr.io/${{ github.repository }}\n" in image
    assert "subject-digest: ${{ steps.build.outputs.digest }}" in image
    assert "push-to-registry: true" in image
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
