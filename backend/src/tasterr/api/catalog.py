"""Shared catalog dependency: build a CatalogService for the request.

Fails loudly at the boundary when TMDB is unconfigured (503), mirroring auth's
`get_auth_context`. The shared httpx client and process-wide cache live on
app.state; the TMDB api_key comes from settings and never leaves the server.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from tasterr.auth.deps import AuthedSession, require_session
from tasterr.catalog.service import CatalogService
from tasterr.clients.tmdb import TmdbClient
from tasterr.settings import Settings, get_settings


def get_catalog(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CatalogService:
    # Session is required *before* the config check, so an unauthenticated
    # caller gets 401 (default-deny), never a 503 that leaks configuration state.
    if settings.tmdb_api_key is None:
        raise HTTPException(status_code=503, detail="Catalog unavailable")
    client = TmdbClient(
        request.app.state.http,
        settings.tmdb_api_key.get_secret_value(),
        request.app.state.catalog_cache,
    )
    return CatalogService(client)


CatalogDep = Annotated[CatalogService, Depends(get_catalog)]
