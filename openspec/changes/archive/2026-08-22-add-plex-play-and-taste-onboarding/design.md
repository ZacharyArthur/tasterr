## Context

Availability currently reduces Seerr `mediaInfo` to status and seasons, even though Seerr already returns Plex web and custom-scheme links. A redacted read against the household Jellyseerr 3.4.1 instance confirmed `mediaUrl` and `iOSPlexUrl`; `plexUrl` was absent, as expected for Jellyseerr. No 4K record was present to exercise the optional 4K values, so recorded fixtures must cover both flavor aliases and all documented variants.

The Android choice was resolved before design on a connected Samsung device running Android 16 with the current `com.plexapp.android` package. Android resolved and opened a real `plex://preplay/…` URI in Plex, while `https://app.plex.tv/desktop/` resolved to Chrome. Chrome's documented `intent://` contract supplies `S.browser_fallback_url` when the target package is absent.

Follow-up LAN testing on Windows, Android, and iPadOS found that Plex Web and the installed mobile apps can discard the requested destination during sign-in or household-user selection and land on Plex Home. The web route sometimes succeeds on a later activation after Plex finishes initializing, while the native route consistently launched Plex but lost the destination in the tested clients. Tasterr cannot inspect or repair cross-origin Plex client navigation state without the prohibited Plex token/API scope, so the UX must preserve Tasterr for a user-driven web retry and label the handoffs honestly.

Cold-start seeding runs asynchronously after login. The durable signal store already tells whether personalization has any input, while a process-local `seeding` set tells whether that answer is still pending. The Home response already contains enough varied titles to populate a small picker without another catalog endpoint.

## Goals / Non-Goals

**Goals:**

- Surface safe Seerr-provided playback links for fully or partially available regular and 4K library records across Overseerr and Jellyseerr.
- Provide separate keyboard/remote-focusable Plex Web and Plex App controls so users can choose a recoverable browser path or attempt native handoff without a dead custom-scheme-only path.
- Offer a one-time, non-blocking taste picker only after a user's cold-start seed has finished with no signals.
- Reuse `watchlist` signals and the existing profile pipeline.

**Non-Goals:**

- Plex tokens, direct Plex HTTP, playback control, watch-history ingestion, or playback progress.
- A new signal kind, recommendation weight, catalog, route-level onboarding wizard, or dependency.
- Separate regular/4K buttons; one regular-first control is sufficient.

## Decisions

### 1. Normalize all Seerr aliases at the client boundary

`SeerrMediaInfo` will accept `plexUrl` or `mediaUrl` as the regular web link, `iOSPlexUrl` as the regular app link, and the corresponding `plexUrl4k`/`mediaUrl4k` and `iOSPlexUrl4k` fields. It will also parse `status4k`. Pydantic alias choices keep the flavor difference inside `clients/seerr.py`; downstream code sees one vocabulary.

Alternative: inspect the configured Seerr flavor. Rejected because the payload itself is sufficient and flavor detection adds a second contract.

### 2. Availability owns validated, ready-to-use links

The typed `Availability` model will contain an optional nested playback-link model for regular and 4K web, app, and Android-intent URLs. Normalization accepts web links only when they are credential-free HTTPS URLs on `app.plex.tv`, and app links only when they are fragment-free `plex://preplay/` URLs. Both link forms reject case-insensitive `X-Plex-Token` parameters before serialization. The Android intent is assembled server-side from those validated inputs with the fixed Plex package and a percent-encoded web fallback. Invalid or incomplete pairs are dropped.

Availability status considers both `status` and `status4k`, preserving the highest Seerr fulfillment state. Playback links are retained only for a variant Seerr marks available or partially available. Batch availability uses the same secret-free model; this avoids a second near-identical response shape. Jellyseerr deployments backed by Jellyfin or Emby can emit `mediaUrl` links for their own host; the narrow `app.plex.tv` allowlist intentionally rejects those links and renders no Plex controls.

