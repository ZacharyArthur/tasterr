# Proposal: m3-seerr

## Why

M2 delivered a usable read-only browser, but every card and detail view leaves a
deliberate hole where library status should be and offers no way to act on a
title. This change implements **PRD/SPEC milestone M3 (Seerr integration)** —
live availability badges, request-as-user through each member's own Seerr
session, and the degradation paths that keep browsing alive when Seerr is down.
It is the milestone that makes Tasterr answer *"is this already here, and if not,
can I get it?"* — turning the browser into the household's request front-end and
exercising, for the first time, the founding invariant that **Seerr outages
degrade rather than block** (M2 built the seam but never made a Seerr call).

## What Changes

- **Seerr read client** (`clients/seerr.py`): the existing auth-only Seerr module
  gains availability reads keyed by TMDB id — `GET {SEERR}/api/v1/{type}/{tmdbId}`
  → `mediaInfo.status` (with per-season status for TV), authenticated by the
  **global `SEERR_API_KEY`** (server setting) because availability is not
  user-attributed. A short timeout, no retry storm, and a typed
  library-status result that distinguishes *known* statuses (available, partially
  available, processing, pending, not-in-library) from **Unknown** (Seerr
  unreachable). Contract validated against the pinned Seerr 3.3.0.
- **Availability engine** (`catalog/availability.py`): pure mapping of Seerr's
  numeric status → a typed, secret-free `Availability` domain model; a short-TTL,
  single-flight cache (reusing M2's `cache.py`) so rail hydration doesn't hammer
  Seerr, with **Seerr errors resolving to Unknown, never stale** (SPEC §10 — Seerr
  degrades to Unknown, unlike TMDB's stale-on-error).
- **Batch availability endpoint** (`api/availability.py`): session-gated
  `POST /availability` taking a bounded list of `{type, id}` and returning a
  status per title, so the SPA hydrates badges *after* the feed renders — the feed
  never blocks on Seerr.
- **Detail-embedded availability**: `GET /title/{type}/{id}` now includes the
  title's availability, fetched in parallel with the TMDB detail under a short
  timeout and degrading to Unknown — authoritative status at the point where the
  request button lives.
- **Request-as-user** (`clients/seerr.py` + `api/request.py`): session-gated,
  CSRF-origin-checked `POST /request` that proxies `POST {SEERR}/api/v1/request`
  using the **per-user Seerr session cookie** stored on the Tasterr session row,
  so the request lands in Seerr as *that* member subject to *their* quota. On
  Seerr `403` (its invalid-session signal, per the auth spike): **Plex users**
  re-auth silently via the stored Fernet-encrypted Plex token → retry **once**;
  **local users** get a `re_auth_required` signal for the SPA to prompt re-login.
  Never more than one re-auth (403 is also genuine permission-denied). Every
  response carries a **server-built Seerr external redirect** (`SEERR_EXTERNAL_URL`)
  as a manual fallback.
- **Degradation paths** (the M3 headline): Seerr **unconfigured** →
  `seerr_configured: false` already in `PublicConfig`, so the SPA disables request
  affordances up front and badges read Unknown; Seerr **down** → availability
  Unknown, request returns a generic failure plus the redirect fallback; browsing
  is never blocked. Availability reads use the global key so badges survive a
  lapsed *user* session; only requests need the per-user cookie.
- **SPA availability + request UX** (`media-browse`): an `AvailabilityBadge` on
  cards, hero, search results, and detail; batch badge hydration via TanStack
  Query; the detail modal's where-to-watch section reworked into a "where & how to
  watch" block that folds in library status, an in-library indicator, and a
  **request button** (disabled when unconfigured/already available; optimistic
  pending state; re-login prompt on `re_auth_required`; "Request in Seerr" link on
  failure). Seerr/library text rendered as text; the redirect URL only ever comes
  from the BFF.
- **Live Seerr contract coverage**: each new capability specifies its own
  live-marked contract test (excluded from `just check`) against the pinned Seerr
  3.3.0 — `media-availability` the availability read shape,
  `media-requests` request-as-user (create + attribution + cleanup, honoring the
  spike's caveat not to trust the delete `204` mid-dispatch) and the 403 →
  stored-Plex-token silent re-auth path. No boundary-tooling change is needed: the
  availability domain model lives under `catalog/`, where the existing secret-free
  import-linter contract and the list-free `test_boundaries.py` already forbid it
  from importing settings.

## Capabilities

### New Capabilities

- `media-availability`: the server-side library-status engine — Seerr availability
  reads behind the client boundary (global API key, short timeout), the typed
  secret-free `Availability` model, the short-TTL single-flight cache with
  Seerr-down→Unknown degradation, the batch `POST /availability` endpoint, and the
  availability embedded in title detail. Consumed by `media-browse` now and by M4's
  recommendation availability-boost later.
- `media-requests`: request-as-user — `POST /request` proxied through the stored
  per-user Seerr session, silent re-auth for Plex users via the encrypted stored
  token, `re_auth_required` for local users, the server-built external redirect
  fallback, and the CSRF/degradation posture for the mutation.

### Modified Capabilities

- `media-browse`: the "Title detail" requirement drops its "availability out of
  scope" clause and now returns availability; the routed SPA browse experience
  gains availability badges across cards/hero/search/detail and the request
  affordance in a reworked where-to-watch section.

## Impact

- **Backend**: `clients/seerr.py` gains availability + request methods (still the
  only Seerr caller); new `catalog/availability.py` (mapping + cache) and
  `api/{availability,request}.py` wired into the router. Silent re-auth reads
  `sessions.plex_token_enc` (Fernet, `auth/crypto.py`) and writes a refreshed
  `sessions.seerr_cookie`. `settings.py`/`PublicConfig` already expose
  `seerr_configured`. **No migration** — `seerr_cookie` and `plex_token_enc`
  columns exist since M1; no new tables (signals/profiles are M4).
- **Frontend**: new `AvailabilityBadge` + request UI in the detail modal, batch
  hydration query keys/hooks in `lib/`, reworked where-to-watch; `api.gen.ts`
  regenerated for the new/changed endpoints.
- **New dependencies**: none — reuses `httpx`, `cache.py`, and the M1
  `cryptography`/Fernet path already in the tree.
- **Tests**: status mapping (pure), availability cache (TTL/single-flight/
  error→Unknown), Seerr client contract tests on `httpx.MockTransport`
  (availability parse, 404→not-in-library, 5xx→Unknown, request 201, 403→re-auth→
  retry, local-user 403→`re_auth_required`), endpoint tests (session gating, CSRF
  on `/request`, batch shape, unconfigured/down degradation, secret-free bodies,
  redirect built server-side), a regression that the availability model is caught
  by the existing secret-free boundary test, and Vitest for badges, batch
  hydration, and the request button states.

## Non-goals

- **A Seerr-sourced "in your library" home rail** — considered and **deferred**:
  SPEC §13 scopes M3 to badges + request-as-user + degradation, KISS favors the
  smaller surface, and a Seerr discovery rail belongs with its siblings — M4's
  personalized/availability-boosted rails and M5's admin service-filtered rails.
  M2's TMDB new-releases rail already covers "what's new." (browserr's
  `/api/v1/media?filter=available` rail is the reference for when it lands.)
- **Personalized rails, the recommendation availability-boost, signals from
  requests, cold-start seed from Seerr request history, explain/reset** (M4) — a
  request records nothing in a `signals` table here; `media-availability` is shaped
  so M4's scorer can read it, but M3 adds no scoring and no `signals`/`profiles`
  tables.
- **Admin settings GUI, `connection-test`, configurable region/services,
  per-service rails** (M5) — availability uses the M2 default region; Seerr
  configuration stays env-only.
- **Broad mutation rate limiting** (M6) — `/request` gets the CSRF origin check
  now; the app-wide token-bucket limiter on mutations is SPEC §13's M6 pass. Auth
  endpoints keep their M1 tight limiter.
- **4K request tiers, season/episode-level request selection, editing or deleting
  requests, request-history views** — M3 requests a whole movie or TV title at the
  default quality; Seerr owns quotas, approval, and management. Per-season request
  selection and history are later polish, not the "request lands attributed"
  milestone bar.
- **Background availability pre-warming** (SPEC §10 refresher) — deferred with the
  M2 refresher; the short-TTL cache + single-flight carry M3 at household scale.
