# FastAPI consumes these nested handlers through decorators at runtime.
# pyright: reportUnusedFunction=false

"""Hermetic real-backend server for the Playwright smoke journey.

The normal application serves the compiled SPA and uses its normal database,
session, catalog, and request paths. Only the two upstreams are replaced with
small local fixtures mounted under a test-only API prefix.
"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

import uvicorn
from fastapi import APIRouter, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr

from tasterr.clients import tmdb
from tasterr.main import create_app
from tasterr.settings import Settings

HOST = "127.0.0.1"
PORT = 8765
ORIGIN = f"http://{HOST}:{PORT}"
FIXTURE_PREFIX = "/api/_e2e"
TMDB_BASE = f"{ORIGIN}{FIXTURE_PREFIX}/tmdb/3"
SEERR_BASE = f"{ORIGIN}{FIXTURE_PREFIX}/seerr"
E2E_EMAIL = "viewer@example.invalid"
E2E_PASSWORD = "placeholder-password"
E2E_SEERR_COOKIE = "connect.sid=e2e-session"


class LocalLoginBody(BaseModel):
    email: str
    password: str


class RequestBody(BaseModel):
    mediaType: Literal["movie", "tv"]
    mediaId: int
    seasons: str | None = None


@dataclass(frozen=True)
class E2EHarness:
    app: FastAPI
    root: Path
    settings: Settings


def _summary(tmdb_id: int, media_type: Literal["movie", "tv"] = "movie") -> dict[str, object]:
    title = f"Fixture {'Movie' if media_type == 'movie' else 'Show'} {tmdb_id}"
    item: dict[str, object] = {
        "id": tmdb_id,
        "media_type": media_type,
        "overview": "Invented catalog data used only by the local browser smoke.",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 8.1,
        "popularity": 100.0 - tmdb_id % 10,
        "genre_ids": [28],
        "original_language": "en",
    }
    if media_type == "movie":
        item.update(title=title, release_date="2026-01-15")
    else:
        item.update(name=title, first_air_date="2026-01-15")
    return item


def _page(media_type: Literal["movie", "tv"] = "movie") -> dict[str, object]:
    return {
        "page": 1,
        "total_pages": 1,
        "results": [_summary(tmdb_id, media_type) for tmdb_id in range(101, 107)],
    }


def _detail(tmdb_id: int, media_type: Literal["movie", "tv"]) -> dict[str, object]:
    title = f"Fixture {'Movie' if media_type == 'movie' else 'Show'} {tmdb_id}"
    detail: dict[str, object] = {
        "id": tmdb_id,
        "overview": "Invented detail data served by the local E2E fixture.",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 8.1,
        "vote_count": 500,
        "popularity": 90.0,
        "original_language": "en",
        "tagline": "A deterministic test fixture",
        "genres": [{"id": 28, "name": "Action"}],
        "videos": {"results": []},
        "images": {"logos": []},
        "credits": {"cast": [], "crew": []},
        "recommendations": {"page": 1, "total_pages": 1, "results": []},
        "similar": {"page": 1, "total_pages": 1, "results": []},
        "watch/providers": {"results": {"US": {"flatrate": [], "rent": [], "buy": []}}},
        "release_dates": {
            "results": [{"iso_3166_1": "US", "release_dates": [{"certification": "PG"}]}]
        },
        "content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-PG"}]},
        "keywords": {"keywords": [{"id": 1, "name": "fixture"}]},
    }
    if media_type == "movie":
        detail.update(title=title, release_date="2026-01-15", runtime=101)
    else:
        detail.update(
            name=title,
            first_air_date="2026-01-15",
            episode_run_time=[45],
            number_of_seasons=1,
            seasons=[],
            created_by=[],
        )
    return detail


def build_fixture_router() -> APIRouter:
    router = APIRouter(prefix=FIXTURE_PREFIX, include_in_schema=False)

    @router.get("/ready")
    async def _ready() -> dict[str, bool]:
        return {"ready": True}

    @router.post("/seerr/api/v1/auth/local")
    async def _local_login(payload: LocalLoginBody) -> JSONResponse:
        if payload.email != E2E_EMAIL or payload.password != E2E_PASSWORD:
            return JSONResponse(status_code=401, content={"message": "Invalid credentials"})
        response = JSONResponse(
            {
                "id": 7001,
                "displayName": "E2E Viewer",
                "email": E2E_EMAIL,
                "permissions": 0,
            }
        )
        response.set_cookie("connect.sid", "e2e-session", httponly=True)
        return response

    @router.get("/seerr/api/v1/request")
    async def _request_history() -> dict[str, list[object]]:
        return {"results": []}

    @router.post("/seerr/api/v1/request")
    async def _create_request(
        payload: RequestBody, cookie: Annotated[str | None, Header()] = None
    ) -> JSONResponse:
        if cookie != E2E_SEERR_COOKIE:
            return JSONResponse(status_code=403, content={"message": "Invalid session"})
        if payload.mediaId < 1:
            return JSONResponse(status_code=422, content={"message": "Invalid title"})
        return JSONResponse(status_code=201, content={"media": {"status": 2}})

    @router.get("/seerr/api/v1/{media_type}/{tmdb_id}")
    async def _media_status(media_type: Literal["movie", "tv"], tmdb_id: int) -> JSONResponse:
        del media_type, tmdb_id
        return JSONResponse(status_code=404, content={"message": "Not requested"})

    @router.get("/tmdb/3/genre/{media_type}/list")
    async def _genres(media_type: Literal["movie", "tv"]) -> dict[str, list[object]]:
        del media_type
        return {"genres": []}

    @router.get("/tmdb/3/trending/{media_type}/{window}")
    async def _trending(media_type: str, window: str) -> dict[str, object]:
        del media_type, window
        return _page()

    @router.get("/tmdb/3/discover/{media_type}")
    async def _discover(media_type: Literal["movie", "tv"]) -> dict[str, object]:
        return _page(media_type)

    @router.get("/tmdb/3/{media_type}/{tmdb_id}")
    async def _title_detail(media_type: Literal["movie", "tv"], tmdb_id: int) -> dict[str, object]:
        return _detail(tmdb_id, media_type)

    return router


@contextmanager
def e2e_harness(static_dir: Path | None = None) -> Generator[E2EHarness]:
    """Build the normal app around disposable state, then remove all state."""
    compiled_spa = static_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    original_tmdb_base = tmdb.BASE
    with TemporaryDirectory(prefix="tasterr-e2e-") as temporary:
        root = Path(temporary)
        settings = Settings(
            tmdb_api_key=SecretStr("e2e-tmdb-placeholder"),
            seerr_internal_url=SEERR_BASE,
            seerr_api_key=SecretStr("e2e-seerr-placeholder"),
            tasterr_secret_key=SecretStr("e2e-session-placeholder"),
            database_path=root / "tasterr.db",
            static_dir=compiled_spa,
        )
        tmdb.BASE = TMDB_BASE
        try:
            app = create_app(settings)
            app.include_router(build_fixture_router())
            yield E2EHarness(app=app, root=root, settings=settings)
        finally:
            tmdb.BASE = original_tmdb_base


def main() -> None:
    with e2e_harness() as harness:
        uvicorn.run(harness.app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
