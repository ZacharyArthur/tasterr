import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient


@pytest.mark.parametrize(
    "status", [200, 201, 204, 301, 302, 400, 401, 403, 404, 429, 500, 501, 502, 503, 504]
)
@pytest.mark.parametrize("followup", [False, True])
async def test_seerr_login_outage_vs_refusal(status: int, followup: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if followup and request.method == "POST":
            return httpx.Response(200, json={"id": 1}, headers={"set-cookie": "connect.sid=cookie"})
        return httpx.Response(status, json={"id": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SeerrAuthClient(http, "http://seerr")
        with pytest.raises(UpstreamUnavailable if status in (502, 503, 504) else UpstreamRejected):
            if followup:
                await client.login_local("email", "password")
            else:
                await client.login_plex("token")


@pytest.mark.parametrize("status", [302, 401, 404, 500, 502, 503, 504])
async def test_admin_read_classification(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as http:
        client = SeerrClient(http, "http://seerr", "key")
        with pytest.raises(UpstreamUnavailable if status in (502, 503, 504) else UpstreamRejected):
            await client.user(1)


@pytest.mark.parametrize("body", [{}, {"id": 2}, {"id": "bad"}])
async def test_admin_malformed_or_mismatched_identity_refuses(body: dict[str, object]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(UpstreamRejected):
            await SeerrClient(http, "http://seerr", "key").user(1)
