# Design: m3-seerr

## Context

M1 delegated identity to Seerr and already persists everything M3 consumes but
never reads: `sessions.seerr_cookie` (plaintext, per the SPEC §5 decision — it is
sent verbatim on every per-user call) and `sessions.plex_token_enc` (Fernet, for
silent re-auth). `clients/seerr.py` is auth-only today — a `SeerrAuthClient` that
logs in and returns a `SeerrLogin(user, cookie)`. M2 built `catalog/`, the
`cache.py` TTL + single-flight + stale-on-error layer, the `MediaSummary`/
`MediaDetail` domain models, the `/home`,`/rails`,`/title`,`/search` endpoints,
and the SPA — and deliberately left a hole for the availability badge (cards and
detail render without it) and no request affordance. `settings.py` already carries
`seerr_internal_url`, `seerr_external_url`, `seerr_api_key`, the `seerr_configured`
flag, and projects `seerr_configured` into `PublicConfig`. The shared
`httpx.AsyncClient` (no-store cookie jar) and the typed
`UpstreamUnavailable`/`UpstreamRejected` hierarchy exist.

This change turns SPEC §4.3 (per-user Seerr session, request-as-user, the 403
re-auth ladder), §6 (`/availability`, `/request`, detail-with-availability), and
§10 (Seerr: short timeout, no retry storm, failures flip to Unknown) into code —
the SPEC §13 M3 milestone ("request lands in Seerr attributed correctly"). The
auth spike (docs/SEERR-AUTH-SPIKE.md, Seerr 3.3.0) already validated the exact
shapes: `POST /api/v1/request {mediaType, mediaId}` → 201 with `requestedBy.id`
matching the user; invalid session → **403** (not 401); re-POSTing the stored Plex
token to `/auth/plex` → fresh `connect.sid`. The reference implementation
(browserr `src/server/seerr/`) is consulted for the availability read shape
(`GET /api/v1/{type}/{tmdbId}` → `mediaInfo.status`, 404 → not-in-library, error →
Unknown) and the request body — consulted, not ported.

## Goals / Non-Goals

**Goals:**

- Live availability badges across the browse surface, hydrated *after* the feed
  renders so Seerr never sits on the critical path (invariant 3).
- Availability reads authenticated by the **global** `SEERR_API_KEY` (not
  user-attributed) so badges survive a lapsed user session, cached briefly with
  single-flight, degrading Seerr errors to **Unknown** (not stale).
- Request-as-user through the stored per-user Seerr cookie, landing in Seerr
  attributed to that member under their quota, with the SPEC §4.3 403 re-auth
  ladder (Plex silent re-auth once; local `re_auth_required`) and a server-built
  external redirect fallback.
- Make the "Seerr degrades, never blocks" invariant real and tested (unconfigured
  and down), where M2 only built the seam.
- Keep the Seerr client the sole Seerr caller and every new response secret-free.

**Non-Goals:**

- A Seerr-sourced library rail (deferred to M4/M5 — proposal Non-goals).
- Any personalization, `signals`/`profiles` writes, availability-boost scoring,
  or cold-start seed (M4).
- Admin settings, `connection-test`, configurable region/services (M5).
- Broad mutation rate limiting (M6); `/request` gets the CSRF origin check now.
- 4K tiers, per-season request selection, request editing/history, background
  availability pre-warming.

## Decisions

1. **Two capabilities: availability engine vs. request product.**
   `media-availability` (Seerr reads + status model + cache + degradation + the
   `/availability` endpoint + detail embedding) is the reusable, cache-backed
   *read* engine that M4's availability-boost will consume; `media-requests`
   (`POST /request` + silent re-auth + redirect fallback) is the per-user
   *mutation* with a distinct security profile (CSRF, the encrypted-token re-auth,
   the per-user cookie). The split mirrors M2's catalog-engine vs. browse-product
   framing and keeps the stable, decoration-only read contract apart from the
   stateful write flow. Rejected: one `seerr-integration` capability — smaller file
   count, but muddies which half M4 reuses (reads) versus which is terminal
   (requests), and blends two different degradation and auth stories.

2. **Availability auth = the global API key; requests = the per-user cookie —
   never crossed.** Availability is not user-attributed (SPEC §4.3), so reads send
   `X-Api-Key: {SEERR_API_KEY}` and keep working when a user's Seerr session
   lapses. Requests send only `Cookie: {seerr_cookie}` so Seerr attributes them to
   the member and enforces *their* quota. The existing client comment already warns
   against attaching the global key to user flows (privilege confusion); this keeps
   the two auth paths strictly separate — the global key is never attached to a
   request, and a user cookie is never attached to an availability read. Rejected:
   using the global key for requests (SPEC's rejected "admin-key impersonation" —
   loses attribution and quota enforcement); using the user cookie for availability
   (breaks badge hydration on session lapse, the whole reason reads are global).

