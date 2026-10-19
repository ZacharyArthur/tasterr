"""Idempotent upgrade-to-head, run inside the app lifespan on every boot."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


@contextmanager
def migration_connection(connection: Connection) -> Generator[None]:
    """Rebuild SQLite tables without cascading into their children."""
    if connection.in_transaction():
        raise RuntimeError("Migrations require a connection outside a transaction")
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()
    try:
        with connection.begin():
            # The SQLite driver's legacy mode does not begin a transaction for DDL.
            connection.exec_driver_sql("BEGIN")
            yield
            if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                raise RuntimeError("Migration left foreign-key violations")
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()


def _upgrade(connection: Connection) -> None:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def upgrade_to_head(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.run_sync(_upgrade)
