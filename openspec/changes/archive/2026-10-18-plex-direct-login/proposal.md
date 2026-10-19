# Proposal: plex-direct-login

## Why

After `linked-accounts`, users are Tasterr-owned, but Plex sign-in still goes
through Seerr: Seerr accepting the Plex token is the only gate, so Seerr remains
a hard dependency (GitHub #34). Tasterr also has no notion of *which* Plex server
it belongs to. It reads history and Continue Watching from up to four servers the
user can see, so a user's history can be read from an unrelated server shared
with them by a friend.

Second of four changes; depends on `linked-accounts`. Advances `user-auth`,
`plex-personalization`, and `container-deploy`.

## What Changes

- **`PLEX_SERVER_ID`** (optional env setting, the server's machine identifier):
  - **Sign-in gate:** with it set, a Plex account may sign in, or be linked,
    only if its plex.tv resources include that server (owner, shared, and Plex
    Home users). The check runs on every sign-in, so an existing link can't
    bypass a revoked share.
  - **Server pinning:** history sync and Continue Watching read only that server.
  - **Admin:** the server's owner is admin (an extra "any link grants" check).
- **Seerr becomes optional.** With `PLEX_SERVER_ID` set, Plex sign-in works
  without Seerr; when Seerr is configured, auto-link is still attempted. A Seerr
  refusal never blocks sign-in, and a Seerr outage blocks only a first sign-in
  that would create a new user, so existing members are never split. Without `PLEX_SERVER_ID`, Plex sign-in keeps today's Seerr gate, so
  existing deployments need no config change.
- **Sessions get a 90-day absolute lifetime** on top of the 30-day sliding
  window, so revoked shares and admin demotions take effect within 90 days.
- **`GET /api/v1/auth/methods`:** unauthenticated, booleans only (`plex`,
  `seerr`), so the login screen knows which buttons to show.
- **Login screen:** a full-width stack of rounded single-sign-on-style pill
  buttons ("Continue with Plex", "Continue with Seerr"), each with the service's
  mark as inline SVG; only configured methods appear; the Seerr form expands in
  place.
- **Compose and env example:** Seerr is optional; `PLEX_SERVER_ID` documented.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-auth`: Plex sign-in gated by `PLEX_SERVER_ID` or Seerr; 90-day absolute
  session lifetime; sign-in methods
  endpoint; new login screen; "Auth degrades when Seerr is unavailable or
  unconfigured" replaced by "Auth degrades when no sign-in method is available".
- `account-linking`: Plex owner admin check; Plex links require server access
  and available Plex sign-in; provider availability follows the new gate.
- `plex-personalization`: discovery pinned to `PLEX_SERVER_ID` when set.
- `app-settings`: `PLEX_SERVER_ID` setting.
- `container-deploy`: Compose example no longer assumes Seerr.

## Impact

- **Backend:** `settings.py` (`PLEX_SERVER_ID` + validator); `api/auth.py`
  (gating, `/auth/methods`, context no longer requires Seerr for Plex);
  `clients/plex.py` discovery filter; admin check in `auth/login.py`;
  `api/account.py` Plex-link gate.
- **Frontend:** `routes/Login.tsx` rebuilt around pill buttons and
  `/auth/methods`; small inline SVG marks. Regenerated `api.gen.ts`.
- **Deploy/docs:** `.env.example`, `docker-compose.yml` comments, README setup
  section, `docs/SECURITY.md` Plex connection checklist (one pinned resource).
- **No new dependency, no migration.**

## Non-goals

- Jellyfin sign-in (`jellyfin-integration`), which reuses this login screen.
- An admin allowlist or approval queue for new Plex accounts.
- Discovering `PLEX_SERVER_ID` automatically or editing it at runtime: it is a
  deployment setting, read from the environment only.
- Tasterr-owned passwords or reverse-proxy sign-in (backlog).
