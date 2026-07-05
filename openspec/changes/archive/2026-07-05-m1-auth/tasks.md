# Tasks: m1-auth

## 1. Foundations — schema & crypto

- [x] 1.1 Add `cryptography` to backend deps (`uv add`), lockfile committed
- [x] 1.2 `db/models.py`: `users` + `sessions` ORM models per SPEC §5; Alembic
      migration 0002 (unique `seerr_user_id`, unique `token_hash`, FK cascade,
      indexed `expires_at`); tests: migration applies on fresh DB, second boot
      no-op still passes, downgrade drops tables
- [x] 1.3 `auth/crypto.py`: Fernet key derivation from `TASTERR_SECRET_KEY`
      (SHA-256 → urlsafe b64), encrypt/decrypt helpers, UUIDv5 Plex client
      identifier; tests: round-trip, stable identifier, identifier ≠ key material

## 2. Session core & shared dependencies

- [x] 2.1 `auth/sessions.py`: mint (256-bit token, SHA-256 hash stored),
      validate, throttled sliding expiry, revoke; tests: hash-only storage,
      expired → rejected + row deleted, slide persists only past 1h threshold,
      fresh token per login
- [x] 2.2 Boot-time sweep of expired session rows in lifespan; test with
      pre-seeded expired rows
- [x] 2.3 `auth/deps.py`: `require_session` (cookie → session row → user) and
      `require_admin`; tests on a probe route: no/invalid/expired cookie → 401,
      non-admin → 403, admin passes
- [x] 2.4 `require_same_origin` dependency (Sec-Fetch-Site, Origin fallback,
      headerless non-browser pass); unit tests covering all header combinations
- [x] 2.5 `auth/ratelimit.py`: per-IP in-process token bucket; unit tests for
      allow/deny/refill
- [x] 2.6 Session cookie helper (`HttpOnly`, `SameSite=Lax`, `Secure` iff HTTPS)
      and uvicorn proxy-headers enabled in `__main__`; test asserting the
      Secure flag follows request scheme

## 3. Outbound clients (first real `clients/` code)

- [x] 3.1 Shared `httpx.AsyncClient` in lifespan (`app.state.http`) + typed
      upstream error hierarchy (`UpstreamUnavailable`, `UpstreamRejected`);
      test client lifecycle open/close
- [x] 3.2 `clients/plex.py`: create PIN + poll PIN (timeouts, typed models,
      auth URL built server-side); contract tests on `httpx.MockTransport`
      fixtures shaped from the spike evidence
- [x] 3.3 `clients/seerr.py`: `login_plex`, `login_local`, typed `SeerrUser`
      (`extra="ignore"`), `connect.sid` cookie extraction; contract tests incl.
      rejection (401/403) and unavailable (timeout/5xx) mapping — upstream
      bodies never surface

## 4. Auth API

- [x] 4.1 `auth/pins.py`: opaque handle store (random ≥256-bit handles, 10-min
      TTL, single-use, bounded size); unit tests: unknown/expired/reused
      handle misses, capacity bound
- [x] 4.2 `api/auth.py`: `POST /auth/plex/pin` + `GET /auth/plex/pin/{handle}`
      full pipeline with faked clients — tests: pending poll (no cookie),
      claimed poll mints session + sets cookie, generic 404 on bad handle,
      Plex token absent from every response body
- [x] 4.3 `POST /auth/local`: verbatim forward, same session pipeline; tests:
      success mints session, Seerr rejection → generic 401 (same body for
      unknown account vs wrong password), credentials never persisted or logged
      (log-capture assertion)
- [x] 4.4 User upsert + admin derivation (`permissions & 2`) shared by both
      flows; tests: first login creates, re-login updates display name/admin
      in place, `last_login_at` refreshes
- [x] 4.5 `GET /auth/me` (local state only, minimal response model) +
      `POST /auth/logout` (delete row, clear cookie); tests: me without
      session → 401, me makes no outbound call, replayed cookie after
      logout → 401
- [x] 4.6 Unconfigured/degraded handling: 503 "authentication unavailable"
      when Seerr or `TASTERR_SECRET_KEY` unset; upstream failure → generic
      502; tests: both cases, `/api/v1/health` still 200 while Seerr is down
- [x] 4.7 Session-gated `GET /api/v1/config` returning `PublicConfig`; tests:
      401 unauthenticated, 200 authenticated with no secret material
- [x] 4.8 Wire `require_same_origin` + rate limiter onto login mutations;
      endpoint tests: cross-origin POST → 403 before any (fake) Seerr call,
      burst → 429, poll endpoint exempt from the tight bucket

## 5. Frontend — login experience & typed client

- [x] 5.1 Regenerate `api.gen.ts` (`just types`) after backend routes settle;
      commit the generated file
- [x] 5.2 Fetch wrapper: typed error with status, `['auth','me']` query hook
      treating 401 as unauthenticated (not an error cascade); Vitest coverage
- [x] 5.3 `Login` component: "Sign in with Plex" (create PIN → open approval
      URL → poll with `refetchInterval` → invalidate me on ok, expired-handle
      message) + local email/password form with generic error display; Vitest
      tests for both paths with mocked fetch
- [x] 5.4 Auth-gated shell: root render switch (401 → Login, ok → shell showing
      display name + health via typed client) and logout control invalidating
      auth state; Vitest tests for both states and logout

## 6. Live Seerr contract suite

- [x] 6.1 `live` pytest marker excluded by default (pytest config; `just check`
      stays hermetic + offline); live tests reading coordinates/credentials
      from env: local login (closes the spike's deferred question), user +
      permissions shape, invalid-session 403, Seerr version recorded in output
- [x] 6.2 `just test-live` recipe + short how-to docstring (env vars needed,
      never committed); run it against the home Seerr and record the tested
      version in the change notes
      — live run 2026-07-04 against Seerr **3.3.0**: all 3 tests passed
      (local login works, closing the spike's deferred question; invalid
      session → 403 confirmed; wrong credentials rejected)

## 7. Gate

- [x] 7.1 Run `just check` inside the devcontainer and fix all failures
