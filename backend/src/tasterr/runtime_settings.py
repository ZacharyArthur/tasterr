"""Typed, non-secret household runtime preferences (M5).

Deployment connections and secrets remain in :mod:`tasterr.settings`.  This
module intentionally has no URL, key, token, cookie, or credential field, which
makes the env/DB boundary structural rather than convention-based.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

DEFAULT_REGION = "US"
MAX_SELECTED_SERVICES = 8


class Theme(StrEnum):
    DARK = "dark"
    LIGHT = "light"


class Accent(StrEnum):
    CRIMSON = "crimson"
    AZURE = "azure"
    VIOLET = "violet"
    EMERALD = "emerald"
    AMBER = "amber"


class RailType(StrEnum):
    HERO = "hero"
    CONTINUE_WATCHING = "continue-watching"
    MY_LIST = "my-list"
    TRENDING = "trending"
    MORE_LIKE = "more-like"
    POPULAR = "popular"
    RECOMMENDED = "recommended"
    UNEXPECTED_PICKS = "unexpected-picks"
    HOUSEHOLD_BLEND = "household-blend"
    SERVICES = "services"
    GENRES = "genres"
    RECENT = "recent"
    TOP_RATED = "top-rated"
    DECADES = "decades"


RAIL_TYPE_LABELS: dict[RailType, str] = {
    RailType.HERO: "Featured hero",
    RailType.CONTINUE_WATCHING: "Continue Watching",
    RailType.MY_LIST: "My List",
    RailType.TRENDING: "Trending",
    RailType.MORE_LIKE: "More like your favorites",
    RailType.POPULAR: "Popular in your region",
    RailType.RECOMMENDED: "Recommended for you",
    RailType.UNEXPECTED_PICKS: "Picks You Wouldn't Usually Watch",
    RailType.HOUSEHOLD_BLEND: "Something for Everyone Tonight",
    RailType.SERVICES: "Selected services",
    RailType.GENRES: "Genres",
    RailType.RECENT: "Recent releases",
    RailType.TOP_RATED: "Top rated",
    RailType.DECADES: "By decade",
}


class Appearance(BaseModel):
    theme: Theme = Theme.DARK
    accent: Accent = Accent.CRIMSON


class RuntimeSettings(BaseModel):
    region: str = DEFAULT_REGION
    service_ids: list[int] = Field(default=[], max_length=MAX_SELECTED_SERVICES)
    disabled_rail_types: list[RailType] = []
    appearance: Appearance = Field(default_factory=Appearance)

    @field_validator("region", mode="before")
    @classmethod
    def normalize_region(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str) -> str:
        if len(value) != 2 or not value.isascii() or not value.isalpha():
            raise ValueError("region must be a two-letter country code")
        return value

    @field_validator("service_ids")
    @classmethod
    def validate_service_ids(cls, value: list[int]) -> list[int]:
        if any(service_id <= 0 for service_id in value):
            raise ValueError("service ids must be positive")
        if len(value) != len(set(value)):
            raise ValueError("service ids must be unique")
        return value

    @field_validator("disabled_rail_types")
    @classmethod
    def validate_disabled_rail_types(cls, value: list[RailType]) -> list[RailType]:
        if len(value) != len(set(value)):
            raise ValueError("disabled rail types must be unique")
        return value


class RailTypeDescriptor(BaseModel):
    id: RailType
    label: str


def rail_type_descriptors() -> list[RailTypeDescriptor]:
    return [
        RailTypeDescriptor(id=rail_type, label=RAIL_TYPE_LABELS[rail_type])
        for rail_type in RailType
    ]
