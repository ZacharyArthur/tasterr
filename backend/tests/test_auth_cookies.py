from datetime import datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi import Response

from tasterr.auth.cookies import (
    COOKIE_NAME,
    clear_session_cookie,
    session_cookie_header,
    set_session_cookie,
)


def test_session_cookie_flags_over_http() -> None:
    response = Response()
    set_session_cookie(response, "raw-token", secure=False)

    header = response.headers["set-cookie"]
    assert header.startswith("tasterr_session=raw-token")
    assert "httponly" in header.lower()
    assert "samesite=lax" in header.lower()
    assert "path=/" in header.lower()
    assert "max-age=2592000" in header.lower()  # 30 days
    assert "secure" not in header.lower()


def test_session_cookie_secure_over_https() -> None:
    response = Response()
    set_session_cookie(response, "raw-token", secure=True)

    assert "secure" in response.headers["set-cookie"].lower()


def test_clear_cookie_expires_immediately() -> None:
    response = Response()
    clear_session_cookie(response, secure=False)

    header = response.headers["set-cookie"]
    assert header.startswith("tasterr_session=")
    assert "max-age=0" in header.lower()
    assert "httponly" in header.lower()


@pytest.mark.parametrize("remaining,expected", [(-1.0, 0), (0.0, 0), (29.9, 29)])
def test_refresh_uses_remaining_session_lifetime(
    monkeypatch: pytest.MonkeyPatch, remaining: float, expected: int
) -> None:
    now = datetime(2026, 1, 1)
    monkeypatch.setattr("tasterr.auth.cookies.utcnow", lambda: now)
    header = session_cookie_header(
        "token", secure=False, expires_at=now + timedelta(seconds=remaining)
    )
    assert int(SimpleCookie(header)[COOKIE_NAME]["max-age"]) == expected
