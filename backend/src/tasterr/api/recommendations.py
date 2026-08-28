"""Explain + reset (SPEC §6): the taste engine's transparency and escape hatch.

Explain derives from the caller's own profile only — no path accepts a user id
from input. Reset deletes only the caller's rows, then re-seeds inline from
their Seerr request history (user-initiated, so the response reflects the
re-seeded state); Seerr down still clears and degrades to unseeded.
"""

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.availability import get_availability
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import (
    build_seerr,
    build_taste,
    cancel_plex_history,
    schedule_plex_history,
)
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.catalog.models import Rail
from tasterr.db.models import Signal, User
from tasterr.rails.registry import MIN_RAIL_ITEMS
from tasterr.recommend import store
from tasterr.recommend.seed import seed_user
from tasterr.recommend.signals import MediaType
from tasterr.runtime_settings import RailType
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.recommendations")
router = APIRouter()


class ExplainResponse(BaseModel):
    personalized: bool
    reasons: list[str] = []


class ResetResponse(BaseModel):
    """`seeded_signals` is how many request-history signals the re-seed
    imported — 0 when the user has no history or Seerr was unreachable."""

    seeded_signals: int


class HouseholdMember(BaseModel):
    id: int = Field(gt=0)
    display_name: str
    avatar_url: str | None
    has_taste_signals: bool


class HouseholdBlendRequest(BaseModel):
    user_ids: list[int] = Field(min_length=2, max_length=6)

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, value: list[int]) -> list[int]:
        if any(user_id <= 0 for user_id in value):
            raise ValueError("user ids must be positive")
        if len(value) != len(set(value)):
            raise ValueError("user ids must be unique")
        return value


@router.get(
    "/recommendations/household-members",
    response_model=list[HouseholdMember],
)
async def household_members(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    runtime: RuntimeSettingsDep,
) -> list[HouseholdMember]:
    if RailType.HOUSEHOLD_BLEND in runtime.disabled_rail_types:
        return []
    return await _load_household_members(db)


@router.post(
    "/recommendations/household-blend",
    response_model=Rail | None,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def household_blend(
    payload: HouseholdBlendRequest,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
) -> Rail | None:
    if RailType.HOUSEHOLD_BLEND in runtime.disabled_rail_types:
        raise _blend_unavailable()
    user_ids = await _validate_household_audience(db, authed.user.id, payload.user_ids)
    availability = get_availability(authed, request, settings)
    taste = build_taste(request, settings, db, runtime, availability)
    if taste is None:
        raise _blend_unavailable()
    try:
        items = await taste.household_blend(user_ids)
    except Exception:
        logger.error("household blend: computation failed")
        await db.rollback()
        raise _blend_unavailable() from None
    try:
        await db.commit()
    except Exception:
        logger.error("household blend: derived-cache commit failed")
        await db.rollback()
    if len(items) < MIN_RAIL_ITEMS:
        return None
    return Rail(
        id="household-blend",
        title="Something for Everyone Tonight",
        kind="standard",
        items=items,
    )


async def _load_household_members(db: AsyncSession) -> list[HouseholdMember]:
    has_signals = exists(select(Signal.id).where(Signal.user_id == User.id))
    result = await db.execute(
        select(User.id, User.display_name, User.avatar_url, has_signals).order_by(User.id)
    )
    return [
        HouseholdMember(
            id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
            has_taste_signals=has_taste_signals,
        )
        for user_id, display_name, avatar_url, has_taste_signals in result.all()
    ]


async def _validate_household_audience(
    db: AsyncSession, caller_id: int, requested_ids: list[int]
) -> list[int]:
    if caller_id not in requested_ids:
        raise _blend_unavailable()
    has_signals = exists(select(Signal.id).where(Signal.user_id == User.id))
    result = await db.execute(
        select(User.id, has_signals).where(User.id.in_(requested_ids)).order_by(User.id)
    )
    members = {user_id: eligible for user_id, eligible in result.all()}
    if len(members) != len(requested_ids) or not all(members.values()):
        raise _blend_unavailable()
    return sorted(members)


def _blend_unavailable() -> HTTPException:
    return HTTPException(status_code=400, detail="Household blend unavailable")


@router.get("/recommendations/explain")
async def explain_title(
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
    media_type: Annotated[MediaType, Query(alias="type")],
    tmdb_id: Annotated[int, Query(alias="id", ge=1)],
) -> ExplainResponse:
    taste = build_taste(request, settings, db, runtime)
    if taste is None:
        return ExplainResponse(personalized=False)  # no catalog, no vectors to overlap
    explanation = await taste.explain_title(authed.user.id, media_type, tmdb_id)
    try:
        await db.commit()  # persist any lazily rebuilt profile/vector materializations
    except Exception:  # derived-cache write only — the explanation still ships
        logger.exception("explain: derived-cache commit failed")
        await db.rollback()
    return ExplainResponse(personalized=explanation.personalized, reasons=explanation.reasons)


@router.post(
    "/recommendations/reset",
    response_model=ResetResponse,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def reset_profile(
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
) -> ResetResponse:
    user_id = authed.user.id
    seerr_user_id = authed.user.seerr_user_id
    plex_token_enc = authed.session.plex_token_enc
    resets = cast("set[int]", request.app.state.plex_history_resets)
    seeded = 0
    resets.add(user_id)
    try:
        await cancel_plex_history(request, user_id)
        await store.delete_user_taste(db, authed.user.id)
        # Do not trust the request's identity-map snapshot: an import may have
        # committed its attempt after session resolution but before cancellation.
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(plex_history_attempted_at=None, plex_history_synced_at=None)
        )
        await db.commit()  # the wipe holds even if the re-seed below fails
        taste = build_taste(request, settings, db, runtime)
        seerr = build_seerr(request, settings)
        if taste is not None and seerr is not None:
            try:
                seeded = await seed_user(db, taste, seerr, user_id, seerr_user_id)
            except Exception:  # cleared but unseeded — generic, no upstream detail
                logger.exception("reset: re-seed failed")
                await db.rollback()
    finally:
        resets.discard(user_id)
    schedule_plex_history(request, settings, user_id, None, plex_token_enc)
    return ResetResponse(seeded_signals=seeded)
