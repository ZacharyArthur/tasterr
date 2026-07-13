"""Pure normalization: summaries, trailer/logo picks, detail mapping (task 2.2)."""

from tasterr.catalog.normalize import (
    pick_logo,
    pick_trailer,
    to_detail,
    to_regions,
    to_services,
    to_summaries,
    to_summary,
)
from tasterr.clients.tmdb import (
    TmdbCastMember,
    TmdbContentRatingEntry,
    TmdbContentRatings,
    TmdbCredits,
    TmdbCrewMember,
    TmdbDetail,
    TmdbGenre,
    TmdbImage,
    TmdbImages,
    TmdbMediaResult,
    TmdbProvider,
    TmdbRegion,
    TmdbReleaseDateItem,
    TmdbReleaseDates,
    TmdbReleaseDatesEntry,
    TmdbSeason,
    TmdbVideo,
    TmdbVideos,
    TmdbWatchEntry,
    TmdbWatchProvider,
    TmdbWatchProviders,
)


def test_to_summary_movie() -> None:
    raw = TmdbMediaResult(
        id=1, media_type="movie", title="A", poster_path="/p.jpg", release_date="2020-05-01"
    )
    summary = to_summary(raw, None)
    assert summary is not None
    assert summary.media_type == "movie"
    assert summary.title == "A"
    assert summary.year == 2020


def test_to_summary_tv_inferred_from_name() -> None:
    raw = TmdbMediaResult(id=2, name="Show", first_air_date="2019-01-01")
    summary = to_summary(raw, None)
    assert summary is not None
    assert summary.media_type == "tv"
    assert summary.title == "Show"
    assert summary.year == 2019


def test_to_summaries_drops_person_results() -> None:
    results = [
        TmdbMediaResult(id=1, media_type="movie", title="A"),
        TmdbMediaResult(id=2, media_type="person", name="Actor"),
    ]
    assert [s.id for s in to_summaries(results, None)] == [1]


def test_to_summary_uses_fallback_when_type_absent() -> None:
    raw = TmdbMediaResult(id=4)  # no media_type, no title, no name
    summary = to_summary(raw, "tv")
    assert summary is not None
    assert summary.media_type == "tv"
    assert summary.title == "Untitled"


def test_pick_trailer_prefers_official_trailer() -> None:
    videos = [
        TmdbVideo(key="teaser01", site="YouTube", type="Teaser", official=True),
        TmdbVideo(key="trailer01", site="YouTube", type="Trailer", official=True),
    ]
    trailer = pick_trailer(videos)
    assert trailer is not None
    assert trailer.key == "trailer01"


def test_pick_trailer_drops_malformed_key() -> None:
    assert pick_trailer([TmdbVideo(key="bad key!", site="YouTube", type="Trailer")]) is None


def test_pick_trailer_none_without_youtube() -> None:
    assert pick_trailer([TmdbVideo(key="abc", site="Vimeo", type="Trailer")]) is None


def test_pick_logo_prefers_english() -> None:
    logos = [
        TmdbImage(file_path="/de.png", iso_639_1="de", vote_average=9.0),
        TmdbImage(file_path="/en.png", iso_639_1="en", vote_average=1.0),
    ]
    assert pick_logo(logos) == "/en.png"


def test_pick_logo_none_when_empty() -> None:
    assert pick_logo([]) is None


def _movie_detail() -> TmdbDetail:
    return TmdbDetail(
        id=42,
        title="Deep",
        overview="o",
        runtime=120,
        tagline="A tag",
        genres=[TmdbGenre(id=18, name="Drama")],
        videos=TmdbVideos(
            results=[TmdbVideo(key="abc123", site="YouTube", type="Trailer", official=True)]
        ),
        images=TmdbImages(logos=[TmdbImage(file_path="/en.png", iso_639_1="en", vote_average=5.0)]),
        credits=TmdbCredits(
            cast=[TmdbCastMember(id=9, name="Actor", character="Hero", order=0)],
            crew=[
                TmdbCrewMember(id=1, name="Dir", job="Director"),
                TmdbCrewMember(id=2, name="Grip", job="Grip"),
            ],
        ),
        release_dates=TmdbReleaseDates(
            results=[
                TmdbReleaseDatesEntry(
                    iso_3166_1="US", release_dates=[TmdbReleaseDateItem(certification="PG-13")]
                )
            ]
        ),
        watch_providers=TmdbWatchProviders(
            results={
                "US": TmdbWatchEntry(
                    flatrate=[
                        TmdbWatchProvider(
                            provider_id=8, provider_name="Netflix", display_priority=1
                        )
                    ]
                )
            }
        ),
    )


def test_to_detail_maps_movie_fields() -> None:
    detail = to_detail(_movie_detail(), "movie", "US")
    assert detail.runtime == 120
    assert detail.certification == "PG-13"
    assert detail.logo_path == "/en.png"
    assert detail.trailer is not None
    assert detail.trailer.key == "abc123"
    assert [p.name for p in detail.cast] == ["Actor"]
    assert [p.name for p in detail.crew] == ["Dir"]  # non-key crew filtered out
    assert detail.watch.flatrate[0].name == "Netflix"


def test_to_detail_tv_drops_specials_and_reads_content_rating() -> None:
    raw = TmdbDetail(
        id=5,
        name="Show",
        seasons=[
            TmdbSeason(season_number=0, name="Specials"),
            TmdbSeason(season_number=1, name="Season 1", episode_count=8),
        ],
        content_ratings=TmdbContentRatings(
            results=[TmdbContentRatingEntry(iso_3166_1="US", rating="TV-MA")]
        ),
    )
    detail = to_detail(raw, "tv", "US")
    assert [s.season_number for s in detail.seasons] == [1]
    assert detail.certification == "TV-MA"


def test_to_detail_watch_empty_when_region_absent() -> None:
    raw = TmdbDetail(
        id=7,
        title="M",
        watch_providers=TmdbWatchProviders(
            results={"GB": TmdbWatchEntry(flatrate=[TmdbWatchProvider(provider_id=1)])}
        ),
    )
    assert to_detail(raw, "movie", "US").watch.flatrate == []


def test_region_options_are_named_and_sorted() -> None:
    options = to_regions(
        [
            TmdbRegion(iso_3166_1="US", english_name="United States"),
            TmdbRegion(iso_3166_1="GB", english_name="United Kingdom"),
        ]
    )
    assert [(item.code, item.name) for item in options] == [
        ("GB", "United Kingdom"),
        ("US", "United States"),
    ]


def test_services_union_movie_and_tv_using_best_priority() -> None:
    movie = [
        TmdbProvider(
            provider_id=8,
            provider_name="Netflix",
            logo_path="/movie.png",
            display_priorities={"US": 4},
        )
    ]
    tv = [
        TmdbProvider(
            provider_id=8,
            provider_name="Netflix",
            logo_path="/tv.png",
            display_priorities={"US": 1},
        ),
        TmdbProvider(
            provider_id=337,
            provider_name="Disney Plus",
            display_priorities={"US": 2},
        ),
    ]

    services = to_services(movie, tv, "US")

    assert [(item.provider_id, item.display_priority) for item in services] == [(8, 1), (337, 2)]
    assert services[0].logo_path == "/tv.png"
