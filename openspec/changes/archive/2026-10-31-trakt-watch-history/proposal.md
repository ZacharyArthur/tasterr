## Why

Tasterr learns watch history only from Plex and Jellyfin, from one server each,
starting at a bounded window. Households that watch across several servers or
services often sync everything to Trakt.tv, so titles watched before the window
or elsewhere are unknown to Tasterr and keep appearing in rails. GitHub issue
#54 asks for an optional per-member Trakt link (device-code OAuth) importing
watched movies and shows as a `watched_trakt` signal, with the same per-source
toggle on `/account`, and those titles hidden from non-personalized rails.

This advances the existing `account-linking` and `taste-recommendations`
capabilities (linked accounts and configurable taste sources) with a new
`trakt-personalization` capability, parallel to `plex-personalization` and
`jellyfin-personalization`.

## What Changes

- **Configuration:** Trakt is available when the operator registers a Trakt API
  app and sets `TRAKT_CLIENT_ID` (plus `TASTERR_SECRET_KEY`);
  `TRAKT_CLIENT_SECRET` is optional, since newer Trakt apps may have none. Both
  stay server-side. OAuth calls use Trakt's `auth.trakt.tv` host and all other
  calls use `api.trakt.tv`, with Trakt's required headers including an
  identifying User-Agent.
- **Linking:** members link Trakt from `/account` with Trakt's device-code flow:
  Tasterr shows a short code and the `auth.trakt.tv/activate` link, polls through an
  opaque session-bound handle (as the Plex link PIN does), and stores the access
  and refresh tokens encrypted on the link.
- **Link-only provider:** Trakt is never a sign-in method, never grants admin,
  never supplies display identity, is not used for Seerr, and does not count as
  "another way to sign in" for unlinking. Unlinking Trakt is never refused by
  that rule. Its link is dormant while Trakt is unconfigured.
- **History import:** a background sync (new link, Home read; six-hour throttle;
  after the Seerr sync) pages `/sync/history/movies` and
  `/sync/history/episodes` newest-first, all time, until 500 unique movies and
  500 unique shows, the last page, or 10 pages per type. Episodes collapse to
  their show. Later syncs skip when `/sync/last_activities` shows no watch newer
  than the watermark overlap, and otherwise read only plays since then. Titles
  map directly from Trakt's TMDB ids.
- **Signal:** new server-recorded `watched_trakt` kind, weight +2.5, one row per
  title at its newest watch, with its own `trakt` taste-source toggle and "Clear
  imported history" action. It anchors "Because You Watched" rails, and
  `discovery-exclusions-everywhere` hides those titles from discovery with no
  further change.
- **One watch per title:** when building the profile, each title contributes
  only its newest watched signal across all watched kinds of switched-on
  sources. This removes double counting when Plex, Jellyfin, and Trakt report the
  same watch, and also fixes today's Plex + Jellyfin overlap.
- **Tokens:** expired access tokens are refreshed before a sync, saving the
  rotated pair atomically. A rejected refresh fails that sync generically and
  keeps the link. A refresh interrupted by reset, unlink, or the deadline still
  commits its rotated pair. Unlink and account deletion revoke the grant at Trakt
  on a best-effort basis that never blocks them.
- Migration `0010`: `watched_trakt` joins the signals partial unique index
  (`ux_signals_unique_per_title`).
- Docs: Trakt app registration (including the GitHub verification Trakt
  requires from 2027-01-01), variables, behavior, and limits in
  `docs/CONFIGURATION.md`; `README.md`; `.env.example`; `compose.example.yaml`;
  the outbound host in `docs/SECURITY.md`.

## Non-goals

- Trakt as a sign-in method.
- Trakt ratings, watchlist, collection, or playback progress (no Continue
  Watching contribution).
- Scrobbling, check-ins, or any write to Trakt other than token revocation.
- A "needs reconnect" link state; a revoked grant behaves like a revoked Plex
  token (relink to fix).
- Live Trakt contract tests (they need a real account and app); fixture-based
  client tests pin the shapes.
- Changing Plex or Jellyfin history windows (`watch-history-window`).

## Capabilities

### New Capabilities

- `trakt-personalization`: Trakt configuration, client boundary, device-code
  linking, token lifecycle, link-only rules, and bounded history sync.

### Modified Capabilities

- `account-linking`: Trakt as a link provider (summary, unlink, delete, account
  page), excluded from admin derivation and the unlink rule.
- `taste-signals`: `watched_trakt` is server-recorded and a unique latest-watch
  fact.
- `taste-recommendations`: `watched_trakt` weight, one watch per title in the
  profile, Because You Watched for every watched kind, the `trakt` source, and
  reset cancelling the Trakt sync.
- `app-database`: migration `0010`.
- `app-settings`: Trakt environment variables.
- `user-auth`: Trakt tokens join the at-rest protection rule.

## Impact

- Backend: new `clients/trakt.py`; `settings.py`; `db/models.py` and migration
  `0010`; `recommend/signals.py` (kind, weight, source, `WATCHED_KINDS`);
  `recommend/profile.py` (one watch per title); a Trakt history mapper in
  `recommend/`; `api/account.py` (device link, unlink and delete revoke); `api/taste.py`
  (trigger, import); `auth/pins.py` (device-code payload).
- Frontend: Trakt card and device-code dialog on `/account`, taste-source
  label, generated types.
- Tests: client, mapper, import, link flow, migration, profile dedupe, e2e
  journey with a fake Trakt.
- Docs as listed above. No new dependency.
- **Depends on and lands after**, in order: `discovery-exclusions-everywhere`,
  `watch-history-window`, `jellyfin-continue-watching`,
  `sign-in-method-allowlist`, `seerr-media-server-awareness`. Its MODIFIED blocks
  are written on top of those changes' text (notably `sign_in` and
  "configured" from the allowlist, and Continue Watching invalidation from
  `jellyfin-continue-watching`).
