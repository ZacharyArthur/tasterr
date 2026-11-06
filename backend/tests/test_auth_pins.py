from tasterr.auth.pins import MAX_PENDING, TTL_SECONDS, PinStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_handles_are_unguessable_and_unique() -> None:
    store = PinStore(clock=FakeClock())

    first = store.create(123456)
    second = store.create(123456)

    assert first != second
    assert len(first) >= 43  # 32 bytes urlsafe-b64 → 256 bits
    assert "123456" not in first


def test_get_returns_pin_id_without_consuming() -> None:
    store = PinStore(clock=FakeClock())
    handle = store.create(123456)

    assert store.get(handle) == 123456
    assert store.get(handle) == 123456  # polling repeats until claimed


def test_unknown_handle_misses() -> None:
    store = PinStore(clock=FakeClock())
    store.create(123456)

    assert store.get("not-a-real-handle") is None


def test_handle_expires_after_ttl() -> None:
    clock = FakeClock()
    store = PinStore(clock=clock)
    handle = store.create(123456)

    clock.advance(TTL_SECONDS + 1)

    assert store.get(handle) is None
    clock.advance(-2)  # even before TTL again, the entry is gone for good
    assert store.get(handle) is None


def test_consumed_handle_is_single_use() -> None:
    store = PinStore(clock=FakeClock())
    handle = store.create(123456)

    store.consume(handle)

    assert store.get(handle) is None


def test_pop_atomically_takes_the_handle() -> None:
    store = PinStore(clock=FakeClock())
    handle = store.create(123456)

    assert store.pop(handle) == 123456
    assert store.pop(handle) is None  # second taker loses
    assert store.get(handle) is None


def test_pop_respects_ttl() -> None:
    clock = FakeClock()
    store = PinStore(clock=clock)
    handle = store.create(123456)

    clock.advance(TTL_SECONDS + 1)

    assert store.pop(handle) is None


def test_pending_count_stays_bounded() -> None:
    clock = FakeClock()
    store = PinStore(clock=clock)

    first = store.create(1)
    handles = [store.create(i) for i in range(2, MAX_PENDING + 10)]

    assert len(store._pending) <= MAX_PENDING  # pyright: ignore[reportPrivateUsage]
    assert store.get(first) is None  # oldest evicted first
    assert store.get(handles[-1]) is not None


def test_per_entry_expiry_and_mutable_payload() -> None:
    clock = FakeClock()
    store = PinStore[dict[str, int]](clock=clock)
    payload = {"interval": 5}
    short = store.create(payload, ttl=10, session_hash="session")
    long = store.create({"interval": 5}, session_hash="session")
    payload["interval"] += 5
    assert store.get(short, session_hash="session") == {"interval": 10}
    assert store.get(short, session_hash="foreign") is None
    clock.advance(10)
    assert store.get(short, session_hash="session") is None
    assert store.get(long, session_hash="session") is not None
