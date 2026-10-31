## Why

Seerr is backed by exactly one media server, but Tasterr treats every Seerr as
accepting Plex, Jellyfin, and local sign-in. In mixed households (for example
Plex + Jellyfin + a Plex-backed Seerr) members are offered Seerr link methods
that can only fail, Tasterr forwards Jellyfin passwords and Plex tokens to a
Seerr that will refuse them, and neither members nor admins are told what will
and will not work. Seerr already publishes its media server type and login
toggles on `/api/v1/settings/public`, which Tasterr reads today for season
policy, so the gap is cheap to close.

This advances the existing `account-linking` capability (linked accounts and
configurable taste sources, archived 2026-10-18) by making its Seerr link and
auto-link behavior aware of the household's actual Seerr setup.

## What Changes

- Read Seerr's media server type and its Plex, Jellyfin, and local login toggles
  from the public settings Tasterr already parses, cached briefly. Anything
  missing, malformed, or unreachable is **unknown**, and unknown keeps today's
  behavior.
- Skip the Seerr auto-link attempt at Plex or Jellyfin sign-in when Seerr is
  known not to accept that method, so credentials are not forwarded to a Seerr
  that will refuse them.
- Refuse a manual Seerr link by a method Seerr is known not to accept, without
  forwarding the credentials, with a clear (non-generic) explanation.
- `GET /api/v1/account` reports which Seerr link methods Seerr accepts, as
  booleans. The Account page and the request control's Connect Seerr dialog hide
  refused methods and explain the member's remaining options (for example: ask
  the admin for a Seerr local account, or link Plex).
- A new admin-only, read-only integration summary in Settings → Connections:
  Seerr's media server type, its accepted login methods, and fixed warnings for
  known mismatches (for example: Plex sign-in depends on Seerr but Seerr is not
  Plex-backed and `PLEX_SERVER_ID` is unset; Jellyfin-only members cannot request
  unless Seerr local login is enabled).
- Settings → Connections gains **Test Plex** and **Test Jellyfin** next to the
  existing TMDB and Seerr tests. Both check through the admin's own linked
  account (Tasterr has no server-wide Plex credential, and the Jellyfin API key is
  only used for reads scoped to a user). They return fixed, secret-free details
  such as "Link Plex on your Account page to test it" or "Plex.tv works, but no
  Plex server was reachable".
- `docs/CONFIGURATION.md` gains a "Mixed setups" section: what depends on what,
  and what happens for each common combination of Plex, Jellyfin, and Seerr.

## Non-goals

- The login screen and `GET /api/v1/auth/methods` are unchanged: that endpoint is
  unauthenticated and stays free of upstream calls.
- No change to request permissions, the re-auth ladder, or quotas.
- No Emby support. An Emby-backed Seerr counts as not accepting Tasterr's
  Jellyfin credentials.
- No new environment variables and no override for detected values.
- Jellyfin Continue Watching is a separate change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-linking`: Seerr auto-link at sign-in and manual Seerr linking honor
  the Seerr login methods Seerr is known to accept; the account summary reports
  them; the Account page explains remaining options; the Connect Seerr dialog
  opens on the first offered form and shows its toggle only when both forms
  are offered.
- `media-requests`: the Connect Seerr dialog offers only methods Seerr is not
  known to refuse and explains when none fit.
- `app-settings`: admins get a read-only Seerr integration summary with mismatch
  warnings; the connection test accepts `plex` and `jellyfin`.

## Impact

- Backend: `clients/seerr.py` (public settings model), `api/auth.py` (auto-link
  gating), `api/account.py` (link refusal, summary field), `api/admin.py` (summary
  endpoint, Plex and Jellyfin connection tests), `clients/jellyfin.py` (public
  server-info read), shared cached read in the Seerr API wiring.
- Frontend: generated API types, `ConnectSeerr.tsx`, `Account.tsx`,
  `Settings.tsx` (Connections section).
- Docs: `docs/CONFIGURATION.md`.
- No migration, no new dependency, no new secret, no new environment variable.
- Landing order: seerr-login-mode-label → tmdb-metadata-language →
  discovery-exclusions-everywhere → watch-history-window →
  jellyfin-continue-watching → sign-in-method-allowlist →
  seerr-media-server-awareness → trakt-watch-history. This change modifies the
  "Connect Seerr dialog names the active credentials" requirement that
  `seerr-login-mode-label` adds, so the dialog opens on the first offered form.
