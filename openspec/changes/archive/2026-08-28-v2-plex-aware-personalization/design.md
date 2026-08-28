## Context

Tasterr 1.1 already has the seams needed for v2: Plex PIN login stores one Fernet-
encrypted account token on each Plex-backed session; all outbound calls are
isolated in `clients/`; the recommendation engine has pure sparse-vector math and
server-only strong signals; and the rail composer already supports per-user
providers, admin gates, de-duplication, minimum sizes, and per-provider
degradation. The implementation should extend those seams instead of creating a
second feed or recommendation system.

The Plex Media Server API now documents JSON responses, authenticated playback
history, pagination, and the `continuewatching` provider feature. Its auth guide
also documents resolving per-server access tokens and preferred local/relay
connections through `clients.plex.tv/api/v2/resources`. Exact response fields,
managed-user behavior, TMDB GUID inclusion, and the household deployment's HTTPS
connections still require a redacted live-contract spike before production code
is allowed to depend on them.

The frozen PRD leaves two product details open: how household members are selected
and what “outside normal taste” means. This design chooses ephemeral caller-driven
selection for a blend and treats exploration as a low-correlation quality filter,
not inverse scoring.

## Goals / Non-Goals

**Goals:**

- Make actual Plex watches a private, bounded, rebuildable input to each user's
  existing taste profile.
- Add Continue Watching without making Plex availability a prerequisite for Home.
- Preserve discovery breadth with an honest, deterministic fringe rail that does
  not surface titles the user has rejected or already engaged with.
- Let two to six household members request one combined rail without exposing any
  member's signals, profile vector, scores, or credentials.
- Keep every v2 rail default-enabled, independently admin-toggleable, accessible,
  typed, and failure-isolated.
- Add no runtime dependency and no required deployment setting.

**Non-Goals:**

- Direct playback/control, Plex writes/webhooks, a durable Plex mirror, fuzzy
  catalog matching, persisted household groups, per-user rail settings, random
  exploration, a new worker/scheduler, or multi-process support.
- Solving legacy-to-JWT Plex auth migration speculatively. The live spike is a
  decision gate; token-flow work is added only if the current stored token cannot
  perform the required documented reads.
- Packaging or publishing v2.0.0 in the feature change.

## Decisions

### 1. A redacted live Plex contract spike gates implementation

Before changing production code, exercise the current PIN-issued token against
`/api/v2/user`, `/api/v2/resources`, PMS `/identity`, `/accounts`,
`/status/sessions/history/all`, `/hubs/continueWatching`, and the minimum metadata
lookup needed to obtain canonical GUIDs. Record only endpoint/status/field shapes,
Plex and PMS versions, paging behavior, user-scope behavior, and generic pass/fail
results in `docs/PLEX-V2-SPIKE.md`; never record a token, connection URL, server or
household name, rating key, title, or raw body.

The spike must confirm the identity fields returned by `/api/v2/user`, how that
identity resolves to the server-local account id exposed by `/accounts`, resource
paging behavior, the exact account-id field echoed on every history row, and the
timestamp used to order Continue Watching items. It must prove that explicit
account filtering isolates owner, managed, and shared-user history and that the
Continue Watching hub is either scoped to that authenticated account or can be
filtered to it. If Continue Watching cannot be proved user-scoped, it is skipped
for tokens with multi-user visibility.

The spike must also confirm that a resource access token works in an HTTP header
and that advertised HTTPS connections present a publicly valid certificate for
their hostname while matching the advertised machine identifier. Standard TLS
certificate and hostname verification stays enabled; `verify=False` is not an
implementation option. Any failed identity, isolation, TLS, or token assumption
stops implementation until this design is revised.

Resource pagination is implemented only if the spike shows that
`/api/v2/resources` actually paginates; otherwise the one bounded response is the
complete contract.

