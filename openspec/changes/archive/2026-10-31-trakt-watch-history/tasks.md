## 1. Configuration and client

- [x] 1.1 Add `TRAKT_CLIENT_ID` and optional `TRAKT_CLIENT_SECRET` to `Settings` with a `trakt_configured` property (client id plus `TASTERR_SECRET_KEY`). Verify with settings tests (no client id is unconfigured; a client id without `TASTERR_SECRET_KEY` is unconfigured; a client id without `TRAKT_CLIENT_SECRET` is configured; boot succeeds in each case) and extend the PublicConfig regression test so neither value can appear.
- [x] 1.2 Add `clients/trakt.py` with:
  - two fixed hosts: `https://auth.trakt.tv` for `/oauth/*`, `https://api.trakt.tv` otherwise;
  - required headers on every call: `trakt-api-version: 2`, `trakt-api-key`, `Content-Type: application/json`, `User-Agent: Tasterr/<version>`;
  - 10 s timeout, no redirects, 8 MiB streamed response cap, strict models, typed errors;
  - methods for device code, device token, refresh, revoke, user settings, last activities, and one page of movie or episode history (`limit`, `page`, optional `start_at`), returning items plus the page count from `X-Pagination-Page-Count` and the applied page size from `X-Pagination-Limit` when present (absent means unknown, not an error).

  Verify with client tests on a fake transport:
  - the host of every call;
  - all four headers on every call;
  - credential placement:
    - client id in `trakt-api-key` and in the OAuth bodies Trakt requires;
    - client secret only in refresh and revoke bodies, and only when configured;
    - device code and refresh token only in OAuth bodies;
    - the refresh body carries exactly `refresh_token`, `client_id`, `grant_type=refresh_token`, `redirect_uri=http://localhost`, and `client_secret` only when configured;
    - access token only in `Authorization`, except the revoke body;
    - nothing secret in any URL;
  - each device-token status mapping, including 420 (account limit, empty body), with 5xx and timeouts as unavailable;
  - 400 `invalid_grant` on refresh as a typed refusal;
  - pagination parameters sent, and page count and page limit parsed;
  - oversize and malformed bodies raising typed errors;
  - 429 and 5xx as unavailable;
  - a redirect response is refused (not followed), each request carries the 10 s timeout, and TLS certificate verification stays enabled;
  - typed errors and their log lines carry no token, device code, or client value;
  - the client exposes only the operations listed above, so no other Trakt write can be made;
  - a valid payload with unknown fields parses and drops them;
  - no inbound browser header reaches Trakt, and no Trakt header or body is passed into an API response.

## 2. Storage and signals

- [x] 2.1 Register the new provider, kind, and source everywhere they are enumerated:
  - `trakt` in the link `Provider` literal (`db/models.py`), reusing the existing `SignInMethod = Literal["plex", "jellyfin", "seerr"]` for the allowlist fields, `TASTERR_SIGN_IN_METHODS`, `/auth/methods`, and `sign_in_offered`.
  - `provider_configured` covering `trakt`.
  - `watched_trakt` (+2.5) in `SignalKind`, the weights, and `WATCHED_KINDS` (`recommend/signals.py`); confirm `UNIQUE_PER_TITLE_KINDS` and `STRONG_POSITIVE_KINDS` include it through `WATCHED_KINDS`, as `discovery-exclusions-everywhere` defines them; add it to the literal SQL predicate `SIGNAL_UNIQUE_INDEX_WHERE` (`db/models.py`).
  - `trakt` in the `TasteSource` literal and `SOURCE_KINDS`.
  - `watched_trakt` rejected from `POST /signals`.

  Verify with tests:
  - signal validation and the source toggle;
  - a `watched_trakt` title anchors a "Because You Watched" rail (extend the existing Plex/Jellyfin label test), is not a candidate while Trakt history is off, and stays out of Recommended for You with watched hiding off;
  - re-recording the same or an older `watched_trakt` watch is a no-op upsert, and a later watch updates only the row's time and invalidates the profile in the same transaction;
  - `TASTERR_SIGN_IN_METHODS=["trakt"]` fails boot, and an admin `PUT /settings` with `disabled_sign_in_methods: ["trakt"]` fails validation and stores nothing;
  - `/account` with a Trakt link raises no error and reports it;
  - with Trakt fully configured, the `/auth/methods` body has no Trakt entry;
  - recording `watched_plex` and `watched_trakt` for one title stores two rows, one per source.
