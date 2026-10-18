"""Explain + reset (SPEC §6): the taste engine's transparency and escape hatch.

Explain derives from the caller's own profile. Reset cancels history work,
clears only the caller's taste, and evaluates the normal background triggers.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.availability import get_availability
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import (
    build_taste,
    cancel_plex_history,
    cancel_seed,
    history_guard,
    schedule_history,
)
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.catalog.models import Rail
from tasterr.db.models import LinkedAccount, Signal, User
from tasterr.rails.registry import MIN_RAIL_ITEMS
from tasterr.recommend import store
from tasterr.recommend.signals import MediaType
from tasterr.runtime_settings import RailType
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.recommendations")
router = APIRouter()


class ExplainResponse(BaseModel):
    personalized: bool
    reasons: list[str] = []


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
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def reset_profile(
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    user_id = authed.user.id
    await db.commit()
    async with history_guard(request, user_id):
        await cancel_seed(request, user_id)
        await cancel_plex_history(request, user_id)
        await store.delete_user_taste(db, user_id)
        await db.execute(
            update(LinkedAccount)
            .where(LinkedAccount.user_id == user_id)
            .values(
                sync_attempted_at=None,
                sync_synced_at=None,
            )
        )
        await db.commit()
    await schedule_history(request, settings, db, user_id)
