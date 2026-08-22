import asyncio
from typing import cast

import pytest

from tasterr.cache import Cache, CacheOpts
from tasterr.catalog import availability as avail
from tasterr.catalog.availability import (
    NOT_REQUESTED,
    UNKNOWN,
    Availability,
    AvailabilityService,
    PlaybackLinks,
    PlaybackVariant,
    availability_from_code,
    to_availability,
)
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.seerr import MediaType, SeerrClient, SeerrMediaInfo

# ── Pure status mapping ──────────────────────────────────────────────────────


def test_codes_map_to_statuses() -> None:
    assert availability_from_code(2).status == "pending"
    assert availability_from_code(3).status == "processing"
    assert availability_from_code(4).status == "partial"
    assert availability_from_code(5).status == "available"


def test_known_statuses_are_known() -> None:
    assert availability_from_code(5).known is True


def test_seerr_unknown_and_unmapped_codes_fall_back_to_not_requested() -> None:
    # Seerr's own status 1 ("unknown") and any unexpected code are actionable as a
    # request — and stay distinct from UNKNOWN (Seerr unreachable).
    assert availability_from_code(1) == NOT_REQUESTED
    assert availability_from_code(99) == NOT_REQUESTED


def test_absent_media_info_is_not_requested() -> None:
    assert to_availability(None) == NOT_REQUESTED


def test_media_info_maps_to_status() -> None:
    assert to_availability(SeerrMediaInfo(status=5)) == Availability(status="available", known=True)


def test_available_overseerr_links_are_validated_and_build_android_fallback() -> None:
    web = "https://app.plex.tv/desktop/#!/server/test/details?key=%2Flibrary%2F42"
    app = "plex://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F42&server=test"

    result = to_availability(
        SeerrMediaInfo.model_validate({"status": 5, "plexUrl": web, "iOSPlexUrl": app})
    )

    assert result.playback == PlaybackLinks(
        regular=PlaybackVariant(
            web_url=web,
            app_url=app,
            android_intent_url=(
                "intent://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F42&server=test"
                "#Intent;scheme=plex;package=com.plexapp.android;"
                "S.browser_fallback_url=https%3A%2F%2Fapp.plex.tv%2Fdesktop%2F%23%21%2F"
                "server%2Ftest%2Fdetails%3Fkey%3D%252Flibrary%252F42;end"
            ),
        )
    )


def test_partially_available_regular_links_are_preserved() -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate(
            {
                "status": 4,
                "plexUrl": "https://app.plex.tv/desktop#!/partial",
                "iOSPlexUrl": "plex://preplay/?metadataKey=partial",
            }
        )
    )

    assert result.status == "partial"
    assert result.playback is not None
    assert result.playback.regular is not None
    assert result.playback.regular.web_url == "https://app.plex.tv/desktop#!/partial"


def test_partially_available_4k_links_are_preserved() -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate(
            {
                "status": 1,
                "status4k": 4,
                "mediaUrl4k": "https://app.plex.tv/desktop#!/partial-4k",
                "iOSPlexUrl4k": "plex://preplay/?metadataKey=partial-4k",
            }
        )
    )

    assert result.status == "partial"
    assert result.playback is not None
    assert result.playback.four_k is not None
    assert result.playback.four_k.web_url == "https://app.plex.tv/desktop#!/partial-4k"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": 4},
        {
            "status": 4,
            "plexUrl": "https://evil.example/partial",
            "iOSPlexUrl": "plex://preplay/?metadataKey=partial",
        },
        {"status4k": 4},
        {
            "status4k": 4,
            "mediaUrl4k": "https://evil.example/partial-4k",
            "iOSPlexUrl4k": "plex://preplay/?metadataKey=partial-4k",
        },
    ],
)
def test_partially_available_media_without_valid_links_has_no_playback(
    payload: dict[str, object],
) -> None:
    result = to_availability(SeerrMediaInfo.model_validate(payload))

    assert result.playback is None


def test_4k_only_availability_and_links_are_preserved() -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate(
            {
                "status": 1,
                "status4k": 5,
                "mediaUrl4k": "https://app.plex.tv/desktop/#!/4k",
                "iOSPlexUrl4k": "plex://preplay/?metadataKey=%2Flibrary%2F84",
            }
        )
    )

    assert result.status == "available"
    assert result.playback is not None
    assert result.playback.regular is None
    assert result.playback.four_k is not None
    assert result.playback.four_k.web_url == "https://app.plex.tv/desktop/#!/4k"


def test_mixed_playable_variant_states_keep_both_link_sets() -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate(
            {
                "status": 4,
                "status4k": 5,
                "mediaUrl": "https://app.plex.tv/desktop/#!/regular",
                "iOSPlexUrl": "plex://preplay/?metadataKey=regular",
                "mediaUrl4k": "https://app.plex.tv/desktop/#!/4k",
                "iOSPlexUrl4k": "plex://preplay/?metadataKey=4k",
            }
        )
    )

    assert result.status == "available"
    assert result.playback is not None
    assert result.playback.regular is not None
    assert result.playback.four_k is not None
    assert result.playback.regular.web_url == "https://app.plex.tv/desktop/#!/regular"
    assert result.playback.four_k.web_url == "https://app.plex.tv/desktop/#!/4k"


