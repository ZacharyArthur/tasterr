# Proposal: jellyfin-integration

## Why

Households that run Jellyfin instead of Plex get no automatic taste learning:
watch history import and "Because You Watched" are Plex-only, so every member has
to build a profile by hand (GitHub #47). After `linked-accounts` and
`plex-direct-login`, adding a provider is a matter of plugging a new linked
account into existing patterns.

Third of four changes; depends on `linked-accounts` and `plex-direct-login`.
Advances `account-linking`, `taste-signals`, and `taste-recommendations`; adds
`jellyfin-personalization`.

## What Changes

- **Configuration:** `JELLYFIN_INTERNAL_URL` + `JELLYFIN_API_KEY` (env only,
  server-side only). Jellyfin features turn on when both are set.
- **New `clients/jellyfin.py`:** typed, bounded, header-only auth. The API key is
  used only for reads scoped to one Jellyfin user id; no user token is stored.
- **Jellyfin sign-in** (`POST /auth/jellyfin`): username/password checked once
  with `AuthenticateByName`; the returned access token is logged out right away;
  only the Jellyfin user id is linked. Any enabled user on the configured server
  is admitted, except passwordless accounts, which are refused unless the
  operator sets `JELLYFIN_ALLOW_EMPTY_PASSWORD=true`. Shows as a "Continue
  with Jellyfin" pill on the login screen.
- **Seerr auto-link** with the same Jellyfin credentials (Seerr's Jellyfin
  login), discarded after the call. A Seerr refusal never blocks Jellyfin sign-in;
  a Seerr outage blocks only a first sign-in that would create a new user.
- **Linking from `/account`:** Jellyfin card (username/password), and a
  `jellyfin` method for linking Seerr.
- **Watch history sync:** new `watched_jellyfin` signal (+2.5, unique per title),
  same throttle, watermark, and bounds as Plex. Episodes collapse to their series
  via the series' TMDB id.
- **Admin:** Jellyfin `Policy.IsAdministrator` joins the any-link admin checks.
- **Display identity:** Jellyfin joins the priority last (Seerr → Plex →
  Jellyfin); Jellyfin-only users show initials because Jellyfin avatars live on
  the internal URL.
- **"Because You Watched"** applies to Jellyfin watches too.
- **Migration `0008`:** unique index covers `watched_jellyfin`.

## Capabilities

### New Capabilities

- `jellyfin-personalization`: configuration, client boundary, sign-in, login
  button, and history sync.

### Modified Capabilities

- `account-linking`: `jellyfin` provider; Seerr auto-link from Jellyfin sign-in;
  Jellyfin admin check; display priority; Jellyfin and Seerr-via-Jellyfin
  linking; unlink history kind.
- `user-auth`: `/auth/methods` gains `jellyfin`; `/auth/jellyfin` joins the
  hardened login endpoints; the live Seerr suite covers Jellyfin login and the
  "login disabled" status.
- `taste-signals`: `watched_jellyfin` is server-recorded and unique per title.
- `taste-recommendations`: weight +2.5; "Because You Watched" label; Jellyfin
  watches excluded from recommended-for-you; reset covers Jellyfin sync.
- `app-database`: migration `0008`.
- `release-readiness`: the live Jellyfin contract suite is a required release
  check.
- `app-settings`: Jellyfin settings.

## Impact

- **Backend:** `settings.py`; new `clients/jellyfin.py`; `api/auth.py`
  (`/auth/jellyfin`, methods); `api/account.py` (Jellyfin link, Seerr `jellyfin`
  method); `auth/login.py` (admin, display); sync scheduling alongside Plex in
  `api/taste.py`; new `recommend/jellyfin_history.py` (import mapping);
  `recommend/signals.py` (new kind); `rails/registry.py` (label); migration
  `0008`.
- **Frontend:** Jellyfin pill on `Login.tsx`; Jellyfin card and Seerr method on
  `Account.tsx`; regenerated `api.gen.ts`.
- **Deploy/docs:** `.env.example`, README, `docs/SECURITY.md` outbound-HTTP
  section for Jellyfin.
- **Testing:** opt-in live Jellyfin contract test (excluded from `just check`),
  mirroring the live Plex/Seerr suites. No new dependency.

## Non-goals

- Jellyfin "Play" links and a Jellyfin Continue Watching rail (backlog; needs a
  browser-facing Jellyfin URL).
- Jellyfin avatars (backlog; need a proxy route).
- Emby (backlog; likely a thin variant later).
- Storing per-user Jellyfin tokens, or using the API key for any write.
- Signing in to Seerr's Jellyfin login from the Seerr email form (the agreed
  gap: Jellyfin-backed Seerr users configure Jellyfin in Tasterr).
- A generic media-server abstraction shared with Plex: only the signal write path
  is shared.
