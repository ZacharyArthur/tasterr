# starlette's TestClient ships partially-unknown method annotations.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

"""Focused contracts for the hermetic real-backend browser harness."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.e2e_server import (
    E2E_EMAIL,
    E2E_PASSWORD,
    E2E_SEERR_COOKIE,
    SEERR_BASE,
    TMDB_BASE,
    e2e_harness,
)

from tasterr.clients import tmdb


def test_harness_is_ready_and_serves_only_invented_upstreams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("fixture spa", encoding="utf-8")
    monkeypatch.setenv("TASTERR_SEERR_INTERNAL_URL", "https://live.invalid")
    original_tmdb_base = tmdb.BASE

    with e2e_harness(static_dir) as harness:
        root = harness.root
        assert harness.settings.seerr_internal_url == SEERR_BASE
        assert tmdb.BASE == TMDB_BASE
        with TestClient(harness.app) as client:
            assert client.get("/api/_e2e/ready").json() == {"ready": True}

            rejected = client.post(
                "/api/_e2e/seerr/api/v1/auth/local",
                json={"email": E2E_EMAIL, "password": "wrong"},
            )
            assert rejected.status_code == 401

            login = client.post(
                "/api/_e2e/seerr/api/v1/auth/local",
                json={"email": E2E_EMAIL, "password": E2E_PASSWORD},
            )
            assert login.status_code == 200
            assert login.json()["displayName"] == "E2E Viewer"

            catalog = client.get("/api/_e2e/tmdb/3/trending/all/day")
            assert catalog.status_code == 200
            assert catalog.json()["results"][0]["title"] == "Fixture Movie 101"

            request = client.post(
                "/api/_e2e/seerr/api/v1/request",
                headers={"Cookie": E2E_SEERR_COOKIE},
                json={"mediaType": "movie", "mediaId": 101},
            )
            assert request.status_code == 201
            assert request.json() == {"media": {"status": 2}}

        assert root.exists()
        assert (root / "tasterr.db").is_file()

    assert not root.exists()
    assert original_tmdb_base == tmdb.BASE
