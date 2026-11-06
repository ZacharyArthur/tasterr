# trakt-personalization Specification (delta)

## Purpose

Optional Trakt integration: configuration, the client boundary, link-only
device-code linking, token lifecycle, and bounded all-time watch-history
synchronization into taste signals.

## ADDED Requirements

### Requirement: Trakt is configured from the environment

Trakt features SHALL be available only when `TRAKT_CLIENT_ID` and
`TASTERR_SECRET_KEY` are set. `TRAKT_CLIENT_SECRET` SHALL be optional: newer
Trakt apps may have none, and when it is set it is used only as defined in
"Trakt calls stay behind the client boundary". No Trakt value SHALL appear in
`PublicConfig`, `/auth/methods`, logs, or any response. Trakt SHALL NOT be a
sign-in method.

#### Scenario: Missing client id leaves Trakt off

- **WHEN** only `TRAKT_CLIENT_SECRET` is set
- **THEN** Trakt linking and sync are unavailable and boot succeeds

#### Scenario: App without a client secret works

- **WHEN** `TRAKT_CLIENT_ID` and `TASTERR_SECRET_KEY` are set and
  `TRAKT_CLIENT_SECRET` is not
- **THEN** Trakt linking and sync are available and no OAuth body carries a
  client secret

#### Scenario: Trakt secrets stay server-side

- **WHEN** `PublicConfig` and `/auth/methods` are serialized with Trakt fully
  configured
- **THEN** neither contains a Trakt value and `/auth/methods` has no Trakt entry

### Requirement: Trakt calls stay behind the client boundary

All Trakt calls SHALL live in `clients/trakt.py` and use only two fixed hosts with
TLS verification: `https://auth.trakt.tv` for every OAuth endpoint (`/oauth/*`)
and `https://api.trakt.tv` for every other call. They SHALL carry explicit
timeouts, never follow redirects, cap response size, parse responses into typed
models (unknown fields dropped), and never forward browser headers upstream or
upstream headers/bodies downstream. Every call SHALL send `trakt-api-version: 2`,
`trakt-api-key: <client id>`, `Content-Type: application/json`, and
`User-Agent: Tasterr/<version>`. The client id SHALL be sent in the
`trakt-api-key` header and, where Trakt's OAuth endpoints require it, in OAuth
request bodies. The token-refresh body SHALL carry `refresh_token`,
`client_id`, `grant_type=refresh_token`, and `redirect_uri` set to
`http://localhost` (the value the operator registers for the app), as
Trakt's contract requires. The client secret, when configured, SHALL be sent only in the
bodies of the token-refresh and revoke requests. The device code and refresh
token SHALL be sent only in OAuth request bodies. The access token SHALL be sent
only in the `Authorization` header, except in the body of the revoke request. No
client value or token SHALL ever appear in a URL. Trakt calls SHALL be limited to
the device-code, device-token, token-refresh, and revoke OAuth endpoints, the
member's own settings, last activities, and movie and episode watch history; no
other write SHALL be made.

#### Scenario: Unexpected Trakt payload

- **WHEN** Trakt returns an unexpected shape or an oversized body
- **THEN** the client raises a typed error and callers degrade generically

#### Scenario: Secrets never appear in URLs

- **WHEN** any Trakt call succeeds or fails
- **THEN** the client secret and member tokens are absent from URLs, logs,
  errors, and responses

#### Scenario: OAuth goes to the auth host

- **WHEN** Tasterr requests a device code, polls for a token, refreshes a token,
  or revokes one
- **THEN** the request goes to `https://auth.trakt.tv`, and every other Trakt
  call goes to `https://api.trakt.tv`

#### Scenario: Every call identifies the app

- **WHEN** any Trakt call is made
- **THEN** it carries the `User-Agent`, `Content-Type`, `trakt-api-version`, and
  `trakt-api-key` headers

#### Scenario: OAuth bodies carry only what Trakt requires

- **WHEN** Tasterr refreshes a member's token with a client secret configured
- **THEN** the request body carries the refresh token, client id,
  `grant_type=refresh_token`, `redirect_uri=http://localhost`, and the
  client secret, and no token or secret is in the URL or any other header

### Requirement: Members link Trakt with the device-code flow

`POST /api/v1/account/links/trakt/device` SHALL require a session, the
same-origin check, the authenticated mutation bucket, and the login bucket; it
SHALL return 503 and store nothing when Trakt is not configured. It SHALL request
a device code from Trakt, keep the device code and polling interval server-side
under an opaque, single-use handle bound to the creating session and to linking,
expiring at Trakt's expiry or 600 seconds, whichever is sooner, and return only
the handle, the user code, the interval, and the expiry. The SPA SHALL show the
user code and a fixed link to `https://auth.trakt.tv/activate`; Trakt's returned
verification URL SHALL NOT be forwarded.

