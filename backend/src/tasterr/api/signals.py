"""Interaction signals (SPEC §6/§8): the SPA's write path into the taste engine.

Only the client-recordable kinds are representable in the request model, so a
browser cannot forge the strong server-recorded kinds (`request`,
`seed_request_history`). Mutating, hence session-gated + CSRF. Logs carry
outcomes only — never per-title viewing behavior, which this household treats
as protected data (docs/SECURITY.md threat model).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import refresh_profile
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.recommend import store
from tasterr.recommend.signals import TOGGLE_KINDS, ClientSignalKind, MediaType
from tasterr.settings import Settings, get_settings

router = APIRouter()


class SignalBody(BaseModel):
    media_type: MediaType
    tmdb_id: int = Field(ge=1)
    kind: ClientSignalKind
    retract: bool = False


class SignalResponse(BaseModel):
    """`recorded` is whether a new row was written — idempotent toggle re-adds
    and same-day detail reopens succeed with `recorded: false`."""

    recorded: bool


@router.post(
    "/signals",
    response_model=SignalResponse,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def post_signal(
    payload: SignalBody,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
) -> SignalResponse:
    if payload.retract:
        if payload.kind not in TOGGLE_KINDS:
            raise HTTPException(status_code=422, detail="Only toggle kinds can be retracted")
        await store.retract_signal(
            db, authed.user.id, payload.media_type, payload.tmdb_id, payload.kind
        )
        recorded = False
    else:
        recorded = await store.record_signal(
            db, authed.user.id, payload.media_type, payload.tmdb_id, payload.kind
        )
    await db.commit()
    await refresh_profile(request, settings, db, authed.user.id, runtime)
    return SignalResponse(recorded=recorded)
