"""Proven external accounts resolve local users; links own credentials."""

from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.crypto import decrypt_token, encrypt_token
from tasterr.auth.sessions import mint_session
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.jellyfin import JellyfinClient, JellyfinUser
from tasterr.clients.plex import PlexAuthClient, PlexCloudAccount, PlexResourceAccess
from tasterr.clients.seerr import SeerrClient, SeerrLogin
from tasterr.db.io import finish_io
from tasterr.db.models import LinkedAccount, Provider, User, utcnow

ADMIN_PERMISSION = 2
CONFLICT_GUIDANCE = (
    "This account belongs to another Tasterr account, "
    "or you must unlink the current account first. "
    "Sign in with each account, keep the one you want, delete the other Tasterr account "
    "from its Account page, then link again."
)


class AccountConflict(Exception):
    pass


@dataclass(frozen=True)
class ProvenAccount:
    provider: Provider
    external_id: str
    display_name: str
    avatar_url: str | None
    credential: str | None

    @classmethod
    def jellyfin(cls, user: JellyfinUser) -> "ProvenAccount":
        return cls("jellyfin", user.id, user.name, None, None)

    @classmethod
    def seerr(cls, login: SeerrLogin) -> "ProvenAccount":
        return cls(
            "seerr",
            str(login.user.id),
            login.user.resolved_display_name,
            login.user.avatar,
            login.cookie,
        )

    @classmethod
    def plex(cls, account: PlexCloudAccount, token: str) -> "ProvenAccount":
        return cls("plex", str(account.id), account.title or account.username, account.thumb, token)


async def get_link(db: AsyncSession, user_id: int, provider: Provider) -> LinkedAccount | None:
    return await finish_io(
        db.scalar(
            select(LinkedAccount).where(
                LinkedAccount.user_id == user_id,
                LinkedAccount.provider == provider,
            )
        )
    )


async def _owner(db: AsyncSession, account: ProvenAccount) -> LinkedAccount | None:
    return await db.scalar(
        select(LinkedAccount).where(
            LinkedAccount.provider == account.provider,
            LinkedAccount.external_id == account.external_id,
        )
    )


async def link_account(
    db: AsyncSession,
    secret_key: str,
    user_id: int,
    account: ProvenAccount,
) -> LinkedAccount:
    """Attach only an authenticated account; callers own the transaction."""
    owner = await _owner(db, account)
    current = await get_link(db, user_id, account.provider)
    if (owner is not None and owner.user_id != user_id) or (
        current is not None and current.external_id != account.external_id
    ):
        raise AccountConflict
    link = current
    if link is None:
        link = LinkedAccount(
            user_id=user_id, provider=account.provider, external_id=account.external_id
        )
        db.add(link)
    link.display_name = account.display_name
    link.avatar_url = account.avatar_url
    link.credential_enc = (
        encrypt_token(secret_key, account.credential) if account.credential is not None else None
    )
    await db.flush()
    return link


async def resolve_user(
    db: AsyncSession,
    secret_key: str,
    account: ProvenAccount,
    seerr_login: SeerrLogin | None,
    *,
    seerr_unavailable: bool = False,
) -> User:
    for attempt in range(2):
        try:
            owner = await _owner(db, account)
            bridge = await _owner(db, ProvenAccount.seerr(seerr_login)) if seerr_login else None
            resolved = owner or bridge
            user = await db.get(User, resolved.user_id) if resolved else None
            if user is None:
                if seerr_unavailable:
                    raise UpstreamUnavailable("Seerr auto-link unavailable")
                user = User(display_name=account.display_name, avatar_url=account.avatar_url)
                db.add(user)
                await db.flush()
            await link_account(db, secret_key, user.id, account)
            if seerr_login is not None and account.provider != "seerr":
                current = await get_link(db, user.id, "seerr")
                if (current is not None and current.external_id == str(seerr_login.user.id)) or (
                    current is None and user.seerr_unlinked_at is None and bridge is None
                ):
                    await link_account(db, secret_key, user.id, ProvenAccount.seerr(seerr_login))
            await db.commit()
            return user
        except (IntegrityError, AccountConflict):
            await db.rollback()
            if attempt:
                raise AccountConflict from None
    raise AssertionError("unreachable")


async def derive_admin(
    links: list[LinkedAccount],
    previous: bool,
    seerr: SeerrClient | None,
    *,
    secret_key: str,
    plex: PlexAuthClient | None,
    server_id: str | None,
    plex_resources: list[PlexResourceAccess] | None,
    jellyfin: JellyfinClient | None = None,
) -> bool:
    errored = False
    for link in links:
        if link.provider == "jellyfin" and jellyfin is not None:
            try:
                jellyfin_user = await jellyfin.user(link.external_id)
            except UpstreamUnavailable:
                errored = True
                continue
            except UpstreamRejected:
                continue
            if jellyfin_user.policy.is_administrator and not jellyfin_user.policy.is_disabled:
                return True
        if link.provider == "seerr" and seerr is not None:
            try:
                upstream = await seerr.user(int(link.external_id))
            except UpstreamUnavailable:
                errored = True
                continue
            except UpstreamRejected:
                continue
            if upstream.permissions & ADMIN_PERMISSION:
                return True
        if link.provider == "plex" and plex is not None and server_id is not None:
            try:
                resources = plex_resources
                if resources is None:
                    if link.credential_enc is None:
                        continue
                    resources = await plex.resources(decrypt_token(secret_key, link.credential_enc))
            except UpstreamUnavailable:
                errored = True
                continue
            except (UpstreamRejected, InvalidToken):
                continue
            if any(item.client_identifier == server_id and item.owned for item in resources):
                return True
    return previous if errored else False


async def complete_login(
    db: AsyncSession,
    secret_key: str,
    account: ProvenAccount,
    seerr_login: SeerrLogin | None,
    seerr: SeerrClient | None,
    *,
    seerr_unavailable: bool = False,
    plex: PlexAuthClient | None = None,
    server_id: str | None = None,
    plex_resources: list[PlexResourceAccess] | None = None,
    jellyfin: JellyfinClient | None = None,
) -> tuple[User, str]:
    user = await resolve_user(
        db, secret_key, account, seerr_login, seerr_unavailable=seerr_unavailable
    )
    links = list(
        (await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user.id))).all()
    )
    is_admin = await derive_admin(
        links,
        user.is_admin,
        seerr,
        secret_key=secret_key,
        plex=plex,
        server_id=server_id,
        plex_resources=plex_resources,
        jellyfin=jellyfin,
    )
    display = next(
        (
            link
            for provider in ("seerr", "plex", "jellyfin")
            for link in links
            if link.provider == provider
        ),
        None,
    )
    user.is_admin = is_admin
    if display is not None:
        user.display_name, user.avatar_url = display.display_name, display.avatar_url
    user.last_login_at = utcnow()
    token = await mint_session(db, user.id)
    return user, token