The 2026-08-25 household spike and 2026-08-27 opt-in suite passed the hard gates.
They found that resources are
one unpaginated response; accepted connections are HTTPS `*.plex.direct` URLs
with explicit advertised ports; history pages use `accountID` and `viewedAt`;
Continue Watching items are nested under `MediaContainer.Hub[].Metadata` and use
`lastViewedAt`, `viewOffset`, and `duration`; and canonical ids require metadata
GUID expansion. Traditional PIN-issued non-JWT tokens remain viable. The cloud
account id directly matches managed/shared PMS account ids, but not the owner id.
Owner-capable tokens resolve `/accounts`; one managed server token explicitly
received 403 because non-admin history is self-only, so that path uses the
validated positive cloud id and retains exact per-row validation. Full redacted
evidence is in `docs/PLEX-V2-SPIKE.md`.

### 2. Extend the thin Plex client; do not add an SDK

`clients/plex.py` remains the only Plex wire boundary. Split its auth and media
responsibilities into small typed clients only if the file becomes materially
clearer; do not add an interface/factory or `python-plexapi`. Pydantic wire models
ignore unknown fields, all calls request JSON, use explicit short timeouts, and
translate transport/5xx/shape failures into the existing upstream errors.

The account token is sent only in `X-Plex-Token`, never a URL/query or log.
Resource discovery asks for HTTPS and relay connections, sorts PMS resources
owned-first and then by advertised machine identifier, and keeps the first four.
The selected resources and each resource's at most six advertised connections
are validated concurrently, but results retain deterministic local HTTPS, remote
direct, relay, then URI preference. Pending lower-priority probes are cancelled
once the first verified connection in that order is known. A connection is accepted
only when its normalized URI is HTTPS on a narrowly
allowlisted Plex hostname/port shape confirmed by the spike, standard TLS
certificate and hostname verification succeeds, and its unauthenticated
`/identity` machine identifier equals the advertised identifier. Plain HTTP,
embedded credentials, fragments, unexpected ports/schemes/hosts, TLS failures,
and identity mismatches are skipped. Redirects are never followed. The allowlist
must not broaden to arbitrary URLs or general private-network hosts.

The confirmed URI policy accepts only `https`, a hostname ending in
`.plex.direct`, an explicit valid port, no embedded credentials, an empty or root
path, and no query or fragment. Resource discovery consumes the single returned
list without pagination. Account validation and resource discovery run together,
but either failure cancels and awaits its sibling. Metadata lookup accepts a row
only when its echoed rating key matches the requested key.

The per-resource `accessToken` is held only in the current call stack. It is never
persisted, returned, logged, placed in a query string, or stored in the general
cache. Only final secret-free mapped Continue Watching results may be cached.
The decrypted account token remains a masked `SecretStr` while it crosses the
request's rail context and is unwrapped only at the Plex call boundary. Invalid
advertised URLs are rejected before the six-connection probe budget is applied,
so malformed entries cannot crowd out otherwise eligible connections.

### 3. Explicit Plex account scoping prevents owner-token privilege confusion

Every history synchronization first validates the account token with
`/api/v2/user` and retains its positive numeric cloud account id and username only
for the current call. Each validated PMS is asked for `/accounts`. Resolve exactly
one positive server-local account row by an exact numeric `id` or `key` match to
the cloud id; when no numeric match exists, as observed for the owner account,
require exactly one case-insensitive `Account.name` match to the validated
username. Ignore unrelated malformed/non-user rows, but ambiguous, conflicting,
missing, or malformed candidate resolution fails that server.

