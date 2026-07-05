# Design: m1-auth

## Context

M0 left `auth/` and `clients/` as empty, boundary-tested packages, an empty
baseline migration, and a PublicConfig model with no endpoint. The auth spike
(docs/SEERR-AUTH-SPIKE.md, Seerr 3.3.0) confirmed the Seerr contract: `POST
/api/v1/auth/plex` accepts a Plex token and returns the user object plus a
`connect.sid` cookie (30-day); `/api/v1/auth/me` exposes a `permissions` bitmask
(ADMIN = bit 2); invalid sessions return **403**, not 401; re-posting a stored
Plex token silently re-auths. Local login was deferred to M1 live tests. This
change turns SPEC §4 + §5 (users/sessions) into code, honoring the frozen
blueprint and the M0 decisions (optional secrets, allowlist PublicConfig,
import-linter boundaries).

## Goals / Non-Goals

**Goals:**

- Both login paths working end-to-end from the SPA against a real Seerr.
- Server-side session store with the SPEC §4.2 properties (hashed tokens,
  HttpOnly sliding cookie, trivial revocation).
- `users` + `sessions` schema (migration 0002) shaped exactly per SPEC §5,
  including the at-rest protections M3 will rely on.
- Reusable, default-deny `require_session` / `require_admin` / same-origin
  dependencies that every later milestone consumes.
- First `clients/` code establishing the house style: typed models, timeouts,
  no header leakage, errors mapped before they reach `api/`.

**Non-Goals:**

- Request-as-user, silent re-auth retries, availability reads (M3) — we only
  persist what M3 needs.
- Global mutation rate limiting, forwarded-header trust configuration, and the
  broader hardening pass (M6).
- Settings GUI or any admin-gated feature beyond the dependency itself (M5).
- SPA URL routing — auth state is a render switch until M2 brings real routes.

## Decisions

1. **Module layout.** `auth/sessions.py` (mint/validate/slide/revoke),
   `auth/pins.py` (in-process PIN handle store), `auth/deps.py`
   (`require_session`, `require_admin`, `require_same_origin`),
   `auth/crypto.py` (Fernet helpers), `auth/ratelimit.py` (token bucket);
   `clients/plex.py`, `clients/seerr.py`; `api/auth.py` router; `/config` joins
   `api/meta.py`. Pure session/crypto logic sits between `api/` and `clients/`
   and unit-tests without network fakes, per the boundary philosophy.

2. **Opaque PIN poll handles, held in-process.** plex.tv PIN ids are
   low-entropy integers; if the SPA polled by raw PIN id, anyone enumerating
   ids could poll a victim's approved PIN and steal the minted session. The
   create endpoint therefore returns a random handle (`secrets.token_urlsafe(32)`)
   mapped in-process to the plex.tv PIN id — TTL 10 minutes, single-use,
   deleted on completion, bounded size. A DB table was rejected: the mapping is
   ephemeral, and single-process is a locked constraint (SPEC §2), so process
   memory is the KISS store. Restart mid-login just means clicking the button
   again.

3. **Stable `X-Plex-Client-Identifier` derived, not stored.** UUIDv5 computed
   from a SHA-256 of `TASTERR_SECRET_KEY` — stable across restarts (the spike
   showed a fresh identifier registers a new device in Plex every run), needs
   no table (the SPEC §5 `settings` table stays with M5, which owns it), and
   the one-way derivation leaks no key material. Trade-off: rotating the secret
   key re-registers the device and orphans encrypted Plex tokens — both merely
   force a re-login, which key rotation should do anyway.

4. **Session mechanics.** Token: `secrets.token_urlsafe(32)` (256 bits); the
   row stores its SHA-256 hex. Validation looks the hash up via the unique
   index — the "comparison" is an exact match on a one-way hash, satisfying
   the constant-time requirement (no secret-dependent branching in our code;
   index timing cannot recover a SHA-256 preimage). Sliding expiry: rows carry
   `expires_at = last activity + 30 days`; to avoid a write per request, the
   slide is persisted only when `last_seen_at` is older than one hour. Expired
   rows are deleted on touch, plus a single sweep at boot (indexed
   `expires_at`). Fresh token on every login; logout deletes the row.

5. **Cookie flags.** `tasterr_session`; HttpOnly, `SameSite=Lax`, `Path=/`,
   `Max-Age` 30 days, `Secure` iff the request scheme is `https`. Uvicorn runs
   with proxy headers enabled so the scheme is correct behind the Cloudflare
   tunnel; deciding which proxy IPs to trust (`forwarded_allow_ips`) is part of
   M6 deployment hardening. A hard-coded `Secure` was rejected: LAN deployments
   are plain HTTP today and would lose login entirely.

