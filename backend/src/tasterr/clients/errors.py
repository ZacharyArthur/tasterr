"""Typed upstream failures. `api/` maps these to generic client errors —
upstream bodies, headers, and URLs never reach the browser."""


class UpstreamError(Exception):
    """Base for failures talking to plex.tv or Seerr."""


class UpstreamUnavailable(UpstreamError):
    """Timeout, transport failure, 5xx, or a response we cannot parse."""


class UpstreamRejected(UpstreamError):
    """The upstream understood the request and said no (4xx)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"upstream rejected the request ({status_code})")
        self.status_code = status_code
