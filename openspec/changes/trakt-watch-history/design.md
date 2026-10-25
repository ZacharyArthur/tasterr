## Context

See proposal.md for motivation. Current state (after the changes this one lands
behind):

- Links live in `linked_accounts` (`provider` is `plex|jellyfin|seerr`, one
  `credential_enc` Fernet column, sync attempt/success timestamps). The account
  summary distinguishes **configured** from **available for sign-in**
  (`sign-in-method-allowlist`).
- Plex linking uses `auth/pins.py:PinStore`: opaque handles bound to the
  creating session and to linking, 600-second TTL, single use; the payload is
  the Plex PIN id (`int`).
- History imports live in `api/taste.py` (`import_plex_history`,
  `import_jellyfin_history`): commit the attempt, read under a 30-second
  deadline, map, write ≤100 facts per transaction, advance `sync_synced_at` only
  on complete reads, six-hour throttle, wait for Seerr. On cancellation they
  roll back and re-raise. Pure mapping sits in `recommend/`
  (`jellyfin_history.py`). Unlink and switch-off cancel syncs through
  `cancel_source_history`'s per-source map; account deletion cancels each sync
  with its own call (`api/account.py`). The per-source task dicts live on
  `app.state`; `main.py`'s lifespan cancels and gathers the seed, Plex, and
  Jellyfin dicts by name at shutdown, and `api/onboarding.py` reports `pending`
  while the caller has a seed, Plex, or Jellyfin sync in flight.
- `recommend/signals.py` owns kinds, weights, sources (`SOURCE_KINDS`), and
  `WATCHED_KINDS` (added by `discovery-exclusions-everywhere`, which also hides
  every watched kind from discovery and builds `UNIQUE_PER_TITLE_KINDS` and
  `STRONG_POSITIVE_KINDS` from it).
- `recommend/profile.py` sums `weight × decay × vector` over every eligible
  signal; a title watched on Plex and Jellyfin counts twice.
