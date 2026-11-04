# Unreleased

The published image remains `2.3.1`. These notes describe current source since
that release, including the earlier linked-account work and eight subsequent
changes. No release version has been assigned. The
[published Compose example](../../compose.example.yaml) stays pinned until
[release readiness](../RELEASING.md) selects a version.

## Before upgrading

- Stop the writer, back up and validate SQLite, and record the running immutable
  image digest. Startup applies migrations `0007`–`0010` automatically.
- Migration `0007` signs everyone out once. Sign in again after upgrading;
  existing taste signals, profiles, My List, and onboarding choices are preserved.
- **Watched hiding is on by default**, including for existing households.
  Watched movies and series with any watched episode disappear from discovery,
  even when the history source is switched off for taste learning. Not interested
  always hides dismissed titles. Search, My List, Continue Watching, and direct
  detail stay accessible. Discover rails refill; Trending can shrink or disappear.
  Turn off **Hide titles members have watched** in Settings or set
  `TASTERR_HIDE_WATCHED_ITEMS=false` to restore watched titles on generic rails.
- Keep `TASTERR_SECRET_KEY` stable: linked Plex tokens, Seerr cookies, and Trakt
  token sets use it for encryption.

## Accounts and sign-in

- Accounts belong to Tasterr. Members manage Plex, Seerr, Jellyfin, and optional
  Trakt links from **Account** (`/account`). Display names follow Seerr → Plex →
  Jellyfin; avatars render as initials. Linked credentials survive sign-out and
  work across devices and sign-in methods.
- `PLEX_SERVER_ID` enables Plex sign-in without Seerr, gates every Plex sign-in
  and link by server membership, pins future history/Continue Watching reads, and
  grants the pinned server owner admin. Members without that server lose Plex
  access even if Seerr previously admitted them. Older imported watches remain
  until cleared or reset.
- Jellyfin sign-in uses `JELLYFIN_INTERNAL_URL` plus `JELLYFIN_API_KEY`.
  Passwords are sent to Jellyfin for authentication and, when Seerr is configured
  and is not known to refuse Jellyfin, once to Seerr's Jellyfin login. The temporary
  Jellyfin token is logged out/discarded. Jellyfin administrators also administer Tasterr.
  Exposing Tasterr exposes Jellyfin password sign-in from Tasterr's address,
  bypassing Jellyfin's local-network rules. Wrong passwords can lock accounts
  (10 attempts/minute/client IP). `JELLYFIN_ALLOW_EMPTY_PASSWORD` defaults false;
  enabling it permits passwordless sign-in and either Jellyfin linking path.
- Seerr is optional with direct Plex or Jellyfin configured. Without a Plex pin,
  Seerr still gates Plex sign-in. Proven links resolve local identity; there is
  no email matching or account merge. Link the new provider from Account before
  switching sign-in methods or removing Seerr. Explicit Seerr unlink prevents
  automatic reconnection until manually linked again.
