import pytest
import uvicorn

from tasterr.__main__ import main
from tasterr.settings import get_settings


def test_main_binds_uvicorn_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("TASTERR_HOST", "127.0.0.1")
    monkeypatch.setenv("TASTERR_PORT", "9000")

    get_settings.cache_clear()
    try:
        main()
    finally:
        get_settings.cache_clear()

    assert captured["app"] == "tasterr.main:create_app"
    assert captured["factory"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9000
    assert captured["proxy_headers"] is True