`POST /api/v1/account/links/trakt/device/poll` SHALL require a session and the
same-origin check, SHALL be gated by its handle and exempt from the login bucket,
and SHALL treat a handle from another session, a sign-in handle, a Plex link
handle, or an expired handle as unknown; likewise, the Plex link poll SHALL treat
a Trakt handle as unknown. A poll sooner than the stored interval since the previous
Trakt poll SHALL return `pending` without calling Trakt. Trakt "pending" and
"slow down" SHALL map to `pending`; on "slow down" the stored interval SHALL grow
by five seconds before the next Trakt poll; invalid, already-used, and expired codes to
`expired`; a denial and Trakt's account-limit status (420) to `denied`, and the
dialog's denied message SHALL say that a member at Trakt's community-app limit
must disconnect an app on Trakt first. A transport failure, timeout, or 5xx from the
device-token request SHALL return the generic upstream error and keep the handle,
so the SPA keeps polling until expiry. On authorization, the server SHALL read the
member's Trakt settings, link the account by its stable Trakt user uuid (never
the slug) with the Trakt username as display name and no avatar, store the
token set encrypted, consume the handle, and return the account summary. Once
Trakt has issued tokens, the handle SHALL be consumed whatever happens next: an
account conflict SHALL return the generic 409 below and store nothing, and any
other failure SHALL store nothing and return the generic upstream error; in both
cases the SPA SHALL offer to start again. The
existing link rules apply: one Trakt link per user, one user per Trakt account
(409 without naming the other user), and relinking the same account refreshes
its tokens and name. Before storing a token set, the poll SHALL cancel and await
the user's in-flight Trakt sync under the per-user scheduling guard, so a refresh
cannot overwrite the newly issued tokens. No device code, token, or client value
SHALL appear in any response.

#### Scenario: Member links Trakt

- **WHEN** a member starts the Trakt link, enters the code at the activation page,
  and the SPA polls
- **THEN** the Trakt account is linked, its tokens are stored encrypted, and a
  history sync becomes eligible

#### Scenario: Early poll makes no Trakt call

- **WHEN** the SPA polls before the stored interval has elapsed
- **THEN** the response is `pending` and Trakt is not called

#### Scenario: Denied authorization stores nothing

- **WHEN** the member denies the app on Trakt
- **THEN** the poll returns `denied` and no link or token is stored

#### Scenario: Trakt outage during polling keeps the handle

- **WHEN** the device-token request fails with a 5xx or times out
- **THEN** the poll returns the generic upstream error, the handle stays valid,
  and a later poll can still complete the link

#### Scenario: Failure after token exchange starts over

- **WHEN** Trakt issues tokens but reading the member's settings fails
- **THEN** the handle is consumed, no link or token is stored, and the dialog
  offers to start again

#### Scenario: Handle is bound to its session

- **WHEN** another session polls with the handle
- **THEN** it fails as an unknown handle and the original session can still
  complete the flow

#### Scenario: Link flows do not share handles

- **WHEN** a session polls the Trakt link endpoint with its own Plex link handle,
  or the Plex link endpoint with its own Trakt handle
- **THEN** each fails as an unknown handle

#### Scenario: Trakt account belongs to another member

- **WHEN** the authorized Trakt account is already linked to another Tasterr user
- **THEN** the poll fails with the generic 409 conflict, the handle is consumed,
  and nothing is stored

#### Scenario: Slow down lengthens the interval

- **WHEN** Trakt answers a device-token poll with "slow down"
- **THEN** the poll returns `pending` and the next Trakt poll waits at least five
  seconds longer than before

### Requirement: Trakt links are link-only

A Trakt link SHALL NOT authenticate anyone into Tasterr, SHALL NOT take part in
admin derivation, SHALL NOT supply display identity, and SHALL NOT be used for
Seerr linking or silent Seerr re-authentication. It SHALL NOT count as another
way to sign in for the unlink rule, and unlinking a Trakt link SHALL NOT be
refused by that rule, so the account summary SHALL report it as unlinkable. It SHALL be ignored by the admin `sign_in_link_counts`
grouping, and `trakt` SHALL NOT be a valid sign-in method name in the sign-in
allowlist or `TASTERR_SIGN_IN_METHODS`. The account summary SHALL report Trakt with `sign_in`
false. A Trakt link SHALL be dormant while Trakt is not configured.