Alternative: forward the raw strings and build the intent in React. Rejected because upstream JSON is untrusted and the frontend security contract requires external URLs to come from the BFF.

### 3. Explicit Plex Web and Plex App controls, regular-first

The detail modal resolves validated playback data without duplicating Seerr status rules, chooses the regular link set first, and falls back to 4K when regular is absent. It renders a Plex Web link for every resolved variant, plus a Plex App link when that variant has a validated platform target. The web link always uses HTTPS and opens in a new context with `noopener noreferrer`, preserving Tasterr so the user can retry after Plex finishes sign-in or household-user selection. On Android, the app link uses the prebuilt intent with its missing-app browser fallback; other platforms use Seerr's custom-scheme app URL without a timed navigation fallback. The controls carry a static experimental qualifier and participate naturally in the modal focus trap.

Alternative: keep one platform-selected Play link or automatically retry the web target. Rejected after live testing because every tested Plex client can discard the requested title during household-user/PIN handling, and browser isolation prevents Tasterr from observing the result. A delayed retry can also replace Tasterr while an iOS app-confirmation prompt remains open. A dedicated dependency, redirect service, or Plex-aware authentication state would exceed this change's scope.

### 4. Persist only whether onboarding was handled

Alembic revision `0005` adds `users.taste_onboarding_seen`, non-null with a false default. Eligibility is derived rather than duplicated: `done` when the flag is true or signals exist, `pending` while the user's cold-start seed is reserved/running, and `show` otherwise. The seed reservation moves before task creation so a status request cannot observe an unscheduled gap; the existing background helper retains single-flight and cleanup behavior.

Alternative: persist a multi-state onboarding/seed state machine. Rejected because signals plus the live seeding set already represent every state needed by one process.

### 5. One read endpoint and one bounded mutation

`GET /api/v1/taste-onboarding` returns `pending`, `show`, or `done` for the session user. `POST /api/v1/taste-onboarding` accepts at most 12 typed title keys within the application's bounded positive title-id range, records each as the existing idempotent `watchlist` signal, marks onboarding seen, commits once, and refreshes the profile once. Every browser-controlled mutation that can record a taste signal, including the direct signal and request endpoints, applies the same database-safe id bound. An empty selection is Skip. Both responses are explicit and secret-free.

Alternative: call `POST /signals` once per selection and keep dismissal in browser storage. Rejected because it recomputes repeatedly and does not honor once-per-user behavior across devices.

### 6. The picker is an inline Home section

Home derives up to 12 unique candidates from the already-loaded hero and rails. The picker is a normal landmark with toggle buttons, a completion action, Clear picks, and Skip; it never traps focus, makes the browse shell inert, or delays Home. Selected title keys are retained independently of feed rerenders, while the same 12-title limit prevents newly presented candidates from extending the durable selection beyond the API bound. Visible selected titles remain removable, and Clear picks restores a choice path when every retained title has left the current candidate window. Submission failures are announced inline and leave browsing and the picker usable. The status query is keyed by session user and polls only after a successful `pending` response; if status fails or candidates are absent, the picker renders nothing and browsing remains intact.

Alternative: an automatic modal or dedicated onboarding route. Rejected because either blocks browsing or adds navigation/state for a one-time optional prompt.

### 7. The opener closes its Plex approval popup best-effort

The Plex sign-in button opens an empty, sized popup synchronously from the user activation and retains only its transient `WindowProxy` in component memory. This follows Seerr's practical popup pattern so the Tasterr parent can remain active enough to run the existing PIN poll instead of becoming a background tab. Before navigating the popup to the backend-provided Plex approval URL, Tasterr sets the child context's `opener` to `null`; this prevents the cross-origin Plex page from navigating or scripting the Tasterr tab while the parent retains the limited handle needed for `close()`. The existing same-origin PIN poll remains the sole login-completion signal. On success, Tasterr closes the approval context when the browser still exposes it, requests focus for the Tasterr window, then refreshes auth state. API failure and component teardown also clean up a live blank/approval context.

