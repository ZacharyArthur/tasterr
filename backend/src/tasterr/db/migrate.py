"""Idempotent upgrade-to-head, run inside the app lifespan on every boot."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


def _upgrade(connection: Connection) -> None:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def upgrade_to_head(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
