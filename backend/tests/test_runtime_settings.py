import logging
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Setting
from tasterr.db.runtime_settings import (
    GLOBAL_SETTINGS_KEY,
    load_runtime_settings,
    save_runtime_settings,
)
from tasterr.runtime_settings import (
    Accent,
    Appearance,
    RailType,
    RuntimeSettings,
    Theme,
    rail_type_descriptors,
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[AsyncSession]:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def test_runtime_settings_normalize_and_serialize() -> None:
    settings = RuntimeSettings.model_validate(
        {
            "region": " gb ",
            "service_ids": [8, 337],
            "disabled_rail_types": ["hero", "genres"],
            "appearance": {"theme": "light", "accent": "azure"},
        }
    )

    assert settings.region == "GB"
    assert settings.service_ids == [8, 337]
    assert settings.disabled_rail_types == [RailType.HERO, RailType.GENRES]
    assert settings.appearance == Appearance(theme=Theme.LIGHT, accent=Accent.AZURE)
    assert RuntimeSettings.model_validate_json(settings.model_dump_json()) == settings


@pytest.mark.parametrize(
    "payload",
    [
        {"region": "USA"},
        {"region": "1!"},
        {"service_ids": [0]},
        {"service_ids": [8, 8]},
        {"service_ids": list(range(1, 10))},
        {"disabled_rail_types": ["hero", "hero"]},
        {"disabled_rail_types": ["unknown"]},
        {"appearance": {"theme": "sepia", "accent": "crimson"}},
        {"appearance": {"theme": "dark", "accent": "custom"}},
    ],
)
def test_runtime_settings_reject_invalid_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings.model_validate(payload)


def test_runtime_shape_has_no_deployment_or_secret_fields() -> None:
    names = set(RuntimeSettings.model_json_schema()["properties"])
    forbidden = {"key", "secret", "token", "cookie", "credential", "url", "host", "port"}
    assert all(not any(marker in name.lower() for marker in forbidden) for name in names)
    assert [item.id for item in rail_type_descriptors()] == list(RailType)


async def test_absent_row_returns_defaults_without_write(db: AsyncSession) -> None:
    assert await load_runtime_settings(db) == RuntimeSettings()
    assert (await db.execute(select(Setting))).scalars().all() == []


async def test_settings_round_trip_and_last_write_wins(db: AsyncSession) -> None:
    first = RuntimeSettings(region="GB", service_ids=[8])
    second = RuntimeSettings(
        region="CA",
        service_ids=[337],
        appearance=Appearance(theme=Theme.LIGHT, accent=Accent.EMERALD),
    )
    await save_runtime_settings(db, first)
    await save_runtime_settings(db, second)
    await db.commit()

    assert await load_runtime_settings(db) == second
    assert len((await db.execute(select(Setting))).scalars().all()) == 1


async def test_invalid_stored_json_uses_defaults_without_logging_value(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    sentinel = "SENTINEL-DO-NOT-LOG"
    db.add(Setting(key=GLOBAL_SETTINGS_KEY, value=sentinel))
    await db.commit()

    with caplog.at_level(logging.WARNING, logger="tasterr.runtime_settings"):
        assert await load_runtime_settings(db) == RuntimeSettings()

    assert "invalid runtime settings row" in caplog.text
    assert sentinel not in caplog.text


async def test_setting_primary_key_is_enforced(db: AsyncSession) -> None:
    db.add_all(
        [
            Setting(key=GLOBAL_SETTINGS_KEY, value="{}"),
            Setting(key=GLOBAL_SETTINGS_KEY, value="{}"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.flush()