@pytest.mark.parametrize(
    ("web", "app"),
    [
        ("javascript:alert(1)", "plex://preplay/?metadataKey=x"),
        ("https://evil.example/", "plex://preplay/?metadataKey=x"),
        ("https://user:pass@app.plex.tv/", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv/?X-Plex-Token=placeholder", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv/?%58-Plex-Token=placeholder", "plex://preplay/?metadataKey=x"),
        (
            "https://app.plex.tv/desktop#!/details?x-plex-token=placeholder",
            "plex://preplay/?metadataKey=x",
        ),
        (" https://app.plex.tv/", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv:8443/", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv:abc/", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv/\x00", "plex://preplay/?metadataKey=x"),
        ("https://app.plex.tv/", "plex://settings/?metadataKey=x"),
        ("https://app.plex.tv/", "plex://preplay/?%78-plex-token=placeholder"),
        (
            "https://app.plex.tv/",
            "plex://preplay/?metadataKey=x&X-Plex-Token=placeholder",
        ),
        ("https://app.plex.tv/", "plex://preplay/?metadataKey=x#Intent;package=evil"),
        ("https://app.plex.tv/", "plex://preplay/?metadataKey=x#"),
    ],
)
def test_unsafe_playback_links_are_dropped(web: str, app: str) -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate({"status": 5, "plexUrl": web, "iOSPlexUrl": app})
    )

    if web == "https://app.plex.tv/" and app.startswith("plex://"):
        assert result.playback == PlaybackLinks(
            regular=PlaybackVariant(web_url="https://app.plex.tv/")
        )
    else:
        assert result.playback is None


def test_non_available_media_drops_stray_playback_links() -> None:
    result = to_availability(
        SeerrMediaInfo.model_validate(
            {
                "status": 2,
                "plexUrl": "https://app.plex.tv/desktop/",
                "iOSPlexUrl": "plex://preplay/?metadataKey=x",
            }
        )
    )

    assert result.status == "pending"
    assert result.playback is None


# ── AvailabilityService: cache, single-flight, degradation ───────────────────


class FakeSeerrClient:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_ids: set[int] = set()
        self.code = 5

    async def media_status(self, media_type: MediaType, tmdb_id: int) -> SeerrMediaInfo | None:
        await asyncio.sleep(0)  # a real yield, so single-flight is genuinely exercised
        self.calls += 1
        if tmdb_id in self.fail_ids:
            raise UpstreamUnavailable("down")
        return SeerrMediaInfo(status=self.code)


def _service(fake: FakeSeerrClient) -> AvailabilityService:
    return AvailabilityService(cast("SeerrClient", fake), Cache())


async def test_fresh_value_skips_the_loader() -> None:
    fake = FakeSeerrClient()
    service = _service(fake)

    assert (await service.status("movie", 1)).status == "available"
    assert (await service.status("movie", 1)).status == "available"
    assert fake.calls == 1  # second call served from cache within TTL


async def test_concurrent_misses_collapse_to_one_fetch() -> None:
    fake = FakeSeerrClient()
    service = _service(fake)

    results = await asyncio.gather(*(service.status("movie", 1) for _ in range(5)))

    assert all(r.status == "available" for r in results)
    assert fake.calls == 1  # single-flight


async def test_cold_error_degrades_to_unknown() -> None:
    fake = FakeSeerrClient()
    fake.fail_ids = {1}
    service = _service(fake)

    assert await service.status("movie", 1) == UNKNOWN


async def test_error_never_serves_a_stale_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # ttl=0 forces a refresh every call; stale=0 means a failed refresh cannot serve
    # the prior value — it must degrade to Unknown (SPEC §10, not TMDB's stale-on-error).
    monkeypatch.setattr(avail, "AVAIL_OPTS", CacheOpts(ttl=0, stale=0))
    fake = FakeSeerrClient()
    service = _service(fake)

    assert (await service.status("movie", 1)).status == "available"  # prime a good value
    fake.fail_ids = {1}
    assert await service.status("movie", 1) == UNKNOWN  # not the stale "available"


async def test_unconfigured_service_is_unknown_without_a_client() -> None:
    service = AvailabilityService(None, Cache())

    assert await service.status("movie", 1) == UNKNOWN


async def test_batch_degrades_per_item() -> None:
    fake = FakeSeerrClient()
    fake.fail_ids = {2}
    service = _service(fake)

    result = await service.batch([("movie", 1), ("tv", 2)])

    assert result["movie:1"].status == "available"
    assert result["tv:2"] == UNKNOWN
