# Design: m2-browse

## Context

M1 left `catalog/`, `rails/`, and `recommend/` as empty boundary-tested packages,
`clients/` holding only `plex.py`/`seerr.py` (auth), and an authenticated SPA shell
that renders the user's name and `/health`. `settings.py` already carries an
optional `TMDB_API_KEY` (SecretStr) and the `tmdb_configured` flag; the shared
`httpx.AsyncClient` (with a no-store cookie jar) and the typed
`UpstreamUnavailable`/`UpstreamRejected` hierarchy exist. The import-linter
contract already confines `httpx` to `tasterr.clients`.

This change turns SPEC §6–§10 (BFF browse endpoints, rails system, TMDB
resilience/caching) and the SPEC §13 M2 milestone ("usable read-only browser")
into code. The reference implementation (browserr `src/server/tmdb`,
`src/server/rails`, `src/server/region.ts`) is consulted for the discover/detail
query shapes, normalization, and rail composition — not ported. Personalization
(M4), Seerr availability/requests (M3), and the admin settings that would make
region/services/toggles configurable (M5) are deliberately out of scope; the code
introduced here is shaped so those slot into existing seams.

## Goals / Non-Goals

**Goals:**

- A TMDB client establishing the house style for a *read* client: typed models,
  timeouts, bounded retry, cache-wrapped, secrets server-side, behind the boundary.
- An in-process TTL + stale-on-error + single-flight cache (SPEC §10) reused by
  every TMDB read.
- Pure normalization from TMDB JSON to typed, secret-free domain models that
  unit-test with no network.
- A rails registry + composer whose provider interface is the extension seam for
  M4 (personalized providers) and M5 (admin toggles), shipping the non-personalized
  providers now.
- Session-gated `/home`, `/rails`, `/title`, `/search` that degrade (unconfigured
  → 503, upstream-down → stale-or-502) and never leak upstream detail.
- A routed SPA browse experience (hero, rails, infinite scroll, detail modal,
  search) that is responsive, XSS-safe, and reduced-motion aware.

**Non-Goals:**

- Availability badges, request-as-user, the Seerr library rail (M3).
- Personalized/because-you-watched rails, signals, recommendations, explain,
  reset (M4).
- Admin settings GUI, configurable region/services, per-service rails, rail
  toggles, `/regions`+`/services`+`connection-test` endpoints (M5).
- The asyncio background refresher warmup (SPEC §10) — deferred; TTL +
  stale-on-error carry the resilience contract for M2.
- TV episode drill-down, provider click-through / Plex deep links, refresh-variation
  reshuffle, the full a11y/10-foot pass (M5), Playwright E2E (M6).

## Decisions

1. **Two capabilities: catalog engine vs. browse product.** `media-catalog`
   (client + normalization + cache + region + degradation) is the reusable
   server-side engine; `media-browse` (the `/home`,`/rails`,`/title`,`/search`
   endpoints + the SPA) is the product on top. The split mirrors SPEC's own
   framing (§8/§10 client+cache vs. §6/§7 endpoints+rails), keeps the stable infra
   invariants (stale-on-error, secret-free models) apart from the fast-evolving
   UX that M3/M4 rewrite, and serves the "re-orient in an hour after six months"
   bar. Rejected: one broad `media-browse` capability (the user-auth precedent) —
   simpler file count, but muddies which requirements M3/M4 will churn.

2. **TMDB client style (`clients/tmdb.py`).** Reuses the lifespan
   `app.state.http` client. Auth via the `api_key` query parameter (SPEC names
   only `TMDB_API_KEY`; no bearer-token path). Every call has an explicit timeout;
   `429`/`5xx` retry with capped exponential backoff honoring `Retry-After`, then
   surface `UpstreamUnavailable`. Responses parse into Pydantic models
   (`extra="ignore"`); a typed `CatalogNotConfigured` signals a missing key.
   `api/` maps these to 502/503 — upstream bodies and URLs never reach the browser.
   The one shared client's no-store cookie jar is already correct for TMDB (no
   cookies). Rejected: a second httpx client (needless), forwarding browser
   headers upstream (SSRF/leak surface).