3. **Seerr read client (`clients/seerr.py`).** Add `availability(type, tmdb_id)`
   and `create_request(cookie, body)` to the existing module (still the only Seerr
   caller). Availability: `GET {SEERR_INTERNAL_URL}/api/v1/{type}/{tmdbId}` with a
   **short timeout and no retry** (SPEC §10 — no retry storm), parsing
   `mediaInfo.status` (+ per-season `status` for TV) into a typed model;
   `404` → a typed *not-in-library* result (known); any other error/timeout →
   raise, and the availability service maps it to **Unknown**. Requests:
   `POST /api/v1/request` with the user cookie, mapping `201` → the created
   request's resulting status, `403` → a typed `SeerrForbidden` the request flow
   interprets (re-auth ladder). Rejected: a second Seerr client class (needless —
   one module, method-level auth); retrying Seerr reads (a rail of 40 misses would
   amplify a Seerr blip into a storm; Unknown is the correct fast degrade).

4. **Availability model + status mapping (`catalog/availability.py`, secret-free).**
   A typed `Availability { status: Literal["available","partial","processing",
   "pending","not_requested","unknown"], known: bool }` — `known=false` only for
   Unknown (Seerr unreachable), distinguishing it from a *known* "not in library".
   Seerr's numeric `mediaInfo.status` (1 unknown/2 pending/3 processing/4 partial/5
   available; absent `mediaInfo` → not_requested) maps in one pure function that
   unit-tests with no network. The model imports no settings (import-linter, see
   decision 9). Rejected: leaking Seerr's raw integer to the client (untyped, ties
   the API to a Seerr internal); a per-season matrix in the summary badge (detail
   carries season detail; the card badge is one status).

5. **Availability cache: short-TTL single-flight, errors → Unknown, no
   invalidation.** Reuse `cache.py` with a short per-class TTL keyed by
   `seerr:avail:{type}:{id}`, so a home render hydrating ~40 cards, and repeat
   navigations, collapse to few Seerr calls. Seerr errors are caught in the
   availability *service* → `Availability(unknown)`, so they are never cached and
   never served stale (SPEC §10 — Seerr degrades to Unknown, unlike TMDB's
   stale-on-error; the stale window is set to zero for this class). No
   cache-invalidation machinery: a successful `POST /request` returns Seerr's
   authoritative new status and the SPA updates that badge optimistically; other
   views may lag by ≤ the short TTL, which is fine at household scale. Rejected:
   stale-on-error for availability (contradicts §10 and would show "available" for
   a title Seerr can no longer confirm); a bespoke availability cache (the M2 layer
   already does TTL + single-flight); active invalidation on request (machinery for
   a ≤30 s cosmetic lag).

6. **Batch `POST /availability` + detail embedding.** The SPA hydrates badges
   *after* the feed paints: session-gated `POST /availability` takes a bounded list
   (Pydantic `max_length`) of `{type, id}` and returns `{ "<type>:<id>":
   Availability }`, fanning out through the cache with bounded concurrency, each
   failure degrading to Unknown independently. `GET /title/{type}/{id}` additionally
   fetches the title's availability **in parallel** with the TMDB detail under the
   short timeout, degrading to Unknown — authoritative status where the request
   button lives — so detail is never slowed or failed by Seerr. Rejected: blocking
   `/home` on availability (violates invariant 3 — the feed would wait on Seerr);
   a GET `/availability?ids=` (a batch of tens of ids is a body, not a query
   string, and a read-only POST with an explicit model is clearer and unbounded-safe).

7. **Request-as-user (`api/request.py`) + the 403 re-auth ladder.** Session-gated,
   `require_same_origin` (CSRF) since it mutates. Body: `{media_type: Literal,
   tmdb_id: int>=1}`; a TV request asks Seerr for the whole series
   (`seasons: "all"`) at default quality (scope: request the title). Flow: read the
   session's `seerr_cookie` → `create_request`. On `SeerrForbidden`:
   - **Plex user** (`session.plex_token_enc` present): decrypt via `TASTERR_SECRET_KEY`
     → `SeerrAuthClient.login_plex(token)` → persist the fresh `connect.sid` to
     `sessions.seerr_cookie` → **retry once**. A second 403 is treated as genuine
     denial (quota/permission) → generic failure + redirect fallback.
   - **Local user** (no stored token): return `re_auth_required` for the SPA to
     prompt re-login — Seerr's 403 is ambiguous (invalid session *or* quota) and we
     cannot silently re-auth without credentials; SPEC §4.3 accepts this.
   At most one re-auth per request (403 is also genuine permission-denied). Success
   returns the new `Availability` (badge flips) plus the redirect URL. Rejected:
   parsing Seerr's 403 error *string* to distinguish invalid-session from quota
   (brittle across Seerr versions — the spike shows the same body for permission
   denial); re-authing local users with stored credentials (SPEC forbids storing
   them); unlimited reton (403-loop risk).