- Trakt API facts used (developer.trakt.tv and Trakt's API announcements,
  checked 2026-10):
  - OAuth endpoints live on `https://auth.trakt.tv` (enforced from 2027-02-01):
    `POST /oauth/device/code`, `POST /oauth/device/token` (400 pending, 404
    invalid, 409 used, 410 expired, 418 denied, 429 slow down), `POST
    /oauth/token` (refresh; the contract requires `refresh_token`, `client_id`,
    `grant_type`, and `redirect_uri`; a refused refresh is 400
    `invalid_grant`), `POST /oauth/revoke` (`token`, `client_id`). The hosted activation page is
    `https://auth.trakt.tv/activate`.
  - Everything else is on `https://api.trakt.tv`: `GET /users/settings`
    (`user.ids.uuid` is globally unique), `GET /sync/last_activities`
    (`movies.watched_at`, `episodes.watched_at`), `GET /sync/history/movies` and
    `GET /sync/history/episodes` (newest first, paginated up to 250 per page,
    `start_at` filter; episode plays carry their show's ids).
  - `/sync/watched/*` is now paginated (100 by default, 250 max) with no
    documented order, and `extended=noseasons` is a no-op, so it can't deliver
    "newest N".
  - Required headers on every call: `trakt-api-version: 2`, `trakt-api-key`,
    `Content-Type: application/json`, and an app `User-Agent`; requests without a
    proper User-Agent may be blocked.
  - Refresh tokens are single-use; access tokens last 7 days. The client secret
    is optional on refresh and revoke ("server only") and some new apps have
    none; the device-token request needs only `code` and `client_id`.
  - Creating a Trakt app already needs a verified GitHub account, and from
    2027-01-01 every existing app needs one too, or its users are logged out.
  - Free Trakt accounts can connect only a small number of community apps, and
    Trakt has changed the number during 2026 (one from July, two from
    2026-09-18 per discussion #943), so the docs don't state a number. Official
    Trakt apps don't count. A member at the limit must disconnect an app before
    authorizing another. Trakt's account-limit status is 420, possibly with an
    empty body.
  - Pagination: Trakt clamps a requested `limit` to an endpoint maximum ("often
    250", not guaranteed) and tells clients to read the applied size from
    `X-Pagination-Limit` and the total from `X-Pagination-Page-Count` rather than
    assume the requested value.
  - The same type-filtered history is also documented as
    `GET /users/{id}/history/{movies|episodes}`, where `{id}` is a slug or `me`
    (the uuid can't be used to read data); Tasterr uses the `/sync/history` route
    and can switch to `/users/me/history/{type}` if the former is retired (same
    response shape). The published OpenAPI describes that route's `start_at` as
    `YYYY-MM-DD` too, but its contract source validates it with
    `z.string().datetime()`, so a switch should confirm the accepted `start_at`
    format first.

## Goals / Non-Goals

**Goals:**
- Trakt joins as a link-only taste source, reusing the link, PIN, sync, and
  taste-source machinery with no new mechanism.
- Older history counts without unbounded TMDB feature work.

**Non-Goals:**
- A provider abstraction over Plex/Jellyfin/Trakt imports. Two concrete import
  functions already exist; Trakt is a third, sharing only the write loop if the
  rule of three is met cleanly.

## Decisions

1. **Two fixed hosts, admin-registered app.** `clients/trakt.py` uses constant
   hosts, `https://auth.trakt.tv` for `/oauth/*` and `https://api.trakt.tv` for
   everything else (neither configurable, so no SSRF surface), a 10-second
   timeout per call, no redirects, strict Pydantic models with unknown fields
   dropped, a response-size cap (8 MiB, enforced while streaming), and typed
   errors (`UpstreamUnavailable` for transport, 429, and 5xx; a typed refusal for
   401/403 and for 400 `invalid_grant` on refresh). Every call sends
   `trakt-api-version: 2`, `trakt-api-key`, `Content-Type: application/json`, and
   `User-Agent: Tasterr/<version>` (the package version). The client id goes in
   `trakt-api-key` and, where Trakt's OAuth endpoints require it, in OAuth bodies;
   the refresh body is `refresh_token`, `client_id`, `grant_type=refresh_token`,
   and `redirect_uri=urn:ietf:wg:oauth:2.0:oob` (the registered value; a module
   constant, since the device flow never redirects);
   the client secret, when configured, only in the refresh and revoke bodies; the
   device code and refresh token only in OAuth bodies; the access token in
   `Authorization`, except in the revoke body. Nothing secret goes in a URL.
   Configuration is `TRAKT_CLIENT_ID` + `TASTERR_SECRET_KEY`, with
   `TRAKT_CLIENT_SECRET` optional. Alternative: a project-owned app, rejected
   because the household should own its app, its GitHub verification, and its
   rate limits.

2. **Device flow through `PinStore`.** `PinStore` becomes generic over its
   payload and gains a per-entry TTL (defaulting to today's 600 s, so Plex is
   unchanged). Trakt gets its **own** `PinStore` instance on `app.state`, so a
   Plex link handle and a Trakt handle are never interchangeable; its payload is
   a small mutable record `(device_code, interval, last_poll)` whose `last_poll`
   the poll endpoint updates in place.
   `POST /account/links/trakt/device` calls Trakt, stores the device code
   server-side under a session-bound handle with TTL `min(expires_in, 600)`, and
   returns only `{handle, user_code, interval, expires_in}`. The SPA renders the
   fixed `https://auth.trakt.tv/activate` link; Trakt's `verification_url` is not
   forwarded. `POST /account/links/trakt/device/poll` returns `pending` without
   calling Trakt when polled sooner than the interval; maps 400/429 to
   `pending`, adding five seconds to the stored interval on 429 (RFC 8628's
   slow-down rule), 410/404/409 to `expired`, 418 and 420 (account limit) to
   `denied`, whose message names the community-app limit; maps a transport error,
   timeout, or 5xx to the generic upstream error **keeping** the handle (the
   device code is still good, so the SPA keeps polling); and on 200 reads
   `/users/settings`, links by `user.ids.uuid` (never the mutable slug), names the
   link from the Trakt username, and stores the token set. Once Trakt has issued
   tokens the device code is spent, so the handle is consumed whatever follows:
   an account conflict returns the usual generic 409; any other failure (settings
   read, the commit) stores nothing and returns the generic upstream error; the
   SPA offers to start again either way.
   Alternative: browser polls Trakt directly, rejected because it would expose the
   device code and client id flow to the browser.

3. **One encrypted token blob, refresh in its own task.** `credential_enc`
   holds Fernet-encrypted JSON `{access_token, refresh_token, expires_at}`, so no
   schema change to links. Refresh happens at sync start when `expires_at` is
   within five minutes; the rotated pair is committed **before** any history
   read, because Trakt invalidates the old refresh token (and reusing it can
   invalidate the new one too). The refresh call and its commit run as a
   separate `asyncio` task with its **own** DB session. The sync never awaits
   that task directly, because cancelling a coroutine that is awaiting a task
   cancels the task too. It waits with `await asyncio.shield(refresh)` inside a
   loop: on `CancelledError` it remembers the cancel and shields again until
   `refresh.done()`, then re-raises. One shield alone is not enough either: it
   re-raises at once while the work continues detached, so
   `_cancel_history_task` would return, and unlink or delete would proceed, before
   the commit, and the sync's `rollback` on cancel could close the session the
   commit is using. With the separate task and the loop, anyone who awaits the
   sync's cancellation (reset, switch-off, unlink, delete, shutdown) sees the
   rotated pair already committed; unlink and delete then delete it and revoke the
   fresh access token. A same-account relink is the one other writer of
   `credential_enc`: the device poll, once Trakt has issued tokens, cancels the
   user's Trakt sync under `history_guard` (as unlink does) before saving, so an
   in-flight refresh can't commit an older token family over the new one. A new `trakt_history_tasks` dict on `app.state` joins the
   lifespan's shutdown cancel-and-gather (so `asyncio.run`'s teardown never
   cancels a refresh task directly) and the onboarding `pending` check. The wait is bounded by the
   10-second call timeout plus one commit. A refusal (400 `invalid_grant`) raises
   a typed error: the sync logs a generic line, leaves the watermark, and keeps
   the link (same as a revoked Plex token). Single-flight per user already
   prevents concurrent refreshes.

4. **Best-effort revoke after the local commit.** Unlink and account deletion
   cancel the Trakt sync first, then read and decrypt the access token (so a
   refresh that just committed is seen; an undecryptable or malformed blob
   just skips revocation), commit the local deletion, then
   call `/oauth/revoke` with a five-second bound, ignoring every failure. The
   local result never depends on Trakt. It is skipped while Trakt is unconfigured
   (no client id to send; a dormant link is just deleted). A stored access token
   past its stored expiry is likely a no-op to revoke at Trakt;
   Tasterr doesn't refresh just to revoke (extra round trip and a refresh-token
   rotation inside an unlink). The docs tell members they can remove the app on
   Trakt. This amends "nothing is deleted in any upstream service" to name the
   one grant revocation.

5. **Link-only rules in one place.** Trakt is excluded from sign-in
   (`/auth/methods`, sign-in dependencies), admin derivation, display identity,
   Seerr linking/re-auth, the unlink rule's count, and `sign_in_link_counts`.
   `trakt` joins the link `Provider` literal (`db/models.py`), and a new
   `SignInMethod = Literal["plex", "jellyfin", "seerr"]` takes over every place
   that means "a way to sign in": the allowlist's `disabled_sign_in_methods` and
   `TASTERR_SIGN_IN_METHODS`, `/auth/methods`, and `sign_in_offered`.
   `provider_configured` covers all four providers (it backs the account summary,
   `can_unlink`, and dormancy, which iterate every link and would otherwise hit a
   missing key for `trakt`). `sign_in_offered` takes a `SignInMethod`, so callers
   that hold a `Provider` (`can_unlink`, the unlink rule, the account summary)
   narrow first and treat `trakt` as not offered; pyright strict enforces the
   narrowing. Unlinking Trakt is never refused by the unlink rule, even for a
   member with no available sign-in method.

6. **Import: history, newest first, bounded per type.** The sync pages
   `GET /sync/history/movies` and `GET /sync/history/episodes` (requesting limit
   250), newest play first, the two types read concurrently so a heavy first sync
   (up to 10 pages each) fits the deadline in about half the sequential time. `recommend/trakt_history.py` (pure, unit-tested) folds each
   page into `{TitleKey: newest watched_at}`: movies by their valid positive TMDB
   id within `MAX_TMDB_ID`; episodes collapsed to their show's TMDB id as `tv`
   (never the episode's own id); plays without an id or a watched time skipped.
   Per type, paging stops at 500 unique titles, the last page, or 10 pages,
   whichever comes first. When `X-Pagination-Page-Count` is sent, it alone names
   the last page. Otherwise the last page is empty or holds fewer plays than the
   effective page size: `X-Pagination-Limit` when sent, else the requested 250.
   So a clamped page size (say 100) never makes full pages look short, which
   would end the first sync early and advance the watermark past history it never
   read. A missing header is "unknown", not a parse error. Reaching a
   cap counts as complete. A failed page or the deadline does not, so the
   watermark stays. The 10-page cap bounds a heavy episode watcher: 2,500 plays
   may collapse to fewer than 500 shows. Those are still the most recent shows,
   which is the accepted trade-off.
   First sync: no lower bound. Later sync: if `/sync/last_activities` shows
   neither `movies.watched_at` nor `episodes.watched_at` at or after
   `sync_synced_at − 24h`, the sync completes with no history read; otherwise it
   passes `start_at` as that bound's date (the `/sync/history` contract,
   `progressParamsSchema`, documents `YYYY-MM-DD`; the datetime schema belongs
   to the `/users/{id}/history` route) and drops plays
   before the exact bound client-side. This keeps "Clear imported history" honest
   (older history stays cleared) and matches the other sources' overlap rule. The
   accepted cost: watches a member adds to Trakt later with old dates (an import
   from another service) arrive only after a reset or a Trakt off/on toggle;
   documented. Writes reuse the ≤100-facts batching. The 30-second deadline
   covers refresh and reads. Alternative: page `/sync/watched/*` in full and sort
   locally, rejected because its order is undocumented (a page cap would cut
   arbitrarily) and later syncs would re-page everything.

7. **One watch per title in the profile.** `profile.py` collapses eligible
   signals of `WATCHED_KINDS` to the newest one per title before summing
   (`SignalInput` gains its kind so the collapse can see it); rows
   remain stored per source, so toggles, clearing, and unlink history deletion
   still act per source. Pure function, unit-tested. Migration `0010` deletes every
   materialized profile on upgrade so the new rule applies at once; profiles
   are fully rebuildable from signals, and otherwise would refresh within their
   existing 24-hour maximum age.

8. **Migration `0010`.** Mirrors `0008`: rebuild the partial unique index
   `ux_signals_unique_per_title` with `watched_trakt` in its predicate (and
   update `SIGNAL_UNIQUE_INDEX_WHERE`, which the upsert's `index_where` must
   match), and delete materialized profiles (decision 7). There is no signal
   kind CHECK constraint to extend; kinds are validated in the application.
   Downgrade deletes `watched_trakt`
   signals and Trakt links, removes `trakt` from every
   `users.taste_excluded_sources`, invalidates affected profiles, and restores
   the prior index. No user can be orphaned: a Trakt link never
   is a member's only link because it can only be created from a session.

## Risks / Trade-offs

- [Trakt changes token lifetimes or API shape] → strict parsing turns drift into
  a failed sync, never bad data; refresh is driven by the stored `expires_at`,
  not an assumed lifetime. Trakt's announced 2027 changes (auth host, GitHub
  verification) are already reflected.
- [Heavy Trakt users have thousands of titles] → newest 500 per type within 10
  pages, then normal decay; documented.
- [All-time history shifts profiles toward old taste] → 90-day half-life decay
  already discounts old watches; one-watch-per-title prevents echo inflation.
- [`last_activities` granularity] → it only lets a sync skip work; when unsure
  (missing field) the sync reads history.
- [Revocation fails or is a no-op for an expired token] → documented; members
  can remove the app from Trakt's connected apps page.
- [Operator's app is unverified after 2027-01-01] → docs tell operators to link
  GitHub under Trakt's My Apps; an unverified app's grants stop working, and
  syncs fail generically until fixed.
- [Refresh requires the app's registered redirect URI] → docs require the app to
  be registered with exactly `urn:ietf:wg:oauth:2.0:oob`, the constant Tasterr
  sends; a mismatch makes refresh fail after the first token expires.
- [A member is at Trakt's community-app limit] → authorization fails on Trakt's
  side (420 maps to denied; if Trakt instead lets the code lapse, expired); the
  denied message and the docs tell members to disconnect an app first.
- [Concurrent type reads] → two requests in flight per sync instead of one;
  single-flight per user still bounds it, and one failed type fails the read
  after the other is cancelled and awaited, so no read outlives the sync.

## Migration Plan

Migration `0010` is additive. Rollback to an image without Trakt requires
downgrading `0010` first (deletes Trakt links and `watched_trakt` signals);
`docs/CONFIGURATION.md` lists this with the other destructive downgrade limits.

## Security considerations

- **Endpoints:** `POST /account/links/trakt/device` requires a session, the
  same-origin check, the authenticated mutation bucket, and the login bucket
  (it triggers an upstream call). `.../device/poll` requires a session and
  same-origin, is gated by its unguessable single-use session-bound handle, and
  is exempt from the login bucket like the Plex link poll; it never calls Trakt
  faster than the server-held interval. Responses carry only the user code,
  interval, expiry, a status, and the account summary. Unlink, clear, and
  taste-source endpoints are unchanged in protection. Failures are generic.
- **Auth & sessions:** Trakt never authenticates anyone into Tasterr and never
  grants admin. The device code, client secret, and tokens stay server-side; the
  browser sees only the short user code meant for the member.
- **Outbound HTTP:** only `clients/trakt.py`, two fixed hosts
  (`auth.trakt.tv`, `api.trakt.tv`), TLS verification, no redirects, 10-second
  timeouts, a 30-second sync deadline, 8 MiB response cap, strict parsing, an
  identifying User-Agent. Volume: one `last_activities` call per user per six
  hours, and at most 10 history pages per type only when there is new activity
  (far under Trakt's 500 authenticated GETs per 5 minutes per user, per its
  rate-limiting guide as of 2026-10).
- **Secrets / PublicConfig:** `TRAKT_CLIENT_ID` and the optional
  `TRAKT_CLIENT_SECRET` are environment-only and never in `PublicConfig`,
  `/auth/methods`, logs, or responses; the PublicConfig regression test covers
  them.
- **Database:** tokens are Fernet-encrypted on the link and deleted with it; only
  canonical `watched_trakt` facts and sync timestamps are stored; no raw Trakt
  history, slugs, or ids beyond the link's account uuid.
- **Frontend:** the code and fixed activation link render as text and a static
  URL; no upstream URL or text is rendered.
- **Dependencies:** none; httpx and cryptography are already used.
