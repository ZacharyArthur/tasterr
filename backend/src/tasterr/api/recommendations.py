"""Explain + reset (SPEC §6): the taste engine's transparency and escape hatch.

Explain derives from the caller's own profile only — no path accepts a user id
from input. Reset deletes only the caller's rows, then re-seeds inline from
their Seerr request history (user-initiated, so the response reflects the
re-seeded state); Seerr down still clears and degrades to unseeded.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import build_seerr, build_taste
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.recommend import store
from tasterr.recommend.seed import seed_user
from tasterr.recommend.signals import MediaType
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


@router.post("/recommendations/reset", dependencies=[Depends(require_same_origin)])
async def reset_profile(
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
) -> ResetResponse:
    await store.delete_user_taste(db, authed.user.id)
    await db.commit()  # the wipe holds even if the re-seed below fails
    taste = build_taste(request, settings, db, runtime)
    seerr = build_seerr(request, settings)
    if taste is None or seerr is None:
        return ResetResponse(seeded_signals=0)
    try:
        seeded = await seed_user(db, taste, seerr, authed.user.id, authed.user.seerr_user_id)
    except Exception:  # cleared but unseeded — generic, no upstream detail
        logger.exception("reset: re-seed failed user_id=%s", authed.user.id)
        await db.rollback()
        return ResetResponse(seeded_signals=0)
    return ResetResponse(seeded_signals=seeded)
