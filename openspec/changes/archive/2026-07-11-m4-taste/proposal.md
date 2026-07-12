# Proposal: m4-taste

## Why

M2/M3 made Tasterr a capable browser and request front-end, but every household
member still sees the same home — the PRD's one-line differentiator (*"every
member gets their own taste profile, their own recommendations"*) is entirely
unrealized, and the app has no memory of anything a user does. This change
implements **PRD/SPEC milestone M4 (Taste engine)**: interaction signals,
TMDB-metadata feature vectors, per-user profiles, scoring, cold-start seeding
from Seerr request history, "why am I seeing this?", profile reset, and the
personalized rails that consume it all. The milestone bar: **two users see
visibly different homes.**

## What Changes

- **Taste storage** (`db/`): migration 0003 adds the three SPEC §5 tables —
  `signals` (append-only per-user interaction events), `title_features`
  (persistent cache of per-title sparse feature vectors), `profiles`
  (materialized per-user taste vector, rebuildable from signals).
- **Signal recording** (`api/signals.py` + `recommend/signals.py`): session-gated,
  CSRF-checked `POST /signals` records `detail_open`, `watchlist`, and
  `not_interested` events from the SPA (with retraction for the toggle kinds —
  remove-from-watchlist, un-hide); `detail_open` is deduplicated per title per
  day. A successful `POST /request` records a `request` signal **server-side**
  (authoritative — the SPA never self-reports requests).
- **Feature vectors** (`recommend/features.py`): per-title sparse weighted
  vectors from TMDB detail — genres, keywords, top-N cast, director/creator,
  original language, decade, runtime bucket — persisted in `title_features`.
  The TMDB detail fetch gains the `keywords` append (deliberately deferred to
  M4), and the catalog exposes an internal, non-API "title facts" surface the
  feature builder consumes. Pure-Python dict math; no numpy.
- **Profile** (`recommend/profile.py`): normalized, exponentially time-decayed
  (half-life ≈ 90 days) sum of signal weight × title vector — request +3.0,
  watchlist +2.0, seed_request_history +2.0, detail_open +0.3,
  not_interested −3.0. Materialized in `profiles`; recomputed on signal writes
  and on staleness.
- **Scoring** (`recommend/scorer.py`): `α·cosine(profile, title) +
  β·quality_prior + γ·availability_boost(in-library, via media-availability,
  degrading to no boost when Seerr is down)`, followed by an MMR-style greedy
  diversity re-rank. Titles the user has hidden are hard-excluded; titles they
  already requested/seeded/watchlisted are excluded from "Recommended for You".
- **Cold start** (`clients/seerr.py` + `recommend/seed.py`): the Seerr client
  gains a request-history read (global API key, `requestedBy=<seerr_user_id>`,
  paginated, capped); first login triggers a background import of the user's
  Seerr request history as `seed_request_history` signals backdated to the
  request dates, so a brand-new user's home is *theirs* within one session.
- **Personalized rails** (`rails/`): the user now threads through `RailContext`;
  new providers — `recommended-for-you` (scored candidate pool),
  `because-you-watched-<title>` (TMDB recommendations+similar for a recent
  strong-positive title, re-ranked locally), and `my-list` (active watchlist
  titles). Users without signals gracefully fall back to the M2 non-personalized
  home (under-filled rails are already omitted by the composer).
- **Explain** (`api/recommendations.py` + `recommend/explain.py`):
  `GET /recommendations/explain?type=&id=` returns the top overlapping features
  between the user's profile and the title, rendered human-readably
  ("Because you like: Science Fiction, time travel, films from the 2010s").
- **Reset** (`api/recommendations.py`): session-gated, CSRF-checked
  `POST /recommendations/reset` deletes the user's signals + profile and
  re-seeds from Seerr request history — per-user, self-service.
