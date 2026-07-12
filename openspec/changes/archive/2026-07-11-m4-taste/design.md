# Design: m4-taste

## Context

M2/M3 built everything the taste engine consumes and left its seams explicitly
open: `recommend/` is an empty package; `rails/registry.py` documents itself as
"the seam M4 extends with personalized providers"; `clients/tmdb.py` notes
"keywords are an M4 signal source and are not fetched until then"; the SPEC §5
tables `signals`, `title_features`, and `profiles` do not exist yet (migrations
stop at 0002). `complete_login` (auth/login.py) is the single choke point where
both login flows upsert the user — the natural hook for the cold-start seed.
`media-availability` provides the cached, degrade-to-Unknown library-status
reads the availability boost needs, and the composer already omits under-filled
rails and degrades per-provider — which is exactly how a signal-less user falls
back to the non-personalized home with no new machinery.

This change turns SPEC §8 (the recommendation engine — deliberately the
browserr-proven, interpretable design, per-user), the personalized half of §7
(rails), and the `/signals`, `/recommendations/*` rows of §6 into code — the
SPEC §13 M4 milestone ("two users see visibly different homes"). browserr
(`src/server/recommend/**`) is the reference for engine behavior — decay,
sparse vectors, MMR — consulted, not ported.

## Goals / Non-Goals

**Goals:**

- Per-user interaction memory: signals recorded from the SPA (detail-open,
  watchlist, not-interested) and server-side (request, seed), append-only,
  the profile always rebuildable from them.
- An interpretable engine: sparse TMDB-metadata vectors, decayed profiles,
  cosine scoring with a quality prior, an in-library availability boost, and
  MMR diversity — pure-Python dict math, unit-testable without I/O.
- Cold start that makes a first login feel personal within the session, seeded
  from Seerr request history, never blocking login and never failing it.
- Personalized rails through the existing registry/composer seam, degrading to
  the M2 non-personalized home for signal-less users and on any engine failure.
- Explain and reset — the PRD's transparency and self-service escape hatches.

**Non-Goals:**

- Onboarding picker (v1.x); Plex watch signals, continue-watching, household
  blend (v2); service rails/toggles and the on-selected-services boost (M5);
  mutation rate limiting (M6); per-user home caching and background pool
  refresh; numpy/embeddings (proposal Non-goals).

## Decisions

1. **Two capabilities: memory vs. engine.** `taste-signals` is the write-side
   product surface (what users record and retract, its validation and privacy
   posture); `taste-recommendations` is everything derived from it (vectors,
   profile, scoring, seed, rails, explain, reset). The split mirrors
   M3's availability/requests framing: the signal contract is small and stable;
   the engine is where iteration happens. Rejected: one `taste-engine`
   capability (blends the client-facing mutation contract with derived
   machinery that will be tuned for releases to come).

2. **`recommend/` splits pure math from I/O.** `features.py` (facts → vector),
   `profile.py` (signals+vectors → profile), `scorer.py` (profile+candidates →
   ranked list), `explain.py` (profile+vector → reasons) are pure functions
   over dicts — no DB, no network, no clock reads (time passed in). A thin
   `store.py` owns the SQLAlchemy reads/writes for the three tables, and
   `service.py` orchestrates (ensure vectors → load profile → score) and is the
   one face the API and rails layers see. This keeps the AGENTS.md "pure domain
   logic between api/ and clients/" rule literal: the math unit-tests without
   mocks of anything. Rejected: ORM-aware engine modules (couples the math to
   session lifecycles and makes the decay/scoring tests I/O tests).

3. **Feature dimensions are label-bearing string keys.** Vectors are
   `dict[str, float]` with namespaced, self-describing keys —
   `genre:Science Fiction`, `kw:time travel`, `cast:Tom Hanks`,
   `director:Denis Villeneuve`, `lang:en`, `decade:2010`, `runtime:epic` —
   lowercased/normalized. Explain then falls out of the arithmetic: the top
   overlap dims *are* the human-readable reasons, no label lookup table to keep
   in sync. Per-class weights are code constants with tests (genres 1.0,
   keywords 0.6 capped at ~12, top-5 cast 0.4, director/creator 0.5, language
   0.3, decade 0.3, runtime bucket 0.2), and title vectors are L2-normalized so
   cosine is a dot product. Rejected: TMDB-id keys + a label table (marginally
   more rename-stable, but adds a join for explain and hides meaning from every
   test and debug session); equal weights per class (genres would drown under
   a dozen keywords).