3. **Cache = `cachetools` bounded store + our stale-on-error/single-flight layer.**
   `cache.py` exposes `async cached(key, CacheOpts, loader)`. Entries hold
   `(value, fetched_at)` in a `cachetools.LRUCache` (bounds memory via LRU
   eviction); freshness, the stale window, and an `asyncio` single-flight lock per
   key are ours. Within TTL → return cached; past TTL → refresh, and on refresh
   failure serve the stale value if inside its stale window, else raise.
   Per-endpoint-class `CacheOpts` constants (regions/genres long; discover/trending
   medium; detail short-ish; search brief), keyed by path + sorted params
   excluding `api_key`. **Why `cachetools` over hand-rolling:** SPEC §2 names it,
   and analysis showed the choice is a wash — `TTLCache`'s auto-eviction actively
   conflicts with stale-on-error (we must *retain* expired entries), so only its
   bounded-LRU store is useful, and single-flight is custom either way; a wash is
   not grounds to deviate from a defined SPEC choice, so we take the library for
   correct bounded eviction. Rejected: hand-rolled `OrderedDict` LRU (marginal,
   deviates from SPEC); a plain `TTLCache` (cannot serve stale).

4. **Default region is a code constant.** M2 has no `settings` table (M5 owns it,
   per the m1 design). A single documented `DEFAULT_REGION` constant feeds
   certification/watch-provider reads and is threaded into discover's
   `watch_region` (inert until service filters land at M5).
   Rejected: a `TASTERR_REGION` env var — SPEC §9 puts region in the DB-backed
   admin-config half, not env; introducing an env knob now would contradict the
   frozen split and be thrown away at M5. Trade-off: the household may not be in
   the default region until M5 — a one-line constant to change meanwhile, and it
   only skews region-dependent data (certifications, where-to-watch), not browsing.

5. **Rails registry + composer.** A provider is `id`, `title`, `kind`, and async
   `fetch(ctx) -> list[MediaSummary]` (the items for its rail); a `RailContext`
   carries the catalog service. The composer owns the Rail assembly: it fans
   providers out with bounded concurrency, catches per-provider errors to an empty
   list (one failure never blanks the feed), dedupes title ids across the ordered
   rails, drops rails under a minimum item count, and wraps the survivors into
   `Rail`s. (The §7 "provider returns a Rail" seam is realized as "provider returns
   items, composer builds the Rail" — simpler, and the composer centralizes dedupe
   and min-size.) `/home` builds the hero (from the trending/top pool)
   plus the first providers; `/rails?cursor=` walks a bounded catalogue of extended
   providers (top-rated, decades, extra genres, movie+TV), integer-cursor
   paginated. M2 wires every provider on (no toggle store yet); `userId` is
   threaded through but drives no scoring. This is the literal SPEC §7 interface —
   M4 registers personalized providers and M5 filters by admin toggles without
   touching the composer. Rejected: a hardcoded feed function (throws away the
   §7 seam M4/M5 need immediately).

6. **Detail = one TMDB call, normalized.** `getDetail` uses
   `append_to_response=videos,images,credits,keywords,recommendations,similar,
   watch/providers` plus `release_dates` (movie) / `content_ratings` (tv), then
   normalizes to `MediaDetail` (trailer pick, logo pick, ranked cast/key-crew,
   region certification, season summaries, region where-to-watch,
   similar/recommended summaries). Where-to-watch renders **provider logos/names
   only** — the outbound JustWatch/provider link is deferred with Plex deep-links
   (M2 avoids the external-URL surface). Episode drill-down is out of scope: season
   summaries come free in the append and the SPEC §6 route table has no season
   endpoint. Rejected: multiple round-trips per detail (append is one request);
   surfacing the provider click-through now (extra external-link hardening for
   little M2 value).

