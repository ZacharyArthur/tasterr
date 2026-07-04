"""Async database engine bound to the SQLite file from settings."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_path: Path) -> AsyncEngine:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