4. **`title_features` is the persistent vector cache; facts ride the existing
   detail fetch.** `clients/tmdb.py` adds `keywords` to `DETAIL_APPEND` (both
   media types; TV creator from `created_by`, movie director from crew), and
   `CatalogService` gains `title_facts(media, id)` — an internal, non-API model
   (genres, keywords, cast, director/creator, language, year, runtime, vote
   stats) derived from the same cached detail payload as `detail()`, so facts
   cost no extra TMDB call when the detail is warm. Built vectors (plus the
   quality-prior inputs) persist in `title_features` keyed `(tmdb_id,
   media_type)` with `fetched_at`, refreshed after ~30 days. Missing vectors are
   built on demand under an `asyncio.Semaphore` (bounded fan-out), and each
   build failure skips that candidate rather than failing the rail. Rejected: a
   client-facing keywords field on `MediaDetail` (bloats every browse response
   for engine-internal data); building vectors from summaries only (loses
   keywords/cast — the dimensions that make profiles distinctive); an
   in-process-only vector cache (cold restarts would refetch the whole pool;
   SQLite is already there).

5. **Profile recompute is inline and cheap; decay at compute time.** The
   profile is recomputed from all of a user's signals (a) after every signal
   write and (b) at read when `computed_at` is older than 24 h — at household
   scale a user has hundreds of signals and recompute is sub-millisecond dict
   math. Decay `exp(-ln2 · age/90d)` is evaluated against the recompute
   moment, so profiles age even without new signals via (b). The materialized
   row is a pure cache: deleting `profiles` loses nothing (spec scenario).
   Every signal write/retraction **invalidates the materialization in the
   same transaction** (review finding: a failed best-effort recompute
   otherwise left a stale profile looking fresh for 24 h); the eager rebuild
   stays best-effort because the next read self-heals from the missing row.
   Vector/profile writes are real upserts, not `merge` (merge's
   select-then-insert races concurrent writers of the same title). Rejected:
   incremental profile updates (invites drift, saves nothing at this scale);
   decaying at signal-write time (freezes decay at whenever the user last
   acted).

6. **Candidate pool from already-cached TMDB surfaces; score-and-diversify.**
   Recommended-for-you candidates = TMDB `recommendations`+`similar` for the
   user's top-K (≈3) strong-positive titles ∪ discover pages for the profile's
   top genres ∪ trending — all reads the M2 cache already serves — capped
   around 150 after exclusions. Exclusions: `not_interested` titles are
   hard-excluded from every personalized rail; titles the user already
   requested/seeded/watchlisted are excluded from recommended-for-you (they
   know about those; My List and Seerr already show them). Scoring:
   `1.0·cosine + 0.15·quality_prior + 0.10·availability_boost`, quality prior a
   vote-count-shrunk rating from the stored facts, availability boost 1 for
   in-library per the cached `media-availability` batch read (Unknown/down →
   0 — degrade, never block). Then greedy MMR (λ ≈ 0.3) over the vector
   similarity of picked titles. All constants live in one module with tests
   asserting the ordering properties, tuned by living with it. Rejected:
   scoring the whole TMDB catalog (there is no such feed; the pool is the
   product surface anyway); dropping diversity (top-N cosine is a wall of one
   franchise); a service-availability boost now (M5 owns service selection).

