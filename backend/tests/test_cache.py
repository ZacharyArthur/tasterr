"""Cache: fresh-hit, refresh, stale-on-error, single-flight (task 1.2)."""

import asyncio

import pytest

import tasterr.cache as cache_mod
from tasterr.cache import Cache, CacheOpts
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

OPTS = CacheOpts(ttl=10.0, stale=100.0)


class FakeTime:
    """Replaces the `time` module reference in tasterr.cache; no real clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def _cache(monkeypatch: pytest.MonkeyPatch) -> tuple[Cache, FakeTime]:
    clock = FakeTime()
    monkeypatch.setattr(cache_mod, "time", clock)
    return Cache(), clock


async def test_fresh_hit_skips_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, _ = _cache(monkeypatch)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return "v"

    assert await cache.cached("k", OPTS, loader) == "v"
    assert await cache.cached("k", OPTS, loader) == "v"
    assert calls == 1


async def test_expired_entry_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, clock = _cache(monkeypatch)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return f"v{calls}"

    first = await cache.cached("k", OPTS, loader)
    clock.now += 5.0  # still within ttl
    second = await cache.cached("k", OPTS, loader)
    clock.now += 10.0  # now past ttl
    third = await cache.cached("k", OPTS, loader)

    assert (first, second, third) == ("v1", "v1", "v2")
    assert calls == 2


async def test_stale_value_served_on_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, clock = _cache(monkeypatch)
    fail = False

    async def loader() -> str:
        if fail:
            raise UpstreamUnavailable("down")
        return "good"

    assert await cache.cached("k", OPTS, loader) == "good"
    clock.now += 20.0  # past ttl, inside stale window
    fail = True
    assert await cache.cached("k", OPTS, loader) == "good"  # last-good served


async def test_cold_miss_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, _ = _cache(monkeypatch)

    async def loader() -> str:
        raise UpstreamUnavailable("down")

    with pytest.raises(UpstreamUnavailable):
        await cache.cached("k", OPTS, loader)


async def test_beyond_stale_window_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, clock = _cache(monkeypatch)
    fail = False

    async def loader() -> str:
        if fail:
            raise UpstreamUnavailable("down")
        return "good"

    await cache.cached("k", OPTS, loader)
    clock.now += 200.0  # past ttl + stale
    fail = True
    with pytest.raises(UpstreamUnavailable):
        await cache.cached("k", OPTS, loader)


async def test_definitive_rejection_is_not_served_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    cache, clock = _cache(monkeypatch)
    fail = False

    async def loader() -> str:
        if fail:
            raise UpstreamRejected(404)
        return "good"

    await cache.cached("k", OPTS, loader)
    clock.now += 20.0  # inside stale window — but a 4xx is definitive, not stale-eligible
    fail = True
    with pytest.raises(UpstreamRejected):
        await cache.cached("k", OPTS, loader)


async def test_concurrent_misses_collapse_to_one_loader_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, _ = _cache(monkeypatch)
    gate = asyncio.Event()
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "v"

    tasks = [asyncio.create_task(cache.cached("k", OPTS, loader)) for _ in range(5)]
    await asyncio.sleep(0.02)  # let one enter the loader and the rest queue on the lock
    gate.set()
    results = await asyncio.gather(*tasks)

    assert results == ["v"] * 5
    assert calls == 1
