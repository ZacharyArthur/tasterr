"""Server-held device attempts and the encrypted Trakt credential payload."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from tasterr.clients.trakt import TokenResponse


@dataclass
class DeviceAttempt:
    device_code: str = field(repr=False)
    interval: int
    last_poll: float


class TraktCredential(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str = Field(min_length=1, repr=False)
    expires_at: float = Field(allow_inf_nan=False)

    @classmethod
    def from_response(cls, response: TokenResponse) -> "TraktCredential":
        return cls(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            expires_at=float(response.created_at + response.expires_in),
        )

    def needs_refresh(self) -> bool:
        return self.expires_at <= datetime.now(UTC).timestamp() + 300