#### Scenario: Trakt does not keep a member signed in

- **WHEN** a member with Plex and Trakt links unlinks Plex while Plex is their
  only available sign-in method
- **THEN** the response is 409 and the Plex link is unchanged

#### Scenario: Trakt is not counted as a sign-in link

- **WHEN** an admin reads settings and a member has Plex and Trakt links
- **THEN** that member is counted under the `{plex}` set in `sign_in_link_counts`

#### Scenario: Trakt is not a sign-in method name

- **WHEN** `TASTERR_SIGN_IN_METHODS` is `["trakt"]`
- **THEN** startup validation fails

#### Scenario: Trakt can always be unlinked

- **WHEN** a member with no available sign-in method has a Trakt link
- **THEN** the account summary reports Trakt as unlinkable, and unlinking it
  removes the link

#### Scenario: Dormant Trakt link does nothing

- **WHEN** Trakt is no longer configured and a member with a Trakt link loads
  Home
- **THEN** no Trakt call is made and the link keeps its stored tokens

### Requirement: Trakt tokens are refreshed and revoked safely

A Trakt sync SHALL refresh the access token when it expires within five minutes,
using the stored refresh token, and SHALL commit the rotated token set before any
history read. The refresh call and that commit SHALL run as a separate task with
its own database session. The sync SHALL wait on that task only in a way that
never propagates its own cancellation into it (a shielded wait, repeated until the
task is done); when the sync task is cancelled (reset, source switch-off,
unlink, account deletion, application shutdown, or the sync deadline) while that
task runs, the sync SHALL keep waiting, again if cancelled again, and only then
re-raise the cancellation. Application shutdown SHALL cancel and await in-flight
Trakt syncs the same way it does Plex and Jellyfin syncs. A token set Trakt has issued is therefore never
lost, and callers that await the sync's cancellation see the rotated set already
committed. A refused refresh (Trakt answers 400 `invalid_grant`) or a failed
refresh SHALL fail that sync generically, SHALL keep the link and its sync
watermark, and SHALL NOT log any token. Unlinking Trakt and deleting the account
SHALL commit the local deletion first and then revoke the stored access token at
Trakt on a best-effort basis bounded to five seconds; a revocation failure SHALL
NOT change the local result or the response. Revocation of an access token that
has already expired (past its stored expiry) may have no effect at Trakt; it SHALL NOT be retried or
preceded by a refresh, and the documentation SHALL tell members they can remove
the app on Trakt. A stored token that cannot be decrypted or parsed SHALL skip
revocation without failing the unlink or deletion. While Trakt is not configured, revocation SHALL be skipped and
the local deletion SHALL proceed as usual.

#### Scenario: Expired token is refreshed before reading

- **WHEN** a Trakt sync starts with an access token that has expired
- **THEN** the token is refreshed, the new pair is stored, and history is read
  with the new access token

#### Scenario: Revoked grant fails quietly

- **WHEN** the member revoked Tasterr on Trakt and a sync runs
- **THEN** the refresh is refused with 400 `invalid_grant` or the read is refused,
  the sync fails generically, the link remains, and Home is unaffected

#### Scenario: Cancellation during refresh keeps the rotated tokens

- **WHEN** a member resets their taste profile while a Trakt sync is refreshing
  the token
- **THEN** by the time reset returns, the rotated token set is stored, and the
  next sync uses it

#### Scenario: Repeated cancellation and shutdown keep the rotated tokens

- **WHEN** a sync is cancelled several times, or the application shuts down,
  while its token refresh is in flight
- **THEN** the refresh task is never cancelled, its rotated token set is
  committed, and only then does the sync stop

#### Scenario: Unlink or deletion during refresh revokes the fresh token

- **WHEN** a member unlinks Trakt or deletes their account while a sync is
  refreshing the token
- **THEN** the unlink or deletion waits for the refresh to commit, reads the
  stored token only after that, deletes the link, and revokes the new access
  token best-effort

#### Scenario: Dormant Trakt link unlinks without revocation

- **WHEN** Trakt is no longer configured and a member unlinks their Trakt link
- **THEN** the link and tokens are deleted locally and no Trakt call is made

#### Scenario: Revocation failure does not block unlink

- **WHEN** a member unlinks Trakt while Trakt is unreachable
- **THEN** the link and tokens are deleted locally and the response succeeds

### Requirement: Trakt watch history synchronizes in bounded background work