- [x] 2.2 Add migration `0010` (rebuild `ux_signals_unique_per_title` with `watched_trakt` in its predicate, matching `SIGNAL_UNIQUE_INDEX_WHERE`; no CHECK constraint; materialized profiles deleted) with a downgrade that removes `watched_trakt` signals and Trakt links, strips `trakt` from `taste_excluded_sources`, invalidates profiles, and restores the prior index. Verify with migration tests: upgrade on a populated database leaves no materialized profile row, unique index on concurrent upserts, downgrade leaves no Trakt rows, no stored `taste_excluded_sources` list contains `trakt`, affected profiles are invalidated, the index predicate is restored to its `0009` form, every user still exists with their other links, and `PRAGMA foreign_key_check` is clean.
- [x] 2.3 Collapse eligible watched signals to the newest per title in `recommend/profile.py` (`SignalInput` gains its kind; update the existing three-argument constructions in `recommend/store.py` and `tests/test_recommend_profile.py`). Verify with profile unit tests: Plex + Trakt watches of one title contribute once at the newer time, and Plex + Jellyfin + Trakt watches of one title contribute once at the newest; switching Trakt off leaves the Plex contribution; non-watched kinds are unaffected.

## 3. Linking and token lifecycle

- [x] 3.1 Make `PinStore` generic over its payload with a per-entry TTL (default 600 s; Plex keeps `int`), and add a separate Trakt `PinStore` instance whose mutable payload holds the device code, interval, and last poll time. Verify the existing PIN tests pass unchanged and add tests for a shorter per-entry TTL and an in-place payload update.
- [x] 3.2 Add `POST /account/links/trakt/device` and `.../device/poll` in `api/account.py` per the spec (session-bound handle, interval enforcement, status mapping, link by `ids.uuid`, encrypted token blob, 409 for another user's Trakt account, relink refreshes). Verify with API tests: 503 when unconfigured, protections (same-origin, buckets), the handle expires at `min(expires_in, 600)` seconds, a user who already has a Trakt link is refused a different Trakt account, early poll makes no Trakt call, pending/expired/denied/linked outcomes (420 maps to denied), a 5xx or timeout on the device-token request returns the generic upstream error and keeps the handle (a later poll can still link), a settings-read failure or a database commit failure after token issue consumes the handle, stores nothing, and returns the generic upstream error, the device response has no `verification_url` field even when Trakt returns one, replaying a consumed handle is unknown and makes no Trakt call, a successful link schedules a Trakt sync, the Trakt poll treats a Plex sign-in handle from the same session as unknown, an account conflict after token issue returns 409 and consumes the handle, a "slow down" adds five seconds before the next Trakt poll, foreign-session handle rejected, each link poll (Plex, Trakt) rejects the other flow's handle from the same session, nothing stored on failure, response carries no device code or token, the stored credential is Fernet ciphertext with no plaintext token, the link key is `ids.uuid` (not the slug), the display name is the username with no avatar, and relinking the same account updates its tokens and name; a relink while a Trakt sync is refreshing waits for that refresh, then stores the new device-flow token set, which survives (the poll cancels the sync under `history_guard` before saving); no `sessions` row contains the access or refresh token; Trakt polls past the login bucket's limit are not rate-limited while `/device` is; a linked poll returns the account summary with Trakt linked and no token fields; after a foreign-session poll is rejected, the original session still completes the same handle.
- [x] 3.3 Add token refresh at sync start (within five minutes of expiry): the refresh call and its commit run as a separate task with its own DB session, and the sync waits on it only through `asyncio.shield` in a loop until it is done (never awaiting it directly), re-raising a remembered cancellation afterwards, so the rotated pair is committed before reads and before any canceller resumes. Add `trakt_history_tasks` to `app.state`, to `main.py`'s lifespan shutdown cancel-and-gather, and to the onboarding `pending` check in `api/onboarding.py`. Add best-effort revoke after the local commit on unlink and account deletion, skipped while Trakt is unconfigured; both read the Trakt token only after cancelling the Trakt sync (account deletion today deletes the user through the cascade without loading links, so it gains this read), and an unreadable stored token (`InvalidToken` or malformed JSON) skips revocation, as other decrypt sites catch `InvalidToken`. Verify with tests: an undecryptable Trakt blob, and a decryptable blob with malformed JSON, each still unlink and delete the account with no Trakt call; a token expiring in four minutes is refreshed and one expiring in six minutes is not; a sync starting with an already-expired token commits the rotated pair before the first history read, which uses the new access token; refresh rotates and persists; the sync deadline expiring mid-refresh still commits the rotated pair before the sync ends; a refused or failed refresh logs no token or secret value (`caplog`); unlink with `delete_history` false keeps the `watched_trakt` rows and still revokes; right after a reset that cancelled the task mid-refresh returns, the stored token set is already the new one; an unlink during a refresh returns only after the refresh committed, leaves no link row, and revokes the new access token; account deletion during a refresh revokes the new access token; cancelling the sync three times during a refresh never cancels the refresh task and still commits the rotated pair; lifespan shutdown during a refresh keeps the rotated pair; lifespan shutdown during a history read cancels it with no write afterwards; a hanging revoke still lets unlink and account deletion return within about five seconds; the fake revoke handler sees the link row already deleted, for both unlink and deletion; onboarding reports `pending` while a Trakt sync runs; a refused refresh (400 `invalid_grant` fixture) keeps the link and the watermark; revoke failure or timeout still unlinks/deletes; a dormant Trakt link unlinks with no Trakt call; unlinking with a stored `expires_at` in the past makes exactly one revoke call and no `/oauth/token` call; unlink with `delete_history` true deletes the caller's `watched_trakt` rows, invalidates their profile, and still revokes best-effort; unlink of Trakt is never refused by the unlink rule (including for a member with no available sign-in method).
- [x] 3.4 Exclude Trakt from sign-in, admin derivation, display identity, Seerr linking/re-auth, the unlink rule's count, and `sign_in_link_counts`; report it in the account summary with `sign_in: false`. Verify with tests for each exclusion (including a member with Plex + Trakt counted as `{plex}` in `sign_in_link_counts`), the summary shape, `available: true` for Trakt with a client id and no secret, and `can_unlink: true` for Trakt even when the member has no other available sign-in method; unlinking Plex while a Trakt link is present and Plex is the only available sign-in method returns 409; with Trakt unconfigured and unlinked but `watched_trakt` history retained, the summary still reports the Trakt source card and its controls, as for the other retained sources.

## 4. History import

- [x] 4.1 Add `recommend/trakt_history.py` folding history pages into `{TitleKey: newest watched_at}`:
  - movies by their valid TMDB id;
  - episodes collapsed to their show's TMDB id as `tv`, never the episode's own id;
  - a watched time required;
  - plays before an optional lower bound dropped;
  - a per-type unique-title cap of 500, reported as reached.

  Verify with unit tests for each inclusion/omission rule, the episode collapse at the newest play, the lower bound, and the unique-title cap.
- [x] 4.2 Add the Trakt trigger and `import_trakt_history` in `api/taste.py`:
  - triggered by a new link or a Home read, with a six-hour throttle, after Seerr;
  - skipped while the `trakt` source is off, Trakt is unconfigured, or the per-user scheduling guard is held (`plex_history_resets`, as the Plex and Jellyfin triggers check);
  - a `last_activities` skip;
  - movies and episodes read concurrently; per type, requesting pages of 250, newest first, stopping at 500 unique titles, the last page, or 10 pages, where the page-count header alone names the last page when sent and otherwise a page is last when empty or shorter than the effective page size (`X-Pagination-Limit` when sent, else 250);
  - later syncs pass `start_at` as the overlap bound's date and filter to the exact bound;
  - ≤100 facts per transaction, a 30 s deadline, and the watermark advanced only on complete reads.

  Add the Trakt branch to `schedule_history` (`api/taste.py`), the one trigger fan-out that Home, sign-in (`api/auth.py`), `_save_link`, reset, and source switch-on already call. Make reset, source switch-off, unlink, and account deletion cancel it like the other syncs; add `trakt` to `cancel_source_history` and a Trakt cancel call to account deletion.

  Verify with tests:
  - a repeated trigger while the user's Trakt task is pending schedules no second task (single-flight);
  - a 205-fact import writes in batches of 100, 100, and 5;
  - a first sync sends no `start_at`, and a later sync sends the overlap bound's date as `YYYY-MM-DD`;
  - Trakt unreachable during a sync: Home still returns normally, the watermark is unchanged, and the next sync waits for the throttle;
  - sign-in by a user with an eligible Trakt link schedules a Trakt sync;
  - a 401 on a history page fails the sync generically, keeps the link and the watermark, and Home is unaffected;
  - switching Trakt history off and clearing Trakt history each cancel an in-flight Trakt sync (extend the existing cancellation matrix);
  - after linking and a completed import the database holds only `watched_trakt` rows, the link's encrypted token blob, uuid, and sync timestamps: no raw entry, slug, episode id, device code, client id, or client secret;
  - a first-sync watch from three years ago is imported even with `TASTERR_WATCH_HISTORY_DAYS=1` (the window governs Plex and Jellyfin only);
  - with the `trakt` source off, nothing is scheduled;
  - with Trakt unconfigured, Home makes no Trakt call and the link keeps its stored tokens;
  - a `sync_attempted_at` under six hours old schedules nothing;
  - the sync starts only after the user's Seerr sync settles;
  - the attempt timestamp commits before the first Trakt call;
  - reset and switching Trakt history back on each schedule a fresh first sync;
  - the first sync pages until 500 unique titles per type;
  - the 10-page cap stops a heavy episode history and still counts as complete;
  - with no page-count header, an empty or short page ends paging and counts as complete;
  - a page-limit header of 100 with full 100-play pages keeps paging, and a page-count header wins over a short page;
  - a heavy-history fixture (10 pages per type, each call delayed) finishes inside the deadline because the two types are read concurrently; one type failing cancels and awaits the other before any write (the cancel-and-await idiom at `clients/plex.py:371-376`), keeps the watermark, and leaves no read in flight when the sync ends;
  - a failed later page keeps the watermark;
  - unchanged activities make no history read and advance the watermark;
  - a missing activity field causes history to be read;
  - a Trakt trigger while the scheduling guard is held (during reset or unlink) schedules nothing;
  - cleared history is not re-imported from before the overlap;
  - the deadline keeps the watermark;
  - reset cancels an in-flight Trakt sync;
  - account deletion cancels an in-flight Trakt sync before the delete commits.

## 5. Frontend

- [x] 5.1 Regenerate `api.gen.ts`; add a Trakt card to `/account` with a device-code dialog (large user code, fixed `https://auth.trakt.tv/activate` link opening in a new tab with `rel="noopener noreferrer"`, polling at the returned interval and continuing through a transient upstream error until expiry, expired/denied messages (denied names the community-app limit), a start-again offer when the handle is gone, cancel), the Trakt taste-source toggle and clear action, and "Trakt" in the delete-account wording. Verify with Vitest cases for each dialog state (including a transient error that keeps polling and a failed link that offers start again), that no upstream URL is rendered, that the Trakt card's Unlink stays enabled when every other link reports `sign_in: false`, that the delete-account text says a Trakt connection is revoked, and that an unconfigured, unlinked Trakt with retained history still shows its source toggle and clear action.
- [x] 5.2 Add fake Trakt endpoints to `scripts/e2e_server.py` (patch the two Trakt host constants the way it patches `tmdb.BASE`, and set `TRAKT_CLIENT_ID`) and a journey: link Trakt, see the card linked, and see an imported watched title absent from Trending. Verify with `just e2e`.

## 6. Documentation

- [x] 6.1 Document Trakt in `docs/CONFIGURATION.md`:
  - registering an app with its redirect URI set to exactly `http://localhost` (development apps allow only localhost redirects; token refresh sends that value; the device flow needs no callback listener), and a verified GitHub account linked under My Apps (Trakt requires it to create an app, and for every app from 2027-01-01);
  - development-app admission: the operator adds household members to the Trakt app before they authorize; developer app and member allowances come from the portal and are separate from connected-community-app limits; the operator currently reports five apps and 16 member seats, with the portal counting the owner toward seats; production registration currently requires contacting Trakt support;
  - Trakt limits how many community apps a free account can connect (no number stated, since Trakt changes it), so a member at the limit disconnects an app in Trakt's connected-apps settings before linking;
  - `TRAKT_CLIENT_ID` and the optional `TRAKT_CLIENT_SECRET`;
  - link-only behavior, updating the Account paragraph (around line 192) so "Unlink requires another usable sign-in method" excepts Trakt and "leaving upstream accounts alone" names the one Trakt grant revocation;
  - the all-time newest-500 import, up to 10 history pages per type;
  - backdated Trakt additions need a reset or an off/on toggle;
  - one watch per title;
  - revocation is best-effort and likely a no-op once the stored access token has expired, so members can remove the app on Trakt;
  - the destructive `0010` downgrade;
  - a Trakt row in the "Mixed setups" matrix;
  - "All four taste sources start on" (line ~197) updated to five, with Trakt.

  Also update `docs/releases/unreleased.md` (Trakt support and the destructive `0010` downgrade), `README.md`, `.env.example`, `compose.example.yaml`, and the outbound hosts (`auth.trakt.tv`, `api.trakt.tv`) in `docs/SECURITY.md`. Verify `test_docs.py` and `test_env_example.py` pass under `just check`.

## 7. Gate

- [x] 7.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate trakt-watch-history --strict`, then archive in a scratch copy and run `openspec validate --specs --strict` on the result.
- [x] 7.2 Run `just check` inside the devcontainer and fix any failures until it passes.