7. **Browse endpoints.** All session-gated via the shared `require_session`
   (default-deny). Inputs are constrained: `type` is `Literal["movie","tv"]`, `id`
   a positive int, `q` trimmed and length-bounded (empty → empty, no upstream
   call), `cursor` a bounded int. Every route declares an explicit secret-free
   `response_model`. No mutations ship in M2, so no CSRF/rate-limit is added here
   (reads; the broad limiter is M6). Unconfigured TMDB → 503; upstream error with
   no cache → generic 502; `/home` degrades to whatever rails succeeded.

8. **Frontend: React Router + TanStack Query.** React Router replaces the M1
   auth render-switch: routes for Home (`/`), Search (`/search`), and a
   deep-linkable Title detail **modal** (`/title/:type/:id`) rendered over the
   browse view. Data flows through the OpenAPI-generated client via TanStack Query;
   the home infinite scroll uses `useInfiniteQuery` over the `/rails` cursor.
   Components: Hero, Rail (CSS scroll-snap), MediaCard, DetailModal (closable via
   Escape and a close control, focus-on-open + restore; the full focus-trap + inert
   background is the M5 a11y pass), Navbar, SearchBar, skeleton loaders. Images build client-side from title paths
   via a small `lib/images.ts` helper over the well-known, non-secret TMDB image
   base + a curated size set (no backend image config, no `/configuration` call).
   CSS-first animation throughout, `prefers-reduced-motion` honored; TMDB text is
   always rendered as text. The full a11y/10-foot pass is M5; M2 keeps rails
   keyboard-scrollable and the modal Escape/close-able with focus-on-open. Rejected: TanStack Router
   (type-safe but heavier; route-param typing is a thin surface next to the
   OpenAPI-typed API client, which already satisfies the typed-end-to-end
   invariant), hand-rolled routing (a false economy as M5 adds routes),
   backend-built image URLs (loses responsive/10-foot sizing).

9. **Boundary + gate hardening (both M2 gate-hardening items).** A third
   import-linter contract forbids the catalog/rails domain-model modules
   (`tasterr.catalog`, `tasterr.rails`) from importing `tasterr.settings` —
   mechanizing SPEC §11's secret-free-model invariant for the domain models that
   multiply in M2. (`api/` routers legitimately import settings for DI; their
   client-facing models stay secret-free via explicit `response_model`s + the
   PublicConfig test.) And `just check` gains an OpenAPI **type-freshness** step:
   regenerate the client types and `git diff --exit-code`, failing if the committed
   `api.gen.ts` drifted from the schema. Both land in the `dev-tooling` spec.

**New dependencies vs. the AGENTS.md slate:**

| Dependency | Kind | Justification |
|---|---|---|
| `cachetools` | backend runtime | Named in SPEC §2 for the in-process TTL cache; pure-Python, maintained, multi-arch wheels. Used for its bounded-LRU store beneath our stale-on-error + single-flight layer (decision 3). Alternatives (hand-rolled LRU) are a wash and deviate from the blueprint. |
| `react-router-dom` | frontend runtime | SPA URL routing was explicitly deferred from M1 to "M2's real navigation needs"; M2 introduces Home/Search/deep-linkable detail. The ubiquitous, well-maintained standard; smaller mental-model + ecosystem cost than TanStack Router for ~5 routes (decision 8). |

## Security considerations

Walked per docs/SECURITY.md for the areas this change touches (endpoints, outbound
HTTP, frontend, dependencies; **no** DB/auth changes):

- **New/changed endpoints.** `/home`, `/rails`, `/title/{type}/{id}`, `/search`
  are all session-gated via the shared default-deny dependency — no new
  unauthenticated surface. Inputs are Pydantic/path/query-validated (`type`
  literal, positive-int `id`, length-bounded `q`, bounded `cursor`) — no raw
  passthrough. Every route declares an explicit `response_model` that is a catalog/rails domain
  shape — the modules the import-linter contract bars from importing settings — so
  no secret can reach a response body. Errors are generic
  (503 unconfigured, 502 upstream, 404 unknown title) with no stack traces,
  internal URLs, or upstream bodies. No mutations → no CSRF/rate-limit needed here
  (reads only; broad limiter is M6). Logs record outcomes only — the TMDB key is
  never logged.
