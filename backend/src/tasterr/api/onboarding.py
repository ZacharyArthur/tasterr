"""Optional cold-start taste picker state and completion.

Only users with no signals are invited. Completion records ordinary watchlist
signals and a per-user seen bit; no selected title is returned or logged.
"""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import refresh_profile
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.recommend import store
from tasterr.recommend.signals import MAX_TMDB_ID, MediaType
from tasterr.settings import Settings, get_settings

router = APIRouter()


class TasteOnboardingStateResponse(BaseModel):
    state: Literal["pending", "show", "done"]


class TasteOnboardingSelection(BaseModel):
    media_type: MediaType
    tmdb_id: int = Field(ge=1, le=MAX_TMDB_ID)


class TasteOnboardingBody(BaseModel):
    selections: Annotated[list[TasteOnboardingSelection], Field(max_length=12)] = []


class TasteOnboardingSubmitResponse(BaseModel):
    recorded_signals: int


@router.get("/taste-onboarding", response_model=TasteOnboardingStateResponse)
async def get_taste_onboarding(
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> TasteOnboardingStateResponse:
    if authed.user.taste_onboarding_seen or await store.has_signals(db, authed.user.id):
        return TasteOnboardingStateResponse(state="done")
    seeding = cast("set[int]", request.app.state.seeding)
    return TasteOnboardingStateResponse(state="pending" if authed.user.id in seeding else "show")


@router.post(
    "/taste-onboarding",
    response_model=TasteOnboardingSubmitResponse,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def complete_taste_onboarding(
    payload: TasteOnboardingBody,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
) -> TasteOnboardingSubmitResponse:
    unique: set[tuple[MediaType, int]] = {
        (item.media_type, item.tmdb_id) for item in payload.selections
    }
    recorded = 0
    for media_type, tmdb_id in unique:
        if await store.record_signal(db, authed.user.id, media_type, tmdb_id, "watchlist"):
            recorded += 1
    authed.user.taste_onboarding_seen = True
    await db.commit()
    if unique:
        await refresh_profile(request, settings, db, authed.user.id, runtime)
    return TasteOnboardingSubmitResponse(recorded_signals=recorded)
