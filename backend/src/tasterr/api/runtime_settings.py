"""Request-scoped runtime-settings dependency."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.deps import get_db
from tasterr.db.runtime_settings import load_runtime_settings
from tasterr.runtime_settings import RuntimeSettings


async def get_runtime_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RuntimeSettings:
    return await load_runtime_settings(db)


RuntimeSettingsDep = Annotated[RuntimeSettings, Depends(get_runtime_settings)]
