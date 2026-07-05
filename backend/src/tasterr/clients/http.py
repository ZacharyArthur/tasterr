"""Shared outbound HTTP client, created once in the app lifespan.

Only `clients/` may import httpx (import-linter contract); the lifespan gets
the client through this factory without naming the type.
"""

import http.cookiejar

import httpx

TIMEOUT_SECONDS = 10.0


def create_http_client(
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    # The client is shared across all users, so it must never persist cookies
    # between requests — a stored Seerr connect.sid would ride along on the
    # next user's login. The empty allowed-domains policy rejects every cookie
    # at storage time; per-response Set-Cookie parsing (response.cookies) is
    # unaffected.
    no_store = http.cookiejar.CookieJar(
        policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])
    )
    return httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        cookies=no_store,
        transport=transport,
    )