8. **Redirect fallback built server-side (SPEC §9).** Every `/request` response
   (success and failure) carries `seerr_url = {SEERR_EXTERNAL_URL}/{type}/{tmdbId}`
   when `SEERR_EXTERNAL_URL` is set — assembled server-side from validated config
   and an integer id, **never echoed from input**, so the SPA can always offer
   "Request in Seerr" without ever constructing a Seerr URL client-side. Unset
   external URL → no link (generic failure only). Rejected: the SPA building the
   Seerr URL from data (violates the SECURITY.md external-URL rule); returning the
   internal URL (secret — never leaves the server).

9. **Boundary hardening comes for free.** The availability domain model lives in
   `catalog/availability.py`, so the M2 secret-free guarantees already cover it with
   **no config change**: the import-linter contract lists `tasterr.catalog` (package
   + descendants) and the list-free `tests/test_boundaries.py` flags *any* file
   whose path starts with `catalog/` that imports settings. The Seerr client already
   lives under the `clients/`-only-httpx contract. The `api/{availability,request}`
   routers legitimately import settings for DI (Seerr config, secret key) — held
   secret-free by explicit `response_model`s + the PublicConfig test, as with the
   other routers. A regression test asserts the availability model is caught by the
   boundary test if it ever reaches for settings.

10. **Frontend (`media-browse`).** An `AvailabilityBadge` (Available / Partial /
    Requested-pending/processing / hidden when `not_requested` or `unknown`)
    rendered on `MediaCard`, `Hero`, search results, and the detail modal. A batch
    hydration hook issues `POST /availability` for the visible title ids via
    TanStack Query, keyed by id, after render. The detail modal's M2 where-to-watch
    section is reworked into "where & how to watch": library status + an in-library
    indicator + a **request button** — disabled when `!seerr_configured`
    (from `PublicConfig`) or already available/requested; optimistic pending on
    click; on `re_auth_required` a re-login prompt; on failure the server-provided
    "Request in Seerr" link. All Seerr/library text rendered as text; the request
    button posts through the OpenAPI-generated client (CSRF-safe same-origin).
    Rejected: badges baked into `/home` (decision 6); a bespoke fetch for the
    request (the generated client keeps the typed-end-to-end invariant).

**New dependencies vs. the AGENTS.md slate:** none. M3 reuses `httpx`
(`clients/`), the M2 `cache.py`, and the M1 `cryptography`/Fernet path
(`auth/crypto.py`). No backend or frontend package is added; no `uv.lock` /
`package-lock.json` change beyond the regenerated `api.gen.ts`.

## Security considerations

Walked per docs/SECURITY.md for the areas this change touches (endpoints,
auth/session, outbound HTTP, frontend, DB; **no** new dependencies):

- **New/changed endpoints.** `POST /availability` and `POST /request` are
  session-gated via the shared default-deny dependency; `GET /title` stays
  session-gated. `POST /request` **mutates**, so it carries the `require_same_origin`
  CSRF dependency (SameSite=Lax is the second layer); `POST /availability` is a
  read-only POST (a batch body, no state change) — session-gated, no CSRF needed.
  Inputs are Pydantic-validated: `media_type` a `Literal["movie","tv"]`, `tmdb_id`
  a positive int, the availability batch a length-bounded list — no raw
  passthrough. Every route declares an explicit secret-free `response_model`
  (`Availability` map / a request result with a server-built URL). Errors are
  generic (401/403/`re_auth_required`/generic 502) with no Seerr body, status, or
  internal URL. Broad mutation rate limiting is M6 (proposal Non-goals). Logs
  record outcomes only — never the cookie, the Plex token, or the API key.
- **Auth & session code.** The per-user `seerr_cookie` is read from the session row
  and sent only to Seerr — never to the browser. Silent re-auth decrypts
  `plex_token_enc` (Fernet, `TASTERR_SECRET_KEY`) **in memory**, calls Seerr, and
  writes back only the fresh `connect.sid`; the plaintext token is never logged,
  returned, or persisted. Re-auth runs at most once per request. `re_auth_required`
  is a generic signal that reveals nothing about why. No credentials are stored
  (local users re-login via the existing flow).