- **SPA** (`media-browse`): the detail modal gains a watchlist toggle, a
  "Not interested" affordance, and the "Why am I seeing this?" explainer;
  opening a detail fires a `detail_open` signal; the navbar user menu gains
  "Reset recommendations" (with confirmation); the home renders the new
  personalized rails through the existing Rail component.

## Capabilities

### New Capabilities

- `taste-signals`: per-user interaction memory — the `signals` store, the
  `POST /signals` endpoint (kinds, retraction, dedup, validation), the
  server-side `request` signal on successful requests, and the privacy posture
  (a user's signals are theirs alone; never exposed to other users).
- `taste-recommendations`: the engine — title feature vectors (+ the
  `title_features` cache), the decayed profile materialization, scoring with
  quality prior/availability boost/diversity, cold-start seed from Seerr
  request history, the personalized rail providers, explain, and reset.

### Modified Capabilities

- `media-browse`: the home feed requirement gains personalized rails
  (recommended-for-you, because-you-watched, my-list) that vary per user and
  degrade to the non-personalized feed for signal-less users; the routed SPA
  requirement gains the detail-modal taste affordances (watchlist, not
  interested, explain), the detail-open signal, and the reset entry point.
- `media-catalog`: normalization gains a feature-oriented **title facts**
  surface (including TMDB keywords, fetched via the detail append) consumed by
  the recommendation engine — internal, never part of an API response.
- `media-requests`: the request requirement now records a `request` taste
  signal server-side on success.

## Impact

- **Backend**: `recommend/` is born (`features.py`, `signals.py`, `profile.py`,
  `scorer.py`, `seed.py`, `explain.py` — pure domain logic, unit-testable
  without network); `clients/tmdb.py` adds `keywords` to the detail append;
  `clients/seerr.py` adds the request-history read (still the only Seerr
  caller); new `api/signals.py` and `api/recommendations.py` routers;
  `api/request.py` records the request signal; `rails/registry.py`/`composer.py`
  thread the user and register the personalized providers; migration 0003 adds
  `signals`, `title_features`, `profiles`.
- **Frontend**: detail-modal affordances + explainer, navbar user-menu reset,
  signal-posting hooks in `lib/`, `api.gen.ts` regenerated.
- **New dependencies**: none — sparse vectors are plain dicts (SPEC §8:
  numpy only if profiling ever demands it).
- **Tests**: recommendation math (decay, weights, cosine, diversity, explain
  overlap) as pure unit tests; signals API (gating, CSRF, validation, dedup,
  retraction); seed import (pagination, backdating, idempotence); Seerr client
  contract tests on `httpx.MockTransport` + a live-marked request-history test
  against the pinned Seerr 3.3.0; rails personalization (distinct homes for
  distinct profiles, signal-less fallback, hidden-title exclusion); migration
  round-trip; Vitest for the new affordances and signal hooks.

## Non-goals

- **Onboarding taste picker** (v1.x) — thin-history local users fall back to
  the non-personalized home until they browse; the PRD explicitly phases the
  picker after v1.0.
- **Plex watch-history signals, continue-watching, household blend** (v2) —
  the `watched_plex` signal kind stays out of the schema's accepted values
  until v2 wires it.
- **Service rails, popular-in-region, admin rail toggles, region/service
  configuration** (M5) — the availability boost uses in-library status only;
  the on-selected-services boost lands when M5 gives admins service selection.
  All new rails ship enabled, toggleable in M5.
- **Rate limiting on the new mutations** (M6) — `/signals` and
  `/recommendations/reset` get the CSRF origin check now, like `/request`
  before them; the app-wide token bucket is M6's pass.
- **Per-user home caching and background pool refresh** (SPEC §7/§10) — at
  household scale scoring a candidate pool per request is cheap; the in-process
  TMDB cache and the persistent `title_features` cache carry the load. Revisit
  only if latency actually hurts.
- **Embeddings, collaborative filtering, numpy** — the browserr-proven sparse
  interpretable design is the deliberate SPEC §8/decision-log choice.