Popup blocking, manual closure, browser opener-policy isolation, or a mobile browser treating the requested popup as a normal tab must never block authentication. The PIN flow continues polling independently, and the existing reopen action creates and tracks another protected context. Auto-close and focus return are therefore progressive enhancements rather than conditions of successful login.

Alternative: remove `noopener` and open Plex directly with an unrestricted opener, or add a Plex `forwardUrl` callback page. The unrestricted opener creates a reverse-tabnabbing capability, while a callback adds public-origin construction and another auth surface for behavior the existing poll already knows. Both are unnecessary.

## Security considerations

- **API endpoints:** both onboarding endpoints require the shared session dependency and explicit Pydantic response models. The POST uses the same-origin guard and shared authenticated mutation limiter, validates media type/id and a maximum list length, keys every write from the session user, and is added to the mutation inventory. The existing request mutation uses the same bounded browser-supplied title id before it can call Seerr or record a signal. Errors remain generic and no title selections are logged.
- **Outbound HTTP:** only `clients/seerr.py` reads the extra upstream fields; the existing fixed settings-derived base URL, API-key read authentication, timeout, no-retry policy, and dropped unknown fields remain unchanged. No browser headers are forwarded and no Plex request is added.
- **Frontend:** links are validated and assembled by the backend, which rejects token-bearing web and app targets before either can reach a browser response or Android intent. React renders accepted links as ordinary attributes, opens the web target with `noopener noreferrer`, suppresses the app target's outbound referrer, and renders all labels/title metadata and the plain-language experimental qualifier as text and as the controls' accessible description; there is no HTML injection or client-side secret/token storage. No timer, popup polling, or cross-origin state inspection is added. Plex sign-in retains only a transient `WindowProxy`, clears the child context's `opener` before cross-origin navigation, navigates only to the backend-provided approval URL, and treats popup, focus, or close failure as non-fatal. Onboarding failures render no blocking UI and are announced to assistive technology; the client retains at most the server's 12 allowed selections, and per-user query keys prevent another household user's cached onboarding state from being displayed.
- **Database:** revision `0005` adds one non-secret boolean. SQLAlchemy expressions remain the only query/write path; no token or household title data is added to the user row or migration output.
- **Secrets/privacy/logging:** Plex/Seerr tokens, cookies, internal URLs, raw upstream bodies, household link values, and selected title ids are not logged or checked into fixtures. Tests use invented URLs and ids. PublicConfig remains unchanged.
- **Dependencies/build:** no dependency or lockfile change.

## Risks / Trade-offs

- [Seerr returns malformed or hostile link strings] → reject anything outside the narrow `app.plex.tv` HTTPS and `plex://preplay/` contracts; render no Play control.
- [A Seerr flavor renames another optional field] → typed parsing drops it safely; unit fixtures plus the opt-in live contract expose contract drift.
- [Android changes intent handling] → the web fallback remains embedded, and the behavior is isolated to one server-side builder plus a small user-agent selection.
- [A Plex client drops the destination during sign-in or household-user/PIN handling] → the controls are explicitly experimental, and Plex Web opens separately so Tasterr remains available for a user-driven retry; repairing Plex client state would require out-of-scope Plex integration.
- [A popup blocker, manual close, browser opener policy, or mobile tab behavior prevents automatic return] → PIN polling and login completion remain independent; the user may reopen or manually return, and auto-close/focus stays best-effort.
- [A user opens Home before background seeding completes] → the reservation makes status `pending`; the picker polls without blocking the feed.
- [Onboarding persistence succeeds but profile refresh fails] → watchlist signals are durable and the materialized profile self-heals on the next read.

## Migration Plan

1. Deploy revision `0005` before serving the new endpoints; existing users receive `taste_onboarding_seen = false`.
2. Existing users with signals resolve directly to `done`; signal-less users become eligible after no seed is running.
3. Rollback drops only the boolean. Picker-created watchlist signals remain valid user taste data and require no conversion.

## Open Questions

None.