- **Outbound HTTP (`clients/seerr.py`).** The base URL is `SEERR_INTERNAL_URL` from
  validated settings — never user input (SSRF); path segments are a constrained
  `type` literal and an integer id. Availability sends the global `X-Api-Key`;
  requests send only the user cookie — the two are never crossed (decision 2).
  Every call has a short timeout; reads are not retried (no storm). Browser headers
  are not forwarded upstream and Seerr response bodies/headers are not returned
  downstream — Seerr JSON is parsed into typed models with unknown fields dropped
  and mapped to the `Availability` enum.
- **Frontend.** No `dangerouslySetInnerHTML`; availability is a typed enum and any
  Seerr/library text renders as text. The only external URL — the "Request in
  Seerr" fallback — comes from the BFF, built server-side from `SEERR_EXTERNAL_URL`
  and an integer id, never assembled client-side or echoed from input (SPEC §9). No
  tokens or secrets touch `localStorage`/`sessionStorage`; the session stays in the
  HttpOnly cookie.
- **Database & migrations.** No new tables or columns — `seerr_cookie` and
  `plex_token_enc` exist since M1 (signals/profiles are M4). Silent re-auth
  `UPDATE`s `sessions.seerr_cookie` via SQLAlchemy expressions only (no string
  SQL). The cookie stays plaintext by the explicit SPEC §5 / docs/IGNORED.md
  decision (sent verbatim every call; host-file access is outside the threat
  model). No migration ships.
- **Invariants.** Secrets stay server-side — `SEERR_API_KEY`, `SEERR_INTERNAL_URL`,
  the per-user cookie, and the Plex token live only in the client/session layer;
  the `Availability` model and the `/availability`,`/request` bodies carry only
  public status + a public external URL (import-linter + explicit `response_model`s
  + the PublicConfig test). All outbound Seerr traffic remains inside `clients/`.
  The **Seerr-degrades-never-blocks** invariant is now exercised for real: reads
  degrade to Unknown, requests to a generic failure + redirect, and browsing keeps
  working with Seerr unconfigured or down.

## Risks / Trade-offs

- [A lapsed Plex Seerr session makes the first request 403 on every call until
  refreshed] → silent re-auth refreshes and persists the cookie on the first 403,
  so subsequent requests reuse it; the cost is one extra Seerr round-trip on the
  boundary request.
- [Seerr returns 403 for both invalid-session and quota/permission denial] →
  Plex: one re-auth then treat as genuine denial; local: `re_auth_required` then a
  generic failure if it recurs. A local user at quota may be told to re-login once
  unnecessarily — accepted by SPEC §4.3; the redirect fallback still lets them act.
- [Short-TTL availability cache lags a just-made request in *other* views] → the
  requesting view updates optimistically from the request's authoritative status;
  ≤ TTL staleness elsewhere is cosmetic at household scale (no invalidation, by
  decision 5).
- [Rail hydration fans out ~40 availability reads on a cold cache] → single-flight
  dedupes concurrent misses, bounded concurrency caps parallelism, the short TTL
  keeps steady-state cheap, and each failure degrades independently to Unknown.
- [Seerr's delete `204` races its async approve/dispatch (spike finding)] → M3
  never deletes in product code; the live contract test cleans up but does not
  treat the `204` as authoritative mid-dispatch (documented in the test).
- [TV "request all seasons" over-requests vs. a single wanted season] → M3 scope is
  request-the-title; per-season selection is an explicit Non-goal, and Seerr's own
  UI remains the path for granular control (surfaced by the redirect fallback).

## Migration Plan

No database migration — `seerr_cookie` and `plex_token_enc` exist since M1 and no
schema changes. No new dependencies; `api.gen.ts` is regenerated after the
endpoints settle. Deploy is the same single container as M2. Rollback is
`git revert` — silent re-auth only rewrites a session's own `seerr_cookie` (a
value a re-login would refresh anyway), so there is no data to unwind.

## Open Questions

None blocking. The Seerr library rail is deferred with rationale (proposal
Non-goals). Distinguishing Seerr's ambiguous 403 more precisely than the SPEC §4.3
ladder is intentionally out of scope (brittle body-string parsing). The optional
stored-Plex-token live re-auth test needs an operator-supplied
`TASTERR_LIVE_PLEX_TOKEN` (docs/DEFERRED.md) and runs outside `just check`.