- **Outbound HTTP (`clients/tmdb.py`).** The base URL is a constant; the API key
  comes from validated settings — never user input (SSRF). Path params reach TMDB
  only as a constrained `type` segment and an integer `id`; the search term is sent
  as the TMDB `query` parameter (URL-encoded, non-structural). Every call has a
  timeout; retries are bounded. Browser headers are not forwarded upstream; TMDB
  JSON is untrusted — parsed into typed models with unknown fields dropped, and its
  text is rendered as text downstream.
- **Frontend.** No `dangerouslySetInnerHTML`; all TMDB text renders as text. The
  only embedded external resource is the trailer: a YouTube `embed` iframe built
  from a video **key** whose charset is validated (`[A-Za-z0-9_-]`) during
  normalization, so a malformed key can't shape the URL. Where-to-watch shows
  provider logos/names with no outbound link in M2. No tokens or secrets touch
  `localStorage`/`sessionStorage`; the session stays in the HttpOnly cookie.
- **Dependencies & build.** `cachetools` and `react-router-dom` justified above;
  `uv.lock` and `package-lock.json` are committed with the change. No Dockerfile
  changes.
- **Invariants.** Secrets stay server-side — the TMDB key lives only in
  `clients/tmdb.py` via settings; the catalog/rails domain models are secret-free
  (now import-linter-enforced) and the `/home`,`/rails`,`/title`,`/search` response
  payloads carry only public catalog data (explicit `response_model`s + the
  PublicConfig test). All outbound HTTP remains inside `clients/` under the
  existing contract. The Seerr-down invariant is not exercised in M2 (no Seerr
  calls); the analogous TMDB-down path degrades via stale-on-error and per-rail
  omission, and cached content keeps browsing alive.
- **Database & migrations.** None — the cache is in-process; no tables or columns
  are added (`title_features`/`profiles` are M4). No migration ships.

## Risks / Trade-offs

- [TMDB rate limits under rail fan-out] → bounded per-request concurrency, the
  shared cache, single-flight (no thundering herd), and `Retry-After`-honoring
  backoff; household traffic is low.
- [Cold-cache latency on the first `/home` after boot (many TMDB calls)] → parallel
  provider fetch + per-rail degrade so partial results render; the background
  refresher that would pre-warm is deferred, and stale-on-error keeps steady-state
  fast. Acceptable at household scale; revisit if real latency bites.
- [Default region may not match the household until M5] → documented single-line
  constant; skews only region-dependent data (certifications, where-to-watch),
  never core browsing.
- [Cross-rail dedupe can shrink a later rail below the minimum] → dedupe first,
  then drop under-filled rails, so a rail is either well-formed or absent — never a
  stub.
- [stale-on-error serves old data] → bounded per-class stale window; acceptable for
  discovery (non-transactional) and strictly better than a blank feed.
- [`react-router-dom` adds a dependency + bundle weight] → justified and small; the
  ubiquitous choice keeps the SPA legible to a solo maintainer.
- [No availability badges yet may read as "missing" in the UI] → intentional M2
  scope; cards/detail leave layout room and M3 fills it.

## Migration Plan

No database migration — the cache is in-process and no schema changes. The new
backend/frontend dependencies land in `uv.lock` / `package-lock.json`;
`api.gen.ts` is regenerated after the routes settle. Deploy is the same single
container as M1. Rollback is `git revert` (no data or schema to unwind).

## Open Questions

None blocking. The default region is a documented constant pending M5's settings
GUI; provider click-through/Plex deep links and TV episode drill-down are explicit
fast-follows recorded in the proposal's Non-goals.