- Seerr linking now follows its detected media-server type and login toggles.
  Known-refused methods receive no credentials; unknown settings preserve the
  existing attempt path. Accepted Plex/Jellyfin auto-link refusal is ignored;
  an outage blocks only a would-be new user to preserve identities. The Connect
  Seerr dialog names the active credential form, opens the first accepted form,
  and offers a toggle only when both forms are accepted. Settings → Connections
  shows detected methods, mismatch warnings, and Plex/Jellyfin connection tests.
  See [mixed setups](../CONFIGURATION.md#mixed-setups).
- Admins choose offered sign-in methods in Settings. Hiding a method leaves
  linking, history, Continue Watching, and requests configured. Settings previews
  affected members and prevents the saving admin's self-lockout; Account warns
  stranded members. The optional `TASTERR_SIGN_IN_METHODS` JSON allowlist locks
  this choice and provides [lockout recovery](../CONFIGURATION.md#sign-in-methods-and-lockout-recovery).
- Sessions retain their 30-day sliding window and gain a 90-day absolute cap.
  Admission and admin checks rerun at sign-in; revocation is not immediate.
- Unlink requires another linked method currently offered for sign-in. Trakt can
  always be unlinked and never counts toward that rule. Members may retain or
  delete a link's imported history. Delete account removes all local data and
  sessions; upstream accounts remain, with best-effort Trakt grant revocation.
  Request controls can connect Seerr inline and retry once.

## Discovery and taste

- Admins choose a household TMDB metadata language in Settings (default
  `en-US`). Display text follows it with TMDB's original-text fallback; images
  and trailers prefer that language, then English, then neutral assets. The UI
  and recommendation vocabulary remain English. No environment override or
  migration is needed.
- Jellyfin adds resumable movies/episodes and next-up episodes to Continue
  Watching. Plex and Jellyfin merge into one five-minute cached rail, with newest
  known activity per TMDB title. One failed source leaves the other contribution;
  cards open Tasterr detail. Jellyfin playback links remain deferred. Next-up
  dates use a bounded recent-episode lookup. Taste toggles do not affect resume.
- Seerr request history syncs incrementally. Plex/Jellyfin history imports
  bounded watched facts; episodes map to series. `TASTERR_WATCH_HISTORY_DAYS`
  configures their first-sync lookback (1–3650 days, default 365). Later syncs
  keep their caps and 24-hour overlap. Changing it needs a restart, then
  **Reset taste profile** or switching the affected source off and on to re-import.
- Optional Trakt links import all-time history across services, bounded to the
  newest 500 unique movies and 500 unique shows within ten pages per type,
  independently of `TASTERR_WATCH_HISTORY_DAYS`. Trakt is a taste source only:
  no sign-in, admin, display identity, Seerr requests, or Continue Watching.
  Each title contributes only its newest watch across enabled Plex/Jellyfin/Trakt
  sources, preventing duplicate watch weight. Watches anchor Because You Watched
  and participate in watched hiding.
- All five taste sources start on: Seerr request history, Plex/Jellyfin/Trakt watch
  history, and browsing activity. Off stops collection and removes influence and
  rail anchors without deleting signals; on resets link sync times for bounded
  re-import. Deliberate requests, My List/onboarding, and Not interested always count.
- **Clear imported history** removes one source's signals, retaining its toggle
  and watermark. The 24-hour overlap can re-import recent activity; a never-synced
  source can re-import its full bounded window. Retained watched signals still
  exclude titles from Recommended for You with their source off.
- **Reset taste profile** deletes all taste signals, including My List and
  Not interested, clears sync times, and schedules enabled imports in the
  background. Source preferences and onboarding completion are preserved.

## New deployment variables and Trakt setup

See the [complete environment reference](../CONFIGURATION.md#application-environment-variables)
for the earlier account variables and these additions:

| Variable | Default | Upgrade use |
|---|---|---|
| `TASTERR_HIDE_WATCHED_ITEMS` | unset; household preference starts on | `true`/`false` overrides and locks watched hiding. |
| `TASTERR_WATCH_HISTORY_DAYS` | `365` | Initial Plex/Jellyfin lookback, 1–3650 days; restart and re-import to change existing links. |
| `TASTERR_SIGN_IN_METHODS` | unset; all configured methods offered | JSON array of 1–3 unique `plex`/`jellyfin`/`seerr` names; locks sign-in choices. |
| `TRAKT_CLIENT_ID` | unset | Operator-owned app id; requires the stable `TASTERR_SECRET_KEY`. |
| `TRAKT_CLIENT_SECRET` | unset | Optional secret, only if issued by Trakt. |

For Trakt, register your own **Development** app with Redirect URI
`http://localhost`, add household members as testers in its Members panel, and
set `TRAKT_CLIENT_ID` (plus `TRAKT_CLIENT_SECRET` if issued). Members then choose
**Link Trakt** in Account and approve the displayed device code. Keep app values
server-side. Read the [Trakt setup instructions](../CONFIGURATION.md#trakt-watch-history)
for developer verification, member allowances, token revocation, and import limits.

## Migration and rollback limits

**An image-only rollback across these revisions is unsupported.** Stop the writer
and restore a matching validated pre-upgrade backup, or use the current image's
Alembic downgrade before starting older code.

| Revision | Upgrade | Destructive downgrade |
|---|---|---|
| `0010` → `0009` | Adds Trakt signal uniqueness and clears rebuildable profiles for watch deduplication. | **Deletes Trakt links and imported history**, removes only Trakt source preferences, and invalidates affected profiles; users and other links remain. |
| `0009` → `0008` | Adds per-member taste-source preferences. | Removes source preferences and invalidates affected profiles without deleting history; older code resumes configured imports. |
| `0008` → `0007` | Adds Jellyfin signal uniqueness. | Deletes Jellyfin links/history and Jellyfin-only users with their local data. |
| `0007` → `0006` | Creates local identities/links and signs everyone out once. | Deletes users without a Seerr link and all their local data; restores retained Seerr identities and deletes every session. |

Back up and validate before any downgrade. Follow the
[upgrade and rollback procedure](../CONFIGURATION.md#upgrade-and-rollback).
