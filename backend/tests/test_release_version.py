"""One release version across package metadata and image tag rules."""

import re
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.1.0"


class PackageManifest(BaseModel):
    version: str


def test_package_and_lock_metadata_are_v1() -> None:
    pyproject = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    uv_lock = (ROOT / "backend" / "uv.lock").read_text(encoding="utf-8")
    frontend = PackageManifest.model_validate_json(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    frontend_lock = PackageManifest.model_validate_json(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )

    assert re.search(rf'(?m)^version = "{re.escape(VERSION)}"$', pyproject)
    assert re.search(rf'(?m)^name = "tasterr"\nversion = "{re.escape(VERSION)}"$', uv_lock)
    assert frontend.version == VERSION
    assert frontend_lock.version == VERSION


def test_image_workflow_maps_v1_tag_to_release_aliases() -> None:
    image = (ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in image
    assert "type=semver,pattern={{version}}" in image
    assert "type=semver,pattern={{major}}.{{minor}}" in image
    assert "type=semver,pattern={{major}}" in image
    assert "type=raw,value=latest" in image


def test_release_documents_name_the_current_stable_tag() -> None:
    releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs" / "releases" / "v1.1.0.md").read_text(encoding="utf-8")

    assert f"package version is\n`{VERSION}`" in releasing
    assert f"Git tag is `v{VERSION}`" in releasing
    assert f"Git tag: `v{VERSION}`" in evidence
    assert re.search(r"(?m)^- Release date: \d{4}-\d{2}-\d{2}$", evidence)
    assert "pending GitHub Release" not in evidence
