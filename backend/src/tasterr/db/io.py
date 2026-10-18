"""Finish SQLite I/O before releasing a canceled task's database session."""

import asyncio
from collections.abc import Coroutine
from contextlib import suppress


async def finish_io[T](operation: Coroutine[object, object, T]) -> T:
    # The async SQLite adapter can leave an open cursor when interrupted mid-fetch.
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        completion = asyncio.gather(task, return_exceptions=True)
        while not completion.done():
            with suppress(asyncio.CancelledError):
                await asyncio.shield(completion)
        raise
