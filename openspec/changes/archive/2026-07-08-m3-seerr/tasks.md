# Tasks: m3-seerr

## 1. Seerr client — availability reads & request-as-user

- [x] 1.1 `clients/seerr.py`: add `availability(media_type, tmdb_id)` —
      `GET /api/v1/{type}/{tmdbId}` with the global `X-Api-Key`, a short timeout,
      **no retry**, parsing `mediaInfo` (overall + per-season status) into a typed
      result; `404` → a typed not-in-library result, any other error/timeout →
      typed upstream error. `httpx.MockTransport` tests: 200 parse (movie + TV
      per-season), `404` → not-in-library, `5xx`/timeout → typed error with no
      upstream body leaked, global key attached / no user cookie attached
- [x] 1.2 `clients/seerr.py`: add `create_request(cookie, media_type, tmdb_id)` —
      `POST /api/v1/request` with only the per-user cookie (TV → whole series,
      `seasons: "all"`), `201` → the resulting media status, `403` → a typed
      `SeerrForbidden`; tests: `201` parse, `403` → `SeerrForbidden`, the global
      API key is never attached to a request

## 2. Availability engine — model, mapping, cache

- [x] 2.1 `catalog/availability.py`: a typed, secret-free `Availability` model and a
      **pure** Seerr-status → enum mapping (available / partial / processing /
      pending / not_requested / unknown, plus a `known` flag); unit tests per
      status including absent `mediaInfo` → not_requested and unreachable →
      unknown(`known=false`). No settings import — the model lives under `catalog/`,
      already covered by the secret-free `tests/test_boundaries.py`
- [x] 2.2 Availability service: a short-TTL, single-flight read over `cache.py`
      keyed `seerr:avail:{type}:{id}`, catching Seerr errors → `unknown` so failures
      are **never cached and never served stale**, and returning `unknown` without a
      call when Seerr is unconfigured; tests: fresh hit skips the loader, concurrent
      misses collapse to one fetch, upstream error → unknown (not stale), unconfigured
      → unknown with no Seerr call

## 3. Availability API — batch hydration & detail embedding

- [x] 3.1 `api/availability.py`: session-gated `POST /availability` taking a
      length-bounded, validated list of `{type, id}` and returning a per-title
      status map behind an explicit secret-free `response_model`, each title
      degrading independently to unknown; register the router. Tests: `401`
      unauthenticated, per-title status shape, one unresolved title → unknown while
      the rest resolve, Seerr unconfigured → all unknown with no call, oversize list
      rejected by validation
- [x] 3.2 `api/title.py`: embed availability in `GET /title/{type}/{id}`, resolved
      **in parallel** with the TMDB detail under the short timeout and degrading to
      unknown; tests: detail includes availability for a known title, Seerr down →
      availability unknown while detail still returns `200`

## 4. Request-as-user API — proxy, re-auth ladder, fallback

- [x] 4.1 `api/request.py`: session-gated **and** `require_same_origin` (CSRF)
      `POST /request` with a validated body (`media_type` literal, positive
      `tmdb_id`), proxying via the session's stored `seerr_cookie`; success returns
      the new `Availability`; the response carries a `seerr_url` built server-side
      from `SEERR_EXTERNAL_URL` + the integer id (absent when unset); explicit
      secret-free `response_model`; register the router. Tests: `401`
      unauthenticated, `403` cross-origin before any Seerr call, success path
      (faked client) attributes + returns status, `seerr_url` present when
      configured and absent with no internal-URL leak when unset
- [x] 4.2 The `403` re-auth ladder: **Plex** member → decrypt `plex_token_enc` →
      `login_plex` → persist the fresh `seerr_cookie` → retry **once**; a second
      `403` → generic failure. **Local** member → `re_auth_required`, no retry.
      Never more than one re-auth. Tests: Plex `403` → silent re-auth → retry
      succeeds and the cookie is persisted, second `403` → generic failure, local
      `403` → `re_auth_required`
- [x] 4.3 Request degradation: Seerr **unconfigured** → requests-unavailable with no
      call; Seerr **down** → generic failure plus the redirect fallback, browsing
      unaffected; tests: unconfigured → unavailable with no Seerr call, Seerr down →
      generic failure + `seerr_url`, `/api/v1/health` and `/home` still respond
      while Seerr is down

## 5. Frontend — availability badges & request UI

- [x] 5.1 Regenerate `api.gen.ts` (`just types`) once the `/availability`,
      `/request`, and detail changes settle; commit the generated file
- [x] 5.2 `AvailabilityBadge` + a batch-hydration hook (TanStack Query over
      `POST /availability`, keyed by title id) wired into `MediaCard`, `Hero`,
      search results, and the detail modal, hydrating **after** render; Vitest:
      badge renders the right label per status, hydration issues the batch call
      after the view paints, unknown/not-requested render muted/hidden
- [x] 5.3 Rework the detail modal's where-to-watch into "where & how to watch" with
      a request button — disabled when `!seerr_configured` (from `PublicConfig`) or
      already available/requested, optimistic pending on submit, re-login prompt on
      `re_auth_required`, and the server-provided "Request in Seerr" link on failure;
      Seerr/library text rendered as text; Vitest: button submits through the typed
      client, disabled states, re-auth prompt, fallback link sourced from the backend

## 6. Live Seerr contract coverage (marked, excluded from the gate)

- [x] 6.1 Extend the live-marked Seerr suite (excluded from `just check`/CI):
      availability read shape (operator-supplied available title + `404`
      not-in-library), request-as-user (create + attribution, cleanup that does
      **not** treat the delete `204` as authoritative mid-dispatch), and the `403`
      re-auth **primitives** — an invalid session returning `403`, plus (given an
      operator-supplied `TASTERR_LIVE_PLEX_TOKEN`) the stored token minting a fresh
      cookie; the ladder's orchestration stays in the mocked unit tests. Record the
      Seerr version and confirm nothing runs under the default gate

## 7. Gate

- [x] 7.1 Run `just check` inside the devcontainer and fix all failures
