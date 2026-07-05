"""Async database engine bound to the SQLite file from settings."""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry


def create_engine(database_path: Path) -> AsyncEngine:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")

    # SQLite leaves foreign-key enforcement OFF per connection by default;
    # without this pragma the sessions→users ON DELETE CASCADE is a no-op.
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
