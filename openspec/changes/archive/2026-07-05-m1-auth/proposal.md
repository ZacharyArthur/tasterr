# Proposal: m1-auth

## Why

M0 delivered a running shell with no notion of identity — nothing personal can be
built until users exist. This change implements **PRD/SPEC milestone M1 (Auth)**:
Seerr-delegated login (Plex PIN primary, local credentials secondary), server-side
Tasterr sessions, and the admin gate. The 2026-07-02 auth spike
(docs/SEERR-AUTH-SPIKE.md) validated the Seerr contract against 3.3.0, so the
design risk is retired; every later milestone (browse personalization M2/M4,
request-as-user M3, admin settings M5) depends on this identity layer.

## What Changes

- **Plex PIN login flow**: backend creates a PIN at plex.tv, SPA opens the
  approval URL and polls; on claim the backend exchanges the Plex token at Seerr
  `/api/v1/auth/plex`, upserts the user, and mints a Tasterr session.
- **Local Seerr login**: email+password forwarded verbatim to Seerr
  `/api/v1/auth/local` — never stored, never logged. Validates the spike's one
  deferred question via live contract tests.
- **Tasterr sessions**: 256-bit random token, only its SHA-256 hash stored;
  HttpOnly `SameSite=Lax` cookie, `Secure` behind HTTPS (proxy-header aware);
  30-day sliding expiry; logout deletes the row.
- **First real schema**: `users` and `sessions` tables (Alembic migration 0002),
  per SPEC §5. Seerr session cookie stored on the session row; Plex token
  encrypted at rest (Fernet) for M3's silent re-auth.
- **`/api/v1/auth/*` router**: `POST /auth/plex/pin`, `GET /auth/plex/pin/{id}`,
  `POST /auth/local`, `POST /auth/logout`, `GET /auth/me`.
- **Session + admin dependencies**: default-deny auth dependency for all future
  session-gated routes; `is_admin` evaluated at login from Seerr permissions
  (bit 2) and stored on the user row.
- **Session-gated `GET /api/v1/config`** serving `PublicConfig` — completes the
  endpoint deferred from M0 (design decision 3).
- **CSRF origin check** dependency on auth mutations, and a tight in-process
  rate limit on the login endpoints (auth-only; the broader rate-limit pass
  stays in M6).
- **First outbound HTTP**: `clients/plex.py` (PIN create/poll) and
  `clients/seerr.py` (auth endpoints), typed models, timeouts, bounded behavior —
  inside the import-linter boundary.
- **SPA login experience**: login screen with both paths, auth state via
  `/auth/me`, logout, auth-gated shell; typed client regenerated (`just types`).
- **Live contract tests** (pytest marker, excluded from `just check`) against the
  home Seerr instance, recording the tested Seerr version.

## Capabilities

### New Capabilities

- `user-auth`: end-to-end authentication — Plex PIN and local login flows,
  Tasterr session lifecycle (mint, validate, slide, revoke), current-user and
  logout endpoints, admin determination and gating, login-endpoint hardening
  (CSRF origin check, rate limit, generic failures), degradation when Seerr is
  down or auth is unconfigured, and the SPA login/logged-in experience.

### Modified Capabilities

- `app-settings`: adds the requirement that `PublicConfig` is served to
  authenticated clients via session-gated `GET /api/v1/config` (M0 defined the
  model + regression test only; delivery was explicitly deferred to M1).
- `app-shell`: the hello-world SPA requirement evolves — the SPA becomes
  auth-gated: unauthenticated visitors see the login screen; the
  health-through-typed-client display now applies to the authenticated shell.

## Impact

- **Backend**: `auth/` gains its first real code (session store, PIN handle
  store, dependencies, crypto helpers); `clients/` gains `plex.py` + `seerr.py`;
  `api/` gains the auth router and `/config`; `db/` gains models + migration
  0002. `settings.py` unchanged (auth uses existing `TASTERR_SECRET_KEY`,
  `SEERR_INTERNAL_URL`, `SEERR_API_KEY`).
- **Frontend**: login route/components, auth query + fetch-wrapper 401 handling,
  `api.gen.ts` regenerated.
- **New dependency**: `cryptography` (Fernet — named in SPEC §5 for Plex token
  encryption at rest). No new frontend dependencies.
- **Tests**: session lifecycle, CSRF dependency, rate limiter, admin gate,
  auth endpoints against a faked Seerr client, client contract tests on recorded
  fixtures, live-marked Seerr suite, frontend login/auth-state tests.

## Non-goals

- **Request-as-user and silent re-auth retry** (M3) — this change only *stores*
  what M3 needs (encrypted Plex token, Seerr cookie).
- **Browsing/catalog** (M2), **settings GUI** (M5) — the admin dependency lands
  now, but nothing admin-gated ships yet beyond being available for M5.
- **General mutation rate limiting and security hardening pass** (M6) — only the
  login endpoints get a tight limiter now.
- **Playwright E2E** (M6 per SPEC §11).
- **User management** — Seerr owns accounts; Tasterr never creates or edits users.
- **Router library in the SPA** — login vs. shell is an auth-state switch;
  URL routing arrives with M2's real navigation needs.
