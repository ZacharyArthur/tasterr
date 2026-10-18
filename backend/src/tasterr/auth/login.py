"""Proven external accounts resolve local users; links own credentials."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.crypto import encrypt_token
from tasterr.auth.sessions import mint_session
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexCloudAccount
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
    credential: str

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
    link.credential_enc = encrypt_token(secret_key, account.credential)
    await db.flush()
    return link


async def resolve_user(
    db: AsyncSession,
    secret_key: str,
    account: ProvenAccount,
    seerr_login: SeerrLogin | None,
) -> User:
    for attempt in range(2):
        try:
            owner = await _owner(db, account)
            bridge = await _owner(db, ProvenAccount.seerr(seerr_login)) if seerr_login else None
            resolved = owner or bridge
            user = await db.get(User, resolved.user_id) if resolved else None
            if user is None:
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
    links: list[LinkedAccount], previous: bool, seerr: SeerrClient | None
) -> bool:
    for link in links:
        if link.provider == "seerr" and seerr is not None:
            try:
                upstream = await seerr.user(int(link.external_id))
            except UpstreamUnavailable:
                return previous
            except UpstreamRejected:
                continue
            if upstream.permissions & ADMIN_PERMISSION:
                return True
    return False


async def complete_login(
    db: AsyncSession,
    secret_key: str,
    account: ProvenAccount,
    seerr_login: SeerrLogin | None,
    seerr: SeerrClient | None,
) -> tuple[User, str]:
    user = await resolve_user(db, secret_key, account, seerr_login)
    links = list(
        (await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user.id))).all()
    )
    is_admin = await derive_admin(links, user.is_admin, seerr)
    display = next(
        (link for provider in ("seerr", "plex") for link in links if link.provider == provider),
        None,
    )
    user.is_admin = is_admin
    if display is not None:
        user.display_name, user.avatar_url = display.display_name, display.avatar_url
    user.last_login_at = utcnow()
    token = await mint_session(db, user.id)
    return user, token
