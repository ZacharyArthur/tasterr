"""Persistence for the one global, typed, non-secret runtime document."""

import logging

from pydantic import ValidationError
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.db.models import Setting, utcnow
from tasterr.runtime_settings import RuntimeSettings

logger = logging.getLogger("tasterr.runtime_settings")

GLOBAL_SETTINGS_KEY = "global"


async def load_runtime_settings(db: AsyncSession) -> RuntimeSettings:
    row = await db.get(Setting, GLOBAL_SETTINGS_KEY)
    if row is None:
        return RuntimeSettings()
    try:
        return RuntimeSettings.model_validate_json(row.value)
    except (ValidationError, ValueError):
        # Never log the persisted value. The model cannot represent secrets, but
        # a manually corrupted database could contain arbitrary text.
        logger.warning("invalid runtime settings row; using defaults")
        return RuntimeSettings()


async def save_runtime_settings(db: AsyncSession, settings: RuntimeSettings) -> RuntimeSettings:
    statement = insert(Setting).values(
        key=GLOBAL_SETTINGS_KEY,
        value=settings.model_dump_json(),
        updated_at=utcnow(),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={"value": settings.model_dump_json(), "updated_at": utcnow()},
    )
    await db.execute(statement)
    await db.flush()
    return settings