The [Plex history contract](https://developer.plex.tv/pms/) is admin-wide for
owners and self-only for non-admins. If and only if `/accounts` returns an
explicit 403, use the already-validated positive cloud account id as the
non-admin history filter. Redirects, 401, transport, 5xx, and malformed responses
do not take this fallback. Neither account data nor the resolved id is persisted
or logged.

The resolved server-local id is passed as the PMS history `accountID` filter even
when the access token would otherwise have administrator visibility. Every
returned row's `accountID` must equal that same resolved id. A page with a
missing, malformed, or different `accountID` fails that server read, and none of
that server's rows are imported. The caller's session supplies both the Tasterr
user id and encrypted Plex token; neither is accepted from the browser.

Local-login sessions have no Plex capability. If the same mirrored Tasterr user
previously imported Plex watches, those durable taste signals remain, but that
local session receives no live Continue Watching rail and cannot trigger a new
Plex sync.

### 4. Canonical TMDB GUIDs are the only cross-catalog join

The Plex adapter maps a movie only from a `tmdb://<positive-id>` GUID. Episode
history and Continue Watching entries collapse to their containing show, whose
metadata must carry its own TMDB GUID. Episode context is generated locally as
`S{season} E{episode}` only from validated positive integer fields; no upstream
display string is forwarded. Duplicate movies/shows across servers are merged by
`(media_type, tmdb_id)`, keeping the entry with the newest validated last-viewed
timestamp (the spike pins its exact Plex field), then deterministic resource order
as a tie-breaker.

Missing/malformed GUIDs, unsupported media types, specials without a resolvable
show, and TMDB ids outside the shared database-safe range are skipped. Title/year
search is rejected: a false match would quietly teach the wrong profile and is
worse than omitting one item.

### 5. History synchronization is bounded, idempotent, and request-triggered

Add nullable `users.plex_history_attempted_at` and
`users.plex_history_synced_at`. Login and Home use one trigger rule: a Plex-backed
session may schedule a per-user single-flight task only when the attempt timestamp
is absent or older than six hours. Plex uses its own in-process single-flight set;
it reads but never joins the separate Seerr seed set that drives onboarding state.
After task creation, the task owns a fresh DB session and commits the attempt
timestamp before any network work. If task creation or that commit fails, cleanup
removes the single-flight claim, no network call runs, and no attempt timestamp is
left behind. Login/Home never waits for or fails on the task.

The existing Seerr cold-start task retains first claim on a new user. Plex sync
does not start while that user's seed task is active; login/reset chains the Plex
eligibility check after seeding settles, and Home defers to the same chain. This
keeps the existing "no stored signals" seed guard from being defeated by a faster
Plex import without adding another seed-state model.

Each sync captures a UTC cutoff. If no success watermark exists, it asks for at
most `cutoff - 365 days` through the cutoff; otherwise it asks from
`plex_history_synced_at - 24 hours` through the cutoff. Reads are newest-first,
pages are 100 rows, and each selected server contributes at most 500 rows. The
entire network/mapping phase has a 30-second deadline. Missing GUIDs may use at
most 500 metadata resolutions across the sync with concurrency eight. Hitting a
row or metadata cap is a successful bounded read: older/unresolved overflow is
deliberately dropped, and this household-scale coverage trade-off is logged only
as generic counts. Deadline expiry is a failure for every server that has not
completed its bounded read; it never counts as cap completion.

The success watermark advances to the captured cutoff only when every selected
server finishes its bounded read. A failed server leaves the prior success
watermark in place while the separate attempt timestamp prevents retry storms.
Successful sibling facts may persist idempotently; after recovery the next run
again reads newest-first from the old success window, so a backlog beyond the cap
can be omitted by design. This global two-timestamp model is preferred over a
per-server state table until observed multi-server failures justify it.

All Plex/TMDB reads and canonical mapping finish before SQLite writes begin.
Mapped facts are upserted in transactions of at most 100 rows with no network I/O
while a write transaction is open. Reset first cancels and awaits any active
per-user Plex task using a `CancelledError`-safe await such as
`asyncio.gather(task, return_exceptions=True)`, then clears that user's
signals/profile and both Plex timestamps in one transaction. The timestamp clear
uses an unconditional SQL update so an import attempt committed after the reset
request loaded its user cannot survive through a stale ORM snapshot. It re-seeds
Seerr as today and, for a usable
Plex-backed session, runs the same post-seed/staleness scheduling path. Task
cancellation must roll back an open batch, and the await remains bounded by the
task's 30-second deadline, so no in-flight import can repopulate the reset state
after a successful reset response.

`watched_plex` is server-recorded, fixed at +2.5, strong-positive, and unique per
user/title. Re-import updates its `created_at` only when the newly observed watch
is later, invalidating the materialized profile in the same transaction. TV
episode counts do not multiply a show's weight. Raw history rows, play counts,
server ids, and rating keys are discarded after mapping. Signal inserts target
the named partial unique-key shape explicitly rather than accepting an arbitrary
future uniqueness conflict.

### 6. Continue Watching is live/cached presentation data, not a signal store

For a Plex-backed session, a `continue-watching` provider asks each validated
server for at most 50 items nested under `MediaContainer.Hub[].Metadata`, orders
eligible rows newest-first with deterministic resource/input ties, and retains at
most the first `RAIL_SIZE = 20` distinct per-server rating keys before any Plex
metadata/GUID expansion. It then
maps and merges canonical titles and resolves at most 20 through TMDB. This may
under-fill when raw rows collapse to the same title or lack a canonical GUID,
which is preferable to expanding up to 200 metadata rows inside the Home
deadline. Add optional
`progress_percent` and `context` fields once to the existing `MediaSummary`, which
the detail shape inherits; ordinary catalog/detail items leave them null. A TV
entry may say `S2 E4` only when both integers validate, and a movie
omits context. Progress is `floor(100 * view_offset / duration)` for finite,
non-negative offsets and positive finite durations. A summary is included only
when that result is 1 through 99; zero, complete, missing, and invalid progress
omit the item rather than clamping it into a misleading state.

The complete Continue Watching load, including connection fallbacks and TMDB
mapping, has a ten-second wall-clock deadline. A redacted cold-path timing check
found that five unavailable advertised connections consumed about 23 seconds
serially before the sixth verified in 0.26 seconds, while the resulting 20-item hub
read took 0.07 seconds. Concurrent bounded identity probes remove the serial
timeout sum, and the pre-expansion 20-item cap bounds the metadata work that the
timing did not measure, while the ten-second aggregate remains a Home-latency
backstop.
Cache only the final secret-free
per-user result for five minutes. A deadline/upstream failure becomes an empty
negative entry for the same five minutes; this provider does not use stale-on-
error, so the existing cache API needs no new write seam. Capability gating occurs
before token decryption and cache access, and the masked account token is unwrapped
only inside the provider fetch. The provider uses no request DB session and composes non-
exclusively, while its declared order still places a successful result first in
the personalized response. It uses normal cross-rail de-duplication and disappears
when disabled, tokenless, not provably user-scoped, empty, or unavailable. Plex
failure never fails Home and never changes Seerr degradation.

Non-exclusive Home work is started before the serial request-session providers,
so the ten-second Plex backstop overlaps their computation without changing
response order. Cancellation or an unexpected exclusive-provider failure still
cancels and awaits every started non-exclusive sibling.

### 7. “Picks You Wouldn't Usually Watch” is a low-correlation gate

Add a pure exploration ranker beside the existing scorer. Build a broad bounded
pool from already-supported trending, popular movie/TV, recent, and non-leading
genre discovery surfaces. Reuse cached title vectors and availability. Exclude
every hidden title and every strong-positive/engaged title, including Plex watches.

Compute similarity for the bounded pool, reject negative values, sort remaining
candidates by `(similarity, media_type, tmdb_id)`, and admit the lowest quarter
rounded up. This relative band adapts to broad and narrow profiles without forcing
negative taste. Rank admitted candidates by the existing shrunken quality prior
plus the single availability boost, then apply the existing MMR diversity penalty.
Do not randomize or invert similarity. The provider requires a non-empty profile
and at least four results; otherwise it disappears. Source rail toggles control
presentation, not reuse of their catalog surfaces, so disabling Trending or
Popular does not remove those titles from the exploration input. Constants live
beside the existing `CANDIDATE_CAP = 150` and are pinned by ordering/boundary tests
rather than exposed as settings.

Place the rail after the principal personalized, trending, popular, and recent
rails. Earlier rails therefore keep priority during cross-rail de-duplication and
the exploration row contains the remaining fringe instead of stealing obvious
home-page titles.

### 8. Home order is deliberate and daily variation stays pagination-safe

The visible Home sequence is Continue Watching, My List, Recommended for You,
Trending Now, the related-title rail, Popular Movies, Popular TV, Recent
Releases, Picks You Wouldn't Usually Watch, Top Rated Movies, Top Rated TV,
selected-service rails, decades, then genres. Omitted or disabled rails close the
gap without changing the relative order of survivors. Later groups may arrive
through the existing paginated rails endpoint, but the SPA appends them in this
same order.

The related-title provider takes the three newest unique non-hidden
strong-positive sources, applies a standard-library shuffle seeded by local user
id plus calendar date, then tries that bounded order. Candidate ranking remains
unchanged. Movie and TV genre providers likewise use one user/day-stable shuffle
after decades, with explicit **{Genre} · Movies** and **{Genre} · TV** labels.
Stable daily seeds give variety without per-request jumps, skipped cursor pages,
or repeated rails; no selection or seed is persisted.

Cross-rail title priority applies to the initial `/home` response, where the full
ordered provider set is composed together. The stateless `/rails` cursor cannot
carry a trustworthy seen-title set from earlier pages; deduplicating only among
the four providers that happen to share one cursor response made a later service,
decade, or genre rail shrink according to page boundaries while duplicates across
adjacent pages remained. Paginated extra rails therefore remove duplicates only
within each individual rail and may repeat a title from another extra rail. This
keeps each category's bounded upstream result intact and makes cursor grouping
irrelevant without adding client-supplied exclusions or server-side pagination
state.

### 9. Household selection is ephemeral and every blend includes the caller

Add a session-gated member read returning the caller and other local users in
ascending local-user-id order using only local user id, display name, avatar, and
`has_taste_signals`. That boolean is
true exactly when at least one stored signal exists; it is a deliberately coarse
household activity indicator, not a profile-quality claim. The endpoint never
returns auth type, admin state, Seerr/Plex ids, activity timestamps, signal kinds,
or profile data. When the global household-blend rail type is disabled it returns
no members, so the SPA does not present a dead control.

An inline Home section presents **Something for Everyone Tonight** as a native
disclosure collapsed by default. Opening it lets the caller choose two to six
eligible users, always including themselves, and explicitly request the blend;
collapsing it hides the picker/result without replacing Home content.
Selection lives only in React state, resets at a confirmed account boundary, and
is not stored in a cookie, browser storage, DB row, or global setting. The compute
endpoint is a same-origin, rate-limited POST because it accepts a private audience
in the body and can materialize derived caches; it persists no selection.

The backend validates unique existing ids, caller inclusion, a stored signal for
each member, and the 2–6 bound before loading profiles. It materializes at most six
profiles through the normal service path; if any resolves empty, the whole request
fails generically rather than silently changing the audience. It computes the
normalized arithmetic mean, adds each selected user's existing bounded candidate
sources until the shared `CANDIDATE_CAP = 150` is reached, vetoes any title hidden
or already strongly engaged by any selected user, and runs the existing
rank/diversity/availability path. It returns only a standard secret-free Rail.
Individual similarity, contributions, reasons, and signals are never exposed.

### 10. New rail types use the existing toggle and degradation machinery

Register `continue-watching`, `unexpected-picks`, and `household-blend` in
`RailType`/labels. The current absent-from-disabled-set rule makes them enabled by
default and the existing admin settings UI lists server-provided descriptors, so
no new preference schema or specialized settings screen is needed.

Continue Watching and unexpected picks compose through normal providers.
Household blend is requested separately because audience selection is ephemeral;
its endpoint checks the same global rail gate before any DB/TMDB work. Each path
has an independent failure boundary and minimum size. No v2 failure replaces Home
with an error. Cross-rail de-duplication remains exact within each Home response;
the separately requested household rail may repeat a title already visible on
Home because sending the client's visible-title set back to the server would add a
second, user-controlled exclusion contract for little benefit.

### 11. Deliver through review checkpoints, then release separately

Implementation proceeds in dependency order: contract/security seam; history
signals; Continue Watching; unexpected picks; household blend; generated
contracts/docs; full verification. Each checkpoint has focused runnable tests and
can be reviewed before the next begins, while the OpenSpec change, code, and
living-spec deltas still archive atomically on one feature branch.

After merge, prepare v2.0.0 in the repository's normal separate release change so
version edits, live verification evidence, image publication, and rollback
instructions receive their own audit.

## Security considerations

**API endpoints.** All new reads use the shared session dependency and explicit
secret-free models. The household compute POST validates through Pydantic, requires
same-origin evidence and the authenticated mutation bucket, returns generic errors,
and is added to the mutation inventory. No route accepts a token, Plex URL, Plex
account id, server id, profile vector, signal, or arbitrary upstream parameter.

**Auth/sessions.** Plex tokens remain Fernet ciphertext at rest and are decrypted
only for a caller's bounded server-side read/task. Local sessions have no Plex
capability. Raw account/resource tokens never enter URLs, logs, task names, cache
keys, response models, frontend state, or generated schemas. Revoked/malformed
tokens degrade and do not reveal why to another user.

**Outbound HTTP / SSRF.** Only `clients/plex.py` imports httpx. Resource URLs are
not trusted merely because plex.tv returned them: scheme/host/port/credential/
fragment checks, public TLS certificate/hostname verification, and machine-
identity verification precede authenticated reads. Redirects are never followed.
The allowlist accepts only spike-confirmed Plex connection host/port shapes; a
`.plex.direct` name resolving to a private server is safe only through its Plex-
controlled hostname certificate plus advertised machine-id match. Connections,
servers, pages, rows, metadata resolutions, concurrency, and total deadlines are
bounded. One server failure cannot trigger unbounded fallback attempts.

**Frontend.** Plex/Seerr/TMDB text remains plain text. No connection URL or token is
sent to or assembled by the SPA, and no audience selection is stored in Web
Storage. Progress/context fields are scalar, validated, secret-free output. New
controls retain visible focus, accessible names/state, remote navigation, reduced-
motion behavior, and confirmed-user cache isolation.

**Database/migrations/privacy.** The migration adds two non-secret sync timestamps
and changes a partial unique index; it does not copy or decrypt secret material.
Plex/TMDB network work finishes before bounded SQLite write batches begin. Durable
viewing data is limited to the canonical title signal already covered by the taste
privacy model. Household operations always include the caller and never serialize
another user's profile or signals. The member list intentionally reveals the
coarse fact that another local account has at least one signal. Caller-inclusive
aggregate rails can still support differential taste inference; that is an
accepted household-trust trade-off for V2, constrained by the 2–6 audience bound,
caller inclusion, candidate cap, generic errors, and existing mutation rate limit.
Logs contain generic outcome/count classes only, never title ids, audiences,
account/server ids, history timestamps, or upstream payloads.

**Dependencies and public release.** No dependency is added. Recorded fixtures use
invented values; live evidence is redacted and excluded from default/CI network
tests. PublicConfig, outbound-boundary, response-model, mutation-inventory, log,
and repository-secret regressions must cover the new paths before archive.

## Risks / Trade-offs

- Plex's resources/history/hub contracts and newer JWT direction may change. The
  spike and opt-in live tests pin only the minimal used contract; all failures
  degrade. If legacy PIN tokens stop working, auth migration becomes a separate
  reviewed prerequisite rather than hidden inside the media client.
- HTTPS-only validated resource connections may omit an HTTP-only server. That is
  the safe default for an internet-exposed service. The live spike may justify a
  narrowly validated operator URL later; this design does not pre-authorize it.
- A global success watermark retries successful servers when one selected server
  fails, while a separate attempt timestamp limits retries. Newest-first row and
  metadata caps mean an oversized stalled backlog can lose older facts when the
  watermark eventually advances. This bounded household-scale trade-off avoids a
  per-server state table; split watermarks are warranted only if observed multi-
  server failures make the loss material.
- Collapsing all episode watches to one latest-dated show signal loses episode
  count and rewatch intensity. It prevents long-running shows from overwhelming
  the profile and matches the title-level engine.
- The relative exploration quartile may under-fill after exclusions or contain
  only modestly distinct items for an unusually uniform pool. Earlier Home rails
  keep de-duplication priority, and omission is preferable to intentionally
  recommending disliked content; tune only from observed results.
- Related-title and genre order changes at the server's calendar-day boundary,
  not on every refresh. This favors stable pagination over fresh randomness on
  each request; revisit only if persistent feed sessions span that boundary often
  enough to cause observed duplicate/skip behavior.
- The ten-second Continue Watching deadline may still under-fill or hide the rail
  for unusually slow relay/remote households. Concurrent bounded connection
  probes plus the numbered hub and TMDB-resolution caps keep it a backstop; tune
  only from further live evidence.
- Arithmetic-mean household profiles are understandable but not a full fairness
  optimizer. A hard hidden/engaged veto prevents the clearest bad outcomes; more
  elaborate per-person minimum-score math waits for real household feedback.
- Ephemeral blend selection requires re-selection after leaving/reloading Home.
  That is deliberate: it avoids durable social state until repeated use proves it
  valuable.
- A caller-inclusive blend can reveal aggregate differences as the caller changes
  selected members, and the member list reveals coarse signal activity. V2 accepts
  this within the authenticated household trust boundary; do not add per-person
  scores or reasons without a new privacy review.

## Migration Plan

1. Complete and review the redacted live spike. Revise the design/specs first if
   any security or identity assumption fails.
2. Add the migration with nullable `plex_history_attempted_at` and
   `plex_history_synced_at`; replace the existing partial unique signal index so
   it also covers `watched_plex`. Existing rows and settings remain valid and new
   rail types default enabled because they are not in existing disabled lists.
3. Land client/domain/history behavior, then each rail and its focused tests in
   the task order. Regenerate OpenAPI/types at each endpoint-model checkpoint and
   perform one final drift check after all models settle.
4. Run strict OpenSpec validation, focused live Plex contracts, living-room/manual
   degradation checks, and `just check` in the devcontainer before archive.
5. Archive on the feature branch so living specs and code land atomically. Prepare
   and publish v2.0.0 in a separate release change.

Rollback requires the `0006` schema downgrade before starting v1.1. The downgrade
removes `watched_plex` signals, restores the prior partial index, drops both Plex
sync timestamps, and removes the three v2 rail ids from the runtime settings'
disabled list while preserving every v1.1 setting. It also removes materialized
profiles for users whose Plex signals were deleted so v1.1 rebuilds them from the
remaining canonical signals. Starting v1.1 directly on a v2
database is unsupported: its profile code would fold `watched_plex` rows in by
stored weight, and an unknown v2 rail id in saved settings would invalidate the
whole runtime document and fall back to defaults. The supported downgrade loses
only re-importable Plex-derived taste data; no raw history or credential is
involved. An absent settings row, unparseable document, missing disabled-list key,
or document already free of v2 ids is treated as already v1.1-compatible and does
not fail the downgrade; v1.1's existing loader will use defaults for an
unparseable document.

## Open Questions

- **Post-ship tuning:** Does the lowest non-negative similarity quartile reliably
  yield four or more useful titles across real profiles? The fraction is a tested
  V2 constant, not a user setting.
