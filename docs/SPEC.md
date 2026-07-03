# Tasterr — Technical Specification

**Status:** Founding blueprint, frozen 2026-07-01 — companion to [PRD.md](./PRD.md)

> **Frozen founding blueprint.** This document captures the founding technical design.
> Once implementation begins, `openspec/specs/` is the living source of truth for
> current behavior; this file is historical rationale and is **not updated**.
> Process and workflow rules live in [AGENTS.md](../AGENTS.md).
**Reference implementation:** [janpuc/browserr](https://github.com/janpuc/browserr)
(Next.js/TypeScript). Useful for: BFF route shapes (`src/app/api/**`), the recommendation
engine's behavior (`src/server/recommend/**`), rails composition (`src/server/rails/**`),
TMDB/Seerr client resilience patterns (`src/server/tmdb/`, `src/server/seerr/`), and the
`toPublicConfig` secret-scrubbing pattern (`src/lib/config*`). Consult, don't port.

---

## 1. Architecture overview

```
Browser ── static SPA assets + /api/v1/* ──> FastAPI (single process, single container)
                                              ├─ auth: Plex PIN flow / Seerr credential forwarding
                                              ├─ BFF routers (normalize, strip secrets)
                                              ├─ per-user Seerr sessions (held server-side)
                                              ├─ recommendation engine (in-process, numpy-free ok)
                                              ├─ rails composer (toggleable rail registry)
                                              ├─ in-process TTL cache + stale-on-error
                                              ├─ asyncio background refresher
                                              └─ SQLite (SQLAlchemy 2.0 + Alembic)
                                                    │
                              TMDB API  ◄─────────┤ (server-side only)
                              Seerr API ◄─────────┤ (internal URL, server-side only)
                              plex.tv   ◄─────────┘ (auth PIN flow only, v1)
```

Hard rules carried over from browserr, kept as **regression-tested invariants**:

1. **Secrets never reach the client.** TMDB key, Seerr API key, Seerr *internal* URL, Plex
   tokens, and Seerr session cookies exist only server-side. The client receives a
   `PublicConfig` projection; a test asserts its schema contains no secret fields.
2. **The browser talks only to Tasterr.** Every TMDB/Seerr/Plex call goes through the BFF.
3. **Browsing never hard-fails on Seerr.** Seerr down ⇒ availability shows "Unknown",
   requests disabled, catalog still browses.

## 2. Stack (locked)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.13 | backend |
| Web framework | FastAPI | async, typed, OpenAPI for free |
| Validation/config | Pydantic v2 + pydantic-settings | env-driven settings model |
| DB | SQLite via SQLAlchemy 2.0 (async) + Alembic | one file, idempotent migrate on boot |
| HTTP client | httpx (async) | shared client, timeouts + retries |
| Packaging/tooling | uv, ruff (lint + format), pyright (strict), pytest (+ pytest-asyncio) | |
| Frontend | Vite + React + TypeScript (strict) + Tailwind + TanStack Query | SPA, built to static assets |
| FE tooling | Biome (lint + format), Vitest | one tool each |
| Animation | CSS-first (transitions, scroll-snap, `prefers-reduced-motion`) | no Framer Motion |
| Container | Multi-stage Dockerfile: node builds SPA → python runtime serves | amd64 + arm64, GHCR |
| Cache | In-process TTL (`cachetools`) | no Redis; single-process by design |
| Background work | asyncio task in app lifespan | no celery/cron |

Single-process is a deliberate constraint (KISS): in-process cache and per-user state assume
one replica. Documented; revisit only if it ever actually matters.

## 3. Repository layout

```
tasterr/
  backend/
    pyproject.toml
    src/tasterr/
      main.py               # app factory, lifespan (migrate, start refresher), static mount
      settings.py           # pydantic-settings; env-only secrets (§8)
      api/                  # routers: auth, home, title, search, request, signals,
                            #          recommendations, settings, meta (health/config/regions/services)
      auth/                 # plex PIN flow, seerr credential forwarding, session store, admin gate
      clients/              # tmdb.py, seerr.py, plex.py — the ONLY modules that do outbound HTTP
      catalog/              # normalization TMDB→domain models, image URL building
      rails/                # rail registry (§7), composer
      recommend/            # features.py, signals.py, profile.py, scorer.py, explain.py
      db/                   # engine, models, alembic/
      cache.py              # TTL + stale-on-error wrapper
    tests/                  # mirrors src; contract tests for clients marked live-only
  frontend/
    src/
      routes/               # home, search, settings, login
      components/           # Hero, Rail, MediaCard, DetailModal, Navbar, AvailabilityBadge...
      lib/                  # api client (typed from OpenAPI), types, query keys
  openspec/                 # living specs + change proposals (OpenSpec workflow)
  docs/                     # PRD.md, SPEC.md (frozen blueprint), spike docs,
                            # CONFIGURATION.md (later), ARCHITECTURE.md (later)
  .github/                  # PR template, workflows (gate on PRs, image build)
  AGENTS.md CLAUDE.md       # agent/process instructions (committed)
  justfile                  # single entrypoint: `just check`
  Dockerfile
  docker-compose.yml
  .env.example
```

Boundary rule (mirrors browserr's server/lib split): **only `clients/` performs outbound
HTTP; only `api/` shapes responses for the browser.** Everything between is pure-ish domain
logic that unit-tests without mocks of the network.

## 4. Authentication & sessions

### 4.1 Login flows

**Plex (primary):**
1. `POST /api/v1/auth/plex/pin` → backend creates a PIN at `plex.tv/api/v2/pins`
   (`X-Plex-Product: Tasterr`, stable `X-Plex-Client-Identifier` from settings/DB) and returns
   `{pin_id, auth_url}` (auth_url = `app.plex.tv/auth#?...`).
2. SPA opens `auth_url`; polls `GET /api/v1/auth/plex/pin/{pin_id}`.
3. On PIN claim, backend receives the **Plex auth token**, then `POST {SEERR}/api/v1/auth/plex`
   with it. Seerr validates the user exists/permitted and returns the user object + a Seerr
   session cookie.
4. Backend upserts the `users` row, stores the Seerr cookie and (encrypted) Plex token in the
   session row, mints a Tasterr session, sets the cookie. Poll response flips to `{status: "ok", user}`.

**Local Seerr account (secondary):**
1. `POST /api/v1/auth/local {email, password}` → forwarded verbatim to
   `{SEERR}/api/v1/auth/local`. Credentials are never stored, never logged.
2. Same upsert/session minting as above (no Plex token in this path).

### 4.2 Tasterr session

- 256-bit random token; **only its SHA-256 hash stored** in `sessions`.
- Cookie: HTTP-only, `SameSite=Lax`, `Secure` when served over HTTPS (proxy-header aware for
  the Cloudflare tunnel), long-lived (default 30 days, sliding).
- Logout deletes the session row (revocation is trivial because sessions are server-side).

### 4.3 Per-user Seerr session (request-as-user)

- The Seerr session cookie from login is stored on the Tasterr session row and attached to all
  per-user Seerr calls (requests, the user's own request history).
- On Seerr `401`/`403` (Seerr 3.3.0 returns **403** with a permission-error body for invalid
  sessions — confirmed by the auth spike): Plex users → silent re-auth via stored Plex token →
  retry once. Local users → surface `re_auth_required`; SPA shows a re-login prompt. 403 is
  also Seerr's genuine permission-denied response, so never re-auth more than once per request.
  Availability reads degrade to the global path rather than failing.
- Availability *reads* may use the global Seerr API key (server setting) since they're not
  user-attributed — keeps badge hydration working even when a user's Seerr session lapses.

### 4.4 Admin gate

`is_admin` = Seerr `/api/v1/auth/me` permissions include ADMIN, evaluated **at login** and
stored on the user row (re-evaluated each login). Admin-only routers (`settings`,
`connection-test`) enforce via a dependency.

## 5. Data model (SQLite)

```
users            id PK, seerr_user_id UNIQUE, display_name, avatar_url,
                 auth_type ('plex'|'local'), is_admin, created_at, last_login_at
sessions         id PK, token_hash UNIQUE, user_id FK, seerr_cookie,
                 plex_token_enc NULL, created_at, expires_at, last_seen_at
signals          id PK, user_id FK, tmdb_id, media_type ('movie'|'tv'),
                 kind ('request'|'watchlist'|'detail_open'|'not_interested'|'seed_request_history'),
                 weight REAL, created_at        # (kind set extends in v2: 'watched_plex')
title_features   (tmdb_id, media_type) PK, features JSON, fetched_at   # cache of TMDB-derived vectors
profiles         user_id PK, vector JSON, computed_at                  # materialized; rebuildable from signals
settings         key PK, value JSON, updated_at                        # admin runtime prefs only, never secrets
```

- `plex_token_enc`: encrypted at rest (Fernet, key = `TASTERR_SECRET_KEY`). Pragmatic, not
  theater — the SQLite file and env live on the same host, but tokens shouldn't be `strings`-able.
- `profiles` is a materialization; `POST /recommendations/reset` deletes the user's signals +
  profile and re-seeds from Seerr request history.

## 6. BFF API (`/api/v1`)

Same-origin only; all mutations CSRF-checked (§9). Response models are Pydantic; the SPA's
client types are generated from the OpenAPI schema (one source of truth).

| Method | Route | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/plex/pin` · GET `/auth/plex/pin/{id}` | — | Plex PIN create / poll-complete |
| POST | `/auth/local` | — | Local Seerr login |
| POST | `/auth/logout` · GET `/auth/me` | session | End session / current user |
| GET | `/health` | — | Liveness + configured flags |
| GET | `/config` | session | `PublicConfig` projection |
| GET | `/regions` · `/services?region=` | admin | Settings screen data |
| GET/PUT | `/settings` | admin | Runtime prefs (region, services, rail toggles, appearance) |
| POST | `/connection-test` | admin | Validate TMDB/Seerr connectivity |
| GET | `/home` | session | Hero + first rails, personalized |
| GET | `/rails?cursor=` | session | Additional rails (infinite scroll) |
| GET | `/title/{type}/{id}` | session | Detail + availability + watch links |
| POST | `/availability` | session | Batch badge hydration |
| POST | `/request` | session | Proxy request **as the user** (redirect fallback in payload) |
| GET | `/search?q=` | session | Multi-search with availability |
| POST | `/signals` | session | Record interaction signals |
| GET | `/recommendations/explain?type=&id=` | session | "Why am I seeing this?" |
| POST | `/recommendations/reset` | session | Wipe + re-seed profile |

## 7. Rails system

A **registry of rail providers**, each with an id, admin toggle, and an async
`compose(user, catalog_ctx) -> Rail`:

- v1 providers: `hero`, `trending`, `recommended_for_you`, `because_you_watched` (from
  strong-signal titles), `genre:*`, `service:*`, `popular_in_region`.
- v2 providers (same interface, gated by toggles + capability checks): `continue_watching`
  (needs Plex token), `household_blend`.
- The composer interleaves enabled providers, dedupes titles across rails, and paginates.
  Home feed structure is cached per-user briefly (short TTL) and shared parts (trending,
  genre pools) cached globally.

## 8. Recommendation engine

Deliberately the same design as browserr (proven, interpretable), reimplemented per-user:

- **Features** (per title, from TMDB detail): genres, keywords, top-N cast, director/creator,
  original language, decade, runtime bucket → sparse weighted vector, cached in `title_features`.
- **Signals** (weighted, exponential time decay, half-life ≈ 90 days): request +3.0,
  watchlist +2.0, detail_open +0.3, seed_request_history +2.0, not_interested −3.0.
  (v2: watched_plex +2.5.)
- **Profile**: normalized decayed sum of signal_weight × title_vector.
- **Scoring**: `score = α·cosine(profile, title) + β·quality_prior(popularity, rating)
  + γ·availability_boost(on_selected_services | in_library)`, α ≫ β, γ; then greedy
  diversity re-rank (MMR-style penalty on similarity to already-picked titles).
- **Because you watched X**: TMDB `recommendations`+`similar` for a recent strong-positive
  title, re-ranked by local scoring.
- **Cold start**: on first login, import the user's Seerr request history as
  `seed_request_history` signals; if empty, fall back to `popular_in_region` until signals
  exist (and the v1.x onboarding picker fills the gap).
- **Explain**: top overlapping features between profile and title, rendered human-readably
  ("Because you like: A24-style keywords, thrillers, films from the 2010s").

Pure-Python math (dicts as sparse vectors) — no numpy dependency unless profiling says otherwise.

## 9. Configuration & security

### Config: split by kind

- **Env-only (secrets & connections)** — via pydantic-settings, never in DB, never in any API
  response, never editable in GUI: `TMDB_API_KEY`, `SEERR_INTERNAL_URL`, `SEERR_EXTERNAL_URL`,
  `SEERR_API_KEY`, `TASTERR_SECRET_KEY`, `DATABASE_PATH`, bind host/port.
- **DB-backed (admin GUI)**: region, selected services, rail toggles, appearance, request
  mode default. Defaults applied on first boot; no LOCK_CONFIG machinery.
- `PublicConfig` projection + regression test asserting no secret ever appears (the browserr
  key rule, kept).

### Security posture (internet-exposed via Cloudflare tunnel is assumed)

- Sessions per §4.2; secrets per above; admin gating per §4.4.
- **CSRF**: mutations require `Origin`/`Sec-Fetch-Site` same-origin check (+ `SameSite=Lax`
  cookie). No token dance needed for a same-origin SPA.
- **Rate limiting**: in-process token bucket on auth endpoints (tight) and mutations (loose).
- **Redirects**: any URL sent to the client (Seerr external, Plex deep link) is built
  server-side from validated config, never echoed from input.
- Proxy-header middleware trusts `X-Forwarded-Proto` so cookies are `Secure` behind the tunnel.
- Login attempts logged; credentials and tokens never logged.
- **Supply chain**: `just audit` (pip-audit + npm audit) run before every release and in the
  PR gate as non-blocking advisory; lockfiles (`uv.lock`, `package-lock.json`) committed.
- **Container**: runs as a non-root user, minimal base image, healthcheck defined.

## 10. Resilience & caching

- TMDB: shared httpx client, timeout + bounded retry w/ backoff; TTL cache per endpoint
  class (config/regions long; trending/rails medium; detail short-ish); **stale-on-error**
  serves the last good value when TMDB errors.
- Seerr: short timeout, no retry storm; failures flip availability to "Unknown" and disable
  request buttons with a UI notice.
- Background asyncio refresher (started in lifespan): re-warms region/services and shared
  rail pools on an interval; jittered; never blocks requests.

## 11. Testing & quality gate

- **Gate before any push:** `just check` (root justfile) — ruff + pyright + pytest on the
  backend, typecheck + vitest + build on the frontend. One command for humans, agents, and CI.
- **Boundary tests** enforce the §1/§3 invariants mechanically: import-linter contracts
  (only `clients/` imports httpx; response models never import secret settings) plus the
  PublicConfig no-secrets regression test.
- Unit: rec engine (decay, scoring, diversity, explain), rails composer, PublicConfig
  scrubbing, session lifecycle, CSRF dependency.
- Contract: TMDB/Seerr client tests against recorded fixtures; a separate live-marked suite
  runs against the real home Seerr before releases (documents the Seerr version tested).
- E2E (light): Playwright smoke — login (mocked Seerr), browse home, open detail, request.

## 12. Deployment

- Multi-stage Dockerfile: `node:*-slim` builds `frontend/dist` → `python:3.13-slim` + uv
  installs backend → FastAPI serves `/api/v1/*` and the SPA (static files + index fallback).
- `docker-compose.yml` example wiring Tasterr beside Seerr on the stack network
  (`SEERR_INTERNAL_URL=http://seerr:5055`); SQLite on a named volume.
- GitHub Actions, two workflows only: a gate workflow running `just check` on every PR
  (identical to the local command — no divergence), and the image build → GHCR on push to
  `main` (amd64 + arm64), same shape as browserr's `image.yml`.

## 13. Milestones

| # | Milestone | Contents | Done when |
|---|---|---|---|
| M0 | Scaffold | Repo layout, tooling, settings, DB+Alembic, Docker skeleton, hello-world SPA served by FastAPI | Gate passes in container |
| M1 | Auth | Plex PIN + local flows, sessions, `/auth/me`, admin gate; live-tested against home Seerr | Both login paths work from the SPA |
| M2 | Browse | TMDB client, catalog normalization, hero+rails home (non-personalized), detail, search | Usable read-only browser |
| M3 | Seerr integration | Availability badges, request-as-user, degradation paths | Request lands in Seerr attributed correctly |
| M4 | Taste engine | Signals, features, profile, scoring, cold-start seed, explain, reset, personalized rails | Two users see visibly different homes |
| M5 | Admin & polish | Settings screen, rail toggles, appearance, a11y/reduced-motion pass, 10-foot check | PRD v1.0 table fully green |
| M6 | Hardening & release | Rate limits, security review, docs (CONFIGURATION/ARCHITECTURE), GHCR image | v1.0 tag |

Then v1.x (Play-in-Plex link, onboarding picker) and v2 (Plex history signals,
continue-watching, household blend) per the PRD phasing.

## 14. Decisions log (from the 2026-07-01 grilling)

| Decision | Choice | Rejected alternatives |
|---|---|---|
| Relationship to browserr | Clean rebuild, browserr as local reference | Continue fork; port |
| Backend | FastAPI | Django (auth batteries unused — Seerr owns users), Flask (sync), Litestar (ecosystem) |
| Frontend | Vite React SPA served by FastAPI | HTMX (UI too interactive), Next.js (two runtimes), Svelte/Vue |
| Identity | Delegated to Seerr; Plex OAuth primary, local secondary | Own accounts; profile-picker-only; proxy-header auth |
| Requests | As the user via stored Seerr session | Admin key impersonation; redirect-only |
| Region/services | Global, admin-set | Per-user |
| Admin | = Seerr admin | First-user-is-admin; open settings |
| Rec engine | browserr design, per-user | TMDB-only v1; embeddings |
| Signals | In-app + Seerr history (v1); Plex history + picker (later) | — |
| Config | Secrets env-only; prefs in DB | browserr parity (GUI secrets + LOCK_CONFIG); env-only-everything |
| Scope | Lean core v1 | Plex features in v1; everything-in-v1 |
| Name | Tasterr (checked available) | Discoverr/Curatarr (taken), Scouterr (Scoutarr clash), Gazerr, Reelerr, Flickerr (org taken) |
| Process | OpenSpec for features/behavior/architecture; `openspec/specs/` is living truth; PRD/SPEC frozen as founding blueprint | Living SPEC.md (dual-update drift trap); decompose SPEC into openspec up front |
| Branching | Branch per OpenSpec change + self-approved PR, squash merge; trivial fixes direct to main | Strict PR-only; trunk-based direct push |
| Commit style | Conventional Commits, imperative, ≤72 chars | Free-form (browserr style) |
| Enforcement | `just check` single gate + import-linter boundary tests + gate CI on PRs | pre-commit hooks; ADR folder (openspec proposals are the decision record) |
| Repo hygiene | AGENTS.md/CLAUDE.md/openspec/ committed; AI tool dot-folders gitignored; no AI mentions in any committed artifact outside those files | Gitignore AGENTS.md too; commit .claude/ (browserr style) |
