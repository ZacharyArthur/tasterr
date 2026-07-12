# Tasks: m4-taste

## 1. Schema & stores

- [x] 1.1 Migration 0003 + ORM models: `signals` (id PK, user_id FK CASCADE,
      tmdb_id, media_type, kind, weight REAL, created_at; index (user_id, kind)),
      `title_features` ((tmdb_id, media_type) PK, features JSON, fetched_at),
      `profiles` (user_id PK FK CASCADE, vector JSON, computed_at) — SPEC §5
      shapes exactly. Tests: migration up/down round-trip, cascade delete sweeps
      a user's signals and profile
- [x] 1.2 `recommend/store.py`: SQLAlchemy reads/writes for the three tables —
      append signal, idempotent toggle add, retraction delete
      (watchlist/not_interested only), `detail_open` per-UTC-day dedup, load
      signals per user, get/put vectors (with `fetched_at`), get/put profile.
      Tests on the in-memory SQLite fixture: toggle idempotence, retraction
      removes only that kind+title, same-day detail_open dedup, cross-user
      isolation of every read

## 2. Title facts & feature vectors

- [x] 2.1 `clients/tmdb.py`: add `keywords` to `DETAIL_APPEND`, parse the
      movie (`keywords.keywords`) and TV (`keywords.results`) shapes plus TV
      `created_by` into the raw detail model; `httpx.MockTransport` tests:
      keywords parsed for both media types, absent keywords tolerated
- [x] 2.2 `catalog/service.py` + a `TitleFacts` internal model: `title_facts(media, id)`
      derived from the same cached detail payload as `detail()` — genres,
      keywords, top-billed cast, director/creator, original language, year,
      runtime, vote stats; no settings import (boundary-covered under `catalog/`).
      Tests: facts include keywords/creator, warm-cache facts make no TMDB call,
      no API `response_model` carries a facts payload
- [x] 2.3 `recommend/features.py`: pure facts → sparse vector with label-bearing
      keys (`genre:*`, `kw:*`, `cast:*`, `director:*`, `lang:*`, `decade:*`,
      `runtime:*`), per-class weights and caps as named constants, L2
      normalization. Pure unit tests: expected dims and weights, keyword cap,
      normalization, empty facts → empty vector

## 3. Profile & scoring math (pure)

- [x] 3.1 `recommend/profile.py`: profile = normalized decayed sum of
      signal weight × title vector; half-life ≈ 90 days evaluated against a
      passed-in "now"; kind weights (+3.0 request, +2.0 watchlist/seed,
      +0.3 detail_open, −3.0 not_interested) as constants. Pure tests: strong
      signal shifts the profile toward the title, one-half-life-old signal
      contributes ~half, not_interested contributes negatively, recompute from
      the same signals is deterministic (rebuildability)
- [x] 3.2 `recommend/scorer.py`: `1.0·cosine + 0.15·quality_prior +
      0.10·availability_boost` with a vote-shrunk quality prior, boost only for
      known in-library status, then greedy MMR (λ ≈ 0.3); exclusion helpers —
      hidden titles from all personalized output, already-signaled titles from
      recommended-for-you. Pure tests: similar beats popular-dissimilar,
      in-library tiebreak wins, unknown availability scores without boost,
      hidden titles never emitted, near-duplicate demoted by MMR
- [x] 3.3 `recommend/explain.py`: element-wise profile×vector overlap → top
      positive dims rendered as readable reasons from the label-bearing keys;
      no profile or no overlap → not-personalized result. Pure tests: top
      overlap dims become reasons in order, negative dims excluded, empty
      profile → `personalized: false`

## 4. Recommend service — vectors, profile lifecycle, candidates

- [x] 4.1 `recommend/service.py`: ensure-vectors (persistent `title_features`
      first, ~30-day staleness, on-demand builds via `title_facts` under an
      `asyncio.Semaphore`, per-title failure skips the candidate); profile
      materialization policy (recompute after signal writes and when
      `computed_at` > 24 h); candidate pool = recs+similar for top-K strong
      titles ∪ top-genre discover ∪ trending, capped ≈150, exclusions applied;
      availability boost via the existing batch availability service (Unknown →
      no boost). Tests with faked catalog/availability: warm vectors skip
      facts fetches, stale vector rebuilt, one failing title skipped not fatal,
      stale profile recomputed on read, pool respects cap and exclusions

## 5. Signals API & the server-side request signal

- [x] 5.1 `api/signals.py`: session-gated + `require_same_origin`
      `POST /signals` — body `{media_type, tmdb_id, kind, retract=false}` with
      `kind` a `Literal` of the client-recordable kinds only; toggle add /
      retract semantics, detail_open dedup, retract-on-append-only rejected
      (422); explicit secret-free `response_model`; profile marked for
      recompute on write; register the router. Tests: 401 unauthenticated, 403
      cross-origin, 422 for `request`/`seed_request_history`/unknown kinds and
      for retracting `detail_open`, watchlist add→retract round-trip, dedup
      returns success without a second row
