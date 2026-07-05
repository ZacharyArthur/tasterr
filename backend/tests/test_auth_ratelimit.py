from tasterr.auth.ratelimit import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_up_to_capacity_then_denies() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=3, refill_per_second=0.0, clock=clock)

    results = [bucket.allow("ip") for _ in range(4)]

    assert results == [True, True, True, False]


def test_refill_restores_tokens_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, clock=clock)
    assert bucket.allow("ip")
    assert bucket.allow("ip")
    assert not bucket.allow("ip")

    clock.advance(1.0)

    assert bucket.allow("ip")
    assert not bucket.allow("ip")


def test_refill_never_exceeds_capacity() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=1.0, clock=clock)
    assert bucket.allow("ip")

    clock.advance(3600.0)

    results = [bucket.allow("ip") for _ in range(3)]
    assert results == [True, True, False]


def test_keys_are_independent() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=1, refill_per_second=0.0, clock=clock)

    assert bucket.allow("first")
    assert not bucket.allow("first")
    assert bucket.allow("second")


def test_key_count_stays_bounded() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=1, refill_per_second=1.0, clock=clock, max_keys=8)

    for i in range(100):
        bucket.allow(f"ip-{i}")
        clock.advance(10.0)  # each earlier bucket fully refills, so it gets pruned

    assert len(bucket._buckets) <= 8  # pyright: ignore[reportPrivateUsage]
