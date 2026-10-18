"""Prove a Jellyfin identity without retaining its authentication token."""

import logging

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.jellyfin import JellyfinClient, JellyfinUser

logger = logging.getLogger(__name__)


async def authenticate_and_logout(
    client: JellyfinClient, username: str, password: str, *, allow_empty_password: bool
) -> JellyfinUser:
    if not password and not allow_empty_password:
        raise UpstreamRejected(401)
    login = await client.authenticate(username, password)
    try:
        await client.logout(login.access_token)
    except (UpstreamRejected, UpstreamUnavailable):
        logger.warning("auth: jellyfin token logout failed")
    if login.user.policy.is_disabled:
        raise UpstreamRejected(401)
    return login.user
