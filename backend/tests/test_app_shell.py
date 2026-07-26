# starlette 1.3's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules for this file rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from tasterr.main import create_app
from tasterr.settings import Settings

SENTINEL = "SENTINEL-SECRET-VALUE"
EXPECTED_SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data: https://image.tmdb.org; connect-src 'self'; "
        "frame-src https://www.youtube.com; font-src 'self' data:; form-action 'self'"
    ),
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
}


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
    }
    return Settings.model_validate({**defaults, **overrides})


def test_factory_startup_runs_migrations_and_shares_engine(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)

    with TestClient(app):
        assert settings.database_path.exists()
        assert isinstance(app.state.engine, AsyncEngine)


def test_health_ok_and_unconfigured_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "tmdb_configured": False,
        "seerr_configured": False,
    }


def test_health_flags_flip_with_settings_and_leak_nothing(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        tmdb_api_key=SecretStr(f"{SENTINEL}-tmdb"),
        seerr_internal_url=f"http://{SENTINEL}-seerr:5055",
        seerr_api_key=SecretStr(f"{SENTINEL}-seerr"),
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert body["tmdb_configured"] is True
    assert body["seerr_configured"] is True
    assert SENTINEL not in response.text


def test_non_api_path_serves_index_html(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.static_dir.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html><title>tasterr</title>")

    with TestClient(create_app(settings)) as client:
        response = client.get("/settings")

    assert response.status_code == 200
    assert "tasterr" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_static_file_served_directly(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assets = settings.static_dir / "assets"
    assets.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html>")
    (assets / "app.js").write_text("console.log('hi')")

    with TestClient(create_app(settings)) as client:
        response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_spa_static_and_error_responses_carry_security_headers(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assets = settings.static_dir / "assets"
    assets.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html>")
    (assets / "app.js").write_text("console.log('hi')")

    with TestClient(create_app(settings)) as client:
        responses = (
            client.get("/api/v1/health"),
            client.get("/settings"),
            client.get("/assets/app.js"),
            client.get("/api/v1/nope"),
        )

    for response in responses:
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers[name] == value
        assert "strict-transport-security" not in response.headers


def test_hsts_is_emitted_only_for_effective_https(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        http = client.get("/api/v1/health")
    with TestClient(app, base_url="https://testserver") as client:
        https = client.get("/api/v1/health")

    assert "strict-transport-security" not in http.headers
    assert https.headers["strict-transport-security"] == "max-age=31536000"


def test_unknown_api_route_stays_json_404(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.static_dir.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html>")

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}


def test_unknown_api_route_is_json_404_for_any_method(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.static_dir.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html>")

    with TestClient(create_app(settings)) as client:
        for method in ("post", "put", "delete", "patch"):
            response = getattr(client, method)("/api/v1/nope")
            assert response.status_code == 404, method
            assert response.headers["content-type"] == "application/json"


def test_non_get_to_spa_path_is_405(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.static_dir.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<!doctype html>")

    with TestClient(create_app(settings)) as client:
        response = client.post("/settings")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD"


def test_wrong_method_on_known_api_route_is_405(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


def test_trace_on_unknown_api_route_is_404(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.request("TRACE", "/api/v1/nope")

    assert response.status_code == 404