- [x] 5.2 `api/request.py`: after a successful Seerr request, record a
      `request` signal for the member server-side (same DB session), wrapped so
      a signal failure logs and never fails the response. Tests: success writes
      the signal, forced signal-write failure still returns the request success

## 6. Cold-start seed & Seerr history client

- [x] 6.1 `clients/seerr.py`: `list_requests(requested_by, take, skip)` —
      `GET /api/v1/request` with the global `X-Api-Key` and explicit
      `requestedBy` filter, short timeout, no retry, bounded pagination capped
      at 200 rows, parsing tmdb id / media type / created-at into a typed
      result; document the global-key-for-reads doctrine in the module
      docstring. `MockTransport` tests: pagination walk, cap enforced,
      malformed rows skipped, user cookie never attached
- [x] 6.2 `recommend/seed.py` + the `complete_login` hook: when the user has
      zero signals, spawn a fire-and-forget asyncio task (in-process
      single-flight per user) importing history as `seed_request_history`
      signals **backdated to each request's creation date**, pre-building their
      vectors and materializing the profile; failures log and leave the user
      unseeded. Tests: first login seeds backdated signals and a profile,
      repeat login is a no-op, concurrent logins seed once, Seerr down → login
      response unaffected and no signals written

## 7. Recommendations API — explain & reset

- [x] 7.1 `api/recommendations.py`: session-gated
      `GET /recommendations/explain?type=&id=` with validated inputs returning
      `{personalized, reasons}` from the caller's own profile; register the
      router. Tests: 401 unauthenticated, 422 bad type/id, reasons for a
      profiled user, `personalized: false` for a signal-less user
- [x] 7.2 `POST /recommendations/reset`: session-gated + `require_same_origin`;
      delete the caller's signals + profile, then run the seed import inline;
      Seerr down → still cleared, response generic. Tests: 403 cross-origin,
      wipe + re-seed round-trip, other users' rows untouched, Seerr down →
      cleared with a successful generic response

## 8. Personalized rails & per-user detail flags

- [x] 8.1 `rails/registry.py` + `composer.py` + `api/home.py`: thread the
      authed user and recommend service through `RailContext` (optional —
      `/rails` pages stay user-free); providers `my-list` (active watchlist →
      summaries), `recommended-for-you` (scored pool), and one
      `because-you-watched` rail labelled "More like <title>" (recs+similar for
      the latest strong-positive title, re-ranked); home order hero → My List →
      Recommended for You → trending → More like X → M2 rails; personalized
      providers run inside `_safe_fetch`/min-items like every other rail.
      Tests: two seeded users get visibly different personalized rails,
      signal-less user gets exactly the M2 feed with no personalized
      placeholders, hidden title absent from personalized rails, engine
      failure degrades to the non-personalized feed
- [x] 8.2 `api/title.py`: detail response carries the caller's per-title taste
      flags (watchlisted, hidden) resolved from signals, so the modal's toggles
      render current state. Tests: flags reflect stored signals per user,
      neutral for a signal-less user

## 9. Frontend — taste affordances

- [x] 9.1 Regenerate `api.gen.ts` (`just types`) once `/signals`,
      `/recommendations/*`, and the detail/home changes settle; commit the
      generated file
- [x] 9.2 Detail modal: `detail_open` posted fire-and-forget on open (errors
      swallowed), watchlist toggle and "Not interested" (+undo) with optimistic
      state posting add/retract through the typed client, initial state from
      the detail's taste flags. Vitest: open fires the signal without blocking
      render, toggles post add/retract and flip optimistically, failed
      detail_open leaves the UI untouched
- [x] 9.3 "Why am I seeing this?" in the detail modal: collapsible, lazily
      queries explain on expand, reasons rendered as text; not-personalized
      response shows the honest empty state. Vitest: no explain call before
      expand, reasons listed as text, not-personalized state rendered
- [x] 9.4 Navbar user menu: "Reset recommendations" behind an explicit
      confirmation, calling the reset endpoint and invalidating the home query
      on success. Vitest: no call without confirmation, confirmed reset calls
      the endpoint and refetches home

## 10. Live Seerr contract coverage (marked, excluded from the gate)

- [x] 10.1 Extend the live-marked Seerr suite: request-history read via the
      global key — `requestedBy` filter honored, pagination shape, the fields
      the seed consumes (tmdb id, media type, created-at) — recording the Seerr
      version; confirm nothing live runs under `just check`

## 11. Gate

- [x] 11.1 Run `just check` inside the devcontainer and fix all failures
