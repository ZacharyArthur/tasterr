"""Shared outbound HTTP client, created once in the app lifespan.

Only `clients/` may import httpx (import-linter contract); the lifespan gets
the client through this factory without naming the type.
"""

import httpx

TIMEOUT_SECONDS = 10.0


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_SECONDS))
