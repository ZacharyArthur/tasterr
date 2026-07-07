# Proposal: m2-browse

## Why

M1 delivered identity but nothing to look at: a logged-in user lands on a shell
that only prints their name and `/health`. This change implements **PRD/SPEC
milestone M2 (Browse)** — the TMDB client, catalog normalization, a hero + rails
home feed, title detail, and search — turning Tasterr into a **usable read-only
browser**. It is the substrate every later milestone decorates: M3 hangs
availability badges and requests on these cards and detail views, M4 personalizes
the rails, M5 makes the region/services/toggles behind them admin-configurable.

## What Changes

- **First TMDB access** (`clients/tmdb.py`): the second outbound client, behind
  the existing import-linter boundary — typed responses, explicit timeouts,
  bounded retry with backoff (honoring `Retry-After`), the global `TMDB_API_KEY`
  attached server-side only. Covers discover, trending, multi-search, detail
  (via `append_to_response`), genres, and title watch-providers.
- **In-process cache with stale-on-error** (`cache.py`): per-endpoint-class TTLs
  over a bounded store, an async single-flight lock deduping concurrent misses,
  and last-good-value service when TMDB errors — the SPEC §10 resilience contract.
- **Catalog normalization** (`catalog/`): TMDB JSON → typed, **secret-free**
  domain models (summaries, detail, hero slides, rails, people, videos, seasons,
  watch-providers), plus the pure pick/rank helpers (trailer, logo, cast/crew,
  certification). Unit-tested with no network.
- **Rails registry + composer** (`rails/`): a provider interface
  (`id`, `title`, `kind`, async `fetch(ctx) -> list[MediaSummary]`) and a composer that
  fans out enabled providers in parallel, degrades per-provider to nothing on error,
  dedupes titles across rails, drops under-filled rails, and paginates additional
  rails for infinite scroll. M2 ships the **non-personalized** providers only
  (trending, popular, recently-added, genre, top-rated, by-decade); the
  interface is the seam M4 (personalized) and M5 (toggles) extend.
- **Browse API** (`api/home.py`, `api/title.py`, `api/search.py`): session-gated
  `GET /home`, `GET /rails?cursor=`, `GET /title/{type}/{id}`, `GET /search?q=`;
  Pydantic-validated inputs, explicit secret-free `response_model`s, generic
  errors, and TMDB-unconfigured → 503 / TMDB-down → stale-or-generic-502
  degradation that never blanks the feed.
- **Default region as a code constant** — M2 has no settings table (M5 owns it),
  so discover/trending run against a documented default region; M5 makes it
  configurable and adds the per-service rails that need admin service selection.
- **SPA browse experience**: React Router replaces the M1 auth render-switch;
  a routed shell (Navbar + search) with a Home route (hero + horizontal rails +
  infinite scroll), a deep-linkable Title detail **modal**
  (`/title/:type/:id` — backdrop, logo, trailer, cast, seasons, where-to-watch,
  similar/recommended), and a Search route. CSS-first animation, responsive
  images, `prefers-reduced-motion` honored, TMDB text rendered as text.
- **Boundary + gate hardening** (both M2 gate-hardening items): an
  import-linter contract that the catalog/rails domain models never import secret
  settings, and an OpenAPI **type-freshness** check wired into `just check` so the
  generated client can't silently drift from the schema.

## Capabilities

### New Capabilities

- `media-catalog`: the server-side catalog engine — outbound TMDB access behind
  the client boundary, normalization into typed secret-free domain models, the
  in-process TTL + stale-on-error + single-flight cache, the default region, and
  TMDB-unconfigured/degraded behavior. Consumed by `media-browse`; reused by M3/M4.
- `media-browse`: the browse product built on the catalog — the hero + rails home
  feed and its infinite scroll, title detail, and multi-search endpoints, plus the
  routed SPA browse experience (hero, rails, cards, detail modal, search,
  responsive images, reduced motion).

### Modified Capabilities

- `app-shell`: the auth-gated authenticated shell evolves from the M1
  health-display placeholder into the routed browse application (React Router);
  the unauthenticated → login behavior is unchanged.
- `dev-tooling`: the mechanically-enforced boundary invariants gain a contract
  that the catalog/rails domain models never import secret settings; the OpenAPI
  type-generation requirement gains a gate check that fails when the committed
  generated types are stale versus the current schema.

## Impact

- **Backend**: new `clients/tmdb.py`, `cache.py`, `catalog/` (models,
  normalization, helpers), `rails/` (registry, composer, providers), and
  `api/{home,title,search}.py` wired into the API router. `settings.py`,
  `auth/`, and `db/` are untouched — **no migration** (the cache is in-process;
  `title_features`/`profiles` tables are M4).
- **Frontend**: `react-router-dom`; new `routes/` (Home, Search, TitleDetail) and
  `components/` (Hero, Rail, MediaCard, DetailModal, Navbar, SearchBar,
  skeletons); `lib/` image-URL helper, query keys/hooks; `api.gen.ts` regenerated.
- **New dependencies**: `cachetools` (backend; named in SPEC §2) and
  `react-router-dom` (frontend; SPA routing deferred from M1). Justified in
  design.md; `uv.lock` + `package-lock.json` committed with the change.
- **Tests**: normalization + pick/rank helpers (pure), cache TTL/stale/
  single-flight, TMDB client contract tests on `httpx.MockTransport` fixtures,
  rails composer (degrade/dedupe/under-fill/pagination), endpoint tests with a
  faked catalog (session gating, validation, 503/502 degradation, secret-free
  bodies), the new import-linter contract, and Vitest coverage of routing, rails,
  detail modal, and search.

## Non-goals

- **Availability badges, request-as-user, the Seerr library rail** (M3) — M2
  makes no per-user Seerr calls; cards and detail leave room for the badge but
  render without it.
- **Personalized / "because you watched" rails, signals, recommendations,
  reset, explain** (M4) — the composer and rail interface are personalization-
  ready, but M2 rails are non-personalized and `userId` drives no scoring.
- **Admin settings GUI, region/service selection, per-service rails, rail
  toggles, `connection-test`, `/regions` + `/services` endpoints** (M5) — region
  is a code default and all rails are enabled.
- **Background refresher warmup** (SPEC §10) — deferred; TTL + stale-on-error
  deliver the resilience invariant for M2, and re-warming pays off once real
  cold-cache latency or M5's shared pools justify it.
- **TV episode drill-down endpoint** and **provider click-through / Plex deep
  links** — detail shows season summaries and provider logos; both drill-downs
  are explicit fast-follows, and neither is in the SPEC §6 route table.
- **Refresh-variation (seeded per-refresh reshuffle), full a11y/10-foot pass
  (M5), Playwright E2E (M6).**