A new Trakt link, a sign-in, and a Home read by any user with a usable Trakt link SHALL
evaluate one per-user single-flight trigger that schedules a background sync only
when the `trakt` taste source is on and the link's `sync_attempted_at` is absent
or older than six hours, waiting for that user's Seerr sync to settle. The task
SHALL commit the attempt timestamp before network work, SHALL NOT delay or fail
Home or linking, and SHALL complete token refresh and all reads under a
30-second deadline.

A sync SHALL read the member's movie watch history and episode watch history,
newest play first, requesting pages of 250, with the movie and episode reads
running concurrently; if one type's read fails, the other SHALL be cancelled and
awaited before any write. For each type it SHALL stop at whichever comes first: 500
unique titles, the last page, or 10 pages. When Trakt sends the page-count header,
it alone SHALL decide the last page. Otherwise the last page is an empty page or
one with fewer plays than the effective page size, which is the page-limit header
when sent and the requested 250 otherwise. A missing pagination header SHALL NOT
fail the read. A first sync SHALL
have no lower time bound on the plays it reads. A later sync SHALL first read the member's last activities;
when neither the movie nor the episode watched time is at or after 24 hours
before `sync_synced_at`, it SHALL complete without reading history; otherwise it
SHALL request history starting from that bound's date and keep only plays at or
after the bound. A missing activity field SHALL cause history to be read. Movie
plays SHALL map from the movie's valid positive TMDB id; episode plays SHALL
collapse to their show and map from the show's valid positive TMDB id as `tv`
(an episode's own TMDB id SHALL NOT be used). Plays without a usable TMDB id or a
watched time SHALL be skipped. Each title SHALL upsert one `watched_trakt` signal
at its newest play time in the read. `sync_synced_at` SHALL advance to the
captured cutoff only after every read completes within bounds (reaching a title
or page cap counts as complete; a failed page or deadline expiry does not).
Network and mapping work SHALL finish before writes, with at most 100 facts per
write transaction. No raw Trakt entry, slug, or Trakt id other than the link's
account uuid SHALL be retained.

#### Scenario: First sync imports older history

- **WHEN** a member links Trakt with watches from three years ago
- **THEN** the first sync imports them as `watched_trakt` signals at their newest
  play times, within the per-type caps

#### Scenario: Heavy history is capped per type

- **WHEN** a member has 2,000 watched movies on Trakt
- **THEN** only the 500 most recently played movies are imported, and paging
  stops once they are found

#### Scenario: Smaller applied page size keeps paging

- **WHEN** Trakt applies a page size of 100, says so in the page-limit header,
  and returns full 100-play pages
- **THEN** each full page is not treated as the last page and paging continues
  to the caps

#### Scenario: Page cap bounds heavy episode history

- **WHEN** a member's newest 2,500 episode plays cover fewer than 500 shows
- **THEN** reading stops after 10 pages, the shows found are imported, and the
  sync counts as complete

#### Scenario: Short page ends paging without a page-count header

- **WHEN** Trakt omits the page-count header and returns a page with fewer plays
  than the effective page size
- **THEN** paging stops, the read counts as complete, and the watermark may
  advance

#### Scenario: Episodes count toward their show

- **WHEN** a member has played several episodes of one show
- **THEN** one `watched_trakt` signal for the show is stored at the newest
  episode play time, from the show's TMDB id

#### Scenario: Failed page keeps the watermark

- **WHEN** a later history page fails after earlier pages succeeded
- **THEN** already mapped facts may be written, `sync_synced_at` does not
  advance, and the sync retries after the six-hour throttle

#### Scenario: No new activity skips history

- **WHEN** a later sync finds no watch since 24 hours before the watermark
- **THEN** no history page is read and the watermark advances

#### Scenario: Cleared history stays cleared

- **WHEN** a member clears Trakt history after a completed sync and later watches
  one new title
- **THEN** the next sync imports only titles played from 24 hours before the
  watermark onward

#### Scenario: Backdated additions after linking are not imported

- **WHEN** after a completed sync a member adds watches to Trakt dated before 24
  hours before the watermark (for example, an import from another service)
- **THEN** later syncs do not import them; a taste reset or switching Trakt
  history off and on re-imports the full bounded history

#### Scenario: Trakt outage does not affect Home

- **WHEN** Trakt is unreachable during a sync
- **THEN** Home returns normally, the watermark is unchanged, and the sync retries
  after the six-hour throttle

#### Scenario: Switched-off source does not sync

- **WHEN** the member's `trakt` taste source is off and they load Home
- **THEN** no Trakt sync is scheduled