7. **Personalized providers thread the user through `RailContext`.**
   `RailContext` gains the authed user and the recommend service (both optional
   — `/rails` extra pages and tests stay user-free). New providers:
   `my-list` (active watchlist signals → summaries via cached detail lookups),
   `recommended-for-you` (decision 6), and one `because-you-watched` rail —
   sourced from the most recent strong-positive title, its TMDB
   recommendations+similar re-ranked by the user's scorer, labelled honestly as
   **"More like <title>"** (v1 has no watch signals; PRD reserves genuine
   "Because you watched" for v2 Plex history). Home order: hero, My List,
   Recommended for You, trending, More like X, then the M2 rails. Providers run
   inside the existing `_safe_fetch`/min-items machinery, so failure or
   thinness degrades exactly like any other rail — that *is* the signal-less
   fallback, no special-casing. Two review-driven refinements: the
   personalized providers are marked **exclusive** and the composer runs them
   one at a time before the concurrent gather (they share the request's
   `AsyncSession`, which is not safe for concurrent tasks — the review
   reproduced concurrent vector writes colliding and silently dropping the
   rails), and a degraded provider **rolls the shared session back** so a
   failed flush cannot poison the request's final derived-cache commit.
   Rejected: a separate `/recommendations` feed endpoint (the home *is* the
   recommendation surface; SPEC §6 has no such route); multiple because-you
   rails (row-surfing bloat before there's data to justify it); a
   session-per-provider (three sessions per home render to save one seam
   comment's worth of clarity).

8. **Signals API: one endpoint, explicit toggle semantics.** `POST /signals`
   takes `{media_type, tmdb_id, kind, retract: bool = false}` with `kind`
   constrained by `Literal` to the client-recordable set — `request` and
   `seed_request_history` are unrepresentable in the request model, so clients
   cannot fabricate strong signals. `watchlist`/`not_interested` are toggles:
   add is idempotent (no duplicate active row), `retract: true` deletes the
   user's rows of that kind for the title; `detail_open` is append-only,
   deduplicated per UTC day, retraction rejected (422). The `request` signal is
   written by `api/request.py` directly after a successful Seerr request —
   authoritative, in the same DB session, wrapped so a signal failure logs and
   never fails the request response. Rejected: recording `detail_open`
   server-side on `GET /title` (a state-writing GET, and any future
   hover-prefetch would pollute the profile); REST-ish DELETE routes per kind
   (three routes for one concept; SPEC §6 defines one `/signals`).

9. **Cold-start seed: background at login, inline at reset, global-key read.**
   `clients/seerr.py` gains `list_requests(requested_by, take, skip)` — global
   `X-Api-Key`, explicit `requestedBy=<seerr_user_id>` filter, short timeout,
   bounded pagination, capped at the 200 most recent. The walk is bounded by
   raw pages requested (not parsed rows), so an upstream serving full pages
   of malformed rows cannot extend it. Seed rows are **idempotent per
   user+title, enforced by the database** — a partial unique index over the
   toggle+seed kinds with `INSERT .. ON CONFLICT DO NOTHING`, so there is no
   check-then-insert to race and an overlapping login-seed and reset (or a
   double reset), even across concurrent sessions, cannot double a title's
   influence. Correctness never depends on the in-process single-flight set,
   which only avoids duplicate work. This extends the M3 auth
   doctrine one notch: the global key authenticates **reads** (availability,
   and now request history — server-initiated, explicitly user-scoped by
   parameter), while user-attributed **mutations** only ever ride the per-user
   cookie. The alternative — the user's own cookie — breaks exactly when the
   seed matters: at reset time the Seerr session may be lapsed, and the re-auth
   ladder doesn't belong in a background job. `complete_login` checks "user has
   zero signals" and spawns a fire-and-forget asyncio task (single-flight per
   user via an in-process set) that imports history as `seed_request_history`
   signals **backdated to each request's creation date** (decay then prices old
   requests honestly), builds their vectors, and materializes the profile.
   Login never waits. Failure modes differ by phase: an **import** failure
   logs and leaves the user unseeded until the next login/reset retries, while
   a **materialization** failure after the signals committed leaves the user
   seeded — the profile is a cache that rebuilds on the next read. Reset
   (`POST /recommendations/reset`,
   CSRF-checked) deletes the caller's signals+profile and awaits the same
   import inline — user-initiated, a second of latency is fine and the response
   reflects the re-seeded state. Rejected: seeding synchronously in the login
   response (couples login latency to Seerr pagination); seeding lazily on
   first `/home` (hides a multi-second stall in the hot path); importing with
   the user cookie (above).