6. **Client style (first `clients/` code — sets precedent).** One shared
   `httpx.AsyncClient` created in lifespan (`app.state.http`); `clients/`
   exposes plain async functions taking the client + settings. Explicit ~10s
   timeout on every call, no retries in M1 (the SPA's poll loop is the retry).
   Responses parse into Pydantic models with `extra="ignore"` (`SeerrUser`
   with `id`, `displayName`, `avatar`, `permissions`; PIN models). Failures
   raise a small typed hierarchy (`UpstreamUnavailable`, `UpstreamRejected`)
   that `api/auth.py` maps to generic 502 / 401 — upstream bodies and URLs
   never reach the browser. Seerr auth calls send only what the endpoint
   needs; the global `SEERR_API_KEY` is *not* attached to login calls (they
   authenticate by credential/token, and mixing the admin key into user flows
   risks privilege confusion).

7. **Login pipeline (both paths converge).** Exchange at Seerr → parse
   `SeerrUser` → derive `is_admin = permissions & 2` (constant named `ADMIN`,
   value confirmed by the spike) → upsert `users` by `seerr_user_id` → insert
   `sessions` row (token hash, raw `connect.sid=…` cookie string for M3,
   Fernet-encrypted Plex token or NULL) → set cookie. The login response body
   is the same shape as `/auth/me`. Multiple concurrent sessions per user are
   allowed (household devices); no per-user cap in M1.

8. **`/auth/me` reads local state only.** Identity and admin are evaluated at
   login and stored (SPEC §4.4); per-request Seerr calls would couple every
   page load to Seerr availability, violating the degradation invariant.
   Response model is minimal: `id`, `display_name`, `avatar_url`, `is_admin` —
   no email (the UI doesn't need it; least data to the client).

9. **CSRF via fetch-metadata with Origin fallback.** `require_same_origin` on
   auth mutations: if `Sec-Fetch-Site` is present it must be `same-origin` (or
   `none`, i.e., user-initiated); otherwise, if `Origin` is present it must
   match the request host; requests with neither header (non-browser clients)
   pass — CSRF is a browser attack, and modern browsers always send fetch
   metadata. `SameSite=Lax` is the second, independent layer. A token dance
   was rejected per SPEC §9 (same-origin SPA needs none).

10. **Rate limiting: tiny in-process token bucket, login endpoints only.**
    Per-client-IP bucket (e.g., 10 attempts/min) on PIN creation and local
    login; polling is excluded (requires an unguessable handle; fires every
    2s by design). A dependency like `slowapi` was rejected — ~30 lines of
    stdlib beats a new dependency (AGENTS.md slate). Behind the tunnel all
    traffic may share one peer IP, degrading to a global bucket — acceptable
    at household scale; forwarded-for trust is an M6 concern.

11. **Schema (migration 0002)** — SQLAlchemy 2.0 typed ORM models in
    `db/models.py`, exactly the SPEC §5 columns: `users` (unique
    `seerr_user_id`) and `sessions` (unique `token_hash`, FK `user_id` with
    cascade delete, indexed `expires_at`). Alembic autogenerate output reviewed
    by hand; downgrade drops the tables.

12. **Unconfigured auth fails loudly at its boundary** (M0 decision 2 carried
    through): a dependency yields 503 "authentication unavailable" when
    `SEERR_INTERNAL_URL` or `TASTERR_SECRET_KEY` is unset. No new settings are
    introduced; TTLs and limits are code constants until someone actually
    needs to tune them (KISS).

13. **Frontend auth state via TanStack Query.** `['auth','me']` query drives a
    render switch in the root: 401 → `<Login/>`, ok → shell. The fetch wrapper
    gains typed error handling (401 → auth-state signal, not an exception
    cascade). Plex flow: create PIN → `window.open(auth_url)` → poll query
    with `refetchInterval` while pending → on `ok`, invalidate `['auth','me']`.
    Local form posts and invalidates the same query; logout likewise. No
    router, no context provider beyond what Query already gives us.

14. **Testing strategy.** API tests override the client-provider dependencies
    with fakes (no network, no monkeypatching); `clients/` contract tests run
    against `httpx.MockTransport` with fixtures shaped from the (redacted)
    spike evidence; session/crypto/ratelimit/pin-store logic unit-tests pure.
    Live suite: `@pytest.mark.live`, excluded by default via pytest config so
    `just check` stays hermetic; runs read coordinates and a local-account
    credential from env (never committed), and assert the contract items the
    spike recorded — including the deferred local-login question — printing
    the Seerr version tested.

**New dependency vs. the AGENTS.md slate:**

| Dependency | Kind | Justification |
|---|---|---|
| cryptography | backend runtime | Fernet is named in SPEC §5 for Plex-token encryption at rest; `cryptography` is the PyCA-maintained canonical implementation (already a transitive ecosystem staple, multi-arch wheels). Alternatives: hand-rolled AES (never), `itsdangerous` (signing, not encryption). The Fernet key is derived from `TASTERR_SECRET_KEY` via SHA-256 → urlsafe base64. |

## Security considerations

Walked per docs/SECURITY.md for every area this change touches:

- **New/changed endpoints.** Default-deny: `/auth/me` (session), `/auth/logout`
  (session + same-origin), `/config` (session). Explicitly unauthenticated by
  nature, each justified: `/auth/plex/pin` create+poll and `/auth/local` are
  pre-login (create + local are same-origin-checked and rate-limited; poll
  requires an unguessable 256-bit handle). All inputs are Pydantic models; all
  responses have explicit `response_model`s; error bodies are generic (no
  stack traces, upstream bodies, or internal URLs); logs record login attempts
  by outcome only — never credentials, tokens, or cookies.
- **Auth & session checklist.** Credentials forwarded verbatim, never stored or
  logged; token comparison is exact-match lookup of a SHA-256 hash (decision 4);
  fresh token every login (no fixation); logout deletes the row; cookie is
  HttpOnly/`SameSite=Lax`/`Secure`-on-HTTPS; login endpoints tightly
  rate-limited; failures are generic (no user enumeration — Seerr 401/403/404
  all surface as the same 401).
- **Outbound HTTP.** Base URLs from validated settings only — user input never
  forms a URL (SSRF); the poll path sends the server-held PIN id, not client
  input. Every call times out; no retries. Browser headers are not forwarded
  upstream; upstream headers/bodies are parsed into typed models and dropped,
  never relayed.
- **Frontend.** Login errors render as static text; the Plex approval URL
  comes only from the backend response (which built it from validated
  settings), never assembled client-side. No tokens in
  localStorage/sessionStorage — the session lives in the HttpOnly cookie.
- **Database & migrations.** SQLAlchemy expressions only. New secret-bearing
  columns: `sessions.plex_token_enc` (Fernet, justified above);
  `sessions.seerr_cookie` stored plaintext by explicit SPEC §5 decision — it
  is a short-lived upstream session identifier needed verbatim on every M3
  call, and the threat model excludes host-file access; revisit at M6 if the
  calculus changes. Migration 0002 creates empty tables — no secret material
  is copied or logged.
- **Dependencies & build.** `cryptography` justified above; `uv.lock` updated
  and committed with the change. No Docker/image changes.
- **Invariants.** Secrets stay server-side (login responses carry only the
  public user shape; the PublicConfig regression test already guards
  `/config`'s payload shape); all outbound HTTP lands in `clients/` under the
  existing import-linter contract; Seerr being down blocks only login itself —
  health, SPA serving, and existing sessions keep working.

## Risks / Trade-offs

- [Seerr auth endpoints are not a stable public contract] → all calls isolated
  in `clients/seerr.py`; contract fixtures mirror the spike evidence; live
  suite pins the tested version (3.3.0 known-good) before release.
- [In-process PIN handles vanish on restart mid-login] → user clicks "Sign in
  with Plex" again; no state worth persisting.
- [Per-IP rate bucket collapses to global behind the tunnel] → household
  scale makes this acceptable; M6 owns forwarded-header trust.
- [Sliding-expiry write throttle] → `last_seen_at` may lag up to an hour;
  expiry precision of ±1h on a 30-day window is immaterial.
- [Our 30-day sliding session outlives the Seerr `connect.sid`] → harmless in
  M1 (nothing calls Seerr per-user after login); M3's re-auth ladder is the
  designed answer and the encrypted Plex token is already in place for it.
- [`TASTERR_SECRET_KEY` rotation invalidates encrypted Plex tokens and the
  Plex device identity] → users re-login once; documented behavior, and
  exactly what rotation should mean.

## Migration Plan

Additive migration 0002 (`users`, `sessions`) applies on boot per the existing
migrate-on-boot machinery; downgrade drops both tables. No data backfill, no
deploy sequencing — single container, `git revert` + downgrade is the rollback.

## Open Questions

None — SPEC §4/§5 fix the shape, and the spike answered the behavioral
unknowns (local login's remaining question is explicitly covered by the live
suite this change adds).
