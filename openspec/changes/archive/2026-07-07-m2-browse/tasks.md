# Tasks: m2-browse

## 1. Foundations — dependencies, cache, TMDB client

- [x] 1.1 Add `cachetools` (backend `uv add`) and `react-router-dom` (frontend
      `npm i`); `uv.lock` + `package-lock.json` committed
- [x] 1.2 `cache.py`: async `cached(key, CacheOpts, loader)` over a bounded
      `cachetools.LRUCache` — per-class TTL + stale window, per-key asyncio
      single-flight; tests: fresh hit skips the loader, post-TTL refresh, stale
      value served on loader failure within the stale window, cold miss + failure
      raises, concurrent misses collapse to one loader call
- [x] 1.3 `clients/tmdb.py`: TMDB fetch via the shared `app.state.http` client —
      `api_key` query auth, explicit timeout, bounded `Retry-After`-honoring
      backoff on 429/5xx, typed TMDB models (`extra="ignore"`), cache-wrapped,
      typed `CatalogNotConfigured`; methods `discover`, `trending`, `multi_search`,
      `detail` (append_to_response), `genres`; `httpx.MockTransport` contract
      tests: 200 parse, 429→retry→success, persistent 5xx→`UpstreamUnavailable`
      (no upstream body leaked), unset key→`CatalogNotConfigured`

## 2. Catalog — domain models, normalization, service

- [x] 2.1 `catalog/models.py`: typed secret-free domain models (MediaSummary,
      MediaDetail, HeroSlide, Rail, Person, Video, SeasonSummary, WatchProviders,
      Genre) — no import of `tasterr.settings` (enforced in 6.1)
- [x] 2.2 `catalog/normalize.py`: pure TMDB→domain normalizers + pick/rank helpers
      — summary (type + year resolution, person dropped), trailer pick (YouTube
      key charset validated), logo pick, ranked cast + key crew, region
      certification, season summaries, region watch-providers; unit tests per
      helper on fixtures, incl. person-dropped and malformed-key-dropped
- [x] 2.3 `catalog/service.py` + `DEFAULT_REGION`: façade composing client +
      normalize into domain ops (`discover`, `trending`, `search`, `detail`,
      `genres`) against the default region; tests with a faked client: ops return
      domain models, empty/whitespace search short-circuits with no client call,
      `CatalogNotConfigured` propagates

## 3. Rails — registry, composer, providers

- [x] 3.1 `rails/registry.py`: provider interface (`id`, `title`, `kind`, async
      `fetch(ctx) -> list[MediaSummary]`) + `RailContext` (catalog service, region);
      registration of the home and extended provider sets
- [x] 3.2 Non-personalized providers — home set (trending, popular,
      recently-added, genre) and extended set (top-rated movie/tv, by-decade,
      further genres), plus a hero builder that enriches the trending/top pool with
      per-slide logo/trailer detail; unit tests per provider against a faked
      catalog service
- [x] 3.3 `rails/composer.py`: `build_home` (bounded-concurrency fan-out,
      per-provider degrade-to-empty, cross-rail title de-dupe, drop under-filled
      rails, hero) and `build_extra_rails(cursor)` (bounded catalogue, integer
      cursor, done signal); tests: a failing provider still yields the others,
      titles de-duped across rails, under-filled rail dropped, paging advances then
      completes

## 4. Browse API

- [x] 4.1 `api/home.py`: session-gated `GET /home` (hero + first rails) and
      `GET /rails?cursor=` (cursor-paginated) with explicit secret-free response
      models; tests: 401 unauthenticated, 200 shape, degraded feed when a provider
      errors, cursor paging then done
- [x] 4.2 `api/title.py`: session-gated `GET /title/{type}/{id}` (`type`
      `Literal["movie","tv"]`, positive int `id`) returning `MediaDetail`; tests:
      401 unauthenticated, movie + tv detail shape, invalid type → validation
      error, unknown id → generic 404 with no upstream detail
- [x] 4.3 `api/search.py`: session-gated `GET /search?q=` (trimmed, length-bounded;
      empty → empty result with no client call); tests: 401 unauthenticated,
      results drop person hits, empty query short-circuits
- [x] 4.4 Degradation + router wiring: TMDB-unconfigured → 503, upstream error with
      no cache → generic 502; register the browse routers in the API app; tests:
      503 when unconfigured, generic 502 on upstream failure, `/api/v1/health`
      still 200 while TMDB is down

## 5. Frontend — routing & browse UI

- [x] 5.1 Regenerate `api.gen.ts` (`just types`) once the browse routes settle;
      commit the generated file
- [x] 5.2 Router shell: `react-router-dom` replacing the M1 auth render-switch —
      Navbar (display name, logout, search entry) hosting Home/Search/Title routes,
      auth-gating preserved; Vitest: unauthenticated → login, authenticated →
      routed shell, logout invalidates auth state
- [x] 5.3 `lib/images.ts` (responsive URLs from the well-known TMDB image base +
      size set) and typed query keys/hooks for home/rails/title/search; Vitest:
      responsive URL building, hooks target the right endpoints
- [x] 5.4 Home view: Hero + Rail (CSS scroll-snap) + MediaCard + skeleton loaders +
      infinite scroll (`useInfiniteQuery` over `/rails`); Vitest: renders hero +
      rails, loads the next page on cursor, applies the reduced-motion path
- [x] 5.5 Detail modal (deep-linkable `/title/:type/:id`): backdrop/logo, trailer
      embed (validated key), cast, season summaries, where-to-watch logos,
      similar/recommended; focus-managed, TMDB text rendered as text; Vitest: opens
      for the route, renders the sections, closes back to the browse view
- [x] 5.6 Search view: SearchBar + results grid + empty / no-results states;
      Vitest: a query renders results, an empty query issues no fetch

## 6. Boundary & gate hardening

- [x] 6.1 Import-linter contract forbidding the catalog/rails domain-model
      modules (`tasterr.catalog`, `tasterr.rails`) from importing
      `tasterr.settings`; test: the contract is present and passes, and a
      deliberate settings import trips it
- [x] 6.2 OpenAPI type-freshness in the gate: a `just` recipe regenerates the
      client types and `git diff --exit-code`s `api.gen.ts`, wired into
      `just check`; verify stale committed types fail the gate

## 7. Gate

- [x] 7.1 Run `just check` inside the devcontainer and fix all failures