10. **Explain is arithmetic, not prose generation.**
    `GET /recommendations/explain?type=&id=` loads the caller's profile and the
    title's vector, multiplies element-wise, and returns the top-contributing
    dimensions (positive overlap only) grouped into a short reasons list
    rendered from the label-bearing keys — `{"personalized": true, "reasons":
    ["Science Fiction", "time travel", "films from the 2010s"]}`. No profile or
    no overlap → `personalized: false` with empty reasons — honest, never
    fabricated. Rejected: LLM-ish templated sentences server-side (the SPA
    owns copy; the API returns typed reasons); exposing raw dim weights
    (meaningless numbers to a household user — and the SPA can't misrender
    what it never gets).

11. **Frontend: affordances ride existing components; signals are
    fire-and-forget.** The detail modal gains a watchlist toggle and a
    "Not interested" control (optimistic flip, retract on second tap/undo) and
    a collapsible "Why am I seeing this?" that lazily queries explain; opening
    the modal posts `detail_open` via a mutation that swallows errors —
    browsing never notices a failed signal. The navbar user menu gains "Reset
    recommendations" behind an explicit confirm. My List / personalized rails
    render through the existing `Rail`/`MediaCard` unchanged. All calls go
    through the regenerated `api.gen.ts` client. Rejected: a dedicated
    watchlist page (My List rail covers v1; a page is M5+ polish); blocking the
    modal on the explain query (it's curiosity content, loaded on demand).

12. **Schema (migration 0003) — additive, behavioral, secret-free.**
    Exactly the SPEC §5 shapes: `signals` (id PK, user_id FK CASCADE + index,
    tmdb_id, media_type, kind, weight REAL, created_at, indexed
    (user_id, kind), plus a **partial unique index** over (user_id,
    media_type, tmdb_id, kind) for the toggle+seed kinds — at-most-one-row
    semantics as a database guarantee, not an application check),
    `title_features` ((tmdb_id, media_type) PK, features JSON, fetched_at),
    `profiles` (user_id PK FK CASCADE, vector JSON, computed_at). Weights are stored per-row (SPEC §5) so historical rows keep
    the weight they earned even if constants are retuned. JSON columns hold
    plain dicts — SQLite JSON1 is not required; the app treats them as opaque
    text. Rejected: normalizing vectors into a dims table (query machinery for
    data only ever read whole); storing computed decay (decision 5).

**New dependencies vs. the AGENTS.md slate:** none. The engine is pure-Python
dict math by explicit SPEC §8 decision ("no numpy unless profiling says
otherwise"); persistence uses the existing SQLAlchemy/Alembic path, HTTP the
existing httpx clients, caching the existing `cache.py` + SQLite.

## Security considerations

Walked per docs/SECURITY.md for endpoints, auth/session, outbound HTTP,
frontend, and DB (no new dependencies). One point of emphasis: the threat
model explicitly protects **household viewing behavior** — signals and
profiles are exactly that, so privacy is treated with the same rigor as
secrets.

- **New/changed endpoints.** `POST /signals`, `GET /recommendations/explain`,
  and `POST /recommendations/reset` are session-gated by the shared
  default-deny dependency. The two mutations carry `require_same_origin`
  (CSRF); explain is a read. Inputs are fully Pydantic-constrained
  (`Literal` media types and kinds, positive-int ids, bool retract) — the
  server-recorded kinds are unrepresentable in the request model, so a client
  cannot forge `request`/seed signals (signal-stuffing your own profile with
  the client-recordable kinds is self-harm at worst — weights are small,
  detail-open is deduped, and reset recovers). Every route declares an explicit
  secret-free `response_model`; errors are generic; broad rate limiting stays
  M6 (proposal Non-goals). Logs record outcomes and counts only — never
  per-title viewing behavior, which is PII under this threat model.
- **Privacy (cross-user isolation).** Every signal/profile read and write is
  keyed by the authenticated session's user id — there is no path that accepts
  a user id from input. Explain derives from the caller's own profile only; no
  endpoint returns raw signal history or another user's data; rails built for
  one user are never cached and served to another (no per-user home cache at
  all in M4).
- **Auth & session code.** Untouched — no new login paths, no new secrets, no
  credential handling. The seed hook in `complete_login` reads only the
  already-stored `seerr_user_id` and spawns a task; it holds no cookie or
  token. The global `SEERR_API_KEY` stays server-side in `clients/`.
- **Outbound HTTP (`clients/`).** The request-history read lives in
  `clients/seerr.py` (still the only Seerr caller): base URL from validated
  settings (SSRF-safe), `requestedBy` an integer from our DB, short timeout, no
  retry, pagination bounded and capped. The global-key-for-reads /
  user-cookie-for-mutations doctrine is stated in the module docstring and
  design decision 9 — the key is never attached to a request mutation. The
  TMDB keywords append rides the existing client: typed parse, unknown fields
  dropped, no browser headers upstream, no upstream bodies downstream.
- **Frontend.** Explain reasons, rail titles ("More like <TMDB title>"), and
  all TMDB/Seerr text render as text — no `dangerouslySetInnerHTML`. No new
  external URLs. Nothing touches `localStorage`; the session stays in the
  HttpOnly cookie.
- **Database & migrations.** Migration 0003 is purely additive; no secret
  material is stored or copied — vectors and signals are public-metadata
  derivatives and behavioral rows, not tokens, so no encryption is warranted
  (host-file access is outside the threat model, and viewing behavior is
  protected at the API surface). All access is SQLAlchemy expressions;
  `user_id` FKs cascade so deleting a user (future admin surface) sweeps their
  behavioral data with them.

## Risks / Trade-offs

- [First personalized home render after a seed may need ~100+ feature vectors
  built, each a TMDB detail fetch] → bounded concurrency over the cached TMDB
  client, the pool capped ~150, every vector persisted in `title_features` so
  the cost is paid once per title per month, and the seed task pre-builds
  vectors for the seeded titles. If the first render still hurts, the fallback
  (noted, not built) is score-with-what-exists + background fill.
- [Engine quality constants (weights, α/β/γ, λ, caps) are guesses until lived
  with] → they encode the browserr-proven shape, live in one constants module,
  and are pinned by ordering-property tests, so retuning is a one-file change
  with a visible diff; explain makes bad tuning visible in-product.
- [Seerr `requestedBy` filter shape could differ across Seerr versions] → the
  live-marked contract test validates filter, pagination, and shape against
  the pinned Seerr 3.3.0 (M3 precedent), and a mismatch degrades to an
  unseeded, non-personalized user — never a login failure.
- [Toggle state (watchlist/hidden) lives only in signals — the SPA must infer
  it] → the detail-open path is fire-and-forget, but the modal needs current
  watchlist/hidden state for its toggles; carried on the title detail response
  (per-user flags resolved from signals at read time) rather than a new
  endpoint. Cheap: one indexed query per detail view.
- [A user who hides aggressively can hollow out their candidate pool] → hard
  exclusion applies to personalized rails only; the non-personalized rails and
  search are never filtered, and reset recovers the profile wholesale.
- [Backdated seed signals mean a long-time Seerr user's profile is mostly
  decayed history] → intended: decay prices old taste honestly, and the PRD
  bar is "noticeably theirs within one session," not "frozen at their 2019
  requests." Fresh browsing signals dominate quickly at these weights.
- [Rollback drops real user behavior] → migration 0003's downgrade drops the
  three tables; acceptable pre-1.0 — the seed rebuilds the request-history
  baseline on next login, and only in-app browsing signals are lost.

## Migration Plan

Single additive Alembic migration (0003) creating `signals`, `title_features`,
and `profiles`; applied idempotently on boot like 0001/0002 — no data
migration, no backfill (profiles materialize lazily, seeds run per-user at
login). Same single container; `api.gen.ts` regenerated once the new endpoints
settle. Rollback: `git revert` + the migration's downgrade (drops the three
tables — see Risks); no other state to unwind.

## Open Questions

None blocking. Engine constants ship as tested defaults and get tuned by
living with them (Risks). The on-selected-services availability boost and rail
toggles land with M5's admin surface; the onboarding picker (v1.x) and Plex
watch signals (v2) are phased by the PRD. Whether `detail_open` should also
fire from long card hovers is deliberately punted — opens are the only
unambiguous browse intent v1 trusts.
