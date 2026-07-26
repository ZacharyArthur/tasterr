# Starlette TestClient and Uvicorn publish structurally-compatible but distinct
# ASGI protocol aliases; relax only those third-party annotation seams here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportArgumentType=false
# pyright: reportUnusedFunction=false

import pytest
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from tasterr.__main__ import main
from tasterr.api.auth import login_rate_limit
from tasterr.auth.cookies import set_session_cookie
from tasterr.main import SecurityHeaders
from tasterr.settings import get_settings


def test_main_binds_uvicorn_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("TASTERR_HOST", "127.0.0.1")
    monkeypatch.setenv("TASTERR_PORT", "9000")
    monkeypatch.setenv("TASTERR_FORWARDED_ALLOW_IPS", "127.0.0.1,172.20.0.0/16")

    get_settings.cache_clear()
    try:
        main()
    finally:
        get_settings.cache_clear()

    assert captured["app"] == "tasterr.main:create_app"
    assert captured["factory"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9000
    assert captured["access_log"] is False
    assert captured["server_header"] is False
    assert captured["proxy_headers"] is True
    assert captured["forwarded_allow_ips"] == "127.0.0.1,172.20.0.0/16"


class _RecordingBucket:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def allow(self, key: str) -> bool:
        self.keys.append(key)
        return True


def _proxy_probe(trusted_hosts: str) -> tuple[ProxyHeadersMiddleware, _RecordingBucket]:
    inner = FastAPI()
    bucket = _RecordingBucket()
    inner.state.login_bucket = bucket

    @inner.post("/")
    def probe(request: Request, response: Response) -> dict[str, str]:
        login_rate_limit(request)
        set_session_cookie(response, "test-token", secure=request.url.scheme == "https")
        return {"scheme": request.url.scheme}

    return ProxyHeadersMiddleware(SecurityHeaders(inner), trusted_hosts=trusted_hosts), bucket


def test_trusted_proxy_controls_login_ip_and_secure_cookie() -> None:
    app, bucket = _proxy_probe("127.0.0.1")

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/",
            headers={
                "X-Forwarded-For": "198.51.100.7",
                "X-Forwarded-Proto": "https",
            },
        )

    assert response.json() == {"scheme": "https"}
    assert bucket.keys == ["198.51.100.7"]
    assert "secure" in response.headers["set-cookie"].lower()
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_untrusted_peer_cannot_spoof_login_ip_or_cookie_scheme() -> None:
    app, bucket = _proxy_probe("127.0.0.1")

    with TestClient(app, client=("203.0.113.9", 50000)) as client:
        response = client.post(
            "/",
            headers={
                "X-Forwarded-For": "198.51.100.7",
                "X-Forwarded-Proto": "https",
            },
        )

    assert response.json() == {"scheme": "http"}
    assert bucket.keys == ["203.0.113.9"]
    assert "secure" not in response.headers["set-cookie"].lower()
    assert "strict-transport-security" not in response.headers


@pytest.mark.parametrize(
    ("peer", "expected_scheme", "expected_key", "secure"),
    (
        ("172.20.8.4", "https", "198.51.100.7", True),
        ("172.21.8.4", "http", "172.21.8.4", False),
    ),
)
def test_proxy_cidr_trust_applies_only_to_network_members(
    peer: str, expected_scheme: str, expected_key: str, secure: bool
) -> None:
    app, bucket = _proxy_probe("172.20.0.0/16")

    with TestClient(app, client=(peer, 50000)) as client:
        response = client.post(
            "/",
            headers={
                "X-Forwarded-For": "198.51.100.7",
                "X-Forwarded-Proto": "https",
            },
        )

    assert response.json() == {"scheme": expected_scheme}
    assert bucket.keys == [expected_key]
    assert ("secure" in response.headers["set-cookie"].lower()) is secure
    assert ("strict-transport-security" in response.headers) is secure
